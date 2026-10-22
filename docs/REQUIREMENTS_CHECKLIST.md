# Requirements checklist

Every requirement in the brief (`AI Product Operator - Niural AI Labs .docx.pdf`), with its page, the build step that closes it, a status, and evidence.
Status: ☐ not started · ◐ partly met · ☑ met (with evidence). Every row must be ☑, or recorded as scoped down in `docs/TRADEOFFS.md`, before submission.

## Phase 01: Task schema and seed taskset (p.7)

| ID | Requirement | Step | Status | Evidence |
|---|---|---|---|---|
| P01.1 | Task schema (JSON/YAML), validated programmatically; fields `id, slice, difficulty, prompt, context_files, ground_truth, verifier, tags, schema_version` | 5 | ☑ | `paygym/schema.py`; `paygym schema`; `tests/test_tasks.py::test_json_schema_has_brief_minimum_fields` — validated on user machine 2026-10-19 |
| P01.2 | ≥10 hand-checked tasks across 3 tiers (Retrieval / Computation / Trap) | 5 | ☑ | `tasks/seed_v1.jsonl` (16 hand-written, `hand_check` enforced by `paygym validate`) — validated on user machine 2026-10-19 |
| P01.3 | ≥3 Tier-3 traps; confident answers score zero or negative, never partial credit | 5, 10 | ☑ (tests pass) | 4 traps + twins; answered trap = −1.0 (`paygym/rubric.py`, `test_answering_a_trap_is_negative_never_partial`) |
| P01.4 | Machine-checkable `ground_truth` (number + tolerance, label, set, JSON, criteria list); no prose-only GT for Tiers 1–2 | 5 | ☑ | value / payslip / refusal GT kinds (`paygym/schema.py`) — validated on user machine 2026-10-19 |
| P01.5 | Validate the whole taskset with one command, ideally in CI | 5, 7 | ☑ (CI green 2026-10-19) | `paygym validate tasks/` + `.github/workflows/ci.yml`; run https://github.com/dibya0/AIGYM/actions/runs/39207551122 |
| P01.E1 | Edge: answer leakage, with a check and a report of what it caught | 6 | ☑ (run 2026-10-19) | `paygym/audit/leakage.py` (literal + balanced classifier); `results/audit/*.json`: 0 literal leaks, eval classifier at chance; caught + fixed an audit false positive (PROGRESS Step 6) |
| P01.E2 | Edge: near-duplicates that inflate sample size | 6 | ☑ (run 2026-10-19) | `paygym/audit/dedup.py`; 0 exact / 0 near dups on eval and train (twins excluded by design, mean Jaccard 0.81) |
| P01.E3 | Edge: unit/scale/format ambiguity (`1,000.50` vs `1.000,50`; monthly vs annual; `03/04`) | 6 | ☑ (run 2026-10-19) | generator format knobs (`Knobs.p_format_variation`, `p_annual_salary`); conventions stated per GEN-§2.4–2.6 |
| P01.E4 | Edge: schema drift (v1 results when v2 adds a field) | 5 | ☑ (tests pass) | `extra="forbid"` + `load_task` migrations; drift tests in `tests/test_tasks.py` |

## Phase 02: Task generator (p.8)

| ID | Requirement | Step | Status | Evidence |
|---|---|---|---|---|
| P02.1 | Seed → N instances; GT computed by an independent Python reference implementation, never an LLM | 4, 6 | ☑ (tests pass) | `paygym/generator.py`; GT via `paygym/truth.py` → reference only |
| P02.2 | Deterministic and reproducible; seed recorded in every result file | 6, 14 | ☑ (tests pass) | PCG64 per task seed; task seeds + taskset hash in every `config.json` |
| P02.3 | Difficulty knobs as parameters (interacting rules, irrelevant input, lookups, absent values; payroll: jurisdictions, mid-period change, proration, retro, currency mix, ceilings) | 6 | ☑ (tests pass) | `Knobs` in `paygym/generator.py`; `test_knob_controls_*` |
| P02.4 | ≥100 instances; non-degenerate score distribution | 6, 15 | ☑ | 529 instances generated (eval 109, held-out 109/124, train, val); score distribution spans −1…+1 for every model, 0–35 % of tasks at 1.0, 14–83 % at ≤ 0 (EVAL_REPORT 'Score distribution'; dashboard distribution chart) |
| P02.5 | Unit tests on the reference implementation | 4 | ☑ | `tests/test_reference.py` (hand-computed) + `tests/test_reference_properties.py` (Hypothesis, 1,050 cases); one manual mutation check during development: deleting the ceiling failed 5 tests (PROGRESS Step 4); no automated mutation testing |
| P02.6 | README states where the "reference = verifier" approach breaks down in the domain | 22 | ☑ | README §'Where the reference is the verifier breaks down' |

## Phase 03: Environment (p.8–9)

| ID | Requirement | Step | Status | Evidence |
|---|---|---|---|---|
| P03.1 | `load_environment(**kwargs) -> vf.Environment` from an installable package with `pyproject.toml` | 1, 12 | ☑ (tests pass) | `paygym/environment.py::load_environment`; `paygym.load_environment` discovered by `vf.load_environment('paygym')` |
| P03.2 | Single-turn mode (`SingleTurnEnv`) | 12 | ☑ (tests pass) | `mode='single'` → `vf.SingleTurnEnv` |
| P03.3 | Tool-use mode (`ToolEnv`) with 2–4 real tools | 9, 12 | ☑ (tests pass) | `mode='tool'` → `PaygymToolEnv(StatefulToolEnv)` with 4 tools |
| P03.4 | In tool mode, tools are the only source of reference data | 9, 12 | ☑ (tests pass) | tools read only the rollout's task; tool-mode prompt carries just the employee id (`paygym/prompting.py::tool_turn_messages`) |
| P03.5 | Enforce `max_turns` and a per-rollout timeout | 12 | ☑ (tests pass) | `max_turns=8`, `timeout_seconds=120` (verifiers `asyncio.wait_for`) |
| P03.6 | Structured output contract with our own parser | 9 | ☑ (tests pass) | `paygym/prompting.py` contract + `paygym/parser.py` |
| P03.7 | Runs against any OpenAI-compatible endpoint; model is a CLI flag | 12, 14 | ☑ | `--model` prefix routing (`gemini/`, `groq/`, `local/` vLLM, `baseline/`) or any endpoint via `--base-url`/`--api-key-var`; real runs on Gemini, Groq and local vLLM (`results/`) |
| P03.E1 | Edge: malformed or truncated JSON | 9 | ☑ (tests pass) | named parser errors; `tests/test_parser_tools.py` |
| P03.E2 | Edge: invalid tool arguments; looping tool calls | 9 | ☑ (tests pass) | structured tool errors + `tool_errors` metric + `tool_loop_detected` stop |
| P03.E3 | Edge: tool raises or times out, recorded loudly, never a silent 0 | 9 | ☑ (tests pass) | tool exceptions become error tool messages (StatefulToolEnv) counted by `tool_errors`; judge failure raises |
| P03.E4 | Edge: rate limits / 5xx, retried with backoff, retried rollouts marked | 14 | ☑ (tests pass) | retries on 429/5xx/timeout, `retried` marked; `test_transient_errors_are_retried_and_marked` |

## Phase 04: Reward and rubric layer (p.9–10)

| ID | Requirement | Step | Status | Evidence |
|---|---|---|---|---|
| P04.1 | Rule set pinned and versioned as its own artifact, separate from code; version in every result file; written as prose before implementation | 2, 3, 14 | ☑ | `ruleset/v1.0/RULESET.md` (prose, written first) + `rules.yaml`; prose-vs-YAML test; `ruleset_version` + fingerprint `42b009c25d689c46` in every `config.json`/`scores.json`/`metrics.json` |
| P04.2 | Reference implementation faithful to the rule set; every rule in code cites its clause | 4, 13 | ☑ (tests pass) | `@cites` on every step; test asserts every cited clause exists in RULESET.md; fidelity audit in Step 13 |
| P04.3 | ≥1 programmatic verifier with zero LLM involvement; tolerance justified by the rule set | 10 | ☑ (tests pass) | `net_pay_exact`, tolerance = one minor unit per GEN-§1.4 (`test_tolerance_is_one_minor_unit_from_the_rule_set`) |
| P04.4 | Each reward function returns the clause(s) that drove the score | 10 | ☑ (tests pass) | `RewardResult.clauses` + `Score.driving_clauses`; first wrong line → its clauses |
| P04.5 | Each score level defined in terms of the rule set; partial credit gated | 10 | ☑ (tests pass) | score-level table in `paygym/rubric.py` docstring; cap tests |
| P04.6 | ≥1 graded partial-credit reward | 10 | ☑ (tests pass) | `line_accuracy` (10 lines) |
| P04.7 | ≥1 LLM-judge reward; criteria from the rule set; prompt versioned; reliability measured (3-run disagreement and/or 15 hand labels) | 11 | ☑ | `paygym/judge.py` (3 GEN-§9 pass/fail criteria, pinned model, prompt hash `d0691c1328f8ba86`); **3-repeat disagreement 0/60** on 20 real explanations (`results/judge/reliability_repeat.json`); hand-label agreement scoped down (TRADEOFFS), sheet prepared |
| P04.8 | Calibration reward; reason recorded for every trap; abstaining on determined tasks penalised like a wrong answer | 5, 10 | ☑ (tests pass) | trap ladder (−1 / 0.3 / 0.8 / +0.2 judge); refusal on a determinable case = wrong-answer path |
| P04.9 | Rule-set fidelity audit: ≥10 generated tasks hand-checked; divergence rate reported | 13 | ☑ (user review pending) | `docs/FIDELITY_AUDIT.md`: 10 tasks, 0/50 divergences, coverage gaps and limits stated |
| P04.10 | Weights documented and defended | 10, 22 | ☑ | weights 0.70/0.25/0.05 + rationale in `paygym/rubric.py` docstring and README; ranking unchanged under 4 alternative weightings, Kendall τ = 1.0 (`results/weight_sensitivity.json`) |
| P04.11 | Adversarial / hand-written baselines probe the reward (p.12, p.11) | 10 | ☑ (tests pass) | 5 baselines with floors (`paygym/baselines.py`, `tests/test_rubric.py`) |

## Phase 05: Eval harness and runner (p.10)

| ID | Requirement | Step | Status | Evidence |
|---|---|---|---|---|
| P05.1 | One command runs an evaluation | 14 | ☑ (real runs 2026-10-19: Groq + Gemini) | `python -m paygym.eval --model … --tier all --rollouts 3 --seed 7 --max-cost 2.00` |
| P05.2 | ≥3 model configs incl. one frontier and one small/cheap | 15 | ☑ | Gemini 3.5 Flash-Lite + 3.8 Flash (frontier lab), gpt-oss-120b (large open), Qwen2.5-3B, Qwen2.5-0.5B base + GRPO (small), Gemini 3.1 Flash-Lite tool mode, 5 baselines (`results/leaderboard.json`) |
| P05.3 | ≥3 rollouts per task at non-zero temperature; mean ± SD | 14, 15 | ☑ | every run 3 rollouts at temperature 1.0; mean ± run SD, rollout SD and disagreement rate per run (`scores.json`, EVAL_REPORT) |
| P05.4 | Per run: `config.json`, `transcript.jsonl`, `metrics.json` (tokens, latency, cost, tool calls), `scores.json` | 14 | ☑ (real runs 2026-10-19; transcript JSON fix) | `paygym/eval/runner.py` writes config/transcript/metrics/scores; `test_baseline_run_writes_the_four_files` |
| P05.5 | Hard `--max-cost` cap that aborts cleanly with partial results | 14 | ☑ (tests pass) | `--max-cost` (list price) → `aborted_cost`; `test_cost_cap_aborts_cleanly_with_partial_results` |
| P05.6 | Bounded-concurrency worker pool; actual spend reported | 14 | ☑ (tests pass) | semaphore `--concurrency` + rate limiter; `metrics.json` list vs actual cost |
| P05.E1 | Edge: crash mid-run is resumable without paying twice | 14 | ☑ (real run: '327 already done, 0 to run') | resume from transcript; `test_resume_does_not_pay_twice` |
| P05.E2 | Edge: one provider down while others work | 14 | ☑ (tests pass) | `--max-consecutive-errors` → `unavailable`; other providers are separate runs; `test_provider_down_is_marked_unavailable` |
| P05.E3 | Edge: non-determinism reported honestly, not hidden in a mean | 14 | ☑ (tests pass) | per-task rollout disagreement rate + paired bootstrap 'indistinguishable' list |

## Phase 06: Results dashboard (p.11)

| ID | Requirement | Step | Status | Evidence |
|---|---|---|---|---|
| P06.1 | Live URL, readable in 90 seconds without cloning | 16 | ☑ (live 2026-10-19: https://aigym-alpha.vercel.app) | `paygym/dashboard/`: static `public/` (Vercel); live URL after deploy |
| P06.2 | Leaderboard: model × mean reward with error bars / ± SD | 16 | ☑ (live 2026-10-19: https://aigym-alpha.vercel.app) | `paygym/dashboard/`: leaderboard bar + error bars (run SD) + table |
| P06.3 | Breakdown by difficulty tier and by reward function | 16 | ☑ (live 2026-10-19: https://aigym-alpha.vercel.app) | `paygym/dashboard/`: tier + reward-function charts |
| P06.4 | Failure heatmap, task × model | 16 | ☑ (live 2026-10-19: https://aigym-alpha.vercel.app) | `paygym/dashboard/`: task × model heatmap (click → transcript) |
| P06.5 | Transcript viewer | 16 | ☑ (live 2026-10-19: https://aigym-alpha.vercel.app) | `paygym/dashboard/`: transcript viewer (tool calls, results, gate, clauses) |
| P06.6 | Adversarial baselines on the same leaderboard | 16 | ☑ (live 2026-10-19: https://aigym-alpha.vercel.app) | `paygym/dashboard/`: baselines on the same leaderboard (grey) |
| P06.7 | Cost and latency per model | 16 | ☑ (live 2026-10-19: https://aigym-alpha.vercel.app) | `paygym/dashboard/`: cost & latency table |
| P06.8 | Answers: which model, for which tasks, where will it hurt us | 16, 21 | ☑ (live 2026-10-19: https://aigym-alpha.vercel.app) | `paygym/dashboard/`: verdict panel (best per tier, cost/correct payslip, top failure clauses, trap/twin rates) |

## Phase 07: RL training loop (p.11–13)

| ID | Requirement | Step | Status | Evidence |
|---|---|---|---|---|
| P07.1 | Policy-gradient method chosen and defended; objective written in README | 17, 22 | ☑ | GRPO (TRL 1.14.1), Dr. GRPO loss, no std scaling, k3 KL; objective + justification in README and `docs/RL_REPORT.md` A1 |
| P07.2 | Open-weight model trainable on available compute (0.5–2B suggested) | 8, 17 | ☑ | Qwen2.5-0.5B-Instruct + LoRA r16 on the local RTX 5070 Ti; difficulty pilot + `easy` preset (RL_REPORT A10–A13) |
| P07.3 | Reward from our own Phase 04 rubric | 17 | ☑ | `paygym/training_reward.py::rubric_reward` calls `paygym.rubric.score_answer` (judge weight 0) |
| P07.4 | Frozen reference model with explicit KL penalty; β, estimator reported; KL logged every step | 8, 17 | ☑ | β ∈ {0.001, 0.04} > 0 enforced; reference = base with the LoRA adapter disabled; TRL k3 KL logged every step (`results/train/*/metrics.csv`) |
| P07.5 | Held-out split; disjoint generator seeds; before/after on never-trained tasks | 6, 18 | ☑ | disjoint seed ranges + content-disjointness test; held-out before/after scored once: heldout_easy **+0.338 [+0.232, +0.442]**, heldout **+0.304 [+0.201, +0.411]** (RL_REPORT B5) |
| P07.6 | ≥4 completions per prompt; fraction of all-identical groups reported | 17 | ☑ | G = 8; `frac_reward_zero_std` logged every step (`metrics.csv`, RL_REPORT B7) |
| P07.7 | Log and plot reward, KL, entropy, completion length, per-tier pass rate, all on the dashboard | 17, 21 | ☑ | `metrics.csv` (reward, KL, entropy, completion length, per-tier pass rate + monitors) → dashboard RL section (live) |
| P07.8 | KL sweep ≥2 values, one deliberately too low; β recommendation | 17, 18 | ☑ | β = 0.001 (too low: KL ~0.15, learned the 'reject' exploit) vs 0.04 (KL ~0.02, honest gain); recommendation β ≥ 0.04 (RL_REPORT B3) |
| P07.9 | ≥1 documented instance of reward gaming with transcripts and the fix, or documentation of what was searched | 18 | ☑ | **three** learned exploits with transcripts and fixes: refuse-everything (rubric 1.2), broken JSON (1.3), invalid decision word (1.4), each verified offline on the real outputs (RL_REPORT B6; `results/train/*/val_samples.jsonl`) |
| P07.E1 | Edges: entropy collapse, KL blow-up, length hacking, format collapse, degenerate groups, split leakage, checkpointing | 6, 17 | ☑ | monitors + relative safety stops (`ValidationAndSafety`), split-disjoint test, checkpoints + `--resume`; the step-14 attention OOM fixed with an exact chunked fallback (RL_REPORT, PROGRESS) |

## Phase 08: Agent sandbox (p.13–14)

| ID | Requirement | Step | Status | Evidence |
|---|---|---|---|---|
| P08.1 | Live URL that stays up without the laptop (free tier OK) | 19 | ☑ (live 2026-10-19: https://aigym-alpha.vercel.app) | Vercel (`api/index.py`, `vercel.json`); live URL after deploy |
| P08.2 | Agent-facing API: fetch a batch of tasks; submit answers for scoring | 19 | ☑ (tests pass; verified live 2026-10-19) | `GET /api/tasks`, `POST /api/submit` |
| P08.3 | Ground truth never crosses the wire | 19 | ☑ (tests pass; verified live 2026-10-19) | HMAC-derived seeds, opaque ids; leak fuzz test |
| P08.4 | Scoring reuses the Phase 04 rubric and pinned rule set (no second scoring path) | 19 | ☑ (tests pass; verified live 2026-10-19) | `score_answer` + parity test (API == rubric == env) |
| P08.5 | Response: per-task score, per-reward-function breakdown, driving clause | 19 | ☑ (tests pass; verified live 2026-10-19) | `per_task[].score/breakdown/clause` |
| P08.6 | `run_id` recording rule-set version, taskset seed, tier mix | 19 | ☑ (tests pass; verified live 2026-10-19) | signed `run_id` (seed, tiers, n, ruleset version); response echoes seed/tier_mix/ruleset_version |
| P08.7 | README quickstart completable in two minutes (fetch, submit trivial answer, print score) | 19 | ☑ (live 2026-10-19: https://aigym-alpha.vercel.app) | `scripts/quickstart.py` (stdlib only) |
| P08.8 | Guardrails: task cap per run, per-caller rate limit, no storage of others' API keys; abuse/cost paragraph | 19 | ☑ (live 2026-10-19: https://aigym-alpha.vercel.app) | n ≤ 50, per-caller rate limits, no key storage; abuse paragraph in README (Step 22) |
| P08.9 | Optional: sandbox runs on the leaderboard, labelled external | 19, 21 | ☑ (live 2026-10-19: external submissions listed by /api/leaderboard, external: true; shown on the dashboard) | `/api/leaderboard` → dashboard external section |
| P08.E1 | Edge: GT leakage test (no expected value in any response), with what it caught | 19 | ☑ (tests pass; verified live 2026-10-19) | `test_no_ground_truth_in_any_response` |
| P08.E2 | Edge: caller asks for 10,000 tasks / submits in a tight loop | 19 | ☑ (tests pass; verified live 2026-10-19) | cap + rate limit tests |
| P08.E3 | Edge: two runs writing to the same store at once | 19 | ☑ (tests pass; verified live 2026-10-19) | atomic set-if-absent per run_id; idempotent resubmission |
| P08.E4 | Edge: version skew, never silently compared across rule-set versions | 19 | ☑ (tests pass; verified live 2026-10-19) | 409 on rule-set mismatch (test) |
| P08.E5 | Edge: cold start documented in README | 19 | ☑ | README 'Cold start' note; quickstart polls `/api/health` first |

## §7 Advanced track C: scaffold comparison (p.15)

| ID | Requirement | Step | Status | Evidence |
|---|---|---|---|---|
| ADV.1 | Model held constant; vary prompt structure, tool availability, self-check step | 20 | ☑ | `SCAFFOLDS` S0–S4 in the same environment; Qwen-3B and 0.5B through all five (`results/local__qwen2.5-*/trackc-*`) |
| ADV.2 | Show whether scaffold matters more than model choice | 20 | ☑ | `docs/TRACK_C.md`: scaffold worth +0.21 for the 3B; the model effect changes sign with the scaffold |

## §8 Compute and budget (p.15–16)

| ID | Requirement | Step | Status | Evidence |
|---|---|---|---|---|
| CMP.1 | Report models chosen and roughly what was spent | 15, 22 | ☑ | EVAL_REPORT 'Compute spend': $0.00 actual, ≈ $0.86 list-price equivalent, local GPU ~6–9 h; models listed in EVAL_REPORT 'Setup' |

## §9 Deliverables (p.16)

| # | Deliverable | Step | Status | Evidence |
|---|---|---|---|---|
| D1 | GitHub repo; runs from a clean clone (`uv sync` / `pip install -e .`, `.env.example`) | 1, 23 | ◐ (clean-clone test ⏳) | `uv sync` + 237 tests pass; `.env.example`; CI green; fresh-clone run still to do |
| D2 | Deployed dashboard (live URL, real results) | 16, 21 | ☑ | https://aigym-alpha.vercel.app (all Phase 06 sections, RL curves, Track C) |
| D3 | Live agent sandbox + two-minute quickstart | 19 | ☑ | https://aigym-alpha.vercel.app/docs; `curl -s https://aigym-alpha.vercel.app/quickstart.py | python3 - https://aigym-alpha.vercel.app` verified live 2026-10-19 |
| D4 | Loom, 8–12 min: ≥3 min reward design, ≥1 min reading a failure transcript, live sandbox request | 24 | ◐ (recording pending) | `docs/LOOM_SCRIPT.md` |
| D5 | README / architecture doc: stack, architecture, task schema, reward functions and weights, how to run, what next | 22 | ☑ | `README.md`: live links, stack, architecture, schema, rewards + weights, RL objective, how to run, cold start, what next |
| D6 | Eval report: 3+ configs, 3+ rollouts, mean ± SD, tier breakdown, adversarial baselines, judge reliability, fidelity divergence rate, total spend | 22 | ☑ | `docs/EVAL_REPORT.md`: 7 configs × 3 rollouts, mean ± SD, tiers, baselines + floors, paired CIs, judge 0/60, fidelity 0/50, spend |
| D7 | RL report: curves (reward, KL, entropy, length, per-tier pass rate), held-out before/after, KL sweep, gaming instance | 18 | ☑ | `docs/RL_REPORT.md` Part A (pre-registration + amendments A9–A16) and Part B (curves, held-out, β sweep, 3 gaming instances) |
| D8 | Failure analysis: 5–10 transcripts read by hand, categorised with counts | 22 | ☑ (user review pending) | `docs/FAILURE_ANALYSIS.md`: 13 transcripts read, 7 categories, each counted across all rollouts |
| D9 | Advanced-track write-up | 20 | ☑ | `docs/TRACK_C.md` |
| D10 | Edge-cases document: top 5 and how each was handled | 22 | ☑ | `docs/EDGE_CASES.md` |
| D11 | Assumptions and trade-offs: ≥3 deliberate trade-offs (mocked, simplified, cut) | 22 | ☑ | `docs/TRADEOFFS.md` (12 trade-offs, what we mocked, what we cut) |
| D12 | AI usage disclosure | 22 | ☑ | `docs/AI_USAGE.md` |

## §10 Evaluation criteria and anti-goals (p.17–18)

| ID | Criterion / anti-goal | Step | Status | Evidence |
|---|---|---|---|---|
| EV.1 | Same environment serves the eval, the trainer, and the sandbox | 12, 14, 19 | ☑ | trainer data = `load_environment(...).get_dataset()`; eval rollouts = `env.run_rollout`; sandbox = same `score_answer`; parity test API == rubric == env |
| EV.2 | Failures, retries, checkpoints and costs handled rather than ignored | 9, 14, 17 | ☑ | retries + `retried` flag, resume, cost cap, daily quota ledger, `unavailable` status, training checkpoints/resume, judge failures raise (PROGRESS: every failure and fix logged) |
| EV.3 | Reward attacked by ourselves and fixed | 10, 18 | ☑ | 5 adversarial baselines under floors + 3 exploits found by the optimiser and closed (RL_REPORT B6) |
| AG.1 | Not a gym where everything scores 100% | 15 | ☑ | no model or baseline at 100 %: full-eval best +0.314; distribution −1…+1 |
| AG.2 | No GT generated by the evaluated model | 4, 6 | ☑ | GT only from `compute_payslip` / rule tables; `paygym validate` recomputes it |
| AG.3 | No single-rollout leaderboard | 15 | ☑ | 3 rollouts per task everywhere |
| AG.4 | Depth over breadth (one slice) | 2 | ☑ | One slice: gross-to-net (`ruleset/v1.0/RULESET.md`) |
| AG.5 | No rising reward curve without held-out evaluation | 18 | ☑ | held-out before/after scored once (RL_REPORT B5); validation split used for selection |
| AG.6 | No training without a reference model / KL term | 17 | ☑ | β > 0 enforced (`train/grpo_train.py`), KL logged every step |
| AG.7 | Transcripts, not just a final number | 16, 18 | ☑ | every rollout's transcript in `transcript.jsonl` + dashboard transcript viewer; FAILURE_ANALYSIS reads 13 |
| AG.8 | Training run finished (scale chosen to fit compute) | 8, 17 | ☑ | β 0.04 and 0.001 runs finished 60 steps each; best-validation checkpoint selected (RL_REPORT A16) |
| AG.9 | Sandbox does not return expected answers | 19 | ☑ (tests pass) | leak fuzz test |
| AG.10 | Sandbox scores with the same logic as the dashboard | 19 | ☑ (tests pass) | parity test |

## §11 Rules and constraints (p.18)

| ID | Rule | Step | Status | Evidence |
|---|---|---|---|---|
| R.1 | Built solo; assignment not shared | all | ☑ | Solo build |
| R.2 | AI tools used and disclosed | 22 | ☑ | `docs/AI_USAGE.md` |
| R.3 | No real customer or personal data; synthetic and fictional only | 2, 6 | ☑ | fictional jurisdictions, synthetic employees (`paygym/generator.py`); no real data anywhere |
| R.4 | No paid infrastructure required | 1 | ☑ | free tiers only: Google AI Studio, Groq, Vercel Hobby, Upstash free; $0 spent |
| R.5 | Mocking documented: what, why, real implementation | 22 | ☑ | `docs/TRADEOFFS.md` §What we mocked |
| R.6 | Scope down loudly: cuts and "two more days" written down | 22 | ☑ | `docs/TRADEOFFS.md` (scoped-down items, 'two more days'); RL_REPORT B8 |
