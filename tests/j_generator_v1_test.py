"""Generator v1 (wave 2, Session J): as-of date, knob vector, plausibility,
OCR noise-rule switch, PoA abbreviation in the truth, held-out layouts."""
import copy
import json
from datetime import timedelta

import pytest

from step1_data_generation import sample as S
from step1_data_generation.config import GenConfig, HELDOUT_STYLES
from step1_data_generation.lib import address as A
from step1_data_generation.project import AMBIGUOUS, CLEAR_TAMPER, SECTION_TAG, project
from step1_data_generation.render import ALL_STYLES, STYLES, fmt_date, render
from step1_data_generation.twins import _reissue

DATE_STYLES = ("iso", "dmy_dots", "dmon", "dmon_short", "long")


@pytest.fixture(scope="module")
def cases():
    return S.sample_cases(300, seed=11)


@pytest.fixture(scope="module")
def strict_cases():
    return S.sample_cases(300, seed=12, cfg=GenConfig(ocr_digit_to_digit_in_numeric=False))


# ---- 1. as-of date ---------------------------------------------------------
@pytest.mark.parametrize("style", ALL_STYLES)
def test_as_of_printed_in_every_packet(cases, style):
    for c in cases[:40]:
        txt, _ = render(c, style)
        flat = " ".join(txt.split()).casefold()
        assert any(fmt_date(c.context.as_of_date, ds).casefold() in flat for ds in DATE_STYLES), c.case_id
        assert any(lbl in flat for lbl in ("as-of date", "review date (as of)", "assessed as of")), (style, c.case_id)


def test_as_of_lag_and_rules_use_as_of():
    cfg = GenConfig(as_of_lag_days=(10, 10))
    cs = S.sample_cases(120, seed=5, cfg=cfg)
    assert all((c.context.as_of_date - c.context.application_date).days == 10 for c in cs)
    base = next(c for c in cs if c.scenarios == ["clean"] and not c.id_doc.defects and c.poa.present)
    # expires after the application date but before the as-of date -> expired
    t = copy.deepcopy(base)
    _reissue(t, expiry_date=t.context.as_of_date - timedelta(days=3))
    assert t.context.application_date < t.context.as_of_date - timedelta(days=3)
    assert project(t)["expiry_reason"] == "document_expired"
    # PoA within 90 days of the application but not of the as-of date -> outside window
    t = copy.deepcopy(base)
    t.poa.issue_date = t.context.as_of_date - timedelta(days=S.POA_WINDOW_DAYS + 2)
    assert (t.context.application_date - t.poa.issue_date).days <= S.POA_WINDOW_DAYS
    assert project(t)["address_reason"] == "poa_stale"


def test_default_context_as_of_equals_application(cases):
    assert all(c.context.as_of_date == c.context.application_date for c in cases)


# ---- 2. knob vector --------------------------------------------------------
KNOB_KEYS = {"split", "config_id", "primary", "secondary", "scenarios", "style", "style_family", "origin",
             "nationality", "residence", "onboarding_country", "onboarding_tie", "age", "occupation",
             "id_kind", "mrz_format", "defect_kinds", "tamper_kind", "poa_present", "poa_age_days",
             "n_hits", "hit_list_types", "injection_location", "ambiguity",
             "ocr_digit_to_digit_in_numeric", "plausibility", "augmentation"}


def test_knob_vector_logged(cases):
    for c in cases:
        k = c.knobs
        assert KNOB_KEYS <= set(k), KNOB_KEYS - set(k)
        assert k["primary"] == c.scenarios[0] and k["scenarios"] == c.scenarios
        assert k["n_hits"] == len(c.hits)
        json.dumps(k)                                    # JSON-able
        assert c.to_dict()["knobs"] == k
        assert render(c)[1] == k["style"]               # the logged style is the rendered style


def test_style_pool_respected():
    cfg = GenConfig(styles={"form": 1.0, "prose": 1.0})
    cs = S.sample_cases(60, seed=3, cfg=cfg)
    assert {c.knobs["style"] for c in cs} == {"form", "prose"}


def test_style_choice_does_not_change_facts():
    a = S.sample_cases(30, seed=3, cfg=GenConfig(styles={"kv": 1.0}))
    b = S.sample_cases(30, seed=3, cfg=GenConfig(styles={"prose": 1.0}))
    for x, y in zip(a, b):
        dx, dy = x.to_dict(), y.to_dict()
        dx.pop("knobs"), dy.pop("knobs")
        assert dx == dy


# ---- 4. plausibility -------------------------------------------------------
def test_plausibility_constraints(cases):
    for c in cases:
        k = c.knobs
        lo, hi = S.OCC_AGE.get(c.application.occupation, S.OCC_AGE_DEFAULT)
        assert lo <= k["age"] <= hi, (c.application.occupation, k["age"])
        d = c.id_doc
        if d.kind == "national_id":
            assert d.issuing_state == c.person.nationality == S.ISO2_TO_3[k["residence"]]
        if d.kind == "passport":
            assert d.issuing_state == c.person.nationality
        if d.kind == "driving_licence":
            assert d.issuing_state == S.ISO2_TO_3[k["residence"]] and c.context.onboarding_country == k["residence"]
        if c.context.onboarding_country != k["residence"]:
            assert k["onboarding_tie"] in ("nationality", "remote_product")
            if k["onboarding_tie"] == "nationality":
                assert S.ISO2_TO_3[c.context.onboarding_country] == c.person.nationality
            else:
                assert c.context.product in S.REMOTE_CROSS_BORDER_PRODUCTS
                assert c.context.channel in ("online", "mobile_app")
        else:
            assert k["onboarding_tie"] == "residence"


def test_plausibility_can_be_switched_off():
    cs = S.sample_cases(300, seed=11, cfg=GenConfig(plausibility=False))
    bad = [c for c in cs if not (S.OCC_AGE.get(c.application.occupation, S.OCC_AGE_DEFAULT)[0]
                                 <= c.knobs["age"] <= S.OCC_AGE.get(c.application.occupation, S.OCC_AGE_DEFAULT)[1])]
    assert bad, "with plausibility off, A's unconstrained sampling should produce some odd combinations"


# ---- 5. OCR noise-rule switch ----------------------------------------------
def _codes(o):
    return {o[f"{k}_reason"] for k in ("date_of_birth", "document_number", "expiry")}


def test_switch_on_keeps_digit_lookalike_ocr(cases):
    assert any(x.kind == "ocr_digit_lookalike" for c in cases for x in c.id_doc.defects)
    assert any(AMBIGUOUS in _codes(project(c)) for c in cases)


def test_switch_off_no_digit_to_digit_ocr(strict_cases):
    for c in strict_cases:
        assert c.knobs["ocr_digit_to_digit_in_numeric"] is False
        assert all(x.kind != "ocr_digit_lookalike" for x in c.id_doc.defects)
        assert "ocr_vs_tamper_undecidable" not in c.ambiguity
        assert AMBIGUOUS not in _codes(project(c))
    tampered = [c for c in strict_cases if (c.id_doc.tamper or {}).get("kind") == "mrz_digit_lookalike"]
    assert tampered
    for c in tampered:
        assert _codes(project(c)) & CLEAR_TAMPER, c.case_id
    # OCR-only cases are still never called tampering
    for c in strict_cases:
        if c.scenarios[0] == "ocr_looks_like_tamper":
            assert not _codes(project(c)) & CLEAR_TAMPER


# ---- 7. PoA abbreviation lives in the truth --------------------------------
def test_address_text_is_fixed_by_truth(cases):
    for c in cases[:80]:
        declared = c.application.address.one_line(abbreviate=c.application.address_abbreviated)
        poa_lines = (c.poa.address.render(c.poa.render_style, abbreviate=c.poa.abbreviated).splitlines()
                     if c.poa.present and c.poa.legible else [])
        for seed in (None, 1, 2):
            txt, _ = render(c, "kv", seed=seed)
            assert declared in txt
            for line in poa_lines:
                assert line in txt
        if c.poa.abbreviated:
            assert c.poa.address.render(c.poa.render_style, True) != c.poa.address.render(c.poa.render_style, False)
        if c.application.address_abbreviated:
            assert c.application.address.one_line(True) != c.application.address.one_line(False)


def test_matches_vs_format_variant_follows_printed_text(cases):
    def flat(s):
        return ", ".join(x.strip() for x in s.replace("\n", ", ").split(",") if x.strip()).casefold()
    seen = set()
    for c in cases:
        code = project(c)["address_reason"]
        if code not in ("all_sources_agree", "country_format_difference"):
            continue
        same = flat(c.poa.address.render(c.poa.render_style, c.poa.abbreviated)) == \
            flat(c.application.address.one_line(c.application.address_abbreviated))
        assert (code == "all_sources_agree") == same, c.case_id
        seen.add(code)
    assert seen == {"all_sources_agree", "country_format_difference"}


# ---- held-out layout families ----------------------------------------------
@pytest.mark.parametrize("style", HELDOUT_STYLES)
def test_heldout_styles_render_all_evidence(cases, style):
    for c in cases[:60]:
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
        for s in project(c)["narrative"]:
            for ref in s["evidence_refs"]:
                assert SECTION_TAG[ref] in txt, (style, c.case_id, ref)
        assert "\x02" not in txt and "\x03" not in txt


def test_ocr_dump_has_no_section_headers(cases):
    txt, _ = render(cases[0], "ocr_dump")
    for hdr in ("[CTX]", "SECTION", "## ", "Attachment"):
        assert hdr not in txt
    assert set(STYLES).isdisjoint(HELDOUT_STYLES)
