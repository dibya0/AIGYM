# Loom script (8–12 min)

The brief requires narrating design decisions, not features: **≥ 3 min on reward design**, **≥ 1 min reading a real failure transcript aloud**, and **the sandbox scoring a live request**.

| Time | Segment | Show | Say |
|---|---|---|---|
| 0:00–0:45 | The problem and the slice | README top | Gross-to-net is computable, real and full of traps. Fictional rules, so models must read rather than recall. One slice, done deeply. |
| 0:45–1:45 | Rule set as the authority | `RULESET.md` (ceilings, GEN-§9), then a `@cites` step in the calculator | The prose came first; code is a claim about it. Four ambiguities found while coding were fixed in the prose. The fidelity audit measures the gap. |
| 1:45–5:00 | **Reward design (≥ 3 min)** | `paygym/rubric.py` docstring, the score-level table; the gating code; the baselines-vs-floors table; the sensitivity τ | What 1.0 / 0.25 / 0.05 / −1 mean under the rules. Why the cap. Why a refusal on a determinable case goes down the wrong-answer path. Twins against refusal collapse. Clause provenance: the first wrong line traced to `VAL-§2.1`. The judge only for the unverifiable part, with its reliability numbers. How we attacked it: five baselines, then RL. |
| 5:00–6:15 | **A real failure transcript (≥ 1 min)** | Dashboard heatmap → click a red cell → transcript viewer | Read it aloud: what the model did, which line went wrong first, which clause, why the score is what it is, and what this failure mode means for deploying an agent. |
| 6:15–7:45 | RL: what the policy learned | Dashboard RL curves (both β), held-out before/after, one gaming transcript | KL at β = 0.001 vs 0.04; where we would set β; validation-based selection and held-out scored once; what the policy gamed (or what we checked). |
| 7:45–9:00 | **Live sandbox request** | Terminal: `python3 scripts/quickstart.py https://…` | Fetch → submit → per-task score, breakdown, clause. Why no ground truth leaves the server (HMAC seeds, no detail text, the leak test). Same scorer as the dashboard. |
| 9:00–10:00 | Track C + verdict | Dashboard verdict panel, Track C table | Does the scaffold beat the model choice? Cost per correct payslip. Which model for which tier, where it hurts. $0 total spend. |
| 10:00–10:30 | What next | README "next" | Real statutes, an anomaly slice, tool RL, decide-then-compute. |
