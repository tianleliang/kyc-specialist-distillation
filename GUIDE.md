# Guide: the pipeline, step by step

Start here after the [README](README.md). Each step folder has its own README (what it does, key files, how to run, where results live, which reports cover it).

**Cost legend:** 🟢 plain Python, laptop, free · 🟡 calls frontier APIs ($ per call) · 🔴 GPU job on Modal ($ per hour). Reproducing the tables needs only 🟢.

## The steps

| # | Folder | Brief stage | What happens | Kind | Key result |
|---|---|---|---|---|---|
| 0 | [`step0_rules/`](step0_rules/README.md) | setup | Output schema (`schema/v1.json`), decision policy (`policy_v1.md`), every prompt (`prompts/`) | 🟢 | Policy re-derived independently on 600/600 cases |
| 1 | [`step1_data_generation/`](step1_data_generation/README.md) | setup | Answer-first synthetic generator: hidden facts → policy computes the label → packet rendered with OCR noise, transliteration, varied layouts, injections | 🟢 | train 3,000 · dev 150 · twins 1,000 · eval sets (below) |
| 2 | [`step2_benchmarking/`](step2_benchmarking/README.md) | 1. Benchmark | Runs any model (frontier API, open model on Modal, our endpoint) on a case file; prompts byte-identical across models | 🟡🔴 | Frontier with rulebook 95.8–99.2%; untrained Qwen 0.8–4B 29–61% → 4B chosen by a pre-set rule |
| 3 | [`step3_domain_adapter/`](step3_domain_adapter/README.md) | 2. Domain adapter | LoRA on public KYC/AML text (FATF, FinCEN CDD, ICAO 9303 MRZ, OFAC, Wolfsberg, address formats), measured on held-out text + a probe quiz | 🔴 | Perplexity −25%; on dev, +0.7 pts on the task (1 case, noise): reported as a null |
| 4 | [`step4_distillation/`](step4_distillation/README.md) | 3. Distillation | Teacher answers → training files: floor, rejection sampling, multi-teacher arbitration, **Counterfactual Twin Distillation**; pre-check blocks; stage-4 file | 🟡🟢 | All within noise (teachers 99.3% = answer key); twins chosen (best actions recall, fewest wrong approvals) |
| 5 | [`step5_training/`](step5_training/README.md) | 3–4. Training + post-train | LoRA SFT / merge on Modal; `launch_final.sh` runs the whole final pipeline (stage 3 → merge → stage 4 → merge → scoring) with resume + retry | 🔴 | Stage 3 +32.7 pts, pre-checker +8.0, post-train ±0 (Table 2) |
| 6 | [`step6_evaluation/`](step6_evaluation/README.md) | 5. Evaluate | Every metric of the brief, Table 1/2 builder, frozen-split guard + contamination check, eval regeneration, blind LLM judge | 🟢🟡 | 96.3% on fresh eval_id v2; tie with Argon and Opus |
| 7 | [`step7_serving/`](step7_serving/README.md) | 6. Serve | vLLM on Modal + proxy (token, prompt, **code pre-checker**, schema); latency measurement; HF upload; pre-checker reader (`prechecks.py` = v3, shipped; `prechecks_v31.py` = v3.1, swap test) + format fuzzer (`fuzz_render.py`, `reader_bench.py`) | 🔴🟢 | p50 3.3 s (H100) / 24.3 s (L4), measured |
| – | [`shared/`](shared/README.md) | used by 2, 4, 6 | One client for OpenAI / Anthropic / Gemini with response cache, cost ledger, eval guard | 🟡 | |
| – | [`data/`](data/README.md) | | All splits; eval sets frozen by sha256 manifest | | 0 overlap with training |
| – | [`results/`](results/README.md) | | Saved per-case outputs behind every number (`runs/`), judge verdicts, latency, metrics JSON | | |
| – | [`tests/`](tests/README.md) | | `python -m pytest -q` | 🟢 | 0 failures: 510 pass with all requirements files; 476 pass + 11 skipped with `requirements.txt` only |

## Test sets (all frozen before any teacher call or training; `step6_evaluation/split_guard.py`)
| Set | Cases | Built by | Role |
|---|---|---|---|
| eval_id | 300 | our generator, separate seeds and name pools; 25% in 2 layouts never in training | in-distribution (frozen v1) |
| eval_ood_template / hand / llm | 50 / 50 / 100 | held-out templates / a session that never saw the generator / LLMs writing free prose | out-of-distribution |
| eval_hard | 150 | 2–3 stacked difficulties per case | stress |
| **eval_id_v2** | 300 | same config as eval_id, new seed, generated after all development | **clean headline** |

## The model names you'll see
| Name | Run id | What it is |
|---|---|---|
| A | `final-A-s4` | adapted base + twins distillation + post-train, **no** pre-checker |
| B | `final-B-s4` | same + pre-checker reader v2 (result before the diagnosis below) |
| **B2 (shipped)** | `final-Brun2-s4` | same pipeline, pre-checker reader v3, 25% blank-block training |
| halfway | `*-s3` | the same model before stage-4 post-training |

**The diagnosis, in one line:** B scored 98% on dev but 93% on eval_id because the pre-checker's reader only knew the training layouts; the frozen sets caught it, reader v3 + a format fuzzer fixed it, and eval_id v2 re-tests cleanly. Full story: [`documentation/04_results/findings_log.md`](documentation/04_results/findings_log.md) §5b–5c.

## Where everything is documented
- **Numbers:** [`documentation/04_results/`](documentation/04_results/) (headline tables, full report, evidence log).
- **Decisions and why:** [`documentation/01_decisions/decision_log.md`](documentation/01_decisions/decision_log.md).
- **Every agent session:** what it was asked ([`06_agent_instructions/`](documentation/06_agent_instructions/README.md)) and what it reported ([`05_progress_reports/`](documentation/05_progress_reports/README.md)).
- **The case requirements, mapped to this repo:** [`documentation/00_requirements/REQUIREMENTS.md`](documentation/00_requirements/REQUIREMENTS.md).

Python folder names can't start with a digit, hence `step1_…` rather than `1_…`.
