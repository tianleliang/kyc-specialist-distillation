"""Shared pieces for the step4_distillation/ CLIs: IO, the student prompt, teacher-output loading,
programmatic checks against gold, path editing, stats logging and the contamination gate.

Schema-agnostic: every schema-specific location comes from the same `FieldMap` YAML that
`step6_evaluation/metrics.py` uses (`--fieldmap`). Swapping in the real schema means writing a new
FieldMap, not editing this package.

Record formats
--------------
gold (one per case)   ``{"case_id", "packet", "expected": {...}, "scenarios"|"tags": [...]}``
                      key names come from the FieldMap (``gold_*_key``); data/draft/cases.jsonl
                      and step1_data_generation/build.py output have this shape.
teacher / student     any of
  outputs             * shared/frontier_api/batch.py results rows ``{"custom_id", "metadata": {"case_id", ...},
                        "response": {"model", "text", ...}}``
                      * eval-style predictions ``{"case_id", "output", "model"?, "usage"?}``
                      * already-normalized rows ``{"case_id", "teacher", "sample", "output"}``
                      * SFT records written by step4_distillation/ (the assistant turn is the output)
                      Several rows per (case, teacher) are k samples, numbered in file order
                      unless a ``sample`` key is present.
SFT (written)         ``{"id", "case_id", "source", "teacher", "messages": [system?, user,
                      assistant]}``; the step5_training/common.py SFT format plus provenance keys.
DPO (written)         ``{"id", "case_id", "source", "prompt": [system?, user], "chosen",
                      "rejected"}``; the step5_training/common.py DPO format.
"""
from __future__ import annotations

import glob
import hashlib
import json
import logging
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from step6_evaluation.metrics import (ABSENT, INVALID, MISSING, EvidenceRefChecker, FieldMap, get_path,
                          make_validator, norm_label, parse_output, score_case)

log = logging.getLogger("distill")

# Case-id prefixes that mark eval records (documentation/03_design/contamination_protocol.md §2).
EVAL_ID_PREFIXES = ("eid-", "ood-", "eval-")
# Where frozen split_guard manifests are looked for when --eval-manifest is not given.
DEFAULT_MANIFEST_GLOBS = ("data/eval/MANIFEST.json", "data/eval*/MANIFEST.json",
                          "data/eval*/**/MANIFEST.json")


# ---------------------------------------------------------------------------
# IO
# ---------------------------------------------------------------------------

def read_jsonl(path: str | Path) -> list[dict]:
    out = []
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                out.append(json.loads(line))
            except ValueError as e:
                raise ValueError(f"{path}:{i}: bad JSONL line: {e}") from None
    return out


def write_jsonl(path: str | Path, rows: Iterable[dict]) -> int:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            n += 1
    return n


_CANON_SCHEMA: dict | None = None
CANON_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "step0_rules" / "schema" / "v1.json"


def _schema_order(obj: Any, schema: dict | None) -> Any:
    """Recursively reorder dict keys to the schema's `properties` order (unknown keys last,
    original order kept). vLLM's structured-output grammar emits properties in schema order,
    so training targets must use the same order or train and serve disagree."""
    if isinstance(obj, dict):
        props = (schema or {}).get("properties") or {}
        keys = [k for k in props if k in obj] + [k for k in obj if k not in props]
        return {k: _schema_order(obj[k], props.get(k)) for k in keys}
    if isinstance(obj, list):
        item = (schema or {}).get("items") if isinstance(schema, dict) else None
        return [_schema_order(v, item) for v in obj]
    return obj


def dump_json(obj: Any) -> str:
    """The canonical training-target serialization: keys in v1 schema order (= serving grammar
    order), UTF-8, json's default separators (", " and ": "), which is exactly what vLLM's
    whitespace-free JSON grammar (xgrammar, disable_any_whitespace) emits at serving time."""
    global _CANON_SCHEMA
    if _CANON_SCHEMA is None:
        _CANON_SCHEMA = json.loads(CANON_SCHEMA_PATH.read_text(encoding="utf-8")) if CANON_SCHEMA_PATH.exists() else {}
    return json.dumps(_schema_order(obj, _CANON_SCHEMA), ensure_ascii=False)


def setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO,
                        format="%(name)s: %(message)s", stream=sys.stderr)


# ---------------------------------------------------------------------------
# Config: FieldMap, schema, student prompt
# ---------------------------------------------------------------------------

def load_fieldmap(path: str | None, schema: str | None = None) -> FieldMap:
    fm = FieldMap.load(path) if path else FieldMap()
    if schema:
        fm.schema_path = schema
    return fm


@dataclass
class StudentPrompt:
    """What the student sees: an optional system prompt and a user turn built from the packet.

    ``user_template`` contains the literal token ``{packet}`` (plain replace, so JSON braces in
    the template are safe). The real templates come from step0_rules/prompts/ (Session I); point
    ``--system-file`` / ``--user-template-file`` at the rendered files.
    """

    system: str | None = None
    user_template: str = "{packet}"

    @classmethod
    def from_files(cls, system_file: str | None, user_template_file: str | None) -> "StudentPrompt":
        sys_ = Path(system_file).read_text(encoding="utf-8") if system_file else None
        tpl = Path(user_template_file).read_text(encoding="utf-8") if user_template_file else "{packet}"
        if "{packet}" not in tpl:
            raise ValueError(f"user template {user_template_file} has no {{packet}} placeholder")
        return cls(sys_, tpl)

    def messages(self, packet: str) -> list[dict]:
        msgs = [{"role": "system", "content": self.system}] if self.system else []
        msgs.append({"role": "user", "content": self.user_template.replace("{packet}", packet)})
        return msgs

    def sha256(self) -> str:
        return hashlib.sha256(json.dumps([self.system, self.user_template]).encode("utf-8")).hexdigest()


def add_prompt_args(ap) -> None:
    ap.add_argument("--system-file", help="student system prompt (rendered from step0_rules/prompts/)")
    ap.add_argument("--user-template-file", help="user-turn template containing {packet}")


def add_common_args(ap, gold_required: bool = True) -> None:
    ap.add_argument("--gold", required=gold_required, help="gold cases JSONL (packet + expected)")
    ap.add_argument("--fieldmap", help="FieldMap YAML (default: step6_evaluation.metrics.FieldMap defaults)")
    ap.add_argument("--schema", help="output JSON Schema; overrides the FieldMap's schema_path")
    ap.add_argument("--eval-manifest", action="append", default=None,
                    help="frozen split_guard manifest(s) to check outputs against "
                         f"(default: any of {', '.join(DEFAULT_MANIFEST_GLOBS)})")
    ap.add_argument("-v", "--verbose", action="store_true")


# ---------------------------------------------------------------------------
# Gold and model outputs
# ---------------------------------------------------------------------------

def load_gold(path: str | Path, fm: FieldMap) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for r in read_jsonl(path):
        cid = str(r.get(fm.gold_id_key))
        if cid in out:
            raise ValueError(f"{path}: duplicate case id {cid}")
        out[cid] = r
    return out


def gold_tags(g: dict, fm: FieldMap) -> list[str]:
    return [str(t) for t in (g.get(fm.gold_tags_key) or g.get("scenarios") or g.get("tags") or [])]


def refuse_eval_ids(case_ids: Iterable[str], prefixes: Sequence[str] = EVAL_ID_PREFIXES,
                    what: str = "input") -> None:
    bad = [c for c in case_ids if str(c).startswith(tuple(prefixes))]
    if bad:
        raise SystemExit(f"CONTAMINATION: {what} contains {len(bad)} eval case id(s), e.g. {bad[:3]}. "
                         "step4_distillation/ never reads eval data.")


@dataclass
class Sample:
    case_id: str
    teacher: str
    sample: int
    raw: Any                       # text or already-parsed dict; None if the call failed
    error: str | None = None       # API / batch error, if any
    meta: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.case_id}|{self.teacher}|{self.sample}"


def _normalize_row(row: dict, default_teacher: str | None) -> Sample:
    if "response" in row and isinstance(row["response"], dict):        # shared/frontier_api/batch.py results
        resp, meta = row["response"], dict(row.get("metadata") or {})
        meta.update({k: v for k, v in (resp.get("metadata") or {}).items() if k not in meta})
        cid = meta.get("case_id")
        teacher = default_teacher or meta.get("teacher") or resp.get("model") or "teacher"
        raw = resp.get("parsed") if isinstance(resp.get("parsed"), dict) else resp.get("text")
        return Sample(str(cid), str(teacher), int(meta.get("sample", -1)), raw,
                      resp.get("error"), {"usage": resp.get("usage"), **meta})
    if isinstance(row.get("messages"), list):                       # an SFT record from step4_distillation/
        msgs = row["messages"]
        raw = msgs[-1].get("content") if msgs and msgs[-1].get("role") == "assistant" else None
        teacher = default_teacher or row.get("teacher") or row.get("source") or "sft"
        return Sample(str(row.get("case_id")), str(teacher), int(row["sample"]) if row.get("sample") is not None else -1,
                      raw, None if raw is not None else "no assistant turn", {"source": row.get("source")})
    cid = row.get("case_id")
    teacher = default_teacher or row.get("teacher") or row.get("model") or "teacher"
    return Sample(str(cid), str(teacher), int(row.get("sample", -1)), row.get("output"),
                  row.get("error"), {k: row[k] for k in ("usage", "latency_ms") if k in row})


def load_samples(specs: Sequence[str]) -> list[Sample]:
    """Each spec is ``PATH`` or ``PATH=TEACHER`` (the name overrides what the rows say)."""
    out: list[Sample] = []
    for spec in specs:
        path, _, name = spec.partition("=")
        rows = read_jsonl(path)
        out += [_normalize_row(r, name or None) for r in rows]
    counters: Counter = Counter()
    for s in out:                              # number k samples in file order
        if s.case_id in ("None", ""):
            raise ValueError(f"output row without a case_id (teacher {s.teacher}); set metadata.case_id")
        if s.sample < 0:
            s.sample = counters[(s.case_id, s.teacher)]
        counters[(s.case_id, s.teacher)] += 1
    return out


def group_by_case(samples: Iterable[Sample]) -> dict[str, list[Sample]]:
    d: dict[str, list[Sample]] = defaultdict(list)
    for s in samples:
        d[s.case_id].append(s)
    return d


# ---------------------------------------------------------------------------
# Programmatic checks
# ---------------------------------------------------------------------------

@dataclass
class CheckCfg:
    min_field_acc: float = 1.0        # share of gold identity fields that must match
    actions: str = "off"              # off | superset | exact
    evidence_refs: str = "strict"     # strict (every sentence resolves) | off
    allow_unchecked_refs: bool = False
    max_extra_hits: int | None = 0    # predicted hits with no gold counterpart; None = ignore


# Score weights for ranking candidates (closeness to gold). Mirrors the brief's emphasis on
# the decision; used only to order passing/failing candidates, never reported as a metric.
SCORE_WEIGHTS = {"decision": 0.35, "screening": 0.2, "fields": 0.2, "risk": 0.1,
                 "actions": 0.05, "grounding": 0.1}


@dataclass
class CheckResult:
    passed: bool
    reasons: list[str]                # coarse failure reasons (stats keys)
    details: list[str]                # fine-grained, human/teacher readable
    score: float                      # closeness to gold in [0, 1]
    obj: dict | None                  # parsed output if it parsed and validated
    parts: dict = field(default_factory=dict)


class Checker:
    """Checks one output against one gold record using step6_evaluation.metrics.score_case."""

    def __init__(self, fm: FieldMap, cfg: CheckCfg | None = None):
        self.fm = fm
        self.cfg = cfg or CheckCfg()
        self.validator = make_validator(fm.schema_path)
        self.refs = EvidenceRefChecker()

    def parse(self, raw: Any) -> tuple[dict | None, str | None]:
        obj, err = parse_output(raw, self.fm.strip_code_fences)
        if obj is not None:
            err = self.validator(obj)
            if err:
                return None, err
        return obj, err

    def check(self, raw: Any, gold: dict) -> CheckResult:
        fm, cfg = self.fm, self.cfg
        obj, err = parse_output(raw, fm.strip_code_fences)
        if obj is None:
            return CheckResult(False, ["unparseable"], [f"output does not parse: {err}"], 0.0, None)
        verr = self.validator(obj)
        if verr:
            return CheckResult(False, ["schema_invalid"], [verr], 0.0, None)
        cs = score_case(gold, {fm.pred_output_key: obj}, fm, None, self.refs)
        reasons, details, parts = [], [], {}

        g, p = cs.decision
        parts["decision"] = float(g is MISSING or g == p)
        if g is not MISSING and g != p:
            reasons.append("decision")
            details.append(f"decision: got {_show(p)}")

        g, p = cs.risk
        parts["risk"] = float(g is MISSING or g == p)
        if g is not MISSING and g != p:
            reasons.append("risk_tier")
            details.append(f"risk tier: got {_show(p)}")

        hit_ids = list(_gold_hit_ids(gold, fm))
        bad_hits = [hid for hid, (gl, pl) in zip(hit_ids, cs.hits) if gl != pl]
        parts["screening"] = 1.0 - len(bad_hits) / len(cs.hits) if cs.hits else 1.0
        if bad_hits:
            reasons.append("screening")
            details += [f"screening hit {h}: disposition is wrong or missing" for h in bad_hits]
        if cfg.max_extra_hits is not None and cs.extra_hits > cfg.max_extra_hits:
            reasons.append("extra_hits")
            details.append(f"screening: {cs.extra_hits} hit(s) that are not in the packet's hit list")

        scored = {k: v for k, v in cs.fields.items() if v[0] is not MISSING}
        bad_fields = [k for k, (gl, pl) in scored.items() if gl != pl]
        acc = 1.0 - len(bad_fields) / len(scored) if scored else 1.0
        parts["fields"] = acc
        if acc + 1e-9 < cfg.min_field_acc:
            reasons.append("fields")
        details += [f"identity field {k}: finding is wrong or missing" for k in bad_fields]

        tp, ng, npred = cs.actions_tp, cs.actions_gold, cs.actions_pred
        parts["actions"] = (2 * tp / (ng + npred)) if (ng + npred) else 1.0
        if cfg.actions == "superset" and tp < ng:
            reasons.append("actions")
            details.append(f"required actions: {ng - tp} required action(s) missing")
        elif cfg.actions == "exact" and not (tp == ng == npred):
            reasons.append("actions")
            details.append("required actions: set differs from what the policy requires")

        n_s = cs.sentences + cs.unchecked
        parts["grounding"] = 1.0 - cs.unsupported / cs.sentences if cs.sentences else (0.0 if n_s else 1.0)
        if cfg.evidence_refs == "strict":
            if cs.unsupported:
                reasons.append("evidence_refs")
                details.append(f"narrative: {cs.unsupported} sentence(s) cite evidence that is not in the packet")
            elif cs.unchecked and not cfg.allow_unchecked_refs:
                reasons.append("evidence_refs_unchecked")
                details.append("narrative: evidence_refs could not be checked (no packet / ref ids)")

        score = sum(SCORE_WEIGHTS[k] * parts[k] for k in SCORE_WEIGHTS)
        # field-level shortfalls below threshold are a failure; ones above it are only details
        return CheckResult(not reasons, reasons, details, round(score, 6), obj, parts)


def _show(v: Any) -> str:
    return {INVALID: "an invalid value", ABSENT: "no value"}.get(v, repr(v)) if isinstance(v, str) else repr(v)


def _gold_hit_ids(gold: dict, fm: FieldMap) -> Iterable[str]:
    """Hit ids in the order score_case lists them (gold hits with a label)."""
    lst = get_path(gold.get(fm.gold_expected_key, {}), fm.screening_path)
    seen = set()
    if not isinstance(lst, list):
        return
    for i, it in enumerate(lst):
        if not isinstance(it, dict):
            continue
        hid = str(i) if fm.screening_id_key is None else (str(it[fm.screening_id_key]) if fm.screening_id_key in it else None)
        if hid is None or hid in seen or fm.lab(it.get(fm.screening_label_key)) is MISSING:
            continue
        seen.add(hid)
        yield hid


def add_check_args(ap) -> None:
    ap.add_argument("--min-field-acc", type=float, default=1.0,
                    help="share of gold identity fields that must match (default 1.0 = all)")
    ap.add_argument("--actions", choices=["off", "superset", "exact"], default="off",
                    help="required-actions check (experiment_plan R9 uses superset)")
    ap.add_argument("--evidence-refs", choices=["strict", "off"], default="strict")
    ap.add_argument("--allow-unchecked-refs", action="store_true",
                    help="pass outputs whose evidence_refs cannot be checked")
    ap.add_argument("--max-extra-hits", type=int, default=0,
                    help="allowed predicted hits not in gold (-1 = ignore)")


def check_cfg_from_args(a) -> CheckCfg:
    return CheckCfg(a.min_field_acc, a.actions, a.evidence_refs, a.allow_unchecked_refs,
                    None if a.max_extra_hits < 0 else a.max_extra_hits)


# ---------------------------------------------------------------------------
# Path editing (the write side of step6_evaluation.metrics.get_path)
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"([^.\[\]]+)|\[([^\]]*)\]")


def path_tokens(path: str) -> list[tuple[str, str]]:
    """``a.b[0][k=v]`` -> [("key","a"), ("key","b"), ("idx","0"), ("sel","k=v")]."""
    out = []
    for m in _TOKEN_RE.finditer(path):
        name, sel = m.group(1), m.group(2)
        if name is not None:
            out.append(("key", name))
        elif re.fullmatch(r"\s*-?\d+\s*", sel):
            out.append(("idx", sel.strip()))
        else:
            out.append(("sel", sel.strip()))
    return out


def tokens_to_path(toks: Sequence[tuple[str, str]]) -> str:
    s = ""
    for kind, v in toks:
        s += (("." if s else "") + v) if kind == "key" else f"[{v}]"
    return s


def parent_path(path: str) -> str | None:
    toks = path_tokens(path)
    return tokens_to_path(toks[:-1]) if len(toks) > 1 else None


def set_path(obj: Any, path: str, value: Any) -> bool:
    """Set the value at ``path`` in place. Missing dict keys on the way are created;
    a ``[k=v]`` selector with no matching item appends ``{k: v}``. Returns False if the
    structure is incompatible (e.g. a list where an object is expected)."""
    toks = path_tokens(path)
    cur = obj
    for i, (kind, v) in enumerate(toks):
        last = i == len(toks) - 1
        nxt_kind = None if last else toks[i + 1][0]
        empty = [] if nxt_kind in ("idx", "sel") else {}
        if kind == "key":
            if not isinstance(cur, dict):
                return False
            if last:
                cur[v] = value
                return True
            if v not in cur or not isinstance(cur[v], (dict, list)):
                cur[v] = empty
            cur = cur[v]
        elif kind == "idx":
            j = int(v)
            if not isinstance(cur, list) or not -len(cur) <= j < len(cur):
                return False
            if last:
                cur[j] = value
                return True
            cur = cur[j]
        else:
            if not isinstance(cur, list):
                return False
            k, want = (s.strip() for s in v.split("=", 1))
            want = want.strip("'\"")
            j = next((n for n, it in enumerate(cur) if isinstance(it, dict) and k in it
                      and norm_label(it[k]) == norm_label(want)), None)
            if j is None:
                cur.append({k: want})
                j = len(cur) - 1
            if last:
                cur[j] = value
                return True
            cur = cur[j]
    return False


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

class Tally:
    """Counts kept / dropped per reason, logged and saved next to the output file."""

    def __init__(self, step: str):
        self.step = step
        self.kept = 0
        self.dropped: Counter = Counter()
        self.extra: dict[str, Any] = {}

    def keep(self, n: int = 1) -> None:
        self.kept += n

    def drop(self, reason: str, n: int = 1) -> None:
        self.dropped[reason] += n

    def summary(self) -> dict:
        return {"step": self.step, "kept": self.kept, "dropped": dict(sorted(self.dropped.items())),
                "dropped_total": sum(self.dropped.values()), **self.extra}

    def save(self, out_path: str | Path, sidecar: str | None = None) -> Path:
        p = Path(sidecar) if sidecar else Path(str(out_path) + ".stats.json")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.summary(), indent=1, ensure_ascii=False, default=str) + "\n",
                     encoding="utf-8")
        log.info("%s: kept %d, dropped %s -> %s", self.step, self.kept,
                 dict(self.dropped) or "{}", p)
        return p


# ---------------------------------------------------------------------------
# Contamination gate for every training-file writer
# ---------------------------------------------------------------------------

def discover_manifests(explicit: Sequence[str] | None, root: str | Path = ".") -> list[str]:
    if explicit:
        return list(explicit)
    found: set[str] = set()
    for pat in DEFAULT_MANIFEST_GLOBS:
        found.update(glob.glob(str(Path(root) / pat), recursive=True))
    from step6_evaluation.split_guard import exact_name_exists
    return sorted(f for f in found if exact_name_exists(f))  # Windows: case-insensitive glob


def _manifest_files(mpath: Path) -> list[str]:
    m = json.loads(mpath.read_text(encoding="utf-8"))
    entries = m.get("files") if isinstance(m, dict) else None
    if not isinstance(entries, list) or not all(isinstance(e, dict) and "path" in e for e in entries):
        raise SystemExit(f"{mpath}: not a split_guard manifest (needs files[].path); "
                         "freeze eval with `python -m step6_evaluation.split_guard freeze`")
    return [str(mpath.parent / e["path"]) for e in entries]


def contamination_gate(train_files: Sequence[str], manifests: Sequence[str] | None,
                       root: str | Path = ".") -> dict:
    """Verify each frozen eval manifest, then run split_guard's overlap check of
    ``train_files`` against the frozen eval files. Raises SystemExit on any problem."""
    from step6_evaluation import split_guard as sg

    paths = discover_manifests(manifests, root)
    if not paths:
        log.warning("no frozen eval manifest found; contamination check skipped "
                    "(it runs automatically once eval is frozen)")
        return {"checked": False, "reason": "no frozen eval manifest found"}
    eval_files: list[str] = []
    for mp in paths:
        problems = sg.verify(mp)
        if problems:
            raise SystemExit(f"eval manifest {mp} does not verify: {problems}")
        eval_files += _manifest_files(Path(mp))
    rep = sg.check_overlap(sg.load_docs(train_files), sg.load_docs(eval_files))
    if rep["contaminated_eval_records"]:
        raise SystemExit(f"CONTAMINATION: {rep['contaminated_eval_records']} eval records overlap "
                         f"{list(train_files)}; first: {rep['findings'][:3]}")
    return {"checked": True, "manifests": paths,
            **{k: v for k, v in rep.items() if k != "findings"}}


def write_training_file(path: str | Path, rows: list[dict], manifests: Sequence[str] | None,
                        tally: Tally | None = None, id_keys: Sequence[str] = ("case_id",)) -> dict:
    """Write rows to ``path`` only if they pass the contamination gate.

    Rows go to a temporary file first; the overlap check runs on it; only a clean file is
    moved into place. The gate result is stored in the tally (and so in the stats file).
    """
    refuse_eval_ids([r.get(k) for r in rows for k in id_keys if r.get(k) is not None], what=str(path))
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    write_jsonl(tmp, rows)
    try:
        gate = contamination_gate([str(tmp)], manifests)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    os.replace(tmp, path)
    if tally is not None:
        tally.extra["contamination_gate"] = gate
        tally.extra["output"] = str(path)
        tally.extra["output_records"] = len(rows)
    return gate


# ---------------------------------------------------------------------------
# Record builders
# ---------------------------------------------------------------------------

def target_text(obj_or_raw: Any) -> str:
    return dump_json(obj_or_raw) if isinstance(obj_or_raw, (dict, list)) else str(obj_or_raw)


def sft_record(source: str, case_id: str, prompt: StudentPrompt, packet: str, target: Any,
               teacher: str | None = None, sample: int | None = None, **extra: Any) -> dict:
    rid = f"{source}:{case_id}" + (f":{teacher}" if teacher else "") + (f":{sample}" if sample is not None else "")
    if sample is not None:
        extra = {"sample": sample, **extra}
    return {"id": rid, "case_id": case_id, "source": source, "teacher": teacher, **extra,
            "messages": prompt.messages(packet) + [{"role": "assistant", "content": target_text(target)}]}


def dpo_record(source: str, case_id: str, prompt: StudentPrompt, packet: str, chosen: Any,
               rejected: Any, n: int = 0, **extra: Any) -> dict:
    return {"id": f"{source}:{case_id}:{n}", "case_id": case_id, "source": source, **extra,
            "prompt": prompt.messages(packet), "chosen": target_text(chosen),
            "rejected": target_text(rejected)}
