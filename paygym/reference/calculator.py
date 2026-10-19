"""Reference payslip calculator: a faithful implementation of ruleset/v1.0/RULESET.md.

Every step cites the clause it implements (``@cites``) and is recorded in a ``Trace``.
Where this code and RULESET.md disagree, RULESET.md is right and this code has a bug.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from paygym.reference.inputs import INPUT_FIELDS, OPTIONAL_INPUTS, PayslipCase
from paygym.reference.trace import Trace, cites
from paygym.ruleset import Band, Jurisdiction, RateTable, Ruleset, load_ruleset

ZERO = Decimal(0)

LINES: tuple[str, ...] = (
    "earned_salary",
    "retro_pay",
    "taxable_allowances",
    "non_taxable_allowances",
    "gross_pay",
    "employee_social_insurance",
    "employee_pension",
    "income_tax",
    "net_pay",
    "employer_social_insurance",
)

REASON_CLAUSES = {
    "NO_APPLICABLE_TABLE": "GEN-§9.3",
    "UNSUPPORTED_CURRENCY": "GEN-§9.4",
    "MISSING_INPUT": "GEN-§9.1",
    "CONFLICTING_RECORDS": "GEN-§9.2",
}


@dataclass(frozen=True)
class Undetermined:
    """The rules do not determine the payslip (GEN-§9); the correct output is a refusal."""

    reason_code: str
    inputs: tuple[str, ...]
    detail: str

    @property
    def clause(self) -> str:
        return REASON_CLAUSES[self.reason_code]


@dataclass(frozen=True)
class Payslip:
    jurisdiction: str
    currency: str
    minor_unit: Decimal
    lines: dict[str, Decimal]
    line_clauses: dict[str, tuple[str, ...]]
    trace: Trace = field(compare=False)


# --------------------------------------------------------------------------- inputs (GEN-§2, §9)


def _canonical(value):
    if isinstance(value, tuple):  # allowances: order of listing is irrelevant
        return tuple(sorted((a.type, a.amount) for a in value))
    return value


def unused_inputs(jur: Jurisdiction, month: int) -> set[str]:
    unused = set(jur.unused_inputs)
    if month == 1:
        unused |= set(jur.january_unused_inputs)  # KES-§1.2 exception
    return unused


def resolve_inputs(case: PayslipCase, ruleset: Ruleset) -> dict | Undetermined:
    """Merge the sources into one value per input (GEN-§2.2, §2.3), or report why that is impossible (GEN-§9)."""
    jur = ruleset.jurisdictions[case.jurisdiction]
    unused = unused_inputs(jur, case.month)
    required = [f for f in jur.required_inputs if f in INPUT_FIELDS and f not in unused]

    resolved: dict = {}
    missing: list[str] = []
    conflicting: list[str] = []
    for name in INPUT_FIELDS:
        if name in unused:
            continue
        stated = [getattr(src, name) for src in case.sources.values() if getattr(src, name) is not None]
        if not stated:
            if name in required:
                missing.append(name)
            continue
        if len({_canonical(v) for v in stated}) > 1:
            conflicting.append(name)
            continue
        resolved[name] = stated[0]

    # GEN-§9.5 precedence: §9.3, §9.4, §9.1, §9.2.
    if ruleset.table(case.jurisdiction, case.year) is None:
        return Undetermined("NO_APPLICABLE_TABLE", ("pay_period",), f"no {case.jurisdiction} rate table for {case.year}")
    currency = resolved.get("salary_currency")
    if currency is not None and currency != jur.currency and ruleset.fx_rate(currency, jur.currency, case.year) is None:
        return Undetermined("UNSUPPORTED_CURRENCY", ("salary_currency",), f"no {currency}->{jur.currency} rate")
    if missing:
        return Undetermined("MISSING_INPUT", tuple(missing), "required input absent from every source")
    if conflicting:
        return Undetermined("CONFLICTING_RECORDS", tuple(conflicting), "sources state different values")
    for name in OPTIONAL_INPUTS:
        resolved.setdefault(name, None)
    return resolved


# --------------------------------------------------------------------------- computation steps


def _period_bounds(case: PayslipCase) -> tuple[date, date]:
    last_day = calendar.monthrange(case.year, case.month)[1]
    return date(case.year, case.month, 1), date(case.year, case.month, last_day)


def _count_days(first: date, last: date, method: str) -> int:
    if first > last:
        return 0
    days = (last - first).days + 1
    if method == "calendar":
        return days
    return sum(1 for i in range(days) if (first + timedelta(days=i)).weekday() < 5)  # NRD-§1.2: Mon–Fri


@cites("GEN-§8.1", "FX-§1.1")
def _salary_in_local_currency(amount: Decimal, rate: Decimal) -> Decimal:
    return amount * rate


@cites("GEN-§6.1", "GEN-§6.2", "GEN-§6.3", "GEN-§6.4")
def _earned_salary(
    old_salary: Decimal,
    new_salary: Decimal | None,
    change_date: date | None,
    start: date,
    end: date | None,
    period_first: date,
    period_last: date,
    method: str,
) -> Decimal:
    total = _count_days(period_first, period_last, method)
    emp_first = max(start, period_first)
    emp_last = min(end or period_last, period_last)
    if emp_first > emp_last:
        return ZERO  # GEN-§6.4
    if new_salary is None or change_date is None or change_date > period_last:
        old_days, new_days = _count_days(emp_first, emp_last, method), 0
    elif change_date <= period_first:
        old_days, new_days = 0, _count_days(emp_first, emp_last, method)
    else:
        old_days = _count_days(emp_first, min(emp_last, change_date - timedelta(days=1)), method)
        new_days = _count_days(max(emp_first, change_date), emp_last, method)
    earned = old_salary * Decimal(old_days) / Decimal(total)
    if new_days:
        earned += new_salary * Decimal(new_days) / Decimal(total)
    return earned


def _allowance_totals(allowances) -> dict[str, Decimal]:
    totals = {"meal": ZERO, "transport": ZERO, "housing": ZERO}
    for a in allowances or ():
        totals[a.type] += a.amount  # GEN-§7.4, GEN-§7.5
    return totals


@cites("GEN-§7.2", "GEN-§7.3", "GEN-§7.4", "GEN-§7.5")
def _taxable_allowances(totals: dict[str, Decimal], meal_exemption: Decimal) -> Decimal:
    return max(ZERO, totals["meal"] - meal_exemption) + totals["housing"]


@cites("GEN-§7.1", "GEN-§7.2", "GEN-§7.4", "GEN-§7.5")
def _non_taxable_allowances(totals: dict[str, Decimal], meal_exemption: Decimal) -> Decimal:
    return min(totals["meal"], meal_exemption) + totals["transport"]


@cites("GEN-§5.1")
def _contributory_earnings(earned: Decimal, retro: Decimal, taxable_allowances: Decimal) -> Decimal:
    return earned + retro + taxable_allowances


@cites("GEN-§5.2")
def _contribution_base_monthly(contributory: Decimal, ceiling: Decimal) -> Decimal:
    return min(contributory, ceiling)


@cites("GEN-§5.2")
def _contribution_base_annual(contributory: Decimal, ceiling: Decimal, ytd: Decimal) -> Decimal:
    remaining = max(ZERO, ceiling - ytd)
    return min(contributory, remaining)


@cites("GEN-§5.2")
def _employee_social_insurance(rate: Decimal, base: Decimal) -> Decimal:
    return rate * base


@cites("GEN-§5.2", "GEN-§5.3")
def _employer_social_insurance(rate: Decimal, base: Decimal) -> Decimal:
    return rate * base


@cites()
def _employee_pension(rate: Decimal, earned: Decimal, retro: Decimal) -> Decimal:
    return rate * (earned + retro)


def bracket_tax(amount: Decimal, bands: tuple[Band, ...]) -> Decimal:
    """GEN-§11.1 marginal bands; GEN-§11.2 negative amounts are treated as zero."""
    amount = max(ZERO, amount)
    tax = ZERO
    for band in bands:
        top = amount if band.upper is None else min(amount, band.upper)
        if top > band.lower:
            tax += band.rate * (top - band.lower)
    return tax


@cites()
def _taxable_income(earned, retro, taxable_allowances, pension, deductible_si, personal_allowance) -> Decimal:
    return earned + retro + taxable_allowances - pension - deductible_si - personal_allowance


@cites("KES-§4.1")
def _monthly_taxable_earnings(earned, retro, taxable_allowances, pension) -> Decimal:
    return earned + retro + taxable_allowances - pension


@cites("KES-§4.2")
def _annual_taxable_income(monthly_taxable: Decimal, annual_allowance: Decimal) -> Decimal:
    return 12 * monthly_taxable - annual_allowance


@cites("GEN-§11.1", "GEN-§11.2")
def _income_tax_brackets(taxable: Decimal, bands: tuple[Band, ...], divisor: int = 1) -> Decimal:
    return bracket_tax(taxable, bands) / divisor


@cites("KES-§4.3")
def _income_tax_non_resident(rate: Decimal, monthly_taxable: Decimal) -> Decimal:
    return rate * max(ZERO, monthly_taxable)


def _round(value: Decimal, minor_unit: Decimal) -> Decimal:
    return value.quantize(minor_unit, rounding=ROUND_HALF_UP)  # GEN-§1.3


# --------------------------------------------------------------------------- entry point


def compute_payslip(case: PayslipCase, ruleset: Ruleset | None = None) -> Payslip | Undetermined:
    """Compute one payslip per RULESET GEN-§3, or return why the rules do not determine it."""
    ruleset = ruleset or load_ruleset()
    resolved = resolve_inputs(case, ruleset)
    if isinstance(resolved, Undetermined):
        return resolved

    code = case.jurisdiction
    jur = ruleset.jurisdictions[code]
    table: RateTable = ruleset.table(code, case.year)  # GEN-§4.1 (presence checked in resolve_inputs)
    trace = Trace()
    period_first, period_last = _period_bounds(case)
    day_clause = f"{code}-§1.2" if jur.day_count == "working" else f"{code}-§1.1"

    # GEN-§8: currency conversion.
    currency = resolved["salary_currency"]
    rate = Decimal(1) if currency == jur.currency else ruleset.fx_rate(currency, jur.currency, case.year)
    salary = _salary_in_local_currency(resolved["monthly_salary"], rate, trace=trace)
    change = resolved["salary_change"]
    new_salary = None
    if change is not None:
        new_salary = _salary_in_local_currency(change.monthly_salary, rate, trace=trace, step="new_salary_in_local_currency")

    # GEN-§6: earned salary.
    earned = _earned_salary(
        salary,
        new_salary,
        change.effective_date if change else None,
        resolved["start_date"],
        resolved["end_date"],
        period_first,
        period_last,
        jur.day_count,
        trace=trace,
        also=(day_clause,),
    )
    retro = trace.record("retro_pay", resolved["retro_pay"] or ZERO, ("GEN-§2.1", "GEN-§2.2"))

    # GEN-§7: allowances.
    totals = _allowance_totals(resolved["allowances"])
    taxable_allow = _taxable_allowances(totals, table.meal_exemption.value, trace=trace)
    non_taxable_allow = _non_taxable_allowances(totals, table.meal_exemption.value, trace=trace)

    # GEN-§5 + jurisdiction §2: social insurance.
    contributory = _contributory_earnings(earned, retro, taxable_allow, trace=trace)
    if jur.si_ceiling_basis == "monthly":
        base = _contribution_base_monthly(contributory, table.si_ceiling.value, trace=trace, step="contribution_base", also=(f"{code}-§2.1",))
    else:
        ytd = ZERO if case.month == 1 else resolved["ytd_contributory_earnings"]  # KES-§1.2 exception
        base = _contribution_base_annual(contributory, table.si_ceiling.value, ytd, trace=trace, step="contribution_base", also=(f"{code}-§2.1", f"{code}-§1.2"))
    # Contribution lines inherit the base's clauses: when the ceiling binds, it is the ceiling
    # clause that drives the amount, so it must appear in the line's provenance.
    base_clauses = tuple(c for c in trace.get("contribution_base").clauses if c != "GEN-§5.2")
    ee_si = _employee_social_insurance(table.si_employee_rate.value, base, trace=trace, also=(f"{code}-§2.2",) + base_clauses)
    er_si = _employer_social_insurance(table.si_employer_rate.value, base, trace=trace, also=(f"{code}-§2.2",) + base_clauses)

    # Jurisdiction §3: pension.
    pension = _employee_pension(table.pension_rate.value, earned, retro, trace=trace, also=(f"{code}-§3.1",))

    # Jurisdiction §4: income tax (GEN-§1.3: later steps use full-precision amounts).
    if jur.tax_method == "monthly_brackets":
        deductible_si = ee_si if jur.si_deductible_from_tax else ZERO
        taxable = _taxable_income(
            earned, retro, taxable_allow, pension, deductible_si, table.personal_allowance.value,
            trace=trace, also=(f"{code}-§4.1",),
        )
        tax = _income_tax_brackets(taxable, table.brackets.bands, trace=trace, step="income_tax", also=(f"{code}-§4.2",))
    else:
        monthly_taxable = _monthly_taxable_earnings(earned, retro, taxable_allow, pension, trace=trace)
        if resolved["tax_residency"] == "resident":
            annual = _annual_taxable_income(monthly_taxable, table.personal_allowance.value, trace=trace)
            tax = _income_tax_brackets(annual, table.brackets.bands, 12, trace=trace, step="income_tax", also=(f"{code}-§4.2",))
        else:
            tax = _income_tax_non_resident(table.non_resident_rate.value, monthly_taxable, trace=trace, step="income_tax")

    # GEN-§10: payslip lines, rounded per GEN-§1.3.
    unit = jur.minor_unit
    rounding = ("GEN-§1.3",) + (("NRD-§1.1",) if code == "NRD" else ())
    raw = {
        "earned_salary": earned,
        "retro_pay": retro,
        "taxable_allowances": taxable_allow,
        "non_taxable_allowances": non_taxable_allow,
        "employee_social_insurance": ee_si,
        "employee_pension": pension,
        "income_tax": tax,
        "employer_social_insurance": er_si,
    }
    lines = {name: _round(value, unit) for name, value in raw.items()}
    line_clauses = {name: trace.get(name).clauses + rounding for name in raw}
    lines["gross_pay"] = lines["earned_salary"] + lines["retro_pay"] + lines["taxable_allowances"] + lines["non_taxable_allowances"]
    line_clauses["gross_pay"] = ("GEN-§10.1", "GEN-§10.2")
    lines["net_pay"] = lines["gross_pay"] - lines["employee_social_insurance"] - lines["employee_pension"] - lines["income_tax"]
    line_clauses["net_pay"] = ("GEN-§10.3",)
    for name in ("gross_pay", "net_pay"):
        trace.record(name, lines[name], line_clauses[name])

    return Payslip(
        jurisdiction=code,
        currency=jur.currency,
        minor_unit=unit,
        lines={name: lines[name] for name in LINES},
        line_clauses={name: line_clauses[name] for name in LINES},
        trace=trace,
    )
