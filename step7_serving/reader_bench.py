"""Reader bench: how the pre-checker reader does on layouts nobody designed.

    python -m step7_serving.reader_bench                          # all families, 300 cases each
    python -m step7_serving.reader_bench --families F-kv F-json --n 100 --show 3
    python -m step7_serving.reader_bench --reader /path/to/prechecks.py --md out.md --json out.json

For each fuzz family x N cases (from ``data/reader_dev`` + ``data/dev``, or
``data/train`` + ``data/dev`` until reader_dev exists): render a new packet
from truth (``fuzz_render``), run ``run_prechecks`` and score it against the
truth-implied values with ``precheck_eval``'s mapping (as_of, mrz status,
expiry, expired, poa_date, poa_window, integrity per field + overall). Also
scores the original packets of each source split per generator style.

Table: family x field -> n, coverage, wrong, plus the first wrong examples
(packet excerpt + reader value + truth value). Exit code 1 if any value is
wrong anywhere. Packets that fail the renderer's self-check are dropped and
counted (F bugs, not reader errors).

``--reader`` loads a prechecks.py from a path (e.g. a scratch checkout of
reader-v3); default imports ``step7_serving.prechecks`` from this checkout.
Never reads eval splits.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import random
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from step7_serving import fuzz_render as FR  # noqa: E402
from step7_serving import precheck_eval as PE  # noqa: E402

FIELDS = PE.FIELDS + PE.INTEG_FIELDS


def load_reader(path: str | None):
    if not path:
        from step7_serving import prechecks
        return prechecks
    spec = importlib.util.spec_from_file_location("prechecks_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_split(split_dir: Path) -> list[tuple[dict, dict]]:
    """[(case, truth)] for one split. Refuses eval splits."""
    if split_dir.name.lower().startswith("eval"):
        raise SystemExit(f"refusing to read eval split {split_dir}")
    truths = {}
    with open(split_dir / "truth.jsonl", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            truths[r["case_id"]] = r["truth"]
    out = []
    with open(split_dir / "cases.jsonl", encoding="utf-8") as f:
        for line in f:
            c = json.loads(line)
            out.append((c, truths[c["case_id"]]))
    return out


def expected_values(t: dict, expected: dict) -> dict:
    """field -> (kind, gold) with kind 'eq' (gold value), 'set' (allowed set),
    'none' (must be None: no MRZ) or None (nothing to score)."""
    as_of = date.fromisoformat(t["context"]["as_of_date"])
    out = {"as_of": ("eq", as_of)}
    tm = t["id_doc"].get("mrz_check") or "none"
    out["mrz"] = ("none", None) if tm == "none" else ("eq", tm)
    te = PE.truth_expiry(t, as_of)
    out["expiry"] = ("eq", te) if te else None
    out["expired"] = ("eq", te < as_of) if te else None
    poa = t.get("poa") or {}
    tp = date.fromisoformat(poa["issue_date"]) if poa.get("present") and poa.get("issue_date") else None
    out["poa_date"] = ("eq", tp) if tp else None
    out["poa_window"] = ("eq", PE.window((as_of - tp).days)) if tp else None
    has_mrz = bool(t["id_doc"].get("mrz_lines"))
    for fk, ek in PE.INTEG_MAP.items():
        out[f"integ_{ek}"] = ("set", PE.gold_classes(expected, ek, has_mrz), fk)
    out["integ_overall"] = ("set", PE.gold_overall(expected))
    return out


def predicted(res: dict, field: str, fk: str | None = None):
    if field == "mrz":
        return res["mrz"]["status"] if res.get("mrz") else None
    if field.startswith("integ_"):
        integ = res.get("integrity") or {}
        if field == "integ_overall":
            return integ.get("overall")
        f = (integ.get("fields") or {}).get(fk)
        return f["class"] if f else None
    return res.get(field)


class Tally:
    def __init__(self, show: int):
        self.s = {k: defaultdict(int) for k in FIELDS}
        self.examples = defaultdict(list)
        self.show = show
        self.dropped = 0
        self.dropped_examples: list[str] = []

    def add(self, cid: str, packet: str, res: dict, exp: dict):
        for field in FIELDS:
            e = exp.get(field)
            if e is None:
                continue
            kind, gold = e[0], e[1]
            pred = predicted(res, field, e[2] if len(e) > 2 else None)
            s = self.s[field]
            if kind == "none":
                s["no_value_cases"] += 1
                if pred is not None:
                    s["n"] += 1
                    s["covered"] += 1
                    self._wrong(field, cid, packet, pred, "none (no MRZ)")
                continue
            s["n"] += 1
            if pred is None:
                continue
            s["covered"] += 1
            ok = pred == gold if kind == "eq" else pred in gold
            if ok:
                s["correct"] += 1
            else:
                self._wrong(field, cid, packet, pred, gold if kind == "eq" else "/".join(sorted(gold)))

    def _wrong(self, field, cid, packet, pred, gold):
        if len(self.examples[field]) < self.show:
            self.examples[field].append({"case_id": cid, "reader": str(pred), "truth": str(gold),
                                         "packet_excerpt": excerpt(packet, pred, gold), "packet": packet})

    @property
    def wrong(self) -> int:
        return sum(s["covered"] - s["correct"] for s in self.s.values())


def _date_strings(d) -> list[str]:
    if not isinstance(d, date):
        return []
    fns = dict(FR.DATE_FORMATS, **FR.EXTRA_FORMATS)
    return [fn(d, random.Random(0)).lower() for fn in fns.values()]


def excerpt(packet: str, pred, gold, ctx: int = 4) -> str:
    """Lines around where the reader's (else the truth) value is written."""
    lines = packet.split("\n")
    for val in (pred, gold):
        needles = _date_strings(val) if isinstance(val, date) else []
        for j, ln in enumerate(lines):
            low = ln.lower()
            if any(n in low for n in needles):
                return "\n".join(lines[max(0, j - ctx):j + ctx + 1])
    return packet[:800]


def bench_family(reader, family: str, pool: list, n: int, seed: int, show: int, reveal: bool = False) -> Tally:
    tl = Tally(show)
    for i, (case, t) in enumerate(pool[:n]):
        try:
            packet, _ = FR.render(t, family, seed + i)
        except FR.SelfCheckError as e:
            tl.dropped += 1
            if len(tl.dropped_examples) < 3:
                tl.dropped_examples.append(f"{case['case_id']}: {e}")
            continue
        tl.add(case["case_id"], packet, reader.run_prechecks(packet), expected_values(t, case["expected"]))
    if family == FR.HELDOUT and not reveal:     # P3 sees the held-out score only
        for exs in tl.examples.values():
            for ex in exs:
                ex["packet_excerpt"] = ex["packet"] = "(held out)"
        tl.dropped_examples = [d.split(":")[0] + ": (held out)" for d in tl.dropped_examples]
    return tl


def bench_original(reader, cases: list, show: int) -> dict[str, Tally]:
    out: dict[str, Tally] = {}
    for case, t in cases:
        tl = out.setdefault(case.get("style", "?"), Tally(show))
        tl.add(case["case_id"], case["packet"], reader.run_prechecks(case["packet"]),
               expected_values(t, case["expected"]))
    return out


def table(rows: list[tuple[str, Tally]]) -> str:
    cols = FIELDS
    out = ["| set | dropped | " + " | ".join(cols) + " | wrong |",
           "|---|---:|" + "---:|" * len(cols) + "---:|"]
    for name, tl in rows:
        cells = []
        for k in cols:
            s = tl.s[k]
            if not s["n"]:
                cells.append("-")
                continue
            w = s["covered"] - s["correct"]
            cells.append(f"{s['covered'] / s['n']:.0%}" + (f" **{w}x**" if w else ""))
        out.append(f"| {name} | {tl.dropped} | " + " | ".join(cells) + f" | {tl.wrong} |")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data", default=str(ROOT / "data"))
    ap.add_argument("--splits", nargs="+", default=None,
                    help="source splits (default: reader_dev dev if reader_dev exists, else train dev)")
    ap.add_argument("--families", nargs="+", default=None, help=f"default: all + {FR.HELDOUT} if present")
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--show", type=int, default=3, help="wrong examples kept per field")
    ap.add_argument("--reader", help="path to a prechecks.py to test (default: this checkout's)")
    ap.add_argument("--no-original", action="store_true", help="skip the original packets per style")
    ap.add_argument("--reveal-heldout", action="store_true", help="print held-out packets (end of the day only)")
    ap.add_argument("--md")
    ap.add_argument("--json")
    a = ap.parse_args(argv)

    reader = load_reader(a.reader)
    data = Path(a.data)
    splits = a.splits or (["reader_dev", "dev"] if (data / "reader_dev" / "truth.jsonl").exists() else ["train", "dev"])
    cases = [ct for sp in splits for ct in load_split(data / sp)]
    pool = list(cases)
    random.Random(a.seed).shuffle(pool)
    fams = a.families or list(FR.FAMILIES) + ([FR.HELDOUT] if FR.heldout_available() else [])

    rows, raw = [], {"splits": splits, "n": a.n, "seed": a.seed, "reader": a.reader or "step7_serving/prechecks.py",
                     "families": {}, "original": {}}
    for fam in fams:
        tl = bench_family(reader, fam, pool, a.n, a.seed, a.show, a.reveal_heldout)
        rows.append((fam, tl))
    orig_rows = []
    if not a.no_original:
        for sp in splits:
            for style, tl in sorted(bench_original(reader, load_split(data / sp), a.show).items()):
                orig_rows.append((f"{sp}/{style}", tl))

    lines = [f"# Reader bench: `{raw['reader']}`", "",
             f"Sources: {', '.join(splits)}; {a.n} cases per family; seed {a.seed}. "
             "Cell = coverage (share not n/d); **Nx** = N wrong values.", "",
             "## Fuzz families", "", table(rows), ""]
    if orig_rows:
        lines += ["## Original packets per generator style", "", table(orig_rows), ""]
    for name, tl in rows + orig_rows:
        for field, exs in tl.examples.items():
            for ex in exs:
                lines += [f"### WRONG {name} {field} {ex['case_id']}: reader={ex['reader']} truth={ex['truth']}",
                          "```", ex["packet_excerpt"][:800], "```", ""]
        for d in tl.dropped_examples:
            lines.append(f"- DROPPED (F self-check) {name}: {d}")
    out = "\n".join(lines)
    print(out)
    for name, tl in rows + orig_rows:
        raw["families" if name in fams else "original"][name] = {
            "dropped": tl.dropped, "wrong": tl.wrong, "fields": {k: dict(v) for k, v in tl.s.items()},
            "examples": dict(tl.examples)}
    if a.md:
        Path(a.md).write_text(out + "\n", encoding="utf-8")
    if a.json:
        Path(a.json).write_text(json.dumps(raw, indent=2, default=str), encoding="utf-8")
    total = sum(tl.wrong for _, tl in rows + orig_rows)
    print(f"\nTOTAL WRONG VALUES: {total}")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
