# Sunday 10/18 ~12:30: B-run2 (Final B pipeline, run 2) retrain + frontier on eval_id v2 (Session R, laptop)

Read `CLAUDE.md`, then this file. Prepared and checked by Claudian (12:30): configs, data, contamination, tokens, tests (486 pass).

## What this is
- **B-run2** (run ids `final-Brun2-s3` / `final-Brun2-s4`, configs `final_Brun2_s{3,4}.yaml`) = the Final B recipe retrained with **pre-checker reader v3** (`frozen/reader-v3` @ a6e09f7, merged into main): adapted base → twins distillation (stage 3) → gold + Sol-narrative post-train (stage 4), every training prompt carries the v3 PRE-CHECKS block, **25% of rows get an all-n/d block** (seeded by case id) so the model learns to fall back when the reader can't read a packet.
  - s3: `data/sft/distill_arbitrate_plus_twins_pc3.jsonl` (3,934 rows, 989 blank), 2 epochs, lr 2e-4 → `final-Brun2-s3`
  - s4: `data/sft/gold_train_solnarr_pc3.jsonl` (3,000 rows, 762 blank), 1 epoch, lr 1e-4 → `final-Brun2-s4`
  - contamination gate 0; longest prompt 2,557 tokens.
- Scoring (automatic, once per model): dev + frozen v1 (eval_id, OOD template / hand / LLM, hard) + **eval_id v2** (`data/eval_id_v2`, 300 cases, seed 3050000, same generator + 6 styles, frozen in `data/eval_v2/MANIFEST.json`, 0 overlap with training). Frozen v1 numbers for B-run2 are labelled "after diagnosis"; eval_id v2 is the clean in-distribution test.
- A and Final B are not touched.

## ① Launch B-run2 (FROM THE LAPTOP in <repo>; GPUs on Modal; ~$8, ~2 h 45)
Laptop plugged in, `powercfg /change standby-timeout-ac 0`, lid open, Claude Desktop open.
```bash
cd <repo> && git pull
ONLY=Brun2 nohup bash step5_training/launch_final.sh distill_arbitrate_plus_twins > outputs/logs/launch_final_Brun2.log 2>&1 &
```
After ~3 min: `tail -8 outputs/logs/launch_final.log` must show the `ok final-Brun2-s3/s4 … gate 0` lines and `[Brun2] s3 SFT START`; `python -m modal app list` shows 1 `zorbe-sft` running.
**Nobody edits files in <repo> while it runs.**

## ② Frontier on eval_id v2 (laptop; API; Argon ~$11, + Opus ~$33, + Astra ~$52)
Same prompt and flags as the original benchmark, so the rows are comparable. Argon is required (it's the model we compare to); Opus/Astra complete the panel if Tianle approves the spend.
```bash
cd <repo>
M=gemini:gemini-4-argon; python -m step2_benchmarking.run_frontier --cases data/eval_id_v2/cases.jsonl --model $M --prompt baseline_best --workers 4 \
  --run-id "$(echo $M | cut -d: -f2)__baseline_best__eval_id_v2" --out-root outputs/bench_frontier
# optional, same command with: M=anthropic:claude-opus-5-5 (workers 4) ; M=openai:gpt-6-astra (workers 8)
```
Writes only under `outputs/` (not uploaded by Modal), so it's safe while ① runs. Report cases / schema-valid / errors / cost.

## Timeline
| ET | stage |
|---|---|
| 12:35 | launch |
| ~13:55 | s3 done (B runs ~10 s/step × 492) → merge |
| ~14:05 | halfway dev + frozen + v2 scoring (parallel) · s4 starts |
| ~14:40 | s4 done → merge → final dev + frozen + v2 scoring |
| **~15:20** | all scores in |
Then: reader v3.1 swap scoring (if v3.1 passed its gate), unsupported-claims judge for B-run2 (~$5), ship decision, deploy.

---

## ③ Reader swap: score B-run2 with reader v3.1 at serving (laptop; ~$4, ~35 min)
Worktree `<repo>-r31` (branch `reader-swap`) = main + `step7_serving/prechecks.py` from `frozen/reader-v3.1` @ 342d0d3. Block format verified identical to v3 (line structure on 450 packets, header, system note). Script `step5_training/eval_reader_swap.sh <merged_run> <tag>`: deploys the merged model under its own app name, scores dev + 5 frozen v1 sets + eval_id_v2 with `--prechecks` (same flags as all other evals), stops the app on exit. Outputs `outputs/student/<run>-r31__<split>/` in the r31 worktree. No retraining.
```bash
cd <repo>-r31 && git pull && nohup bash step5_training/eval_reader_swap.sh final-Brun2-s3 r31 > outputs/logs/swap_s3.log 2>&1 &
sleep 75; cd <repo>-r31 && nohup bash step5_training/eval_reader_swap.sh final-Brun2-s4 r31 > outputs/logs/swap_s4.log 2>&1 &
```
Check: `tail -3 outputs/logs/swap_s3.log outputs/logs/swap_s4.log` (in the r31 worktree).

## ④ Unsupported-claims judge for B-run2 (Anthropic; ~$5–10, cap $15)
Session J's runner, in its worktree; judges only sentences no earlier run wrote, same v2 prompt; other rows untouched.
```bash
cd <repo>-judge && python -m step6_evaluation.judge_claims <repo>/outputs/student/final-Brun2-s3__eval_id <repo>/outputs/student/final-Brun2-s4__eval_id --max-usd 15
```
Report cost + unsupported rate for both runs.

---

## Ship decision (Tianle, ~16:55): **B-run2 final (`final-Brun2-s4`), served with reader v3** (the reader it was trained with)
Reader v3.1 swapped in at serving gave the same scores (B-run2 halfway: identical on every set except eval_id v2 +1 case; final: identical except hand-written OOD +1 case; 19 transient "response is not JSON" serving errors in one v3.1 run, not a reader effect). So v3.1 is safe to swap but buys nothing measurable on our sets → ship v3 (fewer moving parts, matches training).

## ⑤ Deploy the hand-over endpoint (laptop, <repo>; ~$0.80/h while up, ~$19/day)
```bash
cd <repo> && git pull
bash step7_serving/deploy_endpoint.sh final-Brun2-s4 --dry-run   # local parity check: same request as the frozen evals, 401 without token
bash step7_serving/deploy_endpoint.sh final-Brun2-s4             # prints URL, model name, GPU, next commands
```
Then a smoke `curl` with and without the token (the script prints both). Report the proxy URL (not the token).

## ⑥ Latency + cost (laptop; ~25 min, dev cases only, concurrency 1, warm)
```bash
python -m step7_serving.measure_latency --base-url <proxy URL from ⑤>/v1 --name final-Brun2-s4 --n 100 --compare results/runs/final-Brun2-s4__dev
```
Report p50 / p95 / cost per 1k / decision agreement with the saved dev run (should be ~100%).

## ⑦ Weights to Hugging Face (runs on Modal; public repo)
```bash
python -m modal run -m step7_serving.upload_hf --run final-Brun2-s4 --repo tianle-terrence-liang/zorbe-kyc-specialist-4b --dry-run
python -m modal run -m step7_serving.upload_hf --run final-Brun2-s4 --repo tianle-terrence-liang/zorbe-kyc-specialist-4b
```
Report the URL; check it opens in a private/incognito window (no login).

## ⑧ Faster-GPU latency sample: H100 (laptop; ~$1–2, ~20 min). NOT the hand-over endpoint (that stays on the L4)
A temporary second endpoint, same model, same proxy + pre-checks, only the GPU differs. Can run while ⑥ is still measuring the L4 (separate app, separate containers).
```bash
cd <repo> && git pull
ZORBE_SERVE_GPU=H100 ZORBE_ENDPOINT_APP=zorbe-lat-h100 bash step7_serving/deploy_endpoint.sh final-Brun2-s4
python -m step7_serving.measure_latency --base-url <proxy URL printed above>/v1 --name final-Brun2-s4-h100 --n 30 \
  --gpu H100 --gpu-usd-per-hour 3.95 --compare results/runs/final-Brun2-s4__dev
python -m modal app stop zorbe-lat-h100 --yes          # ALWAYS stop it after: it keeps an H100 warm (~$4/h)
python -m modal app list                               # confirm zorbe-lat-h100 is stopped; zorbe-kyc-final-brun2-s4 (L4) stays up
```
Report p50 / p95 / cost per 1k / agreement with the saved dev run, and confirm the H100 app is stopped.

---

## ⑨ Headline on eval_id v2 for every Table 1/2 row (Tianle, ~18:15): open baselines + A halfway on v2, then judge v2
Table 1 and Table 2 move to the fresh eval_id v2 (in-distribution = the headline). Frontier best-prompt and B2 are already scored on it; this adds the rest with the original flags.
```bash
cd <repo> && git pull
bash step2_benchmarking/bench_open_v2.sh        # ~25 min, ~$2: Qwen 0.8B/2B/4B best (+4B zero-shot) and final-A-s3 on eval_id v2; apps stop themselves
```
Then the unsupported-claims judge on eval_id v2 (Anthropic, cap $30):
```bash
cd <repo>-judge && git pull origin main
python -m step6_evaluation.judge_claims <repo>/outputs/bench_frontier/*__baseline_best__eval_id_v2 \
  <repo>/outputs/bench_open/*__eval_id_v2 <repo>/outputs/student/final-A-s3__eval_id_v2 \
  <repo>/outputs/student/final-Brun2-s3__eval_id_v2 <repo>/outputs/student/final-Brun2-s4__eval_id_v2 \
  --gold data/eval_id_v2/cases.jsonl --out results/judge/eval_id_v2 --max-usd 30
```
Report cost and per-run unsupported rate.
