"""ICAO Doc 9303 machine-readable zone (MRZ): build, check, parse.

Supports TD3 (passport booklet, 2 x 44) and TD1 (ID card, 3 x 30).

Check digits (Doc 9303 Part 3, section 4.9): characters map to values
0-9 -> 0-9, A-Z -> 10-35, '<' -> 0; weights repeat 7, 3, 1; the check digit
is the weighted sum mod 10.

Everything here is pure string arithmetic so the generator, the tamper
injector and any tool-assisted pre-check share one implementation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from datetime import date

FILLER = "<"
WEIGHTS = (7, 3, 1)
TD3_LEN = 44
TD1_LEN = 30

_MRZ_CHARS = re.compile(r"^[A-Z0-9<]*$")


class MRZError(ValueError):
    pass


# --------------------------------------------------------------------------
# check digits
# --------------------------------------------------------------------------
def char_value(c: str) -> int:
    if c.isdigit():
        return int(c)
    if "A" <= c <= "Z":
        return ord(c) - ord("A") + 10
    if c == FILLER:
        return 0
    raise MRZError(f"invalid MRZ character {c!r}")


def check_digit(s: str) -> str:
    """ICAO 9303 check digit for string ``s`` (returns a single digit char)."""
    total = sum(char_value(c) * WEIGHTS[i % 3] for i, c in enumerate(s))
    return str(total % 10)


def is_valid_check(s: str, digit: str) -> bool:
    if not digit.isdigit():
        # '<' is allowed as check digit only for an all-filler optional field
        return digit == FILLER and set(s) <= {FILLER}
    try:
        return check_digit(s) == digit
    except MRZError:
        return False


# --------------------------------------------------------------------------
# field formatting
# --------------------------------------------------------------------------
_TRANSLIT = str.maketrans({
    "Ä": "AE", "Ö": "OE", "Ü": "UE", "ß": "SS", "Å": "AA", "Æ": "AE", "Ø": "OE",
    "Þ": "TH", "Ñ": "N", "Ç": "C", "É": "E", "È": "E", "Ê": "E", "Ë": "E",
    "Á": "A", "À": "A", "Â": "A", "Ã": "A", "Í": "I", "Ì": "I", "Î": "I", "Ï": "I",
    "Ó": "O", "Ò": "O", "Ô": "O", "Õ": "O", "Ú": "U", "Ù": "U", "Û": "U",
    "Ý": "Y", "Ÿ": "Y", "Ğ": "G", "Ş": "S", "İ": "I", "Ł": "L", "Č": "C", "Š": "S",
    "Ž": "Z", "Ř": "R", "Ě": "E", "Ő": "O", "Ű": "U",
})


def mrz_text(s: str) -> str:
    """Upper-case, transliterate common Latin diacritics (Doc 9303 Part 3 §6),
    map separators to filler, drop anything else."""
    s = s.upper().translate(_TRANSLIT)
    s = re.sub(r"[\s\-]+", FILLER, s)
    s = re.sub(r"[^A-Z0-9<]", "", s)
    return s


def pad(s: str, n: int) -> str:
    if len(s) > n:
        raise MRZError(f"field {s!r} longer than {n}")
    return s + FILLER * (n - len(s))


def format_name(surname: str, given_names: str, width: int) -> str:
    """Primary identifier << secondary identifier, truncated to ``width``.

    Truncation follows the simple rule in Doc 9303: when too long, the
    secondary identifier is cut first, then the primary.
    """
    p = mrz_text(surname).strip(FILLER)
    g = mrz_text(given_names).strip(FILLER)
    s = p + FILLER * 2 + g if g else p
    if len(s) > width:
        s = s[:width]
    return pad(s, width)


def parse_name(field_: str) -> tuple[str, str]:
    field_ = field_.rstrip(FILLER)
    if FILLER * 2 in field_:
        p, g = field_.split(FILLER * 2, 1)
    else:
        p, g = field_, ""
    return p.replace(FILLER, " ").strip(), g.replace(FILLER, " ").strip()


def fmt_date(d: date) -> str:
    return d.strftime("%y%m%d")


def parse_date(s: str, *, kind: str = "birth", today: date | None = None) -> date | None:
    """YYMMDD -> date. Century: births never in the future; expiries are
    assumed within (today - 50y, today + 50y]."""
    if not re.fullmatch(r"\d{6}", s):
        return None
    today = today or date.today()
    yy, mm, dd = int(s[:2]), int(s[2:4]), int(s[4:])
    if kind == "birth":
        year = 2000 + yy if 2000 + yy <= today.year else 1900 + yy
    else:
        year = 2000 + yy
        if year > today.year + 50:
            year -= 100
    try:
        return date(year, mm, dd)
    except ValueError:
        return None


# --------------------------------------------------------------------------
# data model
# --------------------------------------------------------------------------
@dataclass
class MRZFields:
    doc_type: str            # 'P' for passport; 'I', 'ID', 'AC', ... for TD1
    issuing_state: str       # 3-letter code (ICAO / ISO 3166-1 alpha-3, or a fictional 'UTO')
    surname: str
    given_names: str
    doc_number: str
    nationality: str
    birth_date: date
    sex: str                 # 'M', 'F', or '<' / 'X'
    expiry_date: date
    optional1: str = ""      # TD3: personal number; TD1: optional data line 1
    optional2: str = ""      # TD1 only: optional data line 2

    def to_dict(self) -> dict:
        d = asdict(self)
        d["birth_date"] = self.birth_date.isoformat()
        d["expiry_date"] = self.expiry_date.isoformat()
        return d


@dataclass
class ParsedMRZ:
    format: str
    fields: MRZFields | None
    checks: dict[str, bool] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.errors and all(self.checks.values())


def _sex(s: str) -> str:
    s = (s or FILLER).upper()[:1]
    return {"X": FILLER}.get(s, s) if s in "MFX<" else FILLER


def _doc_code(code: str, td: str) -> str:
    code = mrz_text(code)
    if td == "TD3":
        return pad(code[:2] if code else "P", 2)
    return pad(code[:2] if code else "I", 2)


# --------------------------------------------------------------------------
# TD3
# --------------------------------------------------------------------------
def build_td3(f: MRZFields) -> list[str]:
    line1 = (_doc_code(f.doc_type, "TD3") + pad(mrz_text(f.issuing_state), 3)
             + format_name(f.surname, f.given_names, 39))
    docno = pad(mrz_text(f.doc_number), 9)
    dob = fmt_date(f.birth_date)
    exp = fmt_date(f.expiry_date)
    opt = pad(mrz_text(f.optional1), 14)
    opt_cd = FILLER if set(opt) == {FILLER} else check_digit(opt)
    # Doc 9303 allows '<' or '0' for an empty optional field; we emit '<'.
    l2 = (docno + check_digit(docno) + pad(mrz_text(f.nationality), 3)
          + dob + check_digit(dob) + _sex(f.sex) + exp + check_digit(exp)
          + opt + opt_cd)
    composite_src = l2[0:10] + l2[13:20] + l2[21:43]
    line2 = l2 + check_digit(composite_src)
    assert len(line1) == TD3_LEN and len(line2) == TD3_LEN
    return [line1, line2]


def parse_td3(lines: list[str], today: date | None = None) -> ParsedMRZ:
    out = ParsedMRZ("TD3", None)
    if len(lines) != 2 or any(len(l) != TD3_LEN for l in lines):
        out.errors.append("TD3 needs 2 lines of 44 characters")
        return out
    l1, l2 = lines
    if not all(_MRZ_CHARS.match(l) for l in lines):
        out.errors.append("invalid characters in MRZ")
    sur, given = parse_name(l1[5:44])
    out.checks = {
        "doc_number": is_valid_check(l2[0:9], l2[9]),
        "birth_date": is_valid_check(l2[13:19], l2[19]),
        "expiry_date": is_valid_check(l2[21:27], l2[27]),
        "optional": is_valid_check(l2[28:42], l2[42]),
        "composite": is_valid_check(l2[0:10] + l2[13:20] + l2[21:43], l2[43]),
    }
    dob = parse_date(l2[13:19], kind="birth", today=today)
    exp = parse_date(l2[21:27], kind="expiry", today=today)
    if dob is None:
        out.errors.append("unparseable birth date")
    if exp is None:
        out.errors.append("unparseable expiry date")
    if dob and exp:
        out.fields = MRZFields(
            doc_type=l1[0:2].rstrip(FILLER), issuing_state=l1[2:5].rstrip(FILLER),
            surname=sur, given_names=given, doc_number=l2[0:9].rstrip(FILLER),
            nationality=l2[10:13].rstrip(FILLER), birth_date=dob, sex=l2[20],
            expiry_date=exp, optional1=l2[28:42].rstrip(FILLER))
    return out


# --------------------------------------------------------------------------
# TD1
# --------------------------------------------------------------------------
def build_td1(f: MRZFields) -> list[str]:
    docno = pad(mrz_text(f.doc_number), 9)
    line1 = (_doc_code(f.doc_type, "TD1") + pad(mrz_text(f.issuing_state), 3)
             + docno + check_digit(docno) + pad(mrz_text(f.optional1), 15))
    dob = fmt_date(f.birth_date)
    exp = fmt_date(f.expiry_date)
    l2 = (dob + check_digit(dob) + _sex(f.sex) + exp + check_digit(exp)
          + pad(mrz_text(f.nationality), 3) + pad(mrz_text(f.optional2), 11))
    composite_src = line1[5:30] + l2[0:7] + l2[8:15] + l2[18:29]
    line2 = l2 + check_digit(composite_src)
    line3 = format_name(f.surname, f.given_names, 30)
    assert len(line1) == len(line2) == len(line3) == TD1_LEN
    return [line1, line2, line3]


def parse_td1(lines: list[str], today: date | None = None) -> ParsedMRZ:
    out = ParsedMRZ("TD1", None)
    if len(lines) != 3 or any(len(l) != TD1_LEN for l in lines):
        out.errors.append("TD1 needs 3 lines of 30 characters")
        return out
    l1, l2, l3 = lines
    if not all(_MRZ_CHARS.match(l) for l in lines):
        out.errors.append("invalid characters in MRZ")
    out.checks = {
        "doc_number": is_valid_check(l1[5:14], l1[14]),
        "birth_date": is_valid_check(l2[0:6], l2[6]),
        "expiry_date": is_valid_check(l2[8:14], l2[14]),
        "composite": is_valid_check(l1[5:30] + l2[0:7] + l2[8:15] + l2[18:29], l2[29]),
    }
    dob = parse_date(l2[0:6], kind="birth", today=today)
    exp = parse_date(l2[8:14], kind="expiry", today=today)
    if dob is None:
        out.errors.append("unparseable birth date")
    if exp is None:
        out.errors.append("unparseable expiry date")
    sur, given = parse_name(l3)
    if dob and exp:
        out.fields = MRZFields(
            doc_type=l1[0:2].rstrip(FILLER), issuing_state=l1[2:5].rstrip(FILLER),
            surname=sur, given_names=given, doc_number=l1[5:14].rstrip(FILLER),
            nationality=l2[15:18].rstrip(FILLER), birth_date=dob, sex=l2[7],
            expiry_date=exp, optional1=l1[15:30].rstrip(FILLER),
            optional2=l2[18:29].rstrip(FILLER))
    return out


# --------------------------------------------------------------------------
# convenience
# --------------------------------------------------------------------------
def build(f: MRZFields, fmt: str = "TD3") -> list[str]:
    return build_td3(f) if fmt == "TD3" else build_td1(f)


def parse(text: str | list[str], today: date | None = None) -> ParsedMRZ:
    """Parse an MRZ given as lines or a block of text; format is inferred
    from line lengths."""
    lines = text.split() if isinstance(text, str) else [l.strip() for l in text]
    lines = [l for l in lines if l]
    if len(lines) == 2:
        return parse_td3(lines, today)
    if len(lines) == 3:
        return parse_td1(lines, today)
    p = ParsedMRZ("unknown", None)
    p.errors.append(f"expected 2 or 3 MRZ lines, got {len(lines)}")
    return p
