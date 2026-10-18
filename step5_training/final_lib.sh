# Shared helpers for launch_final.sh / eval_frozen.sh (sourced, not run). Local checks only; no GPU.
#   vol_file <path under /vol/ckpt>   the file exists on the zorbe-checkpoints volume
#   preds_done <run dir>              run_endpoint finished it: endpoint_run.json says every case
#                                     was written with no error and predictions.jsonl has that many lines

say() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*"; }

vol_file() {  # exact file name match (config.json must not match adapter_config.json)
  local dir name
  dir=$(dirname "$1"); name=$(basename "$1")
  python -m modal volume ls zorbe-checkpoints "$dir" 2>/dev/null \
    | grep -qE "(^|[^A-Za-z0-9_.-])${name//./\\.}([^A-Za-z0-9_.-]|$)"
}

preds_done() {
  python - "$1" <<'EOF'
import json, sys
from pathlib import Path
d = Path(sys.argv[1])
try:
    prov = json.loads((d / "endpoint_run.json").read_text(encoding="utf-8"))
    n = sum(1 for l in open(d / "predictions.jsonl", encoding="utf-8") if l.strip())
except (OSError, ValueError):
    sys.exit(1)
ok = prov.get("n_cases") and prov.get("n_written") == prov["n_cases"] == n and prov.get("n_errors") == 0
sys.exit(0 if ok else 1)
EOF
}
