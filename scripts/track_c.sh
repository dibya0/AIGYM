#!/usr/bin/env bash
# Step 20, Track C (brief §7): hold the model constant and vary the agent scaffold; show whether the scaffold
# matters more than the model. Inference only, local vLLM, no hosted quota.
#   fixed model   Qwen2.5-3B-Instruct at S0-S4 on the full eval split (S1/S2 double as its leaderboard rows)
#   comparison    Qwen2.5-0.5B-Instruct at S0 and S4 (matched scaffolds: the model effect)
#
#   sg docker -c ./scripts/track_c.sh         # resumable: re-running skips finished rollouts
set -euo pipefail
cd "$(dirname "$0")/.."

wait_ready() {
  echo "   waiting for vLLM to serve $1 (first start of the 3B downloads ~6 GB) ..."
  for _ in $(seq 1 240); do
    curl -s localhost:8000/v1/models 2>/dev/null | grep -q "\"$1\"" && { echo "   ready"; return 0; }
    sleep 5
  done
  echo "vLLM did not come up; see: docker compose logs llm | tail -30" >&2; exit 1
}
serve() {
  docker compose --profile gpu down >/dev/null 2>&1 || true
  LLM_MODEL="$1" LLM_SERVED_NAME="$2" docker compose --profile gpu up -d llm
  wait_ready "$2"
}
run() {  # model, scaffold
  local d="results/local__${1}/trackc-$2"
  uv run python -m paygym.eval --model "local/$1" --scaffold "$2" --split eval --n-seeds 95 --rollouts 3 --seed 7 \
      --concurrency 8 --run-name "trackc-$2" $( [ -f "$d/config.json" ] && echo --resume "$d" )
}

if pgrep -f "\.venv/bin/python train/grpo_train.py" >/dev/null; then
  echo "training is running: wait for it to finish (the GPU is needed)" >&2; exit 1
fi

echo "== fixed model: Qwen2.5-3B at S0-S4"
serve Qwen/Qwen2.5-3B-Instruct qwen2.5-3b
for S in S0 S1 S2 S3 S4; do echo "-- $S"; run qwen2.5-3b "$S"; done

echo "== comparison model: Qwen2.5-0.5B at S0 and S4"
serve Qwen/Qwen2.5-0.5B-Instruct qwen2.5-0.5b
for S in S0 S4; do echo "-- $S"; run qwen2.5-0.5b "$S"; done
docker compose --profile gpu down

echo "== finding"
uv run python scripts/track_c.py --small local/qwen2.5-3b --compare local/qwen2.5-0.5b
uv run paygym leaderboard >/dev/null && echo "leaderboard updated"
