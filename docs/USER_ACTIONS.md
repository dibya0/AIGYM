# Your action list

Things only you can do: accounts, hardware, long runs, deployments, judgement calls, recording. Claude implements everything else and verifies it against the brief as it goes. Tick items as you finish them, and paste any outputs back so they can be checked and recorded in `docs/PROGRESS.md`.

**Status key:** ☐ to do · ☑ done. **When** says which build step needs it.

---

## Minimum plan (brief thresholds only, chosen 2026-10-19 to show the full flow fast)

| Brief requirement (page) | Minimum | What we run |
|---|---|---|
| Hand-checked tasks, 3 tiers, Tier-3 traps (p.6) | ≥ 10, ≥ 3 traps | 16 seed tasks, 4 traps ✅ |
| Generated instances, non-degenerate distribution (p.8) | ≥ 100 | 529 generated ✅; distribution from the sweep |
| Model configs incl. one frontier + one small (p.10) | ≥ 3 | Gemini 3.5 Flash-Lite (full), Gemini 3.8 Flash (core6), Groq gpt-oss-120b (core10), Qwen 3B and 0.5B (local), 5 baselines |
| Rollouts per task, non-zero temperature (p.10) | ≥ 3 | 3 |
| Judge reliability (p.9) | 3 repeats **or** 15 hand labels | **3 repeats** (automatic); hand labels optional |
| Fidelity audit (p.9) | ≥ 10 tasks | 10 ✅ (0 / 50) |
| GRPO group size (p.11) | G ≥ 4 | G = 8 |
| β sweep, one too low (p.12) | ≥ 2 values | 0.001 and 0.04 |
| RL scope (p.12) | "0.5B over 30 training tasks", held-out before/after | 30 train tasks, 60 steps per β; held-out 109 tasks × 3 |
| Reward gaming (p.12) | ≥ 1 instance, or the documented search | transcript reading at each checkpoint |
| Track C (p.14) | model fixed, scaffold varied | local Qwen-3B × S0–S4 (no hosted quota) |
| Failure analysis (p.16) | 5–10 transcripts | 5 |
| Edge cases / trade-offs (p.16) | top 5 / ≥ 3 | 5 / 8 |
| Loom (p.16) | 8–12 min | ≈ 9 min |

## A. Now (unblocks everything)

| ☐ | Action | When | Notes |
|---|---|---|---|
| ☐ | **NVIDIA driver** for the RTX 5070 Ti: driver ≥ 570 with **open** kernel modules (580/595/610-open), and the kernel module loaded | Step 1 / 8 | Check: `nvidia-smi` shows the card. On 2026-10-17 the 580-open userspace was installed but no module was loaded for kernel `7.0.0-31`. |
| ☐ | **Install uv**: `curl -LsSf https://astral.sh/uv/install.sh \| sh` | Step 1 | |
| ☐ | **Run the Step 1 checks** (block below) and paste the output | Step 1 | Claude already verified the CPU part: `3 passed`, all extras lock (torch 2.13.0+cu129, verifiers 0.2.1), compose OK. |
| ☐ | `git init` in the project folder; create a GitHub repo (public, or private and shared with Niural) | Step 1 / 7 | Commit when you're ready; Claude doesn't commit unless asked. |

Step 1 check block:
```bash
cd /home/dibya/Documents/PROJECT/niural-task
uv sync --extra cpu && uv run pytest -q          # expect: all passed
uv sync --extra cpu --extra train
uv run python scripts/check_gpu.py               # expect: RTX 5070 Ti, sm_120, ~16 GiB, bf16 True, matmul ok
docker run --rm --gpus all nvidia/cuda:12.8.0-base-ubuntu24.04 nvidia-smi   # expect: GPU listed
```

## B. Accounts and keys (all free; put keys in `.env`, never commit it)

| ☐ | Action | When | Notes |
|---|---|---|---|
| ☐ | **Google AI Studio** API key → `GEMINI_API_KEY` | Step 11 (judge), Step 15 (eval) | Note which Gemini models your free tier lists, and their RPM/RPD limits (record them for `docs/TRADEOFFS.md`). |
| ☐ | **Groq** API key → `GROQ_API_KEY` | Step 15 | Note the free models and limits (look for `gpt-oss-120b`). |
| ☐ | **Vercel** account (Hobby), linked to the GitHub repo | Step 16 / 19 | |
| ☐ | **Upstash Redis** via the Vercel Marketplace (free) → `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN` | Step 19 | |
| ☐ | Generate `SANDBOX_SECRET`: `python -c "import secrets; print(secrets.token_hex(32))"` | Step 19 | Put the same value in `.env` and in the Vercel env vars. |
| ☐ | *(optional)* Hugging Face token → `HF_TOKEN` | Step 18 | Only to publish the trained LoRA adapter. |

## C. Reviews only you can do (graded as human judgement)

| ☐ | Action | When | Notes |
|---|---|---|---|
| ☐ | **Read and approve `ruleset/v1.0/RULESET.md`** (the fictional payroll rule book) | Step 2 | Is every rule unambiguous? The rule set is the ground truth; the code is only a claim about it. |
| ☐ | **Spot-check the seed tasks**, especially the 4 traps and their twins | Step 5 | Does each trap really fall under an "undetermined" clause? Is each twin really determinable? |
| ☐ | **Environments Hub review** (brief §2): browse 10–15 environments at app.primeintellect.ai (or `uvx prime env list`) and note how rigorous vs lazy ones define reward | Step 1b | Paste 3–5 observations; Claude writes `docs/RESEARCH_NOTES.md`. The Hub is a JavaScript app Claude can't read. |
| ☐ | **Fidelity audit**: confirm Claude's hand-check of 10 generated tasks against the rule-book prose | Step 13 | The brief asks for a *hand* check; your sign-off makes it genuine. |
| ☐ | **Hand-label 15 judge outputs** (pass/fail per checklist item) | Step 11 | Used for the judge-vs-human agreement figure. Claude prepares a labelling sheet. |
| ☐ | **Read 5–10 failed transcripts** with Claude's categorisation | Step 22 | The brief: "This deliverable reveals more about you than any other." |

## D. Long runs (Claude prepares exact commands and expected output)

| ☐ | Action | When | Approx. time |
|---|---|---|---|
| ☐ | RL smoke test (Qwen-0.5B, 20 tasks, 10 steps) | Step 8 | ~5–10 min |
| ☐ | Eval sweep: Gemini, Groq, local Qwen-3B / 0.5B, baselines × 3 rollouts | Step 15 | Hours, can span 2 days (free-tier limits); resumable |
| ☐ | Difficulty pilot + two GRPO runs (β = 0.001 and 0.04) | Step 17 | ~30–45 min each |
| ☐ | Held-out before/after eval of the best checkpoint | Step 18 | ~15 min |
| ☐ | Track C scaffold runs | Step 20 | ~1 h local + Gemini calls |

## E. Deploy and submit

| ☐ | Action | When |
|---|---|---|
| ☐ | Deploy dashboard + sandbox to Vercel; send Claude the live URL to verify | Step 16 / 19 / 21 |
| ☐ | Run the sandbox quickstart against the live URL | Step 19 |
| ☐ | Fresh-clone test on a clean directory | Step 23 |
| ☐ | Record the Loom (8–12 min) from `docs/LOOM_SCRIPT.md` | Step 24 |
| ☐ | Email repo link, dashboard URL, sandbox URL, Loom link with subject `AI Product Operator Assignment - [Your Name]` | Step 24 |

---

## F. "Run this" blocks per build step

Claude implements and reviews each step against the brief; you run these and paste the output back. ✅ = Claude already ran it in a scratch environment; ⏳ = waiting for you.

### Steps 1–4 (✅ already passed: 36 tests). Re-run anyway after `uv sync`:
```bash
uv sync --extra cpu
uv run pytest -q tests/test_package.py tests/test_ruleset.py tests/test_reference.py tests/test_reference_properties.py
# expect: 36 passed
```

### Step 5: task schema + seed tasks ⏳
```bash
uv run python scripts/build_seed_tasks.py      # expect: wrote 16 tasks to .../tasks/seed_v1.jsonl
uv run paygym validate tasks/                  # expect: 16 tasks | tier1=3 tier2=9 tier3=4 | traps=4 twins=4 | OK
uv run paygym schema | head -5                 # expect: start of the task JSON Schema
uv run pytest -q tests/test_tasks.py           # expect: 13 passed
```
If `validate` prints `ERROR ... hand check ...`, the hand-worked number and the reference disagree. Paste it; one of them has a bug, and the rule book decides which.

### Step 6: generator + audits ✅ (2026-10-19: 0 leaks, 0 dups; see PROGRESS)
```bash
uv run pytest -q tests/test_generator.py                                     # expect: 18 passed
uv run paygym generate --split eval    --seeds 95                             # expect: ~105-120 tasks, all 3 tiers
uv run paygym generate --split heldout --seeds 95
uv run paygym generate --split val     --seeds 36
uv run paygym generate --split train   --seeds 180                            # expect: no tier-1 tasks (by design)
uv run paygym validate tasks/                                                 # expect: ... | OK (seed + all generated sets)
uv run paygym audit tasks/generated/eval.jsonl  --out results/audit/eval.json
uv run paygym audit tasks/generated/train.jsonl --out results/audit/train.json
```
Paste the two `audit` summary lines. Expected:
- `literal leaks: 0`
- `exact dup cases: 0`
- classifier accuracy: anything is fine. If it is well above majority, Claude reads the top n-grams in the JSON to check they are genuine evidence (e.g. `gbp`, `2027`) and not template words, and writes the finding into the eval report.

### Step 7: CI ✅ (2026-10-19: repo github.com/dibya0/AIGYM, first run green)
The folder is not a git repo yet. Create an **empty** GitHub repo first (no README/licence, e.g. `paygym`), then:
```bash
uv lock                                       # CI uses --locked
git init -b main
git status --short | grep -E '\.env$' && echo "STOP: .env would be committed"   # must print nothing
git add -A && git commit -m "PayGym: rule set, reference, tasks, generator, audits"
git remote add origin git@github.com:dibya0/AIGYM.git   # or the https URL
git push -u origin main
```
Expect: the GitHub Actions run `ci` is green. It runs `paygym validate tasks/` and `pytest`. It needs `tasks/seed_v1.jsonl` and `tasks/generated/*.jsonl` committed (Steps 5–6).

### Step 8: RL smoke test on the RTX 5070 Ti ✅ (2026-10-19: 10 steps, ≈24 s/step, KL logged)
```bash
uv sync --extra cpu --extra train
uv run python scripts/check_gpu.py
uv run python train/grpo_train.py --reward smoke --tasks tasks/generated/train.jsonl \
    --n-tasks 20 --max-steps 10 --num-generations 4 --prompts-per-step 2 --beta 0.04 --run-name smoke
```
Expect: 10 steps complete; `results/train/smoke/metrics.csv` exists with columns including `kl`, `entropy`, `reward`, `completions/mean_length`, `frac_reward_zero_std` and `seconds_since_last_log`; `results/train/smoke/final_adapter/` exists.

Paste:
- the last 3 rows of `metrics.csv`: `column -s, -t < results/train/smoke/metrics.csv | tail -3`
- any error

Claude uses the measured seconds per step to size the real runs (Step 17). The smoke reward only checks the output format, so its numbers are **not** training results.

Optional vLLM check: `uv pip install vllm==0.30.0`, then re-run with `--use-vllm`. If it errors on sm_120, keep HF generation (slower, still fine at 0.5B).

### Step 9: tools + parser ⏳
```bash
uv run pytest -q tests/test_parser_tools.py      # expect: 14 passed
```

### Step 10: rubric + gating + baselines ⏳
```bash
uv run pytest -q tests/test_rubric.py      # expect: all passed (~100 incl. parametrised cases)
```
If `test_baseline_stays_under_its_floor[...]` fails, paste the message: it means a cheap strategy scores too well, i.e. the reward is exploitable, and the rubric needs fixing (that is the point of the test).

### Step 11: judge ⏳
```bash
uv run pytest -q tests/test_judge.py       # expect: 5 passed (no API key needed)
```
Then, with `GEMINI_API_KEY` in `.env`, check that your free tier can reach the judge model:
```bash
uv run --env-file .env python -c "from openai import OpenAI; import os; c=OpenAI(api_key=os.environ['GEMINI_API_KEY'], base_url='https://generativelanguage.googleapis.com/v1beta/openai/'); print([m.id for m in c.models.list()][:40])"
```
✅ 2026-10-19: model list pasted. Being listed does not mean a model has free quota, so probe the candidates with **one ~10-token request each** (5 requests total, counted in the daily ledger):
```bash
uv run --env-file .env python scripts/probe_models.py gemini/gemini-3.8-flash gemini/gemini-3.1-pro-preview gemini/gemini-4-argon gemini/gemma-4-31b-it groq/openai/gpt-oss-120b
```
Also open **AI Studio → Dashboard → Usage / Rate limits** (costs no requests) and note the requests-per-day for the models that answered OK. Paste both. Claude picks the eval model and the judge model from them, and sets the daily caps under those limits. The reliability runs (3 repeats + your 15 hand labels) happen after the eval sweep (Step 15), because they need real model refusals to judge.

### Step 12: verifiers environment ✅ (2026-10-19: single-turn on Groq 0 errors; tool mode on Gemini works, 8–17 tool calls per rollout)
```bash
uv sync --extra cpu                       # cpu includes the env extra (verifiers 0.2.1)
uv run pytest -q tests/test_environment.py tests/test_rubric.py    # expect: all passed
uv run python -c "import verifiers as vf; e = vf.load_environment('paygym', mode='tool', n_seeds=20); print(type(e).__name__, len(e.get_dataset()))"
# expect: PaygymToolEnv <~22>
```
Smoke eval through **verifiers' own runner**, to prove portability. 5 tasks per mode, and no Gemini 3.8 Flash quota used:
- **single-turn on Groq:** 5 requests, ~25K tokens;
- **tool mode on Gemini 3.5 Flash-Lite:** ~25 requests. Groq cannot do tool mode: one request exceeds its 8K tokens/minute limit, HTTP 413.
```bash
uv run --env-file .env python - <<'PY'
import verifiers as vf
from verifiers.types import ClientConfig
groq = ClientConfig(api_key_var="GROQ_API_KEY", api_base_url="https://api.groq.com/openai/v1", max_retries=3, timeout=120)
gem = ClientConfig(api_key_var="GEMINI_API_KEY", api_base_url="https://generativelanguage.googleapis.com/v1beta/openai/", max_retries=3, timeout=120)
for mode, client, model, sampling in (("single", groq, "openai/gpt-oss-120b", {"max_tokens": 3000}),
                                      ("tool", gem, "gemini-3.5-flash-lite", {"max_tokens": 4096})):
    env = vf.load_environment("paygym", mode=mode, n_seeds=5)
    out = env.evaluate_sync(client=client, model=model, sampling_args=sampling, num_examples=5, rollouts_per_example=1, max_concurrent=1)
    rows = out["outputs"]
    errors = [r.get("error") for r in rows if r.get("error")]
    print(mode, model, "rewards:", [round(r.get("reward") or 0, 3) for r in rows], "| errors:", len(errors), errors[:1])
PY
```
**Expected:** `errors: 0` on both lines, with no `Aborted rollout` lines; rewards may be anything. Pauses are normal.

History (logged in PROGRESS):
- 1st run: printed "OK" while every rollout had aborted (Groq `service_tier`), so the snippet now prints errors.
- 2nd run: tool mode failed with Groq 400 `reasoning_content`.
- 3rd run: tool mode hit Groq 413 (request too large for 8K TPM), so tool mode moved to Gemini Flash-Lite.

Paste both lines. The `evaluate_sync` / `ClientConfig` signature was checked against the installed verifiers 0.2.1 on 2026-10-19.

### Step 13: fidelity audit worksheet ✅ (2026-10-19: 0/50 divergences; your review of the hand working is pending, §C)
```bash
uv run python scripts/fidelity_sample.py      # expect: wrote docs/FIDELITY_AUDIT.md with 10 tasks
```
Then tell Claude "fidelity worksheet ready". Claude hand-derives all 10 from the RULESET.md prose (Part 1) before reading Part 2, fills in the divergence rate, and fixes any bug found. You then review Claude's hand working (the brief asks for a *hand* check; your review makes it genuine; see §C).

### Step 14: eval harness ✅ (2026-10-19: Groq + Gemini real runs, resume shown; transcript JSON + gpt-oss truncation fixed)
Uses about 3 Groq rollouts (~18K tokens) and about 16 Flash-Lite requests. Gemini 3.8 Flash is not used.
```bash
uv run pytest -q tests/test_eval_harness.py      # expect: all passed (no network; baselines + a fake model)
# our own runner on real providers: single-turn on Groq, tool mode on Gemini Flash-Lite
uv run python -m paygym.eval --model groq/openai/gpt-oss-120b --limit 2 --rollouts 1 --run-name smoke-single
uv run python -m paygym.eval --model gemini/gemini-3.5-flash-lite --mode tool --limit 2 --rollouts 1 --run-name smoke-tool
ls results/groq__openai__gpt-oss-120b/smoke-single/      # expect: config.json metrics.json scores.json transcript.jsonl
cat results/.request_ledger.json                          # today's requests/tokens per model
```
**Resume demo** (a baseline, so no quota is used). Baselines finish in seconds, so Ctrl-C is optional. Either way the second command should print "N already done, 0 to run" (or the remainder if you interrupted): finished rollouts are never redone.
```bash
uv run python -m paygym.eval --model baseline/naive_no_ceiling --rollouts 3 --run-name resume-demo
uv run python -m paygym.eval --model baseline/naive_no_ceiling --rollouts 3 --resume results/baseline__naive_no_ceiling/resume-demo
```
Paste:
- the first lines each eval prints (the budget line and the task count);
- `cat results/groq__openai__gpt-oss-120b/smoke-single/metrics.json` and `cat results/gemini__gemini-3.5-flash-lite/smoke-tool/metrics.json`;
- the ledger.

### Step 15: full eval sweep ⏳ (hosted part ≈ 1 day; runs in parallel with the GPU work)
**Sized to finish in about a day.** The user asked for speed over a 4-day sweep. Every model is capped at **90%** of its free limit, on requests and tokens:

| Model | Free limit | Cap/day | Runs | Fits |
|---|---|---|---|---|
| gemini-3.5-flash-lite | 500 req/day | 450 | full eval 109×3 (327) + tool mode on core10 ×3 (~240) | today + small tail |
| gemini-3.8-flash | **20 req/day** | 18 | core6 ×3 (18) | today |
| groq gpt-oss-120b | **200K tokens/day** | 180K | core10 ×3 (~165K) | today |
| gemini-3.1-flash-lite (judge) | 500 req/day | 450 | trap explanations | today |
| local Qwen 3B / 0.5B | unlimited | – | full eval (+ tool mode for 3B) | hours |

Older Gemini models do not help: 2.5 / 3 / 3.6 / 3.7 Flash are all 20 req/day on this key. Only the Flash-Lite models (500) and Gemma (14.4K, but it returned HTTP 500 twice) have more.

The subsets are nested (`tasks/subsets/eval_core{6,10,20}.txt`), fixed before any model was scored, and every trap comes with its twin. Every other model is also scored on the same tasks, so the comparisons are paired.

**If a model hits its cap,** re-run the same command after midnight US Pacific, when the quotas reset; it continues where it stopped.

```bash
GEMINI_MODEL=<strongest free Gemini id from your Step 11 list> ./scripts/sweep.sh
```
- **Re-running is safe.** Each run lives in `results/<model>/<run-name>/`; re-running the same command finds the existing `config.json` and continues where it stopped, so nothing is paid twice.
- **Local Qwen runs need the vLLM server** (commands printed by the script). If vLLM fails on the 5070 Ti, paste the error; the fallback is an HF-transformers server.

Then:
```bash
uv run paygym judge items results/gemini__*/eval-single results/groq__*/eval-single   # real refusals for the judge
uv run paygym judge repeat                     # 3-repeat disagreement rate: the brief's minimum (p.9)
```
*Optional* (the brief accepts either method): `uv run paygym judge labels`, fill `human_pass` in `docs/judge_labels.csv` for 15 outputs without looking at `judge_pass`, then `uv run paygym judge agreement`.

Paste: the `paygym leaderboard` output, the `sensitivity` output, the judge disagreement rate and the agreement report.

### Step 16: dashboard v1 ⏳
```bash
uv run pytest -q tests/test_dashboard.py                    # expect: 1 passed
uv run python -m paygym.dashboard.build                     # after the Step 15 sweep; writes public/index.html + public/data/*.json
docker compose --profile dashboard up dashboard             # preview at http://localhost:8080
```
Deploy: commit `public/` and push; Vercel (linked to the repo) serves it as-is. The API config lands in Step 19. Send Claude the live URL to verify each P06 item on the deployed page.

### Step 17: RL pilot + the two β runs ⏳ (GPU, ≈ 1.5 h total; brief-minimum scope)
**Scope = the brief's own minimum** (p.12: "a working loop on a 0.5B model over 30 training tasks, with real curves and an honest held-out comparison"): 30 training tasks, G = 8 (brief ≥ 4), two β values (one deliberately too low), 60 steps each. The LR probe is dropped: the brief does not require it (RL_REPORT A10).

**0. One-time Docker permission fix** (the `permission denied … docker.sock` error):
```bash
sudo usermod -aG docker $USER && newgrp docker      # or log out and back in
docker ps                                           # must work without sudo
```

**1. Pilot** (base 0.5B, 30 train tasks × 4 samples, ~5 min). It checks that the tasks are neither impossible nor trivial for the base model:
```bash
LLM_MODEL=Qwen/Qwen2.5-0.5B-Instruct LLM_SERVED_NAME=qwen2.5-0.5b docker compose --profile gpu up -d llm
docker compose logs -f llm      # wait for "Application startup complete", then Ctrl-C (server keeps running)
uv run python -m paygym.eval --model local/qwen2.5-0.5b --tasks tasks/generated/train.jsonl --tier 2,3 --limit 30 \
    --rollouts 4 --max-tokens 384 --concurrency 16 --run-name pilot-default
uv run python scripts/pilot_report.py results/local__qwen2.5-0.5b/pilot-default
```
First delete today's broken pilot directory (400 error rows from a bug since fixed): `rm -rf results/local__qwen2.5-0.5b/pilot-default`.
If the report says "too hard", use the easier preset and pilot again:
```bash
uv run paygym generate --split train --seeds 180 --knobs easy --out tasks/generated/train_easy.jsonl
uv run python -m paygym.eval --model local/qwen2.5-0.5b --tasks tasks/generated/train_easy.jsonl --tier 2,3 --limit 30 \
    --rollouts 4 --max-tokens 384 --concurrency 16 --run-name pilot-easy
uv run python scripts/pilot_report.py results/local__qwen2.5-0.5b/pilot-easy
```
Paste the report. Claude names the train file (`TRAIN=…`).

**2. The two β runs** (free the GPU first; ≈ 30–40 min each):
```bash
docker compose --profile gpu down
for B in 0.001 0.04; do
  uv run python train/grpo_train.py --reward rubric --tasks $TRAIN --n-tasks 30 --beta $B \
      --max-steps 60 --num-generations 8 --prompts-per-step 2 --val-every 20 --save-steps 20 --run-name grpo-b$B
done
```
A crashed run resumes with the same command plus `--resume`.

Paste for each run:
- `cat results/train/<run>/stop_reason.json` (if present)
- `cat results/train/<run>/best_checkpoint.json`
- `tail -5 results/train/<run>/validation.csv`


### Step 18: held-out before/after ⏳ (after Step 17)
```bash
# base policy on held-out (scored once)
LLM_MODEL=Qwen/Qwen2.5-0.5B-Instruct LLM_SERVED_NAME=qwen2.5-0.5b docker compose --profile gpu up -d llm
uv run python -m paygym.eval --model local/qwen2.5-0.5b --tasks tasks/generated/heldout.jsonl --rollouts 3 --max-tokens 384 --concurrency 16 --run-name heldout-base
docker compose --profile gpu down
# each trained run: merge its best-validation checkpoint, serve it, score it on the same held-out file
for RUN in grpo-b0.001 grpo-b0.04; do
  uv run python scripts/merge_adapter.py results/train/$RUN
  LLM_MODEL=/results/train/$RUN/merged LLM_SERVED_NAME=qwen2.5-0.5b-$RUN docker compose --profile gpu up -d llm
  uv run python -m paygym.eval --model local/qwen2.5-0.5b-$RUN --tasks tasks/generated/heldout.jsonl --rollouts 3 --max-tokens 384 --concurrency 16 --run-name heldout
  docker compose --profile gpu down
done
uv run python scripts/rl_summary.py --before results/local__qwen2.5-0.5b/heldout-base \
  --after b0.001=results/local__qwen2.5-0.5b-grpo-b0.001/heldout --after b0.04=results/local__qwen2.5-0.5b-grpo-b0.04/heldout
```
If `merge_adapter.py` says best_step=0 for a run, skip its eval: no checkpoint beat the base on validation, which is itself a result. Then tell Claude "RL results ready". Claude reads the samples, hunts for reward gaming, and writes Part B of `docs/RL_REPORT.md`.

### Step 19: sandbox ⏳
```bash
uv run pytest -q tests/test_sandbox.py                     # expect: 9 passed (incl. the ground-truth leak fuzz test + parity)
docker compose --profile sandbox up -d --build sandbox redis
python3 scripts/quickstart.py http://localhost:8001        # expect: health, a run id, mean reward, per-task score/clause/breakdown
```
Deploy on Vercel (Hobby, free):
1. Import the GitHub repo in Vercel; framework preset **Other**. No build command: `public/` is static and `api/index.py` is the function.
2. Storage → Upstash Redis (free) via the Marketplace. This adds `UPSTASH_REDIS_REST_URL` / `UPSTASH_REDIS_REST_TOKEN`.
3. Environment variables: `SANDBOX_SECRET` (the same 64-hex value as your `.env`), `GEMINI_API_KEY` (optional; enables the judge on trap explanations).
4. Deploy, then run the reviewer's one-liner: `curl -s https://<project>.vercel.app/quickstart.py | python3 - https://<project>.vercel.app` (the dashboard build copies `quickstart.py` into `public/`). Paste the output.

If Vercel rejects the Python function (bundle or runtime errors), paste the build log.

### Step 20: Track C, scaffold comparison ⏳ (local GPU only, no hosted quota)
**Minimum per the brief (p.14):** hold the model constant and vary the scaffold. The model is local **Qwen2.5-3B** at S0–S4 on the full eval set. "Does the scaffold matter more than the model?" is answered by comparing:
- the scaffold effect: 3B from S0 to S4;
- the model effect: 0.5B → 3B → the hosted models, at the default scaffold (the sweep's paired rows).
```bash
LLM_MODEL=Qwen/Qwen2.5-3B-Instruct LLM_SERVED_NAME=qwen2.5-3b docker compose --profile gpu up -d llm
for S in S0 S1 S2 S3 S4; do
  uv run python -m paygym.eval --model local/qwen2.5-3b --scaffold $S --split eval --n-seeds 95 --rollouts 3 --concurrency 8 --run-name trackc-$S
done
docker compose --profile gpu down
LLM_MODEL=Qwen/Qwen2.5-0.5B-Instruct LLM_SERVED_NAME=qwen2.5-0.5b docker compose --profile gpu up -d llm
for S in S0 S4; do   # the comparison model at matched scaffolds
  uv run python -m paygym.eval --model local/qwen2.5-0.5b --scaffold $S --split eval --n-seeds 95 --rollouts 3 --concurrency 16 --run-name trackc-$S
done
uv run python scripts/track_c.py --small local/qwen2.5-3b --compare local/qwen2.5-0.5b
```
Paste the printed finding. Claude writes `docs/TRACK_C.md` from `results/track_c/summary.json`.

### Step 21: dashboard v2 ⏳ (after Steps 17–20)
```bash
uv run paygym leaderboard
uv run python -m paygym.dashboard.build --sandbox-url https://<project>.vercel.app
git add public results docs && git commit -m "results + dashboard" && git push   # Vercel redeploys
```
Send Claude the URL. Claude checks every P06/P07 item on the live page: leaderboard, tiers, reward functions, heatmap, transcripts, cost, RL curves, Track C, external runs.

### Step 22: reports ⏳ (Claude writes; you review)
Tell Claude "results ready". Claude fills `EVAL_REPORT.md`, `FAILURE_ANALYSIS.md` (you read the 5–10 transcripts too), `TRACK_C.md`, `RL_REPORT.md` Part B and `FIDELITY_AUDIT.md` from the committed result files, and replaces the README's `<project>` URLs.

### Step 23: clean-clone test ⏳
```bash
cd /tmp && rm -rf paygym-check && git clone <repo-url> paygym-check && cd paygym-check
cp /path/to/your/.env . && uv sync --extra cpu && uv run pytest -q && uv run paygym validate tasks/
python3 scripts/quickstart.py https://<project>.vercel.app
```
Expected: all tests pass and the quickstart scores. Paste any failure.

### Step 24: Loom + submission ⏳
- Record 8–12 min following `docs/LOOM_SCRIPT.md`.
- Email repo link, dashboard URL, sandbox URL (`/api/docs`) and Loom link. Subject: `AI Product Operator Assignment - [Your Name]`.
