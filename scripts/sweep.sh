#!/usr/bin/env bash
# Full evaluation sweep (brief Phase 05): >=3 model configs x 3 rollouts, plus adversarial baselines. $0.
#
# Free-tier limits (the user's dashboards, 2026-10-19) shape the design. Every hosted call goes through
# the daily ledger (paygym.eval.budget): caps = 75% of each model's free limit, requests AND tokens. A run
# that reaches its cap stops cleanly (exit 6) and the sweep moves on. RE-RUN THIS SCRIPT ONCE A DAY until
# it reports nothing left to run: finished rollouts are skipped, so nothing is ever paid twice.
#
#   model                    free limit              cap/day      what it runs                       days
#   gemini-3.5-flash-lite    500 req/day, 15/min     375 req      full eval (109 x 3) + tool mode     ~2
#   gemini-3.8-flash         20 req/day, 5/min       15 req       core20 subset x 3 (60 req)          ~4
#   groq gpt-oss-120b        200K tok/day, 8K/min    150K tok     core20 subset x 3 (~6k tok each)    ~3
#   judge 3.1-flash-lite     500 req/day             375 req      trap explanations only              -
#   local Qwen 3B / 0.5B     unlimited               -            full eval                           -
#
# The core20 subset (scripts/make_core_subset.py) is stratified and fixed in advance; every model is also
# scored on it, so the scarce models are compared paired, on identical tasks.
set -uo pipefail

SPLIT="--split eval --n-seeds 95"
COMMON="$SPLIT --rollouts 3 --seed 7 --max-cost 25"   # list-price cap; actual spend on free tiers is $0
CORE="--ids tasks/subsets/eval_core20.txt"
LITE="${LITE_MODEL:-gemini-3.5-flash-lite}"
FLASH="${GEMINI_MODEL:-gemini-3.8-flash}"
GROQ="${GROQ_MODEL:-openai/gpt-oss-120b}"

ev() {  # run one eval; a budget stop (6) or an unavailable provider (3) does not stop the sweep
  uv run python -m paygym.eval "$@"
  local c=$?
  case $c in
    0) ;;
    6) echo "   -> daily budget reached for this model; re-run the sweep tomorrow to continue" ;;
    3) echo "   -> provider unavailable; re-run later" ;;
    *) echo "   -> failed with exit $c"; exit $c ;;
  esac
}
resume() {  # continue an existing run directory instead of starting a fresh one
  local d="results/${1//\//__}/$2"
  [ -f "$d/config.json" ] && echo "--resume $d"
}

[ -f tasks/subsets/eval_core20.txt ] || uv run python scripts/make_core_subset.py

echo "== adversarial baselines (no model calls)"
for b in format_only always_abstain modal_answer naive_no_ceiling gross_as_net; do
  ev --model "baseline/$b" $COMMON --run-name eval-single $(resume "baseline/$b" eval-single)
done

echo "== Gemini Flash-Lite (frontier lab, highest free quota): full eval, single-turn"
ev --model "gemini/$LITE" $COMMON --run-name eval-single --judge $(resume "gemini/$LITE" eval-single)

echo "== Gemini 3.8 Flash (strongest Gemini on the free tier, 20 req/day): core20 subset"
ev --model "gemini/$FLASH" $COMMON $CORE --run-name core20-single --judge $(resume "gemini/$FLASH" core20-single)

echo "== Groq gpt-oss-120b (large open-weight; 200K tokens/day): core20 subset"
ev --model "groq/$GROQ" $COMMON $CORE --run-name core20-single --judge $(resume "groq/$GROQ" core20-single)

echo "== tool mode (tools are the only data source): Gemini Flash-Lite on core20"
echo "   (not on Groq: one tool-mode request exceeds its 8K tokens/minute limit, HTTP 413)"
ev --model "gemini/$LITE" $COMMON $CORE --mode tool --run-name core20-tool --judge $(resume "gemini/$LITE" core20-tool)

echo "== local open-weight models (start the server first, one model at a time):"
echo "   LLM_MODEL=Qwen/Qwen2.5-3B-Instruct LLM_SERVED_NAME=qwen2.5-3b docker compose --profile gpu up -d llm"
ev --model local/qwen2.5-3b $COMMON --run-name eval-single --concurrency 8 $(resume local/qwen2.5-3b eval-single)
ev --model local/qwen2.5-3b $COMMON --mode tool --run-name eval-tool --concurrency 8 $(resume local/qwen2.5-3b eval-tool)
echo "   LLM_MODEL=Qwen/Qwen2.5-0.5B-Instruct LLM_SERVED_NAME=qwen2.5-0.5b docker compose --profile gpu up -d llm"
ev --model local/qwen2.5-0.5b $COMMON --run-name eval-single --concurrency 8 $(resume local/qwen2.5-0.5b eval-single)

echo "== aggregate"
uv run paygym leaderboard
uv run python -m paygym.eval.sensitivity
cat results/.request_ledger.json 2>/dev/null
