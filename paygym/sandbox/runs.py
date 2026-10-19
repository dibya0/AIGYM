"""Signed run tokens and server-side task sets.

The generator is open source, so a raw generator seed would let any caller recompute the ground truth.
The sandbox therefore never uses or reveals generator seeds directly:

  public seed (shown, recorded)  --HMAC(SANDBOX_SECRET)-->  per-task generator seeds (never shown)

The same public seed + tier mix + n always yields the same task set, so two runs are comparable
(brief P08: "records the rule-set version, the taskset seed, and the tier mix"), but only the server can
compute the answers. ``run_id`` is a signed token carrying those parameters, so the server needs no
database to score a submission. Task ids are opaque positions, never generator ids (which encode seeds).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass

from paygym.generator import Knobs, generate_one
from paygym.ruleset import load_ruleset
from paygym.schema import Task

MAX_TASKS = 50
TOKEN_VERSION = 1


class TokenError(ValueError):
    pass


def _secret() -> bytes:
    secret = os.environ.get("SANDBOX_SECRET", "")
    if len(secret) < 32:
        raise RuntimeError("SANDBOX_SECRET is not configured (need >= 32 characters)")
    return secret.encode()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


@dataclass(frozen=True)
class RunSpec:
    seed: int  # public seed
    tiers: tuple[int, ...]
    n: int
    ruleset_version: str
    issued_at: int

    @property
    def tier_mix(self) -> str:
        return ",".join(str(t) for t in self.tiers)


def sign(spec: RunSpec) -> str:
    payload = _b64(json.dumps({"v": TOKEN_VERSION, "s": spec.seed, "t": list(spec.tiers), "n": spec.n,
                               "rv": spec.ruleset_version, "iat": spec.issued_at}, separators=(",", ":")).encode())
    mac = _b64(hmac.new(_secret(), payload.encode(), hashlib.sha256).digest()[:16])
    return f"{payload}.{mac}"


def verify(token: str) -> RunSpec:
    try:
        payload, mac = token.split(".")
    except (ValueError, AttributeError):
        raise TokenError("malformed run_id") from None
    expected = _b64(hmac.new(_secret(), payload.encode(), hashlib.sha256).digest()[:16])
    if not hmac.compare_digest(mac, expected):
        raise TokenError("run_id signature does not verify")
    data = json.loads(_unb64(payload))
    return RunSpec(seed=int(data["s"]), tiers=tuple(data["t"]), n=int(data["n"]), ruleset_version=str(data["rv"]),
                   issued_at=int(data["iat"]))


def new_spec(seed: int | None, tiers: tuple[int, ...], n: int) -> RunSpec:
    if seed is None:
        seed = int.from_bytes(os.urandom(4), "big")
    return RunSpec(seed=seed, tiers=tiers, n=n, ruleset_version=load_ruleset().version, issued_at=int(time.time()))


def _task_seed(public_seed: int, i: int) -> int:
    digest = hmac.new(_secret(), f"paygym-sandbox:{public_seed}:{i}".encode(), hashlib.sha256).digest()
    return int.from_bytes(digest[:8], "big") % (2**63)


def taskset(spec: RunSpec) -> list[Task]:
    """The run's tasks, regenerated server-side; ids are opaque positions ("000", "001", ...)."""
    tasks: list[Task] = []
    knobs = Knobs()
    i = 0
    while len(tasks) < spec.n:
        for task in generate_one(_task_seed(spec.seed, i), knobs):
            if task.difficulty in spec.tiers and len(tasks) < spec.n:
                tasks.append(task.model_copy(update={"id": f"{len(tasks):03d}", "seed": None, "twin_of": None}))
        i += 1
        if i > spec.n * 40:  # e.g. a tier that the knobs never produce
            break
    return tasks
