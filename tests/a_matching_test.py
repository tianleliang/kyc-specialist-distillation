import random
from datetime import date

import pytest

from step1_data_generation.lib import matching as M
from step1_data_generation.lib import names as N


def test_normalize():
    assert M.normalize("Sheikh Muhammad AL-Qasimi") == "muhammad qasimi"
    assert M.normalize("José-Luis  Fernández") == "jose luis fernandez"
    assert M.normalize("Mukhammad", phonetic=True) == M.normalize("Muhammad", phonetic=True)


@pytest.mark.parametrize("a,b", [
    ("Muhammad al-Qasimi", "Mohammed Al Qasimi"),
    ("Mukhammad Khasanov", "Muhammad Hasanov"),
    ("Zhang Xiaoming", "Xiaoming Zhang"),
    ("Zhang Xiao Ming", "ZHANG, Xiaoming"),
    ("Abdul Rahman Badawi", "Abdulrahman el-Badawi"),
    ("Yelena Solovyova", "Elena Solovieva"),
    ("Olga Rokovich", "Olga Rokowitsch"),
])
def test_same_person_variants_score_high(a, b):
    assert M.similarity(a, b) >= 0.93


@pytest.mark.parametrize("a,b", [
    ("John Smith", "Maria Garcia"),
    ("Chen Wei", "Folasade Adekunle"),
])
def test_different_people_score_low(a, b):
    assert M.similarity(a, b) < 0.7


def test_shared_given_name_is_ambiguous_band():
    s = M.similarity("Muhammad al-Qasimi", "Muhammad al-Rashidi")
    assert 0.7 < s < 0.93


def test_symmetric_and_bounded():
    rng = random.Random(0)
    for _ in range(50):
        a, b = N.sample_name(rng).full(), N.sample_name(rng).full()
        s1, s2 = M.similarity(a, b), M.similarity(b, a)
        assert 0 <= s1 <= 1 and abs(s1 - s2) < 0.05


def test_generated_variants_match_their_source():
    rng = random.Random(1)
    lows = []
    # Chinese cross-system pairs (Pinyin vs Wade-Giles vs Cantonese) are left
    # out on purpose: string similarity misses them, as real vendors often do,
    # which is what makes them hard true matches.
    for o in [o for o in N.ORIGINS if o != "chinese"]:
        for _ in range(10):
            n = N.sample_name(rng, o)
            for v in N.spelling_variants(n, rng, 3):
                if M.similarity(n.full(), v) < 0.85:
                    lows.append((n.full(), v))
    assert len(lows) <= 2, lows


def test_vendor_score_alias_and_jitter():
    assert M.vendor_score("Mohammed Qasimi", "Ivan Petrov", aliases=["Muhammad al-Qasimi"]) >= 95
    rng = random.Random(0)
    scores = {M.vendor_score("Olga Rokovich", "Olga Rokowitsch", rng=rng) for _ in range(20)}
    assert len(scores) > 1 and all(0 <= s <= 100 for s in scores)


def test_compare_dob():
    d = date(1980, 3, 7)
    L = M.ListedDOB
    assert M.compare_dob(d, L.exact(d)) == "exact"
    assert M.compare_dob(d, L(1980)) == "year_only"
    assert M.compare_dob(d, L(1980, 3)) == "year_month"
    assert M.compare_dob(d, L(1980, 7, 3)) == "day_month_swapped"
    assert M.compare_dob(d, L(1978, year_to=1982)) == "in_range"
    assert M.compare_dob(d, L(1981)) == "near_year"
    assert M.compare_dob(d, L(1965, 1, 1)) == "mismatch"
    assert M.compare_dob(d, L()) == "unknown"
    assert L(1978, year_to=1982).render() == "1978 to 1982"


def test_cantonese_romanization_is_a_hard_true_match():
    assert M.similarity("Li Hua", "Lee Wah") < 0.8
