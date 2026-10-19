"""Judge tests that need no API key: prompt construction, versioning, caching, agreement maths."""

import csv
import importlib.util
from pathlib import Path

import pytest

from paygym.judge import CRITERIA, GeminiJudge, build_messages, prompt_hash
from paygym.judge_reliability import agreement, cohens_kappa

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("seed", ROOT / "scripts" / "build_seed_tasks.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
SEED = {t.id: t for t in _mod.build()}


def test_criteria_are_grounded_in_the_rule_set():
    task = SEED["seed-t3-02"]  # CONFLICTING_RECORDS on start_date
    msgs = build_messages(task, "names_the_input", "The start dates differ.")
    assert "`start_date`" in msgs[1]["content"]
    msgs = build_messages(task, "states_why_rules_do_not_determine", "x")
    assert "GEN-§9.2" in msgs[1]["content"]  # the clause text itself is quoted to the judge
    assert '"pass"' in msgs[0]["content"]


def test_prompt_hash_is_stable_and_versioned():
    assert prompt_hash() == prompt_hash() and len(prompt_hash()) == 16


class FakeJudge(GeminiJudge):
    """GeminiJudge with the network call replaced, to test caching and aggregation."""

    def __init__(self, verdicts):
        self.model, self.use_cache, self.cache, self.cache_path, self.calls = "fake", True, {}, None, 0
        self._verdicts = verdicts

    def judge_criterion(self, task, criterion, explanation):
        key = self._key(task, criterion, explanation)
        if key in self.cache:
            return self.cache[key]
        self.calls += 1
        row = {"criterion": criterion, "pass": self._verdicts[criterion]}
        self.cache[key] = row
        return row


def test_judge_score_is_fraction_of_criteria_passed_and_cached():
    from paygym.parser import parse_answer

    judge = FakeJudge({"names_the_input": True, "states_why_rules_do_not_determine": True, "actionable_for_operator": False})
    parsed = parse_answer('```json\n{"decision":"refuse","reason_code":"CONFLICTING_RECORDS","explanation":"dates differ"}\n```', "refusal")
    score, detail = judge(SEED["seed-t3-02"], parsed)
    assert score == pytest.approx(2 / 3) and "actionable_for_operator=fail" in detail
    judge(SEED["seed-t3-02"], parsed)
    assert judge.calls == len(CRITERIA)  # second call served from cache


def test_cohens_kappa():
    assert cohens_kappa([1, 1, 0, 0], [1, 1, 0, 0]) == pytest.approx(1.0)
    assert cohens_kappa([1, 0, 1, 0], [0, 1, 0, 1]) == pytest.approx(-1.0)
    assert cohens_kappa([1, 1, 1], [1, 1, 1]) is None  # undefined when both raters are constant


def test_agreement_reads_label_sheet(tmp_path):
    path = tmp_path / "labels.csv"
    rows = [("a", "names_the_input", "1", "1"), ("a", "actionable_for_operator", "0", "1"), ("b", "names_the_input", "", "0")]
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["task_id", "reason_code", "criterion", "explanation", "human_pass", "judge_pass"])
        for tid, crit, human, judge in rows:
            w.writerow([tid, "MISSING_INPUT", crit, "e", human, judge])
    report = agreement(path)
    assert report["labelled_rows"] == 2 and report["agreement"] == pytest.approx(0.5)
