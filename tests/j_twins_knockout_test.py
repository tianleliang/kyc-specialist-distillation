"""Counterfactual twins and evidence knockout: the labelled flip must actually
happen through step1_data_generation/project.py, and each edit must touch only the intended fact."""
import json
import random
import subprocess
import sys
from pathlib import Path

import pytest

from step1_data_generation import project as P
from step1_data_generation import sample as S
from step1_data_generation.knockout import KNOCKOUTS, make_knockout, make_knockouts
from step1_data_generation.render import render
from step1_data_generation.twins import FLIPS, _listed, make_twin, make_twins

ROOT = Path(__file__).resolve().parents[1]

# truth sections each op may touch (besides case_id / notes / knobs)
TOUCHES = {
    "expire_document": {"id_doc"}, "renew_document": {"id_doc"}, "tamper_document_digit": {"id_doc"},
    "hit_dob_conflict": {"hits"}, "hit_dob_confirm": {"hits"},
    "listed_dob_partial": {"hits"}, "listed_dob_full": {"hits"},
    "poa_stale": {"poa"}, "poa_refresh": {"poa"}, "poa_contradict": {"poa"}, "poa_fix": {"poa"},
    "declared_dob_typo": {"application"}, "declared_dob_fix": {"application"},
    "add_injection": {"injection"}, "remove_injection": {"injection"},
}
META = {"case_id", "notes", "knobs"}


@pytest.fixture(scope="module")
def cases():
    return S.sample_cases(300, seed=11)


def _diff_sections(a, b):
    da, db = a.to_dict(), b.to_dict()
    return {k for k in da if da[k] != db[k]} - META


@pytest.fixture(scope="module")
def twin_results(cases):
    res = {op: [] for op in FLIPS}
    for c in cases:
        for op, f in FLIPS.items():
            if f.applies(c):
                tw, rec = make_twin(c, op, random.Random(f"{c.case_id}:{op}"))
                res[op].append((c, tw, rec))
    return res


def test_flip_catalog_covered():
    assert set(FLIPS) == set(TOUCHES)


@pytest.mark.parametrize("op", sorted(FLIPS))
def test_twin_flip_happens_through_project(twin_results, op):
    runs = twin_results[op]
    assert runs, f"{op} never applied"
    flipped = 0
    for base, tw, rec in runs:
        assert rec["outcome_from"] == P.outcome(base) and rec["outcome_to"] == P.outcome(tw)
        assert rec["flipped"] == (rec["outcome_from"] != rec["outcome_to"])
        flipped += rec["flipped"]
        # exactly one fact (one truth section) changed
        assert _diff_sections(base, tw) <= TOUCHES[op], (op, _diff_sections(base, tw))
        assert tw.knobs["twin_of"] == base.case_id and tw.knobs["augmentation"] == "twin"
    assert flipped, f"{op} never flipped the outcome"


def test_twin_directions(twin_results):
    def pairs(op):
        return {(r["outcome_from"], r["outcome_to"]) for _, _, r in twin_results[op] if r["flipped"]}
    assert ("approve", "escalate") in pairs("expire_document")
    assert ("escalate", "approve") in pairs("renew_document")
    assert all(to == "reject" for _, to in pairs("tamper_document_digit"))
    assert ("approve", "escalate") in pairs("add_injection")
    assert ("escalate", "approve") in pairs("remove_injection")
    assert ("approve", "escalate") in pairs("poa_stale") and ("escalate", "approve") in pairs("poa_refresh")
    assert ("reject", "approve") in pairs("hit_dob_conflict") or ("escalate", "approve") in pairs("hit_dob_conflict")
    assert all(to == "escalate" for _, to in pairs("listed_dob_partial"))


def test_twin_renders_like_its_base(twin_results):
    for op in ("expire_document", "poa_stale", "hit_dob_conflict"):
        base, tw, _ = twin_results[op][0]
        tb, sb = render(base)
        tt, st = render(tw)
        assert sb == st and tb != tt
        assert tb.splitlines()[0] == tt.splitlines()[0]     # same header => same render stream


def test_make_twins_keeps_only_flips(cases):
    rng = random.Random(0)
    out = [x for c in cases[:80] for x in make_twins(c, rng, max_per_base=2)]
    assert out and all(r["flipped"] for _, r in out)
    assert all(len([1 for _, r in out if r["base_id"] == b]) <= 2 for b in {r["base_id"] for _, r in out})


def test_listed_dob_roundtrip(cases):
    for c in cases:
        for h in c.hits:
            assert _listed(h.entry["dob"]).render() == h.entry["dob"]


# ---- knockout ---------------------------------------------------------------
@pytest.mark.parametrize("op", sorted(KNOCKOUTS))
def test_knockout_turns_decisive_cases_into_escalate(cases, op):
    changed = 0
    for c in cases:
        if not KNOCKOUTS[op].applies(c):
            continue
        ko, rec = make_knockout(c, op, random.Random(c.case_id))
        assert rec["outcome_from"] == P.outcome(c) and rec["outcome_to"] == P.outcome(ko)
        assert rec["escalates"] == (P.outcome(ko) == P.ESCALATE)
        if rec["outcome_from"] == "approve":
            # knocking out evidence must never leave an approvable case
            assert rec["outcome_to"] == P.ESCALATE, (op, c.case_id)
        changed += rec["escalates"] and rec["changed"]
        assert any(a.startswith("knockout:") for a in ko.ambiguity)
        txt, _ = render(ko)
        assert ("None" in txt) <= ("None" in render(c)[0])     # removed fields are omitted, not printed as None
    assert changed, f"{op} never produced a new escalation"


def test_make_knockouts_filter(cases):
    rng = random.Random(0)
    out = [x for c in cases[:120] for x in make_knockouts(c, rng)]
    assert out
    for ko, rec in out:
        assert P.outcome(ko) == P.ESCALATE and rec["outcome_from"] != P.ESCALATE


# ---- build with augmentation -------------------------------------------------
def test_build_with_twins_and_knockouts(tmp_path):
    r = subprocess.run([sys.executable, "-m", "step1_data_generation.build", "--config", "step1_data_generation/configs/train.yaml", "--n", "80",
                        "--out", str(tmp_path), "--set", "twins.enabled=true", "--set", "knockout.enabled=true"],
                       cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    rows = {json.loads(l)["case_id"]: json.loads(l) for l in (tmp_path / "cases.jsonl").read_text(encoding="utf-8").splitlines()}
    tw = [json.loads(l) for l in (tmp_path / "twins.jsonl").read_text(encoding="utf-8").splitlines()]
    ko = [json.loads(l) for l in (tmp_path / "knockouts.jsonl").read_text(encoding="utf-8").splitlines()]
    assert tw and ko
    for rec in tw:
        assert rows[rec["base_id"]]["expected"]["decision"] == rec["outcome_from"]
        assert rows[rec["twin_id"]]["expected"]["decision"] == rec["outcome_to"] != rec["outcome_from"]
        assert rows[rec["twin_id"]]["style"] == rows[rec["base_id"]]["style"]
    for rec in ko:
        assert rows[rec["knockout_id"]]["expected"]["decision"] == "escalate"
    m = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert m["n_twins"] == len(tw) and m["n_knockouts"] == len(ko) and m["n_base"] == 80
