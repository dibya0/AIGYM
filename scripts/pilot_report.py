"""RL difficulty pilot (plan §1b): sample base Qwen-0.5B G=8 times per training task and check that GRPO
will get a gradient. A group whose 8 rollouts all score the same contributes nothing (brief p.12).

    uv run python scripts/pilot_report.py results/local__qwen2.5-0.5b/pilot-<preset>

Reads an eval run made with `--split train --rollouts 8` and recommends a train-split knob preset.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean


def main(run_dir: Path) -> None:
    rows = [json.loads(line) for line in (run_dir / "transcript.jsonl").read_text().splitlines() if line.strip()]
    groups = defaultdict(list)
    tiers = {}
    for r in rows:
        if r.get("status") == "ok":
            groups[r["task_id"]].append(r["reward"])
            tiers[r["task_id"]] = r["difficulty"]
    zero_std = sum(1 for v in groups.values() if len(set(round(x, 6) for x in v)) == 1) / len(groups)
    pass2 = [x >= 0.95 for t, v in groups.items() if tiers[t] == 2 for x in v]
    pass3 = [x >= 0.8 for t, v in groups.items() if tiers[t] == 3 for x in v]
    report = {
        "run": str(run_dir), "tasks": len(groups), "rollouts_per_task": round(mean(len(v) for v in groups.values()), 1),
        "mean_reward": round(mean(x for v in groups.values() for x in v), 4),
        "frac_groups_all_identical": round(zero_std, 4),
        "tier2_pass_rate": round(mean(pass2), 4) if pass2 else None,
        "tier3_pass_rate": round(mean(pass3), 4) if pass3 else None,
    }
    if zero_std > 0.7 or (report["tier2_pass_rate"] or 0) < 0.05:
        report["recommendation"] = "too hard for a gradient: regenerate train with an easier preset (--knobs easy, then easier)"
    elif (report["tier2_pass_rate"] or 0) > 0.8:
        report["recommendation"] = "too easy: little to learn; use the default preset"
    else:
        report["recommendation"] = "in range (target: Tier-2 pass rate ~0.2-0.6, low identical-group fraction): train on this preset"
    out = run_dir / "pilot_report.json"
    out.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
