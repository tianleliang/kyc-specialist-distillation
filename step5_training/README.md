# step5_training — LoRA SFT, merge and DPO jobs on Modal, and the final-model launcher (pipeline stage 4 of the brief; also runs stage 3 training)

## What it does
- Trains 16-bit LoRA adapters with SFT (completion-only loss) on Modal GPUs, then merges and verifies them (`merge.py` fails if the merged model behaves like the base).
- `launch_final.sh` runs the whole final pipeline: adapted base → stage-3 distillation SFT → merge → stage-4 SFT on exact labels → merge, then scores each checkpoint on dev and on every frozen eval split.
- Runs a contamination gate before any upload: the eval manifest must verify and no eval case may appear in a training file.
- The final model B2 is `final-Brun2-s4` (configs `final_Brun2_s3.yaml` → `final_Brun2_s4.yaml`).

## Key files
| File | What it is |
|---|---|
| `sft.py`, `merge.py`, `dpo.py` | Modal jobs: SFT, merge + verify (+ optional HF push), DPO (built, not used in the final model) |
| `common.py`, `gpu.py`, `modal_infra.py` | Config + data checks + contamination gate (no torch); model loading; Modal images and volumes |
| `launch_final.sh`, `final_lib.sh` | Final pipeline launcher (A, B, or `ONLY=Brun2` = B2); resumable, one retry per stage |
| `eval_on_dev.sh`, `eval_frozen.sh` | Deploy a merged model on Modal, score dev / every frozen split via `run_endpoint.py`, stop the app |
| `configs/final_Brun2_s3.yaml`, `configs/final_Brun2_s4.yaml` | B2: stage 3 (2 epochs, lr 2e-4, `*_pc3` data) and stage 4 (1 epoch, lr 1e-4, `gold_train_solnarr_pc3.jsonl`); LoRA r16, A100-80GB |
| `configs/final_{A,B}_s{3,4}.yaml` | Earlier finals A (no pre-checks) and B (pre-checker v2) |
| `configs/distill_4b_*.yaml`, `configs/sft_gold_*.yaml` | Recipe comparison on plain Qwen3.5-4B (floor / reject / arbitrate / twins) and gold-label size sweeps |
| `launch_4b_batch.sh`, `eval_4b_batch.sh`, `score_dev.py` | Saturday 4B recipe batch: train the 4 recipes, score on dev, print the dev table |
| `cpu_smoke.py`, `toy/sft_toy.jsonl` | Offline CPU pre-flight (SFT → merge → DPO on a tiny random model); toy rows for a rehearsal |

## How to use
```bash
pip install -r requirements.txt -r requirements-f.txt
python -m step5_training.cpu_smoke                    # laptop, no GPU, ~1 min (needs torch, transformers>=5, trl, peft)

# one job (--dry-run = all local checks, no GPU)
modal run -m step5_training.sft --config step5_training/configs/sft.yaml --dry-run
modal run -m step5_training.sft --config <config>     # (Modal GPU, costs money)
modal run -m step5_training.merge --config <merge config>   # (Modal GPU, costs money)

# the final model B2, end to end: merge adapter (if missing) -> s3 -> s4 -> dev + frozen evals
SMOKE=1 ONLY=Brun2 bash step5_training/launch_final.sh distill_arbitrate_plus_twins   # tiny plumbing run (Modal GPU, costs money)
ONLY=Brun2 bash step5_training/launch_final.sh distill_arbitrate_plus_twins           # (Modal GPU, costs money; ~2 h 45, ~$8)

# score one merged model (Modal GPU, costs money)
SKIP_MERGE=1 bash step5_training/eval_on_dev.sh final-Brun2-s4 /vol/ckpt/merged/final-Brun2-s3 data/dev/cases.jsonl prechecks
bash step5_training/eval_frozen.sh final-Brun2-s4 prechecks
```
All launch scripts read `.env` (see `.env.example`) and need a Modal login and the `huggingface` secret. Without `ONLY=`, `launch_final.sh` runs A and B in parallel.

## Outputs / where results live
- Checkpoints: Modal volume `zorbe-checkpoints` (`/vol/ckpt/sft/<run>/adapter/`, `/vol/ckpt/merged/<run>/`, with `verify.json`). Each run writes `run.json` (gate report, sha256 of the training file, pip freeze).
- Local, git-ignored: `outputs/logs/`, `outputs/final/` (filled configs), `outputs/student/<run>__<split>/` (scores).
- Committed: `step5_training/results/dev_evals/` (dev predictions of the 4B recipe batch and gold sweeps), `step5_training/results/logs/` (training and merge logs), and every scored run in `results/runs/`.

## Reports and evidence
- [Evidence log §5 (dev size sweep), §5b (4B recipes, winner, stage 4 choice), §5c (frozen results, diagnosis)](../documentation/04_writeup/writeup_evidence_log.md)
- [Headline tables](../documentation/04_writeup/benchmark_report_submission.md) (Table 2 = gain per stage)
- [Session F report (how the jobs were built)](../documentation/05_progress_reports/overnight-F.md)
- Instructions: [TONIGHT_4B.md](../documentation/06_agent_instructions/TONIGHT_4B.md), [FINAL_RUN_INFRA.md](../documentation/06_agent_instructions/FINAL_RUN_INFRA.md), [FINAL_TONIGHT.md](../documentation/06_agent_instructions/FINAL_TONIGHT.md), [SUNDAY_BRUN2.md](../documentation/06_agent_instructions/SUNDAY_BRUN2.md)
- Logs: [`results/logs/`](results/logs/), adapter merge: [`results/logs/merge_adapter_4b.log`](results/logs/merge_adapter_4b.log)

## Details

### Data formats
- SFT: `{"id", "messages": [system, user, assistant]}`; the last (assistant) message is the target.
- DPO: `{"id", "prompt": [system, user], "chosen": str, "rejected": str}`.

### Guardrails built in
- **Contamination gate** (local, before upload): `eval_manifest` must verify, and `step6_evaluation/split_guard.py` must find no eval record inside any training file (exact, n-gram containment, MinHash). The report and file sha256 go into `run.json`.
- **Template parity**: examples are rendered with the model's own chat template and `enable_thinking=False`, the same as vLLM with `chat_template_kwargs={"enable_thinking": false}`.
- **Completion-only loss**, and a warning when examples exceed `max_seq_len` (truncation would cut the JSON target).
- **No QLoRA**: models load in 16-bit on both backends.
- **Merged weights, verified**: `merge.py` fails if the adapter's `lora_B` is all zero, or if the merged model (reloaded from disk, as vLLM loads it) gives the same greedy outputs and logits as the base. Evidence in `verify.json`.
- **GPU hygiene**: each function exits when done; Modal scales to zero. Eval scripts stop their app however they end.

### launch_final.sh stages
Step 0 merges the domain adapter into Qwen3.5-4B (`step3_domain_adapter/configs/merge_adapter_4b.yaml` → `/vol/ckpt/merged/adapter-qwen35-4b`) if missing. Then per pipeline: s3 SFT → merge s3 → {s4 SFT → merge s4 → dev eval → frozen eval} while the s3 checkpoint is scored in parallel (the "halfway" rows). Every stage is skipped if its output exists, so re-running continues after a failure. Logs go to `outputs/logs/` (not inside `step5_training/`: Modal uploads that folder at launch).

### Known risks (from the build; check on new versions)
- Package versions are floors only; pin from the `pip_freeze` in `run.json`.
- TRL 1.16's `DPOConfig` has no `max_prompt_length`; only `max_length` truncates.
- Merged Qwen3.5 checkpoints are text-only (`Qwen3_5ForCausalLM`); vLLM serves them fine.
