# Overnight report: Session J (generator v1)

Branch: `claude/festive-sagan-wxndcj` (the environment set the name; it doesn't contain the letter J).
Files owned: `step1_data_generation/` (wave-2 changes), `step1_data_generation/configs/`, `tests/j_*_test.py`, this report. No new dependencies (PyYAML is already in `requirements.txt`).

**Tests: 283 passed, 3 skipped, 1 failed** (`python -m pytest -q`, about 18 s).
- All 97 of A's tests still pass unchanged.
- 63 new J tests pass: `tests/j_generator_v1_test.py` (20), `tests/j_splits_test.py` (16), `tests/j_twins_knockout_test.py` (27).
- The one failure was there before this work: `tests/f_llm_clients_test.py::test_missing_key_errors_cleanly`. It depends on a local `.env`, and Session I owns the fix.

## Done (every item in the brief)

| # | Item | Where | Notes |
|---|---|---|---|
| 1 | **As-of date** | `truth.Context.as_of_date`, `render._ctx`, `project.py` | Every packet prints it in CTX, labelled "As-of date", "Review date (as of)" or "Assessed as of". Expiry and PoA recency are judged against it. It equals the application date by default. `as_of_lag_days` can separate the two dates, and a test checks the labels follow the as-of date |
| 2 | **Knob vector** | `CaseTruth.knobs`, `sample.knob_vector` | 52 flat, JSON-able keys: scenarios, origin, nationality / residence / onboarding tie, age, occupation, document kind and issuer, MRZ check, defect and tamper kinds, days to expiry, PoA age / relation / style / abbreviation, hit list types and DOB comparisons, injection location, ambiguity flags, **style** (and seen vs held-out), the switches, and augmentation origin. The style is drawn from its own RNG stream, so changing the style pool never changes the facts (tested) |
| 3 | **Split-aware configs + build CLI** | `step1_data_generation/configs/{train,dev,eval_id,eval_ood_template}.yaml`, `step1_data_generation/config.py`, `step1_data_generation/build.py` | See the next table. `python -m step1_data_generation.build --config step1_data_generation/configs/<split>.yaml --n N` writes `data/<split>/{cases,truth}.jsonl` and `manifest.json`. The manifest holds the config, its sha256, any `--set` overrides, the git commit, the sha256 of every file, counts and the exact command. Same config, seed and n give the same bytes (tested). **The real eval set was not generated.** Eval splits refuse to build without `--allow-eval`, and the CLI refuses to overwrite an existing manifest |
| 4 | **Plausibility constraints** (A's Problem 2) | `sample.py` (`plausibility: true`) | Age vs occupation (students 18–30, retired 58+, GP 28+, …). A national ID is issued by the nationality and only held by a citizen living in that country. A driving licence is issued by the country of residence and only used there. Onboarding outside the country of residence happens only in the nationality's country, or for brokerage / crypto / remittance through online or mobile. Can be switched off (A's old behaviour); tested both ways |
| 5 | **Noise-rule switch** (E's Problem 7) | config `ocr_digit_to_digit_in_numeric`, `sample._id_document`, `project._zone_check` | `true` (default; A's behaviour): OCR can misread one digit as a look-alike digit in the MRZ, giving `possible_ocr_or_tamper` → escalate. `false` (E's rule): OCR noise never swaps one digit for another in a numeric field, so a one-digit disagreement is labelled `tamper_indicators`, and no `ocr_vs_tamper_undecidable` ambiguity is produced. Flip with `--set ocr_digit_to_digit_in_numeric=false` |
| 6 | **Twins + knockout** (both off by default) | `step1_data_generation/twins.py`, `step1_data_generation/knockout.py`; `twins:` / `knockout:` blocks in `train.yaml` | **15 twin flip ops**: expire/renew ID, tamper one document digit, listed DOB conflict/confirm, listed DOB partial/full, PoA stale/refresh, PoA contradict/fix, declared DOB typo/fix, add/remove injection. Each edits one truth section, which is tested by diffing the base and twin truths. The twin keeps the base's style and render key, so the packets differ only in that fact. A pair is kept only if `project.outcome()` changes, and `twins.jsonl` records the before and after outcomes. **5 knockout ops**: remove a hit's listed DOB and nationality, remove an article's age/city/occupation, make one ID field illegible in every zone, remove the PoA, make the PoA illegible. A knockout is kept only if the outcome becomes escalate. Tests check that every op's labelled flip happens through `step1_data_generation/project.py`, and that a knockout never leaves an approvable case. Both are refused for eval splits |
| 7 | **PoA abbreviation in the truth** (A's Problem 1) | `Application.address_abbreviated`, `ProofOfAddress.abbreviated`, `project._poa_prints_declared` | Abbreviation is no longer a render-time coin flip, and is only set when it actually changes the text. While fixing this I found a second, larger source of the same noise: A labelled `single_line` PoAs as `format_variant`, but that text is byte-identical to the declared one-line address (200/200 sampled). The label is now `poa_address_matches` exactly when the PoA prints the declared address identically, up to line breaks (tested) |

### Splits

| Split | Seeds | Entity bucket | Nationality pools | Layouts | Injection texts |
|---|---|---|---|---|---|
| train | 1,000,000–1,999,999 | 0–6 | train set | kv, form, prose, mixed | A's 6 |
| dev | 2,000,000–2,099,999 | 7 | = train | = train | = train (same distribution, by design) |
| eval_id | 3,000,000–3,099,999 | 8 | different, home nationality kept | seen + **email, ocr_dump** (so results can be sliced seen vs unseen) | 5 new |
| eval_ood_template | 4,000,000–4,099,999 | 9 | different | **email, ocr_dump only** | 5 new |

- **Entities partitioned** by `sha256(pool:item) mod 10`: person full names (applicant, look-alikes, PEP relatives), document numbers, addresses (full key) and watchlist entry ids. Listed names follow from the people.
- **Held-out layouts:** `email` is an intake e-mail with pasted attachments and a CSV screening export. `ocr_dump` is one wrapped OCR dump with no section headers, only inline reference tags. Train and dev configs that include either one fail to load.
- The two eval configs also use a flatter mix and a different `p_secondary`, and were written separately rather than copy-edited from `train.yaml` (contamination protocol §4).
- **Proof of disjointness:**
  1. On 150 cases per split, the entity sets are pairwise disjoint (0 shared items in every pool). The only exception is the shared step5_training/dev injection pool, which is intended.
  2. Running `python -m step6_evaluation.split_guard check` as a subprocess on built samples gives `OK: 0/80` for train + dev against eval_id + ood, and 0 for train against dev.
  3. A positive control (one eval case appended to train) exits 1 with `CONTAMINATION`.
  4. `build()` aborts if a frozen `data/eval*/MANIFEST.json` overlaps a train or dev build. This is tested with a temporary frozen file.

Decision mix at n=1000 under the provisional policy: train approve 39 / escalate 51 / reject 10; eval_id 34 / 54 / 11; eval_ood_template 33 / 58 / 9.

## Not done / partial
- **New onboarding countries for OOD** (data_design §5 suggests MX, JP): `step1_data_generation/lib/address.py` only has 10 country templates. Adding more means new address templates.
- **Partitioned pools still missing:** PoA issuers, employers and adverse-media headline templates are not partitioned (the pools have 1–11 items). Injection texts are separated per split by the configs instead.
- **Stratified quotas** for eval (≥30 per tag): the eval configs use weights, not quotas. `plan()` already guarantees at least one case per scenario, and quotas are a small addition once the eval sizes are fixed.
- **`data/draft/` is now stale.** `python -m step1_data_generation.build_draft` still runs, but its hashes no longer match A's committed manifest, because packets now print the as-of date, PoA labels changed, and so on. I didn't regenerate it because `data/draft/` is A's wave-1 output and C's harness check used it. One command fixes it: `python -m step1_data_generation.build_draft`.
- `GENERATOR_VERSION` is now `v1.0-wave2`, and `step1_data_generation/project.py` is still the PROVISIONAL v0 policy and schema.

## Problems / things to know
1. **`project.py` reads one truth knob.** The OCR-vs-tamper label depends on `knobs["ocr_digit_to_digit_in_numeric"]`. That's deliberate: under E's rule, a digit→digit disagreement is decidable only because the noise model guarantees it never produces one. **Train and eval must use the same value** (both configs say so). When the policy is chosen, set it in all four YAMLs.
2. **Twins and knockouts are copies of train cases.** They are near-duplicates of their bases inside train, which is fine. They must never be generated from dev or eval truths: the configs refuse that, and `split_guard` would catch it.
3. `hit_dob_confirm` can turn a background false-positive hit (a different, similar-named person) into a true match by giving the entry the applicant's exact DOB. That is consistent with the provisional rule (name + exact DOB + nationality → true_match), but it's worth knowing when choosing ops. Restrict ops with `twins.ops: [...]`.
4. The `remote_product` onboarding tie forces the product to brokerage, crypto or remittance. That applies to about 14% of cases (136 of 1000 at the default config) and nudges them toward medium risk.
5. Knob key names are documented in `sample.knob_vector`. Session K's `step4_distillation/hard_mine.py` should read `knobs["primary"]` / `knobs["scenarios"]` and the other keys from `cases.jsonl` rows (also in `truth.jsonl` → `truth.knobs`).

## Questions for Tianle
1. **Noise rule:** keep `ocr_digit_to_digit_in_numeric: true` (a look-alike digit is ambiguous → escalate) or switch to `false` (E's rule: a digit→digit disagreement is tampering → reject under the current policy)? One flag in each config.
2. **As-of vs application date:** keep them equal (current), or use a review lag (`as_of_lag_days`) so the model must use the as-of date? A lag makes the case harder and adds a policy question: which date governs?
3. **Invented technique:** twins, knockout, or both? Turn one on with `--set twins.enabled=true` and/or `--set knockout.enabled=true` on the train build. Per E's Problem 5, the twins batch must reach teachers by about 15:00 Saturday.
4. **Eval sizes and quotas:** confirm eval_id 300 / OOD template 50 (plus LLM-rendered OOD truths from `eval_ood_template.yaml`), so quotas can replace weights before the freeze.
5. Should the stale `data/draft/` be regenerated (it changes the hashes C's harness check recorded)?

## Commands for Saturday
```bash
python -m step1_data_generation.build --config step1_data_generation/configs/train.yaml --n 3000                      # data/train/
python -m step1_data_generation.build --config step1_data_generation/configs/dev.yaml --n 150                         # data/dev/
# after the schema decision, then freeze immediately:
python -m step1_data_generation.build --config step1_data_generation/configs/eval_id.yaml --n 300 --allow-eval
python -m step1_data_generation.build --config step1_data_generation/configs/eval_ood_template.yaml --n 50 --allow-eval
python -m step6_evaluation.split_guard freeze data/eval_id/cases.jsonl data/eval_ood_template/cases.jsonl --manifest data/eval/MANIFEST.json --readonly
python -m step6_evaluation.split_guard check --train data/train/cases.jsonl data/dev/cases.jsonl --eval data/eval_id/cases.jsonl data/eval_ood_template/cases.jsonl
```
