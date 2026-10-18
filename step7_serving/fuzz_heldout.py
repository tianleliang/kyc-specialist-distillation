"""Held-out fuzz family F-heldout: a cover letter written by a relationship
manager. Not shown to P3 until the end (P3 only sees its score).

What it varies beyond the other families: letter container with a letterhead
place + date (a decoy at the top), phrasings and cue words none of the others
use ("as at", "carried out on", "valid through", "invoice raised"), labels
mostly absent (facts inside sentences), US M/D/Y dates allowed alongside the
spec formats, appendices with the OCR'd documents in random kv / prose, random
wrap, case and look-alike glyph noise in unprotected text.
"""
from __future__ import annotations

import random
from datetime import date

from step7_serving import fuzz_render as FR

FAM = dict(containers=[], labels=["none"], noise=0.3, ocr=0.02, decoys=0.0, wrap=True, case=False)
CITIES = ["London", "Dublin", "Frankfurt", "Lisbon", "Rotterdam", "Leeds"]

# private vocabulary: none of these strings is in fuzz_render.py (which P3 can read)
HO_LABELS = {
    "id_kind": ["kind of paper", "credential"], "issuing_state": ["country that issued it", "home office of"],
    "surname": ["last-name line", "patronymic/family"], "given": ["personal names", "called"],
    "id_nat": ["citizen of", "passport country"], "id_dob": ["came into the world", "natal day"],
    "id_issue": ["handed out", "made out on"], "id_expiry": ["good until", "lapses"],
    "doc_number": ["serial", "ident"], "sex": ["m/f"], "authority": ["office", "bureau"],
    "pob": ["native town", "hometown"],
    "poa_kind": ["paper"], "poa_issuer": ["sender", "company"], "poa_date": ["raised", "put out"],
    "poa_name": ["recipient", "for the attention of"], "poa_addr": ["premises", "delivered to"],
}
US_OK = {"mdy_slash", "month_d_y", "month_ord_y", "mon_d_y", "iso", "compact"}
HO_DECOYS = ["Faxed", "Archived", "Copy made", "Stamped received", "Logged"]


def _ho_section(c, fields) -> list[str]:
    out = []
    for k, kind, v in fields:
        val = c.value(k, kind, v)
        r = c.rng.random()
        lab = None if r < 0.5 else c.rng.choice(HO_LABELS.get(k, ["item"]))
        out.append(f"{lab} {c.rng.choice([':', '-', '=', ''])} {val}".strip() if lab else val)
    c.rng.shuffle(out)
    return [c.rng.choice(["; ", " / ", "  "]).join(out)] if c.rng.random() < 0.5 else out


def render(t: dict, seed: int) -> tuple[str, dict]:
    rng = random.Random(f"{FR.HELDOUT}|{t.get('case_id')}|{seed}")
    c = FR._Ctx(rng, FAM, extra_formats=True)
    # one date order per author: the letter body is US (M/D) or not; enclosed documents never use M/D
    us = rng.random() < 0.4
    allf = dict(FR.DATE_FORMATS, **FR.EXTRA_FORMATS)
    body_f = {k: v for k, v in allf.items() if (k in US_OK if us else k != "mdy_slash")}
    doc_f = dict(FR.DATE_FORMATS)
    c.formats = body_f
    S = FR.facts(t)
    ctx = {k: v for k, _, v in S["ctx"]}
    app = {k: v for k, _, v in S["app"]}
    idf = {k: (kind, v) for k, kind, v in S["id"]}
    as_of = ctx["as_of"]
    letter_day = date.fromordinal(as_of.toordinal() + rng.randint(-5, 5))
    L = [f"{rng.choice(CITIES)}, {c.protect(body_f[rng.choice(sorted(body_f))](letter_day, rng))}",
         "", "To: Financial Crime Compliance", f"Re: {c.protect(ctx['case_ref'])}", "",
         rng.choice(["Dear colleagues,", "Dear Sir or Madam,", "To whom it may concern,"]), ""]
    asof_s = c.date("as_of", as_of)
    appd_s = c.date("app_date", ctx["app_date"])
    s1 = [f"{app['name']} asked us for a {ctx['product']} on {appd_s} ({ctx['channel']}, {ctx['country']}).",
          rng.choice([f"This review is carried out as at {asof_s}.", f"Our assessment is made as at {asof_s}.",
                      f"Please treat {asof_s} as the as-of date of this review."])]
    rng.shuffle(s1)
    L += [" ".join(s1), ""]
    L += [f"The customer states they were born on {c.date('app_dob', app['app_dob'])}, hold "
          f"{app['nationality']} nationality, live at {app['address']} and work as {app['occupation']} "
          f"for {app['employer']}; funds come from {app['sof']} (about {app['volume']} a month).", ""]
    L += [rng.choice(["Appendix A - identity document as scanned", "Enclosure 1 (ID)", "Attached ID:"])]
    c.formats = doc_f
    L += _ho_section(c, S["id"])
    c.formats = body_f
    if S["mrz"]:
        L += FR._mrz_block(c, S["mrz"])
    L += [""]
    if "poa" in S:
        p = {k: (kind, v) for k, kind, v in S["poa"]}
        L += [rng.choice(["Appendix B - address evidence", "Enclosure 2", "We also hold:"])]
        if rng.random() < 0.5:
            L += [f"A {p['poa_kind'][1].lower()} from {p['poa_issuer'][1]}, invoice raised "
                  f"{c.date('poa_date', p['poa_date'][1])}, addressed to {p['poa_name'][1]} at {p['poa_addr'][1]}."]
        else:
            c.formats = doc_f
            L += _ho_section(c, S["poa"])
            c.formats = body_f
        L += [""]
    L += [rng.choice(["Screening returned:", "Watchlist matches:", "Hits:"])] + (S["scr"] or ["none"]) + [""]
    L += [rng.choice(["Kind regards,", "Yours faithfully,"]), "Relationship Manager", FR.DISCLAIMERS[rng.randrange(6)]]
    # held-out decoys, written here rather than by FR.finish (its cue list is public)
    for _ in range(rng.randint(1, 3)):
        d = date.fromordinal(as_of.toordinal() + rng.randint(-400, 30))
        mrz_ph = {f"\x00{i}\x00" for i, x in enumerate(c.prot) if x in S["mrz"]}
        ok = [j for j in range(len(L) + 1) if not (0 < j < len(L) and L[j - 1] in mrz_ph and L[j] in mrz_ph)]
        L.insert(rng.choice(ok), f"{rng.choice(HO_DECOYS)} "
                 f"{c.protect(body_f[rng.choice(sorted(body_f))](d, rng))}")
    packet = FR.finish(c, L, t)
    errs = FR.self_check(packet, t, c.dates)
    if errs:
        raise FR.SelfCheckError("; ".join(errs))
    return packet, {"family": FR.HELDOUT, "dates": [(k, f) for k, f, _, _ in c.dates]}
