"""Judge reliability (brief p.10): we do both measures the brief offers.

1. Repeat disagreement: judge the same outputs 3 times with the cache bypassed and report the share
   of (output, criterion) pairs whose verdicts are not unanimous.
2. Judge vs human: a labelling sheet of 15 outputs x 3 criteria; the user fills ``human_pass``; we
   report raw agreement and Cohen's kappa.

Items are real refusals from eval transcripts: traps refused with the correct reason code (the only
case the judge scores). Input: JSONL rows {"task_id": ..., "explanation": ...}.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from paygym.judge import CRITERIA, GeminiJudge, prompt_hash
from paygym.schema import Task


def load_items(items_path: Path, tasks: dict[str, Task]) -> list[tuple[Task, str]]:
    items = []
    for line in items_path.read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            items.append((tasks[row["task_id"]], row["explanation"]))
    return items


def _progress_key(task: Task, criterion: str, explanation: str, i: int) -> str:
    import hashlib

    return hashlib.sha256(json.dumps([prompt_hash(), task.id, criterion, explanation.strip(), i]).encode()).hexdigest()


def repeat_disagreement(items: list[tuple[Task, str]], repeats: int = 3, judge: GeminiJudge | None = None,
                        progress_path: Path | None = None) -> dict:
    """Each verdict is appended to ``progress_path`` as soon as it arrives, and a re-run skips verdicts already
    there. (2026-10-20: the first run held everything in memory, and a burst of 503s from the provider after ~244
    requests lost all of it.)"""
    done: dict[str, bool] = {}
    if progress_path and progress_path.exists():
        for line in progress_path.read_text().splitlines():
            if line.strip():
                row = json.loads(line)
                done[row["key"]] = row["pass"]
    judge = judge or GeminiJudge(use_cache=False)

    def verdict(task: Task, criterion: str, explanation: str, i: int) -> bool:
        key = _progress_key(task, criterion, explanation, i)
        if key not in done:
            done[key] = judge.judge_criterion(task, criterion, explanation)["pass"]
            if progress_path:
                progress_path.parent.mkdir(parents=True, exist_ok=True)
                with progress_path.open("a") as fh:
                    fh.write(json.dumps({"key": key, "task": task.id, "criterion": criterion, "repeat": i,
                                         "pass": done[key]}) + "\n")
        return done[key]

    pairs, split = [], 0
    for task, explanation in items:
        for criterion in CRITERIA:
            verdicts = [verdict(task, criterion, explanation, i) for i in range(repeats)]
            unanimous = len(set(verdicts)) == 1
            split += not unanimous
            pairs.append({"task": task.id, "criterion": criterion, "verdicts": verdicts})
    return {
        "judge_model": judge.model, "judge_prompt_hash": prompt_hash(), "repeats": repeats,
        "items": len(items), "pairs": len(pairs), "non_unanimous_pairs": split,
        "disagreement_rate": round(split / len(pairs), 4) if pairs else None, "detail": pairs,
    }


def write_label_sheet(items: list[tuple[Task, str]], path: Path, judge: GeminiJudge | None = None, n: int = 15) -> int:
    """CSV for hand labelling: fill human_pass with 1 or 0 for every row (do it before looking at judge_pass)."""
    judge = judge or GeminiJudge()
    rows = []
    for task, explanation in items[:n]:
        for criterion in CRITERIA:
            verdict = judge.judge_criterion(task, criterion, explanation)
            rows.append({"task_id": task.id, "reason_code": task.ground_truth.reason_code, "criterion": criterion,
                         "explanation": explanation, "human_pass": "", "judge_pass": int(verdict["pass"])})
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def cohens_kappa(a: list[int], b: list[int]) -> float | None:
    n = len(a)
    if n == 0:
        return None
    observed = sum(x == y for x, y in zip(a, b)) / n
    pa, pb = sum(a) / n, sum(b) / n
    expected = pa * pb + (1 - pa) * (1 - pb)
    return None if expected == 1 else (observed - expected) / (1 - expected)


def agreement(path: Path) -> dict:
    with path.open() as fh:
        rows = [r for r in csv.DictReader(fh) if r["human_pass"].strip() in ("0", "1")]
    human = [int(r["human_pass"]) for r in rows]
    judge = [int(r["judge_pass"]) for r in rows]
    per = {}
    for criterion in CRITERIA:
        sel = [(h, j) for r, h, j in zip(rows, human, judge) if r["criterion"] == criterion]
        if sel:
            per[criterion] = round(sum(h == j for h, j in sel) / len(sel), 4)
    kappa = cohens_kappa(human, judge)
    return {
        "labelled_rows": len(rows),
        "outputs": len({r["task_id"] + r["explanation"] for r in rows}),
        "agreement": round(sum(h == j for h, j in zip(human, judge)) / len(rows), 4) if rows else None,
        "cohens_kappa": None if kappa is None else round(kappa, 4),
        "agreement_by_criterion": per,
    }


def extract_items(run_dirs: list[Path]) -> list[dict]:
    """Real judge inputs from eval transcripts: traps refused with the *correct* reason code.

    Returns rows {"task_id", "task_json", "explanation", "source_run"} (task_json is embedded so the
    items file is self-contained)."""
    from paygym.environment import completion_text, load_tasks
    from paygym.parser import parse_answer

    items, seen = [], set()
    for run_dir in run_dirs:
        cfg = json.loads((run_dir / "config.json").read_text())
        tasks = {t.id: t for t in load_tasks(cfg["split"], cfg["n_seeds"], cfg.get("tasks_path"), cfg["tier"])}
        for line in (run_dir / "transcript.jsonl").read_text().splitlines():
            row = json.loads(line)
            task = tasks.get(row["task_id"])
            if row.get("status") != "ok" or task is None or task.ground_truth.kind != "refusal":
                continue
            parsed = parse_answer(completion_text(row.get("completion")), "refusal")
            if parsed.decision != "refuse" or parsed.reason_code != task.ground_truth.reason_code:
                continue
            key = (task.id, parsed.explanation.strip())
            if key in seen or not parsed.explanation.strip():
                continue
            seen.add(key)
            items.append({"task_id": task.id, "task_json": task.model_dump_json(exclude_none=True),
                          "explanation": parsed.explanation, "source_run": str(run_dir)})
    return items


def items_from_file(path: Path, max_items: int | None = None) -> list[tuple[Task, str]]:
    out = []
    for line in path.read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            out.append((Task.model_validate_json(row["task_json"]), row["explanation"]))
    return stratified(out, max_items) if max_items else out


def stratified(items: list[tuple[Task, str]], n: int) -> list[tuple[Task, str]]:
    """At most ``n`` items, taken round-robin over reason codes (file order within each), so a cap made to fit
    a daily free-tier quota still covers every trap type instead of only the first run's items."""
    groups: dict[str, list[tuple[Task, str]]] = {}
    for item in items:
        groups.setdefault(item[0].ground_truth.reason_code, []).append(item)
    out: list[tuple[Task, str]] = []
    while len(out) < n and any(groups.values()):
        for code in sorted(groups):
            if groups[code] and len(out) < n:
                out.append(groups[code].pop(0))
    return out
