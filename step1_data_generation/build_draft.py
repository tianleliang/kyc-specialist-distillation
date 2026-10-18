"""Write the PROVISIONAL draft case set.

    python -m step1_data_generation.build_draft                      # 200 cases, seed 20261017 -> data/draft/
    python -m step1_data_generation.build_draft --n 50 --seed 7 --out /tmp/x

Outputs (one JSON object per line, aligned by case_id):
  cases.jsonl     {case_id, schema, style, scenarios, packet, expected}
  truth.jsonl     {case_id, truth}    hidden latent facts (never shown to a model)
  manifest.json   counts, seed, generator version, sha256 of each file

DRAFT ONLY: not an eval set, not training data (see data/draft/README.md).
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
from pathlib import Path

import jsonschema

from step1_data_generation.project import SCHEMA, SCHEMA_ID, project
from step1_data_generation.render import render
from step1_data_generation.sample import sample_cases
from step1_data_generation.truth import GENERATOR_VERSION

DEFAULT_SEED = 20261017


def build(n: int, seed: int, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    validator = jsonschema.Draft202012Validator(SCHEMA)
    cases = sample_cases(n, seed)
    rows, truths = [], []
    for c in cases:
        packet, style = render(c)
        expected = project(c)
        errs = list(validator.iter_errors(expected))
        if errs:
            raise ValueError(f"{c.case_id}: expected output fails schema: {errs[0].message}")
        rows.append({"case_id": c.case_id, "schema": SCHEMA_ID, "style": style,
                     "scenarios": c.scenarios, "packet": packet, "expected": expected})
        truths.append({"case_id": c.case_id, "truth": c.to_dict()})
    files = {"cases.jsonl": rows, "truth.jsonl": truths}
    manifest = {"status": "DRAFT - not an eval set, do not use for training",
                "generator_version": GENERATOR_VERSION, "schema": SCHEMA_ID, "seed": seed, "n": n,
                "command": f"python -m step1_data_generation.build_draft --n {n} --seed {seed}",
                "scenario_counts": dict(collections.Counter(s for r in rows for s in r["scenarios"])),
                "primary_scenario_counts": dict(collections.Counter(r["scenarios"][0] for r in rows)),
                "decision_counts": dict(collections.Counter(r["expected"]["decision"] for r in rows)),
                "risk_tier_counts": dict(collections.Counter(r["expected"]["risk_tier"] for r in rows)),
                "style_counts": dict(collections.Counter(r["style"] for r in rows)),
                "sha256": {}}
    for name, items in files.items():
        data = "".join(json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n" for x in items)
        (out / name).write_text(data, encoding="utf-8", newline="\n")  # LF on every OS so hashes match
        manifest["sha256"][name] = hashlib.sha256(data.encode("utf-8")).hexdigest()
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                                       encoding="utf-8", newline="\n")
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--out", type=Path, default=Path("data/draft"))
    a = ap.parse_args(argv)
    m = build(a.n, a.seed, a.out)
    print(json.dumps({k: m[k] for k in ("n", "seed", "decision_counts", "risk_tier_counts", "sha256")}, indent=2))


if __name__ == "__main__":
    main()
