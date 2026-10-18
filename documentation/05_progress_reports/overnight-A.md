# Overnight report: Session A (KYC building blocks + PROVISIONAL draft generator)

Branch: `claude/zorbe-kyc-overnight-a-2zfyja` (the environment forced the name; it contains the session letter).
Tests: **97 passed** (`python -m pytest -q`, about 1.3 s). There are no extra dependencies beyond `requirements.txt`, so there is no `requirements-a.txt`.
Test files are named `tests/a_*_test.py`. That fits the `tests/<letter>_*` rule and is still picked up by pytest's default `*_test.py` discovery; `pytest.ini` was not touched.

## Done

### Phase 1: building blocks (`step1_data_generation/lib/`), each with pytest
| # | Item | Module | Notes |
|---|---|---|---|
| 1 | MRZ (ICAO 9303) | `mrz.py` | Builds TD3 and TD1, computes check digits (7-3-1, mod 10), parses back to fields, infers the century. **It reproduces the ICAO specimen MRZs exactly** (TD3 `L898902C36UTO...`, TD1 `I<UTOD231458907...`). It also handles diacritic transliteration and name truncation |
| 2 | Name engine | `names.py` | Covers 11 origins. Cyrillic names are stored in Cyrillic and romanized six ways (ICAO 2013, BGN/PCGN, GOST 7.79-B, German, French, legacy passport), so Мухаммад gives Mukhammad, Muchammad and Moukhammad. Chinese names are stored as characters and rendered in Pinyin, Wade-Giles (with and without diacritics) and Cantonese. Arabic names have spelling tables plus rule-based surname respelling, giving Muhammad / Mohammed / Mukhammad / Mehmet and al- / el- / Al / none. Also: patronymics, reorderings, aliases including kunya ("Abu X"), and look-alike different people for false positives. Surnames are built from syllables, and a public-figure blocklist resamples any collision |
| 3 | Name matching | `matching.py` | Normalization strips titles, articles, diacritics and glued `al-`. Similarity is order-insensitive token Jaro-Winkler with a phonetic key and a merged-token pass (Abdul Rahman ~ Abdulrahman). Also a vendor score from 0 to 100 with jitter, and partial DOB comparison (exact / year_month / year_only / range / near_year / day-month swapped). **Known and intended:** Cantonese and Wade-Giles spellings score low against Pinyin (Li Hua vs Lee Wah is 0.48), which makes them hard true matches, as with real vendors |
| 4 | Addresses, 10 countries | `address.py` | US, GB, DE, FR, AE, RU, CN, IN, NG and BR, each in its national postal layout: postcode position and format, uppercase rules, AE P.O. Box with no postcode, RU street→city→region→index, CN in native big-to-small order, IN PIN plus landmark, BR CEP. Single-line and native-script renders. `benign_variant` and `contradicting_variant` (street, number, city, postcode, whole address). Streets are fictional; cities are real places |
| 5 | OCR noise + tamper | `ocr.py` | The **OCR noise** side covers glyph confusions, rn→m, dropped and doubled characters, broken lines and MRZ fillers misread as K, at a configurable rate, with every edit logged. `repair_mrz` and `explain_mrz` classify an MRZ as valid / ocr_repairable / invalid / unreadable. The **separate tamper injector** works on fields and has 4 kinds: visual zone only; both zones without recomputed check digits; both zones with recomputed check digits (undetectable from the document); and an MRZ lookalike digit. Both injectors can mimic each other on purpose (digit-lookalike OCR, lookalike tampering) |
| 6 | Watchlists | `watchlist.py` | Sanctions entries follow the SDN, UN, EU and UK structures: uid formats, programs and regimes, a.k.a. strong/weak (UN: Good/Low), circa DOBs, remarks. PEP entries use FATF categories (domestic / foreign / international organisation) and include family and close-associate records. Adverse-media entries use fictional outlets. **Program codes and regulations are invented (`SYN-…`), and every entry carries `synthetic: true`** |
| 7 | Domain corpus | `step3_domain_adapter/corpus/` | **Partial, see Problems.** It has `SOURCES.md` (every source with URL, date and status), `fetch_corpus.sh` (one command re-fetches everything on the laptop) and three stand-in text files: third-party MRZ spec descriptions, sanctions list *structure* metadata from OpenSanctions/FollowTheMoney schemas, and OpenCage address templates |

### Phase 2: end-to-end draft generator (**PROVISIONAL**, all labelled as such)
| # | Item | File |
|---|---|---|
| 1 | Latent truth, schema-independent (a test checks it never mentions decisions or tiers) | `step1_data_generation/truth.py` |
| 2 | Packet renderer, 4 styles (`kv`, `form`, `prose`, `mixed` with shuffled order and a JSON vendor block). Labels and boilerplate get OCR noise; values that labels depend on sit in protected spans | `step1_data_generation/render.py` |
| 3 | Sampler with 23 scenarios, mapped to every brief item in `BRIEF_COVERAGE`; configurable mix, secondary-scenario stacking, seed | `step1_data_generation/sample.py` |
| 4 | Thin projection plus a flat, enum-heavy schema. The provisional policy is in the module docstring. **It is the only file that knows the schema or the policy** | `step1_data_generation/project.py`, `step0_rules/schema/v0_provisional.json` |
| 5 | 200 draft cases (seed 20261017) with a deterministic sha256 in `manifest.json`, the README banner "DRAFT, not an eval set, do not use for training", and 10 review examples | `data/draft/`, `documentation/05_progress_reports/overnight-A-samples.md` |

Regenerate with `python -m step1_data_generation.build_draft`. Two runs give identical hashes.
Draft mix: approve 72 / escalate 102 / reject 26; risk low 40 / medium 96 / high 64; styles kv 47 / form 57 / mixed 54 / prose 42.

**Labels come from the evidence, not the generator's intent.** A real sanctioned person listed with a year-only DOB is labelled `needs_review`, not `true_match`. A tamper with recomputed check digits only shows up as a DOB mismatch against the application. An OCR lookalike digit and a tamper lookalike digit get the same label (`possible_ocr_or_tamper`, escalate), because the packet can't tell them apart.

## Not done or partial
- **Corpus:** the cloud egress proxy returned 403 for every primary publisher: FATF, FinCEN, govinfo, Federal Register, eCFR, ICAO, Wolfsberg, OFAC, UPU, EU, archive.org and Wikipedia. Only GitHub raw, PyPI and npm were reachable. **To finish it, run `bash step3_domain_adapter/corpus/fetch_corpus.sh` on the laptop.** Some FATF, Wolfsberg and OFAC URLs in the script were written from memory and are marked UNVERIFIED in `SOURCES.md`; landing pages are listed for each. One candidate README was deliberately excluded because its examples name a real SDN-listed person.
- The schema and policy are placeholders by design. Nothing in phase 2 is a decision.

## Problems / known limitations
1. **`poa_address_matches` vs `poa_address_format_variant` is partly noise.** Whether a PoA address is abbreviated is decided at render time, so these two reason codes are not fully learnable. Both are `consistent`, so status-level metrics are unaffected. The fix belongs in the real schema: collapse the two codes, or move the abbreviation choice into the truth object.
2. **Combinations can look implausible:** a 75-year-old "University student" in a risk_profile case; a Chinese driving licence held by a Singaporean onboarding in Russia; a German-named Austrian holding an Emirati ID card. They are internally consistent but odd. The real generator should add plausibility constraints for nationality, issuer, residence and age versus occupation.
3. **G/6 OCR confusion passes MRZ check digits** (G=16 ≡ 6 mod 10), so a glyph-noised document number can validate as read. The projection compares document numbers up to glyph confusion. Worth knowing for the tool-assisted variant.
4. Driving licences have no MRZ, so their document number can only be checked for legibility.
5. The sampler draws the same nationality pool per origin (for example, Arabic names get ARE, SAU, EGY, JOR, QAT). Nationality is just a field, but the eval generator should use different pools and configs (contamination rule).
6. Background vendor hits are always clearly-different people, with DOBs 4 to 25 years off. That is realistic, but easy.

## Questions for Tianle (07:45)
1. **Schema:** keep the five fixed identity keys plus a `reason_code` enum and a free-text `reason`? Is `expired` a `mismatch` (as now) or its own status? Narrative as `[{sentence, evidence_refs}]` with section-level refs (`CTX, APP, ID, MRZ, POA, SCR, H1…`), or finer field-level refs?
2. **PEP/RCA match standard:** exact name + year-only DOB + nationality match currently gives `needs_review` (see sample 5). Should that be `true_match` for PEP lists, which often only hold a birth year?
3. **PEP true match → escalate** (senior approval, source of wealth, source of funds) rather than approve-with-EDD. Agree?
4. **Expired ID → escalate** with `request_valid_id_document`, or reject?
5. **Tamper indicators → reject** (visual zone vs valid MRZ, or a check digit that doesn't fit a value both zones agree on), but `possible_ocr_or_tamper` → escalate. Agree with that split?
6. **Medium risk → approve with EDD actions**; high risk → escalate; 3 or more medium factors → high. OK as a starting point?
7. **Prompt injection → always escalate**, even if the rest of the case is clean, plus `security_review_of_packet`. Or ignore the injection and decide on the merits? This changes the adversarial metric definition.
8. **PoA window:** 90 days, stated nowhere in the packet. Should the packet state the window (as CTX policy text), or should the model know it?
9. **On reject**, required actions are currently only the review that caused the rejection. Should the full EDD list be kept so recall is comparable?
10. **Draft mix:** clean cases are about 10%. Is the approve/escalate/reject balance (36/51/13) roughly what the real eval mix should be?

## How to use from other sessions
- Session C: `step0_rules/schema/v0_provisional.json` and `data/draft/cases.jsonl` (`expected` field) are on this branch. Copy them read-only.
- Library entry points: `step1_data_generation.sample.sample_cases(n, seed, mix)`, `step1_data_generation.render.render(truth, style)`, `step1_data_generation.project.project(truth)`.
