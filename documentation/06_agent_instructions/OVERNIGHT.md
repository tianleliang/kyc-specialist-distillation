# Overnight Run: Fri 10/16 → Sat 07:00 ET

**This is the one setup file for all overnight sessions.** `CLAUDE.md` is loaded automatically, and this file tells each session which task it owns.

## Before your task (every session)
1. Read `CLAUDE.md`, the brief PDF `documentation/00_case_brief_and_plan/Zorbe KYC Take Home.pdf`, and `documentation/00_case_brief_and_plan/00`, `01`, `02` and `05`.
2. **The overnight rule:** build only decision-free work, meaning things defined by a public spec, the brief itself, or plumbing whose design doesn't depend on Tianle's choices. Schema, decision policy, base model and techniques are Tianle's decisions at 07:45. You may draft **options**, never decisions. (One exception: Session A phase 2 builds explicitly PROVISIONAL placeholders so the pipeline can be tested end to end.)
3. Work on your own branch, `overnight-<letter>` if allowed. If the environment forces its own branch name, make sure it contains your session letter. Commit after each sub-task and push often.
   **Environment:** `pip install -r requirements.txt`. If you need extra packages, list them in `requirements-<letter>.txt`. **Don't edit shared files**: `requirements.txt`, `pytest.ini`, `__init__.py` files, `CLAUDE.md`, `README.md`.
4. Never touch another session's files. Ownership:

   | Session | Owns |
   |---|---|
   | A | `step1_data_generation/` (incl. `step1_data_generation/lib/`), `step3_domain_adapter/corpus/`, `data/draft/`, `step0_rules/schema/v0_provisional.json` |
   | B | `step7_serving/`, `step6_evaluation/run_open_models.py` |
   | C | `step6_evaluation/metrics.py`, `step6_evaluation/report.py` |
   | D | `documentation/02_research/` |
   | E | `documentation/03_design/` |
   | F | `shared/frontier_api/`, `step5_training/`, `step6_evaluation/split_guard.py` |
   | G | `documentation/04_results/` |

   Tests go under `tests/<letter>_*.py`. Don't edit `CLAUDE.md`, `documentation/00_case_brief_and_plan/` or this file.
   **If anything in `documentation/00_case_brief_and_plan/` conflicts with this file, this file wins.** The "Tonight" section in `02 Plan` is stale.
   There are **no API keys** in cloud sessions. Don't try to call OpenAI, Anthropic, Gemini, HF or Modal; use mocks.
5. If you're stuck for 45 minutes, write it down and move on. Keep going until every task is done or blocked.
6. **To finish:** write `documentation/05_progress_reports/overnight-<letter>.md` (done / not done / test results / problems / questions for Tianle), push, and open a PR to `main` with that summary. Do not merge.

---

## Session A: KYC building blocks (`step1_data_generation/lib/`, pytest for each)
1. **MRZ (ICAO 9303):** generate TD3 and TD1 MRZ lines from fields, compute and validate check digits, parse back to fields. Test against spec examples.
2. **Synthetic name engine:** fictional name pools (no real people or public figures) for Arabic, Cyrillic, Chinese, Latin and other origins. Transliteration variants (Mukhammad/Muhammad/Mohammed; Pinyin vs Wade-Giles; Cyrillic romanization systems), name reordering, alias generation.
3. **Name matching:** normalization plus a similarity score (e.g. Jaro-Winkler on tokens) that simulates vendor screening scores.
4. **Address renderers for 10 countries** following national/UPU conventions (US, UK, DE, FR, AE, RU, CN, IN, NG, BR), with fictional streets.
5. **OCR noise injector:** 0/O, 1/l/I, 5/S, 8/B, rn/m, dropped characters, line breaks, configurable rate. Also a **separate tamper injector** (altered digits that break MRZ check digits or contradict the visual zone).
6. **Synthetic watchlists:** fake sanctions/PEP/adverse-media entries modeled on the public structure of OFAC SDN, the UN consolidated list and the EU lists. Fictional names only.
7. **Domain corpus:** download public KYC/AML documents to `step3_domain_adapter/corpus/` (text only, PDFs gitignored), with `SOURCES.md` listing URL, title and date. FATF Recommendations plus PEP guidance, the FinCEN CDD final rule, ICAO 9303, the Wolfsberg FAQs.

### Session A, phase 2 (after phase 1): end-to-end draft generator (PROVISIONAL)
Everything in this phase is a **placeholder for speed**, not a decision. Label it `PROVISIONAL` in code and docs. Tianle sets the real schema and policy in the morning.
1. `step1_data_generation/truth.py`: a **latent-truth** case object, the hidden facts behind each case. Applicant identity, the document and its defects, proof-of-address status, screening hits with their real status, injected instructions, ambiguity flags. **It must stay independent of any output schema.**
2. `step1_data_generation/render.py`: turns a truth object into a packet as text. Use **several layout styles** (key-value, prose, form-like, mixed ordering) so the model can't overfit one format. Use the A building blocks for MRZ, names, addresses, OCR noise, tampering and watchlists.
3. `step1_data_generation/sample.py`: samples truth objects covering every "what makes it hard" item in the brief, with configurable mix and seed.
4. `step1_data_generation/project.py` + `step0_rules/schema/v0_provisional.json`: a THIN adapter mapping truth → expected output under a flat, enum-heavy **provisional** schema, with a simple provisional decision policy in code comments. Designed so swapping in the real schema means changing only this file.
5. Write **200 draft cases** to `data/draft/` (packet text + expected output) with a fixed seed, plus `data/draft/README.md` saying **DRAFT, not an eval set, do not use for training**. Add 10 human-readable examples to `documentation/05_progress_reports/overnight-A-samples.md` for Tianle to review.
You own `step1_data_generation/`, `step0_rules/schema/v0_provisional.json`, `data/draft/`.

## Session B: infrastructure smoke test (LAPTOP ONLY; needs Modal and HF credentials in `.env`)
1. `step7_serving/modal_vllm.py`: vLLM on a Modal L4 serving Qwen3.5-0.8B (look up the exact HF ID; fall back to Qwen3-0.6B after 45 minutes). OpenAI-compatible `/v1/chat/completions`, bearer token from a Modal Secret (`--api-key`), thinking off, weights cached in a Volume.
2. `step7_serving/smoke.py`: OpenAI client calls with and without the token (expect a 401 without it). Test that `response_format: json_schema` is enforced with a toy schema. Measure cold start and warm p50/p95 over 20 requests.
3. Rehearse train → merge → serve: a few LoRA steps on toy data on a Modal GPU, **merge into the base weights**, serve, and **verify outputs differ from base**.
4. `step6_evaluation/run_open_models.py` skeleton: model ID + prompt file + inputs JSONL → batch on Modal vLLM → raw outputs to `outputs/<run_id>/`.
5. `step7_serving/README.md`: commands, observed cost, cold-start numbers, gotchas.
6. **Cost guardrails:** under $15 total. Scale to zero or stop at the end. Never leave a GPU running.

## Session C: evaluation metrics (`step6_evaluation/`)
`step6_evaluation/metrics.py` with tests. Schema-agnostic, driven by a field-mapping config:
- decision accuracy plus a confusion matrix
- screening macro F1 (true_match / false_positive / needs_review)
- per-identity-field accuracy
- risk tier exact and within one tier
- required-actions recall (precision reported separately)
- schema validity rate
- adversarial-subset escalation rate
- latency p50/p95 and cost per 1k cases from token counts and a price table
- unsupported-claims scaffold: an interface plus a programmatic `evidence_refs` check (no LLM judge yet)

Then `step6_evaluation/report.py`: Table 1 (models × metrics, with case counts) and Table 2 (stage deltas) as markdown from per-case JSONL, with bootstrap 95% confidence intervals. One command: `python -m step6_evaluation.report outputs/`. No API calls.

### Session C, phase 2: prove the harness works end to end
Once Session A's `step0_rules/schema/v0_provisional.json` and `data/draft/` exist on the remote, find them like this. Session A pushes to its own branch, not `main`. Every ~15 minutes, for up to 3 hours, run `git fetch origin '+refs/heads/*:refs/remotes/origin/*'`, then check each remote branch with `git cat-file -e origin/<branch>:step0_rules/schema/v0_provisional.json`. When you find it, copy A's files **read-only** into a scratch dir (`git archive` / `git show`). **Never merge A's branch into yours.** If they never appear, use a small stand-in fixture in `tests/fixtures/c_*`:
1. Build fake "models" that need no API: **oracle** (returns the expected output, so it should score 100%), **random** (valid random enums), **always-escalate**, **broken JSON** (tests schema validity = 0), and **corrupted** (flips 20% of fields).
2. Run all of them through `step6_evaluation/metrics.py` + `step6_evaluation/report.py` and save the Table 1 output to `documentation/05_progress_reports/overnight-C-harness-check.md`.
3. Any metric that doesn't behave as expected (oracle below 100%, broken JSON above 0%) is a harness bug. Fix it.

Read Session A's files; never edit them.

## Session D: research for Tianle (`documentation/02_research/`, writing only, no decisions)
1. `kyc_primer.md`: a 20-minute primer for a smart beginner. How an analyst adjudicates; sanctions vs PEP vs adverse media; PEP family/close-associate rules (FATF); true match vs false positive practice; partial DOB matching; a catalog of 10–15 standard EDD actions and when each applies; escalate vs reject; tampering vs OCR-noise red flags; proof-of-address recency rules. Cite public sources.
2. `decision_policy_draft.md`: a DRAFT rulebook (approve/reject/escalate, risk drivers, action triggers), clearly labeled a draft, with every judgment call flagged as a question for Tianle.
3. `schema_options.md`: 2–3 alternative output-schema designs with tradeoffs. Flat, enum-heavy, valid under OpenAI, Anthropic and Gemini structured-output limits; narrative as `[{sentence, evidence_refs}]`.
4. `distillation_options.md`: each technique from the brief (hard-case mining, multi-teacher arbitration, rejection sampling, teacher-as-judge preferences, on-policy correction, DPO, GRPO/RLVR) in plain English, with cost and time on a 2B model on Modal, expected gain, and how to ablate it. Then 4 candidate **invented** techniques specific to KYC, with feasibility in about 3 hours each.

## Session E: decision prep and design (`documentation/03_design/`, writing only, Fable). Options and recommendations; Tianle decides
1. `decision_memos.md`: one page per 07:45 decision, each with options, evidence, a recommendation, and what would change it.
   - Base model family and sizes
   - Frontier panel and each model's role (baseline / teacher / judge), with a cost estimate (prices in `05` research brief)
   - Train/eval set sizes and the API budget
   - Tool-assisted variant (code pre-checks MRZ and dates): shipped, or a report row only
   - Serving plan (always-on vs hybrid)
   - Repo sharing
2. `data_design.md`: the answer-first generator design.
   - The latent-truth spec.
   - A **difficulty taxonomy table** mapping every "what makes it hard" item in the brief to its generator knobs, the ground-truth label rule, and the metric it exercises.
   - Case-mix proportions, and how packet formatting varies so the model doesn't overfit our layout.
   - The **OOD eval process**: packets written by a different method or model family with different prompts.
   - A label-audit plan: frontier-disagreement review, plus 20 hand checks.
3. `contamination_protocol.md`: splits, seeds, separate generator configs and prompts for eval, hashing and freezing, exact and n-gram/MinHash overlap checks, teachers never seeing eval cases, and how we'd defend each point under questioning.
4. `experiment_plan.md`: the ordered run list for Saturday and Sunday. For each run: inputs, estimated time and cost, which Table 1 / Table 2 row it fills, the ablation design, and explicit cut lines if time slips.

## Session F: model-call and training plumbing (code, mocks only)
1. `shared/frontier_api/clients.py`: one wrapper for OpenAI, Anthropic and Gemini. Structured output via JSON schema, retry/backoff, rate limiting, token and cost accounting (price table in config), an on-disk cache keyed by request hash so reruns are free, keys read from env, and a mock mode. Tests use mocks only.
2. `shared/frontier_api/batch.py`: submit, poll and collect for all three providers' batch APIs, with resumable state on disk.
3. `step5_training/`: Unsloth/TRL scripts for **SFT (16-bit LoRA)** and **DPO** that run as Modal functions, plus `step5_training/merge.py` (merge the LoRA into the base and push to HF) and config files with placeholder model IDs and data paths. Write them, don't run them. Follow the tooling traps in `05`: no QLoRA on Qwen3.5, Transformers v5, serve merged weights.
4. `step6_evaluation/split_guard.py`: hash and freeze eval files; detect exact and near-duplicate overlap (n-gram/MinHash) between train and eval JSONL; exit non-zero on contamination. With tests.

## Session G: write-up scaffolding (`documentation/04_results/`, writing only)
1. `writeup_skeleton.md`: the 4-page structure with word budgets per section, following the brief's required contents: choices, what failed, the invented technique, contamination controls, stages 7–9, the models-used table, spend, and coding assistants. Use `{{placeholders}}` for every number.
2. `stages_7_9_draft.md`: a DRAFT, for Tianle to rewrite in his own judgment.
   - **Shadow and ramp** for a KYC desk: mirroring, scoring against the frontier as outcomes land, ramp steps and gates, mid-request frontier fallback.
   - **Controller**: a failure taxonomy specific to KYC adjudication, each failure mapped to its trigger signal and fix (re-prompt / re-tune / re-distill / rollback).
   - **Continuous learning**: what to automate first, and why.

   Concrete, about 1 page each, with judgment calls flagged.

---

## Single-session mode (alternative)
If only one cloud session is available: act as the orchestrator. Run **A, C and D as parallel subagents**, each with this file and its own section, and keep the ownership rules. When all three finish, write `documentation/05_progress_reports/overnight-summary.md` and open one PR per branch.
