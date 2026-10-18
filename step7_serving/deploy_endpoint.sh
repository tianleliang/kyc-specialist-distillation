#!/usr/bin/env bash
# Deploy the hand-over endpoint: vLLM (L4, always warm) serving /vol/ckpt/merged/<merged_run> + the proxy
# (CPU, kept warm) in front of it with the code pre-checks on, bearer-token auth, the student system
# prompt + template injected around a bare packet, and response_format = step0_rules/schema/v1_serving.json.
#
#   bash step7_serving/deploy_endpoint.sh <merged_run> [--no-prechecks] [--dry-run]
#     e.g. bash step7_serving/deploy_endpoint.sh final-B-s4
#
# Prints the URL, the model name callers use, the GPU, and the next commands (latency, curl, stop).
# COSTS MONEY WHILE UP: min_containers=1 keeps one L4 running (~$0.80/h, ~$19/day) until
#   python -m modal app stop <app> --yes
# --dry-run: deploys nothing; prints the settings and runs the local proxy parity check
#   (python -m step7_serving.endpoint_parity: same request as the frozen-eval runs, 401 without token).
# Needs: .env with PROXY_API_KEY / VLLM_API_KEY and the Modal secrets from `python -m step7_serving.setup_secrets`.
set -euo pipefail
cd "$(dirname "$0")/.."
RUN=${1:?usage: deploy_endpoint.sh <merged_run> [--no-prechecks] [--dry-run]}; shift
PRECHECKS=1; DRY=0
for arg in "$@"; do
  case "$arg" in
    --no-prechecks) PRECHECKS=0 ;;
    --dry-run) DRY=1 ;;
    *) echo "unknown option $arg"; exit 2 ;;
  esac
done
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8 MSYS_NO_PATHCONV=1
APP="${ZORBE_ENDPOINT_APP:-zorbe-kyc-$(echo "$RUN" | tr 'A-Z._' 'a-z--' | cut -c1-30)}"   # web URLs are lowercase, label <= 63 chars
MODEL_PATH="/vol/ckpt/merged/$RUN"
GPU=${ZORBE_SERVE_GPU:-L4}; export ZORBE_SERVE_GPU=$GPU                # L4 default; L40S / H100 for a latency sample

echo "app:        $APP"
echo "weights:    $MODEL_PATH (Modal volume zorbe-checkpoints)"
echo "GPU:        $GPU, vLLM min_containers=1 (always warm), proxy min_containers=1"
echo "pre-checks: ZORBE_PRECHECKS=$PRECHECKS"
echo "callers:    model \"zorbe-kyc\", Authorization: Bearer <PROXY_API_KEY from .env>"

if [ "$DRY" = 1 ]; then
  echo
  echo "dry run: would run"
  echo "  ZORBE_SERVE_MODEL=$MODEL_PATH ZORBE_SERVE_NAME=$RUN ZORBE_SERVE_APP=$APP ZORBE_SERVE_MIN=1 \\"
  echo "  ZORBE_PROXY_MIN=1 ZORBE_SERVE_MAX_LEN=8192 ZORBE_PRECHECKS=$PRECHECKS python -m modal deploy -m step7_serving.modal_vllm"
  echo
  "${PYTHON:-python}" -m step7_serving.endpoint_parity --n 20 --prechecks "$PRECHECKS"
  exit $?
fi

set -a; . ./.env; set +a
[ -n "${PROXY_API_KEY:-}" ] || { echo "PROXY_API_KEY missing from .env (run python -m step7_serving.setup_secrets)"; exit 1; }
python -m modal volume ls zorbe-checkpoints "merged/$RUN" > /dev/null \
  || { echo "merged weights not found: zorbe-checkpoints:merged/$RUN"; exit 1; }
mkdir -p outputs
LOG="outputs/deploy_endpoint_${RUN}.log"
ZORBE_SERVE_MODEL="$MODEL_PATH" ZORBE_SERVE_NAME="$RUN" ZORBE_SERVE_APP="$APP" ZORBE_SERVE_MIN=1 \
  ZORBE_PROXY_MIN=1 ZORBE_SERVE_MAX_LEN=8192 ZORBE_PRECHECKS="$PRECHECKS" \
  python -m modal deploy -m step7_serving.modal_vllm > "$LOG" 2>&1 || { tail -20 "$LOG"; exit 1; }
PROXY_URL=$(grep -oE 'https://[a-z0-9-]+-proxy[a-z0-9.-]*\.modal\.run' "$LOG" | head -1)
VLLM_URL=$(grep -oE 'https://[a-z0-9-]+-vllm[a-z0-9.-]*\.modal\.run' "$LOG" | head -1)
[ -n "$PROXY_URL" ] || { echo "deployed, but no proxy URL found in $LOG"; exit 1; }

echo
echo "DEPLOYED (the L4 is now billing; vLLM cold start ~5 min before the first answer)"
echo "endpoint:   $PROXY_URL/v1/chat/completions"
echo "model:      zorbe-kyc  (upstream vLLM serves $RUN at $VLLM_URL, VLLM_API_KEY)"
echo "GPU:        $GPU"
echo
echo "wait until warm, then measure (concurrency 1, 100 dev cases):"
echo "  python -m step7_serving.measure_latency --base-url $PROXY_URL/v1 --name $RUN --compare results/runs/${RUN}__dev"
echo "curl (no token -> 401; with token -> 200):"
echo "  curl -s -o /dev/null -w '%{http_code}\\n' $PROXY_URL/v1/chat/completions -H 'Content-Type: application/json' -d '{\"messages\":[{\"role\":\"user\",\"content\":\"<packet>\"}]}'"
echo "  curl -s $PROXY_URL/v1/chat/completions -H \"Authorization: Bearer \$PROXY_API_KEY\" -H 'Content-Type: application/json' -d '{\"model\":\"zorbe-kyc\",\"messages\":[{\"role\":\"user\",\"content\":\"<packet>\"}]}'"
echo "stop (ends GPU billing):"
echo "  python -m modal app stop $APP --yes"
