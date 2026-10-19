# Evaluation report (brief §9 #6)

*Filled from committed result files after the Step 15 sweep. Every number links to its source file.*

## Setup
- **Taskset:** `eval` split, 95 seeds → N tasks (tier mix …), rule set v1.0 (fingerprint …); 3 rollouts per task at temperature 1.0.
- **Models (all $0):**
  - Gemini … (frontier, Google AI Studio free tier);
  - gpt-oss-120b (Groq free tier);
  - Qwen2.5-3B and Qwen2.5-0.5B (local vLLM);
  - 5 adversarial baselines.

## Results (mean ± SD; `results/leaderboard.json`)
| Model | Mean ± SD | Tier 1 | Tier 2 | Tier 3 | Twins | Rollout disagreement |
|---|---|---|---|---|---|---|

## Score distribution (non-degenerate?)
Share of tasks at 1.0 and at ≤ 0 per model (dashboard histogram; brief P02).

## Where the gym cannot distinguish models
(paired bootstrap 95% CIs containing 0)

## Adversarial baselines vs floors
| Baseline | Mean | Floor | Holds? |
|---|---|---|---|

## Reward weights: does the ranking change?
(`results/weight_sensitivity.json`, Kendall's τ)

## Judge reliability
- 3-repeat disagreement rate: … (`results/judge/reliability_repeat.json`)
- Agreement with 15 hand labels: … ; Cohen's κ: … (`results/judge/reliability_human.json`)

## Rule-set fidelity divergence rate
… (`docs/FIDELITY_AUDIT.md`)

## Answer-leakage and near-duplicate audit
… (`results/audit/*.json`): literal leaks, classifier accuracy vs majority with top n-grams, duplicates

## Compute spend
- Actual: **$0.00**.
- List-price equivalent: $… (`metrics.json` per run).
- GPU: local RTX 5070 Ti, ~… h.

## Non-determinism
…
