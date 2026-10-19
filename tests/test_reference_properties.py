"""Property and metamorphic tests for the reference calculator.

Hand-computed examples (test_reference.py) check specific cases; these check invariants
that must hold for *any* inputs under the rule set, which catches whole classes of bug.
"""

from datetime import date, timedelta
from decimal import Decimal as D

from hypothesis import given, settings
from hypothesis import strategies as st

from paygym.reference import Allowance, Payslip, PayslipCase, SourceRecord, compute_payslip
from paygym.ruleset import load_ruleset

RS = load_ruleset("1.0")
LOCAL = {"VAL": "VLD", "KES": "KSD", "NRD": "NMK"}

jurisdictions = st.sampled_from(["VAL", "KES", "NRD"])
years = st.sampled_from([2025, 2026])
months = st.integers(1, 12)
salaries = st.integers(500, 40000).map(D)
allowances = st.lists(
    st.builds(Allowance, type=st.sampled_from(["meal", "transport", "housing"]), amount=st.integers(0, 600).map(D)),
    max_size=3,
).map(tuple)


def make_case(code, year, month, salary, currency=None, start=date(2020, 1, 1), end=None, allow=(), retro=None,
              ytd=D(0), residency="resident") -> PayslipCase:
    return PayslipCase(jurisdiction=code, pay_period=f"{year}-{month:02d}", sources={"hr": SourceRecord(
        monthly_salary=salary, salary_currency=currency or LOCAL[code], start_date=start, end_date=end,
        allowances=allow or None, retro_pay=retro, tax_residency=residency, ytd_contributory_earnings=ytd)})


def compute(c) -> Payslip:
    result = compute_payslip(c, RS)
    assert isinstance(result, Payslip), result
    return result


@settings(max_examples=300, deadline=None)
@given(jurisdictions, years, months, salaries, allowances, st.integers(0, 90000).map(D), st.sampled_from(["resident", "non_resident"]))
def test_core_invariants(code, year, month, salary, allow, ytd, residency):
    p = compute(make_case(code, year, month, salary, allow=allow, ytd=ytd, residency=residency))
    table = RS.table(code, year)
    unit = RS.jurisdictions[code].minor_unit
    lines = p.lines
    # Net pay never exceeds gross pay, and every deduction is non-negative.
    assert lines["net_pay"] <= lines["gross_pay"]
    for name in ("employee_social_insurance", "employee_pension", "income_tax", "employer_social_insurance"):
        assert lines[name] >= 0, name
    # Contributions never exceed rate x ceiling (GEN-§5.2): the cap is the gym's key difficulty.
    assert lines["employee_social_insurance"] <= table.si_employee_rate.value * table.si_ceiling.value + unit
    base = p.trace.get("contribution_base").value
    assert base <= p.trace.get("contributory_earnings").value
    assert base <= table.si_ceiling.value
    # Gross is the sum of its four lines; net follows from the rounded lines (GEN-§10.2, §10.3).
    assert lines["gross_pay"] == sum(lines[k] for k in ("earned_salary", "retro_pay", "taxable_allowances", "non_taxable_allowances"))
    assert lines["net_pay"] == lines["gross_pay"] - lines["employee_social_insurance"] - lines["employee_pension"] - lines["income_tax"]
    # Every line is rounded to the jurisdiction's minor unit (GEN-§1.3).
    for value in lines.values():
        assert value == value.quantize(unit)


@settings(max_examples=200, deadline=None)
@given(jurisdictions, years, months, salaries, st.integers(10, 5000).map(D))
def test_net_pay_monotone_in_salary(code, year, month, salary, raise_by):
    """A higher salary never lowers net pay: every marginal deduction rate is below 100%."""
    low = compute(make_case(code, year, month, salary)).lines["net_pay"]
    high = compute(make_case(code, year, month, salary + raise_by)).lines["net_pay"]
    unit = RS.jurisdictions[code].minor_unit
    assert high >= low - 3 * unit  # rounding of separate lines can wobble by a few minor units


@settings(max_examples=200, deadline=None)
@given(jurisdictions, years, months, st.integers(500, 15000).map(D), st.sampled_from(["USD", "EUR"]))
def test_foreign_salary_equals_its_converted_local_salary(code, year, month, salary, currency):
    """Metamorphic (GEN-§8.1): a foreign salary gives the same payslip as its converted local amount."""
    rate = RS.fx_rate(currency, LOCAL[code], year)
    foreign = compute(make_case(code, year, month, salary, currency=currency))
    local = compute(make_case(code, year, month, salary * rate))
    assert foreign.lines == local.lines


@settings(max_examples=200, deadline=None)
@given(jurisdictions, years, months, salaries, st.integers(1, 27))
def test_proration_split_adds_up_to_full_month(code, year, month, salary, split_day):
    """Metamorphic (GEN-§6.2): leaving on day k and joining on day k+1 earns, in total, one full month."""
    first = date(year, month, 1)
    leave = first + timedelta(days=split_day - 1)
    part1 = compute(make_case(code, year, month, salary, start=date(2020, 1, 1), end=leave))
    part2 = compute(make_case(code, year, month, salary, start=leave + timedelta(days=1)))
    total = part1.trace.get("earned_salary").value + part2.trace.get("earned_salary").value
    assert abs(total - salary) < D("1e-20")


@settings(max_examples=150, deadline=None)
@given(st.sampled_from(["VAL", "NRD"]), years, months, st.integers(8000, 40000).map(D))
def test_monthly_ceiling_binds_above_it(code, year, month, salary):
    """Above the monthly ceiling, employee SI is exactly rate x ceiling, whatever the salary."""
    table = RS.table(code, year)
    p = compute(make_case(code, year, month, salary))
    expected = (table.si_employee_rate.value * table.si_ceiling.value).quantize(RS.jurisdictions[code].minor_unit)
    assert p.lines["employee_social_insurance"] == expected
