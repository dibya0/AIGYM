"""Aggregates run directories into results/leaderboard.json (input to the dashboard).

Runs are only compared within a *comparison group*: same taskset hash, same mode, same rule-set
fingerprint and rubric version. A run scored under a different rule-set version is never silently
compared with one scored under another (brief P08 edge case: version skew). Within a group, every pair
of runs gets a paired bootstrap CI over shared tasks, and pairs whose CI contains 0 are listed as
indistinguishable (brief §10: "honesty about noise").
"""

from __future__ import annotations

import json
from itertools import combinations
from pathlib import Path

from paygym.eval.stats import paired_bootstrap, task_means


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
            "group": f"{cfg['taskset_hash']}|{cfg['mode']}|{cfg.get('scaffold')}|{cfg['ruleset_fingerprint']}|{cfg['rubric_version']}",
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
        })
    return runs


def build(root: Path = Path("results")) -> dict:
    runs = load_runs(root)
    groups: dict[str, list[dict]] = {}
    for run in runs:
        groups.setdefault(run["group"], []).append(run)
    comparisons = []
    for group, members in groups.items():
        for a, b in combinations(members, 2):
            result = paired_bootstrap(a["task_means"], b["task_means"])
            comparisons.append({"group": group, "a": a["run"], "b": b["run"], **result})
    for run in runs:
        run.pop("task_means")
    return {
        "runs": sorted(runs, key=lambda r: (r["group"], -(r["mean_reward"] or -9))),
        "comparisons": comparisons,
        "indistinguishable": [c for c in comparisons if c.get("tasks") and not c["distinguishable"]],
    }


def write(root: Path = Path("results"), out: Path | None = None) -> Path:
    out = out or root / "leaderboard.json"
    out.write_text(json.dumps(build(root), indent=2, default=str))
    return out
