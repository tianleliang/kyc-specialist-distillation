"""Truth -> expected output under step0_rules/schema/v1.json (decision policy v1).

This is the ONLY module that knows the output schema and the decision policy.
The policy it implements is published, in plain words, as
``step0_rules/policy_v1.md`` (Tianle's decisions D1-D16, Sat 2026-10-17);
section numbers below (§n) refer to that file. If the two ever disagree,
that is a bug in one of them. ``truth.py``, ``sample.py`` and ``render.py``
stay schema-agnostic.

Labels are derived from what the packet shows, not from hidden intent: if
the generator listed the real applicant with a year-only DOB, the packet
cannot prove a match, so the label is ``needs_review``, not ``true_match``.

Summary (the policy file is authoritative):
  identity   five findings (consistent | mismatch | unreadable) + one reason
             code each; MRZ-anchored three-way OCR/tamper rule (§3, D6);
             verified = all five consistent (D2).
  screening  one disposition per hit with evidence codes (§4, D7-D8).
  risk       rule table: any high trigger or >= 3 distinct medium drivers
             -> high; any medium -> medium; else low (§5, D10).
  decision   sanctions true match -> reject; clear tamper evidence ->
             reject (D4); injected instructions -> escalate (D5); every
             other escalation rule; else approve (§7).
  actions    every action whose trigger fired, also on reject (§6, D11).
  narrative  4-8 sentences, each with section refs + hit_ids (§8, D3).
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from step1_data_generation.lib import matching as Mt
from step1_data_generation.lib import mrz as M
from step1_data_generation.lib import ocr as O
from step1_data_generation.render import PRODUCT_LABEL
from step1_data_generation.sample import POA_WINDOW_DAYS
from step1_data_generation.truth import CaseTruth

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "step0_rules" / "schema" / "v1.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
SCHEMA_ID = "v1"
SCHEMA_VERSION = "1.0"

FIELDS = ("name", "date_of_birth", "document_number", "expiry", "address")
DOC_FIELDS = ("name", "date_of_birth", "document_number", "expiry")
DOC_LABEL = {"passport": "passport", "national_id": "national identity card", "driving_licence": "driving licence"}
FIELD_LABEL = {"name": "name", "date_of_birth": "date of birth", "document_number": "document number",
               "expiry": "expiry date", "address": "address"}
SERIOUS_MEDIA = {"fraud", "corruption", "money_laundering", "tax_evasion", "organised_crime", "sanctions_evasion"}
ACCEPTED_POA = {"utility_bill", "bank_statement", "council_tax", "telecom_bill", "tenancy_agreement",
                "government_letter"}
CLEAR_TAMPER = {"viz_mrz_disagree", "check_digit_failed", "impossible_date"}
AMBIGUOUS = "ocr_or_tamper_ambiguous"

# narrative section refs (schema enum)
CTX, APP, VIZ, MRZ, POA, SCR = ("context", "application", "id_document_visual", "id_document_mrz",
                                "proof_of_address", "screening_hits")
# section enum -> the tag render.py prints for that section in every layout
SECTION_TAG = {CTX: "CTX", APP: "APP", VIZ: "ID", MRZ: "MRZ", POA: "POA", SCR: "SCR"}


def ref_ids(t: CaseTruth) -> list[str]:
    """Valid narrative refs for this packet: the sections it has, then its hit ids."""
    secs = [s for s in SECTION_TAG if s != MRZ or t.id_doc.mrz_lines]
    return secs + [h.hit_id for h in t.hits]


def _f(status: str, code: str, why: str) -> dict:
    """Internal finding. ``why`` feeds the narrative only; the output keeps status + code."""
    return {"status": status, "reason": code, "why": why}


# --------------------------------------------------------------------------
# identity (§2, §3)
# --------------------------------------------------------------------------
def _mrz_field(t: CaseTruth, fld: str) -> tuple[str | None, bool | None, bool]:
    """(value as read after OCR repair, check ok, repair needed)."""
    d = t.id_doc
    if not d.mrz_lines:
        return None, None, False
    raw = d.mrz_lines
    rep = O.repair_mrz(raw, d.mrz_format)
    li, a, b = O._field_span(d.mrz_format, fld)
    if len(rep[li]) <= b:
        return None, False, False
    s, cd = rep[li][a:b], rep[li][b]
    if any(c in s for c in "?#") or cd in "?#":
        return None, False, False
    ok = M.is_valid_check(s, cd)
    # OCR repair needed = the printed field (with its check digit) differs from the repaired one,
    # whatever the as-read check result (a glyph error can pass a check digit by chance: G and 6 weigh the same)
    repaired = raw[li][a:b + 1] != rep[li][a:b + 1]
    if fld == "doc_number":
        val = s.rstrip("<")
    else:
        dd = M.parse_date(s, kind="birth" if fld == "birth_date" else "expiry", today=t.context.as_of_date)
        val = dd.isoformat() if dd else None
    return val, ok, ok and repaired


_GLYPH = str.maketrans({"O": "0", "D": "0", "Q": "0", "I": "1", "L": "1", "S": "5",
                        "B": "8", "Z": "2", "G": "6", "A": "4", "T": "7"})


def _glyph_eq(a: str, b: str) -> bool:
    """Equal up to OCR letter/digit glyph confusion."""
    return a.upper().translate(_GLYPH) == b.upper().translate(_GLYPH)


def _lookalike_pair(a: str, b: str) -> bool:
    """Exactly one position differs, by an OCR look-alike digit pair."""
    if len(a) != len(b):
        return False
    diff = [(x, y) for x, y in zip(a, b) if x != y]
    return len(diff) == 1 and (O.DIGIT_LOOKALIKE.get(diff[0][0]) == diff[0][1]
                               or O.DIGIT_LOOKALIKE.get(diff[0][1]) == diff[0][0])


def _zone_check(t: CaseTruth, fld: str) -> tuple[dict | None, str | None]:
    """Per-zone check of one document field (§3). Returns (finding, or None
    when the zones are fine; the document's value). A fine result carries its
    consistent reason in ``_zone_ok`` (all_sources_agree, ocr_confusable_resolved
    or no_mrz_single_source)."""
    d = t.id_doc
    viz = d.viz.get(fld, "")
    mval, ok, repaired = _mrz_field(t, fld)
    label = {"doc_number": "document number", "birth_date": "date of birth", "expiry_date": "expiry date"}[fld]
    if d.mrz_lines is None:
        if not viz:
            return _f("unreadable", "field_illegible", f"The {label} is illegible and the document has no MRZ."), None
        return _f("consistent", "no_mrz_single_source", ""), viz
    if not viz and mval is None:
        return _f("unreadable", "field_illegible", f"The {label} is illegible in both the visual zone and the MRZ."), None
    if not viz:
        if ok:
            return _f("consistent", "all_sources_agree", ""), mval
        return _f("unreadable", "field_illegible",
                  f"The {label} is illegible in the visual zone and fails its MRZ check digit."), None
    if mval is None:
        return _f("unreadable", "field_illegible", f"The MRZ {label} cannot be read."), None
    if ok and viz == mval:
        return _f("consistent", "ocr_confusable_resolved" if repaired else "all_sources_agree", ""), viz
    if ok and fld == "doc_number" and _glyph_eq(viz, mval):
        return _f("consistent", "ocr_confusable_resolved", ""), viz
    if ok:
        return _f("mismatch", "viz_mrz_disagree",
                  f"The visual-zone {label} ({viz}) differs from the checksum-valid MRZ ({mval})."), viz
    if viz == mval:
        return _f("mismatch", "check_digit_failed",
                  f"Both zones show {label} {viz}, but the MRZ check digit does not fit that value."), viz
    v_cmp = viz.replace("-", "")[2:] if fld != "doc_number" else viz
    m_cmp = mval.replace("-", "")[2:] if fld != "doc_number" else mval
    if _lookalike_pair(v_cmp, m_cmp):
        if not t.knobs.get("ocr_digit_to_digit_in_numeric", True):
            # noise-rule switch off: OCR never turns one digit into another, so this is an alteration
            return _f("mismatch", "viz_mrz_disagree",
                      f"The MRZ {label} differs from the visual zone ({viz}) by one digit and fails its check digit; "
                      "OCR does not turn one digit into another, so this indicates an alteration."), viz
        return _f("mismatch", AMBIGUOUS,
                  f"The MRZ {label} differs from the visual zone ({viz}) by one look-alike digit and fails its "
                  "check digit, which could be an OCR misread or an alteration."), viz
    return _f("mismatch", "viz_mrz_disagree",
              f"The visual-zone {label} ({viz}) and the MRZ ({mval}) disagree and the MRZ check digit fails."), viz


def _name_finding(t: CaseTruth) -> dict:
    """§2.1, from the printed text: the document's order is given names then surname."""
    app, d = t.application, t.id_doc
    if not d.viz.get("surname"):
        return _f("unreadable", "field_illegible", "The name on the document is illegible.")
    doc_name = f"{d.viz['given_names']} {d.viz['surname']}"
    if app.name_relation == "different_name":
        return _f("mismatch", "application_document_disagree",
                  f"The declared name '{app.full_name}' differs from the document name '{doc_name}'.")
    ta, td = Mt.tokens(app.full_name, drop_articles=False), Mt.tokens(doc_name, drop_articles=False)
    sa, sd = set(ta), set(td)
    if sa != sd and not (sa < sd or sd < sa):
        return _f("consistent", "transliteration_variant",
                  f"The declared name '{app.full_name}' is a romanization variant of the document name '{doc_name}'.")
    if sa != sd:
        return _f("consistent", "additional_name_part",
                  "One of the names adds a middle name or patronymic that the other omits; the other name parts agree.")
    if ta != td:
        return _f("consistent", "reordered_tokens", "The declared name lists the same name parts in a different order.")
    return _f("consistent", "all_sources_agree", "")


def _impossible(t: CaseTruth, dob: str | None, expiry: str | None) -> str | None:
    """Which field carries an impossible date, if any (§3 (d))."""
    issue = t.id_doc.issue_date
    if expiry and issue and date.fromisoformat(expiry) < issue:
        return "expiry"
    if dob and (issue and date.fromisoformat(dob) > issue or date.fromisoformat(dob) > t.context.as_of_date):
        return "date_of_birth"
    return None


def _flat(text: str) -> str:
    return ", ".join(l.strip() for l in text.replace("\n", ", ").split(",") if l.strip()).casefold()


def _poa_prints_declared(t: CaseTruth) -> bool:
    """Does the PoA print the declared address exactly (up to line breaks)?
    Decided from the truth, so the label can't drift with render randomness."""
    p, a = t.poa, t.application
    shown = p.address.render(p.render_style, abbreviate=p.abbreviated)
    declared = a.address.one_line(abbreviate=a.address_abbreviated)
    return _flat(shown) == _flat(declared)


def _name_tokens(name: str) -> frozenset:
    import unicodedata
    s = unicodedata.normalize("NFKD", name or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).lower()
    return frozenset(w for w in "".join(ch if ch.isalpha() else " " for ch in s).split() if w)


def _address_finding(t: CaseTruth) -> dict:
    p, as_of = t.poa, t.context.as_of_date
    if not p.present:
        return _f("unreadable", "field_missing", "No proof-of-address document was provided.")
    if not p.legible:
        return _f("unreadable", "field_illegible", "The proof-of-address document is illegible.")
    if p.kind not in ACCEPTED_POA:
        return _f("mismatch", "poa_document_type_not_accepted",
                  "The document supplied is not an accepted proof-of-address type.")
    if p.issue_date > as_of:
        return _f("mismatch", "poa_future_dated",
                  f"The proof of address is dated {p.issue_date.isoformat()}, after the as-of date {as_of.isoformat()}.")
    if (as_of - p.issue_date).days > POA_WINDOW_DAYS:
        return _f("mismatch", "poa_stale",
                  f"The proof of address is dated {p.issue_date.isoformat()}, more than {POA_WINDOW_DAYS} days before "
                  f"the as-of date {as_of.isoformat()}.")
    if p.name_relation == "different":
        return _f("mismatch", "poa_name_differs",
                  f"The proof of address is addressed to {p.name_on_doc}, not to the applicant.")
    if t.application.name_relation == "different_name" and _name_tokens(p.name_on_doc) != _name_tokens(t.application.full_name):
        # Dev pilot (2026-10-17): all 4 frontier models compare the PoA addressee with the name on the
        # APPLICATION. When the application gives a different name from the document and the PoA is
        # addressed to the document name, the PoA does not support the application -> poa_name_differs.
        # (Case, accents, punctuation and order are ignored; a PoA in the application's name is consistent.)
        return _f("mismatch", "poa_name_differs",
                  f"The proof of address is addressed to {p.name_on_doc}, not to the name on the application.")
    if p.address_relation == "contradicts":
        what = "address" if p.contradiction in ("", "whole") else p.contradiction
        return _f("mismatch", "poa_address_differs",
                  f"The proof-of-address {what} differs from the declared address.")
    if not _poa_prints_declared(t):
        return _f("consistent", "country_format_difference",
                  f"The {p.kind.replace('_', ' ')} dated {p.issue_date.isoformat()} shows the declared address in a "
                  "different format and is within the 90-day window.")
    return _f("consistent", "all_sources_agree",
              f"The {p.kind.replace('_', ' ')} dated {p.issue_date.isoformat()} shows the declared address and is "
              "within the 90-day window.")


def identity(t: CaseTruth) -> dict:
    """{field: finding} for the five fields (internal shape; ``project`` flattens it)."""
    app = t.application
    out = {"name": _name_finding(t)}
    dob, dob_val = _zone_check(t, "birth_date")
    if dob["reason"] == "no_mrz_single_source":     # the application is the second source for a DOB
        dob = _f("consistent", "all_sources_agree", "")
    out["document_number"], _ = _zone_check(t, "doc_number")
    exp, exp_val = _zone_check(t, "expiry_date")
    # §2.2 order: zone finding, then impossible date, then application disagreement / expiry
    bad = _impossible(t, dob_val if dob["status"] == "consistent" else None,
                      exp_val if exp["status"] == "consistent" else None)
    if bad == "date_of_birth":
        dob = _f("mismatch", "impossible_date", "The document's date of birth cannot be true given its other dates.")
    elif dob["status"] == "consistent" and dob_val and dob_val != app.dob.isoformat():
        dob = _f("mismatch", "application_document_disagree",
                 f"The declared date of birth {app.dob.isoformat()} differs from the document ({dob_val}).")
    if bad == "expiry":
        exp = _f("mismatch", "impossible_date", "The document's expiry date is before its issue date.")
    elif exp["status"] == "consistent" and exp_val and date.fromisoformat(exp_val) < t.context.as_of_date:
        exp = _f("mismatch", "document_expired",
                 f"The document expired on {exp_val}, before the as-of date {t.context.as_of_date.isoformat()}.")
    out["date_of_birth"], out["expiry"] = dob, exp
    out = {k: out[k] for k in DOC_FIELDS}
    out["address"] = _address_finding(t)
    return out


def verified(ident: dict) -> bool:
    return all(ident[k]["status"] == "consistent" for k in FIELDS)


# --------------------------------------------------------------------------
# screening (§4)
# --------------------------------------------------------------------------
def _name_tokens(s: str) -> list[str]:
    return sorted(Mt.tokens(s, drop_articles=False))


def _name_evidence(t: CaseTruth, e: dict) -> str:
    me = _name_tokens(t.application.full_name)
    if _name_tokens(e["primary_name"]) == me:
        return "name_exact"
    q = dict(zip(e.get("aliases") or [], e.get("alias_quality") or []))
    strong = [a for a, k in q.items() if _name_tokens(a) == me and k in ("strong", "Good")]
    if strong:
        return "alias_match"
    if any(_name_tokens(a) == me for a in q):
        return "weak_alias_match"
    return "name_variant_or_transliteration"


def _disposition(t: CaseTruth, h) -> tuple[str, list[str], str]:
    e = h.entry
    ev = [_name_evidence(t, e)]
    det = e.get("details") or {}
    if h.list_type == "adverse_media":
        disc = set(h.discriminators)
        code = {"age_consistent": "age_consistent", "city_matches": "location_matches",
                "occupation_matches": "occupation_matches", "age_conflicts": "age_conflicts",
                "city_differs": "location_differs", "occupation_differs": "occupation_differs"}
        ev += [code[x] for x in sorted(disc) if x in code]
        if disc & {"age_conflicts", "city_differs", "occupation_differs"}:
            return "false_positive", ev, "the reported age, city or occupation conflicts with the applicant"
        if disc & {"age_consistent", "city_matches", "occupation_matches"}:
            return "true_match", ev, "the article's reported age, city and occupation fit the applicant"
        ev.append("no_secondary_identifiers")
        return "needs_review", ev, "the article gives nothing beyond the name to compare"
    dc = h.dob_comparison
    if dc == "year_month" and str(e.get("dob", "")).count("-") == 2:
        dc = "mismatch"        # a listed FULL date in the same year and month but another day contradicts (§4.1)
    ev.append({"exact": "dob_exact", "unknown": "dob_not_listed", "mismatch": "dob_mismatch"}.get(dc, "dob_partial"))
    ev.append({True: "nationality_match", False: "nationality_mismatch", None: "nationality_not_listed"}[h.nationality_match])
    doc_match = "matches" in str(det.get("identification", "")).lower()
    if doc_match:
        ev.append("document_number_match")
    if h.pep_relation in ("family", "close_associate"):
        ev.append("pep_relationship_listed")
    what = {"sanctions": "sanctions entry", "pep": "PEP record"}[h.list_type]
    if doc_match:                                   # rule 1
        return "true_match", ev, f"the {what} states that the identity document number on file matches"
    if dc == "mismatch":                            # rule 2: hard conflict
        return "false_positive", ev, f"the listed date of birth ({e['dob']}) contradicts the applicant's"
    if dc == "exact" and h.nationality_match is not False:   # rule 3 (and 4 for relatives / associates)
        rel = {"family": " as a family member of a PEP", "close_associate": " as a close associate of a PEP"}.get(h.pep_relation or "", "")
        return "true_match", ev, f"the name, exact date of birth and nationality match the {what}{rel}"
    if dc == "unknown" and h.nationality_match is None:
        ev.append("no_secondary_identifiers")
        return "needs_review", ev, "the entry lists no date of birth or nationality, so the name match can be neither confirmed nor excluded"
    if dc == "exact":
        return "needs_review", ev, "the date of birth matches but the listed nationality differs"
    if dc == "unknown":
        return "needs_review", ev, "the entry lists no date of birth, so the name match cannot be confirmed"
    return "needs_review", ev, f"the listed date of birth ({e['dob']}) is only a partial match"


def screening(t: CaseTruth) -> list[dict]:
    """Internal shape: output fields plus ``why`` for the narrative."""
    out = []
    for h in t.hits:
        disp, ev, why = _disposition(t, h)
        out.append({"hit_id": h.hit_id, "list_type": h.list_type, "disposition": disp, "evidence": ev, "why": why})
    return out


# --------------------------------------------------------------------------
# risk (§5), decision (§7), actions (§6)
# --------------------------------------------------------------------------
def _flags(t: CaseTruth, ident: dict, scr: list[dict]) -> dict:
    by_id = {h.hit_id: h for h in t.hits}

    def tm(pred):
        return any(s["disposition"] == "true_match" and pred(by_id[s["hit_id"]]) for s in scr)

    def anyd(disps, list_type):
        return any(s["disposition"] in disps and s["list_type"] == list_type for s in scr)

    reasons = {k: ident[k]["reason"] for k in FIELDS}
    return {
        "sanctions_true": tm(lambda h: h.list_type == "sanctions"),
        "pep_self": tm(lambda h: h.list_type == "pep" and h.pep_relation in (None, "self")),
        "pep_rca": tm(lambda h: h.list_type == "pep" and h.pep_relation in ("family", "close_associate")),
        "media_serious": tm(lambda h: h.list_type == "adverse_media" and h.media_category in SERIOUS_MEDIA),
        "media_minor": tm(lambda h: h.list_type == "adverse_media" and h.media_category not in SERIOUS_MEDIA),
        "needs_review": any(s["disposition"] == "needs_review" for s in scr),
        "sanctions_review": anyd(("true_match", "needs_review"), "sanctions"),
        "pep_review": anyd(("needs_review",), "pep"),
        "media_review": anyd(("true_match", "needs_review"), "adverse_media"),
        "tamper": any(r in CLEAR_TAMPER for r in reasons.values()),
        "ambiguous": any(r == AMBIGUOUS for r in reasons.values()),
        "expired": reasons["expiry"] == "document_expired",
        "unreadable": any(ident[k]["status"] == "unreadable" for k in FIELDS),
        "doc_unreadable": any(ident[k]["status"] == "unreadable" for k in DOC_FIELDS),
        "declared_mismatch": any(r == "application_document_disagree" for r in reasons.values()),
        "doc_not_consistent": any(ident[k]["status"] != "consistent" for k in DOC_FIELDS),
        "address_issue": ident["address"]["status"] != "consistent",
        "injection": t.injection.present,
        "occ_high": t.risk.occupation_risk == "high",
        "sof_bad": not t.risk.sof_consistent,
        "activity_bad": not t.risk.activity_consistent,
        "product_remote": t.risk.product_risk == "high" and t.risk.non_face_to_face,
    }


def risk(t: CaseTruth, f: dict) -> tuple[str, list[str]]:
    high = [d for d, on in (("sanctions_match", f["sanctions_true"]), ("pep_exposure", f["pep_self"]),
                            ("pep_associate_or_family", f["pep_rca"]), ("adverse_media_serious", f["media_serious"]),
                            ("document_tamper_evidence", f["tamper"])) if on]
    med = [d for d, on in (("adverse_media_minor", f["media_minor"]), ("unresolved_screening_hit", f["needs_review"]),
                           ("possible_document_alteration", f["ambiguous"]),
                           ("identity_inconsistency", f["declared_mismatch"]),
                           ("insufficient_evidence", f["unreadable"]), ("expired_document", f["expired"]),
                           ("address_unverified", f["address_issue"]),
                           ("packet_contains_instructions", f["injection"]),
                           ("high_risk_occupation", f["occ_high"]),
                           ("source_of_funds_inconsistent", f["sof_bad"]),
                           ("activity_inconsistent", f["activity_bad"]),
                           ("high_risk_product_remote_channel", f["product_remote"])) if on]
    tier = "high" if high or len(med) >= 3 else ("medium" if med else "low")
    drivers = high + med
    if tier != "low" and t.risk.cross_border:
        drivers.append("cross_border")
    return tier, drivers


def decide(f: dict, tier: str) -> str:
    """§7 precedence; the first rule that fires wins."""
    if f["sanctions_true"]:                                     # P1
        return "reject"
    if f["tamper"]:                                             # P2 (D4)
        return "reject"
    if (f["injection"] or f["ambiguous"] or f["needs_review"] or f["pep_self"] or f["pep_rca"]   # P3-P8
            or f["media_serious"] or f["doc_not_consistent"] or f["address_issue"]):
        return "escalate"
    if tier == "high":                                          # P9
        return "escalate"
    return "approve"                                            # P10


def actions(f: dict, decision: str, tier: str) -> list[str]:
    """§6, in catalog order, each once."""
    pep = f["pep_self"] or f["pep_rca"]
    fired = [
        ("senior_management_approval", pep),
        ("verify_source_of_wealth", pep),
        ("verify_source_of_funds", pep or f["sof_bad"] or f["activity_bad"]),
        ("enhanced_ongoing_monitoring", tier == "high" and decision != "reject"),
        ("request_valid_id_document", f["expired"] or f["doc_unreadable"]),
        ("request_secondary_id", f["declared_mismatch"]),
        ("request_new_proof_of_address", f["address_issue"]),
        ("document_authenticity_review", f["tamper"] or f["ambiguous"]),
        ("sanctions_compliance_review", f["sanctions_review"]),
        ("pep_relationship_confirmation", f["pep_review"]),
        ("enhanced_adverse_media_review", f["media_review"]),
        ("manual_packet_integrity_review", f["injection"]),
        ("report_to_sanctions_authority", f["sanctions_true"]),
        ("consider_suspicious_activity_report", f["tamper"]),
    ]
    return [a for a, on in fired if on]


# --------------------------------------------------------------------------
# narrative (§8): 4-8 sentences, each with section refs + hit_ids
# --------------------------------------------------------------------------
_INJ_REF = {"occupation": APP, "employer": APP, "expected_activity": APP, "applicant_note": APP,
            "poa_notes": POA, "id_ocr": VIZ, "hit_remarks": SCR}
_IDENTITY_OK = {"all_sources_agree": "", "no_mrz_single_source": "",
                "ocr_confusable_resolved": " after correcting OCR look-alike characters in the MRZ",
                "transliteration_variant": ", allowing for a romanization variant of the name",
                "reordered_tokens": ", allowing for a different name order",
                "additional_name_part": ", allowing for a middle name or patronymic the document omits"}


def _s(sentence: str, refs: list[str], hit_ids: list[str] | None = None) -> dict:
    return {"sentence": sentence, "evidence_refs": list(dict.fromkeys(refs)), "hit_ids": list(hit_ids or [])}


def _human(code: str) -> str:
    return code.replace("_", " ")


def narrative(t: CaseTruth, ident: dict, scr: list[dict], tier: str, drivers: list[str],
              decision: str, acts: list[str]) -> list[dict]:
    c, app, d = t.context, t.application, t.id_doc
    S = [_s(f"{app.full_name} applied on {c.application_date.isoformat()} for a {PRODUCT_LABEL[c.product]} through the "
            f"{_human(c.channel)} channel in {c.onboarding_country}, declaring the occupation '{app.occupation}' and "
            f"source of funds '{_human(app.source_of_funds)}'; the case is assessed as of {c.as_of_date.isoformat()}.",
            [CTX, APP])]
    id_refs = [VIZ] + ([MRZ] if d.mrz_lines else []) + [APP]
    bad = [k for k in DOC_FIELDS if ident[k]["status"] != "consistent"]
    if not bad:
        extra = next((_IDENTITY_OK[ident[k]["reason"]] for k in DOC_FIELDS if _IDENTITY_OK.get(ident[k]["reason"])), "")
        mrz = "" if d.mrz_lines else " (the document has no MRZ)"
        S.append(_s(f"The {DOC_LABEL[d.kind]}{mrz} agrees with the application on name, date of birth and document "
                    f"details and is unexpired{extra}.", id_refs))
    else:
        for k in bad[:2]:
            S.append(_s(ident[k]["why"], id_refs if k != "name" or d.mrz_lines else [VIZ, APP]))
    S.append(_s(ident["address"]["why"], [POA, APP]))
    if scr:
        fps = [s["hit_id"] for s in scr if s["disposition"] == "false_positive"]
        for s in scr:
            if s["disposition"] != "false_positive":
                S.append(_s(f"Screening hit {s['hit_id']} ({_human(s['list_type'])}) is a {_human(s['disposition'])}: "
                            f"{s['why']}.", [SCR, APP], [s["hit_id"]]))
        if fps:
            many = len(fps) > 1
            S.append(_s(f"Screening hit{'s' if many else ''} {', '.join(fps)} {'are' if many else 'is'} discounted as "
                        f"false positive{'s' if many else ''} because a listed identifier conflicts with the applicant.",
                        [SCR, APP], fps))
    else:
        S.append(_s("Screening returned no hits.", [SCR]))
    if t.injection.present:
        loc = t.injection.location
        S.append(_s("The packet contains text addressed to the reviewer that tries to steer the outcome; it was not "
                    "followed and the packet is flagged for integrity review.",
                    [_INJ_REF[loc]], ["H1"] if loc == "hit_remarks" and t.hits else []))
    drv = ", ".join(_human(x) for x in drivers[:4]) or "no risk drivers"
    S.append(_s(f"Risk is assessed as {tier} ({drv}).", [APP, SCR] if t.hits else [APP]))
    act = "; required actions: " + ", ".join(_human(a) for a in acts) if acts else "; no further actions are required"
    S.append(_s(f"Decision: {decision}{act}.", [CTX, APP]))
    if len(S) > 8:
        S = S[:6] + S[-2:]
    while len(S) < 4:
        S.insert(1, _s(f"The applicant's declared nationality is {app.nationality}.", [APP]))
    return S


# --------------------------------------------------------------------------
def project(t: CaseTruth) -> dict:
    """The expected v1 output for one case, keys in schema order."""
    ident = identity(t)
    scr = screening(t)
    f = _flags(t, ident, scr)
    tier, drivers = risk(t, f)
    decision = decide(f, tier)
    acts = actions(f, decision, tier)
    out: dict = {"schema_version": SCHEMA_VERSION}
    for k in FIELDS:
        out[f"{k}_status"] = ident[k]["status"]
        out[f"{k}_reason"] = ident[k]["reason"]
    out["identity_verified"] = verified(ident)
    out["screening"] = [{k: s[k] for k in ("hit_id", "list_type", "disposition", "evidence")} for s in scr]
    out["risk_tier"] = tier
    out["risk_drivers"] = drivers
    out["decision"] = decision
    out["required_actions"] = acts
    out["narrative"] = narrative(t, ident, scr, tier, drivers, decision, acts)
    return out


# --------------------------------------------------------------------------
# label summary for schema-free callers (step1_data_generation/twins.py, step1_data_generation/knockout.py)
# --------------------------------------------------------------------------
ESCALATE = "escalate"


def outcome(t: CaseTruth) -> str:
    """The case-level outcome under this schema/policy (here: ``decision``)."""
    return project(t)["decision"]
