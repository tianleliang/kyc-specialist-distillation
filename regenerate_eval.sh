#!/usr/bin/env bash
# Rebuild every frozen eval split (eval_id, eval_ood_template, eval_ood_hand, eval_ood_llm, eval_hard)
# from its recorded seed/config into a scratch dir and verify it against the freeze manifests
# (split_guard verify) and byte for byte against data/. Never writes under data/. No API, no GPU:
# eval_ood_llm replays the recorded LLM responses in results/eval_regen/ood_llm_cache/.
#   bash regenerate_eval.sh [--scratch DIR] [--only eval_id,eval_hard]
set -euo pipefail
cd "$(dirname "$0")"
export PYTHONUTF8=1
"${PYTHON:-python}" -m step6_evaluation.regenerate_eval "$@"
