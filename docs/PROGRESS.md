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

---

## Step 7: CI (2026-10-19)

- Repo: https://github.com/dibya0/AIGYM (public). First push `0ca29f4`.
- The brief PDF is excluded from git (`*.docx.pdf` in `.gitignore`): it is Niural's document, not ours to republish.
- GitHub Actions `ci` run [39207551122](https://github.com/dibya0/AIGYM/actions/runs/39207551122): **success**. All steps green: `uv sync --extra cpu --locked` (the lockfile is consistent), `paygym validate` over every taskset, `pytest`. So a clean checkout on a fresh Ubuntu runner installs and passes, an early check for §9 #1 (clean-clone setup).
- Checklist: P01.5 ☑.

---

## Step 8: RL smoke test on the RTX 5070 Ti (2026-10-19)

- **Driver:** 595.91.07 open kernel module, CUDA 13.2, kernel 7.0.0-38. `check_gpu.py`: torch 2.13.0+cu129, sm_120, 15.5 GiB, bf16 OK, matmul OK. The driver install ended the desktop session (display stack restart); the shell profiles were checked and are intact.
- **Run:** `--reward smoke` (format-only), 20 tasks, 10 steps, G = 4, 2 prompts/step, β = 0.04. Completed in 298 s (**≈ 24 s/step** for 8 completions, HF generation, no vLLM).
- **Logged per step, as required:** `kl` (0 at step 1, since the policy equals the reference, then rising to 0.0015: the reference loads and KL is measured), `entropy` (0.38–0.96), completion length (mean 183–276, clipped ratio up to 0.25 at the 384-token cap), `frac_reward_zero_std` (0–0.5), `reward`. Files: `metrics.csv`, `validation.csv`, `val_samples.jsonl`, `config.json`, `final_adapter/`.
- **The step-0 validation is an early pilot signal** (real rubric, greedy, 44 val tasks): base Qwen-0.5B scores **−0.15** overall: Tier 2 **0.09** (near-zero exact net pay), Tier 3 **−0.875** (it answers almost every trap). This is consistent with the pre-registered expectation that the training tasks will need the `easy`/`easier` preset (A4), and it means the main thing RL can learn is when to refuse. The refusal-collapse monitor (twin refusal rate) is what guards that.
- **Fix found by the smoke run:** TRL's default linear LR decay (2e-5 → 2e-6 in the log). Changed to a constant LR and logged as pre-registration amendment A9 (before any real training).
- Checklist: P07.4 ◐ (KL per step shown; real runs pending). Anti-goal "training that didn't finish" de-risked.

---

## Steps 9–11 checks + free-quota protection (2026-10-19)

- **User run:** `pytest` on parser/tools, rubric, judge, environment → **124 passed**. Gemini `/models` list pasted (Gemini 2.5/3.x/3.5–3.8 Flash, 3.1 Pro preview, gemini-4-argon, Gemma 4).
- **Groq:** the user's first sign-up page asked for a $5 card payment (most likely xAI's *Grok*, console.x.ai); the free Groq key was obtained without a card.
- **`.env` hygiene:** a pasted `curl` example containing the Gemini key, and unquoted values with spaces, broke `--env-file` parsing (GROQ_API_KEY was not loaded). Cleaned (backup in the session scratchpad); `SANDBOX_SECRET` generated. `.env` was never committed. The key was printed into the session once, so the user was advised to rotate it.
- **User requirement: do not exhaust any free quota.** `--max-cost` is in list-price dollars, which never protects a free quota, so I added:
  - `paygym/eval/budget.py`: a daily per-model **request ledger** (file-locked JSON, US-Pacific day). Before each call it reserves (1 request single-turn, `max_turns` in tool mode), and after the call it settles the actual turns. Defaults Gemini 120/day, Groq 400/day; `--daily-request-cap` / `PAYGYM_DAILY_CAP`; local and baselines uncapped.
  - Runner: stops before the call that would exceed the cap (`aborted_budget`, exit 6), with no wasted call. It also refuses to start a rollout if the judge budget could not judge it. Resume continues the next day.
  - Judge: counts against its own model's ledger. The sandbox opts out (`ledger=False`; it budgets per IP).
  - Tests: `test_daily_request_budget_stops_cleanly_and_resume_continues`, `test_request_ledger_counts_across_instances_and_settles_actual_use`; `tests/conftest.py` redirects the ledger to tmp so tests never touch the real one. Full suite **210 passed** locally.
  - `scripts/probe_models.py`: one ~10-token request per candidate model, to find which listed models really have free quota.
  - `scripts/sweep.sh`: Gemini single-turn only; Groq single + tool mode; a budget stop moves on to the next model instead of aborting the sweep.
  - Track C large model changed from Gemini to Groq `gpt-oss-120b` (S4 is ≈ 5 requests per rollout), so the brief's question "does scaffold matter more than model choice" is still answered.
- Docs: USER_ACTIONS Steps 11/15/20, TRADEOFFS #8.

**Model probe (2026-10-19, 5 requests):** `gemini-3.8-flash` OK (21.9 s: a reasoning model), `groq/openai/gpt-oss-120b` OK (0.4 s). `gemini-3.1-pro-preview` and `gemini-4-argon` → **429: listed, but no free quota** on this key. `gemma-4-31b-it` → 500 (to retry). Both OK replies were empty because the probe's 16-token cap was consumed by hidden reasoning tokens. The probe now uses 512 and reports reasoning tokens; the eval's 4096 cap is unaffected. **Decision:** the frontier config is `gemini/gemini-3.8-flash` (the strongest Gemini this free key serves; stated as such in EVAL_REPORT, not called "Pro"). `sweep.sh` default updated. Judge model: chosen after probing the lite/Gemma models, which have separate quota buckets.

**Judge model (2026-10-19, 3 more probe requests):** `gemini-3.1-flash-lite` OK 1.5 s, `gemini-3.5-flash-lite` OK 1.3 s, `gemma-4-31b-it` 500 again (dropped). **Decision:** the judge is `gemini-3.5-flash-lite`, a pinned id rather than a `-latest` alias, so it cannot change between runs. It is in a separate free-quota bucket from the eval model, and is a smaller sibling model judging a checklist of verifiable criteria; its reliability is measured anyway (3-repeat disagreement + 15 hand labels).

---

## Step 12: verifiers smoke eval on Groq, and two provider bugs (2026-10-19)

**User run** (verifiers' own `evaluate_sync`, 5 tasks × single + tool mode, Groq gpt-oss-120b): both loops printed "OK", but **every rollout was aborted with reward 0**. Two causes:

1. **`service_tier` validation (blocking, all rollouts).** `1 validation error for ChatCompletion / service_tier: Input should be 'auto', 'default', 'flex', 'scale', 'priority' or 'fast' [input_value='on_demand']`.
   - **Root cause:** read in the installed source. `verifiers/utils/client_utils.py::post_chat_completion_with_routed_experts_sidecar` calls `ChatCompletion.model_validate_json`, and openai 3.33's `ChatCompletion.service_tier` is a closed `Literal`. Groq returns `"on_demand"`. verifiers' v1 stack already widens this field (`verifiers/v1/dialects/chat.py`); the pinned v0 path does not.
   - **Fix:** `paygym/compat.py` wraps the response-stripping step to blank an unknown `service_tier` before validation (only that field, only when unknown). It is applied when `paygym.environment` is imported, so it covers the eval runner, verifiers' own runner and the trainer.
   - **Guard:** `test_groq_service_tier_is_accepted`.
   - **Why not upgrade verifiers:** 0.3.0+ removed the v0 API the brief specifies (TRADEOFFS #7).
2. **Groq free-tier TPM (1 of 10 rollouts).** `Limit 8000, Used 6659, Requested 6533`. One single-turn rollout is ~3–6.5k tokens, so even concurrency 2 overruns the per-minute window.
   - **Fix:** a `TokenLimiter` in the runner, a sliding 60 s window at 90% of the provider TPM (Groq 8000). Each rollout reserves an estimate and is corrected to its real usage. A `--tpm` override was added.
   - **Fix:** the client's SDK-level `max_retries` was raised from 0 to `--max-retries`, so each request, including inner turns of a tool rollout, honours the provider's `retry-after` instead of failing the whole rollout.
   - **Guard:** `test_token_limiter_waits_for_the_window`.
   - **Consequence:** the Groq single-turn eval (≈ 330 rollouts) paces itself to ~1–2 rollouts/min, so it is an overnight run. Planned for in the sweep.
- **Test regression caught during the fix:** the existing harness tests' fake rollouts report 1M tokens each, so the new limiter (correctly) made them wait 60 s per rollout and the suite hung. Fixed by passing `--tpm 0` in those tests. Full suite **212 passed**.
- **Lesson:** "OK" from a runner is not evidence. The re-run must show non-zero rewards and no `Aborted rollout` lines; the eval harness already records `status=error` separately rather than as 0.
- `EDGE_CASES.md` now keeps a running list of edge cases hit in real runs, for the final top-5 selection.

**Step 12 re-run (2026-10-19): `service_tier` fixed, a third provider incompatibility found in tool mode.** All 5 tool rollouts failed with `400 'messages.2': property 'reasoning_content' is unsupported`.
- **Root cause:** when replaying earlier assistant turns, `verifiers/clients/openai_chat_completions_client.py` (line ~234) attaches `reasoning_content`, the model's hidden reasoning, to each assistant message. Groq rejects the field, so every tool rollout failed at its second request.
- **Fix:** `paygym.compat` also wraps the chat client's request call and drops `reasoning_content` from outgoing *assistant* messages, without mutating the caller's object. The model still sees its visible replies and tool calls. Hidden reasoning is not scored, and no evaluated model needs it replayed.
- **Guard:** `test_replayed_assistant_reasoning_is_not_sent`. Suite **213 passed**.
- **Lesson:** single-turn success says nothing about multi-turn. The provider contract differs on turn 2.

---

## Free-tier limits from the user's dashboards → eval redesign (2026-10-19)

**Step 12, 3rd run:** tool mode on Groq → `413 Request too large … TPM: Limit 8000, Requested 8226`. Groq counts input + `max_tokens` against the per-minute window *per request*, and a multi-turn tool request is larger than the whole window. No amount of waiting fixes it.

**The user's limit pages** (no requests used):

| Model | Free limit |
|---|---|
| gemini-3.8-flash | 5 RPM, **20 RPD**, 250K TPM |
| gemini-3.5-flash-lite, 3.1-flash-lite | 15 RPM, 500 RPD each |
| gemma-4-31b-it | 30 RPM, 14.4K RPD, 16K TPM |
| groq gpt-oss-120b (also 20b, qwen3.8-27b) | 30 RPM, 1K RPD, **8K TPM, 200K TPD** |

**What was wrong in my earlier plan:** default caps of Gemini 120/day and Groq 400/day were guesses. The real Gemini 3.8 Flash limit is 20/day, so the first sweep would have exhausted it in minutes, and the tokens-per-day limit was not counted at all. Fixed by replacing guesses with the measured numbers.

**Changes:**
- `paygym/eval/budget.py`:
  - `FREE_TIER_LIMITS` per model, from the dashboards; caps = **75%** of each (`CAP_FRACTION`), so the user keeps a quarter.
  - The ledger now counts **requests and tokens**, and refuses a call if either daily cap would be exceeded.
  - Unknown hosted models get the strictest known limits.
  - Pacing (RPM, TPM) comes from the same table.
- Runner:
  - per-request `max_tokens` is clamped so input + max_tokens fits the provider's TPM window (the 413 cause);
  - a prompt that cannot fit is recorded as an error, not sent;
  - `--ids` runs a fixed task subset.
- Judge: pinned to **gemini-3.1-flash-lite** (own 500/day bucket, separate from both eval models) and paced to its RPM.
- **core20 subset** (`scripts/make_core_subset.py` → `tasks/subsets/eval_core20.txt`):
  - composition: 4 retrieval, 6 payslips, 5 traps + their 5 twins;
  - a fixed-seed stratified pick, chosen before any model was scored;
  - stored as **ids**, because a first version copied the tasks into a second JSONL and `paygym validate tasks/` (correctly) failed with 20 duplicate ids;
  - leaderboard: subset runs are grouped as `subset:eval_core20`, and every full-set run gets a **subset view** on the same 20 tasks, so the scarce models are compared paired.
- **Model allocation:**
  - Gemini 3.5 Flash-Lite: full eval + tool mode on core20 + Track C comparator;
  - Gemini 3.8 Flash: core20, ~4 days at 15/day;
  - Groq gpt-oss-120b: core20 single-turn, ~3 days at 150K tokens/day;
  - local Qwen: everything else, unlimited.
- **Tests:**
  - new: `test_caps_come_from_the_published_free_limits_with_headroom`, `test_ids_subset_runs_exactly_those_tasks`, `test_subset_run_is_compared_with_subset_views_of_full_runs`;
  - harness tests now set their own limits, because their fake 1M-token rollouts would (correctly) trip the real Groq token cap.
  - Suite **216 passed**.
- Docs: USER_ACTIONS Steps 12 / 15 / 20, TRADEOFFS #8.

**Step 12, 4th run (2026-10-19):**
- **Single-turn on Groq gpt-oss-120b: ✅ `errors: 0`, rewards `[0, 0, 0, 1.0, 0.8]`.** The verifiers environment runs end to end through verifiers' own runner on a real provider, and the rewards are non-degenerate. It took 2 min 41 s for 5 rollouts (≈ 32 s each), as Groq's 8K TPM paced it via `retry-after`.
- **Tool mode on Gemini 3.5 Flash-Lite: ❌ every rollout 400** `Function call is missing a thought_signature in functionCall parts … position 2`.
  - **Root cause:** Gemini 3.x returns an opaque `thought_signature` per function call (`tool_calls[i].extra_content.google.thought_signature`) and requires it back on the next turn. verifiers 0.2.1 has no reference to `extra_content` (grep of `verifiers/clients`); it rebuilds tool calls as its own `ToolCall` and drops the field.
  - **Fix:** `paygym.compat` remembers each signature by tool-call id when a response arrives and re-attaches it to that call when the conversation is replayed, as Google's docs specify. Nothing is invented: a call without a known signature is sent unchanged. The store is bounded.
  - **Guard:** `test_gemini_thought_signatures_are_replayed`. Suite **217 passed**.
- **Running count:** four provider incompatibilities in the pinned verifiers v0 client, three on Groq and one on Gemini, all fixed in one documented shim (`paygym/compat.py`) with a test each. This is the price of pinning v0 for spec fidelity (TRADEOFFS #7), and it is the strongest evidence in the project for "test against the real provider, on turn 2".

**Step 12, 5th run: tool mode on Gemini 3.5 Flash-Lite works (2026-10-19).** **4/5 rollouts OK** (the `thought_signature` fix holds). Rewards `[0, 1.0, 0, 0, 0]`; **tool calls per rollout `[12, 10, 16, 17, 8]`**, so the model really uses the tools.
- **The 1 error:** `429 … GenerateRequestsPerMinutePerProjectPerModel-FreeTier, limit 15 … retry in 53s`.
  - **Root cause:** a tool rollout makes ~8 requests back to back inside verifiers; a per-rollout limiter cannot hold a per-minute quota.
  - **Root cause:** Gemini states the delay in the error *body*, not a `Retry-After` header, so the SDK's short backoff gave up.
- **Fix (`paygym.compat`):**
  - every outgoing request is paced per model at the free-tier RPM from `paygym.eval.budget`. This also applies when verifiers' own runner is used. The runner hands its RPM to the shim instead of pacing whole rollouts, to avoid a double wait;
  - a 429 that names "retry in Ns" is waited out and retried (≤ 3 times, ≤ 90 s each).
- **Guard:** `test_requests_are_paced_per_model_and_named_retry_delays_honoured`. Suite **218 passed**.
- **Step 12 status: ✅.** Both modes run through verifiers' own runner on real providers (single-turn: Groq, 0 errors; tool mode: Gemini, signature fixed, the remaining failure mode now handled). Not re-run, to save Flash-Lite quota; the sweep's first tool-mode run (Step 15) exercises the pacing, and the runner records any error as `status=error`, never as 0.

---

## Steps 13–14: fidelity worksheet + eval harness on real providers (2026-10-19)

**Step 13:** `fidelity_sample.py` wrote `docs/FIDELITY_AUDIT.md` with 10 eval tasks: 2005-twin, 2000, 2007, 2002, 2009, 2015, 2003, 2011, 2005-trap, 2004-trap.

**Step 14, user run:** `test_eval_harness.py` 17 passed.
- **Groq smoke** (`--limit 2`, single-turn): completed, 2/2 ok, 0 errors. 9.1K input / 3.0K output tokens; mean latency 4.2 s. Wall clock 63 s: TPM pacing works, no 429/413.
- **Gemini Flash-Lite smoke** (tool mode): completed, 2/2 ok, 0 errors. **11 tool calls per rollout**; 75K input tokens for 2 rollouts (≈ 37K each, because tool results accumulate across turns); mean latency 46 s. Per-request pacing works: no 429.
- **Resume:** the second baseline run printed `327 already done, 0 to run`.
- **Ledger** recorded requests and tokens per model; the early probe entries are in the old int format and are read correctly.

**Reading the transcripts (not just the summaries) found two problems:**
1. **Transcripts stored messages as Python repr strings.** `json.dumps(record, default=str)` turned verifiers' pydantic message objects into `"role='assistant' content=None reasoning_content=…"`, which the transcript viewer and failure analysis cannot parse. Scoring was unaffected: it happens on the objects before writing. **Fix:** `_jsonable()` (recursive `model_dump`). Guard: `test_transcript_stores_messages_as_json_not_repr`. The two smoke runs predate the fix; they are smoke only and are not used in any report.
2. **One Groq rollout truncated at 1,906 output tokens** (`is_truncated`, gate `unparseable`). gpt-oss spent its reply budget on hidden reasoning (default *medium*), and the budget is bounded by the 8K TPM window. That is a limit of our setup, not a model error.
   - **Fix:** gpt-oss on Groq runs with `reasoning_effort="low"`, recorded in `config.json` → `sampling` and overridable with `--reasoning-effort`.
   - **Fix:** the prompt-token estimate was recalibrated from the measured 3.7 chars/token (was 3.2, which over-reserved and shrank the reply budget).
   - Guard: `test_gpt_oss_on_groq_uses_low_reasoning_effort`.
   - EVAL_REPORT will state that gpt-oss ran at low reasoning effort because of the free tier's TPM.
- **Not a bug, noted:** single-turn rollouts report `stop_condition=max_turns_reached`. That is verifiers' label for a single-turn env finishing its one turn; tool mode shows `no_tools_called` (the model answered).
- Suite **220 passed**.

**Step 13 result: fidelity audit 0 / 50 divergences** (`docs/FIDELITY_AUDIT.md`).
- **Method:** Part 1 was hand-derived from `RULESET.md` prose before Part 2 was opened, using a per-task calculator script written from the clauses (in the session scratchpad, not the reference code).
- **Result:** all 48 payslip lines matched to the exact minor unit, and both trap decisions matched (reason code, clause, named input).
- **Gaps stated in the doc:**
  - rules this sample did not exercise: KES non-resident, exhausted annual ceiling, out-of-period salary change, table/currency traps, reason precedence;
  - one author wrote the rule book, the reference and the check, which is why the user's review of the working is the independent check (§C);
  - the worksheet shows normalised inputs. Improvement for next time: print the raw prompt fields.

---

## Sweep resized to ~1 day (2026-10-19, user request: "3–4 days is too much")

- The user interrupted the first sweep after the baselines and part of Flash-Lite. Resume keeps every finished rollout.
- **Why it took days:** Gemini 3.8 Flash is limited to 20 requests/day by Google, and core20 × 3 = 60 requests.
- **Older models do not help:** the user's dashboard shows Gemini 2.5 / 3 / 3.6 / 3.7 Flash at the same 20/day. Only the Flash-Lite models (500/day) and Gemma 4 (14.4K/day, which returned 500 twice in the probe) are larger.
- **Change:**
  - **nested subsets** core6 ⊂ core10 ⊂ core20, the same fixed stratified order, every trap with its twin; core20 unchanged;
  - Gemini 3.8 Flash on **core6** (18 requests, one day);
  - Groq on **core10** (~165K tokens, one day);
  - Flash-Lite tool mode on core10;
  - `CAP_FRACTION` 0.75 → **0.9** (user chose speed; 10% of each quota stays untouched).
- Leaderboard subset views now also map a subset run onto smaller subsets (core10 → core6), so every scarce model is compared paired with every other.
- `scripts/sweep.sh` was replaced atomically (write + `mv`), so a running bash would not read a half-edited script.
- **Cost, stated for EVAL_REPORT:** Gemini 3.8 Flash's numbers rest on 6 tasks × 3 rollouts. That is a spot-check with a wide CI, not a leaderboard-grade estimate. The frontier-lab config with full coverage is Gemini 3.5 Flash-Lite.
- **Key point for the RL story:** the before/after evidence is local Qwen-0.5B (unlimited, $0); it needs no hosted quota, so it runs in parallel on the GPU now.
- Suite 220 passed.
- **Pre-flight on `docker-compose.yml` before the first local run:**
  - `--max-model-len` 8192 → 32768 (Qwen2.5 native). Tool-mode rollouts reach ~37K tokens (Step 14 measurement), so local tool mode would have failed on context length.
  - Added `--enable-auto-tool-choice --tool-call-parser hermes`. Without them vLLM rejects every request that carries `tools`, so local tool mode and Track C S2–S4 could not have run at all.
- **Same day, further resize ("can it finish today?"):** hosted tool mode moved from 3.5 Flash-Lite core10 (~240 requests, which spilled into tomorrow) to **3.1 Flash-Lite core6** (~144 requests). That model's 500/day quota was used only by the judge (~200 today). Gemini 3.8 Flash runs with `--daily-request-cap 19` (18 rollouts + the 1 probe request already spent = 19 of Google's 20).
  - **Brief check:** it requires ≥ 3 configs, ≥ 3 rollouts per task, and ≥ 100 generated instances with a non-degenerate distribution. It does not fix a per-model task count, so smaller hosted subsets keep every requirement. The full 109-task coverage comes from Gemini 3.5 Flash-Lite, local Qwen 3B / 0.5B and the baselines.
  - **Cost, stated for EVAL_REPORT:** in that one run the judge (3.1 Flash-Lite) scores its own model's trap explanations (1 trap × 3 rollouts), a self-preference risk; the judge's weight is 0.2 of a trap's score and its reliability is measured separately.

---

## Minimum-threshold plan + two runner bugs from the first pilot attempt (2026-10-19)

**User request:** "just add the minimum no. of thresholds the document asked, so we can showcase that it works". Every minimum was re-read from the brief text (pdftotext). The table is at the top of USER_ACTIONS.
- **Judge reliability:** the brief says 3 repeats **or** 15 hand labels (p.9). Now 3 repeats only; hand labels are optional.
- **RL** (p.12: "a working loop on a 0.5B model over 30 training tasks"): 30 train tasks, 60 steps per β, G = 8, validation and checkpoints every 20 steps. The LR probe is cancelled. Logged as pre-registration amendment **A10, before any training run**.
- **Track C** (p.14: model fixed, scaffold varied): all local. Qwen-3B × S0–S4, with Qwen-0.5B at S0/S4 as the matched-scaffold comparison model; no hosted quota. `track_c.py --frontier` became `--compare` (default local Qwen-0.5B).
- **Failure analysis:** 5 transcripts (p.16: 5–10).

**First pilot attempt (user run):**
- **Docker:** `permission denied … docker.sock`. The user is not in the `docker` group; fix in Step 17.0 (`usermod -aG docker`).
- **Runner bug 1:** the TPM guard I added earlier today ("input + max_tokens must fit the provider's per-minute window") rejected every request with `--max-tokens < 512`, including local models with no TPM limit. So all 400 pilot rollouts errored with "prompt too large … at 0 TPM". **Fix:** it applies only when a TPM limit exists and the *clamp* (not the user's own `--max-tokens`) leaves too little room.
- **Runner bug 2:** that error path skipped the consecutive-error counter, so a run with **0/400 successful rollouts reported `completed`**, the "silently fails" pattern the brief warns about. **Fix:** every error path counts; a non-baseline run with zero successes is never `completed` (status `unavailable`, exit 3).
- `pilot_report.py` now explains a run with no successes instead of `ZeroDivisionError`.
- **Guards:** `test_small_max_tokens_is_allowed_without_a_tpm_limit`, `test_a_run_where_nothing_succeeded_is_never_completed`. Suite **222 passed**.

**Local model server (2026-10-19):** the first `docker compose --profile gpu up llm` failed with `could not select device driver "nvidia" with capabilities: [[gpu]]`.
- **Cause:** the NVIDIA Container Toolkit package was gone (likely removed with the old NVIDIA packages during the driver reinstall). Docker's `daemon.json` still named `nvidia-container-runtime`, but `nvidia-ctk` was missing.
- **Also in the way:**
  - a broken third-party PPA (`thopiekar/openrgb`, 404 on noble) made `apt-get update && install` stop before installing;
  - the user was not in the `docker` group (`permission denied … docker.sock`);
  - a uv-installer line in `~/.bashrc` / `~/.profile` sourced a path under the VS Code snap `$HOME`, which errored in every new shell. Commented out with backups; `PATH` already covers uv.
- **Fixed:** removed the PPA, installed `nvidia-container-toolkit` 1.20.1, ran `nvidia-ctk runtime configure --runtime=docker`, restarted Docker, `usermod -aG docker`.
- **Result:** **vLLM 0.30.0 serves Qwen2.5-0.5B on the RTX 5070 Ti (sm_120)**, startup ≈ 3 min including the model download, `/v1/models` 200. This settles the plan's open question of whether the pinned vLLM supports Blackwell; no HF-generate fallback is needed for serving. Settings: 32K context, hermes tool parser.

---

## Step 17 pilot (2026-10-19): base 0.5B gets 0 % exact payslips on every preset

- **Pilots** (30 train tasks × 4 samples; local vLLM): default, easy, easier all at **Tier-2 exact 0 %**, all-identical groups 70–80 %, mean reward −0.08 to −0.14. `pilot_report.py` says "too hard" for all three.
- **Diagnosis from transcripts (not just the summary):**
  - **not** truncation (5/120 truncated, mean 216 output tokens);
  - wrong arithmetic (`wrong_net_capped` 56/120);
  - broken JSON such as `"rate": 8%` (28/120 unparseable);
  - traps answered (20/120);
  - nested or non-numeric line values.
- **Decision, logged as pre-registration amendment A11 before training:** A4's rule assumed some preset reaches a 20–60 % pass rate; none does with a fixed 0.5B. So we pick the preset with the most within-group reward spread, which is **`easy`** (30 % of G = 4 groups; trap refusal 44 %; valid JSON 76 %).
- **Stated in advance:** RL is expected to improve format and refuse/compute decisions, not exact arithmetic. The documented fallback is Qwen2.5-1.5B (brief band 0.5–2B), only with the user's go-ahead.
- New train files `train_easy.jsonl` / `train_easier.jsonl` validate: `paygym validate tasks/` → **1031 tasks OK** (ids prefixed per preset, so no collisions).
