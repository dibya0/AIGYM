"""Parser for the output contract in ``paygym.prompting.SYSTEM_PROMPT`` (brief Phase 03).

We own the parser, so scoring never relies on regex archaeology over prose. Every failure
has a named error code, and the rubric records it rather than silently scoring a crash as 0.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from paygym.reference.calculator import LINES

REASON_CODES = ("MISSING_INPUT", "CONFLICTING_RECORDS", "NO_APPLICABLE_TABLE", "UNSUPPORTED_CURRENCY")

_FENCED = re.compile(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", re.DOTALL | re.IGNORECASE)
_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_TRAILING_COMMA = re.compile(r",\s*([}\]])")


@dataclass
class ParsedAnswer:
    ok: bool  # a usable answer object was found and passed the contract checks
    error: str | None = None  # no_json | truncated | invalid_json | not_an_object | bad_decision | bad_reason_code | missing_lines | bad_value
    decision: str | None = None  # "answer" | "refuse"
    reason_code: str | None = None
    lines: dict[str, Decimal] = field(default_factory=dict)  # parsed numeric lines (may be partial)
    value: Decimal | None = None
    explanation: str = ""
    raw: dict | None = None
    normalised_numbers: bool = False  # numbers arrived as strings with separators and were converted


def parse_number(x) -> tuple[Decimal | None, bool]:
    """Parse a JSON number or a numeric string. Returns (value, was_normalised)."""
    if isinstance(x, bool) or x is None:
        return None, False
    if isinstance(x, (int, float)):
        return Decimal(str(x)), False
    if not isinstance(x, str):
        return None, False
    s = x.strip().replace(" ", "").replace(" ", "")
    s = re.sub(r"^[A-Za-z]{3}", "", s)  # leading currency code, e.g. "VLD1234.50"
    percent = s.endswith("%")
    s = s.rstrip("%")
    if "," in s and "." in s:  # whichever separator comes last is the decimal mark
        s = s.replace(",", "") if s.rfind(".") > s.rfind(",") else s.replace(".", "").replace(",", ".")
    elif "," in s:
        head, _, tail = s.rpartition(",")
        s = s.replace(",", "") if len(tail) == 3 else head.replace(",", "") + "." + tail
    try:
        value = Decimal(s)
    except InvalidOperation:
        return None, False
    return (value / 100 if percent else value), True


def _extract_object(text: str) -> tuple[dict | None, str | None]:
    text = _THINK.sub("", text or "")
    blocks = _FENCED.findall(text)
    candidate = blocks[-1] if blocks else None
    if candidate is None:
        if "```json" in text.lower() or text.rstrip().endswith(("{", ",", ":")):
            return None, "truncated"
        start = text.rfind("{")  # tolerate a bare object at the end
        if start == -1:
            return None, "no_json"
        candidate = text[start:]
        if candidate.count("{") > candidate.count("}"):
            return None, "truncated"
    for attempt in (candidate, _TRAILING_COMMA.sub(r"\1", candidate)):
        try:
            obj = json.loads(attempt)
        except json.JSONDecodeError:
            continue
        return (obj, None) if isinstance(obj, dict) else (None, "not_an_object")
    return None, "invalid_json"


def parse_answer(text: str, kind: str) -> ParsedAnswer:
    """Parse a completion for a task whose ground truth is ``kind`` ("value", "payslip" or "refusal")."""
    obj, error = _extract_object(text)
    if obj is None:
        return ParsedAnswer(ok=False, error=error)
    out = ParsedAnswer(ok=True, raw=obj, explanation=str(obj.get("explanation") or "")[:2000])
    decision = str(obj.get("decision", "")).strip().lower()
    if decision in ("refuse", "refusal", "abstain"):
        decision = "refuse"
    if decision not in ("answer", "refuse"):
        out.ok, out.error = False, "bad_decision"
        return out
    out.decision = decision

    if decision == "refuse":
        code = str(obj.get("reason_code") or "").strip().upper()
        out.reason_code = code or None
        if code not in REASON_CODES:
            out.error = "bad_reason_code"  # still a refusal; the rubric decides how much that is worth
        return out

    if kind == "value":
        value, normalised = parse_number(obj.get("value"))
        out.value, out.normalised_numbers = value, normalised
        if value is None:
            out.ok, out.error = False, "bad_value"
        return out

    lines = obj.get("lines")
    if not isinstance(lines, dict):
        out.ok, out.error = False, "missing_lines"
        return out
    for name in LINES:
        value, normalised = parse_number(lines.get(name))
        if value is not None:
            out.lines[name] = value
            out.normalised_numbers |= normalised
    if "net_pay" not in out.lines:
        out.ok, out.error = False, "missing_lines"
    return out
