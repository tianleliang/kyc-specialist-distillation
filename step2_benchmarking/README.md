# step2_benchmarking — run frontier and open baselines (and our endpoint) on a case file (pipeline stage 1 of the brief)

## What it does
- Runs any model over a JSONL of cases and saves one prediction per case, with latency, token usage and errors. Failed cases are kept (`output: null`) so they score zero instead of vanishing.
- `run_frontier.py`: GPT / Claude / Gemini through their native structured-output APIs (via `shared/frontier_api`, with cache and cost ledger). Also used to collect teacher answers for stage 3.
- `run_endpoint.py`: any OpenAI-compatible endpoint: raw vLLM on Modal (untrained Qwen3.5 0.8B / 2B / 4B), our proxy, or our model with the pre-check block.
- Prompts are byte-identical across frontier and open models (`--frontier-prompt` reuses `run_frontier.build_prompt`). Scoring is done later by `step6_evaluation/report.py`.

## Key files
| File | What it is |
|---|---|
| `run_frontier.py` | Frontier runner. `--model provider:model` (`openai:`, `anthropic:`, `gemini:`), `--prompt baseline_zero_shot / baseline_best / teacher`. Few-shot examples from `data/train` only |
| `run_endpoint.py` | OpenAI-compatible runner with concurrency, retries, `--resume`, `--warmup`, optional `--cache`, `--prechecks` |
| `bench_open_v2.sh` | Deploys Qwen3.5 0.8B / 2B / 4B on Modal L4s one app per size, runs the best prompt (plus zero-shot for 4B) on eval_id v2, stops each app; also scores A halfway (`final-A-s3`) |
| `results/bench_frontier/` | Saved frontier runs on the frozen eval v1 sets: 3 models × 2 prompts × 4 sets |
| `results/bench_open/` | Saved untrained-Qwen runs on eval v1: 3 sizes × 2 prompts × 4 sets |
| `results/bench_hard/` | Opus and Astra (best prompt) on eval_hard |
| `results/dev_pilot/` | 100-case dev pilot of 4 frontier models + its `report.md` |

## How to use
Frontier model (API, costs money). Smoke first, then the full run:
```bash
python -m step2_benchmarking.run_frontier --cases data/eval_id/cases.jsonl --model openai:gpt-6-astra \
    --prompt baseline_zero_shot --limit 2 --run-id smoke_f --out-root outputs/smoke
M=gemini:gemini-4-argon; python -m step2_benchmarking.run_frontier --cases data/eval_id_v2/cases.jsonl --model $M \
    --prompt baseline_best --workers 4 --run-id "$(echo $M | cut -d: -f2)__baseline_best__eval_id_v2" --out-root outputs/bench_frontier
```
Use `--workers 4` for Anthropic. Teacher answers for stage 3 use the same script with `--prompt teacher` on `data/train*` (commands in `BIGRUNS.md`). Only `run_endpoint.py` refuses `--prompt teacher` on eval files; `run_frontier.py` has no such check, so never point it at `data/eval*` with the teacher prompt.

Untrained open models on eval_id v2 (Modal GPU, costs money, ~25 min, ~$2; needs `.env`; apps stop themselves):
```bash
bash step2_benchmarking/bench_open_v2.sh
```
One endpoint run by hand (the endpoint itself may be a paid Modal GPU):
```bash
python -m step2_benchmarking.run_endpoint --cases data/eval_id_v2/cases.jsonl --out outputs/bench_open/4b__baseline_best__eval_id_v2 \
    --base-url https://<your-vllm-app>/v1 --model Qwen3.5-4B --api-key-env VLLM_API_KEY \
    --prompt baseline_best --frontier-prompt --response-format schema --schema step0_rules/schema/v1_serving.json \
    --warmup 2 --concurrency 16 --resume
```
Our proxy takes the bare packet (it adds prompt, pre-checks and schema): `--prompt none --response-format none --api-key-env PROXY_API_KEY`.

Score saved runs (free, no API): `bash make_tables.sh` from the repo root. Tests: `python -m pytest -q tests/i_run_endpoint_test.py`

## Outputs / where results live
- Each run writes a run dir: `predictions.jsonl` (`case_id, output, latency_ms, usage, error`), `run.json` (model, gold, params), plus `ledger.json` (API cost, `run_frontier`) or `endpoint_run.json` (provenance: endpoint, prompt hashes, cases sha256, `run_endpoint`).
- New runs go to `outputs/` (gitignored): `run_frontier` uses `<out-root>/<run-id>/` (default `outputs/`); `run_endpoint` uses `--out`.
- Committed copies: the eval v1 stage 1 runs in `step2_benchmarking/results/`; every run behind a reported number (incl. eval_id v2 and eval_hard) in `results/runs/<model>__<prompt>__<set>/`, packaged by `step6_evaluation/collect_runs.py`.
- Response cache for `--cache` and the frontier client: `outputs/llm_cache/`.

## Reports and evidence
- [benchmark_report_submission.md](../documentation/04_writeup/benchmark_report_submission.md): Table 1 (eval_id v2) and Appendix B (initial benchmark on frozen eval v1, zero-shot and best prompt).
- [benchmark_report.md](../documentation/04_writeup/benchmark_report.md): generated report with confidence intervals.
- [writeup_evidence_log.md](../documentation/04_writeup/writeup_evidence_log.md) §3: frontier panel findings.
- [results/dev_pilot/report.md](results/dev_pilot/report.md): dev pilot of 4 frontier models.
- [BIGRUNS.md](../documentation/06_agent_instructions/BIGRUNS.md): Sessions F (frontier benchmark) and Q (open-model benchmark), with the exact commands and the fairness rule.
- [SUNDAY_BRUN2.md](../documentation/06_agent_instructions/SUNDAY_BRUN2.md): frontier and open models on eval_id v2.
- [FINAL_RUN_INFRA.md](../documentation/06_agent_instructions/FINAL_RUN_INFRA.md): the `--prechecks` flag.
- [overnight-I.md](../documentation/05_progress_reports/overnight-I.md): how `run_endpoint.py` was built and tested.
- [overnight-B.md](../documentation/05_progress_reports/overnight-B.md): serving smoke test that `run_endpoint` runs against.

## Details
- **Fairness.** `run_frontier.build_prompt` uses schema field descriptions off, a one-line field guide, and 2 examples from `data/train` with `seed=0`. `run_endpoint --frontier-prompt` reuses it, so open models see the same text.
- **Anthropic schema.** Anthropic structured output rejects `minItems > 1`, `maxItems` and length / range bounds, so `run_frontier.api_schema` sends it a relaxed copy. Every prediction is still scored against full `v1.json`.
- **Open models** use `v1_serving.json` (length caps stop decode loops), `--warmup 2`, concurrency 16, and `ZORBE_SERVE_MAX_LEN=24576` because the best prompt is about 16k tokens.
- **Latency runs** should not use `--cache`: cached records keep their original latency and are flagged `cached: true`.
- **Keys.** `--api-key-env` takes the NAME of an env var; the token is never written anywhere. `run_endpoint.py` refuses `--prompt teacher` on eval case files.
- **Our model on the frozen sets** was run through `run_endpoint.py --prompt student_short --prechecks` (see `step7_serving/README.md` and `step5_training/eval_frozen.sh`).
