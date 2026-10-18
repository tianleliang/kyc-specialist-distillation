"""Build data/reader_dev: reader-development cases for the pre-checker (Session P3, SUNDAY_READER_V3 §3).

    python -m step7_serving.build_reader_dev            # -> data/reader_dev/ (600 cases, seed 1500000)

Train process (configs/train.yaml), an unused train seed (train uses 1000000, its
augmentations reuse it), all 6 generator layout styles. GenConfig refuses the held-out
styles (email, ocr_dump) for split=train because they must never reach *training*; this
set is for developing the deterministic reader only and never feeds training, so the
styles are set after validation. Cases keep split=train semantics (train entity buckets),
so the build's split_guard overlap check still runs.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from step1_data_generation.build import apply_overrides, build
from step1_data_generation.config import HELDOUT_STYLES, SEEN_STYLES, load_config

ROOT = Path(__file__).resolve().parents[1]
STYLES = {s: 1.0 for s in SEEN_STYLES + HELDOUT_STYLES}
CHECK_SPLITS = ("train", "dev", "train_twins", "train_knockout")


def _ids(path: Path) -> set[str]:
    with path.open(encoding="utf-8") as f:
        return {json.loads(line)["case_id"] for line in f if line.strip()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=600)
    ap.add_argument("--seed", type=int, default=1500000)
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "reader_dev")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    cfg = apply_overrides(load_config(ROOT / "step1_data_generation/configs/train.yaml"), [])
    cfg.styles = dict(STYLES)
    cfg.notes = "reader_dev: train process, unused train seed, all 6 styles; reader development only, never training"
    m = build(cfg, a.n, a.seed, a.out, overrides=[f"styles={json.dumps(STYLES)}"], force=a.force)
    new = _ids(a.out / "cases.jsonl")
    overlap = {s: len(new & _ids(ROOT / "data" / s / "cases.jsonl"))
               for s in CHECK_SPLITS if (ROOT / "data" / s / "cases.jsonl").exists()}
    print(json.dumps({"n_total": m["n_total"], "style_counts": m["style_counts"],
                      "case_id_overlap": overlap, "split_guard": m.get("split_guard") if isinstance(
                          m.get("split_guard"), str) else {"contaminated_eval_records":
                                                           m["split_guard"]["contaminated_eval_records"]}},
                     indent=2))
    return 1 if any(overlap.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
