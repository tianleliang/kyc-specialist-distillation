# Sunday 10/18: Pre-checker reader v3 (Session P3) + format fuzzer (Session F). Claude CLOUD sessions, code only

**Read this whole file before writing any code.** Then `CLAUDE.md`, `PIPELINE.md`, `step0_rules/policy_v1.md` §1–§3, `step7_serving/prechecks.py`, `step7_serving/precheck_eval.py`.
Setup in the cloud container: `pip install -r requirements.txt` if present, else `pip install pytest pyyaml`. No GPU, no Modal, no API keys needed. **Launch nothing that costs money.**

## 1. The situation (why you exist)
- We ship a 4B student model + a deterministic **pre-checker**: code that reads the KYC case packet text and computes the arithmetic the model gets wrong (as-of date, MRZ check digits, document expiry, proof-of-address (PoA) age vs the 90-day window, and the policy §3 document-integrity class per field: consistent / OCR noise / ambiguous / clear tamper / impossible date). The result is rendered as a `PRE-CHECKS` block appended to the prompt. Final B is trained with that block and trusts it.
- **What went wrong last night:** on dev the system scored 98% decision accuracy; on the frozen eval sets 90.8%. Cause, diagnosed from packet text only: the pre-checker's **reader** (the part that finds values in the text) was built and verified only on the 4 packet styles in train/dev (`kv`, `form`, `prose`, `mixed`). On styles it never saw it returns `n/d` (not determinable): `email` 17–22% n/d for PoA, `ocr_dump` **100% n/d**, free prose written by an LLM or by hand **~100% n/d**. When the block is readable, Final B scores ~95–96% (Argon level); when it is n/d, 82–88%.
- **The lesson, and the one rule above all: DO NOT OVERFIT AGAIN.** v2 was "0 wrong, 96% coverage" on the formats it was built against and collapsed on others. A reader that handles a list of known formats is not the goal. **The goal is a reader that does not depend on layout at all**, plus a test bench that measures how it does on layouts nobody designed.
- Zorbe's hidden test set is built "to our schema, by a different process". Assume any layout, any wording, OCR noise.

## 2. Hard rules (contamination + honesty)
1. **Never open, read, grep, print, or load anything under `data/eval*`** (`eval`, `eval_id`, `eval_ood_*`, `eval_hard`). Not even to "look at a format". Those are the frozen test sets.
2. **Never use `step1_data_generation/ood_llm.py`, its prompts, or any LLM rewriting.** The LLM-rewritten and hand-written eval sets must stay fully held out from every part of the system. They are our clean real-world check.
3. Development data = `data/train`, `data/dev`, and NEW cases generated from the **train** config on unused **train** seeds (below). Truth values come from `truth.jsonl` of those splits only.
4. `prechecks.py` reads **packet text only**. Never truth, never expected labels.
5. **Never wrong > always readable.** When unsure, output `n/d`. One wrong value anywhere fails the gate.
6. Work on your own branch, commit often, push. Don't push to `main`. Don't edit files outside your scope.

## 3. Shared development data (P3 creates it first; F uses it)
```bash
python -m step1_data_generation.build --config step1_data_generation/configs/train.yaml --n 600 --seed 1500000 \
  --set "styles={kv: 1.0, form: 1.0, prose: 1.0, mixed: 1.0, email: 1.0, ocr_dump: 1.0}" --out data/reader_dev
```
(Adjust the `--set` syntax to what `build.py` accepts; the point is: train process, unused train seed, all 6 generator styles, ~100 per style.) Verify 0 case-id overlap with every existing split. Commit `data/reader_dev/` on your branch. `precheck_eval.py` must accept `--splits reader_dev`.

---

## Session P3: reader v3 (branch `reader-v3`)
Rewrite how `step7_serving/prechecks.py` **finds** values. The calculator parts (check digits, day counts, §3 rule) stay as they are; they are correct.

### Design: rely on content invariants, not layout
1. **MRZ by shape, self-verified.** Find MRZ anywhere: 2–3 runs of 30/36/44 chars dominated by `[A-Z0-9<]`, tolerating spaces, line breaks inside a line, an MRZ split over lines, and look-alike glyphs. Its own check digits confirm the read. No labels.
2. **Visual-zone values by value-matching, not labels.** From the MRZ get document number, date of birth, expiry. Search the **whole packet** for tokens matching them (document number: equal up to look-alike glyphs / one digit pair; dates: any date in the text equal to the MRZ date, or differing by one look-alike digit pair). That is the visual zone, wherever it sits. If several distinct candidates compete → n/d.
3. **One universal date reader.** Extract every date-like span anywhere: ISO, `D.M.Y`, `D/M/Y`, `D-M-Y`, 2- and 4-digit years, month names and 3-letter abbreviations (any case), ordinals (`3rd March 2026`, `March 3rd, 2026`), `14 JAN 2026`, `JAN 14 2026`, compact `20260114` when unambiguous. Ambiguous day/month → two candidates; resolved only by proof (day > 12, another date on the same document, consistency rules), else n/d.
4. **Roles by evidence.** DOB = the date that matches the MRZ DOB (or the application DOB). Expiry = the date that matches the MRZ expiry (no-MRZ documents: the date nearest expiry cue words). As-of = date nearest cue words (`as of`, `as-of`, `assessed`, `review`, `assessment date`, …). PoA date = date nearest PoA cue words (`bill`, `statement`, `letter`, `council tax`, `utility`, `bank`, `dated`, `issued`, `date of issue`, …) inside the PoA part of the packet (PoA part located by cue words, not one header string).
5. **Independent readers vote.** Keep v2's label-based reader as reader 1; add the anchor reader (2) and the cue-window reader (4). Output a value only if (a) they agree, or (b) exactly one produces a value with high confidence and no other contradicts it. Any disagreement → n/d.
6. **Consistency rules only break ties** (DOB < issue < expiry; PoA date ≤ as-of + 31 days; as-of within ±30 days of the application date when both found). They never invent values and never turn a §3 impossible date into n/d.
7. Keep the public API and block header: `run_prechecks(packet) -> dict`, `format_block(res) -> str`, `apply_prechecks(messages)`, header line unchanged; keep one line per item; same wording for each class as v2 (B will be retrained, but serving + training must share one function).

### Also in P3
- **Blank-block option** in `step4_distillation/add_prechecks.py`: `--blank-rate 0.25 --seed 17`: for a deterministic 25% of rows, render every item as `n/d` (block still present), so the model learns to fall back. Stats must report how many rows were blanked. Don't rebuild the `_pc` files yet (Claudian does that after the gate).
- Unit tests for each reader + the vote (`tests/p3_reader_v3_test.py`).

### P3 gate (all must hold; report the table)
| set | wrong values | coverage target |
|---|---|---|
| train, dev (original) | **0** | ≥ v2 (don't regress) |
| reader_dev, per style (6 styles) | **0** | integrity ≥95%, PoA date ≥90%, as-of ≥98% per style (ocr_dump: best effort, report) |
| F's fuzz families (all) | **0** | report |
| F's held-out family | **0** | report (this is the "unknown format" number) |
**Time box: report by 11:00 ET** whether or not every coverage target is met. Never-wrong is not negotiable; coverage is best effort.

---

## Session F: format fuzzer + test bench (branch `fuzzer`)
Build the bench that tells us how the reader does on layouts nobody designed. You don't write the reader.

### F1. Random renderer from truth (`step7_serving/fuzz_render.py`)
From a case's `truth.jsonl` record (train / dev / reader_dev only) write a **new packet** that contains the same facts the reader needs (context dates, applicant fields, ID document visual zone + `mrz_lines` exactly as in truth, PoA document with its issue date, screening hits can be summarized), in randomly chosen ways. Build from truth values directly; don't edit existing packet text. Mutation axes (each sampled per packet, seeded):
- **container:** key-value, prose paragraph(s), email (headers, quoted reply), letter, markdown table, CSV rows, JSON object, bullet list, one long run-on line
- **labels:** canonical / synonym from a large list / random unrelated word / **no label at all**
- **field order** shuffled, sections shuffled, section headers present / renamed / absent
- **dates:** random format from the full list in P3 §3 (incl. month names, ordinals, 2-digit years), per date
- **text:** random case, random line wrap width (20–120), extra blank lines, random spacing, noise lines (disclaimers, page footers, unrelated dates such as "printed on …" that must not be mistaken for the PoA/as-of date)
- **OCR noise:** look-alike glyph swaps in non-MRZ text at a low rate; MRZ always exactly as in truth (it carries the tamper / OCR semantics)
Group axes into **families** (e.g. F-kv, F-prose, F-email, F-table, F-json, F-nolabel, F-noisy). **One family is held out** (choose it up front, e.g. F-letter + no-label, and don't let P3 see its renderer details until the end; P3 only sees its score).

**Self-check every generated packet** before using it: the MRZ lines are present verbatim, every needed date is written in a format the spec allows, nothing contradicts truth. Drop and count packets that fail (they are F bugs, not reader errors).

### F2. Bench (`python -m step7_serving.reader_bench`)
- For each family × N cases (default 300 from `data/reader_dev` + `data/dev`): render, run `prechecks.run_prechecks`, compare with the truth-implied values, reusing `precheck_eval.py`'s truth mapping (as_of, mrz status, expiry, expired, poa_date, poa_window, integrity per field + overall).
- Output a table: family × field → coverage, wrong count, and the first 3 wrong examples (packet excerpt + reader value + truth value). Exit code ≠ 0 if any wrong value.
- Also runs on `reader_dev` original packets per generator style.
- `--reader <path>` or just imports `step7_serving.prechecks` from the current checkout, so P3 can run it after merging your branch.

### F3. Coordination
- Push a first working version **by ~09:45 ET** (even with fewer families), then improve. Tell P3 via the commit message.
- Run the bench against P3's latest `reader-v3` (`git fetch origin reader-v3 && git checkout origin/reader-v3 -- step7_serving/prechecks.py` in a scratch copy) and report the table.
- Tests: `tests/f_fuzz_test.py` (renderer determinism per seed, self-check catches a broken packet, bench flags a planted wrong value).

**F report by 11:00 ET:** families and what each varies, the held-out family, the bench table for v2 (current `main`) and for P3's latest v3.
