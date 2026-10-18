# Reader bench: `/tmp/claude-0/sp/pc_f.py`

Sources: reader_dev, dev; 300 cases per family; seed 818. Cell = coverage (share not n/d); **Nx** = N wrong values.

## Fuzz families

| set | dropped | as_of | mrz | expiry | expired | poa_date | poa_window | integ_date_of_birth | integ_document_number | integ_expiry | integ_overall | wrong |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| F-kv | 0 | 96% | 100% | 96% | 92% | 88% | 85% | 58% | 92% | 73% | 49% | 0 |
| F-prose | 0 | 94% | 100% | 92% | 88% | 85% | 80% | 55% | 84% | 68% | 44% | 0 |
| F-email | 0 | 97% | 100% | 94% | 91% | 91% | 88% | 64% | 93% | 71% | 51% | 0 |
| F-table | 0 | 75% | 100% | 92% | 68% | 64% | 53% | 46% | 81% | 49% | 36% | 0 |
| F-json | 0 | 95% | 100% | 92% | 87% | 86% | 82% | 61% | 94% | 66% | 47% | 0 |
| F-bullets | 0 | 96% | 100% | 92% | 88% | 83% | 81% | 60% | 91% | 67% | 48% | 0 |
| F-nolabel | 0 | 26% | 100% | 92% | 24% | 18% | 5% | 7% | 45% | 8% | 6% | 0 |
| F-noisy | 0 | 52% | 99% | 91% | 46% | 38% | 22% | 21% | 68% | 26% | 17% | 0 |

