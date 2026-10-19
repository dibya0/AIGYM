"""Statistics for honest reporting (brief P05: mean ± SD over >=3 rollouts; non-determinism reported,
not hidden in a mean; brief §10: "Honesty about noise, including where your gym cannot distinguish
two models").
"""

from __future__ import annotations

import math
import random
from statistics import mean, pstdev


def mean_sd(values: list[float]) -> tuple[float, float]:
    if not values:
        return float("nan"), float("nan")
    return mean(values), (pstdev(values) if len(values) > 1 else 0.0)


def task_means(rows: list[dict]) -> dict[str, float]:
    """Mean reward per task over its rollouts (rows: transcript lines with task_id, reward, status)."""
    by_task: dict[str, list[float]] = {}
    for row in rows:
        if row.get("status") == "ok":
            by_task.setdefault(row["task_id"], []).append(row["reward"])
    return {task: mean(rs) for task, rs in by_task.items()}


def run_summary(rows: list[dict]) -> dict:
    """Leaderboard numbers for one run.

    * mean_reward: mean over tasks of the per-task mean (each task weighs the same).
    * rollout_sd: mean over tasks of the SD across that task's rollouts (run-to-run noise).
    * run_sd: SD of the per-rollout-index means (each rollout index treated as one full pass).
    * disagreement_rate: share of tasks whose rollouts did not all get the same reward.
    """
    ok = [r for r in rows if r.get("status") == "ok"]
    by_task: dict[str, list[float]] = {}
    by_index: dict[int, list[float]] = {}
    for r in ok:
        by_task.setdefault(r["task_id"], []).append(r["reward"])
        by_index.setdefault(r["rollout"], []).append(r["reward"])
    per_task = {t: mean(v) for t, v in by_task.items()}
    task_sds = [pstdev(v) for v in by_task.values() if len(v) > 1]
    pass_means = [mean(v) for v in by_index.values()]
    disagree = [len(set(round(x, 6) for x in v)) > 1 for v in by_task.values() if len(v) > 1]
    return {
        "tasks": len(per_task),
        "rollouts_ok": len(ok),
        "rollouts_failed": sum(1 for r in rows if r.get("status") != "ok"),
        "mean_reward": round(mean(per_task.values()), 4) if per_task else None,
        "run_sd": round(pstdev(pass_means), 4) if len(pass_means) > 1 else None,
        "rollout_sd": round(mean(task_sds), 4) if task_sds else None,
        "disagreement_rate": round(sum(disagree) / len(disagree), 4) if disagree else None,
    }


def bootstrap_mean_ci(values: list[float], iters: int = 2000, alpha: float = 0.05, seed: int = 0) -> tuple[float, float]:
    if not values:
        return float("nan"), float("nan")
    rng = random.Random(seed)
    n = len(values)
    means = sorted(sum(rng.choice(values) for _ in range(n)) / n for _ in range(iters))
    return means[int(alpha / 2 * iters)], means[int((1 - alpha / 2) * iters) - 1]


def paired_bootstrap(a: dict[str, float], b: dict[str, float], iters: int = 2000, seed: int = 0) -> dict:
    """Difference in mean reward (a - b) over the tasks both runs scored, resampling tasks with replacement."""
    shared = sorted(set(a) & set(b))
    diffs = [a[t] - b[t] for t in shared]
    if not diffs:
        return {"tasks": 0}
    low, high = bootstrap_mean_ci(diffs, iters=iters, seed=seed)
    return {"tasks": len(shared), "mean_diff": round(mean(diffs), 4), "ci95": [round(low, 4), round(high, 4)],
            "distinguishable": not (low <= 0.0 <= high)}


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    k = (len(ordered) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return ordered[lo] if lo == hi else ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)
