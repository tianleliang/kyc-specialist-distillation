"""GPU-side helpers. Imported only inside Modal containers (torch/transformers live there)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from step5_training.common import LoraCfg, TrainCommon, unsloth_targets


def load_lora_model(cfg: TrainCommon):
    """-> (peft_model, tokenizer). 16-bit LoRA on either backend. Never 4-bit: QLoRA loses
    too much accuracy on Qwen3.5 (research brief, tooling traps)."""
    if cfg.backend == "unsloth":
        from unsloth import FastLanguageModel  # must be imported before transformers/trl

        kw = dict(model_name=cfg.base_model, max_seq_length=cfg.max_seq_len, dtype=None,
                  load_in_4bit=False, full_finetuning=False)
        try:
            model, tok = FastLanguageModel.from_pretrained(load_in_16bit=True, **kw)
        except TypeError:  # older Unsloth without load_in_16bit: 4bit=False already means 16-bit
            model, tok = FastLanguageModel.from_pretrained(**kw)
        model = FastLanguageModel.get_peft_model(
            model, r=cfg.lora.r, lora_alpha=cfg.lora.alpha, lora_dropout=cfg.lora.dropout,
            target_modules=unsloth_targets(cfg.lora), bias="none",
            use_gradient_checkpointing="unsloth", random_state=cfg.seed)
        return model, _tok(tok)

    if cfg.backend != "trl":
        raise ValueError(f"unknown backend {cfg.backend!r}")
    import torch
    from peft import get_peft_model
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(cfg.base_model)
    model = AutoModelForCausalLM.from_pretrained(
        cfg.base_model, dtype=torch.bfloat16 if bf16_ok() else torch.float32, attn_implementation="sdpa")
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    model.enable_input_require_grads()
    model = get_peft_model(model, lora_config(cfg.lora))
    return model, _tok(tok)


def lora_config(lora: LoraCfg):
    from peft import LoraConfig

    return LoraConfig(r=lora.r, lora_alpha=lora.alpha, lora_dropout=lora.dropout,
                      target_modules=lora.target_modules, bias="none", task_type="CAUSAL_LM")


def bf16_ok() -> bool:
    import torch

    return torch.cuda.is_available() and torch.cuda.is_bf16_supported()


def _tok(tok):
    tok = getattr(tok, "tokenizer", tok)  # multimodal processors wrap the tokenizer
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    return tok


def log_example(tok, rendered: dict) -> None:
    """Print one rendered example so the template (thinking off, single EOS) can be eyeballed
    in the Modal logs."""
    print("=== rendered example ===")
    for k, v in rendered.items():
        print(f"--- {k} ({len(tok(v)['input_ids'])} tokens) ---\n{v[-1500:]}")


def make_args(cls, required: tuple[str, ...] = (), **kw):
    """Build a TRL/Transformers config, tolerating version drift: translate warmup_ratio when
    the installed version folded it into warmup_steps, and drop (loudly) unknown kwargs.
    Keys in `required` change what is trained, so they must exist or we stop."""
    import dataclasses

    fields = {f.name for f in dataclasses.fields(cls)}
    missing = [k for k in required if k not in fields]
    if missing:
        raise RuntimeError(f"{cls.__name__} lacks {missing}; pin a TRL version that has them")
    if "warmup_ratio" in kw and "warmup_ratio" not in fields:
        kw["warmup_steps"] = kw.pop("warmup_ratio")  # v5 accepts a float ratio here
    dropped = sorted(k for k in kw if k not in fields)
    if dropped:
        print(f"WARNING: {cls.__name__} does not accept {dropped}; dropped")
    return cls(**{k: v for k, v in kw.items() if k in fields})


def trainable_summary(model) -> dict:
    total = sum(p.numel() for p in model.parameters())
    train = sum(p.numel() for p in model.parameters() if p.requires_grad)
    return {"params_total": total, "params_trainable": train}


def pip_freeze() -> list[str]:
    try:
        return subprocess.run(["pip", "freeze"], capture_output=True, text=True, check=False).stdout.split("\n")
    except OSError:
        return []


def write_json(path: str | Path, obj) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(obj, indent=1, default=str))
