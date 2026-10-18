# Overnight report: Session I (prompts, serving proxy, endpoint runner)

Branch: `claude/serene-cray-jncc3u` (the environment forced this name, so it doesn't contain the letter I; the PR title says "Session I"). Mocks only. No API keys, no Modal, no GPU.

## Done

| # | Task | Where | Status |
|---|---|---|---|
| 1 | Prompt templates + loader | `step0_rules/prompts/*.md`, `step0_rules/prompts/render.py`, `step0_rules/prompts/schemas/judge_unsupported_claims.json`, `step0_rules/prompts/README.md` | Done |
| 2 | OpenAI-compatible proxy | `step7_serving/proxy.py`, `step7_serving/proxy_config.example.yaml` | Done; also smoke-tested over real sockets |
| 3 | Endpoint runner | `step2_benchmarking/run_endpoint.py` | Done; its output goes through `step6_evaluation/report.py` unchanged |
| 4 | Windows encoding fixes | `step6_evaluation/report.py`, `step6_evaluation/metrics.py`, `tests/c_*`, `step6_evaluation/split_guard.py`, `tests/f_llm_clients_test.py` | Done |

### 1. `step0_rules/prompts/`
- Six templates. Each has YAML front matter (`name`, `description`, `variables`) and an `@@system` part and an `@@user` part:
  - `student`: short production prompt for the small model (the policy, the schema, 4 rules). The proxy injects it, and SFT records should use it.
  - `baseline_zero_shot`: task description and schema only.
  - `baseline_best`: policy, a **field guide derived from the schema**, and 2 few-shot examples.
  - `teacher`: the best prompt, plus a rule that every narrative sentence cites every packet section or hit ID it relies on, and every reason names the values it compared.
  - `judge_unsupported_claims`: one grounding verdict per sentence, with a verbatim quote for supported sentences.
  - `ood_renderer`: **eval-only**. A frontier model writes a packet in a new style from a truth object, with a list of strings that must appear verbatim.
- **No schema or policy is hardcoded.** A test fails if any case template contains a v0 schema token. The field guide is generated from whatever schema is passed in: `$ref`s are resolved, a repeated enum points back to its first occurrence, and nullable `anyOf` is handled.
- Substitution is strict and single-pass: placeholders must be declared, a missing or extra variable raises, and a packet containing `{schema}` stays literal.
- Few-shot `load_examples`: deterministic in `seed` and stratified by decision, so the 2 examples show 2 different outcomes. It refuses any pool under an `eval*` directory. For `purpose="teacher"` it also refuses `draft`, because `data/draft/README.md` says draft data may not feed teacher prompts. With `eval_manifests`, it checks every example against the frozen eval set via `split_guard.EvalGuard`.
- Judge bias controls: `render_judge` pools sentences from every model under neutral IDs (`S1..Sn`) in a seeded shuffle, so the judge never sees model names or case ids. `parse_judgments` raises if the judge skipped, duplicated or invented an ID, so the denominator can't shrink silently. `quote_in_packet` checks a "supported" quote programmatically.
- OOD: `check_ood_packet` lists required strings the renderer dropped or "fixed". Drop those packets, because their gold label may no longer hold.
- `PromptBuilder.provenance()` returns hashes (template, system prompt, policy, schema, few-shot case ids) for `run.json` and SFT metadata.
- `--policy module:step1_data_generation.project` uses A's PROVISIONAL policy docstring until a real policy file exists.

### 2. `step7_serving/proxy.py` (FastAPI)
- `POST /v1/chat/completions` and `GET /v1/models` require `Authorization: Bearer`. Tokens come from `PROXY_API_KEYS` (comma-separated) and are compared in constant time. A missing, wrong or non-Bearer token gets **401**. The app **refuses to start without keys**.
- `GET /health` needs no auth, for warm-up and readiness probes.
- **No system message:** the proxy inserts the `student` system prompt (rendered with our schema and policy) and wraps the packet in the training user template. A bare packet works. Content-part lists are accepted.
- **No `response_format`:** the proxy injects `json_schema` (strict) with our schema. A caller's own system prompt and `response_format` are kept as sent.
- Thinking is **forced off**: `chat_template_kwargs.enable_thinking=false` overrides the caller. `reasoning_content` is stripped from the response. `max_tokens` is capped, and temperature defaults to 0.
- **Validation:** the output is validated against our schema, or against the caller's own schema if they sent a different one. A code fence or surrounding prose is repaired and flagged (`repair_fences`, config switch). If the output is still invalid there is **one retry**. After that the proxy returns a **schema-valid `escalate` fallback** (`x-kyc-fallback: invalid_output`), logged.
  - Upstream 5xx, timeouts and connection errors get the same treatment (`upstream_error`; `fallback_on_upstream_error: false` returns a 502 instead).
  - Upstream 4xx is passed through with no retry.
  - Token usage is summed over attempts, so cost stays honest.
- **Fallback:** built from the schema. Every top-level enum that offers `escalate` is set to it, then dotted-path overrides from the config are applied. It is validated **at startup**, so a bad config fails at deploy, not on a live request. The example config gives v0 a fully-specified escalate with identity marked "not assessed".
- **Streaming:** supported in buffered form. The proxy validates the full output first, then sends one SSE content chunk, a finish chunk and `[DONE]` (`x-kyc-stream: buffered`). `n>1` and `tools` get a clear 400.
- **Logging:** one JSON line per request with latency, per-attempt upstream ms, attempts, fallback reason, repaired flag, usage and the packet **sha256** (never the packet text). Optional `log_path`. Response headers: `x-kyc-latency-ms`, `x-kyc-upstream-ms`, `x-kyc-attempts`, `x-kyc-schema-valid`, `x-kyc-repaired`, `x-kyc-prompt-injected`, `x-kyc-response-format-injected`.
- Run: `PROXY_API_KEYS=... PROXY_CONFIG=step7_serving/proxy_config.example.yaml uvicorn step7_serving.proxy:app_from_env --factory`. On Modal, return `create_app(ProxyConfig.load(...))` from an `@modal.asgi_app()`.

### 3. `step2_benchmarking/run_endpoint.py`
- Async httpx with a concurrency semaphore. Works against the proxy, bare vLLM, or any OpenAI-compatible API.
- Request options:
  - `--prompt none|student|baseline_zero_shot|baseline_best|teacher`
  - `--response-format schema|json_object|none`
  - `--extra-body` (e.g. `chat_template_kwargs`, `reasoning_effort`)
  - `--max-tokens-param max_completion_tokens` for OpenAI
- Writes the `step6_evaluation/report.py` record format, `{case_id, output, latency_ms, usage}`, plus extras: `error`, `attempts`, `http_status`, `finish_reason`, `cached`, and `proxy` header flags. A failed case is **written with `output: null`**, so the report scores it zero instead of dropping it. The file is rewritten in input order at the end, so it is deterministic.
- Also writes `run.json`, using only keys `step6_evaluation/report.py` knows (`--meta k=v` is checked against `RUN_META_KEYS`), and `endpoint_run.json` with provenance: endpoint, cases sha256, prompt/schema/policy hashes, counts, wall time, throughput, p50/p95.
- Retries on 408/409/429/5xx and timeouts with exponential backoff, and honours `retry-after`. Other 4xx responses are not retried.
- `--resume` keeps finished cases and reruns only missing or failed ones. `--warmup N` sends untimed cold-start requests.
- `--cache` uses `shared/frontier_api/clients.DiskCache` (keyed by endpoint + payload). Use it for paid APIs. Cached records keep their original latency, are flagged, and are excluded from the run's p50/p95.
- The API key is read from the env var named by `--api-key-env` and is never written; a test checks this.
- `--prompt teacher` refuses eval case files.

### 4. Encoding fixes
- Every `open()`, `read_text()` and `write_text()` in `step6_evaluation/report.py`, `step6_evaluation/metrics.py`, `tests/c_fakes.py`, `tests/c_metrics_test.py`, `tests/c_report_test.py` and `step6_evaluation/split_guard.py` now passes `encoding="utf-8"`. The one binary `open(path, "rb")` was left alone.
- `test_missing_key_errors_cleanly`: dotenv loading is now disabled **before** the client is built (the constructor loads `.env`; the old test patched it afterwards, so a local `.env` with a key broke it). Every provider key env var is cleared. The `openai` module is stubbed, so the test also passes without the SDK installed; it failed in this sandbox before the fix.

## Test results
`python -m pytest tests/` gives **274 passed, 3 skipped**, about 6 s. The skips belong to other sessions.

| File | Tests | Covers |
|---|---|---|
| `i_prompts_test.py` | 23 | all templates parse; no schema tokens hardcoded; strict single-pass fill; field guide on a tiny schema and on v0; stratified deterministic few-shot; step6_evaluation/draft pool refusal; frozen-manifest contamination check; judge blindness and shuffle; judgment parse refusing gaps, duplicates and unknown IDs; OOD check; CLI |
| `i_proxy_test.py` | 22 | bare packet gives valid JSON with injected prompt, schema and thinking off; caller's system prompt and format kept; 401 on 5 bad-auth variants; no keys means no start; retry then valid; invalid twice gives the flagged escalate fallback; upstream 503/timeout/502/400 paths; fence repair on/off; buffered SSE; bad requests get 400; fallback builder |
| `i_run_endpoint_test.py` | 9 | oracle run scores 100% through `step6_evaluation/report.py`; concurrency respected; retries and failures kept; resume reruns only failures; timeouts; cache; key never written; guards; prompt templates applied; **end to end: run_endpoint → proxy (ASGI) → mock upstream** |

**Live-socket smoke** (scratch only, not committed): uvicorn ran a fake vLLM and the proxy, and `run_endpoint` ran over HTTP on 20 draft cases, then `step6_evaluation/report.py`. The run scored 100% on every quality metric, with 0 fallbacks, p50 16 ms and p95 25 ms. With the upstream accidentally pointed at a dead port, all 20 cases came back as flagged `upstream_error` escalate fallbacks, all schema-valid. Buffered SSE also worked over curl.

## Not done / not verified
- Nothing ran against real vLLM, Modal or a frontier API (no keys).
  - vLLM's handling of `response_format: json_schema` and `chat_template_kwargs` is assumed from its docs, not exercised.
  - Check one request against the real server before the first latency run.
- The fallback leaves `screening` empty, because the proxy doesn't parse hit IDs out of the packet. This is honest (it's flagged and escalates), but it scores zero on screening for those cases.
- No LLM judge was *run*: the prompt, schema and parse/validation exist. Wiring it into `step6_evaluation/metrics.ClaimChecker` waits on the judge-model decision.
- I didn't edit `step7_serving/README.md` (Session B's, wave 1). The proxy's docstring and this report document it.

## Problems / notes
- `fastapi` and `httpx` were not installed in the sandbox. They are listed in `requirements-i.txt` (plus `uvicorn`). The proxy and runner tests `importorskip` them.
- FastAPI can't resolve `Request` annotations under `from __future__ import annotations` when the import is local to a function (every route got a 422). FastAPI is now imported at module level.

## Questions for Tianle
1. **Fallback content.** Should the escalate fallback also set the risk tier to `high` and the action to manual review (current example config), or the most conservative values from the final policy? It's a config change only (`fallback_overrides`).
2. **Repairing fences at the proxy.** `repair_fences: true` means the endpoint returns clean JSON even if the model wraps it, and the response is flagged. Is that fair for Table 1 (it's part of the served system), or should we turn it off so the endpoint shows raw model validity? The eval harness itself stays strict either way.
3. **Fallback on upstream errors.** Should we return a flagged escalate (current, safe for a KYC desk), or a 502 so outages are visible to Zorbe's harness?
4. **Student prompt length.** `student` includes the full schema and policy (about 7k characters with v0 and A's policy). After SFT we could serve a shorter system prompt (policy omitted) if Tianle wants lower latency; that is a training-format decision.
5. **Few-shot `k` and stratification** for `baseline_best` and `teacher`: currently 2 examples with different decisions. Keep it, or show an escalate example on purpose?
