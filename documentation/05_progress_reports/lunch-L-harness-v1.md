# Lunch L: harness check on schema v1 (fake models)

**Result: pass.** On both v1 gold sets the oracle scores **100% on every quality metric** (0.0% unsupported claims) and broken JSON scores **0%** on every metric. Checked programmatically from the saved `metrics.json` (every rate key of the oracle is exactly 1.0; every rate key of broken_json is exactly 0.0), not just by eye.

Gold sets: `data/dev/cases.jsonl` (150 cases) and `data/train/cases.jsonl` (3,000 cases), both built by `step1_data_generation/build.py` under policy v1. No eval file was touched.

## Reproduce
```bash
for d in dev train; do
  python -m tests.c_fakes run --gold data/$d/cases.jsonl --schema step0_rules/schema/v1.json \
      --config step6_evaluation/fieldmap_v1.yaml --out /tmp/hc_$d/outputs
  python -m step6_evaluation.report /tmp/hc_$d/outputs --config step6_evaluation/fieldmap_v1.yaml \
      --schema step0_rules/schema/v1.json --json /tmp/hc_$d/metrics.json
done
```

## What changed in the harness for v1 (all opt-in; v0 behaviour unchanged)
| Change | Where | Why |
|---|---|---|
| `step6_evaluation/fieldmap_v1.yaml` | new | flat paths (`name_status`, `identity_verified`, ...) |
| `narrative_hit_ids_key: hit_ids` | `FieldMap` + `score_case` | D3: every id in a sentence's `hit_ids` must resolve like a ref (a fabricated `H93` is unsupported); an empty list adds nothing |
| `gold_ref_ids_key: ref_ids` | case rows now carry `ref_ids` | the section-enum refs valid for that packet (`id_document_mrz` only when the document has an MRZ) plus its hit ids |
| `field_mean_exclude: [verified]` | `FieldMap` + `aggregate` | D15: `verified` gets its own column, outside the field-accuracy mean |
| `adv_escalation_gold_escalate_only: true` | `FieldMap` + `aggregate` | D5: an injected packet that also has a sanctions true match or clear tamper evidence is a gold **reject**. Without this the oracle's adversarial escalation rate would be 96.6% on train (448 of 464). The rate now covers gold-escalate adversarial cases; adversarial decision accuracy still covers all of them |
| adversarial `ambiguous` subset = `insufficient_evidence` + `partial_dob` | fieldmap | the two scenarios whose evidence cannot settle the case |
| `hallucinated_refs` fake writes a fake `hit_ids` entry when the FieldMap has `narrative_hit_ids_key` | `tests/c_fakes.py` | v1 refs are an enum: a fabricated ref string would make the output schema-invalid instead of unsupported |

## Expectations vs observed (train, 3,000)
| Fake | Expected | Observed | OK |
|---|---|---|---|
| oracle | 100% everywhere, 0% unsupported | 100% everywhere, 0.0% | yes |
| broken_json | 0% everywhere | 0% everywhere | yes |
| always_escalate | decision acc = gold escalate share (47.3%) | 47.3% | yes |
| random | ~1/3 on 3-way labels | decision 33–36%, fields ~32% | yes |
| corrupted (p=0.2) | ~80% | decision ~80%, fields ~83% | yes |
| hallucinated_refs | ~50% unsupported, rest 100% | ~51% | yes |

`random` and `corrupted` now show a few % unsupported claims: they flip `evidence_refs` enum values, and `id_document_mrz` on a document without an MRZ correctly fails to resolve.

## Dev (150), verbatim from the report
## Table 1: models × metrics

| Model | Params | Cases | Valid % | Decision acc % | Screening macro-F1 % | Field acc % (mean) | Risk exact % | Risk ±1 % | Actions recall % | Actions precision % | Unsupported claims % | Adversarial escalation % | p50 ms | p95 ms | $ / 1k cases |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| fake:always_escalate | 0 | 150 | 100.0 [100.0, 100.0] | 55.3 [47.3, 63.3] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 0.0 [0.0, 0.0] | 100.0 [100.0, 100.0] | 668 | 1,003 | $0.148 |
| fake:broken_json | 0 | 150 | 0.0 [0.0, 0.0] | 0.0 [0.0, 0.0] | 0.0 [0.0, 0.0] | 0.0 [0.0, 0.0] | 0.0 [0.0, 0.0] | 0.0 [0.0, 0.0] | 0.0 [0.0, 0.0] | n/a | n/a | 0.0 [0.0, 0.0] | 693 | 1,045 | $0.159 |
| fake:corrupted | 0 | 150 | 100.0 [100.0, 100.0] | 82.7 [76.7, 88.7] | 67.4 [58.6, 76.0] | 79.7 [76.8, 82.4] | 82.7 [76.0, 88.7] | 96.0 [92.7, 98.7] | 81.3 [76.0, 86.3] | 28.7 [25.0, 32.1] | 2.3 [1.1, 3.6] | 84.6 [75.0, 94.7] | 678 | 1,138 | $0.155 |
| fake:hallucinated_refs | 0 | 150 | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 51.4 [50.8, 51.9] | 100.0 [100.0, 100.0] | 671 | 1,108 | $0.157 |
| fake:oracle | 0 | 150 | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 0.0 [0.0, 0.0] | 100.0 [100.0, 100.0] | 702 | 1,134 | $0.161 |
| fake:random | 0 | 150 | 100.0 [100.0, 100.0] | 42.7 [34.7, 50.7] | 25.7 [19.5, 31.3] | 32.7 [29.2, 35.9] | 31.3 [24.0, 38.7] | 84.7 [78.0, 90.0] | 52.4 [45.3, 59.5] | 9.4 [7.7, 11.3] | 6.2 [3.7, 9.2] | 30.8 [16.7, 43.8] | 687 | 1,090 | $0.160 |

Unsupported claims: share of checked narrative sentences whose `evidence_refs` are missing or do not resolve to the packet (programmatic check only; no LLM judge yet). Lower is better. Latency and cost are point estimates from the saved per-case measurements.

### Table 1b: per-field accuracy, adversarial subsets, counts

| Model | verified acc % | name acc % | date_of_birth acc % | document_number acc % | expiry acc % | address acc % | Esc. injection % (n) | Esc. ambiguous % (n) | Adv. decision acc % | Hits | Extra hits | Sentences checked | Missing preds |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| fake:always_escalate | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 (16) | 100.0 (11) | 96.3 | 166 | 0 | 928 | 0 |
| fake:broken_json | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 (16) | 0.0 (11) | 0.0 | 166 | 0 | 0 | 0 |
| fake:corrupted | 80.0 | 77.3 | 73.3 | 81.3 | 84.0 | 82.7 | 86.7 (16) | 81.8 (11) | 85.2 | 166 | 0 | 928 | 0 |
| fake:hallucinated_refs | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 (16) | 100.0 (11) | 100.0 | 166 | 0 | 928 | 0 |
| fake:oracle | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 (16) | 100.0 (11) | 100.0 | 166 | 0 | 928 | 0 |
| fake:random | 50.7 | 38.7 | 32.7 | 36.0 | 27.3 | 28.7 | 20.0 (16) | 45.5 (11) | 33.3 | 166 | 0 | 928 | 0 |

## Table 1: models × metrics

| Model | Params | Cases | Valid % | Decision acc % | Screening macro-F1 % | Field acc % (mean) | Risk exact % | Risk ±1 % | Actions recall % | Actions precision % | Unsupported claims % | Adversarial escalation % | p50 ms | p95 ms | $ / 1k cases |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| fake:always_escalate | 0 | 150 | 100.0 [100.0, 100.0] | 55.3 [47.3, 63.3] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 0.0 [0.0, 0.0] | 100.0 [100.0, 100.0] | 668 | 1,003 | $0.148 |
| fake:broken_json | 0 | 150 | 0.0 [0.0, 0.0] | 0.0 [0.0, 0.0] | 0.0 [0.0, 0.0] | 0.0 [0.0, 0.0] | 0.0 [0.0, 0.0] | 0.0 [0.0, 0.0] | 0.0 [0.0, 0.0] | n/a | n/a | 0.0 [0.0, 0.0] | 693 | 1,045 | $0.159 |
| fake:corrupted | 0 | 150 | 100.0 [100.0, 100.0] | 80.7 [74.0, 86.7] | 62.4 [54.2, 71.1] | 82.8 [80.1, 85.3] | 83.3 [77.3, 88.7] | 98.0 [95.3, 100.0] | 81.3 [75.7, 86.9] | 29.4 [25.3, 33.3] | 2.6 [1.4, 4.2] | 88.5 [78.6, 100.0] | 630 | 1,136 | $0.151 |
| fake:hallucinated_refs | 0 | 150 | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 51.4 [50.8, 51.9] | 100.0 [100.0, 100.0] | 671 | 1,108 | $0.157 |
| fake:oracle | 0 | 150 | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 0.0 [0.0, 0.0] | 100.0 [100.0, 100.0] | 702 | 1,134 | $0.161 |
| fake:random | 0 | 150 | 100.0 [100.0, 100.0] | 33.3 [25.3, 40.7] | 27.8 [21.2, 34.5] | 32.1 [28.7, 35.2] | 36.0 [28.7, 43.3] | 87.3 [82.0, 92.0] | 56.7 [49.1, 63.7] | 10.0 [8.2, 11.8] | 6.4 [4.0, 9.2] | 42.3 [26.7, 57.1] | 666 | 1,076 | $0.158 |

Unsupported claims: share of checked narrative sentences whose `evidence_refs` are missing or do not resolve to the packet (programmatic check only; no LLM judge yet). Lower is better. Latency and cost are point estimates from the saved per-case measurements.

### Table 1b: per-field accuracy, adversarial subsets, counts

| Model | verified acc % | name acc % | date_of_birth acc % | document_number acc % | expiry acc % | address acc % | Esc. injection % (n) | Esc. ambiguous % (n) | Adv. decision acc % | Hits | Extra hits | Sentences checked | Missing preds |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| fake:always_escalate | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 (16) | 100.0 (11) | 96.3 | 166 | 0 | 928 | 0 |
| fake:broken_json | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 (16) | 0.0 (11) | 0.0 | 166 | 0 | 0 | 0 |
| fake:corrupted | 78.0 | 81.3 | 71.3 | 86.0 | 86.0 | 89.3 | 86.7 (16) | 90.9 (11) | 88.9 | 166 | 0 | 928 | 0 |
| fake:hallucinated_refs | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 (16) | 100.0 (11) | 100.0 | 166 | 0 | 928 | 0 |
| fake:oracle | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 (16) | 100.0 (11) | 100.0 | 166 | 0 | 928 | 0 |
| fake:random | 46.0 | 32.0 | 34.7 | 32.0 | 27.3 | 34.7 | 40.0 (16) | 45.5 (11) | 40.7 | 166 | 0 | 928 | 0 |

## Train (3,000), verbatim from the report
## Table 1: models × metrics

| Model | Params | Cases | Valid % | Decision acc % | Screening macro-F1 % | Field acc % (mean) | Risk exact % | Risk ±1 % | Actions recall % | Actions precision % | Unsupported claims % | Adversarial escalation % | p50 ms | p95 ms | $ / 1k cases |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| fake:always_escalate | 0 | 3000 | 100.0 [100.0, 100.0] | 47.3 [45.5, 49.1] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 0.0 [0.0, 0.0] | 100.0 [100.0, 100.0] | 667 | 1,099 | $0.155 |
| fake:broken_json | 0 | 3000 | 0.0 [0.0, 0.0] | 0.0 [0.0, 0.0] | 0.0 [0.0, 0.0] | 0.0 [0.0, 0.0] | 0.0 [0.0, 0.0] | 0.0 [0.0, 0.0] | 0.0 [0.0, 0.0] | n/a | n/a | 0.0 [0.0, 0.0] | 666 | 1,102 | $0.155 |
| fake:corrupted | 0 | 3000 | 100.0 [100.0, 100.0] | 79.3 [77.9, 80.7] | 70.5 [68.5, 72.6] | 79.9 [79.2, 80.5] | 79.7 [78.3, 81.2] | 95.3 [94.5, 96.1] | 79.2 [77.9, 80.6] | 26.0 [25.1, 26.9] | 3.2 [2.9, 3.5] | 81.0 [78.5, 83.6] | 667 | 1,084 | $0.155 |
| fake:hallucinated_refs | 0 | 3000 | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 51.0 [51.0, 51.1] | 100.0 [100.0, 100.0] | 665 | 1,093 | $0.154 |
| fake:oracle | 0 | 3000 | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 0.0 [0.0, 0.0] | 100.0 [100.0, 100.0] | 661 | 1,080 | $0.154 |
| fake:random | 0 | 3000 | 100.0 [100.0, 100.0] | 34.4 [32.7, 36.1] | 27.2 [25.7, 28.6] | 33.2 [32.5, 34.0] | 32.7 [31.1, 34.4] | 84.6 [83.3, 85.9] | 50.5 [48.7, 52.2] | 8.1 [7.7, 8.5] | 4.8 [4.3, 5.4] | 33.9 [30.5, 37.1] | 666 | 1,096 | $0.155 |

Unsupported claims: share of checked narrative sentences whose `evidence_refs` are missing or do not resolve to the packet (programmatic check only; no LLM judge yet). Lower is better. Latency and cost are point estimates from the saved per-case measurements.

### Table 1b: per-field accuracy, adversarial subsets, counts

| Model | verified acc % | name acc % | date_of_birth acc % | document_number acc % | expiry acc % | address acc % | Esc. injection % (n) | Esc. ambiguous % (n) | Adv. decision acc % | Hits | Extra hits | Sentences checked | Missing preds |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| fake:always_escalate | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 (215) | 100.0 (263) | 96.6 | 3363 | 0 | 18404 | 0 |
| fake:broken_json | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 (215) | 0.0 (263) | 0.0 | 3363 | 0 | 0 | 0 |
| fake:corrupted | 80.0 | 80.6 | 80.7 | 79.2 | 79.2 | 79.5 | 80.9 (215) | 80.6 (263) | 80.6 | 3363 | 0 | 18404 | 0 |
| fake:hallucinated_refs | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 (215) | 100.0 (263) | 100.0 | 3363 | 0 | 18404 | 0 |
| fake:oracle | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 (215) | 100.0 (263) | 100.0 | 3363 | 0 | 18404 | 0 |
| fake:random | 49.5 | 31.6 | 33.0 | 34.2 | 33.5 | 33.8 | 33.7 (215) | 35.0 (263) | 33.8 | 3363 | 0 | 18404 | 0 |

## Table 1: models × metrics

| Model | Params | Cases | Valid % | Decision acc % | Screening macro-F1 % | Field acc % (mean) | Risk exact % | Risk ±1 % | Actions recall % | Actions precision % | Unsupported claims % | Adversarial escalation % | p50 ms | p95 ms | $ / 1k cases |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| fake:always_escalate | 0 | 3000 | 100.0 [100.0, 100.0] | 47.3 [45.5, 49.1] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 0.0 [0.0, 0.0] | 100.0 [100.0, 100.0] | 667 | 1,099 | $0.155 |
| fake:broken_json | 0 | 3000 | 0.0 [0.0, 0.0] | 0.0 [0.0, 0.0] | 0.0 [0.0, 0.0] | 0.0 [0.0, 0.0] | 0.0 [0.0, 0.0] | 0.0 [0.0, 0.0] | 0.0 [0.0, 0.0] | n/a | n/a | 0.0 [0.0, 0.0] | 666 | 1,102 | $0.155 |
| fake:corrupted | 0 | 3000 | 100.0 [100.0, 100.0] | 80.7 [79.2, 82.1] | 68.8 [66.9, 70.9] | 80.2 [79.5, 80.8] | 79.9 [78.5, 81.4] | 95.3 [94.5, 96.0] | 78.4 [76.9, 79.8] | 25.7 [24.8, 26.5] | 3.2 [2.9, 3.5] | 80.8 [78.1, 83.6] | 667 | 1,098 | $0.155 |
| fake:hallucinated_refs | 0 | 3000 | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 51.0 [51.0, 51.1] | 100.0 [100.0, 100.0] | 665 | 1,093 | $0.154 |
| fake:oracle | 0 | 3000 | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0] | 0.0 [0.0, 0.0] | 100.0 [100.0, 100.0] | 661 | 1,080 | $0.154 |
| fake:random | 0 | 3000 | 100.0 [100.0, 100.0] | 33.6 [31.8, 35.4] | 27.2 [25.7, 28.6] | 33.6 [32.8, 34.3] | 33.8 [32.1, 35.4] | 84.8 [83.4, 86.0] | 51.4 [49.7, 53.0] | 8.3 [7.9, 8.7] | 4.7 [4.2, 5.2] | 37.3 [33.9, 40.5] | 669 | 1,095 | $0.156 |

Unsupported claims: share of checked narrative sentences whose `evidence_refs` are missing or do not resolve to the packet (programmatic check only; no LLM judge yet). Lower is better. Latency and cost are point estimates from the saved per-case measurements.

### Table 1b: per-field accuracy, adversarial subsets, counts

| Model | verified acc % | name acc % | date_of_birth acc % | document_number acc % | expiry acc % | address acc % | Esc. injection % (n) | Esc. ambiguous % (n) | Adv. decision acc % | Hits | Extra hits | Sentences checked | Missing preds |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| fake:always_escalate | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 (215) | 100.0 (263) | 96.6 | 3378 | 0 | 18404 | 0 |
| fake:broken_json | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 (215) | 0.0 (263) | 0.0 | 3378 | 0 | 0 | 0 |
| fake:corrupted | 80.3 | 78.6 | 80.8 | 81.1 | 80.9 | 79.6 | 80.9 (215) | 80.2 (263) | 80.8 | 3378 | 0 | 18404 | 0 |
| fake:hallucinated_refs | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 (215) | 100.0 (263) | 100.0 | 3378 | 0 | 18404 | 0 |
| fake:oracle | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 (215) | 100.0 (263) | 100.0 | 3378 | 0 | 18404 | 0 |
| fake:random | 50.1 | 34.5 | 33.4 | 33.6 | 33.5 | 32.8 | 34.7 (215) | 38.0 (263) | 36.9 | 3378 | 0 | 18404 | 0 |
