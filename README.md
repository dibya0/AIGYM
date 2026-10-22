# PayGym

A verifiable evaluation **and** reinforcement-learning environment for AI agents doing real payroll work: computing a **gross-to-net payslip** under a written rule set, or refusing when the rules do not determine one.

| | |
|---|---|
| **Dashboard** | **https://aigym-alpha.vercel.app** |
| **Sandbox API** | `https://aigym-alpha.vercel.app/tasks`, `/submit`, `/runs/<id>` · interactive docs: **https://aigym-alpha.vercel.app/docs** |
| **Two-minute quickstart** | `curl -s https://aigym-alpha.vercel.app/quickstart.py \| python3 - https://aigym-alpha.vercel.app` |
| **Status** | [docs/STATUS.md](docs/STATUS.md) |
| **Reports** | [Eval](docs/EVAL_REPORT.md) · [RL training](docs/RL_REPORT.md) · [Failure analysis](docs/FAILURE_ANALYSIS.md) · [Track C](docs/TRACK_C.md) · [Edge cases](docs/EDGE_CASES.md) · [Trade-offs](docs/TRADEOFFS.md) · [Fidelity audit](docs/FIDELITY_AUDIT.md) · [AI usage](docs/AI_USAGE.md) · [Research notes](docs/RESEARCH_NOTES.md) |
| **Requirement status** | [docs/REQUIREMENTS_CHECKLIST.md](docs/REQUIREMENTS_CHECKLIST.md) (every brief requirement → evidence) |

**Total model spend: $0.** Free tiers (Gemini via Google AI Studio, Groq) and open-weight models on one local RTX 5070 Ti.

## Results in one screen

| | |
|---|---|
| **Leaderboard** (109 eval tasks × 3 rollouts, rubric 1.4) | Gemini 3.5 Flash-Lite **+0.314** · baselines naive_no_ceiling +0.249 … always_abstain −0.737 · Qwen2.5-3B −0.485 · Qwen2.5-0.5B base −0.652 → **GRPO-trained −0.331** · on fixed subsets (paired, same tasks): **Gemini 3.8 Flash +0.885** (6 tasks), **gpt-oss-120b +0.665** (10 tasks) |
| **What the gym found** | Arithmetic separates the models. The cheap frontier model can't compute payroll: Flash-Lite gets net pay exact on **6 of 210** payslips, while a script that ignores ceilings gets 111, and Flash-Lite is not statistically distinguishable from that script. The strongest Gemini we could afford gets **11 of 12** exact on the same 4 subset payslips where Flash-Lite gets 0, but that rests on 4 tasks (20 free requests/day). So: decide with a cheap model and compute with a calculator; a strong reasoning model is the candidate for end-to-end, after a full eval ([eval report](docs/EVAL_REPORT.md)). |
| **RL** (GRPO, Qwen2.5-0.5B + LoRA, β = 0.04) | held-out, never trained on, scored once: **+0.338 [+0.232, +0.442]** (training difficulty), **+0.304 [+0.201, +0.411]** (full difficulty). Learned: valid payslips, no refusing payable work. Lost: it answers every trap ([RL report](docs/RL_REPORT.md)). |
| **Reward gaming** | The policy learned **three** exploits, each closed in the rubric (1.1 → 1.4) after an offline check on its real outputs: refuse everything, broken JSON, and an invalid decision word. The too-low β = 0.001 found the third; β = 0.04 never used it. The 5 hand-written baselines found none. |
| **Track C** (scaffolds) | For Qwen-3B the scaffold is worth +0.21, mostly from putting the rules in the prompt. The model effect changes sign with the scaffold, and a frontier model is +0.80 above the 3B ([Track C](docs/TRACK_C.md)). |

---

## Why this slice

Gross-to-net is real paid work. Every line is arithmetic over rules, so a program can decide the right answer without asking a model. And it is full of plausible-but-wrong traps: wage ceilings that cap contributions, proration, mid-month raises, stale rate tables, documents that disagree. The rule set is **fictional** (three invented jurisdictions: Valdoria, Kestrel Isles, Nordmark), so no model can answer from memory: it has to read the rules or call the tools.

## Architecture

```
ruleset/v1.0/RULESET.md   prose rule book, stable clause ids (the authority)
ruleset/v1.0/rules.yaml   its rate tables, each value tagged with its clause (a test proves they match the prose)
        │
paygym/reference/         reference calculator: Decimal arithmetic, @cites(clause) on every step, full trace
        │
paygym/generator.py       seeded task generator (one PCG64 stream per task; disjoint seed ranges per split)
        │                 traps always come with a determinable "twin"
paygym/environment.py     load_environment() -> vf.Environment  (verifiers 0.2.1: SingleTurnEnv / StatefulToolEnv)
        │                 prompts (paygym/prompting.py) · tools (paygym/tools.py) · rubric (paygym/rubric.py)
        ├── EVAL     python -m paygym.eval      every rollout runs through the environment; cost cap, resume, stats
        ├── TRAIN    train/grpo_train.py         TRL GRPO, dataset = the environment's dataset, reward = the rubric
        └── SANDBOX  paygym/sandbox/ (FastAPI)   same generator + rubric; ground truth regenerated server-side
results/                  committed JSON per run  ->  python -m paygym.dashboard.build  ->  public/ (Vercel)
```

**One scorer.** `paygym.rubric.score_answer` is the only scoring function. The environment's reward wraps it, the trainer's reward wraps it, and the sandbox calls it. `tests/test_sandbox.py` checks that all three give identical scores.

**Spec version.** The brief's interface (`load_environment`, `Rubric`, `SingleTurnEnv`, `ToolEnv`) is verifiers' **v0 API**. Verifiers removed it in 0.3.0 (Aug 2026) in favour of a v1 `Taskset`/`Harness` design, so this package pins **`verifiers==0.2.1`**, the last release that ships it. Mapping for a v1 port:
- rubric functions → `@vf.reward(weight)`
- monitors → `@vf.metric`
- tools → `vf.Toolset` / `@vf.tool`
- generator → `Taskset.load()` with `INFINITE = True`
- judge → `vf.Judge`

## Task schema

`paygym/schema.py` (`uv run paygym schema` prints the JSON Schema). Minimum fields per the brief: `id, slice, difficulty, prompt, context_files, ground_truth, verifier, tags, schema_version`. Additional fields:
- `case` (structured inputs per source document)
- `lookup`
- `employee_id`
- `ruleset_version`
- `twin_of`
- `trap_reason`
- `provenance`
- `seed`
- `hand_check`

Ground truth is a discriminated union: `value` (Tier 1), `payslip` (Tier 2: every line + tolerance + clauses per line) or `refusal` (Tier 3: reason code + clause). It is always computed by the reference implementation. `paygym validate tasks/` recomputes it and fails on any difference.

| Tier | What it tests | Example |
|---|---|---|
| 1 Retrieval | read the rule set, answer in the contract | "What is Valdoria's social insurance ceiling for 2026?" |
| 2 Computation | multi-step payslip where caps, proration, FX and raises interact | a 9,000 VLD salary where the 6,000 ceiling caps social insurance |
| 3 Trap | the rules do **not** determine the payslip: refuse with the right reason | documents give two different start dates; no 2027 rate table; salary in GBP |

Every trap has a near-identical **twin** that *is* determinable (e.g. the same documents disagreeing only on job title, which is not an input). Twins make over-refusal visible, so the gym cannot reward refusing to work.

## Reward functions and weights

`paygym/rubric.py`: each component returns `(score, clauses, detail)`. The **gated** total is the reward:

| Task kind | Score levels |
|---|---|
| Payslip | **1.0** net pay and every line within one minor unit (tolerance from GEN-§1.4) · **0.75–0.99** net right, some lines wrong · **≤ 0.25** net wrong (capped, whatever else is right) · **−1.0** refused a determinable payslip · **−1.0** unparseable or no valid decision |
| Trap | **1.0** correct refusal + useful explanation (LLM judge) · **0.8** correct reason code · **0.3** refused for the wrong reason · **−1.0** computed a payslip anyway · **−1.0** unparseable |
| Retrieval | **1.0** exact value · **0.05** wrong value, valid format · **−1.0** refused or unparseable |

**Why every wrong decision is −1 (rubric 1.4):** the compute/refuse choice is a decision, and both wrong decisions are penalised the same.
- **Refusing a payable payslip** means employees are not paid.
- **Computing a trap** means paying on rules that do not determine the pay.
- **An unusable answer** cannot be paid or reviewed either.

These values were not the first design. Each one closed an exploit that the GRPO policy actually learned, documented with transcripts in [RL_REPORT B6](docs/RL_REPORT.md):
- 1.0 → 1.1: a refusal kept format credit;
- 1.1 → 1.2: refusing was free, so the policy refused 47/47 tasks;
- 1.2 → 1.3: broken JSON was free, so it wrote broken JSON for 47/47;
- 1.3 → 1.4: an invalid decision word read as a refusal on traps.

Every eval run is re-scored to the current rubric with `paygym rescore` (saved completions, no model calls), so no comparison mixes versions.

**Payslip weights:**
- **Net pay 0.70.** It is what the employee is paid, and it is wrong whenever an upstream mistake matters.
- **Line accuracy 0.25.** Graded partial credit: it rewards getting the ceiling, tax and pension right separately, and gives a learning signal before net pay is right.
- **Format 0.05.** Small enough that format alone is worthless.

`python -m paygym.eval.sensitivity` re-ranks every model under three alternative weightings and reports Kendall's τ (see the [eval report](docs/EVAL_REPORT.md)).

**Where it fails, by clause.** Line accuracy reports the **first wrong line in computation order** and its clauses, so a missed ceiling is traced to `VAL-§2.1`.

**LLM judge** (`paygym/judge.py`). It is used only for the genuinely unverifiable part: whether a correct refusal's explanation names the problem input, states why the rules do not determine the payslip (quoting GEN-§9), and is actionable. Each criterion is a separate pass/fail call. The model is pinned (Gemini 3.1 Flash-Lite), with a versioned prompt and cached verdicts. Reliability is measured by a 3-repeat disagreement rate: 0/60 on 20 real explanations. The hand-label agreement check is prepared but was not run before the deadline. The judge is excluded from the RL reward.

**Adversarial baselines** (`paygym/baselines.py`), each with a stated floor and on the leaderboard:
- `format_only`
- `always_abstain`
- `modal_answer`
- `naive_no_ceiling` (ignores the cap, never refuses)
- `gross_as_net`

## How to run

```bash
cp .env.example .env                 # free-tier keys: GEMINI_API_KEY, GROQ_API_KEY (+ SANDBOX_SECRET for the sandbox)
uv sync --extra cpu                  # gym, environment, eval, sandbox, dashboard (no GPU needed)
uv run pytest -q                     # full test suite
uv run paygym validate tasks/        # schema + ground truth vs reference + hand checks + trap twins

# one evaluation (any OpenAI-compatible endpoint; the model is always a flag)
uv run python -m paygym.eval --model groq/openai/gpt-oss-120b --tier all --rollouts 3 --seed 7 --max-cost 2.00
uv run python -m paygym.eval --model gemini/<model> --mode tool --rollouts 3
uv run python -m paygym.eval --model baseline/naive_no_ceiling            # adversarial baseline, no model calls
uv run paygym leaderboard && uv run python -m paygym.dashboard.build      # results/ -> public/

# portable: the environment works with verifiers' own tooling
uv run python -c "import verifiers as vf; print(vf.load_environment('paygym', mode='tool'))"

# GRPO training (NVIDIA GPU, driver >= 570)
uv sync --extra cpu --extra train
uv run python train/grpo_train.py --reward rubric --beta 0.04 --run-name grpo-b0.04
```

Local services: `docker compose --profile gpu up llm` (vLLM serving Qwen), `docker compose --profile sandbox up sandbox redis`, `docker compose --profile dashboard up dashboard`.

## RL objective (as implemented)

GRPO with the Dr. GRPO loss (TRL 1.14.1), Qwen2.5-0.5B-Instruct + LoRA, one local GPU:

```
A_i  = r_i − mean(r_1..r_G)                      (G = 8; no division by the group std)
J(θ) = 1/(G·L_max) Σ_i Σ_t min(ρ_i,t A_i, clip(ρ_i,t, 1±ε) A_i)  −  β · KL̂(π_θ ‖ π_ref)
KL̂   = exp(log π_ref − log π_θ) − (log π_ref − log π_θ) − 1     (k3, per token, logged every step)
```

- **Why GRPO:** no value network, so it is the cheapest credible on-policy method on one 16 GB GPU, and each completion's advantage is a transparent comparison with its siblings.
- **Why Dr. GRPO:** constant-length normalisation removes the length bias a policy can exploit.
- **Why no std scaling:** dividing by the group std rescales each group to unit variance and overwrites the rubric's designed magnitudes, such as the −1 penalties for wrong decisions.
- **Why the reference is free:** π_ref is the base model with the LoRA adapter disabled.
- **β sweep:** {0.001 (deliberately too low), 0.04}. At 0.001 the policy drifted 7× further (KL 0.15 vs 0.02) and learned an exploit; at 0.04 it improved honestly. We would set β = 0.04 or higher (RL_REPORT B3).
- **Training data:** 30 tasks of the `easy` preset (base 0.5B gets 0 % exact payslips at every difficulty; A11). Selection is on `val_easy`; held-out is reported on both `heldout_easy` and full-difficulty `heldout`.
- **Pre-registration:** stop rules and the held-out protocol were registered before training in [docs/RL_REPORT.md](docs/RL_REPORT.md).

## Agent sandbox

Fetch tasks, run your own agent, submit, get scored by the same rubric, with no clone needed:

```bash
curl -s https://aigym-alpha.vercel.app/quickstart.py | python3 - https://aigym-alpha.vercel.app   # one command, no clone, ~1 minute
```
It needs nothing beyond Python's standard library. It waits out a cold start, fetches 5 Tier-2/3 tasks, submits a trivial answer and prints the per-task score, breakdown and clause.

The paths match the brief's API shape: `/tasks`, `/submit` and `/runs/<run_id>` work, as do the same routes under `/api/` (OpenAPI docs at `/api/docs`).

```
GET  /api/tasks?tier=2,3&n=10&seed=42   -> {run_id, ruleset_version, seed, tier_mix, tasks: [{id, prompt, tool_prompt, tools_available}]}
POST /api/submit {run_id, answers: [{id, answer}]}
                                         -> {mean_reward, per_task: [{id, score, breakdown, clause, gate}]}
GET  /api/runs/{run_id} · GET /api/leaderboard · POST /api/tools/{name}
```

- **No ground truth on the wire.** The generator is open source, so the sandbox never uses a caller-visible seed directly: per-task seeds are `HMAC(SANDBOX_SECRET, public seed)`, and task ids are opaque. Responses carry component scores and clause ids, never the rubric's free-text detail (which names expected values). A fuzz test asserts that no expected value, reason code, seed or secret appears in any response.
- **Feedback can't be used to steer a rerun.** A manual test (2026-10-22) found that a trap refused with the *wrong* reason returned the specific clause (e.g. GEN-§9.4), which names the expected reason code. Because the same public seed regenerates the same tasks, that allowed a probe-then-resubmit attack. Now a trap not refused for the right reason reports the general GEN-§9 (the score is unchanged), and a second submission on a reused (seed, tiers, n) is marked `repeat_seed: true` on the external leaderboard. **Residual, stated:** the gate still tells a caller whether a task was a trap or payable. With a reused seed, an agent could still learn that by probing; the `repeat_seed` flag makes such runs visible rather than impossible. The default seed is random, so ordinary runs never repeat.
- **Comparable runs.** The same public seed, tier mix and `n` give the same tasks; `run_id` is a signed token recording the seed, tiers, n and rule-set version. A run issued under another rule-set version gets **409**, never a silent re-score.
- **Abuse and cost.**
  - **Task cap:** at most 50 tasks per run.
  - **Rate limits per caller:** 30 task fetches and 30 submits a minute, 300 tool calls a minute.
  - **Scoring:** a run is scored once (idempotent).
  - **Judge budget:** the judge runs only within a per-caller daily budget of 20 judged submissions; beyond that, or if the judge is down, its component is marked `deferred`, never a failure.
  - **No keys:** nobody's API keys are accepted or stored (answer-submission mode only).
  - **Cost:** hosting is Vercel Hobby + Upstash free tier; scoring is CPU-only; the only paid-capable dependency, the judge, is capped.
  - **Caveat:** reusing a public seed returns the same tasks (needed for comparability), so per-task feedback from an earlier run could be reused. The default seed is random.
- **Cold start.** The first request after idle can take a few seconds while Vercel starts the function. The quickstart polls `/api/health` first; please do the same rather than concluding it is down.
- **Storage:** Upstash serverless Redis, holding run records, the external leaderboard and rate-limit counters only. `/health` reports `"store": "RedisStore"`. No answers or ground truth are stored: tasks are regenerated from the signed `run_id`.
- **External runs** submitted through the sandbox appear on its leaderboard (`/api/leaderboard`, `"external": true`) and in the dashboard's "External sandbox runs" section.

## The reference implementation is the verifier

`paygym/reference/` is a faithful, clause-cited implementation of the written rule set, checked by hand-computed tests per clause, ~1,050 generated property and metamorphic cases (`tests/test_reference_properties.py`: invariants, monotonicity, FX equivalence, proration additivity, ceilings) and a rule-set fidelity audit (0/50 divergences, `docs/FIDELITY_AUDIT.md`). Because it can be trusted, **the generator can produce unlimited graded tasks for any model, forever, with no human labelling**: every ground-truth answer in this repo, in the RL training data and in the sandbox comes from it, never from a model.

## Where "the reference is the verifier" breaks down

Gross-to-net is computable once the inputs are known **and** the rules are written down. It breaks where payroll work is judgement, not arithmetic:
- **Worker classification and permanent-establishment risk.** Multi-factor legal tests with no closed form.
- **Ambiguous source documents.** Contract wording that can be read two ways. Here we *define* conflicts as undetermined (GEN-§9.2); a real operator resolves them with the employer.
- **Statute drift and interpretive guidance.** Real rules change mid-year, and authorities publish guidance that is not in the statute. A fictional, pinned rule set sidesteps this.
- **Employee-specific elections and garnishments.** These depend on facts no record holds.

In those areas a reference implementation would only encode one opinion, and an LLM judge (with measured reliability) or human review is the honest verifier.

## Bringing your own agent, model or domain

- **Your agent, no clone:** fetch from `/tasks`, answer with any framework, `POST /submit`, and read the per-task score, breakdown and clause. Swagger at `/docs`.
- **Your model:** any OpenAI-compatible endpoint is one flag:
  ```bash
  uv run python -m paygym.eval --model my/model --base-url https://… --api-key-var MY_KEY --rollouts 3
  ```
  The same environment also loads in verifiers' own tooling (`vf.load_environment("paygym")`) and trains with `train/grpo_train.py --model <hf-id>`.
- **Your domain:** the harness (eval runner, budget ledger, leaderboard, dashboard, sandbox, trainer) is domain-agnostic. A new slice replaces the domain half:
  1. a prose rule book with clause ids;
  2. a reference calculator citing them;
  3. a task schema / ground-truth type;
  4. a seeded generator with traps and twins;
  5. the rubric's scoring for that type.

  Everything downstream works unchanged. Payroll is the one slice implemented here.

## What we would build next

- Real statutory tables for a few countries, with effective-dated rule versions and a fidelity audit per release.
- A second slice: payroll **anomaly detection** (seeded errors, scored by precision and recall).
- Multi-turn tool RL, and the trained policy in tool mode.
- **Decision models.** Most payroll mistakes are *decision* errors (which table, does the cap bind, is an input missing), not arithmetic. A "decide-then-compute" agent could use a single-pass decision model for those choices and the verified calculator for every number. A decision model reads the input once and returns probabilities over options with no generated text (Large Decision Models, arXiv 2610.15501; LLM-as-Jev, arXiv 2610.02076). This gym's per-decision ground truth could measure such models' calibration. It was deliberately left out to keep depth on the required phases.

## Repository map

| Path | What |
|---|---|
| `ruleset/v1.0/` | rule book (prose) + rate tables |
| `paygym/reference/` | reference calculator + clause trace |
| `paygym/generator.py`, `tasks/` | generator, seed taskset, generated splits |
| `paygym/environment.py`, `paygym/tools.py`, `paygym/parser.py`, `paygym/prompting.py` | verifiers environment |
| `paygym/rubric.py`, `paygym/judge.py`, `paygym/baselines.py` | reward layer |
| `paygym/eval/` | eval harness, stats, leaderboard, sensitivity |
| `train/` | GRPO training |
| `paygym/sandbox/`, `api/`, `vercel.json` | sandbox API |
| `paygym/dashboard/`, `public/` | dashboard |
| `scripts/` | seed builder, sweep, pilot, merge, RL summary, Track C, fidelity worksheet, quickstart |
| `docs/` | reports, checklist, build log |
