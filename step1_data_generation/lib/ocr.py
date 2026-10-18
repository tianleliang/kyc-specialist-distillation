"""OCR noise injector and a *separate* tamper injector.

OCR noise is what a scanner does by accident: glyph confusions (0/O, 1/l/I,
5/S, 8/B, rn/m, 2/Z, 6/G), dropped or doubled characters, broken lines,
and MRZ fillers read as K or spaces. Rates are configurable and every edit
is logged so the latent truth knows exactly what happened.

Tampering is what a person does on purpose: a changed date or number. The
tamper injector works on *fields*, not text, and records which zone changed
and whether check digits were recomputed. That is what lets a case say
whether a defect is OCR (explainable, usually one zone, usually letter/digit
confusions) or tampering (valid-looking digits, zones disagree, or check
digits that don't fit a value both zones agree on).

The two can be made to look alike on purpose:
* ``ocr_digit_confusion=True`` lets OCR turn 3->8, 1->7, 5->6 in one zone,
  breaking a check digit like tampering would;
* tamper kind ``mrz_digit_lookalike`` changes a digit to an OCR-lookalike
  digit in the MRZ only, so it reads like noise.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field, replace
from datetime import date

from . import mrz as M

# glyph -> things OCR reads it as
CONFUSIONS = {
    "0": ["O", "D", "Q"], "O": ["0", "D"], "D": ["0", "O"], "Q": ["O", "0"],
    "1": ["l", "I", "|", "i"], "l": ["1", "I"], "I": ["1", "l"],
    "5": ["S", "s"], "S": ["5", "$"], "8": ["B", "&"], "B": ["8"],
    "2": ["Z", "z"], "Z": ["2"], "6": ["G", "b"], "G": ["6", "C"],
    "m": ["rn", "nn"], "w": ["vv"], "d": ["cl"], "h": ["b", "li"], "e": ["c", "o"],
    "c": ["e"], "a": ["o", "e"], "u": ["v", "ii"], "n": ["ri", "h"], "g": ["q", "9"],
    "9": ["g", "q"], "4": ["A"], "A": ["4"], "7": ["T", "/"], "T": ["7"],
    "E": ["F", "8"], "F": ["E", "P"], "P": ["F", "R"], "R": ["P", "K"],
    "C": ["G", "("], "U": ["V", "LI"], "V": ["U", "Y"], "K": ["X", "<"],
}
MULTI = {"rn": "m", "cl": "d", "vv": "w", "li": "h"}
# digit -> digit lookalikes (these are the confusions that mimic tampering)
DIGIT_LOOKALIKE = {"3": "8", "8": "3", "1": "7", "7": "1", "5": "6", "6": "5", "0": "8", "9": "8", "4": "1"}
# MRZ-specific
MRZ_FILLER_READS = ["K", "«", " "]  # length-preserving misreads
MRZ_CONFUSIONS = {"0": ["O", "D"], "O": ["0"], "1": ["I", "L"], "I": ["1"], "5": ["S"],
                  "S": ["5"], "8": ["B"], "B": ["8"], "2": ["Z"], "Z": ["2"], "6": ["G"], "G": ["6"]}


@dataclass
class Edit:
    pos: int
    before: str
    after: str
    kind: str   # sub | sub_digit | del | dup | split | merge | filler


@dataclass
class OCRProfile:
    rate: float = 0.02              # probability per character of an edit
    sub: float = 0.7                # relative weights of edit types
    delete: float = 0.12
    dup: float = 0.05
    split: float = 0.05             # break a line at a space
    merge: float = 0.08             # rn->m and friends
    digit_lookalike: float = 0.0    # chance a digit edit is digit->digit (3->8)


def noise_text(text: str, rng: random.Random, profile: OCRProfile | None = None,
               rate: float | None = None) -> tuple[str, list[Edit]]:
    """Apply OCR-style noise to free text. Returns (noisy_text, edits)."""
    p = profile or OCRProfile()
    if rate is not None:
        p = replace(p, rate=rate)
    out: list[str] = []
    edits: list[Edit] = []
    kinds = ["sub", "del", "dup", "split", "merge"]
    weights = [p.sub, p.delete, p.dup, p.split, p.merge]
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\n" or rng.random() >= p.rate:
            out.append(ch)
            i += 1
            continue
        kind = rng.choices(kinds, weights)[0]
        two = text[i:i + 2]
        if kind == "merge" and two in MULTI:
            out.append(MULTI[two])
            edits.append(Edit(i, two, MULTI[two], "merge"))
            i += 2
            continue
        if kind == "sub" or kind == "merge":
            if ch.isdigit() and p.digit_lookalike and rng.random() < p.digit_lookalike and ch in DIGIT_LOOKALIKE:
                new, k = DIGIT_LOOKALIKE[ch], "sub_digit"
            elif ch in CONFUSIONS:
                new, k = rng.choice(CONFUSIONS[ch]), "sub"
            elif ch.isalpha() and ch.lower() in CONFUSIONS and rng.random() < 0.5:
                new, k = rng.choice(CONFUSIONS[ch.lower()]), "sub"
            else:
                out.append(ch)
                i += 1
                continue
            out.append(new)
            edits.append(Edit(i, ch, new, k))
        elif kind == "del" and ch != " ":
            edits.append(Edit(i, ch, "", "del"))
        elif kind == "dup" and ch.isalnum():
            out.append(ch + ch)
            edits.append(Edit(i, ch, ch + ch, "dup"))
        elif kind == "split" and ch == " ":
            out.append("\n")
            edits.append(Edit(i, ch, "\n", "split"))
        else:
            out.append(ch)
        i += 1
    return "".join(out), edits


def noise_mrz(lines: list[str], rng: random.Random, rate: float = 0.03,
              digit_lookalike: float = 0.0) -> tuple[list[str], list[tuple[int, Edit]]]:
    """OCR noise on MRZ lines: glyph confusions and misread fillers.
    Returns (lines, [(line_index, edit)])."""
    out_lines, edits = [], []
    for li, line in enumerate(lines):
        buf = []
        for i, ch in enumerate(line):
            if rng.random() >= rate:
                buf.append(ch)
                continue
            if ch == M.FILLER:
                new, k = rng.choice(MRZ_FILLER_READS), "filler"
            elif ch.isdigit() and digit_lookalike and rng.random() < digit_lookalike and ch in DIGIT_LOOKALIKE:
                new, k = DIGIT_LOOKALIKE[ch], "sub_digit"
            elif ch in MRZ_CONFUSIONS:
                new, k = rng.choice(MRZ_CONFUSIONS[ch]), "sub"
            else:
                buf.append(ch)
                continue
            buf.append(new)
            edits.append((li, Edit(i, ch, new, k)))
        out_lines.append("".join(buf))
    return out_lines, edits


# --------------------------------------------------------------------------
# OCR repair: can a broken MRZ be explained by glyph confusion alone?
# --------------------------------------------------------------------------
_TO_DIGIT = {"O": "0", "D": "0", "Q": "0", "I": "1", "L": "1", "S": "5", "B": "8",
             "Z": "2", "G": "6", "A": "4", "T": "7"}


def repair_mrz(lines: list[str], fmt: str) -> list[str]:
    """Undo the usual OCR damage: restore line length/fillers and map
    letters back to digits in numeric MRZ positions."""
    width = M.TD3_LEN if fmt == "TD3" else M.TD1_LEN
    fixed = []
    for l in lines:
        l = l.replace("«", "<").replace(" ", "<").upper()
        # fillers misread as K at the end of a line are common
        stripped = l.rstrip("<K")
        tail = len(l) - len(stripped)
        l = stripped + "<" * tail
        l = (l + "<" * width)[:width]
        fixed.append(l)
    numeric = _numeric_positions(fmt)
    out = []
    for li, l in enumerate(fixed):
        chars = list(l)
        for i in numeric.get(li, ()):
            if i < len(chars) and chars[i] in _TO_DIGIT:
                chars[i] = _TO_DIGIT[chars[i]]
        out.append("".join(chars))
    return out


def _numeric_positions(fmt: str) -> dict[int, range | list[int]]:
    if fmt == "TD3":
        # line 2: check digits and dates are numeric
        return {1: [9, 13, 14, 15, 16, 17, 18, 19, 21, 22, 23, 24, 25, 26, 27, 43]}
    return {0: [14], 1: [0, 1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 12, 13, 14, 29]}


def explain_mrz(lines: list[str], fmt: str, today: date | None = None) -> str:
    """'valid' | 'ocr_repairable' (fails as read, passes after repair) |
    'invalid' (fails even after repair, so not explainable by glyph
    confusion) | 'unreadable'."""
    raw = M.parse_td3(lines, today) if fmt == "TD3" else M.parse_td1(lines, today)
    if raw.valid:
        return "valid"
    rep = repair_mrz(lines, fmt)
    p = M.parse_td3(rep, today) if fmt == "TD3" else M.parse_td1(rep, today)
    if p.valid:
        return "ocr_repairable"
    if p.fields is None:
        return "unreadable"
    return "invalid"


# --------------------------------------------------------------------------
# Tamper injector
# --------------------------------------------------------------------------
TAMPER_KINDS = (
    "viz_only",              # visual zone altered, MRZ untouched -> zones disagree, MRZ valid
    "both_zones_no_recompute",  # both zones altered, check digits left -> MRZ check fails
    "both_zones_recomputed",    # both zones altered, check digits recomputed -> only external evidence
    "mrz_digit_lookalike",      # MRZ digit changed to an OCR-lookalike digit -> reads like noise
)
TAMPER_FIELDS = ("birth_date", "expiry_date", "doc_number")


@dataclass
class TamperRecord:
    kind: str
    field: str
    original: str
    altered: str
    zones: list[str]
    check_digits_recomputed: bool
    detectable_from_document: bool
    notes: str = ""


def _alter_value(field_: str, f: M.MRZFields, rng: random.Random, lookalike: bool = False):
    if field_ in ("birth_date", "expiry_date"):
        d: date = getattr(f, field_)
        if lookalike:
            s = M.fmt_date(d)
            for _ in range(20):
                i = rng.randrange(6)
                if s[i] in DIGIT_LOOKALIKE:
                    cand = s[:i] + DIGIT_LOOKALIKE[s[i]] + s[i + 1:]
                    nd = M.parse_date(cand, kind="birth" if field_ == "birth_date" else "expiry",
                                      today=date(2026, 10, 17))
                    if nd and nd != d:
                        return nd
            lookalike = False
        if field_ == "expiry_date":
            years = rng.choice([2, 3, 5, 10])
            try:
                return d.replace(year=d.year + years)
            except ValueError:
                return d.replace(year=d.year + years, day=28)
        delta = rng.choice([-7, -5, -3, -2, 2, 3, 5, 8]) * 365 + rng.randint(-40, 40)
        return date.fromordinal(d.toordinal() + delta)
    s = f.doc_number
    for _ in range(20):
        i = rng.randrange(len(s))
        if s[i].isdigit():
            new = DIGIT_LOOKALIKE.get(s[i], "1") if lookalike else rng.choice([c for c in "0123456789" if c != s[i]])
            if new != s[i]:
                return s[:i] + new + s[i + 1:]
    return s[:-1] + ("1" if s[-1] != "1" else "2")


def _fmt(v) -> str:
    return v.isoformat() if isinstance(v, date) else str(v)


def tamper(f: M.MRZFields, fmt: str, rng: random.Random, kind: str | None = None,
           field_: str | None = None, lookalike: bool | None = None
           ) -> tuple[M.MRZFields, list[str], TamperRecord]:
    """Tamper with a document.

    Returns (viz_fields, mrz_lines, record): the fields as printed in the
    visual zone, the MRZ lines as printed, and what was done. For kinds that
    leave stale check digits, a value that happens to satisfy the old check
    digit (1 in 10) is resampled so the record's detectability is true.
    ``lookalike`` forces OCR-lookalike digit changes (3->8, 1->7) for any
    kind; by default only ``mrz_digit_lookalike`` uses them.
    """
    kind = kind or rng.choice(TAMPER_KINDS)
    field_ = field_ or rng.choice(TAMPER_FIELDS)
    for _ in range(30):
        out = _tamper_once(f, fmt, rng, kind, field_,
                           kind == "mrz_digit_lookalike" if lookalike is None else lookalike)
        if kind in ("both_zones_no_recompute", "mrz_digit_lookalike") and M.parse(out[1]).valid:
            continue
        return out
    raise RuntimeError("could not produce a detectable tamper")


def _tamper_once(f, fmt, rng, kind, field_, lookalike):
    new_val = _alter_value(field_, f, rng, lookalike=lookalike)
    altered = replace(f, **{field_: new_val})
    orig_lines = M.build(f, fmt)
    alt_lines = M.build(altered, fmt)
    if kind == "viz_only":
        rec = TamperRecord(kind, field_, _fmt(getattr(f, field_)), _fmt(new_val), ["viz"], False, True,
                           "visual zone disagrees with a valid MRZ")
        return altered, orig_lines, rec
    if kind == "both_zones_recomputed":
        rec = TamperRecord(kind, field_, _fmt(getattr(f, field_)), _fmt(new_val), ["viz", "mrz"], True, False,
                           "zones agree and check digits pass; only external evidence can expose it")
        return altered, alt_lines, rec
    # copy only the data characters of the altered field into the original
    # lines, leaving the original check digits in place
    lines = _splice_field(orig_lines, alt_lines, fmt, field_)
    if kind == "both_zones_no_recompute":
        rec = TamperRecord(kind, field_, _fmt(getattr(f, field_)), _fmt(new_val), ["viz", "mrz"], False, True,
                           "zones agree but the MRZ check digit does not fit the value")
        return altered, lines, rec
    rec = TamperRecord(kind, field_, _fmt(getattr(f, field_)), _fmt(new_val), ["mrz"], False, True,
                       "MRZ digit changed to an OCR-lookalike; visual zone keeps the original")
    return f, lines, rec


def _field_span(fmt: str, field_: str) -> tuple[int, int, int]:
    """(line, start, end) of a field's data characters (no check digit)."""
    if fmt == "TD3":
        return {"doc_number": (1, 0, 9), "birth_date": (1, 13, 19), "expiry_date": (1, 21, 27)}[field_]
    return {"doc_number": (0, 5, 14), "birth_date": (1, 0, 6), "expiry_date": (1, 8, 14)}[field_]


def _splice_field(orig: list[str], alt: list[str], fmt: str, field_: str) -> list[str]:
    li, a, b = _field_span(fmt, field_)
    out = list(orig)
    out[li] = orig[li][:a] + alt[li][a:b] + orig[li][b:]
    return out
