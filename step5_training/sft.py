"""SFT with 16-bit LoRA on Modal (Unsloth by default, plain TRL+PEFT as fallback).

    modal run -m step5_training.sft --config step5_training/configs/sft.yaml            # train
    modal run -m step5_training.sft --config step5_training/configs/sft.yaml --dry-run  # local checks only, no GPU

Locally, before any GPU starts: fill-in check for PLACEHOLDER values, data validation, and
the contamination gate (eval manifest verifies; no eval record overlaps the training data).
On the GPU: render with the model's chat template (thinking off), train on completions only,
save the adapter + run.json (config, data hashes, gate report, metrics, pip freeze) to the
`zorbe-checkpoints` volume under sft/<run_name>/. The container exits when training ends,
so nothing keeps a GPU running.

Next step: step5_training/merge.py (merge into base, verify outputs differ from base, push to HF).
"""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

if __package__ in (None, ""):  # allow `modal run step5_training/sft.py` as well as `-m step5_training.sft`
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import modal

from step5_training.common import (
    SFTCfg, _build, contamination_gate, load_config, read_jsonl, render_sft,
    require_no_placeholders, run_metadata, validate_sft,
)
from step5_training.modal_infra import CKPT, IMAGES, SECRETS, VOLUMES, checkpoints

app = modal.App("zorbe-sft")


def _train(cfg_dict: dict, train_rows: list[dict], val_rows: list[dict], meta: dict,
           commit=lambda: None) -> dict:
    """Runs anywhere torch runs (Modal GPU, or CPU via step5_training/cpu_smoke.py)."""
    from step5_training.gpu import (bf16_ok, load_lora_model, log_example, make_args, pip_freeze,
                           trainable_summary, write_json)

    cfg = _build(SFTCfg, cfg_dict)
    model, tok = load_lora_model(cfg)  # imports unsloth first when that backend is used
    from datasets import Dataset
    from trl import SFTConfig, SFTTrainer

    train = [render_sft(tok, r, cfg.enable_thinking) for r in train_rows]
    val = [render_sft(tok, r, cfg.enable_thinking) for r in val_rows]
    log_example(tok, train[0])
    lengths = [len(tok(x["prompt"] + x["completion"])["input_ids"]) for x in train]
    too_long = sum(n > cfg.max_seq_len for n in lengths)
    if too_long:  # truncation would cut the JSON target and teach malformed output
        print(f"WARNING: {too_long}/{len(train)} examples exceed max_seq_len={cfg.max_seq_len}")

    out = Path(cfg.output_root) / "sft" / cfg.run_name
    args = make_args(
        SFTConfig, required=("completion_only_loss", "max_length"),
        output_dir=str(out / "trainer"), num_train_epochs=cfg.epochs,
        per_device_train_batch_size=cfg.batch_size, per_device_eval_batch_size=cfg.batch_size,
        gradient_accumulation_steps=cfg.grad_accum, learning_rate=cfg.learning_rate,
        lr_scheduler_type=cfg.scheduler, warmup_ratio=cfg.warmup_ratio,
        weight_decay=cfg.weight_decay, logging_steps=cfg.logging_steps, save_strategy="no",
        eval_strategy="epoch" if val else "no", bf16=bf16_ok(), max_length=cfg.max_seq_len,
        completion_only_loss=True, packing=False, report_to="none", seed=cfg.seed,
    )
    trainer = SFTTrainer(model=model, args=args, train_dataset=Dataset.from_list(train),
                         eval_dataset=Dataset.from_list(val) if val else None, processing_class=tok)
    result = trainer.train()

    adapter_dir = out / "adapter"
    model.save_pretrained(str(adapter_dir))
    tok.save_pretrained(str(adapter_dir))
    meta.update(stage="sft", n_train=len(train), n_val=len(val), n_over_max_len=too_long,
                max_tokens_seen=max(lengths), train_metrics=result.metrics,
                log_history=trainer.state.log_history, **trainable_summary(model),
                adapter_dir=str(adapter_dir), pip_freeze=pip_freeze())
    write_json(out / "run.json", meta)
    commit()
    return {k: meta[k] for k in ("stage", "n_train", "n_val", "n_over_max_len", "train_metrics",
                                  "params_trainable", "adapter_dir")}


_fn_kw = dict(volumes=VOLUMES, secrets=SECRETS, gpu="A100-80GB", timeout=4 * 3600)


def _check_vol_base(cfg_dict: dict) -> None:
    """A base on the checkpoints volume (e.g. /vol/ckpt/merged/<run>, the final runs): see the
    latest commit (a merge that just finished) and fail fast if the weights are not there."""
    base = str(cfg_dict["base_model"])
    if base.startswith(CKPT + "/"):
        checkpoints.reload()
        if not (Path(base) / "config.json").exists():
            raise FileNotFoundError(f"base_model not found on the zorbe-checkpoints volume: {base}")


@app.function(image=IMAGES["unsloth"], **_fn_kw)
def sft_unsloth(cfg_dict: dict, train_rows: list, val_rows: list, meta: dict) -> dict:
    _check_vol_base(cfg_dict)
    return _train(cfg_dict, train_rows, val_rows, meta, commit=checkpoints.commit)


@app.function(image=IMAGES["trl"], **_fn_kw)
def sft_trl(cfg_dict: dict, train_rows: list, val_rows: list, meta: dict) -> dict:
    _check_vol_base(cfg_dict)
    return _train(cfg_dict, train_rows, val_rows, meta, commit=checkpoints.commit)


def prepare(config: str) -> tuple[SFTCfg, list, list, dict]:
    """All local checks. Raises SystemExit on any problem."""
    cfg = load_config(config, SFTCfg)
    require_no_placeholders(cfg)
    rows = read_jsonl(cfg.train_file)
    if cfg.max_train_rows:
        rows = rows[: cfg.max_train_rows]
    validate_sft(rows)
    val = read_jsonl(cfg.val_file) if cfg.val_file else []
    validate_sft(val)
    files = [cfg.train_file] + ([cfg.val_file] if cfg.val_file else [])
    gate = contamination_gate(cfg, files)
    return cfg, rows, val, run_metadata(cfg, files, gate)


@app.local_entrypoint()
def main(config: str = "step5_training/configs/sft.yaml", dry_run: bool = False):
    cfg, rows, val, meta = prepare(config)
    print(f"[sft] {cfg.run_name}: {len(rows)} train / {len(val)} val rows, base={cfg.base_model}, "
          f"backend={cfg.backend}, gpu={cfg.gpu}; gate={json.dumps(meta['contamination_gate'])}")
    if dry_run:
        return
    fn = {"unsloth": sft_unsloth, "trl": sft_trl}[cfg.backend]
    res = fn.with_options(gpu=cfg.gpu, timeout=int(cfg.timeout_hours * 3600)).remote(
        dataclasses.asdict(cfg), rows, val, meta)
    print(json.dumps(res, indent=1, default=str))
