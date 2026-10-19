# Defense prep (for you; not a submission deliverable)

Likely questions → a short answer → the evidence to point at. Numbers come from the committed results once the runs are done.

## Domain and rule set
- **Why payroll, why fictional rules?** It is computable (arithmetic over rules), it is real work, and it has natural traps. Fictional rules mean no model answers from memory, and the written rule book is the single authority. → `ruleset/v1.0/RULESET.md`, brief p.4.
- **How do you know your calculator is right?**
  - 16 hand-computed unit tests with the working written out;
  - ~1,000 property and metamorphic cases (net ≤ gross, contributions ≤ rate × ceiling, foreign salary = converted salary, a split month sums to a full month);
  - mutation checks: deleting the ceiling fails 5 tests;
  - the seed tasks' hand checks are enforced by `paygym validate`;
  - the fidelity audit's divergence rate on 10 generated tasks.

  → `tests/test_reference*.py`, `docs/FIDELITY_AUDIT.md`.
- **What did writing the code teach you about the rules?** Four ambiguities, all fixed in the prose first, because the rule set is the authority. → `docs/EDGE_CASES.md` #4.

## Reward design
- **What does a score of 1.0 mean? 0.25? −1?** See the score-level table. → `paygym/rubric.py` docstring, README.
- **Why 0.70 / 0.25 / 0.05?** Net pay is what gets paid; lines give partial-credit signal; format is nearly worthless by design. Sensitivity: the ranking under alternative weightings has Kendall's τ = … → `results/weight_sensitivity.json`.
- **How do you stop the gym rewarding refusal?** Twins; a refusal on a determinable case scored as a wrong answer; −1 for answering traps; traps ≤ 25%; a twin-refusal monitor; no std scaling. → `docs/EDGE_CASES.md` #3.
- **Why is the judge only 0.2 of a trap?** The decision is programmatic; the judge only covers the genuinely unverifiable part (explanation quality), with measured reliability (disagreement …, κ …).
- **Did you attack your own reward?** Yes, two ways:
  - five baselines with floors; naive-no-ceiling (the brief's named failure) scores … vs the floor of 0.35;
  - the RL policy itself; see the RL report §B6.

## RL
- **Why GRPO, why Dr. GRPO, why no std scaling?** No value network: cheapest on one GPU. Constant-length normalisation removes length bias. Std scaling overwrites the designed −1 / 0.05 magnitudes (arXiv 2608.00301). → README "RL objective".
- **Why β = 0.001 and not 0?** TRL at β = 0 loads no reference and logs no KL (read from the 1.14.1 source), so the "too low" run would show nothing.
- **Is the improvement real or memorisation?** Content-disjoint held-out split (tested); model selected on *validation*; held-out scored once; paired bootstrap CI … → `results/train/rl_summary.json`.
- **What did the policy learn to game?** … → `docs/RL_REPORT.md` B6.
- **Why only 0.5B?** The brief says scale earns nothing; when it was too weak we made the training tasks easier, and held-out stays full difficulty.

## Eval rigor
- **Single-rollout leaderboard?** No: 3 rollouts at temperature 1.0, mean ± SD, rollout disagreement rate, and pairs we cannot distinguish (paired bootstrap).
- **What did it cost?** $0 actual; list-price equivalent $…. It runs on free tiers plus a local GPU, and the guardrail is tested.

## Sandbox
- **Can I get the answers out?** No: HMAC-derived seeds, opaque ids, no `detail` text, a leak fuzz test across every endpoint. Seed reuse is the documented caveat.
- **Does it score like the dashboard?** Same function; a parity test against the env reward and `score_answer`.
- **What if your rules change?** A run issued under v1.0 gets 409 under v1.1; the leaderboard groups by rule-set fingerprint.

## Engineering choices
- **Why verifiers 0.2.1?** The brief's API is v0, which was removed in 0.3.0; the README has the v1 mapping.
- **Why Vercel + Upstash?** Free, no card, ~1 s cold start. HF Docker Spaces now need a paid plan; Render sleeps with ~1 min cold starts.
- **Why Docker Compose and uv?** uv is what the brief's setup and commands use; Compose runs the GPU vLLM server, the local sandbox + Redis and the dashboard preview.

## Next at Niural
- Real statutory tables with effective-dated versions;
- an anomaly-detection slice;
- multi-turn tool RL;
- a decide-then-compute agent with a single-pass decision model, measured for calibration by this gym's per-decision ground truth;
- the gym as a pre-deployment gate for payroll agents.
