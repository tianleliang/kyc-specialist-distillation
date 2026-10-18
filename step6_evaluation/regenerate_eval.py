"""Rebuild every frozen eval split from its recorded seed/config into a scratch dir and verify it.

    python -m step6_evaluation.regenerate_eval [--scratch DIR] [--only eval_id,eval_hard]

Never writes under ``data/``. For each split, the recorded command (see each split's
``data/<split>/manifest.json`` and ``data/README.md``) is re-run with ``--out <scratch>/data/<split>``.
Then:

1. ``split_guard verify`` runs on copies of the frozen manifests placed in the scratch tree
   (``data/eval/MANIFEST.json`` for eval_id + 3 OOD; ``data/eval_hard/manifest.json``), so the
   regenerated ``cases.jsonl`` files are checked against the sha256 recorded at freeze time;
2. every regenerated ``cases.jsonl`` / ``truth.jsonl`` is compared byte for byte with the committed file;
3. ``split_guard verify`` runs on the committed manifests too (the committed eval files are intact).

Splits:

* ``eval_id`` (300), ``eval_ood_template`` (50), ``eval_hard`` (150): ``step1_data_generation.build``
  (pure code, seeded).
* ``eval_ood_hand`` (50): ``step1_data_generation.ood_templates`` (hand-written renderers, pure code, seeded).
* ``eval_ood_llm`` (100): ``step1_data_generation.ood_llm``. The truths, prompts, checks and labels are
  code; the packet text was written by two LLMs. Regeneration replays the recorded LLM responses
  from ``results/eval_regen/ood_llm_cache/`` (the exact cache entries the original build read).
  The network is blocked here: a cache miss becomes a dropped packet and fails verification, it
  never calls (or bills) an API. ``--export-llm-cache`` (maintainers only) copies the cache entries
  the build reads from a full local cache into that folder.

Exit code 0 only if every split verifies.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LLM_CACHE = ROOT / "results" / "eval_regen" / "ood_llm_cache"

SPLITS = {  # split -> (module, argv without --out)
    "eval_id": ("step1_data_generation.build",
                ["--config", "step1_data_generation/configs/eval_id.yaml", "--n", "300", "--seed", "3000000",
                 "--allow-eval"]),
    "eval_id_v2": ("step1_data_generation.build",   # fresh in-distribution set (Sun 10/18): same config, new seed
                   ["--config", "step1_data_generation/configs/eval_id.yaml", "--n", "300", "--seed", "3050000",
                    "--allow-eval"]),
    "eval_ood_template": ("step1_data_generation.build",
                          ["--config", "step1_data_generation/configs/eval_ood_template.yaml", "--n", "50",
                           "--seed", "4000000", "--allow-eval"]),
    "eval_ood_hand": ("step1_data_generation.ood_templates", ["--allow-eval", "--n", "50", "--seed", "4010000"]),
    "eval_ood_llm": ("step1_data_generation.ood_llm", ["--allow-eval", "--n", "100", "--seed", "4020000"]),
    "eval_hard": ("step1_data_generation.build",
                  ["--config", "step1_data_generation/configs/eval_hard.yaml", "--n", "150", "--seed", "5000000",
                   "--allow-eval"]),
}
FROZEN = [  # (committed manifest, splits it covers)
    ("data/eval/MANIFEST.json", ["eval_id", "eval_ood_template", "eval_ood_hand", "eval_ood_llm"]),
    ("data/eval_hard/manifest.json", ["eval_hard"]),
    ("data/eval_v2/MANIFEST.json", ["eval_id_v2"]),
]


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


@contextlib.contextmanager
def replay_llm_cache(cache_dir: Path, export_from: Path | None = None):
    """Point every LLMClient at `cache_dir`, read-only, with the network blocked.
    With `export_from`, read from that full cache instead and copy each entry used into `cache_dir`."""
    from shared.frontier_api import clients as C

    orig_init, orig_get, orig_put, orig_prov = (C.DiskCache.__init__, C.DiskCache.get, C.DiskCache.put,
                                                C.LLMClient.provider_for)
    src = export_from or cache_dir

    def init(self, root=None):
        orig_init(self, src)

    def get(self, key):  # explicit UTF-8: DiskCache.get uses the locale encoding (cp1252 on Windows)
        p = self._path(key)
        hit = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
        if hit is not None and export_from is not None:
            dst = cache_dir / key[:2] / f"{key}.json"
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self._path(key), dst)
        return hit

    def no_network(self, req):
        raise RuntimeError(f"cache miss for {req.model}: regeneration replays recorded responses only")

    C.DiskCache.__init__, C.DiskCache.get = init, get
    C.DiskCache.put = lambda self, key, value: None
    C.LLMClient.provider_for = no_network
    try:
        yield
    finally:
        C.DiskCache.__init__, C.DiskCache.get, C.DiskCache.put = orig_init, orig_get, orig_put
        C.LLMClient.provider_for = orig_prov


def run_split(split: str, out: Path, export_from: Path | None) -> None:
    import importlib

    mod_name, argv = SPLITS[split]
    mod = importlib.import_module(mod_name)
    argv = argv + ["--out", str(out)]
    buf = io.StringIO()
    ctx = replay_llm_cache(LLM_CACHE, export_from) if split == "eval_ood_llm" else contextlib.nullcontext()
    with ctx, contextlib.redirect_stderr(buf), contextlib.redirect_stdout(buf):
        rc = mod.main(argv)
    if rc not in (0, None):
        sys.stderr.write(buf.getvalue())
        raise SystemExit(f"{split}: {mod_name} exited {rc}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--scratch", type=Path, help="work dir (default: a new temp dir, removed on success)")
    ap.add_argument("--only", help="comma-separated subset of " + ",".join(SPLITS))
    ap.add_argument("--export-llm-cache", type=Path, metavar="FULL_CACHE",
                    help="maintainers: copy the LLM cache entries eval_ood_llm reads from FULL_CACHE "
                         "into results/eval_regen/ood_llm_cache/")
    a = ap.parse_args(argv)
    import os
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    from step6_evaluation import split_guard

    splits = a.only.split(",") if a.only else list(SPLITS)
    scratch = a.scratch or Path(tempfile.mkdtemp(prefix="zorbe_regen_"))
    scratch = scratch.resolve()
    if ROOT / "data" in [scratch, *scratch.parents]:
        raise SystemExit("refusing to write under data/")
    ok = True
    for sp in splits:
        out = scratch / "data" / sp
        if out.exists():
            shutil.rmtree(out)
        print(f"[regen] {sp}: python -m {SPLITS[sp][0]} {' '.join(SPLITS[sp][1])} --out {out.as_posix()}")
        run_split(sp, out, a.export_llm_cache)
        for name in ("cases.jsonl", "truth.jsonl"):
            new, old = out / name, ROOT / "data" / sp / name
            same = new.exists() and old.exists() and new.read_bytes() == old.read_bytes()
            ok &= same
            print(f"[regen]   {name}: {'identical to committed' if same else 'DIFFERS from committed'}"
                  f" ({sha(new)[:16] if new.exists() else 'missing'})")
    for mpath, covered in FROZEN:
        if not set(covered) & set(splits):
            continue
        frozen = ROOT / mpath
        probs = split_guard.verify(frozen)
        ok &= not probs
        print(f"[verify] committed {mpath}: {'OK' if not probs else probs}")
        copy = scratch / mpath.replace("manifest.json", "FROZEN_MANIFEST.json")
        copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(frozen, copy)
        m = json.loads(copy.read_text(encoding="utf-8"))
        files = [e for e in m["files"] if any(c in e["path"].replace("\\", "/").split("/") for c in splits)
                 or len(covered) == 1]
        m["files"] = files
        copy.write_text(json.dumps(m), encoding="utf-8")
        probs = split_guard.verify(copy)
        ok &= not probs
        print(f"[verify] regenerated vs frozen {mpath} ({len(files)} files): {'OK' if not probs else probs}")
    print(f"[regen] {'ALL SPLITS VERIFY' if ok else 'FAILED'} (scratch: {scratch.as_posix()})")
    if ok and not a.scratch:
        shutil.rmtree(scratch, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
