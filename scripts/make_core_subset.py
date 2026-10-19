"""Stratified "core" subset of the eval split for the models whose free tier cannot afford the full set
(Gemini 3.8 Flash: 20 requests/day; Groq gpt-oss-120b: 200K tokens/day ≈ 40 single-turn rollouts).

    uv run python scripts/make_core_subset.py            # -> tasks/subsets/eval_core20.txt (task ids)
    uv run python -m paygym.eval --model gemini/gemini-3.8-flash --split eval --ids tasks/subsets/eval_core20.txt ...

Composition mirrors the full eval split (≈ 18% T1, 65% T2, 17% T3), and every trap comes **with its
determinable twin**, so over-refusal is still measurable: 4 retrieval, 6 plain payslips, 5 traps + their
5 twins = 20 tasks. Selection is deterministic: a fixed-seed shuffle within each stratum, so the subset is
reproducible and was not chosen by looking at any model's scores. Every other model is also scored on
exactly these tasks (from its full run), so comparisons on the subset are paired. Stored as ids, not a
copy: a copied task file would double-count tasks (``paygym validate`` rejects duplicate ids).
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default="tasks/generated/eval.jsonl")
    ap.add_argument("--out", default="tasks/subsets/eval_core20.txt")
    ap.add_argument("--seed", type=int, default=20261019)
    ap.add_argument("--retrieval", type=int, default=4)
    ap.add_argument("--payslips", type=int, default=6)
    ap.add_argument("--traps", type=int, default=5)
    args = ap.parse_args()

    rows = [json.loads(line) for line in Path(args.tasks).read_text().splitlines() if line.strip()]
    by_id = {r["id"]: r for r in rows}
    rng = random.Random(args.seed)

    def pick(pool, n):
        pool = sorted(pool, key=lambda r: r["id"])
        rng.shuffle(pool)
        return pool[:n]

    retrieval = pick([r for r in rows if r["difficulty"] == 1], args.retrieval)
    payslips = pick([r for r in rows if r["difficulty"] == 2 and not r.get("twin_of")], args.payslips)
    traps = pick([r for r in rows if r["difficulty"] == 3], args.traps)
    twins = [r for r in rows if r.get("twin_of") in {t["id"] for t in traps}]
    assert len(twins) == len(traps), "every trap must have its twin"
    chosen = sorted(retrieval + payslips + traps + twins, key=lambda r: r["id"])
    assert len({r["id"] for r in chosen}) == len(chosen) and all(r["id"] in by_id for r in chosen)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(r["id"] + "\n" for r in chosen))
    print(f"{len(chosen)} tasks -> {args.out}: {len(retrieval)} retrieval, {len(payslips)} payslips, "
          f"{len(traps)} traps + {len(twins)} twins")


if __name__ == "__main__":
    main()
