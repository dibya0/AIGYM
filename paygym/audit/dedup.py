"""Near-duplicate audit (brief p.7: "Near-duplicates that inflate your sample size without adding signal").

Checks exact duplicates (same structured case, or same normalised prompt) and near-duplicates
(Jaccard similarity of word 5-shingles at or above a threshold). Trap/twin pairs are similar
*by design* (they differ minimally), so they are reported separately and not counted as
duplicates.
"""

from __future__ import annotations

import hashlib
import re
from itertools import combinations

from paygym.schema import Task


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def _shingles(text: str, k: int = 5) -> set[str]:
    words = _normalise(text).split()
    return {" ".join(words[i : i + k]) for i in range(max(1, len(words) - k + 1))}


def _jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a or b else 1.0


def _design_pairs(tasks: list[Task]) -> set[frozenset[str]]:
    return {frozenset((t.id, t.twin_of)) for t in tasks if t.twin_of}


def audit(tasks: list[Task], threshold: float = 0.9) -> dict:
    pairs_by_design = _design_pairs(tasks)

    exact_case: dict[str, list[str]] = {}
    exact_prompt: dict[str, list[str]] = {}
    for t in tasks:
        key = t.case.model_dump_json() if t.case is not None else t.lookup.model_dump_json()
        exact_case.setdefault(hashlib.sha256(key.encode()).hexdigest(), []).append(t.id)
        exact_prompt.setdefault(hashlib.sha256(_normalise(t.prompt).encode()).hexdigest(), []).append(t.id)

    shingles = {t.id: _shingles(t.prompt) for t in tasks}
    near, twin_similarity = [], []
    for a, b in combinations(tasks, 2):
        if a.lookup is not None and b.lookup is not None:
            # Retrieval prompts share one template by design; two *different* lookups are not
            # duplicates, and two identical lookups are already caught as exact duplicate cases.
            continue
        sim = _jaccard(shingles[a.id], shingles[b.id])
        if frozenset((a.id, b.id)) in pairs_by_design:
            twin_similarity.append(sim)
        elif sim >= threshold:
            near.append({"a": a.id, "b": b.id, "jaccard": round(sim, 4)})
    dup_cases = [ids for ids in exact_case.values() if len(ids) > 1]
    dup_prompts = [ids for ids in exact_prompt.values() if len(ids) > 1]
    return {
        "n": len(tasks),
        "threshold": threshold,
        "exact_duplicate_cases": dup_cases,
        "exact_duplicate_prompts": dup_prompts,
        "near_duplicates": near,
        "trap_twin_pairs": len(twin_similarity),
        "trap_twin_mean_jaccard": round(sum(twin_similarity) / len(twin_similarity), 4) if twin_similarity else None,
        "unique_tasks_after_dedup": len(tasks) - sum(len(ids) - 1 for ids in dup_cases),
    }

