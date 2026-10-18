"""CPU pre-flight for the domain adapter: train_adapter._train -> measure_adapter._measure on a tiny,
randomly initialised Qwen2-architecture model built offline (no downloads, no GPU, ~1 min).

    python -m step3_domain_adapter.cpu_smoke [--keep DIR]

It runs the same functions the Modal jobs run, on a slice of the real corpus, so it catches
Transformers / PEFT / datasets API drift and split bugs before any GPU time is spent. A random
tiny model learns the corpus' surface statistics quickly, so held-out perplexity must fall; the
probe numbers are noise at this size and are only checked for shape. It says nothing about quality.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import shutil
import tempfile
from pathlib import Path

from step3_domain_adapter import probe as P
from step3_domain_adapter.common import AdapterCfg, CORPUS_DIR, split_corpus
from step5_training.common import LoraCfg


def run(root: Path) -> dict:
    from step3_domain_adapter.measure_adapter import _measure, heldout_by_file
    from step3_domain_adapter.train_adapter import _train
    from step5_training.cpu_smoke import build_tiny_model

    cfg = AdapterCfg(run_name="smoke", base_model="", corpus_dir=str(CORPUS_DIR), max_chars_per_file=40000,
                     chunk_chars=2000, backend="trl", max_seq_len=128, epochs=3, learning_rate=3e-3, batch_size=8,
                     grad_accum=1, logging_steps=5, max_train_blocks=96, output_root=str(root),
                     lora=LoraCfg(r=8, alpha=16, target_modules="all-linear"))
    split = split_corpus(cfg)
    cfg.base_model = build_tiny_model(root, split["train"][:200])
    res = _train(dataclasses.asdict(cfg), split["train"], split["heldout"][:8], {"smoke": True})
    by_file = {k: v[:2] for k, v in heldout_by_file(cfg).items()}
    answerable = P.answerability(CORPUS_DIR)
    rep = _measure(dataclasses.asdict(cfg), by_file, answerable, res["adapter_dir"])
    return {"train": res, "ppl_before": rep["before"]["perplexity"]["overall"],
            "ppl_after": rep["after"]["perplexity"]["overall"], "probe_n": rep["after"]["probe"]["all"]["n"],
            "n_answerable": rep["n_probe_answerable"], "verdict": rep["verdict"]["summary"]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", help="write artifacts here instead of a temp dir")
    a = ap.parse_args()
    root = Path(a.keep) if a.keep else Path(tempfile.mkdtemp(prefix="zorbe-adapter-smoke-"))
    root.mkdir(parents=True, exist_ok=True)
    try:
        print(json.dumps(run(root), indent=1, default=str))
        print("ADAPTER CPU SMOKE OK")
        return 0
    finally:
        if not a.keep:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
