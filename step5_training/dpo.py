"""DPO with 16-bit LoRA on Modal, starting from the *merged* SFT model.

    modal run -m step5_training.dpo --config step5_training/configs/dpo.yaml [--dry-run]

Why merged SFT as the base: a fresh LoRA is trained on top of it and TRL uses the same
model with adapters disabled as the frozen reference, so the reference is exactly the SFT
policy (no second copy of the weights in memory). Produce it with step5_training/merge.py first.

Pairs ({"prompt": [...], "chosen": str, "rejected": str}) come from whichever technique
Tianle picks (e.g. rejection sampling against programmatic checks, teacher-as-judge).
Output: adapter + run.json under dpo/<run_name>/ on the `zorbe-checkpoints` volume; then
merge it with step5_training/merge.py (base_model = the merged SFT weights).
"""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import modal

from step5_training.common import (
    DPOCfg, _build, contamination_gate, load_config, read_jsonl, render_dpo,
    require_no_placeholders, run_metadata, validate_dpo,
)
from step5_training.modal_infra import IMAGES, SECRETS, VOLUMES, checkpoints

app = modal.App("zorbe-dpo")


def _train(cfg_dict: dict, train_rows: list[dict], val_rows: list[dict], meta: dict,
           commit=lambda: None) -> dict:
    """Runs anywhere torch runs (Modal GPU, or CPU via step5_training/cpu_smoke.py)."""
    from step5_training.gpu import (bf16_ok, load_lora_model, log_example, make_args, pip_freeze,
                           trainable_summary, write_json)

    cfg = _build(DPOCfg, cfg_dict)
    model, tok = load_lora_model(cfg)
    if cfg.backend == "unsloth":
        try:
            from unsloth import PatchDPOTrainer

            PatchDPOTrainer()
        except ImportError:  # newer Unsloth patches automatically
            pass
    from datasets import Dataset
    from trl import DPOConfig, DPOTrainer

    train = [render_dpo(tok, r, cfg.enable_thinking) for r in train_rows]
    val = [render_dpo(tok, r, cfg.enable_thinking) for r in val_rows]
    log_example(tok, train[0])

    out = Path(cfg.output_root) / "dpo" / cfg.run_name
    args = make_args(
        DPOConfig, required=("beta", "max_length"),
        output_dir=str(out / "trainer"), beta=cfg.beta, loss_type=cfg.loss_type,
        max_length=cfg.max_seq_len, max_prompt_length=cfg.max_prompt_len,
        num_train_epochs=cfg.epochs, per_device_train_batch_size=cfg.batch_size,
        per_device_eval_batch_size=cfg.batch_size, gradient_accumulation_steps=cfg.grad_accum,
        learning_rate=cfg.learning_rate, lr_scheduler_type=cfg.scheduler,
        warmup_ratio=cfg.warmup_ratio, weight_decay=cfg.weight_decay,
        logging_steps=cfg.logging_steps, save_strategy="no", eval_strategy="epoch" if val else "no",
        bf16=bf16_ok(), report_to="none", seed=cfg.seed,
    )
    trainer = DPOTrainer(model=model, ref_model=None, args=args,
                         train_dataset=Dataset.from_list(train),
                         eval_dataset=Dataset.from_list(val) if val else None, processing_class=tok)
    result = trainer.train()

    adapter_dir = out / "adapter"
    model.save_pretrained(str(adapter_dir))
    tok.save_pretrained(str(adapter_dir))
    meta.update(stage="dpo", n_train=len(train), n_val=len(val), train_metrics=result.metrics,
                log_history=trainer.state.log_history, **trainable_summary(model),
                adapter_dir=str(adapter_dir), pip_freeze=pip_freeze())
    write_json(out / "run.json", meta)
    commit()
    return {k: meta[k] for k in ("stage", "n_train", "n_val", "train_metrics",
                                  "params_trainable", "adapter_dir")}


_fn_kw = dict(volumes=VOLUMES, secrets=SECRETS, gpu="A100-80GB", timeout=4 * 3600)


@app.function(image=IMAGES["unsloth"], **_fn_kw)
def dpo_unsloth(cfg_dict: dict, train_rows: list, val_rows: list, meta: dict) -> dict:
    checkpoints.reload()  # see the merged SFT weights written by an earlier merge run
    return _train(cfg_dict, train_rows, val_rows, meta, commit=checkpoints.commit)


@app.function(image=IMAGES["trl"], **_fn_kw)
def dpo_trl(cfg_dict: dict, train_rows: list, val_rows: list, meta: dict) -> dict:
    checkpoints.reload()  # see the merged SFT weights written by an earlier merge run
    return _train(cfg_dict, train_rows, val_rows, meta, commit=checkpoints.commit)


def prepare(config: str) -> tuple[DPOCfg, list, list, dict]:
    cfg = load_config(config, DPOCfg)
    require_no_placeholders(cfg)
    rows = read_jsonl(cfg.train_file)
    if cfg.max_train_rows:
        rows = rows[: cfg.max_train_rows]
    validate_dpo(rows)
    val = read_jsonl(cfg.val_file) if cfg.val_file else []
    validate_dpo(val)
    files = [cfg.train_file] + ([cfg.val_file] if cfg.val_file else [])
    gate = contamination_gate(cfg, files)
    return cfg, rows, val, run_metadata(cfg, files, gate)


@app.local_entrypoint()
def main(config: str = "step5_training/configs/dpo.yaml", dry_run: bool = False):
    cfg, rows, val, meta = prepare(config)
    print(f"[dpo] {cfg.run_name}: {len(rows)} pairs / {len(val)} val, base={cfg.base_model}, "
          f"beta={cfg.beta}, backend={cfg.backend}; gate={json.dumps(meta['contamination_gate'])}")
    if dry_run:
        return
    fn = {"unsloth": dpo_unsloth, "trl": dpo_trl}[cfg.backend]
    res = fn.with_options(gpu=cfg.gpu, timeout=int(cfg.timeout_hours * 3600)).remote(
        dataclasses.asdict(cfg), rows, val, meta)
    print(json.dumps(res, indent=1, default=str))
