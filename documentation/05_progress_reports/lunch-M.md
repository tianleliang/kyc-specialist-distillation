# Lunch report: Session M (OOD writers + domain adapter)

Branch: `claude/nifty-bell-41llvx`. Cloud session: no API keys, no Modal, mocks only. I never opened `step1_data_generation/render.py` (D14). The only place it is used is a test that imports it as a black box to check that the hand layouts don't copy its boilerplate.

## Done

| # | Task | Where | Status |
|---|---|---|---|
| 1 | 50 hand-template OOD packets, 6 new styles | `step1_data_generation/ood_templates.py` | Done; tested against v0 (this branch) **and** L's v1 (`claude/sweet-mayer-wlxkpz`, in a scratch worktree): 25/25 pass both times |
| 2 | LLM-written OOD writer | `step1_data_generation/ood_llm.py` | Done; mock-tested. The real run happens on the laptop |
| 3a | `train_adapter.py` (CPT, 16-bit LoRA, Modal) + configs + CPU smoke | `step3_domain_adapter/` | Done; see the smoke result below |
| 3b | `measure_adapter.py` (held-out ppl + 30-item probe, before/after) | `step3_domain_adapter/measure_adapter.py`, `probe.py` | Done |
| 3c | `fetch_corpus.sh` URL fixes | `step3_domain_adapter/corpus/fetch_corpus.sh`, `SOURCES.md` | Done (search-verified, **not downloaded**; see below) |
| 4 | Tests | `tests/m_ood_test.py` (25), `tests/m_adapter_test.py` (11, including the CPU smoke) | **Full suite: 411 passed, 0 skipped** (`python -m pytest -q`, with the training and serving deps installed) |

### 1. Hand templates (`ood_templates.py`)
- **Six styles**, none of them in the training renderer:
  - `bank_pdf_export`: core-banking file → PDF → text layer, with page headers and dotted leaders
  - `call_centre_summary`: an agent's after-call summary with the upload tool's OCR pasted in
  - `fax_ocr_dump`: a branch fax, OCR'd, with fax headers per page and smudged boilerplate labels ("APPLICATI0N DATFD")
  - `vendor_json`: an HTTP response carrying another IDV vendor's JSON case-import payload, with different keys and nesting
  - `two_column_form`: a paper form whose OCR read both columns row by row, so applicant and office/PoA fields are interleaved
  - `case_ticket`: a ticket with comments from onboarding-bot, documents-team and screening-service, and a markdown hit table
- **Truths:** `configs/eval_ood_template.yaml` (entity bucket 9, OOD pools and injection texts), seed **4010000**, ids `oodh-…`.
  - L's `eval_ood_template` build uses seed 4000000 and the LLM set uses 4020000, so the three sets never share a case.
  - Styles are balanced (8–9 per style) and deterministic.
- **Labels:** `project.project(t)`, imported lazily, so whichever schema is checked in labels the cases. Each label is validated against `project.SCHEMA`.
- **Fact assertion** (`check_packet`, run on every packet). Every fact the label can depend on must appear verbatim, in the style's own date format and JSON-escaped in `vendor_json`:
  - context: case ref, country, product, channel, as-of and application dates
  - every application field
  - every ID visual-zone value, or the style's illegible marker
  - every MRZ line exactly as OCR'd
  - the PoA: type, issuer, date, addressee and every address line exactly as the truth renders them; or the "missing" statement; or, if illegible, a junk body
  - every hit field: id, list, source, record id, listed name, every alias with its quality, listed DOB, nationality, score, every detail (PEP role/relationship/related PEP, media age/city/occupation, remarks...)
  - the injected text, in its location
  - Coverage is 25–60 facts per packet.
- **Leak check:** words like `tamper`, `expired`, `true match`, `mismatch` and `transliteration` may not appear outside the injected text.
- **Dates are only printed unambiguously** (ISO, Y/M/D, or with a month name), so a day/month-swap case can't be read as a format difference.
- Tests:
  - 150 truths × 6 styles pass the assertion
  - an illegible PoA renders as junk in every style
  - a "fixed" MRZ and an editorial leak are caught
  - injected text is kept verbatim
  - **boilerplate overlap with the training renderer is under 5% of 24-character shingles** after removing fact values (the remaining overlap is the issuing authority's name, which is a truth value)
  - the build is deterministic, refuses to run without `--allow-eval`, refuses to overwrite a frozen `MANIFEST.json`, and needs `--force` to overwrite an unfrozen `manifest.json`
- **I did not build `data/eval_ood_hand/`**, because `data/` belongs to L and the v1 labeller is on L's branch. After both branches merge: `python -m step1_data_generation.ood_templates --allow-eval` (seconds; writes `cases.jsonl`, `truth.jsonl`, `manifest.json`).

### 2. LLM-written OOD (`ood_llm.py`)
- **Truths:** the same config, seed **4020000**, ids `oodl-…`. `--oversample 1.25` renders 125 truths and keeps the first 100 that pass the checks.
- **Models alternate** by index: `claude-sonnet-5-5` (anthropic) and `gemini-3.8-flash` (gemini), through `shared/frontier_api.LLMClient` (disk cache, retries, ledger), with reasoning effort low and `max_tokens` 3000.
- **10 style briefs**, rotated so each brief goes to both models: legacy XML, CSV rows, an internal messenger chat, a credit-union worksheet, a YAML dossier, a junior analyst's memo with appendices, a mobile-app event log, an introducer letter with fixed-width screening, an intranet page dump, and a Spanish/French-labelled branch packet. Every brief carries a rule that dates must be unambiguous.
- **The model sees only a *visible-truth* view**: no scenario names, relations, defect or tamper notes, same-person flags, discriminators, risk facts or knobs. It therefore cannot leak or "explain" them (the prompt's rule 3 becomes a guarantee). A test checks that no hidden key reaches the prompt.
- **Drop rules**, all logged by model and by primary scenario in `manifest.json`:
  - `missing_or_fixed`: `check_ood_packet` on the verbatim strings (names, document number, MRZ lines, address lines, occupation/employer/activity, hit ids, sources, record ids, listed names, aliases, listed DOBs, key PEP/media details, injected text)
  - `date_missing`: no unambiguous rendering of a required date
  - `volume_missing`
  - `leak`
  - `error`
  - `surplus` (already at n)
- Dropped packets go to `dropped.jsonl` for audit.
- Tests use the mock provider with hand packets standing in for the model. Four sabotaged responses each land in the right drop bucket: a fixed MRZ, editorialising, numeric dates only, and an exception.
- Plumbing check without network: `python -m step1_data_generation.ood_llm --allow-eval --mock --out /tmp/x`. Inspect a real prompt with `--dry-run`.

### 3. Domain adapter (`step3_domain_adapter/`)
- **`common.py`:** `AdapterCfg` uses the same field names as `TrainCommon`, so `step5_training.gpu.load_lora_model` is reused unchanged (16-bit, never 4-bit).
  - The split is deterministic: ~4k-character paragraph chunks, and a chunk is held out iff `sha256(file:idx) % 10 == 0`.
  - `max_chars_per_file` caps the 750 kB FinCEN rule at 400k characters so it doesn't dominate.
- **`train_adapter.py`:** a Modal job that **reuses the `modal_infra.py` images** and only appends its own package with `add_local_python_source`, so L's file is untouched.
  - EOS-joined text is packed into `max_seq_len` blocks, with causal-LM loss on every token.
  - Held-out loss is evaluated before training (the untrained LoRA equals the base, since B=0) and after.
  - Outputs: the adapter and `run.json` (with corpus hashes) under `/vol/ckpt/adapter/<run>/`.
- **`measure_adapter.py`:** base vs base+adapter on the same held-out chunks.
  - Token-weighted perplexity, overall and **per file**, so a gain on one dominant document shows up as such.
  - The **30-item probe**, cloze-scored: mean option log-likelihood, accuracy and margin.
  - A **mechanical verdict**: "moved" means perplexity is down at least 2% **and** probe accuracy on the answerable items is not down. Otherwise it prints "DID NOT MOVE (enough)" with the numbers.
- **`probe.py`:** 10 MRZ items, 4 of them check digits computed on invented strings with `lib/mrz.check_digit`; 10 PEP/CDD items (FATF R.10/R.12, family and associates, international-organisation PEPs, FinCEN 25% ownership, the control prong, nature and purpose, ongoing monitoring); 10 list/alias/address items (FtM `weakAlias`/`previousName`/`lastName`/`Sanction`, fuzzy matching, transliteration, DE/US/CN address order, postcode formats).
  - Each item names its source file and an evidence phrase.
  - **Only 12/30 are answerable from the corpus in the repo today.** The MRZ, FATF and Wolfsberg items need the laptop fetch. `measure_adapter` reports accuracy on all items and on the answerable subset, so a missing document doesn't look like a failed adapter. Rerun `answerability()` after the fetch.
- **`fetch_corpus.sh`:** WebFetch and curl to the publishers are still blocked here, so URLs were checked by **web search only**. **VERIFIED-SEARCH** means the exact URL appeared as a result with a matching title; it was **not downloaded**.
  - ICAO moved to `/sites/default/files/publications/DocSeries/9303_pN_cons_en.pdf`; the old path is kept as a fallback.
  - Wolfsberg moved to UUID asset paths on `db.wolfsberg-group.org`.
  - FATF Recommendations: `fatf-recommendations-2012.pdf`, the June 2026 update.
  - Added: Wolfsberg **Negative News Screening FAQs (2022)** (adverse-media text the brief asks for), **EU AMLD 2015/849** (PEP definitions) and the OFAC consolidated format spec.
  - OFAC `dat_spec.txt` is **UNVERIFIED**; three candidates are tried in turn.
  - Dropped: the Wolfsberg correspondent-banking principles (off-topic for individual onboarding, and no URL was found).
  - The script now tries several URLs per document, checks that the file starts with `%PDF`, and prints a sha256 prefix to copy into `SOURCES.md`.
- **CPU smoke** (`python -m step3_domain_adapter.cpu_smoke`): **passes on CPU here.** I installed torch 2.14.1, transformers 5.20.1, peft 0.21.2, trl 1.16.0 and modal, the same floors as `modal_infra.py`. On a tiny random Qwen2 model and a slice of the real corpus (96 blocks × 128 tokens, 3 epochs), held-out perplexity went 602.2 → 537.5 (−10.7%), and the verdict code printed "MOVED". The probe ran end to end (30 items, 12 answerable). Its accuracy (8% → 33%) is noise at this size. This proves the plumbing only, not quality.

## What to run on the laptop, in order

| # | Command | What it gives | Cost / time |
|---|---|---|---|
| 0 | Merge L's and M's branches; `python -m pytest -q` | v1 labels for both OOD writers | free |
| 1 | `python -m step1_data_generation.ood_templates --allow-eval` | `data/eval_ood_hand/` (50 cases, 6 styles) | free, seconds |
| 2 | `python -m step1_data_generation.ood_llm --allow-eval --dry-run \| less` | eyeball one real render prompt | free |
| 3 | `python -m step1_data_generation.ood_llm --allow-eval --n 4 --oversample 1 --out outputs/ood_llm_try` | 4 real renders (2 per model): read them and the drop log | ≈ $0.10 |
| 4 | `python -m step1_data_generation.ood_llm --allow-eval` | `data/eval_ood_llm/`: 100 kept of 125 rendered | **≈ $2–4** (63 × Sonnet ≈ 2.5k in / 1.8k out ≈ $0.023 each; 62 × Gemini Flash ≈ $0.009 each); ~5–10 min at 4 workers; reruns are free (cache) |
| 5 | Check `manifest.json` → `status_by_primary_scenario`. If one hard case (e.g. `tamper_looks_like_ocr`) is dropped far more than the rest, rerun with `--oversample 1.5 --force` or accept the skew and report it | | |
| 6 | Freeze **both** OOD sets with `step6_evaluation/split_guard.py` after the dev pilot, as for L's sets | | free |
| 7 | `bash step3_domain_adapter/corpus/fetch_corpus.sh` | the FATF / ICAO / Wolfsberg / AMLD / OFAC text; paste the printed sha256s into `SOURCES.md`; fix any `FAIL` line from its landing page | free, ~2 min |
| 8 | `python -c "from step3_domain_adapter import probe as P; print(sum(P.answerability('step3_domain_adapter/corpus').values()))"` | expect ~28–30/30 answerable after the fetch | free |
| 9 | `python -m step3_domain_adapter.cpu_smoke` | pre-flight in the training env | free, ~1 min CPU |
| 10 | `modal run -m step3_domain_adapter.train_adapter --config step3_domain_adapter/configs/adapter_toy.yaml`, then `modal run -m step3_domain_adapter.measure_adapter --config step3_domain_adapter/configs/adapter_toy.yaml` | Modal rehearsal on Qwen3-0.6B | **< $0.50** (L4, ~10 min including image build) |
| 11 | Fill `run_name` and `base_model` in `configs/adapter.yaml` (the size stage 1 picked) and run `--dry-run` | corpus stats; expect ~2 M chars ≈ 0.5 M train tokens | free |
| 12 | `modal run -m step3_domain_adapter.train_adapter --config step3_domain_adapter/configs/adapter.yaml` | adapter + held-out loss before/after | **≈ $1–2** for 2B (A100-80GB ~$2.5/h; ~1 M tokens over 2 epochs ≈ 10–20 min plus first image build), ≈ $2–4 for 4B |
| 13 | `modal run -m step3_domain_adapter.measure_adapter --config step3_domain_adapter/configs/adapter.yaml` | `outputs/adapter/<run>/measure.json` + table + verdict, which goes into the write-up as is | ≈ $0.30 (L40S, ~10 min) |
| 14 | If the verdict is "moved" and you keep it: `step5_training/merge.py` (adapter onto base) → use the merged repo as `base_model` in `step5_training/configs/sft.yaml` | stage 2 → 3 hand-off | ≈ $0.20 |

Total for this session's laptop work: **≈ $5–8**.

## Decisions for Tianle
1. **Which 50 "hand-template" cases count for D13?** L's lunch task also builds `eval_ood_template` (50) with the training renderer's held-out families (`email`, `ocr_dump`). That renderer is the training renderer's code, so it is a *style* shift, not a *process* shift. My recommendation:
   - Count `eval_ood_hand` (written blind, D14) as the D13 "50 hand-template".
   - Report L's 50 as a separate "held-out layout" row, or drop them.
2. **LLM drop skew:** the checks are deliberately strict, because a dropped case is cheap and a wrong gold label is not. If the models "fix" MRZs on tamper cases more often, the kept set under-represents those cases. The manifest shows the drop rate per scenario. Decide after step 5 whether to oversample or report the skew.
3. **Adapter hyper-parameters** (`configs/adapter.yaml`): r=32, lr 1e-4, 2 epochs, 1024-token blocks, FinCEN capped at 400k characters. These are defaults, not tuned. A cheaper alternative if time is short: run only the toy rehearsal plus the real run on the chosen size, and skip any sweep.

## Not done / not verified
- No real frontier call, Modal job or GPU run (no keys here).
- The new corpus URLs were **not downloaded**. Their status is from search results only.
- The probe evidence phrases for the not-yet-fetched documents (MRZ wording, FATF and Wolfsberg phrasing) are my best guess at what the text contains. `answerability()` checks them for real after the fetch, and any item still unanswerable is reported as such rather than counted.
- I did not touch `data/`, `step5_training/modal_infra.py` or any file Session L owns.
