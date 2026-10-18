"""Freeze eval files and detect step5_training/eval contamination. Exits non-zero on any problem.

    # 1. hash and freeze the eval set (writes a manifest, optionally makes files read-only)
    python -m step6_evaluation.split_guard freeze data/eval/*.jsonl --manifest data/eval/MANIFEST.json --readonly
    # 2. later, prove nothing changed
    python -m step6_evaluation.split_guard verify --manifest data/eval/MANIFEST.json
    # 3. before every training run: no eval case may appear in training data
    python -m step6_evaluation.split_guard check --train data/train/*.jsonl --eval data/eval/*.jsonl \
        [--report outputs/split_guard_report.json]

Exit codes: 0 clean, 1 contamination or manifest mismatch, 2 usage error.

Overlap checks (each eval record vs each train record, on normalized text):
  exact        sha256 of normalized text is identical.
  containment  share of an eval record's distinctive word n-grams that also appear in one
               train record. Catches an eval packet pasted inside a longer training prompt
               (SFT/DPO records wrap the packet in a system prompt and an answer).
  minhash      MinHash + LSH estimate of Jaccard similarity on the same n-gram sets.
               Catches near-duplicates (lightly edited / re-noised copies).
"Distinctive" n-grams: n-grams present in more than --max-df of eval records are dropped
first. These are template boilerplate ("Proof of address", field labels). Without this,
every pair of cases from the same generator would look similar.

Record text (`--field auto`): `messages` -> user turns; DPO `prompt` lists -> user turns;
else the first of packet / packet_text / text / input / prompt; else the whole record as
sorted JSON. `--field a.b` selects a dotted path.

EvalGuard (used by shared.frontier_api.clients.LLMClient(guard=...)) refuses teacher requests whose text
contains a frozen eval record, so teachers never see eval cases.
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import stat
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np

TEXT_KEYS = ("packet", "packet_text", "text", "input", "prompt")
MASK64 = (1 << 64) - 1


# ---------------------------------------------------------------------------
# Text extraction and shingling
# ---------------------------------------------------------------------------

def exact_name_exists(path: str | Path) -> bool:
    """Case-sensitive existence check. On Windows, ``MANIFEST.json`` (the freeze manifest) and
    ``manifest.json`` (a build manifest) are the same file to ``Path.exists`` and ``glob``."""
    p = Path(path)
    try:
        return p.name in os.listdir(p.parent)
    except (FileNotFoundError, NotADirectoryError):
        return False


def normalize(text: str) -> str:
    # JSON-escaped whitespace ("\\nFull name") would otherwise glue tokens together
    text = re.sub(r"\\[ntr]", " ", text)
    text = unicodedata.normalize("NFKC", text).casefold()
    return " ".join(re.findall(r"\w+", text))


def _user_turns(msgs: list) -> str:
    return "\n".join(str(m.get("content", "")) for m in msgs
                     if isinstance(m, dict) and m.get("role", "user") == "user")


def record_text(rec: Any, field: str = "auto") -> str:
    if not isinstance(rec, dict):
        return rec if isinstance(rec, str) else json.dumps(rec, sort_keys=True)
    if field != "auto":
        v: Any = rec
        for part in field.split("."):
            v = v[part]
        return _user_turns(v) if isinstance(v, list) else str(v)
    if isinstance(rec.get("messages"), list):
        return _user_turns(rec["messages"])
    for k in TEXT_KEYS:
        if k in rec:
            v = rec[k]
            return _user_turns(v) if isinstance(v, list) else str(v)
    return json.dumps(rec, sort_keys=True, ensure_ascii=False)


def _h64(s: str) -> int:
    return int.from_bytes(hashlib.blake2b(s.encode(), digest_size=8).digest(), "little")


def shingles(text: str, n: int) -> set[int]:
    toks = normalize(text).split()
    if not toks:
        return set()
    if len(toks) < n:
        return {_h64(" ".join(toks))}
    return {_h64(" ".join(toks[i:i + n])) for i in range(len(toks) - n + 1)}


@dataclass
class Doc:
    id: str
    text: str
    norm_hash: str = ""
    sh: set[int] = field(default_factory=set)


def load_docs(paths: Iterable[str], field_: str = "auto") -> list[Doc]:
    docs = []
    for p in paths:
        with open(p, encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                if not line.strip():
                    continue
                rec = json.loads(line)
                rid = (rec.get("id") or rec.get("case_id")) if isinstance(rec, dict) else None
                docs.append(Doc(id=f"{p}:{rid if rid is not None else i}", text=record_text(rec, field_)))
    return docs


# ---------------------------------------------------------------------------
# MinHash
# ---------------------------------------------------------------------------

class MinHasher:
    """xor-multiply hash family over 64-bit shingle hashes; numpy wraps mod 2**64."""

    def __init__(self, num_perm: int = 128, seed: int = 1):
        rng = np.random.default_rng(seed)
        self.xor = rng.integers(0, 2**63, size=num_perm, dtype=np.uint64) * np.uint64(2) + np.uint64(1)
        self.mul = rng.integers(0, 2**63, size=num_perm, dtype=np.uint64) * np.uint64(2) + np.uint64(1)
        self.num_perm = num_perm

    def signature(self, sh: set[int]) -> np.ndarray:
        if not sh:
            return np.full(self.num_perm, np.iinfo(np.uint64).max, dtype=np.uint64)
        x = np.fromiter(sh, dtype=np.uint64, count=len(sh))[:, None]
        with np.errstate(over="ignore"):
            return ((x ^ self.xor) * self.mul).min(axis=0)


def lsh_bands(sig: np.ndarray, bands: int) -> list[bytes]:
    rows = len(sig) // bands
    return [bytes([b]) + sig[b * rows:(b + 1) * rows].tobytes() for b in range(bands)]


# ---------------------------------------------------------------------------
# Overlap check
# ---------------------------------------------------------------------------

@dataclass
class CheckConfig:
    ngram: int = 8
    containment: float = 0.5
    jaccard: float = 0.7
    max_df: float = 0.05
    num_perm: int = 128
    bands: int = 32


def prepare(docs: list[Doc], n: int) -> None:
    for d in docs:
        d.norm_hash = hashlib.sha256(normalize(d.text).encode()).hexdigest()
        d.sh = shingles(d.text, n)


def boilerplate(eval_docs: list[Doc], max_df: float) -> set[int]:
    df: dict[int, int] = {}
    for d in eval_docs:
        for s in d.sh:
            df[s] = df.get(s, 0) + 1
    limit = max(1, int(max_df * len(eval_docs)))
    return {s for s, c in df.items() if c > limit} if max_df < 1 else set()


def check_overlap(train: list[Doc], eval_: list[Doc], cfg: CheckConfig = CheckConfig()) -> dict:
    prepare(train, cfg.ngram)
    prepare(eval_, cfg.ngram)
    common = boilerplate(eval_, cfg.max_df)
    ev_sh = [d.sh - common for d in eval_]
    findings: list[dict] = []

    # exact
    by_hash: dict[str, list[int]] = {}
    for j, d in enumerate(eval_):
        by_hash.setdefault(d.norm_hash, []).append(j)
    for t in train:
        for j in by_hash.get(t.norm_hash, []):
            findings.append({"method": "exact", "train": t.id, "eval": eval_[j].id, "score": 1.0})

    # containment via inverted index over distinctive eval n-grams
    index: dict[int, list[int]] = {}
    for j, s in enumerate(ev_sh):
        for x in s:
            index.setdefault(x, []).append(j)
    for t in train:
        counts: dict[int, int] = {}
        for x in t.sh:
            for j in index.get(x, ()):
                counts[j] = counts.get(j, 0) + 1
        for j, c in counts.items():
            score = c / len(ev_sh[j])
            if score >= cfg.containment:
                findings.append({"method": "containment", "train": t.id, "eval": eval_[j].id,
                                 "score": round(score, 4)})

    # MinHash LSH on the same distinctive sets
    mh = MinHasher(cfg.num_perm)
    ev_sig = [mh.signature(s) for s in ev_sh]
    buckets: dict[bytes, list[int]] = {}
    for j, sig in enumerate(ev_sig):
        if ev_sh[j]:
            for b in lsh_bands(sig, cfg.bands):
                buckets.setdefault(b, []).append(j)
    for t in train:
        tsh = t.sh - common
        if not tsh:
            continue
        sig = mh.signature(tsh)
        cands = {j for b in lsh_bands(sig, cfg.bands) for j in buckets.get(b, ())}
        for j in cands:
            est = float(np.mean(sig == ev_sig[j]))
            if est >= cfg.jaccard:
                exact_j = len(tsh & ev_sh[j]) / len(tsh | ev_sh[j])
                findings.append({"method": "minhash", "train": t.id, "eval": eval_[j].id,
                                 "score": round(est, 4), "jaccard": round(exact_j, 4)})

    return {
        "config": cfg.__dict__, "n_train": len(train), "n_eval": len(eval_),
        "boilerplate_ngrams_dropped": len(common),
        "eval_records_without_distinctive_text": sum(1 for s in ev_sh if not s),
        "contaminated_eval_records": len({f["eval"] for f in findings}),
        "findings": findings,
    }


# ---------------------------------------------------------------------------
# Freeze / verify
# ---------------------------------------------------------------------------

def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def freeze(paths: list[str], manifest: str | Path, readonly: bool = False) -> dict:
    mpath = Path(manifest)
    mpath.parent.mkdir(parents=True, exist_ok=True)
    entries = []
    for p in sorted(paths):
        lines = [l for l in Path(p).read_text(encoding="utf-8").splitlines() if l.strip()]
        entries.append({
            "path": os.path.relpath(Path(p).resolve(), mpath.parent.resolve()),  # relative to manifest
            "sha256": sha256_file(p), "bytes": Path(p).stat().st_size, "records": len(lines),
            "record_sha256": [hashlib.sha256(l.encode()).hexdigest() for l in lines],
        })
        if readonly:
            os.chmod(p, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    m = {"frozen_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
         "tool": "step6_evaluation/split_guard.py", "files": entries}
    mpath.parent.mkdir(parents=True, exist_ok=True)
    mpath.write_text(json.dumps(m, indent=1), encoding="utf-8")
    return m


def _resolve(entry_path: str, manifest: Path) -> Path:
    # manifests frozen on Windows store "..\eval_id\cases.jsonl"; normalize so they resolve on POSIX too
    return manifest.parent / entry_path.replace("\\", "/")


def verify(manifest: str | Path) -> list[str]:
    """Return a list of problems (empty = intact)."""
    mpath = Path(manifest)
    m = json.loads(mpath.read_text(encoding="utf-8"))
    problems = []
    for e in m["files"]:
        p = _resolve(e["path"], mpath)
        if not p.exists():
            problems.append(f"missing: {e['path']}")
        elif sha256_file(p) != e["sha256"]:
            problems.append(f"changed: {e['path']}")
    return problems


# ---------------------------------------------------------------------------
# Guard for teacher calls
# ---------------------------------------------------------------------------

class EvalGuard:
    """`check(text)` raises ContaminationError if `text` contains (by containment of
    distinctive n-grams) any eval record. Plug into LLMClient(guard=EvalGuard...)."""

    def __init__(self, eval_docs: list[Doc], ngram: int = 8, threshold: float = 0.5,
                 max_df: float = 0.05):
        self.n, self.threshold = ngram, threshold
        prepare(eval_docs, ngram)
        common = boilerplate(eval_docs, max_df)
        self.docs = eval_docs
        self.sets = [d.sh - common for d in eval_docs]
        self.index: dict[int, list[int]] = {}
        for j, s in enumerate(self.sets):
            for x in s:
                self.index.setdefault(x, []).append(j)

    @classmethod
    def from_manifest(cls, manifest: str | Path, field_: str = "auto", **kw) -> "EvalGuard":
        problems = verify(manifest)
        if problems:
            raise RuntimeError(f"eval manifest does not verify: {problems}")
        mpath = Path(manifest)
        files = [str(_resolve(e["path"], mpath)) for e in json.loads(mpath.read_text(encoding="utf-8"))["files"]]
        return cls(load_docs(files, field_), **kw)

    def check(self, text: str) -> None:
        from shared.frontier_api.clients import ContaminationError

        counts: dict[int, int] = {}
        for x in shingles(text, self.n):
            for j in self.index.get(x, ()):
                counts[j] = counts.get(j, 0) + 1
        for j, c in counts.items():
            if c / len(self.sets[j]) >= self.threshold:
                raise ContaminationError(f"request overlaps eval record {self.docs[j].id} "
                                         f"({c / len(self.sets[j]):.0%} of its distinctive n-grams)")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _expand(patterns: list[str]) -> list[str]:
    out = []
    for p in patterns:
        hits = sorted(glob.glob(p))
        out += hits if hits else [p]
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="split_guard", description="Freeze eval files; detect step5_training/eval overlap.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("freeze")
    f.add_argument("files", nargs="+")
    f.add_argument("--manifest", required=True)
    f.add_argument("--readonly", action="store_true")
    v = sub.add_parser("verify")
    v.add_argument("--manifest", required=True)
    c = sub.add_parser("check")
    c.add_argument("--train", nargs="+", required=True)
    c.add_argument("--eval", nargs="+", required=True)
    c.add_argument("--field", default="auto")
    c.add_argument("--ngram", type=int, default=CheckConfig.ngram)
    c.add_argument("--containment", type=float, default=CheckConfig.containment)
    c.add_argument("--jaccard", type=float, default=CheckConfig.jaccard)
    c.add_argument("--max-df", type=float, default=CheckConfig.max_df)
    c.add_argument("--report")
    c.add_argument("--manifest", help="also verify the eval manifest first")
    try:
        a = ap.parse_args(argv)
    except SystemExit as e:
        return 2 if e.code else 0

    if a.cmd == "freeze":
        m = freeze(_expand(a.files), a.manifest, a.readonly)
        print(f"froze {len(m['files'])} file(s), {sum(e['records'] for e in m['files'])} records -> {a.manifest}")
        return 0
    if a.cmd == "verify":
        problems = verify(a.manifest)
        for p in problems:
            print(f"FAIL {p}")
        print("OK manifest verified" if not problems else f"{len(problems)} problem(s)")
        return 1 if problems else 0

    if a.manifest:
        problems = verify(a.manifest)
        if problems:
            print(f"FAIL eval manifest: {problems}")
            return 1
    try:
        train, ev = load_docs(_expand(a.train), a.field), load_docs(_expand(a.eval), a.field)
    except (OSError, json.JSONDecodeError, KeyError) as e:
        print(f"error reading inputs: {e}", file=sys.stderr)
        return 2
    cfg = CheckConfig(ngram=a.ngram, containment=a.containment, jaccard=a.jaccard, max_df=a.max_df)
    rep = check_overlap(train, ev, cfg)
    if a.report:
        Path(a.report).parent.mkdir(parents=True, exist_ok=True)
        Path(a.report).write_text(json.dumps(rep, indent=1), encoding="utf-8")
    for fnd in rep["findings"][:50]:
        print(f"CONTAMINATION {fnd['method']:<11} score={fnd['score']:.3f} train={fnd['train']} eval={fnd['eval']}")
    if rep["eval_records_without_distinctive_text"]:
        print(f"warning: {rep['eval_records_without_distinctive_text']} eval record(s) are all boilerplate; "
              "only the exact check covers them")
    n = rep["contaminated_eval_records"]
    print(f"{'FAIL' if n else 'OK'}: {n}/{rep['n_eval']} eval records overlap {rep['n_train']} train records")
    return 1 if n else 0


if __name__ == "__main__":
    raise SystemExit(main())
