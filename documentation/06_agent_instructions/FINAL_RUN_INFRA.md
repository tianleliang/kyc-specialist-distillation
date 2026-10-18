# Final-run infra: Sat 10/17 ~21:20 ET (Session M: adapter merge now; Session S: code only)

Read `CLAUDE.md`, `PIPELINE.md`, then this file. Decisions are Tianle's and are fixed (see "Design" below). Don't redesign; build exactly this.

## Design (decided)
Two final models, trained side by side, identical except for the PRE-CHECKS block:

| | Stage 3 (distill) | Stage 4 (post-train) | Prompt |
|---|---|---|---|
| **Final A** | adapted base + WINNER recipe file | + gold SFT (`data/sft/gold_train.jsonl`), 1 epoch | student_short |
| **Final B** | same, block added to every user prompt | same, block added | student_short + PRE-CHECKS block |

- Adapted base = `/vol/ckpt/merged/adapter-qwen35-4b` (Qwen3.5-4B + domain adapter, merged; built as step 0 of `launch_final.sh`).
- WINNER = one of `distill_floor_sol` / `distill_reject_sol` / `distill_arbitrate_splice` / `distill_arbitrate_plus_twins`. Tianle picks it from the dev table (~21:50). **Everything must work for any of the 4** (one setting).
- Halfway checkpoint: after stage 3, merge and score on dev **in parallel with stage 4** (separate GPU, must not delay stage 4). Gives the "+adapter" row and the "before" number for post-training.
- Training hyperparameters = the `distill_4b_*.yaml` ones (LoRA r16, lr 2e-4, 2 epochs, A100-80GB, seed 17), except stage 4: 1 epoch, lr 1e-4.

---

## Session M: adapter merge NOW (run FROM THE LAPTOP in D:\zorbe-kyc; GPU on Modal; ~$0.20, ~5–10 min)
A small separate local session. One job: fold the 4B domain adapter into Qwen3.5-4B so the final runs can start straight away. Don't edit any files.
```bash
cd /d/zorbe-kyc && git pull
export PYTHONUTF8=1 MSYS_NO_PATHCONV=1; set -a; . ./.env; set +a; mkdir -p outputs/logs
python -m modal run -m step5_training.merge --config step3_domain_adapter/configs/merge_adapter_4b.yaml > outputs/logs/merge_adapter_4b.log 2>&1
tail -15 outputs/logs/merge_adapter_4b.log
python -m modal volume ls zorbe-checkpoints /merged      # expect merged/adapter-qwen35-4b
```
- If it fails with "was modified during build", run the same merge command again (a failure costs $0). Any other error: stop and report.
- Report: did the merge check pass (generations/logits differ from base), and does `merged/adapter-qwen35-4b` exist. Then you're done.
- `launch_final.sh` step 0 skips the merge when that folder already exists.

---

## Session S: build the infra (LOCAL, free, ~40 min). Launch nothing on Modal.
**Work in a NEW worktree, not in D:\zorbe-kyc** (Session R is running jobs there, and Modal fails if uploaded files change mid-launch):
```bash
cd /d/zorbe-kyc && git fetch && git worktree add ../zorbe-kyc-final -b final-infra origin/main
cd ../zorbe-kyc-final && git merge --no-edit origin/precheck     # bring in step7_serving/prechecks.py (verified 100% on train/dev)
```
Build:
1. **`step4_distillation/add_prechecks.py`**: `--in <sft.jsonl> --out <sft_pc.jsonl>`. For each row: run `step7_serving.prechecks.run_prechecks` on the packet text from the user message, append `format_block(...)` after the packet, and add one sentence to the system message: the block is computed by code and is reliable for the arithmetic it reports; "n/d" means decide from the packet. **Assistant targets unchanged.** Put the shared logic in one function `apply_prechecks(messages) -> messages` (in `step7_serving/prechecks.py`) so training, eval and serving use byte-identical text. Write `.stats.json` (rows, blocks added, n/d counts). Run it on all 4 distill files + `gold_train.jsonl` → `data/sft/*_pc.jsonl`. Refuse eval ids (`refuse_eval_ids`).
2. **Eval with pre-checks:** add `--prechecks` to `step2_benchmarking/run_endpoint.py` (calls `apply_prechecks` on the messages before sending). Add an optional 4th arg `prechecks` to `step5_training/eval_on_dev.sh` that passes it through, and an env `SKIP_MERGE=1` that skips the merge if `/vol/ckpt/merged/$RUN` already exists.
3. **Serving:** `step7_serving/proxy.py`: env `ZORBE_PRECHECKS=1` → call `apply_prechecks` on the incoming messages. Default off. Add a test.
4. **Configs** `step5_training/configs/final_{A,B}_s3.yaml` and `final_{A,B}_s4.yaml`: s3 base = `/vol/ckpt/merged/adapter-qwen35-4b`, train_file = `WINNER` placeholder (A: plain file, B: `_pc` file). s4 base = `/vol/ckpt/merged/final-<A|B>-s3`, train_file = `gold_train.jsonl` / `gold_train_pc.jsonl`, 1 epoch, lr 1e-4. Confirm `sft.py` loads a base from a `/vol/ckpt/...` path (the volume is mounted); fix if not.
5. **`step5_training/launch_final.sh <winner>`**: **step 0:** if `/vol/ckpt/merged/adapter-qwen35-4b` doesn't exist (`modal volume ls`), run `python -m modal run -m step5_training.merge --config step3_domain_adapter/configs/merge_adapter_4b.yaml` (log to `outputs/logs/merge_adapter_4b.log`; stop the script if the merge check fails). Then fill the winner into the s3 configs, then for A and B **in parallel** (staggered 75 s, logs in `outputs/logs/`, NOT inside `step5_training/`):
   s3 SFT → merge s3 → { s4 SFT → merge s4 → `eval_on_dev.sh final-<X>-s4 …` }  **and in parallel**  { `SKIP_MERGE=1 eval_on_dev.sh final-<X>-s3 …` (halfway) }.
   B's evals use `prechecks`. Print one line per stage start/finish with the time.
6. **Tests + CPU dry-run:** `pytest -q`; `modal run ... --dry-run` style checks where they exist; run `add_prechecks.py` on 5 rows and show one before/after user message.
7. Commit on `final-infra`, push. **Don't merge to main** (Claudian merges after R's scoring finishes).

**Report (short):** what you built, test results, the before/after example, the exact launch command, and the expected wall-clock (stage 3 ~50–70 min depending on winner, stage 4 ~25 min).
