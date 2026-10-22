"""Sandbox tests (brief Phase 08): round trip, guardrails, version skew, idempotency, parity, and the
ground-truth leak test ("Write a test that asserts no expected value appears in any response")."""

import json

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

SECRET = "test-secret-" + "x" * 40


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("SANDBOX_SECRET", SECRET)
    monkeypatch.setenv("SANDBOX_DISABLE_JUDGE", "1")
    from fastapi.testclient import TestClient

    from paygym.sandbox import app as app_module
    from paygym.sandbox.store import MemoryStore

    monkeypatch.setattr(app_module, "store", MemoryStore())
    return TestClient(app_module.app)


def _perfect(task) -> dict:
    gt = task.ground_truth
    if gt.kind == "value":
        return {"decision": "answer", "value": float(gt.value)}
    if gt.kind == "refusal":
        return {"decision": "refuse", "reason_code": gt.reason_code, "lines": None, "explanation": "x"}
    return {"decision": "answer", "lines": {k: float(v) for k, v in gt.lines.items()}, "explanation": "x"}


def _server_tasks(run_id):
    from paygym.sandbox.runs import taskset, verify

    return taskset(verify(run_id))


def test_round_trip_returns_score_breakdown_and_clause(client):
    batch = client.get("/api/tasks", params={"tier": "2,3", "n": 6, "seed": 42}).json()
    assert batch["seed"] == 42 and batch["tier_mix"] == "2,3" and batch["ruleset_version"] == "1.0"
    assert len(batch["tasks"]) == 6 and all(t["id"].isdigit() for t in batch["tasks"])  # opaque ids, never generator ids
    answers = [{"id": t.id, "answer": _perfect(t)} for t in _server_tasks(batch["run_id"])]
    result = client.post("/api/submit", json={"run_id": batch["run_id"], "answers": answers}).json()
    assert len(result["per_task"]) == 6
    for row in result["per_task"]:
        assert row["score"] in (1.0, 0.8) and row["breakdown"] and row["clause"]


def test_same_seed_same_tasks_different_seed_different_tasks(client):
    a = client.get("/api/tasks", params={"n": 5, "seed": 7}).json()
    b = client.get("/api/tasks", params={"n": 5, "seed": 7}).json()
    c = client.get("/api/tasks", params={"n": 5, "seed": 8}).json()
    assert [t["prompt"] for t in a["tasks"]] == [t["prompt"] for t in b["tasks"]]
    assert [t["prompt"] for t in a["tasks"]] != [t["prompt"] for t in c["tasks"]]


def test_scoring_parity_with_the_rubric_and_the_environment(client):
    """No second scoring path: sandbox == paygym.rubric.score_answer == the verifiers environment's reward."""
    from paygym.rubric import score_answer

    batch = client.get("/api/tasks", params={"n": 12, "seed": 3}).json()
    tasks = _server_tasks(batch["run_id"])
    texts = {t.id: f"```json\n{json.dumps(_perfect(t) if i % 2 else {'decision': 'answer', 'lines': {'net_pay': 1}})}\n```"
             for i, t in enumerate(tasks)}
    result = client.post("/api/submit", json={"run_id": batch["run_id"], "answers": [{"id": k, "answer": v} for k, v in texts.items()]}).json()
    api = {r["id"]: r["score"] for r in result["per_task"]}
    for t in tasks:
        assert api[t.id] == pytest.approx(round(score_answer(t, texts[t.id]).total, 4))
    vf = pytest.importorskip("verifiers")  # noqa: F841
    from paygym.environment import make_rubric

    reward_fn = make_rubric(use_judge=False).funcs[0]
    for t in tasks:
        env_score = reward_fn(completion=[{"role": "assistant", "content": texts[t.id]}],
                              info={"task_json": t.model_dump_json()}, state={})
        assert api[t.id] == pytest.approx(round(env_score, 4))


def test_resubmission_is_idempotent(client):
    batch = client.get("/api/tasks", params={"n": 3, "seed": 1}).json()
    body = {"run_id": batch["run_id"], "answers": [{"id": "000", "answer": "nonsense"}]}
    first = client.post("/api/submit", json=body).json()
    second = client.post("/api/submit", json={**body, "answers": [{"id": "000", "answer": "different"}]}).json()
    assert second["mean_reward"] == first["mean_reward"] and "already scored" in second["note"]


def test_task_cap_and_bad_tier(client):
    assert client.get("/api/tasks", params={"n": 10_000}).status_code == 400  # 10,000 tasks: capped
    assert client.get("/api/tasks", params={"tier": "9"}).status_code == 400


def test_rate_limit_per_caller(client, monkeypatch):
    from paygym.sandbox import app as app_module

    monkeypatch.setitem(app_module.RATE_LIMITS, "tasks", 3)
    codes = [client.get("/api/tasks", params={"n": 1}).status_code for _ in range(5)]
    assert codes[:3] == [200, 200, 200] and codes[3:] == [429, 429]  # tight loop: rate limited


def test_tampered_and_version_skewed_runs_are_rejected(client):
    batch = client.get("/api/tasks", params={"n": 2}).json()
    tampered = batch["run_id"][:-2] + ("AA" if not batch["run_id"].endswith("AA") else "BB")
    assert client.post("/api/submit", json={"run_id": tampered, "answers": []}).status_code == 400
    from paygym.sandbox.runs import RunSpec, sign

    old = sign(RunSpec(seed=1, tiers=(2,), n=2, ruleset_version="0.9", issued_at=0))
    response = client.post("/api/submit", json={"run_id": old, "answers": []})
    assert response.status_code == 409 and "0.9" in response.json()["detail"]


def test_tools_endpoint(client):
    batch = client.get("/api/tasks", params={"tier": "2", "n": 2, "seed": 5}).json()
    task = _server_tasks(batch["run_id"])[0]
    ok = client.post("/api/tools/get_employee_record", json={"run_id": batch["run_id"], "task_id": task.id,
                                                             "arguments": {"employee_id": task.employee_id}})
    assert ok.status_code == 200 and "documents" in ok.json()
    assert client.post("/api/tools/rm_rf", json={"run_id": batch["run_id"], "task_id": task.id}).status_code == 404
    bad = client.post("/api/tools/calc", json={"run_id": batch["run_id"], "task_id": task.id, "arguments": {"nope": 1}})
    assert bad.status_code == 400


def _gt_forms(task) -> set[str]:
    """Expected values that would constitute a leak (excluding anything already in the task's own prompt)."""
    gt = task.ground_truth
    if gt.kind == "refusal":
        values, extra = [], {gt.reason_code, gt.clause}
    elif gt.kind == "value":
        return set()  # Tier 1 answers are in the attached rule text by design ("present in the provided context")
    else:
        values, extra = [gt.lines[k] for k in ("net_pay", "income_tax", "employee_social_insurance", "employee_pension") if gt.lines[k] >= 100], set()
    forms = set(extra)
    for v in values:
        forms |= {f"{v:.2f}", f"{v:,.2f}", f'"{float(v)}"', f": {float(v)}"}
    from paygym.prompting import single_turn_messages

    # Raw text, not json.dumps: dumps escapes "§" to "\u00a7", which hid that clause ids like GEN-§9.2 are
    # part of the rule-book text every agent is given (a false "leak" found on the first real run).
    prompt = "\n".join(m["content"] for m in single_turn_messages(task))
    return {f for f in forms if f not in prompt}


def test_no_ground_truth_in_any_response(client):
    """Fuzz every endpoint with valid and invalid input; no expected value, reason code, task seed or
    rubric 'detail' text may appear in any response body."""
    from paygym.sandbox.runs import _task_seed

    bodies, leaks = [], {}
    for seed, tier in [(11, "all"), (12, "2,3"), (13, "3"), (14, "1,2")]:
        r = client.get("/api/tasks", params={"tier": tier, "n": 8, "seed": seed})
        bodies.append(r.text)
        batch = r.json()
        tasks = _server_tasks(batch["run_id"])
        for t in tasks:
            leaks[(seed, t.id)] = _gt_forms(t)
        run = batch["run_id"]
        garbage = [{"id": t["id"], "answer": a} for t, a in zip(batch["tasks"], ["", "{", "```json\n{\"decision\":\"answer\",\"lines\":{}}\n```",
                                                                                   "refuse", {"decision": "maybe"}, {"x": 1}, "1" * 50, "```json\n[]\n```"])]
        for request in [
            lambda: client.post("/api/submit", json={"run_id": run, "answers": garbage}),
            lambda: client.post("/api/submit", json={"run_id": run, "answers": garbage}),  # idempotent replay
            lambda: client.get(f"/api/runs/{run}"),
            lambda: client.post("/api/submit", json={"run_id": run, "answers": [{"id": "x" * 50, "answer": 1}]}),  # 422
            lambda: client.post("/api/submit", json={"run_id": "not.a.token", "answers": []}),
            lambda: client.post("/api/submit", content=b"{not json", headers={"content-type": "application/json"}),
            lambda: client.post("/api/tools/lookup_rules", json={"run_id": run, "task_id": "000", "arguments": {"jurisdiction": "VAL", "year": 2026}}),
            lambda: client.post("/api/tools/get_fx_rate", json={"run_id": run, "task_id": "000", "arguments": {"from_currency": "USD", "to_currency": "VLD", "on_date": "2026-04-30"}}),
            lambda: client.post("/api/tools/calc", json={"run_id": run, "task_id": "000", "arguments": {"expression": "1/0"}}),
            lambda: client.get("/api/leaderboard"),
        ]:
            bodies.append(request().text)
        for i in range(40):
            assert str(_task_seed(seed, i)) not in "".join(bodies)
    everything = "\n".join(bodies)
    assert SECRET not in everything
    # The rubric's free-text `detail` names expected values ("net_pay 7000 vs 6934.00 (tolerance 0.01 …",
    # "refused with 'X'; expected Y"); the API must return scores and clause ids only.
    for marker in ("(tolerance 0", "(tolerance 1", "lines correct", "; expected ", "first wrong:"):
        assert marker not in everything, marker
    for (seed, task_id), forms in leaks.items():
        for form in forms:
            assert form not in everything, f"leak: {form!r} (seed {seed}, task {task_id})"


def test_brief_api_shape_paths_work_without_api_prefix(client):
    """The brief's "workable API shape": GET /tasks?tier=2&n=10, POST /submit, GET /runs/<run_id>."""
    batch = client.get("/tasks", params={"tier": "2", "n": 3}).json()
    assert {"run_id", "ruleset_version", "seed", "tasks"} <= set(batch)
    assert {"id", "prompt", "tools_available"} <= set(batch["tasks"][0])
    result = client.post("/submit", json={"run_id": batch["run_id"], "answers": [{"id": "000", "answer": {"decision": "refuse"}}]}).json()
    assert {"run_id", "mean_reward", "per_task"} <= set(result)
    assert client.get(f"/runs/{batch['run_id']}").status_code == 200
    assert client.get("/health").json()["ok"] is True


def test_trap_feedback_does_not_reveal_the_expected_reason_and_seed_reuse_is_flagged(client):
    """Manual test 2026-10-22: a wrong-reason refusal returned GEN-§9.4, i.e. the expected UNSUPPORTED_CURRENCY, and the
    same public seed regenerates the same tasks, so probe-then-resubmit beat every trap in two requests."""
    from paygym.reference.calculator import REASON_CLAUSES

    first = client.get("/api/tasks", params={"tier": "3", "n": 4, "seed": 11}).json()
    tasks = _server_tasks(first["run_id"])
    wrong = {t.id: next(c for c in REASON_CLAUSES if c != t.ground_truth.reason_code) for t in tasks}
    body = {"run_id": first["run_id"], "answers": [{"id": t.id, "answer": {"decision": "refuse", "reason_code": wrong[t.id]}} for t in tasks]
}
    result = client.post("/api/submit", json=body).json()
    specific = set(REASON_CLAUSES.values())
    for row in result["per_task"]:
        assert row["gate"] == "wrong_reason" and row["score"] == pytest.approx(0.3)
        assert row["clause"] == "GEN-§9" and not specific & set(row["clauses"])  # no sub-clause, so no expected code
    answered = client.post("/api/submit", json={"run_id": client.get("/api/tasks", params={"tier": "3", "n": 4, "seed": 12}).json()["run_id"],
                                                "answers": []}).json()
    assert all(r["clause"] == "GEN-§9" for r in answered["per_task"])  # unanswered = unparseable: generic too
    assert result["repeat_seed"] is False
    import time

    time.sleep(1.1)  # a run_id carries its issue time in seconds: fetched within the same second it is the same run
    second = client.get("/api/tasks", params={"tier": "3", "n": 4, "seed": 11}).json()  # same seed, new run_id
    assert second["run_id"] != first["run_id"]
    again = client.post("/api/submit", json={"run_id": second["run_id"], "answers": []}).json()
    assert again["repeat_seed"] is True
    board = client.get("/api/leaderboard").json()["runs"]
    assert [r["repeat_seed"] for r in board if r["seed"] == 11] == [True, False]  # newest first
    correct = client.post("/api/submit", json={"run_id": client.get("/api/tasks", params={"tier": "3", "n": 4, "seed": 13}).json()["run_id"],
                                               "answers": [{"id": t.id, "answer": _perfect(t)} for t in _server_tasks(
                                                   client.get("/api/tasks", params={"tier": "3", "n": 4, "seed": 13}).json()["run_id"])]}).json()
    assert all(r["clause"] in specific for r in correct["per_task"])  # a correct refusal still gets its specific clause
