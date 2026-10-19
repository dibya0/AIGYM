#!/usr/bin/env bash
# Full evaluation sweep (brief Phase 05): >=3 model configs x 3 rollouts, plus adversarial baselines.
# All free: Gemini (AI Studio free tier), Groq (free tier), local Qwen on the RTX 5070 Ti, baselines (no model).
# Every command is resumable: if one stops (rate limit, Ctrl-C), re-run it with --resume <run dir>.
set -euo pipefail

SPLIT="--split eval --n-seeds 95"
COMMON="$SPLIT --rollouts 3 --seed 7 --max-cost 25"   # list-price cap; actual spend on free tiers is $0
GEMINI_MODEL="${GEMINI_MODEL:-gemini-flash-latest}"    # set to the strongest free Gemini model on your key
GROQ_MODEL="${GROQ_MODEL:-openai/gpt-oss-120b}"

echo "== adversarial baselines (no model calls)"
for b in format_only always_abstain modal_answer naive_no_ceiling gross_as_net; do
  uv run python -m paygym.eval --model "baseline/$b" $COMMON --run-name eval-single
done

echo "== frontier (Gemini) and large open-weight (Groq): single-turn, all tiers"
uv run python -m paygym.eval --model "gemini/$GEMINI_MODEL" $COMMON --run-name eval-single --judge
uv run python -m paygym.eval --model "groq/$GROQ_MODEL"     $COMMON --run-name eval-single --judge

echo "== tool mode on a 50-task subset (tools are the only data source)"
uv run python -m paygym.eval --model "gemini/$GEMINI_MODEL" $COMMON --mode tool --limit 50 --run-name eval-tool --judge
uv run python -m paygym.eval --model "groq/$GROQ_MODEL"     $COMMON --mode tool --limit 50 --run-name eval-tool --judge

echo "== local open-weight models (start the server first, one model at a time):"
echo "   LLM_MODEL=Qwen/Qwen2.5-3B-Instruct LLM_SERVED_NAME=qwen2.5-3b docker compose --profile gpu up -d llm"
uv run python -m paygym.eval --model local/qwen2.5-3b   $COMMON --run-name eval-single --concurrency 8 || echo "start the 3B server and re-run"
echo "   LLM_MODEL=Qwen/Qwen2.5-0.5B-Instruct LLM_SERVED_NAME=qwen2.5-0.5b docker compose --profile gpu up -d llm"
uv run python -m paygym.eval --model local/qwen2.5-0.5b $COMMON --run-name eval-single --concurrency 8 || echo "start the 0.5B server and re-run"

echo "== aggregate"
uv run paygym leaderboard
uv run python -m paygym.eval.sensitivity
