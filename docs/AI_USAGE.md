54.l;,.l# AI usage disclosure (brief §9 #12)

The brief says this role is AI-native and asks for specific, honest disclosure. This is it.

## Tools used
- **Claude Code (Claude Opus 5.5) in VS Code**, on a Claude Pro subscription. Used as a pair-programmer and research assistant throughout. No API credits were used for building.
- **Models evaluated by the gym** (not used to build it): Gemini (Google AI Studio free tier), gpt-oss-120b on Groq (free tier), and Qwen2.5 0.5B / 3B run locally. Gemini Flash is also the LLM judge.

## What Claude Code did
- **Planning and research.** Read the brief and drafted the plan with me; searched 2025–26 literature and docs and summarised them (`docs/RESEARCH_NOTES.md`):
  - GRPO variants;
  - the abstention-collapse result;
  - TRL defaults;
  - the verifiers v0→v1 change, found by inspecting the PyPI wheels;
  - free-tier hosting limits.
- **Implementation.** Wrote the code, tests and docs in this repo, step by step, against a requirements checklist. Each step was checked against the brief's text before and after, and logged in `docs/PROGRESS.md`.
- **Library verification.** Read the *installed* versions' source (TRL 1.14.1, verifiers 0.2.1) to confirm APIs, rather than relying on memory.
- **Self-review.** Every step was reviewed for defects before hand-off. The defects found and fixed are listed per step in `docs/PROGRESS.md`, so the record shows what the AI got wrong, not only what it got right.

## What I did
- **Decisions and approval:** chose the domain, the $0/free-tier constraint, the local GPU, the 0.5B-only RL scope, Vercel hosting and the step-by-step process; reviewed and approved each step.
- **Running everything:** installs, tests, eval sweeps, training, deployment, and pasting the outputs back for checking.
- **Human judgement the brief asks for:**
  - reviewed the rule book;
  - spot-checked the seed traps;
  - reviewed the fidelity audit's hand derivations;
  - hand-labelled the 15 judge outputs;
  - read the failure transcripts;
  - recorded the Loom.

## Where AI was deliberately *not* trusted
- **Ground truth never comes from a model.** It comes from the reference implementation, which is checked against hand calculations that are enforced by `paygym validate`, against property and metamorphic tests, and against the rule-set prose.
- **The LLM judge scores only the genuinely unverifiable criterion,** and its reliability is measured (repeat disagreement + agreement with my hand labels).
