# Output Schema Options: DRAFT for Tianle

> **⚠️ OPTIONS, NOT A DECISION.** Session D overnight, 2026-10-17. Three candidate designs for the published output schema, with tradeoffs. Tianle picks one (or a hybrid) at 08:15. The enum *values* below (actions, drivers, reasons) are placeholders that track `decision_policy_draft.md`; they change when the policy changes.
>
> Machine-readable drafts: `documentation/02_research/schema_options/option_{a,b,c}_*.schema.json`, with one example output each in `examples/`. Linted by `tests/d_schema_options_test.py` (valid Draft 2020-12; portable subset; examples validate; broken variants are rejected). All 12 tests pass.

---

## 1. Constraints every option satisfies

These come from the brief, the `05` research brief (tooling traps) and provider structured-output limits.

| Constraint | Why |
|---|---|
| **Every property `required`, `additionalProperties: false` on every object** | OpenAI strict mode requires both; Anthropic structured outputs require `additionalProperties: false`; Gemini accepts them |
| **No `$ref` / `$defs` / `anyOf` / `oneOf` / `allOf` / `if-then`** | Nested `$defs` raised small-model failure rates from ~3% to 68% in the benchmark cited in `05`. Union support differs between providers |
| **No nulls / type unions** | Gemini historically used OpenAPI-style `nullable` rather than `["string","null"]`. Avoid the question entirely: every field always has a value, and "not applicable" is an enum member |
| **No `pattern` / `format` / string-length / numeric bounds** | Support differs between providers and grammar backends. Unenforced constraints cause silent invalid outputs, which score zero |
| **Enums for everything categorical** | Constrained decoding makes enum fields free accuracy; easy to score |
| **≤ 5 levels of nesting, ≤ 100 properties** | OpenAI's original strict-mode limits (later raised). Staying under the old limits makes the exact current numbers irrelevant |
| **Narrative = `[{sentence, evidence_refs}]`** with 4–8 items | Brief: 4–8 sentences, every claim traceable. `evidence_refs` enables a programmatic grounding check (Session C's `evidence_refs` scaffold) |

**One exception to flag:** `narrative` uses `minItems: 4, maxItems: 8`. vLLM's grammar backends and Gemini enforce array bounds; OpenAI and Anthropic support for them has changed over time. If a provider ignores them and a frontier model writes 3 sentences, that case fails validation and scores zero. **Q-SC1:** keep the bounds in the schema (faithful to the brief, the same rule for everyone) or drop them and score sentence count as a separate metric? *Verify each provider's current docs when keys are live.*

**Verify before trusting:** the provider limits above come from general knowledge of the docs as of mid-2026, not from tonight's checks. Session B (serving) should confirm that vLLM's `response_format: json_schema` enforces the chosen schema, including enums inside array items.

---

## 2. The three options at a glance

| | **A. Brief-mirror (nested)** | **B. Flat codes** | **C. Checks-first scaffold** |
|---|---|---|---|
| Shape | `identity.findings.name.status` ... mirrors the brief's wording | Top-level scalars `name_status`, `name_reason`; arrays only for hits, drivers, actions, narrative | B plus an auxiliary `checks` block of verifiable sub-facts, and the decision **last** |
| Object depth | 4 | 2 | 2 |
| Properties (total) | 32 | 23 | 32 |
| Reasons | Free-text `reason` per field and per hit | Enum `reason` codes (16 values) | Enum codes |
| Order (generation order) | identity → screening → risk → actions → decision → narrative | same as A | checks → findings → screening → drivers → tier → actions → **narrative → decision** |
| Example output size | ~2.1k chars ≈ 550 tokens | ~2.0k chars ≈ 520 tokens | ~2.3k chars ≈ 600 tokens |
| Readability for Zorbe | **Best**: obviously the brief's object | Good | Good, but extra fields need explaining |
| Small-model friendliness | Worst (depth, free text) | **Best** | Good; the scaffold may *help* accuracy |
| Scoring / programmatic rewards | Free-text reasons are unscorable | Everything except narrative is exact-match scorable | Most scorable: checks give dense rewards for RLVR and rejection sampling |
| Burden on Zorbe's hidden set | Low | Low | **Higher**: they must label or ignore `checks` |

(Token counts are chars/4 on the compact JSON example. Pretty-printed or with longer narratives, expect 700–900 tokens. Output length drives latency and cost per 1k cases.)

---

## 3. Option A: brief-mirror, nested

```jsonc
{
  "identity": {
    "verified": true,
    "findings": {
      "name":            {"status": "consistent|mismatch|unreadable", "reason": "<free text>"},
      "date_of_birth":   {...}, "document_number": {...}, "expiry": {...}, "address": {...}
    }
  },
  "screening": [{"hit_id": "H1", "list_type": "sanctions|pep|adverse_media",
                 "disposition": "true_match|false_positive|needs_review",
                 "evidence": ["dob_conflict", "nationality_conflict", ...], "reason": "<free text>"}],
  "risk": {"tier": "low|medium|high", "drivers": ["pep_foreign", ...]},
  "required_actions": ["senior_management_approval", ...],
  "decision": "approve|reject|escalate",
  "narrative": [{"sentence": "...", "evidence_refs": ["application", "id_document_mrz", ...]}]
}
```

**For:** reads exactly like the brief, so reviewers instantly see compliance. Free-text reasons are what a human analyst writes.
**Against:** 4 levels deep. Free-text reasons cost tokens, can't be scored exactly, and are another place for unsupported claims. The brief's "with a reason" is satisfied either way.

## 4. Option B: flat, enum codes

```jsonc
{
  "identity_verified": true,
  "name_status": "consistent",            "name_reason": "transliteration_variant",
  "date_of_birth_status": "consistent",   "date_of_birth_reason": "ocr_confusable_resolved",
  "document_number_status": "...",        "document_number_reason": "...",
  "expiry_status": "mismatch",            "expiry_reason": "document_expired",
  "address_status": "...",                "address_reason": "...",
  "screening": [{"hit_id": "H1", "list_type": "pep", "disposition": "needs_review",
                 "evidence": ["name_exact", "relationship_not_established"]}],
  "risk_tier": "medium", "risk_drivers": ["unresolved_screening_hit"],
  "required_actions": ["pep_relationship_confirmation"],
  "decision": "escalate",
  "narrative": [{"sentence": "...", "evidence_refs": ["screening_hits"]}]
}
```

**For:** the `05` advice in its purest form (flat, enum-heavy). Every non-narrative field is exact-match scorable, so rewards for rejection sampling, DPO pairs and GRPO are trivial. Fewest tokens. The reason codes double as a taxonomy for the write-up and the stage 8 controller.
**Against:** the reason codes are a closed vocabulary we invent tonight. If a real-world reason isn't in the list, the model must pick the nearest one. That's a risk on Zorbe's hidden set (different process) if their cases need reasons we didn't enumerate. **Mitigation option:** keep an extra free-text `notes` string (unscored).

## 5. Option C: checks-first scaffold

Same as B, plus a leading block:

```jsonc
"checks": {
  "mrz_present": "yes|no",
  "mrz_check_digits": "all_valid|valid_after_ocr_correction|invalid|not_applicable",
  "viz_mrz_agree": "yes|no|cannot_determine|not_applicable",
  "document_expired_on_onboarding_date": "yes|no|cannot_determine",
  "poa_within_window": "yes|no|cannot_determine",
  "poa_name_matches_applicant": "yes|no|cannot_determine",
  "packet_contains_instructions_to_reviewer": "yes|no",
  "evidence_sufficient_for_decision": "yes|no"
}
```

…and orders keys so that **findings and evidence come before conclusions** (risk drivers before tier, narrative before decision).

**For:** autoregressive models condition later tokens on earlier ones, so putting verifiable sub-facts first acts as a cheap, structured chain of thought (no free-text thinking, so no latency blow-up). Every check is computable from the latent truth, which gives **dense, per-step programmatic rewards** for rejection sampling and RLVR, and lets Table 2 show *where* the student fails (MRZ arithmetic vs date math vs screening). `packet_contains_instructions_to_reviewer` and `evidence_sufficient_for_decision` directly target the adversarial metric.
**Against:** the extra fields must be explained in the write-up and are **unscored by the brief**. Zorbe builds its hidden set **to our published schema**, so they'd have to label the checks or we'd have to mark them "auxiliary, ignore in scoring". It adds ~80 output tokens. Key order isn't guaranteed on every provider (Gemini orders properties by `propertyOrdering`, or alphabetically, unless told otherwise. Verify), so the scaffold benefit may hold only for OpenAI, vLLM and Anthropic.

**Q-SC2:** If C is chosen, should we publish two schemas, a **scored** schema (B) and a **serving** schema (C ⊇ B), with the endpoint returning C and scoring ignoring `checks`? That keeps Zorbe's labeling burden at B's level.

---

## 6. Cross-cutting design questions

**Q-SC3: `evidence_refs` granularity.** The hidden set is built by a different process, so it may not carry our section tags.
- (a) **Section-level enum** (as drafted): `application | id_document_visual | id_document_mrz | proof_of_address | screening_hits | context`. Works on any packet. The grounding check becomes "does every fact in the sentence appear in the cited sections?", which needs an LLM judge or string matching.
- (b) **Field-level strings** like `"application.date_of_birth"`, `"hit:H2.dob"`. Precise and mostly programmatically checkable, but free strings (no enum, since hit IDs are dynamic) and longer.
- (c) **Hybrid:** section enum plus an optional `hit_id` string per sentence.

**Q-SC4: how hits are identified.** `hit_id` as given in the packet (requires the packet to number hits; Zorbe's might not) vs a positional index (`hit_index: 1..n`, robust to any packet format but less explicit). Draft: string `hit_id`, with instructions to use `"1"`, `"2"`, ... in packet order when hits aren't labeled.

**Q-SC5: risk drivers and actions as enum arrays.** An enum array can repeat items and has no ordering guarantee (`uniqueItems` isn't portable). Score as sets; dedupe before scoring. Fine either way, but say so in the schema description.

**Q-SC6: an `identity.verified` definition.** Whatever the policy decides (`decision_policy_draft.md` Q-I5), put the definition in the schema's `description` so Zorbe's labelers apply the same rule.

**Q-SC7: version field.** Add `"schema_version": {"type":"string","enum":["1.0"]}`? It costs ~6 tokens and makes outputs self-describing. Cheap insurance.

**Q-SC8: "Fourth value" pressure.** Brief enums are 3-valued (`consistent/mismatch/unreadable`; `approve/reject/escalate`). Every extra value (e.g. `expired`, `approve_with_conditions`) makes our output more expressive but less comparable with what Zorbe's hidden-set labelers expect from the brief. Draft recommendation for consideration: **keep the brief's values exactly**, and put nuance in reason codes.

---

## 7. How the options interact with other decisions

| If Tianle chooses... | ...this option fits best |
|---|---|
| GRPO / RLVR is in scope, or rejection sampling with field-level checks | **C** (dense rewards) or **B** |
| Smallest model (≤1B) | **B** (shortest, flattest) |
| A tool-assisted variant (code pre-checks MRZ and dates) | **C**: the tool fills `checks`; the model does the rest. Same schema for both rows |
| Maximum reviewer readability and least explanation needed | **A** |
| Field-wise multi-teacher arbitration (see `distillation_options.md` §3.2) | **B / C**: the fields are discrete, so per-field voting is trivial |

**No recommendation is made here.** The tradeoffs above are the input for the 08:15 decision.
