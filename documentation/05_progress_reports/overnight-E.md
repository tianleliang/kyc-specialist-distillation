# Overnight Report: Session E (decision prep and design)

**Branch:** `claude/kind-planck-ovc0m8`. The cloud environment assigns its own branch name, which doesn't contain the session letter, so this file, the commit messages and the PR title identify the work as **Session E**. No other session needs to read E's branch.
**Scope:** writing only, in `documentation/03_design/`, plus this report. Options and recommendations; **Tianle decides.** No code, no API calls, no files outside E's ownership except this report (as `OVERNIGHT.md` step 6 requires).
**Base:** `main` at `e652c53`.

## Done
| Task | File | Contents |
|---|---|---|
| 1. Decision memos | `documentation/03_design/decision_memos.md` | Six memos (base model, frontier panel and roles with costs, set sizes and API budget, tool-assisted variant, serving, repo sharing), each as question → options → evidence → recommendation → what would change it. One-line summary table at the top |
| 2. Data design | `documentation/03_design/data_design.md` | Latent-truth spec (schema-independent, with invariants: decidability, as-of date, split identity); difficulty taxonomy T0–T11 mapping every brief item to knobs, a PROPOSED label rule, metrics, and a counterfactual twin; case mix; 8 layout families (2 held out); OOD process (LLM-rendered from two families + hand-written templates, with a fact-check gate); 4-stage label audit |
| 3. Contamination protocol | `documentation/03_design/contamination_protocol.md` | Threat model (7 leak paths), splits with disjoint seed ranges, **entity-pool partitioning**, separate configs and prompts, freeze manifest + verify-before-eval, overlap checks table (exact, normalized, truth-level, MinHash, 13-gram, entity, prompt), precise "teachers never see eval" wording, the eval-look budget, render guards, and a Q&A table for defending each point |
| 4. Experiment plan | `documentation/03_design/experiment_plan.md` | Table 1 / Table 2 row definitions, ablation design (cumulative stack + matched-N controls + leave-one-out for the invented technique + paired bootstrap), runs R0–R17 timed against the `02 Plan` blocks with cost and time, cut lines C1–C10, risks |

## Recommendations at a glance (for 07:45)
1. **Base:** Qwen3.5 0.8B/2B/4B. Run the SFT floor on all three and ship the smallest within 2 pts of 4B on dev.
2. **Panel:** baselines Astra / Opus 5.5 / Argon (low effort, plus a small medium-effort check). Teachers: Argon + a GPT model picked on dev (Sol vs Astra, ~$18). Judge: Sonnet, with bias controls. Claude isn't a teacher.
3. **Sizes:** train 3,000 + 1,000 twins; **dev 150 (new: needed so the "best prompt" isn't tuned on eval)**; eval 300 ID + 150 OOD. API ~$410–610 + 20% buffer; all-in ~$650–970.
4. **Tool-assisted variant:** report row only, with a pre-stated promotion bar measured on OOD.
5. **Serving:** always-on Modal L4 **plus a thin proxy** (default system prompt, default `response_format`, thinking off) in case Zorbe's harness sends only the packet.
6. **Repo:** a clean submission repo (no PDF, no vault notes), private + invite. **Weights in a private HF repo + a read token, not public** (public distilled weights contradict our ToS stance).

## Not done
- Nothing in E's list is undone.
- I didn't cross-check against Session D's `documentation/02_research/` drafts (decision policy, schema options, distillation options). They weren't on `main` when I started, so the label rules here are marked PROPOSED and should be reconciled with D's policy draft.
- I didn't check Session A's PROVISIONAL implementation against `data_design.md`; that's for Saturday morning.

## Test results
None: writing-only session. Arithmetic in the cost tables was rechecked by hand (assumption: 4,000 input + 1,200 output tokens per frontier call, prices from `05`; batch at 50%). **Prices and model IDs are unverified** (agent-reported in `05`).

## Problems found (things the current plan doesn't cover)
1. **"Teachers never see eval cases" (`CLAUDE.md`) conflicts with the brief**, which requires the teachers (GPT, Gemini) to run on eval as baselines. Proposed precise wording: no output from any step6_evaluation/dev call ever enters a training file (contamination_protocol §6).
2. **No dev set in the current plan.** Without one, the "best prompt" rows and checkpoint selection are tuned on the test set.
3. **Zorbe's harness may not send our system prompt or `response_format`**, which risks invalid JSON (scored zero) and thinking mode turning on. Proposed fix: the serving proxy plus training with varied or absent system prompts.
4. **Expiry and PoA recency need an as-of date printed in every packet**, or labels depend on the model's notion of "today."
5. **Batch latency (up to 24h) vs the Saturday timeline.** Teacher tranche 1 goes live; tranche 2 and **the twins batch must be submitted by ~15:00 Saturday**, which means deciding the invented technique earlier than the plan's "Saturday night."
6. **All API spend is out of pocket during the case.** The budget in Memo 3 is sized for that.
7. **OCR-noise vs tampering needs a decidable rule.** Proposed: the MRZ is authoritative; a digit→digit disagreement in a numeric field, or a failed check digit, means escalate; letter↔digit confusions with valid checksums are noise. Session A's noise model must then never produce digit→digit substitutions in numeric fields.

## Questions for Tianle
Collected from the docs' "Open questions" sections. The most decision-relevant:
1. Approve the precise "teachers never see eval" wording (contamination §6)?
2. Expired ID, PoA mismatch, tampering, injection: **escalate or reject** for each? (PROPOSED: escalate for all four, plus the matching action.)
3. Expiry finding value: reuse `mismatch` or add `expired`?
4. PoA recency window: 90 or 180 days?
5. Frontier reasoning effort for the baselines: low (spend) vs medium (fairness)? Proposal: low + a 100-case medium check.
6. The invented technique: decide by **15:00 Saturday** (twins need a batch submission then).
7. Who writes the O2 hand templates for OOD (ideally Tianle, ~45 min)?
8. Headline: lead the write-up with OOD or ID numbers? (Recommendation: show both, lead with the lower.)
