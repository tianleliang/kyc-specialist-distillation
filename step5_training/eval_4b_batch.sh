#!/usr/bin/env bash
# CLOUD (Modal GPU, costs money): after all 4 distill trainings finish, merge + serve + score each on 150 dev cases.
# Each app is stopped at the end. If anything errors, run: python -m modal app list  and stop any zorbe-distill-* app.
# usage: bash step5_training/eval_4b_batch.sh      then: python step5_training/score_dev.py
set -uo pipefail
L=outputs/logs; mkdir -p "$L"
for t in floor reject arbitrate twins; do
  bash step5_training/eval_on_dev.sh distill-4b-$t Qwen/Qwen3.5-4B > "$L/eval_distill_4b_$t.log" 2>&1 &
  sleep 75
done
wait
echo "all 4 scored. Run: python step5_training/score_dev.py"
