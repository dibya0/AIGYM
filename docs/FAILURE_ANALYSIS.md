# Failure analysis (brief §9 #8)

*11 failed transcripts read in full, from 5 configurations: Gemini 3.5 Flash-Lite, gpt-oss-120b, Qwen-3B with tools, the GRPO-trained Qwen-0.5B, and Gemini 3.1 Flash-Lite with tools. For each, the expected payslip and the reason a trap is a trap were taken from the reference and compared line by line. Each pattern was then **counted across every scored rollout** of that configuration, so the categories are measured failure modes, not anecdotes. Rubric 1.4; transcripts in `results/<model>/<run>/transcript.jsonl` (task id and rollout given), also clickable on the dashboard.*

## Categories

| # | Category | Read | Count across all rollouts | Example (task, rollout) |
|---|---|---|---|---|
| 1 | **Arithmetic or rule application inside a payslip**: right decision, wrong lines | 4 | Flash-Lite: 179/210 payslip rollouts have a wrong net pay. First wrong line: earned salary (GEN-§6) 100, tax brackets (GEN-§11) 51, contribution base/ceiling (GEN-§5.2) 27 | `gen-2000001` r0, `gen-2000000` r0, `gen-2000002` r0, gpt-oss `gen-2000066-twin` r0 |
| 2 | **Over-refusal: refusing a determinable task on a misread rule** | 3 | Flash-Lite 22/270 determinable rollouts (19 "conflicting records", **9 of them over a job title**); Qwen-3B tools 133/270 (**116 "unsupported currency"**) | `gen-2000005-twin` r0, `gen-2000021-twin` r0, 3B S2 `gen-2000002` r0 |
| 3 | **Answering a trap** | 2 | Flash-Lite 12/57 trap rollouts; trained 0.5B **56/57, all 56 while naming a refusal reason code** | `gen-2000039-trap` r0, trained 0.5B `gen-2000013-trap` r0 |
| 4 | **Output-contract violation with a correct value** | 1 | trained 0.5B: **60/60 Tier-1 rollouts** are a bare number with no JSON object | trained 0.5B `gen-2000008` r0 |
| 5 | **Tool loop: no final answer** | 1 | Gemini 3.1 Flash-Lite tool mode: 12/18 rollouts end at the 8-turn limit with an empty answer | `gen-2000048` r0 |

## The transcripts

### 1. Arithmetic and rule application (the decision is right, the payslip is not)

- **Missed the personal allowance.** Flash-Lite, `gen-2000001` (VAL 2025-08, annual salary stated, `dot_comma` number format).
  - Every line up to income tax is exact: earned salary 3,860.00, social insurance 308.80, pension 193.00.
  - Tax is **471.84 vs 271.64**, exactly +200.00. That is 20 % of the 1,000.00 monthly personal allowance, so the model skipped VAL-§4.1's allowance deduction and taxed 2,358.20 + 1,000.
  - It parsed `46.320,00` correctly and divided by 12: the format knob did not trip it; the rule did.
- **Annualised tax not applied, plus a proration slip.** Flash-Lite, `gen-2000000` (KES 2025-02, USD salary, salary change on the 9th).
  - Earned salary is 9,178.00 vs 9,175.00, a few units off in the day split.
  - Tax is **451.98 vs 2,074.80**. Kestrel residents are taxed by annualising (KES-§4.2: 12 × M − 12,000, annual brackets, ÷ 12). The answer looks like monthly brackets applied to a monthly amount.
  - Its explanation claims "Kestrel Isles resident tax rules", which shows that the gym's line-level check, not the explanation, is what catches this.
- **Wrong day count.** Flash-Lite, `gen-2000002` (NRD 2026-07, EUR salary, change on the 7th): earned salary 4,443 vs 4,615. Nordmark prorates by *working* days (NRD-§1.2); the answer does not match working-day proration.
- **Wrong year's exchange rate.** gpt-oss-120b, `gen-2000066-twin` (KES 2025-07).
  - Earned salary is 4,576.00 vs 4,400.00. 4,400 = 3,520 USD × 1.25 (the 2025 rate) and 4,576 = 3,520 × 1.30 (the 2026 rate).
  - It used the wrong effective-dated FX row (FX-§1.1, GEN-§4.1), and every downstream line inherits the error.

**What it says.** These are the gym working as designed. Each error is pinned to one clause by the line-level comparison (`driving_clauses`), and the net-pay gate caps the score at ≤ 0.25 however many other lines are right. Commercially, an LLM computing payslips directly makes *rule-application* errors a calculator would not. The `naive_no_ceiling` script baseline gets 111/210 payslips exact vs Flash-Lite's 6/210 (EVAL_REPORT).

### 2. Over-refusal on a misread rule (the twins catch it)

- **A job title treated as a conflicting input.** Flash-Lite, `gen-2000005-twin` and `gen-2000021-twin`.
  - Both refuse with `CONFLICTING_RECORDS` because the HR record and the contract give different **job titles**.
  - GEN-§9.2 says the opposite: *"a disagreement … about information that is not an input at all (for example a job title) does not make the payslip undetermined."*
  - 9 of Flash-Lite's 22 refusals of payable payslips are this exact misreading.
  - These tasks are the twins of real conflicting-records traps, which is the design point: the twin differs only in a non-input field, so the model cannot tell "conflict" from "difference".
- **A misread FX rule.** Qwen-3B with tools, `gen-2000002`.
  - It refuses with `UNSUPPORTED_CURRENCY`: *"The exchange rate data only supports rates for the last calendar day of each month, making it impossible to compute the payslip for the middle of a month."*
  - That is the rule (GEN-§8.1 converts at the last day of the period), not a limitation. 116 of its 133 refusals of determinable tasks (of 270: 210 payslips + 60 retrieval) give this reason.

**What it says.** Without the twins, these refusals would look like caution. With them, they are measurably wrong decisions, scored −1 under rubric 1.2+ like answering a trap.

The scaffold changes *which* misreading the 3B makes, not whether it over-refuses:

| Qwen-3B scaffold | refusals of determinable tasks (of 270) | top reason |
|---|---|---|
| S0 bare | 228 | UNSUPPORTED_CURRENCY 111, MISSING_INPUT 105 |
| S1 rules in context | 166 | MISSING_INPUT 154 (UNSUPPORTED_CURRENCY only 6) |
| S2 tools | 133 | UNSUPPORTED_CURRENCY 116 |

With the FX rule's text in context, the 3B stops misreading it; through the `get_fx_rate` tool alone, it misreads it again. Over-refusal is the 3B's dominant failure under every scaffold (TRACK_C.md).

### 3. Answering a trap

- **Never checked the required inputs.** Flash-Lite, `gen-2000039-trap` (KES 2025-12): `tax_residency` is required in Kestrel Isles and no document states it. The model computes a full payslip and explains "computed using Kestrel Isles tax and social insurance rules for 2025".
- **The decision decoupled from its own reasoning.** GRPO-trained 0.5B, `gen-2000013-trap` (NRD 2024-01, no 2024 table).
  - The output is `"decision": "answer"` with `"reason_code": "NO_APPLICABLE_TABLE"`, and the explanation says *"there is no relevant rate table, the payslip cannot be determined"*.
  - All 56 of the trained model's answered-trap rollouts name a reason code this way.

**What it says.** The second example is the most informative transcript in the set. RL moved the policy to *always answer* (the payslips pay), but did not erase its recognition of the trap. The recognition survives in the reason code and the explanation, while the decision field says the opposite. The rubric scores the decision field (correctly), so this is −1. A next step for training follows directly: a consistency check between `decision` and `reason_code` would expose it, and a 1.5B policy may have the capacity to act on what it already recognises (RL_REPORT B5, B8).

### 4. Correct value, broken output contract

- **Trained 0.5B, `gen-2000008`** (Tier 1, VAL social-insurance employee rate). The output is just `0.08`: the right value, no JSON.
- The same happens on all 60 of its Tier-1 rollouts.
- Training used only Tier 2/3 (TRADEOFFS #1), and the format discipline it learned for payslips did not transfer to the retrieval answer format.

**What it says.** It is a fair −1 under the contract, but it is the clearest case where a *narrow* training distribution shows up as a regression: the base model was also −1 here, so nothing was lost; nothing was gained either. Adding a few Tier-1 tasks to training would be cheap.

### 5. Tool loop

- **Gemini 3.1 Flash-Lite with tools, `gen-2000048`** (KES 2026-06): 9 tool calls over 8 turns, then the turn limit, with no final answer.
- 12 of its 18 core6 rollouts end this way.
- The environment records it (`stop_condition: max_turns_reached`) and scores it as no answer, not as a crash.

**What it says.** Tool access without a stopping discipline costs more tokens and produces less. In Track C, the self-check and checklist scaffolds (S3/S4) reduced Qwen-3B's tool calls per rollout (8.1 → 4.8) and improved its score.

## What the failures say about the gym

1. **The gates and line-level clauses make failures diagnosable.** Every failed payslip names its first wrong clause, so "the model is bad at payroll" becomes "it skips the VAL personal allowance" or "it uses the 2026 FX rate in 2025".
2. **The twins and the determinable-refusal penalty are doing real work.** Without them, Flash-Lite's 22 and the 3B's 133–228 refusals of determinable tasks would read as caution.
3. **The scorer reads the decision field, not the prose.** That is what exposed the trained policy's answer-while-saying-refuse behaviour, and what the earlier exploits (RL_REPORT B6) attacked when the field's handling had gaps.
4. **One limit of the gym itself:** the judge scores trap *explanations* only, so a confident but wrong explanation on an answered payslip (the "resident tax rules" example) costs nothing beyond the line errors. That is by design (payslips are graded by arithmetic), but worth stating.
