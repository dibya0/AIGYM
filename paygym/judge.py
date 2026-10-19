"""LLM judge for the one genuinely unverifiable part of the gym: whether a trap refusal's written
explanation is useful (brief p.10). It runs only on traps refused with the *correct* reason code;
the decision itself is scored programmatically.

Criteria come from the rule set (GEN-§9: "the correct output is a refusal that gives the reason code
below and identifies the missing, conflicting or unsupported input"). Each is judged in its own
call and returns pass/fail (Harvey LAB pattern), so a failure traces to one criterion. The judge
never produces a free-form score.

Model: Gemini via Google's OpenAI-compatible endpoint (free tier), temperature 0. Override with
PAYGYM_JUDGE_MODEL / PAYGYM_JUDGE_BASE_URL. Results are cached by (prompt hash, criterion, task,
explanation), so identical answers always get identical judge scores; this keeps the sandbox and
the eval consistent (parity) and avoids paying twice.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path

from paygym.parser import ParsedAnswer
from paygym.render import JURISDICTION_NAMES, ruleset_section
from paygym.schema import Task

JUDGE_PROMPT_VERSION = "1"
# Probed 2026-10-19 on the free tier (1.5 s, 500 requests/day). Its own quota bucket: the eval models are
# gemini-3.8-flash and gemini-3.5-flash-lite, so judging never competes with an eval for requests. A pinned
# id, not a "-latest" alias, so the judge cannot silently change between runs.
DEFAULT_MODEL = os.environ.get("PAYGYM_JUDGE_MODEL", "gemini-3.1-flash-lite")
DEFAULT_BASE_URL = os.environ.get("PAYGYM_JUDGE_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")

# Each criterion is derived from GEN-§9 and is answerable pass/fail from the explanation alone.
CRITERIA: dict[str, str] = {
    "names_the_input": (
        "The explanation identifies the specific input (or rate table / currency) that makes the payslip "
        "undetermined. Expected: {inputs_desc}. Synonyms and plain-language descriptions count; a generic "
        "statement such as 'insufficient information' does not."
    ),
    "states_why_rules_do_not_determine": (
        "The explanation states why the rule set cannot determine the payslip in this case, consistent with "
        "this rule: {clause_text}"
    ),
    "actionable_for_operator": (
        "The explanation tells a payroll operator what would have to be obtained or resolved to compute the "
        "payslip (for example: which document to fix, which value to supply, which table or rate is needed)."
    ),
}

SYSTEM = (
    "You grade one criterion of a payroll agent's refusal explanation. You are strict and literal. "
    "Judge only the given criterion. Reply with a single JSON object: "
    '{"pass": true or false, "why": "<one sentence>"}.'
)


class JudgeError(RuntimeError):
    """The judge could not produce a verdict. Recorded as a scoring error, never as a 0."""


def prompt_hash() -> str:
    blob = json.dumps({"v": JUDGE_PROMPT_VERSION, "system": SYSTEM, "criteria": CRITERIA}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def _inputs_desc(task: Task) -> str:
    gt = task.ground_truth
    if gt.reason_code == "NO_APPLICABLE_TABLE":
        return f"the missing {task.case.jurisdiction} rate table for {task.case.year}"
    if gt.reason_code == "UNSUPPORTED_CURRENCY":
        return "the salary currency, which has no exchange rate in the rule set"
    word = {"MISSING_INPUT": "missing", "CONFLICTING_RECORDS": "conflicting between documents"}[gt.reason_code]
    return ", ".join(f"`{name}` ({word})" for name in gt.inputs)


def _clause_text(task: Task) -> str:
    clause = task.ground_truth.clause  # e.g. GEN-§9.2
    general = ruleset_section("ruleset:GEN", task.ruleset_version)
    line = next((ln for ln in general.splitlines() if f"**{clause}" in ln), clause)
    return line.strip("- ").strip()


def build_messages(task: Task, criterion: str, explanation: str) -> list[dict[str, str]]:
    case = task.case
    rubric_line = CRITERIA[criterion].format(inputs_desc=_inputs_desc(task), clause_text=_clause_text(task))
    user = (
        f"Situation: a payroll agent was asked for a {JURISDICTION_NAMES[case.jurisdiction]} payslip for "
        f"{case.pay_period} and correctly refused with reason code {task.ground_truth.reason_code}.\n\n"
        f"Criterion: {rubric_line}\n\n"
        f"Agent's explanation:\n<<<\n{explanation.strip() or '(empty)'}\n>>>\n\n"
        "Does the explanation meet the criterion?"
    )
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


class GeminiJudge:
    """Callable judge for ``paygym.rubric.score_answer(judge=...)``."""

    def __init__(self, model: str = DEFAULT_MODEL, base_url: str = DEFAULT_BASE_URL, api_key: str | None = None,
                 cache_path: str | Path | None = "results/judge_cache.jsonl", use_cache: bool = True, max_retries: int = 4,
                 ledger: bool = True):
        from openai import OpenAI

        key = api_key or os.environ.get("GEMINI_API_KEY")
        if not key:
            raise JudgeError("GEMINI_API_KEY is not set")
        self.client = OpenAI(api_key=key, base_url=base_url)
        self.model, self.max_retries, self.use_cache = model, max_retries, use_cache
        self.json_mode = True  # switched off if the endpoint rejects response_format
        self.calls = 0
        self.ledger = None
        if ledger:  # local runs: count judge calls against the same daily free-tier budget (not the sandbox)
            from paygym.eval.budget import RequestLedger, caps_for

            self.ledger = RequestLedger(f"gemini/{model}", caps_for(f"gemini/{model}"))
        caps = self.ledger.caps if self.ledger else None
        self.min_interval = 60.0 / caps.rpm if caps and caps.rpm else 0.0  # free tiers limit requests/minute
        self._last_call = 0.0
        self.cache_path = Path(cache_path) if cache_path else None
        self.cache: dict[str, dict] = {}
        if self.cache_path and self.cache_path.exists():
            for line in self.cache_path.read_text().splitlines():
                if line.strip():
                    row = json.loads(line)
                    self.cache[row["key"]] = row

    def _key(self, task: Task, criterion: str, explanation: str) -> str:
        blob = json.dumps([prompt_hash(), self.model, criterion, task.id, explanation.strip()])
        return hashlib.sha256(blob.encode()).hexdigest()

    def judge_criterion(self, task: Task, criterion: str, explanation: str) -> dict:
        key = self._key(task, criterion, explanation)
        if self.use_cache and key in self.cache:
            return self.cache[key]
        messages = build_messages(task, criterion, explanation)
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            if self.ledger and not self.ledger.reserve(1):
                raise JudgeError(f"daily request budget for gemini/{self.model} reached ({self.ledger.cap}/day)")
            wait = self._last_call + self.min_interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()
            try:
                self.calls += 1
                extra = {"response_format": {"type": "json_object"}} if self.json_mode else {}
                try:
                    resp = self.client.chat.completions.create(model=self.model, messages=messages, temperature=0, **extra)
                except Exception as exc:
                    if self.json_mode and "response_format" in str(exc):
                        self.json_mode = False  # endpoint lacks JSON mode: the retry parses JSON from text
                    raise
                text = resp.choices[0].message.content or ""
                match = re.search(r"\{.*\}", text, re.DOTALL)
                verdict = json.loads(match.group(0) if match else text)
                if not isinstance(verdict.get("pass"), bool):
                    raise ValueError(f"no boolean 'pass' in {verdict!r}")
                row = {"key": key, "criterion": criterion, "task": task.id, "pass": verdict["pass"],
                       "why": str(verdict.get("why", ""))[:500], "model": self.model, "prompt_hash": prompt_hash()}
                self.cache[key] = row
                if self.cache_path and self.use_cache:
                    self.cache_path.parent.mkdir(parents=True, exist_ok=True)
                    with self.cache_path.open("a") as fh:
                        fh.write(json.dumps(row) + "\n")
                return row
            except Exception as exc:  # rate limits, 5xx, malformed verdicts: retry with backoff
                last_error = exc
                time.sleep(min(30, 2 ** attempt))
        raise JudgeError(f"judge failed after {self.max_retries} attempts: {last_error}")

    def __call__(self, task: Task, parsed: ParsedAnswer) -> tuple[float, str]:
        rows = [self.judge_criterion(task, c, parsed.explanation) for c in CRITERIA]
        passed = sum(r["pass"] for r in rows)
        detail = "; ".join(f"{r['criterion']}={'pass' if r['pass'] else 'fail'}" for r in rows)
        return passed / len(rows), detail
