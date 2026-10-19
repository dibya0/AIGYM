"""Held-out before/after for the RL report and dashboard (brief p.12: "report before-and-after scores on
tasks the policy never trained on").

    uv run python scripts/rl_summary.py --before results/local__qwen2.5-0.5b/heldout-base \\
        --after beta0.04=results/local__qwen2.5-0.5b-grpo-b0.04/heldout --after beta0.001=results/...

Both sides must have scored the identical held-out taskset (checked via taskset_hash). Reports the mean,
per-tier means, twin score, trap-answered rate and a paired bootstrap CI of the difference.
Writes results/train/rl_summary.json.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from paygym.eval.stats import paired_bootstrap, task_means


def load(run_dir: Path) -> tuple[dict, dict, list[dict]]:
    cfg = json.loads((run_dir / "config.json").read_text())
    scores = json.loads((run_dir / "scores.json").read_text())
    rows = [json.loads(line) for line in (run_dir / "transcript.jsonl").read_text().splitlines() if line.strip()]
    return cfg, scores, rows


def describe(scores: dict, rows: list[dict]) -> dict:
    traps = [r for r in rows if r.get("status") == "ok" and r["kind"] == "refusal"]
    return {"mean_reward": scores["summary"]["mean_reward"], "run_sd": scores["summary"]["run_sd"],
            "by_tier": scores["by_tier"], "twins": scores.get("twins"),
            "trap_answered_rate": round(sum(r.get("gate") == "answered_trap" for r in traps) / len(traps), 4) if traps else None}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--before", required=True)
    ap.add_argument("--after", action="append", required=True, help="label=run_dir")
    ap.add_argument("--out", default="results/train/rl_summary.json")
    args = ap.parse_args()
    b_cfg, b_scores, b_rows = load(Path(args.before))
    summary = {"heldout_taskset_hash": b_cfg["taskset_hash"], "before": {"run": args.before, **describe(b_scores, b_rows)}, "after": {}}
    for item in args.after:
        label, path = item.split("=", 1)
        a_cfg, a_scores, a_rows = load(Path(path))
        if a_cfg["taskset_hash"] != b_cfg["taskset_hash"]:
            raise SystemExit(f"{label}: different held-out taskset; refusing to compare")
        summary["after"][label] = {"run": path, **describe(a_scores, a_rows),
                                   "diff_vs_before": paired_bootstrap(task_means(a_rows), task_means(b_rows))}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
