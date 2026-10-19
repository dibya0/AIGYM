"""Eval harness tests (brief Phase 05), with no network: adversarial baselines run for real, and model
rollouts are replaced by a fake ``env.run_rollout`` to exercise cost caps, retries, outages and resume."""

import asyncio
import json

import pytest

pytest.importorskip("verifiers")

from paygym.eval import leaderboard  # noqa: E402
from paygym.eval.runner import EvalRun, build_parser, main  # noqa: E402
from paygym.eval.stats import bootstrap_mean_ci, paired_bootstrap, run_summary  # noqa: E402


def _args(tmp_path, *extra):
    return build_parser().parse_args(["--n-seeds", "12", "--rollouts", "2", "--out", str(tmp_path), "--run-name", "r", *extra])


def _files(run_dir):
    return {p.name for p in run_dir.iterdir()}


def test_baseline_run_writes_the_four_files(tmp_path):
    assert main(["--model", "baseline/naive_no_ceiling", "--n-seeds", "12", "--rollouts", "2",
                 "--out", str(tmp_path), "--run-name", "r"]) == 0
    run_dir = tmp_path / "baseline__naive_no_ceiling" / "r"
    assert {"config.json", "transcript.jsonl", "metrics.json", "scores.json"} <= _files(run_dir)
    cfg = json.loads((run_dir / "config.json").read_text())
    for key in ("model", "seed", "taskset_hash", "ruleset_version", "ruleset_fingerprint", "prompt_hash", "task_seeds", "schema_version"):
        assert key in cfg, key
    scores = json.loads((run_dir / "scores.json").read_text())
    assert scores["summary"]["tasks"] > 0 and "net_pay_exact" in scores["by_component"]
    metrics = json.loads((run_dir / "metrics.json").read_text())
    assert metrics["status"] == "completed" and metrics["cost_actual_usd"] == 0.0
    for name in ("scores.json", "metrics.json"):  # brief: seed + rule-set version "recorded in every result file"
        stamped = json.loads((run_dir / name).read_text())
        assert {"seed", "task_seeds", "ruleset_version", "ruleset_fingerprint"} <= set(stamped), name
    first = json.loads((run_dir / "transcript.jsonl").read_text().splitlines()[0])
    assert {"seed", "task_seed", "ruleset_version"} <= set(first)


class FakeEnvRollouts:
    """Stands in for env.run_rollout: returns verifiers-shaped outputs, optionally failing."""

    def __init__(self, script):
        self.script = list(script)  # each item: "ok" | "transient" | "fatal"
        self.calls = 0

    async def __call__(self, rollout_input, client, model, sampling):
        self.calls += 1
        kind = self.script.pop(0) if self.script else "ok"
        if kind == "transient":
            return {"error": {"error": "RateLimitError", "message": "429 Too Many Requests"}}
        if kind == "fatal":
            return {"error": {"error": "ModelError", "message": "model not found"}}
        if kind == "empty_timeout":
            return {"reward": -1.0, "metrics": {}, "completion": [], "token_usage": {"input_tokens": 10, "output_tokens": 0},
                    "timing": {}, "stop_condition": "timeout_reached"}
        return {"reward": 0.5, "metrics": {"net_pay_exact": 0.0, "total_tool_calls": 0},
                "completion": [{"role": "assistant", "content": "no json"}],
                "token_usage": {"input_tokens": 1_000_000, "output_tokens": 0},
                "timing": {"model": {"duration": 1.5}}, "stop_condition": "max_turns_reached"}


def _model_run(tmp_path, monkeypatch, script, *extra):
    monkeypatch.setenv("GROQ_API_KEY", "test")
    from paygym.eval import budget

    # The fakes report 1M tokens per rollout (to exercise the cost cap), which the real Groq daily token cap
    # would stop at once; these tests are about the runner, so give the model generous request-only limits.
    monkeypatch.setitem(budget.FREE_TIER_LIMITS, "groq/openai/gpt-oss-120b", {"rpd": 1_000_000})
    args = _args(tmp_path, "--model", "groq/openai/gpt-oss-120b", "--rpm", "0", "--tpm", "0", "--concurrency", "1", *extra)
    run = EvalRun(args)
    fake = FakeEnvRollouts(script)
    run.env.run_rollout = fake
    return run, fake, asyncio.run(run.run())


def test_cost_cap_aborts_cleanly_with_partial_results(tmp_path, monkeypatch):
    # gpt-oss-120b list price $0.15 / M input tokens; each fake rollout uses 1M input tokens.
    run, fake, code = _model_run(tmp_path, monkeypatch, [], "--max-cost", "0.30")
    assert code == 2
    metrics = json.loads((run.dir / "metrics.json").read_text())
    assert metrics["status"] == "aborted_cost" and metrics["rollouts_ok"] == 2 and metrics["cost_list_usd"] == pytest.approx(0.30)
    assert metrics["cost_actual_usd"] == 0.0  # free tier: list price shown, nothing actually spent


def test_transient_errors_are_retried_and_marked(tmp_path, monkeypatch):
    run, fake, code = _model_run(tmp_path, monkeypatch, ["transient"], "--max-cost", "100", "--limit", "1", "--rollouts", "1")
    assert code == 0
    row = json.loads(run.transcript.read_text().splitlines()[0])
    assert row["status"] == "ok" and row["retried"] == 1


def test_provider_down_is_marked_unavailable(tmp_path, monkeypatch):
    run, fake, code = _model_run(tmp_path, monkeypatch, ["fatal"] * 50, "--max-cost", "100", "--max-consecutive-errors", "3")
    assert code == 3
    metrics = json.loads((run.dir / "metrics.json").read_text())
    assert metrics["status"] == "unavailable" and metrics["rollouts_error"] >= 3 and metrics["rollouts_ok"] == 0


def test_resume_does_not_pay_twice(tmp_path, monkeypatch):
    run, fake, code = _model_run(tmp_path, monkeypatch, [], "--max-cost", "100", "--limit", "3")
    assert code == 0 and fake.calls == 6
    run2, fake2, code2 = _model_run(tmp_path, monkeypatch, [], "--max-cost", "100", "--limit", "3", "--resume", str(run.dir))
    assert code2 == 0 and fake2.calls == 0


def test_stats():
    rows = [{"task_id": "a", "rollout": 0, "reward": 1.0, "status": "ok"},
            {"task_id": "a", "rollout": 1, "reward": 0.0, "status": "ok"},
            {"task_id": "b", "rollout": 0, "reward": 1.0, "status": "ok"},
            {"task_id": "b", "rollout": 1, "reward": 1.0, "status": "ok"},
            {"task_id": "c", "rollout": 0, "reward": None, "status": "error"}]
    s = run_summary(rows)
    assert s["mean_reward"] == pytest.approx(0.75) and s["disagreement_rate"] == pytest.approx(0.5)
    assert s["rollouts_failed"] == 1
    low, high = bootstrap_mean_ci([1.0] * 10)
    assert low == high == 1.0
    same = paired_bootstrap({"a": 0.5, "b": 0.5}, {"a": 0.5, "b": 0.5})
    assert same["distinguishable"] is False
    diff = paired_bootstrap({str(i): 1.0 for i in range(30)}, {str(i): 0.0 for i in range(30)})
    assert diff["distinguishable"] is True


def test_leaderboard_groups_and_compares(tmp_path):
    for name in ("naive_no_ceiling", "always_abstain"):
        main(["--model", f"baseline/{name}", "--n-seeds", "12", "--rollouts", "1", "--out", str(tmp_path), "--run-name", "r"])
    board = leaderboard.build(tmp_path)
    assert len(board["runs"]) == 2 and len(board["comparisons"]) == 1
    assert {r["model"] for r in board["runs"]} == {"baseline/naive_no_ceiling", "baseline/always_abstain"}


def test_subset_run_is_compared_with_subset_views_of_full_runs(tmp_path):
    """A scarce model run on --ids is ranked only against other models' rollouts on the same tasks."""
    from paygym.environment import load_tasks

    subsets = tmp_path / "subsets"
    subsets.mkdir()
    ids = [t.id for t in load_tasks(split="eval", n_seeds=12)][:4]
    (subsets / "core4.txt").write_text("\n".join(ids))
    out = tmp_path / "results"
    main(["--model", "baseline/always_abstain", "--n-seeds", "12", "--rollouts", "1", "--out", str(out), "--run-name", "full"])
    main(["--model", "baseline/naive_no_ceiling", "--n-seeds", "12", "--rollouts", "1", "--ids", str(subsets / "core4.txt"),
          "--out", str(out), "--run-name", "core4"])
    board = leaderboard.build(out, subsets)
    sub = [r for r in board["runs"] if r["group"].startswith("subset:core4")]
    assert {r["run"] for r in sub} == {"baseline__naive_no_ceiling/core4", "baseline__always_abstain/full@core4"}
    assert all(r["tasks"] == 4 for r in sub)
    assert any(c["group"].startswith("subset:core4") for c in board["comparisons"])


def test_daily_request_budget_stops_cleanly_and_resume_continues(tmp_path, monkeypatch):
    """Free-tier protection: the run stops *before* a call that would exceed the day's cap."""
    run, fake, code = _model_run(tmp_path, monkeypatch, [], "--max-cost", "100", "--limit", "3", "--daily-request-cap", "4")
    assert code == 6 and fake.calls == 4
    metrics = json.loads((run.dir / "metrics.json").read_text())
    assert metrics["status"] == "aborted_budget" and metrics["rollouts_ok"] == 4
    # Same day, same cap: nothing more is spent.
    run2, fake2, code2 = _model_run(tmp_path, monkeypatch, [], "--max-cost", "100", "--limit", "3", "--daily-request-cap", "4",
                                    "--resume", str(run.dir))
    assert code2 == 6 and fake2.calls == 0
    # A higher cap (or the next day) finishes only the missing rollouts.
    run3, fake3, code3 = _model_run(tmp_path, monkeypatch, [], "--max-cost", "100", "--limit", "3", "--daily-request-cap", "10",
                                    "--resume", str(run.dir))
    assert code3 == 0 and fake3.calls == 2


def test_request_ledger_counts_across_instances_and_settles_actual_use(tmp_path):
    from paygym.eval.budget import RequestLedger, caps_for

    path = tmp_path / "l.json"
    from paygym.eval.budget import Caps

    five = Caps(requests=5, tokens=None, rpm=0, tpm=0)
    a, b = RequestLedger("gemini/x", five, path), RequestLedger("gemini/x", five, path)
    assert a.reserve(4) and not b.reserve(2)  # shared file: a second process sees the first one's use
    a.settle(4, 1)  # a tool rollout reserved max_turns but used 1 turn
    assert b.used_today() == 1 and b.reserve(4) and b.remaining() == 0
    assert RequestLedger("gemini/y", five, path).used_today() == 0  # per model


def test_caps_come_from_the_published_free_limits_with_headroom(tmp_path):
    from paygym.eval.budget import Caps, RequestLedger, caps_for

    assert caps_for("local/qwen2.5-3b") is None and caps_for("baseline/format_only") is None
    flash = caps_for("gemini/gemini-3.8-flash")  # 20 requests/day, 5/min on the free tier
    assert flash.requests == 18 and flash.rpm == 4
    groq = caps_for("groq/openai/gpt-oss-120b")  # 200K tokens/day, 8K/min
    assert groq.tokens == 180_000 and groq.tpm == 8000
    assert caps_for("gemini/some-typo").requests == 18  # unknown models get the strictest limits
    assert caps_for("gemini/gemini-3.8-flash", 0).requests is None
    # The token cap binds independently of the request cap.
    led = RequestLedger("groq/openai/gpt-oss-120b", Caps(requests=100, tokens=10_000, rpm=0, tpm=0), tmp_path / "l.json")
    assert led.reserve(1, 6000) and not led.reserve(1, 6000)
    led.settle(1, 1, 6000, 2000)  # actual use was lower
    assert led.reserve(1, 6000)


def test_groq_service_tier_is_accepted():
    """verifiers 0.2.1 validated responses against the OpenAI SDK's closed service_tier Literal, so every
    Groq response ("on_demand") was rejected (Step 12 smoke eval). paygym.compat widens it."""
    from openai.types.chat import ChatCompletion

    import paygym.environment  # noqa: F401  (applies the shim on import)
    from verifiers.utils import client_utils

    body = {"id": "x", "object": "chat.completion", "created": 0, "model": "openai/gpt-oss-120b", "service_tier": "on_demand",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "hi"}}]}
    stripped, _ = client_utils.strip_routed_experts_data(json.dumps(body).encode())
    assert ChatCompletion.model_validate_json(stripped).choices[0].message.content == "hi"
    ok = json.dumps({**body, "service_tier": "default"}).encode()
    assert client_utils.strip_routed_experts_data(ok)[0] == ok  # known tiers pass through untouched


def test_token_limiter_waits_for_the_window(monkeypatch):
    from paygym.eval import runner as runner_module

    clock = {"t": 1000.0}
    monkeypatch.setattr(runner_module.time, "monotonic", lambda: clock["t"])

    async def fake_sleep(seconds):
        clock["t"] += seconds

    monkeypatch.setattr(runner_module.asyncio, "sleep", fake_sleep)
    lim = runner_module.TokenLimiter(8000)  # 7,200 usable with headroom

    async def go():
        a = await lim.acquire(5000)
        lim.settle(a, 6000)  # real usage was higher than the estimate
        start = clock["t"]
        await lim.acquire(5000)  # 6000 + 5000 > 7200: must wait for the first to leave the window
        return clock["t"] - start

    assert asyncio.run(go()) >= 59.0


def test_replayed_assistant_reasoning_is_not_sent():
    """Groq 400s on assistant messages carrying reasoning_content (tool mode, turn 2+)."""
    import paygym.environment  # noqa: F401
    from verifiers.clients import openai_chat_completions_client as chat_client

    from paygym.compat import strip_replayed_reasoning

    assert chat_client.post_chat_completion_with_routed_experts_sidecar.__name__ == "post_without_replayed_reasoning"
    body = {"model": "m", "messages": [{"role": "user", "content": "q"},
                                       {"role": "assistant", "content": "", "tool_calls": [{"id": "1"}], "reasoning_content": "think"},
                                       {"role": "tool", "tool_call_id": "1", "content": "r"}]}
    out = strip_replayed_reasoning(body)
    assert "reasoning_content" not in out["messages"][1] and out["messages"][1]["tool_calls"] == [{"id": "1"}]
    assert body["messages"][1]["reasoning_content"] == "think"  # caller's object not mutated
    assert out["messages"][0] is body["messages"][0] and out["messages"][2] is body["messages"][2]


def test_ids_subset_runs_exactly_those_tasks(tmp_path):
    ids = tmp_path / "ids.txt"
    from paygym.environment import load_tasks

    chosen = [t.id for t in load_tasks(split="eval", n_seeds=12)][:3]
    ids.write_text("\n".join(chosen) + "\n")
    assert main(["--model", "baseline/format_only", "--n-seeds", "12", "--rollouts", "1", "--ids", str(ids),
                 "--out", str(tmp_path), "--run-name", "r"]) == 0
    rows = [json.loads(l) for l in (tmp_path / "baseline__format_only" / "r" / "transcript.jsonl").read_text().splitlines()]
    assert sorted(r["task_id"] for r in rows) == sorted(chosen)


def test_gemini_thought_signatures_are_replayed():
    """Gemini 3.x 400s on turn 2 unless each function call's thought_signature is sent back; verifiers
    0.2.1 drops it. paygym.compat remembers it by tool-call id and re-attaches it."""
    from openai.types.chat import ChatCompletion

    from paygym import compat

    sig = {"google": {"thought_signature": "abc123"}}
    resp = ChatCompletion.model_validate({
        "id": "r", "object": "chat.completion", "created": 0, "model": "gemini",
        "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {"role": "assistant", "content": None, "tool_calls": [
            {"id": "call-1", "type": "function", "function": {"name": "get_employee_record", "arguments": "{}"}, "extra_content": sig}]}}]})
    compat.remember_signatures(resp)
    body = {"messages": [{"role": "user", "content": "q"},
                         {"role": "assistant", "tool_calls": [{"id": "call-1", "type": "function", "function": {"name": "x", "arguments": "{}"}},
                                                              {"id": "call-unknown", "type": "function", "function": {"name": "y", "arguments": "{}"}}]}]}
    out = compat.reattach_signatures(body)
    calls = out["messages"][1]["tool_calls"]
    assert calls[0]["extra_content"] == sig and "extra_content" not in calls[1]  # never invented
    assert "extra_content" not in body["messages"][1]["tool_calls"][0]  # caller's object not mutated


def test_requests_are_paced_per_model_and_named_retry_delays_honoured(monkeypatch):
    from paygym import compat

    clock = {"t": 0.0}
    monkeypatch.setattr(compat.time, "monotonic", lambda: clock["t"])

    async def fake_sleep(s):
        clock["t"] += s

    monkeypatch.setattr(compat.asyncio, "sleep", fake_sleep)
    compat._NEXT_SLOT.clear()
    compat.set_rpm("m", 12)  # one request every 5 s

    async def three():
        for _ in range(3):
            await compat._pace("https://generativelanguage.googleapis.com/v1beta/openai/", "m")

    asyncio.run(three())
    assert clock["t"] == 10.0  # requests at t = 0, 5, 10
    # Free-tier defaults apply even when verifiers' own runner is used (no runner to set them).
    assert compat._rpm_for("https://generativelanguage.googleapis.com/v1beta/openai/", "gemini-3.5-flash-lite") == 14
    assert compat._retry_delay(Exception("Error code: 429 ... Please retry in 53.57s.")) == 54.57
    assert compat._retry_delay(Exception("Error code: 400 bad request")) is None


def test_transcript_stores_messages_as_json_not_repr(tmp_path, monkeypatch):
    from verifiers.types import AssistantMessage

    run, fake, _ = _model_run(tmp_path, monkeypatch, [], "--max-cost", "100", "--limit", "1", "--rollouts", "1")
    from paygym.eval.runner import _jsonable

    dumped = _jsonable([AssistantMessage(content="hi")])
    assert dumped[0]["role"] == "assistant" and dumped[0]["content"] == "hi"
    row = json.loads(run.transcript.read_text().splitlines()[0])
    assert isinstance(row["completion"][0], dict)


def test_gpt_oss_on_groq_uses_low_reasoning_effort(tmp_path, monkeypatch):
    run, _, _ = _model_run(tmp_path, monkeypatch, [], "--max-cost", "100", "--limit", "1", "--rollouts", "1")
    assert run.sampling_args()["reasoning_effort"] == "low"
    cfg = json.loads((run.dir / "config.json").read_text())
    assert cfg["sampling"]["reasoning_effort"] == "low"  # recorded, so the config is honest about it


def test_small_max_tokens_is_allowed_without_a_tpm_limit(tmp_path, monkeypatch):
    """--max-tokens 384 on a local model (pilot) was rejected as 'prompt too large' by the TPM guard."""
    run, fake, code = _model_run(tmp_path, monkeypatch, [], "--max-cost", "100", "--limit", "2", "--rollouts", "1",
                                 "--max-tokens", "384")
    assert code == 0 and fake.calls == 2


def test_a_run_where_nothing_succeeded_is_never_completed(tmp_path, monkeypatch):
    run, fake, code = _model_run(tmp_path, monkeypatch, ["fatal"] * 50, "--max-cost", "100", "--limit", "2",
                                 "--rollouts", "1", "--max-consecutive-errors", "100")
    metrics = json.loads((run.dir / "metrics.json").read_text())
    assert code == 3 and metrics["status"] == "unavailable" and metrics["rollouts_ok"] == 0


def test_rescore_moves_a_run_to_the_current_rubric_without_model_calls(tmp_path):
    from paygym.eval.runner import rescore
    from paygym.rubric import RUBRIC_VERSION

    assert main(["--model", "baseline/always_abstain", "--n-seeds", "12", "--rollouts", "1", "--out", str(tmp_path), "--run-name", "r"]) == 0
    run_dir = tmp_path / "baseline__always_abstain" / "r"
    cfg = json.loads((run_dir / "config.json").read_text())
    cfg["rubric_version"] = "1.0"  # pretend it was scored under the old rubric, with v1.0's 0.05 for a refused payslip
    (run_dir / "config.json").write_text(json.dumps(cfg))
    rows = [json.loads(l) for l in (run_dir / "transcript.jsonl").read_text().splitlines()]
    for r in rows:
        if r["gate"] == "refused_determinable":
            r["reward"] = 0.05
    (run_dir / "transcript.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    out = rescore(run_dir)
    assert out["changed"] > 0 and out["rubric_version"] == RUBRIC_VERSION
    rows = [json.loads(l) for l in (run_dir / "transcript.jsonl").read_text().splitlines()]
    assert all(r["reward"] == -1.0 for r in rows if r["gate"] == "refused_determinable")  # v1.2
    assert json.loads((run_dir / "config.json").read_text())["rescored_from"] == "1.0"
    assert json.loads((run_dir / "scores.json").read_text())["rubric_version"] == RUBRIC_VERSION


def test_leaderboard_excludes_pilots_and_runs_with_no_successes(tmp_path):
    main(["--model", "baseline/naive_no_ceiling", "--n-seeds", "12", "--rollouts", "1", "--out", str(tmp_path), "--run-name", "r"])
    from paygym.eval.leaderboard import is_leaderboard_run

    assert is_leaderboard_run({"split": "eval", "tasks_path": None}, {"rollouts_ok": 3})
    assert not is_leaderboard_run({"split": "eval", "tasks_path": "tasks/generated/train_easy.jsonl"}, {"rollouts_ok": 120})  # a pilot
    assert not is_leaderboard_run({"split": "eval", "tasks_path": None}, {"rollouts_ok": 0})  # server was down
    assert [r["model"] for r in leaderboard.build(tmp_path)["runs"]] == ["baseline/naive_no_ceiling"]


def test_rescore_needs_no_api_key_for_a_judged_run(tmp_path, monkeypatch):
    from paygym.eval.runner import rescore

    assert main(["--model", "baseline/always_abstain", "--n-seeds", "12", "--rollouts", "1", "--out", str(tmp_path), "--run-name", "r"]) == 0
    run_dir = tmp_path / "baseline__always_abstain" / "r"
    cfg = json.loads((run_dir / "config.json").read_text())
    cfg.update({"rubric_version": "1.0", "judge": True})  # as a hosted run with --judge was recorded
    (run_dir / "config.json").write_text(json.dumps(cfg))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert rescore(run_dir)["rubric_version"] != "1.0"
    assert json.loads((run_dir / "config.json").read_text())["judge"] is True


def test_track_c_s1_s2_are_the_default_configurations():
    from paygym.environment import load_tasks
    from paygym.eval.leaderboard import effective_scaffold
    from paygym.prompting import messages_for

    tasks = load_tasks(split="eval", n_seeds=12)
    assert all(messages_for(t, "single", "S1") == messages_for(t, "single") for t in tasks)
    assert all(messages_for(t, "tool", "S2") == messages_for(t, "tool") for t in tasks)
    assert effective_scaffold({"scaffold": "S1", "mode": "single"}) is None
    assert effective_scaffold({"scaffold": "S2", "mode": "tool"}) is None
    assert effective_scaffold({"scaffold": "S4", "mode": "tool"}) == "S4"


def test_sensitivity_reproduces_the_rubric_under_the_shipped_weights(tmp_path):
    """The sensitivity table re-implements the payslip weighting; under the shipped weights it must give
    exactly the recorded reward for every row, or it has drifted from the rubric (it had, at rubric 1.2)."""
    from paygym.eval.sensitivity import WEIGHTINGS, rescore

    for name in ("always_abstain", "naive_no_ceiling", "format_only", "gross_as_net"):
        main(["--model", f"baseline/{name}", "--n-seeds", "12", "--rollouts", "1", "--out", str(tmp_path), "--run-name", "r"])
        rows = [json.loads(l) for l in (tmp_path / f"baseline__{name}" / "r" / "transcript.jsonl").read_text().splitlines()]
        shipped = next(iter(WEIGHTINGS.values()))
        for r in rows:
            assert rescore(r, shipped) == pytest.approx(r["reward"]), (name, r["task_id"], r["gate"])


def test_empty_timeout_is_an_infrastructure_error_and_is_retried(tmp_path, monkeypatch):
    run, fake, code = _model_run(tmp_path, monkeypatch, ["empty_timeout"], "--max-cost", "100", "--limit", "1", "--rollouts", "1")
    row = json.loads(run.transcript.read_text().splitlines()[0])
    assert code == 0 and fake.calls == 2 and row["status"] == "ok" and row["retried"] == 1  # retried, then scored
