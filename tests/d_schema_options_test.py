"""Session D: lint the draft schema options in documentation/02_research/schema_options/.

Checks each option is valid JSON Schema, stays inside the conservative subset that
OpenAI strict mode, Anthropic structured outputs and Gemini all accept, and that the
example output validates while broken variants do not.
"""
import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

DIR = Path(__file__).resolve().parent.parent / "documentation" / "02_research" / "schema_options"
OPTIONS = ["option_a_nested", "option_b_flat", "option_c_checks_first"]
BANNED_KEYS = {"$ref", "$defs", "definitions", "anyOf", "oneOf", "allOf", "not",
               "if", "then", "else", "patternProperties", "pattern", "format"}
MAX_DEPTH = 5        # conservative: OpenAI's original strict-mode nesting limit
MAX_PROPERTIES = 100  # conservative: OpenAI's original strict-mode property limit


def load(name, kind):
    return json.loads((DIR / ("examples" if kind == "example" else "") / f"{name}.{kind}.json").read_text())


def walk(node, depth=0):
    """Yield (node, object_depth) for every schema node."""
    yield node, depth
    if node.get("type") == "object":
        for child in node["properties"].values():
            yield from walk(child, depth + 1)
    elif node.get("type") == "array":
        yield from walk(node["items"], depth)


@pytest.mark.parametrize("name", OPTIONS)
def test_schema_is_valid_json_schema(name):
    Draft202012Validator.check_schema(load(name, "schema"))


@pytest.mark.parametrize("name", OPTIONS)
def test_portable_subset(name):
    schema = load(name, "schema")
    n_props, max_depth = 0, 0
    for node, depth in walk(schema):
        assert not BANNED_KEYS & node.keys(), f"non-portable keyword in {node}"
        assert not isinstance(node.get("type"), list), "type unions (nullable) avoided on purpose"
        if node.get("type") == "object":
            assert node["additionalProperties"] is False
            assert set(node["required"]) == set(node["properties"]), "every field required"
            n_props += len(node["properties"])
            max_depth = max(max_depth, depth + 1)
    assert n_props <= MAX_PROPERTIES
    assert max_depth <= MAX_DEPTH


@pytest.mark.parametrize("name", OPTIONS)
def test_example_validates(name):
    Draft202012Validator(load(name, "schema")).validate(load(name, "example"))


@pytest.mark.parametrize("name", OPTIONS)
def test_broken_examples_rejected(name):
    v = Draft202012Validator(load(name, "schema"))
    ex = load(name, "example")

    bad_decision = copy.deepcopy(ex)
    bad_decision["decision"] = "approve_with_conditions"
    assert not v.is_valid(bad_decision)

    extra = copy.deepcopy(ex)
    extra["confidence"] = 0.9
    assert not v.is_valid(extra)

    short = copy.deepcopy(ex)
    short["narrative"] = short["narrative"][:3]
    assert not v.is_valid(short)

    missing = copy.deepcopy(ex)
    missing.pop("decision")
    assert not v.is_valid(missing)
