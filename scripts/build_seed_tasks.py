"""Builds tasks/seed_v1.jsonl: the hand-written, hand-checked seed taskset (brief Phase 01).

Each task below was written by hand. Its `hand_check` values were worked out by hand from
ruleset/v1.0/RULESET.md (the working is in `hand_check["working"]`). The ground truth is
then computed by the reference implementation, and `paygym validate` fails if the two
disagree, so the hand check is enforced, not just claimed.

Run: uv run python scripts/build_seed_tasks.py
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal as D
from pathlib import Path

from paygym.reference import Allowance, PayslipCase, SalaryChange, SourceRecord
from paygym.render import Style, context_for, lookup_prompt, payslip_prompt
from paygym.schema import Lookup, Task, TrapReason, dump_task
from paygym.truth import truth_for_case, truth_for_lookup

OUT = Path(__file__).resolve().parent.parent / "tasks" / "seed_v1.jsonl"
RULESET_VERSION = "1.0"


def lookup_task(task_id, jurisdiction, year, field, hand_value, tags):
    lookup = Lookup(jurisdiction=jurisdiction, year=year, field=field)
    return Task(
        id=task_id, difficulty=1, prompt=lookup_prompt(jurisdiction, year, field),
        context_files=context_for(jurisdiction), lookup=lookup, ground_truth=truth_for_lookup(lookup),
        verifier="value_match", tags=("retrieval",) + tags, ruleset_version=RULESET_VERSION,
        provenance="hand_written", hand_check={"value": hand_value},
    )


def case_task(task_id, difficulty, case, name, employee_id, hand_check, tags, documents=None, style=Style(),
              twin_of=None, trap_reason=None):
    documents = documents or {}
    truth = truth_for_case(case)
    return Task(
        id=task_id, difficulty=difficulty, prompt=payslip_prompt(case, documents, name, employee_id, style),
        context_files=context_for(case.jurisdiction), employee_id=employee_id, case=case, documents=documents,
        ground_truth=truth, verifier="refusal" if truth.kind == "refusal" else "payslip_lines",
        tags=tags, ruleset_version=RULESET_VERSION, twin_of=twin_of, trap_reason=trap_reason,
        provenance="hand_written", hand_check=hand_check,
    )


def src(**kw) -> SourceRecord:
    return SourceRecord(**kw)


def build() -> list[Task]:
    tasks: list[Task] = []

    # ---------------------------------------------------------------- Tier 1: retrieval
    tasks.append(lookup_task("seed-t1-01", "VAL", 2026, "si_ceiling", "6000.00", ("ceiling",)))
    tasks.append(lookup_task("seed-t1-02", "KES", 2026, "si_ceiling", "72000.00", ("ceiling", "annual_ceiling")))
    tasks.append(lookup_task("seed-t1-03", "VAL", 2025, "meal_exemption", "120.00", ("effective_date",)))

    # ---------------------------------------------------------------- Tier 2: computation
    tasks.append(case_task(
        "seed-t2-01", 2,
        PayslipCase(jurisdiction="VAL", pay_period="2026-03", sources={
            "hr_record": src(monthly_salary=D(9000), salary_currency="VLD", start_date=date(2024, 5, 1),
                             allowances=(Allowance(type="meal", amount=D(200)), Allowance(type="transport", amount=D(100)))),
            "contract": src(monthly_salary=D(9000), salary_currency="VLD", start_date=date(2024, 5, 1)),
        }),
        "Ilsa Marrow", "VAL-1042",
        {"net_pay": "6934.00", "employee_social_insurance": "480.00", "income_tax": "1436.00",
         "working": "meal 150 exempt/50 taxable; contributory 9,050 -> ceiling 6,000 binds -> SI 480; pension 450; "
                    "taxable 9,000+50-450-480-1,000=7,120; tax 200+600+636=1,436; gross 9,300; net 6,934"},
        ("ceiling_binds", "allowances"),
        documents={"hr_record": {"employee_id": "VAL-1042", "name": "Ilsa Marrow", "job_title": "Operations Lead"}},
    ))
    tasks.append(case_task(
        "seed-t2-02", 2,
        PayslipCase(jurisdiction="VAL", pay_period="2026-04", sources={
            "hr_record": src(monthly_salary=D(2000), salary_currency="USD", start_date=date(2025, 1, 6),
                             salary_change=SalaryChange(effective_date=date(2026, 4, 16), monthly_salary=D(2500))),
            "payroll_note": src(retro_pay=D(300)),
        }),
        "Teodor Vance", "VAL-2210",
        {"net_pay": "5950.75", "earned_salary": "7650.00", "income_tax": "1121.75",
         "working": "USD->VLD 3.4: 6,800 / 8,500; earned 3,400+4,250=7,650; +retro 300 -> base 6,000 -> SI 480; "
                    "pension 397.50; taxable 6,072.50; tax 1,121.75; net 7,950-480-397.50-1,121.75=5,950.75"},
        ("fx", "mid_period_change", "retro", "ceiling_binds", "format:dmy"),
        documents={"hr_record": {"employee_id": "VAL-2210", "name": "Teodor Vance"}},
        style=Style(date_format="dmy"),
    ))
    tasks.append(case_task(
        "seed-t2-03", 2,
        PayslipCase(jurisdiction="KES", pay_period="2026-11", sources={
            "hr_record": src(monthly_salary=D(7000), salary_currency="KSD", start_date=date(2023, 2, 1),
                             tax_residency="resident", ytd_contributory_earnings=D(68000)),
        }),
        "Odile Fenwick", "KES-0317",
        {"net_pay": "5178.00", "employee_social_insurance": "240.00", "income_tax": "1302.00",
         "working": "remaining annual ceiling 72,000-68,000=4,000 -> SI 240; pension 280; M=6,720; "
                    "annual 68,640 -> tax 15,624/12=1,302; net 7,000-240-280-1,302=5,178"},
        ("annual_ceiling", "annualised_tax", "format:comma_dot"),
        documents={"hr_record": {"employee_id": "KES-0317", "name": "Odile Fenwick"}},
        style=Style(number_format="comma_dot"),
    ))
    tasks.append(case_task(
        "seed-t2-04", 2,
        PayslipCase(jurisdiction="NRD", pay_period="2026-02", sources={
            "hr_record": src(monthly_salary=D(6000), salary_currency="NMK", start_date=date(2026, 2, 16)),
            "contract": src(monthly_salary=D(6000), salary_currency="NMK", start_date=date(2026, 2, 16)),
        }),
        "Brannoc Hale", "NRD-0788",
        {"net_pay": "2447", "earned_salary": "3000", "income_tax": "253",
         "working": "Feb 2026: 20 working days, employed 16th-27th = 10 -> earned 3,000; SI 210; pension 90; "
                    "taxable 2,110 -> tax 253.2 -> 253 (whole krone); net 3,000-210-90-253=2,447"},
        ("proration", "working_days", "whole_units", "annual_salary_stated"),
        documents={"hr_record": {"employee_id": "NRD-0788", "name": "Brannoc Hale"}},
        style=Style(annual_salary=True),
    ))
    tasks.append(case_task(
        "seed-t2-05", 2,
        PayslipCase(jurisdiction="VAL", pay_period="2026-01", sources={
            "hr_record": src(monthly_salary=D(5000), salary_currency="VLD", start_date=date(2026, 1, 11)),
        }),
        "Mirela Strand", "VAL-3305",
        {"net_pay": "2752.10", "earned_salary": "3387.10", "income_tax": "194.68",
         "working": "21/31 days -> 3,387.0967742; SI 270.97; pension 169.35; taxable (full precision) 1,946.7741936; "
                    "tax 194.68; net 3,387.10-270.97-169.35-194.68=2,752.10"},
        ("proration", "rounding"),
        documents={"hr_record": {"employee_id": "VAL-3305", "name": "Mirela Strand"}},
    ))

    # ---------------------------------------------------------------- Tier 3: traps, each with a determinable twin
    # Trap 1: required input absent (KES needs YTD outside January).
    kes_src = dict(monthly_salary=D(6000), salary_currency="KSD", start_date=date(2024, 2, 1), tax_residency="resident")
    tasks.append(case_task(
        "seed-t3-01", 3,
        PayslipCase(jurisdiction="KES", pay_period="2026-06", sources={"hr_record": src(**kes_src)}),
        "Caspian Rook", "KES-0911",
        {"reason_code": "MISSING_INPUT", "working": "KES-§1.2 requires ytd_contributory_earnings outside January; no source states it"},
        ("trap", "missing_input", "annual_ceiling"),
        documents={"hr_record": {"employee_id": "KES-0911", "name": "Caspian Rook"}},
        trap_reason=TrapReason(category="input_absent", reason_code="MISSING_INPUT", clause="GEN-§9.1",
                               explanation="The annual cumulative ceiling (KES-§2.1) cannot be applied without year-to-date contributory earnings, which no document states."),
    ))
    tasks.append(case_task(
        "seed-t2-06", 2,
        PayslipCase(jurisdiction="KES", pay_period="2026-01", sources={"hr_record": src(**kes_src)}),
        "Caspian Rook", "KES-0911",
        {"net_pay": "4410.00", "employee_social_insurance": "360.00", "income_tax": "990.00",
         "working": "January: YTD unused (KES-§1.2) -> base 6,000 -> SI 360; pension 240; M 5,760; annual 57,120 -> "
                    "tax 3,600+8,280=11,880/12=990; net 6,000-360-240-990=4,410"},
        ("twin", "annual_ceiling", "january_exception"),
        documents={"hr_record": {"employee_id": "KES-0911", "name": "Caspian Rook"}},
        twin_of="seed-t3-01",
    ))

    # Trap 2: records contradict each other on a required input.
    base_val = dict(monthly_salary=D(6200), salary_currency="VLD")
    tasks.append(case_task(
        "seed-t3-02", 3,
        PayslipCase(jurisdiction="VAL", pay_period="2026-03", sources={
            "hr_record": src(**base_val, start_date=date(2026, 3, 9)),
            "contract": src(**base_val, start_date=date(2026, 3, 16)),
        }),
        "Juno Abernethy", "VAL-4120",
        {"reason_code": "CONFLICTING_RECORDS", "working": "start_date is 2026-03-09 in the HR record but 2026-03-16 in the contract; no precedence (GEN-§9.2)"},
        ("trap", "conflicting_records", "proration"),
        documents={"hr_record": {"employee_id": "VAL-4120", "name": "Juno Abernethy", "job_title": "Payroll Analyst"},
                   "contract": {"job_title": "Payroll Analyst"}},
        trap_reason=TrapReason(category="records_contradictory", reason_code="CONFLICTING_RECORDS", clause="GEN-§9.2",
                               explanation="The two documents give different start dates, which change the prorated salary; the rule set gives no precedence between sources."),
    ))
    tasks.append(case_task(
        "seed-t2-07", 2,
        PayslipCase(jurisdiction="VAL", pay_period="2026-03", sources={
            "hr_record": src(**base_val, start_date=date(2026, 3, 9)),
            "contract": src(**base_val, start_date=date(2026, 3, 9)),
        }),
        "Juno Abernethy", "VAL-4120",
        {"net_pay": "3601.60", "earned_salary": "4600.00", "income_tax": "400.40",
         "working": "23/31 days x 6,200 = 4,600; SI 368; pension 230; taxable 3,002 -> tax 400.40; net 4,600-368-230-400.40=3,601.60. "
                    "Job titles differ but job title is not an input (GEN-§9.2)"},
        ("twin", "proration", "non_input_disagreement"),
        documents={"hr_record": {"employee_id": "VAL-4120", "name": "Juno Abernethy", "job_title": "Payroll Analyst"},
                   "contract": {"job_title": "Senior Payroll Analyst"}},
        twin_of="seed-t3-02",
    ))

    # Trap 3: rules silent, no rate table for the year (the "stale rate" trap).
    nrd = dict(monthly_salary=D(5200), salary_currency="NMK", start_date=date(2022, 1, 1),
               allowances=(Allowance(type="meal", amount=D(120)),))
    tasks.append(case_task(
        "seed-t3-03", 3,
        PayslipCase(jurisdiction="NRD", pay_period="2027-01", sources={"hr_record": src(**nrd)}),
        "Halvard Ness", "NRD-1203",
        {"reason_code": "NO_APPLICABLE_TABLE", "working": "rule set v1.0 has Nordmark tables for 2025 and 2026 only; a 2026 table must not be used for 2027 (GEN-§4.2)"},
        ("trap", "stale_rate", "no_table"),
        documents={"hr_record": {"employee_id": "NRD-1203", "name": "Halvard Ness"}},
        trap_reason=TrapReason(category="rules_silent", reason_code="NO_APPLICABLE_TABLE", clause="GEN-§9.3",
                               explanation="The rule set has no Nordmark rate table for 2027; using the 2026 table would apply a stale rate."),
    ))
    tasks.append(case_task(
        "seed-t2-08", 2,
        PayslipCase(jurisdiction="NRD", pay_period="2026-12", sources={"hr_record": src(**nrd)}),
        "Halvard Ness", "NRD-1203",
        {"net_pay": "4146", "employee_social_insurance": "350", "income_tax": "668",
         "working": "meal 80 exempt/40 taxable; contributory 5,240 -> ceiling 5,000 -> SI 350; pension 156; "
                    "taxable 4,284 -> tax 360+308.16=668.16 -> 668; gross 5,320; net 5,320-350-156-668=4,146"},
        ("twin", "ceiling_binds", "whole_units"),
        documents={"hr_record": {"employee_id": "NRD-1203", "name": "Halvard Ness"}},
        twin_of="seed-t3-03",
    ))

    # Trap 4: rules silent, the salary currency has no FX rate.
    val_fx = dict(monthly_salary=D(3000), start_date=date(2025, 9, 1))
    tasks.append(case_task(
        "seed-t3-04", 3,
        PayslipCase(jurisdiction="VAL", pay_period="2026-05", sources={"hr_record": src(**val_fx, salary_currency="GBP")}),
        "Petra Lindqvist", "VAL-5077",
        {"reason_code": "UNSUPPORTED_CURRENCY", "working": "FX-§1.1 lists only USD and EUR; GBP->VLD has no rate (GEN-§8.2)"},
        ("trap", "unsupported_currency", "fx"),
        documents={"hr_record": {"employee_id": "VAL-5077", "name": "Petra Lindqvist"}},
        trap_reason=TrapReason(category="rules_silent", reason_code="UNSUPPORTED_CURRENCY", clause="GEN-§9.4",
                               explanation="The salary is in GBP and the FX table has no GBP->VLD rate, so the salary cannot be converted."),
    ))
    tasks.append(case_task(
        "seed-t2-09", 2,
        PayslipCase(jurisdiction="VAL", pay_period="2026-05", sources={"hr_record": src(**val_fx, salary_currency="EUR")}),
        "Petra Lindqvist", "VAL-5077",
        {"net_pay": "7945.75", "earned_salary": "10950.00", "income_tax": "1976.75",
         "working": "EUR->VLD 3.65: 10,950; base 6,000 -> SI 480; pension 547.50; taxable 8,922.50 -> "
                    "tax 200+600+1,176.75=1,976.75; net 10,950-480-547.50-1,976.75=7,945.75"},
        ("twin", "fx", "ceiling_binds"),
        documents={"hr_record": {"employee_id": "VAL-5077", "name": "Petra Lindqvist"}},
        twin_of="seed-t3-04",
    ))
    return tasks


def main() -> None:
    tasks = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("".join(dump_task(t) + "\n" for t in tasks))
    print(f"wrote {len(tasks)} tasks to {OUT}")


if __name__ == "__main__":
    main()
