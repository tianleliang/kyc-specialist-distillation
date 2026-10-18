import random

import pytest

from step1_data_generation.lib import names as N


def test_cyrillic_romanization_systems():
    n = N.PersonName("cyrillic", "M", ["Мухаммад"], ["Хасанов"], patronymic="Юрьевич")
    got = {s: n.full(system=s) for s in N.ROMANIZATION_SYSTEMS}
    assert got["icao"] == "Mukhammad Iurevich Khasanov"
    assert got["bgn_pcgn"] == "Mukhammad Yuryevich Khasanov"
    assert got["german"] == "Muchammad Jurjewitsch Chasanow"
    assert got["french"] == "Moukhammad Iourievitch Khasanov"
    assert got["gost_b"].startswith("Muxammad")


def test_bgn_initial_e():
    assert N.romanize("Елена", "bgn_pcgn") == "Yelena"
    assert N.romanize("Елена", "icao") == "Elena"
    assert N.romanize("Соловьёва", "bgn_pcgn") == "Solovyova"


def test_patronymics():
    assert N.patronymic("Сергей", "M") == "Сергеевич"
    assert N.patronymic("Иван", "F") == "Ивановна"
    assert N.patronymic("Дмитрий", "F") == "Дмитриевна"
    assert N.patronymic("Николай", "M") == "Николаевич"


def test_chinese_systems():
    n = N.PersonName("chinese", "M", ["晓", "明"], ["张"])
    assert n.full(order="surname_first") == "Zhang Xiaoming"
    assert n.full(system="wade_giles", order="surname_first") == "Chang Hsiao-ming"
    assert n.full(system="cantonese") == "Hiu Ming Cheung"
    assert n.full(system="pinyin_space", order="surname_first") == "Zhang Xiao Ming"
    q = N.PersonName("chinese", "M", ["志", "强"], ["陈"])
    assert q.full(system="wade_giles", order="surname_first") == "Ch'en Chih-ch'iang"
    assert q.full(system="wade_giles_plain", order="surname_first") == "Chen Chih-chiang"
    a = N.PersonName("chinese", "F", ["嘉", "安"], ["李"])
    assert a.full(order="surname_first") == "Li Jia'an"
    assert a.mrz_parts() == ("Li", "Jiaan")


def test_arabic_variants_cover_muhammad_family():
    n = N.PersonName("arabic", "M", ["muhammad"], ["Qasimi"], ar_article="al-")
    assert n.full() == "Muhammad al-Qasimi"
    rng = random.Random(0)
    spellings = {n.full(system="variant", rng=rng).split()[0] for _ in range(200)}
    assert {"Mohammed", "Mukhammad", "Mohamed"} <= spellings


@pytest.mark.parametrize("origin", N.ORIGINS)
def test_sample_every_origin(origin):
    rng = random.Random(42)
    for _ in range(30):
        n = N.sample_name(rng, origin)
        assert n.origin == origin
        full = n.full()
        assert full and not N.is_blocked(full)
        sur, given = n.mrz_parts()
        assert sur and given
        al = N.aliases(n, rng, 4)
        assert full not in al and len(al) == len(set(al))


def test_sampling_is_deterministic():
    a = [N.sample_name(random.Random(7)).full() for _ in range(3)]
    b = [N.sample_name(random.Random(7)).full() for _ in range(3)]
    assert a == b


def test_blocklist():
    assert N.is_blocked("Vladimir Putin")
    assert N.is_blocked("PUTIN, Vladimir")
    assert N.is_blocked("Xi Jinping")
    assert not N.is_blocked("Anna Eriksson")


def test_reorderings_spanish():
    n = N.PersonName("latin_es", "M", ["José", "Luis"], ["Ferández", "Sanillo"])
    r = N.reorderings(n)
    assert "José Luis Ferández" in r
    assert "José L. Ferández Sanillo" in r
    assert "FERÁNDEZ SANILLO, José Luis" in r


def test_similar_other_person_differs():
    rng = random.Random(3)
    for o in N.ORIGINS:
        n = N.sample_name(rng, o)
        other = N.similar_other_person(n, rng)
        assert other.full() != n.full()
        assert set(other.surname) == set(n.surname) or other.given == n.given
