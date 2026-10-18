"""Session M: hand-template OOD writer (step1_data_generation/ood_templates.py) and the
LLM-written OOD writer (step1_data_generation/ood_llm.py, mocked: no network)."""
import json
import random

import jsonschema
import pytest

from step1_data_generation import ood_llm as L
from step1_data_generation import ood_templates as H


@pytest.fixture(scope="module")
def truths():
    return H.sample_truths(150, H.DEFAULT_SEED, "oodh")


# --------------------------------------------------------------------------
# hand templates
# --------------------------------------------------------------------------
def test_at_least_five_styles():
    assert len(H.STYLES) >= 5


@pytest.mark.parametrize("style", list(H.STYLES))
def test_every_fact_present_in_every_style(truths, style):
    for t in truths:
        packet, v = H.render_hand(t, style)          # asserts internally
        assert H.check_packet(packet, v, H.STYLES[style]) == []
        assert len(v.facts) >= 25


def test_scenario_coverage_of_test_truths(truths):
    """The fixture exercises every hard case the OOD config asks for, so the test above covers them."""
    prim = {t.scenarios[0] for t in truths}
    assert {"tamper_looks_like_ocr", "ocr_looks_like_tamper", "prompt_injection", "insufficient_evidence",
            "poa_contradicts", "alias_true_match", "pep_family"} <= prim
    assert any(t.injection.present and t.injection.location == "hit_remarks" for t in truths)
    assert any(not t.poa.present for t in truths)
    assert any("" in t.id_doc.viz.values() for t in truths)


def test_illegible_poa_renders_as_junk_in_every_style(truths):
    import copy

    t = copy.deepcopy(next(t for t in truths if t.poa.present and t.poa.legible))
    t.poa.legible = False
    for s in H.STYLES:
        packet, v = H.render_hand(t, s)
        assert ("poa.kind", v.poa_kind) in v.facts and not any(k == "poa.date" for k, _ in v.facts)
        assert H.STYLES[s].enc(v.poa_date) not in packet and H.STYLES[s].enc(t.poa.issuer) not in packet


def test_check_detects_a_fixed_mrz_and_a_leak(truths):
    t = next(t for t in truths if t.id_doc.mrz_lines)
    st = H.STYLES["case_ticket"]
    packet, v = H.render_hand(t, "case_ticket")
    fixed = packet.replace(v.mrz[1], v.mrz[1][:-1] + ("0" if v.mrz[1][-1] != "0" else "1"))
    assert any("id.mrz[1]" in p for p in H.check_packet(fixed, v, st))
    assert any("leak" in p for p in H.check_packet(packet + "\nNote: possible tamper.", v, st))
    with pytest.raises(AssertionError):
        bad = H.Style("bad", H.fmt_iso, "?", "none", "none", lambda v, rng: "empty packet")
        H.STYLES["bad"] = bad
        try:
            H.render_hand(t, "bad")
        finally:
            del H.STYLES["bad"]


def test_injection_text_verbatim_and_not_flagged_as_leak(truths):
    inj = [t for t in truths if t.injection.present]
    assert inj
    for t in inj:
        for s in H.STYLES:
            packet, _ = H.render_hand(t, s)
            assert H.STYLES[s].enc(t.injection.text) in packet


def test_dates_are_unambiguous():
    for f in (H.fmt_dmy_short, H.fmt_mdy_long, H.fmt_dmy_caps, H.fmt_ymd_slash, H.fmt_dmy_long, H.fmt_iso):
        a, b = f("1990-03-04"), f("1990-04-03")
        assert a != b
        for x in (a, b):   # never a numeric day/month or month/day form
            assert not __import__("re").search(r"(?<!\d)\d{2}/\d{2}/\d{4}", x)


def test_assign_styles_balanced():
    s = H.assign_styles(50, 1)
    counts = {k: s.count(k) for k in H.STYLES}
    assert max(counts.values()) - min(counts.values()) <= 1 and sum(counts.values()) == 50
    assert s == H.assign_styles(50, 1)


def test_no_layout_shared_with_training_renderer(truths):
    """Boilerplate shingles (fact values removed) barely overlap with step1_data_generation.render
    (this test imports it; the writer module never does)."""
    from step1_data_generation.render import render

    def shingles(text, facts, k=24):
        for f in sorted(facts, key=len, reverse=True):
            if len(f) >= 3:
                text = text.replace(f, "\x00")
        text = " ".join(text.split())
        return {text[i:i + k] for i in range(len(text) - k) if "\x00" not in text[i:i + k]}

    worst = 0.0
    for i, t in enumerate(truths[:30]):
        style = list(H.STYLES)[i % len(H.STYLES)]
        hp, v = H.render_hand(t, style)
        facts = [s for _, s in v.facts] + [t.application.address.one_line(), t.person.address.one_line(),
                                           v.authority, v.place_of_birth]
        tp = render(t)[0]
        hs, ts = shingles(hp, facts), shingles(tp, facts)
        if hs:
            worst = max(worst, len(hs & ts) / len(hs))
    assert worst < 0.05, worst


def test_build_refuses_without_allow_eval(tmp_path):
    with pytest.raises(SystemExit, match="allow-eval"):
        H.build(4, out=tmp_path / "x")


def test_build_refuses_frozen(tmp_path):
    (tmp_path / "MANIFEST.json").write_text("{}")
    with pytest.raises(SystemExit, match="frozen"):
        H.build(4, out=tmp_path, allow_eval=True, force=True)


def test_build_small_valid_and_deterministic(tmp_path):
    m1 = H.build(12, out=tmp_path / "a", allow_eval=True)
    m2 = H.build(12, out=tmp_path / "b", allow_eval=True)
    assert m1["sha256"] == m2["sha256"]
    _, schema, schema_id = H.labeller()
    rows = [json.loads(l) for l in (tmp_path / "a" / "cases.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 12 and all(r["schema"] == schema_id for r in rows)
    assert all(r["case_id"].startswith("oodh-4010000-") for r in rows)
    val = jsonschema.Draft202012Validator(schema)
    assert all(not list(val.iter_errors(r["expected"])) for r in rows)
    assert len({r["style"] for r in rows}) == len(H.STYLES)
    with pytest.raises(SystemExit, match="refusing to overwrite"):
        H.build(12, out=tmp_path / "a", allow_eval=True)


def test_truths_disjoint_from_other_ood_sets():
    a = {t.case_id for t in H.sample_truths(10, H.DEFAULT_SEED, "oodh")}
    b = {t.case_id for t in H.sample_truths(10, L.DEFAULT_SEED, "oodl")}
    assert not a & b
    ha = [H.sample_truths(3, H.DEFAULT_SEED, "x")[i].person.name.canonical for i in range(3)]
    hb = [H.sample_truths(3, 4000000, "x")[i].person.name.canonical for i in range(3)]
    assert ha != hb


# --------------------------------------------------------------------------
# LLM writer (mocked)
# --------------------------------------------------------------------------
HIDDEN_KEYS = {"scenarios", "same_person", "defects", "tamper", "name_relation", "dob_relation", "address_relation",
               "contradiction", "discriminators", "risk", "knobs", "ambiguity", "notes", "mrz_check", "genuine",
               "pep_relation", "dob_comparison", "nationality_match", "media_category", "target", "technique"}


def _keys(o):
    if isinstance(o, dict):
        for k, v in o.items():
            yield k
            yield from _keys(v)
    elif isinstance(o, list):
        for v in o:
            yield from _keys(v)


def test_visible_truth_hides_explanations(truths):
    for t in truths:
        vt = L.visible_truth(t)
        assert not set(_keys(vt)) & HIDDEN_KEYS
        blob = json.dumps(vt, ensure_ascii=False).casefold()
        scrub = blob.replace(json.dumps(t.injection.text, ensure_ascii=False)[1:-1].casefold(), "") \
            if t.injection.present else blob
        assert "tamper" not in scrub and "true_match" not in scrub


def test_required_strings_and_dates_cover_the_label_facts(truths):
    for t in truths:
        req = L.required_strings(t)
        if t.id_doc.mrz_lines:
            assert all(m in req for m in t.id_doc.mrz_lines)
        assert t.application.full_name in req
        assert all(h.hit_id in req for h in t.hits)
        if t.injection.present:
            assert t.injection.text in req
        assert t.context.as_of_date.isoformat() in L.required_dates(t)


def test_date_and_number_forms():
    assert L.date_present("2026-03-04", "issued 4 March 2026 at")
    assert L.date_present("2026-03-04", "ISSUED 04-MAR-2026")
    assert L.date_present("2026-03-04", "on March 4, 2026")
    assert not L.date_present("2026-03-04", "issued 04/03/2026")
    assert L.number_present(143300, "about 143,300 EUR") and L.number_present(143300, "143300")
    assert not L.number_present(143300, "1433000") and not L.number_present(1433, "143300")
    assert L.strip_fences("```text\nhello\n```") == "hello"


def test_models_alternate_and_styles_rotate():
    items = L.plan(8, L.DEFAULT_SEED, 1.0)
    assert [it["model"] for it in items[:4]] == ["claude-sonnet-5-5", "gemini-3.8-flash"] * 2
    assert items[0]["style"] == items[1]["style"] != items[2]["style"]


def _client(responder):
    from shared.frontier_api.clients import LLMClient

    return LLMClient(mock=True, mock_responder=responder, cache_dir=None)


def test_run_mock_keeps_good_packets(tmp_path):
    items = L.plan(10, L.DEFAULT_SEED, 1.2)
    m = L.run(10, out=tmp_path, allow_eval=True, client=_client(L.mock_responder(items)), oversample=1.2,
              log=lambda *a: None)
    assert m["n_kept"] == 10 and m["status_totals"]["kept"] == 10
    rows = [json.loads(l) for l in (tmp_path / "cases.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {r["render_model"] for r in rows} == {"claude-sonnet-5-5", "gemini-3.8-flash"}
    _, schema, _ = H.labeller()
    val = jsonschema.Draft202012Validator(schema)
    assert all(not list(val.iter_errors(r["expected"])) for r in rows)
    assert (tmp_path / "dropped.jsonl").exists() and (tmp_path / "truth.jsonl").exists()


def test_run_drops_fixed_leaky_and_ambiguous_packets(tmp_path):
    items = L.plan(8, L.DEFAULT_SEED, 1.0)
    by_id = {it["truth"].case_id: it["truth"] for it in items}
    good = L.mock_responder(items)
    modes = {}

    def responder(req):
        cid = req.metadata["case_id"]
        t = by_id[cid]
        p = good(req)
        i = list(by_id).index(cid)
        if i == 0 and t.id_doc.mrz_lines:          # "fix" the MRZ
            modes[cid] = "missing_or_fixed"
            return p.replace(t.id_doc.mrz_lines[-1], t.id_doc.mrz_lines[-1].replace("<", " "))
        if i == 1:                                  # editorialise
            modes[cid] = "leak"
            return p + "\nAnalyst note: the document looks tampered."
        if i == 2:                                  # numeric day/month dates only
            modes[cid] = "date_missing"
            d = t.context.as_of_date
            return p.replace(H.fmt_dmy_long(d.isoformat()), f"{d.day:02d}/{d.month:02d}/{d.year}")
        if i == 3:
            modes[cid] = "error"
            raise ValueError("boom")
        return p

    m = L.run(8, out=tmp_path, allow_eval=True, client=_client(responder), oversample=1.0, log=lambda *a: None)
    dropped = {json.loads(l)["case_id"]: json.loads(l) for l in
               (tmp_path / "dropped.jsonl").read_text(encoding="utf-8").splitlines()}
    for cid, mode in modes.items():
        assert mode in dropped[cid]["reasons"], (mode, dropped[cid]["reasons"])
    assert m["n_kept"] == 8 - len(modes)
    assert sum(m["status_totals"].values()) == 8


def test_llm_run_refuses_without_allow_eval(tmp_path):
    with pytest.raises(SystemExit, match="allow-eval"):
        L.run(2, out=tmp_path, client=_client(lambda r: "x"))
