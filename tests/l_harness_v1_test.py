"""Session L: the eval harness on schema v1 labels (oracle = 100% on every metric, broken JSON = 0%)."""
import json

from step6_evaluation import metrics as M
from step6_evaluation import report as R
from tests import c_fakes
from tests.l_v1_cases import FIELDMAP_V1, V1_SCHEMA, v1_cases

SKIP = ("latency", "cost", "n_", "unsupported_rate")


def _rates(m):
    return {k: v for k, v in m.items() if isinstance(v, float) and not k.startswith(SKIP)}


def test_fakes_on_v1_labels(tmp_path):
    fm = M.FieldMap.load(FIELDMAP_V1)
    fm.schema_path = str(V1_SCHEMA)
    golds = [json.loads(json.dumps(c)) for c in v1_cases(60, seed=2000500)]
    gold = tmp_path / "gold.jsonl"
    gold.write_text("".join(json.dumps(g) + "\n" for g in golds), encoding="utf-8")
    c_fakes.run_fakes(golds, json.loads(V1_SCHEMA.read_text(encoding="utf-8")), fm, tmp_path / "runs", str(gold),
                      names=["oracle", "broken_json", "hallucinated_refs", "always_escalate"])
    runs = {r.run_id: M.aggregate(r.scores, fm) for r in R.load_runs([tmp_path / "runs"], fm, None, M.DEFAULT_PRICES)}
    o, b = runs["oracle"], runs["broken_json"]
    assert _rates(o) and all(v == 1.0 for v in _rates(o).values()), {k: v for k, v in _rates(o).items() if v != 1.0}
    assert o["unsupported_rate"] == 0.0 and o["n_sentences"] > 0
    assert all(v == 0.0 for v in _rates(b).values())
    assert runs["hallucinated_refs"]["unsupported_rate"] > 0.4
    assert runs["hallucinated_refs"]["decision_accuracy"] == 1.0          # fake hit ids leave the output valid
    esc = sum(g["expected"]["decision"] == "escalate" for g in golds) / len(golds)
    assert abs(runs["always_escalate"]["decision_accuracy"] - esc) < 1e-9
    assert "verified" in fm.field_mean_exclude
