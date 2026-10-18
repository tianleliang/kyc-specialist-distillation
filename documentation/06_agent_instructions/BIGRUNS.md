# Big Runs: Sat 10/17 (Sessions T, F, Q). Local Claude Code desktop, in `D:\zorbe-kyc`

Read `CLAUDE.md` and `PIPELINE.md` first. These runs spend real money, so follow the commands exactly.

**Rules for all three sessions** (they share one working tree):
- **Do not switch branches, commit, or push.** Write only under `outputs/<your folder>/`. Claudian collects and commits the results.
- Run the **smoke command first** (`--limit 2`), check it says `schema-valid 2, errors 0`, then run the full commands.
- Every API response is cached on disk. If a run dies, re-run the same command: finished cases are free and only the rest get called.
- If errors exceed 5% of a run, or you see rate-limit storms (429), stop and report. Don't retry in a loop.
- Set `PYTHONUTF8=1` (and `MSYS_NO_PATHCONV=1` in Git Bash). Never print `.env`.
- Finish with a short report: each run's line (cases, schema-valid, errors, cost, time), total cost, and any problems.

---

## Session T: teacher answers (stage 3), ~$260, ~1–2 h
Teachers answer **training cases only** (never dev/eval) with the full policy + 2 worked examples (`--prompt teacher`). Their answers become the distillation training data.

```bash
# smoke
python -m step2_benchmarking.run_frontier --cases data/train/cases.jsonl --model gemini:gemini-4-argon --prompt teacher --limit 2 --run-id smoke_t --out-root outputs/smoke
# 1. Argon on train (3,000): main teacher
python -m step2_benchmarking.run_frontier --cases data/train/cases.jsonl --model gemini:gemini-4-argon --prompt teacher --workers 12 --run-id argon_train --out-root outputs/teachers
# 2. Sol on train (3,000): second teacher, for multi-teacher arbitration
python -m step2_benchmarking.run_frontier --cases data/train/cases.jsonl --model openai:gpt-6.1-sol --prompt teacher --workers 12 --run-id sol_train --out-root outputs/teachers
# 3. Argon on twins (1,000) and knockouts (300): inputs for the invented technique (one teacher is enough)
python -m step2_benchmarking.run_frontier --cases data/train_twins/cases.jsonl --model gemini:gemini-4-argon --prompt teacher --workers 12 --run-id argon_twins --out-root outputs/teachers
python -m step2_benchmarking.run_frontier --cases data/train_knockout/cases.jsonl --model gemini:gemini-4-argon --prompt teacher --workers 12 --run-id argon_knockout --out-root outputs/teachers
```
Run 1 and 2 **in parallel** (different providers), then 3. Gemini's account tier caps spend per 10 minutes. If Argon is throttled, lower `--workers` to 6 and let it run; don't retry in a loop.

## Session F: frontier benchmark (stage 1), ~$245, ~1 h
3 frontier models × 2 prompt conditions × 4 frozen eval sets (500 cases). Never edit anything under `data/eval*`.

```bash
# smoke
python -m step2_benchmarking.run_frontier --cases data/eval_id/cases.jsonl --model openai:gpt-6-astra --prompt baseline_zero_shot --limit 2 --run-id smoke_f --out-root outputs/smoke
# full: one run per model x prompt x eval set (24 runs). Providers can run in parallel; keep each provider's runs sequential.
for M in openai:gpt-6-astra anthropic:claude-opus-5-5 gemini:gemini-4-argon; do
  for P in baseline_zero_shot baseline_best; do
    for S in eval_id eval_ood_template eval_ood_hand eval_ood_llm; do
      python -m step2_benchmarking.run_frontier --cases data/$S/cases.jsonl --model $M --prompt $P --workers 8 \
        --run-id "$(echo $M | cut -d: -f2)__${P}__$S" --out-root outputs/bench_frontier
    done
  done
done
```
Use `--workers 4` for Anthropic.

## Session Q: open-model benchmark on Modal (stage 1), ~$10 GPU, ~1–1.5 h
Qwen3.5 **0.8B, 2B, 4B**, untrained, × zero-shot + best prompt, on the same 4 eval sets. Read `step7_serving/README.md` first: it has the deploy and stop commands and the gotchas.

For each size `Qwen/Qwen3.5-0.8B`, `Qwen/Qwen3.5-2B`, `Qwen/Qwen3.5-4B`:
1. Deploy with `ZORBE_SERVE_MODEL=<hf id>`, `ZORBE_SERVE_APP=zorbe-bench-<size>`, **`ZORBE_SERVE_MAX_LEN=24576`** (the best prompt is ~16k tokens), `ZORBE_SERVE_MIN=1` while running. Use an L4 (or A10/A100 if 4B doesn't fit 24k context on an L4; note it).
2. Run `python -m step2_benchmarking.run_endpoint` **against raw vLLM (not the proxy)** for `--prompt baseline_zero_shot` and `--prompt baseline_best`, with `--response-format schema` and the **`step0_rules/schema/v1_serving.json`** schema (`maxLength` stops decode loops), over all 4 eval sets. Output: `outputs/bench_open/<size>__<prompt>__<set>/`. Use `--warmup 2`. Best-prompt few-shot examples come from `data/train` (never eval).
3. **Stop the app** (`modal app stop zorbe-bench-<size>`) before the next size. At the end, confirm `modal container list` is empty.

**Fairness:** the prompts must be byte-identical to the frontier runs. `step2_benchmarking/run_frontier.py::build_prompt` uses schema descriptions off, the field guide replaced by one line, and examples from `data/train` with `seed=0`. If `run_endpoint.py` builds prompts differently, add a flag so it reuses `run_frontier.build_prompt`. That's the only code change allowed; add a test.

Expect low schema validity and accuracy on zero-shot. That's the honest "before" number; don't tune it.
