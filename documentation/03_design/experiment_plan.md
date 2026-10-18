# Experiment Plan: Saturday and Sunday Run List

**Status:** DRAFT from overnight Session E. Assumes the **recommendations** in `decision_memos.md` (Qwen3.5 0.8B/2B/4B; Astra/Opus/Argon baselines; Argon + one GPT teacher; set sizes from Memo 3). If Tianle decides differently at 07:45, the run *order* and *cut lines* still hold; swap the model names and costs.
**Times** are Eastern and slot into the `02 Plan` timeline. **GPU times are estimates**: replace them with Saturday's measured throughput after the first training run (R7) and re-check the cut lines.

---

## 0. What the runs must produce

**Table 1 (models × metrics, eval-ID and eval-OOD columns, case counts):**
| Row group | Rows |
|---|---|
| Open baselines | Qwen3.5-0.8B / 2B / 4B × {zero-shot, best prompt} = 6 rows (+ optional 9B zero-shot ceiling) |
| Frontier panel | Astra / Opus 5.5 / Argon × {zero-shot, best prompt} = 6 rows (+ optional Fable best-prompt) |
| Floors | Always-escalate; majority class (trivial, computed, $0) |
| Ours | Final shipped model (+ optional tool-assisted row) |

**Table 2 (stage deltas on the chosen size, cumulative stack):**
| Row | Stage (brief numbering) | What changes |
|---|---|---|
| S0 | 1 Base | Chosen size, best prompt |
| S1 | 2 Domain adapter | + continued-pretraining LoRA on `step3_domain_adapter/corpus/` (then SFT floor on top; see R8) |
| S2 | 3 Floor | + SFT on raw teacher answers (one Argon sample per case, unfiltered) |
| S3 | 3 Technique 1 | + rejection sampling against programmatic checks |
| S4 | 3 Technique 2 | + multi-teacher arbitration |
| S5 | 3 Invented | + counterfactual twins (name TBD; Tianle decides Saturday night) |
| S6 | 3 Technique 3 (Tier 2) | + on-policy correction / hard-case mining |
| S7 | 4 Post-train (Tier 2) | + DPO on programmatic preference pairs |
| S8 | (Tier 3) | + tool-assisted pre-checks |

**Ablation design:**
- **Cumulative stack** (each row = previous + one change) is the main table. It's cheap (one run per row), but the order matters, so state the order as a limitation.
- **Matched-N controls** for the data-filtering techniques. Rejection sampling and arbitration *shrink* or *reshape* the dataset, and twins *add* data. Without controls, a gain could just be more or fewer examples. For S3–S5, also train a **size-matched control** (same number of examples, drawn without the technique) and report technique − control. That's ~3 extra cheap runs.
- **Leave-one-out for the invented technique:** final − twins. This is the claim reviewers will probe hardest.
- **Variance:** one seed per row by default. For the two key deltas (S2 → final, and twins vs its matched control), run **2 seeds** if Sunday allows and report the spread. All deltas get **paired-bootstrap 95% CIs** (`step6_evaluation/report.py`).
- **Selection on dev, reporting on eval:** every row's choices (epochs, learning rate, checkpoint) are fixed on dev; each row hits eval exactly once (`contamination_protocol.md` §7).

---

## 1. Ordered run list

Columns: **When** · **Run** · **Inputs** · **Est. time** · **Est. cost** · **Fills** · **Notes**.

### Saturday 10/17

| # | When | Run | Inputs | Est. time | Est. cost | Fills | Notes |
|---|---|---|---|---|---|---|---|
| R0 | 10:00–12:30 (parallel) | Deploy the **base** chosen-family model to the Modal endpoint behind the proxy; run the outputs-differ harness with base vs base (should be identical) | Session B's `step7_serving/` | 1h | ~$2 | Engineering (endpoint up early) | The proxy rehearsal: default system prompt + default `response_format` (Memo 5) |
| R1 | 13:00 | **Label pilot**: 3 frontier models zero-shot on 100 dev cases; bucket disagreements; fix rules | dev, v0 prompt | 30 min + fixes | ~$16 | Label audit Stage A | Doubles as the first zero-shot dev numbers |
| R2 | 13:30–14:00 | **Hand checks** (20) + **freeze eval** (manifest, git tag, `split_guard verify-freeze`) | eval-ID 300, OOD 150 | 45 min | ~$10 (OOD rendering) | Contamination | Nothing scores against eval before R2 |
| R3 | 14:00–15:00 | **Teacher pick + prompt iteration on dev**: Sol vs Astra on 150 dev; 3 prompt rounds × 3 frontier models × 100 dev; best prompt for the open models on dev (vLLM) | dev | 1h (live, parallel) | ~$66 + ~$3 GPU | Best-prompt rows (selection) | Choose the GPT teacher by the Memo 2 rule |
| R5 | 14:15 | **Teacher tranche 1, live**: 1,000 train cases, Argon k=2 + GPT k=1 | train[0:1000] | ~1–2h (rate limits) | ~$60 (Sol) / ~$140 (Astra) | Training data for R7+ | Start as soon as the teacher prompt is fixed; it can use the R3 round-1 prompt |
| R6 | 15:00 | **Submit batches**: teacher tranche 2 (2,000 cases) + **twins** (1,000 cases) for Argon and GPT | train[1000:3000], twins | returns 1–24h | ~$80 (Sol) / ~$200 (Astra) | S5 and full-size rows | **Submit the twins now**, not Saturday night; batch latency is the risk |
| R4 | 15:00–17:00 | **Table 1 baselines on eval**: 3 frontier × {zero-shot, best} live (with latency); 3 open sizes × {zero-shot, best} on vLLM | frozen eval, final prompts | 2h (parallel) | ~$144 + ~$5 GPU | **Table 1** baseline rows; **the curve** (zero-shot, best prompt) | Prompts are frozen at the R3 result; one eval run each |
| — | 17:00–17:30 | **Checkpoint**: label audit Stage C on R4 outputs; sanity-check Table 1 (oracle 100%, always-escalate as expected) | R4 outputs | 30 min | $0 | Label audit | A rule bug → v1.1 re-projection, disclosed |
| R7 | 17:30–19:30 | **SFT floor at all 3 sizes** (16-bit LoRA, Unsloth) on tranche 1 (one Argon sample per case, unfiltered); eval on **dev** | tranche 1 | 0.8B ~25 min on L4; 2B ~20 min, 4B ~30 min on A100-80 (+~10 min overhead each); evals ~10 min each | ~$4 | **The post-SFT curve**; size selection (Memo 1 rule) | Run the three in parallel as separate Modal functions. **Merge + outputs-differ check** on the 2B before trusting any number |
| R8 | 17:30–20:00 (parallel) | **Domain adapter**: continued-pretraining LoRA on `step3_domain_adapter/corpus/` (chosen or 2B size), then the SFT floor on top; eval on dev. Also held-out corpus perplexity before and after | `step3_domain_adapter/corpus/`, tranche 1 | ~1.5h | ~$4 | **S1** | "Evidence it moved something": perplexity drop *and* task delta. A null result is reported as null |
| — | 19:30 | **Size decision** (Tianle): apply the Memo 1 rule to R7 dev numbers | R7 | 15 min | — | Decision log | From here on, all runs use the chosen size |
| R9 | 20:45–22:00 | **Rejection sampling (S3)**: keep teacher samples that pass the programmatic checks (schema valid; decision, dispositions, field findings, risk tier exact; actions ⊇ required; every narrative `evidence_ref` resolves to packet text); SFT; plus a **matched-N control** | available teacher data | ~1h | ~$2 | **S3** | If a case has no passing sample, it drops out. Log the drop rate per tag (it shows where teachers fail) |
| R10 | 22:00–23:00 | **Multi-teacher arbitration (S4)**: per case, choose among Argon×2 + GPT×1 by (1) structured-field agreement with the answer key, (2) narrative grounding score, (3) teacher priority; when *all* teachers fail the key on a structured field, keep the case only if the field can be **corrected programmatically** from the label (the narrative stays the teacher's, re-checked for grounding); SFT + matched-N control | teacher data | ~1h | ~$2 | **S4** | Clarify the difference from S3 in the write-up: S3 filters *samples*, S4 resolves *disagreement across teachers* and repairs fields |
| R11 | 23:00–00:00 (queue overnight) | **Counterfactual twins (S5)**: keep a teacher's output pair only if it gets **both** twins right (the decision flips correctly); add the twin pairs to the S4 data; SFT + **matched-N control** (the same number of extra non-twin cases) | twins batch from R6 | ~1h train (+ waiting on batch) | ~$2 | **S5** | If the twins batch isn't back, queue this for overnight with a Modal timeout and auto-shutdown |
| — | 00:00 | **Overnight queue (optional, no human needed)**: if tranche 2 returned, re-run S2–S5 on the full 3,000 cases with fixed hyperparameters; eval each on dev only | | ~3h unattended | ~$8 | Full-size Table 2 | Each job auto-exits; nothing stays warm. **No eval-set runs overnight** |

### Sunday 10/18

| # | When | Run | Inputs | Est. time | Est. cost | Fills | Notes |
|---|---|---|---|---|---|---|---|
| R12 | 07:30–09:00 (Tier 2) | **On-policy correction / hard-case mining (S6)**: run the best model on 1,000 train cases (not dev); collect errors; Argon corrects them (live, given packet + student output + policy, never the label); keep corrections that pass the R9 checks; also generate 500 new cases from the **tags with the highest dev error**; SFT | best model so far, train | ~1.5h | ~$20 API + ~$3 GPU | **S6** | If the time is short, do mining only (no API) and drop correction |
| R13 | 09:00–10:30 (Tier 2) | **DPO (S7)**: pairs = (chosen: an output passing the programmatic checks; rejected: the student's own failing output on the same case) from R12 sampling; DPO from the best SFT checkpoint; eval on dev | R12 samples | ~1h | ~$4 | **S7** = stage 4 "post-train" | Stage-4 rationale for the write-up: "the schema and labels give a free verifier, so preferences come from code, not a judge." If DPO hurts on dev, ship SFT and report the negative result |
| — | 10:30 | **Final model choice on dev** (Tianle); freeze | | 15 min | — | Decision log | Dev picks, eval reports |
| R14 | 10:30–11:00 | **Final eval** of every Table 2 row not yet on eval + the final model, eval-ID + OOD, **once each**; log in RUNLOG | frozen eval | 30 min | ~$3 | **Table 1** "ours", **Table 2** | |
| R15 | 10:30–11:30 (parallel) | **Serve final**: merge → upload to the HF private repo → deploy → **outputs-differ check vs base** → load test 200 dev packets at concurrency 1 and 8 for p50/p95 and throughput → cost per 1k | final weights | 1h | ~$2 | Endpoint; Table 1 latency/cost columns | Latency on dev packets keeps eval untouched |
| R16 | 11:00 (batch) | **Narrative judge** on all Table 1 rows (Sonnet batch) + Opus calibration (200) + Argon cross-judge (100) | R4 + R14 outputs | <1h (Anthropic batch) | ~$30 | Unsupported-claims column | Submit the baseline judging Saturday night to spread the load |
| R17 | 11:00 (Tier 3, only if all above done) | Tool-assisted row; GRPO; 9B ceiling; Fable best-prompt; medium-effort frontier subset | | — | ≤$80 | Optional rows | Each one is independent; cut any of them freely |
| — | 11:00–13:30 | `python -m step6_evaluation.report outputs/` → Table 1, Table 2; reproduction commands from a clean clone | | | | Deliverables | **No new experiments after 14:00** |

**Totals (recommended path, Sol teacher):** API ~$410 + buffer; GPU training/eval ~$35–50; serving ~$135–175 for the 7 days.

---

## 2. Cut lines (if time slips)

Each cut line is a time, a test and what gets dropped. **The endpoint, the frozen eval and Table 1 are never cut.**

| ID | When | If… | Then cut / change |
|---|---|---|---|
| C1 | Sat 14:30 | Eval isn't frozen | Shrink to 200 eval-ID + 100 OOD (O2 hand templates may become 0; keep O1). Freeze by 15:00 at the latest |
| C2 | Sat 17:30 | Tranche 1 teacher data isn't in | Floor on whatever has returned (≥500 cases) from Argon only; GPT joins at S4 |
| C3 | Sat 20:00 | No SFT floor evaluated on dev yet | **Drop the domain adapter (S1) and DPO (S7)**. Table 2 = S0, S2, S3, S4, S5 |
| C4 | Sat 23:00 | Tranche 2 batch not returned | All Table 2 rows stay on the 1,000-case set; say so |
| C5 | Sat 23:00 | Twins batch not returned | Generate twins live for 300 pairs (600 cases × Argon + Sol, ~$24) and run S5 at a reduced N, with the control matched to that N |
| C6 | Sun 09:00 | S6 not done | Drop on-policy correction; keep mining only if it's already running |
| C7 | Sun 10:30 | DPO unstable or worse on dev | Ship the best SFT; report DPO as tried-and-failed (the brief rewards honesty about failures) |
| C8 | Sun 11:00 | Any Tier-3 item not done | Cut it. **Final model frozen at 11:00 regardless** |
| C9 | Sun 13:30 | Judge runs incomplete | Report the programmatic `evidence_refs` metric for all rows + the judge on a labeled subset |
| C10 | Sun 14:00 | — | Experiments end. Write-up only after this |

**The minimum honest submission** (if everything slips): Table 1 with baselines + the SFT floor + one technique (rejection sampling, which needs no extra API calls) + the endpoint. That meets "floor + 2 techniques" only if arbitration (also API-free, given tranche 1 has two teachers) runs too. **Protect R9 and R10**, because they're cheap and they're the minimum the brief asks for.

---

## 3. Risks to the plan

| Risk | Early signal | Mitigation |
|---|---|---|
| OpenAI/Gemini batch latency (up to 24h) | Batch status at 18:00 still "in progress" | C4/C5; tranche 1 live; twins submitted at 15:00, not at night |
| Rate limits on new accounts (`05` §5) | 429s during R1 | Spread over the providers; buy a tier bump ($100 OpenAI) if it blocks R4 |
| Qwen3.5 tooling (LoRA no-op in vLLM, no QLoRA) | Outputs identical to base in R7's outputs-differ check | Merged weights only; fall back to Qwen3 (Memo 1) after 45 min |
| Teacher accuracy low on some tags | High R9 drop rate on a tag | That's a finding: report it per tag; mining (R12) targets it |
| Label bugs found late | Frontier models all disagree on one tag | Rule-level fix + v1.1 re-projection (data_design §6) |
| Overfitting to our layouts | Large seen/unseen-layout gap, or OOD ≪ ID | Prompt-free training mix; more layout variety in S6 mining; lead the write-up with OOD |
| GPU left running | Modal dashboard | Every job has a timeout; R15 serving is the only always-on container; check the dashboard at 00:00 and 14:00 |

---

## 4. Open questions for Tianle
1. Accept the **cumulative order** S1 → S7? (An alternative is S2 → S5 before S1, since the adapter is the least likely to help; putting it first is closer to the brief's numbering.)
2. **Matched-N controls**: ~3 extra cheap runs. Worth it? (Recommendation: yes. "What each technique bought" isn't answerable without them.)
3. **S4 field repair**: correcting a teacher's structured field from the answer key while keeping its narrative. Is that still "black-box distillation" in spirit? (It's a common hybrid; disclose it. The alternative is to drop such cases.)
4. **The invented technique's name and final form** (twins, or another from Session D's `distillation_options.md`): decide by Saturday 15:00, because R6 needs the twins submitted then.
