# Case requirements → where they are met

The case brief itself is confidential and not in this repo; this is our own checklist of its requirements (paraphrased) and where each is satisfied.

## Deliverables
| Requirement | Where |
|---|---|
| OpenAI-compatible chat-completions endpoint, bearer token, model name, hardware | [`README.md`](../../README.md#endpoint-weights) · [`step7_serving/`](../../step7_serving/README.md) (`deploy_endpoint.sh`, `modal_vllm.py`, `proxy.py`) |
| p50 / p95 latency per case and cost per 1,000 cases, **measured** | `results/latency/final-Brun2-s4.json` (L4, 100 cases) and `final-Brun2-s4-h100.json` (H100, 30 cases); `step7_serving/measure_latency.py`; Table 1b |
| Weights and adapters downloadable | Merged weights (public): https://huggingface.co/tianle-terrence-liang/zorbe-kyc-specialist-4b (`step7_serving/upload_hf.py`); LoRA adapters (domain adapter, stage 3, stage 4) on request |
| Benchmark table: our model, each open baseline, each frontier model, same held-out set, all metrics, case counts | [`benchmark_report_submission.md`](../04_results/benchmark_report_submission.md) Table 1 (eval_id v2) · full report with CIs: [`benchmark_report.md`](../04_results/benchmark_report.md) |
| Second table: delta from each pipeline stage | `benchmark_report_submission.md` Table 2 (paired 95% CIs) |
| Repo: output schema | [`step0_rules/schema/v1.json`](../../step0_rules/schema/v1.json) |
| Repo: data generation | [`step1_data_generation/`](../../step1_data_generation/README.md) |
| Repo: training | [`step3_domain_adapter/`](../../step3_domain_adapter/README.md), [`step4_distillation/`](../../step4_distillation/README.md), [`step5_training/`](../../step5_training/README.md) |
| Repo: evaluation harness | [`step6_evaluation/`](../../step6_evaluation/README.md) |
| Repo: serving | [`step7_serving/`](../../step7_serving/README.md) |
| One command reproduces the evaluation table from saved outputs | `bash make_tables.sh` (reads `results/runs/`; no keys, no GPU) |
| One command regenerates the evaluation set | `bash regenerate_eval.sh` (rebuilds every frozen split from its seed, verifies sha256 manifests) |
| Write-up (≤ 4 pages): choices, failures, invented technique, contamination controls, stages 7–9 | Submitted as PDF; all source facts in [`findings_log.md`](../04_results/findings_log.md) |

## Pipeline stages
| Stage | What was required | Where / result |
|---|---|---|
| 1 Benchmark | ≥ 3 open models across sizes, ≥ 3 frontier models, zero-shot + best prompt, choose the smallest that can carry the task, show the curve | 3 Qwen3.5 sizes × 2 prompts, 3 frontier × 2 prompts (benchmark report Appendix B); size curve on dev and the pre-set selection rule (`documentation/01_decisions/decision_log.md`) |
| 2 Domain adapter | Adapt on public KYC/AML material; show whether it moved anything | `step3_domain_adapter/` (corpus + `SOURCES`), measure log `step5_training/results/logs/adapter_4b_measure.log` + `results/adapter/measure_adapter_4b.json`: held-out perplexity 7.39 → 5.52 (−25%), probe 61 → 65%; task effect on dev: twins on the adapted base 91.3% vs plain base 90.7% (1 case, noise; `results/runs/final-A-s3__dev` vs `distill-4b-twins__dev`) |
| 3 Distillation | Floor + ≥ 2 techniques + one invented and named; ablations | Floor, rejection sampling, multi-teacher arbitration, **Counterfactual Twin Distillation** (`step4_distillation/twins_filter.py`); dev ablation in `results/runs/distill-4b-*__dev` |
| 4 Post-train | A method chosen for a stated reason, before / after | SFT on exact labels + teacher narratives (`step4_distillation/gold_with_teacher_narrative.py`); before/after = Table 2 last row |
| 5 Evaluate | Same held-out set for all models; contamination control | Frozen manifests (`data/eval/MANIFEST.json`, `data/eval_hard/`, `data/eval_v2/`), training-time gate (`step5_training/common.py::contamination_gate`), `split_guard check`: 0 overlaps; fresh eval_id v2 after the diagnosis |
| 6 Serve | Endpoint up after submission; first request works; measured latency/cost | Always-warm L4 (`min_containers=1`); `step7_serving/endpoint_parity.py` checks the endpoint sends the evaluated request |
| 7–9 | Written answers | In the write-up PDF |

## Metrics (all in Table 1)
Decision accuracy · screening macro-F1 · accuracy per identity field · risk tier exact and ±1 · required-actions recall (and precision) · unsupported narrative claims (blind LLM judge, `step6_evaluation/judge_claims.py`, `results/judge/`) · schema validity · escalation on injected and ambiguous cases · p50 / p95 latency, cost per 1,000, parameters. Definitions: `step6_evaluation/metrics.py`.

## Ground rules
| Rule | How |
|---|---|
| Synthetic data only | Answer-first generator; synthetic names and list entries (`step1_data_generation/lib/`) |
| Base-model license stated | Qwen3.5-4B, Apache 2.0: commercial use and derivative weights allowed |
| Frontier models as teachers / judges / baselines only, all named | README "Models, assistants, data" |
| Report spend | Write-up; per-run API cost ledgers in `results/runs/*/provenance.json` |
| Coding assistants listed; decisions are the author's | README; `documentation/01_decisions/decision_log.md`; agent briefs and reports in `documentation/06_agent_instructions/`, `documentation/05_progress_reports/` |
