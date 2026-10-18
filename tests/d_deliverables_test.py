"""Session D (Sun 10/18): reproducibility deliverables (report inputs, eval manifests, endpoint parity)."""
import json
from pathlib import Path

from step6_evaluation import metrics as M
from step6_evaluation import report as R
from step6_evaluation import split_guard

ROOT = Path(__file__).resolve().parent.parent


def test_frozen_manifests_verify_on_any_os():
    # data/eval/MANIFEST.json stores Windows-style "..\eval_id\cases.jsonl" paths
    assert split_guard.verify(ROOT / "data/eval/MANIFEST.json") == []
    assert split_guard.verify(ROOT / "data/eval_hard/manifest.json") == []


def test_ref_ids_from_truth_match_stored_ref_ids():
    for split in ("eval_id", "eval_ood_template", "eval_hard", "dev"):
        truths = {t["case_id"]: t["truth"] for t in M.read_jsonl(ROOT / f"data/{split}/truth.jsonl")}
        for row in M.read_jsonl(ROOT / f"data/{split}/cases.jsonl"):
            assert R.section_ref_ids(truths[row["case_id"]]) == row["ref_ids"]


def test_ood_gold_without_ref_ids_gets_them():
    fm = M.FieldMap.load(ROOT / "step6_evaluation/fieldmap_v1.yaml")
    rows = R.read_gold(ROOT / "data/eval_ood_hand/cases.jsonl", fm)
    assert all(r["ref_ids"][:3] == ["context", "application", "id_document_visual"] for r in rows)


def test_committed_runs_cover_every_table1_row():
    runs = {p.parent.name: json.loads(p.read_text(encoding="utf-8")) for p in (ROOT / "results/runs").glob("*/run.json")}
    v1 = [r for r in runs.values() if r.get("table1_group") == "eval_v1"]
    assert len(v1) == 18          # 3 frontier x 2 + 3 open x 2 + A/B/B-run2 halfway + A/B/B-run2 final
    for rid in runs:
        n = sum(1 for ln in (ROOT / "results/runs" / rid / "predictions.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip())
        assert n == {"eval_v1": 500, "eval_hard": 150, "dev": 150, "eval_id_v2": 300}[runs[rid]["table1_group"]], rid


def test_endpoint_parity(monkeypatch):
    import pytest
    pytest.importorskip("fastapi")   # serving deps: requirements-i.txt
    pytest.importorskip("httpx")
    from step7_serving import endpoint_parity
    monkeypatch.setenv("PROXY_API_KEYS", "x")   # main() overwrites both; monkeypatch restores them afterwards
    monkeypatch.setenv("ZORBE_PRECHECKS", "0")
    assert endpoint_parity.main(["--n", "3"]) == 0
