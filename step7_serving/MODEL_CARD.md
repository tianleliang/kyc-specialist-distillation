---
license: apache-2.0
base_model: Qwen/Qwen3.5-4B
tags: [kyc, aml, onboarding, distillation, synthetic-data]
---
# KYC specialist (Qwen3.5-4B), shipped model B2

A 4B specialist for KYC onboarding adjudication: one case packet in, one JSON decision out (schema v1, policy v1). Built for the Zorbe take-home.

- **Base:** Qwen/Qwen3.5-4B (Apache 2.0: commercial use and derivative weights allowed).
- **Pipeline:** domain adapter on public KYC/AML text (merged) → Counterfactual Twin Distillation from frontier teachers (GPT-6.1 Sol, Gemini 4 Argon arbitrated) → SFT post-train on exact synthetic labels. All training data is synthetic.
- **Must be served with the code pre-checker** (`step7_serving/prechecks.py`, reader v3): the proxy appends a `PRE-CHECKS` block (as-of date, MRZ check digits, expiry, proof-of-address age, document-integrity class) to each packet, and the model was trained with it. Use `step7_serving/proxy.py` with `ZORBE_PRECHECKS=1`, the `student_short` prompt and `step0_rules/schema/v1_serving.json`.
- **Adapters** (`adapters/`): `domain_adapter` (LoRA on Qwen/Qwen3.5-4B), `stage3_distillation` (LoRA on Qwen3.5-4B + merged domain adapter), `stage4_posttrain` (LoRA on the merged stage-3 model). Merging the three in order reproduces these weights.
- **Results, code, data and the write-up:** https://github.com/tianleliang/kyc-specialist-distillation
- Synthetic data only; not for production use without the shadow-and-ramp process described in the write-up.
