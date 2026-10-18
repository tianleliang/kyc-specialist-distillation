"""Schema-agnostic evaluation metrics for KYC case adjudication.

Nothing here hard-codes the output schema. A `FieldMap` config says where each
scored quantity lives (decision, screening hits, identity findings, risk tier,
required actions, narrative). Swapping in the real schema means writing a new
FieldMap YAML, not editing this file.

Inputs (one record per case):

* gold record (JSONL): ``{"case_id", "expected": {...}, "tags": [...],
  "packet": "<packet text>", "ref_ids": [...]}``. Key names are configurable
  on the FieldMap (``gold_*_key``). ``expected`` is in the same schema as model
  output, so the same paths apply to both.
* prediction record (JSONL): ``{"case_id", "output": "<raw model text>" | {...},
  "latency_ms": float, "usage": {"input_tokens", "output_tokens"}}``.
  OpenAI-style ``prompt_tokens`` / ``completion_tokens`` are accepted too.

Scoring rules (the brief: "output that fails validation against your own schema
scores zero for that case"):

* The gold file defines the denominator. A case with no prediction, an
  unparseable prediction, or a schema-invalid prediction is scored as wrong on
  every quality metric, never dropped.
* Values missing from an otherwise valid output count as wrong.
* Values missing from the gold record drop that case out of that one metric only.

Everything is computed from per-case `CaseScore` records so that `aggregate`
can be re-run cheaply on bootstrap resamples (see `bootstrap_ci`,
`paired_bootstrap_delta`).

No API calls happen here. The unsupported-claims check is programmatic
(`EvidenceRefChecker`); an LLM judge can be plugged in later through the
`ClaimChecker` interface.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Callable, Iterable, Protocol, Sequence

import numpy as np

MISSING: Any = type("Missing", (), {"__repr__": lambda self: "MISSING", "__bool__": lambda self: False})()

INVALID = "(invalid)"   # prediction slot when the output failed parse/schema or was absent
ABSENT = "(absent)"     # prediction slot when a valid output simply lacks the value

# --------------------------------------------------------------------------
# Paths and labels
# --------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"([^.\[\]]+)|\[([^\]]*)\]")


def get_path(obj: Any, path: str | None) -> Any:
    """Resolve a dotted path. Supports ``a.b``, ``a[0]`` and ``a[key=value]``.

    ``[key=value]`` picks the first list item whose ``key`` normalizes to the
    same label as ``value``. Returns `MISSING` if any step fails.
    """
    if path in (None, "", "."):
        return obj
    cur = obj
    for m in _TOKEN_RE.finditer(path):
        name, sel = m.group(1), m.group(2)
        if name is not None:
            if isinstance(cur, dict) and name in cur:
                cur = cur[name]
            else:
                return MISSING
            continue
        sel = sel.strip()
        if not isinstance(cur, list):
            return MISSING
        if re.fullmatch(r"-?\d+", sel):
            i = int(sel)
            cur = cur[i] if -len(cur) <= i < len(cur) else MISSING
        elif "=" in sel:
            k, v = (s.strip() for s in sel.split("=", 1))
            want = norm_label(v.strip("'\""))
            cur = next((it for it in cur if isinstance(it, dict) and k in it
                        and norm_label(it[k]) == want), MISSING)
        else:
            return MISSING
        if cur is MISSING:
            return MISSING
    return cur


def norm_label(x: Any, aliases: dict[str, str] | None = None) -> Any:
    """Normalize an enum-ish value: lowercase, trim, spaces/hyphens -> '_'.

    Booleans become 'true'/'false'. None and MISSING stay MISSING. Non-scalar
    values are returned unchanged (they never equal a gold label).
    """
    if x is None or x is MISSING:
        return MISSING
    if isinstance(x, bool):
        s = "true" if x else "false"
    elif isinstance(x, (str, int, float)):
        s = re.sub(r"[\s\-]+", "_", str(x).strip().lower())
    else:
        return x
    if aliases:
        s = aliases.get(s, s)
    return s


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

@dataclass
class FieldMap:
    """Where each scored quantity lives in an output object. All paths are
    relative to the output (or gold ``expected``) object. Defaults match the
    test fixture schema in ``tests/fixtures/c_schema.json``; they are
    placeholders, not a schema decision."""

    decision_path: str = "decision"
    decision_labels: list[str] = field(default_factory=lambda: ["approve", "reject", "escalate"])
    escalate_label: str = "escalate"

    screening_path: str = "screening"          # list of hit objects
    screening_id_key: str | None = "hit_id"    # joins predicted hits to gold hits; None = by position
    screening_label_key: str = "disposition"
    screening_labels: list[str] = field(default_factory=lambda: ["true_match", "false_positive", "needs_review"])

    # name -> path of a per-field status label (consistent / mismatch / unreadable, or a bool)
    identity_fields: dict[str, str] = field(default_factory=lambda: {
        "verified": "identity.verified",
        "name": "identity.findings[field=name].status",
        "dob": "identity.findings[field=dob].status",
        "document_number": "identity.findings[field=document_number].status",
        "expiry": "identity.findings[field=expiry].status",
        "address": "identity.findings[field=address].status",
    })

    # identity_fields keys reported per field but left out of field_accuracy_mean (D15: verified)
    field_mean_exclude: list[str] = field(default_factory=list)

    risk_path: str = "risk_tier"
    risk_labels: list[str] = field(default_factory=lambda: ["low", "medium", "high"])  # ordered

    actions_path: str = "required_actions"     # list of codes, or list of objects
    actions_item_key: str | None = None        # set when items are objects

    narrative_path: str = "narrative"          # list of {sentence, evidence_refs}
    narrative_sentence_key: str = "sentence"
    narrative_refs_key: str = "evidence_refs"
    # optional second ref list per sentence (schema v1: hit_ids); each id must resolve like a ref.
    # An empty list adds nothing, so a sentence citing no hit is not penalised.
    narrative_hit_ids_key: str | None = None

    # alias -> canonical label, applied after normalization, to every enum
    label_aliases: dict[str, str] = field(default_factory=dict)

    # subset name -> gold tags; a case is in the subset if it has any listed tag
    adversarial_subsets: dict[str, list[str]] = field(default_factory=lambda: {
        "injection": ["prompt_injection"],
        "ambiguous": ["insufficient_evidence"],
    })
    # True: the adversarial escalation rate counts only cases whose gold decision is escalate
    # (under policy v1 an injected packet with a sanctions match or forged document is a gold reject).
    # Decision accuracy on the subsets still covers every case.
    adv_escalation_gold_escalate_only: bool = False

    gold_id_key: str = "case_id"
    gold_expected_key: str = "expected"
    gold_tags_key: str = "tags"
    gold_packet_key: str = "packet"
    gold_ref_ids_key: str = "ref_ids"
    # regex whose matches in the packet text are valid evidence ref ids (e.g.
    # section ids like CTX / H1); combined with the gold ref_ids list
    packet_ref_id_regex: str | None = None

    pred_id_key: str = "case_id"
    pred_output_key: str = "output"

    schema_path: str | None = None             # JSON Schema for validity; None = "parses to an object"
    strip_code_fences: bool = False            # accept ```json ... ``` wrappers (lenient; off by default)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "FieldMap":
        known = {f.name for f in fields(cls)}
        unknown = set(d) - known
        if unknown:
            raise ValueError(f"unknown FieldMap keys: {sorted(unknown)}")
        return cls(**d)

    @classmethod
    def load(cls, path: str | Path) -> "FieldMap":
        text = Path(path).read_text(encoding="utf-8")
        if str(path).endswith((".yaml", ".yml")):
            import yaml
            d = yaml.safe_load(text) or {}
        else:
            d = json.loads(text)
        return cls.from_dict(d)

    def lab(self, x: Any) -> Any:
        return norm_label(x, self.label_aliases)


# --------------------------------------------------------------------------
# Price table
# --------------------------------------------------------------------------

# PLACEHOLDER prices, copied from documentation/00_case_brief_and_plan/05 (agent-reported; verify in
# provider consoles before reporting). Token prices are USD per 1M tokens.
# GPU entries price self-hosted models by wall-clock: cost per case =
# usd_per_hour * latency / 3600 / concurrency.
DEFAULT_PRICES: dict[str, dict[str, float]] = {
    "gpt-6-astra": {"input_per_mtok": 10.0, "output_per_mtok": 50.0},
    "gpt-6.1-sol": {"input_per_mtok": 2.0, "output_per_mtok": 10.0},
    "gpt-6-luna": {"input_per_mtok": 0.10, "output_per_mtok": 0.50},
    "claude-fable-5-1": {"input_per_mtok": 10.0, "output_per_mtok": 50.0},
    "claude-opus-5-5": {"input_per_mtok": 4.0, "output_per_mtok": 20.0},
    "claude-sonnet-5-5": {"input_per_mtok": 2.0, "output_per_mtok": 10.0},
    "gemini-4-argon": {"input_per_mtok": 2.0, "output_per_mtok": 10.0},
    "gemini-3.8-flash": {"input_per_mtok": 0.75, "output_per_mtok": 3.75},
    "modal-l4": {"usd_per_hour": 0.80, "concurrency": 1},
    "modal-a100-80gb": {"usd_per_hour": 2.50, "concurrency": 1},
}


def case_cost(usage: dict | None, latency_ms: float | None, price: dict | None,
              multiplier: float = 1.0) -> float | None:
    """USD for one case, or None if it can't be priced."""
    if not price:
        return None
    if "usd_per_hour" in price:
        if latency_ms is None:
            return None
        conc = float(price.get("concurrency", 1)) or 1.0
        return price["usd_per_hour"] * (latency_ms / 1000.0) / 3600.0 / conc * multiplier
    if not usage:
        return None
    tin = usage.get("input_tokens", usage.get("prompt_tokens"))
    tout = usage.get("output_tokens", usage.get("completion_tokens"))
    if tin is None or tout is None:
        return None
    return (tin * price.get("input_per_mtok", 0.0) + tout * price.get("output_per_mtok", 0.0)) / 1e6 * multiplier


# --------------------------------------------------------------------------
# Unsupported claims (scaffold)
# --------------------------------------------------------------------------

@dataclass
class ClaimVerdict:
    supported: bool | None  # None = could not be checked
    reason: str = ""


class ClaimChecker(Protocol):
    """Decides whether one narrative sentence is grounded in the packet.

    Implementations: `EvidenceRefChecker` (programmatic, below). The LLM judge runs
    offline (step6_evaluation/judge_claims.py); its verdicts are joined in by `apply_judge`.
    """

    name: str

    def check(self, sentence: str, refs: Sequence[str], packet: str | None,
              ref_ids: set[str]) -> ClaimVerdict: ...


def _norm_text(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


@dataclass
class EvidenceRefChecker:
    """Programmatic check of ``evidence_refs``.

    A sentence is *unsupported* if it has no refs, or if any ref fails to
    resolve. A ref resolves if (mode ``id``) it is one of the packet's known
    reference IDs, (mode ``span``) it appears verbatim in the packet text after
    whitespace/case normalization, or (mode ``auto``) either.

    This only checks that cited evidence exists. It does not check that the
    sentence says what the evidence says; that is the judge's job later.
    """

    mode: str = "auto"
    min_span_chars: int = 3
    name: str = "evidence_refs"

    def check(self, sentence, refs, packet, ref_ids):
        if not isinstance(refs, list) or not refs:
            return ClaimVerdict(False, "no evidence_refs")
        can_id = self.mode in ("id", "auto") and bool(ref_ids)
        can_span = self.mode in ("span", "auto") and bool(packet)
        if not (can_id or can_span):
            return ClaimVerdict(None, "no packet text or ref ids to check against")
        npacket = _norm_text(packet) if can_span else ""
        for r in refs:
            if not isinstance(r, str):
                return ClaimVerdict(False, f"non-string ref {r!r}")
            if can_id and r in ref_ids:
                continue
            nr = _norm_text(r)
            if can_span and len(nr) >= self.min_span_chars and nr in npacket:
                continue
            return ClaimVerdict(False, f"unresolved ref {r!r}")
        return ClaimVerdict(True, "all refs resolve")


# --------------------------------------------------------------------------
# Parsing and validity
# --------------------------------------------------------------------------

def parse_output(raw: Any, strip_code_fences: bool = False) -> tuple[dict | None, str | None]:
    """Return (object, error). Dicts pass through (already-parsed outputs)."""
    if isinstance(raw, dict):
        return raw, None
    if not isinstance(raw, str):
        return None, "missing or non-string output"
    text = raw.strip()
    if strip_code_fences:
        m = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, re.S)
        if m:
            text = m.group(1)
    try:
        obj = json.loads(text)
    except ValueError as e:
        return None, f"json: {e}"
    if not isinstance(obj, dict):
        return None, "top level is not an object"
    return obj, None


def make_validator(schema_path: str | Path | None) -> Callable[[dict], str | None]:
    """Return fn(obj) -> None if valid, else the first error message."""
    if not schema_path:
        return lambda obj: None
    import jsonschema
    schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    cls = jsonschema.validators.validator_for(schema)
    cls.check_schema(schema)
    v = cls(schema)

    def _validate(obj):
        err = next(iter(v.iter_errors(obj)), None)
        return None if err is None else f"schema: {err.message[:200]}"

    return _validate


# --------------------------------------------------------------------------
# Per-case scoring
# --------------------------------------------------------------------------

@dataclass
class CaseScore:
    case_id: str
    valid: bool
    error: str | None
    tags: frozenset
    decision: tuple[Any, Any]                   # (gold, pred)
    hits: list[tuple[Any, Any]]                 # (gold, pred) per gold hit
    extra_hits: int                             # predicted hits with no gold counterpart
    fields: dict[str, tuple[Any, Any]]
    risk: tuple[Any, Any]
    actions_tp: int
    actions_gold: int
    actions_pred: int
    sentences: int                              # narrative sentences checked
    unsupported: int
    unchecked: int
    latency_ms: float | None
    cost_usd: float | None
    sentence_texts: tuple = ()                  # the checked sentences, for the LLM judge lookup
    judged: int = 0                             # sentences with an LLM-judge verdict (apply_judge)
    judged_unsupported: int = 0
    unjudged: int = 0                           # sentences the judge has not seen


def _action_set(obj: Any, fm: FieldMap) -> set:
    lst = get_path(obj, fm.actions_path)
    if not isinstance(lst, list):
        return set()
    out = set()
    for it in lst:
        v = it.get(fm.actions_item_key, MISSING) if (fm.actions_item_key and isinstance(it, dict)) else it
        v = fm.lab(v)
        if v is not MISSING and isinstance(v, str):
            out.add(v)
    return out


def _hit_map(obj: Any, fm: FieldMap) -> dict[str, Any]:
    lst = get_path(obj, fm.screening_path)
    out: dict[str, Any] = {}
    if isinstance(lst, list):
        for i, it in enumerate(lst):
            if not isinstance(it, dict):
                continue
            if fm.screening_id_key is None:      # no hit id in the schema: join by position
                out[str(i)] = fm.lab(it.get(fm.screening_label_key))
            elif fm.screening_id_key in it:
                out.setdefault(str(it[fm.screening_id_key]), fm.lab(it.get(fm.screening_label_key)))
    return out


def score_case(gold: dict, pred: dict | None, fm: FieldMap,
               validator: Callable[[dict], str | None] | None = None,
               checker: ClaimChecker | None = None,
               price: dict | None = None, price_multiplier: float = 1.0) -> CaseScore:
    """Score one prediction record against one gold record."""
    validator = validator or (lambda o: None)
    checker = checker or EvidenceRefChecker()
    exp = gold.get(fm.gold_expected_key, {})
    tags = frozenset(fm.lab(t) for t in (gold.get(fm.gold_tags_key) or []))

    obj, err = (None, "no prediction") if pred is None else parse_output(
        pred.get(fm.pred_output_key), fm.strip_code_fences)
    if obj is not None:
        err = validator(obj)
    valid = obj is not None and err is None
    if not valid:
        obj = None

    def pv(path):
        if not valid:
            return INVALID
        v = fm.lab(get_path(obj, path))
        return ABSENT if v is MISSING else v

    decision = (fm.lab(get_path(exp, fm.decision_path)), pv(fm.decision_path))
    risk = (fm.lab(get_path(exp, fm.risk_path)), pv(fm.risk_path))
    fields_ = {name: (fm.lab(get_path(exp, p)), pv(p)) for name, p in fm.identity_fields.items()}

    ghits = _hit_map(exp, fm)
    phits = _hit_map(obj, fm) if valid else {}
    hits = [(g, (INVALID if not valid else (phits[h] if phits.get(h, MISSING) is not MISSING else ABSENT)))
            for h, g in ghits.items() if g is not MISSING]
    extra = len(set(phits) - set(ghits))

    gacts = _action_set(exp, fm)
    pacts = _action_set(obj, fm) if valid else set()

    n_sent = n_unsup = n_unchk = 0
    texts: list[str] = []
    if valid:
        sents = get_path(obj, fm.narrative_path)
        packet = gold.get(fm.gold_packet_key)
        ref_ids = set(gold.get(fm.gold_ref_ids_key) or [])
        if fm.packet_ref_id_regex and isinstance(packet, str):
            ref_ids |= {m.group(1) if m.groups() else m.group(0)
                        for m in re.finditer(fm.packet_ref_id_regex, packet)}
        if isinstance(sents, list):
            for s in sents:
                if isinstance(s, dict):
                    text, refs = s.get(fm.narrative_sentence_key, ""), s.get(fm.narrative_refs_key)
                    hids = s.get(fm.narrative_hit_ids_key) if fm.narrative_hit_ids_key else None
                    if isinstance(refs, list) and refs and isinstance(hids, list):
                        refs = refs + hids
                else:
                    text, refs = str(s), None
                v = checker.check(text, refs, packet, ref_ids)
                if v.supported is None:
                    n_unchk += 1
                else:
                    n_sent += 1
                    n_unsup += (not v.supported)
                    texts.append(str(text))

    lat = pred.get("latency_ms") if pred else None
    cost = case_cost(pred.get("usage") if pred else None, lat, price, price_multiplier) if pred else None
    return CaseScore(
        case_id=str(gold.get(fm.gold_id_key)), valid=valid, error=err, tags=tags,
        decision=decision, hits=hits, extra_hits=extra, fields=fields_, risk=risk,
        actions_tp=len(gacts & pacts), actions_gold=len(gacts), actions_pred=len(pacts),
        sentences=n_sent, unsupported=n_unsup, unchecked=n_unchk,
        latency_ms=float(lat) if lat is not None else None, cost_usd=cost,
        sentence_texts=tuple(texts),
    )


# --------------------------------------------------------------------------
# LLM judge verdicts (step6_evaluation/judge_claims.py writes them)
# --------------------------------------------------------------------------

def norm_sentence(text: str) -> str:
    return " ".join(str(text).split())


def sentence_key(case_id: Any, text: str) -> tuple[str, str]:
    """A judge verdict depends only on (packet, sentence text), so it is keyed by both."""
    return str(case_id), hashlib.sha256(norm_sentence(text).encode("utf-8")).hexdigest()[:16]


def load_judge_verdicts(paths: Sequence[str | Path]) -> dict[tuple[str, str], bool]:
    """{(case_id, sentence_sha): supported} from one or more verdicts.jsonl files."""
    out: dict[tuple[str, str], bool] = {}
    for p in paths:
        for r in read_jsonl(p):
            out[(str(r["case_id"]), r["sentence_sha"])] = bool(r["supported"])
    return out


def apply_judge(scores: Sequence[CaseScore], verdicts: dict[tuple[str, str], bool]) -> None:
    for s in scores:
        s.judged = s.judged_unsupported = s.unjudged = 0
        for t in s.sentence_texts:
            v = verdicts.get(sentence_key(s.case_id, t))
            if v is None:
                s.unjudged += 1
            else:
                s.judged += 1
                s.judged_unsupported += (not v)


def score_run(golds: Sequence[dict], preds: Iterable[dict], fm: FieldMap,
              validator=None, checker=None, price=None, price_multiplier=1.0
              ) -> tuple[list[CaseScore], dict[str, Any]]:
    """Score every gold case. Returns (scores, diagnostics).

    Predictions are joined by case id. Duplicate predictions keep the first;
    predictions for unknown case ids are counted and ignored.
    """
    by_id: dict[str, dict] = {}
    dupes = 0
    for p in preds:
        cid = str(p.get(fm.pred_id_key))
        if cid in by_id:
            dupes += 1
        else:
            by_id[cid] = p
    gold_ids = {str(g.get(fm.gold_id_key)) for g in golds}
    scores = [score_case(g, by_id.get(str(g.get(fm.gold_id_key))), fm, validator, checker,
                         price, price_multiplier) for g in golds]
    diag = {
        "missing_predictions": sum(1 for g in golds if str(g.get(fm.gold_id_key)) not in by_id),
        "duplicate_predictions": dupes,
        "unknown_case_ids": len(set(by_id) - gold_ids),
        "errors": [(s.case_id, s.error) for s in scores if not s.valid][:20],
    }
    return scores, diag


# --------------------------------------------------------------------------
# Aggregation
# --------------------------------------------------------------------------

def confusion_matrix(pairs: Iterable[tuple[Any, Any]], labels: Sequence[str]
                     ) -> tuple[list[str], list[str], list[list[int]]]:
    """Rows = gold labels, columns = predicted labels + (absent) + (invalid) + (other)."""
    rows = list(labels)
    cols = list(labels) + [ABSENT, INVALID, "(other)"]
    m = [[0] * len(cols) for _ in rows]
    for g, p in pairs:
        if g not in rows:
            continue
        j = cols.index(p) if p in cols else cols.index("(other)")
        m[rows.index(g)][j] += 1
    return rows, cols, m


def macro_f1(pairs: Sequence[tuple[Any, Any]], labels: Sequence[str]) -> float | None:
    """Macro F1 over `labels`. Classes absent from both gold and prediction are
    excluded (otherwise a perfect model on a subset lacking a class scores < 1).
    Wrong/absent/invalid predictions count as false negatives for the gold class."""
    if not pairs:
        return None
    f1s = []
    for c in labels:
        tp = sum(1 for g, p in pairs if g == c and p == c)
        fp = sum(1 for g, p in pairs if g != c and p == c)
        fn = sum(1 for g, p in pairs if g == c and p != c)
        if tp + fp + fn == 0:
            continue
        f1s.append(2 * tp / (2 * tp + fp + fn))
    return float(np.mean(f1s)) if f1s else None


def _rate(num: float, den: float) -> float | None:
    return num / den if den else None


def _pct(vals: list[float], q: float) -> float | None:
    return float(np.percentile(vals, q)) if vals else None


# Metric keys reported with bootstrap CIs (quality metrics only).
QUALITY_KEYS = [
    "schema_validity", "decision_accuracy", "screening_macro_f1", "field_accuracy_mean",
    "risk_exact", "risk_within_one", "actions_recall", "actions_precision",
    "unsupported_rate", "judge_unsupported_rate", "adv_escalation_rate", "adv_decision_accuracy",
]


def aggregate(scores: Sequence[CaseScore], fm: FieldMap) -> dict[str, Any]:
    """All metrics for a list of case scores. Rates are in [0, 1] or None."""
    n = len(scores)
    out: dict[str, Any] = {"n_cases": n}
    out["schema_validity"] = _rate(sum(s.valid for s in scores), n)

    dec = [s.decision for s in scores if s.decision[0] is not MISSING]
    out["n_decision"] = len(dec)
    out["decision_accuracy"] = _rate(sum(g == p for g, p in dec), len(dec))

    hits = [h for s in scores for h in s.hits]
    out["n_hits"] = len(hits)
    out["screening_macro_f1"] = macro_f1(hits, [fm.lab(l) for l in fm.screening_labels])
    out["screening_accuracy"] = _rate(sum(g == p for g, p in hits), len(hits))
    out["extra_hits"] = sum(s.extra_hits for s in scores)

    accs = []
    for name in fm.identity_fields:
        pairs = [s.fields[name] for s in scores if s.fields[name][0] is not MISSING]
        a = _rate(sum(g == p for g, p in pairs), len(pairs))
        out[f"field_accuracy.{name}"] = a
        out[f"n_field.{name}"] = len(pairs)
        if a is not None and name not in fm.field_mean_exclude:
            accs.append(a)
    out["field_accuracy_mean"] = float(np.mean(accs)) if accs else None

    order = {fm.lab(l): i for i, l in enumerate(fm.risk_labels)}
    risk = [s.risk for s in scores if s.risk[0] in order]
    out["n_risk"] = len(risk)
    out["risk_exact"] = _rate(sum(g == p for g, p in risk), len(risk))
    out["risk_within_one"] = _rate(sum(p in order and abs(order[g] - order[p]) <= 1 for g, p in risk), len(risk))

    tp = sum(s.actions_tp for s in scores)
    out["actions_recall"] = _rate(tp, sum(s.actions_gold for s in scores))
    out["actions_precision"] = _rate(tp, sum(s.actions_pred for s in scores))
    out["n_actions_gold"] = sum(s.actions_gold for s in scores)

    out["n_sentences"] = sum(s.sentences for s in scores)
    out["n_sentences_unchecked"] = sum(s.unchecked for s in scores)
    out["unsupported_rate"] = _rate(sum(s.unsupported for s in scores), out["n_sentences"])
    # LLM judge: rate over the judged sentences only (the judge covers eval_id; for a pooled eval_v1 run this
    # is exactly its eval_id rate). n_judged / n_unjudged are reported so the coverage is visible.
    out["n_judged"] = sum(s.judged for s in scores)
    out["n_unjudged"] = sum(s.unjudged for s in scores)
    out["judge_unsupported_rate"] = (_rate(sum(s.judged_unsupported for s in scores), out["n_judged"])
                                     if out["n_judged"] else None)

    esc = fm.lab(fm.escalate_label)
    union: list[CaseScore] = []
    seen = set()
    for name, tags in fm.adversarial_subsets.items():
        want = {fm.lab(t) for t in tags}
        sub = [s for s in scores if s.tags & want]
        out[f"n_adv.{name}"] = len(sub)
        esub = [s for s in sub if s.decision[0] == esc] if fm.adv_escalation_gold_escalate_only else sub
        out[f"adv_escalation_rate.{name}"] = _rate(sum(s.decision[1] == esc for s in esub), len(esub))
        out[f"adv_decision_accuracy.{name}"] = _rate(sum(s.decision[0] == s.decision[1] for s in sub), len(sub))
        for s in sub:
            if id(s) not in seen:
                seen.add(id(s))
                union.append(s)
    out["n_adv"] = len(union)
    eunion = [s for s in union if s.decision[0] == esc] if fm.adv_escalation_gold_escalate_only else union
    out["n_adv_escalation"] = len(eunion)
    out["adv_escalation_rate"] = _rate(sum(s.decision[1] == esc for s in eunion), len(eunion))
    # Escalation *rate* is what the brief asks for; whether escalate is always the
    # right answer on these subsets is a policy call, so accuracy is reported too.
    out["adv_decision_accuracy"] = _rate(sum(s.decision[0] == s.decision[1] for s in union), len(union))

    lats = [s.latency_ms for s in scores if s.latency_ms is not None]
    out["latency_p50_ms"] = _pct(lats, 50)
    out["latency_p95_ms"] = _pct(lats, 95)
    costs = [s.cost_usd for s in scores if s.cost_usd is not None]
    out["cost_per_1k_usd"] = float(np.mean(costs)) * 1000 if costs else None
    out["n_priced"] = len(costs)
    return out


# --------------------------------------------------------------------------
# Bootstrap
# --------------------------------------------------------------------------

def _ci(vals: list[float], alpha: float) -> tuple[float, float] | None:
    vals = [v for v in vals if v is not None and not math.isnan(v)]
    if not vals:
        return None
    return (float(np.percentile(vals, 100 * alpha / 2)), float(np.percentile(vals, 100 * (1 - alpha / 2))))


def bootstrap_ci(scores: Sequence[CaseScore], fm: FieldMap, keys: Sequence[str] = QUALITY_KEYS,
                 n_boot: int = 1000, seed: int = 0, alpha: float = 0.05
                 ) -> dict[str, tuple[float, float] | None]:
    """Percentile bootstrap CI per metric, resampling whole cases."""
    n = len(scores)
    if n == 0:
        return {k: None for k in keys}
    rng = np.random.default_rng(seed)
    samples: dict[str, list] = {k: [] for k in keys}
    for _ in range(n_boot):
        idx = rng.integers(0, n, n)
        agg = aggregate([scores[i] for i in idx], fm)
        for k in keys:
            samples[k].append(agg.get(k))
    return {k: _ci(v, alpha) for k, v in samples.items()}


def paired_bootstrap_delta(base: Sequence[CaseScore], new: Sequence[CaseScore], fm: FieldMap,
                           keys: Sequence[str] = QUALITY_KEYS, n_boot: int = 1000, seed: int = 0,
                           alpha: float = 0.05) -> dict[str, Any]:
    """Delta (new - base) on the cases both runs share, with a paired bootstrap
    CI: each resample draws the same case ids for both runs."""
    bmap = {s.case_id: s for s in base}
    ids = [s.case_id for s in new if s.case_id in bmap]
    nmap = {s.case_id: s for s in new}
    b = [bmap[i] for i in ids]
    a = [nmap[i] for i in ids]
    out: dict[str, Any] = {"n_paired": len(ids)}
    if not ids:
        return out
    ab, aa = aggregate(b, fm), aggregate(a, fm)
    point = {k: (aa[k] - ab[k]) if aa.get(k) is not None and ab.get(k) is not None else None for k in keys}
    rng = np.random.default_rng(seed)
    samples: dict[str, list] = {k: [] for k in keys}
    n = len(ids)
    for _ in range(n_boot):
        idx = rng.integers(0, n, n)
        gb = aggregate([b[i] for i in idx], fm)
        ga = aggregate([a[i] for i in idx], fm)
        for k in keys:
            samples[k].append(ga[k] - gb[k] if ga.get(k) is not None and gb.get(k) is not None else None)
    out["delta"] = point
    out["ci"] = {k: _ci(v, alpha) for k, v in samples.items()}
    return out


# --------------------------------------------------------------------------
# IO helpers
# --------------------------------------------------------------------------

def read_jsonl(path: str | Path) -> list[dict]:
    out = []
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError as e:
                raise ValueError(f"{path}:{i}: bad JSONL line: {e}") from None
    return out
