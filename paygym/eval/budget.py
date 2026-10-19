"""Daily free-tier ledger: hard caps on requests *and* tokens per model per day, shared by every eval run,
the judge and the probe script.

Free tiers are rationed per model per day (Gemini resets at midnight US Pacific), and the owner of the
keys wants to keep headroom on them. ``--max-cost`` is in list-price dollars, which is $0 of real
spend and so never protects a free quota. This ledger counts what the providers actually ration:

  * one JSON file (``results/.request_ledger.json``, gitignored) keyed by Pacific date and model,
    ``{"requests": n, "tokens": t}``;
  * ``reserve(requests, tokens)`` before a call refuses (returns False) if either daily count would
    exceed its cap;
  * ``settle(...)`` afterwards replaces the reservation with what was really used, so the counts are
    exact, not estimates;
  * caps default to ``CAP_FRACTION`` of the free limits in ``FREE_TIER_LIMITS``;
    ``--daily-request-cap`` / ``PAYGYM_DAILY_CAP`` override the request cap (0 = none).

Local models and baselines are never capped. The sandbox does not use this (its judge budget is per
caller IP in Redis).
"""

from __future__ import annotations

import fcntl
import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# Free-tier limits as shown on the user's own dashboards on 2026-10-19 (AI Studio "Rate limits by model";
# console.groq.com/settings/limits). rpm / rpd = requests per minute / day; tpm / tpd = tokens.
FREE_TIER_LIMITS: dict[str, dict[str, int]] = {
    "gemini/gemini-3.8-flash": {"rpm": 5, "rpd": 20, "tpm": 250_000},
    "gemini/gemini-3.5-flash-lite": {"rpm": 15, "rpd": 500, "tpm": 250_000},
    "gemini/gemini-3.1-flash-lite": {"rpm": 15, "rpd": 500, "tpm": 250_000},
    "gemini/gemma-4-31b-it": {"rpm": 30, "rpd": 14_400, "tpm": 16_000},
    "groq/openai/gpt-oss-120b": {"rpm": 30, "rpd": 1_000, "tpm": 8_000, "tpd": 200_000},
    "groq/openai/gpt-oss-20b": {"rpm": 30, "rpd": 1_000, "tpm": 8_000, "tpd": 200_000},
    "groq/qwen/qwen3.8-27b": {"rpm": 30, "rpd": 1_000, "tpm": 8_000, "tpd": 200_000},
}
# Unknown hosted models get the strictest limits seen for that provider, so a typo never drains a quota.
UNKNOWN_LIMITS = {"gemini": {"rpm": 5, "rpd": 20, "tpm": 250_000},
                  "groq": {"rpm": 30, "rpd": 1_000, "tpm": 8_000, "tpd": 200_000}}
# 0.9 (was 0.75): the user chose a faster sweep (one day for the hosted part) over a larger reserve;
# 10% of every daily quota still stays untouched for the owner's own use.
CAP_FRACTION = 0.9
# Providers bill more tokens than their usage field reports (hidden reasoning tokens). Measured
# 2026-10-19: Groq's own TPD counter said 197K when the summed `usage` of our requests was 143K (ratio 1.38),
# so its 200K/day cap was hit while our ledger showed 143K/180K. Token counts are scaled by this factor.
TOKEN_BILLING_FACTOR = {"groq": 1.4}


@dataclass(frozen=True)
class Caps:
    requests: int | None  # per day
    tokens: int | None  # per day
    rpm: int  # 0 = no pacing
    tpm: int  # 0 = no pacing


def limits_for(model: str) -> dict[str, int]:
    return FREE_TIER_LIMITS.get(model) or UNKNOWN_LIMITS.get(model.split("/", 1)[0], {})


def caps_for(model: str, request_override: int | None = None) -> Caps | None:
    """Daily caps and pacing for a hosted model ("gemini/<id>", "groq/<id>"); None = uncapped."""
    if model.split("/", 1)[0] not in UNKNOWN_LIMITS:
        return None
    lim = limits_for(model)
    if request_override is None and os.environ.get("PAYGYM_DAILY_CAP"):
        request_override = int(os.environ["PAYGYM_DAILY_CAP"])
    requests = int(lim["rpd"] * CAP_FRACTION) if "rpd" in lim else None
    if request_override is not None:
        requests = request_override or None
    tokens = int(lim["tpd"] * CAP_FRACTION) if "tpd" in lim else None
    rpm = max(1, lim["rpm"] - 1) if lim.get("rpm") else 0  # one below the limit
    return Caps(requests, tokens, rpm, lim.get("tpm", 0))


def _today() -> str:
    return datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()


def _entry(day: dict, model: str) -> dict:
    value = day.get(model, {})
    if isinstance(value, int):  # written by the first version of the ledger: requests only
        value = {"requests": value}
    day[model] = {"requests": value.get("requests", 0), "tokens": value.get("tokens", 0)}
    return day[model]


class RequestLedger:
    def __init__(self, model: str, caps: Caps | None, path: Path | None = None):
        self.model, self.caps = model, caps
        self.path = Path(path or os.environ.get("PAYGYM_LEDGER", "results/.request_ledger.json"))

    @property
    def cap(self) -> int | None:
        return self.caps.requests if self.caps else None

    def _update(self, d_req: int, d_tok: int, check: bool) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a+") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)  # several eval processes may run at once
            fh.seek(0)
            raw = fh.read()
            data = json.loads(raw) if raw.strip() else {}
            entry = _entry(data.setdefault(_today(), {}), self.model)
            if check and self.caps:
                if self.caps.requests is not None and entry["requests"] + d_req > self.caps.requests:
                    return False
                if self.caps.tokens is not None and entry["tokens"] + d_tok > self.caps.tokens:
                    return False
            entry["requests"] = max(0, entry["requests"] + d_req)
            entry["tokens"] = max(0, entry["tokens"] + d_tok)
            fh.seek(0)
            fh.truncate()
            json.dump(data, fh, indent=1, sort_keys=True)
            return True

    def today(self) -> dict:
        if not self.path.exists():
            return {"requests": 0, "tokens": 0}
        raw = self.path.read_text()
        data = json.loads(raw) if raw.strip() else {}
        return _entry(data.get(_today(), {}), self.model)

    def used_today(self) -> int:
        return self.today()["requests"]

    def remaining(self) -> int | None:
        return None if self.cap is None else max(0, self.cap - self.used_today())

    def reserve(self, requests: int = 1, tokens: int = 0) -> bool:
        return self._update(requests, tokens, check=True)

    def settle(self, reserved: int, used: int, reserved_tokens: int = 0, used_tokens: int = 0) -> None:
        used_tokens = int(used_tokens * TOKEN_BILLING_FACTOR.get(self.model.split("/", 1)[0], 1.0))
        if used != reserved or used_tokens != reserved_tokens:
            self._update(used - reserved, used_tokens - reserved_tokens, check=False)

    def describe(self) -> str:
        t, c = self.today(), self.caps
        text = f"{self.model}: requests {t['requests']}/{c.requests if c and c.requests else 'no cap'}"
        if c and c.tokens:
            text += f", tokens {t['tokens']}/{c.tokens}"
        return text + " today (US Pacific)"
