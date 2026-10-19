#!/usr/bin/env bash
# Step 18: held-out before/after (brief p.12: "report before-and-after scores on tasks the policy never
# trained on"). Base Qwen2.5-0.5B vs the selected GRPO policy (best validation checkpoint), each scored ONCE
# on two never-trained sets, with the same harness, sampler (the model's generation_config, served by vLLM)
# and max tokens as training:
#   heldout_easy.jsonl  124 tasks, training preset, seeds 1000000+ : did the gym teach it something? (A13)
#   heldout.jsonl       109 tasks, full difficulty                  : does it transfer?
# Also writes the 0.5B base and trained leaderboard rows on the eval split (same settings as other models).
#
#   ./scripts/heldout_eval.sh [run]        # default run: grpo-b0.04 (selected in RL_REPORT A16)
# Needs Docker with GPU access (the vLLM service); run in a terminal where `docker ps` works without sudo.
set -euo pipefail
cd "$(dirname "$0")/.."

RUN="${1:-grpo-b0.04}"
RUN_DIR="results/train/$RUN"
EVAL="--rollouts 3 --seed 7 --max-tokens 384 --concurrency 16 --max-cost 25"

wait_ready() {  # until the vLLM server lists the model (first start of a model downloads it)
  echo "   waiting for vLLM to serve $1 ..."
  for _ in $(seq 1 120); do
    curl -s localhost:8000/v1/models 2>/dev/null | grep -q "\"$1\"" && { echo "   ready"; return 0; }
    sleep 5
  done
  echo "vLLM did not come up; see: docker compose logs llm | tail -30" >&2; exit 1
}

serve() {  # model path/id, served name
  docker compose --profile gpu down >/dev/null 2>&1 || true
  LLM_MODEL="$1" LLM_SERVED_NAME="$2" docker compose --profile gpu up -d llm
  wait_ready "$2"
}

if pgrep -f "\.venv/bin/python train/grpo_train.py" >/dev/null; then
  echo "training is still running: wait for it to finish (the GPU is needed)" >&2; exit 1
fi

echo "== 1. merge the best-validation checkpoint of $RUN"
cat "$RUN_DIR/best_checkpoint.json"; echo
[ -d "$RUN_DIR/merged" ] || uv run python scripts/merge_adapter.py "$RUN_DIR"

echo "== 2. base policy"
serve Qwen/Qwen2.5-0.5B-Instruct qwen2.5-0.5b
uv run python -m paygym.eval --model local/qwen2.5-0.5b --tasks tasks/generated/heldout_easy.jsonl $EVAL --run-name heldout-easy-base
uv run python -m paygym.eval --model local/qwen2.5-0.5b --tasks tasks/generated/heldout.jsonl      $EVAL --run-name heldout-base
uv run python -m paygym.eval --model local/qwen2.5-0.5b --split eval --n-seeds 95 --rollouts 3 --seed 7 --concurrency 16 \
    --run-name eval-single $( [ -f results/local__qwen2.5-0.5b/eval-single/config.json ] && echo --resume results/local__qwen2.5-0.5b/eval-single )

echo "== 3. trained policy ($RUN)"
NAME="qwen2.5-0.5b-$RUN"
serve "/results/train/$RUN/merged" "$NAME"
uv run python -m paygym.eval --model "local/$NAME" --tasks tasks/generated/heldout_easy.jsonl $EVAL --run-name heldout-easy
uv run python -m paygym.eval --model "local/$NAME" --tasks tasks/generated/heldout.jsonl      $EVAL --run-name heldout
uv run python -m paygym.eval --model "local/$NAME" --split eval --n-seeds 95 --rollouts 3 --seed 7 --concurrency 16 --run-name eval-single
docker compose --profile gpu down

echo "== 4. before/after with paired bootstrap CIs"
uv run python scripts/rl_summary.py --before results/local__qwen2.5-0.5b/heldout-easy-base \
    --after "$RUN=results/local__${NAME}/heldout-easy" --out results/train/rl_summary_heldout_easy.json
uv run python scripts/rl_summary.py --before results/local__qwen2.5-0.5b/heldout-base \
    --after "$RUN=results/local__${NAME}/heldout" --out results/train/rl_summary_heldout.json
uv run paygym leaderboard >/dev/null && echo "leaderboard updated"
