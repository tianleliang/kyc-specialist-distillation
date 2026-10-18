"""v1 case rows for tests, generated on the fly in the same shape as data/<split>/cases.jsonl."""
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V1_SCHEMA = ROOT / "step0_rules" / "schema" / "v1.json"
V1_SERVING = ROOT / "step0_rules" / "schema" / "v1_serving.json"
FIELDMAP_V1 = ROOT / "step6_evaluation" / "fieldmap_v1.yaml"
POLICY_V1 = ROOT / "step0_rules" / "policy_v1.md"


@lru_cache(maxsize=None)
def v1_cases(n: int = 12, seed: int = 2000000) -> tuple[dict, ...]:
    from step1_data_generation.config import load_config
    from step1_data_generation.project import SCHEMA_ID, project, ref_ids
    from step1_data_generation.render import render
    from step1_data_generation.sample import sample_cases

    cfg = load_config(ROOT / "step1_data_generation" / "configs" / "dev.yaml")
    rows = []
    for c in sample_cases(n, seed, cfg=cfg):
        packet, style = render(c)
        rows.append({"case_id": c.case_id, "split": cfg.split, "schema": SCHEMA_ID, "style": style,
                     "scenarios": c.scenarios, "packet": packet, "ref_ids": ref_ids(c), "expected": project(c)})
    return tuple(rows)
