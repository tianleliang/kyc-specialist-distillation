import random
from datetime import date

from step1_data_generation.lib import names as N
from step1_data_generation.lib import watchlist as W


def test_entry_structures():
    rng = random.Random(0)
    p = N.sample_name(rng, "arabic", "M")
    for src in W.LIST_SOURCES["sanctions"]:
        e = W.make_entry(rng, p, "sanctions", dob=date(1971, 5, 2), nationality="SYN", list_source=src, n_aliases=3)
        d = e.to_dict()
        assert d["synthetic"] is True and len(e.aliases) == 3 == len(e.alias_quality)
        if src.startswith("OFAC"):
            assert e.entry_id.startswith("SYN-") and d["details"]["programs"]
            assert "," in e.primary_name                      # SURNAME, Given
        if src.startswith("UN"):
            assert set(e.alias_quality) <= {"Good", "Low"} and "listed_on" in e.details
        if src.startswith("EU"):
            assert "regulation" in e.details


def test_programs_are_invented():
    assert all(p.startswith("SYN") for p in W.SDN_PROGRAMS)


def test_pep_rca_details():
    rng = random.Random(1)
    d = W.pep_details(rng, "Ivan Sokolov", relation="family", relationship="spouse")
    assert d["rca_type"] == "family" and d["relationship"] == "spouse" and d["related_pep"] == "Ivan Sokolov"
    assert d["pep_category"] in {"domestic", "foreign", "international_org"}


def test_screening_finds_the_listed_person_among_decoys():
    rng = random.Random(2)
    wl = W.Watchlist(W.decoy_entries(rng, 300))
    target = N.sample_name(rng, "cyrillic", "M")
    listed = W.make_entry(rng, target, "sanctions", dob=date(1970, 1, 1), nationality="RUS",
                          primary_system="bgn_pcgn", n_aliases=3)
    wl.add(listed)
    applicant = target.full(system="icao", with_patronymic=False)
    hits = wl.screen(applicant, threshold=80)
    assert hits[0].entry is listed and hits[0].score >= 90


def test_decoys_are_not_blocked_names():
    rng = random.Random(3)
    for e in W.decoy_entries(rng, 100):
        assert not N.is_blocked(e.primary_name)
        assert e.synthetic
