# shared — one client for the OpenAI, Anthropic and Gemini APIs, with cache, cost ledger and batch (used by stages 1, 3 and 5 of the brief)

## What it does
- One request type (`LLMRequest`) and one client (`LLMClient`) for all three frontier providers, with JSON-Schema structured output on each. Invalid output is returned, not raised, so the eval can score schema validity.
- Caches every response on disk, keyed by a hash of everything that affects the output, so reruns are free. Keeps a running cost ledger from a price table.
- Retries with backoff on 408 / 409 / 429 / 5xx and timeouts; per-provider rate limits. A mock provider gives deterministic, schema-valid output with no network (all tests use it).
- Batch API runner (50% off) with all state on disk, so a killed job resumes. Plus a schema linter for provider structured-output rules.

## Key files
| File | What it is |
|---|---|
| `frontier_api/clients.py` | `LLMClient`, `LLMRequest` / `make_request`, providers, `DiskCache`, `CostLedger`, `PriceTable`, `RateLimiter`, mock mode, optional eval guard |
| `frontier_api/batch.py` | `BatchRunner`: submit / poll / collect for the three batch APIs; CLI `run` / `resume` / `status` |
| `frontier_api/schema_check.py` | Lints an output schema for OpenAI / Anthropic / Gemini structured output (no API call) |
| `frontier_api/prices.yaml` | USD per 1M tokens per model, optional `cached_input` rate, `batch_discount: 0.5` |

Used by: `step2_benchmarking/run_frontier.py` (baselines, teacher answers), `step2_benchmarking/run_endpoint.py --cache`, `step1_data_generation/ood_llm.py` (LLM-written OOD set), `step4_distillation/` (on-policy, prefs), `step6_evaluation/judge_claims.py` (unsupported-claims judge).

## How to use
```python
from shared.frontier_api.clients import LLMClient, make_request
client = LLMClient()                       # LLM_MOCK=1 in the env forces mock mode
req = make_request("anthropic", "claude-opus-5-5", user=packet, system=prompt,
                   json_schema=schema, max_tokens=2048, reasoning_effort="low")
resp = client.complete(req)                # (API, costs money) resp.parsed, resp.schema_valid, resp.cost_usd
print(client.ledger.summary())
```
Batch jobs (API, costs money unless `--mock`):
```bash
python -m shared.frontier_api.batch run    --job outputs/batches/NAME --requests reqs.jsonl [--mock]
python -m shared.frontier_api.batch resume --job outputs/batches/NAME [--mock]
python -m shared.frontier_api.batch status --job outputs/batches/NAME
```
Schema lint (free): `python -m shared.frontier_api.schema_check step0_rules/schema/v1.json`

Tests (mocks only, no keys): `python -m pytest -q tests/f_llm_clients_test.py tests/f_llm_batch_test.py tests/f_llm_schema_check_test.py`

**Environment.** Copy `.env.example` to `.env` (gitignored) and fill in the names you need. `.env` is loaded automatically if `python-dotenv` is installed. Keys are never logged or stored.
| Env var | Used for |
|---|---|
| `OPENAI_API_KEY` | OpenAI |
| `ANTHROPIC_API_KEY` | Anthropic |
| `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) | Gemini |
| `LLM_MOCK` | set to `1` to force mock mode |

`.env.example` also lists `HF_TOKEN`, `MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET` (training, serving, upload; not used by this client).

## Outputs / where results live
- **Cache:** `outputs/llm_cache/<first 2 hex>/<key>.json` (default `DEFAULT_CACHE_DIR`; `outputs/` is gitignored). Writes are atomic. Mock answers get a `mock-` key prefix so they never shadow real ones. Batch results are written into the same cache.
- **Cost ledger:** in memory per client (`client.ledger`), per model: calls, cache hits, batch calls, input / output / reasoning tokens, `cost_usd`, `saved_by_cache_usd`, unpriced calls. Cache hits cost 0. Saved with `ledger.save(path)`; `run_frontier.py` writes it as `ledger.json` in each run dir.
- **Batch jobs:** `<job>/requests.jsonl`, `state.json`, `results.jsonl`.
- **Committed copies:** run ledgers under `step2_benchmarking/results/*/*/ledger.json`; the OOD-LLM cache entries needed to rebuild that eval set in `results/eval_regen/ood_llm_cache/`.

## Reports and evidence
- [overnight-F.md](../documentation/05_progress_reports/overnight-F.md): how the client, batch runner and schema linter were built and tested.
- [overnight-I.md](../documentation/05_progress_reports/overnight-I.md): the endpoint runner's `--cache` reuse of this cache.
- [overnight-K.md](../documentation/05_progress_reports/overnight-K.md): distillation steps that build batch requests for this client.
- [lunch-M.md](../documentation/05_progress_reports/lunch-M.md): the LLM OOD writer that calls it.
- [OVERNIGHT.md](../documentation/06_agent_instructions/OVERNIGHT.md) (Session F): the brief that built it.
- [findings_log.md](../documentation/04_results/findings_log.md) §8: cost and logistics.

## Details
- **Structured output per provider:** OpenAI `response_format`, Anthropic `output_config.format`, Gemini `response_json_schema`. Responses are parsed and validated locally.
- **Retries:** SDK-internal retries are off, so the client's exponential backoff with jitter is the single policy. Default rate limits (requests per minute): OpenAI 500, Anthropic 50, Gemini 150.
- **Prices:** `PriceTable.lookup` takes an exact model name, else the longest configured prefix (dated snapshots resolve). Batch calls are priced at the discount. Reasoning tokens are billed as output. The table says to verify against each provider console before reporting spend. `results/prices.yaml` is a different file: GPU-hour prices that `make_tables.sh` uses for self-hosted cost per case.
- **Eval guard:** `LLMClient(guard=EvalGuard(...))` (from `step6_evaluation/split_guard.py`) refuses `purpose="teacher"` requests whose text overlaps a frozen eval set. It is optional: `step4_distillation/onpolicy.py` passes one; `run_frontier.py` does not.
- **Pure functions:** request builders and response parsers work on dicts, so `batch.py` shares them and tests run without any SDK or key.
