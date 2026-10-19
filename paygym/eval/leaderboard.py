"""Aggregates run directories into results/leaderboard.json (input to the dashboard).

Runs are only compared within a *comparison group*: same taskset hash, same mode, same rule-set
fingerprint and rubric version. A run scored under a different rule-set version is never silently
compared with one scored under another (brief P08 edge case: version skew). Within a group, every pair
of runs gets a paired bootstrap CI over shared tasks, and pairs whose CI contains 0 are listed as
indistinguishable (brief §10: "honesty about noise").

Subsets: models whose free tier cannot afford the full eval run on a fixed subset (``--ids
tasks/subsets/<name>.txt``). Such runs are grouped as ``subset:<name>``, and every full-set run that
covers those tasks also gets a *subset view* (its own rollouts on exactly those tasks, re-summarised) in
the same group, so the scarce models are compared paired, on identical tasks, never against a mean
over a different task mix.
"""

from __future__ import annotations

import json
from itertools import combinations
from pathlib import Path
from statistics import mean

from paygym.eval.stats import paired_bootstrap, run_summary, task_means


def is_leaderboard_run(cfg: dict, metrics: dict) -> bool:
    """Eval-split runs only (the full split or a fixed --ids subset of it), with at least one scored rollout.
    Excluded: pilots and training-set runs (--tasks train*.jsonl), held-out RL runs (reported by
    scripts/rl_summary.py), and runs in which nothing succeeded (e.g. a local server that was down)."""
    return cfg.get("split") == "eval" and not cfg.get("tasks_path") and (metrics.get("rollouts_ok") or 0) > 0


def load_runs(root: Path) -> list[dict]:
    runs = []
    for cfg_path in sorted(root.glob("*/*/config.json")):
        run_dir = cfg_path.parent
        scores_path, metrics_path = run_dir / "scores.json", run_dir / "metrics.json"
        if not (scores_path.exists() and metrics_path.exists()):
            continue
        cfg = json.loads(cfg_path.read_text())
        scores = json.loads(scores_path.read_text())
        metrics = json.loads(metrics_path.read_text())
        if not is_leaderboard_run(cfg, metrics):
            continue
        rows = [json.loads(line) for line in (run_dir / "transcript.jsonl").read_text().splitlines() if line.strip()]
        runs.append({
            "run": str(run_dir.relative_to(root)),
            "model": cfg["model"],
            "is_baseline": cfg["model"].startswith("baseline/"),
            "external": False,
            "mode": cfg["mode"],
            "split": cfg.get("split"),
            "taskset_hash": cfg["taskset_hash"],
            "scaffold": cfg.get("scaffold"),
            "group": (f"subset:{Path(cfg['ids']).stem}" if cfg.get("ids") else cfg["taskset_hash"])
                     + f"|{cfg['mode']}|{cfg.get('scaffold')}|{cfg['ruleset_fingerprint']}|{cfg['rubric_version']}",
            "subset": Path(cfg["ids"]).stem if cfg.get("ids") else None,
            "_key": f"|{cfg['mode']}|{cfg.get('scaffold')}|{cfg['ruleset_fingerprint']}|{cfg['rubric_version']}",
            "ruleset_version": cfg["ruleset_version"],
            "status": metrics["status"],
            "rollouts": cfg["rollouts"],
            **scores["summary"],
            "by_tier": scores["by_tier"],
            "twins": scores.get("twins"),
            "by_component": scores["by_component"],
            "gates": scores["gates"],
            "cost_list_usd": metrics["cost_list_usd"],
            "cost_actual_usd": metrics["cost_actual_usd"],
            "latency_s": metrics["latency_s"],
            "tool_calls_mean": metrics["tool_calls_mean"],
            "parse_fail_rate": metrics["parse_fail_rate"],
            "task_means": task_means(rows),
            "_rows": rows,
        })
    return runs


def subset_views(runs: list[dict], subsets: dict[str, set[str]]) -> list[dict]:
    """Runs re-summarised on each (smaller) subset they fully cover, e.g. a full run on core10, a core10 run on core6."""
    views = []
    for name, ids in subsets.items():
        for run in runs:
            if run["subset"] == name or not ids <= set(run["task_means"]):  # a subset run also covers smaller subsets
                continue
            rows = [r for r in run["_rows"] if r["task_id"] in ids]
            by_tier = {}
            for d in (1, 2, 3):
                tm = task_means([r for r in rows if r.get("difficulty") == d])
                by_tier[str(d)] = round(mean(tm.values()), 4) if tm else None
            views.append({**run, **run_summary(rows), "run": f"{run['run']}@{name}", "subset": name, "subset_view_of": run["run"],
                          "group": f"subset:{name}" + run["_key"], "by_tier": by_tier, "task_means": task_means(rows),
                          "by_component": None, "gates": None, "twins": None})
    return views


def load_subsets(root: Path = Path("tasks/subsets")) -> dict[str, set[str]]:
    return {p.stem: {line.strip() for line in p.read_text().splitlines() if line.strip()} for p in sorted(root.glob("*.txt"))}


def build(root: Path = Path("results"), subsets_dir: Path = Path("tasks/subsets")) -> dict:
    runs = load_runs(root)
    runs += subset_views(runs, load_subsets(subsets_dir))
    groups: dict[str, list[dict]] = {}
    for run in runs:
        groups.setdefault(run["group"], []).append(run)
    comparisons = []
    for group, members in groups.items():
        for a, b in combinations(members, 2):
            result = paired_bootstrap(a["task_means"], b["task_means"])
            comparisons.append({"group": group, "a": a["run"], "b": b["run"], **result})
    for run in runs:
        for key in ("task_means", "_rows", "_key"):
            run.pop(key, None)
    return {
        "runs": sorted(runs, key=lambda r: (r["group"], -(r["mean_reward"] or -9))),
        "comparisons": comparisons,
        "indistinguishable": [c for c in comparisons if c.get("tasks") and not c["distinguishable"]],
    }


def write(root: Path = Path("results"), out: Path | None = None) -> Path:
    out = out or root / "leaderboard.json"
    out.write_text(json.dumps(build(root), indent=2, default=str))
    return out
