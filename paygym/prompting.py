"""The one place prompts are built, shared by the verifiers environment, the eval harness and
the GRPO trainer, so all three send exactly the same text (brief §10: "the same environment
serves the eval, the trainer, and the sandbox"). The prompt hash is recorded in result files.
"""

from __future__ import annotations

import hashlib

from paygym.render import JURISDICTION_NAMES, period_label, ruleset_section
from paygym.schema import Task

PROMPT_VERSION = "1"

SYSTEM_PROMPT = """You are a payroll specialist. You compute monthly payslips strictly under the PayGym payroll rule set v1.0.

Finish your reply with exactly one fenced JSON block (```json ... ```) and nothing after it.

For a payslip question, the JSON object must have these keys:
  "decision": "answer" or "refuse"
  "reason_code": null when answering; when refusing, one of "MISSING_INPUT", "CONFLICTING_RECORDS", "NO_APPLICABLE_TABLE", "UNSUPPORTED_CURRENCY"
  "lines": when answering, an object with numeric values for every payslip line:
      "earned_salary", "retro_pay", "taxable_allowances", "non_taxable_allowances", "gross_pay",
      "employee_social_insurance", "employee_pension", "income_tax", "net_pay", "employer_social_insurance"
    (amounts in the local currency, rounded as the rule set requires); null when refusing
  "explanation": one or two sentences; when refusing, name the missing, conflicting or unsupported input and the clause

For a question asking for a single rule-set value, the JSON object must have:
  "decision": "answer"
  "value": the number

Use plain JSON numbers (e.g. 1234.5), with no currency symbols or thousands separators."""

TOOL_SYSTEM_SUFFIX = """

You do not have the rule set or the employee's documents in this conversation. Use the tools to look up the
employee's records, the jurisdiction's rules and rates, and exchange rates, and use the calculator for arithmetic."""


# Track C scaffolds (brief §7): the model is held fixed and only these vary.
SELF_CHECK = """

Self-check (required): before your final JSON, recompute every payslip line with the calc tool and make sure
gross_pay and net_pay equal the sums of their lines. Do not give a final answer you have not checked."""
CHECKLIST = """

Checklist before answering:
1. Which rate table applies? It must be the table for the calendar year of the pay period; if there is none, refuse.
2. Is every required input for this jurisdiction stated, and do all documents agree on every input that is used?
3. Is the salary currency supported by the FX table for that date?
4. Does the social insurance wage ceiling bind? Monthly in Valdoria and Nordmark; annual and cumulative in Kestrel Isles.
5. Proration: calendar days or working days for this jurisdiction? Any mid-period salary change?
6. Which allowances are taxable, and is the meal exemption exceeded?"""

SCAFFOLDS: dict[str, dict] = {
    "S0": {"mode": "single", "context": False, "suffix": "", "label": "bare prompt (no rule set)"},
    "S1": {"mode": "single", "context": True, "suffix": "", "label": "rule set in context"},
    "S2": {"mode": "tool", "context": False, "suffix": "", "label": "tools"},
    "S3": {"mode": "tool", "context": False, "suffix": SELF_CHECK, "label": "tools + calc self-check"},
    "S4": {"mode": "tool", "context": False, "suffix": SELF_CHECK + CHECKLIST, "label": "tools + self-check + checklist"},
}


def context_text(task: Task) -> str:
    """The rule-set sections attached to a single-turn task (``context_files``)."""
    return "\n\n".join(ruleset_section(ref, task.ruleset_version) for ref in task.context_files)


def single_turn_messages(task: Task, with_context: bool = True, suffix: str = "") -> list[dict[str, str]]:
    if with_context:
        user = f"PayGym payroll rule set v{task.ruleset_version} (relevant sections):\n\n{context_text(task)}\n\n---\n\n{task.prompt}"
    else:
        user = task.prompt
    return [{"role": "system", "content": SYSTEM_PROMPT + suffix}, {"role": "user", "content": user}]


def tool_turn_messages(task: Task, suffix: str = "") -> list[dict[str, str]]:
    """Tool mode: the agent gets only a handle; every fact must come from a tool call (brief p.8)."""
    if task.lookup is not None:
        lk = task.lookup
        user = (f"What is the value of `{lk.field}` in {JURISDICTION_NAMES[lk.jurisdiction]} ({lk.jurisdiction}) "
                f"for pay periods in {lk.year}? Look it up with the tools.")
    else:
        case = task.case
        user = (f"Compute the payslip for employee {task.employee_id} ({JURISDICTION_NAMES[case.jurisdiction]}, "
                f"{case.jurisdiction}) for the pay period {period_label(case.pay_period)} ({case.pay_period}). "
                "If the rule set does not determine the payslip, refuse and say why instead of computing it.")
    return [{"role": "system", "content": SYSTEM_PROMPT + TOOL_SYSTEM_SUFFIX + suffix}, {"role": "user", "content": user}]


def messages_for(task: Task, mode: str, scaffold: str | None = None) -> list[dict[str, str]]:
    """The prompt for a task under a mode or a Track C scaffold (the scaffold, if given, fixes the mode)."""
    if scaffold:
        s = SCAFFOLDS[scaffold]
        if s["mode"] == "single":
            return single_turn_messages(task, with_context=s["context"], suffix=s["suffix"])
        return tool_turn_messages(task, suffix=s["suffix"])
    return single_turn_messages(task) if mode == "single" else tool_turn_messages(task)


def prompt_hash(scaffold: str | None = None) -> str:
    """Identifies the prompt template version in result files (brief P05: "prompt hashes")."""
    extra = repr(SCAFFOLDS[scaffold]) if scaffold else ""
    blob = (PROMPT_VERSION + SYSTEM_PROMPT + TOOL_SYSTEM_SUFFIX + extra).encode()
    return hashlib.sha256(blob).hexdigest()[:16]
