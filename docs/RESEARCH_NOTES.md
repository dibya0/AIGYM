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
The Hub is a JavaScript app that could not be read by fetch. **To complete (user, §C of USER_ACTIONS):** review 10–15 environments and note how rigorous vs lazy ones define reward. Observations go here.

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
