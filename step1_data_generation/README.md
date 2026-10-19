# step1_data_generation — answer-first synthetic KYC case generator and dataset splits (setup, feeds every stage of the brief)

## What it does
- Samples the hidden facts of a case first (the "truth"), then computes the correct answer from them with the policy code (`project.py`), then renders the case packet as text. Labels are exact by construction.
- Adds the hard parts on purpose: OCR noise, tampering, transliterated and reordered names, foreign address formats, partial DOBs, PEP / sanctions / adverse-media hits, prompt injections, stale proof of address, varied layouts.
- Builds every split from its own YAML config and seed range, with names, document numbers, addresses and list entries hash-partitioned so train, dev and eval never share entities.
- Also builds counterfactual twins (one decision-flipping fact changed) and evidence knockouts for training, and two out-of-distribution eval sets (hand-written templates, LLM-written prose).

## Key files
| File | What it is |
|---|---|
| `truth.py` | Latent-truth case object, independent of the output schema |
| `sample.py` | Scenario sampler covering every hard-case type (`BRIEF_COVERAGE`), configurable mix and seed |
| `project.py` | Truth → expected output under `step0_rules/schema/v1.json`, applying `policy_v1.md`. **The only module that knows the schema and policy** |
| `render.py` | Truth → packet text: 4 training layouts (`kv`, `form`, `prose`, `mixed`) + 2 held-out (`email`, `ocr_dump`) |
| `lib/` | Decision-free building blocks: MRZ, names, matching, addresses, OCR / tamper noise, synthetic watchlists |
| `config.py`, `configs/*.yaml` | One config per split: `train`, `dev`, `eval_id`, `eval_ood_template`, `eval_hard` |
| `build.py` | CLI: config → `data/<split>/` with sha256 manifest. Refuses eval splits without `--allow-eval` |
| `twins.py`, `knockout.py` | Counterfactual twins (15 flip ops) and evidence knockouts (5 ops); train-side only |
| `ood_templates.py`, `ood_llm.py` | Eval-only OOD writers: 50 hand-template packets in 6 new layouts; 100 LLM-written packets |
| `brief_audit.py` | Coverage audit: one row per brief detail with counts per split |

## How to use
Rebuild the training-side data (pure Python, seconds; same config + seed + n gives identical bytes):
```bash
python -m step1_data_generation.build --config step1_data_generation/configs/train.yaml --n 3000      # -> data/train/
python -m step1_data_generation.build --config step1_data_generation/configs/dev.yaml --n 150         # -> data/dev/
python -m step1_data_generation.build --config step1_data_generation/configs/train.yaml --n 3000 --augment-only \
    --set twins.enabled=true --set twins.fraction=0.3334 --set twins.max_op_share=0.12 --out data/train_twins
python -m step1_data_generation.build --config step1_data_generation/configs/train.yaml --n 3000 --augment-only \
    --set knockout.enabled=true --set knockout.fraction=0.1 --out data/train_knockout
```
Eval sets are frozen. Do not rebuild them into `data/`; verify them instead (writes only to a scratch dir, no API):
```bash
bash regenerate_eval.sh            # eval_id, eval_ood_template, eval_ood_hand, eval_ood_llm (cache replay), eval_hard
```
Try a generator on a scratch dir:
```bash
python -m step1_data_generation.build --config step1_data_generation/configs/train.yaml --n 50 --out /tmp/x \
    --set ocr_digit_to_digit_in_numeric=false --set twins.enabled=true
python -m step1_data_generation.ood_templates --show case_ticket           # print one hand-OOD packet, no files
python -m step1_data_generation.ood_llm --allow-eval --dry-run             # plan + one prompt, no calls
python -m step1_data_generation.ood_llm --allow-eval --mock --out /tmp/x   # plumbing check, no network
python -m step1_data_generation.ood_llm --allow-eval                       # (API, costs money, ~$5) real LLM OOD run
python -m step1_data_generation.brief_audit                                # -> documentation/05_progress_reports/brief_compliance.md
```
Tests: `python -m pytest -q tests/a_*_test.py tests/j_*_test.py tests/m_ood_test.py`

## Outputs / where results live
- `data/<split>/`: `cases.jsonl` (`case_id, split, config_id, schema, style, scenarios, knobs, packet, ref_ids, expected`), `truth.jsonl` (hidden facts, never shown to a model), `manifest.json` (command, config sha256, file hashes). Twins / knockouts add `twins.jsonl` / `knockouts.jsonl`; `eval_ood_llm/` adds `dropped.jsonl`.
- Freeze manifests: `data/eval/MANIFEST.json` (eval_id + 3 OOD sets), `data/eval_hard/manifest.json`, `data/eval_v2/MANIFEST.json` (eval_id_v2).
- Split sizes and decision mix: [data/README.md](../data/README.md).
- LLM cache for replaying the OOD-LLM set: `results/eval_regen/ood_llm_cache/`.

## Reports and evidence
- [overnight-A.md](../documentation/05_progress_reports/overnight-A.md), [overnight-A-samples.md](../documentation/05_progress_reports/overnight-A-samples.md): building blocks and the first draft generator.
- [overnight-J.md](../documentation/05_progress_reports/overnight-J.md): generator v1 (as-of date, splits with disjoint entities, plausibility, twins, knockouts).
- [lunch-L.md](../documentation/05_progress_reports/lunch-L.md): v1 labels and all datasets; independent re-labelling 600/600.
- [brief_compliance.md](../documentation/05_progress_reports/brief_compliance.md): coverage of every brief detail per split.
- [lunch-M.md](../documentation/05_progress_reports/lunch-M.md): hand-template and LLM OOD writers.
- [v1_data_samples.md](../documentation/05_progress_reports/v1_data_samples.md): one example case per data pile.
- [data_design.md](../documentation/03_design/data_design.md), [contamination_protocol.md](../documentation/03_design/contamination_protocol.md): design and contamination rules.
- [OVERNIGHT2.md](../documentation/06_agent_instructions/OVERNIGHT2.md) (Session J), [LUNCH.md](../documentation/06_agent_instructions/LUNCH.md) (Sessions L, M): the briefs that built it.
- [findings_log.md](../documentation/04_results/findings_log.md) §1–2: data, labels, contamination evidence.

## Details
**Building blocks (`lib/`, decision-free)**
| Module | What |
|---|---|
| `mrz.py` | ICAO 9303 TD3 (passport) and TD1 (ID card) MRZ: build, check digits, parse. Tested against the spec specimens |
| `names.py` | Fictional names: Arabic, Cyrillic (several romanizations, patronymics), Chinese (Pinyin / Wade-Giles / Cantonese), Latin (EN/ES/PT/DE/FR), Yoruba, Igbo, Indian. Variants, reorderings, aliases, public-figure blocklist |
| `matching.py` | Name normalization, token Jaro-Winkler similarity, simulated vendor score, partial DOB comparison |
| `address.py` | Addresses for US, GB, DE, FR, AE, RU, CN, IN, NG, BR in national postal layouts (native script for RU/CN); benign vs contradicting variants |
| `ocr.py` | OCR noise injector (text and MRZ, logged edits), MRZ OCR repair/explain, separate field-level tamper injector |
| `watchlist.py` | Synthetic sanctions entries (structured like SDN/UN/EU/UK lists), PEP and RCA entries, adverse media; vendor-style screening |

**Generator v1 behaviour**
- **As-of date**: `Context.as_of_date`, printed in every packet. Expiry and proof-of-address recency use it.
- **Knob vector**: `CaseTruth.knobs` logs scenario, difficulty knobs, document / PoA / hit facts, layout style, switches and augmentation origin.
- **Splits**: case ids `trn-` / `dev-` / `eid-` / `ood-`; entities partitioned by `sha256(pool:item) mod 10` (train 0–6, dev 7, eval_id 8, eval_ood_template 9).
- **Held-out layouts**: `email` and `ocr_dump` are never allowed in train or dev configs.
- **Plausibility** (`plausibility: true`): age vs occupation, national ID only for citizens at home, driving licence only where issued and used, onboarding abroad only where it makes sense.
- **Noise-rule switch** `ocr_digit_to_digit_in_numeric: false`: OCR never swaps one digit for another in a numeric MRZ field, so `project.py` labels such a disagreement as tampering.
- **Twins / knockouts**: a twin is kept only if `project.py` gives a different outcome; a knockout only if the outcome becomes escalate. Both are OFF by default and refused for eval splits.
- **Contamination**: train and dev builds run `step6_evaluation/split_guard.py` against any frozen `data/eval*/MANIFEST.json`; overlap aborts the build.

**Eval sets and their seeds** (from `step6_evaluation/regenerate_eval.py` and the manifests)
| Set | Built by | Seed |
|---|---|---|
| eval_id (300) | `build.py`, `configs/eval_id.yaml` | 3000000 |
| eval_ood_template (50) | `build.py`, `configs/eval_ood_template.yaml` | 4000000 |
| eval_ood_hand (50) | `ood_templates.py` | 4010000 |
| eval_ood_llm (100) | `ood_llm.py` (Claude Sonnet 5.5 and Gemini 3.8 Flash alternate) | 4020000 |
| eval_hard (150) | `build.py`, `configs/eval_hard.yaml` | 5000000 |
| eval_id_v2 (300) | `build.py`, `configs/eval_id.yaml`, generated after all development | 3050000 |

`regenerate_eval.sh` does not cover eval_id_v2; its exact command is in `data/eval_id_v2/manifest.json` and its hashes in `data/eval_v2/MANIFEST.json`.

**Legacy.** `build_draft.py` writes the 200 PROVISIONAL v0 cases to `data/draft/` (frozen fixtures for older tests, never training). It still runs but no longer reproduces the committed `data/draft/` hashes.
