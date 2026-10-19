"""Turns a structured case into what the agent sees: documents and a question.

Formatting knobs (date convention, number format, annual vs monthly salary) exist because
format ambiguity is a real source of payroll error (brief p.7). Whatever convention is used
is always stated in the prompt (RULESET GEN-§2.4–§2.6), so the task is never ambiguous.
"""

from __future__ import annotations

import calendar
import json
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from paygym.reference.inputs import PayslipCase, SourceRecord
from paygym.ruleset import ruleset_dir

JURISDICTION_NAMES = {"VAL": "Valdoria", "KES": "Kestrel Isles", "NRD": "Nordmark"}
LOCAL_CURRENCY = {"VAL": "VLD", "KES": "KSD", "NRD": "NMK"}
SOURCE_TITLES = {
    "hr_record": "HR record",
    "contract": "Employment contract (excerpt)",
    "payroll_note": "Payroll team note",
}


@dataclass(frozen=True)
class Style:
    date_format: str = "iso"  # "iso" (YYYY-MM-DD), "dmy" (DD/MM/YYYY), "mdy" (MM/DD/YYYY)
    number_format: str = "plain"  # "plain" 1000.50, "comma_dot" 1,000.50, "dot_comma" 1.000,50
    annual_salary: bool = False  # state the salary as an annual figure (GEN-§2.6)

    def conventions_note(self) -> str:
        parts = []
        if self.date_format == "dmy":
            parts.append("dates are written DD/MM/YYYY")
        elif self.date_format == "mdy":
            parts.append("dates are written MM/DD/YYYY")
        if self.number_format == "comma_dot":
            parts.append("amounts use ',' for thousands and '.' for decimals (e.g. 1,000.50)")
        elif self.number_format == "dot_comma":
            parts.append("amounts use '.' for thousands and ',' for decimals (e.g. 1.000,50)")
        return ("Formats: " + "; ".join(parts) + ".") if parts else ""


def fmt_date(d: date, style: Style) -> str:
    if style.date_format == "dmy":
        return d.strftime("%d/%m/%Y")
    if style.date_format == "mdy":
        return d.strftime("%m/%d/%Y")
    return d.isoformat()


def fmt_amount(x: Decimal, style: Style) -> str:
    x = x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    plain = f"{x:.2f}"
    if style.number_format == "plain":
        return plain
    grouped = f"{x:,.2f}"  # 1,000.50
    if style.number_format == "comma_dot":
        return grouped
    return grouped.replace(",", "_").replace(".", ",").replace("_", ".")  # 1.000,50


def period_label(pay_period: str) -> str:
    year, month = int(pay_period[:4]), int(pay_period[5:])
    return f"{calendar.month_name[month]} {year}"


def _salary_text(src: SourceRecord, style: Style) -> tuple[str, str] | None:
    if src.monthly_salary is None:
        return None
    if style.annual_salary:
        return "annual_salary", fmt_amount(src.monthly_salary * 12, style)
    return "monthly_salary", fmt_amount(src.monthly_salary, style)


def render_kv(src: SourceRecord, extras: dict[str, str], local: str, style: Style) -> str:
    """Render a source as a structured record (key/value JSON)."""
    out: dict[str, object] = dict(extras)
    salary = _salary_text(src, style)
    if salary:
        out[salary[0]] = salary[1]
    if src.salary_currency is not None:
        out["salary_currency"] = src.salary_currency
    if src.start_date is not None:
        out["start_date"] = fmt_date(src.start_date, style)
    if src.end_date is not None:
        out["end_date"] = fmt_date(src.end_date, style)
    if src.salary_change is not None:
        out["salary_change"] = {
            "effective_date": fmt_date(src.salary_change.effective_date, style),
            ("new_annual_salary" if style.annual_salary else "new_monthly_salary"): fmt_amount(
                src.salary_change.monthly_salary * (12 if style.annual_salary else 1), style
            ),
        }
    if src.allowances is not None:
        out["monthly_allowances"] = [{"type": a.type, "amount": fmt_amount(a.amount, style), "currency": local} for a in src.allowances]
    if src.retro_pay is not None:
        out["retro_pay"] = {"amount": fmt_amount(src.retro_pay, style), "currency": local}
    if src.tax_residency is not None:
        out["tax_residency"] = src.tax_residency
    if src.ytd_contributory_earnings is not None:
        out["ytd_contributory_earnings"] = {"amount": fmt_amount(src.ytd_contributory_earnings, style), "currency": local}
    return json.dumps(out, indent=2, ensure_ascii=False)


def render_prose(src: SourceRecord, extras: dict[str, str], local: str, jurisdiction: str, style: Style) -> str:
    """Render a source as contract-style prose."""
    s: list[str] = [f"{k.replace('_', ' ').capitalize()}: {v}." for k, v in extras.items()]
    if src.monthly_salary is not None:
        cur = src.salary_currency or "(currency not stated)"
        if style.annual_salary:
            s.append(f"The employee's gross salary is {cur} {fmt_amount(src.monthly_salary * 12, style)} per year.")
        else:
            s.append(f"The employee's gross salary is {cur} {fmt_amount(src.monthly_salary, style)} per month.")
    elif src.salary_currency is not None:
        s.append(f"Salary is paid in {src.salary_currency}.")
    if src.start_date is not None:
        s.append(f"Employment commences on {fmt_date(src.start_date, style)}.")
    if src.end_date is not None:
        s.append(f"Employment ends on {fmt_date(src.end_date, style)}.")
    if src.salary_change is not None:
        amount = src.salary_change.monthly_salary * (12 if style.annual_salary else 1)
        per = "per year" if style.annual_salary else "per month"
        s.append(f"From {fmt_date(src.salary_change.effective_date, style)} the salary changes to {src.salary_currency or ''} {fmt_amount(amount, style)} {per}.".replace("  ", " "))
    for a in src.allowances or ():
        s.append(f"The employee receives a monthly {a.type} allowance of {local} {fmt_amount(a.amount, style)}.")
    if src.retro_pay is not None:
        s.append(f"Back pay of {local} {fmt_amount(src.retro_pay, style)} for an earlier period is paid this month.")
    if src.tax_residency is not None:
        status = "resident" if src.tax_residency == "resident" else "non-resident"
        s.append(f"For tax purposes the employee is {status} in {JURISDICTION_NAMES[jurisdiction]}.")
    if src.ytd_contributory_earnings is not None:
        s.append(f"Contributory earnings paid earlier this calendar year total {local} {fmt_amount(src.ytd_contributory_earnings, style)}.")
    return " ".join(s)


def render_documents(case: PayslipCase, documents: dict[str, dict[str, str]], style: Style) -> str:
    local = LOCAL_CURRENCY[case.jurisdiction]
    blocks = []
    for name, src in case.sources.items():
        extras = documents.get(name, {})
        title = SOURCE_TITLES.get(name, name.replace("_", " ").capitalize())
        body = render_kv(src, extras, local, style) if name == "hr_record" else render_prose(src, extras, local, case.jurisdiction, style)
        blocks.append(f"--- {title} ---\n{body}")
    return "\n\n".join(blocks)


def payslip_prompt(case: PayslipCase, documents: dict[str, dict[str, str]], employee_name: str, employee_id: str, style: Style) -> str:
    head = (
        f"Compute the payslip for {employee_name} ({employee_id}), employed in {JURISDICTION_NAMES[case.jurisdiction]}, "
        f"for the pay period {period_label(case.pay_period)} ({case.pay_period}), under the PayGym payroll rule set v1.0. "
        "If the rule set does not determine the payslip, refuse and say why instead of computing it."
    )
    note = style.conventions_note()
    parts = [head] + ([note] if note else []) + ["The employee's documents:", render_documents(case, documents, style)]
    return "\n\n".join(parts)


LOOKUP_LABELS = {
    "personal_allowance": "personal allowance",
    "si_employee_rate": "employee social insurance rate",
    "si_employer_rate": "employer social insurance rate",
    "si_ceiling": "social insurance wage ceiling",
    "pension_rate": "employee pension rate",
    "meal_exemption": "monthly meal-allowance exemption",
    "non_resident_rate": "non-resident flat income tax rate",
}


def lookup_prompt(jurisdiction: str, year: int, field: str) -> str:
    name = JURISDICTION_NAMES[jurisdiction]
    if field.startswith("fx:"):
        what = f"exchange rate from {field[3:]} to {LOCAL_CURRENCY[jurisdiction]} (local currency units per 1 {field[3:]})"
    else:
        what = f"{LOOKUP_LABELS[field]}"
    rate_hint = " Give rates as decimals (e.g. 0.08 for 8%)." if field.endswith("_rate") else ""
    return (
        f"Using the attached PayGym payroll rule set v1.0, what is the {what} in {name} for pay periods in {year}? "
        f"Answer with the number only.{rate_hint}"
    )


# --------------------------------------------------------------------------- rule-set sections


def ruleset_section(ref: str, version: str = "1.0") -> str:
    """Resolve a context-file reference like ``ruleset:VAL`` to that section of RULESET.md."""
    kind, _, key = ref.partition(":")
    if kind != "ruleset":
        raise ValueError(f"unknown context file reference {ref!r}")
    text = (ruleset_dir(version) / "RULESET.md").read_text()
    head = text.split("## Part A")[0].strip()
    if key == "GEN":
        return head + "\n\n## Part A" + text.split("## Part A")[1].split("## Part B")[0].rstrip()
    marker = f"### {key}:"
    if marker not in text:
        raise ValueError(f"no section {key!r} in RULESET.md")
    return marker + text.split(marker)[1].split("\n### ")[0].split("\n---")[0].rstrip()


def context_for(jurisdiction: str) -> tuple[str, ...]:
    return ("ruleset:GEN", f"ruleset:{jurisdiction}", "ruleset:FX")
