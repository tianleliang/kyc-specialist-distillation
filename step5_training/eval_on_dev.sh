#!/usr/bin/env bash
# Merge a trained adapter, serve it on Modal, score it on the 150 dev cases, stop the app.
# usage: bash step5_training/eval_on_dev.sh <run_name> <base_hf_id_or_vol_path> [cases=data/dev/cases.jsonl] [prechecks]
#   4th arg "prechecks": add the PRE-CHECKS block to every request (run_endpoint --prechecks; Final B)
#   SKIP_MERGE=1: skip the merge when /vol/ckpt/merged/<run_name> already exists on the volume
#   --resume: a re-run (retry after a failure) keeps finished cases and re-scores only missing / failed ones
set -euo pipefail
RUN=$1; BASE=$2; CASES=${3:-data/dev/cases.jsonl}; PC=${4:-}
export PYTHONUTF8=1 MSYS_NO_PATHCONV=1
set -a; . ./.env; set +a
APP="zorbe-$(echo "$RUN" | tr 'A-Z.' 'a-z-' | cut -c1-40)"   # web endpoint URLs are lowercase
CFG="outputs/merge_${RUN}.yaml"
mkdir -p outputs
PC_ARGS=()
case "$PC" in
  "") ;;
  prechecks) PC_ARGS=(--prechecks) ;;
  *) echo "[$RUN] unknown 4th arg '$PC' (expected: prechecks)"; exit 2 ;;
esac
if [ -n "${SKIP_MERGE:-}" ] && python -m modal volume ls zorbe-checkpoints "/merged/$RUN" 2>/dev/null | grep -q config.json; then
  echo "[$RUN] merge skipped (SKIP_MERGE=1, /vol/ckpt/merged/$RUN exists)"
else
  sed -e "s#^run_name:.*#run_name: merge-$RUN#" -e "s#^base_model:.*#base_model: $BASE#" \
      -e "s#^adapter_dir:.*#adapter_dir: /vol/ckpt/sft/$RUN/adapter#" -e "s#^output_dir:.*#output_dir: /vol/ckpt/merged/$RUN#" \
      step5_training/configs/merge_gold_0p8b.yaml > "$CFG"
  echo "[$RUN] merge"; python -m modal run -m step5_training.merge --config "$CFG" > "outputs/merge_${RUN}.log" 2>&1
fi
echo "[$RUN] deploy $APP"
# stop the app however this script ends (a failed deploy / score must not leave a min_containers=1 GPU up)
trap 'python -m modal app stop "$APP" --yes > /dev/null 2>&1 || true' EXIT
ZORBE_SERVE_MODEL=/vol/ckpt/merged/$RUN ZORBE_SERVE_APP=$APP ZORBE_SERVE_MIN=1 ZORBE_SERVE_MAX_LEN=8192 \
  python -m modal deploy -m step7_serving.modal_vllm > "outputs/deploy_${RUN}.log" 2>&1
OUT="outputs/student/${RUN}__$(basename "$(dirname "$CASES")")"
echo "[$RUN] score -> $OUT ${PC_ARGS[*]:-}"
python -m step2_benchmarking.run_endpoint --cases "$CASES" --out "$OUT" \
  --base-url "https://tianleliang--${APP}-vllm.us-east.modal.run/v1" --model "$RUN" --api-key-env VLLM_API_KEY \
  --prompt student_short --schema step0_rules/schema/v1_serving.json --warmup 2 --concurrency 16 \
  --resume ${PC_ARGS[@]+"${PC_ARGS[@]}"} 2>&1 | tail -1
python -m modal app stop "$APP" --yes > /dev/null 2>&1 || true
trap - EXIT
echo "[$RUN] done (app stopped)"
