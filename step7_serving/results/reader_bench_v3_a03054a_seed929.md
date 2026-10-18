# Reader bench: `/tmp/claude-0/sp/pc_f.py`

Sources: reader_dev, dev; 300 cases per family; seed 929. Cell = coverage (share not n/d); **Nx** = N wrong values.

## Fuzz families

| set | dropped | as_of | mrz | expiry | expired | poa_date | poa_window | integ_date_of_birth | integ_document_number | integ_expiry | integ_overall | wrong |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| F-kv | 0 | 95% | 100% | 97% | 92% | 86% | 82% | 60% | 97% | 72% | 49% | 0 |
| F-prose | 0 | 97% | 100% | 92% | 89% | 85% | 84% | 61% | 89% | 73% | 45% | 0 |
| F-email | 0 | 95% | 100% | 94% | 89% | 90% | 86% | 65% | 94% | 73% | 52% | 0 |
| F-table | 0 | 72% | 100% | 92% | 66% | 64% | 51% | 32% | 78% | 39% | 24% | 0 |
| F-json | 0 | 95% | 100% | 92% | 88% | 89% | 85% | 62% | 94% | 65% | 44% | 0 |
| F-bullets | 0 | 96% | 100% | 92% | 88% | 84% | 81% | 60% | 94% | 68% | 47% | 0 |
| F-nolabel | 0 | 25% | 100% | 92% | 23% | 23% | 7% | 12% | 43% | 10% | 9% | 0 |
| F-noisy | 0 | 57% | 99% | 91% | 52% | 43% | 29% | 28% | 72% | 27% | 18% | 0 |

