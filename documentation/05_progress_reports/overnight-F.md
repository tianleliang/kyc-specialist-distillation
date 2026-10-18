# Overnight report: Session F (model-call and training plumbing)

Branch: `claude/exciting-cori-5aw02a`. The cloud environment forced this name; it doesn't
contain the letter F, so the PR title says "Session F". Code with mocks only. No API keys
were used, and no Modal or GPU jobs were run.

## Done

| # | Task | Where | Status |
|---|---|---|---|
| 1 | One wrapper for OpenAI / Anthropic / Gemini | `shared/frontier_api/clients.py`, `shared/frontier_api/prices.yaml` | Done |
| 2 | Batch submit / poll / collect, resumable | `shared/frontier_api/batch.py` | Done |
| 3 | SFT (16-bit LoRA) + DPO as Modal functions, merge + push, configs | `step5_training/` | Written, CPU-verified, not run on Modal |
| 4 | Hash/freeze eval files, step5_training/eval overlap detection | `step6_evaluation/split_guard.py` | Done |
| extra | Output-schema linter for strict structured output | `shared/frontier_api/schema_check.py` | Done |
| extra | Offline CPU smoke of the whole training chain | `step5_training/cpu_smoke.py` | Done, passes |

### 1. `shared/frontier_api/clients.py`
- `LLMClient.complete(req)` / `complete_many(reqs)` over OpenAI (Chat Completions, `response_format` json_schema, strict),
  Anthropic (`output_config.format` + `output_config.effort`), and Gemini (`response_json_schema`, `thinking_config.thinking_level`).
- Output is parsed and validated against the schema locally. Invalid output is **returned** with
  `schema_valid=False` rather than raised, because the eval needs it to compute schema validity.
- Retry: exponential backoff with jitter on 408/409/429/5xx, timeouts and connection errors, and it honours `retry-after`. SDK-internal retries are off, so there's a single retry policy.
- Rate limiting: a token bucket per provider (RPM defaults: OpenAI 500, Anthropic 50, Gemini 150). **Set these to the real tiers.**
- Cost: `shared/frontier_api/prices.yaml` (from the research brief, prices are agent-reported and need verifying). Reasoning tokens count as output and cached input uses the cached rate. Batch is priced at 50%. `client.ledger.summary()` gives a per-model breakdown, including how much the cache saved.
- Disk cache under `outputs/llm_cache/` (gitignored), keyed by the sha256 of everything that affects the output. `purpose` and `metadata` are excluded, so a rerun is free. Mock answers use a separate namespace and never shadow real ones.
- Keys come from env / `.env` only and are never logged. Mock mode: `LLMClient(mock=True)` or `LLM_MOCK=1` (deterministic schema-valid output, token counts ≈ chars/4, priced at the named model's rate, so it also works as a dry-run cost estimate).
- **Contamination hook:** `LLMClient(guard=EvalGuard.from_manifest(...))` refuses any `purpose="teacher"` request whose text contains a frozen eval record. Baselines and judges can still run on eval cases.

### 2. `shared/frontier_api/batch.py`
- `BatchRunner(job_dir).add(reqs) → run()` handles submit → poll → collect, with `requests.jsonl`, `state.json` (atomic writes) and `results.jsonl` on disk. A killed process resumes without re-submitting.
- Cache-aware: requests already in the cache are filled in for free and never submitted. Every batch result is written to the cache, so a later live call costs nothing.
- `custom_id` = request hash, so re-adding a request does nothing and the ids are valid on all three APIs. Chunks are grouped by model (Gemini 500/chunk to respect the $10-per-10-min Tier-1 cap). Per-item errors go to `retry_errors()`.
- CLI: `python -m shared.frontier_api.batch run|resume|status --job DIR [--requests reqs.jsonl] [--mock]`.

### 3. `step5_training/`
- `sft.py`, `dpo.py`, `merge.py` are Modal apps, each with an Unsloth image (default) and a plain TRL+PEFT image (fallback). Models always load in **16-bit (no QLoRA)**. Transformers v5.
- **Local gates before any GPU starts:** configs with `PLACEHOLDER` values refuse to run, data is validated, and the **contamination gate** checks that the eval manifest verifies and that `split_guard` finds no eval record in any training file. The gate report and data hashes go into `run.json`.
- Rendering uses the model's own chat template with `enable_thinking=False` (matches vLLM serving). SFT loss is on the completion only.
- DPO starts from the **merged SFT** weights with a fresh LoRA, so TRL's adapter-disabled reference *is* the SFT policy.
- `merge.py`: merges, saves, **reloads from disk the way vLLM will**, and fails if `lora_B` is all zero or if greedy outputs and logits are the same as base (the Qwen3.5 "adapter silently does nothing" trap). It writes `verify.json` and optionally pushes the merged weights plus `adapter/` to one HF repo.
- Configs: `sft.yaml`, `dpo.yaml`, `merge.yaml` (placeholders). `sft_toy.yaml` / `merge_toy.yaml` set up a rehearsal on Qwen3-0.6B with 24 toy rows (rehearsal only, not a model choice).

### 4. `step6_evaluation/split_guard.py`
- `freeze` writes a manifest of file sha256s plus per-record hashes, with an optional read-only chmod. `verify` exits 1 if any file changed or is missing.
- `check --train ... --eval ...`: **exact** (normalized hash), **n-gram containment** (catches an eval packet pasted inside a longer SFT prompt) and **MinHash LSH** (near-duplicates, e.g. re-noised copies). Exits 1 on contamination and writes an optional JSON report.
- Template boilerplate is filtered out: n-grams present in more than 5% of eval records are dropped first. Otherwise every pair of cases from the same generator looks similar (there's a test showing this).
- Speed: 5,000 train × 450 eval long packets in about 3.4 s.

## Test results

`python -m pytest tests/f_*` → **70 passed** (about 14 s; includes the CPU smoke, which skips when torch/trl/peft aren't installed).

| File | Tests | Covers |
|---|---|---|
| `f_llm_clients_test.py` | 26 | builders/parsers for all 3 providers, built kwargs vs installed SDK signatures (openai 3.33, anthropic 1.15, google-genai), validation, pricing, ledger, retry/backoff/retry-after, rate limiter, cache persistence and corruption, mock mode, guard |
| `f_llm_batch_test.py` | 11 | chunking, 50% batch pricing, dedupe, cache-hit skip, crash/resume, item errors + retry, failed batch, per-model grouping, guard, CLI |
| `f_split_guard_test.py` | 13 | clean split, boilerplate filter, exact / embedded-in-SFT / OCR-noised near-dup, MinHash accuracy, freeze/verify/tamper, CLI exit codes, EvalGuard + LLMClient |
| `f_llm_schema_check_test.py` | 4 | strict-mode schema lint |
| `f_train_test.py` | 14 | configs + placeholder gate, data validation, template rendering (thinking off, single EOS), contamination gate, Modal scripts import + local `prepare` |
| `f_train_cpu_smoke_test.py` | 2 | full SFT→merge→DPO→merge on CPU; merge refuses an untrained (no-op) adapter |

CPU smoke (`python -m step5_training.cpu_smoke`, transformers 5.20.1 / TRL 1.16.0 / PEFT 0.21.2):
SFT loss went from 6.22 to 5.25. The merged SFT model differs from base on 4/4 probes (max logit Δ 0.97). DPO loss started at 0.693 (= ln 2, so the reference equals the policy, as intended) and ended at 0.668. The merged DPO model differs on 4/4 probes. I also checked the SFT labels directly: they are exactly the assistant JSON plus one `<|im_end|>`, with the prompt masked.

## Not done / not verified
- **Nothing ran against live APIs or Modal** (no keys, by design). Payload shapes were checked against the installed SDK signatures and pydantic types, but not against live endpoints. Run a 3-request live smoke per provider before the first teacher batch.
- Gemini batch result mapping relies on `metadata.key` echoing back on inline responses, with request order as the fallback. That isn't verified live.
- Unsloth image: not exercised (the CPU smoke uses the TRL backend). If Unsloth fights Qwen3.5, set `backend: trl`.
- Mock batch backend keeps its state in memory, so `resume` across processes only works with real backends.

## Problems hit
- The HF Hub and the PyTorch CPU wheel index are blocked in this sandbox, so I installed torch from PyPI and built a tiny Qwen2-architecture model + BPE tokenizer offline for the smoke test.
- Found and fixed: JSON-escaped newlines (`\nFull`) glued tokens together and hid contamination in raw JSON records. `normalize()` now treats `\n`, `\t`, `\r` escapes as whitespace (there's a test for this).
- TRL 1.16 removed `DPOConfig.max_prompt_length`; `make_args` drops it with a warning. TRL 1.16's `SFTConfig` defaults to bf16 and errors on CPU; it's now set from `torch.cuda.is_bf16_supported()`.

## Questions for Tianle
1. **Base model and sizes** fill `base_model` in `step5_training/configs/*.yaml` (all placeholders).
2. **HF bucket public or private?** `merge.yaml` defaults to `hub_private: true`; the brief needs a link Zorbe can download without logging in.
3. **Contamination thresholds:** 8-word n-grams, containment ≥ 0.5, MinHash Jaccard ≥ 0.7, boilerplate cutoff 5% of eval records. OK, or stricter?
4. **Real rate limits per provider/tier**, so `LLMClient(rpm=...)` matches your accounts.
5. **Reasoning effort default is `low`** for all three (the CLAUDE.md spend rule). On Opus 5.5, thinking can't be turned off, so effort is the only lever. On Gemini this maps to `thinking_level`.
6. `gemini-3.5-flash-lite` has no price in the research brief; add it to `shared/frontier_api/prices.yaml` if it's used.
7. Once the schema is chosen, run `python -m shared.frontier_api.schema_check step0_rules/schema/<file>.json`. OpenAI strict mode needs `additionalProperties: false` and every property in `required` (optional fields as nullable).
8. LoRA defaults (r=16, α=32, lr 2e-4, 2 epochs SFT; β=0.1, lr 5e-6, 1 epoch DPO) are standard starting points, not tuned. Keep or change?
