# Reader bench: `/tmp/claude-0/sp/pc_d.py`

Sources: reader_dev, dev; 300 cases per family; seed 404. Cell = coverage (share not n/d); **Nx** = N wrong values.

## Fuzz families

| set | dropped | as_of | mrz | expiry | expired | poa_date | poa_window | integ_date_of_birth | integ_document_number | integ_expiry | integ_overall | wrong |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| F-kv | 0 | 93% | 100% | 96% | 89% | 89% | 83% | 61% | 90% | 64% | 46% | 0 |
| F-prose | 0 | 95% | 100% | 92% | 88% | 87% | 83% | 63% | 85% | 72% | 47% | 0 |
| F-email | 0 | 94% | 100% | 94% | 88% | 90% | 85% | 60% | 87% | 70% | 48% | 0 |
| F-table | 0 | 69% | 100% | 92% | 64% | 61% | 45% | 37% | 65% | 40% | 29% | 0 |
| F-json | 0 | 95% | 100% | 92% | 87% | 90% | 85% | 65% | 91% | 69% | 52% | 0 |
| F-bullets | 0 | 95% | 100% | 92% | 87% | 87% | 84% | 60% | 92% | 69% | 46% | 0 |
| F-nolabel | 0 | 30% | 100% | 92% | 27% | 22% | 5% | 4% | 25% | 7% | 5% | 0 |
| F-noisy | 0 | 63% | 98% | 91% | 58% | 48% | 31% | 18% | 54% | 23% | 14% | 0 |

