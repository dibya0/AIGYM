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
