"""Per-case latency and cost of the deployed endpoint: concurrency 1, warm, 100 DEV cases.

    python -m step7_serving.measure_latency --base-url https://<workspace>--<app>-proxy.us-east.modal.run/v1 \
        [--name final-B-s4] [--n 100] [--gpu-usd-per-hour 0.80] [--compare results/runs/final-B-s4__dev]

What it does (no new runner: it drives ``step2_benchmarking/run_endpoint.py``):

* sends each dev packet bare, exactly as a customer would (``--prompt none --response-format none``):
  the proxy adds the system prompt, the student template, the PRE-CHECKS block (if the app was
  deployed with ``ZORBE_PRECHECKS=1``) and the response schema;
* ``--warmup 3`` untimed requests first (the vLLM container is kept warm by ``min_containers=1``;
  the warm-up also wakes the CPU proxy), then one request at a time;
* writes the run to ``results/latency/<name>/`` (predictions, endpoint_run.json) and a summary
  ``results/latency/<name>.json``: p50 / p95 / mean latency in ms, and cost per 1k cases
  = GPU $/h × mean latency / 3600 × 1000 (one request on one dedicated L4; an upper bound, since a
  loaded server batches: at 16 concurrent requests the frozen-eval runs cost ~1/10 of this);
* ``--compare``: decision agreement with a saved dev run of the same model (sanity check that the
  endpoint serves the evaluated model and request: temperature 0, same prompt).

Dev cases only: eval packets never go to a serving check. The bearer token is read from the env var
named by ``--api-key-env`` (default ``PROXY_API_KEY``, loaded from ``.env``); it is never printed.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def pct(vals: list[float], q: float) -> float:
    s = sorted(vals)
    k = (len(s) - 1) * q / 100
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def curl_examples(base_url: str, model: str) -> str:
    url = base_url.rstrip("/") + "/chat/completions"
    body = ('{"model": "' + model + '", "messages": [{"role": "user", "content": "<paste the case packet text here>"}]}')
    return (f"# without a token -> 401\ncurl -s -o /dev/null -w '%{{http_code}}\\n' {url} \\\n"
            f"  -H 'Content-Type: application/json' -d '{body}'\n\n"
            f"# with the token (bearer = PROXY_API_KEY from .env) -> 200, schema-valid JSON in choices[0].message.content\n"
            f"curl -s {url} \\\n  -H \"Authorization: Bearer $PROXY_API_KEY\" -H 'Content-Type: application/json' \\\n"
            f"  -d '{body}'\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base-url", required=True, help="the proxy URL ending in /v1 (printed by deploy_endpoint.sh)")
    ap.add_argument("--name", default="final-B-s4", help="label for results/latency/<name>")
    ap.add_argument("--model", default="zorbe-kyc", help="model name the proxy serves")
    ap.add_argument("--api-key-env", default="PROXY_API_KEY")
    ap.add_argument("--cases", default="data/dev/cases.jsonl")
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--warmup", type=int, default=3)
    ap.add_argument("--gpu", default="L4", help="GPU the endpoint runs on (label only)")
    ap.add_argument("--gpu-usd-per-hour", type=float, default=0.80, help="Modal L4 list price")
    ap.add_argument("--compare", type=Path, help="saved dev run dir of the same model, e.g. results/runs/final-B-s4__dev")
    ap.add_argument("--dry-run", action="store_true", help="print the run_endpoint command and curl examples only")
    a = ap.parse_args(argv)
    os.chdir(ROOT)
    if "/eval" in a.cases.replace("\\", "/"):
        raise SystemExit("latency is measured on dev cases only")
    out = Path("results/latency") / a.name
    cmd = [sys.executable, "-m", "step2_benchmarking.run_endpoint", "--cases", a.cases, "--out", out.as_posix(),
           "--base-url", a.base_url, "--model", a.model, "--api-key-env", a.api_key_env,
           "--prompt", "none", "--response-format", "none", "--concurrency", "1", "--warmup", str(a.warmup),
           "--limit", str(a.n), "--display-name", f"{a.name} (endpoint, c=1)"]
    print("$ python " + " ".join(cmd[1:]))
    print(curl_examples(a.base_url, a.model))
    if a.dry_run:
        return 0
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    if not os.environ.get(a.api_key_env):
        raise SystemExit(f"{a.api_key_env} is not set (it lives in .env)")
    subprocess.run(cmd, check=True)

    preds = [json.loads(ln) for ln in (out / "predictions.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]
    lat = [p["latency_ms"] for p in preds if p.get("latency_ms") is not None and not p.get("error")]
    mean = statistics.fmean(lat)
    summary = {
        "name": a.name, "base_url": a.base_url, "model": a.model, "cases": a.cases, "n": len(preds),
        "n_timed": len(lat), "n_errors": sum(1 for p in preds if p.get("error")), "concurrency": 1, "warmup": a.warmup,
        "latency_p50_ms": round(pct(lat, 50), 1), "latency_p95_ms": round(pct(lat, 95), 1),
        "latency_mean_ms": round(mean, 1),
        "gpu": a.gpu, "gpu_usd_per_hour": a.gpu_usd_per_hour,
        "cost_per_1k_usd": round(a.gpu_usd_per_hour * mean / 1000 / 3600 * 1000, 4),
        "cost_note": "one request at a time on one dedicated GPU (upper bound); CPU proxy cost not included (pennies)",
    }
    if a.compare:
        ref = {}
        for ln in (a.compare / "predictions.jsonl").read_text(encoding="utf-8").splitlines():
            if ln.strip():
                r = json.loads(ln)
                try:
                    ref[r["case_id"]] = json.loads(r["output"]).get("decision")
                except (TypeError, ValueError):
                    ref[r["case_id"]] = None
        both = [(ref.get(p["case_id"]), (json.loads(p["output"]) if p.get("output") else {}).get("decision"))
                for p in preds if p["case_id"] in ref]
        summary["compare_to"] = a.compare.as_posix()
        summary["decision_agreement_with_saved_run"] = f"{sum(x == y for x, y in both)}/{len(both)}"
    (Path("results/latency") / f"{a.name}.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
