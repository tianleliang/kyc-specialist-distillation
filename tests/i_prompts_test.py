"""Session I: step0_rules/prompts/render.py and the templates. No network."""

import json
from pathlib import Path

import pytest

from step0_rules.prompts import render as R

ROOT = Path(__file__).resolve().parents[1]
V0 = ROOT / "step0_rules" / "schema" / "v0_provisional.json"
TINY_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["decision", "hits", "note"],
    "$defs": {"disp": {"type": "string", "enum": ["true_match", "false_positive", "needs_review"]}},
    "properties": {
        "decision": {"type": "string", "enum": ["approve", "reject", "escalate"], "description": "final call"},
        "hits": {"type": "array", "items": {"type": "object", "required": ["id", "d"],
                                            "properties": {"id": {"type": "string"},
                                                           "d": {"$ref": "#/$defs/disp"}}}},
        "note": {"anyOf": [{"type": "string"}, {"type": "null"}]},
    },
}


def write_pool(path: Path, n: int = 6) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    decisions = ["approve", "reject", "escalate"]
    path.write_text("".join(json.dumps({"case_id": f"dev-{i}", "packet": f"PACKET {i} " * 5,
                                        "expected": {"decision": decisions[i % 3], "hits": [], "note": None}}) + "\n"
                            for i in range(n)), encoding="utf-8")
    return path


@pytest.fixture
def policy(tmp_path):
    p = tmp_path / "policy.md"
    p.write_text("POLICY-TEXT: reject on sanctions true match.", encoding="utf-8")
    return p


# --- templates -------------------------------------------------------------

def test_all_templates_parse_and_declare_their_variables():
    names = R.list_templates()
    for n in ("student", "baseline_zero_shot", "baseline_best", "teacher",
              "judge_unsupported_claims", "ood_renderer"):
        assert n in names
    for n in names:
        t = R.load_template(n)
        assert t.system and t.user and t.description


@pytest.mark.parametrize("name", ["student", "baseline_zero_shot", "baseline_best", "teacher"])
def test_no_schema_or_policy_hardcoded(name):
    """The case-prompt templates must not name any schema field or policy rule: those
    come from the files passed in. Check against every enum value and property in v0."""
    t = R.load_template(name)
    text = (t.system + t.user)
    assert "{schema}" in text and "{packet}" in text
    schema = json.loads(V0.read_text(encoding="utf-8"))
    tokens = set()

    def walk(n):
        if isinstance(n, dict):
            tokens.update(k for k in n.get("properties", {}) if "_" in k)
            tokens.update(v for v in n.get("enum", []) if isinstance(v, str) and "_" in v)
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)

    walk(schema)
    leaked = sorted(tok for tok in tokens if tok in text)
    assert leaked == [], f"{name} hardcodes schema tokens {leaked}"


def test_zero_shot_has_no_policy(policy):
    assert "policy" not in R.load_template("baseline_zero_shot").variables
    rp = R.PromptBuilder("baseline_zero_shot", schema=TINY_SCHEMA).render("P")
    assert "POLICY-TEXT" not in rp.system and '"escalate"' in rp.system


def test_fill_is_strict_and_single_pass(policy):
    t = R.load_template("student")
    with pytest.raises(KeyError):
        t.fill(schema="{}", packet="x")  # policy missing
    with pytest.raises(KeyError):
        t.fill(schema="{}", policy="p", packet="x", bogus="y")
    rp = R.PromptBuilder("student", schema=TINY_SCHEMA, policy=policy).render("evil {schema} {policy}")
    assert "evil {schema} {policy}" in rp.user  # values are never re-scanned
    assert "POLICY-TEXT" in rp.system and '"enum":["approve","reject","escalate"]' in rp.system
    assert rp.messages()[0]["role"] == "system" and rp.messages()[1]["content"] == rp.user


def test_template_parser_rejects_bad_templates():
    ok = "---\nname: t\nvariables: [a]\n---\n@@system\nS {a}\n@@user\nU\n"
    assert R.Template.parse(ok).system == "S {a}"
    with pytest.raises(ValueError, match="front matter"):
        R.Template.parse("@@system\nx\n@@user\ny\n")
    with pytest.raises(ValueError, match="unused"):
        R.Template.parse(ok.replace("S {a}", "S"))
    with pytest.raises(ValueError, match="undeclared"):
        R.Template.parse(ok.replace("U", "U {b}"))
    with pytest.raises(ValueError, match="exactly one"):
        R.Template.parse(ok.replace("@@user\nU\n", ""))
    # JSON braces in a template are literal text, not placeholders
    assert '{"a": 1}' in R.Template.parse(ok.replace("U", 'U {"a": 1}')).user


def test_provenance_hashes_change_with_inputs(policy, tmp_path):
    a = R.PromptBuilder("student", schema=TINY_SCHEMA, policy=policy).provenance()
    p2 = tmp_path / "p2.md"
    p2.write_text("other policy", encoding="utf-8")
    b = R.PromptBuilder("student", schema=TINY_SCHEMA, policy=p2).provenance()
    assert a["template_sha256"] == b["template_sha256"]
    assert a["vars_sha256"]["policy"] != b["vars_sha256"]["policy"]
    assert "packet" not in a["vars_sha256"]


def test_policy_from_module_docstring():
    assert "policy_v1.md" in R.load_policy("module:step1_data_generation.project")


# --- field guide -------------------------------------------------------------

def test_field_guide_from_schema():
    g = R.field_guide(TINY_SCHEMA)
    assert "- decision: one of: approve, reject, escalate. final call" in g
    assert "- hits: list of objects" in g
    assert "  - hits[].d: one of: true_match, false_positive, needs_review" in g  # $ref resolved
    assert "- note: string or null" in g
    assert "(optional)" not in g


def test_field_guide_on_v0_covers_every_leaf():
    schema = json.loads(V0.read_text(encoding="utf-8"))
    g = R.field_guide(schema)
    for path in ("identity.verified", "identity.address.reason_code", "screening[].disposition",
                 "risk_tier", "required_actions", "decision", "narrative[].evidence_refs"):
        assert f"- {path}:" in g
    assert "same values as identity.name.reason_code" in g  # repeated enums are not repeated


# --- few-shot pool ---------------------------------------------------------

def test_examples_from_dev_pool_are_stratified_and_deterministic(tmp_path):
    pool = write_pool(tmp_path / "data" / "dev" / "cases.jsonl")
    a = R.load_examples(pool, k=2, seed=3)
    b = R.load_examples(pool, k=2, seed=3)
    assert a == b and len(a) == 2
    assert a[0]["output"]["decision"] != a[1]["output"]["decision"]
    block = R.format_examples(a)
    assert block.startswith("Example 1\n<packet>") and "Example 2" in block


@pytest.mark.parametrize("bad", ["eval", "eval_id", "eval-ood"])
def test_examples_refuse_eval_pools(tmp_path, bad):
    pool = write_pool(tmp_path / "data" / bad / "cases.jsonl")
    with pytest.raises(ValueError, match="DEV pool"):
        R.load_examples(pool)


def test_teacher_refuses_draft_pool_but_baseline_may_use_it(tmp_path):
    pool = write_pool(tmp_path / "data" / "draft" / "cases.jsonl")
    assert len(R.load_examples(pool, purpose="baseline")) == 2
    with pytest.raises(ValueError):
        R.load_examples(pool, purpose="teacher")


def test_examples_checked_against_frozen_eval_manifest(tmp_path):
    from shared.frontier_api.clients import ContaminationError
    from step6_evaluation.split_guard import freeze

    long_packet = " ".join(f"word{i}" for i in range(80))
    pool = tmp_path / "data" / "dev" / "cases.jsonl"
    pool.parent.mkdir(parents=True)
    rows = [{"case_id": "d1", "packet": long_packet, "expected": {"decision": "approve"}},
            {"case_id": "d2", "packet": "something else entirely " * 10, "expected": {"decision": "reject"}}]
    pool.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    ev = tmp_path / "frozen" / "cases.jsonl"
    ev.parent.mkdir()
    others = [{"case_id": f"e{i}", "packet": " ".join(f"tok{i}x{j}" for j in range(80))} for i in range(30)]
    ev.write_text("".join(json.dumps(r) + "\n" for r in [{"case_id": "e", "packet": long_packet}] + others),
                  encoding="utf-8")
    freeze([str(ev)], tmp_path / "frozen" / "manifest.json")
    with pytest.raises(ContaminationError):
        R.load_examples(pool, k=2, eval_manifests=[tmp_path / "frozen" / "manifest.json"])


def test_best_and_teacher_need_examples(policy, tmp_path):
    with pytest.raises(ValueError, match="few-shot"):
        R.PromptBuilder("baseline_best", schema=TINY_SCHEMA, policy=policy)
    ex = R.load_examples(write_pool(tmp_path / "dev" / "c.jsonl"), k=2)
    for name in ("baseline_best", "teacher"):
        rp = R.PromptBuilder(name, schema=TINY_SCHEMA, policy=policy, examples=ex).render("THE-PACKET")
        assert "Example 2" in rp.system and "- decision: one of" in rp.system
        assert "THE-PACKET" in rp.user and "THE-PACKET" not in rp.system
    t = R.PromptBuilder("teacher", schema=TINY_SCHEMA, policy=policy, examples=ex).system()
    assert "Evidence references must be complete" in t


# --- judge -------------------------------------------------------------------

def test_judge_is_blind_and_shuffled():
    sents = [(("gpt", "c1", 0), "Alpha."), (("ours", "c1", 0), "Beta."), (("claude", "c1", 0), "Gamma."),
             (("ours", "c1", 1), "Delta\nwith newline.")]
    rp, id_map = R.render_judge("PACKET Alpha Beta", sents, seed=1)
    for model in ("gpt", "ours", "claude", "c1"):
        assert model not in rp.user and model not in rp.system
    assert sorted(id_map) == ["S1", "S2", "S3", "S4"]
    assert "Delta with newline." in rp.user
    orders = {tuple(R.judge_items(sents, seed)[1].values()) for seed in range(10)}
    assert len(orders) > 1  # the seed changes the order
    judge_schema = json.loads(R.JUDGE_SCHEMA_PATH.read_text(encoding="utf-8"))
    assert '"enum":["supported","unsupported"]' in rp.system
    assert judge_schema["properties"]["judgments"]["items"]["additionalProperties"] is False


def test_parse_judgments_maps_back_and_refuses_gaps():
    sents = [("a", "one"), ("b", "two")]
    _, id_map = R.judge_items(sents, seed=0)
    inv = {v: k for k, v in id_map.items()}
    out = {"judgments": [
        {"id": inv["a"], "verdict": "supported", "unsupported_claim": "", "packet_quote": "one"},
        {"id": inv["b"], "verdict": "unsupported", "unsupported_claim": "two", "packet_quote": ""}]}
    res = R.parse_judgments(out, id_map)
    assert res["a"]["supported"] is True and res["b"]["supported"] is False
    with pytest.raises(ValueError, match="skipped"):
        R.parse_judgments({"judgments": out["judgments"][:1]}, id_map)
    with pytest.raises(ValueError, match="twice"):
        R.parse_judgments({"judgments": out["judgments"] + out["judgments"][:1]}, id_map)
    with pytest.raises(ValueError, match="unknown"):
        R.parse_judgments({"judgments": [{"id": "S9", "verdict": "supported"}]}, id_map)
    assert R.quote_in_packet("date of  birth 1982", "Date of birth 1982-03-15")
    assert not R.quote_in_packet("", "x") and not R.quote_in_packet("1983", "1982")


# --- OOD renderer -----------------------------------------------------------

def test_ood_renderer_and_check():
    truth = {"applicant": {"name": "Ama Owusu"}, "id_doc": {"dob_printed": "15.O3.1982"}}
    rp = R.render_ood(truth, "A bank's internal email thread, informal.", ["Ama Owusu", "15.O3.1982"])
    assert '"15.O3.1982"' in rp.user and "email thread" in rp.user and "Ama Owusu" in rp.user
    assert "never reuse" in R.load_template("ood_renderer").description.lower()
    assert R.check_ood_packet("Applicant Ama Owusu, DOB 15.03.1982", ["Ama Owusu", "15.O3.1982"]) == ["15.O3.1982"]


def test_cli_prints_prompt(capsys, policy):
    assert R.main(["student", "--schema", str(V0), "--policy", str(policy)]) == 0
    out = capsys.readouterr().out
    assert out.startswith("=== system ===") and "<PACKET>" in out
    assert R.main(["student", "--schema", str(V0), "--policy", str(policy), "--hashes"]) == 0
    assert "template_sha256" in capsys.readouterr().out
