"""verifiers environment for PayGym (brief Phase 03), targeting verifiers==0.2.1 (the last release with
the v0 API the brief specifies: load_environment -> vf.Environment, Rubric, SingleTurnEnv, ToolEnv).

    import verifiers as vf
    env = vf.load_environment("paygym", mode="tool", split="eval")

One environment, three consumers (brief §10). This module assembles:
  dataset   tasks from the seeded generator (``split`` + ``n_seeds``), or a task file
  prompts   ``paygym.prompting`` (the same builder the GRPO trainer uses)
  tools     ``paygym.tools`` (tool mode only; the only source of data, brief p.8)
  rubric    ``paygym.rubric.score_answer`` (the same scorer the trainer and the sandbox use)

Rubric layout: one reward function, ``paygym_reward`` (weight 1), is the gated total. Gating is a cap, so
it cannot be a weighted sum of components. The components are recorded as weight-0 metrics for
per-reward-function breakdowns, alongside the monitors (parse errors, refusals, tool errors).
"""

from __future__ import annotations

import json
from pathlib import Path

import verifiers as vf
from datasets import Dataset

from paygym.generator import generate_split
from paygym.prompting import SCAFFOLDS, messages_for
from paygym.rubric import Score, score_answer
from paygym.schema import Task
from paygym.tools import HIDDEN_ARGS, TOOLS
from paygym.validate import read_tasks

LOOP_LIMIT = 3  # the same tool call (name + arguments) this many times in a row ends the rollout


# --------------------------------------------------------------------------- dataset


def load_tasks(split: str = "eval", n_seeds: int = 95, tasks_path: str | None = None, tier: str = "all") -> list[Task]:
    if tasks_path:
        tasks, errors = read_tasks(Path(tasks_path))
        if errors:
            raise ValueError("invalid tasks: " + "; ".join(errors[:5]))
    else:
        tasks = generate_split(split, n_seeds)
    if tier != "all":
        tiers = {int(t) for t in str(tier).split(",")}
        tasks = [t for t in tasks if t.difficulty in tiers]
    return tasks


def build_rows(tasks: list[Task], mode: str, scaffold: str | None = None) -> Dataset:
    return Dataset.from_list([
        {
            "prompt": messages_for(t, mode, scaffold),
            "answer": "",  # ground truth stays in info.task_json and never enters the prompt
            "info": json.dumps({"task_id": t.id, "difficulty": t.difficulty, "kind": t.ground_truth.kind,
                                "task_json": t.model_dump_json(exclude_none=True)}),
        }
        for t in tasks
    ])


# --------------------------------------------------------------------------- rubric


def completion_text(completion) -> str:
    """Text of the final assistant message (messages may be dicts or verifiers message objects)."""
    if isinstance(completion, str):
        return completion
    for msg in reversed(completion or []):
        role = msg.get("role") if isinstance(msg, dict) else getattr(msg, "role", None)
        if role != "assistant":
            continue
        content = msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", None)
        if isinstance(content, list):  # content parts
            content = "".join(p.get("text", "") if isinstance(p, dict) else str(getattr(p, "text", "")) for p in content)
        return content or ""
    return ""


def _info(info) -> dict:
    return json.loads(info) if isinstance(info, str) else (info or {})


def make_rubric(use_judge: bool = False) -> vf.Rubric:
    judge = None
    if use_judge:
        from paygym.judge import GeminiJudge

        judge = GeminiJudge()

    def score_of(completion, info, state) -> Score:
        # Computed once per rollout and shared by the reward and the metrics. verifiers' State is a dict and
        # state_to_output saves only standard fields, so this cache never reaches result files.
        cached = state.get("paygym_score")
        if cached is not None:
            return cached
        task = Task.model_validate_json(_info(info)["task_json"])
        score = score_answer(task, completion_text(completion), judge=judge)
        state["paygym_score"] = score
        return score

    def paygym_reward(completion, info, state) -> float:
        """Gated total from paygym.rubric (the training and leaderboard reward)."""
        return score_of(completion, info, state).total

    def _component(name: str):
        def metric(completion, info, state) -> float:
            for comp in score_of(completion, info, state).components:
                if comp.name == name:
                    return comp.score
            return 0.0  # not applicable to this task kind

        metric.__name__ = name
        return metric

    def refused(completion, info, state) -> float:
        return 1.0 if score_of(completion, info, state).decision == "refuse" else 0.0

    def parse_failed(completion, info, state) -> float:
        return 1.0 if score_of(completion, info, state).parse_error is not None else 0.0

    def tool_errors(completion) -> float:
        """Tool results that were structured errors (bad arguments, unknown ids): recorded, never hidden."""
        count = 0
        for msg in completion or []:
            role = msg.get("role") if isinstance(msg, dict) else getattr(msg, "role", None)
            content = msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", "")
            if role == "tool" and isinstance(content, str) and content.startswith('{"error"'):
                count += 1
        return float(count)

    rubric = vf.Rubric(funcs=[paygym_reward], weights=[1.0])
    for name in ("net_pay_exact", "line_accuracy", "trap_decision", "value_exact", "format_valid", "judge_flag_quality"):
        rubric.add_metric(_component(name))
    for fn in (refused, parse_failed, tool_errors):
        rubric.add_metric(fn)
    return rubric


# --------------------------------------------------------------------------- tool mode


class PaygymToolEnv(vf.StatefulToolEnv):
    """Tool mode: the prompt holds only an employee id; facts come from tools. ``task_json`` is injected
    per rollout and hidden from the model's tool schema."""

    def __init__(self, **kwargs):
        super().__init__(tools=[], **kwargs)
        for tool in TOOLS:
            self.add_tool(tool, args_to_skip=HIDDEN_ARGS)

    def update_tool_args(self, tool_name, tool_args, messages, state, **kwargs) -> dict:
        tool_args = dict(tool_args)
        tool_args["task_json"] = _info(state["info"])["task_json"]
        return tool_args

    @vf.stop
    async def tool_loop_detected(self, state) -> bool:
        """Ends the rollout when the agent repeats the identical tool call LOOP_LIMIT times in a row."""
        calls = []
        for step in state["trajectory"]:
            for msg in step["completion"]:
                for call in getattr(msg, "tool_calls", None) or []:
                    calls.append((call.name, call.arguments))
        return len(calls) >= LOOP_LIMIT and len(set(calls[-LOOP_LIMIT:])) == 1


# --------------------------------------------------------------------------- entry point


def load_environment(
    mode: str = "single",
    split: str = "eval",
    n_seeds: int = 95,
    tasks_path: str | None = None,
    tier: str = "all",
    max_turns: int = 8,
    timeout_seconds: float = 120.0,
    use_judge: bool = False,
    scaffold: str | None = None,
    **kwargs,
) -> vf.Environment:
    """Build the PayGym environment.

    Args:
        mode: "single" (rule set in the prompt, SingleTurnEnv) or "tool" (tools only, StatefulToolEnv).
        split: generator split ("eval", "heldout", "val", "train"); ignored if ``tasks_path`` is given.
        n_seeds: number of generator seeds (a trap seed yields a trap and its twin).
        tasks_path: a .jsonl task file or directory instead of generating.
        tier: "all" or a comma list such as "2,3".
        max_turns: tool mode turn limit. timeout_seconds: per-rollout wall-clock limit.
        use_judge: score trap explanations with the LLM judge (needs GEMINI_API_KEY).
        scaffold: a Track C scaffold "S0".."S4" (paygym.prompting.SCAFFOLDS); it fixes the mode.
    """
    if scaffold:
        mode = SCAFFOLDS[scaffold]["mode"]
    if mode not in ("single", "tool"):
        raise ValueError("mode must be 'single' or 'tool'")
    tasks = load_tasks(split, n_seeds, tasks_path, tier)
    rows = build_rows(tasks, mode, scaffold)
    rubric = make_rubric(use_judge)
    common = dict(dataset=rows, eval_dataset=rows, rubric=rubric, timeout_seconds=timeout_seconds, **kwargs)
    if mode == "single":
        return vf.SingleTurnEnv(**common)
    return PaygymToolEnv(max_turns=max_turns, **common)
