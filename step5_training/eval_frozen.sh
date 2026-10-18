#!/usr/bin/env bash
# Score a merged model ONCE on every frozen eval split: deploy /vol/ckpt/merged/<run> once, score each
# split with exactly the dev flags, stop the app however the script ends. Nothing is tuned after this.
# usage: [SMOKE=1] bash step5_training/eval_frozen.sh <run_name> [prechecks]
#   splits: data/{eval_id,eval_ood_template,eval_ood_hand,eval_ood_llm,eval_hard}/cases.jsonl
#           -> outputs/student/<run>__<split>/      (SMOKE=1: the first 5 cases of eval_id only)
#   2nd arg "prechecks": PRE-CHECKS block in every request (Final B), as on dev
#   resume: a split whose run dir is complete (final_lib.sh preds_done) is skipped; if all are, no deploy
set -euo pipefail
RUN=$1; PC=${2:-}
export PYTHONUTF8=1 MSYS_NO_PATHCONV=1
set -a; . ./.env; set +a
. step5_training/final_lib.sh
APP="zorbe-$(echo "$RUN" | tr 'A-Z.' 'a-z-' | cut -c1-36)-fz"   # web endpoint URLs are lowercase
PC_ARGS=()
case "$PC" in
  "") ;;
  prechecks) PC_ARGS=(--prechecks) ;;
  *) echo "[$RUN] unknown 2nd arg '$PC' (expected: prechecks)"; exit 2 ;;
esac
SPLITS=(eval_id eval_ood_template eval_ood_hand eval_ood_llm eval_hard); [ -f data/eval_id_v2/cases.jsonl ] && SPLITS+=(eval_id_v2); LIMIT=()
if [ -n "${SMOKE:-}" ]; then SPLITS=(eval_id); LIMIT=(--limit 5); fi

todo=()
for s in "${SPLITS[@]}"; do
  if preds_done "outputs/student/${RUN}__$s"; then echo "[$RUN] $s already scored, skipped"; else todo+=("$s"); fi
done
if [ ${#todo[@]} = 0 ]; then echo "[$RUN] frozen eval: every split already scored"; exit 0; fi

echo "[$RUN] deploy $APP (frozen eval: ${todo[*]})"
# stop the app however this script ends (a failed deploy / score must not leave a min_containers=1 GPU up)
trap 'python -m modal app stop "$APP" --yes > /dev/null 2>&1 || true' EXIT
mkdir -p outputs
ZORBE_SERVE_MODEL=/vol/ckpt/merged/$RUN ZORBE_SERVE_APP=$APP ZORBE_SERVE_MIN=1 ZORBE_SERVE_MAX_LEN=8192 \
  python -m modal deploy -m step7_serving.modal_vllm > "outputs/deploy_${RUN}_frozen.log" 2>&1
rc=0
for s in "${todo[@]}"; do
  OUT="outputs/student/${RUN}__$s"
  echo "[$RUN] score $s -> $OUT ${PC_ARGS[*]:-}"
  python -m step2_benchmarking.run_endpoint --cases "data/$s/cases.jsonl" --out "$OUT" \
    --base-url "https://tianleliang--${APP}-vllm.us-east.modal.run/v1" --model "$RUN" --api-key-env VLLM_API_KEY \
    --prompt student_short --schema step0_rules/schema/v1_serving.json --warmup 2 --concurrency 16 \
    --resume ${LIMIT[@]+"${LIMIT[@]}"} ${PC_ARGS[@]+"${PC_ARGS[@]}"} 2>&1 | tail -1 || { echo "[$RUN] $s FAILED"; rc=1; }
done
python -m modal app stop "$APP" --yes > /dev/null 2>&1 || true
trap - EXIT
echo "[$RUN] frozen eval done (app stopped), rc=$rc"
exit $rc
