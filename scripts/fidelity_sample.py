"""Builds the rule-set fidelity audit worksheet (brief p.10: "Hand-check at least 10 generated tasks
against the rule-set text and report the divergence rate between the rules and your reference
implementation").

Selects 10 *generated* eval tasks, stratified (every jurisdiction, ceiling binding and not, FX,
proration, and at least two traps), and writes docs/FIDELITY_AUDIT.md. Each task shows the inputs
as the documents state them, with a blank column for the value worked out by hand from RULESET.md.
The reference implementation's values sit in a separate section, to be compared only after the
hand derivation (so the check is not anchored on the code).

Run: uv run python scripts/fidelity_sample.py
"""

from __future__ import annotations

from pathlib import Path

from paygym.generator import generate_split
from paygym.reference.calculator import LINES

OUT = Path(__file__).resolve().parent.parent / "docs" / "FIDELITY_AUDIT.md"
CHECK_LINES = ("earned_salary", "taxable_allowances", "employee_social_insurance", "employee_pension", "income_tax", "net_pay")


def pick(tasks, n=10):
    chosen, seen = [], set()
    wants = [
        lambda t: t.case.jurisdiction == "VAL" and "ceiling_binds" in t.tags,
        lambda t: t.case.jurisdiction == "KES" and "annual_ceiling" in t.tags,
        lambda t: t.case.jurisdiction == "NRD" and "proration_start" in t.tags,
        lambda t: "fx" in t.tags and "mid_period_change" in t.tags,
        lambda t: "retro" in t.tags and "allowances" in t.tags,
        lambda t: t.case.jurisdiction == "NRD" and "ceiling_binds" in t.tags,
        lambda t: t.case.jurisdiction == "KES" and t.case.month == 1,
        lambda t: "proration_end" in t.tags,
        lambda t: t.ground_truth.kind == "refusal" and t.ground_truth.reason_code == "CONFLICTING_RECORDS",
        lambda t: t.ground_truth.kind == "refusal" and t.ground_truth.reason_code in ("MISSING_INPUT", "NO_APPLICABLE_TABLE"),
    ]
    cases = [t for t in tasks if t.case is not None]
    for want in wants:
        task = next((t for t in cases if t.id not in seen and want(t)), None)
        if task:
            chosen.append(task)
            seen.add(task.id)
    for t in cases:  # top up if a stratum was empty
        if len(chosen) >= n:
            break
        if t.id not in seen:
            chosen.append(t)
            seen.add(t.id)
    return chosen[:n]


def main() -> None:
    tasks = pick(generate_split("eval", 95))
    out = ["# Rule-set fidelity audit", "",
           "Brief p.10: hand-check at least 10 generated tasks against the rule-set text and report the divergence rate.", "",
           "**Method.** For each task, work out the payslip **by hand from `ruleset/v1.0/RULESET.md` only** (no code), "
           "write the hand values in Part 1, then compare with the reference implementation in Part 2. A divergence is any "
           "line differing by more than one minor unit (GEN-§1.4), or a different refuse/compute decision or reason code. "
           "Where they differ, the rule set is right and the code has a bug (brief p.9), unless the rule set itself is "
           "ambiguous, in which case the rule set is clarified and its version bumped.", "",
           "## Part 1: hand derivation", ""]
    for i, t in enumerate(tasks, 1):
        out += [f"### {i}. `{t.id}`: {t.case.jurisdiction} {t.case.pay_period}  (tags: {', '.join(t.tags)})", "",
                "Inputs as the documents state them:", "", "```json"]
        for source, record in t.case.sources.items():
            out.append(f"{source}: {record.model_dump_json(exclude_none=True)}")
        out += ["```", "", "| Line | Hand value (from prose) | Working (clauses) |", "|---|---|---|"]
        if t.ground_truth.kind == "refusal":
            out.append("| decision / reason code | | |")
        else:
            out += [f"| {line} | | |" for line in CHECK_LINES]
        out.append("")
    out += ["## Part 2: reference implementation (compare only after Part 1)", ""]
    for i, t in enumerate(tasks, 1):
        gt = t.ground_truth
        if gt.kind == "refusal":
            out.append(f"{i}. `{t.id}`: refuse `{gt.reason_code}` ({gt.clause}), inputs {list(gt.inputs)}")
        else:
            vals = ", ".join(f"{k}={gt.lines[k]}" for k in CHECK_LINES)
            out.append(f"{i}. `{t.id}`: {vals}")
    out += ["", "## Result", "", "| Tasks checked | Lines/decisions compared | Divergences | Divergence rate |", "|---|---|---|---|",
            "| 10 | | | |", "", "Findings and fixes:", ""]
    OUT.write_text("\n".join(out) + "\n")
    print(f"wrote {OUT} with {len(tasks)} tasks: {[t.id for t in tasks]}")


if __name__ == "__main__":
    main()
