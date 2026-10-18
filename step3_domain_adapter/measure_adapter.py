"""Did the domain adapter move anything? Held-out corpus perplexity and the 30-item KYC probe,
base model vs base + adapter, on the same held-out chunks (never trained on).

    modal run -m step3_domain_adapter.measure_adapter --config step3_domain_adapter/configs/adapter.yaml
    modal run -m step3_domain_adapter.measure_adapter --config ... --adapter-dir /vol/ckpt/adapter/<run>/adapter

Writes ``adapter/<run_name>/measure.json`` on the checkpoints volume and a local copy under
``outputs/adapter/<run_name>/measure.json``, and prints a before/after table. The verdict is
mechanical: "moved" needs held-out perplexity down by at least ``MIN_PPL_DROP`` (2%) AND probe
accuracy (answerable items) not down; otherwise it says what did and did not move. Report it as is.

Perplexity is token-weighted over non-overlapping ``max_seq_len`` windows of each held-out chunk,
computed per corpus file as well, so a gain on one dominant document is visible as such.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import modal

from step3_domain_adapter import probe as P
from step3_domain_adapter.common import (MIN_PPL_DROP, ROOT, build_cfg, chunk_text, corpus_files, is_heldout,  # noqa: F401
                                         load_cfg, verdict, write_json)
from step5_training.common import require_no_placeholders
from step5_training.modal_infra import IMAGES, SECRETS, VOLUMES, checkpoints

app = modal.App("zorbe-adapter-measure")
_IMAGE = IMAGES["trl"].add_local_python_source("step3_domain_adapter", "step1_data_generation")


def heldout_by_file(cfg) -> dict[str, list[str]]:
    out = {}
    for p in corpus_files(cfg.corpus_dir, cfg.exclude_files):
        raw = p.read_text(encoding="utf-8", errors="replace")
        text = raw[: cfg.max_chars_per_file] if cfg.max_chars_per_file else raw
        out[p.stem] = [c for i, c in enumerate(chunk_text(text, cfg.chunk_chars)) if is_heldout(p.stem, i, cfg.heldout_mod)]
    return {k: v for k, v in out.items() if v}


def perplexity(model, tok, by_file: dict[str, list[str]], block: int) -> dict:
    import torch

    dev = next(model.parameters()).device
    model.eval()
    res, tot_nll, tot_n = {}, 0.0, 0
    for stem, chunks in by_file.items():
        nll, n = 0.0, 0
        for c in chunks:
            ids = tok(c, add_special_tokens=False)["input_ids"]
            for i in range(0, len(ids) - 1, block):
                w = ids[i:i + block + 1]
                if len(w) < 2:
                    continue
                x = torch.tensor([w], device=dev)
                with torch.no_grad():
                    logits = model(input_ids=x[:, :-1]).logits.float()
                loss = torch.nn.functional.cross_entropy(logits[0], x[0, 1:], reduction="sum")
                nll += loss.item()
                n += len(w) - 1
        res[stem] = {"tokens": n, "ppl": math.exp(nll / n) if n else None}
        tot_nll += nll
        tot_n += n
    return {"overall": math.exp(tot_nll / tot_n) if tot_n else None, "tokens": tot_n, "by_file": res}


def evaluate(model, tok, by_file, block, answerable) -> dict:
    return {"perplexity": perplexity(model, tok, by_file, block), "probe": P.scores(model, tok, answerable=answerable)}


def _measure(cfg_dict: dict, by_file: dict, answerable: dict, adapter_dir: str, commit=lambda: None) -> dict:
    """Runs anywhere torch runs (Modal GPU, or CPU via step3_domain_adapter/cpu_smoke.py)."""
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    cfg = build_cfg(cfg_dict)
    dtype = torch.bfloat16 if torch.cuda.is_available() and torch.cuda.is_bf16_supported() else torch.float32
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    tok = AutoTokenizer.from_pretrained(cfg.base_model)
    tok = getattr(tok, "tokenizer", tok)
    base = AutoModelForCausalLM.from_pretrained(cfg.base_model, dtype=dtype).to(dev)
    before = evaluate(base, tok, by_file, cfg.max_seq_len, answerable)
    model = PeftModel.from_pretrained(base, adapter_dir).to(dev)
    after = evaluate(model, tok, by_file, cfg.max_seq_len, answerable)
    rep = {"run_name": cfg.run_name, "base_model": cfg.base_model, "adapter_dir": adapter_dir,
           "n_probe_items": len(P.items()), "n_probe_answerable": sum(answerable.values()),
           "before": before, "after": after, "verdict": verdict(before, after)}
    out = Path(cfg.output_root) / "adapter" / cfg.run_name / "measure.json"
    write_json(out, rep)
    commit()
    return rep


@app.function(image=_IMAGE, volumes=VOLUMES, secrets=SECRETS, gpu="L40S", timeout=3600)
def measure_remote(cfg_dict: dict, by_file: dict, answerable: dict, adapter_dir: str) -> dict:
    return _measure(cfg_dict, by_file, answerable, adapter_dir, commit=checkpoints.commit)


def table(rep: dict) -> str:
    b, a = rep["before"], rep["after"]
    L = [f"{'metric':42} {'base':>10} {'adapter':>10}",
         f"{'held-out perplexity (overall)':42} {b['perplexity']['overall']:>10.3f} {a['perplexity']['overall']:>10.3f}"]
    for stem in b["perplexity"]["by_file"]:
        x, y = b["perplexity"]["by_file"][stem]["ppl"], a["perplexity"]["by_file"][stem]["ppl"]
        L.append(f"{'  ppl ' + stem:42} {x:>10.3f} {y:>10.3f}")
    for key in ("all", "answerable"):
        if key in b["probe"] and b["probe"][key]["n"]:
            label = f"probe accuracy ({key}, n={b['probe'][key]['n']})"
            L.append(f"{label:42} {b['probe'][key]['accuracy']:>10.0%} {a['probe'][key]['accuracy']:>10.0%}")
    for t in b["probe"]["by_topic"]:
        L.append(f"{'  probe ' + t:42} {b['probe']['by_topic'][t]['accuracy']:>10.0%} "
                 f"{a['probe']['by_topic'][t]['accuracy']:>10.0%}")
    L.append(rep["verdict"]["summary"])
    return "\n".join(L)


@app.local_entrypoint()
def main(config: str = "step3_domain_adapter/configs/adapter.yaml", adapter_dir: str = ""):
    cfg = load_cfg(config)
    require_no_placeholders(cfg)
    by_file = heldout_by_file(cfg)
    answerable = P.answerability(ROOT / cfg.corpus_dir)
    adir = adapter_dir or f"{cfg.output_root}/adapter/{cfg.run_name}/adapter"
    print(f"[measure] {cfg.run_name}: {sum(map(len, by_file.values()))} held-out chunks from {len(by_file)} files; "
          f"{sum(answerable.values())}/{len(answerable)} probe items answerable from the corpus on disk")
    import dataclasses

    rep = measure_remote.remote(dataclasses.asdict(cfg), by_file, answerable, adir)
    write_json(ROOT / "outputs" / "adapter" / cfg.run_name / "measure.json", rep)
    print(table(rep))
