"""Build one split of generated cases from a config in step1_data_generation/configs/.

    python -m step1_data_generation.build --config step1_data_generation/configs/train.yaml --n 3000            # -> data/train/
    python -m step1_data_generation.build --config step1_data_generation/configs/dev.yaml --n 150               # -> data/dev/
    python -m step1_data_generation.build --config step1_data_generation/configs/train.yaml --n 50 --out /tmp/x \\
        --set ocr_digit_to_digit_in_numeric=false --set twins.enabled=true
    python -m step1_data_generation.build --config step1_data_generation/configs/eval_id.yaml --n 300 --allow-eval   # ONLY after the schema decision
    # augmentation of data/train's 3,000 base cases, written on its own (base rows left out):
    python -m step1_data_generation.build --config step1_data_generation/configs/train.yaml --n 3000 --augment-only \
        --set twins.enabled=true --set twins.fraction=0.3334 --set twins.max_op_share=0.12 --out data/train_twins

Outputs (one JSON object per line, aligned by case_id):
  cases.jsonl      {case_id, split, config_id, schema, style, scenarios, knobs, packet, ref_ids, expected}
                   (ref_ids: the narrative refs valid for this packet: its sections, then its hit ids)
  truth.jsonl      {case_id, truth}            hidden latent facts (never shown to a model)
  twins.jsonl      pair records (only when twins are enabled)
  knockouts.jsonl  knockout records (only when knockouts are enabled)
  manifest.json    config + overrides + sha256 of the config and of every file, counts, command

The same config, seed and n reproduce every file byte for byte.
Train/dev builds are checked with step6_evaluation/split_guard.py against any frozen
eval manifest found under data/ (data/eval*/MANIFEST.json); contamination aborts the build.
"""
from __future__ import annotations

import argparse
import collections
import glob
import hashlib
import json
import random
import subprocess
import sys
from pathlib import Path

import jsonschema
import yaml

from step1_data_generation.config import EVAL_SPLITS, GenConfig, load_config
from step1_data_generation.knockout import make_knockouts
from step1_data_generation.project import SCHEMA, SCHEMA_ID, project, ref_ids
from step1_data_generation.render import render
from step1_data_generation.sample import sample_cases
from step1_data_generation.truth import GENERATOR_VERSION, CaseTruth
from step1_data_generation.twins import FLIPS, make_twins


# --------------------------------------------------------------------------
# config overrides: --set a.b=value (value parsed as YAML)
# --------------------------------------------------------------------------
def apply_overrides(cfg: GenConfig, sets: list[str]) -> GenConfig:
    if not sets:
        return cfg
    d = cfg.to_dict()
    for s in sets:
        key, _, raw = s.partition("=")
        if not _:
            raise ValueError(f"--set expects key=value, got {s!r}")
        val = yaml.safe_load(raw)
        parts = key.split(".")
        if parts[0] not in d:
            raise ValueError(f"unknown config key {parts[0]!r}")
        tgt = d
        for p in parts[:-1]:
            tgt[p] = dict(tgt.get(p) or {})
            tgt = tgt[p]
        tgt[parts[-1]] = val
    return GenConfig(**d)


# --------------------------------------------------------------------------
# entities (for cross-split disjointness checks)
# --------------------------------------------------------------------------
def entities(t: CaseTruth) -> dict[str, set[str]]:
    """Reusable entities a case exposes, keyed by pool (the pools partitioned by
    step1_data_generation.config.Partition)."""
    names = {t.person.name.full(order="given_first").casefold()}
    entry_ids, listed = set(), set()
    for h in t.hits:
        entry_ids.add(h.entry["entry_id"])
        listed.add(h.entry["primary_name"].casefold())
    addr = {"|".join(map(str, t.person.address.key()))}
    return {"person_name": names, "doc_number": {t.id_doc.genuine["doc_number"]},
            "address": addr, "watchlist_entry": entry_ids, "listed_name": listed,
            "injection_text": {t.injection.text} if t.injection.present else set()}


def entity_sets(truths: list[CaseTruth]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = collections.defaultdict(set)
    for t in truths:
        for k, v in entities(t).items():
            out[k] |= v
    return dict(out)


# --------------------------------------------------------------------------
def _git_commit() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                              check=True, cwd=Path(__file__).resolve().parents[1]).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _augment(cfg: GenConfig, base: list[CaseTruth], n: int, seed: int):
    twins, kos, recs_tw, recs_ko = [], [], [], []
    if cfg.twins.get("enabled"):
        rng = random.Random(f"twins:{cfg.config_id}:{seed}")
        want = round(float(cfg.twins.get("fraction", 0.25)) * n)
        all_ops = list(cfg.twins.get("ops") or FLIPS)
        # optional cap per flip op, so an op that always flips (e.g. tampering under D4) can't dominate
        share = cfg.twins.get("max_op_share")
        cap = max(1, round(float(share) * want)) if share else None
        used: collections.Counter = collections.Counter()
        order = list(base)
        rng.shuffle(order)
        for b in order:
            if len(recs_tw) >= want:
                break
            ops = [o for o in all_ops if cap is None or used[o] < cap]
            for tw, rec in make_twins(b, rng, ops, int(cfg.twins.get("per_base", 1))):
                twins.append(tw)
                recs_tw.append(rec)
                used[rec["op"]] += 1
    if cfg.knockout.get("enabled"):
        rng = random.Random(f"knockout:{cfg.config_id}:{seed}")
        want = round(float(cfg.knockout.get("fraction", 0.12)) * n)
        order = list(base)
        rng.shuffle(order)
        for b in order:
            if len(recs_ko) >= want:
                break
            for ko, rec in make_knockouts(b, rng, cfg.knockout.get("ops"), 1,
                                          bool(cfg.knockout.get("require_change", True))):
                kos.append(ko)
                recs_ko.append(rec)
    return twins, kos, recs_tw, recs_ko


def _frozen_eval_files(root: Path) -> list[str]:
    files = []
    from step6_evaluation.split_guard import exact_name_exists
    for m in sorted(glob.glob(str(root / "data" / "eval*" / "MANIFEST.json"))):
        if not exact_name_exists(m):  # Windows: don't mistake a build manifest.json for the freeze manifest
            continue
        man = json.loads(Path(m).read_text(encoding="utf-8"))
        for e in man.get("files", []):
            p = Path(e["path"])
            files.append(str(p if p.is_absolute() else (Path(m).parent / p)))
    return [f for f in files if Path(f).exists()]


def build(cfg: GenConfig, n: int, seed: int | None, out: Path, *, overrides: list[str] | None = None,
          allow_eval: bool = False, force: bool = False, guard: bool = True, augment_only: bool = False) -> dict:
    if cfg.split in EVAL_SPLITS and not allow_eval:
        raise SystemExit(f"refusing to build {cfg.split}: the real eval set is frozen only after the schema "
                         "decision. Pass --allow-eval (and freeze with step6_evaluation/split_guard.py right after).")
    seed = cfg.default_seed if seed is None else seed
    cfg.check_seed(seed)
    out.mkdir(parents=True, exist_ok=True)
    for frozen in ("MANIFEST.json", "manifest.json"):
        from step6_evaluation.split_guard import exact_name_exists
        if exact_name_exists(out / frozen) and not force:
            raise SystemExit(f"{out / frozen} exists; refusing to overwrite (use --force for a scratch dir)")
    validator = jsonschema.Draft202012Validator(SCHEMA)
    base = sample_cases(n, seed, cfg=cfg)
    twins, kos, recs_tw, recs_ko = _augment(cfg, base, n, seed)
    rows, truths = [], []
    if augment_only and not (twins or kos):
        raise SystemExit("--augment-only needs twins.enabled or knockout.enabled")
    for c in (twins + kos if augment_only else base + twins + kos):
        packet, style = render(c)
        expected = project(c)
        errs = list(validator.iter_errors(expected))
        if errs:
            raise ValueError(f"{c.case_id}: expected output fails schema: {errs[0].message}")
        rows.append({"case_id": c.case_id, "split": cfg.split, "config_id": cfg.config_id, "schema": SCHEMA_ID,
                     "style": style, "scenarios": c.scenarios, "knobs": c.knobs, "packet": packet,
                     "ref_ids": ref_ids(c), "expected": expected})
        truths.append({"case_id": c.case_id, "truth": c.to_dict()})
    files = {"cases.jsonl": rows, "truth.jsonl": truths}
    if recs_tw:
        files["twins.jsonl"] = recs_tw
    if recs_ko:
        files["knockouts.jsonl"] = recs_ko
    cmd = (f"python -m step1_data_generation.build --config {cfg.source_path or '<in-memory>'} --n {n} --seed {seed}"
           + (" --augment-only" if augment_only else "") + "".join(f" --set {s}" for s in overrides or []))
    manifest = {
        "split": cfg.split, "config_id": cfg.config_id, "config_path": cfg.source_path,
        "config_sha256": cfg.source_sha256, "overrides": list(overrides or []),
        "config": {k: v for k, v in cfg.to_dict().items() if k not in ("source_path", "source_sha256")},
        "generator_version": GENERATOR_VERSION, "git_commit": _git_commit(), "schema": SCHEMA_ID,
        "seed": seed, "n_base": n, "augment_only": augment_only, "n_twins": len(twins), "n_knockouts": len(kos), "n_total": len(rows),
        "command": cmd,
        "primary_scenario_counts": dict(collections.Counter(r["scenarios"][0] for r in rows)),
        "decision_counts": dict(collections.Counter(r["expected"]["decision"] for r in rows)),
        "risk_tier_counts": dict(collections.Counter(r["expected"]["risk_tier"] for r in rows)),
        "style_counts": dict(collections.Counter(r["style"] for r in rows)),
        "augmentation_counts": dict(collections.Counter(str(r["knobs"].get("augmentation")) for r in rows)),
        "sha256": {},
    }
    for name, items in files.items():
        data = "".join(json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n" for x in items)
        (out / name).write_text(data, encoding="utf-8", newline="\n")  # LF on every OS so hashes match
        manifest["sha256"][name] = hashlib.sha256(data.encode("utf-8")).hexdigest()

    if guard and cfg.split in ("train", "dev"):
        ev = _frozen_eval_files(Path(__file__).resolve().parents[1])
        if ev:
            from step6_evaluation import split_guard as SG
            rep = SG.check_overlap(SG.load_docs([str(out / "cases.jsonl")]), SG.load_docs(ev))
            manifest["split_guard"] = {"eval_files": ev, "contaminated_eval_records": rep["contaminated_eval_records"]}
            if rep["contaminated_eval_records"]:
                (out / "cases.jsonl").unlink()
                raise SystemExit(f"split_guard: {rep['contaminated_eval_records']} eval records overlap this build; "
                                 "cases.jsonl removed")
        else:
            manifest["split_guard"] = "no frozen eval manifest found under data/eval*/"
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                                       encoding="utf-8", newline="\n")
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--n", type=int, required=True)
    ap.add_argument("--seed", type=int, help="defaults to the config's default_seed; must be in its seed_range")
    ap.add_argument("--out", type=Path, help="defaults to data/<split>/")
    ap.add_argument("--set", dest="sets", action="append", default=[], metavar="KEY=VALUE",
                    help="override a config value (YAML-parsed; dotted keys for nested, e.g. twins.enabled=true)")
    ap.add_argument("--allow-eval", action="store_true", help="permit building an eval split")
    ap.add_argument("--force", action="store_true", help="overwrite an existing manifest in --out")
    ap.add_argument("--augment-only", action="store_true",
                    help="write only the twin/knockout rows (the base cases are sampled, used, and left out)")
    a = ap.parse_args(argv)
    cfg = apply_overrides(load_config(a.config), a.sets)
    out = a.out or Path("data") / cfg.split
    m = build(cfg, a.n, a.seed, out, overrides=a.sets, allow_eval=a.allow_eval, force=a.force,
              augment_only=a.augment_only)
    print(json.dumps({k: m[k] for k in ("split", "seed", "n_total", "decision_counts", "style_counts", "sha256")},
                     indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
