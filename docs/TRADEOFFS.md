# Assumptions and trade-offs

Living document (brief §9 #11; §11: "Scope down loudly, not silently"). Each entry: what we decided, why, and what the real implementation would look like.

## Deliberate trade-offs

### 1. No retrieval (Tier-1) tasks in the RL training split
- **Decision:** `train` is generated with tier mix (0, 0.67, 0.33); retrieval tasks appear only in eval / held-out / val.
- **Why:** the rule set has only ~50 distinct retrieval questions (3 jurisdictions × 2 years × ~8 fields). Any retrieval task in train would very likely reappear in held-out, which is the "leakage across the split" the brief warns about (p.12). Retrieval also teaches nothing about payroll logic.
- **Cost:** the before/after on held-out Tier 1 measures transfer of format and reading, not learned values.

### 2. The LLM judge is excluded from the RL reward
- **Decision:** training uses the rubric's programmatic components; the judge (0.2 of a correct trap refusal) is used in eval and the sandbox only.
- **Why:** free-tier judge quota and latency (8 judge calls per group × 4 groups per step), and the risk of the policy learning to please the judge rather than refuse correctly.
- **Cost:** the policy gets no gradient towards *better-written* refusals, only correct ones. A real version would distil the judge into a small reward model or batch judge calls.

### 3. Single-turn RL only (no multi-turn tool RL)
- **Decision:** the GRPO policy trains with the rule set in context, not in tool mode.
- **Why:** multi-turn rollouts multiply generation cost and context length beyond a 2–3 h budget on one 16 GB GPU, and the brief explicitly prefers a finished small run.
- **Cost:** the trained policy is evaluated single-turn; tool-mode results come from the hosted and local models only.

### 4. RL policy fixed at 0.5B; difficulty adapted instead
- **Decision:** if base Qwen-0.5B cannot get a gradient, the **training tasks** are made easier (`--knobs easy|easier`) instead of moving to 1.5B.
- **Why:** the brief says scale earns nothing and the approach is what is assessed.
- **Outcome:** the base 0.5B got 0 % exact payslips at every preset (A11), so training used `easy`. Held-out is reported at both the training preset and full difficulty, and the gain transfers (+0.30 [0.20, 0.41] at full difficulty).
- **Cost:** trap discrimination was not learned; a 1.5B policy is the documented next step.

### 5. Fictional rule set instead of real statutes
- **Decision:** three invented jurisdictions.
- **Why:** answers cannot be recalled from pre-training (brief p.4), and the written rule set can be the single source of truth.
- **Cost:** no claim about real-country accuracy. A real version would need dated statutory tables per country and a fidelity audit per release.

### 6. Filesystem results plus a small Redis, not a database
- **Decision:** eval results are committed JSON (Harvey LAB style); the sandbox keeps only run records and rate-limit counters in Upstash Redis.
- **Why:** nothing relational to store; ground truth is regenerated from signed tokens, never stored; it is free with no card.
- **Cost:** no ad-hoc querying across runs beyond the leaderboard aggregator.

### 7. verifiers pinned at 0.2.1
- **Decision:** pin the last release with the brief's v0 API.
- **Why:** the spec in the brief is v0, and v0 was removed in 0.3.0 (Aug 2026).
- **Cost:** not on the current verifiers line. The README maps the design onto v1 for a port.
- **Cost found in practice (2026-10-19):** the v0 OpenAI-chat client broke on real providers in four ways: Groq `service_tier`, Groq rejecting replayed `reasoning_content`, Gemini's required `thought_signature`, and Groq's per-request TPM (413). The first three are patched in `paygym/compat.py`, each with a test; the fourth changed which provider runs tool mode. A port to verifiers v1 would remove the shim.

### 8. Free tiers and list prices
- **Decision:** the `--max-cost` guardrail runs on *list prices* even though actual spend is $0.
- **Why:** it proves the guardrail works and reports what a paid run would cost.
- **Cost:** a sweep can stop on the list-price cap even when it is free, so the cap is set per run.
- **Second guardrail, the free quota itself:** list-price dollars never protect a free quota, so a daily per-model **ledger** (`paygym.eval.budget`) caps requests *and* tokens at 75% of each model's published free limit, read from the user's own dashboards. That covers all eval runs, the judge and the probe. A capped run stops before the call that would exceed the cap (`aborted_budget`) and resumes the next day.
- **The limits shaped the eval design** (2026-10-19):
  - **Gemini 3.8 Flash** allows 20 requests/day and **Groq gpt-oss-120b** 200K tokens/day (≈ 40 single-turn rollouts). Neither can afford 109 tasks × 3 rollouts. They run on **core20**, a stratified subset fixed in advance (`scripts/make_core_subset.py`: every trap with its twin). The leaderboard compares them only against the other models' rollouts on those same 20 tasks (subset views, paired bootstrap), never against a full-set mean. **Cost:** wider CIs for those two models, stated in EVAL_REPORT.
  - **Tool mode cannot run on Groq.** Each request counts input + max_tokens against an 8K tokens/minute window, and a multi-turn tool request exceeds it (HTTP 413). Tool mode and the Track C comparator therefore use **Gemini 3.5 Flash-Lite** (500 requests/day), and Groq is single-turn only.
  - **The judge** (Gemini 3.1 Flash-Lite) has its own 500/day bucket, so it never competes with an eval.
  - **Wall clock:** the sweep takes ~4 days of once-a-day runs instead of one sitting.

### 9. Scarce frontier models evaluated on fixed subsets
- **Decision:** Gemini 3.8 Flash (20 requests/day) runs on core6 and gpt-oss-120b (200K tokens/day) on core10. Both subsets are stratified, every trap with its twin, and fixed before any model was scored. Gemini 3.5 Flash-Lite (500/day) covers the full eval.
- **Why:** the user asked for the evaluation to finish in about a day without exhausting any free quota.
- **Cost:** wide CIs for those two (6 and 10 tasks). They are compared only paired with other models' rollouts on the same tasks, never against a full-set mean.

### 10. The rubric changed during the project (1.0 → 1.4), and every run was re-scored
- **Decision:** when the trained policy exposed an exploit, fix the rubric, bump its version, and re-score every saved eval run (`paygym rescore`, no model calls) rather than keeping old numbers.
- **Why:** a reward that a trained policy can game is not the reward we want to report against. One version per comparison avoids silent skew.
- **Cost:** the training runs themselves used the rubric of their time (the reported β = 0.04 run used 1.3). Its validation and held-out results are scored under 1.4, which differs from 1.3 only on outputs that run never produced on validation.

### 11. Brief-minimum RL scope and an untuned learning rate
- **Decision:** 30 training tasks, 60 steps per β, two β values, one seed each; LR fixed at 5e-5 after the pre-registered probe was cancelled (A10, A13).
- **Why:** the user asked for the brief's minimum to show the flow; the brief itself says a working loop on 30 tasks with an honest held-out comparison is enough.
- **Cost:** no seed variance per β, no β above 0.04, and LR chosen by argument from the observed KL rather than a probe.

### 12. Infrastructure failures are not model failures, but empty model output is
- **Decision:** a rollout that times out before the model replies (our rate-limit queue) is an error, retried and not scored. A reply with no usable content is a scored −1.
- **Why:** the first rule stops the harness penalising a model for our queue; the second stops it excluding real failures, which flattered tool mode.
- **Cost:** the line needs judgement at the edges (e.g. a partially streamed reply). Both rules are documented in the runner.

## What we mocked (brief §11.5)
- **The rule set and jurisdictions (fictional):** so answers cannot be recalled from pre-training (brief p.4). Real version: statutory tables per country with effective dates, maintained against official sources.
- **Employees and documents (synthetic):** no real personal data (brief §11.3). Real version: HRIS and contract-management records.
- **FX table:** fixed month-end rates per year. Real version: a dated rate feed with an auditable source.

## What we cut, and what we would do with two more days (brief §11.6)

**Cut (deliberately):**
- the decision-LLM "decide-then-compute" agent (README, next steps);
- multi-turn tool RL;
- the sandbox driving the caller's agent from their base URL + key (optional in the brief; would mean handling others' keys);
- a judge-distilled reward model;
- Supabase/Postgres (nothing relational to store);
- a third β value.

**With two more days:**
1. **Qwen2.5-1.5B under rubric 1.4,** β ∈ {0.001, 0.04, 0.1}, 2 seeds each. Does trap discrimination become learnable once some answers in a group are right?
2. **The three learned exploits become permanent adversarial baselines** (broken JSON everywhere, invalid decision word, refuse everything), so future rubric changes are tested against what the optimiser found.
3. **GRPO group construction:** trap and twin in the same step, more prompts per step (68–74 % of groups had no gradient), and a few Tier-1 tasks in training (the trained model lost the retrieval answer format).
4. **Tool-mode GRPO,** so the trained model is measured where tools are the only data source.
5. **A second slice** (payroll anomaly detection), **real statutory tables** for two countries, and **a single-pass decision model** for the categorical choices, with its calibration measured against this gym's per-decision ground truth.
