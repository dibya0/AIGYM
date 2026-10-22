# AI usage disclosure (brief §9 #12)

The brief says this role is AI-native and asks for specific, honest disclosure. This is it.

## Tools used

- **Claude Code (Claude Opus 5.5) in VS Code,** on a Claude Pro subscription. Used as pair-programmer, researcher and reviewer throughout. No API credits were used for building.
- **Models the gym evaluates** (not used to build it), all on free tiers or local hardware: Gemini 3.5 Flash-Lite, 3.8 Flash and 3.1 Flash-Lite (Google AI Studio free tier); gpt-oss-120b (Groq free tier); Qwen2.5-0.5B / 3B (local vLLM on an RTX 5070 Ti). Gemini 3.1 Flash-Lite is also the LLM judge.

## Division of work

| | Claude Code | Me |
|---|---|---|
| Plan and scope | drafted the plan against the brief and checked each step against the brief's text before and after | chose the domain, the $0 / free-tier constraint, the local GPU, the 0.5B RL scope, Vercel hosting, the brief-minimum scope, and the speed-vs-headroom trade on free quotas |
| Code, tests, docs | wrote them, step by step, logged in `docs/PROGRESS.md` | reviewed and approved each step |
| Running | wrote the exact commands and expected output | ran everything: installs, driver and Docker setup, sweeps, training, held-out, Track C, the Vercel deploy and Upstash; pasted outputs back |
| Analysis | read transcripts and logs, proposed fixes, wrote the reports from committed files | questioned results, which led to several fixes (logged in `docs/PROGRESS.md`) |
| Library facts | read the *installed* source (TRL 1.14.1, verifiers 0.2.1, vLLM 0.30.0 settings) rather than relying on memory | read the brief's background links (the verifiers library, the Prime Intellect environments docs, Harvey LAB's README and architecture) and checked the explanations of how each was used |
| Research | surveyed the 2025–26 literature on RL rewards and abstention, and the hosting options (`docs/RESEARCH_NOTES.md`) | browsed 10–15 Environments Hub environments and picked the three written up in RESEARCH_NOTES; both compared their reward designs with PayGym's |
