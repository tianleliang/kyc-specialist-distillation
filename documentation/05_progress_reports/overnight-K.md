# Overnight report: Session K (distillation data pipeline)

Branch: `claude/keen-mccarthy-f4kwk7`. The environment forced this branch name, so it can't be `overnight-k`. Files: `step4_distillation/` and `tests/k_distill_test.py` only. No other session's files were touched.

## Done

Every step is a schema-agnostic CLI that reads JSONL and writes JSONL. It is driven by the same `FieldMap` YAML as `step6_evaluation/metrics.py`, and each step writes `<out>.stats.json` with the counts kept and dropped per reason. The checks reuse `step6_evaluation.metrics.score_case`, so "passes the checks" means the same thing as the eval metrics. Everything was tested with mock teachers and students only. No API calls were made.

| # | Task | File | Notes |
|---|---|---|---|
| 1 | SFT floor | `step4_distillation/sft_floor.py` | No filtering. Only rows that can't become an example are dropped (API error, empty output, case not in gold). Invalid outputs are kept and counted. `--samples first` is S2's "one sample per case". `--from-gold` gives the gold-label SFT control (D's Q-DS1) |
| 2 | Rejection sampling | `step4_distillation/reject_sample.py` | Checks: schema, decision, risk tier, every disposition, identity fields ≥ `--min-field-acc`, `evidence_refs`, plus optional `--actions superset\|exact` and no invented hits. Best of k, ranked by closeness to gold, then teacher priority, then shortest. Stats: failure reasons, pass rate per teacher, **case drop rate per tag**. `--rejects-out` feeds the label audit and DPO |
| 3 | Multi-teacher arbitration | `step4_distillation/arbitrate.py` | `gold_select`, `vote` (field-wise majority, no gold) and `splice` (field-wise best-of against gold, unit = the object that owns a label, narrative from a fully grounded teacher that agrees with the spliced decision, re-validated and re-checked). Agreement report: pairwise and all-agree rates per unit kind, and each teacher vs gold. Also lists **label-audit cases**, where all teachers agree with each other but not with gold |
| 4 | Hard-case mining | `step4_distillation/hard_mine.py` | Ranks failure categories by the Wilson lower bound. Categories come from J's knob vector (`--knob-key knobs`, flattened, numeric knobs split into terciles), or from `scenarios` if there is no knob vector. Outputs a `mix:` YAML for `step1_data_generation/build.py` (base = `step1_data_generation.sample.DEFAULT_MIX`, sharpness `--alpha`, `--floor` so nothing drops to zero) plus `knob_targets` and a markdown table. Refuses eval ids and frozen eval files |
| 5 | DPO pairs | `step4_distillation/prefs.py` | `programmatic`: chosen = the best gold-passing teacher or corrected output; rejected = the student's failing output (a near-miss by default). `judge` stub: blind A/B, order randomized per case, then re-asked with the order swapped; only position-consistent verdicts are kept. Runs through `LLMClient` (mock in tests) |
| 6 | On-policy loop | `step4_distillation/onpolicy.py` | `requests` → `run` (live) or `shared.frontier_api.batch` → `collect`, or `loop` for all three. The teacher sees the packet, the student output and the *names* of the failed checks, never gold values (unless `--reveal-gold`). Corrections are re-checked; SFT records plus DPO pairs. `EvalGuard` is attached automatically when a manifest exists |
| 7 | README | `step4_distillation/README.md` | Table 2 row → file mapping, every switch that encodes a choice, the Saturday/Sunday command sequence |
| + | Contamination gate | `step4_distillation/common.py: write_training_file` | Every training-file writer goes through it. It writes to a temp file, runs `split_guard.verify` and `check_overlap` against every frozen eval manifest (`--eval-manifest`, or auto-discovered `data/eval*/MANIFEST.json`), and moves the file into place only if both are clean. Before eval is frozen, the check is skipped and the stats file says so. Eval case-id prefixes (`eid-`, `ood-`, `eval-`) are refused everywhere |
| + | Extras the sequence needed | `teacher_requests.py`, `matched_n.py`, `twins_filter.py` | Cases → teacher `LLMRequest` JSONL (k distinct samples, metadata the steps read back, gated because `shared.frontier_api.batch` has no guard). Size-matched controls for S3–S5. The twins pair filter: keep a pair only if both twins pass; twin hard negatives for DPO; teacher flip consistency |

Input formats accepted everywhere: `shared/frontier_api/batch.py` result rows, eval-style `{case_id, output}` predictions, and distill's own SFT files. So `reject_sample` output can be the `--chosen` input to `prefs`.

## Not done
- **step1_data_generation/build.py, the knob vectors and `step1_data_generation/twins.py` (Session J) weren't on any branch when I finished.** `hard_mine` reads the knob vector from `truth.<knob-key>` with a fallback to `scenarios`, and `twins_filter` reads the pair id from `pair_id` / `twin_pair_id` / `twin_of`. If J picked other key names, it's one flag: `--knob-key` / `--pair-key`.
- **Prompts (Session I) weren't available either.** The steps take the student prompt as rendered files (`--system-file`, `--user-template-file` containing `{packet}`) rather than importing `step0_rules/prompts/render.py`, whose API I couldn't see. The judge and correction prompts have short built-in defaults that can be overridden with a file.
- Error-Surface Resampling (D §3.5, a logistic model over knobs): not built. `hard_mine` ranks categories one knob at a time.
- The narrative "regenerate only conflicting sentences" repair in D's splice recipe: not built. `splice` instead requires a fully grounded narrative from a teacher whose decision matches, and drops the case otherwise.

## Test results
- `python -m pytest tests/k_distill_test.py`: **28 passed** in about 4 s. Coverage: path editing, all input formats, every check failure being named, schema-agnosticism (also run on C's fixture schema), the gate (skipped with no manifest, blocks a contaminated file and leaves no output, refuses a tampered manifest), floor, rejection sampling (best of k, priority, reasons), CLI round-trips, matched-N, arbitration (all modes, ties, repair, label audit, agreement), mining (ranking, mix, knob vectors, refusing a frozen file), DPO (programmatic and judge with position bias), on-policy (no gold in prompts, mock teacher, guard refusal), twins, and `teacher_requests → shared.frontier_api.batch (mock) → reject_sample`.
- Full suite: **247 passed, 3 skipped, 1 failed**. The failure is `tests/f_llm_clients_test.py::test_missing_key_errors_cleanly`, which fails on `main` too: `No module named 'openai'` because `requirements-f.txt` isn't installed. It's Session I's assigned fix, not touched here.
- A manual dry run on 20 draft cases worked: `teacher_requests → shared.frontier_api.batch run --mock → sft_floor / reject_sample`. All mock outputs fail the checks, as expected, since `schema_instance` is not schema-valid for v0.

## Problems / notes
- **k > 1 teacher samples:** identical requests share a cache key and a batch `custom_id` (dedup), so sample i > 0 gets a `[sample i]` line appended to the teacher's user turn. That's the teacher prompt only; the student never sees it. A provider-native `n`/seed would be cleaner, but it differs per provider.
- `cat a.jsonl b.jsonl > train.jsonl` bypasses the distill gate. `step5_training/sft.py`'s own `contamination_gate` still catches it.
- `arbitrate --repair gold` sets the label but leaves the teacher's free-text reason, which can now contradict it. That's why the default is `drop`.

## Questions for Tianle
1. **Rejection-sampling strictness:** identity fields all exact (`--min-field-acc 1.0`, default) or a threshold? Should required actions be checked (`--actions superset`, as experiment_plan R9 says)?
2. **Arbitration mode for S4:** `splice` (recommended: highest yield, and it's the invented-technique candidate D §3.2), `gold_select` (simplest to explain) or `vote`? When no teacher gets a field right: drop (default) or repair from gold (R10)?
3. **On-policy correction:** keep the gold values hidden from the correcting teacher (default, per R12)?
4. **DPO negatives:** near-miss (default), worst, or all failing samples per case?
5. Include the **gold-label SFT control** row (`sft_floor --from-gold`)? It's free and makes the distillation claim falsifiable.
