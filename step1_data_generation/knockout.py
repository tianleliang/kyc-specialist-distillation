"""Evidence knockout: remove or obscure the one piece of evidence a decisive
case rests on, so the correct outcome becomes escalate.

Machinery for a candidate invented technique (documentation/02_research/distillation_options.md
§3.3, escalation calibration). OFF by default (``knockout.enabled: false`` in
step1_data_generation/configs/train.yaml).

Each op edits a deep copy of the truth: a hit loses its listed DOB and
nationality, an ID field becomes illegible in every zone, the PoA goes
missing or unreadable, an article loses its age/city/occupation. The label is
recomputed by ``step1_data_generation/project.py``; a knockout is kept only if the outcome there
is escalate (and, by default, the base case's was not).

    from step1_data_generation.knockout import make_knockouts
    kos = make_knockouts(base_truth, rng)        # [(knocked_truth, record), ...]

Train-side only: build.py refuses knockouts for eval splits.
"""
from __future__ import annotations

import copy
import random
from dataclasses import dataclass
from typing import Callable

from step1_data_generation import project as P
from step1_data_generation.lib.matching import ListedDOB
from step1_data_generation.sample import obscure_mrz_field
from step1_data_generation.truth import CaseTruth, DocDefect, ProofOfAddress


@dataclass(frozen=True)
class Knockout:
    name: str
    evidence: str                                     # what is removed or obscured
    applies: Callable[[CaseTruth], bool]
    apply: Callable[[CaseTruth, random.Random], None]


def _resolved_person_hits(t: CaseTruth):
    """Sanctions/PEP hits the packet currently resolves on DOB (match or conflict)."""
    return [h for h in t.hits if h.list_type in ("sanctions", "pep") and h.dob_comparison in ("exact", "mismatch")]


def _hit_identifiers(t, rng):
    h = rng.choice(_resolved_person_hits(t))
    h.entry["dob"] = ListedDOB().render()
    h.entry["nationality"] = None
    h.dob_comparison, h.nationality_match = "unknown", None
    h.discriminators = []
    t.ambiguity.append("knockout:hit_no_identifiers")


def _media_hits(t):
    return [h for h in t.hits if h.list_type == "adverse_media" and h.discriminators]


def _media_identifiers(t, rng):
    h = rng.choice(_media_hits(t))
    det = h.entry.setdefault("details", {})
    for k in ("age_reported", "city_reported", "occupation_reported"):
        det[k] = None
    h.discriminators = []
    t.ambiguity.append("knockout:media_no_identifiers")


ID_FIELDS = ("birth_date", "doc_number", "expiry_date")


def _id_legible(t):
    return [f for f in ID_FIELDS if t.id_doc.viz.get(f)]


def _id_field(t, rng):
    d = t.id_doc
    fld = rng.choice(_id_legible(t))
    d.viz[fld] = ""
    if d.mrz_lines:
        d.mrz_lines = obscure_mrz_field(d.mrz_lines, d.mrz_format, fld, rng)
        d.mrz_check = "unreadable"
    d.defects.append(DocDefect("ocr_unreadable", fld, "both" if d.mrz_format else "viz", "knockout: illegible in the scan"))
    t.ambiguity.append("knockout:id_field_illegible")


def _poa_missing(t, rng):
    t.poa = ProofOfAddress(False)
    if t.injection.present and t.injection.location == "poa_notes":
        t.injection.location = "applicant_note"
    t.ambiguity.append("knockout:poa_missing")


def _poa_illegible(t, rng):
    t.poa.legible, t.poa.ocr_level = False, 0.35
    if t.injection.present and t.injection.location == "poa_notes":
        t.injection.location = "applicant_note"
    t.ambiguity.append("knockout:poa_illegible")


KNOCKOUTS: dict[str, Knockout] = {k.name: k for k in [
    Knockout("hit_identifiers_removed", "listed DOB and nationality of a resolved hit",
             lambda t: bool(_resolved_person_hits(t)), _hit_identifiers),
    Knockout("media_identifiers_removed", "reported age, city and occupation of an article",
             lambda t: bool(_media_hits(t)), _media_identifiers),
    Knockout("id_field_illegible", "one ID field in every zone",
             lambda t: bool(_id_legible(t)), _id_field),
    Knockout("poa_removed", "the proof-of-address document", lambda t: t.poa.present, _poa_missing),
    Knockout("poa_illegible", "the proof-of-address text", lambda t: t.poa.present and t.poa.legible, _poa_illegible),
]}


def make_knockout(base: CaseTruth, op: str, rng: random.Random) -> tuple[CaseTruth, dict]:
    k = KNOCKOUTS[op]
    if not k.applies(base):
        raise ValueError(f"{op} does not apply to {base.case_id}")
    ko = copy.deepcopy(base)
    k.apply(ko, rng)
    ko.case_id = f"{base.case_id}-ko-{op}"
    ko.knobs = {**base.knobs, "augmentation": "knockout", "knockout_of": base.case_id, "knockout_op": op,
                "knockout_evidence": k.evidence, "render_key": base.knobs.get("render_key", base.case_id),
                "style": base.knobs.get("style"), "ambiguity": list(ko.ambiguity)}
    ko.notes = [*base.notes, f"knockout:{op}"]
    before, after = P.outcome(base), P.outcome(ko)
    rec = {"base_id": base.case_id, "knockout_id": ko.case_id, "op": op, "evidence": k.evidence,
           "outcome_from": before, "outcome_to": after,
           "escalates": after == P.ESCALATE, "changed": before != after}
    return ko, rec


def make_knockouts(base: CaseTruth, rng: random.Random, ops: list[str] | None = None,
                   max_per_base: int = 1, require_change: bool = True) -> list[tuple[CaseTruth, dict]]:
    """Up to ``max_per_base`` knockouts of ``base`` whose outcome is escalate
    (and, with ``require_change``, whose base outcome was not)."""
    cands = [o for o in (ops or list(KNOCKOUTS)) if KNOCKOUTS[o].applies(base)]
    rng.shuffle(cands)
    out = []
    for op in cands:
        ko, rec = make_knockout(base, op, random.Random(f"ko:{base.case_id}:{op}:{rng.random()}"))
        if rec["escalates"] and (rec["changed"] or not require_change):
            out.append((ko, rec))
            if len(out) >= max_per_base:
                break
    return out
