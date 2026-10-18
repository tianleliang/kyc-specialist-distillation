#!/usr/bin/env bash
# Runs FROM THE LAPTOP; GPUs on Modal (costs money): the two final models, A and B, side by side.
# usage: [SMOKE=1] [ONLY=A|B|Brun2] bash step5_training/launch_final.sh <winner>
#   winner = distill_floor_sol | distill_reject_sol | distill_arbitrate_splice | distill_arbitrate_plus_twins
#
#   step 0  adapted base /vol/ckpt/merged/adapter-qwen35-4b (merged only if missing; stops if the merge check fails)
#   then, for A and B in parallel (B staggered 75 s; B = PRE-CHECKS block in every prompt, data/sft/*_pc.jsonl):
#     s3 SFT -> merge s3 -> { s4 SFT -> merge s4 -> eval_on_dev final-<X>-s4 -> eval_frozen final-<X>-s4 }
#                        \-> { SKIP_MERGE=1 eval_on_dev final-<X>-s3 -> eval_frozen final-<X>-s3 }
#                            (halfway rows, own GPU, does not delay s4)
#   s4 trains on gold decisions with Sol narratives (data/sft/gold_train_solnarr{,_pc}.jsonl).
#
# Unattended: every stage is skipped when its output already exists (SFT: /vol/ckpt/sft/<run>/adapter/
# adapter_config.json; merge: /vol/ckpt/merged/<run>/config.json; eval: a complete run dir, final_lib.sh
# preds_done), so re-running the same command after a failure continues where it stopped. A failed
# stage is retried once after 60 s (transient Modal / network errors), then the pipeline gives up.
#
# Logs go to outputs/logs/ (NOT inside step5_training/: Modal uploads that folder at launch and fails with
# "file was modified during build" if a log there is still being written). Filled configs go to outputs/final/.
# Scores: outputs/student/final-<X>-s{3,4}__dev/ and __<eval split>/ (frozen; SMOKE: 5 eval_id cases).
# Expected wall-clock: s3 ~50-70 min, s4 ~25 min, dev evals ~15 min, frozen evals ~25 min.
# watch:  python -m modal app list   |   tail -20 outputs/logs/launch_final.log
set -euo pipefail
WINNER=${1:-}
case "$WINNER" in
  distill_floor_sol|distill_reject_sol|distill_arbitrate_splice|distill_arbitrate_plus_twins) ;;
  *) echo "usage: bash step5_training/launch_final.sh <distill_floor_sol|distill_reject_sol|distill_arbitrate_splice|distill_arbitrate_plus_twins>"; exit 2 ;;
esac
export PYTHONUTF8=1 MSYS_NO_PATHCONV=1
set -a; . ./.env; set +a
. step5_training/final_lib.sh
L=outputs/logs; F=outputs/final; mkdir -p "$L" "$F"
ADAPTED=/vol/ckpt/merged/adapter-qwen35-4b
DEV=data/dev/cases.jsonl
RETRY_WAIT=${RETRY_WAIT:-60}
# SMOKE=1: the whole chain on a tiny scale (128 rows, 1 epoch, 10 dev cases, 5 frozen eval_id cases, run
# names *-smoke, merge output-differ check relaxed) to prove the plumbing end to end before the real launch.
SFX=""; SMOKE_SED=()
if [ -n "${SMOKE:-}" ]; then
  export SMOKE
  SFX="-smoke"
  SMOKE_SED=(-e "s#^max_train_rows:.*#max_train_rows: 128#" -e "s#^epochs:.*#epochs: 1#")
  mkdir -p outputs/final/smoke; head -10 data/dev/cases.jsonl > outputs/final/smoke/cases.jsonl
  DEV=outputs/final/smoke/cases.jsonl
fi
DEVTAG=$(basename "$(dirname "$DEV")")    # eval_on_dev writes outputs/student/<run>__<DEVTAG>
exec > >(tee -a "$L/launch_final.log") 2>&1

say "launch_final winner=$WINNER${SMOKE:+ (SMOKE)}"
for f in "data/sft/$WINNER.jsonl" "data/sft/${WINNER}_pc.jsonl" data/sft/gold_train_solnarr.jsonl \
         data/sft/gold_train_solnarr_pc.jsonl "$DEV" step5_training/eval_frozen.sh; do
  [ -f "$f" ] || { say "missing $f (B files: python -m step4_distillation.add_prechecks --all)"; exit 1; }
done

stage() {  # <label> <log> <cmd...>: one line at start and finish; one retry after RETRY_WAIT s
  local label=$1 log=$2; shift 2
  say "$label START (log $log)"
  if "$@" > "$log" 2>&1; then say "$label DONE"; return 0; fi
  mv -f "$log" "$log.try1"
  say "$label FAILED (see $log.try1), retrying once in ${RETRY_WAIT} s"
  sleep "$RETRY_WAIT"
  say "$label RETRY START (log $log)"
  if "$@" > "$log" 2>&1; then say "$label DONE (on retry)"; return 0; fi
  say "$label FAILED twice, see $log and $log.try1"; return 1
}

stage_unless() {  # <done-check (a command string)> <label> <log> <cmd...>: skip when the output exists
  local check=$1; shift
  if eval "$check"; then say "$1 SKIPPED (output exists: $check)"; return 0; fi
  stage "$@"
}

# ---- step 0: adapted base ----
if vol_file "${ADAPTED#/vol/ckpt}/config.json"; then
  say "step 0: $ADAPTED exists, merge skipped"
else
  stage "step 0: merge domain adapter" "$L/merge_adapter_4b.log" \
    python -m modal run -m step5_training.merge --config step3_domain_adapter/configs/merge_adapter_4b.yaml \
    || { say "step 0: merge FAILED (merge check or error). Stopping."; exit 1; }
fi

# ---- fill the winner into the s3 configs; local checks (data, placeholders, contamination gate; no GPU) ----
PIPES="${ONLY:-A B}"   # ONLY=Brun2: B-run2 = Final B pipeline run 2 (reader v3 blocks, 25% blank), configs final_Brun2_s{3,4}.yaml
for X in $PIPES; do
  sed -e "s#PLACEHOLDER_WINNER#$WINNER#" -e "s#final-\([A-Za-z0-9]*\)-s\([34]\)#final-\1-s\2$SFX#g" ${SMOKE_SED[@]+"${SMOKE_SED[@]}"} "step5_training/configs/final_${X}_s3.yaml" > "$F/final_${X}_s3.yaml"
  sed -e "s#final-\([A-Za-z0-9]*\)-s\([34]\)#final-\1-s\2$SFX#g" ${SMOKE_SED[@]+"${SMOKE_SED[@]}"} "step5_training/configs/final_${X}_s4.yaml" > "$F/final_${X}_s4.yaml"
done
python - "$F" "$PIPES" <<'EOF'
import sys
from step5_training.sft import prepare
for x in sys.argv[2].split():
    for s in ("s3", "s4"):
        cfg, rows, _, meta = prepare(f"{sys.argv[1]}/final_{x}_{s}.yaml")
        print(f"  ok {cfg.run_name}: {len(rows)} rows from {cfg.train_file}, base {cfg.base_model}, "
              f"epochs {cfg.epochs}, lr {cfg.learning_rate}, gate {meta['contamination_gate'].get('contaminated_eval_records')}")
EOF

merge_cfg() {  # <run> <base> -> outputs/final/merge_<run>.yaml
  sed -e "s#^run_name:.*#run_name: merge-$1#" -e "s#^base_model:.*#base_model: $2#" \
      -e "s#^adapter_dir:.*#adapter_dir: /vol/ckpt/sft/$1/adapter#" -e "s#^output_dir:.*#output_dir: /vol/ckpt/merged/$1#" \
      step5_training/configs/merge_gold_0p8b.yaml > "$F/merge_$1.yaml"
  if [ -n "${SMOKE:-}" ]; then sed -i "s#^min_differing_probes:.*#min_differing_probes: 0#" "$F/merge_$1.yaml"; fi
  echo "$F/merge_$1.yaml"
}

evals() {  # <X> <run> <base> <PC> <tag>: dev eval, then the frozen eval of the same model
  local X=$1 R=$2 B=$3 PC=$4 T=$5 rc=0
  stage_unless "preds_done outputs/student/${R}__$DEVTAG" "[$X] $T eval" "$L/final_${X}_${T}_eval.log" \
    env SKIP_MERGE=1 bash step5_training/eval_on_dev.sh "$R" "$B" "$DEV" $PC || rc=1
  stage "[$X] $T frozen eval" "$L/final_${X}_${T}_frozen.log" bash step5_training/eval_frozen.sh "$R" $PC || rc=1
  return $rc
}

pipeline() {  # <A|B>
  local X=$1 PC="" S3="final-$1-s3$SFX" S4="final-$1-s4$SFX" half=0 rc=0
  case "$X" in B*) PC=prechecks ;; esac
  stage_unless "vol_file /sft/$S3/adapter/adapter_config.json" "[$X] s3 SFT" "$L/final_${X}_s3_sft.log" \
    python -m modal run -m step5_training.sft --config "$F/final_${X}_s3.yaml" || return 1
  stage_unless "vol_file /merged/$S3/config.json" "[$X] s3 merge" "$L/final_${X}_s3_merge.log" \
    python -m modal run -m step5_training.merge --config "$(merge_cfg "$S3" "$ADAPTED")" || return 1
  # halfway: score the s3 model (dev, then frozen) on its own GPU while s4 trains
  evals "$X" "$S3" "$ADAPTED" "$PC" s3 &
  half=$!
  stage_unless "vol_file /sft/$S4/adapter/adapter_config.json" "[$X] s4 SFT" "$L/final_${X}_s4_sft.log" \
    python -m modal run -m step5_training.sft --config "$F/final_${X}_s4.yaml" || rc=1
  if [ $rc = 0 ]; then
    stage_unless "vol_file /merged/$S4/config.json" "[$X] s4 merge" "$L/final_${X}_s4_merge.log" \
      python -m modal run -m step5_training.merge --config "$(merge_cfg "$S4" "/vol/ckpt/merged/$S3")" || rc=1
  fi
  if [ $rc = 0 ]; then
    evals "$X" "$S4" "/vol/ckpt/merged/$S3" "$PC" s4 || rc=1
  fi
  wait "$half" || rc=1
  return $rc
}

# ONLY=A | B | Brun2 runs one pipeline; default A and B
declare -A PID RC; first=1
for X in $PIPES; do
  [ $first = 1 ] || sleep 75; first=0
  pipeline "$X" & PID[$X]=$!
done
ALLOK=0
for X in $PIPES; do RC[$X]=0; wait "${PID[$X]}" || { RC[$X]=$?; ALLOK=1; }; done
say "launch_final finished: $(for X in $PIPES; do printf '%s rc=%s ' "$X" "${RC[$X]}"; done). Scores: outputs/student/final-<X>-s{3,4}${SFX}__{$DEVTAG,eval_*}/"
python -m modal app list 2>/dev/null | grep -i "zorbe-final" || true   # eval apps stop themselves; check nothing is left
[ $ALLOK = 0 ]
