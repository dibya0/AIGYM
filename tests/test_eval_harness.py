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
        return {"reward": 0.5, "metrics": {"net_pay_exact": 0.0, "total_tool_calls": 0},
                "completion": [{"role": "assistant", "content": "no json"}],
                "token_usage": {"input_tokens": 1_000_000, "output_tokens": 0},
                "timing": {"model": {"duration": 1.5}}, "stop_condition": "max_turns_reached"}


def _model_run(tmp_path, monkeypatch, script, *extra):
    monkeypatch.setenv("GROQ_API_KEY", "test")
    args = _args(tmp_path, "--model", "groq/openai/gpt-oss-120b", "--rpm", "0", "--concurrency", "1", *extra)
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
