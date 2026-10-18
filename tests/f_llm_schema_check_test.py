"""Session F: shared/frontier_api/schema_check.py."""

import json

from shared.frontier_api.schema_check import lint, main

GOOD = {"type": "object", "additionalProperties": False, "required": ["decision", "hits"],
        "properties": {
            "decision": {"type": "string", "enum": ["approve", "reject", "escalate"]},
            "hits": {"type": "array", "items": {
                "type": "object", "additionalProperties": False, "required": ["id", "dob"],
                "properties": {"id": {"type": "string"}, "dob": {"type": ["string", "null"]}}}}}}


def test_good_schema_is_clean():
    assert lint(GOOD) == ([], [])


def test_errors():
    bad = json.loads(json.dumps(GOOD))
    del bad["properties"]["hits"]["items"]["additionalProperties"]
    bad["required"] = ["decision"]
    errors, _ = lint(bad)
    assert any("$.hits[]: object needs additionalProperties" in e for e in errors)
    assert any("not in required: ['hits']" in e for e in errors)
    assert lint({"type": "array"})[0] == ["$: root must be type object"]


def test_refs_and_recursion():
    s = {"type": "object", "additionalProperties": False, "required": ["n"],
         "properties": {"n": {"$ref": "#/$defs/node"}},
         "$defs": {"node": {"type": "object", "additionalProperties": False, "required": ["next"],
                            "properties": {"next": {"$ref": "#/$defs/node"}}}}}
    errors, warnings = lint(s)
    assert any("recursive" in e for e in errors) and any("$defs" in w for w in warnings)


def test_risky_keywords_warn(tmp_path, capsys):
    s = json.loads(json.dumps(GOOD))
    s["properties"]["decision"]["minLength"] = 1
    errors, warnings = lint(s)
    assert errors == [] and any("minLength" in w for w in warnings)
    p = tmp_path / "s.json"
    p.write_text(json.dumps(s))
    assert main([str(p)]) == 0
    p.write_text(json.dumps({"type": "object", "properties": {"a": {"type": "string"}}}))
    assert main([str(p)]) == 1 and "ERROR" in capsys.readouterr().out
