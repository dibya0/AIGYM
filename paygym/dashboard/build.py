"""Builds the static dashboard (brief Phase 06) from committed result files into ``public/``.

    uv run python -m paygym.dashboard.build [--results results] [--out public] [--sandbox-url https://…]

Nothing re-runs on deploy: Vercel serves ``public/`` as committed (brief p.6), next to the sandbox API.
The page answers "which model should we use, for which tasks, and where will it hurt us?" (brief p.11):
a verdict panel, the leaderboard with baselines and error bars, tier and reward-function breakdowns,
a task x model failure heatmap, cost/latency, a transcript viewer, and (when present) RL curves and
the Track C scaffold comparison.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

from jinja2 import Environment, FileSystemLoader, select_autoescape

from paygym.eval.leaderboard import build as build_leaderboard
from paygym.ruleset import load_ruleset

TEMPLATES = Path(__file__).parent / "templates"
COMPONENTS = ("net_pay_exact", "line_accuracy", "trap_decision", "value_exact", "format_valid", "judge_flag_quality")


def _rows(run_dir: Path) -> list[dict]:
    path = run_dir / "transcript.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


def _last_assistant(completion) -> dict:
    """Compact view of a rollout for the transcript viewer: tool calls and the final answer."""
    steps = []
    if isinstance(completion, str):
        completion = [{"role": "assistant", "content": completion}]
    for msg in completion or []:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        if role == "assistant":
            calls = msg.get("tool_calls") or []
            for c in calls:
                if isinstance(c, str):  # verifiers serialises each ToolCall as a JSON string in real transcripts
                    try:
                        c = json.loads(c)
                    except ValueError:
                        c = {"name": "?", "arguments": c}
                fn = c.get("function", c) if isinstance(c, dict) else {}
                steps.append({"type": "tool_call", "name": fn.get("name") or c.get("name"), "arguments": fn.get("arguments") or c.get("arguments")})
            if msg.get("content"):
                steps.append({"type": "assistant", "text": msg["content"] if isinstance(msg["content"], str) else json.dumps(msg["content"])})
        elif role == "tool":
            content = msg.get("content")
            steps.append({"type": "tool_result", "text": (content if isinstance(content, str) else json.dumps(content))[:1500]})
    return {"steps": steps}


def _main_group(board: dict) -> str | None:
    """The comparison group shown on the leaderboard: the single-turn eval group with the most runs."""
    counts = Counter(r["group"] for r in board["runs"] if r["mode"] == "single")
    return counts.most_common(1)[0][0] if counts else None


def _verdict(runs: list[dict], rows_by_run: dict[str, list[dict]]) -> dict:
    models = [r for r in runs if not r["is_baseline"] and r["mean_reward"] is not None]
    if not models:
        return {}
    best = max(models, key=lambda r: r["mean_reward"])
    by_tier = {}
    for tier in ("1", "2", "3"):
        scored = [r for r in models if r["by_tier"].get(tier) is not None]
        if scored:
            top = max(scored, key=lambda r: r["by_tier"][tier])
            by_tier[tier] = {"model": top["model"], "score": top["by_tier"][tier]}
    per_model = []
    for r in models:
        rows = [x for x in rows_by_run[r["run"]] if x.get("status") == "ok"]
        payslips = [x for x in rows if x["kind"] == "payslip"]
        correct = sum(1 for x in payslips if (x.get("metrics") or {}).get("net_pay_exact") == 1.0)
        traps = [x for x in rows if x["kind"] == "refusal"]
        failures = [x for x in payslips if (x.get("reward") or 0) < 0.95]
        clauses = Counter(c for x in failures for c in (x.get("driving_clauses") or [])[:2])
        per_model.append({
            "model": r["model"],
            "mean_reward": r["mean_reward"],
            "payslip_pass_rate": round(correct / len(payslips), 4) if payslips else None,
            "trap_answered_rate": round(sum(1 for x in traps if x.get("gate") == "answered_trap") / len(traps), 4) if traps else None,
            "twin_score": r.get("twins"),
            "cost_per_correct_payslip_list_usd": round(r["cost_list_usd"] / correct, 5) if correct else None,
            "cost_actual_usd": r["cost_actual_usd"],
            "top_failure_clauses": clauses.most_common(4),
        })
    return {"best_overall": {"model": best["model"], "score": best["mean_reward"]}, "best_by_tier": by_tier, "models": per_model}


def _heatmap(runs: list[dict], rows_by_run: dict[str, list[dict]]) -> dict:
    per = {}
    tiers = {}
    for r in runs:
        by_task = defaultdict(list)
        for x in rows_by_run[r["run"]]:
            if x.get("status") == "ok":
                by_task[x["task_id"]].append(x["reward"])
                tiers[x["task_id"]] = x["difficulty"]
        per[r["model"]] = {t: mean(v) for t, v in by_task.items()}
    tasks = sorted(tiers, key=lambda t: (tiers[t], t))
    models = [r["model"] for r in runs]
    return {"models": models, "tasks": tasks, "tiers": [tiers[t] for t in tasks],
            "z": [[round(per[m].get(t), 3) if t in per[m] else None for t in tasks] for m in models]}


def _distribution(runs: list[dict], rows_by_run: dict[str, list[dict]]) -> dict:
    """Per-task mean rewards per model (brief P02: show the score distribution is non-degenerate:
    not everything at 0, not everything at 1)."""
    out = {}
    for r in runs:
        by_task = defaultdict(list)
        for x in rows_by_run[r["run"]]:
            if x.get("status") == "ok":
                by_task[x["task_id"]].append(x["reward"])
        means = [mean(v) for v in by_task.values()]
        if means:
            out[r["model"]] = {"task_means": [round(m, 4) for m in means],
                               "share_full": round(sum(m >= 0.999 for m in means) / len(means), 4),
                               "share_zero_or_below": round(sum(m <= 0.0 for m in means) / len(means), 4)}
    return out


def _transcripts(run: dict, rows: list[dict], tasks_expected: dict) -> dict:
    out = defaultdict(list)
    for x in rows:
        out[x["task_id"]].append({
            "rollout": x["rollout"], "status": x.get("status"), "reward": x.get("reward"), "gate": x.get("gate"),
            "driving_clauses": x.get("driving_clauses"), "stop_condition": x.get("stop_condition"),
            "error": x.get("error"), **_last_assistant(x.get("completion")),
        })
    return {"run": run["run"], "model": run["model"], "rollouts": out, "expected": tasks_expected}


def _expected(run_dir: Path) -> dict:
    """Ground truth per task, for explaining failures on the dashboard (eval tasks are public)."""
    from paygym.environment import load_tasks

    cfg = json.loads((run_dir / "config.json").read_text())
    expected = {}
    for t in load_tasks(cfg["split"], cfg["n_seeds"], cfg.get("tasks_path"), cfg["tier"]):
        gt = t.ground_truth
        if gt.kind == "payslip":
            expected[t.id] = {"kind": "payslip", "lines": {k: str(v) for k, v in gt.lines.items()}, "prompt": t.prompt}
        elif gt.kind == "refusal":
            expected[t.id] = {"kind": "refusal", "reason_code": gt.reason_code, "clause": gt.clause, "prompt": t.prompt,
                              "why": t.trap_reason.explanation if t.trap_reason else ""}
        else:
            expected[t.id] = {"kind": "value", "value": str(gt.value), "prompt": t.prompt}
    return expected


# The runs the RL report discusses (docs/RL_REPORT.md B3-B6), with what each shows. Other folders under
# results/train (smoke test, crashed or mis-configured runs) are listed as excluded, not plotted.
REPORTED_RL_RUNS = {
    "grpo-b0.04": "rubric 1.3, beta 0.04: selected policy (no exploit; format learned)",
    "grpo-b0.001": "rubric 1.3, beta 0.001: too low, learned the invalid-decision exploit",
    "v1.2-grpo-b0.04": "rubric 1.2, beta 0.04: learned broken JSON (exploit 2)",
    "v1.1-grpo-b0.001": "rubric 1.1, beta 0.001: learned refuse-everything (exploit 1)",
}


def _rl(results: Path) -> dict:
    """RL curves from results/train/<run>/metrics.csv and validation.csv (Phase 07), for the reported runs."""
    runs, excluded = [], []
    for path in sorted(results.glob("train/*/metrics.csv")):
        if path.parent.name not in REPORTED_RL_RUNS:
            excluded.append(path.parent.name)
            continue
        with path.open() as fh:
            rows = [r for r in csv.DictReader(fh) if r.get("reward") not in (None, "")]
        cfg_path = path.parent / "config.json"
        cfg = json.loads(cfg_path.read_text()) if cfg_path.exists() else {}
        keys = ["step", "reward", "kl", "entropy", "completions/mean_length", "frac_reward_zero_std",
                "monitor/pass_rate_tier2", "monitor/pass_rate_tier3", "monitor/twin_refusal_rate",
                "monitor/trap_answer_rate", "monitor/modal_net_share", "monitor/len_reward_corr"]
        series = {k: [float(r[k]) if r.get(k) not in (None, "") else None for r in rows] for k in keys}
        val = {}
        vpath = path.parent / "validation.csv"
        if vpath.exists():
            with vpath.open() as fh:
                vrows = list(csv.DictReader(fh))
            val = {k: [float(r[k]) if r.get(k) not in (None, "") else None for r in vrows]
                   for k in ("step", "val_reward", "val_tier2", "val_tier3")}
        runs.append({"run": path.parent.name, "label": REPORTED_RL_RUNS[path.parent.name], "beta": cfg.get("beta"),
                     "rubric_version": cfg.get("rubric_version"), "reward": cfg.get("reward"), "series": series, "validation": val})
    order = list(REPORTED_RL_RUNS)
    runs.sort(key=lambda r: order.index(r["run"]))
    summaries = {name: json.loads(p.read_text()) for name, p in
                 (("held-out (training preset)", results / "train" / "rl_summary_heldout_easy.json"),
                  ("held-out (full difficulty)", results / "train" / "rl_summary_heldout.json")) if p.exists()}
    return {"runs": runs, "excluded": excluded, "summary": summaries or None}


def _optional_json(path: Path):
    return json.loads(path.read_text()) if path.exists() else None


def build(results: Path = Path("results"), out: Path = Path("public"), sandbox_url: str | None = None) -> Path:
    board = build_leaderboard(results)
    group = _main_group(board)
    main_runs = [r for r in board["runs"] if r["group"] == group]
    other_runs = [r for r in board["runs"] if r["group"] != group]
    rows_by_run = {r["run"]: _rows(results / r["run"]) for r in board["runs"]}

    out.mkdir(parents=True, exist_ok=True)
    import shutil

    shutil.rmtree(out / "data", ignore_errors=True)  # no stale files from earlier builds
    (out / "data").mkdir()
    expected_cache: dict[str, dict] = {}
    for r in board["runs"]:
        if r.get("subset_view_of"):  # a view of a full run on a subset: reuse that run's transcript file
            r["transcript_file"] = f"data/{r['subset_view_of'].replace('/', '__')}.json"
            continue
        key = r["taskset_hash"]
        if key not in expected_cache:
            expected_cache[key] = _expected(results / r["run"])
        slug = r["run"].replace("/", "__")
        (out / "data" / f"{slug}.json").write_text(json.dumps(_transcripts(r, rows_by_run[r["run"]], expected_cache[key]), default=str))
        r["transcript_file"] = f"data/{slug}.json"

    ruleset = load_ruleset()
    data = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "ruleset": {"version": ruleset.version, "fingerprint": ruleset.fingerprint},
        "main_runs": main_runs,
        "other_runs": other_runs,
        "indistinguishable": [c for c in board["indistinguishable"] if c["group"] == group],
        "comparisons": [c for c in board["comparisons"] if c["group"] == group],
        "verdict": _verdict(main_runs, rows_by_run),
        "heatmap": _heatmap(main_runs, rows_by_run),
        "distribution": _distribution(main_runs, rows_by_run),
        "components": list(COMPONENTS),
        "rl": _rl(results),
        "track_c": _optional_json(results / "track_c" / "summary.json"),
        "sensitivity": _optional_json(results / "weight_sensitivity.json"),
        "sandbox_url": sandbox_url,
    }
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"]))
    # Escaped so no string in the data can close the <script> element it is embedded in.
    data_json = json.dumps(data, default=str).replace("<", "\\u003c")
    html = env.get_template("index.html.j2").render(data_json=data_json)
    (out / "index.html").write_text(html)
    # Served next to the dashboard so the sandbox quickstart needs no clone (brief P08):
    #   curl -s https://<host>/quickstart.py | python3 - https://<host>
    quickstart = Path(__file__).resolve().parents[2] / "scripts" / "quickstart.py"
    if quickstart.exists():
        (out / "quickstart.py").write_text(quickstart.read_text())
    return out / "index.html"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="results")
    ap.add_argument("--out", default="public")
    ap.add_argument("--sandbox-url", default=None, help="sandbox base URL, to show external runs live")
    args = ap.parse_args()
    print(f"wrote {build(Path(args.results), Path(args.out), args.sandbox_url)}")


if __name__ == "__main__":
    main()
