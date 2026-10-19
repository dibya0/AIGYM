# Build log

One entry per step: what the brief requires (quoted, with page), what was built, the checks, and any deviation from the plan.

---

## Step 1: Environment setup (2026-10-17)

**Brief (entry gate)**
- p.16, §9 #1: "GitHub repository — Public or shared with us. Must run from a clean clone with documented setup (`uv sync` or `pip install -e .`, plus `.env.example`)."
- p.8, Phase 03: "Expose `load_environment(**kwargs) -> vf.Environment` from an installable package with a `pyproject.toml`."
- p.18, §11.4: "No paid infrastructure required. Free model tiers, free GPU notebooks, and free hosting are sufficient throughout."

**Built**
- `pyproject.toml`: installable `paygym` package, `paygym` CLI entry point, extras (`env`, `eval`, `sandbox`, `dashboard`, `train`, `cpu`), dev group (`pytest`, `hypothesis`).
  - `verifiers==0.2.1` pinned: the last release with the v0 API the brief specifies; 0.3.0 removed it.
  - Training stack pinned to releases ≥2 weeks old that work together: `torch==2.13.0` (CUDA 12.9 wheels, the torch version vLLM 0.30 pins), `transformers==5.18.0`, `trl==1.14.1`, `peft==0.21.1`.
- `.python-version` (3.12), `.env.example` (free-tier keys only), `.gitignore` (secrets, weights, build output).
- `paygym/` package with `__version__` and a CLI skeleton; `tests/test_package.py`.
- `docker-compose.yml`: `redis` (default), `sandbox` (profile, lands in Step 19), `llm` (vLLM `v0.30.0` on the GPU, profile `gpu`), `dashboard` (nginx preview, profile `dashboard`).
- `scripts/check_gpu.py`: PyTorch device, compute capability, bf16, and a real GPU matmul.
- `README.md` setup section; `docs/REQUIREMENTS_CHECKLIST.md` (every brief requirement with page, step, status, evidence).

**Checks (run by Claude in an isolated scratch environment)**
- `uv sync` → `uv.lock` resolves **all** extras (155 packages): `torch 2.13.0+cu129`, `verifiers 0.2.1`, `trl 1.14.1`, so the pins are mutually compatible.
- `uv run pytest -q` → `3 passed`; `uv run paygym --version` → `paygym 0.1.0`.
- `docker compose config --quiet` → OK.
- Pending (user, needs the NVIDIA driver): `scripts/check_gpu.py`, `docker run --gpus all … nvidia-smi`. Listed in `docs/USER_ACTIONS.md` §A.

**Exit gate vs brief**: p.16 §9 #1, installable with `uv sync`, plus `.env.example`: met for setup (the clean-clone run is re-checked in Step 23). p.8, installable package with `pyproject.toml`: met (`load_environment` lands in Step 12).

**Deviations from plan**: none.

---

## Step 2: Rule book, prose (2026-10-17)

**Brief (entry gate)**
- p.9: "Pin and version the rule set as its own artifact… separate from the code… If you invented the rule set, write it out in full before you implement it. A rule set that exists only as Python is circular."
- p.4: "A fictional tax code with six brackets and two ceilings is a perfectly respectable gym… write them out as prose first."
- p.5: "Wage ceilings on statutory contributions are the most productive source of difficulty."
- p.10: abstention is correct only where "the rules are silent, the rules are self-contradictory, or a required input is absent".

**Built**: `ruleset/v1.0/RULESET.md`, written before any calculator code.
- Three fictional jurisdictions with stable clause IDs (`GEN-§`, `VAL-§`, `KES-§`, `NRD-§`, `FX-§`).
- 10 brackets in total; **two ceiling types** (monthly in VAL/NRD; annual cumulative in KES).
- Rounding and tolerance defined by rule (GEN-§1.3/§1.4); explicit order of computation (GEN-§3).
- Effective-dated 2025/2026 tables, FX table.
- Undetermined cases mapped to the brief's three categories: absent input `MISSING_INPUT`; self-contradictory records `CONFLICTING_RECORDS`; rules silent `NO_APPLICABLE_TABLE` / `UNSUPPORTED_CURRENCY`; plus a precedence rule (GEN-§9.5).
- Required / optional / **unused** input classes (GEN-§2.2). These make trap twins possible: residency is required in KES but unused in VAL/NRD.

**Ambiguities found and fixed during review**: optional inputs needed their own class (conflicts on them count); KES January YTD is disregarded if stated; salary-change currency; later steps use full-precision amounts, not rounded lines (GEN-§1.3). The last one was found while writing the calculator, which is exactly the "where code and rule set disagree, fix the rule set's ambiguity" loop the brief describes.

**Exit gate**: every rate and ceiling is in prose with a clause ID. User read-through pending (`docs/USER_ACTIONS.md` §C).

---

## Step 3: Structured rules (2026-10-17)

**Brief (entry gate)**: p.9, "lives in the repo as readable prose or structured rules… with a version identifier recorded in every result file."

**Built**
- `ruleset/v1.0/rules.yaml`: the rate tables, every value tagged with its clause; decimals as strings.
- `paygym/ruleset.py`: typed loader (Decimal), `table()` / `fx_rate()` lookups, and a **fingerprint** (sha256 of RULESET.md + rules.yaml) for result files.
- Rule set packaged into the wheel (`force-include`), so the Vercel sandbox scores against the identical files.
- `tests/test_ruleset.py` parses the **Markdown tables in RULESET.md independently** and asserts every YAML value matches. It also checks that every cited clause exists in the prose and that no rule is YAML-only.

**Checks**: 8 tests pass. **Mutation check**: changing the VAL 2026 ceiling 6000→6100 in YAML fails with `('VAL', 2026, 'si_ceiling')`; restoring passes.

---

## Step 4: Reference calculator (2026-10-17)

**Brief (entry gate)**
- p.8: "ground truth computed by an independent Python reference implementation, not by an LLM… Unit tests on the reference implementation. If you do not trust your own calculator, no number downstream means anything."
- p.9: "Every rule in code carries a citation to the specific clause it implements. Where code and rule set disagree, the rule set is right and the code has a bug."

**Built**
- `paygym/reference/`: `inputs.py` (multi-source inputs), `trace.py` (`@cites` decorator + `Trace`), `calculator.py`.
- `resolve_inputs` implements GEN-§2/§9 with the precedence rule. `compute_payslip` returns a `Payslip` (rounded lines + clauses per line + full trace) or `Undetermined` (reason code, clause, offending inputs).
- Exact `Decimal` arithmetic.
- Contribution lines inherit the ceiling clause when it binds, so provenance names the clause that actually drove the amount.

**Checks**
- `tests/test_reference.py`: 16 hand-computed cases, with the arithmetic written in each docstring. Covers all three jurisdictions, both ceiling types, FX, a mid-month raise, retro pay, calendar and working-day proration, whole-unit rounding, every undetermined reason, the twins, and precedence.
- `tests/test_reference_properties.py` (Hypothesis, ~1,000 random cases):
  - net ≤ gross
  - contributions ≤ rate × ceiling
  - rounding to the minor unit
  - net monotone in salary
  - metamorphic: a foreign salary equals its converted local salary
  - metamorphic: a split month adds up to a full month
- **Mutation check**: deleting the ceiling (the brief's named failure, p.5) fails 5 tests; restored, all **36 pass**.

**Deviation from plan**: none. Property tests were marked *(extra)* and are done.

---

## Step 5: Task schema + seed tasks (2026-10-18)

**Brief (entry gate)**, p.7:
- "Define a task schema (JSON or YAML) and validate it programmatically. Minimum fields: id, slice, difficulty, prompt, context_files (optional), ground_truth, verifier, tags, schema_version."
- "Ship at least 10 hand-checked tasks across three difficulty tiers… Include at least 3 Tier-3 traps. An agent that answers these confidently must score zero or negative."
- "Every task ships with machine-checkable ground_truth… Prose-only ground truth is not acceptable for Tiers 1 and 2."
- "Validate the entire taskset with one command, and ideally in CI."
- Edge case: "Schema drift. What happens to results from v1 when you add a field in v2?"

**Built**
- `paygym/schema.py`: `Task` with the brief's fields plus `case`, `lookup`, `employee_id`, `documents`, `ruleset_version`, `twin_of`, `trap_reason`, `provenance`, `seed`, `hand_check`.
  - Ground truth is a discriminated union: `value` (Tier 1) / `payslip` (Tier 2, lines + tolerance + clauses per line) / `refusal` (Tier 3, reason code + clause).
  - A model validator enforces the consistency rules: verifier matches GT kind; Tier 3 ⇔ refusal; every trap has a `trap_reason`.
- Schema drift: `extra="forbid"` plus `load_task()`, which upgrades through registered `MIGRATIONS` and refuses unknown versions loudly.
- `paygym/truth.py`: GT only from the rule set and reference implementation. `paygym/render.py`: case → documents and prompt, with stated date / number / annual-salary conventions (GEN-§2.4–2.6). Rule-book sections attach as `context_files` (`ruleset:GEN`, `ruleset:VAL`, …).
- `scripts/build_seed_tasks.py` → `tasks/seed_v1.jsonl`, 16 hand-written tasks:
  - Tier 1: 3 retrieval tasks.
  - Tier 2: 5 payslips (ceiling binds; FX + raise + retro; KES annual ceiling; NRD working-day proration with an annual figure; VAL rounding) plus 4 twins.
  - Tier 3: 4 traps, one per reason code, covering all 3 brief categories.
  - Each task carries its **hand-worked** values; `validate` fails if the reference disagrees.
- `paygym validate <path>` (CLI) and `paygym schema`.
- `tests/test_tasks.py`: brief minimums; clean validation; committed file == fresh build; trap categories; prompt leakage guard; tamper / hand-mismatch / missing-twin detection; schema drift.

**Verification (Claude, by review)**: walked each brief sentence above against the code. Traced the JSON round trip (Decimal ↔ str, dates, tuples) and the `validate` equality checks by hand. Twin hand calculations re-derived independently.

**Run**: pending, user (`docs/USER_ACTIONS.md` §F, Step 5).

**Deviation from plan**: 16 seed tasks instead of 12–15, because each of the 4 traps needs its own determinable twin.

---

## Step 6: Generator + audits (2026-10-18)

**Brief (entry gate)**
- p.8: "A generator that takes a seed and emits N instances, with ground truth computed by an independent Python reference implementation, not by an LLM… Deterministic and reproducible: same seed produces an identical taskset. Record the seed in every result file. Difficulty knobs exposed as parameters… Generate at least 100 instances…"
- p.7 edges: "Answer leakage… Write a check for this and report what it caught." "Near-duplicates that inflate your sample size without adding signal." "Unit, scale, and format ambiguity."
- p.12: "Generator seeds must not overlap between the two partitions."

**Built**
- `paygym/generator.py`:
  - **Seeds:** one `PCG64` stream per task seed, so each task is prefix-stable and reproducible. Disjoint seed ranges per split (`SPLITS`: train / val / heldout / eval). The seed is stored on every task.
  - **Knobs** (`Knobs`): tier mix, jurisdictions, years, ceiling-binding, proration, mid-period change, retro, currency mix, allowances (interacting rules), split sources (more lookups), irrelevant context, date/number format, annual-salary statement.
  - **Traps** are always emitted with a minimally different determinable twin. The twin variety tests the rules about unused inputs: an unused input dropped, or documents that disagree only on a non-input. A runtime guard asserts every trap yields exactly its intended reason code.
  - **Tags** reflect what actually happened. `ceiling_binds` is read from the reference trace, not from sampling intent.
- `paygym/audit/leakage.py`: literal-leak check, plus a TF-IDF + logistic-regression "phrasing" classifier against the majority baseline. It reports the top n-grams per label so a human can tell evidence from template artifacts.
- `paygym/audit/dedup.py`: exact duplicates (case and prompt) and 5-shingle Jaccard near-duplicates. Trap/twin pairs are reported separately as similar by design.
- CLI: `paygym generate --split … --seeds …`, `paygym audit …`; `validate` now recurses into `tasks/`.
- `tests/test_generator.py` (17): determinism, prefix-stability, seed recorded, validity, ≥100 with all tiers, all 4 trap reasons with twins, ceiling variation, no duplicates within a split, disjoint ranges **and** disjoint content between train and held-out, train has no retrieval, knobs work, no reason codes in prompts, audits run with 0 literal leaks.

**Defects found by Claude's own review, fixed before hand-off**
1. Conflict values were smuggled into `fields` with magic keys plus a monkeypatch; replaced by an explicit per-source `overrides`.
2. The `ceiling_binds` tag came from sampling intent; proration can undo it, so it is now derived from the trace.
3. **Dataset defect:** only ~50 distinct retrieval questions exist, so they would duplicate within a split and leak across splits. Fix: per-split dedup in `generate()`, and **no retrieval tasks in train** (see `docs/TRADEOFFS.md`).
4. The literal-leak check would flag input coincidences (a 350.00 allowance vs a capped 350 NMK contribution) and bare integers inside employee IDs; it now ignores input amounts and matches formatted amounts only.

**Run**: pending, user (`docs/USER_ACTIONS.md` §F, Step 6).

---

## Step 7: CI (2026-10-18)

**Brief**: p.7, "Validate the entire taskset with one command, and ideally in CI."
**Built**: `.github/workflows/ci.yml`: uv + Python 3.12, `uv sync --extra cpu --locked`, `paygym validate tasks/`, `pytest -q`. CPU only; the training stack is not needed to test the gym.
**Run**: pending, user (push to GitHub).

---

## Step 8: RL smoke-test script (2026-10-18)

**Brief (entry gate)**
- p.11: "Algorithm: your choice… Whatever you choose, write the objective you actually implemented into the README… the reward must come from your own Phase 04 rubric, there must be a frozen reference model with an explicit KL penalty… report your coefficient beta, state which KL estimator you used, and log the measured divergence at every step… sample at least 4 completions per prompt and report the fraction of groups in which every rollout scored identically."
- p.13: "Get the loop running end to end on a tiny taskset on day one of this phase, then scale it."

**API verified against the installed version's source, not memory.** Read TRL 1.14.1 `grpo_config.py` / `grpo_trainer.py` from the published wheel:
- `loss_type="dr_grpo"` is supported, and `scale_rewards="none"` is documented as the Dr. GRPO recommendation.
- `beta` defaults to `0.0` and then "the reference model is not loaded", and `kl` is only logged when `beta != 0`. This confirms the plan's β=0.001-not-0 decision.
- With a PEFT model, the reference is the adapter-disabled base (`ref_model=None`, "adapter can be disabled").
- The KL estimator is k3, `exp(ref−logp) − (ref−logp) − 1`, matching the brief's worked objective.
- Built-in metrics include `kl`, `entropy`, `completions/mean_length`, `frac_reward_zero_std` (the brief's degenerate-group fraction) and `reward`.
- Reward functions get the dataset columns plus a `log_metric` hook (used for hack monitors in Step 17).
- The constructor accepts a model name string, `peft_config` and `callbacks`, and supports conversational prompts. There is no `max_prompt_length` field in this version, so none is passed.

**Built**
- `paygym/prompting.py`: the single prompt builder and output contract shared by env, eval and trainer; prompt hash for result files.
- `train/grpo_train.py`: LoRA r=16; `dr_grpo`; `scale_rewards="none"`; β required > 0; G ≥ 4 enforced; per-step CSV of every TRL metric plus seconds per step; checkpoints every 25 steps; `--resume`; `config.json` with rule-set fingerprint, prompt hash, loss, KL estimator and reference description. `--reward smoke` (format-only, labelled not-a-result); `--reward rubric` wired for Step 10.

**Defect found by review**: the Compose vLLM `max-model-len 4096` was too small for single-turn prompts (~3.4k tokens of rule book + ~0.4k task + 384 completion). Raised to 8192.

**Run**: pending, user (needs the driver).

---

## Step 9: Tools + parser (2026-10-18)

**Brief (entry gate)**, pp.8–9:
- "Tool-use (ToolEnv or equivalent): the model must call tools to succeed. Provide 2-4 real tools… In tool mode, the tools must be the only source of the reference data the model needs."
- "A structured output contract (JSON block or XML tags) with a parser you own."
- Edges: "Model returns malformed or truncated JSON. Model calls a tool with invalid arguments, or loops calling the same tool indefinitely. A tool raises or times out. Does the rollout fail loudly and get recorded…?"

**verifiers 0.2.1 read from source.** `StatefulToolEnv.add_tool(tool, args_to_skip=[...])` hides arguments from the model's schema, and `update_tool_args(...)` injects them per rollout from `state["info"]`. Rubric functions receive `prompt, completion, answer, state, info, parser`. **Implication:** a trap and its twin share an employee id but not their records, so tools take a hidden `task_json` injected per rollout, not a global lookup.

**Built**
- `paygym/parser.py`: the last fenced JSON block wins; `<think>` blocks are ignored; a bare trailing object is tolerated, and so is one trailing comma. Named errors: `no_json`, `truncated`, `invalid_json`, `not_an_object`, `bad_decision`, `bad_reason_code`, `missing_lines`, `bad_value`. Number normalisation for strings, locale separators, a currency prefix and `%`, flagged as `normalised_numbers`.
- `paygym/tools.py`: 4 stateless tools:
  - `get_employee_record`: the documents as stated, per source; never ground truth.
  - `lookup_rules(jurisdiction, year)`: rule text + rate table, or an explicit "no table".
  - `get_fx_rate`: month-end only, per FX-§1.1.
  - `calc`: AST-whitelisted exact decimal arithmetic; no `eval`, no `**`, length cap.

  Bad arguments return structured `{"error", "code"}` JSON. Loop detection and timeouts are environment-level (Step 12).
- `tests/test_parser_tools.py` (14).

**Defects found by review, fixed**: the `calc` comma handling was nonsensical; `Decimal.normalize()` would print `6E+3`; the fenced regex missed arrays (wrong error name).

**Run**: pending, user.

---

## Step 10: Rubric, gating, baselines (2026-10-18)

**Brief (entry gate)**, pp.9–12:
- "At least one programmatic verifier… Its numeric tolerance must be justified in terms of the rule set."
- "Each reward function returns the clause or clauses that drove the score."
- "State what each score level means in terms of the rule set… Gate partial credit so that an answer which would be rejected under the rules cannot score above a low floor."
- "At least one graded partial-credit reward."
- "A calibration reward… Abstaining on a task the rules do determine must be penalised exactly like a wrong answer."
- p.7: Tier-3 confident answers "must score zero or negative, never partial credit."
- "Document your weights and defend them."
- p.11–12: probe the reward with hand-written baselines.

**Built**
- `paygym/rubric.py`, **the single scorer**:
  - A **score-level table** in the module docstring, per task kind.
  - Payslip weights: net 0.70, lines 0.25, format 0.05, with the rationale written beside them.
  - Gates: wrong net capped at 0.25; a refusal on a determinable task goes through the wrong-answer path with no correct lines (0.05); answering a trap is −1.0; a refusal with the wrong reason gets 0.3; a correct refusal gets 0.8 plus up to 0.2 from the judge.
  - Retrieval: exact match (tolerance 0, a table read).
  - Every component returns clauses. Line accuracy reports the **first wrong line in computation order** and its clauses, so a missed ceiling is traced to `VAL-§2.1`.
  - A judge failure **raises** rather than scoring 0.
- Gating is a cap, which a weighted sum can't express, so the total is computed in the rubric and the components are reported as the breakdown (the plan's flat weight table is superseded by per-task-kind weights; see the docstring).
- `paygym/training_reward.py`: the rubric as a TRL reward (judge weight 0), plus per-step monitors via TRL's `log_metric`: twin refusal rate, trap answer rate, parse-fail rate, modal net-pay share, length–reward correlation, per-tier pass rates.
- `paygym/baselines.py`: `format_only`, `always_abstain`, `modal_answer`, `naive_no_ceiling` (the brief's named failure; never refuses), `gross_as_net`, each with a stated floor.
- `tests/test_rubric.py`: score levels; tolerance from the rules (VAL 0.01, NRD 1); cap; partial; refusal on a determinable case vs a wrong answer; trap answered = −1; wrong reason; judge bonus and judge failure; unparseable; retrieval exact; clauses on every component; the ceiling miss traced to `VAL-§2.1`; **every baseline under its floor**; baselines ≥0.4 below the reference; the TRL adapter and its monitors.

**Hand-derived expected baseline means** (default mix ≈ 20% retrieval / 40% payslip / 20% trap / 20% twin): format-only ≈ −0.12, always-abstain ≈ 0.12, modal ≈ <0, naive-no-ceiling ≈ 0.19, gross-as-net ≈ −0.07. All are under their floors. Actual values come from the run.

**Defects found by review, fixed**: an empty clause list on unparseable line accuracy; the baseline FX check used a hard-coded year; the no-ceiling rule set was rebuilt on every call (now cached); a dead line in the reward adapter.

**Run**: pending, user.

---

## Step 11: Judge + reliability tooling (2026-10-18)

**Brief (entry gate)**, p.10: "At least one LLM-judge reward, for something genuinely unverifiable such as the quality of a written flag… The pass or fail criteria must be derived from the rule set, not invented by the judge. Version the prompt in the repo, and measure judge reliability by running it three times over the same outputs and reporting the disagreement rate, or by hand-labelling 15 outputs and reporting judge-versus-human agreement."

**Built**
- `paygym/judge.py`:
  - **Scope:** judges only traps refused with the correct reason code; the decision itself is programmatic.
  - **Criteria:** three pass/fail criteria derived from GEN-§9 ("identifies the missing, conflicting or unsupported input"): names the input; states why the rules do not determine it (quoting the actual clause text); actionable for a payroll operator. Each criterion is judged in its own call (Harvey pattern), and score = fraction passed.
  - **Model and determinism:** Gemini via the OpenAI-compatible endpoint (free), temperature 0. The prompt is versioned and hashed.
  - **Cache:** results are cached by (prompt hash, model, criterion, task, explanation), so identical answers score identically. This gives sandbox/eval parity and no repeat cost.
  - **Failure handling:** retries with backoff; JSON-mode fallback if the endpoint rejects `response_format`; failure raises `JudgeError`, never a silent 0.
- `paygym/judge_reliability.py`: **both** reliability measures. 3-repeat disagreement rate with the cache bypassed, and a 15-output labelling sheet with agreement + Cohen's κ (per criterion and overall).
- `tests/test_judge.py` (5, no key needed).

**Design note**: "no fabricated numbers" was a candidate criterion but is programmatically checkable, so it is deliberately not given to the judge (brief: the judge is for what is *genuinely unverifiable*).

**Run**: pending, user (tests now; reliability after Step 15).

---

## Step 12: verifiers environment (2026-10-18)

**Brief (entry gate)**
- p.8: "Expose `load_environment(**kwargs) -> vf.Environment` from an installable package with a pyproject.toml… Implement both environment modes… Enforce max_turns and a per-rollout timeout… Runnable against any OpenAI-compatible endpoint."
- p.17: "Follows the verifiers spec, so the same environment serves the eval, the trainer, and the sandbox."

**verifiers 0.2.1 read from source**
- `vf.load_environment("paygym")` → `importlib.import_module("paygym").load_environment(**args)`.
- `MultiTurnEnv(max_turns, timeout_seconds)`; the rollout runs under `asyncio.wait_for`.
- `SingleTurnEnv(**kw)` → `MultiTurnEnv(max_turns=1, **kw)`.
- Custom stop conditions are `@vf.stop` methods; `state["stop_condition"]` records the method name.
- Each trajectory step's `completion` is only that step's message, so loop counting is not doubled.
- `state_to_output` saves only standard fields, so caching the score in state is safe.

**Built**
- `paygym/environment.py`:
  - `load_environment(mode, split, n_seeds, tasks_path, tier, max_turns=8, timeout_seconds=120, use_judge)`.
  - The dataset comes from the generator (portable without repo files) or a task file. `info` carries the task JSON; the prompt never carries ground truth.
  - `single` → `vf.SingleTurnEnv`; `tool` → `PaygymToolEnv(vf.StatefulToolEnv)`. The 4 tools are added with `task_json` hidden and injected per rollout.
  - `@vf.stop tool_loop_detected`: the identical call 3× in a row ends the rollout.
  - Rubric: `paygym_reward` (weight 1, the gated total) plus weight-0 metrics for every component and for monitors (`refused`, `parse_failed`, `tool_errors`).
- `paygym.load_environment` at the package root (lazy import), so verifiers discovers the package.
- **One environment, three consumers:** `train/grpo_train.py` now reads its dataset from `load_environment()` (same prompts and `info`), and `rubric_reward` scores the env's `info` column. `train` extra now includes `paygym[env]`.
- `tests/test_environment.py` (7; skip without verifiers).

**Run**: pending, user.

---

## Step 13: Fidelity audit worksheet (2026-10-18)

**Brief**, p.10: "Run a rule-set fidelity audit. Hand-check at least 10 generated tasks against the rule-set text and report the divergence rate between the rules and your reference implementation."

**Built**: `scripts/fidelity_sample.py` picks 10 generated eval tasks, stratified (VAL ceiling binds, KES annual ceiling, NRD proration, FX + mid-period change, retro + allowances, NRD ceiling, KES January, end-date proration, 2 traps). It writes `docs/FIDELITY_AUDIT.md`: Part 1 has the inputs plus blank hand-value columns; Part 2 has the reference values, separated so the hand check is not anchored on the code.

**Remaining**: hand derivation (Claude, from prose) + user review, after the user runs the script. **Run**: pending.

---

## Step 14: Eval harness (2026-10-18)

**Brief (entry gate)**, p.10:
- "One command runs an evaluation… Support at least three model configurations, including one frontier model and one small or cheap model… At least 3 rollouts per task at non-zero temperature, reporting mean +/- standard deviation."
- "Persist per run: config.json (model, seed, taskset version, prompt hashes), transcript.jsonl (full messages and tool calls), metrics.json (tokens, latency, cost, tool-call counts), and scores.json (per-task, per-reward-function breakdown)."
- "Cost guardrail. A hard --max-cost cap that aborts cleanly and reports partial results. Bounded-concurrency worker pool. Report what you actually spent."
- Edges: crash at task 60 (resumable?), one provider down, non-determinism reported honestly.

**verifiers 0.2.1 read from source**: `env.run_rollout(input, ClientConfig(api_key_var, api_base_url, max_retries, timeout), model, sampling_args)` runs and scores one rollout. It returns `reward`, `metrics` (our components and `total_tool_calls`), `token_usage`, `timing` (`model.duration`, `total`), `error`, `stop_condition`, `completion`.

**Built**
- `python -m paygym.eval` (`paygym/eval/runner.py`). **Every model rollout is executed by the verifiers environment** (same prompts, tools, limits and rubric as the trainer and sandbox); the harness adds:
  - concurrency semaphore plus a per-provider rate limiter;
  - `--max-cost` at list prices: no new rollouts once reached, in-flight ones finish, `status=aborted_cost`, exit 2;
  - resume from `transcript.jsonl` (refuses if the model, taskset, rule set, rubric or prompt changed);
  - retries on transient errors (429/5xx/timeout), marked `retried`;
  - `unavailable` after N consecutive provider errors (exit 3);
  - API failures are `status=error`, excluded from means and reported; model behaviour (bad JSON, loops, turn or timeout limits) is scored and flagged via `stop_condition`.
- `--model baseline/<name>` runs the adversarial baselines through the same scorer and files, so they share the leaderboard.
- Files: `config.json` (model, provider, sampling, seed, **task seeds**, taskset hash, schema / rule-set version + fingerprint, rubric version, prompt hash, judge model + hash, git sha, versions); `transcript.jsonl` (one line per rollout: full completion incl. tool calls, prompt with the rule-book text replaced by a marker, reward, components, gate, driving clauses, tokens, latency, cost, retries, status); `metrics.json` (tokens, list vs actual cost, latency mean/p50/p95, tool calls, stop conditions, retries, errors, parse-fail rate, wall clock); `scores.json` (per-task rewards / mean / SD / components, by tier, twins, by component, gates, summary).
- `paygym/eval/providers.py`: prefix routing `groq/`, `gemini/`, `local/`, `baseline/`, or any endpoint via `--base-url`. List prices are for the guardrail only; actual spend is $0 on free tiers.
- `paygym/eval/stats.py`: mean over tasks, run SD (across rollout passes), within-task rollout SD, **disagreement rate**, bootstrap and **paired bootstrap** CIs.
- `paygym/eval/leaderboard.py` + `paygym leaderboard`: comparison groups by taskset, mode, rule-set fingerprint and rubric (**version skew never compared**); pairwise paired bootstrap; an "indistinguishable" list.
- `paygym judge items|repeat|labels|agreement`: judge reliability from real transcripts.
- `tests/test_eval_harness.py` (7): baseline run writes the 4 files with the required config keys; cost-cap abort with partial results; retry marked; provider outage → unavailable; resume makes 0 new calls; stats; leaderboard grouping.

**Defects found by review, fixed**: the twins aggregation was muddled (would report NaN or None); the local dummy key was set after the client config; the verifiers version lookup; added `python-dotenv` so `.env` loads.

**Run**: pending, user.

---

## Step 15: Sweep tooling (2026-10-18)

**Brief**: P05, ">=3 model configurations… >=3 rollouts"; P02, "demonstrate the score distribution is non-degenerate"; P04, "Document your weights and defend them… real consequences for model ranking"; §8, "Report the models you chose and roughly what you spent."

**Built**
- `scripts/sweep.sh` covers:
  - 5 baselines;
  - Gemini (frontier, free) and Groq gpt-oss-120b (large open, free), single-turn with the judge;
  - tool mode on a 50-task subset;
  - local Qwen2.5-3B and Qwen2.5-0.5B-base on vLLM;
  - then the leaderboard and sensitivity.

  Every run is resumable by re-running the same command.
- `paygym/eval/sensitivity.py` *(plan extra)* re-scores the recorded payslip rollouts under 3 alternative (net, lines, format) weightings with the same gates, and reports Kendall's τ of the ranking vs the shipped weights.

**Run**: pending, user (the sweep itself). Results feed Steps 16, 20 and 22.

---

## Step 16: Dashboard v1 (2026-10-18)

**Brief (entry gate)**, p.11: "A deployed page that a hiring manager or product lead can read in 90 seconds… Leaderboard. Model x mean reward, with error bars or +/- SD. Breakdown by difficulty tier and by reward function, not one aggregate number. Failure heatmap. Task x model… Transcript viewer… Adversarial baselines from Phase 04, sitting on the same leaderboard… Cost and latency per model… What is graded is whether the page answers: which model should we use, for which tasks, and where will it hurt us?" p.6: a static page in the Harvey LAB style is fine; results are committed and nothing re-runs on deploy.

**Built**
- `paygym/dashboard/build.py` → `public/index.html` (+ lazy-loaded `public/data/<run>.json` transcripts). Static; Vercel serves the committed `public/`. Sections:
  1. **Verdict:** best overall; best per tier; per model, the payslip exact rate, trap-answered rate, twin score (over-refusal), cost per correct payslip at list price, and the top failure clauses ("where it hurts").
  2. **Leaderboard:** mean ± SD error bars, baselines in grey, within-task rollout SD, disagreement rate, per tier, twins, ok/failed rollouts. Plus an **"indistinguishable pairs"** list from the paired bootstrap.
  3. **Breakdowns:** by tier and by reward function; weight-sensitivity τ table.
  4. **Failure heatmap:** task × model; click opens that transcript.
  5. **Cost and latency:** list vs actual cost, mean/p95 latency, tool calls, parse failures.
  6. **RL curves** (Step 17–18 data).
  7. **Track C** (Step 20 data).
  8. **External sandbox runs:** fetched live (Step 19).
  9. **Transcript viewer:** run and task pickers, failures-only filter, prompt, ground truth, every rollout's tool calls, results and final answer, gate and driving clauses.
- Only one comparison group sits on the main leaderboard; other modes, tasksets or rule-set versions are listed separately, never mixed.
- Safety: transcript text is inserted with `textContent`; the embedded JSON escapes `<`.
- `tests/test_dashboard.py`.
- Output moved from `site/` to committed `public/` (Vercel layout); `.gitignore` and the Compose preview are updated.

**Run**: pending, user (needs Step 15 results for real content).

---

## Step 17: RL pilot + training tooling (2026-10-18)

**Brief (entry gate)**, pp.11–13: frozen reference + explicit KL with β and estimator reported and KL logged every step; held-out split; ≥4 completions per prompt and the fraction of all-identical groups; the five curves; a KL sweep with ≥2 values, one deliberately too low; a documented gaming instance or evidence of the search; edges: entropy collapse, KL blow-up, length hacking, format collapse, degenerate groups, split leakage, a run dying mid-way.

**Built**
- **Pre-registration:** `docs/RL_REPORT.md` Part A. It records the objective as implemented (Dr. GRPO, no std scaling, k3 KL, adapter-off reference), the config, the β sweep {0.001, 0.04} and why not 0, the pilot criterion, the **stop rules**, model selection on validation with held-out scored once, and the gaming-hunt checklist with a monitor per exploit.
- **Difficulty presets** `--knobs default|easy|easier` (train split only; eval/held-out keep full difficulty), per the plan's "easier tasks, not a bigger model".
- `train/grpo_train.py` gains `ValidationAndSafety`:
  - validation at step 0 and every 25 steps (greedy, rubric-scored, per tier) → `validation.csv`, `best_checkpoint.json`;
  - a plateau stop;
  - safety stops on rolling KL / entropy / twin refusal / modal share → `stop_reason.json`;
  - every validation output saved to `val_samples.jsonl`.
- `paygym/training_reward.py` saves sampled training completions per step to `train_samples.jsonl`, for transcript evidence.
- `scripts/pilot_report.py` (identical-group fraction, per-tier pass, preset recommendation); `scripts/merge_adapter.py` (best-validation checkpoint → merged model; best step 0 is reported, not hidden); `scripts/rl_summary.py` (held-out before/after with a paired bootstrap; refuses mismatched tasksets → `results/train/rl_summary.json`, read by the dashboard).
- Compose `llm` mounts `./results` read-only to serve merged models.

**Gap found by review, closed**: the RL report promised transcript reading at checkpoints, but nothing saved completions. Validation and training samples are now persisted.

**Run**: pending, user (GPU).

---

## Step 19: Agent sandbox (2026-10-18)

**Brief (entry gate)**, pp.13–14:
- **Requirements:** a live URL that stays up without the laptop; fetch and submit operations; ground truth never on the wire; the same Phase 04 rubric and pinned rule set (no second scoring path); per-task score + per-reward-function breakdown + driving clause; `run_id` recording rule-set version, taskset seed and tier mix; a two-minute quickstart; guardrails (task cap, per-caller rate limit, no storage of others' keys) with an abuse/cost paragraph; optional external runs on the leaderboard.
- **Edges:** GT leakage (a "verbose validation error, a debug field, or an over-helpful rubric breakdown"; test it); 10,000 tasks / tight loop; concurrent writers; version skew; cold start.

**Built**
- `paygym/sandbox/app.py` (FastAPI): `/api/health`, `/api/tasks`, `/api/submit`, `/api/runs/{id}`, `/api/leaderboard`, `/api/tools/{name}`, OpenAPI docs at `/api/docs`. CORS for the public API.
- `paygym/sandbox/runs.py`:
  - **Public seed → HMAC(SANDBOX_SECRET) → per-task generator seeds.** The generator is open source, so a raw seed would reveal answers.
  - `run_id` is an HMAC-signed token carrying (public seed, tiers, n, rule-set version, issued-at), so scoring needs no stored ground truth.
  - The same public seed gives the same tasks (comparable runs).
  - Task ids are opaque positions (generator ids encode seeds).
- **Scoring is `paygym.rubric.score_answer`.** Responses carry component **scores**, clause ids and the gate, **never the rubric's `detail` text** (it names expected values: the "over-helpful rubric breakdown" the brief warns about).
- **Judge handling:** used if configured and within a per-caller daily budget. A judge outage re-scores without it and marks `judge_flag_quality: "deferred"`, never a 500 or a silent 0.
- **Guardrails:** n ≤ 50; per-caller rate limits (tasks / submit 30/min, tools 300/min, reads 120/min); answer size caps; validation errors return field locations only (no input echo); a generic 500 with no stack trace; nobody's API keys accepted or stored (answer-submission mode only).
- **Store** (`paygym/sandbox/store.py`): Upstash REST on Vercel, Redis locally, memory in tests. Atomic set-if-absent per `run_id`, so concurrent writers never collide and resubmission is idempotent.
- **Version skew:** a run issued under another rule-set version gets 409, never silently re-scored.
- **Vercel:** `api/index.py`, `vercel.json` (rewrites `/api/*`, bundles `paygym/` and `ruleset/`), `requirements.txt` (no verifiers/torch). **Local:** `docker/sandbox.Dockerfile` + the Compose `sandbox` service.
- `scripts/quickstart.py`: standard library only; waits out a cold start via `/api/health`; fetches, submits a trivial answer, prints the scores.
- `tests/test_sandbox.py`: round trip; same/different seed; **parity** (API == `score_answer` == the verifiers env reward); idempotent resubmission; task cap and bad tier; rate limit; tampered token 400 / version skew 409; tools; **leak fuzz** (all endpoints, valid and invalid input; asserts no GT number, reason code, task seed, secret or `detail` text in any body).

**Defects found by review, fixed**: a judge outage would have 500'd submissions; the leak test had a false positive on "tolerance" (that word is in the rule text shown to agents) and was replaced by detail-only markers; a rate-limit test ordering bug.

**Documented caveat** (README abuse paragraph): reusing a public seed returns the same tasks, which comparability requires, so per-task feedback from an earlier run could be reused. The default seed is random.

**Run**: pending, user (tests, local Compose, Vercel deploy).

---

## Step 20: Track C tooling (2026-10-18)

**Brief (entry gate)**, p.15, Track C: "Hold the model constant and vary the scaffold: prompt structure, tool availability, self-check step. Show whether scaffold matters more than model choice." Demonstrates "the single most commercially useful finding available in this space".

**Built**
- Scaffolds are variants of the **same environment**: `paygym/prompting.py::SCAFFOLDS`:
  - S0: bare prompt, no rule set;
  - S1: rule set in context;
  - S2: tools;
  - S3: tools + a mandatory calc self-check;
  - S4: S3 + a checklist (table year, required inputs/conflicts, FX support, ceiling type, proration, allowances).
- The scaffold threads through `load_environment(scaffold=…)`, `python -m paygym.eval --scaffold`, `config.json` (`scaffold`, scaffold-specific prompt hash) and the leaderboard group key.
- `scripts/track_c.py` → `results/track_c/summary.json` (dashboard) with, per (model, scaffold): mean ± SD, payslip exact rate, trap correctness, twin score, tokens and tool calls per rollout, list cost per correct payslip. It also computes the **scaffold effect** (best − worst scaffold, fixed model) vs the **model effect** (frontier − small at matched scaffolds) and states which is larger.
- Test: identical tasks across scaffolds; only the prompt and tools differ.

**Run**: pending, user.

---

## Steps 21–22: dashboard v2 + docs (2026-10-18)

**Brief**: §9 #5 README ("Stack, gym architecture, task schema, reward functions and weights, how to run it, what you would build next"); #10 edge cases ("the top 5 edge cases you hit"); #11 trade-offs (≥3); #12 AI usage ("Be specific and honest"); P02 README "where the approach breaks down"; P07 README objective; P08 quickstart + abuse/cost paragraph + cold start; §11 "document what you mocked", "scope down loudly".

**Built**
- **Dashboard v2:** the RL curves (all five plus monitors), Track C, external sandbox runs and weight sensitivity were already in the Step 16 template, wired to the data files from Steps 17–20; `--sandbox-url` enables the live external section.
- `README.md`:
  - why this slice; architecture; the single scorer;
  - the **spec-version note** (verifiers v0 pin + v1 mapping);
  - task schema and tiers; reward score levels, weights and rationale; clause provenance; judge; baselines;
  - how to run; the **RL objective as implemented**;
  - the sandbox quickstart and API, the **leak defences**, the **abuse/cost paragraph**, the seed-reuse caveat, the **cold-start note**;
  - **where "reference = verifier" breaks down**;
  - next steps including decide-then-compute (decision LLMs as future work); repo map.
- `docs/EDGE_CASES.md`: five real edge cases hit during the build, each with its handling and the test that guards it.
- `docs/TRADEOFFS.md`: 8 deliberate trade-offs plus "what we mocked".
- `docs/AI_USAGE.md`, `docs/RESEARCH_NOTES.md`, `docs/DEFENSE.md` (for the user), `docs/LOOM_SCRIPT.md` (timings match the brief's Loom requirements).
- Templates to be filled from results: `EVAL_REPORT.md` (all §9 #6 items), `FAILURE_ANALYSIS.md`, `TRACK_C.md`; `RL_REPORT.md` Part B.

**Remaining (needs run results)**: the numbers in the eval / RL / Track C / fidelity / failure reports; the Hub review notes; the live URLs.

**Final cross-module check (2026-10-18)**: generating `train.jsonl` and `train_easy.jsonl` from the same seeds would have produced duplicate task ids, failing `paygym validate tasks/` and CI. Non-default presets now prefix ids (`gen-easy-…`); test `test_presets_never_collide_with_default_ids`. Also noted: `pyproject.toml` changed after Step 1 (`paygym[env]` in `train`, `python-dotenv` in `eval`), so run `uv lock` before CI's `--locked` sync (USER_ACTIONS Step 7).

---

## Full brief re-verification (2026-10-18)

Re-read the PDF (pp.7–14 phase specs, plus §§9–11) line by line against the implementation. Six mismatches were found and fixed:

| Brief text | Mismatch | Fix |
|---|---|---|
| P08 "workable API shape": `GET /tasks`, `POST /submit`, `GET /runs/<run_id>` | routes existed only under `/api/` | aliases without the prefix (FastAPI + Vercel rewrites); test `test_brief_api_shape_paths_work_without_api_prefix` |
| P08 "one copy-pasteable command" usable "without cloning your repo" | the quickstart needed the repo | the dashboard build copies `quickstart.py` into `public/`; README: `curl -s …/quickstart.py \| python3 - …` |
| P02 "Record the seed in every result file"; P04 rule-set version "recorded in every result file" | only `config.json` and the transcript had them | `scores.json` and `metrics.json` are stamped with seed, task seeds, taskset hash, rule-set version and fingerprint, rubric and schema versions; transcript lines carry seed + rule-set version; test added |
| P02 "demonstrate the score distribution is non-degenerate" | no distribution shown | per-task reward histogram + share at 1.0 / ≤0 per model on the dashboard; section in EVAL_REPORT; test added |
| P02 "The reference implementation is the verifier… State this explicitly in your README" | README had only the "breaks down" half | new README section stating it explicitly |
| §11.6 "Write down what you cut and what you would do with two more days" | scattered | consolidated in `docs/TRADEOFFS.md` |

**Confirmed as matching** (unchanged):
- P01: all fields; ≥10 hand-checked; 3 tiers; ≥3 traps ≤0; machine-checkable GT; one-command validate + CI; 4 edge cases.
- P03: `load_environment` from an installable package; both modes; 4 tools (sole data source); `max_turns` + timeout; own parser; model as a CLI flag; 4 edge cases.
- P04: pinned prose rule set; clause citations; programmatic verifier with tolerance from the rules; clauses per reward; score levels + gating; partial credit; judge (versioned, both reliability measures); calibration with a reason per trap and penalised abstention; fidelity audit tooling; weights defended.
- P05: one command with the brief's exact flags; ≥3 configs; ≥3 rollouts; the 4 files; cost cap; concurrency; 3 edge cases.
- P06: every bullet.
- P07: all requirements + edge cases. The objective deviates from the brief's worked GRPO (no std, constant length normaliser) **by design, and is documented**.
- P08: every other bullet + edge cases.
- §7 Track C, §8 spend reporting, §9 deliverables 1–12 (results pending), §10 anti-goals, §11 rules.

---

## RL hyperparameters and tuning protocol (2026-10-18)

**Prompted by**: "what about parameter tuning in the RL part, and the choice of approach?" Brief p.11: "Algorithm: your choice… write the objective you actually implemented into the README and justify the choice in a paragraph"; §10: "Is the method you chose defended rather than merely copied?"

**Added to the pre-registration** (`docs/RL_REPORT.md`, before any training):
- **A2b:** every hyperparameter with its value, its reasoning, and whether it is tuned. Includes why GRPO over PPO / RLOO / DPO / REINFORCE, and why G = 8 (≈ 2% chance of an all-identical group at p = 0.4).
- **A8:** a pre-registered **learning-rate probe**: 3 × 30 steps at {1e-5, 2e-5, 5e-5}, chosen on validation with a fixed rule, losers reported. It also states what is deliberately **not** tuned and why: best-of-many noisy short runs is itself overfitting.

**Tuned:** data difficulty (pilot), learning rate (probe), β (required sweep). **Fixed by argument:** algorithm, G, batch, LoRA rank, clip, loss, temperature, completion length.

**USER_ACTIONS Step 17** now runs pilot → LR probe → the two β runs with `--learning-rate $BEST_LR`.

---

## First run on the user's machine (2026-10-19)

**Result**: `build_seed_tasks.py` wrote 16 tasks; `paygym validate tasks/` → `16 tasks | tier1=3 tier2=9 tier3=4 | traps=4 twins=4 | OK` (every hand check matched the reference). `pytest` → **205 passed, 2 failed**. Both failures were test bugs; no product bug was found:

1. `test_rubric_reward_is_the_paygym_total_and_components_are_metrics`: verifiers 0.2.1's `MultiTurnEnv.__init__` calls `add_rubric(MultiTurnMonitorRubric())`, so `env.rubric` becomes `RubricGroup([paygym rubric, monitor])` and `.funcs` on the group is empty. Read from the installed source: the monitor adds only `num_turns` at weight 0, so **the reward is unchanged**. The test now uses the group API (`_get_reward_func_names / _weights / _funcs`) and also asserts that `paygym_reward` is the only weighted function.
2. `test_no_ground_truth_in_any_response`: a false "leak" of `GEN-§9.2`. The test's exclusion of rule text already in the prompt compared against `json.dumps(prompt)`, which escapes `§` to `§`, so clause ids that are in the rule book shown to every agent looked hidden. It now compares against raw prompt text.

**Checklist**: P01.1, P01.2, P01.4, P01.5 (validate) and P02.5 are now confirmed by a real run.

**Re-run after the two test fixes (2026-10-19)**: `uv run pytest -q` → **207 passed** on the user's machine. This covers rule set, reference, tasks, generator, parser and tools, rubric + baseline floors, judge (offline), environment, eval harness, dashboard and sandbox (incl. the leak fuzz and parity tests).

---

## Step 6 run: generator + audits (2026-10-19)

**Generated** (user's machine): eval 109 tasks {T1 20, T2 70, T3 19}; heldout 109 {18, 70, 21}; val 44 {12, 24, 8}; train 251 {0, 180, 71}. `paygym validate` over all files: **529 tasks**, tier1=53 tier2=353 tier3=123, traps = twins = 123, OK.

**First audit run caught two problems in the audit itself:**
1. **Literal-leak false positive** on train `gen-0000060`: `employee_social_insurance` 480.00 rendered as "480,00" matched *inside* the YTD input "22.480,00" (dot_comma locale). The value was not in the prompt. **Fix:** number-boundary regex (`(?<![\d.,])…(?![\d])`); regression test `test_literal_leak_check_matches_whole_numbers_only`.
2. **The classifier collapsed to the majority class** (acc 0.7172 vs majority 0.7171), so it could not detect anything. **Fix:** `class_weight="balanced"` and judge by balanced accuracy vs chance (1/#labels), not raw accuracy vs majority.

**Re-run** (`pytest tests/test_generator.py` 18 passed):

| Split | Literal leaks | Balanced acc vs chance | Exact / near dups |
|---|---|---|---|
| eval | 0 | 0.2019 vs 0.20 (no signal) | 0 / 0 |
| train | 0 | 0.3204 vs 0.20 (+0.12) | 0 / 0 |

**Train lift reviewed by hand**, from the top n-grams per label in `results/audit/train.json`:
- **Genuine evidence (expected; this *is* the trap):** `NO_APPLICABLE_TABLE` → 2027 / 2024 / 2020 (period outside every table); `UNSUPPORTED_CURRENCY` → jpy, gbp.
- **Not leakage:** `MISSING_INPUT` → names / employee IDs ("greta", "9099"). Each appears in the trap's determined twin too (greta: 3 trap, 6 ANSWER; 9099: 1 / 1), so this is the CV memorising 16 examples, not a cue a model could use. `CONFLICTING_RECORDS` → "currency not stated" (paraphrase text), which appears in 5 CONFLICTING, 5 ANSWER and 2 MISSING prompts, so it does not determine the label.
- **Conclusion:** no template wording gives away the label; the eval split's classifier is at chance. This goes in EVAL_REPORT as "what the leakage check caught" (one audit false positive, one degenerate classifier, both fixed).
