#!/usr/bin/env bash
# Full evaluation sweep (brief Phase 05): >=3 model configs x 3 rollouts, plus adversarial baselines.
# All free: Gemini (AI Studio free tier), Groq (free tier), local Qwen on the RTX 5070 Ti, baselines (no model).
#
# Free-quota protection: every hosted call is counted in a daily per-model request ledger
# (paygym.eval.budget; defaults gemini 120/day, groq 400/day, override with PAYGYM_DAILY_CAP). A run that
# reaches its cap stops cleanly (exit 6) and the sweep moves on to the next model. Re-run this script the
# next day: finished rollouts are skipped, so nothing is ever paid twice.
#
# Quota plan: Gemini (the scarcest quota) does single-turn only; Groq (larger quota) also does tool mode
# and is the Track C large-model comparison; local Qwen is unlimited.
set -uo pipefail

SPLIT="--split eval --n-seeds 95"
COMMON="$SPLIT --rollouts 3 --seed 7 --max-cost 25"   # list-price cap; actual spend on free tiers is $0
GEMINI_MODEL="${GEMINI_MODEL:-gemini-flash-latest}"    # set from scripts/probe_models.py
GROQ_MODEL="${GROQ_MODEL:-openai/gpt-oss-120b}"

ev() {  # run one eval; a budget stop (6) or an unavailable provider (3) does not stop the sweep
  uv run python -m paygym.eval "$@"
  local c=$?
  case $c in
    0) ;;
    6) echo "   -> daily request budget reached for this model; re-run the sweep tomorrow to continue" ;;
    3) echo "   -> provider unavailable; re-run later" ;;
    *) echo "   -> failed with exit $c"; exit $c ;;
  esac
}
resume_flag() {  # continue an existing run directory instead of starting a fresh one
  local d="results/${1//\//__}/$2"
  [ -f "$d/config.json" ] && echo "--resume $d"
}

echo "== adversarial baselines (no model calls)"
for b in format_only always_abstain modal_answer naive_no_ceiling gross_as_net; do
  ev --model "baseline/$b" $COMMON --run-name eval-single $(resume_flag "baseline/$b" eval-single)
done

echo "== frontier (Gemini): single-turn, all tiers"
ev --model "gemini/$GEMINI_MODEL" $COMMON --run-name eval-single --judge $(resume_flag "gemini/$GEMINI_MODEL" eval-single)

echo "== large open-weight (Groq): single-turn, then tool mode on a 50-task subset (tools are the only data source)"
ev --model "groq/$GROQ_MODEL" $COMMON --run-name eval-single --judge $(resume_flag "groq/$GROQ_MODEL" eval-single)
ev --model "groq/$GROQ_MODEL" $COMMON --mode tool --limit 50 --run-name eval-tool --judge $(resume_flag "groq/$GROQ_MODEL" eval-tool)

echo "== local open-weight models (start the server first, one model at a time):"
echo "   LLM_MODEL=Qwen/Qwen2.5-3B-Instruct LLM_SERVED_NAME=qwen2.5-3b docker compose --profile gpu up -d llm"
ev --model local/qwen2.5-3b $COMMON --run-name eval-single --concurrency 8 $(resume_flag local/qwen2.5-3b eval-single)
echo "   LLM_MODEL=Qwen/Qwen2.5-0.5B-Instruct LLM_SERVED_NAME=qwen2.5-0.5b docker compose --profile gpu up -d llm"
ev --model local/qwen2.5-0.5b $COMMON --run-name eval-single --concurrency 8 $(resume_flag local/qwen2.5-0.5b eval-single)

echo "== aggregate"
uv run paygym leaderboard
uv run python -m paygym.eval.sensitivity
cat results/.request_ledger.json 2>/dev/null
