# Top edge cases (brief §9 #10)

The five that mattered most, all **hit** during the build and the real runs, with how each is handled and the test that guards it. The full record, with dates, error messages and numbers, is in `docs/PROGRESS.md`.

## 1. The trained policy gamed the reward, three times

- **What happened:** GRPO on the 0.5B found the cheapest harbour the rubric left open, within 20 steps, three times in a row. Each time the validation reward *rose* while competence fell.

  | Rubric | Exploit learned | Evidence |
  |---|---|---|
  | 1.1 | **refuse everything** (refusing a payable payslip cost 0, answering a trap cost −1) | 47/47 validation tasks refused at step 20; val −0.063 → +0.081; entropy 0.49 → 0.16 |
  | 1.2 | **broken JSON everywhere** (an unparseable answer cost 0, both wrong decisions −1) | 47/47 unparseable at step 20; parse failure 100 % for 6 steps |
  | 1.3 | **an invalid decision word**: `"decision": "reject"` read as a refusal on traps (+0.3) and as a lineless answer on payslips (0.0) | 72 % of training samples; found at β = 0.001 only, never at β = 0.04 (0/188) |

- **Handled:**
  - rubric 1.2 → 1.4: every wrong decision and every unusable answer is −1, and the score is monotone in competence;
  - each fix was checked **offline on the policy's real outputs before any retraining** (e.g. refuse-all −0.685, refuse-only-traps +0.166 under 1.2);
  - all eval runs were re-scored to the current rubric at $0 (`paygym rescore`).
- **What it shows:** the 5 hand-written adversarial baselines stayed under their floors throughout and found none of the three. Under 1.3/1.4 the β = 0.04 run improved for 60 steps without an exploit.
- **Guards:**
  - `test_refusing_a_determinable_payslip_scores_like_a_wrong_answer`;
  - `test_unparseable_is_as_bad_as_a_wrong_decision`;
  - `test_an_invalid_decision_is_unparseable_on_every_tier`;
  - `test_sensitivity_reproduces_the_rubric_under_the_shipped_weights` (a second copy of the weighting had drifted).

## 2. Ground truth leaking through the sandbox (three routes)

- **What happened:** three independent leak routes turned up while building the sandbox.
  1. The rubric's free-text `detail` names expected values (`net_pay 7000 vs 6934.00`).
  2. Generated task ids encode the per-task seed, and the generator is open source, so a seed is an answer key.
  3. A caller-visible seed would do the same.
- **Handled:**
  - per-task seeds are `HMAC(SANDBOX_SECRET, public seed : i)`;
  - task ids are opaque positions;
  - responses carry component scores and clause ids only;
  - validation errors do not echo input, and unexpected errors return a generic 500;
  - nothing about answers is stored: tasks are regenerated from the signed `run_id`.
- **Verified live** on https://aigym-alpha.vercel.app (no `ground_truth` in `/tasks`).
- **Guard:** `test_no_ground_truth_in_any_response` fuzzes every endpoint with valid and invalid input. Writing it exposed a false positive (clause ids that are part of the rule text every agent sees), and the test was narrowed rather than the check weakened.

## 3. Measurements that silently scored the wrong thing

- **What happened:** several harness paths produced plausible numbers that were wrong, each found by reading transcripts rather than summaries.
  - verifiers 0.2.1 rejected **every** Groq response (`service_tier: "on_demand"`). A smoke run printed "OK" with every rollout aborted.
  - Tool mode failed on turn 2 for two more provider reasons (replayed `reasoning_content`; Gemini's `thought_signature`).
  - A run with **0/400 successful rollouts reported `completed`**.
  - **Valid unfenced JSON was misparsed.** 10/20 gpt-oss answers were scored unparseable; core10 0.400 → 0.566 after the fix.
  - **Empty rate-limit timeouts** (our queue, not the model) were scored as the model's answers.
  - **Empty model replies in tool mode** were *excluded*, which flattered tool scaffolds.
  - **The dashboard headlined a 6-task subset**: "Gemini 3.8 Flash best, 1.000" on 4 scored tasks.
- **Handled:**
  - one documented compatibility shim (`paygym/compat.py`);
  - a run with no successes is never `completed`;
  - a top-level JSON decoder in the parser;
  - an infrastructure-vs-model rule: an empty timeout is an error and is retried; an empty model reply is a scored −1;
  - the main leaderboard is the full eval.
- **Guards:**
  - `test_groq_service_tier_is_accepted`, `test_replayed_assistant_reasoning_is_not_sent`, `test_gemini_thought_signatures_are_replayed`;
  - `test_a_run_where_nothing_succeeded_is_never_completed`;
  - `test_unfenced_object_with_nested_lines_is_parsed`;
  - `test_empty_timeout_is_an_infrastructure_error_and_is_retried`, `test_an_empty_model_reply_is_a_scored_failure_not_an_error`;
  - `test_main_leaderboard_is_the_full_eval_not_a_bigger_subset_group`.

## 4. Training measured a different policy than the one we evaluated

- **What happened:** three mismatches would each have made the RL result meaningless.
  1. **Sampler:** TRL sampled with top-p 1.0 and no top-k, while the pilot (vLLM) used the model's own top-p 0.8 / top-k 20 / repetition 1.1. Training broke JSON up to 69 % of the time vs 16–38 % in the pilot.
  2. **Validation distribution:** we trained on the `easy` preset but validated at full difficulty, where the 0.5B scores 0 on payslips, so learning would have been invisible.
  3. **Safety stops on noise:** each logged twin-refusal value came from one or two prompt groups, and the base model already refuses some twins 4/4, so runs stopped at step 6–7 before learning.

  An early claim that the policy "learned to refuse in 5 steps" was exactly this noise. It was retracted in RL_REPORT B6.
- **Handled:**
  - sampler parity (A12);
  - `val_easy` / `heldout_easy` from never-trained seed ranges with 0 content overlap (A13);
  - held-out reported at both difficulties;
  - collapse stops relative to the policy's own start;
  - all logged as pre-registration amendments **before** the reported runs.
- **Guard:** the training `config.json` records sampler, rubric version and stop rules; amendments A10–A16 in `docs/RL_REPORT.md`.

## 5. Free-tier limits redesigned the evaluation

- **What happened:**
  - Gemini 3.8 Flash allows 20 requests/day, and Groq gpt-oss-120b allows 200K tokens/day with 8K/minute.
  - My first per-provider caps were guesses (120/day); Groq bills ~1.4× the token usage it reports.
  - One tool-mode request exceeds Groq's per-minute window (HTTP 413).
  - The user also required that no account's quota be exhausted.
- **Handled:**
  - **ledger:** a per-model daily ledger caps requests *and* tokens at 90 % of each published limit (from the user's own dashboards), paces every request, and resumes the next day;
  - **subsets:** the scarce models run on fixed, stratified subsets (core6 / core10, every trap with its twin), compared only paired with every other model's rollouts on the same tasks;
  - **tool mode** moved to Gemini.
  - Actual spend $0, list-price equivalent ≈ $0.82.
- **Guards:**
  - `test_caps_come_from_the_published_free_limits_with_headroom`;
  - `test_daily_request_budget_stops_cleanly_and_resume_continues`;
  - `test_subset_run_is_compared_with_subset_views_of_full_runs`;
  - `test_token_limiter_waits_for_the_window`.

## Also handled

- **Leakage across splits through a small question space.** ~50 distinct retrieval questions produced duplicates within a split and across train/held-out. Fixed with content-level dedup, no Tier 1 in training, and disjoint seed ranges (`test_train_and_heldout_share_no_task`).
- **The leakage audit itself was wrong, twice.** A literal-match false positive ("480,00" inside "22.480,00"), and a classifier that collapsed to the majority class. Fixed with number-boundary matching and a balanced classifier judged against chance.
- **Ambiguity inside the rule set.** Writing the calculator surfaced four places where the prose did not determine one answer. Each was fixed in `RULESET.md` before the code; the YAML/prose agreement is tested.
- **A KL sweep that would have measured nothing.** At β = 0, TRL does not load the reference and logs no KL. The sweep uses 0.001, and the trainer refuses β ≤ 0.
- **A 16.5 GB attention allocation at training step 14.** Two equal-length prompts meant no padding mask, so Transformers took the grouped-query path, and in float32 no fused kernel supports it. Found from the real call's logged shapes after two fixes verified only on reconstructed inputs failed. Handled by an exact chunked fallback that logs any call it handles.
- **Deploy:** Vercel installed from `pyproject.toml`/`uv.lock` (no FastAPI) instead of `requirements.txt`. Fixed with `.vercelignore`, verified on a copy of the exact upload before redeploying.
- **Format and unit ambiguity** (number locale, DD/MM vs MM/DD, annual vs monthly), **schema drift**, **version skew** (409; one rubric version per comparison), **tool misuse** (structured errors, loop detection).
