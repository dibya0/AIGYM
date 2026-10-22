# PayGym walkthrough: every requirement, what we built, how to check it, what it showed

This is for **you**, to understand and defend the project yourself. It follows Niural's brief in order. For each requirement:

- **Brief:** the requirement, in the brief's own words (shortened);
- **Built:** what we made, in plain language, and where it lives;
- **Check:** a command you can run, or the test that proves it;
- **Result:** what it produced;
- **Status:** ✅ done · 🟡 done with a stated limit · ⏳ still to run.

All numbers come from committed files in `results/`, scored under **rubric 1.4** and **rule set 1.0**.

---

## Part 0. The whole system in 60 seconds

```
RULESET.md (the law, in prose, with clause ids like VAL-§2.1)
   │  every number is also in rules.yaml (a test checks the two agree)
   ▼
reference calculator (paygym/reference/)      ← trusted: hand-checked, property-tested, fidelity-audited
   │  computes the correct payslip + which clause drove each line
   ▼
task generator (paygym/generator.py)           ← seed → tasks with known-correct answers, no LLM involved
   │  Tier 1 lookup · Tier 2 payslip · Tier 3 trap (+ its "twin" that is payable)
   ▼
environment (paygym/environment.py)            ← the verifiers object: prompts + tools + parser + rubric
   ├── EVAL harness  (python -m paygym.eval)   → results/<model>/<run>/{config,transcript,metrics,scores}.json
   ├── RL trainer    (train/grpo_train.py)     → results/train/<run>/{metrics,validation}.csv + checkpoints
   └── SANDBOX API   (paygym/sandbox/, Vercel) → https://aigym-alpha.vercel.app
                         │
   rubric (paygym/rubric.py) = the ONE scoring function used by all three
   ▼
dashboard (public/, Vercel)                    ← reads results/, shows leaderboard, failures, RL, Track C
```

**The core idea.** Payroll is arithmetic over written rules. If you have a program you trust that applies the rules, you can mark any model's answer automatically, forever. That program is the **reference calculator**, and it is the "verifier" the brief talks about.

---

## Part 1. What every metric means

| Metric | Meaning | Good is |
|---|---|---|
| **reward / score** of one answer | the rubric's mark for one answer, from −1 to +1 (levels below) | high |
| **mean reward** | average over tasks of the per-task average over its 3 rollouts (every task counts equally) | high |
| **rollout** | one attempt by the model at one task; we do **3 per task** (temperature 1.0), because one attempt is noise | – |
| **run SD (± SD)** | how much the mean moves between rollout #1, #2 and #3: the run-to-run noise | small |
| **rollout disagreement** | share of tasks whose 3 rollouts did not all get the same score | context |
| **Tier 1 / 2 / 3** | retrieval / payslip computation / trap (should refuse) | – |
| **twins** | payable payslips that look like traps; a low twin score means **over-refusal** | high |
| **gate** | why an answer was capped: `wrong_net_capped`, `refused_determinable`, `answered_trap`, `unparseable`, `wrong_reason` | – |
| **driving clause** | the rule clause behind the mark, e.g. `VAL-§2.1` (ceiling) or `GEN-§9.1` (missing input) | – |
| **95 % CI (paired bootstrap)** | range the true difference between two models plausibly lies in, computed on the same tasks; if it contains 0, we **cannot** say one is better | excludes 0 |
| **Kendall's τ** | how similar two rankings are (1.0 = identical); used to show the weights don't change the ranking | 1.0 |
| **KL** (RL) | how far the trained policy has drifted from the original model, k3 estimator, per token | small, steady |
| **entropy** (RL) | how varied the policy's outputs are; collapsing to ~0 means it repeats itself | not collapsing |
| **frac_reward_zero_std** (RL) | share of groups where all 8 samples scored the same, so no learning signal | low |
| **held-out** | tasks from seed ranges the policy never trained on, scored **once**; the only honest test of learning | – |

**Score levels (rubric 1.4, `paygym/rubric.py`):**

| Task | Score |
|---|---|
| payslip | 1.0 every line right · 0.75–0.99 net right, some lines wrong · ≤ 0.25 net wrong (capped) · **−1** refused a payable payslip · **−1** unparseable |
| trap | 1.0 refused, right reason, good explanation (judge) · 0.8 right reason · 0.3 wrong reason · **−1** computed it anyway · **−1** unparseable |
| retrieval | 1.0 exact · 0.05 wrong value · **−1** refused or unparseable |

**Why every wrong decision is −1:**
- refusing a payable payslip means people are not paid;
- computing a trap means paying on rules that don't determine the pay;
- an unreadable answer can't be paid or reviewed.

---

## Part 2. Phase by phase

### Phase 01: Task schema and seed taskset

| Brief | Built | Check | Status |
|---|---|---|---|
| "Define a task schema … validate it programmatically. Minimum fields: id, slice, difficulty, prompt, context_files, ground_truth, verifier, tags, schema_version" | `paygym/schema.py` (pydantic). All 9 fields, plus `case`, `twin_of`, `trap_reason`, `seed`, `hand_check`. `uv run paygym schema` prints the JSON Schema | `test_json_schema_has_brief_minimum_fields` | ✅ |
| "At least 10 hand-checked tasks across three tiers" | `tasks/seed_v1.jsonl`: **16 tasks** (3 retrieval, 9 payslip, 4 trap), each with a hand calculation the validator re-checks | `test_seed_meets_brief_minimums`, `test_hand_check_mismatch_is_caught` | ✅ |
| "At least 3 Tier-3 traps … answers confidently must score zero or negative" | **4 traps**, covering all three brief categories (input absent, records contradictory, rules silent). Answering one = **−1** | `test_traps_cover_all_three_brief_categories`, `test_answering_a_trap_is_negative_never_partial` | ✅ |
| "machine-checkable ground_truth" | a discriminated union: value, payslip lines with tolerance and clauses, or refusal code + clause | `test_tampered_ground_truth_is_caught` | ✅ |
| "Validate the entire taskset with one command, and ideally in CI" | `uv run paygym validate tasks/` → 1,202 tasks OK; runs in GitHub Actions | `.github/workflows/ci.yml` | ✅ |
| Edge: answer leakage ("write a check … report what it caught") | `paygym audit`: literal-value search + a classifier that tries to predict the answer from the wording | eval: 0 leaks, classifier at chance (0.20). It caught two bugs **in itself** (EVAL_REPORT) | ✅ |
| Edge: near-duplicates | exact hash + similarity check | 0 / 0 on eval and train | ✅ |
| Edge: format ambiguity ("1,000.50 vs 1.000,50; monthly vs annual; 03/04") | the generator varies number format, annual salaries and DD/MM vs MM/DD; each task *states* its convention (GEN-§2.4–2.6) | the fidelity audit checked tasks with `dot_comma`, annual and MM/DD | ✅ |
| Edge: schema drift | unknown version or field → loud rejection; a registered migration upgrades old files | `test_unknown_schema_version_is_rejected_loudly`, `test_registered_migration_upgrades_old_version` | ✅ |

**The worked example's lesson, applied:** the brief says the productive tasks are where *"a cap binds"*. Our payslips have contribution ceilings that bind (and don't) by design, so the `naive_no_ceiling` baseline exists to catch "forgot the cap".

### Phase 02: Task generator

| Brief | Built | Check | Status |
|---|---|---|---|
| "seed → N instances, ground truth by an independent Python reference, **not by an LLM**" | `paygym/generator.py` → `paygym/reference/calculator.py`. No model is ever used for an answer | `test_generated_tasks_validate` | ✅ |
| "Deterministic … Record the seed in every result file" | one random stream per task seed; every task, `config.json`, `scores.json` and `metrics.json` carries seeds and rule-set version | `test_same_seed_same_taskset`, `test_seed_recorded_on_every_task` | ✅ |
| "Difficulty knobs … jurisdictions, mid-period salary change, proration, retro, currency mix, ceilings" | 13 knobs in `Knobs`: jurisdictions, years, ceiling binds, proration, salary change, retro, FX, allowances, split sources, irrelevant context, format variation, annual salary, tier mix; presets `default` / `easy` / `easier` | `test_knob_controls_currency_mix`, `test_knob_controls_jurisdictions` | ✅ |
| "At least 100 instances and … non-degenerate score distribution" | 1,202 generated tasks; on the eval set, models score 0–35 % of tasks at 1.0 and 14–83 % at ≤ 0 | EVAL_REPORT "Score distribution" | ✅ |
| "Unit tests on the reference implementation" | 18 hand-computed tests (one per rule area) + ~1,050 generated property cases | `tests/test_reference.py`, `tests/test_reference_properties.py` | ✅ |
| README: "the reference implementation is the verifier … state precisely where it breaks down" | README sections "The reference implementation is the verifier" and "Where it breaks down" (worker classification, ambiguous documents, statute drift, employee elections) | README | ✅ |

### Phase 03: Environment

| Brief | Built | Check | Status |
|---|---|---|---|
| "`load_environment(**kwargs) -> vf.Environment` … installable package with pyproject.toml" | `paygym/environment.py`, package `paygym`. verifiers **0.2.1** is pinned, the last version with the brief's API (removed in 0.3.0) | `test_discovered_by_verifiers`; `vf.load_environment("paygym")` works | ✅ |
| "Single-turn **and** tool-use" | `mode="single"` (SingleTurnEnv) and `mode="tool"` (a StatefulToolEnv subclass) | `test_single_turn_mode`, Step 12 runs on Groq and Gemini | ✅ |
| "2–4 real tools" | **4:** `get_employee_record`, `lookup_rules`, `get_fx_rate`, `calc` | the tool tests in `tests/test_parser_tools.py` (record, rules, FX, calc, bad arguments) | ✅ |
| "In tool mode, the tools must be the only source of the reference data" | the tool-mode prompt carries only the employee id and period, no rules or numbers | `test_tool_mode_prompt_carries_no_data_and_schema_hides_task_json` | ✅ |
| "Enforce max_turns and a per-rollout timeout" | `max_turns=8`, `timeout_seconds` | runs show `max_turns_reached` / `timeout_reached` stop reasons | ✅ |
| "A structured output contract … with a parser you own" | a JSON block `{decision, reason_code, lines \| value, explanation}`; `paygym/parser.py` | the parser tests in `tests/test_parser_tools.py` (malformed, truncated, trailing comma, bad decision, unfenced) | ✅ |
| "Runnable against any OpenAI-compatible endpoint. The model must be a CLI flag" | `--model`, `--base-url`, `--api-key-var` | used with Gemini, Groq and local vLLM | ✅ |
| Edge: malformed / truncated JSON | named parse errors, never a crash; scored −1 | `test_malformed_and_truncated_json_are_named_errors` | ✅ |
| Edge: invalid tool args / loops | structured errors; 3 identical calls end the rollout | `test_wrong_employee_id_is_a_structured_error`, `test_tool_loop_detection` | ✅ |
| Edge: "a tool raises or times out. Does the rollout fail loudly … or silently score 0?" | failures are recorded with a status; **a run with zero successes is never "completed"**; infrastructure timeouts are retried, not scored | `test_a_run_where_nothing_succeeded_is_never_completed`, `test_empty_timeout_is_an_infrastructure_error_and_is_retried` | ✅ |
| Edge: rate limits and 5xx, "retry with backoff and mark retried" | backoff retries, the `retried` count per rollout, per-request pacing, a daily free-quota ledger | `test_transient_errors_are_retried_and_marked` | ✅ |

### Phase 04: Reward and rubric (the most heavily weighted, 20 %)

| Brief | Built | Check | Status |
|---|---|---|---|
| "Pin and version the rule set … readable prose … separate from the code … version recorded in every result file … write it out in full before you implement it" | `ruleset/v1.0/RULESET.md` (prose, clause ids), written first; `rules.yaml` copy; fingerprint `42b009c25d689c46` in every result file | `test_yaml_tables_match_prose_tables`, `test_fingerprint_is_stable_and_versioned` | ✅ |
| "Every rule in code carries a citation to the specific clause" | `@cites("VAL-§2.1")` on every calculator step (15); every output line lists its clauses | `test_every_line_cites_clauses_that_exist`, `test_every_value_cites_an_existing_clause` | ✅ |
| "A programmatic verifier … tolerance justified by the rule set" | `net_pay_exact` with a tolerance of **one minor unit** (0.01; 1 in Nordmark), because GEN-§1.3/§1.4 round to that unit | `test_tolerance_is_one_minor_unit_from_the_rule_set` | ✅ |
| "Each reward function returns the clause(s) that drove the score" | every component returns `(score, clauses, detail)`; a failed payslip names its **first wrong line's clause** | `test_every_component_names_its_clauses`, `test_ignoring_the_ceiling_is_traced_to_the_ceiling_clause` | ✅ |
| "State what each score level means … Gate partial credit" | the score-level table in the rubric docstring; **wrong net pay is capped at 0.25** | `test_wrong_net_is_capped_at_floor_whatever_else_is_right` | ✅ |
| "At least one graded partial-credit reward" | `line_accuracy`: the share of the 10 payslip lines that are right | `test_net_right_but_lines_wrong_is_partial_not_full` | ✅ |
| "At least one LLM-judge reward … criteria derived from the rule set … prompt versioned … reliability measured (3 repeats or 15 hand labels)" | `paygym/judge.py`: 3 criteria quoting GEN-§9; pinned model (Gemini 3.1 Flash-Lite); prompt v1 with a hash; cached; only on correct trap refusals (0.2) | `test_criteria_are_grounded_in_the_rule_set`, `test_prompt_hash_is_stable_and_versioned` | ✅ 3-repeat disagreement **0/60** (20 explanations); the judge fails 5/60, so it isn't a rubber stamp. Hand-label agreement ⏳ |
| "A calibration reward … record why each trap is a trap … abstaining on a determinable task penalised exactly like a wrong answer" | `trap_reason` on every trap; **twins**; refusing a payable task = **−1**, the same as computing a trap | `test_refusing_a_determinable_payslip_scores_like_a_wrong_answer` | ✅ |
| "Rule-set fidelity audit: hand-check ≥ 10 generated tasks … report the divergence rate" | `docs/FIDELITY_AUDIT.md`: 10 tasks derived from the prose before looking at the reference: **0 / 50 divergences** | the doc | ✅ (your spot-check pending) |
| "Document your weights and defend them" | weights 0.70 / 0.25 / 0.05 with the reasoning in the README; ranking unchanged under 4 weightings (**τ = 1.0**) | `results/weight_sensitivity.json` | ✅ |
| §10: "Did you attack your own reward function and fix what you found?" | **5 adversarial baselines** (all under their floors) **and three exploits found by the RL policy itself, each fixed** (Part 3) | `test_baseline_stays_under_its_floor`; RL_REPORT B6 | ✅ |

### Phase 05: Eval harness

| Brief | Built | Check | Status |
|---|---|---|---|
| "One command runs an evaluation" | `uv run python -m paygym.eval --model … --tier all --rollouts 3 --seed 7 --max-cost 2.00` | used for every run | ✅ |
| "At least three model configurations, including one frontier and one small/cheap" | Gemini 3.5 Flash-Lite and 3.8 Flash (frontier lab), gpt-oss-120b (large open), Qwen-3B, Qwen-0.5B base and trained (small), + 5 baselines | `results/leaderboard.json` | 🟡 3.8 Flash (core6, +0.885) and gpt-oss (core10, +0.665) are on small subsets (free limits), compared paired |
| "At least 3 rollouts per task at non-zero temperature, mean ± SD" | 3 rollouts at temperature 1.0; mean ± run SD on every row | leaderboard | ✅ |
| "Persist per run: config.json, transcript.jsonl, metrics.json, scores.json" | all four, every run | `test_baseline_run_writes_the_four_files` | ✅ |
| "A hard --max-cost cap that aborts cleanly with partial results" | list-price cap → `aborted_cost` with partial files | `test_cost_cap_aborts_cleanly_with_partial_results` | ✅ |
| "Bounded-concurrency worker pool. Report what you actually spent" | `--concurrency`; metrics give list price vs actual ($0) | EVAL_REPORT spend | ✅ |
| Edge: "crashes at task 60 of 100 … pay twice?" | resume skips finished rollouts | `test_resume_does_not_pay_twice`; live "327 already done" | ✅ |
| Edge: "one provider is down" | marked `unavailable`; the sweep continues | `test_provider_down_is_marked_unavailable` | ✅ |
| Edge: "non-determinism … report honestly" | run SD, rollout disagreement, and a list of **indistinguishable pairs** | EVAL_REPORT | ✅ |

### Phase 06: Dashboard

| Brief | Built | Status |
|---|---|---|
| "A live URL" | **https://aigym-alpha.vercel.app** (static, Vercel) | ✅ live |
| "Leaderboard with error bars / ± SD" | leaderboard section, full 109-task eval | ✅ |
| "Breakdown by tier and by reward function" | breakdown section | ✅ |
| "Failure heatmap: task × model" | 9 models × 109 tasks, click a cell → transcript | ✅ |
| "Transcript viewer" | transcript viewer (tool calls, answer, gate, clauses) | ✅ |
| "Adversarial baselines on the same leaderboard" | the 5 baselines, greyed, on the same board | ✅ |
| "Cost and latency per model" | cost and latency section (baselines show "—": no model call) | ✅ |
| "Which model, for which tasks, where will it hurt us?" | verdict panel: best per tier, cost per correct payslip, top failure clauses | ✅ |
| Phase 07: "All five [RL curves] on the dashboard" | RL section: reward, KL, entropy, length, per-tier pass rate + validation curve + held-out tables | ✅ |

### Phase 07: RL training loop

| Brief | Built | Result | Status |
|---|---|---|---|
| "Algorithm: your choice … justify" | GRPO with the Dr. GRPO loss, no std scaling (README + RL_REPORT A1–A2b explain why over PPO/DPO/RLOO) | – | ✅ |
| "Open-weight 0.5–2B … LoRA" | Qwen2.5-0.5B-Instruct + LoRA r16, local RTX 5070 Ti | – | ✅ |
| "Reward must come from your own Phase 04 rubric" | `paygym/training_reward.py` wraps `score_answer` | `test_training_reward_matches_rubric_and_logs_monitors` | ✅ |
| "Frozen reference with explicit KL … report β, estimator, log KL every step" | reference = base with the adapter off; β 0.04 and 0.001; k3; `kl` in every row of `metrics.csv` | KL 0.02 (β 0.04) vs 0.15 (β 0.001) | ✅ |
| "At least 4 completions per prompt … report fraction of identical groups" | G = 8; `frac_reward_zero_std` logged | 0.68 (β 0.04) / 0.74; B7 explains and proposes fixes | ✅ |
| "A held-out split … before-and-after on tasks never trained on … seeds must not overlap" | train seeds 0–10k; val 500k+; held-out 1M+; content overlap checked = 0 | **+0.338 [+0.232, +0.442]** (training difficulty), **+0.304 [+0.201, +0.411]** (full difficulty) | ✅ |
| "Log and plot: reward, KL, entropy, completion length, per-tier pass rate" | all in `metrics.csv`, on the dashboard | – | ✅ |
| "Sweep β across at least two values, one deliberately too low … where you would set β" | 0.001 vs 0.04 | 0.001 drifted 7× and learned an exploit; 0.04 improved honestly → set 0.04+ | ✅ |
| "At least one instance of the policy gaming your reward, with transcripts and what you changed" | **three** learned exploits, each with evidence and a rubric fix | RL_REPORT B6 | ✅ |
| Edges: entropy collapse, KL blow-up, length hacking, format collapse, degenerate groups, split leakage, checkpointing | monitors + relative safety stops; checkpoints every 10 steps; resume | entropy collapse seen (v1.1), format collapse seen (v1.2), no length hacking | ✅ |

### Phase 08: Agent sandbox

| Brief | Built (verified live) | Status |
|---|---|---|
| "A live sandbox URL that stays up without your laptop" | https://aigym-alpha.vercel.app (Vercel serverless + Upstash Redis) | ✅ |
| "Fetch a batch of tasks, and submit answers. Ground truth never crosses the wire" | `GET /tasks`, `POST /submit`, `GET /runs/<id>`; seeds are HMAC'd with a secret, ids are opaque | ✅ (fuzz test + live check) |
| "Answer-submission mode" | yes; driving the caller's model is optional and was not built (it would mean handling others' keys) | ✅ |
| "Scoring must reuse the Phase 04 rubric … no second scoring path" | the same `score_answer`; the parity test asserts sandbox = rubric = environment | ✅ |
| "Per-task score, per-function breakdown, and the clause" | `per_task[{score, breakdown, clause, gate}]` | ✅ live |
| "run_id … rule-set version, taskset seed, tier mix" | signed `run_id`; responses echo `ruleset_version`, `seed`, `tier_mix` | ✅ live |
| "A quickstart … two minutes, one copy-pasteable command" | `curl -s https://aigym-alpha.vercel.app/quickstart.py \| python3 - https://aigym-alpha.vercel.app` | ✅ live, no clone needed |
| "Guardrails: task cap, rate limit, no storage of keys; abuse/cost paragraph" | ≤ 50 tasks (400 above); 30 requests/min per caller (429, shared through Redis); no keys accepted; paragraph in the README | ✅ live |
| Optional: "sandbox runs on the same leaderboard, labelled external" | `/api/leaderboard` → `"external": true` → dashboard section | ✅ live |
| Edges: leakage test, 10,000 tasks / tight loop, concurrent writes, version skew, cold start | fuzz test; cap + rate limit; atomic writes + idempotent resubmit; 409 on version mismatch; cold-start note + health polling | ✅ |

### §7: Advanced track (we chose **C**, scaffold comparison)

- **Brief:** "Hold the model constant and vary the agent scaffold … show whether scaffold matters more than model choice."
- **Built:** Qwen-3B fixed at 5 scaffolds S0–S4, plus Qwen-0.5B at S0 and S4, all on 109 tasks × 3 rollouts (`docs/TRACK_C.md`).
- **Finding:**
  - for the 3B the scaffold is worth **+0.21**, and the cheapest step (rules in the prompt) gives +0.14 at a fifth of the tokens tool mode uses;
  - tools alone were *worse*;
  - the model effect **changes sign** with the scaffold;
  - a frontier model is **+0.80** above the 3B.
- **Status:** ✅

---

## Part 3. The results, and what they mean

**1. Arithmetic separates the models** (EVAL_REPORT).
- Gemini 3.5 Flash-Lite, the best full-coverage model (+0.314), gets net pay **exactly right on 6 of 210** payslips.
- A script that ignores the contribution ceilings gets **111**.
- The two are **statistically indistinguishable**. Gemini wins on decisions (traps +0.52 vs −1.0, retrieval 1.0) and loses on arithmetic.
- **But capability matters:** on the same 4 core6 payslip tasks, **Gemini 3.8 Flash gets 11 of 12 exact**, Flash-Lite 0 of 12. On core10, gpt-oss-120b gets 10 of 18 (the script 12 of 18). That is 4 tasks only, because the free tier allows 20 requests a day.
- **Takeaway:** a cheap model decides and a calculator computes. A strong reasoning model is the candidate for end-to-end computation, after a full eval.

**2. RL on a 0.5B model learned a real, transferable skill and lost one** (RL_REPORT B5).
- On held-out tasks it never trained on, scored once: +0.34 at the training difficulty and +0.30 at full difficulty. Both 95 % intervals exclude zero.
- It learned to write valid payslips (broken output 8 → 0 of 36 on validation) and to stop refusing payable work.
- It now answers every trap, while writing the correct refusal reason in the same answer.

**3. The reward was attacked by the optimiser, and survived only after three fixes** (RL_REPORT B6). This is the brief's "single highest-signal thing".

| Rubric | What the policy learned to do | Why it paid | Fix |
|---|---|---|---|
| 1.1 | refuse all 47 validation tasks; the validation reward **rose** | refusing cost 0, answering a trap −1 | 1.2: refusing a payable task = −1 |
| 1.2 | write broken JSON for all 47 | unparseable cost 0 | 1.3: unparseable = −1 |
| 1.3 | write `"decision": "reject"` (found at β 0.001 only) | read as a refusal on traps, a harmless answer on payslips | 1.4: no valid decision = unparseable |

Each fix was checked offline on the policy's real outputs before retraining. The 5 hand-written baselines found none of the three.

**4. The scaffold matters for small models, but less than the model** (TRACK_C).

**5. What the gym caught in models** (FAILURE_ANALYSIS, 11 transcripts, counted across all rollouts):
- a skipped personal allowance (tax off by exactly +200);
- the 2026 FX rate used for a 2025 payslip;
- Gemini refusing payable payslips over a **job title**, which the rules say is not an input (9 of its 22 wrong refusals; the twins caught it);
- the 3B misreading the FX rule as a limitation (116 refusals);
- tool loops.

---

## Part 4. Brief §10, criterion by criterion: what we would say

| Criterion (weight) | Our evidence | Honest weak spot |
|---|---|---|
| Reward & rule-set design (20 %) | prose rule book first, clause citations, fidelity 0/50, gates, partial credit, the judge, **3 exploits found and fixed** | judge consistency only shown at temperature 0; hand-label agreement ⏳ |
| RL loop & analysis (18 %) | frozen reference + KL every step, defended method, held-out +0.30 with CI, 5 curves, the β sweep showing the trade-off, gaming caught | one seed per β; no β above 0.04; trap refusal not learned |
| Task & dataset design (15 %) | real work (payslips), verifiable truth, 3 tiers separate models, traps + twins, 13 knobs, 1,202 tasks | the base 0.5B needed the `easy` preset to get any signal |
| Eval rigor & failure analysis (12 %) | 3 rollouts, SDs, indistinguishable pairs stated, 11 transcripts with counts, non-obvious findings (job title, decision decoupling) | two hosted models on small subsets |
| Agent sandbox (11 %) | works first time for an outside caller (tested live), same rubric (parity test), clause per score, leak fuzz test | – |
| Environment & engineering (10 %) | verifiers spec, one environment for eval/trainer/sandbox, seeds and config recorded, retries/resume/checkpoints/cost/quota handled, CI | clean-clone test ⏳ |
| Communication & docs (7 %) | README, 9 reports, PROGRESS log, this walkthrough; the Loom script explains reasoning | Loom ⏳ |
| Advanced track (4 %) | Track C, with the non-obvious "model effect flips sign" finding | one fixed model |
| Speed (3 %) | started 2026-10-17 | likely past 72 h: the 5-business-day band (1 %) |

**Anti-goals (§10):** each one is avoided.

| Anti-goal | Why we avoid it |
|---|---|
| "everything scores 100 %" | the distribution spans −1 … 1; no full-eval model above +0.32; the best subset score is Gemini 3.8 Flash +0.885 on 6 tasks, with one −1 |
| "ground truth from the model" | the reference calculator only |
| "one rollout" | 3 per task |
| "four slices × 3 tasks" | one slice, 1,202 tasks |
| "rising curve, no held-out" | held-out at two difficulties, scored once |
| "no reference / KL" | frozen reference, KL logged every step |
| "no transcripts" | transcript viewer + failure analysis |
| "too-large model that didn't finish" | 0.5B, finished |
| "sandbox leaks answers" | fuzz test + live check |
| "sandbox scores differently" | parity test, one scorer |

**Rules (§11):**

| Rule | How we meet it |
|---|---|
| solo | yes |
| AI disclosed | `docs/AI_USAGE.md`, incl. where the AI was wrong |
| synthetic data only | fictional rules and employees |
| no paid infrastructure | $0 |
| mocking documented | TRADEOFFS "What we mocked" |
| "scope down loudly" | TRADEOFFS #9–#11, STATUS "open limitations", the cut list and "two more days" |

---

## Part 5. Verify it yourself in ten commands

```bash
cd ~/Documents/PROJECT/niural-task
uv run pytest -q                                   # 1. the whole suite (234 tests) passes
uv run paygym validate tasks/                      # 2. every task re-checked against the reference → OK
uv run paygym audit tasks/generated/eval.jsonl --out /tmp/a.json   # 3. leakage audit: 0 leaks
uv run paygym leaderboard                          # 4. leaderboard rebuilt from results/
uv run python -m paygym.eval.sensitivity           # 5. τ = 1.0 under all weightings
uv run python -m paygym.eval --model baseline/naive_no_ceiling --rollouts 3 --out /tmp/paygym-check --run-name check   # 6. an eval end to end ($0), written outside results/
cat results/train/rl_summary_heldout.json          # 7. the held-out before/after with its CI
cat results/train/grpo-b0.04/validation.csv        # 8. the validation curve the policy was selected on
curl -s https://aigym-alpha.vercel.app/health      # 9. the live API: rubric 1.4, RedisStore
curl -s https://aigym-alpha.vercel.app/quickstart.py | python3 - https://aigym-alpha.vercel.app   # 10. live round trip
```

## Part 6. Still to do (today)

1. ✅ Hosted top-up and the judge 3-repeat run (done 2026-10-20); ⏳ hand-label agreement.
2. ⏳ Your reviews: 2 fidelity hand-derivations, the failure categories, 3–5 Environments Hub notes.
3. ⏳ Clean-clone test, the Loom (`docs/LOOM_SCRIPT.md`), the submission email.
