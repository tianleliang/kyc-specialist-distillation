"""Session L: published schema v1, its serving variant, the policy text and the configs agree."""
import collections
import copy
import json
import random
import re
from pathlib import Path

import jsonschema
import pytest
import yaml

from shared.frontier_api.schema_check import lint
from step0_rules.schema import build_v1 as B
from step1_data_generation import project as P
from step1_data_generation import sample as S
from step1_data_generation.config import load_config

ROOT = Path(__file__).resolve().parents[1]
V1 = json.loads((ROOT / "step0_rules/schema/v1.json").read_text(encoding="utf-8"))
SERVE = json.loads((ROOT / "step0_rules/schema/v1_serving.json").read_text(encoding="utf-8"))
POLICY = (ROOT / "step0_rules/policy_v1.md").read_text(encoding="utf-8")
CONFIGS = sorted((ROOT / "step1_data_generation/configs").glob("*.yaml"))
SERVING_ONLY = {"maxLength", "maxItems"}


@pytest.fixture(scope="module")
def outputs():
    cfg = load_config(ROOT / "step1_data_generation/configs/train.yaml")
    return [P.project(c) for c in S.sample_cases(400, seed=1700000, cfg=cfg)]


def test_files_are_built_from_the_builder():
    assert B.main(["--check"]) == 0


@pytest.mark.parametrize("schema", [V1, SERVE], ids=["v1", "v1_serving"])
def test_schema_lints_clean_and_is_flat(schema):
    jsonschema.Draft202012Validator.check_schema(schema)
    errors, _ = lint(schema)
    assert errors == []
    def keys(n):
        if isinstance(n, dict):
            yield from n
            for v in n.values():
                yield from keys(v)
        elif isinstance(n, list):
            for v in n:
                yield from keys(v)
    assert not {"$ref", "$defs", "definitions"} & set(keys(schema))
    assert set(schema["required"]) == set(schema["properties"])
    assert schema["properties"]["schema_version"]["enum"] == ["1.0"]
    n = schema["properties"]["narrative"]
    assert (n["minItems"], n["maxItems"]) == (4, 8)


def _walk(a, b, path=""):
    """Yield every difference between two schema trees as (path, key)."""
    if isinstance(a, dict) and isinstance(b, dict):
        for k in set(a) | set(b):
            if k not in a:
                yield path, k
            elif k not in b:
                yield path, f"-{k}"
            elif k not in ("$id", "title", "description"):
                yield from _walk(a[k], b[k], f"{path}/{k}")
    elif a != b:
        yield path, "value"


def test_serving_only_adds_bounds():
    diffs = list(_walk(V1, SERVE))
    assert diffs and all(k in SERVING_ONLY for _, k in diffs), diffs
    assert SERVE["properties"]["narrative"]["items"]["properties"]["sentence"]["maxLength"] > 0


def test_valid_under_serving_implies_valid_under_v1(outputs):
    """Property check on real labels and on random mutations of them."""
    v1, sv = jsonschema.Draft202012Validator(V1), jsonschema.Draft202012Validator(SERVE)
    rng = random.Random(0)
    n_serving_valid = 0
    for o in outputs:
        assert not list(sv.iter_errors(o)) and not list(v1.iter_errors(o))
        for _ in range(5):
            m = copy.deepcopy(o)
            s = rng.choice(m["narrative"])
            s["sentence"] = s["sentence"] * rng.choice([1, 3, 20])
            m["risk_drivers"] = m["risk_drivers"] * rng.choice([1, 2, 10])
            if m["screening"]:
                m["screening"][0]["hit_id"] = rng.choice(["H1", "H" + "9" * 40])
            if not list(sv.iter_errors(m)):
                n_serving_valid += 1
                assert not list(v1.iter_errors(m))
    assert n_serving_valid > 0


def test_every_code_is_documented_in_schema_and_policy():
    enums = {"reasons": B.REASONS, "evidence": B.EVIDENCE, "drivers": B.DRIVERS, "actions": B.ACTIONS,
             "sections": B.SECTIONS, "dispositions": B.DISPOSITIONS}
    txt = json.dumps(V1)
    for name, d in enums.items():
        for code, meaning in d.items():
            assert meaning and f"{code}: " in txt, (name, code)
            assert f"`{code}`" in POLICY or code in POLICY, (name, code)
    for f, codes in B.FIELD_REASONS.items():
        assert V1["properties"][f"{f}_reason"]["enum"] == codes
        assert {"field_illegible", "field_missing"} <= set(codes)


def test_labels_only_use_codes_the_schema_lists(outputs):
    seen = collections.defaultdict(set)
    for o in outputs:
        for f in P.FIELDS:
            seen[f].add(o[f"{f}_reason"])
        seen["drivers"] |= set(o["risk_drivers"])
        seen["actions"] |= set(o["required_actions"])
    for f in P.FIELDS:
        assert seen[f] <= set(B.FIELD_REASONS[f])
    assert seen["drivers"] <= set(B.DRIVERS) and seen["actions"] <= set(B.ACTIONS)


def test_output_key_order_follows_schema(outputs):
    assert list(outputs[0]) == list(V1["properties"])


def test_actions_and_drivers_follow_catalog_order(outputs):
    a_order, d_order = list(B.ACTIONS), list(B.DRIVERS)
    for o in outputs:
        assert o["required_actions"] == sorted(o["required_actions"], key=a_order.index)
        assert o["risk_drivers"] == sorted(o["risk_drivers"], key=d_order.index)
        assert len(set(o["required_actions"])) == len(o["required_actions"])


# ---- configs ----------------------------------------------------------------
@pytest.mark.parametrize("path", CONFIGS, ids=lambda p: p.stem)
def test_d6_switch_on_in_every_config(path):
    assert yaml.safe_load(path.read_text())["ocr_digit_to_digit_in_numeric"] is True


def test_train_and_dev_share_the_tuned_mix():
    tr = load_config(ROOT / "step1_data_generation/configs/train.yaml")
    dv = load_config(ROOT / "step1_data_generation/configs/dev.yaml")
    assert tr.mix == dv.mix == S.DEFAULT_MIX
    assert set(tr.mix) == set(S.SCENARIOS)


def test_train_mix_hits_target_and_keeps_hard_cases():
    cfg = load_config(ROOT / "step1_data_generation/configs/train.yaml")
    cs = S.sample_cases(1500, seed=cfg.default_seed, cfg=cfg)
    d = collections.Counter(P.outcome(c) for c in cs)
    share = {k: d[k] / len(cs) for k in ("approve", "escalate", "reject")}
    for k, target in (("approve", 0.38), ("escalate", 0.47), ("reject", 0.15)):
        assert abs(share[k] - target) < 0.03, share
    for item, scens in S.BRIEF_COVERAGE.items():
        assert sum(1 for c in cs if set(c.scenarios) & set(scens)) / len(cs) >= 0.04, item


# ---- serving + SFT serialization --------------------------------------------
def test_proxy_example_points_at_v1_and_fallback_is_valid():
    cfg = yaml.safe_load((ROOT / "step7_serving/proxy_config.example.yaml").read_text())
    assert cfg["schema_path"] == "step0_rules/schema/v1_serving.json"
    assert cfg["policy"] == "step0_rules/policy_v1.md" and (ROOT / cfg["policy"]).exists()
    proxy = pytest.importorskip("step7_serving.proxy")
    for schema in (SERVE, V1):
        fb = proxy.build_fallback(schema, cfg["fallback_overrides"])
        jsonschema.Draft202012Validator(schema).validate(fb)
        assert fb["decision"] == "escalate" and fb["identity_verified"] is False


def test_sft_targets_use_default_json_separators():
    from step4_distillation.common import dump_json
    s = dump_json({"a": 1, "b": [1, 2], "c": {"d": "é"}})
    assert s == '{"a": 1, "b": [1, 2], "c": {"d": "é"}}'
    assert not re.search(r'[,:]\S', s.replace('"é"', ""))


def test_prompt_schema_descriptions_switch():
    from step0_rules.prompts.render import PromptBuilder, format_schema
    full, bare = format_schema(V1), format_schema(V1, descriptions=False)
    assert '"description"' in full and '"description"' not in bare and len(bare) < len(full) / 3
    assert json.loads(bare)["properties"]["name_reason"]["enum"] == V1["properties"]["name_reason"]["enum"]
    pb = PromptBuilder("student", schema=V1, policy=ROOT / "step0_rules/policy_v1.md", schema_descriptions=False)
    assert "KYC Adjudication Policy v1" in pb.system() and '"description"' not in pb.system()
