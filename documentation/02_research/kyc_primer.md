# KYC Adjudication Primer (20-minute read)

*Session D overnight research, 2026-10-17. Background reading only. **It makes no decisions.** Anything that reads like a rule here describes common industry practice or a public standard. Our own rules live in `decision_policy_draft.md`, as a draft for Tianle to decide.*

Who it's for: a smart reader new to compliance who has to design a schema, a decision policy and a generator for synthetic KYC cases by tomorrow morning.

How to read it: sections 1–3 in order (about 8 minutes), then sections 4–9 as reference. Section 10 maps each topic to the brief's "what makes it hard" list. Sources are listed at the end, numbered as **[n]**.

---

## 1. What a KYC analyst actually does

A new applicant at a bank or fintech triggers **customer due diligence (CDD)**. FATF Recommendation 10 requires firms to (a) identify the customer and verify that identity with reliable, independent documents, (b) identify beneficial owners, (c) understand the purpose and intended nature of the relationship, and (d) monitor it on an ongoing basis [1]. In the US, the **Customer Identification Program (CIP)** rule asks for at least name, date of birth, a residential address and an ID number, verified "within a reasonable time" by documentary or non-documentary means. For individuals, the documentary means is an **unexpired** government-issued photo ID [4]. The 2016 FinCEN **CDD Final Rule** added the beneficial-ownership requirement for legal-entity customers and made "understand the nature and purpose" plus ongoing monitoring explicit [3]. Our cases are individuals, so beneficial ownership mostly matters through **PEP close associates** (section 3).

An analyst's adjudication runs in the same order for almost every case:

1. **Read the application.** Who does the applicant say they are? What do they do, where does their money come from, and what activity do they expect? This sets the **expected profile**.
2. **Verify identity against the ID document.** Compare each field (name, DOB, document number, expiry, nationality) between the application, the document's visual zone (the printed text) and the **MRZ** (the machine-readable lines). Check the expiry date. Check the MRZ check digits.
3. **Verify address against proof of address (PoA).** Does the name match? Does the address match? Is the document recent enough, and of an acceptable type?
4. **Disposition each screening hit.** For every sanctions, PEP or adverse-media alert, decide **true match / false positive / needs review** by comparing secondary identifiers, not just the name.
5. **Assess risk.** Combine customer factors (PEP status, occupation, source of funds versus expected activity), geography (high-risk jurisdictions), product/channel (non-face-to-face onboarding is higher risk) and the findings above into a **risk tier**.
6. **Decide and record.** Approve (possibly with EDD conditions), reject, or escalate to a senior reviewer or specialist team. Then write a case note that another analyst or an examiner can follow. **Every claim in that note must point to evidence in the file.**

Three things analysts internalize that a model must learn:
- **Name similarity is cheap, identifiers are expensive.** A 92% name score with a mismatched DOB and nationality is usually a false positive. A 78% score with a matching DOB, nationality and passport number is probably a true match.
- **Absence of evidence ≠ evidence of absence.** If the list entry has no DOB and the name is a strong match, the analyst can't clear the hit. That's "needs review", not "false positive".
- **The file must survive an audit.** Decisions are judged later by people with hindsight. A defensible escalation beats an undefendable approval.

---

## 2. Three kinds of screening: sanctions vs PEP vs adverse media

| | Sanctions | PEP | Adverse media |
|---|---|---|---|
| **What it is** | Government lists of people and entities you may not deal with (OFAC SDN, UN Security Council Consolidated List, EU Consolidated Financial Sanctions List, UK OFSI list) | People entrusted with prominent public functions, plus their family and close associates | Negative news linking a person to financial crime, corruption, fraud, terrorism, etc. |
| **Legal effect** | **Prohibition.** In the US it is effectively strict liability [6]. A true match means you can't onboard, and property may have to be **blocked** and reported | **Not prohibited.** A PEP is a *risk factor* that triggers enhanced measures [1][2] | **Not prohibited.** A risk factor whose weight depends on the severity, credibility and recency of the allegation |
| **True match →** | Reject or block, report (US: blocked or rejected transaction reports to OFAC within 10 business days [7]), notify the sanctions/compliance team. No discretionary approval | EDD: senior-management approval, establish source of wealth and source of funds, enhanced ongoing monitoring [1] | Depends on the content: an unproven allegation leads to EDD and review; a conviction for financial crime often leads to reject or exit under the firm's risk appetite |
| **Typical alert volume** | High. Most alerts are false positives | Medium. Commercial PEP databases are large | High and noisy. Name collisions are common |
| **Structure of a list entry** | Name, aliases (OFAC distinguishes "a.k.a." from lower-quality **"weak a.k.a."** [6]), DOB (often several, or a year only), place of birth, nationality, ID/passport numbers, address, program tag (e.g. `[SDGT]`, `[IRAN]`), listing date | Name, position, country, start and end dates, relationship type (self / family / close associate) and the linked PEP | Name, article source, date, category (fraud, bribery, ...), excerpt |

**Why sanctions are different:** OFAC's enforcement guidelines treat a violation as a violation regardless of intent; intent and compliance-program quality only affect the *penalty* [6]. That's why a firm will **never approve over a confirmed sanctions match**, and why an *unresolved* strong sanctions hit must be escalated rather than cleared.

**OFAC 50 Percent Rule** (useful for entities, rarely for individuals): an entity owned 50% or more, in aggregate, by blocked persons is itself blocked even if it isn't listed [8]. In our individual-applicant cases this shows up only if the packet discloses that the applicant's employer or source-of-funds entity is owned by a listed person.

**UN and EU lists** use a similar structure: a reference number, name in original script plus transliterations, "good quality" vs "low quality" aliases (the UN list makes that distinction explicitly), DOB, POB, nationality, passport/national ID, address, listing date and narrative reasons [9][10]. Our synthetic watchlists should copy these **structures** with fictional names only (see `CLAUDE.md`).

---

## 3. PEPs: who counts, and the family/close-associate rules

### FATF definitions [1][2]
- **Foreign PEP:** prominent public function in a *foreign* country: heads of state or government, senior politicians, senior government, judicial or military officials, senior executives of state-owned corporations, important political party officials.
- **Domestic PEP:** the same functions in the firm's *own* country.
- **International-organisation PEP:** senior management of an international organisation (directors, deputy directors, board members).
- **Explicitly excluded:** middle-ranking or more junior officials.

### Required measures (FATF R.12) [1]
- **Foreign PEPs: always.** (a) Risk-management systems to determine PEP status; (b) **senior management approval** to establish (or continue) the relationship; (c) reasonable measures to establish **source of wealth and source of funds**; (d) **enhanced ongoing monitoring**.
- **Domestic and international-organisation PEPs: risk-based.** Apply (b)–(d) only where the relationship is assessed as higher risk.
- **Family members and close associates:** the same requirements apply to them as to the PEP they're linked to [1].

### Who is "family" and a "close associate"
FATF's 2013 guidance leaves exact scope to countries, on a risk basis [2]. The EU's legal definitions are the most-cited concrete version (Directive (EU) 2015/849, Art. 3(9)–(11)) [11]:
- **Family members:** spouse or equivalent partner; **children and their spouses or partners**; **parents**. Siblings are *not* in the EU minimum list. FATF guidance notes that a wider circle (e.g. siblings) may be included on a risk basis [2].
- **Persons known to be close associates:** (i) joint beneficial ownership of a legal entity or arrangement with a PEP, or any other close business relationship with a PEP; (ii) sole beneficial ownership of an entity known to have been set up *for the de facto benefit* of a PEP.

### How long someone stays a PEP
- FATF: no fixed time limit. Base it on risk, considering the level of influence the person may still exercise and links between the former and current functions [2].
- EU: for **at least 12 months** after leaving office, and until the person is assessed as no longer posing PEP-specific risk (Art. 22) [11].
- UK FCA guidance (FG17/6) applies the same 12-month floor, treats domestic PEPs as lower risk by default, and says family and associates generally stop being treated as PEPs once the PEP leaves office [12].

### Practice notes for our generator
- **Relationship evidence matters.** A PEP hit on an applicant who is the *daughter-in-law* of a minister is a true PEP match **only if** the packet supports the relationship (shared surname is *not* enough; a declared relationship, a matching linked-person record or a shared business does). Otherwise it's needs review.
- **A PEP match is not a reason to reject.** It's a reason for EDD and, at many firms, senior sign-off. In a three-way decision space that usually means escalate. This is a key policy question (see `decision_policy_draft.md` Q-P3).
- **Corruption adverse media + PEP** is the classic high-risk combination [2].

---

## 4. True match vs false positive in practice

Screening engines produce **candidate hits** with a similarity score. The analyst's job is to **resolve** each one. The Wolfsberg sanctions screening guidance describes this alert-investigation process, and stresses that name matching alone is never conclusive and that secondary identifiers drive the disposition [5].

### The standard resolution procedure
1. **Is the name genuinely similar once normalized?** Account for transliteration (Мухаммад → Mukhammad / Muhammad / Mohammed), reordering (Chinese and Hungarian family-name-first; Arabic *nasab* chains like "bin/ibn"), dropped or extra particles (al-, el-, van der, de), initials, and aliases. A vendor score is a hint, not a fact. Vendors over-score common names and under-score heavy transliteration.
2. **Compare secondary identifiers**, strongest first:
   - **Unique IDs** (passport or national ID number): a match is near-conclusive; a clear mismatch is strong exculpatory evidence (allow for re-issued passports).
   - **Date of birth:** full match, partial match or conflict (section 5).
   - **Nationality / place of birth / citizenship.**
   - **Gender, address, occupation, known associates.**
3. **Disposition:**
   - **True match:** name consistent **and** at least one strong identifier matches with nothing conflicting.
   - **False positive:** at least one **hard conflict** (different DOB where the list gives a full DOB, different nationality *and* POB, different ID number, gender conflict) with nothing pointing to a match.
   - **Needs review:** the name is consistent, the identifiers neither confirm nor rule out (the list has no DOB or a year only, nationality partly overlaps, the identifier is unreadable in the OCR), **or** the evidence conflicts.
4. **Record the evidence used.** The note says *which* identifiers were compared and what each showed. This is the brief's "with the evidence used".

### Common false-positive patterns (use as generator knobs)
- Common names ("Li Wei", "Mohammed Ali" types; fictional equivalents) against a list entry with a different DOB.
- Same name, different nationality and a 20+ year DOB gap.
- Partial-token matches: one shared given name plus a common family name.
- Hits against **weak or low-quality aliases** [6][9].

### Common true-match patterns that look like false positives
- Heavy transliteration drops the vendor score below 80, but the DOB and passport number match.
- Name reordered (family name first) plus a dropped middle name.
- The applicant uses a list **alias**, not the primary name.

---

## 5. Partial date-of-birth matching

Lists are messy about dates. OFAC and UN entries often give **multiple DOBs**, **a year only**, **"circa"** years, or ranges ("1960 to 1962") [6][9]. Applicants give a full date. The analyst classifies the comparison:

| Applicant DOB vs list DOB | Interpretation | Usual effect |
|---|---|---|
| Exact full-date match | Strong supporting identifier | Pushes toward true match |
| List has year only; year matches | **Consistent but not confirming** | Can't clear on DOB; needs another identifier |
| List year range or "circa"; applicant's year inside it | Same as above | Same |
| Day and month swapped (03/04 vs 04/03): DD/MM vs MM/DD confusion | **Possible format artifact** | Treat as partial; look at other identifiers |
| Same day and month, year off by 1 | Possible typo or transliteration of a different calendar | Partial; needs review if the name is strong |
| Year differs by >2 and the list gives a full date | Hard conflict | Pushes toward false positive |
| List has no DOB | No information | Can't clear on DOB |

**Calendar traps** to include in data: Hijri vs Gregorian dates, Persian (Solar Hijri) dates, and ambiguous formats like `04/03/1985`. A good model notices ambiguity rather than resolving it silently.

---

## 6. Enhanced due diligence (EDD): a catalog of 15 standard actions

EDD is required for higher-risk relationships: foreign PEPs, high-risk third countries, unusual activity [1]. The list below is a catalog of the steps analysts commonly require, with the usual triggers. It is a menu for the schema's `required_actions` enum. **Which ones we include, and their exact triggers, is Tianle's call** (`decision_policy_draft.md` §4).

| # | Action (suggested enum) | What it is | Typical trigger |
|---|---|---|---|
| 1 | `senior_management_approval` | Sign-off by a senior manager or MLRO before onboarding | Any foreign PEP; higher-risk domestic PEP; their family or close associates [1] |
| 2 | `verify_source_of_wealth` | Evidence of how total wealth was accumulated (salary history, business sale, inheritance) | PEP (FATF R.12 [1]); high-net-worth declared wealth inconsistent with occupation |
| 3 | `verify_source_of_funds` | Evidence of where the *specific* money for this account comes from (payslips, sale contract) | PEP [1]; declared source of funds vague or inconsistent; expected activity far above stated income |
| 4 | `enhanced_ongoing_monitoring` | Lower alert thresholds, more frequent reviews | PEP [1]; high risk tier at approval |
| 5 | `request_valid_id_document` | Ask for an unexpired, readable ID | Expired ID (CIP requires an *unexpired* ID [4]); key fields unreadable |
| 6 | `request_secondary_id` | Second, independent identity document | ID partly unreadable; name or DOB mismatch with a plausible explanation; MRZ problem not clearly OCR noise |
| 7 | `request_new_proof_of_address` | Fresh, acceptable PoA | PoA too old; wrong document type; name or address mismatch with the application |
| 8 | `independent_address_verification` | Non-documentary check (credit bureau, electoral roll equivalent) | PoA unreadable or contradictory; mismatch with a plausible explanation (recent move) |
| 9 | `document_authenticity_review` | Manual or forensic document check by a specialist team | Signs of tampering: VIZ–MRZ disagreement on clean characters, check-digit failures not explained by OCR confusables, impossible dates |
| 10 | `biometric_liveness_check` | Selfie/video match against the ID photo | Non-face-to-face channel with any identity doubt; suspected impersonation |
| 11 | `sanctions_compliance_review` | Referral to the sanctions team for a decision; potential block and report [7] | Any sanctions hit not clearly a false positive |
| 12 | `enhanced_adverse_media_review` | Deeper search and assessment of the allegation's credibility, severity and recency | Adverse-media hit that is a true match or needs review |
| 13 | `clarify_occupation_and_activity` | Ask the customer to explain occupation, expected volumes and purpose | Expected activity inconsistent with occupation or income; vague source of funds |
| 14 | `pep_relationship_confirmation` | Confirm whether, and how, the applicant is related to the listed PEP | PEP hit via family or association that the packet neither confirms nor rules out |
| 15 | `consider_suspicious_activity_report` | Refer internally to the MLRO for a SAR/STR decision | Strong tampering evidence; sanctions-evasion indicators; injected instructions that look like deliberate manipulation (policy question). **Note:** in practice the analyst *refers*; the MLRO decides. Tipping-off rules forbid telling the customer [1, R.21] |

Optional extras, if Tianle wants them: `geographic_risk_review` (high-risk jurisdiction or FATF "grey/black list" country), `manual_packet_integrity_review` (packet contains instructions aimed at an automated reviewer).

---

## 7. Escalate vs reject

Real desks have more than three outcomes: approve, approve with conditions, pend / request information, escalate (to senior, sanctions, fraud or MLRO), decline / reject, and exit (for existing customers). The brief collapses these to **approve / reject / escalate**, so the mapping is a design choice. Common practice:

- **Reject (decline)** when the firm *knows* enough to say no:
  - a confirmed sanctions true match (prohibition);
  - clear evidence of fraud or tampering (the document is forged, not merely unreadable);
  - the applicant is outside risk appetite by a clear policy rule (e.g. a prohibited jurisdiction or product);
  - (sometimes) failure to provide required CDD after requests. In a single-packet setting that can't happen, so it's usually not a reject trigger.
- **Escalate** when a decision needs **authority or information the analyst doesn't have**:
  - an unresolved hit (needs review) on any list;
  - a PEP true match (needs senior approval and SoW/SoF);
  - ambiguous evidence: OCR noise vs tampering can't be told apart; mismatches with plausible innocent explanations;
  - conflicts between sources that can't be resolved from the packet;
  - **anything abnormal about the packet itself**, including text addressed to the reviewer ("ignore previous instructions...").
- **Approve** when identity is verified, no hit is a true match or needs review, and the risk tier is within appetite (possibly with monitoring actions).

The brief's own framing points the same way: "A strong model knows when the evidence does not support a decision and escalates instead of guessing", and the adversarial metric is the **escalation rate** on injected instructions and ambiguous evidence.

**Grey zone to flag for Tianle:** an expired ID or stale PoA with everything else clean. Many desks would *pend* (request a new document). In our 3-way space that's escalate (needs more information) or reject (fails CIP as submitted). Both are defensible; it must be one rule, applied consistently.

---

## 8. Tampering vs OCR-noise red flags

### MRZ basics (ICAO Doc 9303) [13]
- **TD3** (passport): 2 lines × 44 characters. **TD1** (ID card): 3 lines × 30 characters. (TD2: 2 × 36.)
- **Check digits** cover the document number, DOB, expiry, optional data (TD3 personal number) and a **composite** check over several fields. Algorithm: map `0–9` → 0–9, `A–Z` → 10–35, `<` → 0; multiply by repeating weights **7, 3, 1**; sum; take mod 10 [13, Part 3].
- Dates are `YYMMDD`. Names are `SURNAME<<GIVEN<NAMES`, transliterated to A–Z under the ICAO rules (e.g. Ä → AE or A, Ñ → N), so the MRZ name can legitimately differ from the visual-zone name.

### How the two look different in text
| Signal | More likely **OCR noise** | More likely **tampering** |
|---|---|---|
| The differing character | Is a classic confusable: `0/O`, `1/I/l`, `5/S`, `8/B`, `2/Z`, `rn/m`, `6/G` | Is a clean, non-confusable substitution (`3`→`8` in a date, `4`→`9`) |
| Check digits | Fail **only** where a confusable sits; recompute OK if you swap the confusable back | Fail on a clean character, **or** pass in the MRZ while the **visual zone** shows a different value (the forger edited only the printed data) |
| Spread | Random, spread across the document, also affects unimportant fields | Targeted at **decision-relevant** fields (DOB to make someone older or younger, expiry to make an expired doc valid, name to dodge a screening hit) |
| Cross-source consistency | Application and one of VIZ/MRZ agree; the other is garbled | VIZ and MRZ **disagree with each other**, both cleanly legible; or the doc agrees with the application but not with its own MRZ |
| Date logic | Dates plausible | Impossible or implausible dates: issue after expiry, validity longer than the issuing state's maximum (commonly 10 years for adult passports), issue date before DOB, expiry on a weekend/holiday pattern inconsistent with the issuer |
| Format | Spacing and line breaks broken (wrapped MRZ lines, missing `<` fillers) | Fields well formed but with the wrong length or format for the issuing state; document number format wrong for the country |

**The hard cases the brief asks for, as generator recipes:**
- *OCR error that looks like tampering:* `O` read for `0` inside the DOB in the MRZ → the DOB check digit fails → but swapping `O→0` restores it, and the VIZ DOB matches the application. Correct: **consistent / no tampering**, perhaps `unreadable` on the field if we're strict.
- *Tampering that looks like OCR error:* the VIZ expiry `2027` vs MRZ `22xxxx` (expired), and the "difference" is `2`↔`7`, not a confusable. The MRZ check digit is valid for the 2022 date. Correct: **mismatch → document authenticity review → escalate (or reject)**.

---

## 9. Proof-of-address recency and acceptability

- **No single global rule.** US CIP requires collecting a residential address; verification can be documentary or non-documentary and does **not** mandate a utility bill [4]. In the UK, the JMLSG Guidance describes address verification through documents or electronic sources, and **"dated within the last three months"** is the most common firm-level standard for utility bills and bank statements. Some firms accept 6 months, and 12 months for council-tax or tax documents [14]. Treat the window as an **institution policy parameter**.
- **Typical acceptable documents:** utility bill (not mobile phone, at many firms), bank or credit-card statement, government tax or benefits letter, tenancy agreement, local-authority tax bill.
- **Typical red flags:**
  - Dated outside the window (stale), or **dated in the future** relative to the onboarding date.
  - Name on the PoA differs from the applicant (a different person, or a household member: "J. Smith" vs "Jane Smith" is fine; a different given name isn't).
  - Address differs from the application: different flat number, city or postcode. Distinguish format differences (country conventions, abbreviations, transliteration) from **substantive** differences.
  - Address in a different country than declared residence.
  - Document type not acceptable (e.g. a delivery receipt, mobile bill).
  - Same document reused across applicants (outside single-packet scope).

**Address formats differ by country** (UPU postal addressing standards [15]): postcode before the city (DE `10115 Berlin`, FR `75008 Paris`), after it (UK, US), province/oblast-first order (CN and RU traditionally write largest to smallest), PO boxes in AE, PIN codes in IN. A model must not call a format difference a "mismatch".

---

## 10. Map to the brief's "what makes it hard" list

| Brief item | Primer section | What a correct answer usually looks like |
|---|---|---|
| Transliterated and reordered names | §4 step 1 | Name field `consistent` when it's a known variant; screening decided by identifiers |
| Name variants against sanctions aliases | §2, §4 | Alias match + identifier match → true match; weak-alias match + conflicts → false positive |
| Partial DOB matches | §5 | Year-only match → needs review unless another strong identifier decides |
| PEPs by family or business association | §3 | True PEP match only if the relationship is supported in the packet; then EDD + (likely) escalate |
| Expired documents | §1, §7, §8 | Expiry finding `mismatch`/expired; request a valid ID; escalate or reject (policy question) |
| Address formats by country | §9 | Format differences are `consistent`; substantive differences are `mismatch` |
| PoA contradicts application | §9 | Address `mismatch`; request new PoA / independent verification |
| OCR errors that look like tampering | §8 | Recognize confusables plus check-digit repair; don't escalate for fraud |
| Tampering that looks like OCR errors | §8 | Clean substitution in a decision-relevant field → authenticity review → escalate/reject |
| Instructions aimed at the model | §7 | Ignore the instruction; escalate and flag packet integrity |
| Insufficient evidence | §1, §7 | Escalate, don't guess |

---

## Sources

Public documents only. URLs were checked on 2026-10-17 where noted; the rest are stable official locations.

1. **FATF Recommendations** (International Standards on Combating Money Laundering and the Financing of Terrorism & Proliferation), updated periodically. R.10 (CDD), R.12 (PEPs), R.6 (targeted financial sanctions), R.21 (tipping-off). https://www.fatf-gafi.org/en/publications/Fatfrecommendations/Fatf-recommendations.html
2. **FATF Guidance: Politically Exposed Persons (Recommendations 12 and 22)**, June 2013. https://www.fatf-gafi.org/en/publications/Fatfrecommendations/Peps-r12-r22.html (checked 2026-10-17)
3. **FinCEN, Customer Due Diligence Requirements for Financial Institutions, Final Rule**, 81 FR 29398 (May 11, 2016); 31 CFR 1010.230. Effective 2016-07-11, compliance date 2018-05-11. https://www.govinfo.gov/content/pkg/FR-2016-05-11/html/2016-10567.htm (checked 2026-10-17)
4. **Customer Identification Program rule for banks**, 31 CFR 1020.220 (minimum identifying information; verification "through documents" includes "unexpired government-issued identification evidencing nationality or residence and bearing a photograph"). https://www.ecfr.gov/current/title-31/subtitle-B/chapter-X/part-1020/subpart-B/section-1020.220
5. **The Wolfsberg Group, Guidance on Sanctions Screening**, January 2019. https://wolfsberg-group.org/news/publication-of-guidance-on-sanctions-screening/ (checked 2026-10-17)
6. **OFAC, Economic Sanctions Enforcement Guidelines**, 31 CFR Part 501 App. A; **OFAC FAQs** on sanctions list searching, name matching and "weak aliases"; SDN List data format. https://ofac.treasury.gov/faqs and https://ofac.treasury.gov/specially-designated-nationals-and-blocked-persons-list-sdn-human-readable-lists
7. **OFAC reporting rules**, 31 CFR 501.603 (blocked property reports) and 501.604 (rejected transaction reports), both due within 10 business days. https://www.ecfr.gov/current/title-31/subtitle-B/chapter-V/part-501
8. **OFAC, Revised Guidance on Entities Owned by Persons Whose Property and Interests in Property Are Blocked** (the "50 Percent Rule"), August 13, 2014. https://ofac.treasury.gov/
9. **UN Security Council Consolidated List** (structure: reference number, names, good/low-quality aliases, DOB, POB, nationality, documents, listing narrative). https://main.un.org/securitycouncil/en/content/un-sc-consolidated-list
10. **EU Consolidated Financial Sanctions List** (via the EU Sanctions Map / FISMA). https://data.europa.eu/data/datasets/consolidated-list-of-persons-groups-and-entities-subject-to-eu-financial-sanctions
11. **Directive (EU) 2015/849** (4th AML Directive, as amended by 2018/843), Art. 3(9)–(11) (PEP, family member, close associate definitions), Art. 18–23 (EDD, PEP measures, 12-month rule). https://eur-lex.europa.eu/eli/dir/2015/849/oj
12. **UK FCA FG17/6, The treatment of politically exposed persons for anti-money laundering purposes**, July 2017. https://www.fca.org.uk/publications/finalised-guidance/fg17-6-treatment-politically-exposed-persons-peps-money-laundering
13. **ICAO Doc 9303, Machine Readable Travel Documents**, 8th ed. Part 3 (common specifications, check digits), Part 4 (TD3 passports), Part 5 (TD1 cards). https://www.icao.int/publications/pages/publication.aspx?docnum=9303
14. **JMLSG Guidance, Part I, Chapter 5** (customer due diligence; verification of identity and address). https://www.jmlsg.org.uk/guidance/current-guidance/
15. **Universal Postal Union, international addressing standards / postal addressing systems by country.** https://www.upu.int/en/Postal-Solutions/Programmes-Services/Addressing-Solutions

> **Verification note.** These are public sources described from general knowledge plus quick searches. Only items 2, 3 and 5 had their URLs verified tonight. Before quoting any source verbatim in the write-up, open it and check the exact wording. Session A is downloading the same documents to `step3_domain_adapter/corpus/`.
