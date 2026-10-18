"""Stage 2 domain adapter: continued pretraining (causal-LM loss on raw text) with a 16-bit LoRA on
the public KYC/AML corpus, as a Modal GPU job.

    modal run -m step3_domain_adapter.train_adapter --config step3_domain_adapter/configs/adapter.yaml --dry-run
    modal run -m step3_domain_adapter.train_adapter --config step3_domain_adapter/configs/adapter.yaml

Locally, before any GPU starts: PLACEHOLDER check, corpus split (common.split_corpus: ~1 in 10
chunks held out for measure_adapter.py, never trained on), corpus hashes into the run metadata.
On the GPU: the same images as step5_training (``step5_training/modal_infra.py``; this file only
adds its own package to them), the same LoRA loader (``step5_training.gpu.load_lora_model``,
never 4-bit), the training text packed into ``max_seq_len`` blocks with EOS between chunks, loss
on every token. Held-out loss is evaluated before and after training (the untrained LoRA is the
base model, since B=0). The adapter and run.json land on the ``zorbe-checkpoints`` volume under
``adapter/<run_name>/``; the container exits when training ends.

Next: ``measure_adapter.py`` (held-out perplexity and the 30-item probe, base vs adapter). If the
adapter is kept, merge it into the base with ``step5_training/merge.py`` and use the merged weights
as ``base_model`` for SFT (stage 3/4).
"""
from __future__ import annotations

import dataclasses
import json
import math
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import modal

from step3_domain_adapter.common import build_cfg, load_cfg, run_metadata, split_corpus, write_json
from step5_training.common import require_no_placeholders
from step5_training.modal_infra import IMAGES, SECRETS, VOLUMES, checkpoints

app = modal.App("zorbe-adapter")
_IMAGES = {k: im.add_local_python_source("step3_domain_adapter", "step1_data_generation") for k, im in IMAGES.items()}


def pack_blocks(tok, texts: list[str], block: int) -> list[list[int]]:
    """Tokenize, join with EOS, cut into full blocks of `block` tokens (the ragged tail is dropped)."""
    eos = tok.eos_token_id
    ids: list[int] = []
    for t in texts:
        ids += tok(t, add_special_tokens=False)["input_ids"] + [eos]
    return [ids[i:i + block] for i in range(0, len(ids) - block + 1, block)]


def _train(cfg_dict: dict, train_texts: list[str], heldout_texts: list[str], meta: dict,
           commit=lambda: None) -> dict:
    """Runs anywhere torch runs (Modal GPU, or CPU via step3_domain_adapter/cpu_smoke.py)."""
    from step5_training.gpu import bf16_ok, load_lora_model, make_args, pip_freeze, trainable_summary

    cfg = build_cfg(cfg_dict)
    model, tok = load_lora_model(cfg)
    from datasets import Dataset
    from transformers import DataCollatorForLanguageModeling, Trainer, TrainingArguments

    train_blocks = pack_blocks(tok, train_texts, cfg.max_seq_len)
    if cfg.max_train_blocks:
        train_blocks = train_blocks[: cfg.max_train_blocks]
    held_blocks = pack_blocks(tok, heldout_texts, cfg.max_seq_len)
    if not train_blocks or not held_blocks:
        raise SystemExit(f"not enough text for one block of {cfg.max_seq_len} tokens "
                         f"(train {len(train_blocks)}, heldout {len(held_blocks)})")
    out = Path(cfg.output_root) / "adapter" / cfg.run_name
    args = make_args(
        TrainingArguments, output_dir=str(out / "trainer"), num_train_epochs=cfg.epochs,
        per_device_train_batch_size=cfg.batch_size, per_device_eval_batch_size=cfg.batch_size,
        gradient_accumulation_steps=cfg.grad_accum, learning_rate=cfg.learning_rate,
        lr_scheduler_type=cfg.scheduler, warmup_ratio=cfg.warmup_ratio, weight_decay=cfg.weight_decay,
        logging_steps=cfg.logging_steps, save_strategy="no", eval_strategy="no", bf16=bf16_ok(),
        report_to="none", seed=cfg.seed, remove_unused_columns=False)
    trainer = Trainer(model=model, args=args, train_dataset=Dataset.from_dict({"input_ids": train_blocks}),
                      eval_dataset=Dataset.from_dict({"input_ids": held_blocks}),
                      data_collator=DataCollatorForLanguageModeling(tok, mlm=False))
    before = trainer.evaluate()["eval_loss"]
    result = trainer.train()
    after = trainer.evaluate()["eval_loss"]

    adapter_dir = out / "adapter"
    model.save_pretrained(str(adapter_dir))
    tok.save_pretrained(str(adapter_dir))
    meta.update(stage="domain_adapter", n_train_blocks=len(train_blocks), n_heldout_blocks=len(held_blocks),
                train_tokens=len(train_blocks) * cfg.max_seq_len, heldout_loss_before=before,
                heldout_loss_after=after, heldout_ppl_before=math.exp(before), heldout_ppl_after=math.exp(after),
                train_metrics=result.metrics, log_history=trainer.state.log_history, **trainable_summary(model),
                adapter_dir=str(adapter_dir), pip_freeze=pip_freeze())
    write_json(out / "run.json", meta)
    commit()
    return {k: meta[k] for k in ("stage", "n_train_blocks", "n_heldout_blocks", "train_tokens", "heldout_ppl_before",
                                 "heldout_ppl_after", "params_trainable", "adapter_dir")}


_fn_kw = dict(volumes=VOLUMES, secrets=SECRETS, gpu="A100-80GB", timeout=2 * 3600)


@app.function(image=_IMAGES["unsloth"], **_fn_kw)
def adapter_unsloth(cfg_dict: dict, train_texts: list, heldout_texts: list, meta: dict) -> dict:
    return _train(cfg_dict, train_texts, heldout_texts, meta, commit=checkpoints.commit)


@app.function(image=_IMAGES["trl"], **_fn_kw)
def adapter_trl(cfg_dict: dict, train_texts: list, heldout_texts: list, meta: dict) -> dict:
    return _train(cfg_dict, train_texts, heldout_texts, meta, commit=checkpoints.commit)


def prepare(config: str):
    cfg = load_cfg(config)
    require_no_placeholders(cfg)
    split = split_corpus(cfg)
    if not split["train"]:
        raise SystemExit(f"no corpus text under {cfg.corpus_dir}")
    return cfg, split, run_metadata(cfg, split)


@app.local_entrypoint()
def main(config: str = "step3_domain_adapter/configs/adapter.yaml", dry_run: bool = False):
    cfg, split, meta = prepare(config)
    c = meta["corpus"]
    print(f"[adapter] {cfg.run_name}: base={cfg.base_model}, backend={cfg.backend}, gpu={cfg.gpu}; "
          f"{c['n_files']} files, {c['train_chunks']} train / {c['heldout_chunks']} held-out chunks, "
          f"~{c['est_train_tokens']:,} train tokens x {cfg.epochs} epochs")
    if dry_run:
        print(json.dumps(c["files"], indent=1))
        return
    fn = {"unsloth": adapter_unsloth, "trl": adapter_trl}[cfg.backend]
    res = fn.with_options(gpu=cfg.gpu, timeout=int(cfg.timeout_hours * 3600)).remote(
        dataclasses.asdict(cfg), split["train"], split["heldout"], meta)
    print(json.dumps(res, indent=1, default=str))
