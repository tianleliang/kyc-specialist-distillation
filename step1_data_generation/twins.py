"""Counterfactual twins: minimal pairs that differ in exactly one decision-relevant fact.

Machinery for a candidate invented technique (documentation/02_research/distillation_options.md
§3.1). OFF by default (``twins.enabled: false`` in step1_data_generation/configs/train.yaml).

Each flip op edits ONE fact in a deep copy of the truth (an ID that expires,
a listed DOB that stops matching, a PoA that goes stale...). The twin keeps
the base case's layout style and render key, so both packets render the same
way except for that fact. The expected label of each twin comes from
``step1_data_generation/project.py``; a pair is kept only if the case outcome actually flips,
and the record says from what to what.

    from step1_data_generation.twins import make_twins
    pairs = make_twins(base_truth, rng)          # [(twin_truth, record), ...]

Train-side only: build.py refuses twins for eval splits.
"""
from __future__ import annotations

import copy
import random
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable

from step1_data_generation import project as P
from step1_data_generation.lib import matching as Mt
from step1_data_generation.lib import mrz as M
from step1_data_generation.lib import ocr as O
from step1_data_generation.lib.matching import ListedDOB
from step1_data_generation.sample import INJECTION_LOCATIONS, INJECTIONS, POA_WINDOW_DAYS, _add_years
from step1_data_generation.lib import address as A
from step1_data_generation.truth import CaseTruth, DocDefect, Injection


@dataclass(frozen=True)
class Flip:
    name: str
    fact: str                                         # which single fact changes
    applies: Callable[[CaseTruth], bool]
    apply: Callable[[CaseTruth, random.Random], None]  # edits the copy in place


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _fields(d) -> M.MRZFields:
    g = dict(d.genuine)
    g["birth_date"] = date.fromisoformat(g["birth_date"])
    g["expiry_date"] = date.fromisoformat(g["expiry_date"])
    return M.MRZFields(**g)


def _clean_doc(t: CaseTruth) -> bool:
    """No tamper/OCR defects, so the document can be re-issued from its fields."""
    return not t.id_doc.defects and t.id_doc.tamper is None and all(t.id_doc.viz.get(k) for k in
                                                                    ("birth_date", "doc_number", "expiry_date"))


def _reissue(t: CaseTruth, **changes) -> None:
    """Re-print the document (visual zone and MRZ) with changed genuine fields."""
    d = t.id_doc
    f = _fields(d)
    for k, v in changes.items():
        setattr(f, k, v)
    d.genuine = f.to_dict()
    d.viz["birth_date"] = f.birth_date.isoformat()
    d.viz["expiry_date"] = f.expiry_date.isoformat()
    d.viz["doc_number"] = f.doc_number
    if d.mrz_format:
        d.mrz_lines = M.build(f, d.mrz_format)
        d.mrz_check = O.explain_mrz(d.mrz_lines, d.mrz_format, t.context.as_of_date)


def _refresh_hit(t: CaseTruth, h) -> None:
    lst = _listed(h.entry["dob"])
    h.dob_comparison = Mt.compare_dob(t.person.dob, lst)
    nat = h.entry.get("nationality")
    h.nationality_match = None if nat is None else nat == t.person.nationality


def _listed(rendered: str) -> ListedDOB:
    """Inverse of ``ListedDOB.render()``: 'unknown', 'YYYY to YYYY', 'YYYY-MM-DD', 'YYYY-MM', 'YYYY'."""
    if not rendered or rendered == "unknown":
        return ListedDOB()
    if " to " in rendered:
        lo, hi = rendered.split(" to ")
        return ListedDOB(int(lo), year_to=int(hi))
    parts = [int(x) for x in rendered.split("-")]
    return ListedDOB(*parts)


def _person_hits(t: CaseTruth, comparisons: set[str], list_types=("sanctions", "pep")):
    return [h for h in t.hits if h.list_type in list_types and h.dob_comparison in comparisons]


def _other_dob(d: date, rng: random.Random) -> date:
    return date(d.year + rng.choice([-1, 1]) * rng.randint(4, 25), rng.randint(1, 12), rng.randint(1, 28))


# --------------------------------------------------------------------------
# flip ops
# --------------------------------------------------------------------------
def _expire(t, rng):
    as_of = t.context.as_of_date
    exp = as_of - timedelta(days=rng.randint(1, 400))
    _reissue(t, expiry_date=exp)
    t.id_doc.issue_date = _add_years(exp, -10) + timedelta(days=1)
    t.id_doc.viz["issue_date"] = t.id_doc.issue_date.isoformat()
    t.id_doc.defects.append(DocDefect("expired", "expiry_date", "both", "twin: expired before the as-of date"))


def _renew(t, rng):
    as_of = t.context.as_of_date
    exp = as_of + timedelta(days=rng.randint(60, 3000))
    _reissue(t, expiry_date=exp)
    t.id_doc.issue_date = _add_years(exp, -10) + timedelta(days=1)
    t.id_doc.viz["issue_date"] = t.id_doc.issue_date.isoformat()
    t.id_doc.defects = [x for x in t.id_doc.defects if x.kind != "expired"]


def _expired(t):
    return date.fromisoformat(t.id_doc.genuine["expiry_date"]) < t.context.as_of_date


def _hit_dob_conflict(t, rng):
    h = rng.choice(_person_hits(t, {"exact"}))
    h.entry["dob"] = ListedDOB.exact(_other_dob(t.person.dob, rng)).render()
    h.same_person = False
    _refresh_hit(t, h)


def _hit_dob_confirm(t, rng):
    h = rng.choice([x for x in _person_hits(t, {"mismatch"}) if x.nationality_match is not False])
    h.entry["dob"] = ListedDOB.exact(t.person.dob).render()
    h.same_person = True
    _refresh_hit(t, h)


def _listed_dob_partial(t, rng):
    h = rng.choice(_person_hits(t, {"exact"}))
    h.entry["dob"] = ListedDOB(t.person.dob.year).render()
    _refresh_hit(t, h)


def _listed_dob_full(t, rng):
    h = rng.choice(_person_hits(t, {"year_only", "year_month", "in_range"}))
    h.entry["dob"] = ListedDOB.exact(t.person.dob).render()
    h.same_person = True
    _refresh_hit(t, h)


def _poa_ok(t):
    return t.poa.present and t.poa.legible


def _poa_stale(t, rng):
    t.poa.issue_date = t.context.as_of_date - timedelta(days=rng.randint(POA_WINDOW_DAYS + 5, 400))


def _poa_refresh(t, rng):
    t.poa.issue_date = t.context.as_of_date - timedelta(days=rng.randint(2, POA_WINDOW_DAYS - 5))


def _poa_age(t):
    return (t.context.as_of_date - t.poa.issue_date).days


def _poa_contradict(t, rng):
    addr, kind = A.contradicting_variant(t.application.address, rng)
    t.poa.address, t.poa.address_relation, t.poa.contradiction = addr, "contradicts", kind


def _poa_fix(t, rng):
    t.poa.address, t.poa.address_relation, t.poa.contradiction = t.application.address, "same", ""


def _dob_typo(t, rng):
    a = t.application
    a.dob = a.dob + timedelta(days=rng.choice([1, -1, 10, 365, -365]))
    a.dob_relation = "typo_digit"


def _dob_fix(t, rng):
    t.application.dob, t.application.dob_relation = t.person.dob, "same"


def _add_injection(t, rng):
    tech, target, text = rng.choice(INJECTIONS)
    locs = [l for l in INJECTION_LOCATIONS if (l != "hit_remarks" or t.hits) and (l != "poa_notes" or t.poa.present)]
    t.injection = Injection(True, rng.choice(locs), tech, text.format(n=rng.randint(1000, 9999)), target)


def _remove_injection(t, rng):
    t.injection = Injection(False)


def _tamper_digit(t, rng):
    d = t.id_doc
    viz_f, lines, rec = O.tamper(_fields(d), d.mrz_format, rng, "viz_only", rng.choice(["birth_date", "expiry_date", "doc_number"]))
    d.viz["birth_date"], d.viz["expiry_date"], d.viz["doc_number"] = (viz_f.birth_date.isoformat(),
                                                                      viz_f.expiry_date.isoformat(), viz_f.doc_number)
    d.mrz_lines = lines
    d.tamper = rec.__dict__
    d.defects.append(DocDefect("tamper", rec.field, "viz", rec.notes))


FLIPS: dict[str, Flip] = {f.name: f for f in [
    Flip("expire_document", "id_expiry", lambda t: _clean_doc(t) and not _expired(t), _expire),
    Flip("renew_document", "id_expiry",
         lambda t: _expired(t) and t.id_doc.tamper is None and {x.kind for x in t.id_doc.defects} == {"expired"}, _renew),
    Flip("hit_dob_conflict", "listed_dob", lambda t: bool(_person_hits(t, {"exact"})), _hit_dob_conflict),
    Flip("hit_dob_confirm", "listed_dob",
         lambda t: any(h.nationality_match is not False for h in _person_hits(t, {"mismatch"})), _hit_dob_confirm),
    Flip("listed_dob_partial", "listed_dob_precision", lambda t: bool(_person_hits(t, {"exact"})), _listed_dob_partial),
    Flip("listed_dob_full", "listed_dob_precision",
         lambda t: bool(_person_hits(t, {"year_only", "year_month", "in_range"})), _listed_dob_full),
    Flip("poa_stale", "poa_date", lambda t: _poa_ok(t) and _poa_age(t) <= POA_WINDOW_DAYS, _poa_stale),
    Flip("poa_refresh", "poa_date", lambda t: _poa_ok(t) and _poa_age(t) > POA_WINDOW_DAYS, _poa_refresh),
    Flip("poa_contradict", "poa_address", lambda t: _poa_ok(t) and t.poa.address_relation != "contradicts", _poa_contradict),
    Flip("poa_fix", "poa_address", lambda t: _poa_ok(t) and t.poa.address_relation == "contradicts", _poa_fix),
    Flip("declared_dob_typo", "declared_dob", lambda t: t.application.dob_relation == "same", _dob_typo),
    Flip("declared_dob_fix", "declared_dob", lambda t: t.application.dob_relation != "same", _dob_fix),
    Flip("add_injection", "injection", lambda t: not t.injection.present, _add_injection),
    Flip("remove_injection", "injection", lambda t: t.injection.present, _remove_injection),
    Flip("tamper_document_digit", "id_integrity", lambda t: _clean_doc(t) and t.id_doc.mrz_format is not None, _tamper_digit),
]}


def make_twin(base: CaseTruth, op: str, rng: random.Random) -> tuple[CaseTruth, dict]:
    """Apply one flip op. Returns (twin, record); ``record['flipped']`` says
    whether the case outcome changed under step1_data_generation/project.py."""
    f = FLIPS[op]
    if not f.applies(base):
        raise ValueError(f"{op} does not apply to {base.case_id}")
    tw = copy.deepcopy(base)
    f.apply(tw, rng)
    tw.case_id = f"{base.case_id}-tw-{op}"
    tw.knobs = {**base.knobs, "augmentation": "twin", "twin_of": base.case_id, "twin_op": op,
                "twin_fact": f.fact, "render_key": base.knobs.get("render_key", base.case_id),
                "style": base.knobs.get("style")}
    tw.notes = [*base.notes, f"twin:{op}"]
    before, after = P.outcome(base), P.outcome(tw)
    rec = {"base_id": base.case_id, "twin_id": tw.case_id, "op": op, "fact": f.fact,
           "outcome_from": before, "outcome_to": after, "flipped": before != after}
    return tw, rec


def make_twins(base: CaseTruth, rng: random.Random, ops: list[str] | None = None,
               max_per_base: int = 1) -> list[tuple[CaseTruth, dict]]:
    """Up to ``max_per_base`` flipped twins of ``base`` (ops tried in random order)."""
    cands = [o for o in (ops or list(FLIPS)) if FLIPS[o].applies(base)]
    rng.shuffle(cands)
    out = []
    for op in cands:
        tw, rec = make_twin(base, op, random.Random(f"twin:{base.case_id}:{op}:{rng.random()}"))
        if rec["flipped"]:
            out.append((tw, rec))
            if len(out) >= max_per_base:
                break
    return out
