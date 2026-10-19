"""Parser + tool tests (brief Phase 03 edge cases)."""

import importlib.util
import json
from decimal import Decimal as D
from pathlib import Path

from paygym.parser import parse_answer, parse_number
from paygym.tools import calc, get_employee_record, get_fx_rate, lookup_rules

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("seed", ROOT / "scripts" / "build_seed_tasks.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
SEED = {t.id: t for t in _mod.build()}


def _payslip_json(**lines):
    return "Working...\n```json\n" + json.dumps({"decision": "answer", "reason_code": None, "lines": lines, "explanation": "x"}) + "\n```"


# ---------------------------------------------------------------- parser


def test_parses_well_formed_payslip():
    p = parse_answer(_payslip_json(net_pay=6934.0, income_tax=1436), "payslip")
    assert p.ok and p.decision == "answer" and p.lines["net_pay"] == D("6934.0")


def test_last_json_block_wins_and_think_is_ignored():
    text = "<think>```json {\"decision\": \"refuse\"} ```</think> draft ```json {\"decision\":\"refuse\",\"reason_code\":\"MISSING_INPUT\"}```"
    p = parse_answer(text, "refusal")
    assert p.ok and p.decision == "refuse" and p.reason_code == "MISSING_INPUT"


def test_malformed_and_truncated_json_are_named_errors():
    assert parse_answer("no json here", "payslip").error == "no_json"
    assert parse_answer('```json\n{"decision": "answer", "lines": {"net_pay": 1', "payslip").error == "truncated"
    assert parse_answer('```json\n{"decision": answer}\n```', "payslip").error == "invalid_json"
    assert parse_answer('```json\n[1, 2]\n```', "payslip").error == "not_an_object"


def test_trailing_comma_is_tolerated():
    p = parse_answer('```json\n{"decision": "answer", "value": 6000,}\n```', "value")
    assert p.ok and p.value == D(6000)


def test_bad_decision_and_missing_lines():
    assert parse_answer('```json\n{"decision": "maybe"}\n```', "payslip").error == "bad_decision"
    assert parse_answer('```json\n{"decision": "answer", "lines": {}}\n```', "payslip").error == "missing_lines"


def test_unknown_reason_code_is_still_a_refusal():
    p = parse_answer('```json\n{"decision": "refuse", "reason_code": "I_DONT_KNOW"}\n```', "refusal")
    assert p.decision == "refuse" and p.error == "bad_reason_code"


def test_number_normalisation():
    assert parse_number(1234.5) == (D("1234.5"), False)
    assert parse_number("1,234.50")[0] == D("1234.50")
    assert parse_number("1.234,50")[0] == D("1234.50")
    assert parse_number("1234,5")[0] == D("1234.5")
    assert parse_number("VLD 6000")[0] == D(6000)
    assert parse_number("8%")[0] == D("0.08")
    assert parse_number("abc")[0] is None and parse_number(True)[0] is None


# ---------------------------------------------------------------- tools


def test_employee_record_comes_from_this_rollouts_task():
    """A trap and its twin share an employee id but have different records."""
    trap, twin = SEED["seed-t3-02"], SEED["seed-t2-07"]
    trap_rec = json.loads(get_employee_record("VAL-4120", task_json=trap.model_dump_json()))
    twin_rec = json.loads(get_employee_record("VAL-4120", task_json=twin.model_dump_json()))
    assert trap_rec["documents"]["contract"]["start_date"] == "2026-03-16"
    assert twin_rec["documents"]["contract"]["start_date"] == "2026-03-09"


def test_employee_record_never_contains_ground_truth():
    task = SEED["seed-t2-01"]
    rec = get_employee_record("VAL-1042", task_json=task.model_dump_json())
    for line in ("net_pay", "income_tax", "employee_social_insurance"):
        assert f"{task.ground_truth.lines[line]:.2f}" not in rec
    assert "ground_truth" not in rec and "hand_check" not in rec


def test_wrong_employee_id_is_a_structured_error():
    out = json.loads(get_employee_record("VAL-9999", task_json=SEED["seed-t2-01"].model_dump_json()))
    assert out["code"] == "not_found"


def test_lookup_rules_and_missing_table():
    tj = SEED["seed-t2-01"].model_dump_json()
    ok = json.loads(lookup_rules("VAL", 2026, task_json=tj))
    assert ok["rate_table"]["si_ceiling"]["value"] == "6000.00" and "VAL-§2.1" in ok["rules"]
    none = json.loads(lookup_rules("NRD", 2027, task_json=tj))
    assert none["rate_table"] is None and "no NRD rate table" in none["note"]
    assert json.loads(lookup_rules("XYZ", 2026, task_json=tj))["code"] == "invalid_argument"
    assert json.loads(lookup_rules("VAL", "next year", task_json=tj))["code"] == "invalid_argument"


def test_fx_rate_tool():
    tj = SEED["seed-t2-01"].model_dump_json()
    assert json.loads(get_fx_rate("USD", "VLD", "2026-04-30", task_json=tj))["rate"] == "3.4000"
    assert json.loads(get_fx_rate("GBP", "VLD", "2026-04-30", task_json=tj))["rate"] is None
    assert json.loads(get_fx_rate("USD", "VLD", "2026-04-15", task_json=tj))["code"] == "no_rate"
    assert json.loads(get_fx_rate("USD", "VLD", "30/04/2026", task_json=tj))["code"] == "invalid_argument"


def test_calc_is_exact_and_safe():
    assert json.loads(calc("min(9050, 6000) * 0.08"))["result"] == "480.00"
    assert json.loads(calc("5000 * 21 / 31"))["result"].startswith("3387.0967741935")
    assert json.loads(calc("round(253.2, 0)"))["result"] == "253"
    assert json.loads(calc("6000"))["result"] == "6000"
    for bad in ("__import__('os')", "2 ** 999999", "1/0", "x + 1", "", "1" * 600):
        assert "error" in json.loads(calc(bad)), bad
