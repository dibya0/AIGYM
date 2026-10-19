"""Rubric tests (brief Phase 04): score levels, gating, clause provenance, and the adversarial baselines."""

import importlib.util
import json
from decimal import Decimal as D
from pathlib import Path

import pytest

from paygym.baselines import BASELINES, FLOORS
from paygym.generator import generate_split
from paygym.rubric import score_answer
from paygym.training_reward import rubric_reward

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("seed", ROOT / "scripts" / "build_seed_tasks.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
SEED = {t.id: t for t in _mod.build()}
EVAL = generate_split("eval", 160)


def perfect(task) -> str:
    gt = task.ground_truth
    if gt.kind == "value":
        obj = {"decision": "answer", "value": float(gt.value)}
    elif gt.kind == "refusal":
        obj = {"decision": "refuse", "reason_code": gt.reason_code, "lines": None, "explanation": "x"}
    else:
        obj = {"decision": "answer", "reason_code": None, "lines": {k: float(v) for k, v in gt.lines.items()}, "explanation": "x"}
    return "```json\n" + json.dumps(obj) + "\n```"


def answer_with(task, **overrides) -> str:
    lines = {k: float(v) for k, v in task.ground_truth.lines.items()}
    lines.update(overrides)
    return "```json\n" + json.dumps({"decision": "answer", "lines": lines, "explanation": "x"}) + "\n```"


# ---------------------------------------------------------------- score levels


@pytest.mark.parametrize("task", list(SEED.values()) + EVAL[:60], ids=lambda t: t.id)
def test_reference_answer_gets_top_score(task):
    expected = 0.8 if task.ground_truth.kind == "refusal" else 1.0  # traps: 0.8 without a judge
    assert score_answer(task, perfect(task)).total == pytest.approx(expected)


def test_tolerance_is_one_minor_unit_from_the_rule_set():
    t = SEED["seed-t2-01"]  # VAL: 0.01 (GEN-§1.4)
    net = float(t.ground_truth.lines["net_pay"])
    assert score_answer(t, answer_with(t, net_pay=net + 0.01)).breakdown()["net_pay_exact"] == 1.0
    assert score_answer(t, answer_with(t, net_pay=net + 0.02)).breakdown()["net_pay_exact"] == 0.0
    n = SEED["seed-t2-04"]  # NRD: whole krone
    assert score_answer(n, answer_with(n, net_pay=float(n.ground_truth.lines["net_pay"]) + 1)).breakdown()["net_pay_exact"] == 1.0


def test_wrong_net_is_capped_at_floor_whatever_else_is_right():
    t = SEED["seed-t2-01"]
    s = score_answer(t, answer_with(t, net_pay=1.0))  # 9 of 10 lines right
    assert s.total <= 0.25 and s.gate == "wrong_net_capped"


def test_net_right_but_lines_wrong_is_partial_not_full():
    t = SEED["seed-t2-01"]
    s = score_answer(t, answer_with(t, income_tax=0.0, employee_pension=0.0))
    assert 0.75 <= s.total < 1.0


def test_refusing_a_determinable_payslip_scores_like_a_wrong_answer():
    t = SEED["seed-t2-07"]  # twin
    refusal = "```json\n" + json.dumps({"decision": "refuse", "reason_code": "CONFLICTING_RECORDS", "lines": None}) + "\n```"
    s = score_answer(t, refusal)
    assert s.gate == "refused_determinable" and s.total == pytest.approx(0.05)
    assert s.total <= score_answer(t, answer_with(t, net_pay=1.0)).total


def test_answering_a_trap_is_negative_never_partial():
    trap, twin = SEED["seed-t3-02"], SEED["seed-t2-07"]
    s = score_answer(trap, perfect(twin))  # a perfectly computed payslip, for a case the rules leave undetermined
    assert s.total == -1.0 and s.gate == "answered_trap"


def test_trap_refused_for_the_wrong_reason_is_partial():
    t = SEED["seed-t3-01"]
    wrong = "```json\n" + json.dumps({"decision": "refuse", "reason_code": "NO_APPLICABLE_TABLE"}) + "\n```"
    assert score_answer(t, wrong).total == pytest.approx(0.3)


def test_judge_adds_up_to_point_two_and_failures_are_not_silent():
    t = SEED["seed-t3-01"]
    assert score_answer(t, perfect(t), judge=lambda task, parsed: (1.0, "ok")).total == pytest.approx(1.0)
    assert score_answer(t, perfect(t), judge=lambda task, parsed: (0.5, "meh")).total == pytest.approx(0.9)

    def broken(task, parsed):
        raise RuntimeError("judge API down")

    with pytest.raises(RuntimeError):
        score_answer(t, perfect(t), judge=broken)


def test_unparseable_scores_zero():
    for t in (SEED["seed-t2-01"], SEED["seed-t3-01"], SEED["seed-t1-01"]):
        s = score_answer(t, "I think the answer is about 7000.")
        assert s.total == 0.0 and s.parse_error == "no_json"


def test_retrieval_is_exact():
    t = SEED["seed-t1-01"]
    ok = "```json\n{\"decision\": \"answer\", \"value\": 6000}\n```"
    off = "```json\n{\"decision\": \"answer\", \"value\": 6000.01}\n```"
    assert score_answer(t, ok).total == pytest.approx(1.0)
    assert score_answer(t, off).total == pytest.approx(0.05)


# ---------------------------------------------------------------- clause provenance (brief p.10)


@pytest.mark.parametrize("name", list(BASELINES))
def test_every_component_names_its_clauses(name):
    for task in EVAL[:40]:
        s = score_answer(task, BASELINES[name](task))
        assert s.driving_clauses, (name, task.id)
        for comp in s.components:
            assert comp.clauses, (name, task.id, comp.name)


def test_ignoring_the_ceiling_is_traced_to_the_ceiling_clause():
    t = SEED["seed-t2-01"]  # ceiling binds
    s = score_answer(t, BASELINES["naive_no_ceiling"](t))
    assert s.gate == "wrong_net_capped"
    assert s.extra["first_wrong_line"] == "employee_social_insurance"
    assert "VAL-§2.1" in s.driving_clauses


# ---------------------------------------------------------------- adversarial baselines (attack the reward)


@pytest.mark.parametrize("name", list(BASELINES))
def test_baseline_stays_under_its_floor(name):
    scores = [score_answer(t, BASELINES[name](t)).total for t in EVAL]
    mean = sum(scores) / len(scores)
    assert mean < FLOORS[name], f"{name}: mean reward {mean:.3f} >= floor {FLOORS[name]}"


def test_baselines_never_beat_the_reference():
    ref = sum(score_answer(t, perfect(t)).total for t in EVAL) / len(EVAL)
    for name, fn in BASELINES.items():
        mean = sum(score_answer(t, fn(t)).total for t in EVAL) / len(EVAL)
        assert mean < ref - 0.4, (name, mean, ref)


# ---------------------------------------------------------------- training adapter


def test_training_reward_matches_rubric_and_logs_monitors():
    tasks = [SEED["seed-t3-02"], SEED["seed-t2-07"], SEED["seed-t2-01"]]
    completions = [[{"role": "assistant", "content": perfect(SEED["seed-t2-07"])}],  # answers the trap
                   [{"role": "assistant", "content": BASELINES["always_abstain"](tasks[1])}],  # refuses the twin
                   [{"role": "assistant", "content": perfect(tasks[2])}]]
    logged = {}
    infos = [json.dumps({"task_json": t.model_dump_json()}) for t in tasks]  # the environment's info column
    rewards = rubric_reward(completions, infos, log_metric=lambda k, v: logged.__setitem__(k, v))
    assert rewards == pytest.approx([-1.0, 0.05, 1.0])
    assert logged["monitor/trap_answer_rate"] == 1.0
    assert logged["monitor/twin_refusal_rate"] == 1.0
    assert logged["monitor/pass_rate_tier2"] == pytest.approx(0.5)
