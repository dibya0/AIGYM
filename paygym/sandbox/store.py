"""Sandbox storage: run records, the external leaderboard, rate-limit and judge-budget counters.

Ground truth is never stored: it is regenerated from the signed run token on every submit.
Run records are written once per ``run_id`` with an atomic set-if-absent, so two runs writing at the
same time never collide, and resubmitting a run returns the stored result (idempotent).

Backends: Upstash Redis REST (Vercel, free tier), local Redis (docker compose), in-memory (tests).
"""

from __future__ import annotations

import json
import os
import time
from typing import Protocol


class Store(Protocol):
    def incr_window(self, key: str, window_s: int) -> int: ...
    def put_run_once(self, run_id: str, record: dict) -> bool: ...
    def get_run(self, run_id: str) -> dict | None: ...
    def list_runs(self, limit: int = 100) -> list[dict]: ...


LEADERBOARD_KEY = "paygym:leaderboard"
RUN_TTL_S = 60 * 60 * 24 * 30  # run records kept 30 days (free-tier storage)


class MemoryStore:
    def __init__(self):
        self.counters: dict[str, tuple[int, float]] = {}
        self.runs: dict[str, dict] = {}
        self.order: list[str] = []

    def incr_window(self, key: str, window_s: int) -> int:
        now = time.time()
        count, start = self.counters.get(key, (0, now))
        if now - start >= window_s:
            count, start = 0, now
        self.counters[key] = (count + 1, start)
        return count + 1

    def put_run_once(self, run_id: str, record: dict) -> bool:
        if run_id in self.runs:
            return False
        self.runs[run_id] = record
        self.order.insert(0, run_id)
        return True

    def get_run(self, run_id: str) -> dict | None:
        return self.runs.get(run_id)

    def list_runs(self, limit: int = 100) -> list[dict]:
        return [self.runs[r]["summary"] for r in self.order[:limit]]


class RedisStore:
    """Works with redis-py (local) and upstash-redis (REST); both expose incr/expire/set(nx)/get/lpush/lrange."""

    def __init__(self, client):
        self.r = client

    def incr_window(self, key: str, window_s: int) -> int:
        bucket = f"paygym:rl:{key}:{int(time.time() // window_s)}"
        count = int(self.r.incr(bucket))
        if count == 1:
            self.r.expire(bucket, window_s * 2)
        return count

    def put_run_once(self, run_id: str, record: dict) -> bool:
        created = self.r.set(f"paygym:run:{run_id}", json.dumps(record), nx=True, ex=RUN_TTL_S)
        if created:
            self.r.lpush(LEADERBOARD_KEY, json.dumps(record["summary"]))
            self.r.ltrim(LEADERBOARD_KEY, 0, 499)
        return bool(created)

    def get_run(self, run_id: str) -> dict | None:
        raw = self.r.get(f"paygym:run:{run_id}")
        return json.loads(raw) if raw else None

    def list_runs(self, limit: int = 100) -> list[dict]:
        return [json.loads(x) for x in self.r.lrange(LEADERBOARD_KEY, 0, limit - 1)]


def make_store() -> Store:
    # Vercel's Upstash integration names them KV_REST_API_URL / KV_REST_API_TOKEN; Upstash's own docs use
    # UPSTASH_REDIS_REST_URL / _TOKEN. Accept either, so no manual renaming is needed on deploy.
    for a_, b_ in (("UPSTASH_REDIS_REST_URL", "KV_REST_API_URL"), ("UPSTASH_REDIS_REST_TOKEN", "KV_REST_API_TOKEN")):
        if not os.environ.get(a_) and os.environ.get(b_):
            os.environ[a_] = os.environ[b_]
    if os.environ.get("UPSTASH_REDIS_REST_URL") and os.environ.get("UPSTASH_REDIS_REST_TOKEN"):
        from upstash_redis import Redis

        return RedisStore(Redis(url=os.environ["UPSTASH_REDIS_REST_URL"], token=os.environ["UPSTASH_REDIS_REST_TOKEN"]))
    if os.environ.get("REDIS_URL"):
        import redis

        return RedisStore(redis.Redis.from_url(os.environ["REDIS_URL"], decode_responses=True))
    return MemoryStore()  # single-process fallback (tests, quick local runs)
