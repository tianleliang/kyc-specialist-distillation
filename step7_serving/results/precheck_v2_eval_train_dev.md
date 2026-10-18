# Pre-checker v2: document integrity (policy_v1 §3) vs gold, train + dev

`python -m step7_serving.precheck_eval --md step7_serving/results/precheck_v2_eval_train_dev.md --json step7_serving/results/precheck_v2_eval_train_dev.json`

Computed integrity class vs the gold identity reason code; coverage = share not n/d.

| split | field | n | coverage | accuracy (when determinable) | errors |
|---|---|---:|---:|---:|---:|
| train | integ_date_of_birth | 3000 | 96.1% | 100.00% | 0 |
| train | integ_document_number | 3000 | 100.0% | 100.00% | 0 |
| train | integ_expiry | 3000 | 96.2% | 100.00% | 0 |
| train | integ_overall | 3000 | 95.9% | 100.00% | 0 |
| dev | integ_date_of_birth | 150 | 97.3% | 100.00% | 0 |
| dev | integ_document_number | 150 | 100.0% | 100.00% | 0 |
| dev | integ_expiry | 150 | 97.3% | 100.00% | 0 |
| dev | integ_overall | 150 | 96.7% | 100.00% | 0 |

Confusions (wrong when determinable): none.

v1 fields (same run):

| split | field | n | coverage | accuracy (when determinable) | errors |
|---|---|---:|---:|---:|---:|
| train | as_of | 3000 | 100.0% | 100.00% | 0 |
| train | mrz | 2801 | 100.0% | 100.00% | 0 |
| train | expiry | 2911 | 95.9% | 100.00% | 0 |
| train | expired | 2911 | 95.9% | 100.00% | 0 |
| train | poa_date | 2972 | 89.5% | 100.00% | 0 |
| train | poa_window | 2972 | 89.5% | 100.00% | 0 |
| dev | as_of | 150 | 100.0% | 100.00% | 0 |
| dev | mrz | 137 | 100.0% | 100.00% | 0 |
| dev | expiry | 146 | 93.8% | 100.00% | 0 |
| dev | expired | 146 | 93.8% | 100.00% | 0 |
| dev | poa_date | 145 | 89.0% | 100.00% | 0 |
| dev | poa_window | 145 | 89.0% | 100.00% | 0 |

## Wrong dev decisions of `step5_training/results/dev_evals/distill-4b-twins__dev/predictions.jsonl`

| case | predicted | gold | v2 integrity line | integrity decides it | block states it |
|---|---|---|---|---|---|
| dev-2000000-000001 | reject | escalate | ambiguous | yes | yes |
| dev-2000000-000017 | reject | escalate | ambiguous | yes | yes |
| dev-2000000-000031 | escalate | reject | clear tamper | yes | yes |
| dev-2000000-000041 | reject | escalate | ambiguous | yes | yes |
| dev-2000000-000053 | approve | escalate | consistent | no | no |
| dev-2000000-000082 | approve | escalate | consistent | no | no |
| dev-2000000-000090 | reject | escalate | ambiguous | yes | yes |
| dev-2000000-000106 | approve | escalate | consistent | no | no |
| dev-2000000-000107 | approve | reject | clear tamper | yes | yes |
| dev-2000000-000110 | approve | escalate | consistent | no | no |
| dev-2000000-000111 | escalate | reject | clear tamper | yes | yes |
| dev-2000000-000133 | reject | escalate | ambiguous | yes | yes |
| dev-2000000-000134 | reject | escalate | ambiguous | yes | yes |
| dev-2000000-000136 | approve | reject | clear tamper | yes | yes |

10 of 14 wrong decisions now have the deciding fact stated in the block (10 of 14 are decided by §3).
