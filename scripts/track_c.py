"""Track C summary (brief §7: "Hold the model constant and vary the scaffold… Show whether scaffold matters
more than model choice"). Reads results/*/trackc-S*/ runs and writes results/track_c/summary.json for the
dashboard and docs/TRACK_C.md.

    uv run python scripts/track_c.py --small local/qwen2.5-3b --compare local/qwen2.5-0.5b

The fixed model runs S0–S4; the comparison model runs at least S0 and S4 (matched scaffolds), so the
scaffold effect (fixed model, best vs worst scaffold) can be set against the model effect (the two models at
the same scaffold). Both local: no hosted quota.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean

from paygym.prompting import SCAFFOLDS


def load(results: Path) -> list[dict]:
    rows = []
    for cfg_path in sorted(results.glob("*/trackc-*/config.json")):
        run = cfg_path.parent
        cfg = json.loads(cfg_path.read_text())
        scores = json.loads((run / "scores.json").read_text())
        metrics = json.loads((run / "metrics.json").read_text())
        trans = [json.loads(l) for l in (run / "transcript.jsonl").read_text().splitlines() if l.strip()]
        ok = [r for r in trans if r.get("status") == "ok"]
        payslips = [r for r in ok if r["kind"] == "payslip"]
        correct = sum(1 for r in payslips if (r.get("metrics") or {}).get("net_pay_exact") == 1.0)
        traps = [r for r in ok if r["kind"] == "refusal"]
        rows.append({
            "model": cfg["model"], "scaffold": cfg["scaffold"], "scaffold_label": SCAFFOLDS[cfg["scaffold"]]["label"],
            "mean_reward": scores["summary"]["mean_reward"], "run_sd": scores["summary"]["run_sd"],
            "payslip_exact_rate": round(correct / len(payslips), 4) if payslips else None,
            "trap_correct_rate": round(sum(r["reward"] >= 0.8 for r in traps) / len(traps), 4) if traps else None,
            "twin_score": scores.get("twins"),
            "tokens_per_rollout": round(mean((r.get("input_tokens") or 0) + (r.get("output_tokens") or 0) for r in ok), 1) if ok else None,
            "tool_calls_per_rollout": metrics.get("tool_calls_mean"),
            "list_cost_per_correct_payslip": round(metrics["cost_list_usd"] / correct, 5) if correct else None,
        })
    return rows


def finding(rows: list[dict], small: str, frontier: str) -> str:
    """`frontier` is the comparison model (any model run at matched scaffolds; here local Qwen-0.5B)."""
    by = {(r["model"], r["scaffold"]): r["mean_reward"] for r in rows if r["mean_reward"] is not None}
    small_scores = {s: v for (m, s), v in by.items() if m == small}
    if not small_scores:
        return "No runs for the fixed model yet."
    best_s = max(small_scores, key=small_scores.get)
    worst_s = min(small_scores, key=small_scores.get)
    scaffold_effect = small_scores[best_s] - small_scores[worst_s]
    lines = [f"Fixed model {small}: best scaffold {best_s} ({SCAFFOLDS[best_s]['label']}) {small_scores[best_s]:.3f} vs "
             f"worst {worst_s} {small_scores[worst_s]:.3f}: scaffold effect {scaffold_effect:+.3f}."]
    model_effects = {s: by[(frontier, s)] - by[(small, s)] for s in SCAFFOLDS if (frontier, s) in by and (small, s) in by}
    if model_effects:
        avg_model = mean(model_effects.values())
        lines.append(f"Model effect ({frontier} minus {small}) at matched scaffolds: "
                     + ", ".join(f"{s} {v:+.3f}" for s, v in model_effects.items()) + f" (mean {avg_model:+.3f}, size {abs(avg_model):.3f}).")
        verdict = "scaffold matters more than model choice" if scaffold_effect > abs(avg_model) else "model choice matters more than scaffold"
        lines.append(f"On this gym: {verdict}.")
    if (frontier, "S0") in by:
        lines.append(f"Fixed model with its best scaffold ({small_scores[best_s]:.3f}) vs {frontier} with a bare prompt "
                     f"({by[(frontier, 'S0')]:.3f}).")
    return " ".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="results")
    ap.add_argument("--small", required=True)
    ap.add_argument("--compare", "--frontier", dest="frontier", default="local/qwen2.5-0.5b",
                    help="comparison model run at matched scaffolds (default: local Qwen-0.5B)")
    args = ap.parse_args()
    rows = load(Path(args.results))
    summary = {"rows": rows, "finding": finding(rows, args.small, args.frontier)}
    out = Path(args.results) / "track_c" / "summary.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2))
    print(summary["finding"])


if __name__ == "__main__":
    main()
