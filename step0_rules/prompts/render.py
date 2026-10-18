"""Prompt templates: load, fill, and build chat messages.

    from step0_rules.prompts.render import PromptBuilder
    pb = PromptBuilder("student", schema="step0_rules/schema/v1.json", policy="step0_rules/policy_v1.md")
    msgs = pb.messages(packet_text)          # [{"role": "system", ...}, {"role": "user", ...}]

Templates live next to this file as ``<name>.md``: YAML front matter (``name``,
``description``, ``variables``), then an ``@@system`` part and an ``@@user`` part.
A placeholder is ``{name}`` where ``name`` is a declared variable. Nothing else
is substituted, so JSON braces in a template or in a value are safe, and a value
is never re-scanned (a packet containing ``{schema}`` stays literal).

No schema or policy is hardcoded anywhere: both are files passed in. The field
guide is derived from the schema itself, and few-shot examples come from a DEV
pool (``load_examples`` refuses eval paths and, for teacher prompts, draft data).

Judge helpers (``judge_items`` / ``parse_judgments``) pool and shuffle sentences
from several sources under neutral IDs so the judge is blind to who wrote them.

CLI (prints a rendered prompt, for eyeballing):
    python -m step0_rules.prompts.render student --schema step0_rules/schema/v1.json \
        --policy step0_rules/policy_v1.md --packet-file packet.txt
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import random
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml

PROMPT_DIR = Path(__file__).resolve().parent
SCHEMA_DIR = PROMPT_DIR / "schemas"
JUDGE_SCHEMA_PATH = SCHEMA_DIR / "judge_unsupported_claims.json"
_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")
_PART = re.compile(r"^@@(system|user)[ \t]*$", re.M)

# Path segments a few-shot pool may never come from. Teacher prompts also refuse
# draft data (data/draft/README.md: "nothing here may feed training or teacher prompts").
FORBIDDEN_POOL_SEGMENTS = ("eval",)
FORBIDDEN_TEACHER_POOL_SEGMENTS = ("draft",)


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Template:
    name: str
    description: str
    variables: tuple[str, ...]
    system: str
    user: str
    sha256: str

    @classmethod
    def parse(cls, text: str, source: str = "<string>") -> "Template":
        m = re.match(r"\A---\n(.*?)\n---\n(.*)\Z", text, re.S)
        if not m:
            raise ValueError(f"{source}: missing YAML front matter")
        meta = yaml.safe_load(m.group(1)) or {}
        body = m.group(2)
        parts = _PART.split(body)
        # parts = [preamble, tag1, text1, tag2, text2, ...]
        if parts[0].strip():
            raise ValueError(f"{source}: text before the first @@system/@@user marker")
        got = dict(zip(parts[1::2], parts[2::2]))
        if sorted(got) != ["system", "user"] or len(parts) != 5:
            raise ValueError(f"{source}: need exactly one @@system and one @@user part")
        variables = tuple(meta.get("variables") or ())
        used = set(_PLACEHOLDER.findall(body))
        declared = set(variables)
        if declared - used:
            raise ValueError(f"{source}: declared but unused variables {sorted(declared - used)}")
        # Undeclared {words} are literal text, but in practice they are typos: refuse them.
        if used - declared:
            raise ValueError(f"{source}: undeclared placeholders {sorted(used - declared)}")
        return cls(name=meta.get("name", source), description=meta.get("description", ""),
                   variables=variables, system=got["system"].strip("\n"),
                   user=got["user"].strip("\n"), sha256=sha256_text(text))

    def fill(self, **values: Any) -> "RenderedPrompt":
        missing = [v for v in self.variables if v not in values]
        if missing:
            raise KeyError(f"template {self.name!r} needs {missing}")
        extra = set(values) - set(self.variables)
        if extra:
            raise KeyError(f"template {self.name!r} does not take {sorted(extra)}")
        vals = {k: v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
                for k, v in values.items()}

        def sub(s: str) -> str:
            return _PLACEHOLDER.sub(lambda m: vals[m.group(1)] if m.group(1) in vals else m.group(0), s)

        return RenderedPrompt(template=self.name, template_sha256=self.sha256,
                              system=sub(self.system), user=sub(self.user),
                              var_sha256={k: sha256_text(v) for k, v in vals.items()})


@dataclass
class RenderedPrompt:
    template: str
    template_sha256: str
    system: str
    user: str
    var_sha256: dict[str, str] = field(default_factory=dict)

    def messages(self) -> list[dict]:
        return [{"role": "system", "content": self.system}, {"role": "user", "content": self.user}]

    def provenance(self) -> dict:
        """Hashes only (no text), for run.json / SFT metadata. The packet hash is per case."""
        return {"template": self.template, "template_sha256": self.template_sha256,
                "system_sha256": sha256_text(self.system),
                "vars_sha256": {k: v for k, v in self.var_sha256.items() if k != "packet"}}


def list_templates() -> list[str]:
    return sorted(p.stem for p in PROMPT_DIR.glob("*.md") if p.stem.lower() != "readme")


def load_template(name: str) -> Template:
    p = PROMPT_DIR / f"{name}.md"
    if not p.is_file():
        raise FileNotFoundError(f"no template {name!r}; have {list_templates()}")
    return Template.parse(p.read_text(encoding="utf-8"), source=p.name)


def render(name: str, **values: Any) -> RenderedPrompt:
    return load_template(name).fill(**values)


# ---------------------------------------------------------------------------
# Schema and policy inputs
# ---------------------------------------------------------------------------

def load_schema(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _drop_descriptions(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: _drop_descriptions(v) for k, v in node.items() if k != "description"}
    if isinstance(node, list):
        return [_drop_descriptions(v) for v in node]
    return node


def format_schema(schema: dict, descriptions: bool = True) -> str:
    """Compact JSON: small models pay for every token. Drops top-level `$id`/`$schema` noise.
    ``descriptions=False`` also drops every `description` (schema v1: 21k -> 5k chars) for prompts
    that already carry the policy, which explains every code."""
    s = {k: v for k, v in schema.items() if k not in ("$id", "$schema")}
    if not descriptions:
        s = _drop_descriptions(s)
    return json.dumps(s, ensure_ascii=False, separators=(",", ":"))


def load_policy(spec: str | Path) -> str:
    """A text/markdown file, or ``module:<dotted.module>`` to use that module's docstring
    (e.g. ``module:step1_data_generation.project``). The published policy is ``step0_rules/policy_v1.md``."""
    spec = str(spec)
    if spec.startswith("module:"):
        doc = importlib.import_module(spec[len("module:"):]).__doc__
        if not doc:
            raise ValueError(f"{spec} has no docstring")
        return doc.strip()
    return Path(spec).read_text(encoding="utf-8").strip()


def _resolve_ref(schema_root: dict, node: dict) -> dict:
    seen = 0
    while "$ref" in node:
        ref = node["$ref"]
        if not ref.startswith("#/"):
            raise ValueError(f"only local $ref supported, got {ref}")
        target: Any = schema_root
        for part in ref[2:].split("/"):
            target = target[part.replace("~1", "/").replace("~0", "~")]
        node = {**target, **{k: v for k, v in node.items() if k != "$ref"}}
        seen += 1
        if seen > 32:
            raise ValueError("$ref cycle")
    return node


def field_guide(schema: dict, max_enum: int = 40) -> str:
    """One line per field, derived from the schema: path, type, allowed values, description.
    Schema-agnostic: works on whatever schema Tianle picks."""
    lines: list[str] = []
    seen_enums: dict[str, str] = {}  # repeated enum lists point back to the first field

    def unwrap(node: dict) -> dict:
        node = _resolve_ref(schema, node)
        for k in ("anyOf", "oneOf"):  # nullable X written as anyOf [X, null]
            opts = [_resolve_ref(schema, o) for o in node.get(k, [])]
            non_null = [o for o in opts if o.get("type") != "null"]
            if len(non_null) == 1 and len(opts) == 2:
                node = {**non_null[0], "nullable": True}
        return node

    def kind(node: dict) -> str:
        t = node.get("type")
        ts = t if isinstance(t, list) else [t]
        if "object" in ts or "properties" in node:
            return "object"
        if "array" in ts:
            return "array"
        return "leaf"

    def describe(node: dict, path: str) -> str:
        if "enum" in node:
            key = json.dumps(node["enum"])
            if len(node["enum"]) > 3 and key in seen_enums:
                d = f"one of the same values as {seen_enums[key]}"
            else:
                seen_enums.setdefault(key, path)
                d = f"one of: {_enum(node['enum'], max_enum)}"
        else:
            t = node.get("type", "any")
            d = " or ".join(t) if isinstance(t, list) else t
        if node.get("nullable"):
            d += " or null"
        return d

    def walk(node: dict, path: str, depth: int, optional: bool) -> None:
        node = unwrap(node)
        k = kind(node)
        if k == "array":
            item = unwrap(node.get("items", {}))
            desc = "list of objects" if kind(item) == "object" else f"list, each {describe(item, path + '[]')}"
            bounds = [f"min {node['minItems']}" if "minItems" in node else "",
                      f"max {node['maxItems']}" if "maxItems" in node else ""]
            if any(bounds):
                desc += f" ({', '.join(b for b in bounds if b)} items)"
        elif k == "object":
            desc = "object"
        else:
            desc = describe(node, path)
        if node.get("description"):
            desc += f". {' '.join(node['description'].split())}"
        if optional:
            desc += " (optional)"
        if path:
            lines.append(f"{'  ' * (depth - 1)}- {path}: {desc}")
        if k == "object":
            req = set(node.get("required", []))
            for name, sub in (node.get("properties") or {}).items():
                walk(sub, f"{path}.{name}" if path else name, depth + 1, name not in req)
        elif k == "array" and kind(unwrap(node.get("items", {}))) == "object":
            item = unwrap(node.get("items", {}))
            req = set(item.get("required", []))
            for name, sub in (item.get("properties") or {}).items():
                walk(sub, f"{path}[].{name}", depth + 1, name not in req)

    walk(schema, "", 0, False)
    return "\n".join(lines)


def _enum(values: list, limit: int) -> str:
    vals = [json.dumps(v) if not isinstance(v, str) else v for v in values]
    return ", ".join(vals[:limit]) + (f", ... ({len(vals) - limit} more)" if len(vals) > limit else "")


# ---------------------------------------------------------------------------
# Few-shot examples (DEV pool only)
# ---------------------------------------------------------------------------

def _get(rec: dict, dotted: str) -> Any:
    cur: Any = rec
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def check_pool_path(path: str | Path, purpose: str = "baseline") -> None:
    segs = [s.lower() for s in Path(path).resolve().parts]
    bad = FORBIDDEN_POOL_SEGMENTS + (FORBIDDEN_TEACHER_POOL_SEGMENTS if purpose == "teacher" else ())
    for seg in segs:
        for b in bad:
            if seg == b or seg.startswith(b + "_") or seg.startswith(b + "-"):
                raise ValueError(f"few-shot pool {path} is under a '{seg}' directory; "
                                 f"{purpose} prompts take examples from the DEV pool only")


def load_examples(pool: str | Path, k: int = 2, seed: int = 0, *, purpose: str = "baseline",
                  packet_key: str = "packet", output_key: str = "expected",
                  stratify: str | None = "decision", id_key: str = "case_id",
                  eval_manifests: Iterable[str | Path] = ()) -> list[dict]:
    """Pick k examples from a DEV JSONL pool, deterministic in `seed`.

    `stratify` is a dotted path inside the output (e.g. "decision"): examples are
    taken round-robin over its values so 2 examples show 2 different outcomes.
    Refuses eval paths (and draft paths for teacher prompts), and, when frozen eval
    manifests are given, any example whose packet overlaps an eval record."""
    check_pool_path(pool, purpose)
    recs = [json.loads(l) for l in Path(pool).read_text(encoding="utf-8").splitlines() if l.strip()]
    recs = [r for r in recs if r.get(packet_key) and r.get(output_key) is not None]
    if len(recs) < k:
        raise ValueError(f"pool {pool} has {len(recs)} usable records, need {k}")
    rng = random.Random(seed)
    rng.shuffle(recs)
    if stratify:
        buckets: dict[str, list[dict]] = {}
        for r in recs:
            buckets.setdefault(json.dumps(_get(r[output_key], stratify)), []).append(r)
        order = sorted(buckets)
        rng.shuffle(order)
        picked: list[dict] = []
        while len(picked) < k:
            for key in order:
                if buckets[key] and len(picked) < k:
                    picked.append(buckets[key].pop())
    else:
        picked = recs[:k]
    manifests = list(eval_manifests)
    if manifests:
        from step6_evaluation.split_guard import EvalGuard

        for m in manifests:
            guard = EvalGuard.from_manifest(m)
            for r in picked:
                guard.check(r[packet_key])
    return [{"case_id": r.get(id_key), "packet": r[packet_key], "output": r[output_key]} for r in picked]


def format_examples(examples: list[dict]) -> str:
    out = []
    for i, ex in enumerate(examples, 1):
        o = ex["output"] if isinstance(ex["output"], str) else json.dumps(
            ex["output"], ensure_ascii=False, separators=(",", ":"))
        out.append(f"Example {i}\n<packet>\n{ex['packet']}\n</packet>\nOutput:\n{o}")
    return "\n\n".join(out)


# ---------------------------------------------------------------------------
# Builder used by the proxy, the endpoint runner and step4_distillation/
# ---------------------------------------------------------------------------

class PromptBuilder:
    """Renders one template many times: static vars (schema, policy, field guide,
    examples) are fixed at construction; `packet` varies per case."""

    def __init__(self, template: str, *, schema: str | Path | dict | None = None,
                 policy: str | Path | None = None, examples: list[dict] | None = None,
                 field_guide_text: str | None = None, schema_descriptions: bool = True):
        self.template = load_template(template)
        self.schema = load_schema(schema) if isinstance(schema, (str, Path)) else schema
        self.static: dict[str, str] = {}
        need = set(self.template.variables)
        if "schema" in need:
            if self.schema is None:
                raise ValueError(f"{template} needs a schema")
            self.static["schema"] = format_schema(self.schema, descriptions=schema_descriptions)
        if "policy" in need:
            if policy is None:
                raise ValueError(f"{template} needs a policy (file or module:<name>)")
            self.static["policy"] = load_policy(policy)
        if "field_guide" in need:
            self.static["field_guide"] = field_guide_text or field_guide(self.schema)
        if "examples" in need:
            if not examples:
                raise ValueError(f"{template} needs few-shot examples (load_examples from a DEV pool)")
            self.static["examples"] = format_examples(examples)
        self.example_ids = [e.get("case_id") for e in (examples or [])]

    def render(self, packet: str, **more: Any) -> RenderedPrompt:
        return self.template.fill(**self.static, packet=packet, **more)

    def messages(self, packet: str) -> list[dict]:
        return self.render(packet).messages()

    def system(self) -> str:
        """The system part (it never depends on the packet in our templates)."""
        return self.render("").system

    def wrap_user(self, packet: str) -> str:
        return self.render(packet).user

    def provenance(self) -> dict:
        p = self.render("").provenance()
        p["few_shot_case_ids"] = self.example_ids
        return p


# ---------------------------------------------------------------------------
# Judge: blind, pooled, shuffled
# ---------------------------------------------------------------------------

def judge_items(sentences: list[tuple[Any, str]], seed: int) -> tuple[str, dict[str, Any]]:
    """sentences: [(hidden_key, text)], e.g. key = (model, case_id, idx). Keys never reach
    the judge. Returns (numbered block for {sentences}, {neutral_id: hidden_key})."""
    order = list(range(len(sentences)))
    random.Random(seed).shuffle(order)
    id_map: dict[str, Any] = {}
    lines = []
    for n, i in enumerate(order, 1):
        sid = f"S{n}"
        id_map[sid] = sentences[i][0]
        text = " ".join(str(sentences[i][1]).split())  # one line each
        lines.append(f"{sid}: {text}")
    return "\n".join(lines), id_map


def render_judge(packet: str, sentences: list[tuple[Any, str]], seed: int,
                 policy: str | None = None) -> tuple[RenderedPrompt, dict]:
    """policy=None: v1 (packet only). With the policy text: v2 (packet + policy)."""
    block, id_map = judge_items(sentences, seed)
    schema = load_schema(JUDGE_SCHEMA_PATH)
    extra = {} if policy is None else {"policy": policy}
    rp = render("judge_unsupported_claims" if policy is None else "judge_unsupported_claims_v2",
                packet=packet, sentences=block, output_schema=format_schema(schema), **extra)
    return rp, id_map


def parse_judgments(parsed: dict, id_map: dict[str, Any]) -> dict[Any, dict]:
    """Judge output -> {hidden_key: {"supported": bool, ...}}. Raises if any sentence is
    missing, duplicated or unknown, so a sloppy judge can't silently shrink the denominator."""
    seen: dict[str, dict] = {}
    for j in parsed.get("judgments", []):
        sid = j.get("id")
        if sid not in id_map:
            raise ValueError(f"judge returned unknown id {sid!r}")
        if sid in seen:
            raise ValueError(f"judge returned {sid} twice")
        seen[sid] = j
    missing = sorted(set(id_map) - set(seen), key=lambda s: int(s[1:]))
    if missing:
        raise ValueError(f"judge skipped {missing}")
    return {id_map[sid]: {"supported": j["verdict"] == "supported",
                          "unsupported_claim": j.get("unsupported_claim", ""),
                          "packet_quote": j.get("packet_quote", "")} for sid, j in seen.items()}


def quote_in_packet(quote: str, packet: str) -> bool:
    """Programmatic double-check on a 'supported' verdict: is the quote really in the packet?"""
    norm = lambda s: " ".join(s.split()).lower()  # noqa: E731
    return bool(quote.strip()) and norm(quote) in norm(packet)


# ---------------------------------------------------------------------------
# OOD renderer
# ---------------------------------------------------------------------------

def render_ood(truth: dict, style: str, required_strings: list[str]) -> RenderedPrompt:
    req = "\n".join(f"- {json.dumps(s, ensure_ascii=False)}" for s in required_strings) or "- (none)"
    return render("ood_renderer", truth=json.dumps(truth, ensure_ascii=False, indent=1),
                  style=style.strip(), required_strings=req)


def check_ood_packet(packet: str, required_strings: list[str]) -> list[str]:
    """Strings the frontier renderer dropped or 'fixed'. Non-empty => discard the packet,
    because the gold label may no longer hold."""
    return [s for s in required_strings if s not in packet]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("template", choices=list_templates())
    ap.add_argument("--schema", help="output JSON Schema file")
    ap.add_argument("--policy", help="policy file, or module:<dotted.module>")
    ap.add_argument("--pool", help="DEV JSONL pool for few-shot examples")
    ap.add_argument("--k", type=int, default=2)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--packet-file", help="packet text file (default: a placeholder)")
    ap.add_argument("--hashes", action="store_true", help="print provenance hashes instead")
    a = ap.parse_args(argv)
    if a.template in ("judge_unsupported_claims", "judge_unsupported_claims_v2", "ood_renderer"):
        ap.error("use render_judge / render_ood from Python for this template")
    purpose = "teacher" if a.template == "teacher" else "baseline"
    ex = load_examples(a.pool, a.k, a.seed, purpose=purpose) if a.pool else None
    pb = PromptBuilder(a.template, schema=a.schema, policy=a.policy, examples=ex)
    packet = Path(a.packet_file).read_text(encoding="utf-8") if a.packet_file else "<PACKET>"
    if a.hashes:
        print(json.dumps(pb.provenance(), indent=1))
        return 0
    rp = pb.render(packet)
    sys.stdout.write(f"=== system ===\n{rp.system}\n\n=== user ===\n{rp.user}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
