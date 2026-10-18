# Tonight Sat 10/17 ~20:15 ET: 4B adapter check + distillation (Sessions R, P). Local Claude Code desktop

**Session R must be a LOCAL Claude Code session (or Git Bash) on the laptop: it needs `.env` and the Modal login, which only exist there. A cloud session cannot launch these.**

Read `CLAUDE.md` and `PIPELINE.md` first. Size is settled: **4B only** (2B is dropped).
Order: ① and ② start together. ③ starts only after all 4 trainings in ① have finished.

**Rules for all sessions**
- **Session R works in `D:\zorbe-kyc` (main). Session P works only in `D:\zorbe-kyc-precheck` (branch `precheck`).** Never both in one folder.
- Run the scripts exactly as written. Don't edit configs, don't retry in a loop. On error: stop and report.
- Set `PYTHONUTF8=1` and `MSYS_NO_PATHCONV=1`. Never print `.env`.
- Stopping a local `modal run` does NOT stop Modal. Check with `python -m modal app list`; stop with `python -m modal app stop <app> --yes`.
- Finish each step with a short report: what ran, finished or error, numbers, time.

---

## ①b RELAUNCH (20:15): first run of ① hit a log-location bug. Do this instead of ①:
```bash
python -m modal app list          # stop every running zorbe-sft app: python -m modal app stop <app-id> --yes
git pull
NO_ADAPTER=1 bash step5_training/launch_4b_batch.sh   # 4 trainings only; adapter already done
python -m modal app list          # expect 4 zorbe-sft running
```

## ① Session R: launch (run FROM THE LAPTOP in D:\zorbe-kyc; GPUs run on Modal; costs money, ~$12, ~45–60 min)
5 jobs: adapter check (base 4B vs 4B + domain adapter) and 4 distillation trainings on Qwen3.5-4B (floor / reject / arbitrate / arbitrate+twins), staggered 75 s.
```bash
cd /d/zorbe-kyc && git pull
bash step5_training/launch_4b_batch.sh        # returns after ~6 min; jobs keep running on Modal
python -m modal app list                      # expect 5 running
```
Status check (any time):
```bash
python -m modal app list
tail -3 outputs/logs/*4b*.log
```
Adapter result: DONE 20:13, MOVED (ppl 7.39->5.52, probe 61%->65%); saved in `step5_training/results/logs/adapter_4b_measure.log` (before/after table + verdict "moved / didn't move").

## ② Session P: finish the pre-checker (LOCAL, free)
In `D:\zorbe-kyc-precheck` only. Finish `step7_serving/prechecks.py` (MRZ check digits, expiry vs as-of, PoA age). Run `step7_serving/precheck_eval.py` on train and dev. **Target ≥99% correct per check.** Commit and push to `precheck`. **Don't merge.** Report the accuracy table.

## ③ Session R: score on dev (run FROM THE LAPTOP; GPUs on Modal; costs money, ~$5, ~20 min). Only after all 4 trainings finished
Merge + serve + score each run on the 150 dev cases; each app is stopped at the end.
```bash
bash step5_training/eval_4b_batch.sh
python step5_training/score_dev.py            # paste this table to Tianle
python -m modal app list                      # confirm NO zorbe-distill-* app is still deployed (min_containers=1 burns money)
```
Then commit the logs and dev predictions summary to main and push. Tianle picks the recipe for the final post-train.
