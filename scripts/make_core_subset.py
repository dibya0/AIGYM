"""Stratified, nested "core" subsets of the eval split for models whose free tier cannot afford the full
set in one day, sized so each finishes in a day:
  * eval_core6  (1 retrieval, 3 payslips, 1 trap + twin) x 3 rollouts = 18 requests: Gemini 3.8 Flash (20/day);
  * eval_core10 (2, 4, 2 + 2 twins) x 3 = 30 rollouts ≈ 170K tokens: Groq gpt-oss-120b (200K tokens/day);
    also tool mode and the Track C comparator on Gemini Flash-Lite;
  * eval_core20 (4, 6, 5 + 5 twins): kept for runs that can afford it.

    uv run python scripts/make_core_subset.py            # -> tasks/subsets/eval_core{6,10,20}.txt (task ids)

Every trap comes **with its determinable twin**, so over-refusal stays measurable. Selection is deterministic: a fixed-seed shuffle within each stratum, so the subset is
reproducible and was not chosen by looking at any model's scores. Every other model is also scored on
exactly these tasks (from its full run), so comparisons on the subset are paired. Stored as ids, not a
copy: a copied task file would double-count tasks (``paygym validate`` rejects duplicate ids).
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path


SIZES = {  # name: (retrieval, payslips, traps); each trap brings its twin. Nested: core6 ⊂ core10 ⊂ core20.
    "eval_core20": (4, 6, 5),
    "eval_core10": (2, 4, 2),
    "eval_core6": (1, 3, 1),
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default="tasks/generated/eval.jsonl")
    ap.add_argument("--out-dir", default="tasks/subsets")
    ap.add_argument("--seed", type=int, default=20261019)
    args = ap.parse_args()

    rows = [json.loads(line) for line in Path(args.tasks).read_text().splitlines() if line.strip()]
    rng = random.Random(args.seed)

    def order(pool):
        pool = sorted(pool, key=lambda r: r["id"])
        rng.shuffle(pool)
        return pool

    # One fixed order per stratum; every subset takes a prefix of it, so smaller subsets nest in larger ones.
    retrieval = order([r for r in rows if r["difficulty"] == 1])
    payslips = order([r for r in rows if r["difficulty"] == 2 and not r.get("twin_of")])
    traps = order([r for r in rows if r["difficulty"] == 3])
    twin_of = {r["twin_of"]: r for r in rows if r.get("twin_of")}

    for name, (n_ret, n_pay, n_trap) in SIZES.items():
        chosen_traps = traps[:n_trap]
        twins = [twin_of[t["id"]] for t in chosen_traps]  # KeyError if a trap had no twin
        chosen = sorted(retrieval[:n_ret] + payslips[:n_pay] + chosen_traps + twins, key=lambda r: r["id"])
        assert len({r["id"] for r in chosen}) == len(chosen)
        out = Path(args.out_dir) / f"{name}.txt"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("".join(r["id"] + "\n" for r in chosen))
        print(f"{len(chosen):2d} tasks -> {out}: {n_ret} retrieval, {n_pay} payslips, {n_trap} traps + {len(twins)} twins")


if __name__ == "__main__":
    main()
