# Evaluation report (brief §9 #6)

*From committed result files (`results/`), rubric **1.4**, rule set **1.0** (fingerprint `42b009c25d689c46`). Every eval run was re-scored to rubric 1.4 with `paygym rescore` (saved completions, no model calls), so no row mixes rubric versions. Items still open are marked ⏳.*

## Setup

- **Taskset:** the `eval` split, 95 seeds → **109 tasks**: 20 retrieval (Tier 1), 70 payslips (Tier 2, 19 of them twins of traps) and 19 traps (Tier 3).
- **Rollouts and sampling:** 3 per task. Temperature 1.0; the model's own top-p/top-k for local models; provider defaults for hosted ones. gpt-oss runs at `reasoning_effort=low` (see Groq below).
- **Subsets for the scarce free tiers:** the core subsets (`tasks/subsets/eval_core{6,10}.txt`) were fixed before any model was scored and are stratified with every trap's twin. Every other model is also scored on exactly those tasks, so subset comparisons are paired.
- **Configurations (all $0):**

  | Config | Role | Provider | Tasks |
  |---|---|---|---|
  | Gemini 3.5 Flash-Lite | frontier lab, full coverage | Google AI Studio free tier | 109 |
  | Gemini 3.8 Flash | strongest Gemini on the free tier (20 req/day) | Google AI Studio | core6 ⏳ (4/6 tasks scored until the top-up) |
  | gpt-oss-120b | large open-weight | Groq free tier (200K tokens/day) | core10 (20/30 rollouts ⏳) |
  | Gemini 3.1 Flash-Lite, tool mode | hosted tool use | Google AI Studio | core6 |
  | Qwen2.5-3B (S1 = default prompt) | mid open-weight | local vLLM, RTX 5070 Ti | 109 |
  | Qwen2.5-0.5B base / GRPO-trained | small | local vLLM | 109 |
  | 5 adversarial baselines | reward probes | no model | 109 |

## Results (mean reward ± run SD; `results/leaderboard.json`)

**Full eval, single-turn, 109 tasks** (the main comparison group):

| Model | Mean ± SD | Tier 1 | Tier 2 | Tier 3 | Twins | Tasks at 1.0 | Tasks ≤ 0 | Rollout disagreement |
|---|---|---|---|---|---|---|---|---|
| Gemini 3.5 Flash-Lite | **+0.314 ± 0.024** | 1.000 | 0.063 | 0.517 | −0.069 | 25 % | 14 % | 22 % |
| *baseline: naive_no_ceiling* | +0.249 | 0.098 | 0.631 | −1.000 | 0.668 | 35 % | 17 % | 0 % |
| *baseline: gross_as_net* | −0.027 | 0.098 | 0.201 | −1.000 | 0.201 | 1 % | 17 % | 0 % |
| *baseline: modal_answer* | −0.095 | 0.098 | 0.096 | −1.000 | 0.090 | 1 % | 17 % | 0 % |
| *baseline: format_only* | −0.104 | 0.050 | 0.095 | −1.000 | 0.087 | 0 % | 17 % | 0 % |
| Qwen2.5-0.5B, GRPO-trained | −0.331 ± 0.005 | −1.000 | 0.041 | −1.000 | −0.030 | 0 % | 39 % | 3 % |
| Qwen2.5-3B (S1) | −0.485 ± 0.009 | −0.248 | −0.775 | 0.332 | −0.891 | 6 % | 67 % | 4 % |
| Qwen2.5-0.5B, base | −0.652 ± 0.009 | −1.000 | −0.527 | −0.749 | −0.561 | 0 % | 76 % | 18 % |
| *baseline: always_abstain* | −0.737 | −1.000 | −1.000 | 0.511 | −1.000 | 0 % | 83 % | 0 % |

**Subsets** (paired against every other model's rollouts on the same tasks; dashboard "subset" groups):

| Model | Subset | Mean ± SD |
|---|---|---|
| gpt-oss-120b (Groq) | core10 | **+0.566 ± 0.214** (20/30 rollouts; ⏳ 10 to top up) |
| Gemini 3.8 Flash | core6 | ⏳ 4/6 tasks scored (10 rollouts were empty timeouts in *our* rate-limit queue, reclassified as infrastructure errors and re-run in the top-up) |
| Gemini 3.1 Flash-Lite, **tool mode** | core6 | −0.380 ± 0.050 |

## What the leaderboard says

1. **The gym separates good from bad behaviour, but no model computes payroll well.**
   - Gemini 3.5 Flash-Lite gets **net pay exactly right on 6 of 210 payslip rollouts (3 %)**.
   - The `naive_no_ceiling` *baseline*, a deterministic script that ignores the contribution ceilings, gets **111 of 210 (53 %)**, because the ceiling does not bind on about half the tasks.
   - Flash-Lite's first wrong line is usually **earned salary** (100 rollouts: proration, salary changes, FX) or the **tax brackets** (51).
   - Flash-Lite wins overall only on decisions: retrieval 1.00, traps +0.52 vs −1.00.
   - **Commercial reading:** use an LLM for the *decisions* (is this payslip determinable, which rule applies) and a calculator or tools for the arithmetic, not an LLM alone.
2. **The trained 0.5B (−0.331) beats its base (−0.652) and the 3B (−0.485) on the full eval.** It writes valid payslips and never refuses payable work, but it answers every trap (Tier 3 −1.0). RL_REPORT B5 has the held-out version.
3. **Tool mode does not rescue small or cheap models here:**
   - Gemini 3.1 Flash-Lite with tools −0.38 on core6, and empty final answers after 8 turns (tool loops) in 12/18 rollouts;
   - Qwen-3B's best tool scaffold −0.41 vs −0.49 with rules in context (TRACK_C.md).

## Score distribution (brief P02: non-degenerate)

- **Range:** per-task mean rewards cover −1 to +1 for every model.
- **Share of tasks at 1.0:** 0–35 % across models.
- **Share of tasks at ≤ 0:** 14–83 %.
- **No model is everywhere 0 % or 100 %.** The gym discriminates both between models and between baselines.

## Where the gym cannot tell models apart (paired bootstrap 95 % CI contains 0)

| Pair (full eval) | Δ mean | 95 % CI |
|---|---|---|
| naive_no_ceiling vs Gemini 3.5 Flash-Lite | −0.066 | [−0.260, +0.120] |
| Qwen-0.5B trained vs Qwen-3B (S1) | +0.154 | [−0.068, +0.348] |
| Qwen-0.5B base vs Qwen-3B (S1) | +0.168 | [−0.001, +0.320] |
| always_abstain vs Qwen-0.5B base | −0.084 | [−0.221, +0.074] |
| format_only vs modal_answer | −0.009 | [−0.029, +0.001] |

The first row is the most important: **on this taskset, the best full-coverage hosted model is not distinguishable from a script that ignores ceilings.** Its strength on decisions is cancelled by its weakness on arithmetic. This is reported, not hidden in the ranking.

## Adversarial baselines vs floors (`paygym/baselines.py`, `tests/test_rubric.py`)

| Baseline | What it does | Mean (eval) | Floor | Holds? |
|---|---|---|---|---|
| format_only | valid JSON, garbage values | −0.104 | ≤ 0.10 | ✅ |
| always_abstain | refuse everything | −0.737 | ≤ 0.20 | ✅ |
| modal_answer | the same answer everywhere | −0.095 | ≤ 0.10 | ✅ |
| naive_no_ceiling | correct except ceilings ignored | +0.249 | ≤ 0.35 | ✅ |
| gross_as_net | net pay = gross pay | −0.027 | ≤ 0.10 | ✅ |

All five stay under their floors. They did **not** find the three exploits the trained policy found (refuse everything under 1.1, broken JSON under 1.2, an invalid decision word under 1.3; RL_REPORT B6). The brief's point holds here: an optimiser attacks the reward harder than hand-written probes.

## Reward weights: does the ranking change? (`results/weight_sensitivity.json`)

Re-scoring every full-eval run under four weightings (shipped 0.70/0.25/0.05, net-heavy, lines-heavy, no-format) gives **Kendall's τ = 1.0 against the shipped ranking for all four**. The ranking does not depend on the weight choice. The sensitivity table is checked to reproduce the rubric exactly under the shipped weights (`test_sensitivity_reproduces_the_rubric_under_the_shipped_weights`); a copy of the weighting had drifted at rubric 1.2 and was fixed.

## Judge reliability ⏳

The judge (Gemini 3.1 Flash-Lite, pinned) scores trap explanations only: 0.2 of a correct refusal's score.

- **3-repeat disagreement rate** (the brief's minimum): run after the quota reset with `paygym judge items … && paygym judge repeat` → `results/judge/`.
- **Hand labels:** optional (the brief accepts either method).
- **Known risk:** in the one tool-mode run the judge scores its own model family's explanations (self-preference). Limited impact: 0.2 of 1 trap × 3 rollouts.

## Rule-set fidelity divergence rate

**0 / 50 (0 %)**: 10 generated tasks hand-derived from `RULESET.md` before comparing with the reference (48 payslip lines + 2 refuse decisions). Rules not exercised by that sample and the limits of a same-author check are listed in `docs/FIDELITY_AUDIT.md`.

## Answer-leakage and near-duplicate audit (`results/audit/*.json`)

| Split | Literal leaks | Classifier balanced acc. vs chance | Exact / near duplicates |
|---|---|---|---|
| eval | 0 | 0.202 vs 0.20 (no signal) | 0 / 0 |
| train | 0 | 0.320 vs 0.20 | 0 / 0 |

- **The train classifier's lift was read by hand.** It comes from genuine evidence: the years 2027/2024/2020 for `NO_APPLICABLE_TABLE`, and GBP/JPY for `UNSUPPORTED_CURRENCY`. Names and IDs shared with twins add a little. No template wording gives the label away.
- **The audit caught two bugs in itself:** a literal-match false positive ("480,00" inside "22.480,00"), and a classifier that collapsed to the majority class. Both were fixed (PROGRESS.md, Step 6).

## Compute spend

- **Actual: $0.00.** Free tiers only (Google AI Studio, Groq), plus a local RTX 5070 Ti.
- **List-price equivalent of all hosted eval runs:** ≈ **$0.82** (sum of `cost_list_usd` in `results/*/*/metrics.json`).
- **GPU:** local; not metered. Roughly 6–9 h in total, from the logged step times and run durations: pilots, about 10 training runs (including the stopped ones; ~35–45 s/step), held-out and Track C inference.
- **Free-quota protection:** a per-model daily ledger caps requests and tokens at 90 % of each published free limit (`paygym/eval/budget.py`).

## Non-determinism (brief P05)

- **Run-to-run SD:** Gemini Flash-Lite 0.024; 3B 0.009; 0.5B base 0.009; 0.5B trained 0.005; gpt-oss 0.21 (on 10 tasks with partial rollouts).
- **Rollout disagreement** (tasks whose 3 rollouts did not all score the same):
  - Flash-Lite 22 %, 0.5B base 18 %, the 3B 4 %;
  - the **trained 0.5B 3 %**: RL made it nearly deterministic (RL_REPORT B5).
- **Reported as is:** a ranking change smaller than these spreads is listed as indistinguishable (above), never as a win.

## Harness problems found while evaluating (all fixed; PROGRESS.md)

1. **Groq's 8K-tokens-per-minute window:** one tool-mode request cannot fit, so tool mode moved to Gemini.
2. **Unfenced JSON was misparsed:** 10/20 valid gpt-oss answers had been scored unparseable; core10 went from 0.400 to 0.566 after the fix.
3. **Empty rate-limit timeouts:** Gemini 3.8 Flash rollouts that never reached the model had been scored as the model's answers. They are now infrastructure errors, retried.
4. **Empty model replies in tool mode:** they had been excluded, which flattered tool scaffolds. They are now scored failures.
5. **Four verifiers-0.2.1 incompatibilities** with Groq and Gemini, fixed in one documented shim (`paygym/compat.py`).
