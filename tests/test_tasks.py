"""Seed taskset + schema tests (brief Phase 01)."""

import importlib.util
import json
from pathlib import Path

import pytest

from paygym.schema import MIGRATIONS, SCHEMA_VERSION, Task, dump_task, load_task
from paygym.validate import validate_path, validate_tasks

ROOT = Path(__file__).resolve().parent.parent
SEED_FILE = ROOT / "tasks" / "seed_v1.jsonl"


def _build_seed():
    spec = importlib.util.spec_from_file_location("build_seed_tasks", ROOT / "scripts" / "build_seed_tasks.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build()


SEED = _build_seed()


def test_seed_meets_brief_minimums():
    """p.7: >=10 hand-checked tasks across three tiers, >=3 Tier-3 traps."""
    assert len(SEED) >= 10
    assert {t.difficulty for t in SEED} == {1, 2, 3}
    assert sum(t.difficulty == 3 for t in SEED) >= 3
    assert all(t.provenance == "hand_written" and t.hand_check for t in SEED)


def test_seed_validates_cleanly():
    """Ground truth == reference, hand checks agree, every trap has a twin."""
    assert validate_tasks(SEED) == []


def test_committed_seed_file_is_current():
    """tasks/seed_v1.jsonl must equal a fresh build (no stale or hand-edited ground truth)."""
    assert SEED_FILE.exists(), "run: uv run python scripts/build_seed_tasks.py"
    assert SEED_FILE.read_text() == "".join(dump_task(t) + "\n" for t in SEED)
    report = validate_path(SEED_FILE)
    assert report.ok, report.errors


def test_traps_cover_all_three_brief_categories():
    """p.10: rules silent, rules self-contradictory, required input absent."""
    categories = {t.trap_reason.category for t in SEED if t.trap_reason}
    assert categories == {"input_absent", "records_contradictory", "rules_silent"}


def test_prompts_never_contain_the_answer():
    """Basic leakage guard: no ground-truth number or reason code appears in the prompt."""
    for t in SEED:
        gt = t.ground_truth
        if gt.kind == "refusal":
            assert gt.reason_code not in t.prompt, t.id
        elif gt.kind == "payslip":
            for line in ("net_pay", "income_tax", "employee_social_insurance"):
                value = gt.lines[line]
                if value > 100:  # small numbers can coincide with ordinary inputs
                    assert f"{value:.2f}" not in t.prompt and f"{value:,.2f}" not in t.prompt, (t.id, line)


def test_hand_check_mismatch_is_caught():
    bad = SEED[3].model_copy(update={"hand_check": {"net_pay": "1.00"}})
    errors = validate_tasks([bad])
    assert any("hand check net_pay" in e for e in errors)


def test_tampered_ground_truth_is_caught():
    task = next(t for t in SEED if t.ground_truth.kind == "payslip")
    lines = dict(task.ground_truth.lines)
    lines["net_pay"] += 1
    tampered = task.model_copy(update={"ground_truth": task.ground_truth.model_copy(update={"lines": lines}), "hand_check": None})
    assert any("differs from the reference" in e for e in validate_tasks([tampered]))


def test_trap_without_twin_is_caught():
    traps = [t for t in SEED if t.difficulty == 3]
    assert any("no determinable twin" in e for e in validate_tasks(traps[:1]))


# ---------------------------------------------------------------- schema drift (p.7 edge case)


def test_unknown_schema_version_is_rejected_loudly():
    raw = json.loads(dump_task(SEED[0]))
    raw["schema_version"] = "2.0"
    with pytest.raises(ValueError, match="unsupported task schema_version"):
        load_task(raw)


def test_unknown_field_is_rejected_not_silently_dropped():
    raw = json.loads(dump_task(SEED[0]))
    raw["new_field_from_v2"] = 1
    with pytest.raises(Exception):
        load_task(raw)


def test_registered_migration_upgrades_old_version(monkeypatch):
    """The upgrade path: a registered migration lifts an old record to the current version."""
    raw = json.loads(dump_task(SEED[0]))
    raw["schema_version"] = "0.9"
    raw["tier"] = raw.pop("difficulty")  # pretend v0.9 called the field 'tier'

    def v09_to_v10(d):
        d = dict(d)
        d["difficulty"] = d.pop("tier")
        d["schema_version"] = SCHEMA_VERSION
        return d

    monkeypatch.setitem(MIGRATIONS, "0.9", v09_to_v10)
    assert load_task(raw) == SEED[0]


def test_json_schema_has_brief_minimum_fields():
    props = Task.model_json_schema()["properties"]
    for name in ("id", "slice", "difficulty", "prompt", "context_files", "ground_truth", "verifier", "tags", "schema_version"):
        assert name in props, name
