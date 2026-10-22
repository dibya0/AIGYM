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

from fastapi import FastAPI, HTTPException, Path, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

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

API_DESCRIPTION = """
Score **your own agent** on PayGym, a gym for gross-to-net payroll under a fictional, versioned rule set
(three jurisdictions: Valdoria, Kestrel Isles, Nordmark). Same rubric as the dashboard; no ground truth ever leaves the server.

**Flow (two calls):**
1. `GET /api/tasks?tier=2,3&n=5` → a signed `run_id` + tasks (each with a single-turn `prompt` and a tool-mode `tool_prompt`).
2. Run your agent on each prompt, then `POST /api/submit` with `{run_id, answers: [{id, answer}]}` → a score per task,
   the per-reward-function breakdown, the gate that applied, and the rule-set clause that drove the mark.

**The answer format** (the output contract in each prompt's system message), as text ending in a ```json block, or as the object itself:
`{"decision": "answer" | "refuse", "reason_code": null | "MISSING_INPUT" | "CONFLICTING_RECORDS" | "NO_APPLICABLE_TABLE" | "UNSUPPORTED_CURRENCY", "lines": {10 payslip lines} | null, "explanation": "..."}`

**Score levels** (rubric 1.4): payslip all lines right 1.0 · net pay wrong ≤ 0.25 · refused a payable payslip −1 ·
trap refused with the right reason 0.8 (+ up to 0.2 judge) · wrong reason 0.3 · trap answered −1 · unreadable −1.

**Limits:** ≤ 50 tasks per run; per-caller rate limits; a run is scored once (resubmitting returns the stored result);
a submission on an already-used public seed is flagged `repeat_seed`. Omit `seed` for a fresh random task set.
Free hosting can cold-start: call `GET /api/health` first. Quickstart: `curl -s <host>/quickstart.py | python3 - <host>`.
"""

TAGS = [
    {"name": "1. Run an agent", "description": "Fetch tasks, submit answers, get scores. This is all an outside agent needs."},
    {"name": "2. Tool mode", "description": "The four tools for agents using `tool_prompt`: the only data source in tool mode."},
    {"name": "3. Results", "description": "Stored runs and the external leaderboard shown on the dashboard."},
    {"name": "Service", "description": "Liveness and versions."},
]

app = FastAPI(title="PayGym sandbox", version=__version__, description=API_DESCRIPTION, openapi_tags=TAGS,
              docs_url="/api/docs", openapi_url="/api/openapi.json")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"], allow_headers=["*"])  # public API
store = make_store()


# --------------------------------------------------------------------------- models


_EXAMPLE_PAYSLIP = {"decision": "answer", "reason_code": None,
                    "lines": {"earned_salary": 9177.42, "retro_pay": 0, "taxable_allowances": 390, "non_taxable_allowances": 150,
                              "gross_pay": 9717.42, "employee_social_insurance": 480, "employee_pension": 458.87,
                              "income_tax": 1588.56, "net_pay": 7189.99, "employer_social_insurance": 720},
                    "explanation": "Prorated 25/31 days; social insurance capped at the 6,000 ceiling (VAL-§2.1)."}
_EXAMPLE_REFUSAL = {"decision": "refuse", "reason_code": "CONFLICTING_RECORDS", "lines": None,
                    "explanation": "The HR record and the contract state different monthly_salary values; GEN-§9.2 gives no precedence."}


class Answer(BaseModel):
    id: str = Field(max_length=8, description="The task id from `GET /api/tasks` (`000`, `001`, ...).", examples=["000"])
    answer: str | dict = Field(
        description="Your agent's reply for this task: either its full completion text (ending in a ```json block) or the "
                    "contract JSON object itself. A missing task scores as unparseable (−1).",
        examples=[_EXAMPLE_PAYSLIP])


class Submission(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{
        "run_id": "<paste the run_id from GET /api/tasks>",
        "answers": [{"id": "000", "answer": _EXAMPLE_PAYSLIP}, {"id": "001", "answer": _EXAMPLE_REFUSAL}],
    }]})
    run_id: str = Field(max_length=400, description="The signed `run_id` returned by `GET /api/tasks` (it encodes the seed, tiers, n and rule-set version).")
    answers: list[Answer] = Field(max_length=MAX_TASKS, description="One entry per task you answer (at most 50).")


class ToolCall(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{
        "run_id": "<paste the run_id from GET /api/tasks>", "task_id": "000",
        "arguments": {"expression": "min(9567.42, 6000) * 0.08"},
    }]})
    run_id: str = Field(max_length=400, description="The signed `run_id` from `GET /api/tasks`.")
    task_id: str = Field(max_length=8, description="Which task of the run the call is for (`000`, ...): tools answer from that task's records.")
    arguments: dict = Field(
        default_factory=dict,
        description="The tool's arguments. `get_employee_record`: {employee_id}. `lookup_rules`: {jurisdiction: VAL|KES|NRD, year}. "
                    "`get_fx_rate`: {from_currency, to_currency, on_date: YYYY-MM-DD (a month-end)}. `calc`: {expression}.")


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


@app.get("/api/health", tags=["Service"], summary="Liveness, versions and storage backend",
         description="Call this first: free hosting can cold-start. `store` is `RedisStore` (persistent, shared) or `MemoryStore` (per instance).")
@app.get("/health", include_in_schema=False)
def health():
    rs = load_ruleset()
    # "store" says where run records and rate limits live: RedisStore (persistent, shared by all instances) or
    # MemoryStore (per instance: fine locally, but on serverless a cold instance starts empty).
    return {"ok": True, "ruleset_version": rs.version, "rubric_version": RUBRIC_VERSION, "paygym_version": __version__,
            "store": type(store).__name__}


@app.get("/api/tasks", tags=["1. Run an agent"], summary="Fetch a batch of tasks (no answers included)",
         description="Returns a signed `run_id` and the tasks. Each task has `prompt` (single-turn: system contract + rule-set "
                     "sections + documents + question) and `tool_prompt` (tool mode: an employee id only; use `/api/tools/{name}`). "
                     "Tier 1 = look up one rule-set value; Tier 2 = compute a 10-line payslip; Tier 3 = traps the rules do not "
                     "determine (refuse with the reason code). The same `seed` + `tier` + `n` always gives the same tasks.")
@app.get("/tasks", include_in_schema=False)  # the brief's "workable API shape" paths work too
def get_tasks(request: Request,
              tier: str = Query("all", max_length=20, description="`all`, or a comma list of tiers: `1`, `2`, `3`, e.g. `2,3`.", examples=["2,3"]),
              n: int = Query(10, ge=1, description=f"Number of tasks (1–{MAX_TASKS}).", examples=[5]),
              seed: int | None = Query(None, ge=0, le=2**31 - 1,
                                       description="Public seed for a reproducible task set (compare two agents on the same tasks). "
                                                   "Omit for a fresh random set.", examples=[42])):
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


@app.post("/api/submit", tags=["1. Run an agent"], summary="Submit your agent's answers; get scores, breakdown and clauses",
          description="Scored by `paygym.rubric.score_answer`, the same function as the eval and the dashboard. Per task: `score`, "
                      "`breakdown` (per reward function), `gate` (e.g. `wrong_net_capped`, `refused_determinable`, `answered_trap`, "
                      "`unparseable`) and `clause` (the rule-set clause behind the mark). A run is scored once; resubmitting returns "
                      "the stored result. Paste the `run_id` from `GET /api/tasks` into the example below.")
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
        clauses = list(score.driving_clauses)
        if task.ground_truth.kind == "refusal" and score.gate is not None:
            # On a trap not refused for the right reason, the specific clause (GEN-§9.1-9.4) IS the expected reason
            # code. Returning it let a caller probe once and resubmit the same public seed with the right codes
            # (found in a manual test, 2026-10-22). The general refusal clause still says which rule drove the mark.
            clauses = ["GEN-§9"]
        per_task.append({"id": task_id, "tier": task.difficulty, "score": round(score.total, 4), "breakdown": breakdown,
                         "clause": clauses[0] if clauses else None,
                         "clauses": clauses, "gate": score.gate, "answered": task_id in answers})
    response = {"run_id": body.run_id, "ruleset_version": spec.ruleset_version, "seed": spec.seed, "tier_mix": spec.tier_mix,
                "n_tasks": len(tasks), "n_answered": len(set(answers) & set(tasks)), "unknown_ids": unknown,
                "mean_reward": round(total / len(tasks), 4) if tasks else None, "per_task": per_task}
    # The same public seed regenerates the same tasks (comparability), so per-task feedback from one run could steer a
    # second run on that seed. A repeat is still scored, but marked, so the external leaderboard shows it.
    seed_key = f"seed:{spec.seed}:{spec.tier_mix}:{spec.n}"
    repeat_seed = store.incr_window(seed_key, 60 * 60 * 24 * 30) > 1
    response["repeat_seed"] = repeat_seed
    summary = {"run_id": body.run_id, "ruleset_version": spec.ruleset_version, "seed": spec.seed, "tier_mix": spec.tier_mix,
               "n_tasks": len(tasks), "mean_reward": response["mean_reward"], "external": True, "repeat_seed": repeat_seed,
               "submitted_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
    if not store.put_run_once(body.run_id, {"response": response, "summary": summary, "answers": answers,
                                            "scored_at": time.time()}):
        stored = store.get_run(body.run_id)  # a concurrent submit of the same run won; return its result
        return {**stored["response"], "note": "already scored; returning the stored result"}
    return response


@app.get("/api/runs/{run_id}", tags=["3. Results"], summary="Read back a scored run",
         description="The stored response and the submitted answers for a run (kept 30 days). 404 until the run is submitted.")
@app.get("/runs/{run_id}", include_in_schema=False)
def get_run(request: Request, run_id: str = Path(description="The signed `run_id` from `GET /api/tasks`.")):
    _limit(request, "read")
    _spec(run_id)
    stored = store.get_run(run_id)
    if stored is None:
        raise HTTPException(404, "run not submitted yet")
    return {"response": stored["response"], "answers": stored["answers"]}


@app.get("/api/leaderboard", tags=["3. Results"], summary="Recent external runs (shown on the dashboard)",
         description="Newest first: run id, rule-set version, seed, tier mix, tasks, mean reward, `repeat_seed`, time.")
@app.get("/leaderboard", include_in_schema=False)
def leaderboard(request: Request, limit: int = Query(100, ge=1, le=500, description="How many runs to return (1–500).", examples=[10])):
    _limit(request, "read")
    return {"runs": store.list_runs(limit), "note": "external runs submitted through the sandbox"}


@app.post("/api/tools/{name}", tags=["2. Tool mode"], summary="Call a tool for one task of a run",
          description="Tools: `get_employee_record` (the task's documents, as stated), `lookup_rules` (rule text + that year's rate "
                      "table, or none), `get_fx_rate` (month-end rates only), `calc` (exact decimal arithmetic: + − × ÷, min, max, "
                      "abs, round). Bad arguments return a structured error, so an agent can recover.")
def call_tool(request: Request, body: ToolCall,
              name: str = Path(description="`get_employee_record`, `lookup_rules`, `get_fx_rate` or `calc`.", examples=["calc"])):
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
