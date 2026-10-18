# Session F: format fuzzer + reader bench (report)

`python -m step7_serving.reader_bench [--reader path/to/prechecks.py] [--n 300] [--md out.md --json out.json]`
Sources: `data/reader_dev` + `data/dev` (300 cases per family, seed 0). Exit 1 on any wrong value.
Scoring = `precheck_eval`'s truth mapping (cross-checked: original dev packets give identical n / coverage / errors).

## Families (each packet rendered from truth, never from packet text; self-checked, 0 dropped)
| family | container | labels | other axes |
|---|---|---|---|
| F-kv | key: value (random separator) | canonical / synonym | field + section order, headers present/renamed/absent, decoy dates |
| F-prose | sentences ("The {label} is {value}.") | canonical / synonym | as above + noise lines |
| F-email | headers + body + forwarded / `>`-quoted PoA | canonical / synonym | email `Date:` header near as-of, decoys |
| F-table | markdown table or CSV (long or wide) | canonical / synonym | |
| F-json | JSON object, MRZ after it | canonical / synonym | |
| F-bullets | bullet list or one run-on line | canonical / synonym | |
| F-nolabel | kv / bullets / prose | none / random word / synonym | |
| F-noisy | any of kv, prose, email, bullets, table | canonical / synonym / random | random case, wrap 20-120, extra spacing, glyph noise 3%, blank line inside MRZ block 10% |
| F-heldout | cover letter from a relationship manager + enclosed ID / PoA (`fuzz_heldout.py`, committed after the 14:00 ET gate) | mostly none; private vocabulary | letterhead date decoy, cue after the date, US M/D/Y in the letter body (one order per author), private decoy stamps, wrap, glyph noise |
| F-inject | kv / prose / email / bullets | canonical / synonym | adversarial notes inside sections asserting a FALSE as-of / PoA date / expiry / DOB / document number |

All families: every date in a random format of the P3 §3 list (ISO, D.M.Y, D/M/Y, D-M-Y, 2-digit years,
month names / abbreviations in any case, ordinals, `14 JAN 2026`, `JAN 14 2026`, compact); MRZ lines verbatim;
document number verbatim; illegible fields as `[illegible]` / `[smudged]` / `▒▒▒` / `???`; screening hits summarized
(listed DOB is a natural decoy); decoy lines "Printed on / Downloaded / Report run / Exported … <date>".

## Results
- v2 (`main`): `reader_bench_v2.md`
- v3 WIP (`reader-v3` 3b23bb8): `reader_bench_v3_3b23bb8.md`
- v3 (`reader-v3` 3e77183): `reader_bench_v3_3e77183.md`
- v3 (`reader-v3` 280a028): `reader_bench_v3_280a028.md` (seed 0: 2 wrong; fresh seed 303: 0 wrong)
- v3 (`reader-v3` 5257a5f): seed 0 `reader_bench_v3_5257a5f_s0.md` (0 wrong), fresh seed 404 `reader_bench_v3_5257a5f_s404.md` (5 wrong: the 280a028 PoA class again)
- v3 (`reader-v3` e343588): 0 wrong on seeds 0, 404, 505, 707; 2 wrong on seed 606 (`reader_bench_v3_e343588_s606.md`); seed 9137 (requested by P3, all families incl. F-heldout): 0 wrong (`reader_bench_v3_e343588_s9137.md`)
- v3 (`reader-v3` 4c71bcc): seeds 0 / 115140 / 179961: 2 / 1 / 0 wrong (`reader_bench_v3_4c71bcc_s0.md`, `_s115140.md`)
- v3 (`reader-v3` a03054a): seeds 0 / 168473 / 112012: 2 / 2 / 0 wrong (`reader_bench_v3_a03054a_s0.md`, `_s168473.md`)

## Release
- v3 freeze (`reader-v3` @ a6e09f7 = a03054a): `reader_v3_freeze_release.md` (seeds 817292 / 330866 / 209993, incl. F-inject + F-heldout)
- v3.1 ed6471c vs freeze (same seeds): `reader_v31_ed6471c_vs_freeze.md`: PoA coverage +1..+8 pts, public-family wrong 3 -> 23 (PoA by elimination takes container dates)
- v3.1 475ba81 vs freeze: `reader_v31_475ba81_vs_freeze.md`: public wrong 3 -> 7, F-inject 31 -> 32, ORIGINALS 0 -> 2 (regression)
- v3.1 4374f64 vs freeze: `reader_v31_4374f64_vs_freeze.md` (release seeds) + `_confirm_seeds.md` (unseen seeds 6605863 / 5239230): originals 0 wrong; public 3 -> 1 and 2 -> 0; F-inject 31 -> 30 and 25 -> 25; coverage +0..+7 pts, no field drops > 1 pt
- v3.1 0718e2b vs freeze: `reader_v31_0718e2b_vs_freeze.md`: first held-out coverage (as-of 0 -> 25%, doc-number
  integrity 0 -> 23%); originals 0 wrong; public wrong 3 -> 10 (PoA content-window elimination); held-out 0 -> 1.
- v3.1 e72eb05 vs freeze: `reader_v31_e72eb05_vs_freeze.md` + `_confirm_seeds.md`: originals 0 wrong; public 3 -> 1 and 2 -> 0; held-out as-of 0 -> 25-28%, doc-number integrity 0 -> 23-25%, held-out wrong 0 -> 1 and 0 -> 3 (all day/month order taken from another document)
- v3.1 aa49ca2 ("release candidate") vs freeze: `reader_v31_aa49ca2_vs_freeze.md` + `_fresh_seeds.md` (81704392 / 65526398): originals 0 wrong; public 1/0/0 and 0/0 (freeze 1/2/0, 0/0); F-inject 30 and 18 (freeze 31, 18); held-out 0 wrong but held-out coverage back to 0% (as-of post-cue off)
- v3.1 342d0d3 ("candidate B") vs freeze: `reader_v31_342d0d3_vs_freeze.md` + `_fresh_seeds.md` (55909196 / 99439721): originals 0 wrong, coverage unchanged except PoA -1.7 (ocr_dump) / -1.1 (prose) / +1.0 (form); public wrong never above the freeze (1/0/0 vs 1/2/0; 0/1 vs 0/1, the same pre-existing case); F-inject 26 / 39 (freeze 31 / 43); held-out 0 wrong on 5 seeds with as-of +23..24 pts and doc-number integrity +21..22; public as-of -2..-6 pts
- **Bench fix (12:25 ET), F-heldout only:** the letter body now uses ONE day/month order per author (US or not);
  enclosed documents never use M/D. Before, each date drew its order independently, so one author mixed M/D and D/M,
  which defeats the spec-sanctioned "order proven by another date on the same document" rule (2 of 3 held-out
  wrong values on 0718e2b were that artifact). Both readers re-run on the same seeds after the fix; the freeze stays
  0 wrong / 0% on held-out.

## Anti-overfitting protocol (bench side)
1. **Report failure classes, never strings.** Notes to P3 describe the class of failure (e.g. "a 2-digit year
   resolved to the wrong century", "PoA part runs past its end into unrelated sections") and never the literal
   decoy words, labels or phrasings the fuzzer uses. A fix that adds a fuzzer string to a list is overfitting;
   a fix to a rule ("2-digit year is n/d unless proven") is not.
2. **Held-out family uses private vocabulary.** F-heldout's labels, decoy cues and phrasings appear nowhere in
   `fuzz_render.py` (checked by grep). P3 sees its score only; it is committed after the gate.
3. **Fresh seed at the gate.** Development runs use seed 0. The gate run uses seeds nobody has seen (picked
   at gate time); coverage and wrong counts must hold within noise. Seed check on 3e77183 (seeds 0/101/202):
   coverage within ~5 points per family, wrong counts the same order, i.e. not tuned to seed 0.
4. **Vocabulary audit of the reader.** Every cue word in `prechecks.py` that also appears in the fuzzer is
   checked to come from training packets or the spec. On 3e77183: all of them do (e.g. "applied on" 3750x
   in train/dev/reader_dev packets); none comes only from the fuzzer.
5. The end-to-end check stays the frozen eval sets (incl. hand-written and LLM-rewritten), which nobody opens.

## Coverage findings for P3 (e343588, classes only)
1. **Integrity is gated on the as-of date.** When as-of is n/d, every integrity field is n/d, even the
   document number, which needs no date at all. Public families: document-number integrity is 0/197
   (F-nolabel), 0/109 (F-noisy), 0/17 (F-kv) when as-of is n/d, vs 82/90, 150/178, 262/270 when it is found.
   On F-heldout, supplying an as-of date alone moves document-number integrity from 0% to 97%.
   Suggest: document number never depends on as-of; DOB / expiry century and the impossible-date check
   can use any proven bound (application date, other dates on the document), and only the date-dependent
   checks go n/d.
2. **Visual-zone dates are still found by label, not by value.** With as-of supplied, F-heldout DOB integrity
   stays ~1%. Design point 2 (find the date equal to the MRZ date anywhere, in any format) is not doing the work.
3. **As-of and the PoA part depend on known cue vocabulary.** F-heldout: as-of 0%, "no POA section found" on
   every packet. Fix by rule, not by adding words: e.g. a date that the text calls the date of this review,
   wherever the cue sits relative to the date, and a PoA part found by its content (an issuer + an address
   matching the applicant + a date) rather than by its header.

## Gate (14:00 ET) status
- Watcher stopped at 14:00 ET; last reader-v3.1 code benched: 342d0d3 (candidate B). No later `prechecks.py` push.
- F recommendation: 342d0d3. Never worse than the v3 freeze (`frozen/reader-v3` = a6e09f7) on wrong values on any
  family or seed (5 seeds); originals 0 wrong with unchanged as-of / integrity coverage; F-heldout 0 wrong with
  as-of +23..24 pts and doc-number integrity +21..22 pts. Open in both: injected-value false tamper (F-inject),
  illegible PoA date replaced by a trailing stamp (1 case), near match over exact match (1 case).
- F-heldout renderer committed now (`step7_serving/fuzz_heldout.py`); from here on it is no longer held out, so a
  new held-out family is needed for any further reader iteration.
