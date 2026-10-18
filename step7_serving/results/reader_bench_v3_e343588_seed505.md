# Reader bench: `/tmp/claude-0/sp/pc_d.py`

Sources: reader_dev, dev; 300 cases per family; seed 505. Cell = coverage (share not n/d); **Nx** = N wrong values.

## Fuzz families

| set | dropped | as_of | mrz | expiry | expired | poa_date | poa_window | integ_date_of_birth | integ_document_number | integ_expiry | integ_overall | wrong |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| F-kv | 0 | 94% | 100% | 97% | 91% | 83% | 78% | 61% | 89% | 72% | 51% | 0 |
| F-prose | 0 | 96% | 100% | 93% | 89% | 81% | 79% | 63% | 85% | 68% | 47% | 0 |
| F-email | 0 | 96% | 100% | 93% | 90% | 91% | 87% | 61% | 89% | 67% | 45% | 0 |
| F-table | 0 | 76% | 100% | 93% | 70% | 63% | 52% | 41% | 73% | 50% | 33% | 0 |
| F-json | 0 | 94% | 100% | 93% | 88% | 86% | 82% | 61% | 89% | 69% | 47% | 0 |
| F-bullets | 0 | 95% | 100% | 93% | 88% | 84% | 81% | 62% | 91% | 68% | 48% | 0 |
| F-nolabel | 0 | 32% | 100% | 93% | 30% | 23% | 7% | 7% | 28% | 10% | 6% | 0 |
| F-noisy | 0 | 60% | 97% | 93% | 54% | 49% | 33% | 15% | 50% | 20% | 11% | 0 |

