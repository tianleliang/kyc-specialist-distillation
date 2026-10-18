# Reader v3.1 gate (`reader-v3.1` @ e72eb05) vs v3 freeze (a6e09f7)

Block format: byte-identical to the freeze (`format_block`, `format_integrity`, header, class wording,
system note, `apply_prechecks*` unchanged; 9 lines; checked on all 600 reader_dev packets). Only coverage changes.

## Wrong values (never-wrong is the gate)

| set | v3 freeze | v3.1 |
|---|---|---|
| train, dev, reader_dev (6 styles) | 0 | 0 |
| P3 stress checks (7) | 0 | 0 |
| F families, fresh seed 4444 | **2** (F-noisy PoA + window) | 0 |
| F families, fresh seed 5555 | 0 | 0 |
| F families, fresh seed 6666 | 0 | 0 |
| F families, fresh seed 7777 | **1** (F-noisy PoA) | 0 |
| F families, seed 2222 (earlier run) | **1** (F-noisy PoA) | 0 |
| F-heldout | F to report | F to report |

The frozen v3 is not never-wrong on fresh seeds (1-2 wrong PoA values in F-noisy at 2222, 4444, 7777).
Class: the label reader's PoA section runs on into a headerless ID document and takes its "date of
issue". v3.1 accepts a label-reader PoA date alone only where the layout-free part map also places it in
a PoA part.

## Coverage, v3 -> v3.1 (mean of fresh seeds 4444 / 5555 / 6666, % not n/d)

| family | as-of | PoA date | DOB integ. | doc no. integ. | expiry integ. | overall integ. | wrong v3 / v3.1 |
|---|---|---|---|---|---|---|---|
| F-kv | 94 → 94 | 83 → 84 | 61 → 62 | 95 → 98 | 68 → 70 | 49 → 51 | 0 / 0 |
| F-prose | 94 → 94 | 83 → 85 | 61 → 62 | 86 → 89 | 69 → 70 | 46 → 47 | 0 / 0 |
| F-email | 94 → 94 | 89 → 89 | 59 → 59 | 92 → 94 | 70 → 70 | 48 → 48 | 0 / 0 |
| F-table | 70 → 70 | 60 → 60 | 40 → 40 | 80 → 82 | 44 → 44 | 32 → 33 | 0 / 0 |
| F-json | 94 → 94 | 87 → 89 | 59 → 60 | 95 → 98 | 69 → 71 | 47 → 49 | 0 / 0 |
| F-bullets | 95 → 95 | 85 → 87 | 60 → 61 | 96 → 98 | 71 → 72 | 49 → 49 | 0 / 0 |
| F-nolabel | 28 → 28 | 23 → 24 | 9 → 9 | 45 → 48 | 10 → 10 | 8 → 8 | 0 / 0 |
| F-noisy | 53 → 54 | 41 → 40 | 25 → 27 | 69 → 77 | 25 → 27 | 19 → 21 | 2 / 0 |

train / dev / reader_dev: same as v3 (PoA 93.5 / 94.5 / 90.2-99.0 per style; integrity 99.1 / 98.7 /
95.6-100). reader_dev ocr_dump PoA 94.1 -> 91.6 (generic document-noun cues instead of the generator's
word list).

## What v3.1 changes
- **Generic document-noun cues** ("<word(s)> bill|statement|invoice|letter|notice|agreement|contract|
  certificate", "<noun> date", "date of <noun>") replace the generator's list of PoA document kinds.
- **Anchor over the whole packet** except the screening hits: it fills a visual-zone value only under a
  closed-world condition (every other date / same-shape token accounted for). Its veto stays on the ID
  part. The application's own DOB is a second source, not a competitor.
- **OCR look-alike folding** for cue words (l / I / 1 / | -> i, 0 -> o, 5 -> s, in text and patterns).
- **A bare "date" cue** may not pick between several dates in a PoA part.
- **A date is claimed / explained only when every reading is accounted for.**
- **As-of / application cue may follow its date** (same line, brackets or <= 2 short words between).
  This added no measurable as-of coverage on the public families.
- **Label reader alone** must agree with the layout-free part map on where a PoA date sits.

## Tried and switched off (kept behind flags for measurement): elimination
- `USE_ELIMINATION` (PoA = the only recent unclaimed date in the packet): 1-5 wrong per family.
- `USE_ADDRESS_ELIMINATION` (PoA document located by its repeated address number tokens, elimination only in
  its window): 0 wrong on train/dev/reader_dev, 43-52% coverage alone, but 1-5 wrong per family on fresh
  seeds; 9 of 14 had the real PoA date garbled past the date reader.
- Conclusion: elimination ("the date left over is the answer") fails unsafe under OCR noise, because the
  reader cannot prove it saw every date. Positive identification (cue, MRZ value) fails to n/d.

## Honest assessment
v3.1 is safer than v3 (0 vs 1-2 wrong on fresh seeds) with small coverage gains (+1-3 points on most
fields, document number +2-8). It does not solve coverage on unknown layouts: on label-free layouts
(F-nolabel) DOB / expiry / overall integrity stay under 10% and as-of under 30%. The limit is structural:
DOB and expiry integrity need the ID issue date (policy §2.2), which has no MRZ anchor, and roles need
either a cue or an anchor value.

Bench files: `reader_bench_v31_e72eb05_seed{4444,5555,6666,7777}.md`, `reader_bench_v3freeze_seed{4444,5555,6666,7777}.md`.
