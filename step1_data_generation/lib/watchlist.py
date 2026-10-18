"""Synthetic watchlists: sanctions, PEP and adverse-media entries.

Entries copy the *public structure* of the OFAC SDN list (uid, SDN type,
programs, a.k.a. list with strong/weak quality, multiple DOBs, POB,
identification documents, remarks), the UN Security Council consolidated
list (reference number, name parts, designation, listed-on date, alias
quality Good/Low), and the EU consolidated list (logical id, regulation,
name aliases with 'strong' flag, circa birth dates). Every name is
fictional (step1_data_generation.lib.names), program codes and regulations are invented,
and every entry carries ``synthetic: true``.

PEP entries follow FATF categories (domestic / foreign / international
organisation) with family members and close associates. Adverse-media
entries are fictional headlines from fictional outlets.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field, asdict
from datetime import date, timedelta

from . import matching
from .matching import ListedDOB
from .names import PersonName, aliases as name_aliases, sample_name, ORIGIN_NATIONALITIES

LIST_SOURCES = {
    "sanctions": ["OFAC-SDN-SYN", "UN-SC-CONSOLIDATED-SYN", "EU-CFSP-SYN", "UK-HMT-SYN"],
    "pep": ["PEP-DB-SYN"],
    "adverse_media": ["MEDIA-MONITOR-SYN"],
}
# invented program codes / regimes, formatted like the real ones
SDN_PROGRAMS = ["SYN-NARCO", "SYN-CYBER2", "SYN-EO99012", "SYN-TCO", "SYN-PROLIF", "SYN-REGION-EO99031"]
UN_REGIMES = [("SYi", "1999 Synthetic Committee"), ("XYi", "2101 Synthetic Panel"), ("KZi", "2203 Synthetic Regime")]
EU_REGS = ["(SYN) 2031/101", "(SYN) 2029/447", "(SYN) 2033/12"]
PEP_ROLES = [
    ("Deputy Minister of Transport", "domestic", 1), ("Member of Parliament", "domestic", 2),
    ("Governor of a regional administration", "domestic", 1), ("Supreme Court judge", "domestic", 1),
    ("Head of a state-owned energy company", "domestic", 2), ("Ambassador", "foreign", 2),
    ("Minister of Finance", "foreign", 1), ("Senior military officer (general)", "foreign", 1),
    ("Senior official of a political party", "domestic", 2), ("Mayor of a capital city", "domestic", 2),
    ("Board member of an international organisation", "international_org", 2),
    ("Central bank deputy governor", "foreign", 1),
]
RELATIONSHIPS = {"family": ["spouse", "child", "parent", "sibling", "son-in-law", "daughter-in-law"],
                 "close_associate": ["business partner", "co-owner of a company", "known close associate",
                                     "beneficial owner of an entity controlled by the PEP"]}
MEDIA_OUTLETS = ["The Meridian Ledger", "Coastal Business Wire", "Northgate Herald", "The Civic Observer",
                 "Delta Financial Times-Courier", "Harbourline Daily", "The Plainfield Gazette"]
MEDIA_CATEGORIES = {
    "fraud": "charged in an alleged investment fraud scheme",
    "corruption": "named in a procurement bribery investigation",
    "money_laundering": "accused of laundering proceeds through shell companies",
    "tax_evasion": "under investigation for alleged tax evasion",
    "organised_crime": "linked by prosecutors to an organised smuggling ring",
    "sanctions_evasion": "accused of helping a listed company evade trade restrictions",
    "minor_civil": "involved in a civil dispute with a former landlord",
}


@dataclass
class Entry:
    """One listed record (structure-agnostic core plus list-specific details)."""
    entry_id: str
    list_type: str            # sanctions | pep | adverse_media
    list_source: str
    primary_name: str
    aliases: list[str]
    alias_quality: list[str]  # parallel to aliases: strong/weak (or Good/Low)
    dob: ListedDOB
    nationality: str | None
    details: dict = field(default_factory=dict)
    synthetic: bool = True

    def to_dict(self) -> dict:
        d = asdict(self)
        d["dob"] = self.dob.render()
        return d


@dataclass
class Hit:
    """A vendor screening hit: an entry plus the vendor's match score."""
    entry: Entry
    score: int
    matched_on: str           # the listed name/alias that scored highest

    def to_dict(self) -> dict:
        return {"score": self.score, "matched_on": self.matched_on, **self.entry.to_dict()}


# --------------------------------------------------------------------------
# entry builders
# --------------------------------------------------------------------------
def _listed_dob(rng: random.Random, dob: date | None, precision: str | None = None) -> ListedDOB:
    if dob is None:
        return ListedDOB()
    precision = precision or rng.choices(["exact", "year", "range", "year_month"], [5, 3, 2, 1])[0]
    if precision == "exact":
        return ListedDOB.exact(dob)
    if precision == "year":
        return ListedDOB(dob.year)
    if precision == "year_month":
        return ListedDOB(dob.year, dob.month)
    if precision == "none":
        return ListedDOB()
    lo = dob.year - rng.randint(0, 2)
    return ListedDOB(lo, year_to=lo + rng.randint(2, 4))


def make_entry(rng: random.Random, person: PersonName, list_type: str, *,
               dob: date | None, nationality: str | None, list_source: str | None = None,
               dob_precision: str | None = None, n_aliases: int | None = None,
               primary_system: str | None = None, details: dict | None = None) -> Entry:
    """A listed entry for ``person``. The listed primary name may use a
    different romanization than the applicant's documents."""
    src = list_source or rng.choice(LIST_SOURCES[list_type])
    if primary_system is None and rng.random() < 0.5:
        primary_system = rng.choice(person.systems())
    order = "surname_comma" if src.startswith(("OFAC", "UK")) else "given_first"
    if person.origin == "chinese" and order == "given_first":
        order = "surname_first"
    primary = person.full(system=primary_system, order=order, rng=rng,
                          upper_surname=src.startswith(("OFAC", "UN")))
    k = n_aliases if n_aliases is not None else rng.randint(1 if list_type == "sanctions" else 0, 4)
    als = name_aliases(person, rng, k) if k else []
    quality = [rng.choice(["strong", "strong", "weak"]) for _ in als]
    if src.startswith("UN"):
        quality = ["Good" if q == "strong" else "Low" for q in quality]
    eid = _entry_id(rng, src)
    det = dict(details or {})
    if list_type == "sanctions":
        det.setdefault("sdn_type" if src.startswith("OFAC") else "subject_type", "Individual" if src.startswith("OFAC") else "person")
        if src.startswith("OFAC"):
            det.setdefault("programs", rng.sample(SDN_PROGRAMS, rng.randint(1, 2)))
        elif src.startswith("UN"):
            code, regime = rng.choice(UN_REGIMES)
            det.setdefault("regime", regime)
            det.setdefault("listed_on", (date(2020, 1, 1) + timedelta(days=rng.randint(0, 2000))).isoformat())
        else:
            det.setdefault("regulation", rng.choice(EU_REGS))
        det.setdefault("remarks", rng.choice(["", "Linked to a sanctioned synthetic entity.",
                                              "Believed to reside abroad.", "Additional DOB reported."]))
    return Entry(eid, list_type, src, primary, als, quality,
                 _listed_dob(rng, dob, dob_precision), nationality, det)


def _entry_id(rng: random.Random, src: str) -> str:
    if src.startswith("OFAC"):
        return f"SYN-{rng.randint(10000, 99999)}"
    if src.startswith("UN"):
        code, _ = rng.choice(UN_REGIMES)
        return f"{code}.{rng.randint(100, 999)}"
    if src.startswith("EU"):
        return f"EU.SYN.{rng.randint(1000, 99999)}"
    if src.startswith("UK"):
        return f"SYN{rng.randint(1000, 9999)}"
    if src.startswith("PEP"):
        return f"PEP-{rng.randint(100000, 999999)}"
    return f"AM-{rng.randint(100000, 999999)}"


def pep_details(rng: random.Random, pep_name: str, relation: str | None = None,
                relationship: str | None = None, status: str | None = None,
                country: str | None = None) -> dict:
    """PEP entry details. ``relation`` None = the PEP themselves; otherwise
    'family' / 'close_associate' with ``relationship`` (spouse, ...)."""
    role, category, level = rng.choice(PEP_ROLES)
    status = status or rng.choice(["current", "current", "former"])
    d = {"pep_category": category, "position": role, "level": level, "status": status,
         "country": country or "", "since": rng.randint(2008, 2024)}
    if status == "former":
        d["left_office"] = rng.randint(2010, 2025)
    if relation:
        d["rca_type"] = relation
        d["relationship"] = relationship or rng.choice(RELATIONSHIPS[relation])
        d["related_pep"] = pep_name
    return d


def media_details(rng: random.Random, category: str | None = None, when: date | None = None) -> dict:
    category = category or rng.choice(list(MEDIA_CATEGORIES))
    when = when or date(2026, 10, 17) - timedelta(days=rng.randint(30, 3650))
    return {"category": category, "outlet": rng.choice(MEDIA_OUTLETS),
            "published": when.isoformat(), "headline_template": MEDIA_CATEGORIES[category]}


# --------------------------------------------------------------------------
# hits
# --------------------------------------------------------------------------
def score_hit(applicant_name: str, entry: Entry, rng: random.Random | None = None,
              jitter: float = 2.5) -> Hit:
    s, on = matching.best_alias_similarity(applicant_name, entry.primary_name, entry.aliases)
    score = 100 * s + (rng.gauss(0, jitter) if rng else 0)
    return Hit(entry, int(max(0, min(100, round(score)))), on)


class Watchlist:
    """A pool of synthetic entries with threshold screening, the way a
    vendor would run it."""

    def __init__(self, entries: list[Entry] | None = None):
        self.entries = list(entries or [])

    def add(self, e: Entry) -> None:
        self.entries.append(e)

    def screen(self, name: str, threshold: int = 80, rng: random.Random | None = None,
               limit: int = 5) -> list[Hit]:
        hits = [score_hit(name, e, rng) for e in self.entries]
        hits = [h for h in hits if h.score >= threshold]
        return sorted(hits, key=lambda h: -h.score)[:limit]


def decoy_entries(rng: random.Random, n: int) -> list[Entry]:
    """Background population of listed fictional people."""
    out = []
    for _ in range(n):
        p = sample_name(rng)
        lt = rng.choices(["sanctions", "pep", "adverse_media"], [5, 3, 2])[0]
        y = rng.randint(1945, 1995)
        dob = date(y, rng.randint(1, 12), rng.randint(1, 28))
        nat = rng.choice(ORIGIN_NATIONALITIES[p.origin])
        det = pep_details(rng, "", country=nat) if lt == "pep" else (media_details(rng) if lt == "adverse_media" else None)
        out.append(make_entry(rng, p, lt, dob=dob, nationality=nat, details=det))
    return out
