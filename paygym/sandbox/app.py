"""PayGym agent sandbox (brief Phase 08): outside agents fetch tasks and submit answers for scoring.

    (each route is also served without the /api prefix, matching the brief's API shape: /tasks, /submit, /runs/<id>)
    GET  /api/health                          liveness (use it to wait out a cold start)
    GET  /api/tasks?tier=2,3&n=10[&seed=42]   a batch of tasks; never any ground truth
    POST /api/submit                          {run_id, answers: [{id, answer}]} -> per-task score, breakdown, clause
    GET  /api/runs/{run_id}                   the stored submission and scores for that run
    GET  /api/leaderboard                     recent external runs (shown on the dashboard, labelled external)
    POST /api/tools/{name}                    the tool-mode tools, for agents that want to call them

Scoring is ``paygym.rubric.score_answer``, the same function the eval harness and the GRPO trainer use
(no second scoring path; ``tests/test_sandbox.py`` checks parity). Responses carry component *scores*
and clause ids only, never the rubric's free-text ``detail`` (which names expected values).
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from paygym import __version__
from paygym.prompting import single_turn_messages, tool_turn_messages
from paygym.rubric import RUBRIC_VERSION, score_answer
from paygym.ruleset import load_ruleset
from paygym.sandbox.runs import MAX_TASKS, RunSpec, TokenError, new_spec, sign, taskset, verify
from paygym.sandbox.store import make_store
from paygym.tools import TOOL_NAMES, TOOLS

RATE_LIMITS = {"tasks": 30, "submit": 30, "tools": 300, "read": 120}  # requests per minute per caller
JUDGED_SUBMITS_PER_DAY = int(os.environ.get("SANDBOX_JUDGED_SUBMITS_PER_DAY", "20"))  # per caller; protects the free judge quota
MAX_ANSWER_CHARS = 20_000

app = FastAPI(title="PayGym sandbox", version=__version__, docs_url="/api/docs", openapi_url="/api/openapi.json")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"], allow_headers=["*"])  # public API
store = make_store()


# --------------------------------------------------------------------------- models


class Answer(BaseModel):
    id: str = Field(max_length=8)
    answer: str | dict = Field(description="the agent's completion text, or the contract JSON object itself")


class Submission(BaseModel):
    run_id: str = Field(max_length=400)
    answers: list[Answer] = Field(max_length=MAX_TASKS)


class ToolCall(BaseModel):
    run_id: str = Field(max_length=400)
    task_id: str = Field(max_length=8)
    arguments: dict = Field(default_factory=dict)


# --------------------------------------------------------------------------- helpers


def _caller(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")


def _limit(request: Request, kind: str) -> None:
    if store.incr_window(f"{kind}:{_caller(request)}", 60) > RATE_LIMITS[kind]:
        raise HTTPException(429, f"rate limit: at most {RATE_LIMITS[kind]} {kind} requests per minute")


def _spec(run_id: str) -> RunSpec:
    try:
        spec = verify(run_id)
    except TokenError as exc:
        raise HTTPException(400, str(exc)) from None
    current = load_ruleset().version
    if spec.ruleset_version != current:  # version skew: never silently score under a different rule set
        raise HTTPException(409, f"run was issued under rule set {spec.ruleset_version}; the server runs {current}. Fetch a new run.")
    return spec


def _answer_text(answer: str | dict) -> str:
    if isinstance(answer, dict):
        return "```json\n" + json.dumps(answer) + "\n```"
    return answer[:MAX_ANSWER_CHARS]


def _judge_for(request: Request):
    """The LLM judge, if configured and this caller still has judge budget today; otherwise None (marked deferred)."""
    if not os.environ.get("GEMINI_API_KEY") or os.environ.get("SANDBOX_DISABLE_JUDGE"):
        return None
    if store.incr_window(f"judge:{_caller(request)}", 86_400) > JUDGED_SUBMITS_PER_DAY:
        return None
    from paygym.judge import GeminiJudge

    return GeminiJudge(cache_path=None, ledger=False)  # the sandbox budgets judge calls per caller IP instead


def _public_task(task) -> dict:
    return {"id": task.id, "tier": task.difficulty, "prompt": single_turn_messages(task),
            "tool_prompt": tool_turn_messages(task), "tools_available": list(TOOL_NAMES)}


@app.exception_handler(RequestValidationError)
async def _validation_error(request: Request, exc: RequestValidationError):
    # Field locations and messages only: no echo of submitted values and no internal state.
    errors = [{"loc": list(e.get("loc", [])), "msg": e.get("msg", "")} for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": errors})


@app.exception_handler(Exception)
async def _unexpected(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={"detail": "internal error"})  # never a stack trace


# --------------------------------------------------------------------------- endpoints


@app.get("/api/health")
@app.get("/health", include_in_schema=False)
def health():
    rs = load_ruleset()
    return {"ok": True, "ruleset_version": rs.version, "rubric_version": RUBRIC_VERSION, "paygym_version": __version__}


@app.get("/api/tasks")
@app.get("/tasks", include_in_schema=False)  # the brief's "workable API shape" paths work too
def get_tasks(request: Request, tier: str = Query("all", max_length=20), n: int = Query(10, ge=1),
              seed: int | None = Query(None, ge=0, le=2**31 - 1)):
    _limit(request, "tasks")
    if n > MAX_TASKS:
        raise HTTPException(400, f"n is capped at {MAX_TASKS} tasks per run")
    try:
        tiers = (1, 2, 3) if tier == "all" else tuple(sorted({int(t) for t in tier.split(",")}))
    except ValueError:
        raise HTTPException(400, "tier must be 'all' or a comma list of 1, 2, 3") from None
    if not tiers or any(t not in (1, 2, 3) for t in tiers):
        raise HTTPException(400, "tier must be 'all' or a comma list of 1, 2, 3")
    spec = new_spec(seed, tiers, n)
    tasks = taskset(spec)
    return {"run_id": sign(spec), "ruleset_version": spec.ruleset_version, "seed": spec.seed, "tier_mix": spec.tier_mix,
            "n_tasks": len(tasks), "tasks": [_public_task(t) for t in tasks],
            "submit": {"method": "POST", "path": "/api/submit", "body": {"run_id": "<run_id>", "answers": [{"id": "000", "answer": "<completion text or contract JSON>"}]}}}


@app.post("/api/submit")
@app.post("/submit", include_in_schema=False)
def submit(request: Request, body: Submission):
    _limit(request, "submit")
    spec = _spec(body.run_id)
    stored = store.get_run(body.run_id)
    if stored is not None:  # idempotent: a run is scored once
        return {**stored["response"], "note": "already scored; returning the stored result"}
    tasks = {t.id: t for t in taskset(spec)}
    answers = {a.id: _answer_text(a.answer) for a in body.answers}
    unknown = sorted(set(answers) - set(tasks))
    judge = _judge_for(request)
    per_task, total = [], 0.0
    for task_id, task in tasks.items():
        text = answers.get(task_id, "")
        try:
            score = score_answer(task, text, judge=judge)
        except Exception:  # judge outage: score without it and mark the judge component deferred
            score = score_answer(task, text, judge=None)
        total += score.total
        breakdown = {c.name: c.score for c in score.components}
        if task.ground_truth.kind == "refusal" and score.decision == "refuse" and "judge_flag_quality" not in breakdown and score.gate is None:
            breakdown["judge_flag_quality"] = "deferred"  # judge unavailable or caller's judge budget used up
        per_task.append({"id": task_id, "tier": task.difficulty, "score": round(score.total, 4), "breakdown": breakdown,
                         "clause": score.driving_clauses[0] if score.driving_clauses else None,
                         "clauses": score.driving_clauses, "gate": score.gate, "answered": task_id in answers})
    response = {"run_id": body.run_id, "ruleset_version": spec.ruleset_version, "seed": spec.seed, "tier_mix": spec.tier_mix,
                "n_tasks": len(tasks), "n_answered": len(set(answers) & set(tasks)), "unknown_ids": unknown,
                "mean_reward": round(total / len(tasks), 4) if tasks else None, "per_task": per_task}
    summary = {"run_id": body.run_id, "ruleset_version": spec.ruleset_version, "seed": spec.seed, "tier_mix": spec.tier_mix,
               "n_tasks": len(tasks), "mean_reward": response["mean_reward"], "external": True,
               "submitted_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
    if not store.put_run_once(body.run_id, {"response": response, "summary": summary, "answers": answers,
                                            "scored_at": time.time()}):
        stored = store.get_run(body.run_id)  # a concurrent submit of the same run won; return its result
        return {**stored["response"], "note": "already scored; returning the stored result"}
    return response


@app.get("/api/runs/{run_id}")
@app.get("/runs/{run_id}", include_in_schema=False)
def get_run(request: Request, run_id: str):
    _limit(request, "read")
    _spec(run_id)
    stored = store.get_run(run_id)
    if stored is None:
        raise HTTPException(404, "run not submitted yet")
    return {"response": stored["response"], "answers": stored["answers"]}


@app.get("/api/leaderboard")
@app.get("/leaderboard", include_in_schema=False)
def leaderboard(request: Request, limit: int = Query(100, ge=1, le=500)):
    _limit(request, "read")
    return {"runs": store.list_runs(limit), "note": "external runs submitted through the sandbox"}


@app.post("/api/tools/{name}")
def call_tool(request: Request, name: str, body: ToolCall):
    _limit(request, "tools")
    if name not in TOOL_NAMES:
        raise HTTPException(404, f"unknown tool; available: {', '.join(TOOL_NAMES)}")
    spec = _spec(body.run_id)
    task = next((t for t in taskset(spec) if t.id == body.task_id), None)
    if task is None:
        raise HTTPException(404, "unknown task_id for this run")
    fn = dict(zip(TOOL_NAMES, TOOLS))[name]
    args = {k: v for k, v in body.arguments.items() if k != "task_json"}  # the hidden argument is server-side only
    try:
        return json.loads(fn(**args, task_json=task.model_dump_json()))
    except TypeError:
        raise HTTPException(400, "invalid arguments for this tool") from None
