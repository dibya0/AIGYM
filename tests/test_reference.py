"""Unit tests for the reference calculator (brief Phase 02: "unit tests on the reference implementation").

Every expected figure below was worked out by hand from ruleset/v1.0/RULESET.md, and the
arithmetic is written next to it, so these tests check the code against the rules rather
than against itself.
"""

from datetime import date
from decimal import Decimal as D

import pytest

from paygym.reference import (
    Allowance,
    Payslip,
    PayslipCase,
    SalaryChange,
    SourceRecord,
    Undetermined,
    bracket_tax,
    compute_payslip,
)
from paygym.ruleset import load_ruleset

RS = load_ruleset("1.0")


def case(jurisdiction, period, **inputs):
    return PayslipCase(jurisdiction=jurisdiction, pay_period=period, sources={"hr_record": SourceRecord(**inputs)})


def payslip(c) -> Payslip:
    result = compute_payslip(c, RS)
    assert isinstance(result, Payslip), result
    return result


# ------------------------------------------------------------------ Valdoria


def test_val_full_month_ceiling_binds_with_meal_and_transport():
    """VAL 2026-03, 9,000 VLD/month, meal 200, transport 100.

    meal: 150 exempt (2026), 50 taxable; transport 100 exempt  -> taxable 50, non-taxable 250
    contributory = 9,000 + 50 = 9,050; ceiling 6,000 binds -> base 6,000
    employee SI = 8% x 6,000 = 480; employer SI = 12% x 6,000 = 720   (naive, uncapped: 724)
    pension = 5% x 9,000 = 450
    taxable = 9,000 + 50 - 450 - 480 - 1,000 = 7,120
    tax = 2,000x10% + 3,000x20% + 2,120x30% = 200 + 600 + 636 = 1,436
    gross = 9,000 + 0 + 50 + 250 = 9,300; net = 9,300 - 480 - 450 - 1,436 = 6,934
    """
    p = payslip(case("VAL", "2026-03", monthly_salary=D(9000), salary_currency="VLD", start_date=date(2024, 5, 1),
                     allowances=(Allowance(type="meal", amount=D(200)), Allowance(type="transport", amount=D(100)))))
    assert p.lines == {
        "earned_salary": D("9000.00"), "retro_pay": D("0.00"), "taxable_allowances": D("50.00"),
        "non_taxable_allowances": D("250.00"), "gross_pay": D("9300.00"), "employee_social_insurance": D("480.00"),
        "employee_pension": D("450.00"), "income_tax": D("1436.00"), "net_pay": D("6934.00"),
        "employer_social_insurance": D("720.00"),
    }
    assert "VAL-§2.1" in p.line_clauses["employee_social_insurance"]  # the ceiling clause drove this line
    assert p.trace.get("contribution_base").value == D(6000)


def test_val_usd_salary_mid_month_raise_and_retro():
    """VAL 2026-04 (30 days), 2,000 USD -> 2,500 USD from 16 April, retro 300 VLD.

    FX 2026 USD->VLD 3.4: 6,800 and 8,500 VLD
    earned = 6,800 x 15/30 + 8,500 x 15/30 = 3,400 + 4,250 = 7,650
    contributory = 7,650 + 300 = 7,950 -> base 6,000; employee SI 480; employer SI 720
    pension = 5% x (7,650 + 300) = 397.50
    taxable = 7,950 - 397.50 - 480 - 1,000 = 6,072.50
    tax = 200 + 600 + 1,072.50 x 30% = 1,121.75
    gross = 7,950; net = 7,950 - 480 - 397.50 - 1,121.75 = 5,950.75
    """
    p = payslip(case("VAL", "2026-04", monthly_salary=D(2000), salary_currency="USD", start_date=date(2025, 1, 6),
                     salary_change=SalaryChange(effective_date=date(2026, 4, 16), monthly_salary=D(2500)),
                     retro_pay=D(300)))
    assert p.lines["earned_salary"] == D("7650.00")
    assert p.lines["employee_social_insurance"] == D("480.00")
    assert p.lines["employee_pension"] == D("397.50")
    assert p.lines["income_tax"] == D("1121.75")
    assert p.lines["net_pay"] == D("5950.75")


def test_val_prorated_start_rounding_at_line_level():
    """VAL 2026-01 (31 calendar days), start 11 Jan -> 21 employed days, 5,000 VLD.

    earned = 5,000 x 21/31 = 3,387.0967741...       -> 3,387.10
    base = 3,387.0967741 (below ceiling); employee SI = 270.9677419 -> 270.97; employer = 406.4516129 -> 406.45
    pension = 169.3548387 -> 169.35
    taxable = 3,387.0967742 - 169.3548387 - 270.9677419 - 1,000 = 1,946.7741936 (full precision, GEN-§1.3)
    tax = 10% x 1,946.7741936 = 194.6774194 -> 194.68
    net = 3,387.10 - 270.97 - 169.35 - 194.68 = 2,752.10
    """
    p = payslip(case("VAL", "2026-01", monthly_salary=D(5000), salary_currency="VLD", start_date=date(2026, 1, 11)))
    assert p.lines["earned_salary"] == D("3387.10")
    assert p.lines["employee_social_insurance"] == D("270.97")
    assert p.lines["employer_social_insurance"] == D("406.45")
    assert p.lines["employee_pension"] == D("169.35")
    assert p.lines["income_tax"] == D("194.68")
    assert p.lines["net_pay"] == D("2752.10")


def test_val_2025_table_uses_2025_ceiling():
    """VAL 2025-06, 9,000 VLD: 2025 ceiling 5,500 -> employee SI = 8% x 5,500 = 440 (not 480)."""
    p = payslip(case("VAL", "2025-06", monthly_salary=D(9000), salary_currency="VLD", start_date=date(2020, 1, 1)))
    assert p.lines["employee_social_insurance"] == D("440.00")


# ------------------------------------------------------------------ Kestrel Isles


def test_kes_resident_annual_ceiling_partly_used():
    """KES 2026-11 resident, 7,000 KSD, YTD contributory 68,000.

    remaining ceiling = 72,000 - 68,000 = 4,000 -> base 4,000; employee SI 240; employer SI 360
    pension = 4% x 7,000 = 280; M = 7,000 - 280 = 6,720 (SI not deductible in KES)
    annual = 12 x 6,720 - 12,000 = 68,640
    annual tax = 24,000x15% + 36,000x25% + 8,640x35% = 3,600 + 9,000 + 3,024 = 15,624 -> /12 = 1,302
    net = 7,000 - 240 - 280 - 1,302 = 5,178
    """
    p = payslip(case("KES", "2026-11", monthly_salary=D(7000), salary_currency="KSD", start_date=date(2023, 2, 1),
                     tax_residency="resident", ytd_contributory_earnings=D(68000)))
    assert p.lines["employee_social_insurance"] == D("240.00")
    assert p.lines["employer_social_insurance"] == D("360.00")
    assert p.lines["income_tax"] == D("1302.00")
    assert p.lines["net_pay"] == D("5178.00")
    assert "KES-§2.1" in p.line_clauses["employee_social_insurance"]


def test_kes_non_resident_flat_tax():
    """Same as above but non-resident: tax = 25% x 6,720 = 1,680; net = 7,000 - 240 - 280 - 1,680 = 4,800."""
    p = payslip(case("KES", "2026-11", monthly_salary=D(7000), salary_currency="KSD", start_date=date(2023, 2, 1),
                     tax_residency="non_resident", ytd_contributory_earnings=D(68000)))
    assert p.lines["income_tax"] == D("1680.00")
    assert p.lines["net_pay"] == D("4800.00")
    assert "KES-§4.3" in p.line_clauses["income_tax"]


def test_kes_ceiling_exhausted_means_no_contribution():
    """KES 2026-12, YTD 75,000 >= 72,000: remaining ceiling 0 -> both contributions 0."""
    p = payslip(case("KES", "2026-12", monthly_salary=D(7000), salary_currency="KSD", start_date=date(2023, 2, 1),
                     tax_residency="resident", ytd_contributory_earnings=D(75000)))
    assert p.lines["employee_social_insurance"] == D("0.00")
    assert p.lines["employer_social_insurance"] == D("0.00")


def test_kes_january_ytd_unused_and_disregarded():
    """KES-§1.2: in January YTD is zero by definition, so missing YTD is fine and a stated YTD is ignored.

    2026-01, 7,000: base = min(7,000, 72,000 - 0) = 7,000 -> employee SI = 420
    """
    missing = payslip(case("KES", "2026-01", monthly_salary=D(7000), salary_currency="KSD", start_date=date(2023, 2, 1),
                           tax_residency="resident"))
    stated = payslip(case("KES", "2026-01", monthly_salary=D(7000), salary_currency="KSD", start_date=date(2023, 2, 1),
                          tax_residency="resident", ytd_contributory_earnings=D(70000)))
    assert missing.lines["employee_social_insurance"] == D("420.00")
    assert stated.lines == missing.lines


# ------------------------------------------------------------------ Nordmark


def test_nrd_working_day_proration_and_whole_units():
    """NRD 2026-02 (20 working days), start Monday 16 Feb -> 10 working days, 6,000 NMK.

    earned = 6,000 x 10/20 = 3,000; base 3,000 (< 5,000); employee SI 210; employer SI 300
    pension = 3% x 3,000 = 90; taxable = 3,000 - 90 - 800 = 2,110 (SI not deductible in NRD)
    tax = 12% x 2,110 = 253.2 -> 253 (whole krone, NRD-§1.1)
    net = 3,000 - 210 - 90 - 253 = 2,447
    """
    p = payslip(case("NRD", "2026-02", monthly_salary=D(6000), salary_currency="NMK", start_date=date(2026, 2, 16)))
    assert p.lines["earned_salary"] == D(3000)
    assert p.lines["income_tax"] == D(253)
    assert p.lines["net_pay"] == D(2447)
    assert p.minor_unit == D(1)
    assert "NRD-§1.2" in p.line_clauses["earned_salary"]


def test_nrd_end_date_mid_month():
    """NRD 2026-03: 1 March 2026 is a Sunday; 22 working days. End Friday 13 March -> 10 working days.

    earned = 4,400 x 10/22 = 2,000
    """
    p = payslip(case("NRD", "2026-03", monthly_salary=D(4400), salary_currency="NMK", start_date=date(2025, 1, 1),
                     end_date=date(2026, 3, 13)))
    assert p.lines["earned_salary"] == D(2000)


# ------------------------------------------------------------------ brackets


def test_bracket_tax_marginal_and_negative():
    bands = RS.table("VAL", 2026).brackets.bands
    assert bracket_tax(D(2000), bands) == D(200)
    assert bracket_tax(D(12000), bands) == D(200 + 600 + 1500 + 800)
    assert bracket_tax(D(-50), bands) == D(0)  # GEN-§11.2


# ------------------------------------------------------------------ undetermined cases (GEN-§9) and their twins


def test_no_applicable_table():
    r = compute_payslip(case("VAL", "2027-02", monthly_salary=D(5000), salary_currency="VLD", start_date=date(2024, 1, 1)), RS)
    assert isinstance(r, Undetermined) and r.reason_code == "NO_APPLICABLE_TABLE" and r.clause == "GEN-§9.3"


def test_unsupported_currency():
    r = compute_payslip(case("VAL", "2026-02", monthly_salary=D(5000), salary_currency="GBP", start_date=date(2024, 1, 1)), RS)
    assert isinstance(r, Undetermined) and r.reason_code == "UNSUPPORTED_CURRENCY"


def test_missing_residency_kes_but_not_val():
    """tax_residency is required in KES (trap) but unused in VAL (twin: still computable)."""
    kes = compute_payslip(case("KES", "2026-05", monthly_salary=D(5000), salary_currency="KSD", start_date=date(2024, 1, 1),
                               ytd_contributory_earnings=D(20000)), RS)
    assert isinstance(kes, Undetermined) and kes.reason_code == "MISSING_INPUT" and kes.inputs == ("tax_residency",)
    val = compute_payslip(case("VAL", "2026-05", monthly_salary=D(5000), salary_currency="VLD", start_date=date(2024, 1, 1)), RS)
    assert isinstance(val, Payslip)


def test_conflicting_start_dates_vs_conflicting_unused_input():
    """Sources disagree on start_date (used) -> CONFLICTING_RECORDS; disagree on residency in VAL (unused) -> computable."""
    base = dict(monthly_salary=D(5000), salary_currency="VLD")
    conflict = PayslipCase(jurisdiction="VAL", pay_period="2026-03", sources={
        "hr_record": SourceRecord(**base, start_date=date(2026, 3, 9)),
        "contract": SourceRecord(**base, start_date=date(2026, 3, 16)),
    })
    r = compute_payslip(conflict, RS)
    assert isinstance(r, Undetermined) and r.reason_code == "CONFLICTING_RECORDS" and r.inputs == ("start_date",)

    twin = PayslipCase(jurisdiction="VAL", pay_period="2026-03", sources={
        "hr_record": SourceRecord(**base, start_date=date(2024, 3, 9), tax_residency="resident"),
        "contract": SourceRecord(**base, start_date=date(2024, 3, 9), tax_residency="non_resident"),
    })
    assert isinstance(compute_payslip(twin, RS), Payslip)


def test_input_stated_in_one_source_only_is_used():
    """GEN-§2.3: a value stated by only one source is used as stated."""
    c = PayslipCase(jurisdiction="VAL", pay_period="2026-03", sources={
        "hr_record": SourceRecord(monthly_salary=D(5000), start_date=date(2024, 1, 1)),
        "contract": SourceRecord(salary_currency="VLD"),
    })
    assert isinstance(compute_payslip(c, RS), Payslip)


def test_reason_precedence():
    """GEN-§9.5: no table (2027) wins over a missing required input."""
    r = compute_payslip(case("KES", "2027-03", monthly_salary=D(5000), salary_currency="KSD", start_date=date(2024, 1, 1)), RS)
    assert isinstance(r, Undetermined) and r.reason_code == "NO_APPLICABLE_TABLE"


# ------------------------------------------------------------------ clause provenance


@pytest.mark.parametrize("code,period,extra", [
    ("VAL", "2026-03", {}),
    ("KES", "2026-03", {"tax_residency": "resident", "ytd_contributory_earnings": D(10000)}),
    ("NRD", "2026-03", {}),
])
def test_every_line_cites_clauses_that_exist(code, period, extra):
    prose = (RS and __import__("paygym.ruleset", fromlist=["ruleset_dir"]).ruleset_dir("1.0") / "RULESET.md").read_text()
    p = payslip(case(code, period, monthly_salary=D(8000), salary_currency="USD", start_date=date(2024, 1, 1), **extra))
    for line, clauses in p.line_clauses.items():
        assert clauses, line
        for clause in clauses:
            assert f"**{clause}" in prose, f"{line} cites {clause}, which is not in RULESET.md"
