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
[train] no-MRZ docs: 199, MRZ invented: 0; expected=document_expired: 155, said NOT EXPIRED: 0; PoA n/d reasons: {'ambiguous_dmy': 292, 'illegible_scan': 19}
[dev] no-MRZ docs: 13, MRZ invented: 0; expected=document_expired: 6, said NOT EXPIRED: 0; PoA n/d reasons: {'ambiguous_dmy': 16}
