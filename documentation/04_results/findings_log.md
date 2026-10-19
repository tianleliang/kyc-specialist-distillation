# Findings log: every result, its numbers, and the reasoning behind it

Every result and judgment in the order it happened. Each entry: **what happened → evidence (file or run) → section of the write-up it supports.**

---

## 1. Data, labels, and the rulebook
- **The policy is unambiguous (independent check).** A fresh agent re-implemented every label from `step0_rules/policy_v1.md` alone, without reading the generator, and matched **600/600 cases on every field**. It caught one real label bug (an OCR glyph that happens to pass the check digit was labelled tamper → reject). → `documentation/05_progress_reports/lunch-L.md`. *Write-up: §2 choices, §4 rigor.*
- **The dev pilot found a second rule ambiguity.** On `name_mismatch` cases, all 4 frontier models (given the policy) compared the proof-of-address addressee with the **application** name; our labeller compared it with the document name. Fix: the policy now says "as named on the application"; labeller and policy updated, every split rebuilt. The first fix overcorrected (2 cases where the PoA *is* in the application name); the pilot data caught that too. After the fix, Astra and Sol agree with gold 100% on decision, risk, and address. → `step2_benchmarking/results/dev_pilot/`, commit `d400398`. *§4 rigor ("label audit by frontier disagreement"), §5 what failed.*
- **Rule of thumb adopted:** where our policy differs from frontier default behaviour without a strong reason, align with consensus, because Zorbe's hidden set will be labelled by their process. Example: frontier zero-shot rejects an expired passport; our policy escalates (the applicant can cure it), and that's stated explicitly. *§2.*
- **Difficulty is mixed, not one-trap-per-case:** train 7% clean / 70% one difficulty / 23% two stacked; eval_id 31% two stacked; OOD-LLM 38%. The policy precedence order (P1–P10) keeps labels defined under stacking. *§2 data.*
- **eval_hard (stress set, added mid-run):** 150 cases, every case 2–3 stacked difficulties (55% three), ID OCR noise ×2.5, no clean cases, frozen separately. **Frontier with policy stays saturated even here** (Astra 99.3% decision, Opus 98.7%). Interpretation: our cases' real difficulty is *knowing and applying the policy*, not perceiving messy evidence. That's an honest limitation of synthetic data, and it's why OOD sets exist. → `data/eval_hard/`, `step2_benchmarking/results/bench_hard/`. *§4, §5.*

## 2. Contamination controls (evidence)
- Eval frozen with a sha256 manifest, read-only (`data/eval/MANIFEST.json`, 500 records; `data/eval_hard/MANIFEST.json`, 150). `split_guard verify` passes.
- **0/500 and 0/150** eval records overlap any training file (exact, 8-gram containment, MinHash) across train, dev, twins, knockouts and every SFT file; the gate runs automatically before every training file is written and before every Modal training job.
- Teachers only ever answered train / twins / knockouts. Few-shot examples come from train. The pilot and all model selection used **dev**, never eval.
- Generation is byte-deterministic across machines (Windows rebuild == cloud build, hashes equal).
- The 3 OOD processes are disjoint by seed range and entity bucket; the hand-template writer never read the training renderer; the LLM-written OOD drops any packet that changed a fact (1 dropped of 101).
*§4 (20 pts).*

## 3. Frontier panel: benchmark findings
- **With the policy in the prompt, frontier models are near-perfect in distribution:** decision Astra 99.2%, Opus 98.4%, Argon 95.8% (500 eval cases). → `outputs/bench_frontier/`.
- **Zero-shot (no policy) is much weaker where policy matters:** decision 87.6–92.6%, **risk tier 73–81%**, actions exactly right ~62–76%. Zero-shot models mostly fail *our policy*, not perception. Hardest zero-shot types: partial DOB 77%, PEP false positive 79%, transliterated names 82%, reordered names 85%.
- **Untrained open models are near useless:** Qwen3.5 0.8B and 2B ≈ 40% decision (below always-escalate), even with the policy in the prompt. Schema validity is still 100%, because the server forces the format. The format is solved by constrained decoding; the content is what training must fix.
- **Cost per case** (16k-token best prompt): Sol $0.035, Argon $0.036, Opus $0.11, Astra $0.175. Frontier p50 latency 8–13 s.
- **Definition of "match"** (pre-stated): compare against the panel **with the policy** (how a customer would deploy it), on every brief metric with 95% bootstrap CIs. "Match" = CI overlap / paired difference not significant vs a panel member, or better. Zero-shot also reported. *§1 headline, §3.*

## 4. Teachers and distillation data
- **Claude is never a teacher:** ToS restrictions on training competing models plus Anthropic's distillation-detection announcement (Oct 12). Claude is used only as baseline and judge. *§7 models table.*
- **The Gemini Tier-1 rate cap** collapsed Argon throughput when two sessions shared it. **Sol became the main teacher** (train + twins + knockouts); Argon answers train only (the second opinion for arbitration). Argon resumed after the benchmark finished: 3,000 cases, 34 errors, $97.
- **Teacher accuracy vs gold:** Sol decision 99.3%, actions 99.1%; Argon decision 95.9%, actions 93.8%; Sol/Argon agree 95.9% on decision.
- **Consequence for the techniques (key honesty point):** teachers are ~99% policy-consistent, so **rejection sampling drops only 1%** (2,971/3,000 kept) and **arbitration mostly selects Sol** (2,954 kept). Expect small deltas from these two, and report them as such. The real gap is the *student's* capacity (arithmetic), so the techniques that react to the student (twins/knockouts, hard-case mining, corrections) are where gains should come from. *§3, §5.*

## 5. Student results (dev, 150 cases, gold-label SFT, short prompt)
| Model | Decision | Risk | Fields | Actions recall | Screening |
|---|---|---|---|---|---|
| 0.8B | 84.0 | 84.7 | 97.6 | 79.5 | 100 |
| 0.8B + twins (gold) | **87.3** | 84.7 | 98.1 | 83.7 | 100 |
| 4B | **90.0** | 89.3 | 97.7 | 85.3 | 100 |
- **Twins: +3.3 decision points at the same size**, early evidence for the invented technique.
- **Failure analysis:** the remaining errors are overwhelmingly **arithmetic**: MRZ check digits (obvious tamper 1/5 at 4B), date arithmetic (stale PoA 1/4 at 4B), OCR-vs-tamper. More size helps slowly. Mostly escalate→approve (missed red flags).
- Size rule (pre-stated, D16): ship the smallest size within 2 pts of 4B on dev decision accuracy with ≥99% valid JSON.

### 5b. Sat night (4B): adapter + distillation results
- **Domain adapter (stage 2), 4B:** MOVED. Held-out corpus perplexity 7.39 → 5.52 (−25%), down on all 10 documents (e.g. FATF Recs 7.59 → 4.79, ICAO 9303 p4 5.99 → 4.04). KYC probe (23 answerable items) 61% → 65% (= 1 item; within noise): alias 70 → 80, MRZ 30 → 30, PEP 90 → 90. Read: it learned the domain's *language*, not measurably its *knowledge*; MRZ stuck at 30% is consistent with the arithmetic finding (§6). → `step5_training/results/logs/adapter_4b_measure.log`. *§2.*
- **Distillation on 4B (stage 3), dev 150, model alone, short prompt, plain base:**

| run | valid | decision | risk | fields | actions recall | screening | wrong approvals |
|---|---|---|---|---|---|---|---|
| gold-only SFT (control) | 100 | 90.0 | 89.3 | 97.7 | 85.3 | 100 | – |
| floor (Sol) | 100 | 89.3 | 88.0 | 98.4 | 88.4 | 100 | 7 |
| + rejection (code checks) | 100 | 91.3 | 90.7 | 98.1 | 84.2 | 99.3 | 11 |
| + arbitration (Sol + Argon, code picks) | 100 | 90.0 | 89.3 | 98.1 | 86.3 | 100 | 10 |
| **+ Counterfactual Twin Distillation** | 100 | 90.7 | 90.7 | **98.8** | **90.5** | 100 | **6** |

  - Spread is 3 cases of 150 (±~3 pts noise at n=150): flat, as predicted in §4 (teachers ~99% policy-consistent → rejection/arbitration have ~nothing to correct).
  - **Distillation matches the gold-label ceiling** (90.7 vs 90.0): the student absorbed what the teachers know; the residual is student capacity (arithmetic), not teaching signal. In production there is no answer key; gold is our oracle control, showing distillation loses nothing.
  - "Wrong approvals" = predicted approve when gold is escalate/reject (the costly error on a KYC desk).
- **Winner pick (Tianle, 21:55): twins.** The pre-stated rule (highest dev decision; within 1 pt take the simpler) would have picked *rejection* (91.3 vs 90.7 = 1 case). We chose twins on actions recall (+6.3), fields, and half the wrong approvals (6 vs 11). **This was chosen after seeing dev; state it as such.** The frozen eval was not touched.
- **Error anatomy (twins, 14 dev decision errors):** 11 are OCR-vs-tamper / obvious tamper / stale PoA. In 7–8 of them the model *rejects* where policy §3 says *escalate* (one look-alike digit pair + failing check digit = ambiguous). The v1 pre-checker reports "MRZ invalid" for both ambiguous and clear-tamper cases, so it cannot separate them → v2 adds the §3 classification per field (Sat ~22:30). *§6.*
- **Invented technique named: Counterfactual Twin Distillation** (pairs identical except one decision-flipping fact; forces attention to the deciding fact rather than template cues). 0.8B: +3.3 (gold labels). 4B: +0.7 decision vs arbitration (noise), best actions/fields, fewest wrong approvals.
- **Cut: adversarial hard-case mining** (Tianle, 20:20). Brief minimum met by floor + rejection + arbitration + invented; the residual errors are arithmetic, which more hard examples don't fix and pre-checks target directly; saves ~2 h + new teacher spend. → "what we'd do next".
- **Stage 4 = SFT on task data (gold), not DPO/RL** (Tianle, ~22:05). Our labels are exact (code-computed, independently verified), so imitation of the exact answer is the most direct signal; DPO needs rejected answers (teachers produced ~30, too few) and RLVR (natural fit: the policy is a perfect verifier) is too slow/fragile for the deadline → lead "next step". Stage-4 targets: **gold structured fields + Sol's narrative** (gold narratives are template text; keep the teacher's analyst prose).
- **Final pipeline:** Qwen3.5-4B → domain adapter (merged) → twins distillation → gold post-train. Final A = model alone; Final B = same + PRE-CHECKS block in training and serving. Halfway (post-distillation) checkpoint scored too → "+adapter" and "before post-train" rows.

### 5c. Sun: frozen results, diagnosis, reader v3
- **Frozen eval v1, decision % (dev / eval_id / OOD template / OOD hand / OOD LLM / hard / pooled 500):** A halfway 91.3 / 86.7 / 88.0 / 86.0 / 94.0 / 86.0 / 88.2 · A final 93.3 / 88.3 / 84.0 / 82.0 / 94.0 / 85.3 / 88.4 · B halfway 97.3 / 93.0 / 90.0 / 88.0 / 88.0 / 92.7 / 91.2 · **Final B 98.0 / 93.0 / 90.0 / 88.0 / 86.0 / 93.3 / 90.8**. Frontier best prompt per split: eval_id Argon 94.0, Opus 98.0, Astra 99.0; OOD template 100/100/100; hand 98/100/100; LLM 98/98/99. Untrained Qwen3.5-4B: 60.0% zero-shot, 61.2% best prompt (with the rulebook) on eval500; 0.8B ≈ 40%.
- **Reporting decision (Tianle):** eval_id is the headline (in-distribution, and already harder than a plain held-out split: 25% of it uses 2 layouts never seen in training, `email`, `ocr_dump`); OOD reported beside it as generalization. The sets were separate by design (D13).
- **Diagnosis (adaptive overfitting, not contamination):** dev 98 vs eval_id 93. Pre-checker reader v2 was built and verified on train/dev's 4 styles only; n/d by style (packet text only): train styles 6–11% PoA / 0–5% integrity, `email` 17–22%, `ocr_dump` 100%, LLM/hand prose ~100%. Block readable → B 96.1% on eval_id (233 cases); n/d → 82.1% (67). With a blank block B falls *below* A on OOD LLM (86 vs 94): it learned to trust the block. 37/56 frozen errors are escalate→approve. Twins + pre-checker v2 were tuned on dev → dev overstated by ~5 pts. The frozen sets did their job.
- **Reader v3 (Session P3) + format fuzzer (Session F):** developed only on train-process data (`data/reader_dev`, 600 new train-config cases, all 6 generator styles) and fuzzed layouts rendered from train truth; eval and the LLM-rewrite process never touched. v3: 0 wrong on train/dev/reader_dev; coverage per generator style 90–99% (`ocr_dump` 0 → 94–97%). Fuzzer: 9 families incl. one held out from P3, fresh seeds each run; 0 wrong on most seeds, rare new wrong classes on fresh seeds (~1 per 1,000+ packets, whack-a-mole) → frozen with known classes documented. Fuzz coverage: integrity ~47–51% on structured families, no-label 5%, heavy noise 14%. → `step7_serving/results/p3_reader_v3_gate.md`, `reader_bench_*.md`.
- **The limit (a finding, and the next step):** values with an anchor (MRZ-matched document number / DOB / expiry) can be read layout-free; values whose *role* depends on meaning (which date is the PoA date, which is the as-of) need language understanding, so any hard-coded reader stays vocabulary-bound (v3 still keys on generator section tags and document-type words). Next: "model reads, code computes" (the model extracts raw values, code does the arithmetic).
- **Wide-net v3.1 (in parallel, Sun):** roles by elimination (claim MRZ-proven dates, application/as-of pair; one remaining recent date = PoA date, else n/d), generic document-noun patterns instead of word lists, MRZ anchor over the whole packet. Same block format byte-for-byte.
- **Interface principle:** B is trained on the block *interface* (75% v3-filled, 25% blank → fallback). A better reader only fills more lines in the same format, so it can be swapped at serving without retraining; we score B-run2 with v3 and v3.1 and report both. Stage 9 point: the tool improves independently of the model.
- **eval_id v2:** same generator + 6 styles, new seed, frozen Sunday; measures fresh cases (not unseen formats, since the reader now knows all 6 styles). Argon re-run on it for an apples-to-apples row. Unseen-format evidence = OOD hand/LLM (untouched by any development) + F's held-out family.

## 6. The pre-check component (tool-assisted specialist)
- **Why:** the residual gap is arithmetic that small models do poorly and code does perfectly. The brief: "Focus on the result, even if you have to stray from the exact architecture." Zorbe's thesis is to own a specialist *system*; banks already validate MRZ check digits in the scanner and leave judgment to the analyst.
- **Honesty rules:** (1) the pre-checker parses the **packet text only**, never the hidden truth; it must work on Zorbe's differently formatted packets, and when it can't parse something it emits nothing. (2) **We report both rows**: model alone, and model + pre-checks. (3) Frontier models run without tools, as customers normally use them, and we say so.
- **Training implication:** the student is trained with the same PRE-CHECKS block (computed by the same code from the packet text), so it learns to use it.

## 7. Engineering findings (each one a "what failed / what we caught")
- Training targets were alphabetically keyed while vLLM's grammar emits schema order, a silent train/serve mismatch. Fixed: targets are serialized in schema order.
- Anthropic structured output rejects `minItems>1`, `maxItems` and length bounds; Claude gets a relaxed API schema, but **all outputs are scored against the full v1 schema**.
- The prompt field guide (13k chars) restated the policy; dropped, cutting input cost ~25%.
- The policy+schema prompt (~11k tokens) exceeded the 4k training window, so the **student gets a 613-char prompt and learns the policy in training** (D21b): the specialist absorbs the policy instead of renting it per call.
- The Qwen3.5 LoRA silent-no-op risk was guarded by a merge check (outputs must differ from base). They do: base emits free text, merged emits schema JSON.
- `causal-conv1d` failed to build in the training image (needs nvcc); dropped.
- Windows-only bugs caught in local audits: UTF-8 defaults, CRLF vs LF hashes, case-insensitive `MANIFEST.json` vs `manifest.json`, Git Bash path rewriting.
- Untrained base models loop on whitespace and free text inside the JSON grammar; fixed with `disable_any_whitespace` and `maxLength` on the serving schema.

- **Sat night:** launch script put logs inside `step5_training/`, which Modal uploads at launch → "file was modified during build" crashed 1 of 4 trainings ($0). Fixed: logs to `outputs/logs/`. Lesson: never write to an uploaded package while launching.
- Pre-checker v1 verified 100% on train+dev for MRZ check digits / expiry / PoA age (abstains with "n/d" on ambiguous day-month dates, never guesses). → `step7_serving/results/precheck_eval_train_dev.md`.
- Dev scoring latency (p50 32.6 s, p95 114 s) is queueing: 16 concurrent requests on one L4. Not the per-case latency; measure Sunday at concurrency 1 warm. Throughput ≈ 1,500 cases/h on an L4 (~$0.80/h) ≈ **$0.55 / 1k cases** vs Sol ~$35 / 1k, Astra ~$175 / 1k (dev pilot).

## 8. Cost and logistics
- Total spend: see [RESULTS.md](../../RESULTS.md#4-spend). Per-run API cost ledgers are inside each `results/runs/*/provenance.json` and `step4_distillation/teacher_outputs/*/ledger.json`.
