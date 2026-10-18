# tests — offline test suite for every pipeline step (no stage of its own; covers stages 1–6 of the brief)

## What it does
- Checks every step without network, API keys or GPU: frontier calls use the mock provider, endpoints use mock transports, Modal code is only imported.
- Proves the contamination controls (frozen eval manifests, split disjointness, teacher pools never from eval), the labels (policy code vs schema), the metrics (oracle = 100%, broken JSON = 0%) and the serving pieces (proxy, pre-checker).
- File names start with the letter of the build session that wrote them (see `documentation/06_agent_instructions/`). Letters are reused across briefs, so the table groups by area.

## Key files
| Files | Area |
|---|---|
| `a_mrz`, `a_names`, `a_matching`, `a_address`, `a_ocr`, `a_watchlist`, `a_phase2` | `step1_data_generation/lib/` building blocks; end-to-end generator + v1 projection |
| `j_generator_v1`, `j_splits`, `j_twins_knockout`, `m_ood` | Generator v1, split configs and `build.py` CLI, twins / knockouts, OOD writers (mock LLM) |
| `i_prompts`, `l_schema_v1`, `d_schema_options` | `step0_rules/` prompts and render, schema v1 vs serving schema vs policy, draft schema options |
| `i_run_endpoint` | `step2_benchmarking/run_endpoint.py` with mock transports |
| `m_adapter` | `step3_domain_adapter/`: corpus split, probe, verdict; optional CPU smoke |
| `k_distill` | `step4_distillation/` data steps with mock teachers and students |
| `f_train`, `f_train_cpu_smoke` | `step5_training/` configs, data validation, contamination gate, Modal scripts import; optional CPU smoke |
| `c_metrics`, `c_report`, `c_judge_claims`, `l_harness_v1`, `f_split_guard`, `d_deliverables` | `step6_evaluation/`: metrics, report, judge (mock), eval lock and leak detector, reproducibility deliverables |
| `b_serve`, `i_proxy`, `s_final_infra`, `v_precheck_v2`, `p3_reader_v3` | `step7_serving/`: Modal vLLM app (offline), proxy, PRE-CHECKS block, pre-checker v2 and reader v3, launch scripts |
| `f_llm_clients`, `f_llm_batch`, `f_llm_schema_check` | `shared/frontier_api/`: client, batch runner, schema linter (mocks only) |
| `c_fakes.py`, `l_v1_cases.py`, `fixtures/` | Helpers, not tests: fake models, v1 case rows built on the fly, a stand-in gold fixture |

## How to use
```bash
pip install -r requirements.txt                                     # base: pytest, jsonschema, pydantic, numpy, pyyaml, python-dotenv, rapidfuzz
pip install -r requirements-i.txt                                   # optional: fastapi, httpx, uvicorn (proxy, endpoint runner)
pip install -r requirements-f.txt                                   # optional: openai, anthropic, google-genai SDKs, modal
python -m pytest -q                                                 # whole suite, from the repo root
python -m pytest -q tests/i_prompts_test.py                         # one file
python -m pytest -q tests/j_*_test.py                               # one area
```
`pytest.ini` sets `testpaths = tests` and `pythonpath = .`, so run from the repo root. Everything here is free: no test calls an API or starts a GPU.

**What is skipped, and why** (all via `pytest.importorskip` or `skipif`; nothing needs network or a GPU):
| Skipped unless | Tests |
|---|---|
| `modal` is installed | `b_serve_test.py` (whole file), the Modal-import test in `f_train_test.py` |
| `fastapi` / `httpx` are installed (`requirements-i.txt`) | `i_proxy_test.py` (whole file, both), `i_run_endpoint_test.py` (whole file needs `httpx`, one test `fastapi`); parts of `d_deliverables_test.py`, `s_final_infra_test.py` |
| `openai`, `anthropic`, `google-genai` are installed | the SDK-signature check in `f_llm_clients_test.py` |
| `torch`, `transformers`, `trl`, `peft`, `datasets`, `tokenizers`, `modal` are installed | `f_train_cpu_smoke_test.py`, `test_cpu_smoke` in `m_adapter_test.py` (tiny offline model on CPU; large download) |
| `data/` is built | parts of `s_final_infra_test.py`, `v_precheck_v2_test.py`, `i_run_endpoint_test.py` |
| `data/draft/` (v0 fixtures) exists | `k_distill_test.py` (whole file), one test in `c_report_test.py` |
| `bash` is on the PATH | launch-script tests in `s_final_infra_test.py`, `v_precheck_v2_test.py` |

## Outputs / where results live
- Tests write only to pytest's `tmp_path`; nothing under `data/` or `results/` is changed.
- Test inputs: `tests/fixtures/` (stand-in gold, schema, v0 field map), the committed `data/` splits and manifests, `results/runs/` for `d_deliverables_test.py`.

## Reports and evidence
Each build report lists the tests it added and the suite count at that time:
- [overnight-A.md](../documentation/05_progress_reports/overnight-A.md) (`a_*`), [overnight-B.md](../documentation/05_progress_reports/overnight-B.md) (`b_serve`), [overnight-C.md](../documentation/05_progress_reports/overnight-C.md) and [overnight-C-harness-check.md](../documentation/05_progress_reports/overnight-C-harness-check.md) (`c_*`), [overnight-D.md](../documentation/05_progress_reports/overnight-D.md) (`d_schema_options`), [overnight-F.md](../documentation/05_progress_reports/overnight-F.md) (`f_*`).
- [overnight-I.md](../documentation/05_progress_reports/overnight-I.md) (`i_*`), [overnight-J.md](../documentation/05_progress_reports/overnight-J.md) (`j_*`), [overnight-K.md](../documentation/05_progress_reports/overnight-K.md) (`k_distill`).
- [lunch-L.md](../documentation/05_progress_reports/lunch-L.md) and [lunch-L-harness-v1.md](../documentation/05_progress_reports/lunch-L-harness-v1.md) (`l_*`), [lunch-M.md](../documentation/05_progress_reports/lunch-M.md) (`m_*`).
- Later sessions have no report file. Their briefs: [FINAL_RUN_INFRA.md](../documentation/06_agent_instructions/FINAL_RUN_INFRA.md) (Session S, `s_final_infra`), [FINAL_TONIGHT.md](../documentation/06_agent_instructions/FINAL_TONIGHT.md) (Session V, `v_precheck_v2`), [SUNDAY_READER_V3.md](../documentation/06_agent_instructions/SUNDAY_READER_V3.md) (Session P3, `p3_reader_v3`), [SUNDAY_DELIVERABLES.md](../documentation/06_agent_instructions/SUNDAY_DELIVERABLES.md) (Session D, `d_deliverables`). `SUNDAY_READER_V3.md` also names `tests/f_fuzz_test.py` for the format fuzzer; that file is not in this repo.
- [GUIDE.md](../GUIDE.md) gives the current pass count.
