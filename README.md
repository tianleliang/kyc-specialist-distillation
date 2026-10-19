# kyc-specialist-distillation

**A 4B open-weight specialist for KYC onboarding adjudication. On 300 fresh in-distribution cases it scores 96.3%, a statistical tie with Gemini 4 Argon and Claude Opus 5.5 (GPT-6 Astra stays ahead), at $3.59–5.36 per 1,000 cases against $37–175 for the frontier APIs. Latency is a hardware choice: 24 s per case on the L4 hand-over endpoint, 3.3 s on an H100 (frontier APIs: 8.6–12.1 s). It trails the frontier on out-of-distribution free prose and on injected instructions (86% escalated vs 100%); both are documented.**

One case packet in (applicant profile, OCR'd ID document with MRZ, proof of address, sanctions / PEP / adverse-media hits, jurisdiction) → one JSON decision out (identity findings, screening dispositions, risk tier, required actions, approve / reject / escalate, a grounded narrative).

## Results (fresh eval_id v2, 300 cases generated after all development, never seen by any part of the system)

| | Decision accuracy | Their accuracy − ours (pts, paired 95% CI) | Unsupported narrative claims | p50 latency | $ / 1,000 cases |
|---|---|---|---|---|---|
| **Ours (Qwen3.5-4B specialist, B2)** | **96.3%** | – | 13.7% | 24.3 s (L4, hand-over) · 3.3 s (H100) | $5.36 (L4) · $3.59 (H100) · $0.47 (L4, 16 concurrent) |
| GPT-6 Astra (best prompt) | 99.3% | Astra ahead (+3.0, +0.7 to +5.3) | 7.4% | 12.1 s | $175 |
| Claude Opus 5.5 (best prompt) | 97.7% | **tie** (+1.3, −1.3 to +4.0) | 8.6% | 11.5 s | $116 |
| Gemini 4 Argon (best prompt) | 95.0% | **tie** (−1.3, −4.7 to +2.0) | 8.8% | 8.6 s | $37 |
| Qwen3.5-4B untrained (best prompt) | 56.0% | | 52.0% | | |

- On the frozen eval v1 (500 cases incl. 200 out-of-distribution), the specialist scores 94.6% (Argon 95.8, Opus 98.4, Astra 99.2); out-of-distribution free prose is where it still trails.
- Full tables (every metric of the brief, case counts, stage deltas): [`documentation/04_results/benchmark_report_submission.md`](documentation/04_results/benchmark_report_submission.md). Generated report with confidence intervals: [`documentation/04_results/benchmark_report.md`](documentation/04_results/benchmark_report.md).
- Our latency is measured one request at a time on a warm endpoint (100 dev cases on L4, 30 on H100); frontier latency is measured through their public APIs during the benchmark. Different hardware; same caller-side measurement.

## Find it fast
| You want | Where |
|---|---|
| **All results + build timeline, one page** | [`RESULTS.md`](RESULTS.md) |
| **Process log: every decision, realization, failure** | [`documentation/04_results/process_log.md`](documentation/04_results/process_log.md) |
| Pipeline map (each step folder, what it does, how to run) | [`GUIDE.md`](GUIDE.md) |
| **Output JSON schema** | [`step0_rules/schema/v1.json`](step0_rules/schema/v1.json) (serving copy: [`v1_serving.json`](step0_rules/schema/v1_serving.json)) |
| Decision policy (what every situation must produce) | [`step0_rules/policy_v1.md`](step0_rules/policy_v1.md) |
| **Rebuild every table from saved outputs** | `bash make_tables.sh` |
| **Regenerate every evaluation set (and verify hashes)** | `bash regenerate_eval.sh` |
| Benchmark tables (Table 1, Table 2, appendices) | [`documentation/04_results/benchmark_report_submission.md`](documentation/04_results/benchmark_report_submission.md) |
| Data generation | [`step1_data_generation/`](step1_data_generation/README.md) |
| Training (adapter, distillation data, SFT / merge) | [`step3_domain_adapter/`](step3_domain_adapter/README.md) · [`step4_distillation/`](step4_distillation/README.md) · [`step5_training/`](step5_training/README.md) |
| Evaluation harness (metrics, report, contamination guard, LLM judge) | [`step6_evaluation/`](step6_evaluation/README.md) |
| Serving (vLLM + proxy + code pre-checker) | [`step7_serving/`](step7_serving/README.md) |
| Saved per-case predictions behind every number | [`results/runs/`](results/README.md) |
| Decisions and why | [`documentation/01_decisions/decision_log.md`](documentation/01_decisions/decision_log.md) |
| Case requirements → where each is met | [`documentation/00_requirements/REQUIREMENTS.md`](documentation/00_requirements/REQUIREMENTS.md) |

## What's in the pipeline

Qwen3.5-4B (Apache 2.0: commercial use and derivative weights allowed) → **domain adapter** on public KYC/AML text (merged) → **black-box distillation** from GPT-6.1 Sol and Gemini 4 Argon with our invented **Counterfactual Twin Distillation** (pairs of cases that differ by one decision-flipping fact) → **SFT post-train** on exact synthetic labels → served with a **deterministic code pre-checker** (MRZ check digits, expiry, proof-of-address age, document-integrity class) whose result the model was trained to read. Step-by-step map: [`GUIDE.md`](GUIDE.md).

## Endpoint, weights

- **Endpoint:** OpenAI-compatible `POST https://tianleliang--zorbe-kyc-final-brun2-s4-proxy.us-east.modal.run/v1/chat/completions`, model `zorbe-kyc`, bearer token (shared privately), 1× NVIDIA L4, always warm. Send the bare case packet as the user message; the proxy adds the prompt, pre-checks and JSON schema. **Measured per case** (warm, one request at a time): p50 24.3 s, p95 29.1 s, $5.36 per 1,000 cases ($0.47 at 16 concurrent); same model on an H100: p50 3.3 s, p95 3.8 s, $3.59 per 1,000 ([`results/latency/`](results/latency/)).
- **Weights (merged, public):** https://huggingface.co/tianle-terrence-liang/zorbe-kyc-specialist-4b · LoRA adapters in the same repo under `adapters/`: `domain_adapter` (on Qwen3.5-4B), `stage3_distillation` (on Qwen3.5-4B + merged domain adapter), `stage4_posttrain` (on the merged stage-3 model); merging all three in that order gives the shipped weights.
- **Output schema:** [`step0_rules/schema/v1.json`](step0_rules/schema/v1.json) (serving variant `v1_serving.json`); **policy:** [`step0_rules/policy_v1.md`](step0_rules/policy_v1.md).

## Reproduce

Python 3.11+, from a clean clone, no API keys and no GPU needed:

```bash
pip install -r requirements.txt
bash make_tables.sh        # rebuilds every benchmark table from the saved outputs in results/runs/ (both reports)
bash regenerate_eval.sh    # rebuilds every frozen eval split from its seed/config and verifies the sha256 manifests
```

Training and serving commands (Modal GPU, cost money) are in each step folder's README; the agent briefs that ran them are in [`documentation/06_agent_instructions/`](documentation/06_agent_instructions/).

## Models, assistants, data

- **Frontier models** (teachers, baselines, judge; never shipped): GPT-6.1 Sol (main teacher), Gemini 4 Argon (second teacher + baseline), GPT-6 Astra and Claude Opus 5.5 (baselines), Claude Sonnet 5.5 (blind unsupported-claims judge; also wrote half of the LLM out-of-distribution set with Gemini 3.8 Flash). Claude never taught.
- **Coding assistants:** Claude Code (desktop and cloud sessions) wrote and ran the code under written briefs (`documentation/06_agent_instructions/`, reports in `documentation/05_progress_reports/`); Claude in Obsidian (Claudian) for planning, audits and the decision log. Every design decision is Tianle's and logged in [`documentation/01_decisions/decision_log.md`](documentation/01_decisions/decision_log.md).
- **Data:** fully synthetic (answer-first generator; no real people, documents or list entries). How it was built: [`step1_data_generation/README.md`](step1_data_generation/README.md).
- Requirements of the case mapped to where they are met: [`documentation/00_requirements/REQUIREMENTS.md`](documentation/00_requirements/REQUIREMENTS.md).
