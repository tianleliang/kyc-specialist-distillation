# Reader bench: `/tmp/claude-0/sp/pc_d.py`

Sources: reader_dev, dev; 300 cases per family; seed 0. Cell = coverage (share not n/d); **Nx** = N wrong values.

## Fuzz families

| set | dropped | as_of | mrz | expiry | expired | poa_date | poa_window | integ_date_of_birth | integ_document_number | integ_expiry | integ_overall | wrong |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| F-kv | 0 | 96% | 100% | 96% | 92% | 86% | 83% | 61% | 91% | 66% | 47% | 0 |
| F-prose | 0 | 97% | 100% | 91% | 88% | 86% | 83% | 64% | 89% | 73% | 51% | 0 |
| F-email | 0 | 95% | 100% | 93% | 89% | 89% | 85% | 60% | 89% | 70% | 47% | 0 |
| F-table | 0 | 71% | 100% | 91% | 65% | 61% | 51% | 37% | 64% | 41% | 28% | 0 |
| F-json | 0 | 95% | 100% | 91% | 86% | 88% | 83% | 63% | 89% | 70% | 50% | 0 |
| F-bullets | 0 | 96% | 100% | 91% | 87% | 80% | 78% | 61% | 92% | 72% | 49% | 0 |
| F-nolabel | 0 | 30% | 100% | 92% | 28% | 19% | 8% | 5% | 26% | 6% | 5% | 0 |
| F-noisy | 0 | 58% | 99% | 91% | 54% | 45% | 28% | 19% | 46% | 24% | 14% | 0 |

