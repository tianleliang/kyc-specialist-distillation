"""Build the benchmark tables (markdown) from saved per-case outputs.

    python -m step6_evaluation.report outputs/

Layout read from each run directory (any depth under the given paths)::

    outputs/<run_id>/predictions.jsonl   # one record per case (see step6_evaluation/metrics.py)
    outputs/<run_id>/run.json            # optional metadata, see RUN_META_KEYS

``run.json`` keys (all optional):

* ``model``: display name (default: run dir name)
* ``gold``: path to the gold JSONL (relative to the repo root or the run dir), or a list of
  paths that are concatenated in order (e.g. the 4 splits of frozen eval v1);
  ``--gold`` overrides it for every run
* ``price_key`` and ``price_multiplier``: entry in the price table (e.g. 0.5 for batch APIs)
* ``params``: parameter count shown in Table 1 (e.g. "0.8B")
* ``table1_order``: sort key for Table 1 rows; ``table1: false`` hides a run from Table 1
* ``table1_group``: Table 1 is rendered once per group (e.g. ``eval_v1``, ``eval_hard``, ``dev``)
* ``display``: metric key -> literal text shown instead of the number (e.g. latency
  ``"pending (deploy)"`` when the saved latency was measured under load)
* ``pipeline``, ``stage``, ``stage_order``: Table 2. Within each pipeline,
  stages are sorted by ``stage_order`` and each one is compared to the previous
  stage, unless ``compare_to`` names a run_id to compare against.

``--pending FILE`` (YAML) adds clearly marked placeholder rows / sections for results that do not
exist yet (``table1``: group, model, params, note; ``table2``: pipeline, stage, compared_to, note;
``sections``: title, text). Gold rows without ``ref_ids`` get them from the ``truth.jsonl`` next
to the gold file (same rule as ``step1_data_generation/project.py:ref_ids``).

Nothing here calls an API. The output depends only on the saved files, the
config, and the bootstrap seed, so reruns are byte-identical.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from step6_evaluation import metrics as M

RUN_META_KEYS = {"model", "gold", "price_key", "price_multiplier", "params", "table1_order",
                 "table1", "pipeline", "stage", "stage_order", "compare_to", "notes",
                 "table1_group", "display"}

GROUP_TITLES = {
    "eval_v1": "Frozen eval v1 (eval_id 300 + OOD template 50 + OOD hand 50 + OOD LLM 100 = 500)",
    "eval_hard": "eval_hard (150 stress cases, frozen separately)",
    "dev": "dev (150; model selection and ablations, never eval)",
    "eval_id_v2": "Fresh eval_id v2 (300; generated Sun 10/18 with the eval_id config and a new seed, untouched by any development; frontier re-run on it)",
}
GROUP_ORDER = ["eval_id_v2", "eval_v1", "eval_hard", "dev"]
SPLIT_ORDER = ["eval_id", "eval_ood_template", "eval_ood_hand", "eval_ood_llm"]


@dataclass
class Run:
    run_id: str
    path: Path
    meta: dict
    gold_path: Path | tuple
    scores: list = field(default_factory=list)
    diag: dict = field(default_factory=dict)
    agg: dict = field(default_factory=dict)
    ci: dict = field(default_factory=dict)
    splits: dict = field(default_factory=dict)   # case_id -> gold split name

    @property
    def group(self) -> str:
        return str(self.meta.get("table1_group", ""))

    @property
    def model(self) -> str:
        return self.meta.get("model", self.run_id)


def discover(paths: list[Path]) -> list[Path]:
    found = []
    for p in paths:
        if p.is_file() and p.name == "predictions.jsonl":
            found.append(p.parent)
        elif p.is_dir():
            found.extend(sorted(q.parent for q in p.rglob("predictions.jsonl")))
    return sorted(set(found))


def _resolve(p: str, run_dir: Path) -> Path:
    cand = Path(p)
    if cand.is_absolute() or cand.exists():
        return cand
    return run_dir / cand


def display(path) -> str:
    if isinstance(path, tuple):
        return " + ".join(display(p) for p in path)
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def sha256(path) -> str:
    if isinstance(path, tuple):
        return hashlib.sha256(b"".join(Path(p).read_bytes() for p in path)).hexdigest()
    return hashlib.sha256(path.read_bytes()).hexdigest()


def section_ref_ids(truth: dict) -> list[str]:
    """Valid narrative refs of a case, from its truth record (mirrors project.ref_ids)."""
    secs = ["context", "application", "id_document_visual", "id_document_mrz", "proof_of_address", "screening_hits"]
    if not (truth.get("id_doc") or {}).get("mrz_lines"):
        secs.remove("id_document_mrz")
    return secs + [h["hit_id"] for h in truth.get("hits") or []]


def read_gold(path: Path, fm) -> list[dict]:
    rows = M.read_jsonl(path)
    truth_p = path.parent / "truth.jsonl"
    if any(fm.gold_ref_ids_key not in r for r in rows) and truth_p.exists():
        truths = {t["case_id"]: t["truth"] for t in M.read_jsonl(truth_p)}
        for r in rows:
            if fm.gold_ref_ids_key not in r and r.get(fm.gold_id_key) in truths:
                r[fm.gold_ref_ids_key] = section_ref_ids(truths[r[fm.gold_id_key]])
    return rows


# ---------- formatting ----------

def f_pct(v, ci=None, signed=False) -> str:
    if v is None:
        return "n/a"
    fmt = "{:+.1f}" if signed else "{:.1f}"
    s = fmt.format(100 * v)
    if ci:
        s += " [" + fmt.format(100 * ci[0]) + ", " + fmt.format(100 * ci[1]) + "]"
    return s


def f_ms(v) -> str:
    return "n/a" if v is None else f"{v:,.0f}"


def f_usd(v) -> str:
    return "n/a" if v is None else (f"${v:,.2f}" if v >= 1 else f"${v:,.3f}")


def md_table(header: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(lines)


# ---------- tables ----------

T1_COLS = [
    ("Valid %", "schema_validity"),
    ("Decision acc %", "decision_accuracy"),
    ("Screening macro-F1 %", "screening_macro_f1"),
    ("Field acc % (mean)", "field_accuracy_mean"),
    ("Risk exact %", "risk_exact"),
    ("Risk ±1 %", "risk_within_one"),
    ("Actions recall %", "actions_recall"),
    ("Actions precision %", "actions_precision"),
    ("Unsupported claims, LLM judge % (judged sentences)", "judge_unsupported_rate"),
    ("Unsupported refs, programmatic %", "unsupported_rate"),
    ("Adversarial escalation %", "adv_escalation_rate"),
]

T2_COLS = [
    ("Δ Valid", "schema_validity"),
    ("Δ Decision", "decision_accuracy"),
    ("Δ Screening F1", "screening_macro_f1"),
    ("Δ Field acc", "field_accuracy_mean"),
    ("Δ Risk exact", "risk_exact"),
    ("Δ Actions recall", "actions_recall"),
    ("Δ Unsupported (judge)", "judge_unsupported_rate"),
    ("Δ Unsupported refs", "unsupported_rate"),
    ("Δ Adv. escalation", "adv_escalation_rate"),
]


def _cell(r: Run, key: str, text: str) -> str:
    return str(r.meta.get("display", {}).get(key, text))


def table1(runs: list[Run], fm: M.FieldMap, pending: list[dict] | None = None) -> str:
    header = ["Model", "Params", "Cases"] + [c for c, _ in T1_COLS] + ["p50 ms", "p95 ms", "$ / 1k cases"]
    rows = []
    for r in runs:
        a = r.agg
        rows.append([r.model, str(r.meta.get("params", "")), str(a["n_cases"])]
                    + [_cell(r, k, "n/a (not judged)" if k == "judge_unsupported_rate" and a.get(k) is None
                             else f_pct(a.get(k), r.ci.get(k))) for _, k in T1_COLS]
                    + [_cell(r, "latency_p50_ms", f_ms(a["latency_p50_ms"])),
                       _cell(r, "latency_p95_ms", f_ms(a["latency_p95_ms"])),
                       _cell(r, "cost_per_1k_usd", f_usd(a["cost_per_1k_usd"]))])
    for p in pending or []:
        rows.append([f"**{p['model']}** (PENDING)", str(p.get("params", "")), str(p.get("cases", ""))]
                    + ["pending"] * len(T1_COLS) + ["pending"] * 3)
    return md_table(header, rows)


def split_table(runs: list[Run], fm: M.FieldMap) -> str:
    """Decision / risk / actions recall per gold split, for runs whose gold spans several splits."""
    splits = [s for s in SPLIT_ORDER if any(s in r.splits.values() for r in runs)]
    splits += sorted({s for r in runs for s in r.splits.values()} - set(splits))
    header = ["Model"] + [f"{s}: n, decision / risk / actions recall %" for s in splits]
    rows = []
    for r in runs:
        cells = [r.model]
        for sp in splits:
            sub = [s for s in r.scores if r.splits.get(s.case_id) == sp]
            if not sub:
                cells.append("")
                continue
            a = M.aggregate(sub, fm)
            cells.append(f"{len(sub)}: {f_pct(a['decision_accuracy'])} / {f_pct(a['risk_exact'])} / "
                         f"{f_pct(a['actions_recall'])}")
        rows.append(cells)
    return md_table(header, rows)


def table1b(runs: list[Run], fm: M.FieldMap) -> str:
    names = list(fm.identity_fields)
    subs = list(fm.adversarial_subsets)
    header = (["Model"] + [f"{n} acc %" for n in names] + [f"Esc. {s} % (n)" for s in subs]
              + ["Adv. decision acc %", "Hits", "Extra hits", "Sentences checked", "Sentences judged", "Missing preds"])
    rows = []
    for r in runs:
        a = r.agg
        rows.append([r.model] + [f_pct(a.get(f"field_accuracy.{n}")) for n in names]
                    + [f"{f_pct(a.get(f'adv_escalation_rate.{s}'))} ({a.get(f'n_adv.{s}', 0)})" for s in subs]
                    + [f_pct(a.get("adv_decision_accuracy")), str(a["n_hits"]), str(a["extra_hits"]), str(a["n_sentences"]), str(a["n_judged"]),
                       str(r.diag.get("missing_predictions", 0))])
    return md_table(header, rows)


def stage_pairs(runs: list[Run]) -> list[tuple[Run, Run]]:
    by_id = {r.run_id: r for r in runs}
    staged = [r for r in runs if "stage" in r.meta]
    pairs = []
    pipelines: dict[str, list[Run]] = {}
    for r in staged:
        pipelines.setdefault(str(r.meta.get("pipeline", "main")), []).append(r)
    for name in sorted(pipelines):
        seq = sorted(pipelines[name], key=lambda r: (r.meta.get("stage_order", 0), r.run_id))
        for i, r in enumerate(seq):
            base_id = r.meta.get("compare_to")
            if base_id:
                if base_id not in by_id:
                    raise SystemExit(f"run {r.run_id}: compare_to {base_id!r} not found")
                pairs.append((by_id[base_id], r))
            elif i > 0:
                pairs.append((seq[i - 1], r))
    return pairs


def table2(runs: list[Run], fm: M.FieldMap, n_boot: int, seed: int, pending: list[dict] | None = None) -> str:
    pairs = stage_pairs(runs)
    if not pairs and not pending:
        return "_No staged runs (add `stage` / `stage_order` to run.json)._"
    header = ["Pipeline", "Stage", "Compared to", "Paired cases"] + [c for c, _ in T2_COLS]
    rows = []
    for base, new in pairs:
        if base.gold_path != new.gold_path:
            raise SystemExit(f"Table 2: {new.run_id} and {base.run_id} use different gold files")
        d = M.paired_bootstrap_delta(base.scores, new.scores, fm, n_boot=n_boot, seed=seed)
        rows.append([str(new.meta.get("pipeline", "main")), f"{new.meta['stage']} ({new.model})",
                     f"{base.meta.get('stage', base.run_id)} ({base.model})", str(d["n_paired"])]
                    + [f_pct(d.get("delta", {}).get(k), d.get("ci", {}).get(k), signed=True) for _, k in T2_COLS])
    for p in pending or []:
        rows.append([str(p["pipeline"]), f"**{p['stage']}** (PENDING)", str(p.get("compared_to", "")), "pending"]
                    + ["pending"] * len(T2_COLS))
    return md_table(header, rows)


def confusion_section(runs: list[Run], fm: M.FieldMap) -> str:
    out = []
    labels = [fm.lab(l) for l in fm.decision_labels]
    for r in runs:
        rows_, cols, m = M.confusion_matrix([s.decision for s in r.scores], labels)
        keep = [j for j, c in enumerate(cols) if c in labels or any(row[j] for row in m)]
        out.append(f"**{r.model}** (rows = expected, columns = predicted)\n\n"
                   + md_table(["expected \\ predicted"] + [cols[j] for j in keep],
                              [[rows_[i]] + [str(m[i][j]) for j in keep] for i in range(len(rows_))]))
    return "\n\n".join(out)


# ---------- main ----------

def load_runs(paths: list[Path], fm: M.FieldMap, gold_override: Path | None,
              prices: dict, judge: dict | None = None) -> list[Run]:
    validator = M.make_validator(fm.schema_path)
    checker = M.EvidenceRefChecker()
    gold_cache: dict[Any, list[dict]] = {}
    runs = []
    for d in discover(paths):
        meta = json.loads((d / "run.json").read_text(encoding="utf-8")) if (d / "run.json").exists() else {}
        unknown = set(meta) - RUN_META_KEYS
        if unknown:
            print(f"warning: {d}/run.json has unknown keys {sorted(unknown)}", file=sys.stderr)
        if gold_override:
            gp = gold_override.resolve()
        elif isinstance(meta.get("gold"), list):
            gp = tuple(_resolve(g, d).resolve() for g in meta["gold"])
        elif meta.get("gold"):
            gp = _resolve(meta["gold"], d).resolve()
        else:
            raise SystemExit(f"{d}: no gold file (set `gold` in run.json or pass --gold)")
        if gp not in gold_cache:
            gold_cache[gp] = [row for g in (gp if isinstance(gp, tuple) else (gp,)) for row in read_gold(g, fm)]
        price = prices.get(meta["price_key"]) if meta.get("price_key") else None
        if meta.get("price_key") and price is None:
            print(f"warning: {d}: price_key {meta['price_key']!r} not in price table", file=sys.stderr)
        run = Run(run_id=d.name, path=d, meta=meta, gold_path=gp,
                  splits={str(g.get(fm.gold_id_key)): str(g.get("split", "")) for g in gold_cache[gp]})
        run.scores, run.diag = M.score_run(gold_cache[gp], M.read_jsonl(d / "predictions.jsonl"), fm,
                                           validator, checker, price, float(meta.get("price_multiplier", 1.0)))
        M.apply_judge(run.scores, judge or {})
        runs.append(run)
    ids = [r.run_id for r in runs]
    if len(ids) != len(set(ids)):
        raise SystemExit(f"duplicate run ids (run dir names must be unique): {ids}")
    return runs


def _group_key(g: str) -> tuple:
    return (GROUP_ORDER.index(g) if g in GROUP_ORDER else len(GROUP_ORDER), g)


def build_report(runs: list[Run], fm: M.FieldMap, n_boot: int, seed: int, command: str,
                 pending: dict | None = None) -> str:
    pending = pending or {}
    for r in runs:
        r.agg = M.aggregate(r.scores, fm)
        r.ci = M.bootstrap_ci(r.scores, fm, n_boot=n_boot, seed=seed)
    t1 = sorted([r for r in runs if r.meta.get("table1", True)],
                key=lambda r: (r.meta.get("table1_order", 1e9), r.run_id))
    golds = sorted({r.gold_path for r in runs}, key=display)
    parts = [
        "# Benchmark report",
        "",
        f"Generated by `{command}`. Bootstrap: {n_boot} case resamples, seed {seed}, 95% percentile CIs in brackets.",
        "Invalid, unparseable or missing outputs score zero on every quality metric (the gold file is the denominator).",
        "",
        "Gold files (sha256):",
        "",
    ]
    n_gold = {g: sum(len(M.read_jsonl(x)) for x in (g if isinstance(g, tuple) else (g,))) for g in golds}
    parts += [f"- `{display(g)}`: `{sha256(g)[:16]}…` ({n_gold[g]} cases)" for g in golds]
    if pending.get("intro"):
        parts += ["", str(pending["intro"]).strip()]
    groups = sorted({r.group for r in t1}, key=_group_key)
    pend1 = pending.get("table1") or []
    parts += ["", "## Table 1: models × metrics"]
    for g in groups:
        rows = [r for r in t1 if r.group == g]
        if g:
            parts += ["", f"### {GROUP_TITLES.get(g, g)}"]
        if len({r.gold_path for r in rows}) > 1:
            parts += ["", "**Warning:** runs in this table use different gold files; rows are not directly comparable."]
        parts += ["", table1(rows, fm, [p for p in pend1 if str(p.get("group", "")) == g])]
        if any(len(set(r.splits.values())) > 1 for r in rows):
            parts += ["", "Per split (the same runs, scores restricted to each split's cases):", "",
                      split_table([r for r in rows if len(set(r.splits.values())) > 1], fm)]
        parts += ["", "Per identity field, adversarial subsets, counts:", "", table1b(rows, fm)]
    parts += ["", "Unsupported claims, LLM judge (the brief's metric): share of narrative sentences from schema-valid outputs "
              "that a blind Claude Sonnet judge found not grounded in the packet and policy v1 (`step6_evaluation/judge_claims.py`, "
              "prompt v2; sentences of all runs pooled and shuffled per case, one call per packet); `n/a` where a run's sentences "
              "judge covers the `eval_id` cases only, so the column is each run's eval_id rate (sentences judged / not judged are in Table 1b); `n/a` = no judged sentences. Unsupported refs, programmatic: share of the same sentences whose "
              "`evidence_refs` / `hit_ids` are missing or do not resolve to the packet (checks that cited evidence exists, not that "
              "the sentence is true). Lower is better for both. Latency and cost are point estimates from the saved per-case "
              "measurements; a literal text in a cell (e.g. `pending (deploy)`) comes from the run's `display` override, used where "
              "the saved latency was measured under load."]
    notes = [f"- **{r.model}** (`{r.run_id}`): {r.meta['notes']}" for r in t1 if r.meta.get("notes")]
    if notes:
        parts += ["", "Run notes:", ""] + notes
    parts += ["", "## Table 2: stage deltas (paired bootstrap)", "",
              table2(runs, fm, n_boot, seed, pending.get("table2") or []),
              "", "Deltas are percentage points, new stage minus the stage it is compared to, on the cases both share. "
              "For unsupported claims, negative is better."]
    for sec in pending.get("sections") or []:
        parts += ["", f"## {sec['title']}", "", str(sec.get("text", "")).strip()]
    parts += ["", "## Decision confusion matrices", "", confusion_section(t1, fm)]
    issues = [(r.run_id, r.diag) for r in runs
              if r.diag["missing_predictions"] or r.diag["duplicate_predictions"] or r.diag["unknown_case_ids"]]
    if issues:
        parts += ["", "## Data warnings", ""]
        parts += [f"- `{rid}`: {d['missing_predictions']} missing, {d['duplicate_predictions']} duplicate, "
                  f"{d['unknown_case_ids']} unknown case ids" for rid, d in issues]
    return "\n".join(parts) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m step6_evaluation.report", description=__doc__.split("\n")[0])
    ap.add_argument("paths", nargs="+", type=Path, help="run dirs or a parent dir such as outputs/")
    ap.add_argument("--config", type=Path, help="FieldMap YAML/JSON (default: built-in fixture mapping)")
    ap.add_argument("--schema", type=Path, help="JSON Schema for validity (overrides config schema_path)")
    ap.add_argument("--gold", type=Path, help="gold JSONL for every run (overrides run.json)")
    ap.add_argument("--prices", type=Path, help="YAML/JSON price table merged over the defaults")
    ap.add_argument("--n-boot", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--judge", type=Path, action="append", default=[],
                    help="LLM-judge verdicts.jsonl (repeatable), e.g. results/judge/eval_id/verdicts.jsonl")
    ap.add_argument("--out", type=Path, help="write markdown here as well as stdout")
    ap.add_argument("--json", type=Path, help="write per-run aggregate metrics as JSON")
    ap.add_argument("--quiet", action="store_true", help="do not echo the markdown to stdout")
    ap.add_argument("--pending", type=Path, help="YAML of placeholder rows/sections for results not yet run")
    args = ap.parse_args(argv)

    fm = M.FieldMap.load(args.config) if args.config else M.FieldMap()
    if args.schema:
        fm.schema_path = str(args.schema)
    prices = dict(M.DEFAULT_PRICES)
    if args.prices:
        text = args.prices.read_text(encoding="utf-8")
        if args.prices.suffix in (".yaml", ".yml"):
            import yaml
            prices.update(yaml.safe_load(text) or {})
        else:
            prices.update(json.loads(text))

    runs = load_runs(args.paths, fm, args.gold, prices, M.load_judge_verdicts(args.judge))
    if not runs:
        print(f"no predictions.jsonl found under {[str(p) for p in args.paths]}", file=sys.stderr)
        return 1
    command = "python -m step6_evaluation.report " + " ".join(argv if argv is not None else sys.argv[1:])
    pending = None
    if args.pending:
        import yaml
        pending = yaml.safe_load(args.pending.read_text(encoding="utf-8")) or {}
    md = build_report(runs, fm, args.n_boot, args.seed, command, pending)
    if not args.quiet:
        sys.stdout.write(md)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(md, encoding="utf-8", newline="\n")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({r.run_id: {"model": r.model, "metrics": r.agg,
                                                    "ci95": r.ci, "diagnostics": r.diag} for r in runs},
                                        indent=2, default=str), encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
