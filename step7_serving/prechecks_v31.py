"""Deterministic pre-checker: arithmetic a small model gets wrong, computed by
code from the KYC case packet text alone.

    run_prechecks(packet: str) -> dict
    format_block(result: dict) -> str
    apply_prechecks(messages) -> messages   # training, dev eval and serving all use this

It reads ONLY the packet text (never truth / expected labels). Every value is
conservative: when a value cannot be determined with confidence the field is
``None`` and renders as "n/d". It never guesses.

What it computes:

* **As-of date** from labels such as "As-of date", "Assessed as of",
  "Review date (as of)". ISO, D.M.Y / D/M/Y (only when unambiguous: day > 12,
  or day == month) and month-name dates are parsed.
* **MRZ** (TD3 2x44 or TD1 3x30) found in the text, tolerating spaces inside
  a line and an MRZ split over whitespace. Each check digit (document number,
  date of birth, expiry, composite) is reported OK / FAIL as read; if the MRZ
  fails as read, ICAO glyph repair (step1 ``repair_mrz``) is tried and the
  per-check result after repair is reported too. Overall status is one of
  ``valid``, ``ocr_repairable``, ``invalid``, ``unreadable`` (same semantics
  as ``step1_data_generation.lib.ocr.explain_mrz``).
* **Document expiry** from the MRZ (YYMMDD, the lib's century logic) when its
  check digit passes (as read or after repair); from the visual zone only
  when the document has no MRZ. EXPIRED / NOT EXPIRED vs the as-of date.
* **Document integrity (policy_v1 §3, v2).** Per field (date of birth,
  document number, expiry) the visual-zone value is compared with the MRZ
  value and its check digit, row by row down the §3 table, giving one class:
  consistent / readable OCR noise / ambiguous (OCR or tamper) / clear tamper
  / unreadable / single source (no MRZ); §2.2 step 2 impossible dates count
  as clear tamper. One overall line folds them: clear tamper | ambiguous |
  noise only | consistent | n/d. An ambiguous D.M.Y date is tried both ways
  and kept only when both readings give the same class.
* **Proof-of-address date** from labels in the POA section ("Date of
  letter", "Statement date", "Bill date", "Issued on", "dated", ...): days
  before as-of and WITHIN 90 DAYS / OLDER THAN 90 DAYS / DATED AFTER AS-OF
  (policy_v1 §1: day 90 is inside the window).
"""
from __future__ import annotations

import functools
import re
from datetime import date

try:  # shared MRZ arithmetic with the generator
    from step1_data_generation.lib import mrz as M
    from step1_data_generation.lib import ocr as O
except Exception:  # pragma: no cover - the lib ships with the repo
    M = None
    O = None

POA_WINDOW_DAYS = 90
HEADER = 'PRE-CHECKS (computed by code from the packet text; "n/d" = not determinable):'

# --------------------------------------------------------------------------
# dates
# --------------------------------------------------------------------------
_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}
_MON = r"(?:" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")"

# one alternation; named groups tell which form matched
DATE_RE = re.compile(
    r"(?<![\w.\-/])(?:"
    r"(?P<iso>(?P<iy>\d{4})-(?P<im>\d{1,2})-(?P<id>\d{1,2}))"
    r"|(?P<dmy>(?P<dd>\d{1,2})(?P<sep>[./])(?P<dm>\d{1,2})(?P=sep)(?P<dy>\d{4}))"
    r"|(?P<dmon>(?P<nd>\d{1,2})(?:st|nd|rd|th)?[ \-](?P<nm>" + _MON + r")\.?,?[ \-](?P<ny>\d{4}))"
    r"|(?P<mond>(?P<mm>" + _MON + r")\.? (?P<md>\d{1,2})(?:st|nd|rd|th)?,? (?P<my>\d{4}))"
    r")(?![\w\-/]|\.\d)",
    re.IGNORECASE,
)


def _mk(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def parse_date_match(m: re.Match) -> date | None:
    """Turn a DATE_RE match into a date, or None when invalid / ambiguous."""
    if m.group("iso"):
        return _mk(int(m.group("iy")), int(m.group("im")), int(m.group("id")))
    if m.group("dmy"):
        a, b, y = int(m.group("dd")), int(m.group("dm")), int(m.group("dy"))
        if a == b:
            return _mk(y, b, a)
        if a > 12 and b <= 12:      # unambiguous D.M.Y
            return _mk(y, b, a)
        return None                  # ambiguous (or M.D.Y) -> not determinable
    if m.group("dmon"):
        return _mk(int(m.group("ny")), _MONTHS[m.group("nm").lower()], int(m.group("nd")))
    if m.group("mond"):
        return _mk(int(m.group("my")), _MONTHS[m.group("mm").lower()], int(m.group("md")))
    return None


def parse_date_text(s: str) -> date | None:
    """Parse a string that is exactly one date (surrounding space allowed)."""
    m = DATE_RE.fullmatch(s.strip())
    return parse_date_match(m) if m else None


def _date_after(text: str, pos: int, max_gap: int = 40) -> date | None | str:
    """The first date starting within ``max_gap`` chars after ``pos`` (only
    separators allowed in between). Returns a date, None (no date there) or
    the string 'unparseable' (a date-like token that cannot be parsed)."""
    seg = text[pos:pos + max_gap + 30]
    m = re.match(r"[\s:=\-–|.,*]*", seg)
    start = m.end() if m else 0
    if start > max_gap:
        return None
    dm = DATE_RE.match(seg, start)
    if dm:
        d = parse_date_match(dm)
        return d if d else "unparseable"
    if re.match(r"\S*\d", seg[start:start + 12]):
        return "unparseable"
    return None


# --------------------------------------------------------------------------
# as-of date
# --------------------------------------------------------------------------
_ASOF_LABEL = re.compile(
    r"\bas[\s\-]of[\s\-]date\b\)?|\bassessed\s+as\s+of\b|\breview\s+date\s*\(as[\s\-]of\)"
    r"|\bdate\s*\(as[\s\-]of\)|\bas[\s\-]of\b(?!\s+date)",
    re.IGNORECASE,
)


def find_as_of(text: str) -> date | None:
    vals: set[date] = set()
    bad = False
    for m in _ASOF_LABEL.finditer(text):
        d = _date_after(text, m.end())
        if isinstance(d, date):
            vals.add(d)
        elif d == "unparseable":
            bad = True
    if len(vals) == 1 and not bad:
        return next(iter(vals))
    if len(vals) == 1 and bad:
        # one clean reading plus a garbled one: still unique, keep it
        return next(iter(vals))
    return CONFLICT if len(vals) > 1 else None


# --------------------------------------------------------------------------
# sections
# --------------------------------------------------------------------------
_SECTION_START = {
    "POA": re.compile(r"\(POA[;)]|\bSECTION POA\b|\[POA\]|\bPOA\s*[|:]|^#+ .*\bPOA\b", re.MULTILINE),
    "ID": re.compile(r"\(ID[;)]|\bSECTION ID\b|\[ID\]|\bID\s*[|:]|^#+ .*\bID\b", re.MULTILINE),
}
_ANY_SECTION = re.compile(
    r"\((?:CTX|APP|ID|MRZ|POA|SCR)[;)]|\bSECTION (?:CTX|APP|ID|MRZ|POA|SCR)\b|\[(?:CTX|APP|ID|MRZ|POA|SCR)\]"
    r"|^#+ ", re.MULTILINE)


def section(text: str, name: str) -> str | None:
    m = _SECTION_START[name].search(text)
    if not m:
        return None
    nxt = None
    for n in _ANY_SECTION.finditer(text, m.end()):
        if n.start() > m.end():
            nxt = n
            break
    end = nxt.start() if nxt else len(text)
    # for a "## heading" or "SECTION X |" banner, cut back to the start of that line
    line_start = text.rfind("\n", 0, end) + 1 if nxt else end
    if nxt and text[line_start:nxt.start()].strip(" =#-0123456789.") == "":
        end = line_start
    return text[m.end():end]


# --------------------------------------------------------------------------
# proof of address
# --------------------------------------------------------------------------
_POA_LABEL = re.compile(
    r"(?:^|(?<=[\n|]))[ \t]*(?:[-*•]\s*|\d+\.\s+)?"
    r"(?:date of letter|letter date|statement date|statement period ending|period ending"
    r"|issue date|date of issue|issued on|issued|bill date|billing date|invoice date|notice date"
    r"|agreement dated|document date|date)\b[ \t]*[:=]?"
    r"|\bdated\b",
    re.IGNORECASE,
)


def find_poa_date(text: str) -> tuple[date | None, str]:
    """Returns (date or None, note)."""
    sec = section(text, "POA")
    if sec is None:
        return None, "no POA section found"
    vals: set[date] = set()
    bad = False
    for m in _POA_LABEL.finditer(sec):
        d = _date_after(sec, m.end(), max_gap=30)
        if isinstance(d, date):
            vals.add(d)
        elif d == "unparseable":
            bad = True
    if len(vals) == 1 and not bad:
        return next(iter(vals)), ""
    if len(vals) > 1:
        return None, "POA date conflict"
    if vals or bad:
        return None, "POA date ambiguous or unparseable"
    # fallback (OCR-garbled label such as "Bill dae", a label broken over two lines): the
    # section holds exactly one date-like token, it parses, and its line is
    # not about something else (due date, period start, birth, expiry)
    toks = list(DATE_RE.finditer(sec))
    if len(toks) == 1:
        d = parse_date_match(toks[0])
        ls = sec.rfind("\n", 0, toks[0].start()) + 1
        line = sec[ls:toks[0].start()].lower()
        if not re.search(r"due|from|start|birth|expir|valid|until|period\s+begin", line):
            if d:
                return d, "fallback: the only date in the POA section"
            return None, "POA date ambiguous or unparseable"
    return None, "no dated label in POA"


# --------------------------------------------------------------------------
# visual-zone expiry (documents without an MRZ only)
# --------------------------------------------------------------------------
_EXPIRY_LABEL = re.compile(r"(?:^|(?<=\n))[ \t]*(?:\d+\.\s+)?(?:date of expiry|expiry date|expires|valid until)"
                           r"(?:\s*/\s*[^:\n]{0,30})?[ \t]*[:=]?", re.IGNORECASE)


def find_visual_expiry(text: str) -> date | None:
    sec = section(text, "ID") or text
    vals = set()
    for m in _EXPIRY_LABEL.finditer(sec):
        d = _date_after(sec, m.end(), max_gap=30)
        if isinstance(d, date):
            vals.add(d)
        elif d == "unparseable":
            return None
    return next(iter(vals)) if len(vals) == 1 else None


# --------------------------------------------------------------------------
# MRZ
# --------------------------------------------------------------------------
_MRZ_LINE = re.compile(r"^[A-Z0-9<«#?]{1}[A-Z0-9<«#? ]*$")  # # and ? = obscured glyphs


def _mrz_candidates(text: str) -> list[list[str]]:
    """Runs of consecutive MRZ-looking lines (each line stripped)."""
    runs, cur = [], []
    for raw in text.splitlines():
        # leading whitespace is layout (an MRZ line never starts with a filler);
        # trailing spaces are kept because OCR may read trailing fillers as spaces
        l = raw.rstrip("\r").strip("`").lstrip()
        if l.strip() and _MRZ_LINE.match(l) and ("<" in l or "«" in l) and len(l.replace(" ", "")) >= 20:
            cur.append(l)
        else:
            if cur:
                runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    return runs


def _fit(run: list[str]) -> tuple[str, list[str]] | None:
    """Fit a run of lines to TD3 (2x44) or TD1 (3x30)."""
    formats = (("TD3", 2, 44), ("TD1", 3, 30))
    # (a) one line per MRZ line; internal spaces kept (misread fillers)
    for fmt, n, width in formats:
        if len(run) == n and all(len(l) == width for l in run):
            return fmt, run
    # (a2) trailing spaces were layout after all
    rs = [l.rstrip() for l in run]
    for fmt, n, width in formats:
        if len(run) == n and all(len(l) == width for l in rs):
            return fmt, rs
    # (b) spaces are layout: drop them per line
    nos = [l.replace(" ", "") for l in run]
    for fmt, n, width in formats:
        if len(run) == n and all(len(l) == width for l in nos):
            return fmt, nos
    # (c) lines split on whitespace into full-width tokens
    toks = " ".join(run).split()
    for fmt, n, width in formats:
        if len(toks) == n and all(len(t) == width for t in toks):
            return fmt, toks
    # (d) broken lines: the whitespace-free concatenation splits evenly
    joined = "".join(nos)
    hits = [(fmt, [joined[i * width:(i + 1) * width] for i in range(n)])
            for fmt, n, width in formats if len(joined) == n * width]
    # only for genuinely broken lines with no space / filler-misread ambiguity
    if len(hits) == 1 and len(run) > len(hits[0][1]) and not any(c in "".join(run) for c in " «"):
        return hits[0]
    return None


def find_mrz(text: str) -> tuple[str, list[str]] | None:
    fits = [f for f in (_fit(r) for r in _mrz_candidates(text)) if f]
    if len(fits) != 1:
        return None
    return fits[0]


# MRZ by shape, anywhere: whitespace-separated runs of MRZ glyph tokens that hold "<",
# joined; a run whose length is exactly 2x44 / 3x30 (one line per token, or glued) is a
# candidate, and only its own check digits (as read or after glyph repair) confirm it
_MRZ_TOKEN = re.compile(r"(?<![^\s:=|;,(\[])[A-Z0-9<«]{5,}(?![^\s|;,)\].])")
_MRZ_LOOK = re.compile(r"[A-Z0-9«<]{0,44}<<[A-Z0-9«<]{0,44}")


def _shape_groups(text: str) -> list[list[str]]:
    groups, cur, last = [], [], None
    for m in _MRZ_TOKEN.finditer(text):
        tok = m.group(0)
        if "<" not in tok and "«" not in tok and not (cur and len(tok) >= 20):
            if cur:
                groups.append(cur)
            cur, last = [], None
            continue
        if cur and text[last:m.start()].strip():
            groups.append(cur)
            cur = []
        cur.append(tok)
        last = m.end()
    if cur:
        groups.append(cur)
    return groups


def find_mrz_shape(text: str) -> tuple[str, list[str]] | None:
    """An MRZ found by shape alone, returned only when its check digits confirm it."""
    fits = []
    for g in _shape_groups(text):
        joined = "".join(g)
        for fmt, n, width in (("TD3", 2, 44), ("TD1", 3, 30)):
            if len(joined) == n * width:
                fits.append((fmt, [joined[i * width:(i + 1) * width] for i in range(n)]))
    if len(fits) != 1 or M is None:
        return None
    fmt, lines = fits[0]
    try:
        status = O.explain_mrz(lines, fmt, None)
    except Exception:
        return None
    return (fmt, lines) if status in ("valid", "ocr_repairable") else None


def has_mrz_text(text: str) -> bool:
    """Any MRZ-looking text at all (then a document is never treated as MRZ-less)."""
    return bool(_mrz_candidates(text)) or any(len(m.group(0)) >= 12 for m in _MRZ_LOOK.finditer(text))


_CHECK_NAMES = (("doc_number", "document number"), ("birth_date", "date of birth"),
                ("expiry_date", "expiry"), ("composite", "composite"))

# (line, start, end) spans each check covers, check digit included
_SPANS = {
    "TD3": {"doc_number": [(1, 0, 10)], "birth_date": [(1, 13, 20)], "expiry_date": [(1, 21, 28)],
            "composite": [(1, 0, 10), (1, 13, 20), (1, 21, 44)]},
    "TD1": {"doc_number": [(0, 5, 15)], "birth_date": [(1, 0, 7)], "expiry_date": [(1, 8, 15)],
            "composite": [(0, 5, 30), (1, 0, 7), (1, 8, 15), (1, 18, 30)]},
}
_MRZ_OK = re.compile(r"^[A-Z0-9<]*$")


def _readable(lines: list[str], fmt: str, key: str) -> bool:
    return all(_MRZ_OK.match(lines[li][a:b]) for li, a, b in _SPANS[fmt][key])


def _parse(lines: list[str], fmt: str, today: date | None):
    return M.parse_td3(lines, today) if fmt == "TD3" else M.parse_td1(lines, today)


def mrz_checks(fmt: str, lines: list[str], today: date | None) -> dict:
    raw = _parse(lines, fmt, today)
    rep_lines = O.repair_mrz(lines, fmt)
    rep = _parse(rep_lines, fmt, today)
    status = O.explain_mrz(lines, fmt, today)
    out = {"format": fmt, "lines": lines, "status": status,
           "checks": {k: bool(raw.checks.get(k)) for k, _ in _CHECK_NAMES},
           "readable": {k: _readable(rep_lines, fmt, k) for k, _ in _CHECK_NAMES},
           "checks_repaired": None, "expiry": None, "expiry_source": None}
    if status != "valid":
        out["checks_repaired"] = {k: bool(rep.checks.get(k)) for k, _ in _CHECK_NAMES}
    # expiry: only when its own check digit passes (as read, else after repair)
    exp_s = None
    if raw.checks.get("expiry_date") and raw.fields:
        exp_s = raw.fields.expiry_date
        out["expiry_source"] = "MRZ"
    elif rep.checks.get("expiry_date") and rep.fields:
        exp_s = rep.fields.expiry_date
        out["expiry_source"] = "MRZ after OCR repair"
    out["expiry"] = exp_s
    return out


# --------------------------------------------------------------------------
# document integrity (policy_v1 §3): visual zone vs MRZ, per field
# --------------------------------------------------------------------------
# §3 lists, verbatim: glyphs O/0 D/0 Q/0 I/1 L/1 S/5 B/8 Z/2 G/6 A/4 T/7 (the MRZ
# repair itself is step1 ``repair_mrz``); look-alike digit pairs 3/8 1/7 5/6 0/8 9/8 4/1
GLYPHS = str.maketrans({"O": "0", "D": "0", "Q": "0", "I": "1", "L": "1", "S": "5",
                        "B": "8", "Z": "2", "G": "6", "A": "4", "T": "7"})
DIGIT_PAIRS = frozenset(frozenset(p) for p in ("38", "17", "56", "08", "98", "41"))

INTEGRITY_FIELDS = (("birth_date", "Date of birth"), ("doc_number", "Document number"),
                    ("expiry_date", "Expiry"))
# per-field classes (integrity_overall folds them into the overall line)
CONSISTENT, NOISE, AMBIGUOUS, TAMPER, UNREADABLE, NO_MRZ = (
    "consistent", "noise", "ambiguous", "tamper", "unreadable", "no_mrz")

# visual-zone labels as the ID scan prints them (English, optional French after " / ")
_VIZ_LABELS = {
    "birth_date": ["date of birth", "date of birth / date de naissance"],
    "issue_date": ["date of issue", "date of issue / date de delivrance"],
    "expiry_date": ["date of expiry", "date of expiry / date d'expiration"],
    "doc_number": ["passport no.", "card no.", "licence no."],
    # the other ID lines, so a noisy label is never mistaken for one of ours
    "_other": ["surname", "surname / nom", "given names", "given names / prenoms", "nationality",
               "nationality / nationalite", "sex", "sex / sexe", "place of birth",
               "place of birth / lieu de naissance", "authority", "authority / autorite",
               "issuing state", "issuing state / etat emetteur"],
}
_ILLEGIBLE = re.compile(r"(?:\[illegible\]|\[smudged\]|▒[▒ ]*|--|\?\?[? ]*)\s*$")
_DOCNUM = re.compile(r"(?<![^\s:=])([A-Z0-9]{5,12})\s*$")


def _label_kind(label: str) -> str | None:
    """Which ID line a (possibly OCR-noisy) label is; None unless clearly one."""
    from difflib import SequenceMatcher
    lab = re.sub(r"\s+", " ", label.strip(" :=\t").lower())
    if not lab:
        return None
    scores = sorted(((max(SequenceMatcher(None, lab, n).ratio() for n in names), kind)
                     for kind, names in _VIZ_LABELS.items()), reverse=True)
    (best, kind), (second, _) = scores[0], scores[1]
    return kind if best >= 0.8 and best - second >= 0.1 else None


def _numeric_order(sec: str) -> str | None:
    """"DMY" or "MDY" when the section's own numeric dates prove the order (one
    document prints all its dates one way): some date has a first part > 12 and
    none a second part > 12, or the reverse. None when nothing proves it."""
    dmy = mdy = False
    for m in DATE_RE.finditer(sec):
        if m.group("dmy"):
            a, b = int(m.group("dd")), int(m.group("dm"))
            dmy |= a > 12 >= b
            mdy |= b > 12 >= a
    return "DMY" if dmy and not mdy else "MDY" if mdy and not dmy else None


def _date_candidates(s: str, order: str | None = None) -> set[date] | None:
    """Every date the printed text can mean: one, or two for a numeric date with
    day and month both <= 12 whose order the document does not prove. None
    when it is not one date."""
    m = DATE_RE.fullmatch(s.strip())
    if not m:
        return None
    if m.group("dmy"):
        a, b, y = int(m.group("dd")), int(m.group("dm")), int(m.group("dy"))
        reads = {"DMY": [(b, a)], "MDY": [(a, b)]}.get(order, [(b, a), (a, b)])
        return {d for d in (_mk(y, mo, dd) for mo, dd in reads) if d} or None
    d = parse_date_match(m)
    return {d} if d else None


def find_viz_fields(text: str, mark_conflicts: bool = False) -> dict:
    """{kind: value} read from the ID visual zone. A date is a set of candidate
    dates, a document number a string, an illegible value the string
    "illegible". A kind that is missing, repeated or unparseable is None (n/d)."""
    keys = ("birth_date", "issue_date", "expiry_date", "doc_number")
    out: dict = {k: None for k in keys}
    sec = section(text, "ID")
    if sec is None:
        return out
    seen: dict[str, list] = {k: [] for k in keys}
    order = _numeric_order(sec)
    pending = None      # the previous line when it held no value (OCR broke a label line)
    for line in sec.split("\n"):
        line = line.rstrip()
        if not line.strip():
            continue
        ill = _ILLEGIBLE.search(line)
        dm = None
        for m in DATE_RE.finditer(line):
            if line[m.end():].strip() == "":
                dm = m
        dn = _DOCNUM.search(line)
        if ill:
            label, val = line[:ill.start()], "illegible"
        elif dm:
            label, val = line[:dm.start()], _date_candidates(dm.group(0), order)
        elif dn:
            label, val = line[:dn.start()], dn.group(1)
        else:
            pending = line
            continue
        kind = _label_kind(label)
        if kind is None and pending is not None:
            kind = _label_kind(pending + " " + label)
        pending = None
        if kind in seen:
            seen[kind].append(val)
    for k, vals in seen.items():
        if mark_conflicts and len(vals) > 1 and any(v != vals[0] for v in vals):
            out[k] = CONFLICT
            continue
        if len(vals) != 1 or vals[0] is None:
            continue
        v = vals[0]
        if v == "illegible" or (isinstance(v, set) if k != "doc_number" else isinstance(v, str)):
            out[k] = v
    return out


def _mrz_value(fmt: str, lines: list[str], fld: str, as_of: date) -> tuple:
    """(value or None when the MRZ field cannot be read, check ok, glyph repair
    changed the field, as-repaired text). Same reading as project._mrz_field."""
    rep = O.repair_mrz(lines, fmt)
    li, a, b = O._field_span(fmt, fld)
    if len(rep[li]) <= b:
        return None, False, False, None
    s, cd = rep[li][a:b], rep[li][b]
    if any(c in s for c in "?#") or cd in "?#":
        return None, False, False, None
    ok = M.is_valid_check(s, cd)
    repaired = lines[li][a:b + 1] != rep[li][a:b + 1]
    if fld == "doc_number":
        return s.rstrip("<"), ok, repaired, s.rstrip("<")
    d = M.parse_date(s, kind="birth" if fld == "birth_date" else "expiry", today=as_of)
    return d, ok, repaired, s


def _one_pair(a: str, b: str) -> bool:
    """Exactly one position differs, by a §3 look-alike digit pair."""
    if len(a) != len(b):
        return False
    diff = [(x, y) for x, y in zip(a, b) if x != y]
    return len(diff) == 1 and frozenset(diff[0]) in DIGIT_PAIRS


def _zone_class(fld: str, viz, mz: tuple | None) -> tuple[str, str]:
    """(class, detail) for one field and ONE reading of its visual-zone value
    (a date, a str, or "illegible"), row by row down the §3 table."""
    if mz is None:  # the document has no MRZ
        if viz == "illegible":
            return UNREADABLE, "visual zone illegible, no MRZ"
        return NO_MRZ, "no MRZ, visual zone only"
    mval, ok, repaired, _ = mz
    if viz == "illegible" and mval is None:
        return UNREADABLE, "illegible in the visual zone and in the MRZ"
    if viz == "illegible":
        if ok:
            return CONSISTENT, "visual zone illegible, MRZ check digit OK (MRZ value used)"
        return UNREADABLE, "visual zone illegible, MRZ check digit FAIL"
    if mval is None:
        return UNREADABLE, "MRZ value cannot be read"
    if ok and viz == mval:
        if repaired:
            return NOISE, "equal after OCR glyph repair, check digit OK after repair"
        return CONSISTENT, "equal, check digit OK"
    if ok and fld == "doc_number" and viz.upper().translate(GLYPHS) == mval.upper().translate(GLYPHS):
        return NOISE, "equal up to OCR look-alike glyphs, check digit OK"
    if ok:
        return TAMPER, "zones differ, MRZ check digit OK (MRZ valid, visual zone differs)"
    if viz == mval:
        return TAMPER, "same value in both zones, check digit FAIL, no glyph repair fixes it"
    v, m = (viz, mval) if fld == "doc_number" else (viz.strftime("%y%m%d"), mval.strftime("%y%m%d"))
    if _one_pair(v, m):
        return AMBIGUOUS, "one look-alike digit pair, check digit FAIL"
    return TAMPER, "zones differ beyond one look-alike digit pair, check digit FAIL"


APP_ASOF_DAYS = 30   # consistency rule: as-of lies within 30 days of the application date


def integrity_checks(text: str, as_of: date | None, mrz: tuple[str, list[str]] | None,
                     has_mrz_text: bool, viz: dict | None = None, app: date | None = None) -> dict:
    """Per-field §3 class (None = n/d) with its detail, §2.2 step 2 impossible
    dates on top, and the overall class (see integrity_overall).

    The document number needs no date. The date fields need a bound on the as-of
    date (MRZ century, "birth after as-of"): the as-of date itself, else the
    application date +- APP_ASOF_DAYS; with neither, the date fields are n/d."""
    fields = {f: None for f, _ in INTEGRITY_FIELDS}
    out = {"fields": fields, "overall": None}
    # MRZ-looking text that does not fit is n/d
    if M is None or (has_mrz_text and mrz is None):
        return out
    from datetime import timedelta
    if as_of is not None:
        lo = hi = as_of
    elif app is not None:
        lo, hi = app - timedelta(days=APP_ASOF_DAYS), app + timedelta(days=APP_ASOF_DAYS)
    else:
        lo = hi = None
    if viz is None:
        viz = find_viz_fields(text)
    used: dict[str, set] = {}       # value(s) the §2.2 step 2 check uses, per date field
    for fld, _ in INTEGRITY_FIELDS:
        v = viz.get(fld)
        if v is None or (fld != "doc_number" and lo is None):
            continue
        try:
            ref = hi or date.today()     # doc_number: the date plays no part
            mz = _mrz_value(mrz[0], mrz[1], fld, ref) if mrz else None
            if mz and lo != hi and _mrz_value(mrz[0], mrz[1], fld, lo)[0] != mz[0]:
                continue                 # the MRZ century depends on where as-of lies in the bound
        except Exception:
            continue
        readings = sorted(v) if isinstance(v, set) else [v]
        classes = {_zone_class(fld, r, mz) for r in readings}
        if len(classes) != 1:       # an ambiguous D.M.Y whose two readings classify differently
            continue
        cls, detail = classes.pop()
        if fld == "doc_number" or v == "illegible":
            shown = v
        else:
            shown = "/".join(r.isoformat() for r in readings)
        fields[fld] = {"class": cls, "detail": detail, "viz": shown,
                       "mrz": (mz[3] if mz[3] is not None else "unreadable") if mz else None}
        if fld != "doc_number" and cls in (CONSISTENT, NOISE, NO_MRZ):
            used[fld] = {mz[0]} if v == "illegible" else set(readings)

    # §2.2 step 2, in project._impossible's order: expiry before issue, else birth after issue / as-of
    issue = viz.get("issue_date") if isinstance(viz.get("issue_date"), set) else None
    # expiry state: "impossible", "fine" (checked, possible or not a candidate), or None (unknown)
    exp_state = "fine"
    if "expiry_date" in used:
        exp = used["expiry_date"]
        if issue is not None and all(e < i for e in exp for i in issue):
            exp_state = "impossible"
            fields["expiry_date"] = {**fields["expiry_date"], "class": TAMPER,
                                     "detail": "impossible date: expiry before the issue date"}
        elif issue is None or any(e < i for e in exp for i in issue):
            exp_state, fields["expiry_date"] = None, None
    elif fields["expiry_date"] is None:
        exp_state = None            # expiry n/d: it might have carried the impossible date
    if "birth_date" in used and exp_state != "impossible":   # project flags one field only
        dob = used["birth_date"]
        # impossible only when EVERY reading of birth and issue date makes it so (an
        # issue date with several readings, e.g. a 2-digit year, must not make a tamper)
        bad = [d > hi or (issue is not None and all(d > i for i in issue)) for d in dob]
        good = [d <= lo and issue is not None and all(d <= i for i in issue) for d in dob]
        if all(bad) and exp_state == "fine":
            fields["birth_date"] = {**fields["birth_date"], "class": TAMPER,
                                    "detail": "impossible date: birth after the issue or as-of date"}
        elif not all(good):
            fields["birth_date"] = None
    out["overall"] = integrity_overall(fields)
    return out


def integrity_overall(fields: dict) -> str | None:
    """clear tamper (any field) > n/d (any field undetermined) > ambiguous >
    noise only > consistent. An unreadable field is missing evidence, not an
    integrity finding, so it does not change the overall class."""
    cls = [None if f is None else f["class"] for f in fields.values()]
    if TAMPER in cls:
        return "clear tamper"
    if None in cls:
        return None
    if AMBIGUOUS in cls:
        return "ambiguous"
    if NOISE in cls:
        return "noise only"
    return "consistent"


_CLASS_TEXT = {CONSISTENT: "CONSISTENT", NOISE: "READABLE OCR NOISE (repaired, consistent)",
               AMBIGUOUS: "AMBIGUOUS (OCR or tamper)", TAMPER: "CLEAR TAMPER",
               UNREADABLE: "UNREADABLE (missing evidence)", NO_MRZ: "SINGLE SOURCE (no MRZ)"}


def format_integrity(integ: dict | None) -> list[str]:
    nd = "n/d"
    lines = []
    fields = (integ or {}).get("fields") or {}
    for fld, label in INTEGRITY_FIELDS:
        f = fields.get(fld)
        if not f:
            lines.append(f"- {label}: {nd}")
            continue
        zones = f"visual zone {f['viz']}" + (f" vs MRZ {f['mrz']}" if f["mrz"] is not None else "")
        lines.append(f"- {label}: {zones}, {f['detail']} -> {_CLASS_TEXT[f['class']]}")
    lines.append(f"- Document integrity (policy §3): {(integ or {}).get('overall') or nd}")
    return lines


# ==========================================================================
# reader v3: layout-free readers that vote with the v2 label reader above
# (Session P3, SUNDAY_READER_V3). The calculators (check digits, day counts,
# §3 table) are unchanged; only how values are FOUND changes.
#
#   reader 1  the v2 label reader (find_as_of / find_poa_date / find_viz_fields)
#   reader 2  anchor reader: MRZ values matched against the whole ID part
#   reader 3  cue-window reader: every date anywhere (one universal date
#             reader), its role from the nearest cue words, inside the packet
#             part (ID / proof of address / ...) located by cue words
#
# A value is output only when the readers that found one agree; any
# disagreement is n/d. Consistency rules only drop impossible readings of a
# date that has two (day/month order, 2-digit year century).
# ==========================================================================
CONFLICT = "conflict"   # a reader saw competing values: a veto in the vote, never a value

_MON2 = r"(?:" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")"
DATE2_RE = re.compile(
    r"(?<![\w])(?<!\d[./\-])(?:"
    r"(?P<ymd>(?P<ay>(?:19|20)\d{2})(?P<as>[./\-])(?P<am>\d{1,2})(?P=as)(?P<ad>\d{1,2}))"
    r"|(?P<num>(?P<b1>\d{1,2})(?P<bs>[./\-])(?P<b2>\d{1,2})(?P=bs)(?P<by>\d{4}|\d{2}))"
    r"|(?P<dmon>(?P<cd>\d{1,2})(?:st|nd|rd|th)?(?:\s+of)?[\s\-/.]{1,3}(?P<cm>" + _MON2 + r")\.?,?[\s\-/.]{1,3}"
    r"(?P<cy>\d{4}|'?\d{2}))"
    r"|(?P<mond>(?P<dm>" + _MON2 + r")\.?[\s\-/.]{1,3}(?P<dd>\d{1,2})(?:st|nd|rd|th)?,?[\s\-/.]{1,3}(?P<dy>\d{4}))"
    r"|(?P<compact>(?P<ey>(?:19|20)\d{2})(?P<em>[01]\d)(?P<ed>[0-3]\d))"
    r")(?![\w])(?![./\-]\d)",
    re.IGNORECASE,
)


def _years(s: str) -> list[int]:
    s = s.lstrip("'")
    return [int(s)] if len(s) == 4 else [1900 + int(s), 2000 + int(s)]


def date2_candidates(m: re.Match, order: str | None = None) -> frozenset:
    """Every date one DATE2_RE match can mean: one, or several when the day/month
    order or the century is not proven. Empty = date-shaped but invalid."""
    out = []
    if m.group("ymd"):
        out = [_mk(int(m.group("ay")), int(m.group("am")), int(m.group("ad")))]
    elif m.group("num"):
        a, b = int(m.group("b1")), int(m.group("b2"))
        reads = [(b, a)] if a > 12 else [(a, b)] if b > 12 else (
            {"DMY": [(b, a)], "MDY": [(a, b)]}.get(order, [(b, a), (a, b)]))
        out = [_mk(y, mo, d) for y in _years(m.group("by")) for mo, d in reads]
    elif m.group("dmon"):
        out = [_mk(y, _MONTHS[m.group("cm").lower()], int(m.group("cd"))) for y in _years(m.group("cy"))]
    elif m.group("mond"):
        out = [_mk(int(m.group("dy")), _MONTHS[m.group("dm").lower()], int(m.group("dd")))]
    elif m.group("compact"):
        out = [_mk(int(m.group("ey")), int(m.group("em")), int(m.group("ed")))]
    return frozenset(d for d in out if d)


def all_dates(text: str) -> list[tuple[int, int, re.Match]]:
    return [(m.start(), m.end(), m) for m in DATE2_RE.finditer(text)]


def numeric_order(text: str) -> str | None:
    """DMY / MDY when the text's own numeric dates prove the order, else None."""
    dmy = mdy = False
    for m in DATE2_RE.finditer(text):
        if m.group("num"):
            a, b = int(m.group("b1")), int(m.group("b2"))
            dmy |= a > 12 >= b
            mdy |= b > 12 >= a
    return "DMY" if dmy and not mdy else "MDY" if mdy and not dmy else None


# -- flat text: MRZ lines out, all whitespace one space (layout no longer matters)
def _is_mrz_line(l: str) -> bool:
    return bool(l and _MRZ_LINE.match(l) and ("<" in l or "«" in l) and len(l.replace(" ", "")) >= 20)


_MRZ_TAG = re.compile(r"^[\W_]*(?:\(?\s*(?:machine.readable zone|mrz)[^\n]{0,30})$", re.I)


_BREAKS: dict[str, frozenset] = {}   # flat text -> offsets where a source line started


def flatten(text: str) -> str:
    """MRZ lines (and a bare "MRZ" tag line right before them) out, every run of
    whitespace one space: layout no longer matters to the readers below. Where the
    source lines started is remembered (``line_breaks``) for the cue-to-date rule."""
    lines = [raw.strip().strip("`") for raw in text.split("\n")]
    drop = [_is_mrz_line(l) for l in lines]
    for i in range(len(lines) - 1):
        if not drop[i] and drop[i + 1] and len(lines[i]) <= 40 and _MRZ_TAG.match(lines[i]):
            drop[i] = True
    out, starts, pos = [], [], 0
    for l, d in zip(lines, drop):
        if d:
            continue
        l = _MRZ_TOKEN.sub(lambda m: " " if ("<" in m.group(0) or "«" in m.group(0)) and len(m.group(0)) >= 20
                           else m.group(0), l)
        l = re.sub(r"\s+", " ", l).strip()
        if not l:
            continue
        if out:
            pos += 1
            starts.append(pos)
        out.append(l)
        pos += len(l)
    flat = " ".join(out)
    if len(_BREAKS) > 256:
        _BREAKS.clear()
    _BREAKS[flat] = frozenset(starts)
    return flat


def line_breaks(flat: str) -> frozenset:
    return _BREAKS.get(flat, frozenset())


# -- packet parts by cue words (tags are case-sensitive, words are not)
_DOC_NOUN = r"(?:bill|statement|invoice|letter|notice|agreement|contract|certificate)"
_PART_CUES = [
    ("CTX", r"\bCTX\b", 0), ("APP", r"\bAPP\b", 0), ("ID", r"\bID\b", 0), ("ID", r"\bMRZ\b", 0),
    ("POA", r"\bPOA\b", 0), ("SCR", r"\bSCR\b", 0),
    ("CTX", r"case reference|onboarding country|case context", re.I),
    ("APP", r"application form|applicant (?:profile|details|name)|customer details|occupation|employer"
            r"|source of funds|expected monthly|expected account", re.I),
    ("ID", r"passport|passeport|pasaporte|identity card|identity document|id card|carte d.identit|driving licen[cs]e"
           r"|driver.?s licen[cs]e|residence permit|issuing state|machine.readable", re.I),
    # proof of address: the spec's cue words, else any "<word(s)> <document noun>" ("... bill",
    # "... statement", "... letter", ...) - a pattern, not a list of document kinds
    ("POA", r"proof of address|utility|council tax|statement of account"
            r"|\b[^\W\d_]+(?:\s+[^\W\d_]+)?\s+" + _DOC_NOUN + r"s?\b"
            r"|\b" + _DOC_NOUN + r"\s+(?:date|dated|period)", re.I),
    ("SCR", r"screening|watch ?list|match score|listed name|candidate hit|\bhits?\b", re.I),
]
_PART_RE = [(k, re.compile(p, f)) for k, p, f in _PART_CUES]


@functools.lru_cache(maxsize=64)
def parts(flat: str) -> list[tuple[int, int, str]]:
    """(start, end, kind) spans: each cue opens a part that runs to the next cue of another kind."""
    cues = sorted((m.start(), k) for k, r in _PART_RE for m in r.finditer(flat))
    out: list[list] = []
    for pos, k in cues:
        if out and out[-1][2] == k:
            continue
        if out:
            out[-1][1] = pos
        out.append([pos, len(flat), k])
    return tuple(tuple(p) for p in out)


def part_of(spans, pos: int) -> str | None:
    for a, b, k in spans:
        if a <= pos < b:
            return k
    return None


# -- field cues: the role of a date is the nearest cue before it
_FIELD_CUES = [
    ("other", r"place of birth|lieu de naissance|listed dob|listed date|birth place|country of birth"),
    ("dob", r"date of birth|birth ?date|\bd\.?o\.?b\b|\bborn\b|date de naissance|naissance|fecha de nacimiento"
            r"|\bbirth\b"),
    ("issue", r"date of issue|issue date|date issued|issued on|issued|d[eé]livrance|\bissue\b"),
    ("expiry", r"date of expiry|expiry date|expir\w*|valid until|valid thru|valid to|expires"),
    ("asof", r"as[\s\-]of[\s\-]date|as[\s\-]of|assessed|assessment date|date of assessment|review date|reviewed on"),
    ("appdate", r"application date|date of application|applied on|received on|submitted on|application received"),
    ("poa", r"\b" + _DOC_NOUN + r"\s+(?:date|dated|issued(?:\s+on)?)|date\s+of\s+(?:the\s+)?" + _DOC_NOUN
            + r"|billing date|period ending|document date|dated"),
    ("date", r"\bdate\b"),
    ("neg", r"\bdue\b|\bfrom\b|period start|\bbegin|\buntil\b|printed|generated|scanned|received|\bopened\b"
            r"|last updated|\bpage\b|\bsince\b|\bto\b"),
]
# cue words are matched with OCR look-alikes folded (l / I / 1 / | -> i, 0 -> o, 5 -> s) in the
# text AND the patterns, so "lssued", "Issued", "1ssued" all read the same
_FIELD_RE = re.compile("|".join(f"(?P<{k}{i}>{p.replace('l', 'i')})" for i, (k, p) in enumerate(_FIELD_CUES)), re.I)
_CUE_GAP = 32


# OCR look-alikes folded for cue search only (same length, so positions hold)
_CUE_FOLD = str.maketrans("0156|lIL", "oissiiii")


@functools.lru_cache(maxsize=64)
def _cue_hits(flat: str):
    return tuple((m.start(), m.end(), next(k for k, v in m.groupdict().items() if v).rstrip("0123456789"))
                 for m in _FIELD_RE.finditer(flat.translate(_CUE_FOLD)))


def _label_gap(gap: str) -> bool:
    """Text between a cue and its date holds no value of its own: the date sits in
    the cue's own clause (no field / sentence boundary - ``: = | ;`` or a full stop -
    followed by words in between), no digits, at most 5 words."""
    if re.search(r"\d", gap) or len(re.findall(r"[^\W\d_]+", gap)) > 5:
        return False
    return not re.search(r"(?:[:=|;]|\.\s)\W*[^\W\d_]", gap)


def _same_line_or_bare(flat: str, ce: int, s: int, brk: frozenset) -> bool:
    """A cue labels a date on a later source line only when nothing but separators
    sits between them (a label broken over lines); otherwise the date belongs to
    whatever precedes it on its own line, and the cue's line has its own value."""
    if not any(ce < b <= s for b in brk):
        return True
    return not re.search(r"[^\W_]", flat[ce:s])


@functools.lru_cache(maxsize=64)
def _role_dates(flat: str) -> tuple:
    return tuple(_role_dates_uncached(flat))


def role_dates(flat: str) -> list[dict]:
    return list(_role_dates(flat))


def _role_dates_uncached(flat: str) -> list[dict]:
    """Every date in the flat text with the role of its nearest cue (or None)."""
    cues = _cue_hits(flat)
    dates = all_dates(flat)
    spans = parts(flat)
    out = []
    prev_end = 0
    for s, e, m in dates:
        role = None
        # nearest cue before the date (no other date in between); a bare "date" yields
        # to a specific cue in the same window ("Date of birth / Date de naissace")
        brk = line_breaks(flat)
        near = [k for cs, ce, k in cues if prev_end < ce <= s and s - ce <= _CUE_GAP and _label_gap(flat[ce:s])
                and _same_line_or_bare(flat, ce, s, brk)]
        if near:
            spec = [k for k in near if k != "date"]
            role = spec[-1] if spec else "date"
        elif USE_POST_CUE:
            role = _post_cue(flat, e, cues, dates, brk)
        out.append({"start": s, "end": e, "m": m, "role": role, "part": part_of(spans, s)})
        prev_end = e
    return out


# On F-heldout it lifts as-of 0 -> 25-28%. Its 1-3 wrong values were an ambiguous numeric as-of
# taking its day/month order from another document: order is now proven only within the part.
USE_POST_CUE = True     # back on with part-local day/month order (F's held-out class)
_POST_ROLES = ("asof", "appdate")


def _post_cue(flat: str, e: int, cues, dates, brk) -> str | None:
    """A case-level cue (as-of / application date) written AFTER its date: "05.08.2026
    (assessment date)". Same line, only brackets / dashes / commas and <= 2 short words
    in between, and the cue does not itself label the next date."""
    for cs, ce, k in cues:
        if cs < e:
            continue
        gap = flat[e:cs]
        if len(gap) > 20 or re.search(r"[\d:=|;]", gap) or any(e < b <= cs for b in brk) \
                or len(re.findall(r"[^\W\d_]+", gap)) > 2 or any(len(w) > 4 for w in re.findall(r"[^\W\d_]+", gap)):
            return None
        if k not in _POST_ROLES:
            return None
        nxt = next((ds for ds, _, _ in dates if ds >= ce), None)
        if nxt is not None and nxt - ce <= _CUE_GAP and _label_gap(flat[ce:nxt]) and _same_line_or_bare(flat, ce, nxt, brk):
            return None             # the cue labels the date after it
        return k
    return None


def _resolve(cands: set, ok) -> frozenset:
    """Consistency rules only break ties: keep the readings ``ok`` allows when that leaves one."""
    if len(cands) <= 1:
        return frozenset(cands)
    kept = frozenset(d for d in cands if ok(d))
    return kept if len(kept) == 1 else frozenset(cands)


def _one(values: list[frozenset]):
    """The single reading all hits share; None when there is none; CONFLICT when hits
    disagree or one is date-shaped but invalid."""
    if not values:
        return None
    if any(not v for v in values):
        return CONFLICT
    first = values[0]
    return first if all(v == first for v in values) else CONFLICT


def _local_order(flat: str, pos: int) -> str | None:
    """Day/month order proven by the part (document) the date at ``pos`` sits in, never
    by another document of the packet."""
    for a, b, _ in parts(flat):
        if a <= pos < b:
            return numeric_order(flat[a:b])
    spans = parts(flat)
    return numeric_order(flat[:spans[0][0]] if spans else flat)


def _case_dates(flat: str, role: str) -> list:
    return [date2_candidates(r["m"], _local_order(flat, r["start"])) for r in role_dates(flat) if r["role"] == role]


def cue_as_of(flat: str) -> date | None:
    """As-of date from its cues. Day/month order only from the as-of's own part; the
    application date (+-30 days) breaks a remaining tie; still ambiguous -> n/d."""
    v = _one(_case_dates(flat, "asof"))
    if v is None or v == CONFLICT:
        return v
    appd = _one(_case_dates(flat, "appdate"))
    if len(v) > 1 and appd not in (None, CONFLICT):
        v = _resolve(v, lambda d: any(abs((d - a).days) <= APP_ASOF_DAYS for a in appd))
    return next(iter(v)) if len(v) == 1 else None


def poa_part_dates(flat: str, as_of: date | None) -> set | None:
    """The readings of the ONLY date in the cue-located PoA part(s) (roles that name
    another kind of date excluded from 'only'), else None."""
    rd = [r for r in role_dates(flat) if r["part"] == "POA"]
    if len(rd) != 1 or rd[0]["role"] in ("dob", "expiry", "asof", "appdate", "other", "neg"):
        return None
    # an uncued date never beats a cued one: any PoA-type cued date elsewhere (outside the
    # identity document) means the PoA document's own date may sit outside the found part
    if rd[0]["role"] is None and any(r["role"] in ("poa", "date", "issue") and r["part"] != "ID"
                                     and r is not rd[0] for r in role_dates(flat)):
        return None
    return set(date2_candidates(rd[0]["m"], None))


def app_date(flat: str):
    v = _one(_case_dates(flat, "appdate"))
    if v not in (None, CONFLICT) and len(v) > 1:
        asof = _one(_case_dates(flat, "asof"))
        if asof not in (None, CONFLICT):
            v = _resolve(v, lambda d: any(abs((d - a).days) <= APP_ASOF_DAYS for a in asof))
    return next(iter(v)) if v not in (None, CONFLICT) and len(v) == 1 else None


def cue_poa_date(flat: str, as_of: date | None, mrz_dates: frozenset = frozenset()) -> date | None:
    """PoA date: dates whose nearest cue is a PoA date cue, inside proof-of-address parts."""
    rd = [r for r in role_dates(flat) if r["part"] == "POA"]
    if not rd:
        return None
    if any(r["role"] in ("dob", "expiry") for r in rd):
        return CONFLICT     # birth / expiry dates: an identity document runs into this part
    if any(r["role"] == "issue" for r in rd) and not any(
            r["role"] == "issue" and r["part"] == "ID" for r in role_dates(flat)):
        return CONFLICT     # an issue date the identity document may own (it shows none of its own)
    if mrz_dates and any(date2_candidates(r["m"]) & mrz_dates for r in rd):
        return CONFLICT     # the MRZ's birth / expiry date printed here: identity-document text
    spans = parts(flat)
    poa_text = " ".join(flat[a:b] for a, b, k in spans if k == "POA")
    order = numeric_order(poa_text)
    if any(r["role"] == "date" for r in rd) and not any(r["role"] in ("poa", "issue") for r in rd) and len(rd) > 1:
        return CONFLICT     # a bare "date" cue is weak: it may not pick between several dates
    hits = [date2_candidates(r["m"], order) for r in rd if r["role"] in ("poa", "issue", "date")]
    v = _one(hits)
    if v is None or v == CONFLICT:
        return v
    if as_of is not None:
        v = _resolve(v, lambda d: (as_of - d).days >= -31 and (as_of - d).days <= 3660)
    return next(iter(v)) if len(v) == 1 else None


_ILLEG2 = re.compile(r"^[\s:=\-|\"'“”,]*(?:\[illegible\]|\[smudged\]|▒[▒ ]*|--(?![\w])|\?\?[? ]*)")
_DOCCUE = re.compile((r"(?:passport|card|licen[cs]e|document|permit)\s*(?:no\.?|number|nr\.?|#)"
                      r"|\bdoc(?:ument)? no\b").replace("l", "i"), re.I)     # matched on folded text
_TOKEN = re.compile(r"(?<![\w])([A-Za-z0-9]{5,12})(?![\w])")


def cue_viz_fields(flat: str, order: str | None = "proof") -> dict:
    """Reader 3 for the ID visual zone: {kind: value} like find_viz_fields.
    ``order`` "proof" = the day/month order the ID part itself proves; "DMY" /
    "MDY" force one reading (used only to test which order the MRZ proves)."""
    keys = ("birth_date", "issue_date", "expiry_date", "doc_number")
    out: dict = {k: None for k in keys}
    spans = parts(flat)
    id_parts = [(a, b) for a, b, k in spans if k == "ID"]
    if not id_parts:
        return out
    id_text = " ".join(flat[a:b] for a, b in id_parts)
    if order == "proof":
        order = numeric_order(id_text)
    role_key = {"dob": "birth_date", "issue": "issue_date", "expiry": "expiry_date"}
    seen: dict[str, list] = {k: [] for k in keys}
    for r in role_dates(flat):
        if r["part"] == "ID" and r["role"] in role_key:
            seen[role_key[r["role"]]].append(date2_candidates(r["m"], order))
    # illegible values right after a date cue
    for cs, ce, k in _cue_hits(flat):
        if k in role_key and part_of(spans, cs) == "ID" and _ILLEG2.match(flat[ce:ce + 20]):
            seen[role_key[k]].append("illegible")
    for m in _DOCCUE.finditer(flat.translate(_CUE_FOLD)):
        if part_of(spans, m.start()) != "ID":
            continue
        rest = flat[m.end():m.end() + 24]
        if _ILLEG2.match(rest):
            seen["doc_number"].append("illegible")
            continue
        t = re.match(r"[\s:=\-|.\"'“”‘’,\[\]{}()]*([A-Za-z0-9]{5,12})(?![\w])", rest)
        if t and any(ch.isdigit() for ch in t.group(1)):
            seen["doc_number"].append(t.group(1).upper())
        # a cue with no number-shaped value after it ("passport number on file") reads nothing
    for k, vals in seen.items():
        if not vals:
            continue
        if any(v is None or (isinstance(v, frozenset) and not v) for v in vals):
            out[k] = CONFLICT
        elif all(v == vals[0] for v in vals):
            out[k] = set(vals[0]) if isinstance(vals[0], frozenset) else vals[0]
        else:
            out[k] = CONFLICT
    return out


def mrz_proven_order(flat: str, mrz, as_of) -> dict:
    """{field: "DMY"|"MDY"} when the OTHER MRZ-carrying date of the same document
    matches its MRZ value under exactly one day/month order (and no field points the
    other way). A field never proves its own order, so a tampered field is still
    judged against the order its document uses. -> (orders, readings per order)"""
    if mrz is None or as_of is None or O is None:
        return {}, {}
    by = {o: cue_viz_fields(flat, o) for o in ("DMY", "MDY")}
    match = {}
    for fld in ("birth_date", "expiry_date"):
        try:
            mval = _mrz_value(mrz[0], mrz[1], fld, as_of)[0]
        except Exception:
            mval = None
        if mval is None:
            continue
        d, m = by["DMY"][fld] == {mval}, by["MDY"][fld] == {mval}
        if d != m:
            match[fld] = "DMY" if d else "MDY"
    out = {}
    for fld in ("birth_date", "expiry_date", "issue_date"):
        others = {o for g, o in match.items() if g != fld}
        if len(others) == 1:
            out[fld] = others.pop()
    return out, by


def _non_scr(flat: str) -> list[dict]:
    """Every date except those the text names as screening data (a listed DOB etc. in
    the screening part). Uncued dates in the screening part stay: part boundaries can
    run on past the hits into another document."""
    return [r for r in role_dates(flat) if not (r["part"] == "SCR" and r["role"] == "other")]


_DATEISH = re.compile(r"\d{1,4}\s?[./\-]\s?\d{1,2}\s?[./\-]\s?\d{2,4}|\b\d{6,8}\b|" + _MON2
                      + r"\W{0,3}\d{1,2}\b|\b\d{1,2}(?:st|nd|rd|th)?\W{0,4}" + _MON2, re.I)


def unread_dates(flat: str) -> bool:
    """Is there date-like text the universal reader did not read as a date?"""
    spans = [(a, b) for a, b, _ in all_dates(flat)]
    for m in _DATEISH.finditer(flat):
        if not any(a <= m.start() < b or a < m.end() <= b for a, b in spans):
            tok = m.group(0)
            if re.fullmatch(r"\d{6,8}", tok):
                continue        # plain numbers (references, amounts) are not date-like on their own
            return True
    return False


def _same_shape(t: str, ref: str) -> bool:
    """A token that could be a document number like ``ref`` (same length, letters and
    digits in about the same places)."""
    if len(t) != len(ref) or not any(c.isdigit() for c in t):
        return False
    return sum(a.isdigit() != b.isdigit() for a, b in zip(t, ref)) <= 2


def anchor_viz_fields(flat: str, mrz: tuple[str, list[str]] | None, as_of: date | None,
                      scope: str = "all") -> dict:
    """Reader 2: the MRZ's own values looked up in the whole packet except the
    screening-hits part (and except the application's own DOB, a second source by
    design). {field: (value, exact)}: value when exactly one distinct token is equal
    to the MRZ value up to noise (dates: equal or one look-alike digit pair; document
    number: look-alike glyphs or one pair); exact when printed identically."""
    out: dict = {"birth_date": (None, False), "expiry_date": (None, False), "doc_number": (None, False)}
    if mrz is None or as_of is None or O is None:
        return out
    spans = parts(flat)
    keep = (lambda k: k == "ID") if scope == "id" else (lambda k: k != "SCR")
    text = " ".join(flat[a:b] for a, b, k in spans if keep(k))
    if spans and scope != "id":
        text = flat[:spans[0][0]] + " " + text
    if not text.strip():
        return out
    order = numeric_order(text)
    for fld in ("birth_date", "expiry_date", "doc_number"):
        try:
            mval, ok, _, _ = _mrz_value(mrz[0], mrz[1], fld, as_of)
        except Exception:
            continue
        if mval is None:
            continue
        if fld == "doc_number":
            key = mval.upper().translate(GLYPHS)
            c = {t.upper() for t in _TOKEN.findall(text) if any(ch.isdigit() for ch in t)
                 and (t.upper().translate(GLYPHS) == key or _one_pair(t.upper(), mval))}
            if len(c) == 1:
                v = c.pop()
                out[fld] = (v, v == mval)
            continue
        ms = mval.strftime("%y%m%d")
        c, exact = set(), False
        for r in _non_scr(flat):
            if (scope == "id" and r["part"] != "ID") or (fld == "birth_date" and r["part"] == "APP"
                                                         and r["role"] == "dob"):
                continue
            cs = date2_candidates(r["m"], order)
            for d in cs:
                if d == mval or _one_pair(d.strftime("%y%m%d"), ms):
                    c.add(d)
                    exact |= cs == {mval}
        if len(c) == 1:
            out[fld] = (c, exact)
    return out


# --------------------------------------------------------------------------
# PoA located by content (v3.1): the proof of address must print the applicant's
# address; its number tokens (house number, postcode, box) survive reformatting,
# abbreviation and transliteration. The PoA date is read only in a window around
# such a repeat, by elimination inside that small window.
# --------------------------------------------------------------------------
_NUM_TOK = re.compile(r"(?<![\w.,])\d{2,}(?![\w]|[.,]\d)")
_ADDR_SPAN = 120     # number tokens of one address lie within this many chars
_POA_WINDOW = 300    # the PoA document's own date lies within this many chars of its address
_DATEISH_LOOSE = re.compile(r"[\dOoIlSB]{1,4}\s?[./\-]\s?[\dOoIlSB]{1,2}\s?[./\-]\s?[\dOoIlSB]{2,4}"
                            r"|[\dOoIl]{1,2}(?:st|nd|rd|th)?\W{0,3}" + _MON2 + r"|" + _MON2 + r"\W{0,3}[\dOoIl]{1,2}\b",
                            re.I)


def address_repeats(flat: str) -> list[tuple[int, int]]:
    """(start, end) of every place where >= 2 number tokens recur together (at least one
    of >= 4 digits) that also recur together elsewhere: the applicant's address and its
    copies. Dates, the screening part and MRZ text are not address material."""
    date_spans = [(a, b) for a, b, _ in all_dates(flat)]
    scr = [(a, b) for a, b, k in parts(flat) if k == "SCR"]
    toks = [(m.start(), m.end(), m.group(0)) for m in _NUM_TOK.finditer(flat)
            if not any(a <= m.start() < b for a, b in date_spans + scr)]
    count: dict[str, int] = {}
    for _, _, t in toks:
        count[t] = count.get(t, 0) + 1
    shared = [x for x in toks if count[x[2]] >= 2]
    locs, cur = [], []
    for x in shared:
        if cur and x[0] - cur[-1][1] > _ADDR_SPAN:
            locs.append(cur)
            cur = []
        cur.append(x)
    if cur:
        locs.append(cur)
    out = []
    for loc in locs:
        vals = {t for _, _, t in loc}
        if len(vals) >= 2 and any(len(v) >= 4 for v in vals):
            out.append((loc[0][0], loc[-1][1], frozenset(vals)))
    # keep places whose token set recurs at another place (>= 2 tokens in common)
    keep = [(a, b) for i, (a, b, v) in enumerate(out)
            if any(len(v & w) >= 2 for j, (_, _, w) in enumerate(out) if j != i)]
    return keep


def poa_by_address(flat: str, as_of: date | None, claims: set, mrz_dates: frozenset = frozenset()):
    """PoA date by elimination inside the windows around the address repeats that are
    not the application's own. None when nothing (or several dates) remain, or when
    date-like text in a window could not be read."""
    reps = address_repeats(flat)
    if len(reps) < 2:
        return None
    spans = parts(flat)
    non_app = [(a, b) for a, b in reps if part_of(spans, a) != "APP"]
    if len(non_app) == len(reps) and len(reps) > 2:
        return None                 # application not located and several copies: unclear
    wins = [(max(0, a - _POA_WINDOW), b + _POA_WINDOW) for a, b in (non_app or reps)]
    if len(non_app) == len(reps):
        wins = [(max(0, a - _POA_WINDOW), b + _POA_WINDOW) for a, b in reps]
    dspans = {(a, b) for a, b, _ in all_dates(flat)}
    for wa, wb in wins:
        for m in _DATEISH_LOOSE.finditer(flat, wa, wb):
            if not any(a <= m.start() < b for a, b in dspans):
                return None         # date-like text the reader could not read: it may be the date
    left = []
    for r in role_dates(flat):
        if not any(wa <= r["start"] < wb for wa, wb in wins) or r["part"] == "SCR":
            continue
        cs = date2_candidates(r["m"])
        if not cs:
            return None
        # claimed: a known date, or an OCR copy (one look-alike digit pair) of an MRZ date
        if all(d in claims or any(_one_pair(d.strftime("%y%m%d"), c.strftime("%y%m%d")) for c in mrz_dates)
               for d in cs):
            continue                # every reading is accounted for (one reading is not enough)
        if r["role"] in ("dob", "expiry", "asof", "appdate", "other"):
            continue
        left.append(cs)
    if len(left) != 1 or len(left[0]) != 1:
        return None
    d = next(iter(left[0]))
    if as_of is not None and not (-31 <= (as_of - d).days <= 3 * 366):
        return None
    return d


# PoA by elimination over the whole packet (reader 4) is OFF: a real PoA date the date reader cannot parse
# (OCR-garbled) leaves another date as "the only one left" -> wrong values on train and
# reader_dev (v3.1 gate, seeds 1111/2222/3333). Kept for measurement only.
USE_ELIMINATION = False
# The address-anchored version (elimination only inside the PoA document's window) is OFF
# for the same reason: on F's fresh seeds 4444/5555 9 of 14 of its wrong values were a
# real PoA date garbled past the date reader, leaving one other date "the only one left".
# Elimination fails unsafe under OCR noise; positive identification (cue, MRZ value) fails
# to n/d. Kept for measurement only.
USE_ADDRESS_ELIMINATION = False

_EXPLAINED_ROLES = ("issue", "asof", "appdate", "poa", "other")


def closed_world(flat: str, fld: str, mval, claims: set) -> bool:
    """May the MRZ value of ``fld`` stand for its visual zone without a label? Only
    when every date outside the screening hits is accounted for: equal to the MRZ
    value itself, to a known date (as-of, application, PoA, the other MRZ date), or
    named by a cue as another kind of date. Any unexplained date could be a
    (tampered) visual-zone value -> False."""
    seen_exact = False
    for r in _non_scr(flat):
        cs = date2_candidates(r["m"])
        if not cs:
            return False
        if cs == {mval}:
            seen_exact = True
            continue
        if cs <= claims:
            continue                # every reading is a known date
        if r["role"] in _EXPLAINED_ROLES:
            continue
        return False
    return seen_exact


def closed_world_docnum(flat: str, mval: str) -> bool:
    """Same for the document number: no other token of its shape anywhere outside
    the screening hits (only exact / look-alike copies of the MRZ value)."""
    spans = parts(flat)
    text = " ".join(flat[a:b] for a, b, k in spans if k != "SCR")
    if spans:
        text = flat[:spans[0][0]] + " " + text
    key = mval.upper().translate(GLYPHS)
    toks = {t.upper() for t in _TOKEN.findall(text)}
    exact = [t for t in toks if t.translate(GLYPHS) == key]
    others = [t for t in toks if t.translate(GLYPHS) != key and _same_shape(t, mval)]
    return bool(exact) and not others


def poa_by_elimination(flat: str, as_of: date | None, claims: set):
    """Reader 4 for the PoA date: every date outside the screening hits is claimed
    (MRZ dates and their look-alike copies, as-of / application dates, dates a cue
    names as another kind); if exactly one plausible unclaimed date remains (within
    3 years of as-of) and it is recent (<= 1 year before as-of, <= 31 days after),
    it is the PoA date. A packet with no proof-of-address part gives None."""
    from datetime import timedelta
    if as_of is None or not any(k == "POA" for _, _, k in parts(flat)) or unread_dates(flat):
        return None
    left = []
    for r in _non_scr(flat):
        cs = date2_candidates(r["m"])
        if not cs:
            return None
        if cs & claims or any(_one_pair(d.strftime("%y%m%d"), c.strftime("%y%m%d"))
                              for d in cs for c in claims if c not in (as_of,)):
            continue
        if r["role"] in ("dob", "expiry", "asof", "appdate", "other"):
            continue                # claimed by a cue naming another kind of date (an "issue"
            #                         cue may be the ID's or the PoA's: it never claims)
        if any(abs((d - as_of).days) <= 3 * 366 for d in cs):
            left.append(cs)
    if len(left) != 1:
        return None                 # nothing left, or several dates compete
    recent = {d for d in left[0] if -31 <= (as_of - d).days <= 366}
    if len(recent) != 1 or recent != set(left[0]):
        return None
    return next(iter(recent))


def _agree(*vals):
    """Vote: the value every reader that found one agrees on (a date set may narrow
    to a subset proven by another reader), else None."""
    got = [v for v in vals if v is not None]
    if not got or CONFLICT in got:
        return None
    if all(isinstance(v, set) for v in got):
        small = min(got, key=len)
        return set(small) if all(small <= v for v in got) else None
    return got[0] if all(v == got[0] for v in got) else None


def _closed(flat, k, b, mrz, as_of, claims) -> bool:
    if k == "doc_number":
        return closed_world_docnum(flat, b)
    return closed_world(flat, k, next(iter(b)), set(claims or ()))


def vote_viz_fields(text: str, flat: str, mrz, as_of, claims: set | None = None) -> dict:
    r1 = find_viz_fields(text, mark_conflicts=True)
    r3 = cue_viz_fields(flat)
    r2 = anchor_viz_fields(flat, mrz, as_of, scope="id")       # veto: the ID part, as in v3
    r2all = anchor_viz_fields(flat, mrz, as_of, scope="all")   # fill: the whole packet
    proven = mrz_proven_order(flat, mrz, as_of) if mrz else ({}, {})
    out = {}
    for k in ("birth_date", "issue_date", "expiry_date", "doc_number"):
        a, c = r1.get(k), r3.get(k)
        o = proven[0].get(k)
        if o and isinstance(c, set) and len(c) > 1:
            c = proven[1][o][k]     # the order the document's other MRZ date proves
        v = _agree(a, c)
        b, exact = r2.get(k, (None, False))
        if CONFLICT in (a, c):
            v = None
        elif v is None and a is None and c is None and exact:
            v = b                   # (v3) printed exactly as the MRZ says in the ID part, nothing competes
        elif v is None and a is None and c is None and r2all.get(k, (None, False))[1] and _closed(
                flat, k, r2all[k][0], mrz, as_of, claims):
            v = r2all[k][0]         # (v3.1) same, ID part not found: nothing competes anywhere
        elif v is not None and b is not None and v != "illegible" and _agree(v, b) is None:
            v = None                # another token equal-up-to-noise to the MRZ competes
        out[k] = v
    return out


# --------------------------------------------------------------------------
# main entry points
# --------------------------------------------------------------------------
def run_prechecks(packet: str) -> dict:
    text = packet if isinstance(packet, str) else str(packet)
    text = text.replace("\r\n", "\n")
    flat = flatten(text)
    as_of = _agree(find_as_of(text), cue_as_of(flat))
    app = app_date(flat)
    if as_of is not None and app is not None and abs((as_of - app).days) > APP_ASOF_DAYS:
        as_of = app = None          # consistency: as-of within 30 days of the application date;
        #                             one of the two is misread, so neither bounds anything
    res: dict = {"as_of": as_of, "mrz": None, "expiry": None, "expiry_source": None,
                 "expired": None, "poa_date": None, "poa_days": None, "poa_window": None,
                 "integrity": None, "notes": []}

    found = find_mrz(text) if M is not None else None
    if found is None and M is not None:
        found = find_mrz_shape(text)
    mrz_text = has_mrz_text(text)
    if found:
        fmt, lines = found
        try:
            res["mrz"] = mrz_checks(fmt, lines, as_of)
        except Exception:  # never crash a request on odd text
            res["mrz"] = None
    if res["mrz"]:
        res["expiry"] = res["mrz"]["expiry"]
        res["expiry_source"] = res["mrz"]["expiry_source"]
    elif not mrz_text:
        # no MRZ-looking text at all: fall back to the visual zone
        v = find_visual_expiry(text)
        if v:
            res["expiry"], res["expiry_source"] = v, "visual zone, no MRZ"
    if res["expiry"] and as_of:
        res["expired"] = res["expiry"] < as_of
    poa, note = find_poa_date(text)
    mrz_dates = set()
    if found and as_of:
        for fld in ("birth_date", "expiry_date"):
            try:
                v = _mrz_value(found[0], found[1], fld, as_of)[0]
            except Exception:
                v = None
            if v:
                mrz_dates.add(v)
    poa3 = cue_poa_date(flat, as_of, frozenset(mrz_dates))
    if poa3 == CONFLICT or note == "POA date conflict" or (poa is not None and poa3 is not None and poa != poa3):
        poa, note = None, "POA date readers disagree"
    elif poa is None and poa3 is not None:
        poa, note = poa3, ""
    elif poa is not None and poa3 is None and note.startswith("fallback") and poa_part_dates(flat, as_of) != {poa}:
        poa, note = None, "POA fallback date not confirmed by the cue reader"
    if poa is not None and poa3 is None and note == "":
        # reader 1 alone (label/section based, tuned to the training layouts): accept its value
        # only where the layout-free part map also puts that date in a proof-of-address part
        where = {r["part"] for r in role_dates(flat) if date2_candidates(r["m"]) == {poa}}
        if "POA" not in where:
            poa, note = None, "POA date of the label reader lies outside every PoA part"
    if poa is not None and poa in mrz_dates:
        poa, note = None, "POA date equals an MRZ date (identity-document text)"
    if poa is not None and as_of is not None and not (-31 <= (as_of - poa).days <= 3660):
        poa, note = None, "POA date implausible vs as-of (more than 31 days after or 10 years before)"
    claims = set(mrz_dates) | {d for d in (as_of, app) if d}
    elim = None
    if USE_ELIMINATION:
        elim = poa_by_elimination(flat, as_of, claims)
    elif USE_ADDRESS_ELIMINATION:
        elim = poa_by_address(flat, as_of, claims, frozenset(mrz_dates))
    vetoed = note.startswith(("POA date readers disagree", "POA fallback", "POA date equals", "POA date implausible",
                              "POA date conflict"))
    if elim == CONFLICT or (poa is not None and elim is not None and poa != elim):
        if poa is not None:
            poa, note = None, "POA date readers disagree (elimination)"
    elif poa is None and elim is not None and not vetoed:
        poa, note = elim, ""
    res["poa_date"] = poa
    if note:
        res["notes"].append(note)
    try:
        viz = vote_viz_fields(text, flat, found, as_of or app, claims | ({poa} if poa else set()))
        res["integrity"] = integrity_checks(text, as_of, found, mrz_text, viz, app)
    except Exception:  # never crash a request on odd text
        res["integrity"] = None
    if poa and as_of:
        days = (as_of - poa).days
        res["poa_days"] = days
        if days < 0:
            res["poa_window"] = "DATED AFTER AS-OF"
        elif days <= POA_WINDOW_DAYS:
            res["poa_window"] = "WITHIN 90 DAYS"
        else:
            res["poa_window"] = "OLDER THAN 90 DAYS"
    return res


_STATUS_TEXT = {"valid": "valid", "ocr_repairable": "valid only after OCR glyph repair",
                "invalid": "invalid", "unreadable": "unreadable"}


def format_block(res: dict) -> str:
    nd = "n/d"
    lines = [HEADER]
    as_of = res.get("as_of")
    lines.append(f"- As-of date: {as_of.isoformat() if as_of else nd}")

    mz = res.get("mrz")
    if mz:
        parts = []
        rep = mz.get("checks_repaired")
        for k, label in _CHECK_NAMES:
            ok = mz["checks"][k]
            if not mz.get("readable", {}).get(k, True):
                parts.append(f"{label} check UNREADABLE")
                continue
            s = f"{label} check {'OK' if ok else 'FAIL'}"
            if rep is not None and not ok:
                s += " (OK after OCR repair)" if rep[k] else " (FAIL after OCR repair)"
            parts.append(s)
        parts.append(f"status: {_STATUS_TEXT.get(mz['status'], mz['status'])}")
        lines.append(f"- MRZ ({mz['format']}): " + "; ".join(parts))
    else:
        lines.append(f"- MRZ: {nd}")

    exp = res.get("expiry")
    if exp:
        verdict = nd if res.get("expired") is None else ("EXPIRED" if res["expired"] else "NOT EXPIRED")
        lines.append(f"- Document expiry: {exp.isoformat()} ({res.get('expiry_source')}) -> {verdict}")
    else:
        lines.append(f"- Document expiry: {nd}")

    lines += format_integrity(res.get("integrity"))

    poa = res.get("poa_date")
    if poa and res.get("poa_window"):
        d = res["poa_days"]
        rel = f"{d} days before as-of" if d >= 0 else f"{-d} days after as-of"
        lines.append(f"- Proof-of-address date: {poa.isoformat()} -> {rel} -> {res['poa_window']}")
    elif poa:
        lines.append(f"- Proof-of-address date: {poa.isoformat()} -> {nd}")
    else:
        lines.append(f"- Proof-of-address date: {nd}")
    return "\n".join(lines)


def precheck_block(packet: str) -> str:
    """Convenience: the formatted block for one packet."""
    return format_block(run_prechecks(packet))


# --------------------------------------------------------------------------
# chat messages: the ONE place the block is put into a prompt (training data,
# dev eval and the serving proxy all call this, so the text is byte-identical)
# --------------------------------------------------------------------------
SYSTEM_NOTE = ('A PRE-CHECKS block follows the packet. It is computed by code from the packet text and is '
               'reliable for the arithmetic it reports (as-of date, MRZ check digits, the policy §3 visual-zone '
               'vs MRZ comparison per field and the document-integrity class it gives, document expiry, '
               'proof-of-address age); "n/d" means not determinable, so decide that item from the packet.')
_PACKET_CLOSE = "</packet>"


def _packet_of(user_text: str) -> str:
    """The packet inside <packet>...</packet> (the student user template), else the whole text."""
    a, b = user_text.find("<packet>"), user_text.rfind(_PACKET_CLOSE)
    if a == -1 or b == -1 or b < a:
        return user_text
    inner = user_text[a + len("<packet>"):b]
    if inner.startswith("\n"):
        inner = inner[1:]
    if inner.endswith("\n"):
        inner = inner[:-1]
    return inner


def blank_result() -> dict:
    """A run_prechecks result with every item n/d (training-time fallback rows)."""
    return {"as_of": None, "mrz": None, "expiry": None, "expiry_source": None, "expired": None,
            "poa_date": None, "poa_days": None, "poa_window": None,
            "integrity": {"fields": {f: None for f, _ in INTEGRITY_FIELDS}, "overall": None}, "notes": ["blanked"]}


def apply_prechecks_with_result(messages: list[dict], blank: bool = False) -> tuple[list[dict], dict | None]:
    """-> (new messages, run_prechecks result or None when nothing was added).

    Appends the PRE-CHECKS block after the packet in the LAST user message and
    SYSTEM_NOTE to the system message (a system message holding only the note is
    prepended when there is none). Idempotent: a user message that already holds
    the block is left alone. Non-string user content (content parts) is left alone.
    ``blank`` renders every item as n/d (the block is still present; training only).
    Never mutates the input."""
    msgs = [dict(m) for m in messages]
    ui = next((i for i in range(len(msgs) - 1, -1, -1) if msgs[i].get("role") == "user"), None)
    if ui is None or not isinstance(msgs[ui].get("content"), str) or HEADER in msgs[ui]["content"]:
        return msgs, None
    text = msgs[ui]["content"]
    res = blank_result() if blank else run_prechecks(_packet_of(text))
    msgs[ui]["content"] = text.rstrip("\n") + "\n\n" + format_block(res)
    si = next((i for i, m in enumerate(msgs) if m.get("role") in ("system", "developer")), None)
    if si is None:
        msgs.insert(0, {"role": "system", "content": SYSTEM_NOTE})
    elif isinstance(msgs[si].get("content"), str) and SYSTEM_NOTE not in msgs[si]["content"]:
        msgs[si]["content"] = msgs[si]["content"].rstrip("\n") + "\n\n" + SYSTEM_NOTE
    return msgs, res


def apply_prechecks(messages: list[dict]) -> list[dict]:
    """Messages with the PRE-CHECKS block added (see apply_prechecks_with_result)."""
    return apply_prechecks_with_result(messages)[0]


if __name__ == "__main__":  # pragma: no cover
    import sys
    print(precheck_block(sys.stdin.read()))
