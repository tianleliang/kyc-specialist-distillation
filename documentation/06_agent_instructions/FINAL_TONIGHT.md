# Final runs tonight: Sat 10/17 ~22:15 ET (Sessions R, V). Local Claude Code desktop

Read `CLAUDE.md`, `PIPELINE.md`, `documentation/04_writeup/writeup_evidence_log.md` §5b, then this file. Decisions are Tianle's and fixed. Build exactly this; don't redesign.
**Winner recipe: `distill_arbitrate_plus_twins` (Counterfactual Twin Distillation).**

**Rules for all sessions**
- Session R runs in `D:\zorbe-kyc` (main, has `.env` + Modal login). Session V works ONLY in a new worktree `D:\zorbe-kyc-v2`.
- **While any Modal job launched from `D:\zorbe-kyc` is running, nobody edits files there** (Modal uploads the code at each stage launch; a changed file crashes it).
- `PYTHONUTF8=1`, `MSYS_NO_PATHCONV=1`. Never print `.env`. Never open or read anything under `data/eval*` except through the existing scoring commands.
- On error: stop and report. Don't retry in loops (the scripts' own single retries are fine).

Order: **① R smoke** and **② V build** run at the same time → Claudian reviews and merges V → **③ R real launch**.

---

## ① Session R: smoke test (FROM THE LAPTOP; GPUs on Modal; ~$2, ~20–25 min)
Runs the whole final chain on a tiny scale (128 rows, 1 epoch, 10 dev cases, run names `*-smoke`) to prove the plumbing before the 2.5 h launch.
```bash
cd /d/zorbe-kyc && git pull
SMOKE=1 bash step5_training/launch_final.sh distill_arbitrate_plus_twins
```
Pass = the last line says `A rc=0, B rc=0`, and `outputs/student/final-{A,B}-s{3,4}-smoke__smoke/predictions.jsonl` each have 10 lines.
Report: pass/fail, each stage's start/finish time (from `outputs/logs/launch_final.log`), and `python -m modal app list` showing no `zorbe-final-*` app left.
If a stage fails: paste the last 30 lines of that stage's log. Don't fix code in `D:\zorbe-kyc`.

---

## ② Session V: pre-checker v2 + stage-4 file + frozen eval + resume (LOCAL, free, ~45 min). Launch nothing on Modal.
```bash
cd /d/zorbe-kyc && git fetch && git worktree add ../zorbe-kyc-v2 -b final-v2 origin/main && cd ../zorbe-kyc-v2
```

### V1. Pre-checker v2: policy §3 classification (the most important item)
Why: twins' dev errors are mostly OCR-vs-tamper. v1 says "MRZ invalid" for both *ambiguous* (→ escalate) and *clear tamper* (→ reject), so it can't separate them. Policy `step0_rules/policy_v1.md` §3 decides it with a fixed rule; compute that rule.
- In `step7_serving/prechecks.py`, per field (date of birth, document number, expiry): compare the **visual zone** value with the **MRZ** value and its check digit, and output the §3 class exactly as the policy table defines it: readable OCR noise (repaired, consistent) / **ambiguous: OCR or tamper** (exactly one look-alike digit pair, check digit fails) / **clear tamper** (MRZ passes but visual zone differs; same value but check fails and no repair fixes it; any other difference with a failing check) / **impossible date** (§2.2 step 2). Use the policy's glyph and digit-pair lists verbatim; reuse `step1_data_generation.lib` helpers where they take only packet-derived values.
- Render it in the block, one line per field, e.g. `- Document number: visual zone X1234567 vs MRZ X1234561, one look-alike digit pair, check digit FAIL -> AMBIGUOUS (OCR or tamper)`. Add one overall line: `- Document integrity (policy §3): clear tamper | ambiguous | noise only | consistent | n/d`.
- Reads **packet text only** (never truth / expected). Conservative: if a value can't be read with confidence → `n/d`. Never guess.
- **Verify on train + dev only** (extend `step7_serving/precheck_eval.py`): computed class per field vs the gold identity finding reason code (`all_sources_agree` / `ocr_confusable_resolved` / `ocr_or_tamper_ambiguous` / `viz_mrz_disagree` / `check_digit_failed` / `impossible_date`), and the overall class vs gold. **Target: 0 wrong when determinable (100.00%), n/d ≤ 5%.** Save `step7_serving/results/precheck_v2_eval_train_dev.{md,json}`. If you can't reach 0 wrong, report the confusions; don't ship a wrong rule.
- Check: on the 14 dev cases twins got wrong (`step5_training/results/dev_evals/distill-4b-twins__dev/predictions.jsonl` vs `data/dev/cases.jsonl`), print the v2 integrity line next to the gold decision. Report how many errors the block now resolves (states the deciding fact).

### V2. Stage-4 training file: gold decisions + Sol narratives
- New `step4_distillation/gold_with_teacher_narrative.py`: for each row of `data/sft/gold_train.jsonl`, parse the gold target; if the Sol answer for the same `case_id` (assistant target in `data/sft/distill_floor_sol.jsonl`) parses and has the **same decision and risk_tier**, replace only `narrative` with Sol's; otherwise keep gold's. Re-serialize with `dump_json` (schema key order). Write `data/sft/gold_train_solnarr.jsonl` + `.stats.json` (rows, narratives replaced, kept).
- Point `step5_training/configs/final_A_s4.yaml` at `gold_train_solnarr.jsonl`.

### V3. Rebuild all `_pc` files with the v2 block
`python -m step4_distillation.add_prechecks --all` (or equivalent), so every `*_pc.jsonl`, including a new `gold_train_solnarr_pc.jsonl`, carries the v2 block. Assistant targets unchanged (check the stats). Point `final_B_s4.yaml` at `gold_train_solnarr_pc.jsonl`. Show one before/after user message for an ambiguous case.

### V4. Frozen eval, automatic at the end of each pipeline
- New `step5_training/eval_frozen.sh <run> [prechecks]`: deploy `/vol/ckpt/merged/<run>` **once**, score each frozen file with exactly the dev flags (`--prompt student_short --schema step0_rules/schema/v1_serving.json --warmup 2 --concurrency 16`, plus `--prechecks` for B): `data/eval_id`, `data/eval_ood_template`, `data/eval_ood_hand`, `data/eval_ood_llm`, `data/eval_hard` (`cases.jsonl` in each) → `outputs/student/<run>__<split>/`. Stop the app on any exit (trap), like `eval_on_dev.sh`.
- In `launch_final.sh`: after each **s4** dev eval → `eval_frozen.sh final-<X>-s4`; after each **s3** halfway dev eval → `eval_frozen.sh final-<X>-s3` (parallel to s4; gives the Table 2 stage rows on the frozen set). In SMOKE mode, frozen = first 5 cases of `eval_id` only.
- These run once per model; nothing is tuned after them.

### V5. Robustness for an unattended 2.5 h run
- **Resume:** each stage skips if its output already exists (SFT: `/vol/ckpt/sft/<run>/adapter/adapter_config.json`; merge: `/vol/ckpt/merged/<run>/config.json`; eval: predictions file with the full case count). Re-running the same command after a failure continues where it stopped.
- **One retry per stage** after 60 s on failure (transient Modal / network errors), then give up and report.
- Keep logs in `outputs/logs/`. Keep the 75 s stagger between new app launches.

### V6. Tests + report
`pytest -q` all green; `bash -n` on the scripts; a local simulation of the config fill for SMOKE and real mode. Commit on `final-v2`, push. **Don't merge to main.**
Report: V1 accuracy table + the 14-error check, V2 stats, V3 example, files changed, and the exact real-launch command.

---

## ③ Session R: real launch (after Claudian merges V; FROM THE LAPTOP; ~$12, ~2.5 h). Laptop stays on, plugged in, awake.
```bash
cd /d/zorbe-kyc && git pull
bash step5_training/launch_final.sh distill_arbitrate_plus_twins
```
### What this one command does (verified locally by Claudian, 22:58: configs, data, row counts, contamination gate 0)
Step 0: adapted base `/vol/ckpt/merged/adapter-qwen35-4b` already exists (Qwen3.5-4B + domain adapter, merged 21:30) → skipped.
Then **Final A** and **Final B** run side by side (B starts 75 s later). Same base, same recipe, same settings; the only difference is the PRE-CHECKS block.

| Stage | Final A (model alone) | Final B (model + pre-checks) |
|---|---|---|
| s3 distillation (stage 3) | adapted base + `distill_arbitrate_plus_twins.jsonl` (3,934 rows: 2,954 arbitrated Sol/Argon + 980 Counterfactual Twins), 2 epochs, lr 2e-4 → `final-A-s3` | same rows + v2 PRE-CHECKS block in every prompt (`_pc`, 3,934/3,934 blocks) → `final-B-s3` |
| merge s3 | → `/vol/ckpt/merged/final-A-s3` | → `/vol/ckpt/merged/final-B-s3` |
| halfway score (own GPU, parallel to s4) | dev 150 + 5 frozen sets, no block | dev 150 + 5 frozen sets, with block |
| s4 post-train (stage 4) | on merged s3: `gold_train_solnarr.jsonl` (3,000: gold decisions/fields + Sol narratives), 1 epoch, lr 1e-4 → `final-A-s4` | same + block (`gold_train_solnarr_pc.jsonl`, 3,000/3,000) → `final-B-s4` |
| merge s4 | → `/vol/ckpt/merged/final-A-s4` = **Final A** | → `/vol/ckpt/merged/final-B-s4` = **Final B** |
| final score | dev 150 + 5 frozen sets (eval_id 300, OOD template 50 / hand 50 / LLM 100, eval_hard 150), no block | same sets, with block |

Frozen sets are scored **once per model**; nothing is tuned afterwards. Every scoring app stops itself. Outputs: `outputs/student/final-<A|B>-s<3|4>__<dev|split>/`. Expected: s3 ~75 min, s4 ~30 min, scoring ~45 min → done ~2.5 h after launch.

Then hands off. Status any time: `tail -20 outputs/logs/launch_final.log` and `python -m modal app list`. If it stops with a failure: re-run the same command (it resumes).
