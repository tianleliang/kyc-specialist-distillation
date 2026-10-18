"""Shared, dependency-light helpers for step3_domain_adapter/train_adapter.py and measure_adapter.py.

Nothing here imports torch, transformers or modal, so it is unit-tested locally.

Corpus split: every ``corpus/*.txt`` file is cut into ~4,000-character chunks at paragraph
boundaries; a chunk is HELD OUT iff ``sha256("<file stem>:<chunk index>") mod heldout_mod == 0``
(about 1 in 10). Training sees only the other chunks, measurement only the held-out ones, and the
split depends on nothing but the text files, so it is identical on the laptop, on Modal and in tests.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from step5_training.common import LoraCfg, _build as _build_cfg

ROOT = Path(__file__).resolve().parents[1]
CORPUS_DIR = Path(__file__).resolve().parent / "corpus"
MIN_PPL_DROP = 0.02   # verdict: "moved" needs held-out perplexity down >= 2% and probe accuracy not down


@dataclass
class AdapterCfg:
    """Continued pretraining (causal-LM loss on raw text) with a 16-bit LoRA. Field names match
    step5_training.common.TrainCommon where they overlap, so step5_training.gpu.load_lora_model works."""
    run_name: str
    base_model: str
    corpus_dir: str = "step3_domain_adapter/corpus"
    exclude_files: list = field(default_factory=list)   # corpus file stems to leave out
    heldout_mod: int = 10                     # 1 in N chunks is held out for perplexity
    chunk_chars: int = 4000
    max_chars_per_file: int | None = None     # cap a dominant file (e.g. the 750 kB FinCEN rule)
    backend: str = "unsloth"                  # unsloth | trl
    gpu: str = "A100-80GB"
    timeout_hours: float = 2.0
    max_seq_len: int = 1024                   # = block size of the packed training sequences
    epochs: float = 2.0
    learning_rate: float = 1e-4
    batch_size: int = 8
    grad_accum: int = 2
    warmup_ratio: float = 0.03
    scheduler: str = "cosine"
    weight_decay: float = 0.0
    seed: int = 17
    logging_steps: int = 10
    max_train_blocks: int | None = None       # cap for smoke runs
    output_root: str = "/vol/ckpt"
    lora: LoraCfg = field(default_factory=LoraCfg)


def build_cfg(d: dict) -> AdapterCfg:
    return _build_cfg(AdapterCfg, d)


def load_cfg(path: str | Path) -> AdapterCfg:
    return build_cfg(yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {})


# --------------------------------------------------------------------------
# corpus
# --------------------------------------------------------------------------
def corpus_files(corpus_dir: str | Path = CORPUS_DIR, exclude: list[str] | tuple = ()) -> list[Path]:
    d = Path(corpus_dir)
    if not d.is_absolute():
        d = ROOT / d
    return [p for p in sorted(d.glob("*.txt")) if p.stem not in set(exclude)]


def chunk_text(text: str, target: int = 4000) -> list[str]:
    """Greedy paragraph packing to ~target characters; an over-long paragraph is cut hard."""
    paras = [p.strip() for p in text.replace("\r\n", "\n").split("\n\n") if p.strip()]
    out, cur = [], ""
    for p in paras:
        while len(p) > target:
            if cur:
                out.append(cur)
                cur = ""
            out.append(p[:target])
            p = p[target:]
        if cur and len(cur) + 2 + len(p) > target:
            out.append(cur)
            cur = p
        else:
            cur = f"{cur}\n\n{p}" if cur else p
    if cur:
        out.append(cur)
    return out


def is_heldout(stem: str, idx: int, mod: int = 10) -> bool:
    return int(hashlib.sha256(f"{stem}:{idx}".encode()).hexdigest()[:12], 16) % mod == 0


def split_corpus(cfg: AdapterCfg) -> dict:
    """{"train": [text], "heldout": [text], "files": {stem: {...stats, sha256}}}."""
    train, held, files = [], [], {}
    for p in corpus_files(cfg.corpus_dir, cfg.exclude_files):
        raw = p.read_text(encoding="utf-8", errors="replace")
        text = raw[: cfg.max_chars_per_file] if cfg.max_chars_per_file else raw
        chunks = chunk_text(text, cfg.chunk_chars)
        h = [c for i, c in enumerate(chunks) if is_heldout(p.stem, i, cfg.heldout_mod)]
        tr = [c for i, c in enumerate(chunks) if not is_heldout(p.stem, i, cfg.heldout_mod)]
        train += tr
        held += h
        files[p.stem] = {"sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(), "chars": len(text),
                         "chunks": len(chunks), "train_chunks": len(tr), "heldout_chunks": len(h)}
    return {"train": train, "heldout": held, "files": files}


def corpus_summary(split: dict) -> dict:
    tc, hc = sum(map(len, split["train"])), sum(map(len, split["heldout"]))
    return {"n_files": len(split["files"]), "train_chunks": len(split["train"]),
            "heldout_chunks": len(split["heldout"]), "train_chars": tc, "heldout_chars": hc,
            "est_train_tokens": tc // 4, "files": split["files"]}


def run_metadata(cfg: AdapterCfg, split: dict) -> dict:
    return {"config": dataclasses.asdict(cfg), "corpus": corpus_summary(split)}


def write_json(path: str | Path, obj) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(obj, indent=1, default=str), encoding="utf-8")


def verdict(before: dict, after: dict) -> dict:
    pb, pa = before["perplexity"]["overall"], after["perplexity"]["overall"]
    drop = (pb - pa) / pb
    key = "answerable" if after["probe"].get("answerable", {}).get("n") else "all"
    ab, aa = before["probe"][key]["accuracy"], after["probe"][key]["accuracy"]
    mb, ma = before["probe"][key]["mean_margin"], after["probe"][key]["mean_margin"]
    moved = drop >= MIN_PPL_DROP and aa >= ab
    parts = [f"held-out perplexity {pb:.2f} -> {pa:.2f} ({-drop:+.1%})",
             f"probe accuracy ({key}, n={after['probe'][key]['n']}) {ab:.0%} -> {aa:.0%}",
             f"probe margin {mb:+.3f} -> {ma:+.3f}"]
    return {"moved": moved, "ppl_relative_drop": drop, "probe_subset": key, "probe_acc_before": ab,
            "probe_acc_after": aa, "summary": ("MOVED: " if moved else "DID NOT MOVE (enough): ") + "; ".join(parts)}
