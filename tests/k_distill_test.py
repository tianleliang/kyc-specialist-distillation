"""Tests for step4_distillation/ (Session K). Mock teacher/student outputs only; no API calls.

Data: Session A's PROVISIONAL draft cases (data/draft/cases.jsonl) with its schema and the
FieldMap Session C wrote for it, plus Session C's 60-case fixture with the default FieldMap,
to show the steps are schema-agnostic.
"""
from __future__ import annotations

import copy
import json
import random
from pathlib import Path

import pytest

from step4_distillation import arbitrate, hard_mine, matched_n, onpolicy, prefs, reject_sample, sft_floor
from step4_distillation.common import (CheckCfg, Checker, Sample, StudentPrompt, Tally, contamination_gate,
                            get_path, load_fieldmap, load_gold, load_samples, parent_path, read_jsonl,
                            refuse_eval_ids, set_path, write_jsonl, write_training_file)
from step5_training.common import validate_dpo, validate_sft

ROOT = Path(__file__).resolve().parents[1]
DRAFT = ROOT / "data/draft/cases.jsonl"
DRAFT_TRUTH = ROOT / "data/draft/truth.jsonl"
SCHEMA = ROOT / "step0_rules/schema/v0_provisional.json"
FM_DRAFT = ROOT / "tests/fixtures/c_fieldmap_v0_provisional.yaml"
C_GOLD = ROOT / "tests/fixtures/c_gold.jsonl"
C_SCHEMA = ROOT / "tests/fixtures/c_schema.json"

pytestmark = pytest.mark.skipif(not DRAFT.exists() or not SCHEMA.exists(), reason="Session A draft data missing")


@pytest.fixture(autouse=True)
def _no_repo_manifests(monkeypatch, tmp_path):
    # Run each test from an empty dir so a real frozen eval manifest in the repo can't leak in.
    monkeypatch.chdir(tmp_path)


@pytest.fixture(scope="module")
def fm():
    return load_fieldmap(str(FM_DRAFT), str(SCHEMA))


@pytest.fixture(scope="module")
def gold(fm):
    g = load_gold(DRAFT, fm)
    return dict(list(g.items())[:60])


def other(label, labels):
    return next(x for x in labels if x != label)


def flip_decision(e, fm):
    e = copy.deepcopy(e)
    e["decision"] = other(e["decision"], fm.decision_labels)
    return e


def flip_field(e, name="name"):
    e = copy.deepcopy(e)
    st = e["identity"][name]["status"]
    e["identity"][name]["status"] = "mismatch" if st != "mismatch" else "consistent"
    return e


def case_with_hit(gold):
    return next(cid for cid, g in gold.items() if g["expected"]["screening"])


def write_outputs(path, rows):
    write_jsonl(path, [{"case_id": cid, "output": json.dumps(o) if not isinstance(o, str) else o, **extra}
                       for cid, o, extra in rows])
    return str(path)


# ---------------------------------------------------------------------------
# common
# ---------------------------------------------------------------------------

def test_set_path_and_parent_path():
    obj = {"identity": {"findings": [{"field": "dob", "status": "consistent"}]}}
    assert set_path(obj, "identity.findings[field=dob].status", "mismatch")
    assert get_path(obj, "identity.findings[field=dob].status") == "mismatch"
    assert set_path(obj, "identity.findings[field=name].status", "consistent")   # appended
    assert get_path(obj, "identity.findings[field=name].status") == "consistent"
    assert set_path(obj, "a.b", 1) and obj["a"]["b"] == 1
    assert not set_path({"x": [1]}, "x.y", 2)
    assert parent_path("identity.name.status") == "identity.name"
    assert parent_path("identity.findings[field=dob].status") == "identity.findings[field=dob]"
    assert parent_path("decision") is None


def test_load_samples_all_formats(tmp_path):
    write_jsonl(tmp_path / "batch.jsonl", [
        {"custom_id": "x1", "metadata": {"case_id": "c1"}, "response": {"model": "m1", "text": "{}", "metadata": {}}},
        {"custom_id": "x2", "metadata": {"case_id": "c1"}, "response": {"model": "m1", "text": "{\"a\":1}"}},
    ])
    write_jsonl(tmp_path / "pred.jsonl", [{"case_id": "c2", "output": {"a": 2}}])
    write_jsonl(tmp_path / "sft.jsonl", [{"id": "s", "case_id": "c3", "source": "reject_sample", "teacher": "t9",
                                          "messages": [{"role": "user", "content": "p"},
                                                       {"role": "assistant", "content": "{\"a\":3}"}]}])
    ss = load_samples([str(tmp_path / "batch.jsonl"), str(tmp_path / "pred.jsonl") + "=stu",
                       str(tmp_path / "sft.jsonl")])
    assert [(s.case_id, s.teacher, s.sample) for s in ss] == [("c1", "m1", 0), ("c1", "m1", 1),
                                                                ("c2", "stu", 0), ("c3", "t9", 0)]
    assert ss[1].raw == "{\"a\":1}" and ss[2].raw == {"a": 2} and ss[3].raw == "{\"a\":3}"


def test_checker_oracle_passes_and_each_failure_is_named(fm, gold):
    ck = Checker(fm)
    cid = case_with_hit(gold)
    g = gold[cid]
    e = g["expected"]
    ok = ck.check(json.dumps(e), g)
    assert ok.passed and ok.score == pytest.approx(1.0), ok.details
    assert ck.check("{not json", g).reasons == ["unparseable"]
    bad = copy.deepcopy(e)
    bad["decision"] = "maybe"
    assert ck.check(bad, g).reasons == ["schema_invalid"]
    assert "decision" in ck.check(flip_decision(e, fm), g).reasons
    r = ck.check(flip_field(e), g)
    assert r.reasons == ["fields"] and any("name" in d for d in r.details)
    # field threshold: 1 wrong of 6 fields passes at 0.8
    assert Checker(fm, CheckCfg(min_field_acc=0.8)).check(flip_field(e), g).passed
    h = copy.deepcopy(e)
    h["screening"][0]["disposition"] = other(h["screening"][0]["disposition"], fm.screening_labels)
    r = ck.check(h, g)
    assert r.reasons == ["screening"] and h["screening"][0]["hit_id"] in r.details[0]
    rt = copy.deepcopy(e)
    rt["risk_tier"] = other(rt["risk_tier"], fm.risk_labels)
    assert "risk_tier" in ck.check(rt, g).reasons
    n = copy.deepcopy(e)
    n["narrative"][0]["evidence_refs"] = ["a sentence that is nowhere in the packet"]
    assert ck.check(n, g).reasons == ["evidence_refs"]
    assert Checker(fm, CheckCfg(evidence_refs="off")).check(n, g).passed
    a = copy.deepcopy(e)
    a["required_actions"] = []
    if e["required_actions"]:
        assert ck.check(a, g).passed                                   # actions off by default
        assert Checker(fm, CheckCfg(actions="superset")).check(a, g).reasons == ["actions"]


def test_checker_is_schema_agnostic_on_c_fixture():
    fm = load_fieldmap(None, str(C_SCHEMA))                            # default FieldMap = C's fixture schema
    g = read_jsonl(C_GOLD)[0]
    ck = Checker(fm, CheckCfg(evidence_refs="off"))
    assert ck.check(g["expected"], g).passed
    bad = copy.deepcopy(g["expected"])
    bad["identity"]["findings"][0]["status"] = "unreadable"
    assert ck.check(bad, g).reasons == ["fields"]


# ---------------------------------------------------------------------------
# contamination gate
# ---------------------------------------------------------------------------

def _freeze_eval(tmp_path, packet_rows):
    from step6_evaluation import split_guard as sg
    ev = tmp_path / "data/eval/eval_id.jsonl"
    write_jsonl(ev, packet_rows)
    sg.freeze([str(ev)], tmp_path / "data/eval/MANIFEST.json")
    return ev


def test_gate_skips_without_manifest_and_blocks_contaminated_file(tmp_path, gold, fm):
    rows = [sft_floor.sft_record("x", cid, StudentPrompt("sys"), g["packet"], g["expected"])
            for cid, g in list(gold.items())[:20]]
    t = Tally("t")
    write_training_file(tmp_path / "clean.jsonl", rows, None, t)
    assert t.extra["contamination_gate"]["checked"] is False
    # freeze eval made of 5 of these packets (auto-discovered under data/eval/)
    _freeze_eval(tmp_path, [{"case_id": f"eid-{i}", "packet": g["packet"]}
                            for i, g in enumerate(list(gold.values())[:5])])
    with pytest.raises(SystemExit, match="CONTAMINATION"):
        write_training_file(tmp_path / "dirty.jsonl", rows, None)
    assert not (tmp_path / "dirty.jsonl").exists() and not (tmp_path / "dirty.jsonl.tmp").exists()
    clean = rows[5:]
    t2 = Tally("t2")
    write_training_file(tmp_path / "ok.jsonl", clean, None, t2)
    assert t2.extra["contamination_gate"]["checked"] is True and (tmp_path / "ok.jsonl").exists()


def test_gate_refuses_changed_manifest_and_eval_ids(tmp_path, gold):
    ev = _freeze_eval(tmp_path, [{"case_id": "eid-0", "packet": "zzz qqq"}])
    ev.chmod(0o644)
    ev.write_text("tampered\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="does not verify"):
        contamination_gate([str(DRAFT)], None)
    with pytest.raises(SystemExit, match="eval case id"):
        refuse_eval_ids(["tr-1", "ood-000045"])


# ---------------------------------------------------------------------------
# sft_floor
# ---------------------------------------------------------------------------

def test_sft_floor_keeps_everything_but_unusable_rows(tmp_path, gold, fm):
    ids = list(gold)
    rows = [(cid, gold[cid]["expected"], {}) for cid in ids[:10]]
    rows[1] = (ids[1], flip_decision(gold[ids[1]]["expected"], fm), {})     # wrong: still kept (floor)
    rows[2] = (ids[2], "{broken", {})                                      # unparseable: kept as raw text
    rows.append((ids[0], gold[ids[0]]["expected"], {}))                    # second sample: dropped (first only)
    rows.append((ids[11], "", {"error": "HTTP 500"}))                      # API error: dropped
    rows.append(("not-in-gold", "{}", {}))
    out = write_outputs(tmp_path / "t.jsonl", rows)
    recs, tally = sft_floor.build(gold, load_samples([out + "=argon"]), StudentPrompt("SYS", "Packet:\n{packet}"),
                                  Checker(fm), fm)
    assert tally.kept == 10
    assert tally.dropped == {"extra_sample": 1, "api_error_or_empty": 1, "case_not_in_gold": 1}
    assert tally.extra["invalid_kept"] == {"unparseable": 1}
    validate_sft(recs)
    r0 = recs[0]
    assert r0["messages"][0] == {"role": "system", "content": "SYS"}
    assert r0["messages"][1]["content"] == "Packet:\n" + gold[ids[0]]["packet"]
    assert json.loads(r0["messages"][-1]["content"]) == gold[ids[0]]["expected"]
    recs2, t2 = sft_floor.build(gold, load_samples([out]), StudentPrompt(), Checker(fm), fm, require_schema=True)
    assert t2.kept == 9 and t2.dropped["unparseable"] == 1


def test_sft_floor_cli(tmp_path, gold, fm):
    ids = list(gold)[:5]
    out = write_outputs(tmp_path / "t.jsonl", [(c, gold[c]["expected"], {}) for c in ids])
    (tmp_path / "sys.txt").write_text("You adjudicate KYC cases.", encoding="utf-8")
    assert sft_floor.main(["--gold", str(DRAFT), "--fieldmap", str(FM_DRAFT), "--schema", str(SCHEMA),
                           "--teacher-outputs", out + "=argon", "--system-file", str(tmp_path / "sys.txt"),
                           "--out", str(tmp_path / "floor.jsonl")]) == 0
    recs = read_jsonl(tmp_path / "floor.jsonl")
    assert len(recs) == 5 and all(r["teacher"] == "argon" for r in recs)
    stats = json.loads((tmp_path / "floor.jsonl.stats.json").read_text(encoding="utf-8"))
    assert stats["kept"] == 5 and "contamination_gate" in stats


# ---------------------------------------------------------------------------
# reject_sample
# ---------------------------------------------------------------------------

def test_reject_sample_best_of_k_and_drop_reasons(tmp_path, gold, fm):
    ids = list(gold)[:6]
    e = {c: gold[c]["expected"] for c in ids}
    rows = [
        (ids[0], flip_decision(e[ids[0]], fm), {}), (ids[0], e[ids[0]], {}),      # 2nd sample passes
        (ids[1], flip_decision(e[ids[1]], fm), {}), (ids[1], flip_field(e[ids[1]]), {}),  # none pass
        (ids[2], e[ids[2]], {}),
        (ids[3], "{oops", {}),
    ]
    a = write_outputs(tmp_path / "a.jsonl", rows)
    b = write_outputs(tmp_path / "b.jsonl", [(ids[2], e[ids[2]], {}), (ids[4], e[ids[4]], {})])
    recs, rejects, tally = reject_sample.build(gold, load_samples([a + "=argon", b + "=sol"]), StudentPrompt(),
                                               Checker(fm), fm, priority=["sol", "argon"])
    validate_sft(recs)
    kept = {r["case_id"]: (r["teacher"], r["sample"]) for r in recs}
    assert kept == {ids[0]: ("argon", 1), ids[2]: ("sol", 0), ids[4]: ("sol", 0)}   # priority breaks the tie
    assert tally.dropped == {"no_passing_sample": 2}
    assert tally.extra["sample_failure_reasons"] == {"decision": 2, "fields": 1, "unparseable": 1}
    assert tally.extra["cases_with_samples"] == 5
    assert {r["case_id"] for r in rejects} == {ids[0], ids[1], ids[3]}
    assert sum(v["n"] for v in tally.extra["case_drop_rate_by_tag"].values()) >= 5
    recs_all, _, _ = reject_sample.build(gold, load_samples([a, b]), StudentPrompt(), Checker(fm), fm, keep="all")
    assert len(recs_all) == 4


def test_reject_sample_cli_and_matched_n_control(tmp_path, gold, fm):
    ids = list(gold)[:20]
    rng = random.Random(1)
    rows = [(c, flip_decision(gold[c]["expected"], fm) if rng.random() < 0.4 else gold[c]["expected"], {}) for c in ids]
    t = write_outputs(tmp_path / "t.jsonl", rows)
    common = ["--gold", str(DRAFT), "--fieldmap", str(FM_DRAFT), "--schema", str(SCHEMA), "--teacher-outputs", t]
    assert sft_floor.main(common + ["--out", str(tmp_path / "floor.jsonl")]) == 0
    assert reject_sample.main(common + ["--out", str(tmp_path / "rej.jsonl"),
                                        "--rejects-out", str(tmp_path / "rej.fail.jsonl")]) == 0
    n_rej = len(read_jsonl(tmp_path / "rej.jsonl"))
    assert 0 < n_rej < 20 and len(read_jsonl(tmp_path / "rej.fail.jsonl")) == 20 - n_rej
    assert matched_n.main(["--pool", str(tmp_path / "floor.jsonl"), "--like", str(tmp_path / "rej.jsonl"),
                           "--out", str(tmp_path / "ctrl.jsonl")]) == 0
    ctrl = read_jsonl(tmp_path / "ctrl.jsonl")
    assert len(ctrl) == n_rej and ctrl == matched_n.draw(read_jsonl(tmp_path / "floor.jsonl"), n_rej, 17)


# ---------------------------------------------------------------------------
# arbitrate
# ---------------------------------------------------------------------------

def _teachers(tmp_path, gold, fm, edits):
    """edits: teacher -> fn(expected, cid) -> output."""
    specs = []
    for t, fn in edits.items():
        specs.append(write_outputs(tmp_path / f"{t}.jsonl", [(c, fn(g["expected"], c), {}) for c, g in gold.items()]) + f"={t}")
    return load_samples(specs)


def test_arbitrate_gold_select_picks_closest(tmp_path, gold, fm):
    ss = _teachers(tmp_path, gold, fm, {"a": lambda e, c: flip_decision(e, fm), "b": lambda e, c: flip_field(e),
                                        "c": lambda e, c: flip_decision(flip_field(e), fm)})
    recs, tally = arbitrate.build(gold, ss, StudentPrompt(), Checker(fm), fm, mode="gold_select")
    assert tally.kept == len(gold) and tally.extra["winners"] == {"b": len(gold)}   # field error costs less
    recs2, t2 = arbitrate.build(gold, ss, StudentPrompt(), Checker(fm), fm, mode="gold_select", require_pass=True)
    assert t2.kept == 0 and t2.dropped["no_teacher_passes"] == len(gold)
    validate_sft(recs)


def test_arbitrate_vote_fixes_outvoted_units_and_reports_agreement(tmp_path, gold, fm):
    ss = _teachers(tmp_path, gold, fm, {"a": lambda e, c: e, "b": lambda e, c: e,
                                        "c": lambda e, c: flip_field(flip_decision(e, fm))})
    recs, tally = arbitrate.build(gold, ss, StudentPrompt(), Checker(fm), fm, mode="vote", priority=["c", "a", "b"])
    assert tally.kept == len(gold)
    for r in recs:
        assert json.loads(r["messages"][-1]["content"]) == gold[r["case_id"]]["expected"]
        assert r["provenance"]["base"] in ("a", "b")                  # c is outvoted everywhere
    ag = tally.extra["agreement"]
    assert ag["pairwise"]["decision:a~b"]["rate"] == 1.0 and ag["pairwise"]["decision:a~c"]["rate"] == 0.0
    assert ag["vs_gold"]["decision:c"]["rate"] == 0.0 and ag["all_agree"]["decision"]["rate"] == 0.0
    assert tally.extra["vote_vs_gold_decision"] == [len(gold), len(gold)]


def test_arbitrate_vote_two_teachers_tie(tmp_path, gold, fm):
    ss = _teachers(tmp_path, gold, fm, {"a": lambda e, c: e, "b": lambda e, c: flip_decision(e, fm)})
    _, t = arbitrate.build(gold, ss, StudentPrompt(), Checker(fm), fm, mode="vote", tie="drop")
    assert t.kept == 0 and t.dropped == {"vote_tie:decision": len(gold)}
    recs, t = arbitrate.build(gold, ss, StudentPrompt(), Checker(fm), fm, mode="vote", priority=["a", "b"])
    assert t.kept == len(gold)
    assert all(json.loads(r["messages"][-1]["content"]) == gold[r["case_id"]]["expected"] for r in recs)


def test_arbitrate_splice_combines_complementary_teachers(tmp_path, gold, fm):
    hit_case = case_with_hit(gold)

    def a(e, c):          # right decision, wrong name finding (whole unit incl. reason is wrong)
        e = flip_field(e)
        e["identity"]["name"]["reason"] = "TEACHER A REASON"
        return e

    def b(e, c):          # wrong decision, wrong first hit
        e = flip_decision(e, fm)
        if e["screening"]:
            e["screening"][0]["disposition"] = other(e["screening"][0]["disposition"], fm.screening_labels)
        return e

    ss = _teachers(tmp_path, gold, fm, {"a": a, "b": b})
    recs, tally = arbitrate.build(gold, ss, StudentPrompt(), Checker(fm), fm, mode="splice")
    # hit cases: a supplies decision + hit, b supplies the name unit -> passes; no hit: same
    assert tally.kept == len(gold), tally.dropped
    by = {r["case_id"]: r for r in recs}
    out = json.loads(by[hit_case]["messages"][-1]["content"])
    exp = gold[hit_case]["expected"]
    assert out["decision"] == exp["decision"] and out["identity"]["name"] == exp["identity"]["name"]
    assert out["screening"][0]["disposition"] == exp["screening"][0]["disposition"]
    assert by[hit_case]["provenance"]["units"]["field:name"] == "b"
    assert by[hit_case]["provenance"]["units"]["narrative"] == "a"             # b's decision is wrong


def test_arbitrate_splice_repair_and_label_audit(tmp_path, gold, fm):
    ss = _teachers(tmp_path, gold, fm, {"a": lambda e, c: flip_decision(e, fm), "b": lambda e, c: flip_decision(e, fm)})
    _, t = arbitrate.build(gold, ss, StudentPrompt(), Checker(fm), fm, mode="splice")
    assert t.kept == 0 and t.dropped == {"no_teacher_right:decision": len(gold)}
    assert t.extra["agreement"]["label_audit_count"] == len(gold)
    # repair=gold fixes the decision label but the narrative's teacher decided differently
    _, t2 = arbitrate.build(gold, ss, StudentPrompt(), Checker(fm), fm, mode="splice", repair="gold")
    assert t2.dropped == {"no_grounded_consistent_narrative": len(gold)}
    ss3 = _teachers(tmp_path, gold, fm, {"a": lambda e, c: flip_field(e), "b": lambda e, c: flip_field(e)})
    recs3, t3 = arbitrate.build(gold, ss3, StudentPrompt(), Checker(fm), fm, mode="splice", repair="gold")
    assert t3.kept == len(gold) and all(r["provenance"]["repaired"] == ["field:name"] for r in recs3)


def test_arbitrate_cli(tmp_path, gold, fm):
    ids = list(gold)[:8]
    a = write_outputs(tmp_path / "a.jsonl", [(c, gold[c]["expected"], {}) for c in ids])
    b = write_outputs(tmp_path / "b.jsonl", [(c, flip_decision(gold[c]["expected"], fm), {}) for c in ids])
    assert arbitrate.main(["--mode", "splice", "--gold", str(DRAFT), "--fieldmap", str(FM_DRAFT), "--schema", str(SCHEMA),
                           "--teacher-outputs", a + "=a", "--teacher-outputs", b + "=b",
                           "--out", str(tmp_path / "s.jsonl"), "--report", str(tmp_path / "agree.json")]) == 0
    assert len(read_jsonl(tmp_path / "s.jsonl")) == 8
    assert json.loads((tmp_path / "agree.json").read_text())["pairwise"]["decision:a~b"]["rate"] == 0.0


# ---------------------------------------------------------------------------
# hard_mine
# ---------------------------------------------------------------------------

def _student_preds(gold, fm, bad_scenario, p_bad=0.9, p_other=0.05, seed=0):
    rng = random.Random(seed)
    out = []
    for cid, g in gold.items():
        bad = bad_scenario in g["scenarios"]
        e = flip_decision(g["expected"], fm) if rng.random() < (p_bad if bad else p_other) else g["expected"]
        out.append({"case_id": cid, "output": e})
    return out


def test_hard_mine_ranks_failing_scenario_first_and_upweights_it(tmp_path, fm):
    gold = load_gold(DRAFT, fm)
    target = "prompt_injection"
    preds = _student_preds(gold, fm, target)
    fails = hard_mine.failures(gold, preds, Checker(fm), fm, "any")
    cats, src = hard_mine.categories(fails, gold, {}, fm, "knobs")
    assert src == "scenarios"
    rows, base = hard_mine.rank(fails, cats, min_n=5)
    assert rows[0]["category"] == f"scenario={target}" and rows[0]["lift"] > 2
    base_mix = {s: 1.0 for s in {g["scenarios"][0] for g in gold.values()}}
    mix = hard_mine.resample_mix(fails, gold, fm, base_mix, alpha=1.0, floor=0.25)
    assert mix[target] == max(mix.values()) and mix[target] > 1.0
    assert sum(mix.values()) == pytest.approx(sum(base_mix.values()), rel=1e-3)
    assert all(w > 0 for w in mix.values())
    flat = hard_mine.resample_mix(fails, gold, fm, base_mix, alpha=0.0)
    assert all(w == pytest.approx(1.0) for w in flat.values())


def test_hard_mine_uses_knob_vectors_when_present(fm):
    gold = dict(list(load_gold(DRAFT, fm).items())[:40])
    truths = {cid: {"knobs": {"style": "prose" if i % 2 else "kv", "ocr_rate": i / 40, "flags": ["x"]}}
              for i, cid in enumerate(gold)}
    preds = [{"case_id": cid, "output": flip_decision(g["expected"], fm) if truths[cid]["knobs"]["style"] == "prose"
              else g["expected"]} for cid, g in gold.items()]
    fails = hard_mine.failures(gold, preds, Checker(fm), fm, "decision")
    cats, src = hard_mine.categories(fails, gold, truths, fm, "knobs")
    assert src == "knobs"
    assert {"style=prose", "flags=x"} <= set(cats[next(iter(gold))]) | {"style=prose"}
    assert any(c.startswith("ocr_rate=") and c.split("=")[1] in ("low", "mid", "high") for c in cats[next(iter(gold))])
    rows, _ = hard_mine.rank(fails, cats, 5)
    assert rows[0]["category"] == "style=prose" and rows[0]["fail_rate"] == 1.0


def test_hard_mine_cli_and_refuses_eval(tmp_path, fm):
    gold = load_gold(DRAFT, fm)
    p = tmp_path / "preds.jsonl"
    write_jsonl(p, _student_preds(gold, fm, "partial_dob"))
    assert hard_mine.main(["--gold", str(DRAFT), "--truth", str(DRAFT_TRUTH), "--predictions", str(p),
                           "--fieldmap", str(FM_DRAFT), "--schema", str(SCHEMA),
                           "--mix-out", str(tmp_path / "mix.yaml"), "--report", str(tmp_path / "r.md")]) == 0
    import yaml
    out = yaml.safe_load((tmp_path / "mix.yaml").read_text(encoding="utf-8"))
    assert out["mix"]["partial_dob"] == max(out["mix"].values())
    assert set(out["mix"]) >= {"clean", "partial_dob"}                 # base = step1_data_generation.sample.DEFAULT_MIX
    assert "| scenario=partial_dob |" in (tmp_path / "r.md").read_text(encoding="utf-8")
    # an eval-frozen gold file is refused
    from step6_evaluation import split_guard as sg
    ev = tmp_path / "data/eval/e.jsonl"
    ev.parent.mkdir(parents=True)
    ev.write_bytes(DRAFT.read_bytes())
    sg.freeze([str(ev)], tmp_path / "data/eval/MANIFEST.json")
    with pytest.raises(SystemExit, match="frozen eval file"):
        hard_mine.main(["--gold", str(ev), "--predictions", str(p), "--fieldmap", str(FM_DRAFT),
                        "--mix-out", str(tmp_path / "m2.yaml")])


# ---------------------------------------------------------------------------
# prefs
# ---------------------------------------------------------------------------

def test_prefs_programmatic_pairs(tmp_path, gold, fm):
    ids = list(gold)[:10]
    teacher = write_outputs(tmp_path / "t.jsonl", [(c, gold[c]["expected"], {}) for c in ids[:8]])
    stu_rows = []
    for i, c in enumerate(ids):
        e = gold[c]["expected"]
        if i < 3:                                    # student right: no pair
            stu_rows.append((c, e, {}))
        else:                                        # two failing samples: near-miss and far
            stu_rows.append((c, flip_decision(flip_field(e), fm), {}))
            stu_rows.append((c, flip_field(e), {}))
    stu = write_outputs(tmp_path / "s.jsonl", stu_rows)
    recs, tally = prefs.programmatic(gold, load_samples([teacher + "=argon"]), load_samples([stu + "=student"]),
                                     StudentPrompt("S"), Checker(fm), fm)
    validate_dpo(recs)
    assert tally.kept == 5                            # ids 3..7 (8, 9 have no teacher output)
    assert tally.dropped == {"student_passes": 3, "no_passing_chosen": 2}
    for r in recs:
        assert json.loads(r["chosen"]) == gold[r["case_id"]]["expected"]
        assert r["rejected_reasons"] == ["fields"]   # hardest = near-miss
        assert r["prompt"][-1]["role"] == "user"
    recs_all, _ = prefs.programmatic(gold, load_samples([teacher]), load_samples([stu]), StudentPrompt(), Checker(fm), fm,
                                     pick="all", max_pairs=2)
    assert len(recs_all) == 10


def _mock_client(responder):
    from shared.frontier_api.clients import LLMClient
    return LLMClient(mock=True, mock_responder=responder, cache_dir=None,
                     rpm={"anthropic": 1e9, "gemini": 1e9, "openai": 1e9})


def test_prefs_judge_keeps_only_position_consistent_verdicts(gold, fm, tmp_path):
    ids = list(gold)[:6]
    rows = []
    for c in ids:
        e = gold[c]["expected"]
        short = copy.deepcopy(e)
        short["narrative"][-1]["sentence"] = short["narrative"][-1]["sentence"][:12]
        rows += [(c, e, {}), (c, short, {})]
    cands = load_samples([write_outputs(tmp_path / "c.jsonl", rows) + "=student"])

    def prefers_longer(req):
        text = req.messages[0]["content"]
        a = text.split("OUTPUT A:\n", 1)[1].split("\n\nOUTPUT B:\n")[0]
        b = text.split("OUTPUT B:\n", 1)[1].split("\n\nReturn JSON")[0]
        return {"winner": "A" if len(a) > len(b) else "B", "reason": "more complete"}

    recs, t = prefs.judge(gold, cands, StudentPrompt(), Checker(fm), fm, _mock_client(prefers_longer),
                          provider="anthropic", model="claude-opus-5-5")
    validate_dpo(recs)
    assert t.kept == 6 and t.extra["judge_calls"] == 12
    assert all(len(r["chosen"]) > len(r["rejected"]) for r in recs)
    recs, t = prefs.judge(gold, cands, StudentPrompt(), Checker(fm), fm,
                          _mock_client(lambda req: {"winner": "A", "reason": "first"}),
                          provider="anthropic", model="claude-opus-5-5")
    assert t.kept == 0 and t.dropped == {"position_inconsistent": 6}


# ---------------------------------------------------------------------------
# onpolicy
# ---------------------------------------------------------------------------

def test_onpolicy_requests_hide_gold_and_loop_produces_corrections(tmp_path, gold, fm):
    ids = list(gold)[:8]
    stu = load_samples([write_outputs(tmp_path / "s.jsonl",
                                      [(c, gold[c]["expected"] if i < 3 else flip_decision(gold[c]["expected"], fm), {})
                                       for i, c in enumerate(ids)]) + "=student"])
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    reqs, rt = onpolicy.make_requests(gold, stu, Checker(fm), fm, provider="gemini", model="gemini-4-argon",
                                      schema=schema, system="T")
    assert len(reqs) == 5 and rt.dropped == {"student_passes": 3}
    for q in reqs:
        cid = q.metadata["case_id"]
        assert q.purpose == "teacher" and q.json_schema == schema
        assert "decision: got" in q.messages[0]["content"]
        assert "REFERENCE ANSWER" not in q.messages[0]["content"]
        assert gold[cid]["packet"] in q.messages[0]["content"]
    reqs_g, _ = onpolicy.make_requests(gold, stu, Checker(fm), fm, provider="gemini", model="m", schema=None,
                                       system=None, reveal_gold=True)
    assert "REFERENCE ANSWER" in reqs_g[0].messages[0]["content"]

    # mock teacher: fixes 4 of 5, the 5th correction is still wrong
    bad = reqs[-1].metadata["case_id"]

    def teacher(req):
        cid = req.metadata["case_id"]
        return flip_decision(gold[cid]["expected"], fm) if cid == bad else gold[cid]["expected"]

    rows = onpolicy.run(reqs, _mock_client(teacher))
    corr = tmp_path / "corr.jsonl"
    write_jsonl(corr, rows)
    sft, pairs, tally = onpolicy.collect(gold, stu, load_samples([str(corr)]), StudentPrompt("S"), Checker(fm), fm)
    validate_sft(sft)
    validate_dpo(pairs)
    assert tally.kept == 4 and tally.dropped == {"correction_fails:decision": 1}
    assert len(pairs) == 4 and all(r["corrected_from"] == ["decision"] for r in sft)
    assert all(r["teacher"] == "gemini-4-argon" for r in sft)


def test_onpolicy_cli_requests_and_collect(tmp_path, gold, fm):
    ids = list(gold)[:4]
    s = write_outputs(tmp_path / "s.jsonl", [(c, flip_decision(gold[c]["expected"], fm), {}) for c in ids])
    base = ["--gold", str(DRAFT), "--fieldmap", str(FM_DRAFT), "--schema", str(SCHEMA), "--student", s]
    assert onpolicy.main(["requests", *base, "--teacher-provider", "openai", "--teacher-model", "gpt-6.1-sol",
                          "--out", str(tmp_path / "reqs.jsonl")]) == 0
    reqs = read_jsonl(tmp_path / "reqs.jsonl")
    assert len(reqs) == 4 and reqs[0]["metadata"]["failed"] == ["decision"]
    c = write_outputs(tmp_path / "c.jsonl", [(cid, gold[cid]["expected"], {"model": "gpt-6.1-sol"}) for cid in ids])
    assert onpolicy.main(["collect", *base, "--corrections", c, "--out", str(tmp_path / "op.jsonl"),
                          "--pairs-out", str(tmp_path / "op_pairs.jsonl")]) == 0
    assert len(read_jsonl(tmp_path / "op.jsonl")) == 4 and len(read_jsonl(tmp_path / "op_pairs.jsonl")) == 4


def test_onpolicy_guard_refuses_teacher_request_overlapping_eval(tmp_path, gold, fm):
    from shared.frontier_api.clients import ContaminationError, make_request  # noqa: F401
    pk = next(iter(gold.values()))["packet"]
    _freeze_eval(tmp_path, [{"case_id": "eid-0", "packet": pk}])
    client = onpolicy.make_client(True, None)
    req = make_request("gemini", "m", "PACKET:\n" + pk, purpose="teacher")
    with pytest.raises(Exception, match="(?i)eval|contamin"):
        client.complete(req, use_cache=False)


def test_sample_dataclass_key():
    assert Sample("c", "t", 2, "{}").key == "c|t|2"


# ---------------------------------------------------------------------------
# twins_filter
# ---------------------------------------------------------------------------

def test_twins_filter_keeps_pairs_only_when_both_twins_pass(tmp_path, gold, fm):
    from step4_distillation import twins_filter
    # fake twin pairs: consecutive cases with different gold decisions share a pair id
    ids = list(gold)
    pairs, used = [], set()
    for x in ids:
        if x in used:
            continue
        y = next((c for c in ids if c not in used and c != x
                  and gold[c]["expected"]["decision"] != gold[x]["expected"]["decision"]), None)
        if y:
            pairs.append((x, y))
            used |= {x, y}
        if len(pairs) == 3:
            break
    tg = {}
    for i, (x, y) in enumerate(pairs):
        for c in (x, y):
            tg[c] = {**gold[c], "pair_id": f"p{i}"}
    (p0a, p0b), (p1a, p1b), (p2a, p2b) = pairs
    out = write_outputs(tmp_path / "t.jsonl", [
        (p0a, tg[p0a]["expected"], {}), (p0b, tg[p0b]["expected"], {}),                 # both right
        (p1a, tg[p1a]["expected"], {}), (p1b, tg[p1a]["expected"], {}),                 # no flip on twin b
        (p2a, flip_decision(tg[p2a]["expected"], fm), {}), (p2b, flip_field(tg[p2b]["expected"]), {}),
    ])
    sft, dpo, t = twins_filter.build(tg, load_samples([out + "=argon"]), StudentPrompt(), Checker(fm), fm)
    validate_sft(sft)
    validate_dpo(dpo)
    assert t.kept == 1 and t.dropped == {"one_twin_fails": 1, "both_twins_fail": 1}
    assert {r["case_id"] for r in sft} == {p0a, p0b} and len(dpo) == 2
    assert json.loads(dpo[0]["rejected"])["decision"] != json.loads(dpo[0]["chosen"])["decision"]
    assert t.extra["teacher_flip_consistency"] == pytest.approx(1 / 3, abs=1e-3)
    assert t.extra["gold_decision_flips"] == 3


# ---------------------------------------------------------------------------
# teacher_requests -> shared.frontier_api.batch (mock) -> sft_floor: the formats connect
# ---------------------------------------------------------------------------

def test_teacher_requests_roundtrip_through_mock_batch(tmp_path, gold, fm):
    from step4_distillation import teacher_requests
    from shared.frontier_api.batch import BatchRunner
    from shared.frontier_api.clients import LLMClient, LLMRequest

    sub = dict(list(gold.items())[:4])
    rows = teacher_requests.build(sub, fm, StudentPrompt("TEACH"), provider="gemini", model="gemini-4-argon",
                                  k=2, schema=json.loads(SCHEMA.read_text(encoding="utf-8")), teacher_name="argon")
    reqs = [LLMRequest.from_dict(r) for r in rows]
    assert len(reqs) == 8 and len({q.cache_key() for q in reqs}) == 8      # k samples are distinct
    assert all(q.purpose == "teacher" and q.reasoning_effort == "low" and q.system == "TEACH" for q in reqs)
    client = LLMClient(mock=True, cache_dir=None,
                       mock_responder=lambda q: sub[q.metadata["case_id"]]["expected"])
    runner = BatchRunner(str(tmp_path / "job"), client=client)
    runner.add(reqs)
    runner.run(poll_interval=0.01)
    write_jsonl(tmp_path / "res.jsonl", runner.results())
    ss = load_samples([str(tmp_path / "res.jsonl")])
    assert sorted((s.case_id, s.teacher, s.sample) for s in ss) == sorted((c, "argon", i) for c in sub for i in (0, 1))
    recs, _, t = reject_sample.build(sub, ss, StudentPrompt(), Checker(fm), fm)
    assert t.kept == 4 and t.extra["teacher_pass_rate"] == {"argon": 1.0}


def test_sft_floor_from_gold_control(tmp_path):
    assert sft_floor.main(["--gold", str(DRAFT), "--fieldmap", str(FM_DRAFT), "--schema", str(SCHEMA),
                           "--from-gold", "--out", str(tmp_path / "gold_sft.jsonl")]) == 0
    recs = read_jsonl(tmp_path / "gold_sft.jsonl")
    g = read_jsonl(DRAFT)
    assert len(recs) == len(g) and all(r["teacher"] == "gold" for r in recs)
    assert json.loads(recs[0]["messages"][-1]["content"]) == g[0]["expected"]
