# PayGym: submission status

*Last updated: 2026-10-19. One page: what is done, where it lives, and what is left before submission.*

## Live links

| What | URL |
|---|---|
| Dashboard | https://aigym-alpha.vercel.app |
| Sandbox API docs (Swagger, try-it-out) | https://aigym-alpha.vercel.app/docs |
| Fetch tasks | `GET https://aigym-alpha.vercel.app/tasks?tier=2,3&n=10` |
| Submit answers | `POST https://aigym-alpha.vercel.app/submit` |
| A stored run | `GET https://aigym-alpha.vercel.app/runs/<run_id>` |
| Two-minute quickstart | `python3 scripts/quickstart.py https://aigym-alpha.vercel.app` |
| Repository | https://github.com/dibya0/AIGYM |

## Deliverables (brief §9)

| # | Deliverable | Status | Evidence / where |
|---|---|---|---|
| 1 | GitHub repo, clean clone, `.env.example` | ✅ built, CI green, 233 tests | clean-clone test still to run |
| 2 | Deployed dashboard | ✅ **live** | all Phase 06 sections plus RL curves, held-out tables, Track C |
| 3 | Live agent sandbox + quickstart | ✅ **live** | Redis store, persistence, idempotent submit, 30/min rate limit, 50-task cap, no ground truth, same rubric 1.4 |
| 4 | Loom (8–12 min) | 🟡 script ready | `docs/LOOM_SCRIPT.md` (≈ 10 min, timings checked against the brief); you record |
| 5 | README / architecture | ✅ | live links, results, rubric 1.4 and why, RL objective + results, sandbox (cold start, storage, external runs), bring-your-own agent/model/domain |
| 6 | Eval report | 🟡 numbers in | judge reliability (3 repeats) and the hosted top-up pending |
| 7 | RL training report | ✅ Part A + Part B complete | `docs/RL_REPORT.md` |
| 8 | Failure analysis (5–10 transcripts) | ✅ 11 read, 5 categories with counts | `docs/FAILURE_ANALYSIS.md`; your review pending |
| 9 | Advanced track (C) | ✅ | `docs/TRACK_C.md` |
| 10 | Top-5 edge cases | ✅ | `docs/EDGE_CASES.md` (each with its guarding tests; all 18 cited tests exist) |
| 11 | ≥ 3 trade-offs | ✅ 12 | `docs/TRADEOFFS.md` |
| 12 | AI usage disclosure | ✅ | `docs/AI_USAGE.md`, including where the AI was wrong; pending reviews listed, not claimed |

## Headline results

- **Leaderboard** (rubric 1.4, 109 eval tasks × 3 rollouts):
  - Gemini 3.5 Flash-Lite +0.314; Groq gpt-oss-120b +0.566 (core10 subset);
  - baselines from naive_no_ceiling +0.249 down to always_abstain −0.737;
  - Qwen-0.5B base −0.652 → trained −0.331.
- **RL** (GRPO, Qwen2.5-0.5B + LoRA, β = 0.04), held out, scored once:
  - `heldout_easy` **+0.338 [+0.232, +0.442]**; full `heldout` **+0.304 [+0.201, +0.411]**;
  - learned: valid payslips, no refusing payable work;
  - lost: now answers every trap.
- **Reward gaming:** three exploits *learned by the policy* (refuse everything, broken JSON, invalid decision word), each closed in the rubric (1.1 → 1.4) and verified offline on the real outputs. The too-low β = 0.001 found the third; β = 0.04 never used it.
- **Track C:**
  - the scaffold is worth +0.21 for Qwen-3B, and the rules in the prompt give most of it at the lowest cost;
  - the model effect changes sign with the scaffold;
  - a frontier model is +0.80 above the 3B.
- **Spend:** $0 (free tiers + local RTX 5070 Ti).

## What is left

| When | Task | Who | Time |
|---|---|---|---|
| done | Reports: EVAL_REPORT, FAILURE_ANALYSIS, README, EDGE_CASES, TRADEOFFS, AI_USAGE, LOOM_SCRIPT | Claude | ✅ |
| any time | Environments Hub notes: browse 10–15 environments, give 3–5 observations on how they define reward (for `RESEARCH_NOTES.md`, brief §2) | you | ~30 min |
| after the quota reset (midnight US Pacific) | `./scripts/sweep.sh`: 12 missing hosted rollouts (2 Gemini 3.8 Flash, 10 Groq) | you run | ~5 min |
| after the top-up | Judge reliability: `uv run paygym judge items results/gemini__*/eval-single results/groq__*/core10-single && uv run paygym judge repeat` | you run, Claude analyses | ~20 min |
| after the reports | Review Claude's write-ups (failure categories, fidelity hand-check) | you | ~45 min |
| near the end | Clean-clone test: fresh clone → `uv sync` → tests → one eval → quickstart | you | ~20 min |
| last | Loom (8–12 min: ≥ 3 min reward design, ≥ 1 min a failure transcript, a live sandbox request), then the submission email | you | ~1 h |

## Open limitations (stated in the reports)

- The trained 0.5B does not learn trap refusal. Next step: a 1.5B policy.
- Gemini 3.8 Flash and Groq run on fixed subsets (core6 / core10) because of free-tier limits; they are compared paired on the same tasks.
- One seed per β, and no β above 0.04.
- Tool mode is evaluated but not trained (single-turn RL only).
