"""Tool-mode tools (brief Phase 03: "Provide 2-4 real tools… the tools must be the only source of
the reference data the model needs").

Four stateless, idempotent tools:
  get_employee_record(employee_id)            the employee's documents (all sources, as stated)
  lookup_rules(jurisdiction, year)            rule-book text + that year's rate table (or "no table")
  get_fx_rate(from_currency, to_currency, on_date)
  calc(expression)                            exact decimal arithmetic

Each tool takes a hidden ``task_json`` argument that the environment injects per rollout (from
the dataset row) and that is removed from the schema the model sees. A trap and its twin share
an employee id but have different records, so the data must come from the rollout, not a
global lookup. Tools never return ground truth: they return inputs and rules, exactly what
a payroll specialist would look up.

Bad arguments get a structured error string (``{"error": ..., "code": "invalid_argument"}``) so
the model can recover; they are counted by the environment's monitors, not swallowed.
"""

from __future__ import annotations

import ast
import calendar
import json
import operator
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, DivisionByZero, InvalidOperation, localcontext

from paygym.render import ruleset_section
from paygym.ruleset import load_ruleset
from paygym.schema import Task

TOOL_NAMES = ("get_employee_record", "lookup_rules", "get_fx_rate", "calc")
HIDDEN_ARGS = ["task_json"]


def _err(message: str, code: str = "invalid_argument") -> str:
    return json.dumps({"error": message, "code": code})


def _task(task_json: str) -> Task:
    return Task.model_validate_json(task_json)


def get_employee_record(employee_id: str, task_json: str = "") -> str:
    """Return the employee's records exactly as each source document states them.

    Args:
        employee_id: The employee id, e.g. "VAL-1042".
    """
    task = _task(task_json)
    if task.case is None:
        return _err("this task is not about an employee", "not_found")
    if not isinstance(employee_id, str) or employee_id.strip().upper() != (task.employee_id or "").upper():
        return _err(f"no employee with id {employee_id!r}", "not_found")
    docs = {}
    for source, record in task.case.sources.items():
        stated = json.loads(record.model_dump_json(exclude_none=True))
        docs[source] = {**task.documents.get(source, {}), **stated}
    return json.dumps({"employee_id": task.employee_id, "jurisdiction": task.case.jurisdiction,
                       "pay_period": task.case.pay_period, "documents": docs}, indent=2)


def lookup_rules(jurisdiction: str, year: int, task_json: str = "") -> str:
    """Return the rule-set text for a jurisdiction (general + jurisdiction rules) and its rate table for a year.

    Args:
        jurisdiction: "VAL" (Valdoria), "KES" (Kestrel Isles) or "NRD" (Nordmark).
        year: Calendar year of the pay period, e.g. 2026.
    """
    rs = load_ruleset(_task(task_json).ruleset_version)
    code = str(jurisdiction).strip().upper()
    if code not in rs.jurisdictions:
        return _err(f"unknown jurisdiction {jurisdiction!r}; use VAL, KES or NRD")
    try:
        year = int(year)
    except (TypeError, ValueError):
        return _err(f"year must be an integer, got {year!r}")
    table = rs.table(code, year)
    payload = {
        "jurisdiction": code,
        "year": year,
        "rules": ruleset_section("ruleset:GEN") + "\n\n" + ruleset_section(f"ruleset:{code}"),
        "rate_table": json.loads(table.model_dump_json()) if table is not None else None,
    }
    if table is None:
        payload["note"] = f"The rule set has no {code} rate table for {year}."
    return json.dumps(payload, indent=2, default=str)


def get_fx_rate(from_currency: str, to_currency: str, on_date: str, task_json: str = "") -> str:
    """Return the exchange rate (units of to_currency per 1 from_currency) on a date.

    Args:
        from_currency: e.g. "USD".
        to_currency: e.g. "VLD".
        on_date: "YYYY-MM-DD".
    """
    rs = load_ruleset(_task(task_json).ruleset_version)
    try:
        d = date.fromisoformat(str(on_date))
    except ValueError:
        return _err(f"on_date must be YYYY-MM-DD, got {on_date!r}")
    src, dst = str(from_currency).strip().upper(), str(to_currency).strip().upper()
    if d.day != calendar.monthrange(d.year, d.month)[1]:
        return _err("rates are published for the last calendar day of each month only (FX-§1.1)", "no_rate")
    rate = rs.fx_rate(src, dst, d.year)
    if rate is None:
        return json.dumps({"from": src, "to": dst, "date": d.isoformat(), "rate": None,
                           "note": f"no {src}->{dst} rate is published for this date"})
    return json.dumps({"from": src, "to": dst, "date": d.isoformat(), "rate": str(rate)})


# --------------------------------------------------------------------------- calculator

_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCS = {"min": min, "max": max, "abs": abs}
MAX_EXPR_LEN = 500


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return Decimal(str(node.value))
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
        return _BIN[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_eval(node.operand))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS and not node.keywords:
        return _FUNCS[node.func.id](*[_eval(a) for a in node.args])
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "round" and not node.keywords:
        args = [_eval(a) for a in node.args]
        digits = int(args[1]) if len(args) > 1 else 0
        return args[0].quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
    raise ValueError(f"unsupported expression element: {type(node).__name__}")


def calc(expression: str, task_json: str = "") -> str:
    """Evaluate arithmetic exactly (decimal). Supports + - * / ( ) and min, max, abs, round(x, digits) (round is half-up).

    Args:
        expression: e.g. "min(9050, 6000) * 0.08".
    """
    if not isinstance(expression, str) or not expression.strip():
        return _err("expression must be a non-empty string")
    if len(expression) > MAX_EXPR_LEN:
        return _err(f"expression longer than {MAX_EXPR_LEN} characters")
    try:
        tree = ast.parse(expression, mode="eval")
        with localcontext() as ctx:
            ctx.prec = 40
            value = _eval(tree)
    except (SyntaxError, ValueError, TypeError, InvalidOperation, DivisionByZero, ZeroDivisionError) as exc:
        return _err(f"cannot evaluate: {exc}")
    return json.dumps({"expression": expression, "result": format(value, "f")})  # fixed-point, never 6E+3


TOOLS = [get_employee_record, lookup_rules, get_fx_rate, calc]
