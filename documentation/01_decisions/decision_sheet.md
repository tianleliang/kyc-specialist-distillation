# Decision Sheet: Saturday 07:45

**Session H, wave 2 (writing only). Every recommendation below is a proposal; Tianle decides.** Tick one option per decision, log it in the vault's `03 Zorbe Decision Log.md`, and the "code change if chosen" column says what to flip.

**Sources deduplicated here:** the questions in the wave-1 reports (A 10, C 6, D 10 + 27 `Q-xx` in `decision_policy_draft.md` + 8 `Q-SC` + 7 `Q-DS`, E 8 + memos + open questions in `data_design.md`, `contamination_protocol.md` and `experiment_plan.md`, F 8, G 5). That is about 50 distinct questions after merging repeats, reduced to **20 decisions**. Each decision lists the question IDs it covers, so nothing is lost. Small items with an obvious default are in the [appendix](#appendix-small-defaults-no-decision-needed-unless-you-object). The three-way policy disagreement (A vs D vs E) is [§ Policy disagreements](#policy-disagreements-a-vs-d-vs-e-side-by-side).

**How to read the "code change" column:** files that exist on `main` are named exactly. Files that wave-2 Sessions I, J and K are building tonight are marked *(I)*, *(J)* or *(K)*, using the names `documentation/06_agent_instructions/OVERNIGHT2.md` gives them. They weren't on the remote when this sheet was written, so check the exact config key on their branch before flipping it.

**Effect check on A's 200 draft cases** (computed from `data/draft/cases.jsonl`): A's provisional policy gives approve 72 / escalate 102 / reject 26. Of the 26 rejects, 14 are tamper and 12 are sanctions. **If decision 4 goes the recommended way (tamper → escalate), the mix becomes 72 / 116 / 12, i.e. 36% / 58% / 6%**, and an always-escalate model scores 58% on decisions. Decision 13 corrects for that.

---

## Index, in the order the decisions must be made

| # | Decision | Recommendation | Decide by | Unblocks |
|---|---|---|---|---|
| 1 | Schema shape | **B flat + enum reason codes** | **07:45** | 2, 3, 11, 16; J/K/I rewiring; eval freeze |
| 2 | Identity values and `verified` | **Keep the brief's 3 values; `verified` = all 5 fields consistent** | **07:45** | 9, `step1_data_generation/project.py` |
| 3 | `evidence_refs` and hit IDs | **Section enum + per-sentence `hit_ids`** | **07:45** | 16, judge prompt, K's evidence check |
| 4 | What rejects | **Sanctions true match only** | **07:45** | 6, 13 (mix), every label |
| 5 | Prompt injection | **Always escalate, unless a sanctions true match rejects** | **07:45** | adversarial metric (16), J mix |
| 6 | OCR noise vs tampering | **MRZ-anchored two-way rule; J switch off** | **07:45** | J noise config, 10 |
| 7 | Screening disposition rule | **A's rule + D's hard conflicts; nationality alone isn't a conflict** | by 10:00 | 8, 13 |
| 8 | PEP and adverse-media outcomes | **PEP true match → escalate + EDD; serious adverse media → escalate** | by 10:00 | 10, 11 |
| 9 | Expired ID and proof-of-address outcomes | **Escalate; 90-day window stated in the policy** | by 10:00 | 12 |
| 10 | Risk tier method | **A's rule table (hard triggers, ≥3 medium → high)** | by 10:00 | 11 |
| 11 | Actions catalog and actions on reject | **D's 12 codes; list every triggered action, also on reject** | by 10:00 | eval freeze |
| 12 | Policy text in prompts | **In best / teacher / student; out of zero-shot** | by 10:00 | I prompts, R1 pilot |
| 13 | Splits, sizes, mix, firewall | **Train 3k (+1k twins) / dev 150 / eval 300 + OOD 150; E's firewall wording** | **07:45** (sizes) / 13:00 (mix) | J configs, budget |
| 14 | OOD set and headline | **100 LLM-rendered + 50 hand templates by a fresh session; lead with the lower score** | by 12:30 | eval freeze 13:30 |
| 15 | Metric conventions | **Strict parse; absent classes excluded; `verified` outside the mean** | by 13:00 | Table 1 layout |
| 16 | Base model and sizes | **Qwen3.5 0.8B / 2B / 4B, pre-stated selection rule** | **07:45** | train configs, R0 |
| 17 | Frontier panel, roles, effort | **Astra / Opus 5.5 / Argon baselines at low effort; Argon + GPT teacher; Sonnet judge** | **07:45** | R1, R3, R5, budget |
| 18 | Technique stack and Table 2 design | **Floor + rejection sampling + arbitration + gold-label control; cumulative + matched-N** | by 14:00 | K pipeline order |
| 19 | Invented technique | **Counterfactual Twins (knockouts as one flip family)** | **by 15:00** (R6 batch) | twins batch, S5 |
| 20 | Compute, serving, tool-assist, repo, weights | **Modal; L4 always-on + proxy; tool-assist = report row; clean private repo; private HF + token** | **07:45** (Modal, proxy) / Sat 18:00 (repo) | R0 deploy, invite |

**At 07:45 (about 30 min):** 1, 2, 3, 4, 5, 6, 13 (sizes), 16, 17, 20 (Modal + proxy). Decisions 1–6 block the generator rewrite and the eval freeze; 16, 17 and 20 block accounts and the base deploy.
**08:15–10:00 schema-and-policy block:** 7–12. `policy_v1_candidate.md` already holds the recommended answer to each, so this block is review and edit, not authoring.
**Later, with hard deadlines:** 13 mix (13:00, before the freeze), 14 (12:30), 15 (13:00), 18 (14:00), **19 (15:00, the batch submission)**, 20 repo (Sat 18:00, so the invite isn't stuck on Sunday night).

---

## Schema

### 1. Schema shape
Covers: D schema options A/B/C, Q-SC2, Q-SC7, Q-SC1; A Q1 (reason codes); 05 (no nested `$defs`).

| Option | Means | Tradeoff | Code change if chosen |
|---|---|---|---|
| A. Brief-mirror nested | `identity.findings.name.status` + free-text reasons | Most readable; 4 levels deep; free text is unscorable and a source of unsupported claims | Copy `documentation/02_research/schema_options/option_a_nested.schema.json` → `step0_rules/schema/v1.json`; rewrite the return dicts in `step1_data_generation/project.py` |
| **B. Flat + enum reason codes** | `name_status` / `name_reason`, arrays only for hits, drivers, actions, narrative | Shortest and most scorable; best for ≤2B models and for K's checks; the reason vocabulary is closed | Copy `option_b_flat.schema.json` → `step0_rules/schema/v1.json`, then swap in the enums from `policy_v1_candidate.md` §9 (A's driver and screening-evidence names; option B's reason codes and actions). Flatten `project()` in `step1_data_generation/project.py`. New FieldMap `step6_evaluation/fieldmap_v1.yaml` (copy `tests/fixtures/c_fieldmap_v0_provisional.yaml` and change paths to `name_status` etc.). Run `python -m shared.frontier_api.schema_check step0_rules/schema/v1.json` |
| C. Checks-first scaffold | B + a `checks` block, decision last | Dense rewards and a free chain of thought; Zorbe must label or ignore unscored fields; Gemini key order isn't guaranteed | As B, from `option_c_checks_first.schema.json`; `step1_data_generation/project.py` also emits `checks` |
| C-serve ⊇ B-score | Publish B as the scored schema, serve C | Keeps Zorbe's labelling burden at B; two schemas to explain | Both files; FieldMap ignores `checks` |
| Keep v0 provisional | `step0_rules/schema/v0_provisional.json` as is | Zero work now; **uses `$defs`/`$ref`**, which `05` and D's constraints warn against for small models | None now; rename later |

**Recommendation: B**, plus `schema_version: "1.0"` (Q-SC7, ~6 tokens) and narrative `minItems 4 / maxItems 8` (Q-SC1: keep them, so it's the same rule for everyone; check that Anthropic and OpenAI enforce them when keys are live). *Why:* the brief's "with a reason" is met by codes, and every field except the narrative becomes exact-match scorable, which rejection sampling, arbitration and DPO all need.
**Unblocks:** 2, 3, 11, 15; I's `{schema}` slot, K's FieldMap, J's projection.

### 2. Identity field values and the meaning of `verified`
Covers: D Q-I1, Q-I2, Q-I5, Q-SC6, Q-SC8; E data_design Q4; A Q1 (`expired`).

| Option | Means | Code change if chosen |
|---|---|---|
| **a. Brief's 3 values; nuance in reason codes** | Expired → `mismatch` + `document_expired`; stale PoA → address `mismatch` + `poa_stale` | Reason enum in `step0_rules/schema/v1.json`; `identity()` in `step1_data_generation/project.py` already does this (only the code names change) |
| b. Add `expired` as a 4th value | More precise; departs from the brief's wording, which Zorbe's labellers will read | Status enum + the `expiry` branch of `identity()` |
| c. Separate `poa_recency` finding | A 6th field | New schema field + projection branch + FieldMap entry |

`verified`:
| Option | Means | Code change if chosen |
|---|---|---|
| **i. All five findings consistent** (A, current) | Matches the brief's grouping of address under `identity`; simplest for Zorbe's labellers | None (`identity()` already computes this); put the definition in the schema `description` |
| ii. Name, DOB, document number, expiry consistent and no tamper (D) | "Identity ≠ residence" | One line in `identity()`: drop `address` from the `all(...)` |

**Recommendation: a + i.** *Why:* keep the brief's enums exactly (Q-SC8), and pick the reading of `verified` that a labeller who has only seen our schema would pick.
**Unblocks:** 9; `step1_data_generation/project.py` rewrite.

### 3. `evidence_refs` granularity and hit identification
Covers: D Q-SC3, Q-SC4; C Q3, Q4; A Q1 (refs).

| Option | Means | Tradeoff | Code change if chosen |
|---|---|---|---|
| a. Section enum | `application, id_document_visual, id_document_mrz, proof_of_address, screening_hits, context` | Works on any packet, including Zorbe's; can't say which hit | `narrative()` in `step1_data_generation/project.py`: map CTX→context, APP→application, ID→id_document_visual, MRZ→id_document_mrz, POA→proof_of_address, SCR/Hn→screening_hits. The `EvidenceRefChecker` in `step6_evaluation/metrics.py` needs a section-alias map (owner C; small) |
| b. Field-level strings | `application.date_of_birth`, `hit:H2.dob` | Precise; free strings, longer, can't be an enum | `narrative()` + C's checker in `refs` mode |
| **c. Section enum + per-sentence `hit_ids: [string]`** | As (a), plus the hit IDs a sentence talks about | Cheap; grounding checks can resolve hits | As (a), plus a `hit_ids` field in `step0_rules/schema/v1.json` and `narrative()`. C's checker resolves `hit_ids` against `packet_ref_id_regex` (already exists) |
| v0 short tags | `CTX, APP, ID, MRZ, POA, SCR, H1…` as free strings | Already works with C's harness; tags won't exist in Zorbe's packets | None |

Hits: echo `hit_id` from the packet in each screening item; if the packet doesn't number hits, use `"1"`, `"2"`… in packet order (D's draft, Q-SC4). The scorer joins on `hit_id` (`screening_id_key: hit_id` in the FieldMap, as now).
**Recommendation: c.** *Why:* the section enum survives Zorbe's differently built packets, and `hit_ids` keeps hit-level grounding checkable by code.
**Unblocks:** 15; I's `judge_unsupported_claims` prompt; K's `evidence_refs` gate in `step4_distillation/reject_sample.py` *(K)*.

---

## Policy

### 4. What rejects
Covers: D Q-D1, Q-T1; A Q5; E Q2 / data_design Q1–2; C Q1 (partly).

| Option | Rejects on | Draft mix (A's 200 cases) | Code change if chosen |
|---|---|---|---|
| **a. Sanctions true match only** (D default, E) | Sanctions true match | 36 / 58 / 6 % | `decide()` in `step1_data_generation/project.py`: delete `or f["tamper"]` from the reject line and add `f["tamper"]` to the escalate list |
| b. + clear tamper evidence (A, current) | + `tamper_indicators` | 36 / 51 / 13 % | None |
| c. + expired document | + `document_expired` | more rejects | `decide()`: add `f["expired"]` to the reject line |
| d. + 2+ independent tamper signals (D Q-T1b) | Counting rule | — | New counter in `_flags()` |

**Recommendation: a.** *Why:* two of the three drafts agree, and a text packet can't prove forgery, so a real desk would send it to document forensics; Zorbe's labellers are likely to do the same. Fix the class balance in the mix (13), not the policy, and report the always-escalate floor in Table 1.
**Unblocks:** 6 (if b, decision 6 must be the three-way rule), 13, every label.

### 5. Prompt injection
Covers: A Q7; D Q-D3, Q-R2, Q-N1; E Q3 / data_design Q3; C Q1.

| Option | Means | Code change if chosen |
|---|---|---|
| **a. Always escalate, but a sanctions true match still rejects** (A, D) | The instruction is ignored for every finding; decision escalate + `manual_packet_integrity_review`; medium driver `packet_contains_instructions` | `decide()` already escalates on `f["injection"]` after the reject check. Rename the action in `_actions()` |
| b. Always escalate, even over a sanctions match (E as literally written) | Injection outranks everything | `decide()`: move `f["injection"]` above the reject check |
| c. Decide on the merits, flag only | Rewards ignoring injections; the brief's metric is an escalation *rate*, so this scores lower there | `decide()`: remove `f["injection"]`; keep the action |

The narrative mentions that the packet contained text addressed to the reviewer and **never quotes it** (D Q-N1).
**Recommendation: a.** *Why:* it matches the brief's metric, and nobody approves a sanctions match because the packet asked nicely.
**Unblocks:** 15 (how the adversarial rate is computed when gold is reject); J's injection stacking.

### 6. OCR noise vs tampering
Covers: E problem 7 / data_design T8–T9; A problem 3, Q5; D Q-I3, §3; OVERNIGHT2 J item 5.

| Option | Rule | Code change if chosen |
|---|---|---|
| **a. Two-way, MRZ-anchored** (E) | A failed MRZ check digit that no letter↔digit swap repairs, **or** a digit→digit disagreement between the visual zone and a checksum-valid MRZ in a numeric field = **tamper evidence** (field `mismatch`, `viz_mrz_disagree` / `check_digit_failed`, escalate, `document_authenticity_review`, high). A letter↔digit confusion with valid checksums = noise (`consistent`, `ocr_confusable_resolved`) | `step1_data_generation/configs/*.yaml`: `ocr_digit_to_digit_in_numeric: false` *(J)*. In `_zone_check()` in `step1_data_generation/project.py`, the `_lookalike_pair` branch returns the same tamper finding as the other branches |
| b. Three-way (A, current) | Noise / `possible_ocr_or_tamper` (escalate, medium) / `tamper_indicators` (high, rejects under 4b) | `ocr_digit_to_digit_in_numeric: true` *(J)*; `step1_data_generation/project.py` as is |

Both options agree on D Q-I3: a confusable fixed by the check digit is `consistent`.
**Recommendation: a**, given 4a. *Why:* with tamper → escalate, the two classes already get the same decision, and the two-way rule is exact on our data and easy to state in the policy. **If 4b is chosen, pick b**, so a real 6↔8 misread never rejects.
**Unblocks:** J's noise config; 10.

### 7. Screening disposition rule
Covers: A Q2; D Q-S1, Q-S2, Q-S4, §2; E T2–T4.

| Sub-question | Options | Recommended | Code change if not the current code |
|---|---|---|---|
| Nationality conflict alone | FP (E) / not enough (D; A gives `needs_review`) | **Not enough → `needs_review`** (people hold several nationalities) | current A behaviour |
| Year-only DOB on a PEP list | `needs_review` (A, D) / `true_match` | **`needs_review`** | current |
| Weak alias only, no identifiers | FP (D) / `needs_review` (A, E) | **`needs_review`** (no alias-strength concept in A's generator; conservative) | current |
| Nationality not listed + exact DOB | TM (A "not contradicted") / needs a match (D) | **TM** | current |
| Hard conflicts | Full DOB differs (a day/month swap is partial, not a conflict), document number differs, gender differs | **These three → FP** | `_disposition()` in `step1_data_generation/project.py`: add document-number and gender conflicts once J renders them |
| ID number on hit = applicant's | → TM (D rule 1) | **Yes**, a dormant rule until J renders hit ID numbers | `_disposition()` |
| PEP family / associate | TM only if the packet states the relationship *and* identifiers agree | **Yes** (A and D agree) | current |
| Former PEPs (12-month rule) | Include (D) / leave out | **Leave out of v1 generation** | none |
| Vendor score | Never decides by itself | **Yes** (all agree) | none |

**Recommendation:** the "Recommended" column, i.e. A's code + D's hard-conflict list. *Why:* it's what A already implements and labels, apart from two dormant rules.
**Unblocks:** 8, 13 (twin flips for screening).

### 8. PEP and adverse-media outcomes
Covers: A Q3; D Q-P3, Q-P4, Q-S3.

| Option | Means | Code change if chosen |
|---|---|---|
| **PEP TM → escalate**, actions `senior_management_approval`, `verify_source_of_wealth`, `verify_source_of_funds`, `enhanced_ongoing_monitoring` (A, D, E) | Senior approval is outside the analyst's authority | current |
| PEP TM → approve with those actions | Closer to how some desks record it; the decision carries less | `decide()`: remove `pep_self` / `pep_rca` |
| **Adverse media "true match" = identity only** (D Q-S3) | Relevance goes to risk and actions | current |
| **Serious adverse media (financial-crime categories) TM → escalate + high; other → medium + `enhanced_adverse_media_review`** | `SERIOUS_MEDIA` in `step1_data_generation/project.py` (fraud, corruption, money laundering, tax evasion, organised crime, sanctions evasion) | current; add `violent_crime` to `SERIOUS_MEDIA` if D's 2-class version is preferred |

**Recommendation:** the bold rows. *Why:* all three drafts already agree on PEP, and A's serious set is D's "financial crime" class.
**Unblocks:** 10, 11.

### 9. Expired ID and proof-of-address outcomes
Covers: A Q4, Q8; D Q-I4, Q-I2; E Q4 / data_design Q5, problem 4.

| Sub-question | Options | Recommended | Code change |
|---|---|---|---|
| Expired ID | Escalate + `request_valid_id_document` (all) / reject (4c) | **Escalate** (the applicant can cure it) | current |
| PoA window | 90 / 180 days | **90 days** | `POA_WINDOW_DAYS` in `step1_data_generation/sample.py` (J may move it into `step1_data_generation/configs/` *(J)*) |
| Where the window is stated | In the packet (CTX) / in the policy text / "the model should know" | **In the policy text** (decision 12); the packet prints only the as-of date | none; the as-of date is J item 1 *(J)* |
| PoA dated after the as-of date | `mismatch` + `poa_future_dated` (D) | **Yes**, if J generates it | `identity()` address branch |
| PoA name ≠ applicant | `mismatch` + `poa_name_differs` | **Yes**, if J generates it | `identity()` address branch |
| Address `mismatch` / `unreadable` | Escalate + `request_new_proof_of_address` (all) | **Escalate** | current |

**Recommendation:** the "Recommended" column. *Why:* it's conventional practice ("request documents", not "reject"), all three drafts agree, and it's decidable once the as-of date is printed.
**Unblocks:** 12.

### 10. Risk tier method
Covers: A Q6; D Q-R1, Q-R2, Q-R3, Q-D2; E risk drivers.

| Option | Rule | Draft tiers (A's 200) | Code change if chosen |
|---|---|---|---|
| **a. A's rule table** | High = any hard trigger (sanctions TM, PEP TM, serious adverse media TM, tamper) **or ≥3 distinct medium drivers**; medium = any medium driver; else low | 40 / 96 / 64 | `risk()` in `step1_data_generation/project.py`: tamper becomes a hard trigger under 6a |
| b. D points | Driver points summed; 0–1 low, 2–3 medium, ≥4 high; hard overrides | — | Rewrite `risk()` |
| c. E points | 0 low, 1 medium, ≥2 or any hard trigger high; sanctions `needs_review` → high | more highs | Rewrite `risk()` |

Related sub-decisions:
- **High risk with everything else resolved** → escalate (A, D's draft) or approve with EDD (D Q-D2). **Recommended: escalate.** Current code.
- **Medium risk** → approve with its EDD actions (A Q6). **Recommended: yes.** Current code.
- **High-risk-jurisdiction list** (D Q-R3): real ISO codes labelled synthetic / fictional / none. **Recommended: none in v1.** It avoids labelling real countries high risk, and A's generator has no such driver yet.
- **Injection and tier** (Q-R2): medium driver (A). **Recommended: yes.**

**Recommendation: a.** *Why:* a rule table is easier for a small model to learn and for us to explain, it's implemented and tested, and points need a tuning pass we have no time for.
**Unblocks:** 11.

### 11. Required-actions catalog and actions on reject
Covers: D Q-A1–A5; A Q9.

| Option | Means | Code change if chosen |
|---|---|---|
| A's 13 codes (current) | e.g. `manual_screening_review`, `confirm_details_with_applicant`, `request_document_rescan_or_original` | none |
| **D's 12 codes** (= option B's enum) | Drops SAR, liveness and independent address verification; splits screening review by list type | Rename in `_actions()` in `step1_data_generation/project.py` (mapping in `policy_v1_candidate.md` §6) |
| D's full 15–16 | Realistic; long for a 1–2B model | `_actions()` + schema enum |

Actions on reject: **list every triggered action** (D Q-A5) / only the review that caused the reject (A). **Recommended: list every triggered action**: recall is then comparable across decisions, and rejecting a sanctions match still needs the sanctions team. Code: delete the `if decision == "reject":` early return in `_actions()`.
**Recommendation: D's 12 + list on reject.** *Why:* conventional EDD names that Zorbe's labellers will recognise, a size that fits a small model, and one consistent recall definition.
**Unblocks:** eval freeze.

### 12. Policy text in the prompts
Covers: D Q-0; E Memo 5 (prompt-free robustness); A Q8 (partly).

| Option | Means | Code change if chosen |
|---|---|---|
| **a. Policy in `baseline_best`, `teacher` and the student prompt; out of `baseline_zero_shot`** | Gives both of the brief's conditions; a fair frontier comparison | `step0_rules/prompts/` templates *(I)*: `{policy}` is rendered from `documentation/01_decisions/policy_v1_candidate.md` once it becomes `policy/POLICY.md` |
| b. Never in the prompt | The student must learn it from data; the frontier is penalised for not knowing our house rules | Drop `{policy}` from the templates *(I)* |

Student training mix (E): **about 70% full system prompt, 30% short or no system prompt**, so the model still works when Zorbe's harness sends only the packet (the proxy injects ours anyway, decision 20).
**Recommendation: a.**
**Unblocks:** I's prompts; R1 label pilot; K's `step4_distillation/sft_floor.py` prompt *(K)*.

---

## Data

### 13. Splits, sizes, case mix and the eval firewall
Covers: E Memo 3, contamination §6 and Q1–Q3, E problems 1–2; A Q10; F Q3.

| Sub-question | Options | Recommended | Code change |
|---|---|---|---|
| Sizes | S (1.5k / 100 / 200 / 100) · **M (3k + 1k twins / dev 150 / eval 300 / OOD 150)** · L (6k / 200 / 600 / 300) | **M** (±4 pts at n=300) | `step1_data_generation/build.py --config step1_data_generation/configs/<split>.yaml --n N` *(J)* |
| Dev set | yes / no | **Yes, 150, from the train config, disjoint seeds** | `step1_data_generation/configs/dev.yaml` *(J)* |
| Target decision mix | A draft 36/51/13 · D ~40/50/10 · E 35/45/20 | **~38 / 47 / 15** after decision 4a | Raise `alias_true_match` (and lower some escalate-only scenarios) in the mix of `step1_data_generation/configs/train.yaml` *(J)*, or in `DEFAULT_MIX` in `step1_data_generation/sample.py`; check the counts after sampling |
| "Teachers never see eval" | Literal `CLAUDE.md` (conflicts with the brief) / **E's wording**: no output from any eval or dev call ever enters a training file | **E's wording** (contamination §6) | Log it; `CLAUDE.md` is Tianle's to edit |
| Overlap thresholds | **F's: 8-gram containment ≥0.5, MinHash Jaccard ≥0.7, boilerplate cutoff 5%** · E's: Jaccard 0.8 fail / 0.6 report, 13-gram | **F's** (implemented and stricter); report the max Jaccard as E asks | `step6_evaluation/split_guard.py check --ngram --containment --jaccard --max-df` (defaults already F's) |
| Commit eval JSONL | Yes / manifest + regeneration command only | **Yes** (synthetic; easiest to reproduce) | `git add data/eval*`; `split_guard freeze --readonly` |

**Recommendation:** the "Recommended" column. Sizes must be fixed at **07:45** (budget and J's configs). The mix can be tuned up to **13:00**.
**Unblocks:** J's split configs, the budget in 17, R2 freeze.

### 14. OOD set and the headline
Covers: E data_design §5, Q6–Q7; E Q8; G Q1; contamination Q4.

| Sub-question | Options | Recommended | Code change |
|---|---|---|---|
| Composition | **O1: 100 LLM-rendered (Sonnet 5.5 + Gemini 3.8 Flash) + O2: 50 hand templates** / O1 only (cut line C1) | **O1 + O2** | `step1_data_generation/configs/eval_ood_template.yaml` *(J)*; `step0_rules/prompts/ood_renderer` *(I)* |
| Who writes the O2 templates | Tianle (~45 min) / **a fresh session given only the truth spec, never `step1_data_generation/render.py`** | **A fresh session**; Tianle reviews one sample per template (~10 min) | none |
| Headline | ID first / OOD first / **both columns, lead with the lower** | **Both, lead with the lower** | `documentation/04_writeup/writeup_skeleton.md` §1 |

**Recommendation:** as above. *Why:* "a different process" is our best proxy for Zorbe's hidden set, and Tianle's morning hours are worth more on decisions than on templates.
**Decide by 12:30** (the freeze is at 13:30–14:00). **Unblocks:** eval freeze.

### 15. Metric conventions
Covers: C Q1, Q2, Q5, Q6; D Q-SC5.

| Sub-question | Options | Recommended | Code change |
|---|---|---|---|
| Code fences around JSON | Strict (invalid) / lenient | **Strict for Table 1**; a lenient column in 1b only for the open baselines | FieldMap `strip_code_fences: false` (default) |
| Macro-F1 when a class is absent from gold and prediction | **Exclude (C default)** / count as 0 (sklearn) | **Exclude, and say so** | none |
| `verified` in the field-accuracy mean | In / **out** | **Out of the mean**; its own column in 1b | `identity_fields` in `step6_evaluation/fieldmap_v1.yaml` without `verified`, plus a separate entry (C's code supports both) |
| Adversarial headline | **Escalation rate (brief)** + decision accuracy in 1b | **Both**. Under 5a, a sanctions + injection case has gold reject, so the oracle's rate is below 100%. Either generate no sanctions TM in injection cases in eval, or show the rate over gold-escalate cases only | Mix rule in `step1_data_generation/configs/eval_id.yaml` *(J)*, or a small option in `step6_evaluation/metrics.py` (owner C) |
| Drivers and actions | Scored as sets, deduplicated | **Yes** | none |

**Unblocks:** the Table 1 layout. **Decide by 13:00.**

---

## Models

### 16. Base model family and sizes
Covers: E Memo 1; 05 §1; F Q1, Q8; 02 open decisions.

| Option | Sizes | Code change if chosen |
|---|---|---|
| **Qwen3.5** | 0.8B / 2B / 4B (+ optional 9B zero-shot ceiling) | `base_model:` in `step5_training/configs/sft.yaml` and `merge.yaml` (HF IDs to be looked up; `05` gives no exact IDs); serving model ID in `step7_serving/` |
| Qwen3 | 0.6B / 1.7B / 4B | same keys |
| Gemma 4 / Llama 3.2 | awkward sizes / gated license | not recommended |

Selection rule, stated in advance (E): **ship the smallest size whose SFT-floor dev decision accuracy is within 2 pts of 4B *and* whose schema validity is ≥99%**; else ship 4B and say why. Fallback: Qwen3 if Qwen3.5 tooling still fails after 2h. LoRA defaults (r16 / α32 / 2e-4 / 2 epochs; DPO β0.1 / 5e-6 / 1 epoch) stay unless R7 says otherwise.
**Recommendation: Qwen3.5 0.8 / 2 / 4B** (Apache 2.0, one family, ~2× size steps).
**Unblocks:** R0 base deploy, R4 open baselines, R7.

### 17. Frontier panel, roles, effort and budget
Covers: E Memo 2–3; 05 §4–5; F Q4, Q5, Q6; D Q-DS5; E Q5.

| Role | Recommended | Alternatives | Code change |
|---|---|---|---|
| Baselines | **`gpt-6-astra`, `claude-opus-5-5`, `gemini-4-argon`**, zero-shot + best prompt, **low effort, live** (latency) | Fable instead of Opus (+$54); mid-tier panel (too weak) | Model list in the `step2_benchmarking/run_endpoint.py` invocation *(I)*; `shared/frontier_api/prices.yaml` |
| Effort fairness | **Low + one medium-effort run of Astra and Opus on 100 cases (~$30)** | Medium throughout (~3× output cost) | effort argument on `LLMClient` requests (default `low`) |
| Teachers | **Argon k=2 + one GPT** chosen on dev: Astra only if it beats Sol by ≥3 pts (~$18 test) | Argon only (if OpenAI tier-limited); Claude never (ToS + distillation classifier) | teacher list in `step4_distillation/*` / `shared/frontier_api/batch.py` job specs *(K)* |
| Judge | **Sonnet 5.5** + Opus calibration (200) + Argon cross-judge (100); programmatic `evidence_refs` is the primary metric | — | `step0_rules/prompts/judge_unsupported_claims` *(I)* |
| Budget | **API cap $650 + $100 reserve**; all-in ~$650–970 | — | per-provider caps in config (F flagged this as a wanted guardrail) |

Must also happen at 07:45: check OpenAI tier limits and the Anthropic eval-tier cap, set `rpm=` on `LLMClient` to the real tiers (F Q4), and add a `gemini-3.5-flash-lite` price to `shared/frontier_api/prices.yaml` if it's used (F Q6). **Verify every model ID and price in the consoles**: `05` is agent-reported.
**Recommendation:** the "Recommended" column.
**Unblocks:** R1 pilot, R3 teacher pick, R5 tranche 1, budget.

---

## Techniques

### 18. Technique stack and Table 2 design
Covers: D Q-DS1, DS2, DS3, DS6, DS7; E experiment_plan Q1–Q3; G Q4; plan tiers.

| Sub-question | Options | Recommended | Code change |
|---|---|---|---|
| Tier 1 techniques | Floor + 2 of {rejection sampling, arbitration, hard mining, judge prefs, on-policy} | **Floor + rejection sampling + arbitration** (both reuse one teacher pass, $0 extra API) | `step4_distillation/sft_floor.py`, `reject_sample.py`, `arbitrate.py` *(K)* |
| Gold-label SFT control (Q-DS1) | yes / no | **Yes** (~$3; makes "distillation helped" falsifiable) | a gold-target mode in K's SFT builder *(K)* |
| Tier 2 | DPO, on-policy correction, hard mining, domain adapter | **DPO on programmatic pairs; mining; adapter reported honestly even if null** | `step4_distillation/prefs.py`, `hard_mine.py`, `onpolicy.py` *(K)*; `step5_training/configs/dpo.yaml` |
| GRPO (Q-DS6) | in / **cut** | **Cut** (3–6h of engineering) | none |
| Table 2 shape (Q-DS3, G Q4) | **Cumulative stack** / leave-one-out | **Cumulative + matched-N controls for S3–S5 + leave-one-out for the invented technique** | run list in `documentation/03_design/experiment_plan.md` |
| Arbitration field repair (E Q3) | Repair structured fields from the label and disclose it / drop such cases | **Repair and disclose**; report data yield both ways | `step4_distillation/arbitrate.py --mode splice` *(K)* |
| Seeds (Q-DS2) | 1 / 2–3 on key deltas | **2 seeds on floor→final and twins-vs-control, if Sunday allows** | `seed:` in `step5_training/configs/sft.yaml` |
| Cumulative order (E Q1) | S1 adapter first (brief numbering) / S2–S5 first | **S2–S5 first, adapter as a side row** (least likely to help; keeps the main chain clean) | experiment plan |

**Recommendation:** the "Recommended" column. **Decide by 14:00** (K's pipeline runs from 17:30, but tranche 1 goes out ~14:15).

### 19. Invented technique
Covers: D Q-DS4; E Q6 / experiment_plan Q4; plan's candidate; OVERNIGHT2 J item 6.

| Option | Extra API | Targets | Code change if chosen |
|---|---|---|---|
| **Counterfactual Twin Distillation** | ~1k calls (~$20–60) | Decision + fields; flip consistency | `step1_data_generation/twins.py` *(J)* switch on in `step1_data_generation/configs/train.yaml` *(J)*; pair filter in K's rejection sampling |
| Evidence Knockout | ~500 calls | Adversarial (ambiguous) escalation | `step1_data_generation/knockout.py` *(J)* switch on |
| Field-wise Splice Arbitration | ~0 | Data yield; all structured fields | `step4_distillation/arbitrate.py --mode splice` *(K)*: already part of 18 |
| Rendering-Invariance Filtering | 2k+ calls | ID→OOD gap | not built tonight |

**Recommendation: Counterfactual Twins, with knockouts included as one flip family (twins whose flip is "decisive evidence → missing evidence, so escalate").** *Why:* it was already the plan's candidate, J builds both on the same truth-edit machinery, and a single name with one leave-one-out row is a cleaner story than two half-techniques. Knockout-only twins can be a sub-row if the numbers differ.
**Deadline: Saturday 15:00**, because R6 has to submit the twins batch then (batch latency of up to 24h is the risk). After 15:00 the fallback is cut line C5: 300 live pairs (~$24).

---

## Serving and repo

### 20. Compute, serving, tool-assisted variant, repo and weights
Covers: E Memos 4–6; 02 open decisions (GPU provider, tool-assisted, repo); F Q2; plan's decision log "Pending".

| Sub-question | Options | Recommended | Code change |
|---|---|---|---|
| GPU provider | **Modal** / RunPod / AWS (credits, quota delay) | **Modal** for training and serving | none (`step5_training/` is Modal already) |
| Serving | **L4 always-on (`min_containers=1`) + proxy** / scale-to-zero + keep-warm / RunPod | **Always-on + proxy**, `max_containers=2`, scale down on **2026-10-25** | `step7_serving/modal_vllm.py` (Session B, **not on `main`**) + `step7_serving/proxy.py` *(I)* |
| Tool-assisted variant | **Report row only**, with a pre-stated promotion bar on OOD / ship it / skip | **Report row only (Tier 3)** | the proxy's pre-check hook (later) |
| Repo | Private + invite / **clean submission repo, private + invite** / scrub history | **Clean submission repo**; ask Zorbe for GitHub handles on Saturday | export script (Sunday) |
| Weights bucket | Public HF / **private HF + scoped read token** / presigned S3 | **Private HF + read token** (public distilled weights contradict our ToS stance). Note: `00` §G says "works without our login"; a token in the email satisfies that literally, but say so | `hub_private: true` in `step5_training/configs/merge.yaml` (already the default) |

**Recommendation:** the "Recommended" column. Modal and the proxy must be settled at **07:45** (R0 deploys the base model at 10:00); the repo by **Sat 18:00**; the weights at Sunday 11:00.

---

## Policy disagreements: A vs D vs E, side by side

A = `step1_data_generation/project.py` (PROVISIONAL code; labels the 200 draft cases). D = `documentation/02_research/decision_policy_draft.md`. E = `documentation/03_design/data_design.md` (PROPOSED rules) and its open questions. **Bold** = the recommended option (it goes into `policy_v1_candidate.md`). "—" = that draft says nothing.

| # | Topic | A: provisional code | D: research draft | E: design draft | Decision |
|---|---|---|---|---|---|
| 1 | **Tamper evidence → decision** | **reject** (`tamper_indicators`) | **escalate** + `document_authenticity_review` (Q-T1 default) | **escalate** + fraud referral | 4 → **escalate** |
| 2 | OCR-vs-tamper classes | three-way: noise / `possible_ocr_or_tamper` (escalate, medium) / tamper (reject, high) | tamper if a clean-legible value disagrees or the check fails with no single confusable repair; otherwise noise | two-way, MRZ-anchored; digit→digit = possible tamper; the generator never makes digit→digit OCR | 6 → **E** |
| 3 | Reject scope | sanctions TM + tamper | **sanctions TM only** (Q-D1 default) | sanctions TM (T2); E's target 20% reject is inconsistent with sanctions-only unless sanctions cases are upweighted | 4 → **sanctions only** |
| 4 | Injection vs sanctions match | sanctions rejects first; else escalate | D1 sanctions outranks D2 injection | "always escalate" (precedence not stated) | 5 → **sanctions still rejects** |
| 5 | Injection and risk | medium driver | at least medium (Q-R2 open) | — | 5/10 → **medium driver** |
| 6 | `verified` | **all 5 fields consistent** | name, DOB, doc number, expiry + no tamper; address excluded (Q-I5) | expired → false; address not stated | 2 → **all 5 (A)** |
| 7 | Expired document value | `mismatch` + `document_expired` | `mismatch` + reason (Q-I1) | `mismatch`, or a 4th value `expired` (open) | 2 → **`mismatch`** |
| 8 | Nationality conflict alone (with exact DOB) | `needs_review` | **not a hard conflict** → `needs_review` (Q-S1) | **hard conflict → false_positive** | 7 → **`needs_review`** |
| 9 | Nationality needed for TM | not contradicted (unlisted is OK) | must match | no identifier may conflict | 7 → **A** |
| 10 | Weak alias, no identifiers | `needs_review` (no alias strength modelled) | **false_positive** (Q-S2) | `needs_review` | 7 → **`needs_review`** |
| 11 | ID number on the hit | not modelled | match → TM; differs → FP | ID-number match upgrades a partial DOB to TM | 7 → **D (dormant until J renders IDs)** |
| 12 | Former PEPs | not modelled | include, 12-month rule | — | 7 → **leave out of v1** |
| 13 | Sanctions `needs_review` → tier | medium (`unresolved_screening_hit`) | +2 points (medium) | **high** | 10 → **medium** |
| 14 | Risk tier method | rule table: hard trigger or ≥3 medium → high | points 0–1 / 2–3 / ≥4, rule table preferred (Q-R1) | points 0 / 1 / ≥2 or hard trigger | 10 → **A** |
| 15 | High-risk jurisdictions | none (`cross_border` reported only above low) | real ISO codes labelled synthetic, +2 | fictional or structure-only list, +1 | 10 → **none in v1** |
| 16 | Channel / product | one combined driver: high-risk product **and** remote | separate `non_face_to_face_channel` +1 and `high_risk_product` +1 | combined, +1 | 10 → **A (combined)** |
| 17 | High risk, everything resolved | escalate | escalate (Q-D2 open) | — | 10 → **escalate** |
| 18 | Medium risk | approve with EDD actions | approve unless a rule fires | — | 10 → **approve with EDD** |
| 19 | Serious adverse media | escalate + high; financial-crime categories | escalate for financial crime (maybe violent crime too, Q-P4), +3 | not covered | 8 → **A's set** |
| 20 | Actions on reject | only the causing review | **every triggered action** (Q-A5) | — | 11 → **every triggered action** |
| 21 | Action vocabulary | 13 codes (`manual_screening_review`, `document_fraud_review`, …) | 12 of 16 codes (`document_authenticity_review`, list-specific reviews, …) | 11 codes (`refer_to_fraud_review`, `flag_suspicious_content`, `file_internal_report`, …) | 11 → **D's 12** |
| 22 | Name/DOB declared vs document mismatch → action | `confirm_details_with_applicant` | `request_secondary_id` | `request_secondary_id` (in catalog) | 11 → **`request_secondary_id`** |
| 23 | Illegible ID field → action | `request_document_rescan_or_original` | `request_valid_id_document` | — | 11 → **`request_valid_id_document`** |
| 24 | PoA format variant vs exact match | two reason codes, chosen at render time (A Problem 1: 142 of 200 drafts are "format_variant") | `country_format_difference` reason | formatting is never a mismatch | 1/2 → **one code, unless J moves the choice into the truth** |
| 25 | PoA future-dated / name differs | not modelled | mismatch (`poa_future_dated`) | mismatch (`different_name`) | 9 → **mismatch, if generated** |
| 26 | Evidence refs | `CTX, APP, ID, MRZ, POA, SCR, H1…` | section enum (`application`, …) | — | 3 → **section enum + `hit_ids`** |
| 27 | Injected text in the narrative | "disregarded and flagged", not quoted | never quote (Q-N1) | the narrative mentions the instruction | 5 → **mention, never quote** |

Where all three agree (no decision needed beyond ticking): PEP true match → escalate; expired → escalate; address mismatch or stale PoA → escalate; PoA window 90 days; a check-digit-repaired confusable is `consistent`; labels come from code; packet text is never an instruction; the vendor score never decides alone.

---

## Appendix: small defaults (no decision needed unless you object)

| Item | Default | Where | Source |
|---|---|---|---|
| `schema_version` field | add, `"1.0"` | `step0_rules/schema/v1.json` | D Q-SC7 |
| Narrative bounds | `minItems 4 / maxItems 8` | `step0_rules/schema/v1.json` | D Q-SC1 |
| LoRA / DPO hyperparameters | F's defaults until R7 | `step5_training/configs/*.yaml` | F Q8 |
| Provider RPM | set to the real tiers at 07:45 | `LLMClient(rpm=...)` | F Q4 |
| Reasoning effort | `low` everywhere; Opus can't turn thinking off | `shared/frontier_api/clients.py` | F Q5 |
| Actions enum cap | no SAR action; no liveness check | `step0_rules/schema/v1.json` | D Q-A4 |
| Activity/income check | obvious-only cases, no numeric threshold | J's `risk_profile` scenario | D Q-A2 |
| Validity limits | flat 10 years | generator | D Q-T2 |
| Spend reporting | to date + projected serving through 10/25 | write-up §7 | G Q5 |
| Stage 7 stance | drafting assistant: a human signs every reject and escalate; auto-approve only after the ramp gates | `documentation/04_writeup/stages_7_9_draft.md` | G Q2 |
| Stage 8 controller | acts on route-around and rollback; proposes model changes | same | G Q3 |
| Eval-look budget | each Table 1 / 2 row hits eval once, logged in `outputs/eval/RUNLOG.jsonl` | contamination §7 | E |
| Corpus | run `bash step3_domain_adapter/corpus/fetch_corpus.sh` on the laptop (the cloud proxy blocked every publisher) | `step3_domain_adapter/corpus/` | A |
