# P3 gate: pre-checker reader v3 (`reader-v3` @ e343588)

Never-wrong holds everywhere it was measured: **0 wrong values** on train, dev, reader_dev (all 6 styles),
all 8 public fuzz families at 3 seeds (0, and fresh seeds 404 and 505), and P3's own layout stress checks.
F-heldout is scored by Session F only (P3 has not seen its renderer); see F's report for e343588.

Reproduce:
```
python -m step7_serving.build_reader_dev                                   # data/reader_dev (600, seed 1500000)
python -m step7_serving.precheck_eval --splits train dev reader_dev --decision-errors ''
python -m step7_serving.precheck_eval --splits reader_dev --by-style --decision-errors ''
python -m step7_serving.reader_bench --seed {0,404,505}                     # F's bench, on branch fuzzer
```
Saved outputs: `precheck_v3_eval_*.{txt,json}`, `reader_bench_v3_e343588_seed{0,404,505}.md`.

## Update (`a03054a`): every seed run so far, clean and failing

Wrong values per commit and seed (all 8 public families; F-heldout from F's report, scores only):

| commit | 0 | 303 | 404 | 505 | 606 | 707 | 777 | 818 | 929 | 9137 | F-heldout |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 3e77183 | 269 | | | | | | | | | | 3 |
| 280a028 | 2 | 0 | | | | | | | | | |
| 5257a5f | 0 | | 5 | | | | | | | | |
| e343588 | 0 | | 0 | 0 | **2** (F-bullets PoA) | 0 | **2** (F-table as-of, PoA) | | | 0 | 0 wrong, ~0% coverage |
| **a03054a** | **0** | | | | **0** | | **0** | **0** | **0** | | F to report |

What changed after e343588 (classes, no fuzzer strings):
1. Integrity no longer depends on the as-of date. The document number needs no date. The DOB and expiry
   dates use the as-of date, else the application date ± 30 days (the spec's consistency bound; the MRZ
   century must be the same at both ends of that bound). An as-of read that the application date vetoes
   bounds nothing.
2. The cue-to-date rule now respects source lines. A cue labels a date on a later line only when nothing
   but separators sits between them. Seed 606 failed this way (a cue whose own line has a value), and so
   did seed 777 (a wide table's header row followed by a line with its own label).
3. An uncued PoA fallback date never beats a cued PoA-type date elsewhere in the packet.

Effect, seed 0, document-number integrity coverage: F-nolabel 26 -> 44%, F-noisy 46 -> 68%, F-table
64 -> 79%. train/dev/reader_dev coverage is unchanged or higher, still 0 wrong; stress checks 0 wrong;
453 tests pass. Bench outputs: `reader_bench_v3_a03054a_seed{0,606,777,818,929}.md`.

Generalization ablation (scratch, seed 777, on e343588): removing the generator-derived cue words costs
5-9 points of PoA and 4-7 points of integrity on the F families (wrong counts unchanged). The v2 label
reader adds nothing on F families (identical with it off); it helps only on our 4 training layouts.

## Gate table

| set | wrong values | coverage (v3) | v2 coverage | target met |
|---|---:|---|---|---|
| train | **0** | as-of 100, PoA 93.5, integrity 99.0, expiry 95.9 | 100 / 89.5 / 95.9 / 95.9 | yes (≥ v2 on every field) |
| dev | **0** | as-of 100, PoA 94.5, integrity 98.7, expiry 93.8 | 100 / 89.0 / 96.7 / 93.8 | yes |
| reader_dev / kv | **0** | as-of 100, PoA 91.1, integrity 95.6 | 100 / 90.0 / 93.4 | yes |
| reader_dev / form | **0** | as-of 100, PoA 92.6, integrity 98.9 | 100 / 87.2 / 94.7 | yes |
| reader_dev / prose | **0** | as-of 100, PoA 93.7, integrity 100 | 100 / 90.5 / 96.9 | yes |
| reader_dev / mixed | **0** | as-of 100, PoA 99.0, integrity 99.0 | 100 / 98.1 / 95.2 | yes |
| reader_dev / email | **0** | as-of 100, PoA 90.2, integrity 98.9 | 100 / 88.0 / 96.7 | yes |
| reader_dev / ocr_dump | **0** | as-of 100, PoA 94.1, integrity 97.5 | 100 / **0** / **0** | yes |
| F families, seed 0 / 404 / 505 | **0 / 0 / 0** | see below | (v2 on main: 6 wrong, seed 0) | yes |
| F-heldout | F reports | | | |

Fuzz families, seed 0 (coverage %; seeds 404 / 505 within ~5 points):

| family | as_of | poa_date | integ DOB | integ doc no. | integ expiry | integ overall | wrong |
|---|---:|---:|---:|---:|---:|---:|---:|
| F-kv | 96 | 86 | 61 | 91 | 66 | 47 | 0 |
| F-prose | 97 | 86 | 64 | 89 | 73 | 51 | 0 |
| F-email | 95 | 89 | 60 | 89 | 70 | 47 | 0 |
| F-table | 71 | 61 | 37 | 64 | 41 | 28 | 0 |
| F-json | 95 | 88 | 63 | 89 | 70 | 50 | 0 |
| F-bullets | 96 | 80 | 61 | 92 | 72 | 49 | 0 |
| F-nolabel | 30 | 19 | 5 | 26 | 6 | 5 | 0 |
| F-noisy | 58 | 45 | 19 | 46 | 24 | 14 | 0 |

(v2 on the same families: integrity overall 0–1%, PoA 0–5%.)

P3 stress checks on reader_dev (re-wrap 25–90, upper / lower case, section tags removed, MRZ inline on one
labelled line, MRZ glued into one string, decoy "printed / generated" dates): 0 wrong in all 7.

## What v3 does (design, `step7_serving/prechecks.py`)
- **Reader 1** = v2 label reader, unchanged except that it now reports competing values as a conflict.
- **Universal date reader** (`DATE2_RE`): ISO, D.M.Y / D/M/Y / D-M-Y, 2- and 4-digit years, month names and
  abbreviations in any case, ordinals, `JAN 14 2026`, compact `20260114`. Unproven day/month order or
  century → several candidates.
- **Flat text**: MRZ lines and inline MRZ tokens are taken out and all whitespace becomes one space, so line
  layout stops mattering. **Packet parts** (CTX / APP / ID / POA / SCR) come from cue words, not headers.
- **Reader 3 (cue window)**: each date's role is the nearest cue before it, in the same clause (no `: = | ;`
  or sentence break followed by other words in between, no digits, ≤ 5 words).
- **Reader 2 (anchor)**: MRZ values matched by value in the ID part. It vetoes when another token close to
  the MRZ value competes, and it fills a value only when the visual zone prints the MRZ value exactly and
  readers 1 and 3 have none.
- **MRZ by shape** anywhere (inline, glued, split). It is used only when its own check digits confirm it. Any
  MRZ-looking text means the document is never treated as "no MRZ".
- **Vote**: output a value only if every reader that found one agrees; any reader's conflict is a veto.
- **Day/month order**: proven by day > 12 on the same document, or by the document's *other* MRZ date
  matching the MRZ under exactly one order. A field never proves its own order.
- **Consistency rules** only drop readings or veto. PoA ≤ as-of + 31 days breaks ties. As-of must be within
  ±30 days of the application date, else n/d. PoA dates more than 10 years before as-of are n/d. A PoA part
  that holds birth or expiry dates, an issue date the ID doesn't own, or an MRZ date is a conflict.
- **§2.2 impossible date**: tamper only when *every* reading of birth and issue date is impossible. It used
  to be "any", which turned a 2-digit-year issue date into a false tamper (F's bench).
- API, header, line count and class wording are unchanged. `apply_prechecks(..., blank=)` and
  `blank_result()` were added for training.

## Also delivered
- `data/reader_dev/`: train config, unused train seed 1500000, all 6 styles. 0 case-id overlap with train,
  dev, train_twins and train_knockout. Eval configs use other prefixes and seed ranges. Nothing under
  `data/eval*` was opened.
- `precheck_eval --by-style`.
- `step4_distillation/add_prechecks.py --blank-rate 0.25 --seed 17`: deterministic (sha256 of seed and case
  id). Stats count `blanked_rows` (98 of the first 400 gold_train rows). The `_pc` files were **not** rebuilt.
- `tests/p3_reader_v3_test.py` (16 tests). One v2 test assertion changed: an ambiguous D.M.Y DOB is now
  proven by the MRZ-matching expiry; the n/d case is kept with a month-name expiry. Full suite:
  453 passed, 10 skipped (`httpx` needed for 2 infra tests).

## Open decisions for Tianle (not enabled)
1. **Packet-level day/month order.** Most remaining PoA n/d (about 6–10% per style) are D.M.Y PoA dates with
   day ≤ 12 and no other date on the bill. Reading them in the order the rest of the packet proves would push
   PoA to about 97%. It assumes one convention per packet, which an unknown process may break (a US bill
   in a DMY packet). Kept off.
2. **MRZ found by shape that fails its check digits** stays unused (n/d), so a tampered MRZ printed inline
   gives n/d, not "invalid". Using it would add coverage, at the risk of a mis-grouped read.
3. Coverage on label-free and heavily noisy layouts (F-nolabel, F-noisy) is low by design: without cue words
   the roles can't be proven. It falls back to n/d, which is why the blank-block training option exists.
