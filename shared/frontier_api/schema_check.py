"""Lint an output JSON Schema for use as structured output on OpenAI, Anthropic and Gemini.

    python -m shared.frontier_api.schema_check step0_rules/schema/<file>.json     # exit 1 on errors, 0 otherwise

Errors (OpenAI strict mode rejects these, and the brief scores invalid output as zero):
  - root is not an object
  - an object without `additionalProperties: false`
  - an object property missing from `required` (express optional fields as nullable instead)
  - recursive `$ref`
Warnings (accepted but risky):
  - `$ref` / `$defs`: nested definitions sharply raise small-model failures (research brief)
  - nesting deeper than 5 levels
  - keywords some providers ignore or reject (verify per provider before relying on them)
It does not call any API.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RISKY_KEYWORDS = {"minLength", "maxLength", "pattern", "format", "minimum", "maximum",
                  "exclusiveMinimum", "exclusiveMaximum", "multipleOf", "minItems", "maxItems",
                  "uniqueItems", "oneOf", "allOf", "not", "if", "then", "else", "patternProperties"}


def lint(schema: dict) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if schema.get("type") != "object":
        errors.append("$: root must be type object")
    if "$defs" in schema or "definitions" in schema:
        warnings.append("$: uses $defs; keep the schema flat for small models")

    def walk(node, path: str, depth: int, refs: tuple[str, ...]) -> None:
        if not isinstance(node, dict):
            return
        if "$ref" in node:
            ref = node["$ref"]
            if ref in refs:
                errors.append(f"{path}: recursive $ref {ref}")
                return
            warnings.append(f"{path}: $ref {ref}")
            target = _resolve(schema, ref)
            if target is not None:
                walk(target, path, depth, refs + (ref,))
            return
        if depth > 5:
            warnings.append(f"{path}: nesting depth {depth} > 5")
        for kw in sorted(RISKY_KEYWORDS & set(node)):
            warnings.append(f"{path}: keyword `{kw}` (provider support varies)")
        types = node.get("type")
        types = types if isinstance(types, list) else [types]
        if "object" in types:
            props = node.get("properties", {})
            if node.get("additionalProperties") is not False:
                errors.append(f"{path}: object needs additionalProperties: false")
            missing = sorted(set(props) - set(node.get("required", [])))
            if missing:
                errors.append(f"{path}: properties not in required: {missing}")
            for k, v in props.items():
                walk(v, f"{path}.{k}", depth + 1, refs)
        if "array" in types:
            walk(node.get("items", {}), f"{path}[]", depth + 1, refs)
        for k in ("anyOf", "oneOf", "allOf"):
            for i, sub in enumerate(node.get(k, [])):
                walk(sub, f"{path}<{k}{i}>", depth, refs)

    walk(schema, "$", 0, ())
    return errors, warnings


def _resolve(schema: dict, ref: str):
    if not ref.startswith("#/"):
        return None
    node = schema
    for part in ref[2:].split("/"):
        node = node.get(part) if isinstance(node, dict) else None
    return node


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print("usage: python -m shared.frontier_api.schema_check <schema.json>", file=sys.stderr)
        return 2
    errors, warnings = lint(json.loads(Path(args[0]).read_text()))
    for w in warnings:
        print(f"warning: {w}")
    for e in errors:
        print(f"ERROR: {e}")
    print(f"{len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
