# Advanced track C: scaffold comparison (brief §7)

**Question (brief §7):** "Hold the model constant and vary the agent scaffold: prompt structure, tool availability, self-check step. Show whether scaffold matters more than model choice."

**Answer in one line:** for a small open model the scaffold moves the score by +0.21, but the model effect changes *sign* with the scaffold, and a frontier model with the plainest useful scaffold beats the best small-model scaffold by +0.73. Pick the model and the scaffold together; the cheapest scaffold step (put the rules in the prompt) gives most of the scaffold gain.

## Setup

- **Fixed model:** Qwen2.5-3B-Instruct, served locally by vLLM on an RTX 5070 Ti. $0, no hosted quota.
- **Comparison model:** Qwen2.5-0.5B-Instruct at S0 and S4 (matched scaffolds).
- **Tasks and settings:** the full eval split, 109 tasks × 3 rollouts per configuration, temperature 1.0 with the model's own top-p/top-k, rubric 1.4, the same harness as the leaderboard.
- **Frontier reference:** Gemini 3.5 Flash-Lite at the default single-turn prompt (= S1) on the same 109 tasks.
- **Data:** `results/local__qwen2.5-{3b,0.5b}/trackc-S*/`, `results/track_c/summary.json`; dashboard §Track C.

| Scaffold | What changes |
|---|---|
| S0 | bare prompt: the task, no rule set |
| S1 | rule-set sections in context (the default single-turn prompt) |
| S2 | no rules in context; tools: `get_employee_record`, `lookup_rules`, `get_fx_rate`, `calc` (the default tool mode) |
| S3 | S2 + a mandatory `calc` self-check before answering |
| S4 | S3 + a checklist: table year, missing/conflicting inputs, FX support, ceiling type, proration, allowances |

S1 and S2 send exactly the default single-turn and tool-mode prompts (verified on every task, `test_track_c_s1_s2_are_the_default_configurations`). They are therefore also Qwen-3B's leaderboard rows.

## Results

| Model | Scaffold | Mean reward (± run SD) | Correct trap refusals | Twins | Tokens / rollout | Tool calls / rollout |
|---|---|---|---|---|---|---|
| Qwen-3B | S0 bare | −0.622 ± 0.004 | 16 % | −1.000 | 0.6 K | 0 |
| Qwen-3B | **S1 rules in context** | **−0.485 ± 0.009** | **47 %** | −0.891 | 4.6 K | 0 |
| Qwen-3B | S2 tools | −0.526 ± 0.028 | 26 % | −0.927 | 23.2 K | 8.1 |
| Qwen-3B | S3 tools + self-check | −0.423 ± 0.020 | 26 % | −0.622 | 29.7 K | 7.3 |
| Qwen-3B | **S4 tools + self-check + checklist** | **−0.412 ± 0.018** | 18 % | −0.640 | 28.1 K | 4.8 |
| Qwen-0.5B | S0 bare | −0.454 ± 0.009 | 5 % | −0.391 | 0.7 K | 0 |
| Qwen-0.5B | S4 | −0.997 ± 0.004 | 0 % | −1.000 | 5.2 K | 1.6 |
| *Gemini 3.5 Flash-Lite (reference)* | *S1* | *+0.314 ± 0.024* | | | | |

Exactly correct payslips: **0 % in every Qwen configuration.** Every difference above comes from decisions (refuse vs compute), format and partial line credit, not from correct arithmetic.

## Finding

1. **The scaffold matters for a fixed small model: +0.21** (S0 → S4).
   - Most of it comes from the cheapest step: **rules in context (S1) gives +0.14 at 4.6 K tokens.**
   - **Tools alone (S2) are worse than rules in context** (−0.526 vs −0.485) at 5× the tokens. The model makes ~8 tool calls but often stops without a usable answer, and 27 of 327 S2 rollouts were empty replies (scored −1).
   - The self-check (S3) and checklist (S4) recover +0.10 over S2 and end slightly above S1 (−0.41 vs −0.49), at 6× S1's tokens.
2. **Model vs scaffold has no single answer: the effect changes sign.**
   - **At S0 the 0.5B beats the 3B** (−0.454 vs −0.622). Without the rule set, the larger model refuses most payable payslips (228/327 rollouts, −1 each), which is reasonable behaviour that the rubric penalises, while the small one guesses.
   - **At S4 the 3B wins by +0.59.** The 0.5B cannot drive the tools.
   - The "mean" model effect (−0.21) equals the scaffold effect (+0.21) only by averaging two opposite effects.
3. **Against a frontier model, the model gap dominates.** Gemini Flash-Lite at S1 (+0.314) is **+0.80 above the 3B at S1** and +0.73 above the 3B's best scaffold. On this gym, no scaffold closes the gap between a 3B and a frontier model.

## Commercial reading

- **Cost per point.** For a small model, the rule book in the prompt is the best value: +0.14 for ~4.6 K tokens per task. Tool scaffolds cost ~5–6× more tokens for at most +0.07 more. At a hypothetical $0.10 / M tokens: S1 ≈ $0.46 per 1,000 tasks, S4 ≈ $2.8 per 1,000 tasks.
- **Cost per correct payslip** is undefined for every Qwen configuration (none correct). For payroll, where a wrong net pay is a real error, the gym says: no small open model here is fit to compute payslips unsupervised, whatever the scaffold. A frontier model with the rules in context is the starting point, and the scaffold is a second-order lever on top.
- **Scaffolds also change failure modes.** S0 makes a careful model refuse everything; tool scaffolds create empty replies and tool loops. A scaffold choice should be made against the failure modes it introduces, not only the mean.

## Limits

- One fixed model (3B) and one comparison model; the frontier comparison is at S1 only, because Gemini's free quota could not cover multi-turn S2–S4 on 109 tasks.
- Tool-mode rollouts are capped at 8 turns.
- 3 rollouts per task; the run SDs (≤ 0.03) are small next to the effects reported.
- Rubric 1.4 penalises a refusal of a payable payslip at −1. Under a softer penalty, S0's careful refusals would look better and the S0 sign flip could shrink.
