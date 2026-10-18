"""Add the code-computed PRE-CHECKS block to every row of an SFT file (Final B).

    python -m step4_distillation.add_prechecks --in data/sft/gold_train.jsonl --out data/sft/gold_train_pc.jsonl
    python -m step4_distillation.add_prechecks --all     # the 4 distill files + gold_train (+ _solnarr) -> data/sft/*_pc.jsonl

Per row, ``step7_serving.prechecks.apply_prechecks`` appends the block after the packet in
the user message and one note to the system message. That same function is used by the dev
eval (``run_endpoint --prechecks``) and the serving proxy (``ZORBE_PRECHECKS=1``), so the
prompt text is byte-identical across training, eval and serving. Assistant targets are
NOT changed. Rows holding eval case ids are refused. Writes ``<out>.stats.json``.

``--blank-rate 0.25 --seed 17``: a deterministic share of rows (sha256 of seed and the row's
case id, else its index) gets the block with every item rendered n/d, so the model learns to
fall back to the packet; ``blanked_rows`` in the stats counts them.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from step4_distillation.common import refuse_eval_ids
from step7_serving.prechecks import apply_prechecks_with_result

ALL = ["distill_floor_sol", "distill_reject_sol", "distill_arbitrate_splice",
       "distill_arbitrate_plus_twins", "gold_train", "gold_train_solnarr"]
_ND_FIELDS = ("as_of", "mrz", "expiry", "poa_date", "integrity")


def is_blanked(key: str, rate: float, seed: int) -> bool:
    """Deterministic: the same (seed, key) is always blanked or never."""
    if rate <= 0:
        return False
    h = int.from_bytes(hashlib.sha256(f"{seed}:{key}".encode()).digest()[:8], "big")
    return h / 2 ** 64 < rate


def add_prechecks(inp: str | Path, out: str | Path, limit: int | None = None, blank_rate: float = 0.0,
                  seed: int = 17) -> dict:
    inp, out = Path(inp), Path(out)
    if inp.resolve() == out.resolve():
        raise SystemExit("--out must differ from --in")
    with open(inp, encoding="utf-8") as f:
        rows = [json.loads(l) for l in f if l.strip()]
    if limit:
        rows = rows[:limit]
    refuse_eval_ids([r.get(k) for r in rows for k in ("case_id", "id") if r.get(k) is not None], what=str(inp))

    nd = {k: 0 for k in _ND_FIELDS}
    stats = {"input": inp.as_posix(), "output": out.as_posix(), "rows": len(rows), "blocks_added": 0,
             "assistant_targets_changed": 0, "blank_rate": blank_rate, "blank_seed": seed, "blanked_rows": 0}
    out_rows = []
    for i, r in enumerate(rows):
        msgs = r["messages"]
        key = str(r.get("case_id") or r.get("id") or i)
        blank = is_blanked(key, blank_rate, seed)
        new, res = apply_prechecks_with_result(msgs, blank=blank)
        if res is not None:
            stats["blocks_added"] += 1
            stats["blanked_rows"] += blank
            for k in _ND_FIELDS:
                v = res.get(k)
                nd[k] += (v or {}).get("overall") is None if k == "integrity" else v is None
        if [m for m in new if m["role"] == "assistant"] != [m for m in msgs if m["role"] == "assistant"]:
            stats["assistant_targets_changed"] += 1  # must stay 0
        out_rows.append({**r, "messages": new})
    if stats["assistant_targets_changed"]:
        raise SystemExit(f"BUG: assistant targets changed in {stats['assistant_targets_changed']} rows")
    stats["nd_counts"] = nd
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        for r in out_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    Path(str(out) + ".stats.json").write_text(json.dumps(stats, indent=1) + "\n", encoding="utf-8")
    return stats


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--in", dest="inp")
    ap.add_argument("--out")
    ap.add_argument("--all", action="store_true", help=f"data/sft/{{{','.join(ALL)}}}.jsonl -> *_pc.jsonl")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--blank-rate", type=float, default=0.0, help="share of rows whose block is all n/d")
    ap.add_argument("--seed", type=int, default=17, help="seed for which rows are blanked")
    a = ap.parse_args(argv)
    if a.all:
        jobs = [(f"data/sft/{n}.jsonl", f"data/sft/{n}_pc.jsonl") for n in ALL]
    elif a.inp and a.out:
        jobs = [(a.inp, a.out)]
    else:
        ap.error("give --in and --out, or --all")
    for i, o in jobs:
        s = add_prechecks(i, o, a.limit, a.blank_rate, a.seed)
        print(f"{o}: {s['rows']} rows, {s['blocks_added']} blocks, {s['blanked_rows']} blanked, n/d {s['nd_counts']}")


if __name__ == "__main__":
    main()
