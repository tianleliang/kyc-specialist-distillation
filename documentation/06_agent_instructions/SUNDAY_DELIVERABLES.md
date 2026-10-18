# Sunday 10/18: deliverables (Session D, local, free) + claims judge (Session J, local, API ~$20–40)

Read `CLAUDE.md`, `PIPELINE.md`, `documentation/04_writeup/writeup_evidence_log.md` (§5b + §6/§7), the brief's deliverables (`documentation/00_case_brief_and_plan/`), then this file.

## Situation
Modeling is done except one pending row: **B-v3** (pre-checker reader v3 + retrain, results ~13:30 ET). Everything else is final and saved under `D:\zorbe-kyc\outputs\` (git-ignored, so **not in the repo yet**). Submission ~21:00 ET. Graders check that the repo contains: the schema, data generation, training, eval harness, serving code, **one command that rebuilds the evaluation tables from saved outputs**, and **one command that regenerates the eval set**, and that both run from a clean clone. Table 1 must show every metric of the brief for every model on the same held-out set; Table 2 the gain per pipeline stage. Missing any of this loses points we already earned.

## Rules (both sessions)
- **Work in your own worktree**, never in `D:\zorbe-kyc` (GPU jobs launch from there; changed files there crash a Modal launch). Read from `D:\zorbe-kyc\outputs\` (read-only) is fine.
  - D: `cd /d/zorbe-kyc && git fetch && git worktree add ../zorbe-kyc-deliv -b deliverables origin/main`
  - J: `cd /d/zorbe-kyc && git fetch && git worktree add ../zorbe-kyc-judge -b judge origin/main && cp .env ../zorbe-kyc-judge/.env` (`.env` is git-ignored; never print or commit it)
- **No retraining, no relabeling, no tuning on eval.** You only package, score and document what exists. Never edit predictions.
- Launch nothing on Modal. Session J spends API money: cap **$50**, stop and report if the estimate exceeds it.
- `PYTHONUTF8=1`, `MSYS_NO_PATHCONV=1`. Commit on your branch, push, don't merge to `main`.

---

## Session D: repo deliverables + Tables 1/2 draft (branch `deliverables`)
### D1. Saved outputs into the repo
Copy every run that feeds a table into a committed folder `results/runs/<run_id>/` (only `predictions.jsonl` + `endpoint_run.json`/provenance + a new `run.json`; no caches, no logs with secrets). Runs:
- frontier + open baselines, zero-shot and best prompt, on `eval_id`, `eval_ood_template`, `eval_ood_hand`, `eval_ood_llm`, and the hard set (find them under `outputs/bench_frontier`, `outputs/bench_open`, and wherever the eval_hard benchmark was saved; also check what commit `5c87816` already saved);
- our models: `final-A-s3`, `final-A-s4`, `final-B-s3`, `final-B-s4` on dev + every frozen split (`outputs/student/`);
- dev-only ablation runs: `step5_training/results/dev_evals/*` (gold SFT sizes, distill floor/reject/arbitrate/twins).
Write each `run.json` per `step6_evaluation/report.py` (`model`, `params`, `price_key`, `gold`, `table1_order`, `pipeline`/`stage`/`stage_order`/`compare_to`). Check size (<150 MB total) and that no file contains a key.

### D2. One command each
- `bash make_tables.sh` → runs `python -m step6_evaluation.report results/runs …` and writes `documentation/04_writeup/benchmark_report.md`. Byte-identical on rerun.
- `bash regenerate_eval.sh` → rebuilds every frozen eval split with its recorded seed/config (`build.py --allow-eval` into a scratch dir, never over `data/`) and verifies against the manifests (`split_guard verify`). The LLM OOD set: rebuild from its cache if deterministic, otherwise document that it's regenerated from the cached LLM responses; the hand set is a static file (say so).
- Mention both in `README.md` (top, "Reproduce").

### D3. Benchmark report draft
- **Table 1 (frozen eval v1: eval_id + 3 OOD = 500, plus hard 150 as its own column/table):** rows = 3 frontier × {zero-shot, best}, 3 open Qwen sizes × {zero-shot, best}, Final A, **Final B (shipped candidate, pre-diagnosis)**, and a **placeholder row "B-v3 (after diagnosis)"**. Columns = every brief metric: decision accuracy, screening macro-F1, field accuracy per identity field, risk tier exact + within one, required actions recall **and precision**, unsupported claims (from Session J; placeholder until then), schema validity, adversarial escalation rate (injection + insufficient evidence), p50/p95 latency, cost per 1k, parameter count, **case counts**. Latency/cost cells for our model: placeholder (measured at deploy). Confirm `report.py` computes each column; add any that's missing (metrics only, no API).
- **Table 2 (stage gains):** (a) dev, plain 4B: gold-only control → floor → +rejection → +arbitration → +Counterfactual Twin Distillation; (b) frozen v1: open Qwen 4B best prompt → A halfway (+adapter +twins) → A final (+post-train) and → B halfway (+pre-checks v2) → B final (+post-train); placeholders for B-v3 rows. Bootstrap CIs as `report.py` does.
- Leave a clearly marked section "Fresh eval_id v2 (generated Sun, untouched): B-v3 vs Argon": placeholder.

### D4. Clean-clone test
`git clone` the `deliverables` branch into a temp dir, `pip install -r requirements.txt`, run `bash make_tables.sh` (must reproduce the committed report byte for byte) and `bash regenerate_eval.sh` (must verify). Report what failed and fix it.

### D5. Endpoint readiness (prepare only, deploy nothing)
Read `step7_serving/` (`modal_vllm.py`, `proxy.py`). Confirm there's a way to deploy the **proxy as a Modal web endpoint** in front of vLLM, with `ZORBE_PRECHECKS=1`, the bearer token, the student system prompt injection, and `response_format` schema. If any piece is missing, write it. Write `step7_serving/deploy_endpoint.sh <merged_run>` (vLLM always warm `min_containers=1` + proxy; prints URL, model name, GPU) and `step7_serving/measure_latency.py` (concurrency 1, warm, 100 **dev** cases, p50/p95, cost per 1k from the GPU price; `curl` example with and without token). Dry-run what can run locally; deploy nothing.

**Report:** files added, table draft (pasted), clean-clone result, endpoint readiness + the exact deploy/measure commands, anything missing.

---

## Session J: unsupported-claims judge (branch `judge`)
**What it is:** the brief's metric "unsupported claims = narrative sentences not grounded in the packet". Today `metrics.py` only checks `evidence_refs` programmatically. J runs the LLM judge (`step0_rules/prompts/judge_unsupported_claims.md`, Claude **Sonnet**, judging only, never a teacher) blind: for each case, pool the narrative sentences from **all** Table 1 runs, shuffle, hide the source, one judge call per packet.
- Scope: **`eval_id` (300 cases)** for every Table 1 run (frontier × 2, open × 2 sizes … whatever has narratives, Final A, Final B). Hard/OOD sets: not judged (state it in the report; cost).
- Build or reuse a runner (look for `judge_items` in `step0_rules/prompts/render.py` and the clients/cache/cost ledger in `shared/frontier_api/`). Validate judge output against the prompt's schema; retry once on invalid; log cost.
- **Smoke first:** 3 packets, print verdicts for a few sentences and the cost per call; estimate the full run; stop if > $50.
- Output `results/judge/eval_id/verdicts.jsonl` + per-run `unsupported_rate` (+ count of sentences judged), plugged into `report.py` as the Table 1 "Unsupported claims" column (keep the programmatic number as a second column).
- Design it so **B-v3 can be added later** (judge only its sentences, same prompt, ~$5) without re-judging the others.
- Spot-check 10 verdicts by hand (5 supported, 5 unsupported) and report agreement.

**Report:** cost, per-run unsupported rate table, the spot-check, the command to add B-v3 later.
