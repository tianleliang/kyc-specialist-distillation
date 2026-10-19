# Overnight Run, Wave 2: Sat 10/17, 01:00 → 07:00 ET

Wave 1 (Sessions A–G) is merged into `main`. Read its reports in `documentation/05_progress_reports/overnight-*.md` first. **This file is the only source for wave-2 tasks.** `CLAUDE.md` rules apply, and the rules in `documentation/06_agent_instructions/OVERNIGHT.md` §"Before your task" still apply: branches, no keys, mocks only, finish with a report and a PR, never merge.

**The goal of wave 2:** when Tianle makes each decision at 07:45, the very next step is ready to run. Build for **every likely answer**, behind a config switch, rather than guessing one.

## Ownership (wave 2)
| Session | Owns |
|---|---|
| H | `documentation/01_decisions/` |
| I | `step0_rules/prompts/`, `step7_serving/proxy.py`, `step2_benchmarking/run_endpoint.py`, plus the encoding fixes listed below |
| J | `step1_data_generation/` (wave-2 changes), `step1_data_generation/configs/`, `tests/j_*_test.py` |
| K | `step4_distillation/`, `tests/k_*_test.py` |

Tests must be named `tests/<letter>_*_test.py`; files not ending in `_test.py` are silently skipped. Don't edit another session's files. Report: `documentation/05_progress_reports/overnight-<letter>.md`.

---

## Session H: the decision sheet (`documentation/01_decisions/`, Fable, writing only)
Read every wave-1 report plus `documentation/02_research/decision_policy_draft.md`, `documentation/02_research/schema_options.md`, `documentation/03_design/*.md`, `step1_data_generation/project.py` (A's provisional policy) and `documentation/04_results/writeup_skeleton.md`.
1. `decision_sheet.md`: **deduplicate the ~50 questions** in the wave-1 reports into **at most 20 decisions**, in the order they must be made: schema → policy → data → models → techniques → serving/repo.
   - Each decision is a small table of options, a recommendation with a one-line reason, which other decisions it unblocks, and a **"code change if chosen"** column naming the exact file/config to flip.
   - Mark which ones must be made at 07:45 and which can wait (with their deadline, e.g. the invented technique by 15:00).
   - Note every place A's provisional policy, D's draft policy and E's proposed label rules disagree, side by side.
2. `policy_v1_candidate.md`: a single reconciled decision policy taking the recommended option at every fork. Every recommended choice is marked `[DEFAULT, pending Tianle]`, so ticking the sheet turns it into the real policy.
3. `morning_brief.md`: a ≤1-page summary of what exists after waves 1 and 2, what's still missing, and the first three things to run after the decisions.

## Session I: prompts, serving proxy, endpoint runner (Opus, code with mocks)
1. `step0_rules/prompts/`: templates parameterized by `{schema}`, `{policy}` and `{packet}`, with no schema or policy hardcoded:
   - `baseline_zero_shot` (task description + schema only)
   - `baseline_best` (policy + field-by-field instructions + 2 few-shot examples drawn from a **dev** pool, never eval)
   - `teacher` (best prompt + a request for complete evidence_refs)
   - `judge_unsupported_claims` (per-sentence grounding judgment with bias controls: blind to which model produced it, randomized order)
   - `ood_renderer` (instructions for a frontier model to write a packet in a novel style from a truth object, for the OOD set)

   Add a `step0_rules/prompts/render.py` loader with tests. Keep prompts short and explicit; small models are the audience for the student prompt.
2. `step7_serving/proxy.py`: a thin OpenAI-compatible proxy, testable locally with a mock upstream. It **injects our system prompt and `response_format` json_schema if the caller omits them**, forces thinking off, checks the bearer token, logs latency, and validates the output against the schema. If the output is still invalid: one retry, then a schema-valid `escalate` fallback, flagged in a response header and logged. Tests: a bare packet with no system prompt gets valid JSON; a missing or wrong token gets 401; streaming is either supported or rejected clearly.
3. `step2_benchmarking/run_endpoint.py`: runs any OpenAI-compatible endpoint (our proxy, vLLM, OpenAI itself) over a JSONL of cases with concurrency, recording latency and usage, and writes predictions in **exactly the record format `step6_evaluation/report.py` expects** (see `documentation/05_progress_reports/overnight-C.md`). Uses the F client's cache where it makes sense. Mock tests.
4. **Windows encoding fixes:** every `open()`, `read_text()` and `write_text()` in `step6_evaluation/report.py`, `step6_evaluation/metrics.py`, `tests/c_*` and `step6_evaluation/split_guard.py` gets an explicit `encoding="utf-8"`. Also make `tests/f_llm_clients_test.py::test_missing_key_errors_cleanly` independent of a local `.env` (monkeypatch the env, and disable dotenv loading in that test). You own these specific edits.

## Session J: generator v1 (Opus, code)
Read `documentation/03_design/data_design.md`, `documentation/03_design/contamination_protocol.md`, `documentation/02_research/distillation_options.md` and `documentation/05_progress_reports/overnight-A.md` (especially the Problems list). Extend A's generator **without breaking A's tests**, and keep `step1_data_generation/project.py` as the only schema-aware file.
1. **As-of date** in the truth object and printed in every packet (CTX). Expiry and PoA recency are computed against it.
2. **Knob vector** logged in every truth object (scenario, difficulty knobs, style), so we can break results down per category and resample where the model fails.
3. **Split-aware configs** in `step1_data_generation/configs/`: `train`, `dev`, `eval_id`, `eval_ood_template` with disjoint seed ranges, **disjoint entity pools** (names, document numbers, addresses, watchlist entries), different nationality pools, and **held-out layout families** (2 styles never used in train). Add a `step1_data_generation/build.py --config step1_data_generation/configs/<split>.yaml --n N` CLI that writes `data/<split>/` plus a manifest with hashes. **Do not generate the real eval set**; that's frozen only after the schema decision. Prove disjointness with a test that runs `step6_evaluation/split_guard.py check` on small samples.
4. **Plausibility constraints** (A's Problem 2): age vs occupation, issuing country vs nationality, residence vs onboarding country.
5. **A noise-rule switch** (E's Problem 7): `ocr_digit_to_digit_in_numeric: true|false`, so the OCR-vs-tamper rule can follow whichever policy Tianle picks.
6. **Machinery for the two leading invented-technique candidates**, both off by default:
   - `step1_data_generation/twins.py`, **counterfactual twins**: from a truth object, produce minimal pairs differing in exactly one decision-relevant fact, with the expected decision flip recorded.
   - `step1_data_generation/knockout.py`, **evidence knockout**: remove or obscure one piece of evidence so the correct answer becomes escalate.
   - Both with tests asserting the labeled flip actually happens through `step1_data_generation/project.py`.
7. Remove the `poa_address_matches` vs `poa_address_format_variant` noise (A's Problem 1): move the abbreviation choice into the truth object.

## Session K: distillation data pipeline (`step4_distillation/`, Opus, code with mocks)
Stage 3 is worth 20 points, and its data-building steps don't exist yet. Read `documentation/02_research/distillation_options.md`, `documentation/03_design/experiment_plan.md`, `shared/frontier_api/clients.py`, `shared/frontier_api/batch.py`, `step6_evaluation/metrics.py`, `step1_data_generation/project.py`. Build **schema-agnostic** steps (driven by the same FieldMap config as `step6_evaluation/metrics.py`). Each is a CLI that turns JSONL into JSONL and logs counts kept or dropped per reason. Everything has tests using mock teacher outputs.
1. `step4_distillation/sft_floor.py`: teacher outputs → SFT records (prompt = student prompt + packet, completion = teacher JSON). No filtering. This is **the floor**.
2. `step4_distillation/reject_sample.py`: **rejection sampling against programmatic checks.** Keep a teacher output only if it validates against the schema, matches gold on decision, risk tier and every screening disposition, has field findings ≥ a threshold, and passes the `evidence_refs` check. Support k samples per case and pick the best passing one.
3. `step4_distillation/arbitrate.py`: **multi-teacher arbitration.** Combine the outputs of 2–3 teachers per case. Modes: `gold_select` (the teacher closest to gold wins), `vote` (field-wise majority, no gold), `splice` (field-wise best-of, re-validated). Report teacher agreement rates.
4. `step4_distillation/hard_mine.py`: given student predictions + gold, rank failure categories using the truth-object knob vectors (Session J adds them; fall back to `scenarios` if missing) and emit a resampling mix for `step1_data_generation/build.py`.
5. `step4_distillation/prefs.py`: **DPO pair building.** chosen = a gold-passing teacher (or corrected) output; rejected = a student output that fails gold. Also a teacher-as-judge mode stub (prompt via `step0_rules/prompts/`, mock judge).
6. `step4_distillation/onpolicy.py`: the on-policy correction loop scaffold: student outputs → failures → correction requests to a teacher (via `shared/frontier_api/`, mock) → corrected SFT records.
7. `step4_distillation/README.md`: which file implements which Table 2 row, and the exact command sequence for Saturday.
Every training-file writer must run the `step6_evaluation/split_guard.py` contamination check against frozen eval manifests when they exist. Own `step4_distillation/` and `tests/k_*_test.py` only.
