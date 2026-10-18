# results — the saved per-case outputs behind every reported number (pipeline stages 1 and 5 of the brief)

## What it does
- Stores the raw predictions of every model × eval set that appears in a table, so every number can be rebuilt with no API and no GPU.
- Stores the unsupported-claims judge verdicts, the measured endpoint latency, the price table and the computed metrics.
- Stores the recorded LLM responses needed to rebuild the LLM-written OOD eval set offline.

## Key files
| Path | What it is |
|---|---|
| `runs/<model>__<prompt>__<set>/`, `runs/<run>__<set>/` | 52 runs. Each has `predictions.jsonl` (raw output per case), `run.json` (table metadata) and `provenance.json` (source, sha256, request settings, API cost ledger) |
| `runs/final-Brun2-s4__*` | The final model B2 on dev, frozen eval v1 (500), eval_hard (150) and eval_id v2 (300) |
| `runs/final-A-*`, `runs/final-B-*`, `runs/final-Brun2-s3__*` | Earlier finals A and B, and each pipeline's stage-3 ("halfway") checkpoint |
| `runs/*-r31__eval_id_v2` | B2 checkpoints served with pre-checker reader v3.1 (swap test) |
| `runs/distill-4b-*__dev`, `runs/sft-gold-*__dev` | Recipe comparison and gold-label size sweep on dev |
| `report_metrics.json` | Per-run metrics, 95% CIs and diagnostics (written by `make_tables.sh`) |
| `judge/` | Unsupported-claims verdicts: `eval_id/` (prompt v2, used), `eval_id_packet_only/` (v1, provenance), `eval_id_v2/` |
| `latency/final-Brun2-s4.json`, `latency/final-Brun2-s4-h100.json` | Measured endpoint latency and cost (L4, H100), plus the per-case runs |
| `prices.yaml`, `pending.yaml` | Price table for self-hosted runs (L4, 16 concurrent); placeholder rows for the report |
| `eval_regen/ood_llm_cache/` | Recorded LLM responses replayed by `regenerate_eval.sh` |

## How to use
```bash
bash make_tables.sh                                  # rebuild every table from runs/ (free, ~2 min, byte-identical)
python -m step6_evaluation.make_submission_report    # headline tables from report_metrics.json + latency/
python -m step6_evaluation.judge_claims results/runs/<run_id> --gold data/eval_id_v2/cases.jsonl \
    --out results/judge/eval_id_v2 --summary-only    # judge rates from saved verdicts (free)
```
The runs were packaged once from local `outputs/` with `python -m step6_evaluation.collect_runs --src <outputs dir>` (copies only, nothing re-scored).

## Outputs / where results live
- Tables built from this folder: `documentation/04_writeup/benchmark_report.md` and `documentation/04_writeup/benchmark_report_submission.md`.
- Frozen eval v1 runs (`__eval_v1`) concatenate the 4 split predictions in this order: eval_id, eval_ood_template, eval_ood_hand, eval_ood_llm.

## Reports and evidence
- [Headline tables](../documentation/04_writeup/benchmark_report_submission.md), [full generated report](../documentation/04_writeup/benchmark_report.md)
- [Judge README: prompt versions, spot checks, cost](judge/README.md)
- [Evidence log §3 (frontier panel), §5c (frozen results), §8 (cost)](../documentation/04_writeup/writeup_evidence_log.md)
- [SUNDAY_DELIVERABLES.md](../documentation/06_agent_instructions/SUNDAY_DELIVERABLES.md) (packaging and regeneration), [BIGRUNS.md](../documentation/06_agent_instructions/BIGRUNS.md) (frontier and open benchmark runs)

## Details

### Run naming
- Baselines: `<model>__<prompt>__<set>`, with prompt `baseline_zero_shot` or `baseline_best` (rulebook + few-shot), set `eval_v1`, `eval_hard` or `eval_id_v2`.
- Our models: `<run>__<set>`, with set `dev`, `eval_v1`, `eval_hard` or `eval_id_v2`. `-s3` = after distillation (stage 3), `-s4` = after the stage-4 post-train.
- Model ids: A = `final-A-s4` (no pre-checks), B = `final-B-s4` (pre-checker v2, before the diagnosis), B2 = `final-Brun2-s4` (pre-checker v3, 25% blank blocks in training; the final model).

### Headline (eval_id v2, 300 cases, decision accuracy)
B2 96.3%; GPT-6 Astra 99.3%, Claude Opus 5.5 97.7%, Gemini 4 Argon 95.0% (best prompt); untrained Qwen3.5-4B 56.0% (best prompt). Full numbers and CIs are in the submission report.

### Latency (B2, 100 dev cases, 1 request at a time)
L4: p50 24.3 s, p95 29.1 s, $5.36 per 1k. H100: p50 3.3 s, p95 3.8 s, $3.59 per 1k. At 16 concurrent requests on L4 the eval runs cost about $0.47 per 1k.

### pending.yaml
It still lists "B-v3" placeholder rows and a PENDING section (B-v3 was the working name for B2). The B2 runs now exist, so the full report shows a few PENDING rows next to the real B2 rows. The submission report does not use this file.
