# Benchmark report

## Table 1. Final model vs open baselines and frontier models (fresh eval_id v2, 300 cases)

### Table 1a. Decision quality

| Model | Params | Cases | Decision acc % | Their acc − ours (pts) [95% CI, paired] | Screening macro-F1 % | Risk exact % | Risk ±1 % | Actions recall % | Actions precision % | Unsupported claims % (LLM judge) | Schema valid % |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **Ours: Zorbe KYC specialist (B2), Qwen3.5-4B** | 4B | 300 | 96.3 | – | 99.6 | 95.3 | 100.0 | 93.6 | 97.6 | 13.7 | 100.0 |
| Qwen3.5-0.8B (best prompt) | 0.8B | 300 | 44.3 | -52.0 [-57.7, -46.3] | 25.2 | 26.3 | 83.7 | 4.7 | 32.0 | 60.8 | 100.0 |
| Qwen3.5-2B (best prompt) | 2B | 300 | 39.7 | -56.7 [-62.3, -51.0] | 42.9 | 37.0 | 88.3 | 30.2 | 17.8 | 45.3 | 100.0 |
| Qwen3.5-4B (best prompt) | 4B | 300 | 56.0 | -40.3 [-46.3, -34.0] | 34.6 | 50.3 | 98.3 | 34.6 | 17.3 | 52.0 | 100.0 |
| GPT-6 Astra (best prompt) | undisclosed | 300 | 99.3 | +3.0 [+0.7, +5.3] | 100.0 | 99.3 | 100.0 | 98.8 | 99.7 | 7.4 | 100.0 |
| Claude Opus 5.5 (best prompt) | undisclosed | 300 | 97.7 | +1.3 [-1.3, +4.0] | 100.0 | 97.3 | 100.0 | 97.4 | 96.3 | 8.6 | 100.0 |
| Gemini 4 Argon (best prompt) | undisclosed | 300 | 95.0 | -1.3 [-4.7, +2.0] | 100.0 | 95.7 | 100.0 | 92.2 | 96.1 | 8.8 | 100.0 |

### Table 1b. Identity fields, adversarial cases, latency and cost

| Model | Verified % | Name % | Date of birth % | Document no. % | Expiry % | Address % | Escalation on injection % (n) | Escalation on ambiguous % (n) | p50 latency | p95 latency | $ / 1k cases |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **Ours: Zorbe KYC specialist (B2), Qwen3.5-4B** | 98.3 | 99.3 | 99.7 | 99.3 | 100.0 | 98.3 | 86.2 (30) | 100.0 (26) | 24.3 s (L4, 1 at a time) / 3.3 s (H100, 1 at a time) | 29.1 s (L4, 1 at a time) / 3.8 s (H100, 1 at a time) | $0.47 (L4, 16 concurrent) / $5.36 (L4, 1 at a time) / $3.59 (H100, 1 at a time) |
| Qwen3.5-0.8B (best prompt) | 66.0 | 97.0 | 91.7 | 95.3 | 93.3 | 87.7 | 6.9 (30) | 7.7 (26) | 8.7 s (L4, 16 concurrent) | 10.9 s (L4, 16 concurrent) | $0.12 (L4, 16 concurrent) |
| Qwen3.5-2B (best prompt) | 68.3 | 97.7 | 91.7 | 94.0 | 94.3 | 88.0 | 17.2 (30) | 34.6 (26) | 14.1 s (L4, 16 concurrent) | 19.5 s (L4, 16 concurrent) | $0.20 (L4, 16 concurrent) |
| Qwen3.5-4B (best prompt) | 73.3 | 68.7 | 94.3 | 91.0 | 90.0 | 90.7 | 82.8 (30) | 96.2 (26) | 31.1 s (L4, 16 concurrent) | 40.0 s (L4, 16 concurrent) | $0.44 (L4, 16 concurrent) |
| GPT-6 Astra (best prompt) | 99.0 | 99.7 | 100.0 | 99.3 | 99.7 | 100.0 | 100.0 (30) | 100.0 (26) | 12.1 s (API) | 15.3 s (API) | $175.31 (API) |
| Claude Opus 5.5 (best prompt) | 97.7 | 100.0 | 100.0 | 98.7 | 99.0 | 99.7 | 100.0 (30) | 100.0 (26) | 11.5 s (API) | 16.8 s (API) | $116.41 (API) |
| Gemini 4 Argon (best prompt) | 98.0 | 100.0 | 100.0 | 98.7 | 99.0 | 99.7 | 100.0 (30) | 100.0 (26) | 8.6 s (API) | 32.7 s (API) | $36.92 (API) |

## Table 2. Gain from each pipeline stage (final model's pipeline, fresh eval_id v2, 300 cases)

| Stage | Decision acc % | Δ decision (pts) [95% CI] | Risk exact % | Δ risk | Actions recall % | Δ actions | Screening macro-F1 % | Δ screening | Unsupported claims % | Δ unsupported |
|---|---|---|---|---|---|---|---|---|---|---|
| Qwen3.5-4B, zero-shot | 56.3 | – | 34.0 | – | 33.1 | – | 23.6 | – | 59.4 | – |
| + best prompt (rulebook in the prompt) | 56.0 | -0.3 [-6.0, +5.7] | 50.3 | +16.3 | 34.6 | +1.5 | 34.6 | +11.0 | 52.0 | -7.4 |
| + domain adapter + Counterfactual Twin Distillation (short prompt, no pre-checks) | 88.7 | +32.7 [+26.0, +39.3] | 88.3 | +38.0 | 85.2 | +50.6 | 97.4 | +62.8 | 16.2 | -35.8 |
| + code pre-checker (reader v3, trained with 25% blank blocks) | 96.7 | +8.0 [+4.3, +11.7] | 96.0 | +7.7 | 95.1 | +9.9 | 99.5 | +2.1 | 13.7 | -2.5 |
| + post-train: SFT on exact labels (= final model, B2) | 96.3 | -0.3 [-1.7, +0.7] | 95.3 | -0.7 | 93.6 | -1.5 | 99.6 | +0.1 | 13.7 | -0.0 |

## Appendix A. A, B and B2 against the frontier, every test set (decision accuracy %)

A = model alone. B = model + code pre-checker (reader v2), the result before the diagnosis. B2 = final model: pre-checker reader v3, trained with 25% blank blocks, after the diagnosis.

| Model | eval_id (300) | OOD template (50) | OOD hand (50) | OOD LLM (100) | Frozen 500 | Hard (150) | Fresh eval_id v2 (300) |
|---|---|---|---|---|---|---|---|
| A: model alone (Final A) | 88.3 | 84.0 | 82.0 | 94.0 | 88.4 | 85.3 | – |
| B: model + pre-checker v2 (Final B, pre-diagnosis) | 93.0 | 90.0 | 88.0 | 86.0 | 90.8 | 93.3 | – |
| B2: model + pre-checker v3, blank-block training (shipped model) | 96.0 | 94.0 | 92.0 | 92.0 | 94.6 | 92.7 | 96.3 |
| GPT-6 Astra (best prompt) | 99.0 | 100.0 | 100.0 | 99.0 | 99.2 | 99.3 | 99.3 |
| Claude Opus 5.5 (best prompt) | 98.0 | 100.0 | 100.0 | 98.0 | 98.4 | 98.7 | 97.7 |
| Gemini 4 Argon (best prompt) | 94.0 | 100.0 | 98.0 | 98.0 | 95.8 | – | 95.0 |

## Appendix B. Initial benchmark: open and frontier models, zero-shot and best prompt (frozen eval v1, 500 cases)

| Model | Prompt | Params | Decision acc % | Risk exact % | Actions recall % | Screening macro-F1 % | Unsupported claims % (LLM judge) | Schema valid % | $ / 1k cases |
|---|---|---|---|---|---|---|---|---|---|
| GPT-6 Astra | zero-shot | undisclosed | 92.6 | 73.4 | 96.0 | 84.0 | 18.2 | 100.0 | $108.29 |
| GPT-6 Astra | best prompt | undisclosed | 99.2 | 99.2 | 99.4 | 100.0 | 7.3 | 100.0 | $176.17 |
| Claude Opus 5.5 | zero-shot | undisclosed | 87.6 | 77.6 | 93.9 | 89.3 | 18.5 | 100.0 | $75.01 |
| Claude Opus 5.5 | best prompt | undisclosed | 98.4 | 96.0 | 98.1 | 100.0 | 8.3 | 100.0 | $116.67 |
| Gemini 4 Argon | zero-shot | undisclosed | 91.4 | 81.2 | 89.4 | 98.1 | 22.7 | 100.0 | $22.24 |
| Gemini 4 Argon | best prompt | undisclosed | 95.8 | 96.0 | 94.4 | 100.0 | 8.8 | 100.0 | $37.05 |
| Qwen3.5-0.8B | zero-shot | 0.8B | 40.0 | 24.0 | 25.5 | 6.9 | 73.7 | 100.0 | $0.14 |
| Qwen3.5-0.8B | best prompt | 0.8B | 39.6 | 21.6 | 3.7 | 21.4 | 63.6 | 100.0 | $0.12 |
| Qwen3.5-2B | zero-shot | 2B | 29.0 | 29.2 | 49.1 | 38.2 | 64.2 | 99.6 | $0.26 |
| Qwen3.5-2B | best prompt | 2B | 39.4 | 36.2 | 29.4 | 44.3 | 45.9 | 100.0 | $0.20 |
| Qwen3.5-4B | zero-shot | 4B | 60.0 | 34.8 | 38.5 | 25.8 | 59.7 | 100.0 | $0.36 |
| Qwen3.5-4B | best prompt | 4B | 61.2 | 51.6 | 37.2 | 34.7 | 53.1 | 100.0 | $0.44 |

## Appendix C. Model size and distillation ablation (dev, 150 cases; model selection only, never the test sets)

Rejection sampling scored one case higher than Counterfactual Twin Distillation on decision accuracy (a tie within noise); twins was chosen after seeing dev for its required-actions recall and fewest wrong approvals, and that choice is stated as post-hoc.

| Run (dev, 150 cases) | Decision acc % | Risk exact % | Field acc % (mean) | Actions recall % | Screening macro-F1 % |
|---|---|---|---|---|---|
| Qwen3.5-0.8B, trained on the answer key | 84.0 | 84.7 | 97.6 | 79.5 | 100.0 |
| Qwen3.5-0.8B, answer key + Counterfactual Twins | 87.3 | 84.7 | 98.1 | 83.7 | 100.0 |
| Qwen3.5-2B, trained on the answer key | 86.7 | 80.7 | 97.6 | 79.5 | 100.0 |
| Qwen3.5-4B, trained on the answer key (ceiling / control) | 90.0 | 89.3 | 97.7 | 85.3 | 100.0 |
| 4B distillation: floor (Sol answers) | 89.3 | 88.0 | 98.4 | 88.4 | 100.0 |
| 4B distillation: + rejection sampling (code checks) | 91.3 | 90.7 | 98.1 | 84.2 | 97.2 |
| 4B distillation: + multi-teacher arbitration (Sol / Argon) | 90.0 | 89.3 | 98.1 | 86.3 | 100.0 |
| 4B distillation: + Counterfactual Twin Distillation (chosen) | 90.7 | 90.7 | 98.8 | 90.5 | 100.0 |
| 4B: twins on the domain-adapted base | 91.3 | 90.7 | 98.7 | 90.5 | 100.0 |
