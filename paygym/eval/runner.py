"""Eval harness (brief Phase 05).

    uv run python -m paygym.eval --model groq/openai/gpt-oss-120b --tier all --rollouts 3 --seed 7 --max-cost 2.00

Every rollout is executed by the verifiers environment (``env.run_rollout``: prompts, tools, turn limit,
timeout, rubric), the same environment the trainer and the sandbox use. This harness adds what the
brief asks of a runner:

  * bounded concurrency plus a per-provider request-rate limit (free tiers);
  * a daily *request* ledger per free-tier model (``paygym.eval.budget``): a run stops cleanly with
    ``aborted_budget`` before it would exceed the day's cap, and resumes the next day;
  * a hard ``--max-cost`` guardrail at list prices: once reached, no new rollouts start, in-flight
    ones finish, partial results are written, and the run is marked ``aborted_cost``;
  * resume: rollouts already in ``transcript.jsonl`` are skipped, so a crash never pays twice;
  * retries with backoff on rate limits / 5xx / timeouts, each retried rollout marked ``retried``;
  * a provider that keeps failing is marked ``unavailable`` and the run stops cleanly;
  * per run: config.json, transcript.jsonl, metrics.json, scores.json.

Provider / API failures are recorded with ``status="error"`` and excluded from means (reported
separately). Model behaviour (bad JSON, tool loops, hitting the turn limit or the timeout) is
*scored* (it is what the gym measures) and flagged via ``stop_condition``.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import random
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

from paygym import __version__
from paygym.eval.budget import RequestLedger, cap_for
from paygym.eval.providers import ModelSpec, resolve
from paygym.eval.stats import percentile, run_summary
from paygym.prompting import prompt_hash
from paygym.rubric import RUBRIC_VERSION, score_answer
from paygym.ruleset import load_ruleset
from paygym.schema import SCHEMA_VERSION, Task

TRANSIENT = ("429", "rate limit", "rate_limit", "ratelimit", "500", "502", "503", "504", "overloaded",
             "timeout", "timed out", "temporarily", "connection", "unavailable")


# --------------------------------------------------------------------------- helpers


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")


def _git_sha() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return None


def _error_text(err) -> str | None:
    if not err:
        return None
    if isinstance(err, dict):
        return f"{err.get('error', '')}: {err.get('message', '')}".strip(": ")
    return str(err)


def _is_transient(text: str) -> bool:
    low = text.lower()
    return any(marker in low for marker in TRANSIENT)


def _info(row) -> dict:
    info = row["info"]
    return json.loads(info) if isinstance(info, str) else dict(info)


def _compact_prompt(prompt: list[dict], mode: str) -> list[dict]:
    """Transcripts keep the full conversation, except that the attached rule-set text in single-turn mode
    (identical across tasks, ~14 kB) is replaced by a marker; it is reproducible from context_files."""
    if mode != "single":
        return prompt
    out = []
    for msg in prompt:
        content = msg.get("content", "")
        if msg.get("role") == "user" and "\n\n---\n\n" in content:
            content = "[rule-set sections from context_files omitted]\n\n---\n\n" + content.split("\n\n---\n\n", 1)[1]
        out.append({**msg, "content": content})
    return out


class RateLimiter:
    def __init__(self, rpm: int):
        self.interval = 60.0 / rpm if rpm and rpm > 0 else 0.0
        self.next_at = 0.0
        self.lock = asyncio.Lock()

    async def wait(self) -> None:
        if not self.interval:
            return
        async with self.lock:
            now = time.monotonic()
            delay = max(0.0, self.next_at - now)
            self.next_at = max(now, self.next_at) + self.interval
        if delay:
            await asyncio.sleep(delay)


# --------------------------------------------------------------------------- the run


class EvalRun:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.spec: ModelSpec = resolve(args.model, args.base_url, args.api_key_var, args.rpm, args.paid)
        from paygym.environment import load_environment

        self.env = load_environment(mode=args.mode, split=args.split, n_seeds=args.n_seeds, tasks_path=args.tasks,
                                    tier=args.tier, max_turns=args.max_turns, timeout_seconds=args.timeout,
                                    use_judge=args.judge, scaffold=args.scaffold)
        if args.scaffold:
            from paygym.prompting import SCAFFOLDS

            args.mode = SCAFFOLDS[args.scaffold]["mode"]
        rows = list(self.env.get_eval_dataset())
        if args.limit:
            rows = rows[: args.limit]
        self.rows = rows
        self.tasks = {(_info(r)["task_id"]): Task.model_validate_json(_info(r)["task_json"]) for r in rows}
        self.taskset_hash = hashlib.sha256(
            "\n".join(sorted(_info(r)["task_json"] for r in rows)).encode()).hexdigest()[:16]
        name = args.run_name or f"{args.mode}-{args.split if not args.tasks else Path(args.tasks).stem}-{_now()}"
        self.dir = Path(args.resume) if args.resume else Path(args.out) / self.spec.slug / name
        self.transcript = self.dir / "transcript.jsonl"
        self.write_lock = asyncio.Lock()
        self.limiter = RateLimiter(self.spec.rpm)
        uncapped = self.spec.is_baseline or self.spec.provider == "local"
        self.ledger = None if uncapped else RequestLedger(self.spec.name, cap_for(self.spec.provider, args.daily_request_cap))
        self.judge_ledger = None
        if args.judge:
            from paygym.judge import DEFAULT_MODEL as JUDGE_MODEL

            self.judge_ledger = RequestLedger(f"gemini/{JUDGE_MODEL}", cap_for("gemini", args.daily_request_cap))
        self.cost_list = 0.0
        self.abort: str | None = None
        self.consecutive_errors = 0
        self.started = time.time()

    # ---------------------------------------------------------------- config / resume

    def config(self) -> dict:
        ruleset = load_ruleset()
        from importlib.metadata import version as pkg_version

        cfg = {
            "model": self.spec.name, "provider": self.spec.provider, "model_id": self.spec.model_id,
            "base_url": self.spec.base_url, "free_tier": self.spec.free_tier, "list_price_usd_per_mtok": self.spec.price,
            "mode": self.args.mode, "scaffold": self.args.scaffold, "split": self.args.split, "tasks_path": self.args.tasks, "n_seeds": self.args.n_seeds,
            "tier": self.args.tier, "limit": self.args.limit, "n_tasks": len(self.rows), "rollouts": self.args.rollouts,
            "seed": self.args.seed, "sampling": self.sampling_args(), "max_turns": self.args.max_turns,
            "timeout_s": self.args.timeout, "max_cost_usd": self.args.max_cost, "concurrency": self.args.concurrency,
            "judge": self.args.judge, "taskset_hash": self.taskset_hash, "task_seeds": sorted(
                t.seed for t in self.tasks.values() if t.seed is not None),
            "schema_version": SCHEMA_VERSION, "ruleset_version": ruleset.version,
            "ruleset_fingerprint": ruleset.fingerprint, "rubric_version": RUBRIC_VERSION,
            "prompt_hash": prompt_hash(self.args.scaffold), "paygym_version": __version__, "verifiers_version": pkg_version("verifiers"),
            "git_sha": _git_sha(), "python": platform.python_version(),
        }
        if self.args.judge:
            from paygym.judge import DEFAULT_MODEL, prompt_hash as judge_hash

            cfg.update(judge_model=DEFAULT_MODEL, judge_prompt_hash=judge_hash())
        return cfg

    def provenance(self) -> dict:
        """Stamped into every result file (brief: seed and rule-set version "recorded in every result file")."""
        rs = load_ruleset()
        return {"model": self.spec.name, "seed": self.args.seed, "task_seeds": sorted(t.seed for t in self.tasks.values() if t.seed is not None),
                "taskset_hash": self.taskset_hash, "ruleset_version": rs.version, "ruleset_fingerprint": rs.fingerprint,
                "rubric_version": RUBRIC_VERSION, "schema_version": SCHEMA_VERSION}

    def sampling_args(self) -> dict:
        args = {"temperature": self.args.temperature, "max_tokens": self.args.max_tokens}
        if self.args.seed is not None and self.spec.provider not in ("gemini",):  # Gemini's compat layer rejects seed
            args["seed"] = self.args.seed
        return args

    def load_done(self) -> dict[tuple[str, int], dict]:
        done: dict[tuple[str, int], dict] = {}
        if self.transcript.exists():
            for line in self.transcript.read_text().splitlines():
                if line.strip():
                    row = json.loads(line)
                    done[(row["task_id"], row["rollout"])] = row  # last line per key wins
        return done

    # ---------------------------------------------------------------- one rollout

    async def one(self, index: int, row: dict, rollout: int) -> None:
        if self.abort:
            return
        info = _info(row)
        task = self.tasks[info["task_id"]]
        record = {"task_id": task.id, "rollout": rollout, "example_id": index, "task_seed": task.seed, "seed": self.args.seed,
                  "ruleset_version": task.ruleset_version,
                  "difficulty": task.difficulty, "kind": task.ground_truth.kind, "retried": 0,
                  "started_at": datetime.now(timezone.utc).isoformat()}
        if self.spec.is_baseline:
            record.update(self._baseline(task))
        else:
            result = await self._model_rollout(index, row, rollout)
            if result is None:  # daily budget reached before the call: left for a resumed run
                return
            record.update(result)
        await self.write(record)

    def _baseline(self, task: Task) -> dict:
        from paygym.baselines import BASELINES

        text = BASELINES[self.spec.model_id](task)
        score = score_answer(task, text)
        return {"status": "ok", "reward": score.total, "metrics": {c.name: c.score for c in score.components},
                "gate": score.gate, "driving_clauses": score.driving_clauses, "stop_condition": "baseline",
                "latency_s": 0.0, "input_tokens": 0, "output_tokens": 0, "cost_list_usd": 0.0, "tool_calls": 0,
                "completion": [{"role": "assistant", "content": text}]}

    async def _model_rollout(self, index: int, row: dict, rollout: int) -> dict:
        from verifiers.types import ClientConfig

        if self.spec.provider == "local":
            os.environ.setdefault("LOCAL_API_KEY", "local")  # vLLM accepts any key
        client = ClientConfig(api_key_var=self.spec.api_key_var or "LOCAL_API_KEY", api_base_url=self.spec.base_url,
                              max_retries=0, timeout=float(self.args.timeout) + 30)
        rollout_input = {"prompt": row["prompt"], "example_id": index, "answer": row.get("answer", ""), "info": row["info"]}
        retried, out, err = 0, None, None
        per_attempt = self.args.max_turns if self.args.mode == "tool" else 1
        for attempt in range(self.args.max_retries + 1):
            if self.abort:
                return None
            # A trap rollout may need the judge (one call per criterion); never start a model call whose
            # judging would then be refused, or the model call is wasted.
            if self.judge_ledger and self.judge_ledger.remaining() is not None and self.judge_ledger.remaining() < 3:
                self.abort = "aborted_budget"
                return None
            if self.ledger and not self.ledger.reserve(per_attempt):
                self.abort = "aborted_budget"
                return None
            await self.limiter.wait()
            try:
                out = await self.env.run_rollout(rollout_input, client, self.spec.model_id, self.sampling_args())
                err = _error_text(out.get("error"))
            except Exception as exc:  # the environment raised instead of recording the error
                out, err = None, f"{type(exc).__name__}: {exc}"
            if self.ledger:
                turns = int(((out or {}).get("metrics") or {}).get("num_turns") or 1)
                self.ledger.settle(per_attempt, min(per_attempt, max(1, turns)))
            if err and _is_transient(err) and attempt < self.args.max_retries:
                retried += 1
                await asyncio.sleep(min(60.0, 2.0 ** attempt + random.random()))
                continue
            break

        usage = (out or {}).get("token_usage") or {}
        tin, tout = float(usage.get("input_tokens", 0) or 0), float(usage.get("output_tokens", 0) or 0)
        cost = self.spec.cost_usd(tin, tout)
        self.cost_list += cost
        if self.cost_list >= self.args.max_cost and not self.abort:
            self.abort = "aborted_cost"
        if err:
            self.consecutive_errors += 1
            if self.consecutive_errors >= self.args.max_consecutive_errors and not self.abort:
                self.abort = "unavailable"
        else:
            self.consecutive_errors = 0
        timing = (out or {}).get("timing") or {}
        metrics = (out or {}).get("metrics") or {}
        info = _info(row)
        score = None
        if out is not None and not err:
            task = self.tasks[info["task_id"]]
            # The env already scored the rollout; re-derive the gate and clauses for the transcript (same scorer).
            from paygym.environment import completion_text

            score = score_answer(task, completion_text(out.get("completion")))
        return {
            "status": "error" if err else "ok",
            "error": err,
            "retried": retried,
            "reward": (out or {}).get("reward") if not err else None,
            "metrics": metrics,
            "gate": score.gate if score else None,
            "driving_clauses": score.driving_clauses if score else None,
            "stop_condition": (out or {}).get("stop_condition"),
            "is_truncated": (out or {}).get("is_truncated"),
            "latency_s": round(float(((timing.get("model") or {}).get("duration")) or timing.get("total") or 0.0), 3),
            "input_tokens": tin, "output_tokens": tout, "cost_list_usd": round(cost, 6),
            "tool_calls": metrics.get("total_tool_calls", 0),
            "prompt": _compact_prompt(row["prompt"], self.args.mode),
            "completion": (out or {}).get("completion"),
        }

    async def write(self, record: dict) -> None:
        line = json.dumps(record, default=str)
        async with self.write_lock:
            with self.transcript.open("a") as fh:
                fh.write(line + "\n")
                fh.flush()

    # ---------------------------------------------------------------- driver

    async def run(self) -> int:
        self.dir.mkdir(parents=True, exist_ok=True)
        cfg = self.config()
        cfg_path = self.dir / "config.json"
        if cfg_path.exists():
            old = json.loads(cfg_path.read_text())
            for key in ("model", "taskset_hash", "mode", "ruleset_fingerprint", "rubric_version", "prompt_hash"):
                if old.get(key) != cfg.get(key):
                    print(f"refusing to resume: {key} changed ({old.get(key)} -> {cfg.get(key)})", file=sys.stderr)
                    return 4
        cfg_path.write_text(json.dumps(cfg, indent=2, default=str))

        done = {k for k, v in self.load_done().items() if v.get("status") == "ok"}
        work = [(i, row, r) for r in range(self.args.rollouts) for i, row in enumerate(self.rows)
                if (_info(row)["task_id"], r) not in done]
        planned = len(self.rows) * self.args.rollouts
        est = self.estimate_cost(len(work))
        for led in (self.ledger, self.judge_ledger):
            if led and led.cap is not None:
                print(f"daily request budget {led.model}: {led.used_today()}/{led.cap} used today (US Pacific)")
        print(f"{self.spec.name}: {len(self.rows)} tasks x {self.args.rollouts} rollouts = {planned} "
              f"({len(done)} already done, {len(work)} to run); list-price estimate ${est:.2f}, cap ${self.args.max_cost:.2f}"
              + ("  [baseline: no model calls]" if self.spec.is_baseline else ""))
        if not self.spec.is_baseline and self.spec.api_key_var and self.spec.provider != "local" and not os.environ.get(self.spec.api_key_var):
            print(f"{self.spec.api_key_var} is not set", file=sys.stderr)
            return 5

        sem = asyncio.Semaphore(self.args.concurrency)

        async def guarded(i, row, r):
            async with sem:
                await self.one(i, row, r)

        await asyncio.gather(*(guarded(i, row, r) for i, row, r in work))
        status = self.abort or "completed"
        self.finalise(status, planned)
        print(f"{status}: results in {self.dir}")
        if status == "aborted_budget":
            print("daily request budget reached: re-run the same command with --resume tomorrow", file=sys.stderr)
        return {"completed": 0, "aborted_cost": 2, "unavailable": 3, "aborted_budget": 6}[status]

    def estimate_cost(self, n: int) -> float:
        if self.spec.is_baseline or not n:
            return 0.0
        avg_in = mean(len(json.dumps(r["prompt"])) / 4 for r in self.rows)
        turns = self.args.max_turns if self.args.mode == "tool" else 1
        return n * self.spec.cost_usd(avg_in * (2 if turns > 1 else 1), 1200)

    # ---------------------------------------------------------------- outputs

    def finalise(self, status: str, planned: int) -> None:
        rows = list(self.load_done().values())
        ok = [r for r in rows if r["status"] == "ok"]
        summary = run_summary(rows)

        per_task: dict[str, dict] = {}
        for r in rows:
            t = per_task.setdefault(r["task_id"], {"difficulty": r["difficulty"], "kind": r["kind"],
                                                    "task_seed": r.get("task_seed"), "rewards": [], "gates": [],
                                                    "statuses": [], "components": {}})
            t["statuses"].append(r["status"])
            if r["status"] == "ok":
                t["rewards"].append(r["reward"])
                t["gates"].append(r.get("gate"))
                for name, value in (r.get("metrics") or {}).items():
                    t["components"].setdefault(name, []).append(value)
        for t in per_task.values():
            rs = t["rewards"]
            t["mean"] = round(mean(rs), 4) if rs else None
            t["sd"] = round((sum((x - mean(rs)) ** 2 for x in rs) / len(rs)) ** 0.5, 4) if len(rs) > 1 else (0.0 if rs else None)
            t["components"] = {k: round(mean(v), 4) for k, v in t["components"].items() if v}

        def mean_where(pred):
            vals = [t["mean"] for t in per_task.values() if t["mean"] is not None and pred(t)]
            return round(mean(vals), 4) if vals else None

        component_names = sorted({k for r in ok for k in (r.get("metrics") or {})})
        stamp = self.provenance()
        scores = {
            **stamp,
            "summary": summary,
            "by_tier": {str(d): mean_where(lambda t, d=d: t["difficulty"] == d) for d in (1, 2, 3)},
            "by_component": {n: round(mean([r["metrics"][n] for r in ok if n in (r.get("metrics") or {})]), 4)
                             for n in component_names},
            "gates": dict(Counter(r.get("gate") or "none" for r in ok)),
            "per_task": per_task,
        }
        # Twins (determinable look-alikes of traps) separately: a low twin score means over-refusal.
        twin_ids = {t.id for t in self.tasks.values() if t.twin_of}
        twin_means = [per_task[i]["mean"] for i in twin_ids if i in per_task and per_task[i]["mean"] is not None]
        scores["twins"] = round(mean(twin_means), 4) if twin_means else None
        (self.dir / "scores.json").write_text(json.dumps(scores, indent=2, default=str))

        latencies = [r["latency_s"] for r in ok if r.get("latency_s")]
        tool_calls = [r.get("tool_calls") or 0 for r in ok]
        metrics = {
            **stamp,
            "status": status,
            "rollouts_planned": planned,
            "rollouts_recorded": len(rows),
            "rollouts_ok": len(ok),
            "rollouts_error": sum(1 for r in rows if r["status"] == "error"),
            "retried_rollouts": sum(1 for r in rows if r.get("retried")),
            "errors_sample": [r.get("error") for r in rows if r["status"] == "error"][:5],
            "input_tokens": sum(r.get("input_tokens") or 0 for r in rows),
            "output_tokens": sum(r.get("output_tokens") or 0 for r in rows),
            "cost_list_usd": round(sum(r.get("cost_list_usd") or 0 for r in rows), 4),
            "cost_actual_usd": 0.0 if self.spec.free_tier else round(sum(r.get("cost_list_usd") or 0 for r in rows), 4),
            "latency_s": {"mean": round(mean(latencies), 3) if latencies else None,
                          "p50": percentile(latencies, 0.5), "p95": percentile(latencies, 0.95)},
            "tool_calls_total": sum(tool_calls),
            "tool_calls_mean": round(mean(tool_calls), 3) if tool_calls else None,
            "stop_conditions": dict(Counter(r.get("stop_condition") or "none" for r in ok)),
            "parse_fail_rate": round(mean([(r.get("metrics") or {}).get("parse_failed", 0.0) for r in ok]), 4) if ok else None,
            "wall_clock_s": round(time.time() - self.started, 1),
        }
        (self.dir / "metrics.json").write_text(json.dumps(metrics, indent=2, default=str))


# --------------------------------------------------------------------------- CLI


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m paygym.eval", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", required=True, help="e.g. groq/openai/gpt-oss-120b, gemini/<model>, local/<served-name>, baseline/<name>")
    ap.add_argument("--mode", choices=["single", "tool"], default="single")
    ap.add_argument("--scaffold", choices=["S0", "S1", "S2", "S3", "S4"], help="Track C scaffold (fixes --mode)")
    ap.add_argument("--split", default="eval", choices=["eval", "heldout", "val", "train"])
    ap.add_argument("--n-seeds", type=int, default=95)
    ap.add_argument("--tasks", help="task .jsonl file or directory instead of generating the split")
    ap.add_argument("--tier", default="all", help='"all" or e.g. "2,3"')
    ap.add_argument("--limit", type=int, help="only the first N tasks (debugging)")
    ap.add_argument("--rollouts", type=int, default=3)
    ap.add_argument("--seed", type=int, default=7, help="sampling seed where the provider supports it")
    ap.add_argument("--temperature", type=float, default=1.0)
    ap.add_argument("--max-tokens", type=int, default=4096)
    ap.add_argument("--max-turns", type=int, default=8)
    ap.add_argument("--timeout", type=float, default=180.0, help="per-rollout wall-clock limit (s)")
    ap.add_argument("--max-cost", type=float, default=2.00, help="hard cap in USD at list prices")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--rpm", type=int, help="requests per minute (default per provider)")
    ap.add_argument("--daily-request-cap", type=int,
                    help="max requests per model per day across all runs (0 = no cap; default per provider, see paygym.eval.budget)")
    ap.add_argument("--max-retries", type=int, default=4)
    ap.add_argument("--max-consecutive-errors", type=int, default=8, help="mark the provider unavailable after this many")
    ap.add_argument("--judge", action="store_true", help="score trap explanations with the LLM judge (GEMINI_API_KEY)")
    ap.add_argument("--base-url")
    ap.add_argument("--api-key-var")
    ap.add_argument("--paid", action="store_true", help="count list-price cost as actual spend")
    ap.add_argument("--out", default="results")
    ap.add_argument("--run-name")
    ap.add_argument("--resume", help="an existing run directory to continue")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.rollouts < 1:
        raise SystemExit("--rollouts must be >= 1")
    try:
        from dotenv import load_dotenv  # optional convenience

        load_dotenv()
    except ImportError:
        pass
    return asyncio.run(EvalRun(args).run())
