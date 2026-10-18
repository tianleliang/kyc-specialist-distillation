"""End-to-end checks for the generator and the v1 projection (policy v1)."""
import collections
import jsonschema
import pytest

from step1_data_generation import sample as S
from step1_data_generation.lib import names as N
from step1_data_generation.project import CLEAR_TAMPER, SCHEMA, SECTION_TAG, project
from step1_data_generation.render import STYLES, render

V = jsonschema.Draft202012Validator(SCHEMA)


@pytest.fixture(scope="module")
def cases():
    return S.sample_cases(300, seed=11)


@pytest.fixture(scope="module")
def projected(cases):
    return [(c, project(c)) for c in cases]


def test_deterministic():
    a = [c.to_dict() for c in S.sample_cases(5, 99)]
    b = [c.to_dict() for c in S.sample_cases(5, 99)]
    assert a == b
    assert render(S.sample_cases(1, 99)[0]) == render(S.sample_cases(1, 99)[0])


def test_every_scenario_covered():
    prims = {p for p, _ in S.plan(200, 1)}
    assert prims == set(S.DEFAULT_MIX)
    assert set(S.SCENARIOS) == set(S.DEFAULT_MIX)


def test_truth_is_schema_independent():
    import step1_data_generation.truth as T
    src = open(T.__file__).read()
    assert "decision" not in src.replace("decision policy", "") and "risk_tier" not in src


def test_expected_outputs_validate(projected):
    for c, o in projected:
        errs = list(V.iter_errors(o))
        assert not errs, (c.case_id, errs[0].message)
        assert 4 <= len(o["narrative"]) <= 8
        assert [s["hit_id"] for s in o["screening"]] == [h.hit_id for h in c.hits]


@pytest.mark.parametrize("style", STYLES)
def test_render_styles_carry_section_ids_and_protected_values(cases, style):
    for c in cases[:40]:
        txt, used = render(c, style)
        assert used == style
        for tag in ("CTX", "APP", "ID", "POA", "SCR"):
            assert tag in txt
        if c.id_doc.mrz_lines:
            for line in c.id_doc.mrz_lines:
                assert line in txt
        assert c.application.full_name in txt
        for h in c.hits:
            assert h.hit_id in txt
        assert "\x02" not in txt and "\x03" not in txt


def test_narrative_refs_resolve(cases, projected):
    for c, o in projected[:60]:
        txt, _ = render(c)
        for s in o["narrative"]:
            for ref in s["evidence_refs"]:
                assert SECTION_TAG[ref] in txt, (c.case_id, ref)
            for h in s["hit_ids"]:
                assert h in txt and h in {x["hit_id"] for x in o["screening"]}, (c.case_id, h)


def _by(projected, scen, primary_only=True):
    return [(c, o) for c, o in projected if (c.scenarios[0] == scen if primary_only else scen in c.scenarios)]


def test_scenario_invariants(projected):
    for c, o in _by(projected, "alias_true_match"):
        assert o["decision"] == "reject" and o["risk_tier"] == "high"
        assert "true_match" in {s["disposition"] for s in o["screening"]}
    for c, o in _by(projected, "tamper_obvious"):
        assert o["decision"] == "reject"                       # D4: clear tamper evidence rejects
        assert "document_tamper_evidence" in o["risk_drivers"]
    for c, o in _by(projected, "prompt_injection", primary_only=False):
        assert o["decision"] != "approve"
        assert "packet_contains_instructions" in o["risk_drivers"]
    for c, o in _by(projected, "partial_dob"):
        assert "needs_review" in {s["disposition"] for s in o["screening"]}
        assert o["decision"] in ("escalate", "reject")
    for scen in ("pep_self", "pep_family", "pep_associate", "expired_document", "poa_contradicts",
                 "poa_stale", "poa_name_differs", "insufficient_evidence", "dob_mismatch", "name_mismatch"):
        for c, o in _by(projected, scen):
            assert o["decision"] in ("escalate", "reject"), (scen, c.case_id)
    for c, o in _by(projected, "ocr_looks_like_tamper"):
        assert all(o[f"{k}_reason"] not in CLEAR_TAMPER for k in
                   ("date_of_birth", "document_number", "expiry")), c.case_id
        assert o["decision"] != "reject"
    for c, o in _by(projected, "translit_name") + _by(projected, "reordered_name"):
        assert o["name_status"] == "consistent"
    for c, o in _by(projected, "name_mismatch"):
        assert (o["name_status"], o["name_reason"]) == ("mismatch", "application_document_disagree")
    for c, o in _by(projected, "poa_name_differs"):
        assert (o["address_status"], o["address_reason"]) == ("mismatch", "poa_name_differs")


def test_decision_mix_is_not_degenerate(projected):
    d = collections.Counter(o["decision"] for _, o in projected)
    assert all(d[k] >= 0.07 * len(projected) for k in ("approve", "reject", "escalate")), d


def test_no_blocked_names(cases):
    for c in cases:
        assert not N.is_blocked(c.person.name.full())
        for h in c.hits:
            assert not N.is_blocked(h.entry["primary_name"])
