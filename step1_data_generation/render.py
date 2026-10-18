"""Truth -> case packet text.

PROVISIONAL (overnight draft). Several layout styles so a model can't
overfit one format:

* ``kv``     key: value blocks under bracketed section headers
* ``form``   boxed onboarding-form look with numbered fields
* ``prose``  case-file style paragraphs
* ``mixed``  shuffled section order, mixed key styles, JSON-ish vendor block

Held-out layout families (v1; never used for step5_training/dev, see ``step1_data_generation.config``):

* ``email``     an intake e-mail thread with the documents pasted in as
                "attachments" and the screening as a CSV export
* ``ocr_dump``  one unbroken OCR dump with no section headers; sections are
                marked only by short inline reference tags

Every packet prints the as-of date in CTX. Every style tags sections with ids the narrative cites: CTX, APP, ID, MRZ,
POA, SCR and H1..Hn.

Background OCR noise is applied at render time to labels and boilerplate
only. Values that the labels depend on (names, dates, numbers, MRZ lines,
addresses) are protected, because their defects are decided in the truth
object, not here. Rendering is deterministic for a given (truth, style, seed).
"""
from __future__ import annotations

import json
import random
from datetime import date

from step1_data_generation.lib import address as A
from step1_data_generation.lib import ocr as O
from step1_data_generation.truth import CaseTruth

STYLES = ("kv", "form", "prose", "mixed")          # seen in training
HELDOUT_STYLES = ("email", "ocr_dump")             # held out of step5_training/dev
ALL_STYLES = STYLES + HELDOUT_STYLES
_P0, _P1 = "\x02", "\x03"          # protected-span markers
MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
COUNTRY_NAMES = {**A.COUNTRY_NAMES}
DOC_TITLES = {"passport": ["PASSPORT / PASSEPORT / PASAPORTE", "PASSPORT", "PASSEPORT - PASSPORT"],
              "national_id": ["NATIONAL IDENTITY CARD", "IDENTITY CARD / CARTE D'IDENTITE", "ID CARD"],
              "driving_licence": ["DRIVING LICENCE", "DRIVER LICENSE", "PERMIS DE CONDUIRE"]}
POA_TITLES = {"utility_bill": "Utility bill", "bank_statement": "Account statement",
              "council_tax": "Council tax / municipal levy notice", "telecom_bill": "Mobile and broadband bill",
              "tenancy_agreement": "Tenancy agreement (extract)", "government_letter": "Residency confirmation letter"}
PRODUCT_LABEL = {"current_account": "current account", "savings": "savings account",
                 "business_account": "business account", "crypto_wallet": "crypto wallet",
                 "remittance": "remittance service", "premium_card": "premium credit card",
                 "brokerage": "brokerage account"}
POA_DATE_LABEL = {"utility_bill": ["Bill date", "Statement date", "Date"], "telecom_bill": ["Bill date", "Invoice date"],
                  "bank_statement": ["Statement date", "Statement period ending"],
                  "council_tax": ["Notice date", "Date of issue"], "tenancy_agreement": ["Agreement dated", "Date"],
                  "government_letter": ["Date of letter", "Issued on"]}
POA_ADDR_LABEL = {"utility_bill": ["Supply address", "Service address", "Address"],
                  "telecom_bill": ["Service address", "Billing address"],
                  "bank_statement": ["Address", "Correspondence address"],
                  "council_tax": ["Property", "Property address"], "tenancy_agreement": ["Property", "Premises"],
                  "government_letter": ["Registered address", "Address"]}
VENDOR = ["SynScreen Watchlist Service (synthetic)", "Clearwater Screening API (synthetic)", "ListGuard v4 (synthetic)"]


def P(s) -> str:
    """Protect a value from background OCR noise."""
    return f"{_P0}{s}{_P1}"


def _strip(s: str) -> str:
    return s.replace(_P0, "").replace(_P1, "")


def fmt_date(d: date | str | None, style: str) -> str:
    if d in (None, ""):
        return ""
    if isinstance(d, str):
        d = date.fromisoformat(d)
    if style == "iso":
        return d.isoformat()
    if style == "dmy_dots":
        return f"{d.day:02d}.{d.month:02d}.{d.year}"
    if style == "dmon":
        return f"{d.day:02d} {MONTHS[d.month - 1]} {d.year}"
    if style == "dmon_short":
        return f"{d.day:02d} {MONTHS[d.month - 1]} {d.year % 100:02d}"
    if style == "long":
        return d.strftime("%d %B %Y").lstrip("0")
    raise ValueError(style)


def _illegible(rng: random.Random) -> str:
    return rng.choice(["[illegible]", "▒▒ ▒▒▒ ▒▒▒▒", "--", "?? ??? ????", "[smudged]"])


# --------------------------------------------------------------------------
# section builders: each returns (title, list[(key, value)]) so styles can lay them out
# --------------------------------------------------------------------------
def _ctx(t: CaseTruth, rng, ds) -> list[tuple[str, str]]:
    c = t.context
    return [("Case reference", P(c.case_ref)),
            ("Onboarding country", f"{COUNTRY_NAMES[c.onboarding_country]} ({c.onboarding_country})"),
            ("Product", PRODUCT_LABEL[c.product]),
            ("Channel", c.channel.replace("_", " ")),
            ("Application date", P(fmt_date(c.application_date, ds))),
            (rng.choice(["As-of date", "Review date (as of)", "Assessed as of"]), P(fmt_date(c.as_of_date, ds)))]


def _app(t: CaseTruth, rng, ds, inj) -> list[tuple[str, str]]:
    a = t.application
    occ, emp, act = a.occupation, a.employer, a.expected_activity
    if inj.present and inj.location == "occupation":
        occ = f"{occ}. {inj.text}"
    if inj.present and inj.location == "employer":
        emp = f"{emp} ({inj.text})"
    if inj.present and inj.location == "expected_activity":
        act = f"{act}. {inj.text}"
    rows = [(rng.choice(["Full name", "Name", "Applicant name"]), P(a.full_name)),
            ("Date of birth", P(fmt_date(a.dob, ds))),
            ("Nationality", P(a.nationality)),
            ("Residential address", P(a.address.one_line(abbreviate=a.address_abbreviated))),
            ("Occupation", occ), ("Employer", emp),
            (rng.choice(["Declared source of funds", "Source of funds"]), a.source_of_funds.replace("_", " ")),
            ("Expected monthly volume", P(f"{a.expected_monthly_volume:,} {a.currency}")),
            ("Expected account activity", act)]
    if inj.present and inj.location == "applicant_note":
        rows.append((rng.choice(["Applicant comments", "Additional information", "Notes from applicant"]), inj.text))
    return rows


def _id_text(t: CaseTruth, rng, inj) -> str:
    d = t.id_doc
    v = d.viz
    ds = rng.choice(["dmon", "dmy_dots", "iso"]) if d.kind != "driving_licence" else "dmy_dots"

    def val(k, f=None):
        x = v.get(k, "")
        if not x:
            return _illegible(rng)
        return P(f(x) if f else x)
    bil = rng.random() < 0.5
    lab = lambda en, fr: f"{en} / {fr}" if bil else en
    lines = [rng.choice(DOC_TITLES[d.kind]), f"{lab('Issuing state', 'Etat emetteur')}: {P(d.issuing_state)}"]
    fields = [
        (lab("Surname", "Nom"), val("surname", str.upper)),
        (lab("Given names", "Prenoms"), val("given_names", str.upper)),
        (lab("Nationality", "Nationalite"), val("nationality")),
        (lab("Date of birth", "Date de naissance"), val("birth_date", lambda x: fmt_date(x, ds))),
        (lab("Sex", "Sexe"), val("sex")),
        (lab("Place of birth", "Lieu de naissance"), val("place_of_birth", str.upper)),
        (lab("Date of issue", "Date de delivrance"), P(fmt_date(d.issue_date, ds))),
        (lab("Date of expiry", "Date d'expiration"), val("expiry_date", lambda x: fmt_date(x, ds))),
        (lab("Authority", "Autorite"), v.get("authority", "")),
        ({"passport": "Passport No.", "national_id": "Card No.", "driving_licence": "Licence No."}[d.kind],
         val("doc_number")),
    ]
    if rng.random() < 0.5:
        # OCR often reads two-column layouts in a scrambled order
        head, tail = fields[:3], fields[3:]
        rng.shuffle(tail)
        fields = head + tail
    sep = rng.choice([": ", " ", "  "])
    lines += [f"{k}{sep}{x}" for k, x in fields]
    if inj.present and inj.location == "id_ocr":
        lines.insert(rng.randint(2, len(lines)), inj.text)
    return "\n".join(lines)


def _mrz_text(t: CaseTruth) -> str:
    return "\n".join(P(l) for l in t.id_doc.mrz_lines) if t.id_doc.mrz_lines else ""


def _poa_text(t: CaseTruth, rng, inj) -> str:
    p = t.poa
    if not p.present:
        return ""
    ds = rng.choice(["dmon", "long", "dmy_dots", "iso"])
    addr = p.address.render(p.render_style, abbreviate=p.abbreviated)
    lines = [p.issuer.upper(), POA_TITLES[p.kind],
             f"{rng.choice(POA_DATE_LABEL[p.kind])}: {P(fmt_date(p.issue_date, ds))}",
             f"{rng.choice(['Account number', 'Customer ref', 'Reference'])}: {rng.randint(10000000, 99999999)}",
             f"{rng.choice(['Account holder', 'Name', 'Addressed to'])}: {P(p.name_on_doc)}",
             f"{rng.choice(POA_ADDR_LABEL[p.kind])}:",
             *[P(l) for l in addr.splitlines()]]
    if p.kind in ("utility_bill", "telecom_bill"):
        lines.append(f"Amount due: {rng.randint(20, 400)}.{rng.randint(0, 99):02d}")
    if inj.present and inj.location == "poa_notes":
        lines.append(f"{rng.choice(['Notes', 'Message', 'Remarks'])}: {inj.text}")
    text = "\n".join(lines)
    if not p.legible:
        # an unreadable scan: heavy noise everywhere, address lines blotted
        text = _strip(text)
        noisy, _ = O.noise_text(text, rng, O.OCRProfile(rate=p.ocr_level))
        out = []
        for l in noisy.splitlines():
            out.append("".join(ch if rng.random() > 0.45 or ch == " " else rng.choice("▒#~.") for ch in l))
        return "[scan quality poor - text partially unreadable]\n" + "\n".join(out)
    return text


def _hit_rows(t: CaseTruth, h, rng, inj) -> list[tuple[str, str]]:
    e = h.entry
    rows = [("Hit", h.hit_id), ("List", f"{e['list_source']} ({h.list_type.replace('_', ' ')})"),
            ("Entry id", e["entry_id"]), ("Listed name", P(e["primary_name"]))]
    if e["aliases"]:
        rows.append(("Aliases", P("; ".join(f"{a} [{q}]" for a, q in zip(e["aliases"], e["alias_quality"])))))
    rows.append(("Listed DOB", P(e["dob"] if e["dob"] != "unknown" else "not listed")))
    rows.append(("Listed nationality", P(e["nationality"] or "not listed")))
    det = e.get("details") or {}
    if h.list_type == "sanctions":
        for k in ("programs", "regime", "regulation", "listed_on", "identification"):
            if det.get(k):
                rows.append((k.replace("_", " ").capitalize(), ", ".join(det[k]) if isinstance(det[k], list) else str(det[k])))
    elif h.list_type == "pep":
        rows.append(("PEP position", f"{det.get('position', '')} ({det.get('pep_category', '')}, {det.get('status', '')})"))
        if det.get("rca_type"):
            rows.append(("Relationship", f"{det['relationship']} of {P(det['related_pep'])} (PEP)"))
    else:
        age = det.get("age_reported")
        occ, city = det.get("occupation_reported") or "", det.get("city_reported") or ""
        desc = " ".join(x for x in (occ.lower(), f"from {city}" if city else "") if x)
        bits = [e["primary_name"]] + ([str(age)] if age is not None else []) + ([desc] if desc else [])
        headline = ", ".join(bits) + f", {det['headline_template']}"
        rows.append(("Article", f"{det['outlet']}, {fmt_date(det['published'], 'dmon')}"))
        rows.append(("Excerpt", P(headline)))
    remarks = det.get("remarks", "")
    if inj.present and inj.location == "hit_remarks" and h.hit_id == "H1":
        remarks = f"{remarks} {inj.text}".strip()
    if remarks:
        rows.append(("Remarks", remarks))
    rows.append(("Match score", P(str(h.score))))
    return rows


# --------------------------------------------------------------------------
# layouts
# --------------------------------------------------------------------------
TITLES = {"CTX": ["Jurisdiction and product", "Case context", "CONTEXT"],
          "APP": ["Applicant profile (as submitted)", "Application form", "Customer details"],
          "ID": ["Identity document (OCR)", "ID document scan - OCR text", "Identity document"],
          "MRZ": ["Machine-readable zone", "MRZ (OCR)", "MRZ"],
          "POA": ["Proof of address (OCR)", "Proof-of-address document", "Address evidence (OCR)"],
          "SCR": ["Screening results", "Watchlist screening", "Vendor screening report"]}


def _kv_block(rows, keyfmt="{k}: {v}") -> str:
    return "\n".join(keyfmt.format(k=k, v=v) for k, v in rows)


def render(t: CaseTruth, style: str | None = None, seed: int | None = None) -> tuple[str, str]:
    """Return (packet_text, style_used). Without ``style`` the truth's knob
    vector decides (``knobs['style']``), else a seen style at random. Twins
    keep their base case's ``knobs['render_key']`` so both render alike."""
    rng = random.Random(f"render:{t.knobs.get('render_key', t.case_id)}:{seed}")
    style = style or t.knobs.get("style") or rng.choice(STYLES)
    if style not in ALL_STYLES:
        raise ValueError(f"unknown style {style!r}")
    inj = t.injection
    ds_app = rng.choice(["iso", "dmon", "long"])
    title = {k: rng.choice(v) for k, v in TITLES.items()}
    ctx, app = _ctx(t, rng, ds_app), _app(t, rng, ds_app, inj)
    id_txt, mrz_txt, poa_txt = _id_text(t, rng, inj), _mrz_text(t), _poa_text(t, rng, inj)
    vendor = rng.choice(VENDOR)
    hits = [(h, _hit_rows(t, h, rng, inj)) for h in t.hits]

    # OCR background noise on document text (labels/boilerplate only)
    id_txt = _noise_unprotected(id_txt, rng, t.id_doc.ocr_level)
    if t.poa.legible:
        poa_txt = _noise_unprotected(poa_txt, rng, t.poa.ocr_level)

    if style == "kv":
        sec = []
        sec.append(f"[CTX] {title['CTX']}\n{_kv_block(ctx)}")
        sec.append(f"[APP] {title['APP']}\n{_kv_block(app)}")
        doc = f"[ID] {title['ID']}\n{id_txt}"
        if mrz_txt:
            doc += f"\n[MRZ] {title['MRZ']}\n{mrz_txt}"
        sec.append(doc)
        sec.append(f"[POA] {title['POA']}\n{poa_txt}" if poa_txt else f"[POA] {title['POA']}\nNo document provided.")
        scr = f"[SCR] {title['SCR']} - provider: {vendor}\n"
        scr += ("\n".join(f"[{h.hit_id}]\n" + _kv_block(rows[1:], "  {k}: {v}") for h, rows in hits)
                if hits else "No hits returned.")
        sec.append(scr)
        body = "\n\n".join(sec)
    elif style == "form":
        def boxed(tag, ttl, rows):
            n = [f"  {i + 1:>2}. {k:<28} {v}" for i, (k, v) in enumerate(rows)]
            bar = "=" * 60
            return f"{bar}\n SECTION {tag} | {ttl.upper()}\n{bar}\n" + "\n".join(n)
        sec = [boxed("CTX", title["CTX"], ctx), boxed("APP", title["APP"], app)]
        doc = f"{'=' * 60}\n SECTION ID | {title['ID'].upper()}\n{'=' * 60}\n{id_txt}"
        if mrz_txt:
            doc += f"\n--- MRZ ---\n{mrz_txt}"
        sec.append(doc)
        sec.append(f"{'=' * 60}\n SECTION POA | {title['POA'].upper()}\n{'=' * 60}\n" + (poa_txt or "(not provided)"))
        scr = f"{'=' * 60}\n SECTION SCR | {title['SCR'].upper()} ({vendor})\n{'=' * 60}\n"
        scr += ("\n".join(f"  -- {h.hit_id} --\n" + _kv_block(rows[1:], "     {k:<20} {v}") for h, rows in hits)
                if hits else "  (no hits)")
        sec.append(scr)
        body = "\n\n".join(sec)
    elif style == "prose":
        c = dict(ctx)
        a = app
        para_ctx = (f"Case context (CTX). Case {c['Case reference']} concerns an application for a {c['Product']} "
                    f"opened via the {c['Channel']} channel in {c['Onboarding country']}, received on {c['Application date']} "
                    f"and assessed as of {ctx[-1][1]}.")
        para_app = "Applicant profile (APP). The applicant submitted the following: " + "; ".join(f"{k.lower()}: {v}" for k, v in a) + "."
        doc = f"Identity document (ID). The OCR output of the submitted document reads:\n{id_txt}"
        if mrz_txt:
            doc += f"\nThe machine-readable zone (MRZ) reads:\n{mrz_txt}"
        poa = (f"Proof of address (POA). The applicant supplied the following document (OCR):\n{poa_txt}" if poa_txt
               else "Proof of address (POA). No proof-of-address document was supplied.")
        if hits:
            hs = []
            for h, rows in hits:
                hs.append(f"Hit {h.hit_id}: " + "; ".join(f"{k.lower()} {v}" for k, v in rows[1:]) + ".")
            scr = f"Screening (SCR). {vendor} returned {len(hits)} candidate hit{'s' if len(hits) > 1 else ''}. " + " ".join(hs)
        else:
            scr = f"Screening (SCR). {vendor} returned no hits."
        body = "\n\n".join([para_ctx, para_app, doc, poa, scr])
    elif style == "email":
        body = _email(t, rng, title, ctx, app, id_txt, mrz_txt, poa_txt, vendor, hits)
    elif style == "ocr_dump":
        body = _ocr_dump(t, rng, ctx, app, id_txt, mrz_txt, poa_txt, vendor, hits)
    else:  # mixed
        blocks = {
            "CTX": f"## {title['CTX']} (CTX)\n" + _kv_block(ctx, "- {k}: {v}"),
            "APP": f"## {title['APP']} (APP)\n" + _kv_block(app, rng.choice(["- {k}: {v}", "{k} = {v}", "{k}: {v}"])),
            "ID": f"## {title['ID']} (ID)\n```\n{id_txt}\n```" + (f"\nMRZ (MRZ):\n```\n{mrz_txt}\n```" if mrz_txt else ""),
            "POA": f"## {title['POA']} (POA)\n" + (f"```\n{poa_txt}\n```" if poa_txt else "_none provided_"),
        }
        if hits:
            payload = [{k.lower().replace(" ", "_"): _strip(v) for k, v in rows} for h, rows in hits]
            scr_body = json.dumps({"provider": vendor, "hits": payload}, ensure_ascii=False, indent=1)
        else:
            scr_body = json.dumps({"provider": vendor, "hits": []})
        hit_ids = f"; hits H1..H{len(hits)}" if len(hits) > 1 else ("; hit H1" if hits else "")
        blocks["SCR"] = f"## {title['SCR']} (SCR{hit_ids})\n```json\n{scr_body}\n```"
        order = ["CTX", "APP", "ID", "POA", "SCR"]
        mid = order[1:4]
        rng.shuffle(mid)
        order = [order[0]] + mid + [order[4]] if rng.random() < 0.6 else mid + ["SCR", "CTX"]
        body = "\n\n".join(blocks[k] for k in order)
    header = rng.choice(["KYC ONBOARDING CASE PACKET", "Onboarding review packet", "CASE FILE - NEW CUSTOMER", "KYC case"])
    return _strip(f"{header}\n\n{body}\n"), style


def _email(t, rng, title, ctx, app, id_txt, mrz_txt, poa_txt, vendor, hits) -> str:
    """L5 held-out family: an intake e-mail with pasted attachments."""
    c = dict(ctx)
    sender = rng.choice(["onboarding-intake", "branch-ops", "kyc-queue", "new-accounts"])
    who = rng.choice(["Priya", "Tomasz", "Ines", "Kwame", "Mei", "Olu", "Sofia"])
    head = (f"From: {sender}@bank.example\nTo: kyc-review@bank.example\n"
            f"Subject: {rng.choice(['New onboarding case', 'Case for review', 'FW: application received'])} "
            f"{c['Case reference']}\n\n"
            f"{rng.choice(['Hi team,', 'Hello,', 'Dear reviewer,'])}\n\n"
            f"Forwarding a new {c['Product']} application ({c['Channel']} channel, {c['Onboarding country']}). "
            f"Case details are below as CTX; the form and scans are pasted under each attachment heading.\n\n"
            "CTX\n" + "\n".join(f"  {k} - {v}" for k, v in ctx))
    att = [f"--- Attachment 1: application_form.txt [APP] ---\n" + "\n".join(f"{k}: {v}" for k, v in app)]
    doc = f"--- Attachment 2: id_scan_ocr.txt [ID] ---\n{id_txt}"
    if mrz_txt:
        doc += f"\n(MRZ strip, OCR) [MRZ]\n{mrz_txt}"
    att.append(doc)
    att.append(f"--- Attachment 3: proof_of_address_ocr.txt [POA] ---\n{poa_txt}" if poa_txt
               else "--- Attachment 3: proof_of_address [POA] ---\n(customer did not upload one)")
    if hits:
        cols = ["hit", "list", "entry_id", "listed_name", "aliases", "listed_dob", "listed_nationality", "other", "score"]
        lines = [",".join(cols)]
        for h, rows in hits:
            r = {k.lower().replace(" ", "_"): v for k, v in rows}
            other = "; ".join(f"{k}: {v}" for k, v in rows
                              if k not in ("Hit", "List", "Entry id", "Listed name", "Aliases", "Listed DOB",
                                           "Listed nationality", "Match score"))
            vals = [h.hit_id, r.get("list", ""), r.get("entry_id", ""), r.get("listed_name", ""), r.get("aliases", ""),
                    r.get("listed_dob", ""), r.get("listed_nationality", ""), other, r.get("match_score", "")]
            lines.append(",".join('"' + str(v).replace('"', "'") + '"' for v in vals))
        scr = f"--- Attachment 4: screening_export.csv [SCR] ({vendor}) ---\n" + "\n".join(lines)
    else:
        scr = f"--- Attachment 4: screening_export.csv [SCR] ({vendor}) ---\nhit,list,entry_id\n(no rows)"
    att.append(scr)
    sign = f"Thanks,\n{who}\n{rng.choice(['Onboarding Operations', 'Branch Services', 'Customer Intake'])}"
    footer = ("This e-mail and any attachments are confidential and intended solely for the addressee. "
              "If you received it in error please delete it.")
    return head + "\n\n" + "\n\n".join(att) + "\n\n" + sign + "\n\n" + footer


def _wrap_protected(text: str, width: int) -> list[str]:
    """Greedy word wrap that never breaks inside a protected span."""
    toks, buf, prot = [], [], False
    for ch in text:
        if ch == _P0:
            prot = True
            buf.append(ch)
        elif ch == _P1:
            prot = False
            buf.append(ch)
        elif ch in " \n" and not prot:
            if buf:
                toks.append("".join(buf))
                buf = []
        else:
            buf.append(ch)
    if buf:
        toks.append("".join(buf))
    lines, cur = [], ""
    for tok in toks:
        if cur and len(_strip(cur)) + 1 + len(_strip(tok)) > width:
            lines.append(cur)
            cur = tok
        else:
            cur = f"{cur} {tok}" if cur else tok
    if cur:
        lines.append(cur)
    return lines


def _ocr_dump(t, rng, ctx, app, id_txt, mrz_txt, poa_txt, vendor, hits) -> str:
    """L8 held-out family: one OCR dump of the whole file, no section headers;
    only short reference tags (CTX, APP, ...) mark where each part starts."""
    sep = rng.choice([" | ", " ; ", "  "])
    parts = ["CTX " + sep.join(f"{k} {v}" for k, v in ctx),
             "APP " + sep.join(f"{k} {v}" for k, v in app),
             "ID " + id_txt.replace("\n", sep)]
    parts.append("POA " + (poa_txt.replace("\n", sep) if poa_txt else "no document"))
    if hits:
        parts.append(f"SCR {vendor} " + sep.join(
            f"{h.hit_id} " + " ".join(f"{k} {v}" for k, v in rows[1:]) for h, rows in hits))
    else:
        parts.append(f"SCR {vendor} no hits")
    if rng.random() < 0.5:
        parts.append(rng.choice(["Page 1 of 1", "Scanned by MFD-04", "Customer copy - retain for your records"]))
    width = rng.choice([90, 110, 130])
    lines = _wrap_protected(" ".join(parts), width)
    if mrz_txt:
        # the MRZ is a fixed-width strip; OCR keeps it on its own lines, tagged inline
        at = next((i for i, l in enumerate(lines) if "POA " in _strip(l)), len(lines))
        lines[at:at] = ["MRZ"] + mrz_txt.splitlines()
    return "\n".join(lines)


def _noise_unprotected(text: str, rng: random.Random, rate: float) -> str:
    if rate <= 0:
        return text
    out, buf, prot = [], [], False
    for ch in text:
        if ch == _P0:
            out.append(O.noise_text("".join(buf), rng, rate=rate)[0])
            buf, prot = [], True
            out.append(ch)
        elif ch == _P1:
            out.append("".join(buf))
            buf, prot = [], False
            out.append(ch)
        else:
            buf.append(ch)
    tail = "".join(buf)
    out.append(tail if prot else O.noise_text(tail, rng, rate=rate)[0])
    return "".join(out)
