# step7_serving — serve the model on Modal with vLLM, the proxy and the code pre-checker (pipeline stage 6 of the brief)

## What it does
- Serves a merged model with vLLM on a Modal GPU (L4 by default), behind a CPU proxy that checks a bearer token, adds the student prompt, forces schema-constrained JSON, validates, retries once, and falls back to a valid `escalate`.
- Runs the **code pre-checker** (`prechecks.py`, reader v3): from the packet text only, it computes the as-of date, MRZ check digits, document expiry, proof-of-address age and a document-integrity class, and appends them as a `PRE-CHECKS` block. It never guesses: unknown values render `n/d`. The same function builds training data, dev/eval requests and serving requests.
- Measures pre-checker accuracy against the hidden truth on train-process data only (`precheck_eval.py`), and endpoint latency / cost (`measure_latency.py`).
- Deploys the hand-over endpoint and uploads the final weights to Hugging Face.

## Key files
| File | What it is |
|---|---|
| `modal_vllm.py` | One Modal app, two web functions: `vllm` (GPU) and `proxy` (CPU). Settings via `ZORBE_SERVE_*` env at deploy time |
| `proxy.py`, `proxy_config.example.yaml` | OpenAI-compatible proxy: auth, prompt + schema injection, validation, retry, fallback; `ZORBE_PRECHECKS=1` adds the block |
| `prechecks.py` | Deterministic pre-checker, reader v3 (three readers vote; any disagreement = `n/d`) |
| `precheck_eval.py` | Coverage and accuracy of the pre-checker vs truth; refuses `eval*` splits |
| `build_reader_dev.py` | Builds `data/reader_dev/` (600 train-process cases, all 6 styles) for reader development |
| `deploy_endpoint.sh` | Deploy the hand-over endpoint (vLLM always warm + proxy with pre-checks); `--dry-run` deploys nothing |
| `endpoint_parity.py` | Local check that the proxy sends vLLM the exact request the eval runs sent; 401 without token |
| `measure_latency.py` | Concurrency-1 latency and cost on 100 dev cases through the proxy |
| `upload_hf.py`, `MODEL_CARD.md` | Upload `/vol/ckpt/merged/<run>` to the HF Hub (runs on Modal) with the model card |
| `setup_secrets.py`, `smoke.py`, `rehearsal/` | One-time secrets; serving smoke test; toy train → merge → serve rehearsal |

## How to use
```bash
pip install -r requirements.txt -r requirements-f.txt -r requirements-i.txt

# free, local
python -m step7_serving.precheck_eval --splits train dev reader_dev --decision-errors ''
python -m step7_serving.precheck_eval --splits reader_dev --by-style --decision-errors ''
python -m step7_serving.endpoint_parity                         # no GPU, no network
bash step7_serving/deploy_endpoint.sh final-Brun2-s4 --dry-run  # prints settings + runs the parity check

# deploy and measure the final model (Modal GPU, costs money: ~$0.80/h on L4 while up)
python -m step7_serving.setup_secrets                           # once per workspace
bash step7_serving/deploy_endpoint.sh final-Brun2-s4            # prints the proxy URL
python -m step7_serving.measure_latency --base-url <proxy URL>/v1 --name final-Brun2-s4 \
    --compare results/runs/final-Brun2-s4__dev
ZORBE_SERVE_GPU=H100 bash step7_serving/deploy_endpoint.sh final-Brun2-s4   # latency sample on H100 (costs more)
python -m modal app stop <app printed by deploy_endpoint.sh> --yes          # ends GPU billing

# publish weights (Modal, runs remotely)
python -m modal run -m step7_serving.upload_hf --run final-Brun2-s4 --repo <hf-user>/<repo> --dry-run
```
Callers send a bare packet to `<proxy URL>/v1/chat/completions` with `Authorization: Bearer <PROXY_API_KEY>` and model `zorbe-kyc`.

## Outputs / where results live
- `results/latency/final-Brun2-s4.json` (L4) and `results/latency/final-Brun2-s4-h100.json` (H100), plus per-case runs in `results/latency/<name>/`.
- `step7_serving/results/`: pre-checker evals (`precheck_eval_train_dev.*` = v1, `precheck_v2_*` = v2, `precheck_v3_*` = v3), the reader v3 gate (`p3_reader_v3_gate.md`), and format-fuzz bench outputs (`reader_bench_v3_<commit>_seed<N>.md`).
- Smoke and rehearsal runs write to `outputs/smoke/`, `outputs/rehearsal/` (git-ignored).

## Reports and evidence
- [Reader v3 gate: 0 wrong values on train, dev, reader_dev and fuzz seeds](results/p3_reader_v3_gate.md)
- [Pre-checker v3 by style](results/precheck_v3_eval_reader_dev_by_style.txt), [v2 eval](results/precheck_v2_eval_train_dev.md)
- [Evidence log §5c (diagnosis, reader v3) and §6 (the pre-check component)](../documentation/04_results/findings_log.md)
- [Headline tables (latency and cost in Table 1b)](../documentation/04_results/benchmark_report_submission.md)
- Session reports: [overnight-B.md](../documentation/05_progress_reports/overnight-B.md) (serving smoke), [overnight-I.md](../documentation/05_progress_reports/overnight-I.md) (proxy, endpoint runner)
- [SUNDAY_READER_V3.md](../documentation/06_agent_instructions/SUNDAY_READER_V3.md), [SUNDAY_DELIVERABLES.md](../documentation/06_agent_instructions/SUNDAY_DELIVERABLES.md)

## Details

### Measured, final model B2 (`results/latency/`)
- L4, 1 request at a time, 100 dev cases: p50 24.3 s, p95 29.1 s, $5.36 per 1k cases (upper bound: one request on a dedicated GPU). Decision agreement with the saved dev run: 100/100.
- H100, 1 at a time: p50 3.3 s, p95 3.8 s, $3.59 per 1k (30/30 agreement).

### Measured in the first serving smoke test (Qwen3.5-0.8B base, Session B)
| | Result |
|---|---|
| Auth (raw vLLM and proxy) | no token 401, wrong token 401, right token 200 |
| `response_format: json_schema` | enforced (enum + int bounds + regex valid on an adversarial prompt) |
| Thinking | off: no `<think>`, no reasoning field |
| Cold start | first ever 385 s; caches warm 288 s; `--enforce-eager` 209 s but slower warm |
| Warm latency, toy schema | raw vLLM p50 761 ms; through proxy 822 ms (proxy hop ~60 ms); with `disable_any_whitespace` 367 / 412 ms |
| Train → merge → serve rehearsal | served merged vs base: 6/6 outputs differ. PASS |

A cold start of ~5 min means the hand-over endpoint keeps one container warm (`ZORBE_SERVE_MIN=1`).

### Env knobs (read at deploy time, baked into the image)
`ZORBE_SERVE_MODEL` (HF id or `/vol/ckpt/...`), `ZORBE_SERVE_NAME`, `ZORBE_SERVE_APP`, `ZORBE_SERVE_MIN` (0 = scale to zero, 1 = warm), `ZORBE_SERVE_SCALEDOWN` (idle s, 300), `ZORBE_SERVE_EAGER`, `ZORBE_SERVE_MAX_LEN` (8192), `ZORBE_SERVE_NO_WS`, `ZORBE_SERVE_GPU`, and `ZORBE_PRECHECKS` for the proxy.

### Gotchas
1. **Whitespace runaway under constrained decoding.** vLLM's JSON grammar allows free whitespace; an untrained model can fill max_tokens with spaces. `disable_any_whitespace` (default on; `ZORBE_SERVE_NO_WS=0` turns it off) fixes most of it, and needs an explicit `backend` (xgrammar or guidance).
2. **A dead vLLM process can hold the GPU** until `startup_timeout`. A watchdog thread now kills the container when vLLM exits.
3. **Redeploying does not replace a warm container.** Stop the app, then deploy.
4. **Merged Qwen3.5 checkpoints are text-only** (`Qwen3_5ForCausalLM`); vLLM serves them. The base needs `--limit-mm-per-prompt {"image":0,"video":0}` to run text-only.
5. **Git Bash path conversion** mangles `/vol/ckpt/...`. Use `MSYS_NO_PATHCONV=1`; `modal_vllm.py` refuses such paths.
6. **Modal CLI on Windows**: set `PYTHONIOENCODING=utf-8`; `modal app stop` needs `--yes` when not interactive.
7. Modal labels the web URLs "(unauthenticated)"; that is Modal's own auth. The bearer tokens do the auth.

### Reader bench
`reader_bench_*.md` were produced by a format fuzzer (`step7_serving.reader_bench`) developed on a separate branch. That script is **not in this repo**; only its saved outputs are.
