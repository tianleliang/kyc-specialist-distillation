"""Hand-template OOD packets: 50 eval cases in six packet layouts written for this set only.

    python -m step1_data_generation.ood_templates --allow-eval                  # -> data/eval_ood_hand/ (50 cases)
    python -m step1_data_generation.ood_templates --allow-eval --n 12 --out /tmp/x --force

D14: written by a session that never read ``step1_data_generation/render.py``. Everything here
works from the truth object (``truth.py``) and the sampler's knobs (``sample.py``); no layout,
label or phrase is shared with the training renderer. Labels come from ``project.py`` (imported
lazily, so whichever schema version is checked in, v0 or v1, labels the cases).

Truths come from ``configs/eval_ood_template.yaml`` (entity bucket 9, OOD nationality pools,
OOD injection texts) with their own seed (4010000) and case-id prefix (``oodh``), so they
are disjoint from L's ``eval_ood_template`` build (seed 4000000) and from the LLM-written set
(``ood_llm.py``, seed 4020000).

The six styles (none exists in the training renderer):
  bank_pdf_export     a core-banking onboarding file exported to PDF and text-extracted (page headers, dotted leaders)
  call_centre_summary an agent's after-call summary with the uploaded document OCR pasted below
  fax_ocr_dump        a scanned branch fax run through OCR: fax headers per page, caps labels, smudged boilerplate
  vendor_json         a JSON case-import payload from a different IDV vendor, as received over HTTP
  two_column_form     a two-column paper form whose OCR read the columns row by row (interleaved)
  case_ticket         a case-management ticket: comments from onboarding, documents and screening teams

Guarantees, asserted for every packet (``check_packet``):
  * every truth fact the label can depend on appears verbatim (in the style's own date format,
    and JSON-escaped for ``vendor_json``): context, every application field, every ID-document
    visual-zone value or its illegible marker, every MRZ line exactly as OCR'd, the proof of
    address (or the statement that it is missing),
    every hit field (id, list, entry id, names, aliases with quality, DOB, nationality, score,
    every listed detail) and the injected text; an illegible PoA body is generated junk;
  * no hidden truth leaks (scenario names, "tamper", "true match", "expired", ...) outside the
    injected text.
Dates are only ever printed unambiguously (ISO, Y/M/D or month names), so a day/month swap in the
truth can never be mistaken for a format difference.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import importlib
import json
import random
import subprocess
import sys
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Callable

from step1_data_generation.config import load_config
from step1_data_generation.truth import GENERATOR_VERSION, CaseTruth

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "step1_data_generation" / "configs" / "eval_ood_template.yaml"
DEFAULT_OUT = Path("data") / "eval_ood_hand"
DEFAULT_SEED = 4010000
DEFAULT_N = 50
SPLIT = "eval_ood_hand"
RENDERER = "hand_template_v1"

PRODUCT_TEXT = {"current_account": "personal current account", "savings": "savings account",
                "business_account": "business account (sole trader)", "crypto_wallet": "digital-asset wallet",
                "remittance": "international money-transfer service", "premium_card": "premium credit card",
                "brokerage": "investment brokerage account"}
CHANNEL_TEXT = {"online": "web onboarding", "mobile_app": "mobile app", "branch": "in-branch",
                "introducer": "third-party introducer"}
SOF_TEXT = {"salary": "employment income", "savings": "personal savings", "pension": "pension income",
            "investment_returns": "investment returns", "business_income": "income from own business",
            "inheritance": "inheritance", "sale_of_property": "proceeds of a property sale",
            "family_support": "support from family", "crypto_gains": "gains from crypto-asset trading",
            "gift": "gift", "scholarship": "scholarship / grant", "part_time_salary": "part-time employment income",
            "sale_of_assets": "proceeds of an asset sale"}
DOC_TEXT = {"passport": "passport", "national_id": "national identity card", "driving_licence": "driving licence"}
POA_TEXT = {"utility_bill": "utility bill", "bank_statement": "bank statement", "council_tax": "local tax bill",
            "tenancy_agreement": "tenancy agreement", "telecom_bill": "phone / broadband bill",
            "government_letter": "letter from a government office"}
LIST_TEXT = {"sanctions": "Sanctions", "pep": "PEP", "adverse_media": "Adverse media"}
DETAIL_TEXT = {"sdn_type": "SDN type", "subject_type": "subject type", "programs": "programs", "regime": "regime",
               "regulation": "regulation", "listed_on": "listed on", "remarks": "remarks",
               "identification": "identification", "pep_category": "PEP category", "position": "position",
               "level": "level", "status": "status", "country": "country", "since": "in role since",
               "left_office": "left office", "rca_type": "relation type", "relationship": "relationship",
               "related_pep": "related PEP", "category": "category", "outlet": "outlet", "published": "published",
               "headline_template": "headline", "age_reported": "age reported", "city_reported": "city reported",
               "occupation_reported": "occupation reported"}
_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
_MONTHS_LONG = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
                "October", "November", "December"]

# words that would hand the answer to the model (checked outside the injected text)
LEAK_WORDS = ("tamper", "forged", "forgery", "altered", "true match", "true_match", "false positive",
              "false_positive", "needs review", "needs_review", "mismatch", "expired", "ocr error", "misread",
              "same person", "same_person", "suspicious", "contradict", "stale", "transliteration")


# --------------------------------------------------------------------------
# date formats (all unambiguous)
# --------------------------------------------------------------------------
def _d(iso: str) -> date | None:
    try:
        return date.fromisoformat(iso)
    except (TypeError, ValueError):
        return None


def fmt_dmy_short(iso: str) -> str:          # 19 Jun 1964
    d = _d(iso)
    return f"{d.day:02d} {_MONTHS[d.month - 1]} {d.year}" if d else iso


def fmt_mdy_long(iso: str) -> str:           # June 19, 1964
    d = _d(iso)
    return f"{_MONTHS_LONG[d.month - 1]} {d.day}, {d.year}" if d else iso


def fmt_dmy_caps(iso: str) -> str:           # 19-JUN-1964
    d = _d(iso)
    return f"{d.day:02d}-{_MONTHS[d.month - 1].upper()}-{d.year}" if d else iso


def fmt_ymd_slash(iso: str) -> str:          # 1964/06/19
    d = _d(iso)
    return f"{d.year:04d}/{d.month:02d}/{d.day:02d}" if d else iso


def fmt_dmy_long(iso: str) -> str:           # 19 June 1964
    d = _d(iso)
    return f"{d.day} {_MONTHS_LONG[d.month - 1]} {d.year}" if d else iso


def fmt_iso(iso: str) -> str:
    return iso


# --------------------------------------------------------------------------
# the view: every fact a style must show, already formatted for that style
# --------------------------------------------------------------------------
@dataclass
class Hit:
    hit_id: str
    list_type: str
    source: str
    entry_id: str
    primary: str
    aliases: list[tuple[str, str]]     # (alias, quality)
    dob: str                           # as listed ("unknown" if none)
    nationality: str                   # ISO3 or "not listed"
    score: str
    matched_on: str
    details: list[tuple[str, str]]     # (label, value), in listing order


@dataclass
class View:
    style: str
    case_ref: str
    country: str
    product: str
    channel: str
    as_of: str
    app_date: str
    name: str
    dob: str
    nationality: str
    address: str
    occupation: str
    employer: str
    sof: str
    volume: str
    currency: str
    activity: str
    note: str                          # applicant free-text note (injection or "")
    doc_kind: str
    issuer: str
    surname: str
    given: str
    doc_number: str
    doc_dob: str
    expiry: str
    issue: str
    doc_nationality: str
    sex: str
    place_of_birth: str
    authority: str
    mrz: list[str]
    id_extra: str                      # an extra OCR line on the ID scan (injection or "")
    poa_present: bool
    poa_legible: bool
    poa_kind: str
    poa_issuer: str
    poa_date: str
    poa_name: str
    poa_lines: list[str]
    poa_note: str
    hits: list[Hit]
    injection: str
    illegible: str
    no_poa: str
    no_hits: str
    facts: list[tuple[str, str]] = field(default_factory=list)   # (fact key, string that must appear)


@dataclass(frozen=True)
class Style:
    name: str
    date: Callable[[str], str]
    illegible: str
    no_poa: str
    no_hits: str
    layout: Callable[[View, random.Random], str]
    enc: Callable[[str], str] = staticmethod(lambda s: s)   # how a fact string looks inside the packet
    number: Callable[[int], str] = staticmethod(lambda n: f"{n:,}")


def make_view(t: CaseTruth, st: Style) -> View:
    c, a, d, p, inj = t.context, t.application, t.id_doc, t.poa, t.injection
    D = st.date
    loc = inj.location if inj.present else ""

    def with_inj(value: str, where: str) -> str:
        return f"{value} {inj.text}" if loc == where else value

    viz = lambda k: d.viz.get(k) or st.illegible          # noqa: E731
    vizd = lambda k: D(d.viz[k]) if d.viz.get(k) else st.illegible   # noqa: E731
    hits = []
    for i, h in enumerate(t.hits):
        e = h.entry
        dets = []
        for k, v in (e.get("details") or {}).items():
            if v in ("", None, []):
                continue
            val = ", ".join(map(str, v)) if isinstance(v, list) else str(v)
            dets.append((DETAIL_TEXT.get(k, k.replace("_", " ")), val))
        if loc == "hit_remarks" and i == 0:
            dets.append(("vendor remarks", inj.text))
        hits.append(Hit(h.hit_id, LIST_TEXT[h.list_type], e["list_source"], e["entry_id"], e["primary_name"],
                        list(zip(e.get("aliases") or [], e.get("alias_quality") or [])),
                        e.get("dob") or "unknown", e.get("nationality") or "not listed", str(h.score),
                        h.matched_on, dets))
    poa_lines = [l.strip() for l in p.address.render(p.render_style, abbreviate=p.abbreviated).splitlines()
                 if l.strip()] if p.present and p.address else []
    v = View(
        style=st.name, case_ref=c.case_ref, country=c.onboarding_country, product=PRODUCT_TEXT[c.product],
        channel=CHANNEL_TEXT[c.channel], as_of=D(c.as_of_date.isoformat()), app_date=D(c.application_date.isoformat()),
        name=a.full_name, dob=D(a.dob.isoformat()), nationality=a.nationality,
        address=a.address.one_line(abbreviate=a.address_abbreviated),
        occupation=with_inj(a.occupation, "occupation"), employer=with_inj(a.employer, "employer"),
        sof=SOF_TEXT.get(a.source_of_funds, a.source_of_funds.replace("_", " ")),
        volume=st.number(a.expected_monthly_volume), currency=a.currency,
        activity=with_inj(a.expected_activity, "expected_activity"),
        note=inj.text if loc == "applicant_note" else "",
        doc_kind=DOC_TEXT[d.kind], issuer=d.issuing_state, surname=viz("surname"), given=viz("given_names"),
        doc_number=viz("doc_number"), doc_dob=vizd("birth_date"), expiry=vizd("expiry_date"),
        issue=vizd("issue_date"), doc_nationality=viz("nationality"), sex=viz("sex"),
        place_of_birth=viz("place_of_birth"), authority=viz("authority"), mrz=list(d.mrz_lines or []),
        id_extra=inj.text if loc == "id_ocr" else "",
        poa_present=p.present, poa_legible=p.legible if p.present else False,
        poa_kind=POA_TEXT.get(p.kind, p.kind.replace("_", " ")) if p.present else "",
        poa_issuer=p.issuer, poa_date=D(p.issue_date.isoformat()) if p.present and p.issue_date else "",
        poa_name=p.name_on_doc, poa_lines=poa_lines, poa_note=inj.text if loc == "poa_notes" else "",
        hits=hits, injection=inj.text if inj.present else "",
        illegible=st.illegible, no_poa=st.no_poa, no_hits=st.no_hits)
    v.facts = view_facts(v)
    return v


def view_facts(v: View) -> list[tuple[str, str]]:
    f = [("case_ref", v.case_ref), ("onboarding_country", v.country), ("product", v.product),
         ("channel", v.channel), ("as_of_date", v.as_of), ("application_date", v.app_date),
         ("app.name", v.name), ("app.dob", v.dob), ("app.nationality", v.nationality),
         ("app.address", v.address), ("app.occupation", v.occupation), ("app.employer", v.employer),
         ("app.source_of_funds", v.sof), ("app.volume", v.volume), ("app.currency", v.currency),
         ("app.activity", v.activity),
         ("id.kind", v.doc_kind), ("id.issuer", v.issuer), ("id.surname", v.surname), ("id.given", v.given),
         ("id.doc_number", v.doc_number), ("id.dob", v.doc_dob), ("id.expiry", v.expiry), ("id.issue", v.issue),
         ("id.nationality", v.doc_nationality), ("id.sex", v.sex)]
    f += [(f"id.mrz[{i}]", l) for i, l in enumerate(v.mrz)]
    if not v.poa_present:
        f.append(("poa.missing", v.no_poa))
    else:
        f += [("poa.kind", v.poa_kind)]
        if v.poa_legible:
            f += [("poa.issuer", v.poa_issuer), ("poa.date", v.poa_date), ("poa.name", v.poa_name)]
            f += [(f"poa.address[{i}]", l) for i, l in enumerate(v.poa_lines)]
    if not v.hits:
        f.append(("hits.none", v.no_hits))
    for h in v.hits:
        k = f"hit.{h.hit_id}"
        f += [(f"{k}.id", h.hit_id), (f"{k}.list", h.list_type), (f"{k}.source", h.source),
              (f"{k}.entry_id", h.entry_id), (f"{k}.primary", h.primary), (f"{k}.dob", h.dob),
              (f"{k}.nationality", h.nationality), (f"{k}.score", h.score)]
        f += [(f"{k}.alias[{i}]", al) for i, (al, _) in enumerate(h.aliases)]
        f += [(f"{k}.{lab}", val) for lab, val in h.details]
    if v.injection:
        f.append(("injection", v.injection))
    return f


def check_packet(packet: str, v: View, st: Style) -> list[str]:
    """Problems with a rendered packet: required facts missing or hidden truth leaking.
    Empty list = good. (An illegible PoA's body is generated junk by construction, so its
    address cannot show through; its address lines also appear in the application.)"""
    probs = [f"missing {k}: {s!r}" for k, s in v.facts if st.enc(s) not in packet]
    scrub = packet.replace(st.enc(v.injection), " ") if v.injection else packet
    low = scrub.casefold()
    probs += [f"leak: {w!r}" for w in LEAK_WORDS if w in low]
    return probs


# --------------------------------------------------------------------------
# helpers shared by layouts
# --------------------------------------------------------------------------
def _garble(rng: random.Random, n_lines: int = 5, width: int = 46) -> list[str]:
    junk = "░▒▓#%&*~-=:;.,'`|/\\"
    return ["".join(rng.choice(junk) if rng.random() < 0.75 else rng.choice("aeimnorstu ") for _ in range(width))
            for _ in range(n_lines)]


def _alias_str(h: Hit) -> str:
    return "; ".join(f"{a} [{q}]" for a, q in h.aliases) or "none listed"


def _ref(rng: random.Random, prefix: str, digits: int = 6) -> str:
    return prefix + "".join(rng.choice("0123456789") for _ in range(digits))


# --------------------------------------------------------------------------
# style 1: bank onboarding file exported to PDF, text-extracted
# --------------------------------------------------------------------------
def layout_bank_pdf(v: View, rng: random.Random) -> str:
    bank = rng.choice(["Northbridge Retail Bank", "Calder & Vane Bank plc", "Ostrava Mutual", "Pellucid Savings Bank"])
    W = 70

    def row(label: str, value: str) -> str:
        return f"  {label} " + "." * max(3, 34 - len(label)) + f" {value}"

    def header(page: int) -> list[str]:
        return [f"{bank} · Onboarding file {v.case_ref} · CONFIDENTIAL".ljust(W - 12) + f"Page {page} of 3", "-" * W]

    L = [f"{bank.upper()}", "CUSTOMER ONBOARDING FILE (PDF export, text layer)", "",
         row("File reference", v.case_ref), row("Review date (as-of)", v.as_of),
         row("Application received", v.app_date), row("Booking country", v.country),
         row("Product applied for", v.product), row("Channel", v.channel), "",
         "PART A  CUSTOMER AS DECLARED ON THE APPLICATION",
         row("A1 Full name", v.name), row("A2 Date of birth", v.dob), row("A3 Nationality", v.nationality),
         row("A4 Residential address", v.address), row("A5 Occupation", v.occupation),
         row("A6 Employer", v.employer), row("A7 Source of funds", v.sof),
         row("A8 Expected monthly turnover", f"{v.volume} {v.currency}"),
         row("A9 Expected account use", v.activity),
         row("A10 Customer remarks", v.note or "—"), "", "\f"]
    L += header(2) + ["PART B  IDENTITY DOCUMENT · OCR CAPTURE OF UPLOADED IMAGE",
                      row("Document type", v.doc_kind), row("Issuing state", v.issuer),
                      row("Issuing authority", v.authority), row("Surname", v.surname),
                      row("Given names", v.given), row("Document no.", v.doc_number),
                      row("Nationality", v.doc_nationality), row("Sex", v.sex), row("Date of birth", v.doc_dob),
                      row("Place of birth", v.place_of_birth), row("Date of issue", v.issue),
                      row("Date of expiry", v.expiry)]
    L += ["  Machine-readable zone (as captured):"] + [f"    {m}" for m in v.mrz] if v.mrz else \
        ["  Machine-readable zone: none on this document type"]
    if v.id_extra:
        L += [f"  Additional text captured on image: {v.id_extra}"]
    L += ["", "PART C  PROOF OF ADDRESS · OCR CAPTURE"]
    if not v.poa_present:
        L += [f"  {v.no_poa}"]
    elif not v.poa_legible:
        L += [row("Document type", v.poa_kind), "  Text layer (OCR):"] + [f"    {g}" for g in _garble(rng)]
    else:
        L += [row("Document type", v.poa_kind), row("Issuer", v.poa_issuer), row("Document date", v.poa_date),
              row("Addressed to", v.poa_name), "  Address block as printed:"] + [f"    {l}" for l in v.poa_lines]
    if v.poa_note:
        L += [f"  Note on document: {v.poa_note}"]
    L += ["", "\f"] + header(3) + ["PART D  SCREENING VENDOR RESULTS"]
    if not v.hits:
        L += [f"  {v.no_hits}"]
    for h in v.hits:
        L += [f"  Result {h.hit_id} — {h.list_type} list {h.source}, record {h.entry_id}, similarity {h.score}/100",
              row("    Listed name", h.primary), row("    Matched on", h.matched_on),
              row("    Aliases", _alias_str(h)), row("    Listed DOB", h.dob), row("    Listed nationality", h.nationality)]
        L += [row(f"    {lab.capitalize()}", val) for lab, val in h.details]
    L += ["", "End of export."]
    return "\n".join(L)


# --------------------------------------------------------------------------
# style 2: contact-centre after-call summary with pasted OCR
# --------------------------------------------------------------------------
def layout_call_centre(v: View, rng: random.Random) -> str:
    agent = rng.choice(["agent 2214", "agent 0871", "agent 3390", "agent 1150"])
    L = [f"CONTACT CENTRE · NEW-ACCOUNT CALL SUMMARY  (call {_ref(rng, 'CC-')}, {agent})",
         f"Case {v.case_ref}. Review as of {v.as_of}; application dated {v.app_date}.",
         f"Customer is applying for a {v.product} via {v.channel}, account to be held in {v.country}.", "",
         "What the customer told me on the call (typed back from the application form):",
         f"- Name given: {v.name}",
         f"- Born {v.dob}; nationality {v.nationality}",
         f"- Lives at: {v.address}",
         f"- Works as: {v.occupation} (employer: {v.employer})",
         f"- Money comes from: {v.sof}",
         f"- Expects roughly {v.volume} {v.currency} a month through the account; usage: {v.activity}"]
    L += [f'- Asked me to add this comment word for word: "{v.note}"'] if v.note else ["- No other comments from the customer."]
    L += ["", f"Uploaded ID ({v.doc_kind}, issued by {v.issuer}). OCR text from the upload tool:", "    ----"]
    L += [f"    Surname / Nom: {v.surname}", f"    Given names / Prénoms: {v.given}",
          f"    Nationality: {v.doc_nationality}    Sex: {v.sex}", f"    Date of birth: {v.doc_dob}",
          f"    Place of birth: {v.place_of_birth}", f"    Document number: {v.doc_number}",
          f"    Issued: {v.issue}    Valid until: {v.expiry}", f"    Authority: {v.authority}"]
    L += [f"    {m}" for m in v.mrz]
    if v.id_extra:
        L += [f"    {v.id_extra}"]
    L += ["    ----", ""]
    if not v.poa_present:
        L += [f"Proof of address: {v.no_poa}"]
    elif not v.poa_legible:
        L += [f"Proof of address uploaded ({v.poa_kind}). OCR output:", "    ----"] + \
             [f"    {g}" for g in _garble(rng)] + ["    ----"]
    else:
        L += [f"Proof of address uploaded: {v.poa_kind} from {v.poa_issuer}, dated {v.poa_date}, "
              f"addressed to {v.poa_name}. Address on it reads:"] + [f"    {l}" for l in v.poa_lines]
    if v.poa_note:
        L += [f"    (text on the document: {v.poa_note})"]
    L += ["", "Watchlist screening ran automatically when I closed the call:"]
    if not v.hits:
        L += [f"  {v.no_hits}"]
    for h in v.hits:
        d = "; ".join(f"{lab}: {val}" for lab, val in h.details)
        L += [f"  [{h.hit_id}] {h.list_type} · {h.source} · ref {h.entry_id} · score {h.score}",
              f"       name on list: {h.primary} (hit on '{h.matched_on}')",
              f"       also known as: {_alias_str(h)}",
              f"       DOB on list: {h.dob}; nationality on list: {h.nationality}"]
        if d:
            L += [f"       {d}"]
    L += ["", "Passing to KYC review. I have not made a decision on this account."]
    return "\n".join(L)


# --------------------------------------------------------------------------
# style 3: scanned branch fax, OCR'd, page headers, smudged boilerplate
# --------------------------------------------------------------------------
_SMUDGE = {"A": "4", "E": "F", "I": "1", "O": "0", "S": "5", "B": "8", "N": "H", "T": "7"}


def _smudge(label: str, rng: random.Random, p: float = 0.12) -> str:
    return "".join(_SMUDGE[c] if c in _SMUDGE and rng.random() < p else c for c in label)


def layout_fax(v: View, rng: random.Random) -> str:
    branch = _ref(rng, "BR", 4)
    tm = f"{rng.randint(8, 17):02d}:{rng.randint(0, 59):02d}"
    hdr = lambda n: f"FROM: {branch} ONBOARDING FAX   {v.as_of}  {tm}   P.00{n}/003"  # noqa: E731
    s = lambda x: _smudge(x, rng)  # noqa: E731
    L = [hdr(1), "", s("ACCOUNT OPENING - BRANCH REFERRAL"), s("REF NO") + f": {v.case_ref}",
         s("REVIEW AS AT") + f": {v.as_of}      " + s("APPLICATION DATED") + f": {v.app_date}",
         s("COUNTRY OF ACCOUNT") + f": {v.country}   " + s("PRODUCT") + f": {v.product}   " + s("ROUTE") + f": {v.channel}",
         "", s("APPLICANT"), s("NAME") + f": {v.name}", s("D.O.B") + f": {v.dob}   " + s("NATIONALITY") + f": {v.nationality}",
         s("HOME ADDRESS") + f": {v.address}", s("OCCUPATION") + f": {v.occupation}",
         s("EMPLOYER") + f": {v.employer}", s("SOURCE OF FUNDS") + f": {v.sof}",
         s("MONTHLY TURNOVER EXPECTED") + f": {v.volume} {v.currency}", s("PURPOSE") + f": {v.activity}"]
    if v.note:
        L += [s("APPLICANT NOTE") + f": {v.note}"]
    L += ["", " .  ' ||  ", hdr(2), "", s("COPY OF IDENTITY DOCUMENT ATTACHED") + f" ({v.doc_kind}, {v.issuer})",
          f"{v.surname}", f"{v.given}", s("NO") + f". {v.doc_number}   {v.doc_nationality}   {v.sex}",
          s("BORN") + f" {v.doc_dob}  {v.place_of_birth}", s("ISSUED") + f" {v.issue}   " + s("EXPIRES") + f" {v.expiry}",
          f"{v.authority}"]
    L += v.mrz
    if v.id_extra:
        L += [v.id_extra]
    L += ["", s("PROOF OF ADDRESS")]
    if not v.poa_present:
        L += [v.no_poa]
    elif not v.poa_legible:
        L += [f"({v.poa_kind})"] + _garble(rng, 4, 40)
    else:
        L += [f"{v.poa_kind} - {v.poa_issuer} - {v.poa_date}", f"{v.poa_name}"] + v.poa_lines
    if v.poa_note:
        L += [v.poa_note]
    L += ["", "  ,  .|", hdr(3), "", s("SCREENING PRINTOUT")]
    if not v.hits:
        L += [v.no_hits]
    for h in v.hits:
        L += [f"#{h.hit_id}  {h.list_type}  {h.source}  {h.entry_id}  " + s("SCORE") + f" {h.score}",
              f"   {h.primary}", "   " + s("AKA") + f": {_alias_str(h)}",
              "   " + s("DOB") + f": {h.dob}   " + s("NAT") + f": {h.nationality}"]
        L += [f"   {lab.upper()}: {val}" for lab, val in h.details]
    L += ["", s("END OF TRANSMISSION")]
    return "\n".join(L)


# --------------------------------------------------------------------------
# style 4: JSON case-import payload from another vendor
# --------------------------------------------------------------------------
def _json_enc(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)[1:-1]


def layout_vendor_json(v: View, rng: random.Random) -> str:
    poa: dict
    if not v.poa_present:
        poa = {"received": False, "message": v.no_poa}
    elif not v.poa_legible:
        poa = {"received": True, "doc_class": v.poa_kind, "ocr_text": "\n".join(_garble(rng))}
    else:
        poa = {"received": True, "doc_class": v.poa_kind, "issuer_name": v.poa_issuer, "doc_date": v.poa_date,
               "recipient": v.poa_name, "address_lines": v.poa_lines}
    if v.poa_note:
        poa["annotations"] = [v.poa_note]
    id_ocr = {"doc_class": v.doc_kind, "issuing_country": v.issuer, "fields": {
        "family_name": v.surname, "given_names": v.given, "document_number": v.doc_number,
        "nationality": v.doc_nationality, "sex": v.sex, "birth_date": v.doc_dob, "birth_place": v.place_of_birth,
        "issue_date": v.issue, "expiry_date": v.expiry, "issuing_authority": v.authority},
        "mrz_raw": v.mrz or None}
    if v.id_extra:
        id_ocr["unparsed_text"] = [v.id_extra]
    payload = {
        "schema": "kestrel.case-import/3.2", "import_id": _ref(rng, "imp_", 10),
        "case": {"external_ref": v.case_ref, "review_as_of": v.as_of, "submitted_at": v.app_date,
                 "jurisdiction": v.country, "product": v.product, "onboarding_channel": v.channel},
        "subject": {"name_as_entered": v.name, "birth_date": v.dob, "citizenship": v.nationality,
                    "residence_address": v.address, "occupation": v.occupation, "employer": v.employer,
                    "source_of_funds": v.sof,
                    "expected_monthly_volume": {"amount": int(v.volume), "currency": v.currency},
                    "intended_use": v.activity, "free_text": v.note or None},
        "documents": {"identity": id_ocr, "proof_of_address": poa},
        "watchlist": {"result_count": len(v.hits), "message": None if v.hits else v.no_hits, "results": [
            {"result_id": h.hit_id, "list_category": h.list_type, "list_name": h.source, "record_id": h.entry_id,
             "listed_name": h.primary, "matched_name": h.matched_on,
             "aka": [{"name": a, "quality": q} for a, q in h.aliases],
             "listed_dob": h.dob, "listed_nationality": h.nationality, "similarity": int(h.score),
             "attributes": {lab: val for lab, val in h.details}} for h in v.hits]},
    }
    return ("HTTP/1.1 200 OK\nContent-Type: application/json; charset=utf-8\nX-Vendor: Kestrel IDV\n\n"
            + json.dumps(payload, ensure_ascii=False, indent=2))


# --------------------------------------------------------------------------
# style 5: two-column paper form, OCR read row by row
# --------------------------------------------------------------------------
def layout_two_column(v: View, rng: random.Random) -> str:
    left = ["SECTION 1 - ABOUT YOU", f"Full name: {v.name}", f"Date of birth: {v.dob}",
            f"Nationality: {v.nationality}", f"Home address: {v.address}", f"Occupation: {v.occupation}",
            f"Employer: {v.employer}", f"Source of funds: {v.sof}", f"Monthly amount expected: {v.volume} {v.currency}",
            f"How you will use the account: {v.activity}", f"Anything else we should know: {v.note or 'no'}"]
    right = ["SECTION 2 - FOR OFFICE USE", f"Ref: {v.case_ref}", f"Assessed as at: {v.as_of}",
             f"Form signed: {v.app_date}", f"Account country: {v.country}", f"Product: {v.product}",
             f"Taken via: {v.channel}", "SECTION 3 - ADDRESS EVIDENCE"]
    if not v.poa_present:
        right += [v.no_poa]
    elif not v.poa_legible:
        right += [f"Type: {v.poa_kind}"] + [g[:30] for g in _garble(rng, 4)]
    else:
        right += [f"Type: {v.poa_kind}", f"From: {v.poa_issuer}", f"Dated: {v.poa_date}",
                  f"Name shown: {v.poa_name}"] + [f"  {l}" for l in v.poa_lines]
    if v.poa_note:
        right += [f"Written on it: {v.poa_note}"]
    n = max(len(left), len(right))
    left, right = left + [""] * (n - len(left)), right + [""] * (n - len(right))
    rows = [(l.ljust(58) + " " + r).rstrip() for l, r in zip(left, right)]
    L = ["ACCOUNT APPLICATION FORM  (scanned; OCR reads both columns line by line)", ""] + rows
    L += ["", "PAGE 2 - COPY OF IDENTITY DOCUMENT (OCR)",
          f"Type: {v.doc_kind}    Issuing state: {v.issuer}    Authority: {v.authority}",
          f"Surname: {v.surname}".ljust(40) + f"Given names: {v.given}",
          f"Number: {v.doc_number}".ljust(40) + f"Nationality: {v.doc_nationality}",
          f"Sex: {v.sex}".ljust(40) + f"Born: {v.doc_dob} ({v.place_of_birth})",
          f"Issued: {v.issue}".ljust(40) + f"Expires: {v.expiry}"] + v.mrz
    if v.id_extra:
        L += [v.id_extra]
    L += ["", "PAGE 3 - SCREENING (stapled printout)"]
    if not v.hits:
        L += [v.no_hits]
    for h in v.hits:
        L += [f"{h.hit_id} | {h.list_type} | {h.source} | {h.entry_id} | score {h.score} | {h.primary}",
              f"    aka: {_alias_str(h)} | dob: {h.dob} | nationality: {h.nationality}"]
        L += [f"    {lab}: {val}" for lab, val in h.details]
    return "\n".join(L)


# --------------------------------------------------------------------------
# style 6: case-management ticket with team comments
# --------------------------------------------------------------------------
def layout_ticket(v: View, rng: random.Random) -> str:
    key = _ref(rng, "ONB-", 5)
    L = [f"[{key}] Onboarding review: {v.name}",
         f"Status: Awaiting KYC decision · Priority: Normal · External ref: {v.case_ref}",
         f"Review as-of: {v.as_of} · Created: {v.app_date} · Country: {v.country} · Product: {v.product} · Channel: {v.channel}",
         "", "── Comment 1 · onboarding-bot", "Form submission:",
         f"* **Name:** {v.name}", f"* **DOB:** {v.dob}", f"* **Nationality:** {v.nationality}",
         f"* **Address:** {v.address}", f"* **Occupation:** {v.occupation}", f"* **Employer:** {v.employer}",
         f"* **Source of funds:** {v.sof}", f"* **Volume per month (expected):** {v.volume} {v.currency}",
         f"* **Planned activity:** {v.activity}"]
    if v.note:
        L += [f"* **Applicant message:** {v.note}"]
    L += ["", "── Comment 2 · documents-team", f"ID scan received ({v.doc_kind}, {v.issuer}). Pasting the OCR:", "```",
          f"SURNAME {v.surname}", f"GIVEN NAMES {v.given}", f"DOC NO {v.doc_number}",
          f"NATIONALITY {v.doc_nationality}  SEX {v.sex}", f"DATE OF BIRTH {v.doc_dob}  PLACE {v.place_of_birth}",
          f"DATE OF ISSUE {v.issue}  DATE OF EXPIRY {v.expiry}", f"AUTHORITY {v.authority}"] + v.mrz
    if v.id_extra:
        L += [v.id_extra]
    L += ["```"]
    if not v.poa_present:
        L += [f"Address proof: {v.no_poa}"]
    elif not v.poa_legible:
        L += [f"Address proof received ({v.poa_kind}); OCR came back as:", "```"] + _garble(rng) + ["```"]
    else:
        L += [f"Address proof received: {v.poa_kind}, {v.poa_issuer}, dated {v.poa_date}, to {v.poa_name}:", "```"] \
            + v.poa_lines + ["```"]
    if v.poa_note:
        L += [f"There is also this on the address proof: {v.poa_note}"]
    L += ["", "── Comment 3 · screening-service"]
    if not v.hits:
        L += [v.no_hits]
    else:
        L += ["| Hit | List | Source | Record | Score | Listed name | Aliases | DOB | Nationality |",
              "|---|---|---|---|---|---|---|---|---|"]
        L += [f"| {h.hit_id} | {h.list_type} | {h.source} | {h.entry_id} | {h.score} | {h.primary} | "
              f"{_alias_str(h)} | {h.dob} | {h.nationality} |" for h in v.hits]
        for h in v.hits:
            if h.details:
                L += [f"{h.hit_id} details: " + "; ".join(f"{lab}: {val}" for lab, val in h.details)]
    L += ["", "── Comment 4 · onboarding-bot", "Assigning to KYC analyst queue."]
    return "\n".join(L)


STYLES: dict[str, Style] = {s.name: s for s in [
    Style("bank_pdf_export", fmt_dmy_short, "[unreadable]", "No proof-of-address document on file.",
          "No results returned.", layout_bank_pdf),
    Style("call_centre_summary", fmt_mdy_long, "(not legible on the scan)",
          "the customer has not uploaded one yet.", "  nothing came back.", layout_call_centre),
    Style("fax_ocr_dump", fmt_dmy_caps, "#######", "NOT ENCLOSED", "NO HITS", layout_fax),
    Style("vendor_json", fmt_iso, "<illegible>", "no proof-of-address document received",
          "no watchlist results", layout_vendor_json, enc=_json_enc, number=str),
    Style("two_column_form", fmt_ymd_slash, "~~~~~~", "None attached", "No matches on printout.",
          layout_two_column),
    Style("case_ticket", fmt_dmy_long, "▒▒▒▒▒▒", "not provided by the applicant.",
          "Screening returned zero hits.", layout_ticket),
]}


def render_hand(t: CaseTruth, style: str, rng: random.Random | None = None) -> tuple[str, View]:
    """Render one truth in one hand style. Raises AssertionError if a required fact is missing
    or hidden truth leaks (the label would no longer be derivable from the packet)."""
    st = STYLES[style]
    rng = rng or random.Random(f"hand:{t.case_id}:{style}")
    v = make_view(t, st)
    packet = st.layout(v, rng)
    probs = check_packet(packet, v, st)
    assert not probs, f"{t.case_id} [{style}]: " + "; ".join(probs[:5])
    return packet, v


def assign_styles(n: int, seed: int) -> list[str]:
    """Balanced, deterministic: each style gets n/6 cases (+1 for the first n%6)."""
    names = list(STYLES)
    out = [names[i % len(names)] for i in range(n)]
    random.Random(f"hand-style:{seed}").shuffle(out)
    return out


# --------------------------------------------------------------------------
# build
# --------------------------------------------------------------------------
def labeller():
    """project.py, imported lazily so the current schema version (v0 or v1) labels the cases."""
    P = importlib.import_module("step1_data_generation.project")
    return P.project, P.SCHEMA, getattr(P, "SCHEMA_ID", "unknown")


def sample_truths(n: int, seed: int, prefix: str) -> list[CaseTruth]:
    from step1_data_generation.sample import sample_cases

    cfg = replace(load_config(CONFIG), case_id_prefix=prefix)
    return sample_cases(n, seed, cfg=cfg)


def _git_commit() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True,
                              cwd=ROOT).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def write_jsonl_files(out: Path, files: dict[str, list[dict]]) -> dict[str, str]:
    sha = {}
    for name, items in files.items():
        data = "".join(json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n" for x in items)
        (out / name).write_text(data, encoding="utf-8", newline="\n")
        sha[name] = hashlib.sha256(data.encode("utf-8")).hexdigest()
    return sha


def guard_out(out: Path, allow_eval: bool, force: bool) -> None:
    if not allow_eval:
        raise SystemExit(f"refusing to build {out}: this is an EVAL set. Pass --allow-eval "
                         "(and freeze it with step6_evaluation/split_guard.py after the dev pilot).")
    from step6_evaluation.split_guard import exact_name_exists  # case-sensitive on Windows too
    if exact_name_exists(out / "MANIFEST.json"):
        raise SystemExit(f"{out}/MANIFEST.json exists: this eval set is frozen; never overwrite it")
    if exact_name_exists(out / "manifest.json") and not force:
        raise SystemExit(f"{out}/manifest.json exists; refusing to overwrite (use --force before the freeze)")


def build(n: int = DEFAULT_N, seed: int = DEFAULT_SEED, out: Path = DEFAULT_OUT, *, allow_eval: bool = False,
          force: bool = False) -> dict:
    guard_out(out, allow_eval, force)
    project, schema, schema_id = labeller()
    import jsonschema

    validator = jsonschema.Draft202012Validator(schema)
    truths = sample_truths(n, seed, "oodh")
    styles = assign_styles(n, seed)
    rows, truth_rows = [], []
    for t, style in zip(truths, styles):
        packet, v = render_hand(t, style)
        expected = project(t)
        errs = list(validator.iter_errors(expected))
        if errs:
            raise ValueError(f"{t.case_id}: expected output fails schema: {errs[0].message}")
        t.split = "eval_ood_template"
        t.knobs = {**t.knobs, "style": style, "style_family": "ood_hand", "renderer": RENDERER}
        rows.append({"case_id": t.case_id, "split": SPLIT, "config_id": t.config_id, "schema": schema_id,
                     "style": style, "renderer": RENDERER, "scenarios": t.scenarios, "knobs": t.knobs,
                     "packet": packet, "expected": expected, "n_required_facts": len(v.facts)})
        truth_rows.append({"case_id": t.case_id, "truth": t.to_dict()})
    out.mkdir(parents=True, exist_ok=True)
    sha = write_jsonl_files(out, {"cases.jsonl": rows, "truth.jsonl": truth_rows})
    manifest = {
        "split": SPLIT, "renderer": RENDERER, "config_path": str(CONFIG.relative_to(ROOT)),
        "config_sha256": hashlib.sha256(CONFIG.read_bytes()).hexdigest(), "generator_version": GENERATOR_VERSION,
        "git_commit": _git_commit(), "schema": schema_id, "seed": seed, "n_total": len(rows),
        "command": f"python -m step1_data_generation.ood_templates --allow-eval --n {n} --seed {seed}",
        "fact_check": "every packet passed check_packet (all required facts present, no leaks)",
        "style_counts": dict(collections.Counter(r["style"] for r in rows)),
        "primary_scenario_counts": dict(collections.Counter(r["scenarios"][0] for r in rows)),
        "decision_counts": dict(collections.Counter(r["expected"].get("decision") for r in rows)),
        "sha256": sha,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                                       encoding="utf-8", newline="\n")
    return manifest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=DEFAULT_N)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--allow-eval", action="store_true", help="required: this writes an eval set")
    ap.add_argument("--force", action="store_true", help="overwrite an unfrozen manifest.json")
    ap.add_argument("--show", metavar="STYLE", help="print one rendered example of STYLE and exit (no files)")
    a = ap.parse_args(argv)
    if a.show:
        t = sample_truths(1, a.seed, "oodh")[0]
        print(render_hand(t, a.show)[0])
        return 0
    m = build(a.n, a.seed, a.out, allow_eval=a.allow_eval, force=a.force)
    print(json.dumps({k: m[k] for k in ("split", "n_total", "style_counts", "decision_counts", "sha256")}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
