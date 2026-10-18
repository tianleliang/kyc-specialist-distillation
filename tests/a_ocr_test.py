import random
from datetime import date

import pytest

from step1_data_generation.lib import mrz as M
from step1_data_generation.lib import ocr as O

TODAY = date(2026, 10, 17)


def fields():
    return M.MRZFields("P", "UTO", "Okonkwo", "Adaeze", "A12345678", "NGA",
                       date(1985, 3, 14), "F", date(2030, 8, 31), "")


def test_noise_rate_zero_is_identity():
    t = "Passport No: A12345678\nSurname: OKONKWO"
    assert O.noise_text(t, random.Random(0), rate=0) == (t, [])


def test_noise_is_logged_and_deterministic():
    t = "Date of birth 14 MAR 1985 Place of birth LAGOS " * 4
    a = O.noise_text(t, random.Random(3), rate=0.1)
    b = O.noise_text(t, random.Random(3), rate=0.1)
    assert a == b and a[0] != t and a[1]
    assert all(e.kind in {"sub", "sub_digit", "del", "dup", "split", "merge"} for e in a[1])


def test_noise_rate_scales():
    t = "abcdefghijklmnopqrstuvwxyz0123456789 " * 20
    lo = len(O.noise_text(t, random.Random(1), rate=0.01)[1])
    hi = len(O.noise_text(t, random.Random(1), rate=0.2)[1])
    assert hi > 4 * lo


def test_digit_lookalike_only_when_enabled():
    t = "3333333333" * 10
    _, e0 = O.noise_text(t, random.Random(0), rate=0.5)
    _, e1 = O.noise_text(t, random.Random(0), O.OCRProfile(rate=0.5, digit_lookalike=1.0))
    assert not any(e.kind == "sub_digit" for e in e0)
    assert any(e.kind == "sub_digit" and e.after == "8" for e in e1)


@pytest.mark.parametrize("fmt", ["TD3", "TD1"])
def test_glyph_noise_on_mrz_is_repairable(fmt):
    lines = M.build(fields(), fmt)
    rng = random.Random(5)
    repaired = 0
    for _ in range(50):
        noisy, edits = O.noise_mrz(lines, rng, rate=0.04)
        res = O.explain_mrz(noisy, fmt, TODAY)
        if not edits:
            assert res == "valid"
        elif res == "ocr_repairable":
            repaired += 1
        assert res in ("valid", "ocr_repairable", "invalid", "unreadable")
    assert repaired >= 20


@pytest.mark.parametrize("fmt", ["TD3", "TD1"])
def test_tamper_kinds(fmt):
    rng = random.Random(9)
    f = fields()
    for fld in O.TAMPER_FIELDS:
        viz, lines, rec = O.tamper(f, fmt, rng, "viz_only", fld)
        assert M.parse(lines, TODAY).valid and getattr(viz, fld) != getattr(f, fld)

        viz, lines, rec = O.tamper(f, fmt, rng, "both_zones_recomputed", fld)
        p = M.parse(lines, TODAY)
        assert p.valid and getattr(p.fields, fld) == getattr(viz, fld) != getattr(f, fld)
        assert not rec.detectable_from_document

        viz, lines, rec = O.tamper(f, fmt, rng, "both_zones_no_recompute", fld)
        p = M.parse(lines, TODAY)
        assert not p.valid and getattr(p.fields, fld) == getattr(viz, fld)
        assert O.explain_mrz(lines, fmt, TODAY) == "invalid"   # not explainable by glyph confusion

        viz, lines, rec = O.tamper(f, fmt, rng, "mrz_digit_lookalike", fld)
        p = M.parse(lines, TODAY)
        assert not p.valid and viz == f
        assert rec.zones == ["mrz"]
