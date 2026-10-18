"""Table 2 S6 (mining half): rank the student's failure categories and emit a resampling mix.

    python -m step4_distillation.hard_mine --gold data/dev/cases.jsonl --truth data/dev/truth.jsonl \
        --predictions outputs/dev/student_v1/predictions.jsonl --fieldmap step6_evaluation/fieldmap_v1.yaml \
        --mix-out step1_data_generation/configs/mined_mix.yaml --report outputs/distill/hard_mine.md

Inputs are a **train or dev** split only. Eval case ids, and any gold file whose hash is in a
frozen eval manifest, are refused (mining on eval failures is a leak:
contamination_protocol.md).

A case fails if (``--failure any``, default) any rejection-sampling check fails, or
(``--failure decision``) only if the decision is wrong. A missing or invalid prediction fails.

Categories come from the truth object's knob vector (Session J; ``--knob-key``, looked up in the
truth record, then in the gold record), flattened to ``key=value`` (lists give one category per
element; numeric knobs are split into terciles). Without knobs, the case's ``scenarios`` are
used. Categories are ranked by the Wilson lower bound of their failure rate (min support
``--min-n``), so a 1/1 failure doesn't outrank 30/60.

The mix: for each primary scenario s,
    w_s = base_s * (smoothed_fail_rate_s / overall_fail_rate) ** alpha
renormalized to the base total, then blended with the base mix (``--floor``) so nothing drops to
zero. The base is ``--base-mix`` (YAML mapping, or ``{mix: mapping}``), else step1_data_generation.sample.DEFAULT_MIX.
Output YAML: ``{mix: {...}, knob_targets: [...], ...}``; pass ``mix`` to step1_data_generation/build.py.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import yaml

from step4_distillation.common import (Checker, add_check_args, add_common_args, check_cfg_from_args,
                            discover_manifests, gold_tags, load_fieldmap, load_gold, read_jsonl,
                            refuse_eval_ids, setup_logging)


def wilson_lb(k: int, n: int, z: float = 1.96) -> float:
    if n == 0:
        return 0.0
    p = k / n
    den = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (centre - margin) / den)


def _flatten(d, prefix=""):
    if isinstance(d, dict):
        for k, v in d.items():
            yield from _flatten(v, f"{prefix}{k}.")
    else:
        yield prefix[:-1], d


def knob_vector(cid: str, gold_rec: dict, truths: dict, key: str):
    for src in (truths.get(cid), gold_rec):
        if not isinstance(src, dict):
            continue
        for cand in (src.get(key), (src.get("truth") or {}).get(key) if isinstance(src.get("truth"), dict) else None):
            if isinstance(cand, dict) and cand:
                return cand
    return None


def categories(cases: dict[str, dict], gold: dict, truths: dict, fm, knob_key: str) -> tuple[dict[str, list[str]], str]:
    """-> ({case_id: [category, ...]}, source) where source is 'knobs' or 'scenarios'."""
    knobs = {cid: knob_vector(cid, gold[cid], truths, knob_key) for cid in cases}
    if not any(knobs.values()):
        return {cid: [f"scenario={t}" for t in gold_tags(gold[cid], fm)] for cid in cases}, "scenarios"
    numeric = defaultdict(list)
    for kv in knobs.values():
        for k, v in _flatten(kv or {}):
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                numeric[k].append(float(v))
    edges = {}
    for k, vals in numeric.items():
        if len(set(vals)) > 6:                       # continuous: terciles
            s = sorted(vals)
            edges[k] = (s[len(s) // 3], s[(2 * len(s)) // 3])
    out = {}
    for cid, kv in knobs.items():
        cats = [f"scenario={t}" for t in gold_tags(gold[cid], fm)]
        for k, v in _flatten(kv or {}):
            vals = v if isinstance(v, list) else [v]
            for x in vals:
                if k in edges and isinstance(x, (int, float)) and not isinstance(x, bool):
                    lo, hi = edges[k]
                    x = "low" if x <= lo else ("mid" if x <= hi else "high")
                cats.append(f"{k}={x}")
        out[cid] = cats
    return out, "knobs"


def failures(gold: dict, preds: list[dict], checker: Checker, fm, mode: str) -> dict[str, list[str]]:
    """-> {case_id: [reasons]} for every gold case with a prediction slot ([] = passed)."""
    by_id = {}
    for p in preds:
        by_id.setdefault(str(p.get(fm.pred_id_key)), p)
    out = {}
    for cid, g in gold.items():
        p = by_id.get(cid)
        if p is None:
            out[cid] = ["no_prediction"]
            continue
        raw = p.get(fm.pred_output_key)
        res = checker.check(raw, g)
        if mode == "decision":
            out[cid] = [r for r in res.reasons if r in ("decision", "unparseable", "schema_invalid")]
        else:
            out[cid] = res.reasons
    return out


def rank(fails: dict[str, list[str]], cats: dict[str, list[str]], min_n: int) -> tuple[list[dict], float]:
    n_all = len(fails)
    base = sum(bool(v) for v in fails.values()) / n_all if n_all else 0.0
    n, k = Counter(), Counter()
    reasons = defaultdict(Counter)
    for cid, rs in fails.items():
        for c in set(cats.get(cid, [])):
            n[c] += 1
            if rs:
                k[c] += 1
                reasons[c].update(rs)
    rows = []
    for c in n:
        if n[c] < min_n:
            continue
        rate = k[c] / n[c]
        rows.append({"category": c, "n": n[c], "fails": k[c], "fail_rate": round(rate, 4),
                     "wilson_lb": round(wilson_lb(k[c], n[c]), 4),
                     "lift": round(rate / base, 3) if base else None,
                     "top_reasons": dict(reasons[c].most_common(3))})
    rows.sort(key=lambda r: (-r["wilson_lb"], -r["fails"], r["category"]))
    return rows, base


def load_base_mix(path: str | None) -> tuple[dict[str, float], str]:
    if path:
        d = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return {str(k): float(v) for k, v in (d.get("mix", d)).items()}, path
    try:
        from step1_data_generation.sample import DEFAULT_MIX
        return {k: float(v) for k, v in DEFAULT_MIX.items()}, "step1_data_generation.sample.DEFAULT_MIX"
    except ImportError:
        return {}, "uniform"


def resample_mix(fails: dict[str, list[str]], gold: dict, fm, base_mix: dict[str, float],
                 alpha: float = 1.0, floor: float = 0.25, prior: float = 1.0) -> dict[str, float]:
    n, k = Counter(), Counter()
    for cid, rs in fails.items():
        tags = gold_tags(gold[cid], fm)
        if tags:                                     # primary scenario drives the generator plan
            n[tags[0]] += 1
            k[tags[0]] += bool(rs)
    base_mix = dict(base_mix) or {s: 1.0 for s in n}
    for s in n:
        base_mix.setdefault(s, sum(base_mix.values()) / max(len(base_mix), 1))
    total_n = sum(n.values())
    overall = (sum(k.values()) + prior) / (total_n + 2 * prior) if total_n else 0.5
    raw = {}
    for s, b in base_mix.items():
        rate = (k[s] + prior * overall) / (n[s] + prior) if n[s] else overall
        raw[s] = b * (rate / overall) ** alpha
    scale = sum(base_mix.values()) / (sum(raw.values()) or 1.0)
    return {s: round((1 - floor) * raw[s] * scale + floor * base_mix[s], 4) for s in sorted(base_mix)}


def guard_inputs(paths: list[str], manifests) -> None:
    """Refuse inputs whose bytes are a frozen eval file."""
    from step6_evaluation import split_guard as sg
    frozen = set()
    for mp in discover_manifests(manifests):
        m = json.loads(Path(mp).read_text(encoding="utf-8"))
        frozen |= {e.get("sha256") for e in m.get("files", []) if isinstance(e, dict)}
    for p in paths:
        if p and sg.sha256_file(p) in frozen:
            raise SystemExit(f"CONTAMINATION: {p} is a frozen eval file; mine on step5_training/dev only")


def to_markdown(rows: list[dict], base: float, source: str, mix: dict, top: int = 25) -> str:
    out = ["# Hard-case mining\n", f"Overall failure rate: {base:.1%}. Categories from: **{source}**.\n",
           "| category | n | fails | rate | Wilson LB | lift | top reasons |", "|---|---|---|---|---|---|---|"]
    for r in rows[:top]:
        out.append(f"| {r['category']} | {r['n']} | {r['fails']} | {r['fail_rate']:.1%} | {r['wilson_lb']:.1%} "
                   f"| {r['lift']} | {', '.join(f'{k} {v}' for k, v in r['top_reasons'].items())} |")
    out += ["", "## Resampling mix (pass to step1_data_generation/build.py)", "", "| scenario | weight |", "|---|---|"]
    out += [f"| {s} | {w} |" for s, w in sorted(mix.items(), key=lambda kv: -kv[1])]
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_common_args(ap)
    add_check_args(ap)
    ap.add_argument("--predictions", required=True, help="student predictions (eval record format)")
    ap.add_argument("--truth", help="truth JSONL ({case_id, truth}) holding the knob vectors")
    ap.add_argument("--knob-key", default="knobs")
    ap.add_argument("--failure", choices=["any", "decision"], default="any")
    ap.add_argument("--min-n", type=int, default=5)
    ap.add_argument("--alpha", type=float, default=1.0, help="mix sharpness (0 = base mix)")
    ap.add_argument("--floor", type=float, default=0.25, help="share of the base mix kept")
    ap.add_argument("--base-mix")
    ap.add_argument("--top-knobs", type=int, default=10)
    ap.add_argument("--mix-out", required=True)
    ap.add_argument("--report", help="markdown report path")
    a = ap.parse_args(argv)
    setup_logging(a.verbose)
    guard_inputs([a.gold, a.predictions, a.truth], a.eval_manifest)
    fm = load_fieldmap(a.fieldmap, a.schema)
    gold = load_gold(a.gold, fm)
    refuse_eval_ids(gold, what=a.gold)
    truths = {str(r.get("case_id")): (r.get("truth") or r) for r in read_jsonl(a.truth)} if a.truth else {}
    fails = failures(gold, read_jsonl(a.predictions), Checker(fm, check_cfg_from_args(a)), fm, a.failure)
    cats, source = categories(fails, gold, truths, fm, a.knob_key)
    rows, base = rank(fails, cats, a.min_n)
    base_mix, base_src = load_base_mix(a.base_mix)
    mix = resample_mix(fails, gold, fm, base_mix, a.alpha, a.floor)
    knob_targets = [r for r in rows if not r["category"].startswith("scenario=") and (r["lift"] or 0) > 1][:a.top_knobs]
    out = {"mix": mix, "knob_targets": knob_targets, "category_source": source,
           "base_mix": base_src, "overall_fail_rate": round(base, 4), "n_cases": len(fails),
           "failure_mode": a.failure, "alpha": a.alpha, "floor": a.floor, "ranking": rows}
    Path(a.mix_out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.mix_out).write_text(yaml.safe_dump(out, sort_keys=False, allow_unicode=True), encoding="utf-8")
    if a.report:
        Path(a.report).parent.mkdir(parents=True, exist_ok=True)
        Path(a.report).write_text(to_markdown(rows, base, source, mix), encoding="utf-8")
    print(f"overall fail rate {base:.1%} over {len(fails)} cases; top: "
          + ", ".join(f"{r['category']} ({r['fails']}/{r['n']})" for r in rows[:5]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
