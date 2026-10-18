#!/usr/bin/env bash
# Runs FROM THE LAPTOP; GPUs on Modal (costs money): 4B adapter check + 4 distillation trainings, staggered 75 s.
# usage: bash step5_training/launch_4b_batch.sh                 (adapter + all 4)
#        NO_ADAPTER=1 bash step5_training/launch_4b_batch.sh    (skip the adapter check)
# Logs go to outputs/logs/ : NOT inside step5_training/, because Modal uploads that folder at launch and
# fails with "file was modified during build" if a running job's log is still being written there.
# watch:  python -m modal app list   |   tail -3 outputs/logs/*4b*.log
set -euo pipefail
export PYTHONUTF8=1 MSYS_NO_PATHCONV=1
set -a; . ./.env; set +a
L=outputs/logs; mkdir -p "$L"
if [ -z "${NO_ADAPTER:-}" ]; then
  echo "launch adapter check (4B)"
  nohup python -m modal run -m step3_domain_adapter.measure_adapter \
    --config step3_domain_adapter/configs/adapter_4b.yaml > "$L/adapter_4b_measure.log" 2>&1 &
  sleep 75
fi
for t in floor reject arbitrate twins; do
  echo "launch distill-4b-$t"
  nohup python -m modal run -m step5_training.sft \
    --config step5_training/configs/distill_4b_$t.yaml > "$L/distill_4b_$t.log" 2>&1 &
  sleep 75
done
echo "all launched. Logs in $L/"
