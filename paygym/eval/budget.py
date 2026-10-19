"""Daily request ledger: a hard cap on free-tier API calls, shared by every eval run and the judge.

Free tiers are rationed per model per day (Gemini resets at midnight US Pacific), and the owner of the
keys wants to keep headroom on them. ``--max-cost`` is in list-price dollars, which is $0 of real
spend and so never protects a free quota. This ledger counts *requests*:

  * one JSON file (``results/.request_ledger.json``, gitignored) keyed by Pacific date and model;
  * ``reserve(n)`` before a call refuses (returns False) if the day's count + n would exceed the cap;
  * ``settle(reserved, used)`` afterwards records what was really used (tool rollouts use fewer
    turns than reserved), so the count is exact, not an estimate;
  * caps: ``--daily-request-cap`` / ``PAYGYM_DAILY_CAP`` (0 = no cap), else the per-provider default.

Local models and baselines are never capped. The sandbox does not use this (its judge budget is per
caller IP in Redis).
"""

from __future__ import annotations

import fcntl
import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# Requests per model per day. Deliberately well under the free limits (Gemini Flash free tier is
# rate-limited per model in the low hundreds/day; Groq gpt-oss-120b ~1k/day), to keep headroom.
DEFAULT_DAILY_CAPS = {"gemini": 120, "groq": 400}


def _today() -> str:
    return datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()


def cap_for(provider: str, override: int | None = None) -> int | None:
    """None = uncapped."""
    if override is None and os.environ.get("PAYGYM_DAILY_CAP"):
        override = int(os.environ["PAYGYM_DAILY_CAP"])
    if override is not None:
        return override or None
    return DEFAULT_DAILY_CAPS.get(provider)


class RequestLedger:
    def __init__(self, model: str, cap: int | None, path: Path | None = None):
        self.model, self.cap = model, cap
        self.path = Path(path or os.environ.get("PAYGYM_LEDGER", "results/.request_ledger.json"))

    def _update(self, delta: int, check: bool) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a+") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)  # several eval processes may run at once
            fh.seek(0)
            raw = fh.read()
            data = json.loads(raw) if raw.strip() else {}
            day = data.setdefault(_today(), {})
            used = day.get(self.model, 0)
            if check and self.cap is not None and used + delta > self.cap:
                return False
            day[self.model] = max(0, used + delta)
            fh.seek(0)
            fh.truncate()
            json.dump(data, fh, indent=1, sort_keys=True)
            return True

    def used_today(self) -> int:
        if not self.path.exists():
            return 0
        raw = self.path.read_text()
        return (json.loads(raw) if raw.strip() else {}).get(_today(), {}).get(self.model, 0)

    def remaining(self) -> int | None:
        return None if self.cap is None else max(0, self.cap - self.used_today())

    def reserve(self, n: int = 1) -> bool:
        return self._update(n, check=True)

    def settle(self, reserved: int, used: int) -> None:
        if used != reserved:
            self._update(used - reserved, check=False)
