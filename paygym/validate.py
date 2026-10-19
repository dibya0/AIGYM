"""`paygym validate`: checks a whole taskset in one command (brief Phase 01).

For every task: the schema parses; the ground truth equals what the rule set and reference
implementation produce *now* (so a stale or hand-edited answer is caught); any hand-check
values agree with that ground truth; every trap records why it is a trap and has a
determinable twin; and ids are unique.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from paygym.ruleset import load_ruleset
from paygym.schema import Task, load_task
from paygym.truth import truth_for_case, truth_for_lookup


@dataclass
class Report:
    tasks: list[Task] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        tiers = Counter(t.difficulty for t in self.tasks)
        traps = sum(1 for t in self.tasks if t.difficulty == 3)
        twins = sum(1 for t in self.tasks if t.twin_of)
        status = "OK" if self.ok else f"{len(self.errors)} error(s)"
        return (f"{len(self.tasks)} tasks | tier1={tiers[1]} tier2={tiers[2]} tier3={tiers[3]} "
                f"| traps={traps} twins={twins} | {status}")


def _check_hand(task: Task, errors: list[str]) -> None:
    if not task.hand_check:
        return
    gt = task.ground_truth
    for key, expected in task.hand_check.items():
        if key == "working":
            continue
        if gt.kind == "refusal":
            actual = getattr(gt, key, None)
            same = str(actual) == expected
        elif gt.kind == "value":
            actual = gt.value
            same = key == "value" and gt.value == Decimal(expected)
        else:
            actual = gt.lines.get(key)
            same = actual is not None and actual == Decimal(expected)
        if not same:
            errors.append(f"{task.id}: hand check {key}={expected} but reference gives {actual}")


def validate_tasks(tasks: list[Task]) -> list[str]:
    errors: list[str] = []
    ruleset = load_ruleset()
    by_id: dict[str, Task] = {}
    for task in tasks:
        if task.id in by_id:
            errors.append(f"{task.id}: duplicate id")
        by_id[task.id] = task
        if task.ruleset_version != ruleset.version:
            errors.append(f"{task.id}: ruleset_version {task.ruleset_version} != loaded {ruleset.version}")
            continue
        expected = truth_for_lookup(task.lookup, ruleset) if task.lookup else truth_for_case(task.case, ruleset)
        if expected != task.ground_truth:
            errors.append(f"{task.id}: stored ground truth differs from the reference implementation")
        _check_hand(task, errors)

    twins_of: dict[str, list[str]] = {}
    for task in tasks:
        if task.twin_of is None:
            continue
        twins_of.setdefault(task.twin_of, []).append(task.id)
        trap = by_id.get(task.twin_of)
        if trap is None:
            errors.append(f"{task.id}: twin_of {task.twin_of} not found")
        elif trap.difficulty != 3:
            errors.append(f"{task.id}: twin_of {task.twin_of} is not a trap")
        if task.ground_truth.kind == "refusal":
            errors.append(f"{task.id}: a twin must be determinable, but its ground truth is a refusal")
    for task in tasks:
        if task.difficulty == 3 and task.id not in twins_of:
            errors.append(f"{task.id}: trap has no determinable twin")
    return errors


def read_tasks(path: Path) -> tuple[list[Task], list[str]]:
    files = sorted(path.rglob("*.jsonl")) if path.is_dir() else [path]
    tasks, errors = [], []
    for file in files:
        for n, line in enumerate(file.read_text().splitlines(), 1):
            if not line.strip():
                continue
            try:
                tasks.append(load_task(line))
            except Exception as exc:  # report every bad line, don't stop at the first
                errors.append(f"{file.name}:{n}: {exc}")
    if not files:
        errors.append(f"no .jsonl files under {path}")
    return tasks, errors


def validate_path(path: Path) -> Report:
    tasks, errors = read_tasks(path)
    return Report(tasks=tasks, errors=errors + validate_tasks(tasks))
