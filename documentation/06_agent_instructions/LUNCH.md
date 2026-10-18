# Lunch Run: Sat 10/17, ~13:00 → 14:15 ET (Sessions L and M)

Read `CLAUDE.md` and `PIPELINE.md` first; they're the map of this repo. Then read the brief PDF (`documentation/00_case_brief_and_plan/Zorbe KYC Take Home.pdf`) and the decisions below. **This file is the only source for lunch tasks.** There are no API keys in cloud sessions: use mocks. Commit often, write a report to `documentation/05_progress_reports/lunch-<letter>.md`, push, and open a PR. Do not merge.

## Tianle's decisions (final; these override any recommendation in `documentation/01_decisions/`)
| # | Decision |
|---|---|
| D1 | Schema = **option B, flat + enum reason codes** (`documentation/02_research/schema_options/option_b_flat.schema.json` is the starting point). Reason-code enums must cover **nearly every real reason**; true edge cases are described in the narrative and escalated |
| D2 | Identity statuses are exactly the brief's 3: `consistent` / `mismatch` / `unreadable`. Expiry is a reason code (`document_expired`). `verified` = all 5 fields consistent |
| D3 | Narrative sentences cite a **section enum** (`context, application, id_document_visual, id_document_mrz, proof_of_address, screening_hits`) **plus `hit_ids`**. Every screening item echoes its `hit_id` |
| D4 | **Reject = sanctions true match OR clear tamper evidence.** (This is **not** the decision sheet's recommendation 4a. A's current code already does 4b) |
| D5 | Prompt injection → escalate + `manual_packet_integrity_review` + medium driver; a sanctions true match still rejects. The narrative mentions the injection but never quotes it |
| D6 | **Three-way** OCR/tamper rule (current code): readable noise = consistent; ambiguous OCR-or-tamper → escalate; clear tamper → reject. `ocr_digit_to_digit_in_numeric: true` in every config |
| D7–D12 | As in `documentation/01_decisions/policy_v1_candidate.md`, **except where it assumed 4a/6a**. Wherever it does, D4/D6 above win |
| D13 | Sizes: train 3,000 (+ twins/knockouts) / dev 150 / eval_id 300 / OOD 150 (100 LLM-written + 50 hand-template) |
| D14 | OOD = 100 LLM-rendered + 50 hand templates written by a fresh session that **never reads `step1_data_generation/render.py`** |
| D15 | Metric conventions as in decision sheet §15 (strict parse; absent classes excluded; `verified` outside the mean) |
| D16 | Qwen3.5 0.8B / 2B / 4B |

## Ownership
| Session | Owns |
|---|---|
| L | `step0_rules/` (schema, a new `policy_v1.md`, prompt wiring), `step1_data_generation/` (**except** `ood_llm.py` and `ood_templates.py`), `step6_evaluation/fieldmap_v1.yaml`, `step7_serving/proxy_config*.yaml`, `step4_distillation/common.py` (separator change only), `step5_training/modal_infra.py` (kernel packages only), `data/` |
| M | `step1_data_generation/ood_llm.py`, `step1_data_generation/ood_templates.py`, `step3_domain_adapter/`, `tests/m_*_test.py` |

---

## Session L: decisions → code → datasets (Opus)
1. **`step0_rules/schema/v1.json`**: flat, from option B, implementing D1–D3. No `$defs`/`$ref`. Every field `required`, `additionalProperties: false`, narrative `minItems 4 / maxItems 8`, plus `schema_version: "1.0"`. **Make the reason-code, evidence, driver and action enums comprehensive** (D1); list every code with a one-line meaning in the schema `description` fields. It must pass `python -m shared.frontier_api.schema_check step0_rules/schema/v1.json`. Also write `v1_serving.json`, the same schema plus `maxLength` on free-text strings (stops decode loops; Session B finding). Every output valid under `v1_serving` must also be valid under `v1`. Test that.
2. **`step0_rules/policy_v1.md`**: the published, human-readable decision policy (what Zorbe's labellers will read). Reconcile `policy_v1_candidate.md` with D4–D12. Plain rules, a precedence order, the 90-day PoA window, the as-of date rule, and the action catalog. No open questions left in it.
3. **`step1_data_generation/project.py` → v1**: emit the v1 schema exactly as the policy says. Keep the truth object schema-agnostic. Keep v0 working only if that's cheap; otherwise delete v0 and update the tests.
4. **`step6_evaluation/fieldmap_v1.yaml`**, then rerun Session C's harness check on v1 drafts: **oracle = 100% on every metric, broken JSON = 0%.** Save it to `documentation/05_progress_reports/lunch-L-harness-v1.md`.
5. Point `step0_rules/prompts` and `step7_serving/proxy_config.example.yaml` (schema path + escalate fallback) at v1 and `policy_v1.md`.
6. **Decision mix:** tune `step1_data_generation/configs/train.yaml` toward about **38% approve / 47% escalate / 15% reject** without dropping any brief hard-case below ~4%. Report the actual mix per split.
7. **Build the data:** `train` (3,000) and `dev` (150). Build twins (1,000) and knockouts (300) as **separate** files under `data/train_twins/` and `data/train_knockout/` (the invented technique is chosen at 15:30; both must be ready). Build `eval_id` (300) and `eval_ood_template` (50) with `--allow-eval`, but **do not freeze**: the freeze happens after the dev pilot. Commit all `data/` outputs.
8. **Brief compliance audit** → `documentation/05_progress_reports/brief_compliance.md`: a table with **one row per detail in the brief** (every input field, every output field and value, every "what makes it hard" item, every metric), showing where it's generated or scored, 1–2 example case ids, and counts per split. Flag anything thin (<3% of train) or missing.
9. Session B follow-ups:
   - (a) serialize SFT targets with the **default JSON separators** (`", "`, `": "`) so they match vLLM's whitespace-free grammar (`step4_distillation/common.py`, one line + a test);
   - (b) add `flash-linear-attention` and `causal-conv1d` to the training image in `step5_training/modal_infra.py`.

All tests must pass: `python -m pytest -q`.

## Session M: OOD writers + domain adapter (Opus; a fresh session, so don't read `step1_data_generation/render.py`)
1. **`step1_data_generation/ood_templates.py`**: **50 hand-template OOD packets.** Write at least **5 new packet styles** of your own invention (e.g. a bank onboarding PDF export, a call-centre transcript summary, a scanned-fax OCR dump with page headers, a JSON API payload from a different vendor, a two-column form read row-wise), working only from the truth object (`step1_data_generation/truth.py`, `sample.py` for the knobs) and the brief. Labels come from `project.py` (v1, written by L at the same time; import it lazily and test against v0 if v1 isn't there yet). Every truth fact the label depends on must appear in the packet (assert it). Build CLI writing to `data/eval_ood_hand/`, which refuses to run without `--allow-eval`.
2. **`step1_data_generation/ood_llm.py`**: the LLM-written OOD set. It takes truths from `step1_data_generation/configs/eval_ood_template.yaml` and calls a frontier model through `shared/frontier_api` with `step0_rules/prompts` `ood_renderer` (models: `claude-sonnet-5-5` and `gemini-3.8-flash`, alternating). It runs `check_ood_packet` and drops packets where a required fact is missing or "fixed", logging the counts. Output to `data/eval_ood_llm/`. Mock tests; the real run happens on the laptop (≈100 cases, ~$5).
3. **`step3_domain_adapter/`**: stage 2 of the brief.
   - `train_adapter.py`: continued pretraining (16-bit LoRA, causal-LM loss on raw text) on `step3_domain_adapter/corpus/*.txt`, as a Modal job reusing `step5_training/modal_infra.py` images. Configs with placeholders, plus a CPU smoke on a tiny model as in `step5_training/cpu_smoke.py`.
   - `measure_adapter.py`: held-out corpus perplexity before vs after, and a 30-item KYC knowledge probe (MRZ check digits, PEP definitions, alias conventions; synthetic, answerable from the corpus) scored before vs after. The point is "evidence the adapter moved something, or honestly not".
   - `corpus/fetch_corpus.sh`: fix the URLs that failed (FATF, ICAO 9303 parts 3–5, Wolfsberg) to currently valid public locations where you can verify them, and mark the rest UNVERIFIED.
4. Report: what to run on the laptop, in order, with cost estimates.
