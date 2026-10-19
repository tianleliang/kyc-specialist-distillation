# step6_evaluation — metrics, benchmark tables, eval freeze and leak checks (pipeline stage 5 of the brief)

## What it does
- Scores saved predictions on every metric in the brief (decision, screening macro-F1, risk tier, actions, identity fields, schema validity, latency, cost). Invalid or missing output scores zero, never dropped.
- Builds the benchmark tables (Table 1: models × metrics; Table 2: gain per stage, paired bootstrap 95% CIs) from `results/runs/`. No API, no GPU.
- Freezes eval files by sha256 and checks that no eval case leaks into training (`split_guard.py`); rebuilds every frozen split from its seed and verifies the hashes (`regenerate_eval.py`).
- Runs the blind LLM judge for the "unsupported claims" metric (`judge_claims.py`).

## Key files
| File | What it is |
|---|---|
| `metrics.py` | Schema-agnostic per-case scoring + aggregation + bootstrap CIs; locations come from a FieldMap |
| `fieldmap_v1.yaml` | FieldMap for schema v1 (where each scored value lives) |
| `report.py` | Full benchmark report (markdown + JSON) from run dirs; used by `make_tables.sh` |
| `make_submission_report.py` | The short, paste-ready headline tables (B2 vs open and frontier) |
| `collect_runs.py` | One-time packaging of local `outputs/` runs into `results/runs/` (copies, never re-scores) |
| `judge_claims.py` | Unsupported-claims judge (Claude Sonnet), blind and resumable; `--summary-only` = no API |
| `split_guard.py` | `freeze` / `verify` / `check` (exact, n-gram containment, MinHash); `EvalGuard` for API clients |
| `regenerate_eval.py` | Rebuild each frozen split in a scratch dir and verify it (OOD-LLM replays a recorded cache) |

## How to use
From the repo root. All free unless marked.
```bash
bash make_tables.sh          # -> documentation/04_results/benchmark_report.md + results/report_metrics.json (~2 min, byte-identical)
python -m step6_evaluation.make_submission_report   # -> documentation/04_results/benchmark_report_submission.md
bash regenerate_eval.sh      # rebuild + verify every frozen eval split; never writes under data/

python -m step6_evaluation.split_guard verify --manifest data/eval/MANIFEST.json
python -m step6_evaluation.split_guard verify --manifest data/eval_v2/MANIFEST.json
python -m step6_evaluation.split_guard check --train data/sft/*.jsonl --eval data/eval_id/cases.jsonl

python -m step6_evaluation.report results/runs/final-Brun2-s4__eval_id_v2 \
    --config step6_evaluation/fieldmap_v1.yaml --schema step0_rules/schema/v1.json   # score one run

python -m step6_evaluation.judge_claims results/runs/<run_id> --gold data/eval_id_v2/cases.jsonl \
    --out results/judge/eval_id_v2 --summary-only                                      # rates from saved verdicts
python -m step6_evaluation.judge_claims results/runs/<run_id> --max-usd 50            # (API, costs money)
```
`make_submission_report.py` reads `results/report_metrics.json`, so run `make_tables.sh` first.

## Outputs / where results live
- `documentation/04_results/benchmark_report.md` (full report) and `documentation/04_results/benchmark_report_submission.md` (headline tables).
- `results/report_metrics.json` (per-run metrics, CIs, diagnostics).
- `results/judge/<set>/` (`verdicts.jsonl`, `calls.jsonl`, `summary.md`).
- Freeze manifests: `data/eval/MANIFEST.json` (frozen v1: eval_id + 3 OOD = 500), `data/eval_hard/manifest.json` (150), `data/eval_v2/MANIFEST.json` (eval_id v2, 300).

## Reports and evidence
- [Headline tables](../documentation/04_results/benchmark_report_submission.md), [full generated report](../documentation/04_results/benchmark_report.md)
- [Evidence log §2 (contamination controls), §3, §5c](../documentation/04_results/findings_log.md)
- [Contamination protocol](../documentation/03_design/contamination_protocol.md)
- [Judge README (prompt versions, spot checks, cost)](../results/judge/README.md)
- Session reports: [overnight-C.md](../documentation/05_progress_reports/overnight-C.md) (metrics), [overnight-C-harness-check.md](../documentation/05_progress_reports/overnight-C-harness-check.md), [lunch-L-harness-v1.md](../documentation/05_progress_reports/lunch-L-harness-v1.md), [overnight-F.md](../documentation/05_progress_reports/overnight-F.md) (split guard)
- [SUNDAY_DELIVERABLES.md](../documentation/06_agent_instructions/SUNDAY_DELIVERABLES.md) (packaging, regeneration, judge)

## Details

### Scoring rules
- The gold file defines the denominator. A case with no prediction, an unparseable prediction, or a schema-invalid prediction is wrong on every quality metric.
- Values missing from a valid output count as wrong. Values missing from gold drop that case out of that one metric only.
- Everything is computed from per-case records, so bootstrap resamples are cheap (`bootstrap_ci`, `paired_bootstrap_delta`).

### run.json keys read by report.py
`model`, `gold` (a path or a list concatenated in order, e.g. the 4 splits of frozen v1), `price_key`, `price_multiplier`, `params`, `table1_group`, `table1_order`, `display` (literal text instead of a number), and `pipeline` / `stage` / `stage_order` / `compare_to` for Table 2. `--pending` adds placeholder rows from a YAML.

### split_guard checks
- `exact`: identical normalized text. `containment`: share of an eval record's distinctive word n-grams found in one train record (catches a packet pasted inside an SFT prompt). `minhash`: near-duplicates.
- N-grams in more than `--max-df` of eval records are dropped first (template boilerplate).
- Exit codes: 0 clean, 1 contamination or manifest mismatch, 2 usage error.

### Judge
One Claude Sonnet call per packet. Sentences from all runs are pooled, de-duplicated, shuffled and renamed, so the judge never sees which run wrote them. Verdicts are keyed by (case, sentence hash), so adding a run judges only new sentences. Prompt v2 (packet + policy v1) is the default and is used in Table 1.
