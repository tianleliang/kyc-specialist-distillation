#!/usr/bin/env bash
# Rebuild every benchmark table from the saved per-case outputs in results/runs/ (no API, no GPU).
#   bash make_tables.sh
# Writes documentation/04_writeup/benchmark_report.md (+ results/report_metrics.json).
# Byte-identical on rerun: depends only on results/runs/, data/ gold files, the configs below and the bootstrap seed.
set -euo pipefail
cd "$(dirname "$0")"
export PYTHONUTF8=1 PYTHONHASHSEED=0
PY="${PYTHON:-python}"
"$PY" -m step6_evaluation.report results/runs \
  --config step6_evaluation/fieldmap_v1.yaml --schema step0_rules/schema/v1.json \
  --prices results/prices.yaml --pending results/pending.yaml \
  --judge results/judge/eval_id/verdicts.jsonl --judge results/judge/eval_id_v2/verdicts.jsonl \
  --n-boot 1000 --seed 0 --quiet \
  --out documentation/04_writeup/benchmark_report.md --json results/report_metrics.json
echo "wrote documentation/04_writeup/benchmark_report.md"
