"""Generator tests (brief Phase 02, plus the Phase 01/07 edge cases it is responsible for)."""

from collections import Counter

import pytest

from paygym.generator import SPLITS, Knobs, content_key, generate, generate_one, generate_split
from paygym.schema import dump_task
from paygym.validate import validate_tasks

EVAL = generate_split("eval", 160)


def _dump(tasks):
    return [dump_task(t) for t in tasks]


def test_same_seed_same_taskset():
    """p.8: "Deterministic and reproducible: same seed produces an identical taskset." """
    assert _dump(generate(0, 40)) == _dump(generate(0, 40))


def test_task_depends_only_on_its_own_seed():
    """Prefix-stable: generating more seeds never changes earlier tasks."""
    assert _dump(generate(0, 20)) == _dump(generate(0, 40))[: len(generate(0, 20))]
    assert _dump(generate_one(12345)) == _dump(generate_one(12345))


def test_seed_recorded_on_every_task():
    assert all(t.seed is not None and t.provenance == "generated" for t in EVAL)


def test_generated_tasks_validate():
    """Ground truth == reference implementation; every trap has a determinable twin; unique ids."""
    assert validate_tasks(EVAL) == []


def test_at_least_100_instances_with_all_tiers():
    """p.8: at least 100 instances; the three tiers are all present."""
    assert len(EVAL) >= 100
    tiers = Counter(t.difficulty for t in EVAL)
    assert all(tiers[d] > 0 for d in (1, 2, 3)), tiers


def test_all_trap_reasons_and_twins_appear():
    traps = [t for t in EVAL if t.difficulty == 3]
    assert {t.ground_truth.reason_code for t in traps} == {
        "MISSING_INPUT", "CONFLICTING_RECORDS", "NO_APPLICABLE_TABLE", "UNSUPPORTED_CURRENCY"}
    twins = {t.twin_of for t in EVAL if t.twin_of}
    assert {t.id for t in traps} == twins


def test_ceiling_variation_survives():
    """The key difficulty must vary: some payslips hit the ceiling, some do not (non-degenerate)."""
    tags = Counter(tag for t in EVAL if t.ground_truth.kind == "payslip" for tag in t.tags)
    assert tags["ceiling_binds"] > 0 and tags["ceiling_slack"] > 0, tags


def test_no_duplicate_questions_within_a_split():
    keys = [content_key(t) for t in EVAL if not t.id.endswith("-twin")]
    assert len(keys) == len(set(keys))


def test_split_seed_ranges_are_disjoint():
    ranges = sorted(SPLITS.values())
    for (a_start, a_end), (b_start, _) in zip(ranges, ranges[1:]):
        assert a_end <= b_start


def test_train_and_heldout_share_no_task():
    """p.12: "Generator seeds must not overlap between the two partitions", checked on content too."""
    train = {content_key(t) for t in generate_split("train", 120)}
    heldout = {content_key(t) for t in generate_split("heldout", 120)}
    assert train.isdisjoint(heldout)


def test_train_split_has_no_retrieval_tasks():
    assert all(t.difficulty != 1 for t in generate_split("train", 60))


@pytest.mark.parametrize("p_fx,expect_any", [(0.0, False), (1.0, True)])
def test_knob_controls_currency_mix(p_fx, expect_any):
    tasks = generate(10_000, 40, Knobs(tier_mix=(0, 1, 0), p_fx=p_fx))
    has_fx = ["fx" in t.tags for t in tasks]
    assert any(has_fx) == expect_any and all(has_fx) == expect_any


def test_knob_controls_jurisdictions():
    tasks = generate(20_000, 30, Knobs(jurisdictions=("NRD",)))
    assert {t.case.jurisdiction if t.case else t.lookup.jurisdiction for t in tasks} == {"NRD"}


def test_trap_prompts_do_not_name_the_reason_code():
    for t in EVAL:
        if t.ground_truth.kind == "refusal":
            assert t.ground_truth.reason_code not in t.prompt


def test_audits_run_and_find_no_literal_leaks():
    pytest.importorskip("sklearn")
    from paygym.audit import dedup, leakage

    report = leakage.audit(EVAL)
    assert report["literal_leak_count"] == 0, report["literal_leaks"][:3]
    assert "cv_accuracy" in report["classifier"]
    d = dedup.audit(EVAL)
    assert d["exact_duplicate_cases"] == []
    assert d["trap_twin_pairs"] == sum(1 for t in EVAL if t.twin_of)


def test_presets_never_collide_with_default_ids():
    from paygym.generator import KNOB_PRESETS

    default = {t.id for t in generate_split("train", 20)}
    easy = {t.id for t in generate_split("train", 20, KNOB_PRESETS["easy"], "easy")}
    assert default.isdisjoint(easy) and all(i.startswith("gen-easy-") for i in easy)


def test_literal_leak_check_matches_whole_numbers_only():
    """Regression (first real run): SI 480.00 was flagged because "480,00" sits inside the YTD input "22.480,00"."""
    from paygym.audit.leakage import literal_leaks

    task = next(t for t in EVAL if t.ground_truth.kind == "payslip")
    value = task.ground_truth.lines["net_pay"]
    padded = task.model_copy(update={"prompt": task.prompt + f" YTD 9{value:.2f}"})  # value only as a substring of a bigger number
    exact = task.model_copy(update={"prompt": task.prompt + f" net {value:.2f} "})
    assert not [x for x in literal_leaks([padded]) if x["line"] == "net_pay"]
    assert [x for x in literal_leaks([exact]) if x["line"] == "net_pay"]
