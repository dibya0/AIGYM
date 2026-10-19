"""verifiers environment tests (brief Phase 03). Skipped if the `env` extra (verifiers) is not installed."""

import asyncio
import json
from types import SimpleNamespace

import pytest

vf = pytest.importorskip("verifiers")

from paygym.environment import PaygymToolEnv, completion_text, load_environment  # noqa: E402
from paygym.tools import TOOL_NAMES  # noqa: E402


def test_discovered_by_verifiers():
    """`vf.load_environment("paygym")` imports the package and calls paygym.load_environment."""
    env = vf.load_environment("paygym", n_seeds=20)
    assert isinstance(env, vf.Environment)


def test_single_turn_mode():
    env = load_environment(mode="single", n_seeds=20)
    assert isinstance(env, vf.SingleTurnEnv)
    row = env.get_dataset()[0]
    assert row["prompt"][0]["role"] == "system" and "GEN-§1" in row["prompt"][1]["content"]
    assert json.loads(row["info"])["task_json"]


def test_tool_mode_prompt_carries_no_data_and_schema_hides_task_json():
    env = load_environment(mode="tool", n_seeds=30, tier="2,3")
    assert isinstance(env, PaygymToolEnv) and env.max_turns == 8
    names = {d.name for d in env.tool_defs}
    assert names == set(TOOL_NAMES)
    for d in env.tool_defs:
        assert "task_json" not in json.dumps(d.parameters)
    for row in env.get_dataset():
        user = row["prompt"][1]["content"]
        assert "GEN-§" not in user and "monthly_salary" not in user and "start_date" not in user


def test_tool_args_injected_per_rollout():
    env = load_environment(mode="tool", n_seeds=10, tier="2,3")
    info = env.get_dataset()[0]["info"]
    args = env.update_tool_args("get_employee_record", {"employee_id": "X"}, [], {"info": json.loads(info)})
    assert args["employee_id"] == "X" and "task_json" in args


def _state_with_calls(calls):
    steps = [{"completion": [SimpleNamespace(role="assistant", tool_calls=[SimpleNamespace(name=n, arguments=a)])]}
             for n, a in calls]
    return {"trajectory": steps}


def test_tool_loop_detection():
    env = load_environment(mode="tool", n_seeds=5, tier="2,3")
    same = [("calc", '{"expression": "1+1"}')] * 3
    varied = [("calc", '{"expression": "1+1"}'), ("calc", '{"expression": "1+2"}'), ("calc", '{"expression": "1+1"}')]
    assert asyncio.run(env.tool_loop_detected(_state_with_calls(same))) is True
    assert asyncio.run(env.tool_loop_detected(_state_with_calls(varied))) is False


def test_rubric_reward_is_the_paygym_total_and_components_are_metrics():
    env = load_environment(mode="single", n_seeds=20)
    # verifiers wraps our rubric in a RubricGroup with its own MultiTurnMonitorRubric (num_turns, weight 0),
    # so read through the group API, which works for a single Rubric too.
    names, weights, funcs = env.rubric._get_reward_func_names(), env.rubric._get_reward_weights(), env.rubric._get_reward_funcs()
    assert names[0] == "paygym_reward" and weights[0] == 1.0
    assert sum(w for w in weights if w) == 1.0  # the gated total is the only weighted function: monitors cannot shift the reward
    for metric in ("net_pay_exact", "line_accuracy", "trap_decision", "format_valid", "refused", "parse_failed", "tool_errors"):
        i = names.index(metric)
        assert weights[i] == 0.0, metric

    row = env.get_dataset()[0]
    info = json.loads(row["info"])
    state = {}
    reward = funcs[0](completion=[{"role": "assistant", "content": "no json"}], info=info, state=state)
    assert reward == 0.0 and state["paygym_score"].parse_error == "no_json"


def test_completion_text_handles_message_shapes():
    assert completion_text("plain") == "plain"
    assert completion_text([{"role": "assistant", "content": "a"}, {"role": "tool", "content": "t"}]) == "a"
    assert completion_text([SimpleNamespace(role="assistant", content=[{"type": "text", "text": "x"}])]) == "x"


def test_scaffolds_vary_only_the_prompt_and_tools():
    """Track C: same tasks and scorer; S0 has no rule text, S1 has it, S2-S4 are tool mode with growing instructions."""
    from paygym.prompting import SCAFFOLDS

    envs = {s: load_environment(scaffold=s, n_seeds=8, tier="2,3") for s in SCAFFOLDS}
    infos = {s: [r["info"] for r in e.get_dataset()] for s, e in envs.items()}
    assert len({tuple(v) for v in infos.values()}) == 1  # identical tasks across scaffolds
    first = {s: e.get_dataset()[0]["prompt"] for s, e in envs.items()}
    assert "GEN-§1" not in first["S0"][1]["content"] and "GEN-§1" in first["S1"][1]["content"]
    assert isinstance(envs["S2"], PaygymToolEnv) and "Self-check" in first["S3"][0]["content"]
    assert "Checklist" in first["S4"][0]["content"] and "Checklist" not in first["S3"][0]["content"]
