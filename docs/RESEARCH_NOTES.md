# Research notes

## Background reading (brief §2)

### verifiers (github.com/PrimeIntellect-ai/verifiers)
- **The brief's spec is the v0 API.** `load_environment() -> vf.Environment`, `Rubric`, `SingleTurnEnv`, `ToolEnv`. The current docs say "The legacy v0 stack (`import verifiers as vf`) has been removed." Main is v1: `Taskset.load()`, `Harness`, `@vf.reward`, `@vf.metric`, `vf.Toolset`, TOML `vf-eval`.
- **PyPI wheels inspected:** 0.2.1 (Jul 2026) is the last release exporting the v0 classes; 0.3.0 removed them. We pin 0.2.1 and map the design to v1 in the README.
- **Read from the 0.2.1 source:**
  - `StatefulToolEnv.add_tool(args_to_skip=…)` + `update_tool_args` (per-rollout hidden arguments);
  - `MultiTurnEnv(max_turns, timeout_seconds)`;
  - `@vf.stop` conditions;
  - `env.run_rollout(...)` → `RolloutOutput` with reward, metrics, token usage, timing, error and stop condition;
  - `state_to_output` serialises standard fields only.
- **v1 conventions adopted anyway:** external or judge failures raise instead of returning 0; weight-0 functions are used as logged monitors.

### Harvey LAB (README + docs/architecture.md)
- **Borrowed:**
  - filesystem-first runs and static reports;
  - per-run `config.json`, `transcript.jsonl`, `metrics.json`, `scores.json`;
  - a `finish_reason` / stop condition per rollout;
  - adapter routing by model prefix;
  - preflight before sweeps;
  - judge criteria evaluated independently.
- **Deliberate difference:** Harvey grades prose with LLM judges against rubric text. Our slice is computable, so the judge covers only the unverifiable explanation quality.

### Prime Intellect environments overview
Environment = dataset + harness + scoring rules, so one object serves eval and RL. That is why `load_environment()` is the single source for the eval, the trainer and the sandbox.

### Environments Hub
**Reviewed: the author browsed 10–15 Hub environments in a browser on 2026-10-22; three that show distinct reward designs are written up below.** The Hub is a JavaScript app that could not be read by fetch, so this reading was done by hand, and the notes come from each environment's README, not its code. The reward-design choices themselves were grounded earlier in the verifiers source (v0.2.1 and v1), Harvey LAB's architecture docs and the literature below.

**`zapier/AutomationBench`** (one of the most-installed environments; 800 multi-step business-workflow tasks over 47 simulated SaaS tools; arXiv 2604.18934):
- **Rigorous:**
  - **outcome verification without an LLM judge:** each task asserts the *final state* of the simulated CRM/inbox/calendar;
  - **an all-or-nothing official score** (`task_completed_correctly`: every assertion must pass);
  - **traps and distractors** (stale data, irrelevant records);
  - **a private, harder held-out task set** for the official leaderboard, so the public set can't be memorised;
  - **versioned tasks, with models re-run** when a fix changes scores;
  - foundational "simple" tasks excluded from the score.
- **Weaker, by our standard:** the **training reward is ungated partial credit** (`reward = partial_credit`, the fraction of assertions met; the all-or-nothing metric has weight 0). 7/10 assertions earns 0.7 even if the missed three are the consequential ones, so an optimiser can farm easy assertions. The README does not say whether wrong side effects are penalised, or how over-caution (doing nothing) is measured.
- **What it confirms or contrasts in PayGym:**
  - outcome checks by a reference, not a judge: the same choice;
  - a held-out set the agent never sees: our held-out split and the HMAC-seeded sandbox;
  - versioning plus re-scoring: our rule-set fingerprint and `paygym rescore`;
  - **the contrast:** our partial credit is *gated* (a wrong net pay is capped at 0.25), a confident wrong action on a trap scores −1, and twins measure over-refusal. Those are the three things an optimiser exploited in our own training (RL_REPORT B6), and exactly what an ungated fraction-of-assertions reward would leave open.

**`codenames`** (multi-agent: a cluegiver and a guesser trained together; seeded boards, 800 train / 200 eval):
- **Reward:** a weighted sum.
  - game 1.0: assassin −1, otherwise +2/R per red found and −1/R per blue hit (R = red words);
  - shot-calling 0.5: declared targets found ÷ R;
  - format 0.1 + 0.1.
- **Rigorous:**
  - programmatic outcome;
  - wrong guesses cost something (blue −1/R), so random guessing is not free;
  - the catastrophe (assassin) is the largest penalty;
  - seeded, deterministic boards with disjoint train/eval;
  - assassin/red/shot metrics logged.
- **Weaker, by our standard:**
  - **The catastrophe is a term, not a gate.** Nothing in the described rubric caps the total after an assassin hit, so format (+0.2) and possibly shot-calling (≤ +0.5) can offset it, to about −0.3 (whether shot-calling pays out on an assassin game depends on the code).
  - **Format is about 12 % of the maximum** (0.2 of 1.7).
  - **Joint training of both agents** lets them drift to a private clue code that the reward cannot detect; only a KL anchor or evaluation against a fixed partner would.
  - **Whether guess-everything pays** (2 − blue/R) depends on whether the assassin is always present and guessing stops; the README does not say.
- **Contrast with PayGym:** we compute the total *after* the gates (an answered trap is −1 whatever else is right), and format is 5 %.

**`science-env`** (single-turn science QA, the INTELLECT-3-RL science subset, about 33.8k items; `\boxed{}` answers):
- **Reward:** `correct_answer` = 1 if a rule-based `math_verify` passes **or**, when it fails, an LLM judge says the answer is correct (binary).
- **Rigorous:**
  - programmatic verification first;
  - a strict parser (`StrictMaybeThinkParser`, boxed extraction);
  - a **difficulty filter on measured pass rates** (Qwen3-4B avg@8 within [min, max]), which removes tasks every rollout gets right or wrong. This is the same purpose as our difficulty pilot (no gradient from all-identical groups).
- **Weaker, by our standard:**
  - **The judge is an OR fallback: it can only turn a 0 into a 1.** An optimiser can write answers that fail the strict check but persuade the judge, so the judge becomes the attack surface.
  - **The judge model is not pinned by default** (`judge_model=None`), so "the same environment" scores differently by configuration.
  - **Binary 0/1 with no cost for a confident wrong answer**, so guessing always pays.
  - **The default split is `train`**, so evaluating on the RL data measures memorisation.
- **Contrast with PayGym:**
  - our judge never overturns a programmatic verdict; it only adds ≤ 0.2 to a refusal that is already correct;
  - it is pinned, prompt-hashed and repeat-measured;
  - it is excluded from the RL reward;
  - train/val/held-out seed ranges are disjoint by test.

**Across the three:** all verify outcomes programmatically first, which is the rigorous core. Each has a path by which credit can outweigh or bypass the decisive check:
- ungated fraction-of-assertions (AutomationBench);
- an additive catastrophe term (Codenames);
- an LLM judge that can overturn the rule-based "wrong" (science-env).

Those are the failure modes our own optimiser exploited three times (RL_REPORT B6), and the reasons PayGym's total is gated rather than summed and its judge is a bounded bonus outside the RL reward.

**How PayGym differs from the environments reviewed:**

| Design question | AutomationBench | Codenames | science-env | **PayGym** |
|---|---|---|---|---|
| How correctness is checked | assertions on final app state | game outcome | `math_verify`, then LLM judge | **reference calculator, line by line, with a clause per line** |
| Can partial credit rescue the decisive error? | yes (fraction of assertions) | partly (additive terms) | n/a (binary) | **no: a wrong net pay is capped at 0.25** |
| Cost of a confident wrong action | not stated | blue −1/R, assassin −1 (additive) | 0 (same as no answer) | **−1, as a gate (answered trap)** |
| Is "can't be done" a correct answer? | not described | no | no | **yes: 4 trap types, the right reason code required** |
| Is over-caution measured? | not described | no | no | **yes: every trap has a determinable twin; refusing it is −1** |
| Format credit | — | ~12 % of max | — | **5 %** |
| LLM judge | none | none | an OR fallback that can overturn "wrong" | **a bounded +0.2 bonus on correct refusals only; pinned, repeat-measured, not in the RL reward** |
| Does a failure say *why*? | which assertion failed | no | no | **yes: the first wrong line and its rule-book clause** |
| Held-out / leakage | private harder set | seeded train/eval | default split is train | **disjoint seed ranges + HMAC-seeded sandbox; held-out scored once** |
| Was the reward attacked by an optimiser? | not reported | not reported | not reported | **yes: 3 learned exploits found and closed (RL_REPORT B6)** |

The common thread: these environments check outcomes rigorously but *combine* credit, by summing, taking a fraction, or ORing in a judge, so the decisive error can be outweighed. PayGym's distinctive choices are a **gated** total, **priced refusals in both directions** (traps and twins), and **clause-level diagnosis**. These came from domain needs (a payslip with the wrong pay is wrong, and refusing to pay is also wrong) and were then hardened by watching our own optimiser exploit every gap.

## 2025–26 literature that shaped decisions

| Source | Finding | What we did |
|---|---|---|
| Abstention collapse law (arXiv 2608.00301, Jul 2026) | With error-penalised rewards, KL-anchored RL can drift to refusing everything while mean reward rises; group-std normalisation replaces designed penalties with unit size | `scale_rewards="none"`; twin refusal rate as a per-step monitor with a safety stop; twins for every trap |
| TruthRL (arXiv 2509.25760) | Ternary reward (+1 correct, 0 abstain, −1 hallucinate) | Trap ladder: −1 for answering a trap, 0.8 for a correct refusal |
| Abstain-R1 (arXiv 2604.17073) | Reward refusal *plus* a clarification naming what is missing | The judge's criteria: name the input, state why, actionable |
| Dr. GRPO / DAPO / GSPO (incl. arXiv 2607.00152) | They mostly differ in std scaling, length normalisation and which groups contribute; GSPO mainly matters for MoE | `loss_type="dr_grpo"` (length bias), no std scaling; GSPO not needed for a dense 0.5B |
| Biased group-relative advantage (arXiv 2601.08521) | Advantage is underestimated on hard prompts | Not implemented; mitigated by the difficulty pilot; listed as next step |
| Verifier errors in RLVR (arXiv 2609.35677, 2610.19525) | A verifier used as a reward gets exploited | Adversarial baseline suite with floors; hack monitors; transcript reading |
| TRL 1.14.1 source | `beta` defaults to 0 and then loads no reference and logs no KL; k3 estimator; `frac_reward_zero_std` built in | β ∈ {0.001, 0.04}; β ≤ 0 refused |
| Large Decision Models (arXiv 2610.15501), LLM-as-Jev (arXiv 2610.02076), OpenAI Decisions API (beta, Oct 2026) | Single-pass decision readout: probabilities over options, zero generated tokens | Future work (README): "decide-then-compute"; cut to keep depth |
| "Lost in Diffusion" (arXiv 2604.10556) | Diffusion LLMs hallucinate more on reasoning | Not used |

## Hosting research (Oct 2026)
- **Hugging Face Spaces:** Docker Spaces now need a paid plan (official docs).
- **Render (free):** spins down after 15 min, with ~1 min cold starts and an ephemeral disk.
- **Vercel Hobby:** free, no card, ~1 s cold start; Python functions up to 300 s.
- **Upstash Redis:** free, no card.
- **Chosen:** Vercel + Upstash.
