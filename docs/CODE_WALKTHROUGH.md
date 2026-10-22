# PayGym: code walkthrough, step by step

*Written 2026-10-20. This is the companion to [WALKTHROUGH.md](WALKTHROUGH.md). That file checks every brief requirement and lists the results. This one explains **how the code works**, in the order it was built, with links to the exact functions. Every number in the worked example below was produced by running the code (command in §0.2).*

**How to read this.** Part 0 follows one real task through the whole system end to end. That is the fastest way to see how the pieces connect. Parts 1–10 then go through the code in the order we built it (Steps 1–24 of the plan). Each step covers:
- **Why:** the brief requirement or problem it solves;
- **Files:** where the code is;
- **How it works:** the important 



















functions, line by line where it matters;
- **What went wrong:** the bugs we hit, and how they were fixed (full log in [PROGRESS.md](PROGRESS.md));
- **See it yourself:** a command you can run.

---

## Part 0: the big picture

### 0.1 The pipeline in one picture

```
ruleset/v1.0/RULESET.md   (prose rule book, clause ids like GEN-§9.2: the AUTHORITY)
ruleset/v1.0/rules.yaml   (the same rate tables as data)
        │  paygym/ruleset.py loads both, fingerprints them
        ▼
paygym/reference/          the CALCULATOR: computes a payslip, or says "undetermined" + why
        │                  (every step cites its clause)
        ▼
paygym/generator.py        makes tasks from seeds: retrieval / payslip / trap + twin
paygym/truth.py            ground truth = calculator output (never an LLM)
paygym/schema.py           what a task looks like; paygym/validate.py checks every task
        │
        ▼
paygym/prompting.py        builds the exact text the model sees (one builder for everyone)
paygym/tools.py            4 tools for tool mode
paygym/parser.py           reads the model's JSON answer
paygym/rubric.py           SCORES the answer: the single scorer for everyone
paygym/environment.py      wraps all of the above as a verifiers environment: load_environment()
        │
        ├──► paygym/eval/runner.py     evaluation harness  → results/<model>/<run>/ (4 files)
        ├──► train/grpo_train.py       GRPO training (TRL)  → results/train/<run>/
        └──► paygym/sandbox/app.py     public API (Vercel)  → outside agents get scored
                    │
paygym/eval/leaderboard.py + paygym/dashboard/build.py  →  public/ (the website)
```

**The key idea.** There is **one** calculator, **one** prompt builder, **one** parser and **one** scorer. The eval, the trainer and the sandbox all import the same functions. That is why a score means the same thing everywhere (brief §10, and the parity test in `tests/test_sandbox.py`).

### 0.2 One task, end to end (real numbers)

Run this yourself (CPU only, a few seconds):

```bash
uv run python -c "
from paygym.generator import generate_one
from paygym.reference import compute_payslip
from paygym.rubric import score_answer
from paygym.baselines import BASELINES
for t in generate_one(2000005):
    print(t.id, t.ground_truth.kind)
    for b in ('always_abstain','naive_no_ceiling'):
        s = score_answer(t, BASELINES[b](t)); print('  ', b, round(s.total,3), s.gate)
"
```

Seed `2000005` is in the **eval** seed range. A seed is either a single task or a **trap + twin pair**, and this one is a pair.

**Step 1, generate.** [`generate_one(2000005)`](../paygym/generator.py#L318-L352) creates an employee:
- Greta Quayle, Valdoria (VAL), pay period May 2026;
- salary VLD 11,380/month, starting 7 May 2026;
- a meal allowance of 220 and a housing allowance of 320.

It then makes two versions:

| | **trap** `gen-2000005-trap` | **twin** `gen-2000005-twin` |
|---|---|---|
| What differs | the contract says a **different salary** from the HR record | the HR record and contract agree on salary; they disagree only on the **job title** |
| What the rules say | GEN-§9.2: two sources state different values for an input, no precedence, **undetermined** | GEN-§9.2: "a disagreement about … a job title does not make the payslip undetermined", **must compute** |
| Ground truth | refusal, `CONFLICTING_RECORDS`, input `monthly_salary` | a full payslip, net pay **7,189.99** |

The twin is what catches a model that refuses whenever documents disagree.

**Step 2, ground truth.** [`compute_payslip`](../paygym/reference/calculator.py#L259-L363) on the twin records every step with its clause:

| Step | Value | Clause(s) | How |
|---|---|---|---|
| earned_salary | 9,177.42 | GEN-§6.2, VAL-§1.1 | 11,380 × 25/31: employed 7–31 May = 25 of 31 calendar days |
| taxable_allowances | 390.00 | GEN-§7.2, §7.3 | meal 220 − the 2026 exemption 150 = 70, + housing 320 |
| non_taxable_allowances | 150.00 | GEN-§7.1, §7.2 | the exempt part of the meal allowance |
| contributory_earnings | 9,567.42 | GEN-§5.1 | earned + retro + taxable allowances |
| contribution_base | **6,000.00** | GEN-§5.2, VAL-§2.1 | **the ceiling binds**: min(9,567.42, 6,000) |
| employee_social_insurance | 480.00 | VAL-§2.2 | 8 % × 6,000 (not × 9,567: that is the naive mistake) |
| employer_social_insurance | 720.00 | GEN-§5.3 | 12 % × 6,000, reported but not deducted |
| employee_pension | 458.87 | VAL-§3.1 | 5 % × earned salary |
| taxable_income | 7,628.55 | VAL-§4.1 | earned + taxable allowances − pension − SI − 1,000 allowance |
| income_tax | 1,588.56 | GEN-§11.1, VAL-§4.2 | 10 % × 2,000 + 20 % × 3,000 + 30 % × 2,628.55 (full precision, then rounded) |
| gross_pay | 9,717.42 | GEN-§10.2 | sum of the 4 rounded lines |
| **net_pay** | **7,189.99** | GEN-§10.3 | 9,717.42 − 480 − 458.87 − 1,588.56 |

On the trap, the same function stops early in [`resolve_inputs`](../paygym/reference/calculator.py#L80-L114). Two sources give different `monthly_salary` values, so it returns `Undetermined("CONFLICTING_RECORDS", ("monthly_salary",))`.

**Step 3, prompt.** [`single_turn_messages`](../paygym/prompting.py#L69-L74) builds:
- the system prompt, which defines the JSON output contract;
- the relevant rule-book sections;
- the task text: three documents (an HR record as JSON, a payroll note in prose, a contract excerpt).

**Step 4, a model answers**, and **Step 5, scoring.** [`score_answer`](../paygym/rubric.py#L211-L219) gave these real scores:

| Agent | Trap | Twin |
|---|---|---|
| `always_abstain` (refuses with MISSING_INPUT) | **+0.3**: right decision, wrong reason code | **−1.0**: refused a payable payslip (`refused_determinable`) |
| `naive_no_ceiling` (ignores the ceiling, never refuses) | **−1.0**: computed a trap (`answered_trap`) | **+0.2**: lines partly right but net pay wrong, so capped (`wrong_net_capped`); the first wrong line is social insurance, clause VAL-§2.2 |

That is the whole gym in one example:
- the trap punishes guessing;
- the twin punishes over-refusing;
- the cap stops partial credit from rescuing a wrong net pay;
- the clause says exactly where the agent went wrong.

---

## Part 1: rule set and calculator (Steps 1–4)

### Step 1: project setup
- **Files:**
  - [pyproject.toml](../pyproject.toml): Python 3.12, `verifiers==0.2.1` pinned, extras `train` and `sandbox`, CLI entry `paygym = paygym.cli:main`;
  - [.env.example](../.env.example): key names only;
  - [docker-compose.yml](../docker-compose.yml): `llm` (vLLM, GPU), `sandbox`, `redis`, `dashboard`;
  - [.github/workflows/ci.yml](../.github/workflows/ci.yml): tests + validate on every push.
- **Why verifiers 0.2.1:** the brief's API (`load_environment`, `SingleTurnEnv`, `ToolEnv`, `Rubric`) is verifiers' v0 API. Version 0.3.0 removed it, so 0.2.1 is the last release that matches the brief exactly ([RESEARCH_NOTES.md](RESEARCH_NOTES.md)).
- **What went wrong:**
  - the GPU driver had no kernel module loaded;
  - Docker needed `usermod` and `sg docker`;
  - the NVIDIA container toolkit was missing;
  - broken `uv` lines in `.bashrc`.

  All are logged in PROGRESS.md.

### Step 2: the rule book in prose ([RULESET.md](../ruleset/v1.0/RULESET.md))
- **Why:** brief Phase 04, "the rule set is written out first, pinned, versioned". The prose is the authority, and code is a *claim* about it.
- **What's in it:**
  - three fictional jurisdictions: Valdoria (monthly ceiling), Kestrel Isles (annual cumulative ceiling, annualised tax, residency), Nordmark (whole-unit rounding, working-day proration);
  - general rules GEN-§1 … §11;
  - **GEN-§9, the 4 "undetermined" cases** (§9.1–§9.4) plus the precedence order (§9.5). The traps come from these.
- **Why fictional:** no model can answer from memory, so the gym measures rule-following, not recall.

### Step 3: the rate tables as data ([rules.yaml](../ruleset/v1.0/rules.yaml) + [ruleset.py](../paygym/ruleset.py))
- Every value has its clause next to it, e.g. `si_ceiling: {value: "6000.00", clause: VAL-§2.1}`.
- Numbers are **strings** turned into `Decimal`, never floats, because 0.1 + 0.2 ≠ 0.3 in float.
- [`load_ruleset`](../paygym/ruleset.py#L102-L111):
  - reads both files;
  - checks that the version matches;
  - computes a **fingerprint**: the SHA-256 of prose + YAML (line 110).

  The fingerprint goes into every result file. If anyone edits a rule, old and new results can't be silently compared.
- `tests/test_ruleset.py` fails if the YAML and the prose tables disagree.

### Step 4: the reference calculator ([paygym/reference/](../paygym/reference/))
The verifier. Ground truth comes from here and nowhere else.

- **[`trace.py`](../paygym/reference/trace.py#L36-L55), the `@cites` decorator.** Wrap a function with `@cites("GEN-§5.2")`. Each call then records `(step name, value, clauses)` into a `Trace`. That makes the calculation auditable: every number knows the rule behind it.
- **[`inputs.py`](../paygym/reference/inputs.py).** A `PayslipCase` is a jurisdiction, a pay period, and **several source documents** (`SourceRecord`), each of which may or may not state each input. Conflicts and missing inputs can be represented because sources are kept separate.
- **[`calculator.py`](../paygym/reference/calculator.py), read in this order:**
  1. [`resolve_inputs`](../paygym/reference/calculator.py#L80-L114) merges the sources:
     - for each input, collect what each source says;
     - none, but required → **missing**;
     - two different values → **conflicting**;
     - inputs the jurisdiction doesn't use are skipped, so a conflict in them doesn't matter;
     - then the **precedence order of GEN-§9.5** (lines 102–111): no rate table first, then unsupported currency, then missing, then conflicting.
  2. [`compute_payslip`](../paygym/reference/calculator.py#L259-L363) follows GEN-§3 in order:
     - FX conversion;
     - earned salary with proration and any mid-month change ([`_earned_salary`](../paygym/reference/calculator.py#L139-L165));
     - allowances;
     - contributory earnings;
     - **contribution base**, monthly cap (VAL/NRD) or annual cumulative cap using YTD (KES), lines 304–308;
     - social insurance;
     - pension;
     - income tax: monthly brackets (VAL/NRD) or annualised ÷ 12, or a flat non-resident rate (KES);
     - rounding.
  3. **Rounding** (lines 334–354): every line is rounded half-up to the minor unit (0.01, or 1 in Nordmark). `gross_pay` and `net_pay` are then the *sums of rounded lines* (GEN-§10.2/§10.3), so they always add up on the payslip. Intermediate steps use full precision (GEN-§1.3); that is why income tax is 1,588.56 in the example and not a figure from pre-rounded numbers.
  4. [`bracket_tax`](../paygym/reference/calculator.py#L216-L224) applies marginal bands: each rate only on the part inside its band.
- **Tests:**
  - [tests/test_reference.py](../tests/test_reference.py): hand-computed payslips, one per clause family;
  - [tests/test_reference_properties.py](../tests/test_reference_properties.py): Hypothesis property tests, e.g. net ≤ gross, contribution ≤ rate × ceiling, net never falls when gross rises.

---

## Part 2: tasks, generator and audits (Steps 5–7)

### Step 5: task schema + hand-checked seed tasks
- **[schema.py](../paygym/schema.py#L78-L116), `Task`:** the brief's fields `id, slice, difficulty, prompt, context_files, ground_truth, verifier, tags, schema_version`, plus our own: `case`, `lookup`, `twin_of`, `trap_reason`, `seed`, `ruleset_version`.
  - `ground_truth` is a **tagged union** (line 58) of three kinds:
    - `ValueTruth`: Tier 1, one number;
    - `PayslipTruth`: Tier 2, all 10 lines + tolerance;
    - `RefusalTruth`: Tier 3, reason code + clause.
  - [`_consistent`](../paygym/schema.py#L99-L116) rejects nonsense tasks:
    - the verifier must match the truth kind;
    - Tier 3 if and only if refusal;
    - every trap must record *why* it is a trap.
  - `extra="forbid"` + [`load_task`](../paygym/schema.py#L127-L137) + `MIGRATIONS` handle **schema drift**. A task written under a newer schema fails loudly instead of being half-read.
- **[truth.py](../paygym/truth.py):** ground truth = `compute_payslip(case)` turned into the schema type. One function, so stored truth can always be recomputed.
- **[validate.py](../paygym/validate.py#L59-L90)** (`uv run paygym validate tasks/`) checks, for every task:
  - the schema parses;
  - **stored truth == truth recomputed now**, so a hand-edited or stale answer is caught;
  - the hand-check values agree;
  - every trap has a twin and every twin is determinable;
  - ids are unique.
- **[scripts/build_seed_tasks.py](../scripts/build_seed_tasks.py) → `tasks/seed_v1.jsonl`:** 16 hand-written tasks (3 retrieval, 9 payslips, 4 traps + their 4 twins), each with a `hand_check` worked out from the prose.

### Step 6: the seeded generator ([generator.py](../paygym/generator.py))
- **Seeds:** [`SPLITS`](../paygym/generator.py#L30-L35) gives each split its own disjoint seed range: train 0+, val 500,000+, held-out 1,000,000+, eval 2,000,000+. A held-out task *cannot* be a training task.
- **One random stream per task:** `PCG64(seed)` (line 321). Task 2000005 is identical whether you generate 1 task or 500, which is what "deterministic, seed recorded" means.
- **[`Knobs`](../paygym/generator.py#L48-L64)**, the brief's difficulty knobs: ceiling binds, proration, salary change, retro pay, FX, allowances, split sources (more lookups), irrelevant context, date and number formats, annual salary.
- **[`_draft`](../paygym/generator.py#L120-L215)** builds a random *determinable* employee. Notice line 133–139: salary is chosen relative to the ceiling, so "ceiling binds" happens on purpose about half the time.
- **[`_trap_pair`](../paygym/generator.py#L241-L293)** copies the draft twice and mutates both:
  - MISSING_INPUT: drop a required input from every document. The twin drops an *unused* input instead, which must not block the payslip.
  - CONFLICTING_RECORDS: the contract states a different salary or start date. The twin's documents disagree only on job title.
  - NO_APPLICABLE_TABLE: shift the period to a year with no table (2027, or 2024).
  - UNSUPPORTED_CURRENCY: pay in GBP/JPY/CHF/SEK.
- **A guard** at [lines 347–351](../paygym/generator.py#L347-L351): if a mutation doesn't produce exactly the intended refusal, or the twin isn't payable, generation **crashes** rather than emitting a bad task.
- **Dedup:** [`generate`](../paygym/generator.py#L360-L376) skips a seed whose structured case repeats one already made.
- **Presets** [`KNOB_PRESETS`](../paygym/generator.py#L391-L399) (`easy`, `easier`) make *training* tasks easier for the 0.5B model. Eval and held-out keep full difficulty.
- **Rendering ([render.py](../paygym/render.py)):** the same case is shown as JSON records or contract prose, in several date and number formats. The format used is always stated in the prompt, so the task is never ambiguous.

### Step 6b: the audits ([paygym/audit/](../paygym/audit/))
- **[`literal_leaks`](../paygym/audit/leakage.py#L45-L65):** does the answer number appear in the prompt? It matches only whole numbers (the regex at line 62), after a bug where "480,00" matched inside "22.480,00".
- **[`classifier_leakage`](../paygym/audit/leakage.py#L68-L120):** a TF-IDF + logistic-regression model tries to predict answer vs refusal reason from the wording alone. `class_weight="balanced"` came after a bug: unweighted, it just predicted the majority class.
- **[dedup.py](../paygym/audit/dedup.py):** exact and near-duplicates (Jaccard over 5-word shingles). Trap/twin pairs are reported separately, since they are similar on purpose.
- **See it:** `uv run paygym audit tasks/generated/eval.jsonl`.

### Step 7: CI
[ci.yml](../.github/workflows/ci.yml) runs `pytest` + `paygym validate` on GitHub for every push.

---

## Part 3: training smoke test (Step 8)

We ran RL **early**, before the rubric existed, to make sure it would run on this GPU at all. [`smoke_reward`](../train/grpo_train.py#L51-L64) gives 1 point for a parseable JSON block. Its numbers are **not** results; it only proved that GPU, LoRA, KL logging and checkpoints work. Pre-registration amendment A9 (constant learning rate) came out of this ([RL_REPORT.md](RL_REPORT.md)).

---

## Part 4: the environment (Steps 9–12)

### Step 9a: the output parser ([parser.py](../paygym/parser.py))
The model must end with a ```` ```json ```` block holding `decision`, `reason_code`, `lines` and `explanation` (the contract is in [`SYSTEM_PROMPT`](../paygym/prompting.py#L15-L32)).

- **[`_extract_object`](../paygym/parser.py#L165-L199):**
  - strips `<think>` blocks;
  - takes the **last** fenced block;
  - if there is no fence, decodes complete top-level objects with `raw_decode` and keeps the last;
  - recognises truncation;
  - retries once without trailing commas.
- **Every failure has a name:** `no_json`, `truncated`, `invalid_json`, `bad_decision`, `missing_lines`, … It is never a crash.
- **[`parse_number`](../paygym/parser.py#L141-L162)** accepts `"1.000,50"`, `"VLD1234.50"` and `"8%"`. The rule is that whichever separator comes last is the decimal mark.
- **What went wrong:** the bare-JSON path used to take `rfind("{")`, which is the *nested* `lines` object. So every valid unfenced gpt-oss answer was marked unparseable (comment at lines 172–174).

### Step 9b: the tools ([tools.py](../paygym/tools.py))
Tool mode gets **only an employee id**. Every fact must come from these 4 tools (brief p.8):

| Tool | Returns |
|---|---|
| `get_employee_record(employee_id)` | each source document as stated, conflicts included |
| `lookup_rules(jurisdiction, year)` | the rule text + that year's rate table, or `null` + "no table" |
| `get_fx_rate(from, to, on_date)` | the rate only for a month-end date (FX-§1.1), or `null` |
| `calc(expression)` | exact decimal arithmetic |

- **`calc` never uses Python `eval`.** [`_eval`](../paygym/tools.py#L122-L137) walks the parsed expression tree and allows only numbers, `+ − × ÷`, `min/max/abs/round`. Anything else is an error, so a model can't run code through it.
- **Hidden argument `task_json`:** a trap and its twin share an employee id but have different documents. So each tool receives that rollout's task, injected by the environment and hidden from the model's tool schema.
- **Bad arguments** return `{"error": …, "code": "invalid_argument"}` so the model can recover. They are counted, never swallowed.

### Step 10: the rubric ([rubric.py](../paygym/rubric.py)), the most important file
Read the docstring (lines 1–65); it's the design document. Then the code:

- **Constants** (lines 77–88):
  - weights 0.70 net / 0.25 lines / 0.05 format;
  - wrong-net cap 0.25;
  - trap: correct reason 0.80, judge bonus 0.20, wrong reason 0.30, answered −1;
  - `UNPARSEABLE = −1`.
- **[`_score_payslip`](../paygym/rubric.py#L128-L164):**
  1. No object, or no valid decision → **−1** (`unparseable`, rubric 1.3/1.4).
  2. Each of the 10 lines is compared within one minor unit (`_within`).
  3. `first_wrong` = the first wrong line in computation order (`LINE_ORDER`). Its clause becomes the "driving clause", so a failure points at a rule.
  4. Raw total = 0.70 × net correct + 0.25 × share of lines correct + 0.05 × format.
  5. **The gates:**
     - refused a payable payslip → **−1**;
     - net wrong → capped at **0.25**.

     A plain weighted sum can't express a cap, which is why the total is computed here and not as a sum.
- **[`_score_trap`](../paygym/rubric.py#L167-L194):**
  - unparseable → −1;
  - answered → **−1**;
  - refused with the wrong code → 0.3;
  - right code → 0.8, + 0.2 × judge score if a judge is attached.
- **[`_score_value`](../paygym/rubric.py#L197-L208)** (Tier 1): exact value 1.0, wrong 0.05, refused or unparseable −1.
- **Every component returns `RewardResult(score, clauses, detail)`**, the clause-traceability requirement.

**Why it ended at version 1.4.** Each change closed an exploit **the trained policy actually found** (Part 7). The docstring's "Why v1.x" paragraphs tell the story with numbers.

**Adversarial baselines ([baselines.py](../paygym/baselines.py)):** five no-model strategies a cheating policy might find:
- format-only;
- always abstain;
- a constant answer;
- naive no-ceiling ([`_force_determinable`](../paygym/baselines.py#L83-L99) guesses past every gap: first source wins, nearest year's table, unknown currency treated as local);
- gross-as-net.

Each must stay under its [`FLOORS`](../paygym/baselines.py#L28-L34) value, enforced by `test_baseline_stays_under_its_floor`.

### Step 11: the LLM judge ([judge.py](../paygym/judge.py))
- **Used for one thing only:** whether a *correct* trap refusal's explanation is useful. Everything else is programmatic.
- **3 pass/fail criteria** derived from GEN-§9 ([`CRITERIA`](../paygym/judge.py#L37-L51)): names the input; says why the rules don't determine the payslip; is actionable for an operator. **Each is judged in its own call** (Harvey pattern). Score = criteria passed ÷ 3, so it's worth at most 0.2.
- **Pinned model** (`gemini-3.1-flash-lite`), temperature 0, **versioned prompt hash**.
- **Cache** keyed by (prompt hash, model, criterion, task, explanation), so the same answer always gets the same verdict.
- **A failure raises `JudgeError`**: recorded, never a silent 0.
- **Kept out of the RL reward** (cost, latency, and the risk of the policy learning to please the judge).
- **Reliability:** [judge_reliability.py](../paygym/judge_reliability.py) gives 3-repeat disagreement plus hand labels with Cohen's κ. *Still to run today.*

### Step 12: the verifiers environment ([environment.py](../paygym/environment.py))
- **[`load_environment`](../paygym/environment.py#L336-L370)** is the brief's required entry point:
  - loads tasks (generated split or a file);
  - [`build_rows`](../paygym/environment.py#L215-L224): prompt + `info.task_json` (ground truth stays in `info` and never enters the prompt);
  - builds the rubric;
  - returns `vf.SingleTurnEnv` or our `PaygymToolEnv`.
- **[`make_rubric`](../paygym/environment.py#L249-L302):** one reward function (`paygym_reward`, weight 1) = the gated total. The components and monitors (`refused`, `parse_failed`, `tool_errors`) are weight-0 metrics. The score is computed once per rollout and cached in `state`.
- **[`PaygymToolEnv`](../paygym/environment.py#L308-L330):**
  - adds the 4 tools with `task_json` hidden;
  - injects it in `update_tool_args`;
  - `tool_loop_detected` ends a rollout after 3 identical calls in a row.
- **[compat.py](../paygym/compat.py), four fixes for verifiers 0.2.1 on real providers**, all found in Step 12–14 smoke runs:
  1. Groq returns `service_tier="on_demand"`, which the OpenAI types reject. Fix: blank it.
  2. verifiers replays `reasoning_content` and Groq returns 400. Fix: strip it.
  3. Gemini needs its `thought_signature` sent back. Fix: remember it by tool-call id and re-attach.
  4. Free-tier per-minute limits. Fix: pace every request; obey the "retry in Ns" text in 429s.

---

## Part 5: fidelity audit (Step 13)

[FIDELITY_AUDIT.md](FIDELITY_AUDIT.md) hand-checks generated tasks against the prose (sampler: [scripts/fidelity_sample.py](../scripts/fidelity_sample.py)). The result: 10 tasks, 0 divergences in 50 lines and decisions compared. That is a loose bound, because 10 tasks don't exercise every rule. Two hand derivations are still for **you** to review.

---

## Part 6: evaluation (Steps 14–16)

### Step 14: the harness ([eval/runner.py](../paygym/eval/runner.py))
Command: `uv run python -m paygym.eval --model <provider>/<id> --rollouts 3 --seed 7 --max-cost 25`.

- **[providers.py](../paygym/eval/providers.py):** the model prefix chooses the endpoint: `gemini/`, `groq/`, `local/` (vLLM on :8000) or `baseline/` (no model).
- **[`EvalRun.__init__`](../paygym/eval/runner.py#L172-L227):**
  - builds the environment;
  - optionally keeps only a fixed id list (`--ids`, for the core subsets);
  - hashes the taskset;
  - sets pacing and the daily caps.
- **[`config`](../paygym/eval/runner.py#L229-L251):** everything needed to reproduce the run: model, sampling, seeds, taskset hash, rule-set fingerprint, rubric version, prompt hash, git sha, library versions.
- **[`_model_rollout`](../paygym/eval/runner.py#L316-L417), one rollout:**
  1. Reserve the requests and tokens in the **daily ledger** first; if the day's cap would be passed, stop cleanly (`aborted_budget`).
  2. `env.run_rollout(...)`: verifiers runs the prompt, tools and rubric.
  3. **Retry only infrastructure failures** (429, 5xx, timeouts), marking them `retried`. Model failures (bad JSON, loops) are *scored*, because they are what the gym measures.
  4. Two classification rules learned the hard way:
     - an **empty model reply** is the model's fault, so it is scored −1;
     - a **timeout with zero output** is the rate-limit queue's fault, so it is an error and retried.
  5. Add up the cost at list prices; stop new rollouts once `--max-cost` is hit (`aborted_cost`).
- **Resume:** [`load_done`](../paygym/eval/runner.py#L277-L286) reads `transcript.jsonl`, and [`run`](../paygym/eval/runner.py#L433-L478) skips every `(task, rollout)` already ok. A crash never pays twice. Resuming is **refused** if the model, taskset, rubric or prompt changed (lines 436–442).
- **[`finalise`](../paygym/eval/runner.py#L489-L558)** writes the 4 files the brief names:
  - `config.json`;
  - `transcript.jsonl`: every rollout with prompt, completion, reward, gate and clauses;
  - `scores.json`: summary, by tier, by component, gates, per task, twins;
  - `metrics.json`: status, tokens, list-price and actual cost, latency p50/p95, tool calls, stop conditions, parse-fail rate.
- **[budget.py](../paygym/eval/budget.py), the daily ledger:**
  - [`FREE_TIER_LIMITS`](../paygym/eval/budget.py#L33-L41) holds the limits copied from your dashboards;
  - caps at 90 %;
  - Groq tokens × 1.4 (Groq bills hidden reasoning tokens);
  - file-locked JSON keyed by US-Pacific date.

  The first version guessed 120/day; Gemini 3.8 Flash really allows 20.
- **[`rescore`](../paygym/eval/runner.py#L561-L626)** (`uv run paygym rescore`): re-scores saved completions under the current rubric with **no model calls and no API key**. That is how all runs moved to 1.4 for free. Correct trap refusals keep their recorded score, because it holds a judge verdict.
- **Tests:**
  - `test_cost_cap_aborts_cleanly_with_partial_results`;
  - `test_resume_does_not_pay_twice`;
  - `test_daily_request_budget_stops_cleanly_and_resume_continues`;
  - and more in [tests/test_eval_harness.py](../tests/test_eval_harness.py).

### Step 15: the sweep ([scripts/sweep.sh](../scripts/sweep.sh))
The header comment explains the budget maths per model. In summary:
- Flash-Lite on the full 109 tasks × 3;
- 3.8 Flash on core6 (20 requests/day);
- Groq on core10;
- local Qwen 0.5B and 3B, unlimited;
- 5 baselines.

**Core subsets** ([make_core_subset.py](../scripts/make_core_subset.py)) are nested (core6 ⊂ core10 ⊂ core20), fixed before any model was scored, and every trap comes with its twin.

**Statistics ([stats.py](../paygym/eval/stats.py)):**
- [`run_summary`](../paygym/eval/stats.py#L28-L54):
  - mean reward = the mean over tasks of each task's mean, so every task weighs the same;
  - rollout SD;
  - disagreement rate.
- [`paired_bootstrap`](../paygym/eval/stats.py#L66-L74): the difference between two models **on the same tasks**, resampled 2,000 times. If the 95 % interval contains 0, the gym **cannot tell them apart**, and we say so.
- **Weight sensitivity** ([sensitivity.py](../paygym/eval/sensitivity.py)): re-ranks the leaderboard under alternative weights. Kendall τ = 1.0 means the ranking didn't move.

### Step 16: leaderboard + dashboard
- **[leaderboard.py](../paygym/eval/leaderboard.py):**
  - [`is_leaderboard_run`](../paygym/eval/leaderboard.py#L27-L32) keeps only eval-split runs, so pilots and training runs are excluded (that was a bug once);
  - `subset_views` re-summarises every run on each subset it fully covers, so a core6 model is compared paired.
- **[dashboard/build.py](../paygym/dashboard/build.py)** + [template](../paygym/dashboard/templates/index.html.j2) → static `public/`, with:
  - verdict;
  - leaderboard with baselines;
  - tier and reward-function breakdowns;
  - task × model heatmap;
  - score distribution;
  - transcript viewer, with the expected answer shown;
  - cost and latency;
  - RL curves;
  - Track C.

  `_main_group` picks the **full** eval group; it once picked core6, which caused your "empty fields".
- **See it:** `uv run paygym leaderboard && uv run python -m paygym.dashboard.build && open public/index.html`.

---

## Part 7: RL training (Steps 17–18)

### The training script ([train/grpo_train.py](../train/grpo_train.py))
- **Data = the environment's dataset.** [`build_dataset`](../train/grpo_train.py#L80-L87) calls `load_environment(...)`, so the trainer sees exactly the eval prompts.
- **Reward = the rubric.** [`rubric_reward`](../paygym/training_reward.py#L58-L93) calls `score_answer` with no judge, and logs **monitors** every step:
  - twin refusal rate;
  - trap answer rate;
  - parse-fail rate;
  - modal net-pay share;
  - length–reward correlation;
  - per-tier pass rates.

  These are the signals of a gamed reward. It also saves 8 completions per step for the hack hunt.
- **The objective** ([`GRPOConfig`](../train/grpo_train.py#L377-L413)):
  - **GRPO**: for each prompt, sample G = 8 answers, score them, and push up the ones above the group mean. There is no value network, the cheapest credible method on one GPU.
  - `loss_type="dr_grpo"`: no length bias.
  - `scale_rewards="none"`: advantage = reward − group mean, **not** divided by the standard deviation, so a −1 stays a −1.
  - `beta`: the KL penalty against the frozen reference (TRL's k3 estimator). The reference is **the base model with the LoRA adapter switched off**, a true frozen copy at no extra memory. β must be > 0 (line 332), or TRL loads no reference and logs no KL.
  - LoRA r = 16 on all linear layers ([line 414](../train/grpo_train.py#L414-L415)), bf16, gradient checkpointing.
  - **Micro-batch 4** with gradient accumulation (line 391): G = 8 at once ran out of memory. The objective is unchanged.
  - **Sampler parity** (line 400): top_p 0.8, top_k 20, repetition penalty 1.1, the same as the pilot and the vLLM eval (A12).
  - Constant LR 5e-5 (A9, A13).
- **[`ValidationAndSafety`](../train/grpo_train.py#L180-L293), the pre-registered stop rules:**
  - every `--val-every` steps (default 25; the reported 60-step runs used 20), score greedily on the **validation** split;
  - record `validation.csv`, `val_samples.jsonl` and `best_checkpoint.json`;
  - stop on plateau;
  - **safety stops:** KL too high, entropy too low, or twin refusal / modal answer climbing. The last two are *relative to the start* (≥ 0.25 above the first 5 values), after absolute thresholds fired on noise.
  - **The held-out set is never touched here.**
- **[`CsvMetrics`](../train/grpo_train.py#L150-L177):** every logged step goes to `metrics.csv` (reward, KL, entropy, completion length, `frac_reward_zero_std`, the monitors), and survives a resume.
- **The step-14 crash, three attempts:**
  1. Qwen uses grouped-query attention. With a padding mask, PyTorch fell back to the "math" kernel, which built the full attention matrix and asked for 16.5 GB.
  2. A scoped kernel setting was ignored; disabling math globally gave "Invalid backend".
  3. **The fix:** [`install_sdpa_fallback`](../train/grpo_train.py#L93-L144). Try the fast kernel; if it refuses, compute that one call **exactly** in 256-row chunks and log the shapes. `sdpa_fallback.json` confirmed the cause: fp32, no mask, GQA.

### What happened in training (what each rubric version taught us)

| Run | What the policy learned | Fix |
|---|---|---|
| v1.0/v1.1 | refuse everything (47/47 validation tasks); validation reward *rose*, because refusing a payslip cost 0 and answering a trap cost −1 | rubric **1.2**: refusing a payable task = −1 |
| v1.2 | write broken JSON everywhere (arithmetic inside JSON values): "unusable" still cost 0 | rubric **1.3**: unparseable = −1 |
| β = 0.001 (too low) | `"decision": "reject"` with a payslip attached, treated as a refusal on traps and as harmless on payslips | rubric **1.4**: an invalid decision = unparseable |
| **β = 0.04 (selected)** | honest improvement; never used "reject" (0/188) | — |

Each fix was checked **offline on the real outputs** (`paygym rescore`, re-scoring the saved samples) before retraining. That is the brief's "highest-signal item", written up in [RL_REPORT.md](RL_REPORT.md) B6.

### Step 18: held-out, scored once ([scripts/heldout_eval.sh](../scripts/heldout_eval.sh))
1. Merge the best-validation checkpoint into the base ([merge_adapter.py](../scripts/merge_adapter.py)).
2. Serve base and trained models in turn through vLLM.
3. Run **the same eval harness** on `heldout_easy` (124 tasks, training difficulty) and `heldout` (109 tasks, full difficulty); seeds 1,000,000+ were never seen in training.

[rl_summary.py](../scripts/rl_summary.py) computes paired bootstrap CIs:

| Set | Change | 95 % CI |
|---|---|---|
| `heldout_easy` | **+0.338** | [0.232, 0.442] |
| `heldout` | **+0.304** | [0.201, 0.411] |

---

## Part 8: the sandbox (Step 19)

**Live at https://aigym-alpha.vercel.app/docs**

- **[runs.py](../paygym/sandbox/runs.py), why answers can't leak.** The generator is open source, so a raw seed would let anyone recompute the answers. Instead:
  - you send a public `seed`;
  - the server turns it into per-task seeds with **HMAC(SANDBOX_SECRET, seed)** ([`_task_seed`](../paygym/sandbox/runs.py#L90-L92)), which only the server can compute;
  - the same public seed always gives the same tasks, so runs stay comparable;
  - task ids are just `000`, `001`, …
- **The `run_id` is a signed token** ([`sign`](../paygym/sandbox/runs.py#L64-L68) / [`verify`](../paygym/sandbox/runs.py#L71-L81)) carrying seed, tiers, n, rule-set version and time. The server needs **no database to score**: it re-generates the tasks from the token, so ground truth is never stored.
- **[app.py](../paygym/sandbox/app.py) endpoints:**
  - **`GET /tasks`** ([`get_tasks`](../paygym/sandbox/app.py#L136-L153)): tasks with prompt and tool prompt only; at most 50.
  - **`POST /submit`** ([`submit`](../paygym/sandbox/app.py#L156-L192)):
    - checks the token, and returns **409** if the rule-set version changed;
    - scores with **`score_answer`**, the same function as the eval;
    - returns a per-task score, breakdown, clause and gate;
    - is idempotent: the first result is stored with an atomic set-if-absent, and a resubmit returns it.
  - **`GET /runs/{id}`**, **`GET /leaderboard`**, **`POST /api/tools/{name}`**.
  - **Safety:**
    - per-IP rate limits (30/min);
    - a judge budget per IP per day; when it's used up, the judge component is `"deferred"`, never 0;
    - error handlers that never echo inputs or stack traces;
    - free-text `detail` (which names expected values) is never returned.
- **[store.py](../paygym/sandbox/store.py):** `RedisStore` (Upstash on Vercel, Redis locally) or `MemoryStore` (tests). `make_store` accepts Vercel's `KV_REST_API_*` names.
- **Deploy:**
  - [api/index.py](../api/index.py) imports the app;
  - [vercel.json](../vercel.json) routes `/api/*`, `/tasks`, `/submit`, … to it, and redirects `/docs`;
  - [.vercelignore](../.vercelignore) hides `pyproject.toml`, so Vercel installs the small [requirements.txt](../requirements.txt). That fixed `ModuleNotFoundError: fastapi`.
- **Tests:** [tests/test_sandbox.py](../tests/test_sandbox.py):
  - a fuzz test asserts that no ground truth or seed appears in any response;
  - `test_scoring_parity_with_the_rubric_and_the_environment` checks that sandbox score = environment score = rubric score.

---

## Part 9: Track C, scaffold comparison (Step 20)

- **The model is fixed, the scaffold varies:** [`SCAFFOLDS`](../paygym/prompting.py#L55-L61):
  - S0: bare prompt;
  - S1: rules in context;
  - S2: tools;
  - S3: tools + required `calc` self-check;
  - S4: S3 + a ceiling/effective-date checklist.
- **Script:** [scripts/track_c.sh](../scripts/track_c.sh) runs Qwen-3B (and 0.5B) through S0–S4 with the same harness. [track_c.py](../scripts/track_c.py) builds the table and an honest verdict: it reports interactions and ties instead of declaring a winner.
- **Result:**
  - the best scaffold is worth +0.21 for the 3B, and S1 gives most of that gain at the lowest cost;
  - for the 0.5B, more scaffold made it *worse*, so the effect changes sign with the model.

  See [TRACK_C.md](TRACK_C.md).

---

## Part 10: reports and checks (Steps 21–24)

| File | What it is |
|---|---|
| [EVAL_REPORT.md](EVAL_REPORT.md) | numbers per model, tiers, baselines, CIs, spend; the judge section still to fill |
| [RL_REPORT.md](RL_REPORT.md) | Part A pre-registration + amendments A9–A16; Part B results and reward gaming |
| [FAILURE_ANALYSIS.md](FAILURE_ANALYSIS.md) | 11 transcripts read, 5 categories with counts |
| [EDGE_CASES.md](EDGE_CASES.md), [TRADEOFFS.md](TRADEOFFS.md), [AI_USAGE.md](AI_USAGE.md) | brief §9 items 10–12 |
| [WALKTHROUGH.md](WALKTHROUGH.md) | every brief requirement → evidence |
| [LOOM_SCRIPT.md](LOOM_SCRIPT.md) | the video plan |

---

## Appendix A: the CLI

| Command | What it does | Code |
|---|---|---|
| `paygym validate tasks/` | schema + recompute truth + twins | [validate.py](../paygym/validate.py) |
| `paygym generate --split eval --seeds 95` | make a split | [generator.py](../paygym/generator.py#L402-L409) |
| `paygym audit <file>` | leakage + near-dup report | [audit/](../paygym/audit/) |
| `python -m paygym.eval …` | run an eval | [eval/runner.py](../paygym/eval/runner.py) |
| `paygym rescore [--force]` | re-score saved runs, no model calls | [runner.py](../paygym/eval/runner.py#L561-L626) |
| `paygym leaderboard` | aggregate → `results/leaderboard.json` | [leaderboard.py](../paygym/eval/leaderboard.py) |
| `paygym judge items / repeat / labels / agreement` | judge reliability | [judge_reliability.py](../paygym/judge_reliability.py) |
| `python -m paygym.dashboard.build` | build the website into `public/` | [build.py](../paygym/dashboard/build.py) |
| `python train/grpo_train.py --reward rubric --beta 0.04 …` | train | [grpo_train.py](../train/grpo_train.py) |

## Appendix B: five things to check yourself (15 minutes)

1. **The calculator is right:** run the command in §0.2. Then redo the twin's table by hand from RULESET.md GEN-§6, §7, §5 and VAL-§2–4.
2. **The ground truth can't drift:** `uv run paygym validate tasks/` recomputes every stored answer.
3. **The scorer is shared:** `grep -rn "score_answer" paygym train`. Eval, environment, trainer, sandbox and baselines all import the one function.
4. **The sandbox doesn't leak:** `curl -s "https://aigym-alpha.vercel.app/tasks?n=5&seed=1" | grep -c -e ground_truth -e line_clauses` prints 0. (`net_pay` does appear, but only as a key name in the output-contract instructions, never with a value.)
5. **The exploits were real:** in each run's `val_samples.jsonl`, look at the step-20 rows (all 47 validation tasks):
   - `results/train/v1.1-grpo-b0.001/`: all 47 contain `"refuse"`;
   - `results/train/v1.2-grpo-b0.04/`: all 47 are `unparseable`;
   - `results/train/grpo-b0.001/`: all 47 contain `"reject"`.
