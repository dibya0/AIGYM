#!/usr/bin/env bash
# Full evaluation sweep (brief Phase 05): >=3 model configs x 3 rollouts, plus adversarial baselines. $0.
#
# Sized so the hosted part finishes TODAY (user request). Every hosted call goes through the daily ledger
# (paygym.eval.budget; caps = 90% of each model's free limit, requests AND tokens). A run that reaches its
# cap stops cleanly (exit 6) and the sweep moves on; re-running continues where it stopped (quotas reset
# at midnight US Pacific). Nothing is ever paid twice.
#
#   model                    free limit              cap/day      runs                                  fits in
#   gemini-3.5-flash-lite    500 req/day, 15/min     450 req      full eval 109 x 3 (327 req)            today
#   gemini-3.8-flash         20 req/day, 5/min       19 req (*)   core6 x 3 (18 req)                     today
#   groq gpt-oss-120b        200K tok/day, 8K/min    180K tok     core10 x 3 (~5.5K tok each)            today
#   gemini-3.1-flash-lite    500 req/day, 15/min     450 req      judge (~200) + tool mode core6 x 3     today
#                                                                 (~8 requests per tool rollout ≈ 144)
#   local Qwen 0.5B          unlimited               -            full eval, single-turn                 minutes (GPU)
#   (local Qwen 3B: via Track C, Step 20; its S1/S2 runs are its single/tool leaderboard rows)
#   (*) 18 rollouts + the 1 probe request already spent today = 19 of Google's 20.
# Tool mode costs ~8 requests per rollout (one per model turn; Step 14 measured 11 tool calls per rollout),
# so the hosted tool-mode run is the small core6 on a model whose quota only the judge uses; full-coverage
# tool mode comes from local Qwen-3B.
#   local Qwen 3B / 0.5B     unlimited               -            full eval (+ tool mode for 3B)         hours (GPU)
#
# Subsets are nested (core6 ⊂ core10 ⊂ core20, scripts/make_core_subset.py), fixed before any model was
# scored, and every trap comes with its twin. The leaderboard compares a subset run only with every
# other model's rollouts on the same tasks (paired).
set -uo pipefail

SPLIT="--split eval --n-seeds 95"
COMMON="$SPLIT --rollouts 3 --seed 7 --max-cost 25"   # list-price cap; actual spend on free tiers is $0
LITE="${LITE_MODEL:-gemini-3.5-flash-lite}"
FLASH="${GEMINI_MODEL:-gemini-3.8-flash}"
GROQ="${GROQ_MODEL:-openai/gpt-oss-120b}"

ev() {  # run one eval; a budget stop (6) or an unavailable provider (3) does not stop the sweep
  uv run python -m paygym.eval "$@"
  local c=$?
  case $c in
    0) ;;
    6) echo "   -> daily budget reached for this model; re-run after midnight US Pacific to finish" ;;
    3) echo "   -> provider unavailable (for local models: start the vLLM server); re-run later" ;;
    4) echo "   -> refused to resume (config changed); run: uv run paygym rescore, then re-run" ;;
    *) echo "   -> failed with exit $c"; exit $c ;;
  esac
}
resume() {  # continue an existing run directory instead of starting a fresh one
  local d="results/${1//\//__}/$2"
  [ -f "$d/config.json" ] && echo "--resume $d"
}

[ -f tasks/subsets/eval_core6.txt ] || uv run python scripts/make_core_subset.py
# Rubric 1.1 (2026-10-19): bring finished runs scored under an older rubric up to date ($0, no model calls),
# so the leaderboard never mixes versions and resumed runs pass the version check.
uv run paygym rescore >/dev/null

echo "== adversarial baselines (no model calls)"
for b in format_only always_abstain modal_answer naive_no_ceiling gross_as_net; do
  ev --model "baseline/$b" $COMMON --run-name eval-single $(resume "baseline/$b" eval-single)
done

echo "== Gemini 3.5 Flash-Lite (frontier lab, highest free quota): full eval, single-turn"
ev --model "gemini/$LITE" $COMMON --run-name eval-single --judge $(resume "gemini/$LITE" eval-single)

echo "== Gemini 3.8 Flash (strongest Gemini on the free tier, 20 req/day): core6"
# One request at a time and a long timeout: at 4 req/min, queued requests wait inside the rollout's clock, and
# with concurrency 4 that turned 10 of 18 rollouts into empty timeouts (2026-10-19).
ev --model "gemini/$FLASH" $COMMON --ids tasks/subsets/eval_core6.txt --daily-request-cap 19 --concurrency 1 --timeout 600 \
   --run-name core6-single --judge $(resume "gemini/$FLASH" core6-single)

echo "== Groq gpt-oss-120b (large open-weight; 200K tokens/day): core10"
ev --model "groq/$GROQ" $COMMON --ids tasks/subsets/eval_core10.txt --run-name core10-single --judge $(resume "groq/$GROQ" core10-single)

TOOLM="${TOOL_MODEL:-gemini-3.1-flash-lite}"
echo "== hosted tool mode (tools are the only data source): Gemini 3.1 Flash-Lite on core6"
echo "   (not on Groq: one tool-mode request exceeds its 8K tokens/minute limit, HTTP 413)"
ev --model "gemini/$TOOLM" $COMMON --ids tasks/subsets/eval_core6.txt --mode tool --run-name core6-tool --judge $(resume "gemini/$TOOLM" core6-tool)

echo "== local open-weight models (start the server first, one model at a time):"
echo "   (Qwen-3B's leaderboard rows come from its Track C runs: S1 and S2 send exactly the default single/tool"
echo "    prompts, so they are the same configuration; see docs/USER_ACTIONS.md Step 20)"
echo "   LLM_MODEL=Qwen/Qwen2.5-0.5B-Instruct LLM_SERVED_NAME=qwen2.5-0.5b docker compose --profile gpu up -d llm"
ev --model local/qwen2.5-0.5b $COMMON --run-name eval-single --concurrency 8 $(resume local/qwen2.5-0.5b eval-single)

echo "== aggregate"
uv run paygym leaderboard
uv run python -m paygym.eval.sensitivity
cat results/.request_ledger.json 2>/dev/null
