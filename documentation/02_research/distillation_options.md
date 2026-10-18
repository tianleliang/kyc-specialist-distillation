# Distillation Options: DRAFT for Tianle

> **⚠️ OPTIONS, NOT DECISIONS.** Session D overnight, 2026-10-17. Every technique the brief names, in plain English, with rough cost and time for a **~2B student on Modal**, expected gain and an ablation design. Then **four candidate invented techniques** specific to KYC. Tianle chooses which to run and which one to name as ours.
>
> **All numbers are planning estimates**, built from the assumptions in §0, not from measurements. The "expected gain" lines are priors to be replaced by Table 2.

---

## 0. Shared assumptions behind every estimate

| Quantity | Assumption | Source / reasoning |
|---|---|---|
| Packet length | ~1,500 tokens | A five-section packet with an MRZ and 1–4 hits |
| System prompt + policy | ~1,500 tokens | If the policy is in the prompt (`decision_policy_draft.md` Q-0) |
| Output length | ~600 tokens | `schema_options.md` examples are 520–600 tokens |
| Teacher thinking | Low effort, ~500 tokens, billed as output | `05` §4: keep reasoning low |
| Train set | ~3,000 cases | Plan, Tier 1 |
| Student | Qwen3.5-2B (proposed in `05`; not yet decided), 16-bit LoRA | `05` §2: no QLoRA on Qwen3.5 |
| Training throughput | ~5k tokens/s on an A100-80GB (Unsloth, LoRA, 2B), ~1.5k tokens/s on an L4 | Conservative guess; **measure in the first run** |
| Modal prices | A100-80GB $2.50/h, L4 $0.80/h | `05` §3 |
| Teacher prices (batch, 50% off) | `gpt-6-astra` $5/$25 per M tokens; `claude-opus-5-5` $2/$10; `gemini-4-argon` $1/$5; `gpt-6.1-sol` $1/$5 | `05` §4 |

**Derived unit costs (planning numbers):**
- **One SFT epoch** on 3k cases ≈ 3k × 2.1k tokens (packet + output; the system prompt is shorter in training) ≈ 6.3M tokens → ~21 min on an A100. **A 3-epoch SFT run ≈ 1 h ≈ $2.50**, plus ~10 min of image build and weight download.
- **One teacher pass over 1,000 cases** (3k in, 1.1k out incl. thinking): Astra ≈ **$43**, Opus 5.5 ≈ **$17**, Argon or Sol ≈ **$8.5**.
- **One student eval** over 450 cases on vLLM on an L4: ~270k output tokens → a few minutes → **< $0.50**.

**Conclusion that shapes everything below:** GPU training is cheap (single dollars per run). **The binding constraints are teacher API spend, batch latency (OpenAI and Gemini batches can take up to 24 h, per `05` §4) and wall-clock hours before Sunday.** So prefer techniques that reuse one teacher pass, and run ablations as additional cheap training runs over the *same* teacher data.

---

## 1. A control we should probably have anyway: gold-label SFT

The answer-first generator produces **ground truth for every structured field**. Only the narrative needs a writer. So there's a non-distillation baseline: **SFT on gold structured fields + a template narrative.**

- **Why it matters:** it answers the obvious reviewer question: "did the frontier teachers add anything beyond your own labels?" If teacher-SFT beats gold-SFT, distillation earned its place. If not, we say so honestly.
- **Cost:** one SFT run (~$3), zero API.
- **Q-DS1:** include this as a Table 2 row? (It costs almost nothing and makes the distillation claims falsifiable.)

---

## 2. The brief's techniques

### 2.1 SFT on teacher answers (the floor)
- **Plain English:** each frontier model solves the training cases; the student learns to imitate the answers.
- **Recipe:** one teacher (or several, concatenated) × 3k train cases → validate the schema → LoRA SFT (r=16–32, 2–3 epochs, loss on the assistant tokens only).
- **Cost:** API $8.5–43 per teacher per 1k cases → **$25–130 per teacher for 3k**; GPU ~$3.
- **Time:** batch submit Saturday morning (Anthropic ~1 h; OpenAI/Gemini up to 24 h); training ~1 h.
- **Expected gain:** the big jump. A 2B zero-shot model will often fail the schema or the policy; after SFT, expect most of the eventual accuracy. *Prior: zero-shot decision accuracy roughly 30–50% → 75–90% after SFT.*
- **Ablation:** this *is* the baseline row for every other technique. Also report SFT with each single teacher vs all three, which is free once the data exists.
- **Risk:** the student inherits teacher errors, including policy mistakes the teacher makes consistently (frontier models carry real-world habits, such as rejecting PEPs, that conflict with our policy).

### 2.2 Rejection sampling against programmatic checks
- **Plain English:** keep only the teacher answers that our code can verify as correct; throw away the rest.
- **Recipe:** for each teacher output, check (a) schema validity, (b) decision = gold, (c) each disposition = gold, (d) each field status = gold, (e) actions ⊇ gold-required, (f) narrative sanity (no dates or names absent from the packet; sentence count 4–8). Keep outputs passing all checks. Optionally **sample k=2–4** at temperature 0.7 on cases where nothing passes.
- **Cost:** filtering is free. Re-sampling the hard fraction (say 20% of cases × 3 extra samples) adds ~60% of one teacher pass.
- **Time:** minutes of code; resampling waits on a batch.
- **Expected gain:** removes teacher-policy disagreement from the training data, so the student learns *our* policy cleanly. *Prior: +2–6 points decision accuracy over 2.1, more on fields and dispositions; the gain is larger if teachers disagree with the policy often.*
- **Ablation:** (i) SFT on all teacher outputs vs (ii) SFT on filtered outputs. **Control for data size:** also train on a random subset of (i) the same size as (ii), so we measure *quality* not *quantity*.
- **Risk:** filtering removes exactly the hard cases (where teachers fail), so the student sees fewer hard examples. The fixes are resampling, or arbitration (2.3) to recover them.

### 2.3 Multi-teacher arbitration
- **Plain English:** when GPT, Claude and Gemini disagree, use a rule to choose which answer to train on.
- **Recipe:** for each case, collect all three outputs. Rules, simplest first: (a) **gold arbiter**: keep the teacher(s) matching gold; tie-break by narrative grounding score; (b) **majority vote** on decision + dispositions without gold (useful for the OOD-style cases where gold is noisy); (c) **disagreement as a label audit**: all three teachers disagree with gold → flag for a generator-bug check (plan §2, Saturday 17:00 checkpoint).
- **Cost:** needs ≥2 teachers on the same cases, so the API bill is the sum of teachers. Arbitration itself is free.
- **Time:** depends on the slowest teacher batch.
- **Expected gain:** cleaner labels + more stylistic diversity in narratives (helps OOD robustness). *Prior: +1–3 points over the best single teacher after filtering; its biggest value may be the label audit.*
- **Ablation:** best single teacher (filtered) vs arbitrated mix, at equal N.
- **Risk:** ToS concern on Anthropic as a high-volume teacher (`05` §5). Two teachers (GPT + Gemini) with Claude as judge still allow arbitration.

### 2.4 Adversarial hard-case mining
- **Plain English:** find the kinds of cases the student gets wrong and make more of them.
- **Recipe:** train v1 → evaluate on a **dev split from the training generator (never the eval sets)** → break down errors by generator knob (transliteration scheme, DOB partial-match type, tamper type, injection style, ...) → oversample the worst knobs in a fresh generation batch → teacher-label (or gold-label) → retrain.
- **Cost:** new teacher calls only for the new cases (e.g. 1k hard cases ≈ $8.5–43 per teacher); GPU ~$3 per retrain.
- **Time:** serial (needs v1 first), plus one teacher batch → **3–5 h wall clock**.
- **Expected gain:** targets the long tail that drives the adversarial and screening metrics. *Prior: +2–5 points on the mined categories, ~+1 overall.*
- **Ablation:** v1 + N random new cases vs v1 + N mined cases (equal N, equal teacher).
- **Contamination note:** the error analysis must use a **dev** split. Mining on eval failures is a leak; `contamination_protocol.md` (Session E) should forbid it explicitly.

### 2.5 Teacher-as-judge preference data
- **Plain English:** a frontier model looks at two of the student's answers and says which is better; we train toward the better one.
- **Recipe:** sample 2–4 student outputs per train case → the structured fields are judged **by code** (no LLM needed) → the LLM judge (Claude, consistent with CLAUDE.md "Claude is used for baselines and judging") compares only the **narratives** on grounding and completeness → pairs (chosen, rejected) → DPO (2.7).
- **Cost:** judge call ≈ 3.2k in + 200 out → **~$8 per 1k pairs** on Opus 5.5 batch. Student sampling is cheap.
- **Time:** ~2 h including the batch.
- **Expected gain:** mainly the **unsupported-claims** metric (the place small models are expected to lose: `01` §4). Little effect on decision accuracy. *Prior: unsupported-claim rate down by a third to a half; decision accuracy flat.*
- **Ablation:** SFT vs SFT + DPO(judge pairs); report narrative metrics with the same judge **and** a different judge model, to show we're not just fitting the judge's taste.
- **Risk:** judge self-preference and verbosity bias; mitigate with position swapping and a length-controlled rubric.

### 2.6 On-policy correction of the student's own mistakes
- **Plain English:** let the student answer, find its mistakes with code, have a teacher fix exactly those, and train on the fixes.
- **Recipe:** student v1 on ~2k train prompts → programmatic checks flag wrong fields → the teacher receives packet + student output + "these fields are wrong" (optionally + gold) and returns a corrected full output → validate → SFT on corrections (or DPO with student-as-rejected and corrected-as-chosen; see 2.7).
- **Cost:** teacher calls only on failures (~30–50% of prompts) → **$5–40**. Use *live* (non-batch) calls if OpenAI or Gemini batches are slow.
- **Time:** serial after v1, ~2–3 h.
- **Expected gain:** fixes the student's *own* error distribution (off-policy SFT can't target these errors). *Prior: +2–4 points decision accuracy; synergistic with DPO.*
- **Ablation:** v1 + N on-policy corrections vs v1 + N fresh teacher examples (equal N).
- **Risk:** teacher "corrections" can drift from policy, so re-filter with 2.2.

### 2.7 DPO (direct preference optimization)
- **Plain English:** instead of "copy this answer", show the model a better and a worse answer and nudge it to prefer the better one. No reward model, no RL loop.
- **Where pairs come from (all cheap here):** (a) passing vs failing teacher outputs from rejection sampling (off-policy); (b) **student's wrong output vs corrected output** from 2.6 (on-policy, usually stronger); (c) judge pairs from 2.5; (d) the counterfactual-twin pairs in §3.1.
- **Recipe:** TRL `DPOTrainer` (or Unsloth's DPO path) from the SFT checkpoint, β≈0.1, 1 epoch, 1–2k pairs.
- **Cost:** ~2× SFT per example (chosen + rejected) plus a reference model → **~1 h on an A100 ≈ $3**.
- **Time:** ~1.5 h including setup, if the SFT pipeline already works.
- **Expected gain:** this is the brief's "post-train" stage with a before and after. *Prior: +1–4 points; the biggest effect is on cases where SFT learned the right fields but the wrong decision precedence.*
- **Ablation:** SFT vs SFT+DPO with each pair source separately (pair sources are cheap to swap).
- **Risk:** DPO on long structured outputs can reward verbosity or break the format; keep schema-constrained decoding at eval time and watch validity and length.

### 2.8 GRPO / RL with verifiable rewards (RLVR)
- **Plain English:** the model tries several answers per case; code scores each (schema valid? decision right? fields right?); the model is pushed toward the higher-scoring tries. GRPO compares answers *within* a group, so no separate value model is needed.
- **Reward design (the hard part):** a gate of 0 if the schema is invalid; otherwise a weighted sum of decision (e.g. 0.35, mirroring the brief's weighting of the task), dispositions, field findings, risk tier (partial credit for off-by-one), action recall *and* precision (so it can't spam actions), and a narrative-grounding proxy (penalize dates or names absent from the packet). **Reward-hacking watch:** with an escalate-heavy distribution, "always escalate" gets a high decision reward, so balance it with per-class weights.
- **Recipe:** TRL `GRPOTrainer` + vLLM generation, from the SFT (or DPO) checkpoint, group size 8, ~500–1,000 prompts, 1 epoch.
- **Cost:** generation-heavy: 1k prompts × 8 × 600 tokens ≈ 5M generated tokens + training → **~2–4 h on an A100 ≈ $5–10**, *after* it works.
- **Time:** the real cost is engineering. A first GRPO setup can easily eat 3–6 hours (plan Tier 3 = stretch).
- **Expected gain:** potentially the best decision accuracy, since it optimizes the exact metric; also the most variance. *Prior: +0–5 points over SFT+DPO; could be negative if the reward is mis-specified.*
- **Ablation:** SFT(+DPO) vs + GRPO, same prompts; report the reward curve and per-metric deltas.
- **Note:** the brief says the schema and ground truth "make programmatic rewards easy". Option C's `checks` block (`schema_options.md` §5) gives denser rewards if chosen.

### 2.9 Summary table

| Technique | API $ (3k train) | GPU $ | Wall time | Depends on | Prior gain | Ablation arm |
|---|---|---|---|---|---|---|
| Gold-label SFT (control) | 0 | ~3 | 1 h | generator | n/a (control) | gold vs teacher SFT |
| SFT on teacher (floor) | 25–130 / teacher | ~3 | batch + 1 h | teacher batch | large | baseline |
| Rejection sampling | 0–80 | ~3 | +0.5 h | floor data | +2–6 | all vs filtered, equal N |
| Multi-teacher arbitration | Σ teachers | ~3 | slowest batch | ≥2 teachers | +1–3, label audit | best-single vs arbitrated |
| Hard-case mining | 10–45 / teacher | ~3 | 3–5 h serial | v1 + dev split | +1 overall | random vs mined, equal N |
| Teacher-as-judge prefs | ~8 / 1k pairs | ~3 | 2 h | v1 | unsupported claims ↓ | SFT vs +DPO(judge) |
| On-policy correction | 5–40 | ~3 | 2–3 h serial | v1 | +2–4 | fresh vs corrections |
| DPO | 0 (reuses pairs) | ~3 | 1.5 h | SFT + pairs | +1–4 | SFT vs +DPO per pair source |
| GRPO / RLVR | 0 | 5–10 | 3–6 h eng. | SFT, rewards | 0–5, high variance | ±GRPO |

**Cheapest high-value set, if Tianle wants a starting point to react to (not a decision):** floor + rejection sampling + arbitration all reuse one teacher pass and differ only in data filtering, so three Table 2 rows for one API bill. DPO on on-policy pairs is the natural "post-train" row.

### 2.10 Ablation hygiene (applies to all)
- Same base checkpoint, same eval sets, same decoding (temperature 0, schema-constrained), same prompt.
- **Equal-N controls** whenever a technique changes data size.
- Report **bootstrap 95% CIs** over cases (Session C's `step6_evaluation/report.py` does this). With ~300 eval cases, a ±3-point difference is often inside the noise, so say so rather than over-claim.
- Seeds: training runs cost ~$3, so **2–3 seeds for the final comparison rows** are affordable and catch seed noise. Q-DS2: worth it?
- Table 2 can be **additive** (each stage on top of the last) or **leave-one-out** from the final recipe. Additive is cheaper and matches "delta from each pipeline stage"; leave-one-out is more rigorous. Q-DS3.

---

## 3. Four candidate invented techniques (KYC-specific)

Each is designed to be (a) KYC-specific, (b) buildable in ~3 hours on top of Session A's answer-first generator, (c) cheap to ablate, and (d) easy to name and explain in one sentence. They need the generator to re-render a latent truth with controlled edits; `step1_data_generation/truth.py` + `step1_data_generation/render.py` from Session A phase 2 are designed for that.

### 3.1 Counterfactual Twin Distillation *(already a candidate in `02` Plan)*
**One line:** train on minimal pairs of packets that differ in exactly one decision-relevant fact, and keep teacher outputs only when the teacher flips correctly across the twin.

- **Why KYC:** most KYC errors come from **attending to the wrong evidence** (name score instead of DOB; vendor score instead of identifiers). Twins force the model to locate the single fact that matters: passport valid ↔ expired; hit DOB match ↔ conflict; PoA 60 ↔ 120 days old; relationship stated ↔ not stated; MRZ confusable ↔ clean substitution.
- **Recipe:** (1) for M base truths, apply one *flip edit* from a catalog of ~10 flips; (2) re-render both twins with the **same** layout and noise seed (only the fact differs); (3) teacher-label both; (4) **keep the pair only if both teacher outputs match gold** (a pair-level rejection filter: stricter than single-case filtering, and it catches teachers that are right for the wrong reason); (5) train with SFT on both, **plus** DPO using the twin's wrong-for-this-packet answer as `rejected` (a natural hard negative).
- **Cost:** M=500 pairs = 1k teacher calls ≈ $8.5–43; GPU ~$3–6.
- **3-hour plan:** flip catalog + twin renderer (1.5 h) → teacher batch on Anthropic or live calls (0.5–1 h) → filter + train + eval (1 h).
- **Ablation:** +N twin cases vs +N independent cases (equal N, same flip-type distribution), and SFT-only twins vs SFT+DPO twins.
- **Metric to watch:** decision accuracy on **twin-sensitive eval categories** (expired, partial DOB, PoA stale), plus a *flip-consistency* metric on a held-out twin set: the fraction of pairs where the model changes its decision correctly.
- **Risk:** the model may learn "look for the diff" artifacts if twins are always adjacent in training; shuffle them.

### 3.2 Field-wise Splice Arbitration
**One line:** instead of picking the best *whole* teacher answer, build each training target field by field from whichever teacher got that field right, and keep the narrative only from a teacher whose every sentence is grounded.

- **Why KYC:** the output is a bundle of independent sub-judgments (5 field findings, N dispositions, tier, actions, decision). Teachers have **different strengths**: one is good at MRZ arithmetic, another at transliteration, another at policy. Whole-answer arbitration throws away a GPT answer with one wrong field even if its screening work is the best. Splicing keeps the best of each.
- **Recipe:** for each case, for each field, choose the value from the teacher(s) that match gold (ties: majority, then teacher with the higher historical per-field accuracy on a dev split). For per-hit `evidence` lists and reason codes, take the version from a teacher whose disposition matched. For the narrative: choose the teacher narrative with the best grounding score, then **regenerate only the sentences that contradict the spliced fields** (one cheap teacher call), or drop the case. Validate the spliced object.
- **Cost:** zero extra API if 3 teachers already labeled; small repair cost for narrative conflicts (~$5).
- **3-hour plan:** splice logic + consistency check (1.5 h) → narrative repair calls (0.5 h) → train + eval (1 h).
- **Ablation:** whole-answer arbitration vs field-wise splice at equal N; also report **data yield**: how many more cases survive filtering (splicing should recover many cases rejection sampling throws away).
- **Risk:** spliced fields + narrative can be inconsistent, so the consistency check is mandatory. Without gold (OOD-style data), splicing reduces to per-field majority vote, which still works.

### 3.3 Evidence Knockout (escalation calibration)
**One line:** programmatically remove or corrupt the single piece of evidence a decision depends on, so the gold answer becomes "escalate: insufficient evidence", and train the student to notice when the packet no longer supports a confident call.

- **Why KYC:** the brief's sharpest line is "a strong model knows when the evidence does not support a decision and escalates instead of guessing", and the adversarial metric measures exactly that. Ordinary cases rarely teach *when evidence is missing*, and teachers tend to guess. Knockouts manufacture that signal from cases we already have.
- **Recipe:** take a decisive case (e.g. a hit cleared as false positive *because* of a DOB conflict). Knock out the decisive evidence: delete the list DOB, make the applicant's DOB unreadable with heavy OCR damage, truncate the MRZ, remove the PoA date. Gold flips to `needs_review` / `unreadable` / escalate, via the policy. Teacher-label and keep outputs matching gold (teachers who still guess are filtered out, which is itself informative to report). Mix ~10–15% knockouts into training.
- **Cost:** ~500 knockout cases ≈ $4–22 per teacher; GPU ~$3.
- **3-hour plan:** knockout operators on the truth object (1.5 h; small, since they're truth edits plus the existing renderer) → teacher labels (0.5–1 h) → train + eval (1 h).
- **Ablation:** with vs without knockouts (equal N). Measure **escalation recall on ambiguous eval cases** and **over-escalation on clear cases** (the cost side: an always-escalating model must not look good).
- **Risk:** over-escalation. Report the precision of escalate decisions, not just recall.

### 3.4 Rendering-Invariance Filtering ("same truth, different paper")
**One line:** render each latent truth in several different packet layouts, keep teacher outputs only when the teacher gives the same structured answer across renderings, and train the student on all renderings with one target.

- **Why KYC:** the plan's **#1 risk** is overfitting to our own templates, since Zorbe's hidden set is "built by a different process". KYC packets vary wildly in practice (vendor formats, scan quality, field orders, date formats, name orders, address conventions). This technique makes invariance to presentation an explicit training signal and uses teacher *inconsistency* as a label-noise detector.
- **Recipe:** for each truth, render K=3 variants: different layout style (key-value / prose / form / mixed order), date format, name order, address convention, OCR-noise seed, and section ordering. Teacher-label all K. Keep the truth only if the teacher's structured fields agree across all K renderings **and** match gold. Train on all K renderings with the **same** (best-grounded) structured target; narratives may differ per rendering.
- **Cost:** K× teacher calls on the subset used (e.g. 700 truths × 3 = 2.1k calls ≈ $18–90 per teacher).
- **3-hour plan:** multi-render sampler (1 h; Session A's renderer already has several styles) → teacher labels (1 h) → train + eval (1 h).
- **Ablation:** N cases with 1 rendering each vs N/K truths × K renderings (equal N). Primary metric: the **gap between in-distribution eval and the OOD eval set**. If the technique works, the gap shrinks.
- **Risk:** fewer distinct truths at equal N, so content diversity drops. Report both ID and OOD scores so the trade is visible.

### 3.5 Honorable mention: Error-Surface Resampling
A variant of hard-case mining: fit a small logistic model of *student error* over the generator's knob vector (transliteration scheme, DOB-match type, tamper type, OCR rate, injection style, layout...) on the dev split, then sample new cases with probability proportional to the predicted error. It's more principled than "oversample the worst category", and the fitted coefficients double as a **failure taxonomy** for the stage 8 controller write-up. ~3 hours, but it depends on the knobs being logged per case, so ask Session A to log the knob vector in each truth object.

### 3.6 Comparison

| | Twins | Splice | Knockout | Invariance |
|---|---|---|---|---|
| Targets metric | decision, fields | all structured fields, data yield | adversarial escalation | OOD gap |
| Extra API | 1k calls | ~0 (+ repairs) | ~500 calls | 2k+ calls |
| Needs ≥2 teachers | no | **yes** | no | no |
| Needs generator edits | flip ops | none | knockout ops | multi-render |
| Story strength ("invented") | strong; already in plan | medium (a refinement of arbitration) | strong; maps to a brief quote | strong; maps to the #1 risk |
| Biggest risk | diff artifacts | inconsistent splices | over-escalation | less content diversity |

**Q-DS4:** which one gets the name in the write-up? These aren't exclusive: Knockout and Twins share the "truth edit + re-render" machinery, so building one makes the other ~1 hour.

---

## 4. Questions for Tianle (index)

| ID | Question |
|---|---|
| Q-DS1 | Add a gold-label SFT control row? |
| Q-DS2 | 2–3 seeds for the final comparison rows? |
| Q-DS3 | Table 2 additive or leave-one-out? |
| Q-DS4 | Which invented technique is ours, and which (if any) are extra rows? |
| Q-DS5 | Which teachers carry volume, given the Anthropic distillation-defense risk (`05` §5)? Affects arbitration and splicing |
| Q-DS6 | Is GRPO in scope at all, or explicitly cut, to protect Sunday? |
| Q-DS7 | Domain adapter (stage 2) data: Session A's `step3_domain_adapter/corpus/` + continued pretraining for ~1 epoch (~$2), reported honestly even if null? (Not in Session D's scope; listed for completeness) |
