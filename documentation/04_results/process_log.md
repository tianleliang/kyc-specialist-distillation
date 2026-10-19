# Process log: every decision, realization and failure

Everything we chose, why, what each result taught us, and what failed, in the order of the pipeline. Numbers come from the committed results ([RESULTS.md](../../RESULTS.md), [benchmark_report_submission.md](benchmark_report_submission.md)); the chronological record is [findings_log.md](findings_log.md) and the decision list is [decision_log.md](../01_decisions/decision_log.md). Model names: **A** = model alone, **B** = model + pre-checker v2, **B2** = shipped model.

---

## 1. Result in one paragraph
A Qwen3.5-4B specialist scores **96.3%** decision accuracy on 300 fresh in-distribution cases (eval_id v2, generated after all development). Paired on the same cases, that is a statistical tie with Gemini 4 Argon (95.0%; difference −1.3, 95% CI −4.7 to +2.0) and Claude Opus 5.5 (97.7%; +1.3, −1.3 to +4.0); GPT-6 Astra stays ahead (99.3%). It costs $3.59–5.36 per 1,000 cases against $37–175, and answers in 24 s on the cheap L4 hand-over endpoint or 3.3 s on an H100 (frontier APIs 8.6–12.1 s). It trails the frontier on out-of-distribution free prose (92% vs 98–100%) and on injected instructions (escalates 86% vs 100%), and its narratives are less grounded (13.7% unsupported sentences vs 7–9%).

## 2. Setup: rules, data, test sets
**Rules before data.** The schema is flat with fixed reason codes (D1), so every decision traces to a rule and true edge cases go to the narrative and escalate. Each identity field gets one of the three task statuses (consistent / mismatch / unreadable); `verified` means all five are consistent (D2). Evidence is a section enum plus per-sentence `hit_ids` (D3), which keeps narrative grounding checkable on any packet.
- **What rejects (D4):** only a sanctions true match or *clear* tampering. The decision sheet recommended rejecting less; we overrode it because a training set where almost everything escalates teaches nothing, and desks do reject clear fraud. Decision mix ≈ 36% approve / 51% escalate / 13% reject.
- **Injection (D5):** any instruction aimed at the model → escalate, except that a sanctions true match still rejects. A security control the packet cannot switch off.
- **OCR vs tamper (D6):** three classes, not two: readable OCR noise (repaired, consistent) / ambiguous (exactly one look-alike digit pair and a failing check digit → escalate) / clear tamper (→ reject). This is how the task's "OCR errors that look like tampering, and tampering that looks like OCR" become decidable.

**Answer-first data.** The generator samples a case's hidden facts, code computes the label from the policy, and only then renders the packet (OCR noise, transliterated and reordered names, country address formats, aliases, partial DOBs, PEP associations, contradicting proof of address, injections). The answer key is exact, so teachers and students can be graded against it. Two checks on the labels:
- An independent agent re-implemented the policy from its text alone and matched **600/600** cases on every field; it found and we fixed one real bug (an OCR glyph that passes the check digit had been labelled tamper).
- In the dev pilot all four frontier models disagreed with gold on the proof-of-address addressee in name-mismatch cases. The rule was ambiguous, so we **fixed the rule, not the cases** (compare the PoA name with the application name, ignoring case, accents and order) and rebuilt every split.

**Test sets built by different processes, because the hidden test set will be.** eval_id (300) uses our generator with separate seeds and name pools, and a quarter of it uses two layouts (email, OCR dump) that never appear in training. Out-of-distribution: held-out templates (50), a session that never saw our generator code writing in six new styles (50), and LLMs writing free prose (100; Claude Sonnet 5.5 and Gemini 3.8 Flash). eval_hard (150) stacks 2–3 difficulties per case, built after zero-shot frontier models scored 100% on half the case types.

**Contamination controls.** Every test set was frozen by sha256 before any teacher call; a gate checks every training file against every test case (exact match, 8-gram containment, MinHash) before training: 0 overlaps. Train and test use separate seeds and separate name and list-entry pools. Teachers only ever saw training cases (the runners refuse teacher prompts on eval files). Every model choice was made on dev. Section 8 shows the one place that discipline slipped and how the test sets caught it.

## 3. Benchmark, teacher, size
- **Realization: the frontier misses our policy, not the documents.** With the rulebook in the prompt: Astra 99.2%, Opus 98.4%, Argon 95.8% on the frozen 500; zero-shot 87.6–92.6%, with risk tier at 73–81%. Beating them on accuracy in-distribution was unrealistic; the goal became matching them at a fraction of the cost.
- **The policy learned, not rented (D21).** The full rulebook plus schema is ~16k tokens, which doesn't fit a 4,096-token training window and costs money on every call. The student gets a 613-character prompt and learns the policy from training data; teachers and best-prompt baselines get the full rulebook.
- **Teacher chosen by a pilot.** On 100 dev cases: Astra 100%, Sol 100%, Argon 99%, Opus 98%; Sol was cheapest ($3.52 / 100 cases). Sol became the main teacher, Argon the second opinion. Claude never teaches (provider terms). Gemini's tier-1 rate cap throttled Argon mid-run, which is another reason Sol carried the training set.
- **Untrained baselines:** Qwen3.5 0.8B / 2B / 4B score 40 / 39 / 61% with the rulebook (29–60% zero-shot). The rulebook in the prompt does almost nothing for a 4B model (56.3 → 56.0 on eval_id v2): it has to be trained in.
- **Size by a rule set in advance:** the smallest model within 2 points of 4B on dev with ≥ 99% valid JSON. Trained on the answer key: 84.0 / 86.7 / 90.0 → 2B was 3.3 behind, so 4B (Apache 2.0: commercial use and derivatives allowed).

## 4. Domain adapter
A LoRA on 14 public KYC/AML documents (~420k tokens: FATF recommendations and PEP guidance, the FinCEN CDD rule, ICAO 9303 parts 3–5, OFAC FAQ, Wolfsberg, sanctions-list structure, address formats). Measured on held-out chunks it never trained on and a 30-item probe quiz; one probe item that appeared verbatim in the corpus was reworded (memorization guard).
- Held-out perplexity 7.39 → 5.52 (**−25%**), lower on all ten documents; probe 61% → 65% (one item).
- On the task: twins on the adapted base 91.3% vs plain base 90.7% on dev (+0.7, one case). **It learned the language, not the task.** Reported as a null; kept because it costs nothing at serving.

## 5. Distillation
**One controlled comparison:** the same 4B model and settings; only the training answers change. A model trained on the answer key itself is the ceiling.
- **Floor:** Sol's answers as they are.
- **Rejection sampling:** drop Sol answers that fail code checks (29 of 3,000).
- **Multi-teacher arbitration:** code picks Sol or Argon field by field (it almost always picked Sol).
- **Counterfactual Twin Distillation (ours):** every training case gets a twin identical except for one fact that flips the decision (e.g. a sanctions hit's date of birth changes from matching to conflicting, turning escalate into approve). If the pair differs only in the deciding fact, the student can't lean on template cues; it has to find the fact. Pairs are kept only if the teacher flips correctly on both (Sol: 98.6% of 1,000 pairs; 980 kept). At 0.8B, twins added +3.3 points.

**Dev results:** ceiling 90.0 · floor 89.3 · rejection 91.3 · arbitration 90.0 · twins 90.7 (three cases of 150). **Realization: the techniques were flat by construction.** Sol already matched the answer key on 99.3% of decisions, so there was almost no teacher error to filter or arbitrate, and distillation already reached the ceiling. The student's remaining errors were its own (section 6).
- **The pick, stated as post-hoc:** our pre-set rule would have chosen rejection (one case higher). After seeing dev we chose twins for the best required-actions recall (90.5%) and the fewest wrong approvals (6 vs 11), the error that hurts a desk most.
- **Cut:** adversarial hard-case mining. The brief's minimum (floor + two techniques + one invented) was met, and the remaining errors were arithmetic, which more hard examples don't fix.

## 6. The pre-checker: the model judges, code computes
**Realization from error analysis:** most remaining student errors were arithmetic: MRZ check digits, document expiry against the as-of date, and the 90-day proof-of-address window. The model usually approved what it should have escalated.
- **Design:** deterministic code reads the packet text, computes those values, and appends a short PRE-CHECKS block. The model is **trained with the block**, so it is part of the system, not a bolt-on. We report the model with it (B) and without it (A); the frontier runs without tools.
- **v1 → v2:** v1 reported "MRZ invalid" for both ambiguous and clear-tamper cases, so it couldn't separate escalate from reject. v2 computes the policy's three-way integrity class per field, verified at 0 wrong on train and dev.
- **Effect (halfway checkpoints, B vs A):** +6.0 on dev, +3.0 on the frozen 500, +6.7 on the hard set.

## 7. Post-training
SFT on the exact labels, one more pass at half the learning rate, keeping Sol's narratives (the generator's are template text; 2,978 of 3,000 swapped, the rest where Sol's decision or risk differed).
- **Why SFT:** the labels are exact, so imitating them is the most direct signal. DPO needs wrong answers to contrast and the teachers produced about 30. RL with the policy as a verifiable reward is the natural next step but was too slow and fragile for the deadline.
- **Result: within noise** (B 91.2 → 90.8 on the frozen 500; B2 96.7 → 96.3 on eval_id v2). It re-used the same packets with labels that already matched the teacher 99% of the time, so it added little information. We kept it because the two were statistically tied and it is the pipeline we designed beforehand.

## 8. The diagnosis: we caught our own overfitting
Final B scored **98.0% on dev but 93.0% on eval_id and 90.8% on the frozen 500**.
- **Cause:** we had built pre-checker v2 by studying dev's errors and verified it only on the four layouts train and dev share. Its reader returned "not determinable" on 17–22% of email packets, **100% of OCR dumps**, and nearly all hand- and LLM-written prose.
- **Why it hurt:** B had learned to trust the block. On eval_id it scored 96.1% when the block was readable and 82.1% when it was empty, and on LLM-written packets it fell *below* the model without pre-checks (86% vs 94%). 37 of 56 frozen errors were escalate → approve.
- **Not contamination:** no test case or label touched training. It was adaptive overfitting to dev, and the test sets did exactly what they were built for. We report Final B (90.8%) as the clean result from before the fix.

## 9. The fix, done so the re-test stays clean
- **Reader v3 reads by content, not layout:** finds the MRZ by its shape and trusts it only if its check digits pass; finds visual-zone values by matching them to the MRZ; one date reader for every format; several readers vote, and any disagreement gives "not determinable", because **never wrong beats always readable**. Developed only on new training-process cases in all six generator layouts; the frozen sets and the LLM-rewriting process were off limits.
- **A format fuzzer** writes training facts in random layouts (key-value, prose, email, tables, JSON, no labels, noise), including one family hidden from the reader's authors, and checks the reader is never wrong. Result: 0 wrong on all six generator layouts with 90–99% coverage (OCR dumps 0 → 94–97%); on random layouts, about one new kind of mistake per thousand packets, documented.
- **The limit, and the next step:** values tied to the MRZ can be read anywhere, but knowing which date is the bill date takes language. A code reader stays vocabulary-bound; next step is "the model reads, code computes".
- **B2 = B retrained with the block blank 25% of the time,** so the model learns to fall back on its own judgment when the reader can't read a packet.
- **Fresh eval_id v2** (same generator config, new seed) because the fix used what the frozen sets showed us; the frontier models were re-run on it, so the headline comparison is untouched by any development.
- **Reader v3.1 swap:** a wider-net reader swapped in at serving without retraining gave identical scores. The model learned the block's format, so the tool can be upgraded on its own (we ship v3).

## 10. Results
| | eval_id v2 | eval_id | OOD template | OOD hand | OOD LLM | frozen 500 | hard |
|---|---|---|---|---|---|---|---|
| A (model alone) | – | 88.3 | 84.0 | 82.0 | 94.0 | 88.4 | 85.3 |
| B (pre-checker v2) | – | 93.0 | 90.0 | 88.0 | 86.0 | 90.8 | 93.3 |
| **B2 (shipped)** | **96.3** | 96.0 | 94.0 | 92.0 | 92.0 | 94.6 | 92.7 |
| Argon / Opus / Astra | 95.0 / 97.7 / 99.3 | 94.0 / 98.0 / 99.0 | 100 / 100 / 100 | 98 / 100 / 100 | 98 / 98 / 99 | 95.8 / 98.4 / 99.2 | – / 98.7 / 99.3 |

- **Stage gains on eval_id v2:** rulebook in the prompt −0.3 · adapter + twins distillation **+32.7** · pre-checker **+8.0** · post-train −0.3.
- **Unsupported claims** (blind Claude Sonnet judge, judging against packet + policy, all models' sentences pooled and shuffled per case): B2 13.7%, frontier 7.4–8.8%, untrained Qwen 45–61%. Fallback training cost some grounding (B 14.2% → B2 17.3% on eval_id).
- **Latency and cost (measured, one request at a time, warm):** L4 hand-over endpoint p50 24.3 s / p95 29.1 s, $5.36 per 1,000 ($0.47 at 16 concurrent); H100 p50 3.3 s / p95 3.8 s, $3.59 per 1,000. A faster GPU barely changes cost per case because it finishes sooner; it only raises the idle cost of an always-on endpoint.

## 11. Reporting choices (and why)
- **Headline = eval_id v2 (in-distribution).** The product is a specialist for one desk's known formats; out-of-distribution is reported right beside it, never hidden, and it shows which packets to route to the frontier.
- **Post-hoc choices, all disclosed:** twins over rejection (section 5); the reader fix after seeing the frozen sets (section 9), which is why eval_id v2 exists.
- **Final B is kept as the pre-diagnosis result;** B2's numbers on the frozen v1 sets are "after diagnosis".

## 12. What failed
- The pre-checker overfit to dev (section 8): verify a tool on formats it wasn't built against.
- Prompt injection: B2 escalates 86% of injected packets vs the frontier's 100%; the fuzzer shows planted false values can fool the reader into a false "clear tamper". Fix: competing values must give "not determinable", never "tamper".
- Free prose: a code reader can't assign roles to dates in a letter.
- Flat distillation techniques, a null adapter, a flat post-train (sections 4, 5, 7).
- Narratives got less grounded with fallback training (14.2% → 17.3%).
- Engineering: a launch log written inside an uploaded folder crashed a training launch; a merge safety check rejected a correct post-trained model at 1 a.m. (its first 96 tokens matched the base; logits differed); Gemini's rate cap stalled a teacher run; an Anthropic budget ran out mid-benchmark (resumed from cache).

## 13. What we'd do next
Model extraction + code arithmetic (the model reads the values, code computes); "competing values → not determinable" in the reader; RL with the policy as the reward; DPO on the student's own mistakes; hard-case mining on injection and free prose; route OOD-looking packets to the frontier in production.

## 14. Models, assistants, spend
- **Base:** Qwen3.5-4B (Apache 2.0; commercial use and derivative weights allowed).
- **Frontier models, never shipped:** GPT-6.1 Sol (main teacher), Gemini 4 Argon (second teacher, baseline), GPT-6 Astra and Claude Opus 5.5 (baselines), Claude Sonnet 5.5 (blind judge; co-wrote the LLM OOD set with Gemini 3.8 Flash).
- **Coding assistants:** Claude Code (desktop and cloud sessions) wrote and ran the code under written briefs ([06_agent_instructions](../06_agent_instructions/README.md), reports in [05_progress_reports](../05_progress_reports/README.md)); Claude in Obsidian for planning, audits and the decision log. Every design decision is Tianle's ([decision_log.md](../01_decisions/decision_log.md)).
- **Spend:** [RESULTS.md §4](../../RESULTS.md#4-spend).
