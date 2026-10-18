# Decision Memos for the 07:45 Sprint

**Status:** DRAFT options and recommendations from overnight Session E. **Tianle decides.** Nothing here is logged as a decision until it's in `03 Zorbe Decision Log.md`.
**Inputs:** the brief PDF, `documentation/00_case_brief_and_plan/00`–`05`, `documentation/06_agent_instructions/OVERNIGHT.md`. Prices and model IDs come from `05 Research Brief` and are **agent-reported, not verified**. Check them in the provider consoles before spending.
**Companion docs:** `data_design.md`, `contamination_protocol.md`, `experiment_plan.md` (same folder).

There are six memos, one per decision. Each has the same layout: **Question → Options → Evidence → Recommendation → What would change it.** The table below summarizes them.

| # | Decision | Recommendation (one line) |
|---|---|---|
| 1 | Base model family and sizes | Qwen3.5 0.8B / 2B / 4B; run the SFT floor on all three before choosing; ship the smallest within ~2 pts of 4B |
| 2 | Frontier panel and roles | Baselines: GPT-6 Astra, Claude Opus 5.5, Gemini 4 Argon. Teachers: Argon + one GPT model (chosen by the dev set). Judge: Claude. ~$410–610 API spend before buffer |
| 3 | Set sizes and API budget | Train 3,000 (+1,000 counterfactual twins), dev 150, eval 300 in-distribution + 150 OOD. API cap $650, plus a $100 reserve |
| 4 | Tool-assisted variant | **Report row only** (Tier 3). Ship it only if it clears a pre-stated bar on the **OOD** set by Sunday 11:00 |
| 5 | Serving plan | Always-on Modal L4 (`min_containers=1`) with a thin proxy in front of vLLM; ~$135–175 for the 7-day window |
| 6 | Repo sharing | Clean submission repo (fresh history, no PDF, no vault notes), private plus collaborator invite; **weights not public** |

Cost math used throughout: one frontier call ≈ **4,000 input + 1,200 output tokens** (system prompt with policy and schema ~2k, packet ~2k; JSON ~700 plus low reasoning ~500). Per call, at list price: Astra or Fable **$0.10**; Opus 5.5 **$0.04**; Sonnet 5.5, GPT-6.1 Sol or Argon **$0.02**; Gemini 3.8 Flash **$0.0075**. Batch is half price. **The biggest uncertainty is reasoning tokens.** At medium effort the output can triple, and so can the cost of the output-heavy models.

---

## Memo 1: Base model family and sizes

**Question.** Which open-weight family, and which ≥3 sizes, give us the curve and the shipped model?

**Options**
| Option | Sizes | Pros | Cons |
|---|---|---|---|
| **A. Qwen3.5** | 0.8B / 2B / 4B (9B optional as a ceiling point) | Apache 2.0 (commercial use and derivatives allowed); ungated; one family with ~2× steps, so a clean curve; a June 2026 precedent of LoRA on structured financial extraction (F1 94.8 / 95.2 / 96.6 at 0.8 / 2 / 4B) | Newer tooling: **no QLoRA** (accuracy loss), LoRA adapters can **silently no-op in vLLM** (so serve merged weights), and thinking mode must be off |
| B. Qwen3 | 0.6B / 1.7B / 4B | Mature tooling; same license | Slightly older and likely a little weaker per parameter; a "why not the newer one?" question |
| C. Gemma 4 | Awkward size spread | A second family for robustness | Gemma license terms need a separate check; the sizes don't give a clean curve |
| D. Llama 3.2 | 1B / 3B | Well known | Gated (access delays), restrictive license; ruled out in `05` |

**Evidence.** The brief rewards "the smallest open model that can plausibly carry the task" and says "a 1B model with a sharp pipeline and honest numbers beats a 7B model with vanilla fine-tuning." The task is narrow, structured and largely rule-checkable, which is where small models close the gap. Zero-shot scores of 0.8–2B models on a 6-part JSON task will likely be poor and noisy, so **a choice made from zero-shot numbers alone would be weakly grounded.**

**Recommendation.** **Option A**, with one change to the selection method:
1. Benchmark all three sizes zero-shot and with the best prompt (required by the brief).
2. Also run the **SFT floor on all three sizes**. It's cheap: 0.8B and 2B on an L4 or A100 cost a few dollars each (see `experiment_plan.md`). This gives a *post-training* curve, which is the curve that actually justifies the choice.
3. **Selection rule (state it in advance, in the write-up):** ship the smallest size whose SFT-floor decision accuracy on the **dev** set is within 2 points of the 4B's *and* whose schema validity is ≥99%. If none qualifies, ship 4B and say why.
4. Optional: one zero-shot run of 9B as a ceiling point on the curve (~$2 of GPU), never trained.

Expect 2B to be the shipped size; 0.8B is a real chance for an "it carries the task" headline.

**What would change it.** Qwen3.5 tooling still failing after 2 hours (the 45-minute rule per blocker) → switch to Option B with the same selection rule. If 0.8B ties 2B on dev, ship 0.8B (cheaper serving, stronger story). If even 4B can't reach schema validity with constrained decoding, re-examine the schema (nesting) before blaming the model.

---

## Memo 2: Frontier panel and each model's role

**Question.** Which three frontier models, and which of them act as baseline, teacher or judge?

**Constraints already in force.** `CLAUDE.md`: **Claude is baselines and judging only** (low volume). `05`: Anthropic's distillation-detection classifier (announced Oct 12) makes bulk teacher calls from a new account risky. Decision #4: **out of pocket, ~$500–1k total budget**; the YC credits arrive after the deadline.

**Options for roles**
| Role | Option | Cost driver | Notes |
|---|---|---|---|
| Baseline (Table 1) | **Astra + Opus 5.5 + Argon** | 900 live calls each (450 eval × 2 prompts): **$90 + $36 + $18 = $144** | Run live, not batch: Table 1 needs their **latency** too, and OpenAI/Gemini batches can take 24h |
| | Swap Opus → Fable 5.1 | +$54 | Fable is Anthropic's top tier. It pre-empts "you didn't beat the best Claude," at +$54 |
| | All mid-tier (Sol / Sonnet / Flash) | ~$45 total | Too weak a panel: "beats the frontier" stops meaning much. **Not recommended** |
| Teacher (bulk) | **Argon k=2 + GPT Sol k=1** (all batch) | 6,000 × $0.01 + 3,000 × $0.01 = **$90** ($120 with the first 1,000 cases live) | Argon is a flagship at mid-tier price, the best value teacher. Two families support multi-teacher arbitration |
| | Argon k=2 + **GPT Astra** k=1 (all batch) | $60 + $150 = **$210** ($280 with the first 1,000 live) | A stronger second teacher, at +$120–160 |
| | Claude as teacher | — | Excluded by `CLAUDE.md` and ToS risk |
| Judge (unsupported claims) | **Claude Sonnet 5.5** primary (batch) + Opus on a 200-case calibration subset | ~$24 + ~$4 | A Claude judge on Claude's own baseline rows risks **self-preference bias**. Mitigation: report judge agreement against a second judge (Argon) on 100 cases, and use the programmatic `evidence_refs` check as the primary metric |

**Recommendation.**
- **Baselines:** GPT-6 Astra, Claude Opus 5.5, Gemini 4 Argon, each **zero-shot and with the best prompt**, at **low reasoning effort**. Also run **Fable 5.1 best-prompt only** if the budget allows (+$45 for 450 calls).
- **Teachers:** Argon is the primary teacher (k=2 samples per case for rejection sampling). For the second teacher, **run both Sol and Astra on the 150-case dev set (~$18)** and choose by dev score: Astra only if it beats Sol by ≥3 points on decision accuracy. A data-driven, cheap choice that makes a good write-up line.
- **Judge:** Sonnet 5.5, with the bias controls above.

**Estimated API spend under the recommendation** (details in Memo 3): **~$410 (Sol teacher) to ~$610 (Astra teacher)**, before a 20% reasoning-token overrun buffer.

**The fairness question to decide explicitly: reasoning effort for the baselines.** `CLAUDE.md` says to keep reasoning low for spend. But a reviewer can say "you beat a hobbled frontier." Proposal: run the panel at **low** effort as documented, plus **one medium-effort run of the best-prompt Astra and Opus on a 100-case subset** (~$30 extra) to show how much effort buys. Report that row honestly whichever way it goes.

**What would change it.** Rate limits (`05` §5): if OpenAI is stuck in a low tier, either Gemini carries the teacher volume alone (arbitration then becomes Argon-vs-Argon samples plus the answer key, which is a weaker story), or we buy $100 of OpenAI credit to move up a tier. If Anthropic's eval tier caps spend at $500/month, the recommended Claude spend (~$90) still fits.

---

## Memo 3: Train/eval set sizes and the API budget

**Question.** How many cases go in each split, and what's the API spend cap?

**Statistical evidence.** At ~85% decision accuracy, the 95% CI half-width is about **±4.0 pts at n=300**, **±5.8 at n=150** and **±3.3 at n=450**. Per-difficulty slices are much noisier: with 30 cases per slice the interval is ±13–16 pts. Paired comparisons (same cases, two models) are tighter than these unpaired numbers, so `step6_evaluation/report.py` should use a **paired bootstrap for deltas** (Table 2).

**Options**
| Option | Train | Dev | Eval in-dist | Eval OOD | Frontier eval cost | Comment |
|---|---|---|---|---|---|---|
| S | 1,500 | 100 | 200 | 100 | ~$96 | Cheapest; CIs too wide to rank the panel |
| **M (plan)** | **3,000 + 1,000 twins** | **150** | **300** | **150** | **~$144** | Matches the plan; ±4 pts on the main number |
| L | 6,000 | 200 | 600 | 300 | ~$288 | Tighter, but doubles labeling, teacher and audit time on a 2-day clock |

**Recommendation: Option M**, plus three rules:
1. **A dev set exists and is separate from eval.** "Best prompt" and checkpoint selection are tuned on dev only. Without it, the "best prompt" row is tuned on the test set. That's the most likely contamination question we'll get.
2. **Stratify eval so each "what makes it hard" item has ≥30 cases** (cases carry several tags, so 300 cases can cover 11 tags at ≥30 each; see `data_design.md`).
3. **Teacher data in two tranches:** the first 1,000 train cases go **live** (so the SFT floor can start Saturday ~17:30, not whenever a 24-hour batch lands); the remaining 2,000 plus the twins go through batch.

**Proposed API budget (cap $650, reserve $100)**
| Line | Calls | Sol-teacher variant | Astra-teacher variant |
|---|---|---|---|
| Baselines on eval (3 models × 450 × 2 prompts, live) | 2,700 | $144 | $144 |
| Prompt iteration on dev (3 models × 100 × 3 rounds) + teacher pick on dev | ~1,200 | $66 | $66 |
| Teacher data, 3,000 cases (Argon k=2, GPT k=1; first 1,000 cases live) | 9,000 | $120 | $280 |
| Counterfactual twins, 1,000 cases (Argon + GPT, batch) | 2,000 | $20 | $60 |
| On-policy correction, 1,000 student mistakes (Argon, live) | 1,000 | $20 | $20 |
| Narrative judge (Sonnet batch) + Opus calibration | ~5,600 | $28 | $28 |
| OOD packet rendering (~200 calls, two renderers) | 200 | $10 | $10 |
| **Subtotal** | | **~$410** | **~$610** |
| Reasoning-overrun buffer (20%) | | $80 | $120 |
| Optional: Fable best-prompt row; medium-effort subset | | +$45; +$30 | +$45; +$30 |

Add GPU (training ~$25–65, serving ~$135–175) and **the total lands at ~$650–970**, inside the $500–1k budget from decision #4. **Guardrail:** `shared/frontier_api/clients.py` (Session F) should enforce a hard per-provider dollar cap from config and refuse calls past it.

**What would change it.** Frontier panel agreement with the labels below ~80% on the pilot → the label policy is ambiguous: fix the policy, don't add data. SFT learning curve flat between 1k and 3k → skip the extra 2,000 and put the money into twins and hard-case mining.

---

## Memo 4: Tool-assisted variant (code pre-checks MRZ and dates)

**Question.** Should a deterministic pre-processor (MRZ check digits, MRZ↔visual-zone field comparison, DOB/expiry/PoA-date arithmetic against the packet's as-of date) feed hints into the model? If so, is that the **shipped** model or just **a row in the report**?

**Options**
| Option | Description | Upside | Risk |
|---|---|---|---|
| **A. Report row only** | Build it if time allows; it appears in Table 1 / Table 2 as "+ tools" | Shows the idea; no risk to the endpoint | Leaves points on the table if it's large |
| B. Ship it | A proxy in front of vLLM runs the checks and appends a `PRECHECKS` block to the prompt | The checks small models get wrong (checksums, date arithmetic) become ~free and exact | **Zorbe's hidden set is built by a different process.** A parser tuned to our layouts may misparse theirs and feed confident *wrong* hints, which is worse than no hints. Also adds a component that can fail during the 7 days |
| C. Skip | — | Saves ~2–3 hours | Loses a natural "what would we do in production" story |

**Evidence.** The brief says "Focus on the result, even if you have to stray from the exact architecture," so tools are permitted. But the score is judged on **their** hidden set, and our pre-checker has only ever seen our formats. MRZ lines are standardized (ICAO 9303) and parse robustly. Visual-zone dates and names are not. For fairness, the frontier rows should get the same hints in a "+ tools" variant, or the comparison is apples to oranges.

**Recommendation.** **A (report row only), Tier 3**, with a pre-stated promotion bar. Ship it only if **all** hold by Sunday 11:00:
1. It improves decision accuracy by ≥3 pts on the **OOD** set (not just in-distribution);
2. It is no worse on any Table 1 metric on OOD;
3. The parser **abstains** (emits no hint) when it can't parse, and a test shows that a garbled packet produces no hints rather than wrong ones;
4. The proxy it rides on is already built for Memo 5 anyway.

Limit the pre-checker to MRZ parsing and check digits, MRZ↔VIZ comparison and date arithmetic. Don't do name matching in code; that's the model's job.

**What would change it.** If the student is weak specifically on checksums and dates (visible in per-field accuracy on Saturday night) *and* the OOD set confirms the parser generalizes, promote it to Option B. If the proxy isn't built, stay at A.

---

## Memo 5: Serving plan

**Question.** How do we keep an OpenAI-compatible, bearer-token endpoint up for 7 days with "first request works," and measure p50/p95 and cost per 1k cases?

**Options**
| Option | Cost (7–9 days) | Cold-start risk | Ops burden |
|---|---|---|---|
| **A. Modal L4, always on** (`min_containers=1`, vLLM, merged weights in a Volume) | ~$135–175 | None while warm | Low; one Python file |
| B. Modal scale-to-zero + scheduled keep-warm ping | ~$20–60 | **Real.** vLLM cold start is likely 30–120s; a reviewer's first `curl` may time out. The brief names "first request works" explicitly | Low |
| C. RunPod L4 pod | ~$99/week | None | A second platform to learn; manual restarts |
| D. AWS (YC $10k credits) | ~$0 out of pocket | None | GPU quota approval may take days; only if approved before Sunday |

**Two issues found that the current plan doesn't cover:**
1. **Zorbe's harness may not send our system prompt or our `response_format`.** If they send only the packet, an unconstrained 2B model may emit invalid JSON (scored zero), and thinking mode may switch on by the chat template's default. **Fix: a thin proxy** (FastAPI, same Modal app) in front of vLLM that (a) checks the bearer token, (b) inserts our default system prompt when none is given, (c) adds our `response_format: json_schema` when absent, (d) forces thinking off, and (e) logs latency. Also train with a mix of no or varied system prompts so the model doesn't depend on ours. The proxy is also where Memo 4's pre-checks would live.
2. **Cost per 1k cases depends on load.** Report two numbers: **marginal** (at measured throughput with concurrent requests: GPU $/h ÷ cases/h) and **dedicated** (the always-on daily cost ÷ the cases actually served). The brief asks for cost "at that latency," so report marginal cost at the concurrency where p95 was measured, and state the concurrency.

**Recommendation.** **Option A plus the proxy**, `max_containers=2` for bursts if Zorbe runs their whole hidden set at once (one L4 should handle a 2B model at moderate concurrency; cap concurrency and measure). Add a health check and an external uptime ping that alerts Tianle's phone. If AWS quota lands before Sunday 11:00, consider moving serving there; otherwise don't migrate under deadline. **Scale-down date: 2026-10-25** (calendar reminder; `CLAUDE.md` says never leave a GPU running).

**What would change it.** Measured cold start <10s (unlikely with vLLM) → Option B is acceptable. Endpoint instability on Modal during Saturday testing → RunPod as a warm standby.

---

## Memo 6: Repo sharing (and the weights bucket)

**Question.** How do Zorbe get the repo, given the brief PDF is confidential and is in git history? And where do the weights go?

**Facts.** `CLAUDE.md`: the repo stays private; never public while the PDF is in history. `documentation/00_case_brief_and_plan/` also holds **personal vault notes** (spend, account and ToS discussion, references to other projects) that weren't written for Zorbe. The brief: "Weights and adapters in a bucket we can download." `05`: the frontier ToS bars training *competing* models on outputs; our stated position is research and evaluation only, not distributed beyond the evaluation.

**Options: repo**
| Option | How | Pros | Cons |
|---|---|---|---|
| A. Private repo + collaborator invite | Invite Zorbe's GitHub handles | Simple; matches `CLAUDE.md` | Needs their handles (ask now, in the reply chain); the reviewer sees the PDF and the vault notes in history |
| **B. Clean submission repo** (private + invite, or public) | Export the working tree to a fresh repo: no PDF, no `documentation/00_case_brief_and_plan/`, no `documentation/06_agent_instructions/OVERNIGHT.md` | No confidential or personal material; a curated first impression; can even be public | ~30 min of work; history isn't preserved (we can say so, and keep the full repo for audit on request) |
| C. Scrub history (`git filter-repo`) and publish | Rewrite history | Keeps the commit trail | Easy to get wrong; force-push risk; the vault notes still need judging line by line |

**Options: weights**
| Option | Pros | Cons |
|---|---|---|
| Public HF repo (the current `05` default) | "Works without our login" | **Publishing frontier-distilled weights publicly contradicts our "not distributed" ToS stance** |
| **Private HF repo + a fine-grained read-only token in the email** | Downloadable with one token; revocable after evaluation | Not literally login-free, but token-free browsing isn't required by the brief |
| S3/GCS presigned URL | No account needed | Max 7-day expiry on S3 presigned URLs, so it needs re-issuing |

**Recommendation.** **Repo: B**, a clean private submission repo with a collaborator invite (ask Zorbe for handles in the reply thread on Saturday so the invite isn't blocked on Sunday night). Keep this working repo private as the audit trail. **Weights: private HF repo + a scoped read token**, revoked after evaluation, with the license and the distillation caveat stated in the write-up.

**What would change it.** If Zorbe can't take collaborator invites, make the clean repo **public** (it holds nothing confidential). If they explicitly want the full history, give them access to this repo instead, after removing nothing (the PDF is theirs anyway), but ask them first.

---

## Open questions for Tianle (not covered by the six memos)
1. **The `CLAUDE.md` rule "teacher models never see eval cases" conflicts with the brief**: GPT and Gemini are both teachers *and* baselines, and baselines must run on eval. Proposed reading: *no output from any eval-case call ever enters a training file*, enforced by path separation plus `step6_evaluation/split_guard.py`. API providers don't train on API traffic by default (verify the account settings). See `contamination_protocol.md` §6.
2. **Policy alignment with Zorbe's hidden labels.** Zorbe labels their hidden set to *our* schema, but presumably with *their* reading of correct KYC practice. Every judgment call in our policy that departs from conventional practice is a likely point of disagreement. When unsure, choose the conventional answer (e.g., PEP true match → escalate with EDD, not reject).
3. **The as-of date.** Expiry and PoA recency are only decidable if the packet states a reference date. Every packet should print an onboarding or review date; never rely on the model's sense of "today."
