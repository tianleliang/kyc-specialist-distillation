# Overnight report: Session D (research for Tianle)

Branch: `claude/upbeat-darwin-vuimz6`. The cloud environment assigned this branch name, so it doesn't contain `overnight-d`; every file it touches is Session D's. Writing only, and **no decisions made**: every judgment call is flagged as a `Q-xx` question.

## Done
| # | Deliverable | File | Notes |
|---|---|---|---|
| 1 | KYC primer (~20 min) | `documentation/02_research/kyc_primer.md` | The analyst workflow; sanctions vs PEP vs adverse media; FATF/EU/UK PEP family and close-associate rules plus how long PEP status lasts; true match vs false positive; partial DOB table; **15-action EDD catalog** with triggers; escalate vs reject; tampering vs OCR noise (MRZ check digits, a signal table, two recipes for the brief's hard cases); PoA recency; a map to the brief's difficulty list. 15 public sources |
| 2 | Draft decision policy | `documentation/02_research/decision_policy_draft.md` | Field-finding rules, screening disposition rules, tamper rules, action triggers, an **11-step precedence decision table**, risk tier (points vs rule table), narrative plan. **27 flagged questions** with a draft default each, indexed in §8 |
| 3 | Schema options | `documentation/02_research/schema_options.md` + `documentation/02_research/schema_options/*.schema.json` + `examples/` | A: brief-mirror nested; B: flat enum codes; C: checks-first scaffold (verifiable sub-facts first, decision last). The portable-subset constraints are explained; 8 cross-cutting questions (evidence_refs granularity, hit IDs, minItems support...) |
| 4 | Distillation options | `documentation/02_research/distillation_options.md` | Shared cost assumptions; each brief technique (SFT floor, rejection sampling, arbitration, hard-case mining, teacher-as-judge, on-policy correction, DPO, GRPO) with cost, time, prior gain and ablation; a proposed **gold-label SFT control**; **4 invented candidates**: Counterfactual Twin Distillation, Field-wise Splice Arbitration, Evidence Knockout, Rendering-Invariance Filtering (+ Error-Surface Resampling as an honorable mention) |

## Not done
- No source documents were downloaded (that's Session A's corpus task). Only 3 of the 15 primer citations (FATF PEP guidance, the FinCEN CDD rule, Wolfsberg sanctions screening) had their URLs checked tonight; the rest are stable official locations from general knowledge. **Check the wording before quoting anything in the write-up.**
- The provider structured-output limits in `schema_options.md` weren't re-checked against live docs (no keys, and no time well spent). Verify when keys are live, especially array `minItems`/`maxItems` support on OpenAI and Anthropic, and key ordering on Gemini.

## Test results
`python -m pytest -q tests/d_schema_options_test.py` → **12 passed**. For each of the 3 schema options, the tests check that it's valid JSON Schema 2020-12, stays in the portable subset (no `$ref`/unions/patterns, every field required, `additionalProperties:false`, ≤5 nesting levels, ≤100 properties), that its example validates, and that broken variants (bad enum, extra key, 3-sentence narrative, missing decision) are rejected.

## Problems
- None blocking. Environment: no API keys (as expected); web search was used only to check citations.
- All cost and gain numbers in `distillation_options.md` are **planning priors**, built from stated assumptions (5k tok/s training on an A100 is a guess). The first real SFT run should replace them.

## Questions for Tianle (the ones that matter most at 07:45 / 08:15)
1. **Q-D1: what triggers `reject` besides a sanctions true match?** Sanctions-only gives ~50% escalate, so an always-escalate baseline scores ~50%. Adding expired ID or tamper evidence balances the classes but is harsher than practice.
2. **Q-0: is the policy text in the prompt?** Draft: in for "best prompt", out for "zero-shot". That gives both brief conditions.
3. **Schema A / B / C (+ Q-SC2: publish scored schema B and serve C ⊇ B?)**
4. **Q-SC3: `evidence_refs` granularity.** Section-level enum works on Zorbe's differently built packets; field-level is checkable by code but can't be an enum.
5. **Q-T1: tamper evidence → escalate or reject?**
6. **Q-P3: PEP true match → escalate, or approve with `senior_management_approval`?**
7. **Q-A1: size of the action enum** (draft: 12 of the 15).
8. **Q-DS1: add a gold-label SFT control row** (cheap; makes the distillation claims falsifiable).
9. **Q-DS4: which invented technique to name.** Twins and Knockout share machinery.
10. Ask Session A to **log the generator knob vector in each truth object** (it enables Error-Surface Resampling and per-category Table 2 breakdowns).
