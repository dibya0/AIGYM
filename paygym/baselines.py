"""Adversarial baselines: cheap strategies a reward-hacking policy could find (brief p.11–12).

Each produces a completion string for a task without any model. They sit on the leaderboard
next to real models (brief P06), and ``FLOORS`` states the mean reward each must stay under on a
representative taskset; ``tests/test_rubric.py`` enforces the floors.

  format_only       valid JSON, every line 0           -> tests that format alone is worth ~nothing
  always_abstain    refuse every task                   -> tests that refusing is not a safe harbour
  modal_answer      one fixed plausible payslip always  -> tests that a constant answer is not rewarded
  naive_no_ceiling  correct arithmetic except it ignores the contribution ceiling and never refuses
                    (fills missing inputs, takes the first source, uses the nearest year's table,
                    treats unknown currencies as local): the brief's named failure (p.5)
  gross_as_net      reports gross pay as net pay        -> tests that "no deductions" is caught
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Callable

from paygym.reference import Payslip, PayslipCase, SourceRecord, compute_payslip
from paygym.reference.calculator import LINES
from paygym.ruleset import Ruleset, load_ruleset
from paygym.schema import Task

# Mean reward each baseline must stay under (on a set with the default tier mix).
FLOORS: dict[str, float] = {
    "format_only": 0.10,
    "always_abstain": 0.20,
    "modal_answer": 0.10,
    "naive_no_ceiling": 0.35,
    "gross_as_net": 0.10,
}


def _wrap(obj: dict) -> str:
    return "```json\n" + json.dumps(obj, default=str) + "\n```"


def _answer(lines: dict[str, Decimal]) -> str:
    return _wrap({"decision": "answer", "reason_code": None,
                  "lines": {k: float(v) for k, v in lines.items()}, "explanation": "computed"})


def format_only(task: Task) -> str:
    if task.lookup is not None:
        return _wrap({"decision": "answer", "value": 0})
    return _answer({name: Decimal(0) for name in LINES})


def always_abstain(task: Task) -> str:
    return _wrap({"decision": "refuse", "reason_code": "MISSING_INPUT", "lines": None,
                  "explanation": "Not enough information."})


MODAL_LINES = {"earned_salary": Decimal(6000), "retro_pay": Decimal(0), "taxable_allowances": Decimal(0),
               "non_taxable_allowances": Decimal(0), "gross_pay": Decimal(6000),
               "employee_social_insurance": Decimal(480), "employee_pension": Decimal(300),
               "income_tax": Decimal(900), "net_pay": Decimal(4320), "employer_social_insurance": Decimal(720)}


def modal_answer(task: Task) -> str:
    if task.lookup is not None:
        return _wrap({"decision": "answer", "value": 6000})
    return _answer(MODAL_LINES)


_NO_CEILING: dict[str, Ruleset] = {}


def _no_ceiling_ruleset(rs: Ruleset) -> Ruleset:
    if rs.fingerprint in _NO_CEILING:
        return _NO_CEILING[rs.fingerprint]
    data = rs.model_dump()
    for jur in data["jurisdictions"].values():
        for table in jur["tables"].values():
            table["si_ceiling"]["value"] = Decimal("1e12")
    _NO_CEILING[rs.fingerprint] = Ruleset.model_validate(data)
    return _NO_CEILING[rs.fingerprint]


def _force_determinable(task: Task, rs: Ruleset) -> PayslipCase:
    """What a model that never refuses does: guess past every gap the rules leave open."""
    case = task.case
    jur = rs.jurisdictions[case.jurisdiction]
    merged: dict = {}
    for record in case.sources.values():  # first source wins on conflicts
        for key, value in record.model_dump(exclude_none=True).items():
            merged.setdefault(key, value)
    merged.setdefault("salary_currency", jur.currency)
    merged.setdefault("start_date", f"{case.year - 1}-01-01")
    merged.setdefault("tax_residency", "resident")
    merged.setdefault("ytd_contributory_earnings", Decimal(0))
    year = min(max(case.year, min(jur.tables)), max(jur.tables))  # nearest year that has a table
    if merged["salary_currency"] != jur.currency and rs.fx_rate(merged["salary_currency"], jur.currency, year) is None:
        merged["salary_currency"] = jur.currency  # treat an unknown currency as local
    period = f"{year}-{case.pay_period[5:]}"
    return PayslipCase(jurisdiction=case.jurisdiction, pay_period=period, sources={"merged": SourceRecord(**merged)})


def _naive_payslip(task: Task, ceiling: bool) -> Payslip:
    rs = load_ruleset(task.ruleset_version)
    result = compute_payslip(_force_determinable(task, rs), rs if ceiling else _no_ceiling_ruleset(rs))
    assert isinstance(result, Payslip), result
    return result


def naive_no_ceiling(task: Task) -> str:
    if task.lookup is not None:
        return modal_answer(task)
    return _answer(_naive_payslip(task, ceiling=False).lines)


def gross_as_net(task: Task) -> str:
    if task.lookup is not None:
        return modal_answer(task)
    lines = dict(_naive_payslip(task, ceiling=True).lines)
    for name in ("employee_social_insurance", "employee_pension", "income_tax"):
        lines[name] = Decimal(0)
    lines["net_pay"] = lines["gross_pay"]
    return _answer(lines)


BASELINES: dict[str, Callable[[Task], str]] = {
    "format_only": format_only,
    "always_abstain": always_abstain,
    "modal_answer": modal_answer,
    "naive_no_ceiling": naive_no_ceiling,
    "gross_as_net": gross_as_net,
}
