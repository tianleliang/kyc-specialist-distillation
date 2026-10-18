# data — every generated dataset: train, dev, frozen eval sets and SFT files (input to pipeline stages 1–5 of the brief)

## What it does
- Holds the synthetic KYC cases built by `step1_data_generation/` (answer-first: hidden truth → packet + gold label), schema v1 / policy v1.
- Keeps training data (`train*`, `sft/`) and development data (`dev`, `reader_dev`) apart from the eval sets.
- The eval sets are **frozen by sha256 manifests** and never feed training or teacher prompts. `split_guard verify` proves they are unchanged.
- Every split has a `manifest.json` with the exact build command, seed, config sha256, git commit and file hashes.

## Key files
| Path | What it is |
|---|---|
| `train/` (3,000), `train_twins/` (1,000), `train_knockout/` (300) | Training cases; counterfactual twins and evidence knockouts of train cases (`twins.jsonl` / `knockouts.jsonl` link each to its base) |
| `dev/` (150) | Model selection and ablations; never eval |
| `reader_dev/` (600) | Train-process cases in all 6 styles, only for developing the pre-checker reader; never training |
| `eval_id/` (300), `eval_ood_template/` (50), `eval_ood_hand/` (50), `eval_ood_llm/` (100) | Frozen eval v1 = 500 cases, manifest `eval/MANIFEST.json` |
| `eval_hard/` (150) | Stress cases, frozen separately (`eval_hard/manifest.json`) |
| `eval_id_v2/` (300) | Fresh in-distribution set (new seed), frozen Sunday in `eval_v2/MANIFEST.json`; headline test set |
| `sft/` | SFT training files from `step4_distillation/`, each with `<file>.stats.json` |
| `draft/` (200) | Legacy v0 cases for older tests; not v1, never training (see `draft/README.md`) |

Each split dir has `cases.jsonl` (what a model sees, plus `expected` = gold), `truth.jsonl` (hidden latent facts, never shown to a model) and `manifest.json`.

## How to use
```bash
bash regenerate_eval.sh                                   # rebuild frozen v1 + eval_hard in a scratch dir, verify hashes (free)
python -m step6_evaluation.split_guard verify --manifest data/eval/MANIFEST.json
python -m step6_evaluation.split_guard verify --manifest data/eval_v2/MANIFEST.json
python -m step1_data_generation.build --config step1_data_generation/configs/train.yaml --n 3000   # rebuild train (free)
python -m step1_data_generation.brief_audit                # coverage of every brief detail per split
```
Rebuilding `eval_ood_llm` from scratch calls two LLMs (API, costs money); `regenerate_eval.sh` replays the recorded responses instead.

## Outputs / where results live
- This folder is the output of `step1_data_generation/` and `step4_distillation/`.
- Final model training files: `sft/distill_arbitrate_plus_twins_pc3.jsonl` (stage 3) and `sft/gold_train_solnarr_pc3.jsonl` (stage 4).
- Model predictions on these sets live in `results/runs/`, not here.

## Reports and evidence
- [Evidence log §1 (data, labels, rulebook) and §2 (contamination controls)](../documentation/04_writeup/writeup_evidence_log.md)
- [Brief compliance audit](../documentation/05_progress_reports/brief_compliance.md), [one example per pile](../documentation/05_progress_reports/v1_data_samples.md)
- [Data design](../documentation/03_design/data_design.md), [contamination protocol](../documentation/03_design/contamination_protocol.md)
- Session reports: [lunch-L.md](../documentation/05_progress_reports/lunch-L.md) (v1 datasets), [lunch-M.md](../documentation/05_progress_reports/lunch-M.md) (OOD sets), [overnight-J.md](../documentation/05_progress_reports/overnight-J.md) (generator v1)

## Details

### Build commands and decision mix (approve / escalate / reject)
| Dir | Command (from `manifest.json`) | Mix |
|---|---|---|
| `train/` | `python -m step1_data_generation.build --config step1_data_generation/configs/train.yaml --n 3000 --seed 1000000` | 1,141 / 1,419 / 440 |
| `dev/` | `... --config .../dev.yaml --n 150 --seed 2000000` | 50 / 83 / 17 |
| `train_twins/` | `... --config .../train.yaml --n 3000 --augment-only --set twins.enabled=true --set twins.fraction=0.3334 --set twins.max_op_share=0.12 --out data/train_twins` | 25.7 / 47.1 / 27.2 % |
| `train_knockout/` | `... --config .../train.yaml --n 3000 --augment-only --set knockout.enabled=true --set knockout.fraction=0.1 --out data/train_knockout` | 0 / 100 / 0 % |
| `eval_id/` | `... --config .../eval_id.yaml --n 300 --seed 3000000 --allow-eval` | 91 / 169 / 40 |
| `eval_ood_template/` | `... --config .../eval_ood_template.yaml --n 50 --seed 4000000 --allow-eval` | 13 / 34 / 3 |
| `eval_ood_hand/` | `python -m step1_data_generation.ood_templates --allow-eval --n 50 --seed 4010000` | 15 / 31 / 4 |
| `eval_ood_llm/` | `python -m step1_data_generation.ood_llm --allow-eval --n 100 --seed 4020000` | 34 / 62 / 4 |
| `eval_hard/` | `... --config .../eval_hard.yaml --n 150 --seed 5000000 --allow-eval` | see manifest |
| `eval_id_v2/` | `... --config .../eval_id.yaml --n 300 --seed 3050000` | 108 / 164 / 28 |
| `reader_dev/` | `python -m step7_serving.build_reader_dev` (train config, seed 1500000, all 6 styles) | 235 / 288 / 77 |

### Freeze dates
- `eval/MANIFEST.json` (eval_id + 3 OOD): frozen 2026-10-17 19:17 UTC.
- `eval_hard/manifest.json`: frozen 2026-10-17 20:31 UTC.
- `eval_v2/MANIFEST.json` (eval_id_v2): frozen 2026-10-18 16:18 UTC.

### Notes
- 25% of `eval_id` uses two layout styles never seen in training (`email`, `ocr_dump`).
- Each case row: `{case_id, split, config_id, schema, style, scenarios, knobs, packet, ref_ids, expected}`.
- `eval_ood_llm/dropped.jsonl` lists LLM-written packets that failed the fact checks.
- `regenerate_eval.sh` covers frozen v1 and `eval_hard`; it does not rebuild `eval_id_v2` (verify that one with `split_guard verify`).
