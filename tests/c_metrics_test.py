"""Session C: unit tests for step6_evaluation/metrics.py."""
import json
import math
from pathlib import Path

import pytest

from step6_evaluation import metrics as M

FIX = Path(__file__).parent / "fixtures"
SCHEMA = FIX / "c_schema.json"


def gold_case(cid="c1", decision="escalate", risk="medium", hits=None, actions=None, tags=None,
              statuses=None, verified=False):
    statuses = statuses or {"name": "consistent", "dob": "mismatch", "document_number": "consistent",
                            "expiry": "consistent", "address": "unreadable"}
    return {
        "case_id": cid,
        "tags": tags or [],
        "packet": "APPLICANT: Tolvan Prenwick\nDOB: 1971-02-03\nPASSPORT NO: X1234567",
        "ref_ids": ["profile.name"],
        "expected": {
            "identity": {"verified": verified,
                         "findings": [{"field": f, "status": s, "reason": "r"} for f, s in statuses.items()]},
            "screening": hits if hits is not None else [
                {"hit_id": "H1", "disposition": "false_positive", "evidence": "e"},
                {"hit_id": "H2", "disposition": "needs_review", "evidence": "e"}],
            "risk_tier": risk,
            "risk_drivers": [],
            "required_actions": actions if actions is not None else ["senior_approval", "request_new_poa"],
            "decision": decision,
            "narrative": [
                {"sentence": "Applicant is Tolvan Prenwick.", "evidence_refs": ["APPLICANT: Tolvan Prenwick"]},
                {"sentence": "Name on file.", "evidence_refs": ["profile.name"]},
            ],
        },
    }


def pred_for(gold, **overrides):
    out = json.loads(json.dumps(gold["expected"]))
    out.update(overrides)
    return {"case_id": gold["case_id"], "output": json.dumps(out), "latency_ms": 100.0,
            "usage": {"input_tokens": 1000, "output_tokens": 500}}


@pytest.fixture
def fm():
    return M.FieldMap(schema_path=str(SCHEMA))


@pytest.fixture
def validator(fm):
    return M.make_validator(fm.schema_path)


# ---------------- paths and labels ----------------

def test_get_path_variants():
    obj = {"a": {"b": [{"k": "X", "v": 1}, {"k": "y z", "v": 2}]}, "c": [10, 20]}
    assert M.get_path(obj, "a.b[k=x].v") == 1
    assert M.get_path(obj, "a.b[k=Y-Z].v") == 2       # selector values are label-normalized
    assert M.get_path(obj, "c[1]") == 20
    assert M.get_path(obj, "c[-1]") == 20
    assert M.get_path(obj, "c[5]") is M.MISSING
    assert M.get_path(obj, "a.b[k=nope].v") is M.MISSING
    assert M.get_path(obj, "a.zz") is M.MISSING
    assert M.get_path(obj, "c.x") is M.MISSING
    assert M.get_path(obj, "") is obj


def test_norm_label():
    assert M.norm_label(" True Match ") == "true_match"
    assert M.norm_label("false-positive") == "false_positive"
    assert M.norm_label(True) == "true"
    assert M.norm_label(None) is M.MISSING
    assert M.norm_label("tm", {"tm": "true_match"}) == "true_match"


def test_fieldmap_rejects_unknown_keys(tmp_path):
    with pytest.raises(ValueError):
        M.FieldMap.from_dict({"decison_path": "x"})
    p = tmp_path / "fm.yaml"
    p.write_text("decision_path: outcome\nactions_item_key: code\n", encoding="utf-8")
    fm = M.FieldMap.load(p)
    assert fm.decision_path == "outcome" and fm.actions_item_key == "code"


# ---------------- parsing and validity ----------------

def test_parse_output():
    assert M.parse_output('{"a": 1}') == ({"a": 1}, None)
    assert M.parse_output('{"a": ')[0] is None
    assert M.parse_output("[1, 2]")[0] is None
    assert M.parse_output(None)[0] is None
    fenced = '```json\n{"a": 1}\n```'
    assert M.parse_output(fenced)[0] is None                 # strict by default
    assert M.parse_output(fenced, strip_code_fences=True)[0] == {"a": 1}


def test_validator(validator):
    g = gold_case()
    assert validator(g["expected"]) is None
    bad = dict(g["expected"], decision="maybe")
    assert validator(bad).startswith("schema:")
    assert M.make_validator(None)({"anything": 1}) is None


# ---------------- per-case scoring ----------------

def test_oracle_case_scores_perfect(fm, validator):
    g = gold_case()
    s = M.score_case(g, pred_for(g), fm, validator)
    assert s.valid and s.error is None
    assert s.decision == ("escalate", "escalate")
    assert all(gl == p for gl, p in s.hits)
    assert all(gl == p for gl, p in s.fields.values())
    assert s.actions_tp == s.actions_gold == s.actions_pred == 2
    assert s.sentences == 2 and s.unsupported == 0


def test_invalid_case_scores_zero(fm, validator):
    g = gold_case()
    for pred in [None, {"case_id": "c1", "output": "{not json"},
                 pred_for(g, decision="maybe")]:          # schema-invalid
        s = M.score_case(g, pred, fm, validator)
        assert not s.valid
        agg = M.aggregate([s], fm)
        assert agg["schema_validity"] == 0
        assert agg["decision_accuracy"] == 0
        assert agg["screening_macro_f1"] == 0
        assert agg["field_accuracy_mean"] == 0
        assert agg["risk_exact"] == 0 and agg["risk_within_one"] == 0
        assert agg["actions_recall"] == 0
        assert agg["actions_precision"] is None           # no predicted actions at all
        assert agg["unsupported_rate"] is None            # no narrative to check


def test_missing_value_in_valid_output_is_wrong(fm):
    g = gold_case()
    out = json.loads(json.dumps(g["expected"]))
    del out["decision"]
    out["screening"] = out["screening"][:1] + [{"hit_id": "H9", "disposition": "true_match", "evidence": ""}]
    s = M.score_case(g, {"case_id": "c1", "output": out}, fm)  # no validator: lenient
    assert s.valid
    assert s.decision == ("escalate", M.ABSENT)
    assert s.hits[1] == ("needs_review", M.ABSENT)
    assert s.extra_hits == 1


def test_missing_gold_value_drops_case_from_that_metric(fm):
    g = gold_case()
    del g["expected"]["risk_tier"]
    agg = M.aggregate([M.score_case(g, pred_for(g), fm)], fm)
    assert agg["n_risk"] == 0 and agg["risk_exact"] is None
    assert agg["decision_accuracy"] == 1.0


def test_score_run_counts_missing_and_duplicates(fm, validator):
    golds = [gold_case("a"), gold_case("b"), gold_case("c")]
    preds = [pred_for(golds[0]), pred_for(golds[0]), pred_for(golds[1]), {"case_id": "zzz", "output": "{}"}]
    scores, diag = M.score_run(golds, preds, fm, validator)
    assert len(scores) == 3
    assert diag == {**diag, "missing_predictions": 1, "duplicate_predictions": 1, "unknown_case_ids": 1}
    assert M.aggregate(scores, fm)["decision_accuracy"] == pytest.approx(2 / 3)


# ---------------- aggregate metrics ----------------

def test_macro_f1_hand_computed():
    labels = ["true_match", "false_positive", "needs_review"]
    pairs = [("true_match", "true_match"), ("true_match", "false_positive"),
             ("false_positive", "false_positive"), ("needs_review", "false_positive")]
    # TM: tp1 fp0 fn1 -> 2/3 ; FP: tp1 fp2 fn0 -> 2/4 ; NR: tp0 fp0 fn1 -> 0
    assert M.macro_f1(pairs, labels) == pytest.approx((2 / 3 + 0.5 + 0) / 3)
    # classes absent from gold and prediction are excluded
    assert M.macro_f1([("true_match", "true_match")], labels) == 1.0
    assert M.macro_f1([], labels) is None
    # invalid predictions are false negatives, not false positives
    assert M.macro_f1([("true_match", M.INVALID)], labels) == 0.0


def test_confusion_matrix():
    rows, cols, m = M.confusion_matrix(
        [("approve", "approve"), ("approve", "escalate"), ("reject", M.INVALID), ("reject", "weird")],
        ["approve", "reject", "escalate"])
    assert m[0][cols.index("approve")] == 1 and m[0][cols.index("escalate")] == 1
    assert m[1][cols.index(M.INVALID)] == 1 and m[1][cols.index("(other)")] == 1


def test_risk_within_one(fm):
    cases = []
    for gold, pred in [("low", "low"), ("low", "medium"), ("low", "high"), ("high", "medium")]:
        g = gold_case(risk=gold)
        cases.append(M.score_case(g, pred_for(g, risk_tier=pred), fm))
    agg = M.aggregate(cases, fm)
    assert agg["risk_exact"] == 0.25
    assert agg["risk_within_one"] == 0.75


def test_actions_recall_precision(fm):
    g1 = gold_case("a", actions=["senior_approval", "request_new_poa"])
    g2 = gold_case("b", actions=[])
    s1 = M.score_case(g1, pred_for(g1, required_actions=["senior_approval", "enhanced_monitoring"]), fm)
    s2 = M.score_case(g2, pred_for(g2, required_actions=["request_new_id"]), fm)
    agg = M.aggregate([s1, s2], fm)
    assert agg["actions_recall"] == 0.5           # 1 of 2 gold actions found
    assert agg["actions_precision"] == pytest.approx(1 / 3)  # 1 of 3 predicted correct


def test_actions_item_key():
    fm = M.FieldMap(actions_item_key="code")
    g = gold_case()
    g["expected"]["required_actions"] = [{"code": "A"}, {"code": "B"}]
    s = M.score_case(g, pred_for(g, required_actions=[{"code": "a"}]), fm)
    assert (s.actions_tp, s.actions_gold, s.actions_pred) == (1, 2, 1)


def test_adversarial_escalation(fm):
    g1 = gold_case("a", tags=["prompt_injection"])
    g2 = gold_case("b", tags=["insufficient_evidence"])
    g3 = gold_case("c", tags=["prompt_injection", "insufficient_evidence"])
    g4 = gold_case("d")
    scores = [M.score_case(g1, pred_for(g1, decision="approve"), fm),
              M.score_case(g2, pred_for(g2), fm),
              M.score_case(g3, pred_for(g3), fm),
              M.score_case(g4, pred_for(g4, decision="approve"), fm)]
    agg = M.aggregate(scores, fm)
    assert agg["n_adv.injection"] == 2 and agg["adv_escalation_rate.injection"] == 0.5
    assert agg["n_adv.ambiguous"] == 2 and agg["adv_escalation_rate.ambiguous"] == 1.0
    assert agg["n_adv"] == 3 and agg["adv_escalation_rate"] == pytest.approx(2 / 3)  # union, no double count
    assert agg["adv_decision_accuracy"] == pytest.approx(2 / 3)


def test_latency_and_cost(fm):
    golds = [gold_case(str(i)) for i in range(20)]
    preds = []
    for i, g in enumerate(golds):
        p = pred_for(g)
        p["latency_ms"] = float(i + 1)
        preds.append(p)
    price = {"input_per_mtok": 2.0, "output_per_mtok": 10.0}
    scores, _ = M.score_run(golds, preds, fm, price=price, price_multiplier=0.5)
    agg = M.aggregate(scores, fm)
    assert agg["latency_p50_ms"] == pytest.approx(10.5)
    assert agg["latency_p95_ms"] == pytest.approx(19.05)
    # (1000*2 + 500*10)/1e6 * 0.5 = 0.0035 per case -> 3.5 per 1k
    assert agg["cost_per_1k_usd"] == pytest.approx(3.5)


def test_gpu_cost_and_openai_usage_names():
    assert M.case_cost(None, 3600_000.0, {"usd_per_hour": 0.8, "concurrency": 4}) == pytest.approx(0.2)
    assert M.case_cost({"prompt_tokens": 1e6, "completion_tokens": 0}, None,
                       {"input_per_mtok": 3.0, "output_per_mtok": 9.0}) == pytest.approx(3.0)
    assert M.case_cost({"input_tokens": 1}, None, {"input_per_mtok": 1}) is None
    assert M.case_cost({"input_tokens": 1, "output_tokens": 1}, None, None) is None


# ---------------- unsupported claims ----------------

def test_evidence_ref_checker():
    c = M.EvidenceRefChecker()
    packet = "APPLICANT: Tolvan  Prenwick\nDOB: 1971-02-03"
    ids = {"profile.dob"}
    assert c.check("s", ["applicant: tolvan prenwick"], packet, ids).supported is True   # whitespace/case norm
    assert c.check("s", ["profile.dob"], packet, ids).supported is True
    assert c.check("s", [], packet, ids).supported is False
    assert c.check("s", None, packet, ids).supported is False
    assert c.check("s", ["profile.dob", "invented fact"], packet, ids).supported is False
    assert c.check("s", ["DO"], packet, set()).supported is False  # too short to count as a span
    assert c.check("s", ["x"], None, set()).supported is None
    assert M.EvidenceRefChecker(mode="id").check("s", ["DOB: 1971"], packet, ids).supported is False
    assert M.EvidenceRefChecker(mode="span").check("s", ["profile.dob"], packet, ids).supported is False


def test_unsupported_rate(fm):
    g = gold_case()
    nar = [{"sentence": "ok", "evidence_refs": ["profile.name"]},
           {"sentence": "made up", "evidence_refs": ["Customer is a billionaire"]},
           {"sentence": "no refs", "evidence_refs": []},
           {"sentence": "ok2", "evidence_refs": ["PASSPORT NO: X1234567"]}]
    s = M.score_case(g, pred_for(g, narrative=nar), fm)
    assert (s.sentences, s.unsupported) == (4, 2)
    assert M.aggregate([s], fm)["unsupported_rate"] == 0.5


class _AlwaysUnsure:
    name = "unsure"

    def check(self, sentence, refs, packet, ref_ids):
        return M.ClaimVerdict(None, "judge abstained")


def test_custom_checker_plugs_in(fm):
    g = gold_case()
    s = M.score_case(g, pred_for(g), fm, checker=_AlwaysUnsure())
    assert s.sentences == 0 and s.unchecked == 2
    agg = M.aggregate([s], fm)
    assert agg["unsupported_rate"] is None and agg["n_sentences_unchecked"] == 2


# ---------------- schema-agnostic ----------------

def test_different_schema_via_fieldmap():
    """A flat schema with different names scores correctly with only a new FieldMap."""
    fm = M.FieldMap(
        decision_path="outcome", decision_labels=["APPROVE", "REJECT", "ESCALATE"], escalate_label="ESCALATE",
        screening_path="hits", screening_id_key="id", screening_label_key="call",
        identity_fields={"name": "id_name_status", "verified": "id_ok"},
        risk_path="risk", risk_labels=["L", "M", "H"], actions_path="edd",
        narrative_path="story", narrative_sentence_key="text", narrative_refs_key="refs",
        label_aliases={"tm": "true_match", "fp": "false_positive"},
        adversarial_subsets={"inj": ["injection"]}, gold_expected_key="label",
        gold_id_key="id", pred_id_key="id", pred_output_key="raw",
    )
    gold = {"id": "1", "tags": ["injection"], "packet": "hello world",
            "label": {"outcome": "ESCALATE", "hits": [{"id": 7, "call": "fp"}], "id_name_status": "MISMATCH",
                      "id_ok": False, "risk": "H", "edd": ["X"], "story": [{"text": "t", "refs": ["hello"]}]}}
    pred = {"id": "1", "raw": json.dumps({"outcome": "escalate", "hits": [{"id": 7, "call": "False Positive"}],
                                          "id_name_status": "mismatch", "id_ok": False, "risk": "m", "edd": ["x"],
                                          "story": [{"text": "t", "refs": ["hello"]}]})}
    scores, diag = M.score_run([gold], [pred], fm)
    agg = M.aggregate(scores, fm)
    assert diag["missing_predictions"] == 0
    assert agg["decision_accuracy"] == 1.0
    assert agg["screening_macro_f1"] == 1.0
    assert agg["field_accuracy_mean"] == 1.0
    assert agg["risk_exact"] == 0.0 and agg["risk_within_one"] == 1.0
    assert agg["actions_recall"] == 1.0
    assert agg["adv_escalation_rate.inj"] == 1.0
    assert agg["unsupported_rate"] == 0.0


# ---------------- bootstrap ----------------

def _mixed_scores(fm, n=40):
    out = []
    for i in range(n):
        g = gold_case(str(i), decision=["approve", "reject", "escalate"][i % 3])
        dec = g["expected"]["decision"] if i % 4 else "approve"
        out.append(M.score_case(g, pred_for(g, decision=dec), fm))
    return out


def test_bootstrap_deterministic_and_brackets_point(fm):
    scores = _mixed_scores(fm)
    a = M.bootstrap_ci(scores, fm, n_boot=200, seed=7)
    b = M.bootstrap_ci(scores, fm, n_boot=200, seed=7)
    assert a == b
    point = M.aggregate(scores, fm)["decision_accuracy"]
    lo, hi = a["decision_accuracy"]
    assert lo <= point <= hi and lo < hi
    assert a["schema_validity"] == (1.0, 1.0)


def test_paired_delta(fm):
    base = _mixed_scores(fm)
    same = M.paired_bootstrap_delta(base, base, fm, n_boot=100)
    assert same["delta"]["decision_accuracy"] == 0 and same["ci"]["decision_accuracy"] == (0.0, 0.0)
    oracle = [M.score_case(gold_case(str(i), decision=["approve", "reject", "escalate"][i % 3]),
                           pred_for(gold_case(str(i), decision=["approve", "reject", "escalate"][i % 3])), fm)
              for i in range(40)]
    d = M.paired_bootstrap_delta(base, oracle, fm, n_boot=200)
    expected = 1 - M.aggregate(base, fm)["decision_accuracy"]
    assert d["n_paired"] == 40
    assert d["delta"]["decision_accuracy"] == pytest.approx(expected)
    lo, hi = d["ci"]["decision_accuracy"]
    assert 0 < lo <= expected <= hi
    # pairing only uses shared case ids
    assert M.paired_bootstrap_delta(base[:10], oracle, fm, n_boot=10)["n_paired"] == 10


def test_positional_hit_join():
    fm = M.FieldMap(screening_id_key=None)
    g = gold_case()
    hits = [{"hit_id": "zz", "disposition": "false_positive", "evidence": ""},
            {"hit_id": "yy", "disposition": "true_match", "evidence": ""}]
    s = M.score_case(g, pred_for(g, screening=hits), fm)
    assert s.hits == [("false_positive", "false_positive"), ("needs_review", "true_match")]


def test_packet_ref_id_regex():
    fm = M.FieldMap(packet_ref_id_regex=r"\b(CTX|APP|H\d+)\b")
    g = gold_case()
    g["packet"] = "## Context (CTX)\nhit H1 here"
    g["ref_ids"] = []
    nar = [{"sentence": "a", "evidence_refs": ["CTX", "H1"]}, {"sentence": "b", "evidence_refs": ["H2"]}]
    s = M.score_case(g, pred_for(g, narrative=nar), fm)
    assert (s.sentences, s.unsupported) == (2, 1)
