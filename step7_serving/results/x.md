Seeds 817292, 330866, 209993; 300 cases per family per seed from reader_dev, dev; coverage pooled over seeds; wrong per seed.

### v3-freeze

| family | as_of | poa_date | expiry | integ_date_of_birth | integ_document_number | integ_expiry | integ_overall | wrong per seed |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| F-kv | 95% | 84% | 98% | 60% | 94% | 68% | 47% | 0 / 0 / 0 |
| F-prose | 94% | 84% | 93% | 59% | 87% | 67% | 44% | 0 / 0 / 0 |
| F-email | 95% | 89% | 95% | 62% | 92% | 71% | 50% | 0 / 0 / 0 |
| F-table | 68% | 59% | 93% | 37% | 81% | 43% | 30% | 1 / 0 / 0 |
| F-json | 96% | 89% | 93% | 62% | 95% | 72% | 51% | 0 / 0 / 0 |
| F-bullets | 95% | 81% | 93% | 59% | 95% | 70% | 48% | 0 / 0 / 0 |
| F-nolabel | 30% | 21% | 94% | 10% | 45% | 10% | 7% | 0 / 2 / 0 |
| F-noisy | 55% | 46% | 93% | 20% | 70% | 24% | 15% | 0 / 0 / 0 |
| F-inject | 82% | 52% | 94% | 52% | 90% | 50% | 30% | 12 / 9 / 10 |
| F-heldout | 0% | 0% | 93% | 0% | 0% | 0% | 0% | 0 / 0 / 0 |

Original packets (10 split/style sets): 0 wrong. Coverage as_of / poa_date / integ_overall per set: reader_dev/email 100%/90%/99%; reader_dev/form 100%/93%/99%; reader_dev/kv 100%/91%/96%; reader_dev/mixed 100%/99%/99%; reader_dev/ocr_dump 100%/93%/97%; reader_dev/prose 100%/94%/100%; dev/form 100%/95%/100%; dev/kv 100%/89%/97%; dev/mixed 100%/97%/100%; dev/prose 100%/96%/96%

### v3.1@342d0d3

| family | as_of | poa_date | expiry | integ_date_of_birth | integ_document_number | integ_expiry | integ_overall | wrong per seed |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| F-kv | 90% | 85% | 98% | 57% | 97% | 66% | 45% | 0 / 0 / 0 |
| F-prose | 90% | 85% | 93% | 58% | 87% | 65% | 43% | 0 / 0 / 0 |
| F-email | 88% | 89% | 95% | 58% | 93% | 68% | 48% | 0 / 0 / 0 |
| F-table | 65% | 60% | 93% | 36% | 81% | 41% | 30% | 1 / 0 / 0 |
| F-json | 91% | 89% | 93% | 60% | 97% | 70% | 50% | 0 / 0 / 0 |
| F-bullets | 90% | 82% | 93% | 57% | 97% | 68% | 46% | 0 / 0 / 0 |
| F-nolabel | 28% | 21% | 94% | 9% | 45% | 9% | 7% | 0 / 0 / 0 |
| F-noisy | 51% | 47% | 93% | 20% | 75% | 24% | 15% | 0 / 0 / 0 |
| F-inject | 66% | 51% | 94% | 48% | 90% | 47% | 28% | 10 / 7 / 9 |
| F-heldout | 24% | 0% | 93% | 1% | 22% | 0% | 1% | 0 / 0 / 0 |

Original packets (10 split/style sets): 0 wrong. Coverage as_of / poa_date / integ_overall per set: reader_dev/email 100%/90%/99%; reader_dev/form 100%/94%/99%; reader_dev/kv 100%/91%/96%; reader_dev/mixed 100%/99%/99%; reader_dev/ocr_dump 100%/92%/97%; reader_dev/prose 100%/93%/100%; dev/form 100%/95%/100%; dev/kv 100%/89%/97%; dev/mixed 100%/97%/100%; dev/prose 100%/96%/96%

### v3.1@342d0d3 minus v3-freeze (coverage points; wrong total over seeds)

| family | as_of | poa_date | expiry | integ_date_of_birth | integ_document_number | integ_expiry | integ_overall | wrong v3-freeze | wrong v3.1@342d0d3 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| F-kv | -5 | +1 | +0 | -2 | +2 | -2 | -1 | 0 | 0 |
| F-prose | -4 | +0 | +0 | -2 | -0 | -2 | -1 | 0 | 0 |
| F-email | -6 | -0 | +0 | -3 | +1 | -3 | -3 | 0 | 0 |
| F-table | -4 | +1 | +0 | -2 | +0 | -1 | -1 | 1 | 1 |
| F-json | -5 | -0 | +0 | -2 | +2 | -2 | -1 | 0 | 0 |
| F-bullets | -5 | +0 | +0 | -1 | +1 | -2 | -1 | 0 | 0 |
| F-nolabel | -2 | +1 | +0 | -1 | +0 | -1 | -1 | 2 | 0 |
| F-noisy | -4 | +0 | +0 | -0 | +4 | -1 | -0 | 0 | 0 |
| F-inject | -16 | -1 | +0 | -4 | +0 | -4 | -2 | 31 | 26 |
| F-heldout | +24 | +0 | +0 | +1 | +22 | +0 | +1 | 0 | 0 |

### Wrong values: v3-freeze (34)

- F-table seed 817292 integ_date_of_birth trn-1500000-000054: reader=ambiguous truth=tamper
- F-nolabel seed 330866 integ_expiry trn-1500000-000010: reader=tamper truth=consistent/no_mrz/noise
- F-nolabel seed 330866 integ_overall trn-1500000-000010: reader=clear tamper truth=consistent/noise only
- F-inject seed 817292 integ_date_of_birth trn-1500000-000147: reader=tamper truth=consistent
- F-inject seed 817292 integ_date_of_birth trn-1500000-000577: reader=tamper truth=consistent
- F-inject seed 817292 integ_date_of_birth dev-2000000-000030: reader=tamper truth=consistent
- F-inject seed 817292 integ_date_of_birth dev-2000000-000143: reader=tamper truth=consistent
- F-inject seed 817292 integ_overall trn-1500000-000147: reader=clear tamper truth=consistent
- F-inject seed 817292 integ_overall trn-1500000-000577: reader=clear tamper truth=consistent
- F-inject seed 817292 integ_overall dev-2000000-000030: reader=clear tamper truth=consistent
- F-inject seed 817292 integ_overall dev-2000000-000143: reader=clear tamper truth=consistent
- F-inject seed 817292 poa_date trn-1500000-000488: reader=2027-09-28 truth=2026-06-23
- F-inject seed 817292 poa_date trn-1500000-000175: reader=2025-02-21 truth=2026-06-09
- F-inject seed 817292 poa_date trn-1500000-000512: reader=2025-05-27 truth=2026-08-25
- F-inject seed 817292 poa_window trn-1500000-000175: reader=OLDER THAN 90 DAYS truth=WITHIN 90 DAYS
- F-inject seed 330866 integ_date_of_birth trn-1500000-000346: reader=tamper truth=consistent
- F-inject seed 330866 integ_date_of_birth dev-2000000-000007: reader=tamper truth=consistent/no_mrz/noise
- F-inject seed 330866 integ_date_of_birth trn-1500000-000554: reader=ambiguous truth=tamper
- F-inject seed 330866 integ_overall trn-1500000-000346: reader=clear tamper truth=ambiguous
- F-inject seed 330866 integ_overall dev-2000000-000007: reader=clear tamper truth=consistent/noise only
- F-inject seed 330866 integ_overall dev-2000000-000071: reader=clear tamper truth=consistent
- F-inject seed 330866 integ_overall trn-1500000-000240: reader=clear tamper truth=consistent
- F-inject seed 330866 integ_expiry dev-2000000-000071: reader=tamper truth=consistent
- F-inject seed 330866 integ_expiry trn-1500000-000240: reader=tamper truth=consistent
- F-inject seed 209993 integ_date_of_birth trn-1500000-000442: reader=tamper truth=consistent/no_mrz/noise
- F-inject seed 209993 integ_date_of_birth trn-1500000-000441: reader=tamper truth=consistent/no_mrz/noise
- F-inject seed 209993 integ_expiry trn-1500000-000442: reader=tamper truth=consistent
- F-inject seed 209993 integ_expiry trn-1500000-000256: reader=tamper truth=consistent
- F-inject seed 209993 integ_expiry trn-1500000-000299: reader=tamper truth=consistent
- F-inject seed 209993 integ_expiry trn-1500000-000513: reader=tamper truth=consistent
- F-inject seed 209993 integ_overall trn-1500000-000442: reader=clear tamper truth=consistent/noise only
- F-inject seed 209993 integ_overall trn-1500000-000299: reader=clear tamper truth=consistent
- F-inject seed 209993 integ_overall trn-1500000-000513: reader=clear tamper truth=consistent
- F-inject seed 209993 integ_overall trn-1500000-000441: reader=clear tamper truth=consistent/noise only

### Wrong values: v3.1@342d0d3 (27)

- F-table seed 817292 integ_date_of_birth trn-1500000-000054: reader=ambiguous truth=tamper
- F-inject seed 817292 integ_date_of_birth trn-1500000-000147: reader=tamper truth=consistent
- F-inject seed 817292 integ_date_of_birth trn-1500000-000577: reader=tamper truth=consistent
- F-inject seed 817292 integ_date_of_birth dev-2000000-000030: reader=tamper truth=consistent
- F-inject seed 817292 integ_date_of_birth dev-2000000-000143: reader=tamper truth=consistent
- F-inject seed 817292 integ_overall trn-1500000-000147: reader=clear tamper truth=consistent
- F-inject seed 817292 integ_overall trn-1500000-000577: reader=clear tamper truth=consistent
- F-inject seed 817292 integ_overall dev-2000000-000030: reader=clear tamper truth=consistent
- F-inject seed 817292 integ_overall dev-2000000-000143: reader=clear tamper truth=consistent
- F-inject seed 817292 poa_date trn-1500000-000488: reader=2027-09-28 truth=2026-06-23
- F-inject seed 817292 poa_date trn-1500000-000175: reader=2025-02-21 truth=2026-06-09
- F-inject seed 330866 integ_date_of_birth trn-1500000-000346: reader=tamper truth=consistent
- F-inject seed 330866 integ_date_of_birth dev-2000000-000007: reader=tamper truth=consistent/no_mrz/noise
- F-inject seed 330866 integ_date_of_birth trn-1500000-000554: reader=ambiguous truth=tamper
- F-inject seed 330866 integ_overall trn-1500000-000346: reader=clear tamper truth=ambiguous
- F-inject seed 330866 integ_overall dev-2000000-000007: reader=clear tamper truth=consistent/noise only
- F-inject seed 330866 integ_overall trn-1500000-000240: reader=clear tamper truth=consistent
- F-inject seed 330866 integ_expiry trn-1500000-000240: reader=tamper truth=consistent
- F-inject seed 209993 integ_date_of_birth trn-1500000-000442: reader=tamper truth=consistent/no_mrz/noise
- F-inject seed 209993 integ_date_of_birth trn-1500000-000441: reader=tamper truth=consistent/no_mrz/noise
- F-inject seed 209993 integ_expiry trn-1500000-000442: reader=tamper truth=consistent
- F-inject seed 209993 integ_expiry trn-1500000-000299: reader=tamper truth=consistent
- F-inject seed 209993 integ_expiry trn-1500000-000513: reader=tamper truth=consistent
- F-inject seed 209993 integ_overall trn-1500000-000442: reader=clear tamper truth=consistent/noise only
- F-inject seed 209993 integ_overall trn-1500000-000299: reader=clear tamper truth=consistent
- F-inject seed 209993 integ_overall trn-1500000-000513: reader=clear tamper truth=consistent
- F-inject seed 209993 integ_overall trn-1500000-000441: reader=clear tamper truth=consistent/noise only

