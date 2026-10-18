"""Name normalization and similarity, simulating a screening vendor's score.

``similarity`` is order-insensitive token Jaro-Winkler with a concatenation
fallback (so "Xiao Ming" ~ "Xiaoming", "Abdul Rahman" ~ "Abdulrahman").
``vendor_score`` maps it to the 0-100 scale screening vendors report, with
optional jitter, because real vendors disagree with each other by a few points.

Also: partial date-of-birth comparison, since a watchlist DOB is often just
a year or a range.
"""
from __future__ import annotations

import random
import re
import unicodedata
from dataclasses import dataclass
from datetime import date

from rapidfuzz.distance import JaroWinkler

TITLES = {"mr", "mrs", "ms", "miss", "dr", "prof", "sir", "sheikh", "shaikh",
          "haji", "hajji", "hj", "sayyid", "sri", "shri", "smt", "chief",
          "alhaji", "mme", "m", "herr", "frau", "sr", "sra", "dona", "don"}
ARTICLES = {"al", "el", "ul", "ad", "ar", "as", "at", "az", "ash", "bin", "ibn",
            "bint", "ben", "abu", "de", "da", "do", "dos", "das", "del", "la",
            "van", "von", "der", "den", "le"}
# Order matters: longer patterns first.
_PHONETIC = [
    ("schtsch", "shch"), ("tsch", "ch"), ("sch", "sh"), ("shch", "sh"),
    ("kh", "h"), ("gh", "g"), ("ph", "f"), ("dh", "z"), ("th", "t"),
    ("ou", "u"), ("oo", "u"), ("ee", "i"), ("ie", "i"), ("ey", "i"), ("iy", "i"),
    ("cz", "ts"), ("tz", "ts"), ("ck", "k"), ("q", "k"), ("x", "h"), ("w", "v"),
    ("y", "i"), ("j", "i"), ("c", "k"), ("z", "s"), ("e", "i"),
]


def strip_accents(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def tokens(name: str, drop_articles: bool = True) -> list[str]:
    s = strip_accents(name).lower()
    s = s.replace("'", "").replace("’", "").replace("`", "")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    toks = [t for t in s.split() if t not in TITLES]
    if drop_articles:
        toks = [t for t in toks if t not in ARTICLES] or toks
    return toks


def phonetic_key(tok: str) -> str:
    t = tok
    for a, b in _PHONETIC:
        t = t.replace(a, b)
    t = re.sub(r"(.)\1+", r"\1", t)           # collapse doubles
    if len(t) > 1:
        t = t[0] + re.sub(r"[aiou]", "", t[1:]) or t  # vowels carry little signal
    return t


def normalize(name: str, phonetic: bool = False) -> str:
    toks = tokens(name)
    if phonetic:
        toks = [phonetic_key(t) for t in toks]
    return " ".join(toks)


def _tok_sim(a: str, b: str) -> float:
    s = JaroWinkler.similarity(a, b)
    pa, pb = phonetic_key(a), phonetic_key(b)
    if pa == pb:
        s = max(s, 0.95)
    elif pa and pb:
        s = max(s, 0.9 * JaroWinkler.similarity(pa, pb))
    if len(a) >= 1 and len(b) >= 1 and (len(a) == 1 or len(b) == 1):
        # an initial matches the token it abbreviates
        if a[0] == b[0]:
            s = max(s, 0.85)
    return s


def _aligned(ta: list[str], tb: list[str]) -> float:
    if not ta or not tb:
        return 0.0
    if len(ta) > len(tb):
        ta, tb = tb, ta
    used: set[int] = set()
    sims = []
    # greedy best-pair alignment (fine for <= 5 tokens)
    pairs = sorted(((_tok_sim(a, b), i, j) for i, a in enumerate(ta)
                    for j, b in enumerate(tb)), reverse=True)
    done_a: set[int] = set()
    for s, i, j in pairs:
        if i in done_a or j in used:
            continue
        done_a.add(i)
        used.add(j)
        sims.append(s)
    core = sum(sims) / len(sims)
    # penalty for unmatched extra tokens (e.g. a missing middle name)
    extra = len(tb) - len(ta)
    return core * (0.92 ** extra)


_GLUED_ARTICLE = re.compile(r"^(al|el|ul)(?=[^aeiou]{1,2}[aeiou])")


def _deglue(toks: list[str]) -> list[str]:
    """'alqasimi' -> 'qasimi'. Only tried as an alternative reading, since
    'alina' or 'elena' must survive."""
    return [_GLUED_ARTICLE.sub("", t) if len(t) > 5 else t for t in toks]


def similarity(a: str, b: str) -> float:
    """0..1 similarity between two personal names."""
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    da, db = _deglue(ta), _deglue(tb)
    if da != ta or db != tb:
        return max(_similarity(ta, tb), _similarity(da, db))
    return _similarity(ta, tb)


def _similarity(ta: list[str], tb: list[str]) -> float:
    best = _aligned(ta, tb)
    if len(ta) != len(tb):
        # spacing differences (Xiao Ming / Xiaoming); Winkler's prefix
        # bonus is too generous on whole names, so this path is discounted
        ca, cb = "".join(ta), "".join(tb)
        best = max(best, JaroWinkler.similarity(ca, cb) * 0.95)
    # concatenation of any adjacent pair (Abdul Rahman ~ Abdulrahman)
    for toks, other in ((ta, tb), (tb, ta)):
        for i in range(len(toks) - 1):
            merged = toks[:i] + [toks[i] + toks[i + 1]] + toks[i + 2:]
            best = max(best, _aligned(merged, other))
    return round(min(best, 1.0), 4)


def best_alias_similarity(name: str, primary: str, aliases: list[str] = ()) -> tuple[float, str]:
    best = (similarity(name, primary), primary)
    for al in aliases:
        s = similarity(name, al)
        if s > best[0]:
            best = (s, al)
    return best


def vendor_score(a: str, b: str, rng: random.Random | None = None,
                 jitter: float = 3.0, aliases: list[str] = ()) -> int:
    """Simulated vendor match score 0-100 (max over primary and aliases)."""
    s, _ = best_alias_similarity(a, b, aliases)
    score = 100 * s
    if rng is not None and jitter:
        score += rng.gauss(0, jitter)
    return int(max(0, min(100, round(score))))


# --------------------------------------------------------------------------
# date of birth comparison
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class ListedDOB:
    """A watchlist DOB: exact date, year only, or a year range ('circa')."""
    year: int | None = None
    month: int | None = None
    day: int | None = None
    year_to: int | None = None  # inclusive upper bound for ranges

    @classmethod
    def exact(cls, d: date) -> "ListedDOB":
        return cls(d.year, d.month, d.day)

    def render(self) -> str:
        if self.year is None:
            return "unknown"
        if self.year_to and self.year_to != self.year:
            return f"{self.year} to {self.year_to}"
        if self.month and self.day:
            return f"{self.year:04d}-{self.month:02d}-{self.day:02d}"
        if self.month:
            return f"{self.year:04d}-{self.month:02d}"
        return f"{self.year}"


DOB_RESULTS = ("exact", "year_month", "year_only", "in_range", "day_month_swapped",
               "near_year", "mismatch", "unknown")


def compare_dob(applicant: date, listed: ListedDOB) -> str:
    """How an applicant DOB relates to a listed DOB."""
    if listed.year is None:
        return "unknown"
    if listed.year_to:
        if listed.year <= applicant.year <= listed.year_to:
            return "in_range"
        return "near_year" if min(abs(applicant.year - listed.year),
                                   abs(applicant.year - listed.year_to)) <= 1 else "mismatch"
    if applicant.year == listed.year:
        if listed.month is None:
            return "year_only"
        if listed.day is None:
            return "year_month" if applicant.month == listed.month else "mismatch"
        if (applicant.month, applicant.day) == (listed.month, listed.day):
            return "exact"
        if (applicant.month, applicant.day) == (listed.day, listed.month):
            return "day_month_swapped"
        if applicant.month == listed.month:
            return "year_month"
        return "mismatch"
    if abs(applicant.year - listed.year) == 1 and listed.month is None:
        return "near_year"
    return "mismatch"
