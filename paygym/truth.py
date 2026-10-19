"""Ground truth for tasks, derived only from the rule set and the reference calculator (never an LLM)."""

from __future__ import annotations

from decimal import Decimal

from paygym.reference import Payslip, PayslipCase, compute_payslip
from paygym.ruleset import Ruleset, load_ruleset
from paygym.schema import Lookup, PayslipTruth, RefusalTruth, ValueTruth

# Units for retrieval answers: currency amounts vs rates.
RATE_FIELDS = {"si_employee_rate", "si_employer_rate", "pension_rate", "non_resident_rate"}


def truth_for_lookup(lookup: Lookup, ruleset: Ruleset | None = None) -> ValueTruth:
    ruleset = ruleset or load_ruleset()
    jur = ruleset.jurisdictions[lookup.jurisdiction]
    if lookup.field.startswith("fx:"):
        currency = lookup.field[3:]
        rate = ruleset.fx_rate(currency, jur.currency, lookup.year)
        if rate is None:
            raise ValueError(f"no FX rate {currency}->{jur.currency} in {lookup.year}")
        return ValueTruth(value=rate, unit="fx_rate", tolerance=Decimal(0), clauses=(ruleset.fx.clause, "GEN-§8.1"))
    table = ruleset.table(lookup.jurisdiction, lookup.year)
    if table is None:
        raise ValueError(f"no {lookup.jurisdiction} table for {lookup.year}")
    cited = getattr(table, lookup.field)
    if cited is None or not hasattr(cited, "value"):
        raise ValueError(f"{lookup.field} is not a single-valued rate-table field")
    unit = "rate" if lookup.field in RATE_FIELDS else jur.currency
    # Retrieval answers are read, not computed: exact match is required (tolerance 0).
    return ValueTruth(value=cited.value, unit=unit, tolerance=Decimal(0), clauses=(cited.clause, "GEN-§4.1"))


def truth_for_case(case: PayslipCase, ruleset: Ruleset | None = None) -> PayslipTruth | RefusalTruth:
    result = compute_payslip(case, ruleset or load_ruleset())
    if isinstance(result, Payslip):
        return PayslipTruth(
            currency=result.currency,
            tolerance=result.minor_unit,  # GEN-§1.4: one minor unit
            lines=result.lines,
            line_clauses=result.line_clauses,
        )
    return RefusalTruth(reason_code=result.reason_code, inputs=result.inputs, clause=result.clause)
