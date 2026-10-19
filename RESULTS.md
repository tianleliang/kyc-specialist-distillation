# Results and progress, in one place

Every headline number, what it means, and the file it comes from. Tables are generated from `results/` by `bash make_tables.sh`; nothing here is hand-typed from memory. Model names: **A** = model alone, **B** = model + pre-checker v2 (before the diagnosis), **B2** = shipped model (pre-checker v3, blank-block training). See [GUIDE.md](GUIDE.md) for the pipeline and [process_log.md](documentation/04_results/process_log.md) for every decision, realization and failure.

## 1. Headline: fresh eval_id v2 (300 cases, generated after all development)
| Model | Decision acc. | Their acc. − ours (paired 95% CI) | Unsupported claims | p50 latency | $ / 1k cases |
|---|---|---|---|---|---|
| **B2 (ours, 4B)** | **96.3%** | – | 13.7% | 24.3 s (L4, hand-over) · 3.3 s (H100) | $5.36 (L4) · $3.59 (H100) · $0.47 (L4, 16 concurrent) |
| GPT-6 Astra | 99.3% | +3.0 (+0.7, +5.3): ahead | 7.4% | 12.1 s | $175 |
| Claude Opus 5.5 | 97.7% | +1.3 (−1.3, +4.0): tie | 8.6% | 11.5 s | $116 |
| Gemini 4 Argon | 95.0% | −1.3 (−4.7, +2.0): tie | 8.8% | 8.6 s | $37 |
| Qwen3.5-4B, untrained | 56.0% | −40.3 | 52.0% | | |

Source: [benchmark_report_submission.md](documentation/04_results/benchmark_report_submission.md) Table 1 (all metrics, case counts) · latency: [results/latency/](results/latency/) · judge: [results/judge/](results/judge/README.md).

## 2. What each stage bought (eval_id v2, paired 95% CI)
| Stage | Decision acc. | Δ |
|---|---|---|
| Qwen3.5-4B, zero-shot | 56.3% | |
| + rulebook in the prompt (best prompt) | 56.0% | −0.3 (−6.0, +5.7) |
| + domain adapter + Counterfactual Twin Distillation | 88.7% | **+32.7** (+26.0, +39.3) |
| + code pre-checker (reader v3) | 96.7% | **+8.0** (+4.3, +11.7) |
| + post-train (SFT on exact labels) = B2 | 96.3% | −0.3 (−1.7, +0.7) |

Source: [benchmark_report_submission.md](documentation/04_results/benchmark_report_submission.md) Table 2.

## 3. Stage by stage
| Stage | Result | Evidence |
|---|---|---|
| Rules + data | Policy re-derived from its text by an independent agent: 600/600 labels match; 2 label bugs found and fixed | [lunch-L.md](documentation/05_progress_reports/lunch-L.md), [step0_rules/policy_v1.md](step0_rules/policy_v1.md) |
| 1 Benchmark | Frontier with rulebook (frozen 500): Astra 99.2, Opus 98.4, Argon 95.8; zero-shot 87.6–92.6. Untrained Qwen 0.8B / 2B / 4B, best prompt: 40 / 39 / 61 (zero-shot 40 / 29 / 60) | [Appendix B](documentation/04_results/benchmark_report_submission.md) |
| Size choice | Trained on the answer key, dev: 0.8B 84.0, 2B 86.7, 4B 90.0 → 4B by the pre-set rule (smallest within 2 pts of 4B) | [Appendix C](documentation/04_results/benchmark_report_submission.md), [results/runs/](results/runs/), [decision_log.md](documentation/01_decisions/decision_log.md) |
| 2 Domain adapter | Held-out perplexity 7.39 → 5.52 (−25%); probe 61 → 65%; task on dev +0.7 (1 case): a null on the task | [adapter_4b_measure.log](step5_training/results/logs/adapter_4b_measure.log), [measure_adapter_4b.json](results/adapter/measure_adapter_4b.json) |
| 3 Distillation (dev, 4B) | Answer-key ceiling 90.0 · floor 89.3 · + rejection 91.3 · + arbitration 90.0 · **+ Counterfactual Twins 90.7** (best actions recall 90.5, fewest wrong approvals 6). Teacher Sol matched the answer key on 99.3% → flat by construction. Twins at 0.8B: +3.3. Sol flipped correctly on 98.6% of 1,000 twin pairs | [Appendix C](documentation/04_results/benchmark_report_submission.md), [findings_log.md §5b](documentation/04_results/findings_log.md), [distill_twins_sol.jsonl.stats.json](data/sft/distill_twins_sol.jsonl.stats.json) |
| 4 Post-train | SFT on exact labels + teacher narratives, chosen because the labels are exact (DPO had ~30 rejected answers to contrast; RL too slow for the deadline): ±0 (Table 2) | Table 2, [findings_log.md §5b](documentation/04_results/findings_log.md) |
| Pre-checker v2 | Halfway checkpoints (B vs A, before post-train): +6.0 dev, +3.0 frozen 500, +6.7 hard; final models: +2.4 frozen 500, +8.0 hard | [Appendix A](documentation/04_results/benchmark_report_submission.md), `results/runs/final-{A,B}-s3__*` |
| **Diagnosis** | B: dev 98.0 vs eval_id 93.0. The reader only knew the 4 training layouts (`ocr_dump` 100% "not determinable", LLM prose ~100%); with an empty block B fell below A on LLM-written packets (86 vs 94) | [findings_log.md §5c](documentation/04_results/findings_log.md) |
| Reader v3 + fuzzer | 0 wrong values on all 6 generator layouts, 90–99% readable (`ocr_dump` 0 → 94–97%); random-layout fuzzer with a held-out family | [p3_reader_v3_gate.md](step7_serving/results/p3_reader_v3_gate.md), [fuzz_report.md](step7_serving/results/fuzz_report.md) |
| B2 on every set | eval_id v2 96.3 · eval_id 96.0 · OOD template 94 / hand 92 / LLM 92 · frozen 500 94.6 · hard 92.7 | [Appendix A](documentation/04_results/benchmark_report_submission.md) |
| Reader v3.1 swap | Swapped in at serving without retraining: identical scores → ship v3 | [reader_v31_final_342d0d3_vs_freeze_F.md](step7_serving/results/reader_v31_final_342d0d3_vs_freeze_F.md), `results/runs/*-r31__eval_id_v2` |
| 6 Serve | L4 hand-over endpoint p50 24.3 s / p95 29.1 s (100 cases, 100/100 agree with the evaluated run); H100 p50 3.3 s / p95 3.8 s (30 cases) | [results/latency/](results/latency/) |
| Contamination | All test sets frozen by sha256 before any teacher call; training-time gate 0 overlaps; `regenerate_eval.sh` rebuilds every set byte for byte | [data/eval/MANIFEST.json](data/eval/MANIFEST.json), [data/eval_hard/manifest.json](data/eval_hard/manifest.json), [data/eval_v2/MANIFEST.json](data/eval_v2/MANIFEST.json) |

## 4. Spend
| Item | USD | Source |
|---|---|---|
| OpenAI (GPT-6.1 Sol teacher, GPT-6 Astra baseline) | ~405 | per-run cost ledgers |
| Google (Gemini 4 Argon teacher + baseline) | ~138 | per-run cost ledgers |
| Anthropic (Claude Opus 5.5 baseline, Claude Sonnet 5.5 judge) | ~165 | per-run cost ledgers |
| **API total** | **~708** | ledgers in `results/runs/*/provenance.json`, `step4_distillation/teacher_outputs/*/ledger.json`, `results/judge/*/calls.jsonl` |
| Modal GPU (training, scoring, serving) | (final figure added at submission) | Modal billing dashboard |

## 5. Build timeline (Fri 10/16 night → Sun 10/18, ET)
| When | Phase | Brief / report |
|---|---|---|
| Fri night | Wave 1: building blocks, serving smoke test, metrics, API clients, research + design docs | [OVERNIGHT.md](documentation/06_agent_instructions/OVERNIGHT.md) → reports A–G in [05_progress_reports](documentation/05_progress_reports/README.md) |
| Sat 01:00–07:00 | Wave 2: decision sheet, prompts + proxy, generator v1, distillation data steps | [OVERNIGHT2.md](documentation/06_agent_instructions/OVERNIGHT2.md) → reports H–K |
| Sat morning | 20 design decisions (schema, policy, sizes, models) | [decision_sheet.md](documentation/01_decisions/decision_sheet.md), [decision_log.md](documentation/01_decisions/decision_log.md) |
| Sat midday | Schema v1, policy v1, all datasets, OOD sets, adapter code; eval frozen | [LUNCH.md](documentation/06_agent_instructions/LUNCH.md) → [lunch-L.md](documentation/05_progress_reports/lunch-L.md), [lunch-M.md](documentation/05_progress_reports/lunch-M.md) |
| Sat afternoon | Teacher answers, frontier + open benchmark | [BIGRUNS.md](documentation/06_agent_instructions/BIGRUNS.md) |
| Sat evening | Size choice, adapter check, 4 distillation recipes | [TONIGHT_4B.md](documentation/06_agent_instructions/TONIGHT_4B.md) |
| Sat night | Final runs A and B (stage 3 → stage 4 → scoring) | [FINAL_RUN_INFRA.md](documentation/06_agent_instructions/FINAL_RUN_INFRA.md), [FINAL_TONIGHT.md](documentation/06_agent_instructions/FINAL_TONIGHT.md) |
| Sun morning | Frozen results → diagnosis → reader v3 + fuzzer | [SUNDAY_READER_V3.md](documentation/06_agent_instructions/SUNDAY_READER_V3.md), [p3_reader_v3_gate.md](step7_serving/results/p3_reader_v3_gate.md) |
| Sun midday | Deliverables packaging + LLM judge; B2 retrain; eval_id v2 | [SUNDAY_DELIVERABLES.md](documentation/06_agent_instructions/SUNDAY_DELIVERABLES.md), [SUNDAY_BRUN2.md](documentation/06_agent_instructions/SUNDAY_BRUN2.md) |
| Sun afternoon | Reader swap test, endpoint, latency (L4 + H100), weights, open baselines on eval_id v2 | [SUNDAY_BRUN2.md](documentation/06_agent_instructions/SUNDAY_BRUN2.md) steps ③–⑨ |

Every finding with its reasoning, in order: [documentation/04_results/findings_log.md](documentation/04_results/findings_log.md).
