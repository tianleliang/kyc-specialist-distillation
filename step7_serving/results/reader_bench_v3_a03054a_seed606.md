# Reader bench: `/tmp/claude-0/sp/pc_f.py`

Sources: reader_dev, dev; 300 cases per family; seed 606. Cell = coverage (share not n/d); **Nx** = N wrong values.

## Fuzz families

| set | dropped | as_of | mrz | expiry | expired | poa_date | poa_window | integ_date_of_birth | integ_document_number | integ_expiry | integ_overall | wrong |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| F-kv | 0 | 96% | 100% | 97% | 93% | 90% | 85% | 59% | 93% | 70% | 45% | 0 |
| F-prose | 0 | 94% | 100% | 92% | 87% | 84% | 81% | 58% | 89% | 70% | 43% | 0 |
| F-email | 0 | 95% | 100% | 93% | 89% | 88% | 84% | 57% | 92% | 67% | 45% | 0 |
| F-table | 0 | 68% | 100% | 92% | 63% | 65% | 52% | 43% | 82% | 45% | 35% | 0 |
| F-json | 0 | 93% | 100% | 92% | 85% | 85% | 80% | 59% | 94% | 66% | 44% | 0 |
| F-bullets | 0 | 94% | 100% | 92% | 87% | 83% | 79% | 63% | 94% | 70% | 49% | 0 |
| F-nolabel | 0 | 29% | 100% | 92% | 26% | 20% | 7% | 9% | 43% | 11% | 8% | 0 |
| F-noisy | 0 | 57% | 99% | 91% | 55% | 47% | 28% | 22% | 71% | 24% | 15% | 0 |

