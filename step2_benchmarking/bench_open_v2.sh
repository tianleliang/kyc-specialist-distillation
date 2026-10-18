#!/usr/bin/env bash
# Open baselines (untrained Qwen3.5 0.8B / 2B / 4B) on the fresh eval_id v2, with exactly the flags of the
# original Session-Q benchmark (frontier-identical prompts, schema, warmup 2, concurrency 16). Best prompt for
# all sizes; zero-shot too for 4B (Table 2 starts from it). One app per size, stopped on exit.
# usage: bash step2_benchmarking/bench_open_v2.sh            (~25 min, ~$2 on L4s)
set -uo pipefail
export PYTHONUTF8=1 MSYS_NO_PATHCONV=1
set -a; . ./.env; set +a
mkdir -p outputs/logs
run_size() {  # <size> <hf id> <prompts...>
  local SZ=$1 HF=$2; shift 2
  local APP="zorbe-bench-${SZ}-v2" NAME; NAME=$(basename "$HF")
  trap 'python -m modal app stop "$APP" --yes > /dev/null 2>&1 || true' RETURN
  echo "[$SZ] deploy $APP"
  ZORBE_SERVE_MODEL=$HF ZORBE_SERVE_APP=$APP ZORBE_SERVE_MIN=1 ZORBE_SERVE_MAX_LEN=24576 \
    python -m modal deploy -m step7_serving.modal_vllm > "outputs/logs/deploy_bench_${SZ}_v2.log" 2>&1 || { echo "[$SZ] deploy FAILED"; return 1; }
  for P in "$@"; do
    echo "[$SZ] $P"
    python -m step2_benchmarking.run_endpoint --cases data/eval_id_v2/cases.jsonl --out "outputs/bench_open/${SZ}__${P}__eval_id_v2" \
      --base-url "https://tianleliang--${APP//./-}-vllm.us-east.modal.run/v1" --model "$NAME" --api-key-env VLLM_API_KEY \
      --prompt "$P" --frontier-prompt --response-format schema --schema step0_rules/schema/v1_serving.json \
      --warmup 2 --concurrency 16 --resume 2>&1 | tail -1
  done
  python -m modal app stop "$APP" --yes > /dev/null 2>&1 || true
  echo "[$SZ] done (app stopped)"
}
run_size 0.8b Qwen/Qwen3.5-0.8B baseline_best > outputs/logs/bench_open_v2_0.8b.log 2>&1 &
sleep 75
run_size 2b Qwen/Qwen3.5-2B baseline_best > outputs/logs/bench_open_v2_2b.log 2>&1 &
sleep 75
run_size 4b Qwen/Qwen3.5-4B baseline_zero_shot baseline_best > outputs/logs/bench_open_v2_4b.log 2>&1 &
sleep 75
# Table 2 middle row: A halfway (adapter + twins, no pre-checks) on eval_id v2
SKIP_MERGE=1 bash step5_training/eval_on_dev.sh final-A-s3 /vol/ckpt/merged/adapter-qwen35-4b data/eval_id_v2/cases.jsonl \
  > outputs/logs/eval_A_s3_v2.log 2>&1 &
wait
echo "all done"; python -m modal app list 2>/dev/null | grep -E "zorbe-bench|zorbe-final-a" || true
