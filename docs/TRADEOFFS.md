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
- **Why:** the brief says scale earns nothing and the approach is what is assessed; held-out evaluation still uses full-difficulty tasks, so any gain has to transfer.

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
1. Tool-mode GRPO on the 0.5B policy, so the trained model is measured where tools are the only data source.
2. Fix the biased group-relative advantage on hard prompts (arXiv 2601.08521) with difficulty-weighted advantages, and use the pilot's identical-group fraction to rebalance the train mix.
3. A second slice, payroll anomaly detection (seeded errors, precision/recall), sharing the rule set and reference.
4. Real statutory tables for two countries, with versioned rule sets and a fidelity audit per release.
5. A single-pass decision model for the categorical choices (table year, cap type, refuse or answer), with its calibration measured against this gym's per-decision ground truth.
