"""The Phase 04 rubric as a TRL GRPO reward function, plus per-step reward-hacking monitors.

The reward is ``paygym.rubric.score_answer`` with no judge (judge weight 0 in training: cost,
latency, and the risk of the policy learning to please the judge; a documented trade-off).

Monitors are logged every step through TRL's ``log_metric`` hook (TRL 1.14.1), so the five
brief-required curves come with the signals that reveal a gamed reward:
  monitor/twin_refusal_rate     refusing determinable twins: the "refuse everything" collapse
  monitor/trap_answer_rate      computing payslips the rules do not determine
  monitor/parse_fail_rate       format collapse
  monitor/modal_net_share       share of completions in the batch with the single most common net pay
  monitor/len_reward_corr       correlation of completion length with reward: length hacking
  monitor/pass_rate_tier{2,3}   per-tier pass rate (total >= 0.95 on Tier 2; correct refusal on Tier 3)
"""

from __future__ import annotations

import json
import os
from collections import Counter

from paygym.parser import parse_answer
from paygym.rubric import score_answer
from paygym.schema import Task

_TASK_CACHE: dict[str, Task] = {}


def _task(item) -> Task:
    """Accepts the environment's ``info`` column (dict or JSON string holding ``task_json``) or a task JSON string."""
    if isinstance(item, str):
        data = json.loads(item)
        task_json = data["task_json"] if "task_json" in data else item
    else:
        task_json = item["task_json"]
    task = _TASK_CACHE.get(task_json)
    if task is None:
        task = _TASK_CACHE[task_json] = Task.model_validate_json(task_json)
    return task


def _text(completion) -> str:
    return completion[-1]["content"] if isinstance(completion, list) else str(completion)


def _corr(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    sx = sum((x - mx) ** 2 for x in xs) ** 0.5
    sy = sum((y - my) ** 2 for y in ys) ** 0.5
    if sx == 0 or sy == 0:
        return 0.0
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)


def rubric_reward(completions, info=None, log_metric=None, **kwargs) -> list[float]:
    """TRL reward: ``info`` is the verifiers environment's dataset column (one per completion)."""
    texts = [_text(c) for c in completions]
    tasks = [_task(item) for item in info]
    scores = [score_answer(t, s) for t, s in zip(tasks, texts)]
    rewards = [s.total for s in scores]

    if log_metric is not None:
        twins = [s for t, s in zip(tasks, scores) if t.twin_of]
        traps = [s for t, s in zip(tasks, scores) if t.difficulty == 3]
        tier2 = [s for t, s in zip(tasks, scores) if t.difficulty == 2]
        nets = [_net(text) for text, s in zip(texts, scores) if s.decision == "answer"]
        nets = [n for n in nets if n is not None]
        if twins:
            log_metric("monitor/twin_refusal_rate", sum(s.decision == "refuse" for s in twins) / len(twins))
        if traps:
            log_metric("monitor/trap_answer_rate", sum(s.decision == "answer" for s in traps) / len(traps))
            log_metric("monitor/pass_rate_tier3", sum(s.total >= 0.8 for s in traps) / len(traps))
        if tier2:
            log_metric("monitor/pass_rate_tier2", sum(s.total >= 0.95 for s in tier2) / len(tier2))
        log_metric("monitor/parse_fail_rate", sum(s.parse_error is not None for s in scores) / len(scores))
        if nets:
            log_metric("monitor/modal_net_share", Counter(nets).most_common(1)[0][1] / len(nets))
        log_metric("monitor/len_reward_corr", _corr([float(len(t)) for t in texts], rewards))
    _save_samples(kwargs.get("trainer_state"), tasks, texts, scores)
    return rewards


SAMPLES_PER_STEP = 8


def _save_samples(trainer_state, tasks, texts, scores) -> None:
    """Keep a few training completions per step for the reward-gaming hunt (docs/RL_REPORT.md A7)."""
    path = os.environ.get("PAYGYM_SAMPLES_PATH")
    if not path:
        return
    step = getattr(trainer_state, "global_step", None)
    with open(path, "a") as fh:
        for task, text, score in list(zip(tasks, texts, scores))[:SAMPLES_PER_STEP]:
            fh.write(json.dumps({"step": step, "task_id": task.id, "difficulty": task.difficulty, "reward": score.total,
                                 "gate": score.gate, "decision": score.decision, "completion": text}) + "\n")


def _net(text: str) -> str | None:
    parsed = parse_answer(text, "payslip")
    value = parsed.lines.get("net_pay")
    return None if value is None else str(value.normalize())
