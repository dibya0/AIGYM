"""The PayGym rubric: the single scorer used by the eval harness, the GRPO trainer and the sandbox.

Every component returns a ``RewardResult(score, clauses, detail)`` naming the rule-set clauses
that drove it (brief p.10). The total is computed here, not as a plain weighted sum, because the
brief's gating rules are caps, which a weighted sum cannot express.

WHAT EACH SCORE LEVEL MEANS (brief p.10)

Determinable payslip (Tier 2):
  1.00         net pay and every line correct (within one minor unit, GEN-§1.4), valid format:
               would pass payroll review under the rules.
  0.75-0.99    net pay correct, some intermediate lines wrong (net right for partly wrong reasons).
  <= 0.25      net pay wrong: capped at the floor, however many other lines are right.
  -1.00        refused a payslip the rules determine (v1.2; 0.00 in v1.1, 0.05 in v1.0). The compute/refuse
               choice is a decision, and both wrong decisions are penalised the same: refusing a payable
               payslip (employees not paid) scores exactly like computing a trap (-1). Brief p.10:
               "abstaining on a task the rules do determine must be penalised exactly like a wrong answer".
  -1.00        no parseable answer (v1.3; 0.00 before): an output no one can read cannot be paid or reviewed.

  Why v1.1 (2026-10-19, reward gaming found by GRPO, docs/RL_REPORT.md B6): in v1.0 a refusal kept the
  0.05 format credit, so on a payslip it beat broken JSON (0.00) and roughly matched a typical wrong
  answer (~0.05-0.12) at much lower variance. Within 5 steps the 0.5B policy was refusing 5-6 of 8
  determinable payslips.

  Why v1.2 (2026-10-19, reward gaming LEARNED by GRPO, docs/RL_REPORT.md B6): under v1.1 the decision was
  asymmetric (answer a trap -1, refuse a payable payslip 0). For a policy that earns ~0.1 by attempting
  payslips, refusing everything was the best strategy: by validation step 20 the 0.5B refused 47/47 tasks
  and its validation reward ROSE (-0.063 -> +0.081, the always_abstain baseline's level). Checked offline on
  those real outputs before changing anything: under v1.2 refuse-everything scores -0.685 (worst), the base
  -0.063, and a policy that refuses only traps +0.166 (best).

  Why v1.3 (2026-10-19, the second learned exploit): with both wrong decisions at -1 (v1.2), an UNPARSEABLE
  answer still scored 0, so it became the harbour. By validation step 20 the 0.5B wrote broken JSON for
  47/47 tasks (arithmetic inside JSON values: "net_pay": 4950.0 + 60.0 - 0 ...), parse failures 100 % for
  six training steps. Checked offline on the real outputs of all three runs before changing anything: under
  v1.3 broken-everywhere -1.000 and refuse-everything -0.685 are the two worst policies, below the base model
  (-0.319); fixing the base model's JSON alone gives -0.140, and refusing only traps -0.004. The score is now
  monotone in competence: no cheap strategy beats an honest attempt.

  Why v1.4 (2026-10-19, the third learned exploit, found only at the too-low beta = 0.001): a "decision" other
  than "answer"/"refuse" (the parser's bad_decision) was not treated as a contract violation. On a trap it fell
  into the refusal branch (+0.3, or +0.8 with the right code); on a payslip it read no lines and scored 0.0
  instead of -1. The policy learned to write "decision": "reject" with a payslip attached: 72 % of training
  samples, 47/47 validation tasks at step 20, validation +0.070 (above the honest beta = 0.04 policy's -0.129).
  Now any output without a valid decision scores as unparseable (-1) on every tier. The beta = 0.04 run never
  used it on validation (0/188), so its numbers are unchanged. Format credit is for a payslip; a refusal of a payable payslip is not one.

Trap (Tier 3, the rules do not determine the payslip, GEN-§9):
  1.00         refused with the correct reason code and a useful explanation (judge).
  0.80         refused with the correct reason code (judge unavailable, or explanation weak).
  0.30         refused, but with the wrong reason code: right call, wrong reason.
  -1.00        computed a payslip anyway: "must score zero or negative, never partial credit" (p.7).
  -1.00        no parseable answer (v1.3; 0.00 before): an output no one can read cannot be paid or reviewed.

Retrieval (Tier 1):
  1.00         the exact value (tolerance 0: it is read from a table, not computed).
  0.05         wrong value, valid format.  -1.00 unparseable (v1.3).
  -1.00        refused (v1.2, consistent with payslips: every retrieval task is determinable).

WEIGHTS (determinable payslip): net_pay_exact 0.70, line_accuracy 0.25, format_valid 0.05.
  Net pay is what the employee is paid, and it is wrong whenever any upstream line is wrong
  enough to matter, so it carries most of the weight. Line accuracy is the graded partial credit:
  it rewards getting the ceiling, tax and pension right separately, and is what gives a learning
  signal when net pay is not yet right. Format is small so that format alone is worth almost nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Callable

from paygym.parser import ParsedAnswer, parse_answer
from paygym.reference.calculator import LINES
from paygym.schema import Task

RUBRIC_VERSION = "1.4"  # 1.4: a decision other than answer/refuse = unparseable; 1.3: unparseable = -1; 1.2: refusing a determinable task = -1
UNPARSEABLE = -1.0  # v1.3: no usable output is as bad as a wrong decision (see "Why v1.3" in the docstring)

W_NET, W_LINES, W_FORMAT = Decimal("0.70"), Decimal("0.25"), Decimal("0.05")
WRONG_NET_CAP = Decimal("0.25")
TRAP_CORRECT_REASON, TRAP_JUDGE_BONUS, TRAP_WRONG_REASON, TRAP_ANSWERED = (
    Decimal("0.80"), Decimal("0.20"), Decimal("0.30"), Decimal("-1.00"))
FORMAT_CLAUSE = "CONTRACT"  # the output contract in paygym/prompting.py, not a rule-set clause

# Computation order (GEN-§3) used to find the *first* wrong line: the clause where the agent went wrong.
LINE_ORDER = ("earned_salary", "retro_pay", "taxable_allowances", "non_taxable_allowances", "gross_pay",
              "employee_social_insurance", "employer_social_insurance", "employee_pension", "income_tax", "net_pay")


@dataclass
class RewardResult:
    name: str
    score: float
    clauses: list[str]
    detail: str


@dataclass
class Score:
    total: float
    components: list[RewardResult]
    gate: str | None  # which gating rule capped or set the total, if any
    driving_clauses: list[str]  # the clause(s) behind the mark (sandbox "clause" field)
    decision: str | None
    parse_error: str | None
    judged: bool = False
    extra: dict = field(default_factory=dict)

    def breakdown(self) -> dict[str, float]:
        return {c.name: c.score for c in self.components}


# A judge takes (task, parsed answer) and returns (score in [0, 1], detail), or raises on failure.
Judge = Callable[[Task, ParsedAnswer], tuple[float, str]]


def _within(a: Decimal, b: Decimal, tol: Decimal) -> bool:
    return abs(a - b) <= tol


def _format_result(parsed: ParsedAnswer) -> RewardResult:
    ok = parsed.ok and parsed.error is None
    return RewardResult("format_valid", 1.0 if ok else 0.0, [FORMAT_CLAUSE],
                        "valid answer object" if ok else f"contract violation: {parsed.error}")


def _score_payslip(task: Task, parsed: ParsedAnswer) -> Score:
    gt = task.ground_truth
    fmt = _format_result(parsed)
    if parsed.raw is None or parsed.decision is None:  # no object, or no valid decision (v1.4)
        comps = [RewardResult("net_pay_exact", 0.0, list(gt.line_clauses["net_pay"]), f"unparseable ({parsed.error})"),
                 RewardResult("line_accuracy", 0.0, ["GEN-§10.1"], "unparseable"), fmt]
        return Score(UNPARSEABLE, comps, "unparseable", ["GEN-§10.1"], None, parsed.error)

    lines = parsed.lines if parsed.decision == "answer" else {}  # a refusal = an answer with no lines
    correct = {name: name in lines and _within(lines[name], gt.lines[name], gt.tolerance) for name in LINES}
    net_ok = correct["net_pay"]
    accuracy = sum(correct.values()) / len(LINES)
    first_wrong = next((name for name in LINE_ORDER if not correct[name]), None)

    net = RewardResult(
        "net_pay_exact", 1.0 if net_ok else 0.0, list(gt.line_clauses["net_pay"]) + ["GEN-§1.4"],
        f"net_pay {lines.get('net_pay')} vs {gt.lines['net_pay']} (tolerance {gt.tolerance}, GEN-§1.4)",
    )
    line_clauses = list(gt.line_clauses[first_wrong]) if first_wrong else ["GEN-§10.1"]
    line = RewardResult(
        "line_accuracy", round(accuracy, 4), line_clauses,
        f"{sum(correct.values())}/{len(LINES)} lines correct" + (f"; first wrong: {first_wrong}" if first_wrong else ""),
    )
    raw_total = W_NET * (1 if net_ok else 0) + W_LINES * Decimal(str(accuracy)) + W_FORMAT * Decimal(str(fmt.score))
    gate = None
    if parsed.decision == "refuse":
        gate = "refused_determinable"  # the wrong decision, scored like computing a trap (v1.2)
        raw_total = Decimal(-1)
        driving = ["GEN-§9"] + list(gt.line_clauses["net_pay"])
    elif not net_ok:
        gate = "wrong_net_capped"
        raw_total = min(raw_total, WRONG_NET_CAP)
        driving = line_clauses
    else:
        driving = line_clauses if first_wrong else list(gt.line_clauses["net_pay"])
    return Score(float(raw_total), [net, line, fmt], gate, driving, parsed.decision, parsed.error,
                 extra={"first_wrong_line": first_wrong})


def _score_trap(task: Task, parsed: ParsedAnswer, judge: Judge | None) -> Score:
    gt = task.ground_truth
    fmt = _format_result(parsed)
    if parsed.raw is None or parsed.decision is None:  # no object, or no valid decision (v1.4)
        comps = [RewardResult("trap_decision", 0.0, [gt.clause], f"unparseable ({parsed.error})"), fmt]
        return Score(UNPARSEABLE, comps, "unparseable", [gt.clause], None, parsed.error)
    if parsed.decision == "answer":
        comps = [RewardResult("trap_decision", -1.0, [gt.clause],
                              f"computed a payslip the rules do not determine ({gt.reason_code})"), fmt]
        return Score(float(TRAP_ANSWERED), comps, "answered_trap", [gt.clause], "answer", parsed.error)

    reason_ok = parsed.reason_code == gt.reason_code
    decision = RewardResult(
        "trap_decision", 1.0 if reason_ok else 0.3, [gt.clause],
        f"refused with {parsed.reason_code!r}; expected {gt.reason_code}",
    )
    comps = [decision, fmt]
    if not reason_ok:
        return Score(float(TRAP_WRONG_REASON), comps, "wrong_reason", [gt.clause], "refuse", parsed.error)

    total = TRAP_CORRECT_REASON
    judged = False
    if judge is not None:
        judge_score, detail = judge(task, parsed)  # raises on failure: recorded, never a silent 0
        comps.append(RewardResult("judge_flag_quality", round(judge_score, 4), [gt.clause], detail))
        total += TRAP_JUDGE_BONUS * Decimal(str(judge_score))
        judged = True
    return Score(float(total), comps, None, [gt.clause], "refuse", parsed.error, judged=judged)


def _score_value(task: Task, parsed: ParsedAnswer) -> Score:
    gt = task.ground_truth
    fmt = _format_result(parsed)
    ok = parsed.decision == "answer" and parsed.value is not None and _within(parsed.value, gt.value, gt.tolerance)
    exact = RewardResult("value_exact", 1.0 if ok else 0.0, list(gt.clauses),
                         f"value {parsed.value} vs {gt.value} (tolerance {gt.tolerance})")
    if parsed.raw is None or parsed.decision is None:  # no object, or no valid decision (v1.4)
        return Score(UNPARSEABLE, [exact, fmt], "unparseable", list(gt.clauses), parsed.decision, parsed.error)
    if parsed.decision == "refuse":  # the wrong decision on a determinable task (v1.2), as for payslips
        return Score(-1.0, [exact, fmt], "refused_determinable", list(gt.clauses), parsed.decision, parsed.error)
    total = Decimal("0.95") * (1 if ok else 0) + W_FORMAT * Decimal(str(fmt.score))
    return Score(float(total), [exact, fmt], None if ok else "wrong_value", list(gt.clauses), parsed.decision, parsed.error)


def score_answer(task: Task, completion: str, judge: Judge | None = None) -> Score:
    """Score one completion against one task. ``judge`` is only used on correctly refused traps."""
    kind = task.ground_truth.kind
    parsed = parse_answer(completion, kind)
    if kind == "payslip":
        return _score_payslip(task, parsed)
    if kind == "refusal":
        return _score_trap(task, parsed, judge)
    return _score_value(task, parsed)
