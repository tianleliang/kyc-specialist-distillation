# step4_distillation — turn teacher answers into SFT training files (pipeline stage 3 of the brief)

## What it does
- Takes frontier teacher answers on train cases (GPT-6.1 Sol, Gemini 4 Argon) and builds SFT files: the floor (unfiltered), rejection sampling, multi-teacher arbitration, and **Counterfactual Twin Distillation** (twins_filter.py).
- Builds the stage-4 file: exact gold labels with the teacher's narrative (`gold_with_teacher_narrative.py`).
- Adds the code pre-checker block (`PRE-CHECKS`) to any SFT file (`add_prechecks.py`), with an optional share of blank blocks.
- Every writer runs the contamination gate against the frozen eval manifests, and refuses eval case ids.

## Key files
| File | What it is |
|---|---|
| `teacher_outputs/{sol_train,argon_train,sol_twins,sol_knockout}/` | Saved teacher answers (`predictions.jsonl`, `run.json`, `ledger.json` with API cost) |
| `sft_floor.py` | Floor: one teacher sample per case, unfiltered. `--from-gold` = gold-label control |
| `reject_sample.py` | Keeps a sample only if schema, decision, risk tier, every hit disposition, identity fields and evidence refs pass |
| `arbitrate.py` | Multi-teacher arbitration: `gold_select` / `vote` / `splice`, plus teacher agreement rates |
| `twins_filter.py` | Counterfactual Twin Distillation: keeps a twin pair only if the teacher is right on **both** twins |
| `gold_with_teacher_narrative.py` | Stage-4 file: gold fields, Sol's narrative where Sol's decision and risk tier match gold |
| `add_prechecks.py` | Appends the `PRE-CHECKS` block (same function as eval and serving); `--blank-rate` for blank blocks |
| `common.py` | IO, prompt building, `Checker` (built on `step6_evaluation.metrics`), contamination gate |
| `teacher_requests.py`, `matched_n.py` | Build teacher request batches; matched-N random controls |
| `hard_mine.py`, `onpolicy.py`, `prefs.py` | Built and tested, **not used** in the final model (hard-case mining was cut; stage 4 is SFT, not DPO) |

## How to use
All commands below are local and free (no API, no GPU). They read the committed teacher outputs.
```bash
# stage-4 file: gold labels + Sol narratives (defaults are the real paths)
python -m step4_distillation.gold_with_teacher_narrative
#   data/sft/gold_train.jsonl + data/sft/distill_floor_sol.jsonl -> data/sft/gold_train_solnarr.jsonl

# add the PRE-CHECKS block (Final B, reader v2 era): every file -> *_pc.jsonl
python -m step4_distillation.add_prechecks --all

# B2 files: reader v3 block, 25% of rows blank (seeded)
python -m step4_distillation.add_prechecks --in data/sft/distill_arbitrate_plus_twins.jsonl \
    --out data/sft/distill_arbitrate_plus_twins_pc3.jsonl --blank-rate 0.25 --seed 17
python -m step4_distillation.add_prechecks --in data/sft/gold_train_solnarr.jsonl \
    --out data/sft/gold_train_solnarr_pc3.jsonl --blank-rate 0.25 --seed 17

# twin pair filter (pattern; teacher file = PATH[=NAME])
python -m step4_distillation.twins_filter --gold <twins gold JSONL> --fieldmap step6_evaluation/fieldmap_v1.yaml \
    --teacher-outputs step4_distillation/teacher_outputs/sol_twins/predictions.jsonl=sol \
    --system-file <rendered student system prompt> --out data/sft/distill_twins_sol.jsonl

python -m pytest tests/k_distill_test.py      # mock teachers, no keys
```
New teacher answers cost money: `teacher_requests.py` + `python -m shared.frontier_api.batch run ...` (API, costs money). See Details.

## Outputs / where results live
- `data/sft/*.jsonl` with a `<file>.stats.json` next to each (kept / dropped per reason, contamination gate result).
- Final model inputs: `data/sft/distill_arbitrate_plus_twins_pc3.jsonl` (stage 3, 3,934 rows = 2,954 arbitrated + 980 twin rows, 989 blank blocks) and `data/sft/gold_train_solnarr_pc3.jsonl` (stage 4, 3,000 rows, 762 blank blocks).
- Teacher agreement: `data/sft/arbitration_agreement.json`.

## Reports and evidence
- [Evidence log §4 (teachers) and §5b (4B distillation results, winner pick)](../documentation/04_writeup/writeup_evidence_log.md)
- [Session K report (how the pipeline was built)](../documentation/05_progress_reports/overnight-K.md)
- [FINAL_TONIGHT.md](../documentation/06_agent_instructions/FINAL_TONIGHT.md), [SUNDAY_BRUN2.md](../documentation/06_agent_instructions/SUNDAY_BRUN2.md), [SUNDAY_READER_V3.md](../documentation/06_agent_instructions/SUNDAY_READER_V3.md) (blank-block option)
- Dev scores of each recipe: [`results/runs/distill-4b-*__dev/`](../results/runs/), [`step5_training/results/dev_evals/`](../step5_training/results/dev_evals/)

## Details

Each step is a CLI that reads JSONL and writes JSONL. Nothing here knows the schema: every location (decision, risk tier, hits, identity fields, actions, narrative) comes from the FieldMap YAML (`--fieldmap`, plus `--schema`) that `step6_evaluation/metrics.py` also uses.

Key numbers (from the `.stats.json` files): floor 3,000 rows; rejection keeps 2,971/3,000 (teachers are ~99% policy-consistent, so it drops ~1%); splice arbitration keeps 2,954; twins keeps 980/1,000 pairs (1,960 records), teacher flip consistency 0.986. Contamination gate: 0 contaminated eval records on every file.

### Which file fills which Table 2 row (original plan)
| Row (`documentation/03_design/experiment_plan.md`) | File | What it does |
|---|---|---|
| input to all | `teacher_requests.py` | train cases → teacher request JSONL for `shared.frontier_api.batch` (k samples, contamination gate) |
| S2 floor | `sft_floor.py` | teacher outputs → SFT records, unfiltered |
| gold-label control | `sft_floor.py --from-gold` | target = generator labels; answers "did the teachers add anything?" |
| S3 rejection | `reject_sample.py` | best of k passing samples; drop rate per tag |
| S3–S5 controls | `matched_n.py` | random floor subset of the same size |
| S4 arbitration | `arbitrate.py` | `gold_select` / `vote` / `splice` (field-wise best-of, re-validated) |
| S5 invented technique | `twins_filter.py` | pair filter; `--pairs-out` writes twin hard negatives for DPO |
| S6 hard-case mining | `hard_mine.py` | dev failures → resampling mix (cut) |
| S6 on-policy correction | `onpolicy.py` | student failures → teacher corrections (not run) |
| S7 DPO | `prefs.py` | preference pairs (not run) |

### Contamination
- Every training-file writer goes through `write_training_file`: it writes a temp file, runs `step6_evaluation/split_guard.py`'s overlap check against every frozen eval manifest (`--eval-manifest`, or auto-discovered `data/eval*/MANIFEST.json`), and moves the file into place only if clean.
- Case ids that start with `eid-`, `ood-` or `eval-` are refused everywhere. `hard_mine.py` refuses any frozen eval file; mining runs on dev only.
- `gold_with_teacher_narrative.py` and `add_prechecks.py` only re-combine already-gated files, so they refuse eval ids but are not re-gated.

### Switches that encode a choice
| Flag | Default | Alternatives |
|---|---|---|
| `--min-field-acc` | `1.0` (all identity fields exact) | e.g. `0.8` |
| `--actions` | `off` | `superset`, `exact` |
| `--evidence-refs` | `strict` | `off` |
| `--max-extra-hits` | `0` (no invented hits) | `-1` = ignore |
| `sft_floor --samples` | `first` | `all` |
| `reject_sample --keep` | `best` | `all` |
| `arbitrate --repair` | `drop` | `gold` |
| `arbitrate --tie` | `priority` | `drop` |

### New teacher answers (API, costs money)
```bash
python -m step4_distillation.teacher_requests --gold data/train/cases.jsonl --fieldmap step6_evaluation/fieldmap_v1.yaml \
    --schema step0_rules/schema/v1.json --system-file <teacher system> --user-template-file <teacher user> \
    --provider openai --model gpt-6.1-sol --teacher-name sol --k 1 --out outputs/distill/reqs_sol.jsonl
python -m shared.frontier_api.batch run --job outputs/batches/sol --requests outputs/distill/reqs_sol.jsonl
```
Render the prompt files with `python -m step0_rules.prompts.render <template> --schema step0_rules/schema/v1.json`. Dry run without keys: add `--mock` to the batch command; mock outputs fail the gold checks, so it tests plumbing, not yield.
