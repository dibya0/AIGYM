# AI usage disclosure (brief §9 #12)

The brief says this role is AI-native and asks for specific, honest disclosure. This is it, including where the AI was wrong.

## Tools used

- **Claude Code (Claude Opus 5.5) in VS Code,** on a Claude Pro subscription. Used as pair-programmer, researcher and reviewer throughout. No API credits were used for building.
- **Models the gym evaluates** (not used to build it), all on free tiers or local hardware: Gemini 3.5 Flash-Lite, 3.8 Flash and 3.1 Flash-Lite (Google AI Studio free tier); gpt-oss-120b (Groq free tier); Qwen2.5-0.5B / 3B (local vLLM on an RTX 5070 Ti). Gemini 3.1 Flash-Lite is also the LLM judge.

## Division of work

| | Claude Code | Me |
|---|---|---|
| Plan and scope | drafted the plan against the brief and checked each step against the brief's text before and after | chose the domain, the $0 / free-tier constraint, the local GPU, the 0.5B RL scope, Vercel hosting, the brief-minimum scope, and the speed-vs-headroom trade on free quotas |
| Code, tests, docs | wrote them, step by step, logged in `docs/PROGRESS.md` | reviewed and approved each step |
| Running | wrote the exact commands and expected output | ran everything: installs, driver and Docker setup, sweeps, training, held-out, Track C, the Vercel deploy and Upstash; pasted outputs back |
| Analysis | read transcripts and logs, proposed fixes, wrote the reports from committed files | questioned results ("is it the model or our implementation?", "is it alright?", "why empty fields?") that led to several of the fixes below |
| Library facts | read the *installed* source (TRL 1.14.1, verifiers 0.2.1, vLLM 0.30.0 settings) rather than relying on memory | |

## Where the AI was wrong, and how it was caught

Kept here deliberately: the record should show what the AI got wrong, not only what it got right. Each item is in `docs/PROGRESS.md` with evidence.

1. **"The policy learned to refuse in 5 steps."** I reported reward gaming at rubric 1.0 that was actually base-model behaviour under a mismatched training sampler. Caught when the user asked whether it was "the model or our implementation". Retracted in RL_REPORT B6, and the sampler was fixed (A12).
2. **Free-tier caps were guesses.** I set Gemini 120/day; the real limit for 3.8 Flash is 20. Groq bills ~1.4× the tokens it reports. Caught from the providers' 429s and the user's dashboards.
3. **Two fixes for a training crash were verified on reconstructed inputs, not on the failing call.** The real call (float32, no mask, grouped heads) only surfaced after adding logging of the failing call's shapes.
4. **A smoke test printed "OK" while every rollout had failed.** Caught by reading the output rather than the summary line, after which the runner refuses to report a run with zero successes as completed.
5. **The dashboard headlined a 6-task subset** ("Gemini 3.8 Flash best, 1.000"). Caught when the user asked why fields were empty.
6. **Track C's one-line verdict declared a winner from a tie** (+0.210 vs 0.209) whose model effect changes sign. Caught while writing the report.
7. **Smaller ones, each caught before it reached a report:**
   - a denominator error in the failure analysis (210 vs 270);
   - a README claim of "mutation checks" that do not exist;
   - TRL's silent LR decay;
   - a TPM guard that rejected every local request;
   - a test fake with the wrong error shape;
   - the sensitivity table's copy of the weighting drifting from the rubric.

## Where AI was deliberately *not* trusted

- **Ground truth never comes from a model.** It comes from the reference implementation, which is checked against:
  - hand calculations, enforced by `paygym validate`;
  - ~1,050 property and metamorphic cases;
  - the rule-set prose, through a fidelity audit (0/50 divergences).
- **Reward changes were never accepted on argument alone.** Each rubric revision (1.1 → 1.4) was checked offline against the trained policy's real outputs before any retraining.
- **The LLM judge scores only the genuinely unverifiable criterion** (trap explanations, 0.2 of a correct refusal), with a pinned model and a versioned prompt. Its reliability is measured by repeat disagreement.

## Human review still to do before submission

- [ ] Spot-check two of the fidelity audit's hand derivations against `RULESET.md`.
- [ ] Read the failure-analysis transcripts and confirm or correct the categories.
- [ ] Environments Hub notes (brief §2) for `docs/RESEARCH_NOTES.md`.
- [ ] Record the Loom.

*(These boxes are ticked only when done; nothing above claims a review that has not happened.)*
