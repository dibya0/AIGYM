"""Weight-sensitivity analysis (brief p.10: "Document your weights and defend them. Weighted-sum reward
design is a real decision with real consequences for model ranking").

Re-scores every recorded payslip rollout under alternative weightings of (net, lines, format), keeping
the same gates, and reports whether the model ranking changes (Kendall's tau vs the shipped weights).
Trap and retrieval scores do not depend on these weights and are kept as recorded.

    uv run python -m paygym.eval.sensitivity [--results results]
"""

from __future__ import annotations

import argparse
import json
from itertools import combinations
from pathlib import Path
from statistics import mean

WEIGHTINGS = {
    "shipped (0.70/0.25/0.05)": (0.70, 0.25, 0.05),
    "net-heavy (0.85/0.10/0.05)": (0.85, 0.10, 0.05),
    "lines-heavy (0.50/0.45/0.05)": (0.50, 0.45, 0.05),
    "no format (0.72/0.28/0.00)": (0.72, 0.28, 0.00),
}
CAP = 0.25


def rescore(row: dict, w: tuple[float, float, float]) -> float | None:
    if row.get("status") != "ok":
        return None
    if row.get("kind") != "payslip":
        return row["reward"]
    m = row.get("metrics") or {}
    if row.get("gate") in ("unparseable",):
        return 0.0
    net, lines, fmt = m.get("net_pay_exact", 0.0), m.get("line_accuracy", 0.0), m.get("format_valid", 0.0)
    total = w[0] * net + w[1] * lines + w[2] * fmt
    return total if net >= 1.0 else min(total, CAP)


def kendall_tau(a: list[str], b: list[str]) -> float:
    pos_b = {x: i for i, x in enumerate(b)}
    pairs = list(combinations(a, 2))
    if not pairs:
        return 1.0
    concordant = sum(1 if pos_b[x] < pos_b[y] else -1 for x, y in pairs)
    return concordant / len(pairs)


def analyse(results: Path) -> dict:
    runs = {}
    for t in sorted(results.glob("*/*/transcript.jsonl")):
        cfg = json.loads((t.parent / "config.json").read_text())
        if cfg["mode"] != "single":
            continue
        rows = [json.loads(line) for line in t.read_text().splitlines() if line.strip()]
        runs[cfg["model"]] = rows
    table = {}
    for label, w in WEIGHTINGS.items():
        table[label] = {}
        for model, rows in runs.items():
            by_task: dict[str, list[float]] = {}
            for r in rows:
                s = rescore(r, w)
                if s is not None:
                    by_task.setdefault(r["task_id"], []).append(s)
            table[label][model] = round(mean(mean(v) for v in by_task.values()), 4) if by_task else None
    rankings = {label: sorted(scores, key=lambda m: -(scores[m] or -9)) for label, scores in table.items()}
    shipped = rankings[next(iter(WEIGHTINGS))]
    return {
        "mean_reward_by_weighting": table,
        "ranking_by_weighting": rankings,
        "kendall_tau_vs_shipped": {label: round(kendall_tau(shipped, r), 4) for label, r in rankings.items()},
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="results")
    ap.add_argument("--out", default="results/weight_sensitivity.json")
    args = ap.parse_args()
    report = analyse(Path(args.results))
    Path(args.out).write_text(json.dumps(report, indent=2))
    for label, tau in report["kendall_tau_vs_shipped"].items():
        print(f"{label:<32} tau={tau}  ranking={report['ranking_by_weighting'][label]}")


if __name__ == "__main__":
    main()
