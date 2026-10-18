# Reader bench: `/tmp/claude-0/sp/pc_f.py`

Sources: reader_dev, dev; 300 cases per family; seed 777. Cell = coverage (share not n/d); **Nx** = N wrong values.

## Fuzz families

| set | dropped | as_of | mrz | expiry | expired | poa_date | poa_window | integ_date_of_birth | integ_document_number | integ_expiry | integ_overall | wrong |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| F-kv | 0 | 93% | 100% | 96% | 88% | 84% | 79% | 65% | 93% | 69% | 52% | 0 |
| F-prose | 0 | 94% | 100% | 92% | 86% | 80% | 78% | 59% | 88% | 66% | 43% | 0 |
| F-email | 0 | 93% | 100% | 95% | 89% | 88% | 83% | 58% | 93% | 73% | 46% | 0 |
| F-table | 0 | 72% | 100% | 92% | 66% | 63% | 53% | 37% | 82% | 47% | 32% | 0 |
| F-json | 0 | 94% | 100% | 92% | 87% | 87% | 83% | 62% | 94% | 66% | 45% | 0 |
| F-bullets | 0 | 95% | 100% | 92% | 87% | 81% | 78% | 61% | 95% | 72% | 49% | 0 |
| F-nolabel | 0 | 27% | 100% | 93% | 26% | 21% | 6% | 8% | 42% | 9% | 6% | 0 |
| F-noisy | 0 | 59% | 99% | 91% | 53% | 38% | 25% | 29% | 72% | 30% | 23% | 0 |

