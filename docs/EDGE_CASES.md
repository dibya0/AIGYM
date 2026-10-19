# Top edge cases (brief §9 #10)

The five that mattered most, each found while building (see `docs/PROGRESS.md`), with how it is handled and the test that guards it.

## 1. Ground truth leaking through the sandbox (three separate routes)
- **What happened:** three independent leak routes turned up during the build.
  1. The rubric's free-text `detail` says things like `net_pay 7000 vs 6934.00 (tolerance 0.01)`. That is exactly the "over-helpful rubric breakdown" the brief warns about.
  2. Generated task ids (`gen-0001234`) encode the per-task seed, and the generator is open source, so a seed is an answer key.
  3. A caller-visible seed would do the same thing.
- **Handled:** per-task seeds are `HMAC(SANDBOX_SECRET, public seed : i)`; task ids are opaque positions; responses carry component *scores* and clause ids only; validation errors return field locations without echoing input; unexpected errors return a generic 500 with no stack trace.
- **Guard:** `tests/test_sandbox.py::test_no_ground_truth_in_any_response` fuzzes every endpoint with valid and invalid input and asserts no expected value, reason code, task seed, secret or `detail` marker appears in any body. Writing that test also exposed a false positive: the word "tolerance" legitimately appears in the rule text shown to agents, so the test now checks detail-only markers.

## 2. Leakage across splits through a small question space
- **What happened:** there are only ~50 distinct retrieval questions (3 jurisdictions × 2 years × ~8 fields), so random seeds produced exact duplicates within a split, and the same question appeared in both train and held-out.
- **Handled:** `generate()` skips any seed whose task repeats one already generated in the split, and the train split has no retrieval tasks (`docs/TRADEOFFS.md` #1). Splits use disjoint seed ranges.
- **Guard:** `tests/test_generator.py::test_no_duplicate_questions_within_a_split`, `test_train_and_heldout_share_no_task` (content-level, not just seeds).

## 3. Abstention as a safe harbour
- **What happened:** a gym that only has traps rewards refusing everything. Group-std reward scaling in GRPO would also rescale the designed penalties and push towards blanket refusal (arXiv 2608.00301).
- **Handled:**
  - every trap has a determinable twin;
  - refusing a determinable payslip is scored through the wrong-answer path (0.05);
  - answering a trap is −1;
  - traps are capped at ~20–25% of tasks;
  - training uses `scale_rewards="none"`;
  - the twin refusal rate is a per-step monitor with a pre-registered safety stop at 0.5.
- **Guard:** `tests/test_rubric.py::test_refusing_a_determinable_payslip_scores_like_a_wrong_answer`, `test_baseline_stays_under_its_floor[always_abstain]`.

## 4. Ambiguity inside the rule set itself
- **What happened:** writing the calculator surfaced four places where the prose did not determine a single answer:
  1. Do *optional* inputs (end date, allowances) count in conflicts?
  2. What if a January KES record states a YTD figure anyway?
  3. Which currency is a salary change in?
  4. Is Valdoria's deductible social insurance the rounded line or the full-precision amount?
- **Handled:** each was fixed in `RULESET.md` (GEN-§2.2, KES-§1.2, GEN-§2.7, GEN-§1.3) **before** the code, because the rule set is the authority. The remaining risk is measured by the fidelity audit (`docs/FIDELITY_AUDIT.md`).
- **Guard:** `tests/test_ruleset.py` parses the prose tables independently and fails on any YAML drift. It was mutation-checked: changing one ceiling fails it.

## 5. A KL sweep that would have measured nothing
- **What happened:** the obvious "too low" β is 0, but reading TRL 1.14.1's source showed that at β = 0 the reference model is not loaded and `kl` is never logged. The low-β run would then have no KL curve, which is the whole point of the sweep.
- **Handled:** the sweep is β ∈ {0.001, 0.04}, and `train/grpo_train.py` refuses β ≤ 0.
- **Guard:** the argument check in the trainer, plus the Step 8 smoke check that `kl` appears in `metrics.csv`.

## Also handled
- **Format and unit ambiguity.** Number locale, DD/MM vs MM/DD, and annual vs monthly salary are all stated in each task (GEN-§2.4–2.6); the parser normalises, and the generator varies them.
- **Schema drift.** Unknown versions and fields are rejected, with a migration path (`tests/test_tasks.py`).
- **Version skew.** The leaderboard never compares across rule-set fingerprints; the sandbox returns 409.
- **Provider failures.** Retries with backoff are marked; a dead provider becomes `unavailable`; runs resume without paying twice; the cost cap aborts cleanly with partial results (`tests/test_eval_harness.py`).
- **Tool misuse.** Bad arguments get a structured error; the identical call 3× in a row ends the rollout; tool errors are counted, never silent.

## Hit during the real runs (candidates for the top 5; final selection at Step 22)
Each one is logged with its evidence in `docs/PROGRESS.md`.
- **The leakage audit itself was wrong, twice** (Step 6). A literal-match false positive ("480,00" inside "22.480,00") and a classifier that collapsed to the majority class (acc 0.7172 vs 0.7171), which could therefore detect nothing. Fixed with number-boundary matching and a balanced classifier judged against chance. Guard: `test_literal_leak_check_matches_whole_numbers_only`.
- **A provider the eval stack could not parse** (Step 12). verifiers 0.2.1 rejected *every* Groq response because the OpenAI SDK's `service_tier` is a closed Literal and Groq says `"on_demand"`. All rollouts were aborted with reward 0, and the run still printed "OK". That is the "silently score 0" failure the brief warns about. Fixed with `paygym/compat.py`, the same widening verifiers made in its v1 stack. Guard: `test_groq_service_tier_is_accepted`. Lesson: a smoke eval must assert non-error rollouts, not just "it returned". A second incompatibility appeared only on turn 2 of tool mode: verifiers replays the model's hidden `reasoning_content`, and Groq 400s on it. The shim drops it (`test_replayed_assistant_reasoning_is_not_sent`). A third appeared on Gemini: its tool calls carry a `thought_signature` that must be echoed back, and verifiers drops it, so every turn 2 got a 400. The shim remembers and re-attaches it by tool-call id (`test_gemini_thought_signatures_are_replayed`). That makes four provider incompatibilities in total, all in one documented shim.
- **The free tier rations tokens, not requests** (Step 12). Groq gpt-oss-120b allows 8,000 tokens/min and one rollout is 3–6.5k tokens, so concurrency 2 hit 429s. Fixed with a token-per-minute sliding window, plus SDK retries that honour `retry-after` per request. Guard: `test_token_limiter_waits_for_the_window`.
- **Protecting free quotas, and the limits redesigning the eval** (user requirement). A list-price `--max-cost` is $0 on free tiers, so it protects nothing. A per-model ledger now caps requests *and* tokens at 75% of the real free limits. My first caps were guesses, and Gemini 3.8 Flash's real limit was 20/day, not 120. The limits forced a fixed core20 subset for the scarce models, compared only paired; tool mode moved off Groq after a 413 (one request > 8K TPM). Guards: `test_caps_come_from_the_published_free_limits_with_headroom`, `test_subset_run_is_compared_with_subset_views_of_full_runs`.
- **A silent training default** (Step 8). TRL's linear LR decay would have made the 30-step LR probe not transfer to 150-step runs. Changed to a constant LR, logged as pre-registration amendment A9.
- **The optimiser found the abstention harbour in 5 steps** (Step 17, rubric v1.0). A refusal of a payable payslip kept 0.05 format credit and beat broken JSON at no risk; refusals went from 1/8 to 5–6/8. The fix was rubric 1.1 (refusal = 0.00), with every saved run re-scored at $0 (`paygym rescore`). Plus a false-positive safety stop from a monitor that counted completions instead of tasks. Guards: `test_refusing_a_determinable_payslip_scores_like_a_wrong_answer`, `test_modal_net_monitor_counts_distinct_tasks_only`.
- **GRPO learned "refuse everything", and the validation reward went UP** (rubric 1.1, step 20). The 0.5B refused 47/47 validation tasks; reward rose −0.063 → +0.081 because the compute/refuse decision was asymmetric (trap answered −1, payable payslip refused 0). The fix was rubric 1.2 (both wrong decisions −1), checked offline on the real outputs first (refuse-all −0.685, refuse-only-traps +0.166). Every eval run was rescored at $0, which also revealed Gemini Flash-Lite wrongly refusing 22 payable payslips. Also caught: the sensitivity table's copy of the weighting had drifted from the rubric. Guards: `test_refusing_a_determinable_payslip_scores_like_a_wrong_answer`, `test_sensitivity_reproduces_the_rubric_under_the_shipped_weights`.
- **Three learned exploits, each the next-cheapest harbour** (rubrics 1.1 → 1.4): refuse everything, then broken JSON, then `"decision": "reject"`, a value the scorer read as a refusal on traps and as a lineless answer on payslips. The last was found only at the too-low β = 0.001 (72 % of its samples) and never at β = 0.04 (0/188 validation), which is the brief's β-sweep shape. Each fix was verified offline on the real outputs before any retraining. Guards: `test_unparseable_is_as_bad_as_a_wrong_decision`, `test_an_invalid_decision_is_unparseable_on_every_tier`.
