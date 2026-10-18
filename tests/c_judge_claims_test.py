"""Session J: unsupported-claims judge (step6_evaluation/judge_claims.py) with a mock judge. No network."""
import copy
import json
import re
from pathlib import Path

import pytest

from shared.frontier_api.clients import LLMClient
from step6_evaluation import judge_claims as J
from step6_evaluation import metrics as M
from step6_evaluation import report as R

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "data/eval_id/cases.jsonl"
FM = ROOT / "step6_evaluation/fieldmap_v1.yaml"
SCHEMA = ROOT / "step0_rules/schema/v1.json"


def _write_run(d: Path, golds: list[dict], tweak=None) -> Path:
    d.mkdir(parents=True)
    with (d / "predictions.jsonl").open("w", encoding="utf-8") as f:
        for g in golds:
            out = copy.deepcopy(g["expected"])
            if tweak:
                tweak(out)
            f.write(json.dumps({"case_id": g["case_id"], "output": json.dumps(out)}) + "\n")
    (d / "run.json").write_text(json.dumps({"model": d.name, "gold": str(GOLD)}), encoding="utf-8")
    return d


def _invent(out):
    out["narrative"].append({"sentence": "INVENTED the applicant holds a second passport.",
                             "evidence_refs": ["application"], "hit_ids": []})


class MockJudge:
    """Marks a sentence unsupported iff it contains INVENTED; records what it was shown."""

    def __init__(self):
        self.seen: list[str] = []

    def __call__(self, req):
        block = req.messages[0]["content"].split("<sentences>")[1]
        items = re.findall(r"^(S\d+): (.*)$", block, re.M)
        self.seen += [t for _, t in items]
        return {"judgments": [
            {"id": sid, "verdict": "unsupported" if "INVENTED" in t else "supported",
             "unsupported_claim": "second passport" if "INVENTED" in t else "", "packet_quote": ""}
            for sid, t in items]}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    golds = M.read_jsonl(GOLD)[:2]
    gold = tmp_path / "gold.jsonl"
    gold.write_text("".join(json.dumps(g) + "\n" for g in golds), encoding="utf-8")
    judge = MockJudge()
    monkeypatch.setattr(J, "LLMClient", lambda: LLMClient(mock=True, mock_responder=judge, cache_dir=None))
    return golds, gold, judge, tmp_path


def _argv(runs, gold, out):
    return [str(r) for r in runs] + ["--gold", str(gold), "--out", str(out),
                                     "--config", str(FM), "--schema", str(SCHEMA)]


def test_blind_pooled_dedup_and_incremental(setup):
    golds, gold, judge, tmp = setup
    a = _write_run(tmp / "runs/a", golds)
    b = _write_run(tmp / "runs/b", golds)            # identical sentences to a
    out = tmp / "judge"
    assert J.main(_argv([a, b], gold, out)) == 0
    n_gold_sents = sum(len(g["expected"]["narrative"]) for g in golds)
    assert len(judge.seen) == n_gold_sents           # a and b pooled, duplicates judged once
    assert not any(n in s for s in judge.seen for n in ("runs/a", "runs/b"))  # sources hidden
    summ = json.loads((out / "summary.json").read_text())["runs"]
    assert summ["a"]["unsupported_rate"] == 0.0 and summ["a"]["n_sentences_judged"] == n_gold_sents

    # adding a run later judges only its new sentences
    c = _write_run(tmp / "runs/c", golds, _invent)
    judge.seen.clear()
    before = (out / "verdicts.jsonl").read_text(encoding="utf-8")
    assert J.main(_argv([a, b, c], gold, out)) == 0
    assert judge.seen == ["INVENTED the applicant holds a second passport."] * 2
    after = (out / "verdicts.jsonl").read_text(encoding="utf-8")
    assert set(before.splitlines()) < set(after.splitlines())
    summ = json.loads((out / "summary.json").read_text())["runs"]
    assert summ["c"]["n_unsupported"] == 2
    assert summ["c"]["unsupported_rate"] == pytest.approx(2 / (n_gold_sents + 2))

    # report: judge column filled from verdicts; programmatic column kept
    fm = M.FieldMap.load(FM)
    fm.schema_path = str(SCHEMA)
    runs = R.load_runs([tmp / "runs"], fm, gold, M.DEFAULT_PRICES,
                       M.load_judge_verdicts([out / "verdicts.jsonl"]))
    agg = {r.run_id: M.aggregate(r.scores, fm) for r in runs}
    assert agg["c"]["judge_unsupported_rate"] == pytest.approx(summ["c"]["unsupported_rate"])
    assert agg["a"]["judge_unsupported_rate"] == 0.0
    assert agg["c"]["n_judged"] == agg["c"]["n_sentences"]


def test_partial_coverage_reports_na(setup):
    golds, gold, judge, tmp = setup
    a = _write_run(tmp / "runs/a", golds)
    fm = M.FieldMap.load(FM)
    fm.schema_path = str(SCHEMA)
    runs = R.load_runs([a], fm, gold, M.DEFAULT_PRICES, {})
    agg = M.aggregate(runs[0].scores, fm)
    assert agg["n_unjudged"] > 0 and agg["judge_unsupported_rate"] is None


def test_invalid_judge_output_retried_once_then_fails(setup, monkeypatch):
    golds, gold, _, tmp = setup
    calls = []

    def bad(req):
        calls.append(1)
        return {"judgments": []}                     # skips every sentence

    monkeypatch.setattr(J, "LLMClient", lambda: LLMClient(mock=True, mock_responder=bad, cache_dir=None))
    a = _write_run(tmp / "runs/a", golds[:1])
    out = tmp / "judge"
    J.main(_argv([a], gold, out))
    assert len(calls) == 2
    assert not (out / "verdicts.jsonl").read_text(encoding="utf-8").strip()
    row = json.loads((out / "calls.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert row["ok"] is False and "skipped" in row["error"]


def test_v2_prompt_carries_policy_cached_and_versions_do_not_mix(setup):
    golds, gold, judge, tmp = setup
    policy = (ROOT / "step0_rules/policy_v1.md").read_text(encoding="utf-8").strip()
    req, _, rp = J.build_request(golds[0], [(("x", "y"), "A sentence.")], J.DEFAULT_MODEL, 32000, policy)
    assert policy in rp.system and policy not in rp.user
    assert req.extra["system"][0]["cache_control"] == {"type": "ephemeral"}
    req1, _, rp1 = J.build_request(golds[0], [(("x", "y"), "A sentence.")], J.DEFAULT_MODEL, 32000)
    assert "<policy>" not in rp1.system and not req1.extra

    a = _write_run(tmp / "runs/a", golds)
    out = tmp / "judge"
    assert J.main(_argv([a], gold, out) + ["--policy", "none"]) == 0
    with pytest.raises(SystemExit, match="another prompt version"):
        J.main(_argv([a], gold, out))                # default = v2 into a v1 dir
