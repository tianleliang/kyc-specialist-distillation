"""Size-matched control for data-filtering / data-adding techniques (experiment_plan §0).

    python -m step4_distillation.matched_n --pool data/sft/floor.jsonl --like data/sft/reject.jsonl \
        --out data/sft/reject.control.jsonl [--seed 17] [--by-case]

Draws as many records from ``--pool`` as ``--like`` has (or ``--n``), uniformly at random
with a fixed seed, so "technique vs control" measures data *quality*, not quantity.
``--by-case`` draws whole cases (all records of a case_id) until the count is reached.
"""
from __future__ import annotations

import argparse
import random
from collections import defaultdict

from step4_distillation.common import Tally, read_jsonl, setup_logging, write_training_file


def draw(pool: list[dict], n: int, seed: int, by_case: bool = False) -> list[dict]:
    if n > len(pool):
        raise SystemExit(f"cannot draw {n} records from a pool of {len(pool)}")
    rng = random.Random(f"matched_n:{seed}")
    if not by_case:
        idx = sorted(rng.sample(range(len(pool)), n))
        return [pool[i] for i in idx]
    groups = defaultdict(list)
    for r in pool:
        groups[r.get("case_id")].append(r)
    keys = sorted(groups, key=str)
    rng.shuffle(keys)
    out: list[dict] = []
    for k in keys:
        if len(out) >= n:
            break
        out += groups[k]
    return out[:n]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pool", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--like", help="match this file's record count")
    g.add_argument("--n", type=int)
    ap.add_argument("--seed", type=int, default=17)
    ap.add_argument("--by-case", action="store_true")
    ap.add_argument("--eval-manifest", action="append", default=None)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    setup_logging()
    pool = read_jsonl(a.pool)
    n = a.n if a.n is not None else len(read_jsonl(a.like))
    rows = draw(pool, n, a.seed, a.by_case)
    tally = Tally("matched_n")
    tally.keep(len(rows))
    tally.drop("not_drawn", len(pool) - len(rows))
    tally.extra.update({"pool": a.pool, "like": a.like, "n": n, "seed": a.seed})
    write_training_file(a.out, rows, a.eval_manifest, tally)
    tally.save(a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
