"""Clause-provenance trace: every computed value records the rule-set clauses behind it."""

from __future__ import annotations

import functools
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Callable


@dataclass(frozen=True)
class TraceStep:
    name: str
    value: Decimal
    clauses: tuple[str, ...]


@dataclass
class Trace:
    steps: list[TraceStep] = field(default_factory=list)

    def record(self, name: str, value: Decimal, clauses: tuple[str, ...]) -> Decimal:
        self.steps.append(TraceStep(name, value, clauses))
        return value

    def get(self, name: str) -> TraceStep:
        for step in reversed(self.steps):
            if step.name == name:
                return step
        raise KeyError(name)

    def as_dict(self) -> dict[str, dict]:
        return {s.name: {"value": str(s.value), "clauses": list(s.clauses)} for s in self.steps}


def cites(*clauses: str) -> Callable[[Callable[..., Decimal]], Callable[..., Decimal]]:
    """Mark a computation step with the general clauses it implements and record its result.

    Call-time keywords (removed before the wrapped function sees them):
      ``trace``  — the Trace to record into (required);
      ``step``   — record under this name instead of the function name;
      ``also``   — extra clauses that depend on the case, e.g. the jurisdiction's ``VAL-§2.2``.
    """

    def decorate(fn: Callable[..., Decimal]) -> Callable[..., Decimal]:
        default_name = fn.__name__.lstrip("_")

        @functools.wraps(fn)
        def wrapper(*args, trace: Trace, step: str | None = None, also: tuple[str, ...] = (), **kwargs) -> Decimal:
            return trace.record(step or default_name, fn(*args, **kwargs), clauses + tuple(also))

        wrapper.__clauses__ = clauses  # type: ignore[attr-defined]
        return wrapper

    return decorate
