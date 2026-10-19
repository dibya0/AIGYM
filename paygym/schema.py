"""Versioned task schema (brief Phase 01).

A task is either a *retrieval* question about the rule set (Tier 1) or a *payslip case*
(Tiers 2–3). Ground truth is always machine-checkable and is recomputed from the case by
``paygym validate``; it is never written by hand or by a model.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Annotated, Callable, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from paygym.reference.inputs import PayslipCase

SCHEMA_VERSION = "1.0"

ReasonCode = Literal["MISSING_INPUT", "CONFLICTING_RECORDS", "NO_APPLICABLE_TABLE", "UNSUPPORTED_CURRENCY"]


class _Model(BaseModel):
    # extra="forbid": a task written under a newer schema fails loudly here instead of being
    # silently half-read (schema drift, brief p.7).
    model_config = ConfigDict(frozen=True, extra="forbid")


class ValueTruth(_Model):
    """Tier 1: a single rule-set value, e.g. a ceiling. Exact match (tolerance from GEN-§1.4)."""

    kind: Literal["value"] = "value"
    value: Decimal
    unit: str  # currency code, "rate" or "fx_rate"
    tolerance: Decimal
    clauses: tuple[str, ...]


class PayslipTruth(_Model):
    """Tier 2: every payslip line, rounded per GEN-§1.3, with the clauses behind each line."""

    kind: Literal["payslip"] = "payslip"
    currency: str
    tolerance: Decimal  # one minor unit (GEN-§1.4)
    lines: dict[str, Decimal]
    line_clauses: dict[str, tuple[str, ...]]


class RefusalTruth(_Model):
    """Tier 3: the rules do not determine the payslip (GEN-§9); the correct output is a refusal."""

    kind: Literal["refusal"] = "refusal"
    reason_code: ReasonCode
    inputs: tuple[str, ...]
    clause: str


GroundTruth = Annotated[Union[ValueTruth, PayslipTruth, RefusalTruth], Field(discriminator="kind")]


class Lookup(_Model):
    """What a retrieval task asks for: a rate-table field, or an FX rate."""

    jurisdiction: Literal["VAL", "KES", "NRD"]
    year: int
    field: str  # a RateTable field name, or "fx:USD" / "fx:EUR"


class TrapReason(_Model):
    """Why a Tier-3 task is a trap, in the brief's three categories (p.10)."""

    category: Literal["input_absent", "records_contradictory", "rules_silent"]
    reason_code: ReasonCode
    clause: str
    explanation: str


class Task(_Model):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    slice: Literal["gross_to_net"] = "gross_to_net"
    difficulty: Literal[1, 2, 3]
    prompt: str
    context_files: tuple[str, ...] = ()  # rule-set sections attached in single-turn mode, e.g. "ruleset:VAL"
    employee_id: str | None = None  # tool mode: the only handle the agent gets (data comes from tools)
    case: PayslipCase | None = None
    documents: dict[str, dict[str, str]] = {}  # per-source non-input facts shown to the agent (name, job title)
    lookup: Lookup | None = None
    ground_truth: GroundTruth
    verifier: Literal["value_match", "payslip_lines", "refusal"]
    tags: tuple[str, ...] = ()
    ruleset_version: str
    twin_of: str | None = None
    trap_reason: TrapReason | None = None
    provenance: Literal["hand_written", "generated"]
    seed: int | None = None
    hand_check: dict[str, str] | None = None  # values worked out by hand from RULESET.md (seed tasks)

    @model_validator(mode="after")
    def _consistent(self) -> "Task":
        kind = self.ground_truth.kind
        expected_verifier = {"value": "value_match", "payslip": "payslip_lines", "refusal": "refusal"}[kind]
        if self.verifier != expected_verifier:
            raise ValueError(f"verifier {self.verifier!r} does not match ground truth kind {kind!r}")
        if kind == "value":
            if self.lookup is None or self.difficulty != 1:
                raise ValueError("value tasks need a lookup and are Tier 1")
        elif self.case is None:
            raise ValueError("payslip and refusal tasks need a case")
        if (kind == "refusal") != (self.difficulty == 3):
            raise ValueError("Tier 3 is exactly the refusal (trap) tasks")
        if kind == "refusal" and self.trap_reason is None:
            raise ValueError("every trap records why it is a trap (brief p.10)")
        if self.trap_reason is not None and self.trap_reason.reason_code != self.ground_truth.reason_code:
            raise ValueError("trap_reason and ground truth disagree")
        return self


# --------------------------------------------------------------------------- schema drift

# Upgrades from older schema versions, keyed by the version they upgrade *from*.
# Results record the schema version of their taskset, and the eval harness and dashboard
# refuse to compare runs across versions (brief p.7 edge case "schema drift").
MIGRATIONS: dict[str, Callable[[dict], dict]] = {}


def load_task(raw: dict | str) -> Task:
    data = json.loads(raw) if isinstance(raw, str) else dict(raw)
    version = str(data.get("schema_version", ""))
    seen = set()
    while version != SCHEMA_VERSION:
        if version in seen or version not in MIGRATIONS:
            raise ValueError(f"unsupported task schema_version {version!r} (this code reads {SCHEMA_VERSION!r})")
        seen.add(version)
        data = MIGRATIONS[version](data)
        version = str(data.get("schema_version", ""))
    return Task.model_validate(data)


def dump_task(task: Task) -> str:
    return task.model_dump_json(exclude_none=True)


def json_schema() -> dict:
    return Task.model_json_schema()
