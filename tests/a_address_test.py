import random
import re

import pytest

from step1_data_generation.lib import address as A

POSTCODE = {
    "US": r"\d{5}(-\d{4})?", "GB": r"[A-Z]{1,2}\d{1,2} \d[A-Z]{2}", "DE": r"\d{5}",
    "FR": r"\d{5}", "AE": r"", "RU": r"\d{6}", "CN": r"\d{6}", "IN": r"\d{6}",
    "NG": r"\d{6}", "BR": r"\d{5}-\d{3}",
}


@pytest.mark.parametrize("c", A.COUNTRIES)
def test_sample_and_render(c):
    rng = random.Random(11)
    for _ in range(40):
        a = A.sample_address(rng, c)
        assert re.fullmatch(POSTCODE[c], a.postcode), a.postcode
        for style in ("postal", "single_line"):
            for ab in (False, True):
                t = a.render(style, ab)
                assert a.city.upper() in t.upper()
                if a.postcode:
                    assert a.postcode in t
        assert "\n" not in a.render("single_line")


def test_country_conventions():
    rng = random.Random(2)
    us = A.sample_address(rng, "US").render().splitlines()
    assert re.search(r", [A-Z]{2} \d{5}", us[-1])               # CITY, ST ZIP last
    de = A.sample_address(rng, "DE").render().splitlines()
    assert re.fullmatch(r"\d{5} .+", de[-1])                    # PLZ before city
    fr = A.sample_address(rng, "FR").render().splitlines()
    assert re.fullmatch(r"\d{5} [A-ZÉÈ' -]+", fr[-1])           # CP + CITY in caps
    gb = A.sample_address(rng, "GB").render().splitlines()
    assert re.fullmatch(POSTCODE["GB"], gb[-1])                 # postcode on its own line
    ae = A.sample_address(rng, "AE").render()
    assert "P.O. Box" in ae
    br = A.sample_address(rng, "BR").render().splitlines()
    assert re.fullmatch(POSTCODE["BR"], br[-1])
    ru = A.sample_address(rng, "RU")
    assert "ул." in ru.render("native") and "г." in ru.render("native")
    cn = A.sample_address(rng, "CN")
    native = cn.render("native")
    assert "路" in native and "号" in native and cn.number in native


@pytest.mark.parametrize("c", A.COUNTRIES)
def test_variants(c):
    rng = random.Random(4)
    for _ in range(20):
        a = A.sample_address(rng, c)
        assert A.benign_variant(a, rng).key() == a.key()
        assert A.render_variant(a, rng)
        for kind in A.CONTRADICTIONS:
            b, k = A.contradicting_variant(a, rng, kind)
            assert k == kind and b.key() != a.key()
            if kind == "city":
                assert b.city != a.city


def test_streets_are_fictional_compounds():
    rng = random.Random(0)
    a = A.sample_address(rng, "US")
    assert any(a.street.startswith(p) for p in A._EN_A)
