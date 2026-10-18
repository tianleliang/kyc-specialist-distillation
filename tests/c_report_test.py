"""Session C: end-to-end tests for step6_evaluation/report.py using the fake models."""
import json
from pathlib import Path

import pytest

from step6_evaluation import metrics as M
from step6_evaluation import report as R
from tests import c_fakes

FIX = Path(__file__).parent / "fixtures"
SCHEMA = FIX / "c_schema.json"
GOLD = FIX / "c_gold.jsonl"


@pytest.fixture(scope="module")
def runs_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("outputs")
    golds = M.read_jsonl(GOLD)
    c_fakes.run_fakes(golds, json.loads(SCHEMA.read_text(encoding="utf-8")), M.FieldMap(), d, str(GOLD.resolve()))
    return d


@pytest.fixture(scope="module")
def aggs(runs_dir):
    fm = M.FieldMap(schema_path=str(SCHEMA))
    runs = R.load_runs([runs_dir], fm, None, M.DEFAULT_PRICES)
    return {r.run_id: M.aggregate(r.scores, fm) for r in runs}


def test_fixture_is_reproducible():
    assert GOLD.read_text(encoding="utf-8") == "".join(json.dumps(c) + "\n" for c in c_fakes.make_fixture())


def test_fixture_gold_is_schema_valid():
    v = M.make_validator(SCHEMA)
    assert all(v(g["expected"]) is None for g in M.read_jsonl(GOLD))


def test_oracle_scores_100(aggs):
    a = aggs["oracle"]
    for k in ["schema_validity", "decision_accuracy", "screening_macro_f1", "field_accuracy_mean",
              "risk_exact", "risk_within_one", "actions_recall", "actions_precision", "adv_decision_accuracy"]:
        assert a[k] == 1.0, k
    assert a["unsupported_rate"] == 0.0


def test_broken_json_scores_zero(aggs):
    a = aggs["broken_json"]
    for k in ["schema_validity", "decision_accuracy", "screening_macro_f1", "field_accuracy_mean",
              "risk_exact", "risk_within_one", "actions_recall", "adv_escalation_rate"]:
        assert a[k] == 0.0, k


def test_always_escalate(aggs):
    a = aggs["always_escalate"]
    assert a["adv_escalation_rate"] == 1.0
    golds = M.read_jsonl(GOLD)
    share = sum(g["expected"]["decision"] == "escalate" for g in golds) / len(golds)
    assert a["decision_accuracy"] == pytest.approx(share)


def test_random_and_corrupted_in_expected_ranges(aggs):
    r, c = aggs["random"], aggs["corrupted"]
    assert r["schema_validity"] == 1.0 and c["schema_validity"] == 1.0   # fakes keep enums valid
    assert 0.15 < r["decision_accuracy"] < 0.55
    for k in ["decision_accuracy", "field_accuracy_mean", "risk_exact"]:
        assert 0.65 < c[k] < 0.95, k
        assert r[k] < c[k] < 1.0, k


def test_hallucinated_refs_raise_unsupported_rate(aggs):
    a = aggs["hallucinated_refs"]
    assert a["unsupported_rate"] == 0.5          # fixture narratives have 4 sentences; 2 get fake refs
    assert a["decision_accuracy"] == 1.0


def test_report_cli_is_deterministic(runs_dir, tmp_path, capsys):
    args = [str(runs_dir), "--schema", str(SCHEMA), "--n-boot", "100"]
    assert R.main(args + ["--out", str(tmp_path / "a.md"), "--json", str(tmp_path / "a.json")]) == 0
    assert R.main(args + ["--out", str(tmp_path / "b.md")]) == 0
    a, b = (tmp_path / "a.md").read_text(encoding="utf-8"), (tmp_path / "b.md").read_text(encoding="utf-8")
    assert a.replace("a.md", "b.md").split("\n", 3)[3] == b.split("\n", 3)[3]
    assert "## Table 1" in a and "## Table 2" in a
    assert "| fake:oracle | 0 | 60 | 100.0 [100.0, 100.0] | 100.0 [100.0, 100.0]" in a
    assert "harness-check | oracle (fake:oracle) | corrupted (fake:corrupted) | 60" in a
    data = json.loads((tmp_path / "a.json").read_text(encoding="utf-8"))
    assert data["oracle"]["metrics"]["decision_accuracy"] == 1.0


def test_missing_predictions_are_penalized_and_reported(tmp_path, capsys):
    golds = M.read_jsonl(GOLD)
    d = tmp_path / "out" / "partial"
    d.mkdir(parents=True)
    half = golds[: len(golds) // 2]
    (d / "predictions.jsonl").write_text("".join(
        json.dumps({"case_id": g["case_id"], "output": json.dumps(g["expected"])}) + "\n" for g in half), encoding="utf-8")
    (d / "run.json").write_text(json.dumps({"model": "partial", "gold": str(GOLD)}), encoding="utf-8")
    out = tmp_path / "r.md"
    assert R.main([str(tmp_path / "out"), "--schema", str(SCHEMA), "--n-boot", "50", "--out", str(out)]) == 0
    md = out.read_text(encoding="utf-8")
    assert "| partial |  | 60 | 50.0" in md       # denominator is the gold file, not the predictions
    assert "`partial`: 30 missing" in md
    assert "No staged runs" in md


def test_no_runs_found(tmp_path):
    assert R.main([str(tmp_path)]) == 1


REPO = Path(__file__).resolve().parent.parent
DRAFT = REPO / "data" / "draft" / "cases.jsonl"
V0 = REPO / "step0_rules" / "schema" / "v0_provisional.json"


@pytest.mark.skipif(not (DRAFT.exists() and V0.exists()), reason="Session A's draft data not on this branch")
def test_fakes_on_session_a_draft(tmp_path):
    fm = M.FieldMap.load(FIX / "c_fieldmap_v0_provisional.yaml")
    fm.schema_path = str(V0)
    golds = M.read_jsonl(DRAFT)
    c_fakes.run_fakes(golds, json.loads(V0.read_text(encoding="utf-8")), fm, tmp_path, str(DRAFT),
                      names=["oracle", "broken_json", "hallucinated_refs"])
    runs = {r.run_id: M.aggregate(r.scores, fm) for r in R.load_runs([tmp_path], fm, None, M.DEFAULT_PRICES)}
    assert runs["oracle"]["schema_validity"] == 1.0
    assert runs["oracle"]["decision_accuracy"] == 1.0 and runs["oracle"]["field_accuracy_mean"] == 1.0
    assert runs["oracle"]["unsupported_rate"] == 0.0      # every gold evidence ref resolves to the packet
    assert runs["broken_json"]["schema_validity"] == 0.0
    assert runs["hallucinated_refs"]["unsupported_rate"] > 0.4
