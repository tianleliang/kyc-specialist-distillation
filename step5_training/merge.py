"""Merge a LoRA adapter into its base weights, prove the merge changed the model, and
optionally push merged weights + adapter to Hugging Face.

    modal run -m step5_training.merge --config step5_training/configs/merge.yaml [--dry-run]

Why: Qwen3.5 LoRA adapters can load into vLLM and silently do nothing (research brief,
tooling traps). So we serve merged weights, and this script refuses to finish unless the
merged model, reloaded from disk exactly as vLLM will load it, behaves differently from the
base on probe prompts:
  1. the adapter's lora_B weights are not all zero (training actually moved something);
  2. greedy generations differ from base on >= min_differing_probes probes, and
  3. next-token logits differ (max |delta| reported).
Results go to verify.json next to the merged weights (and into the HF repo).
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
    TOY_PROBES, MergeCfg, _build, load_config, probe_prompts, read_jsonl, render_prompt,
    require_no_placeholders,
)
from step5_training.modal_infra import IMAGES, SECRETS, VOLUMES, checkpoints

app = modal.App("zorbe-merge")


def _generate(model, tok, probes, cfg: MergeCfg):
    import torch

    outs, first_logits = [], None
    for msgs in probes:
        enc = tok(render_prompt(tok, msgs, cfg.enable_thinking), return_tensors="pt").to(model.device)
        with torch.no_grad():
            if first_logits is None:
                first_logits = model(**enc).logits[0, -1].float().cpu()
            gen = model.generate(**enc, max_new_tokens=cfg.max_new_tokens, do_sample=False,
                                 pad_token_id=tok.pad_token_id or tok.eos_token_id)
        outs.append(tok.decode(gen[0, enc["input_ids"].shape[1]:], skip_special_tokens=True))
    return outs, first_logits


def merge_and_verify(cfg: MergeCfg, probes: list, commit=lambda: None) -> dict:
    """Runs anywhere torch runs (Modal GPU, or CPU via step5_training/cpu_smoke.py)."""
    import gc

    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    from step5_training.gpu import bf16_ok, write_json

    if not Path(cfg.adapter_dir).exists():
        raise FileNotFoundError(f"adapter not found on volume: {cfg.adapter_dir}")
    tok = AutoTokenizer.from_pretrained(cfg.adapter_dir)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    dev, dtype = ("cuda", torch.bfloat16) if bf16_ok() else ("cpu", torch.float32)
    load = lambda p: AutoModelForCausalLM.from_pretrained(p, dtype=dtype).to(dev)  # noqa: E731

    base = load(cfg.base_model)
    base_out, base_logits = _generate(base, tok, probes, cfg)  # before merge mutates weights

    peft_model = PeftModel.from_pretrained(base, cfg.adapter_dir)
    lora_b_norm = sum(p.detach().float().norm().item()
                      for n, p in peft_model.named_parameters() if "lora_B" in n)
    if lora_b_norm == 0.0:
        raise RuntimeError("adapter lora_B weights are all zero: training did not move the model")
    merged = peft_model.merge_and_unload()
    merged.save_pretrained(cfg.output_dir, safe_serialization=True)
    tok.save_pretrained(cfg.output_dir)
    del base, peft_model, merged
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    reloaded = load(cfg.output_dir)  # what vLLM will see
    new_out, new_logits = _generate(reloaded, tok, probes, cfg)
    n_diff = sum(a != b for a, b in zip(base_out, new_out))
    max_logit_delta = float((new_logits - base_logits).abs().max())
    verify = {
        "base_model": cfg.base_model, "adapter_dir": cfg.adapter_dir, "output_dir": cfg.output_dir,
        "lora_b_norm": lora_b_norm, "n_probes": len(probes), "n_outputs_differ": n_diff,
        "max_next_token_logit_delta": max_logit_delta,
        "examples": [{"prompt": p[-1]["content"][:300], "base": b[:300], "merged": m[:300]}
                     for p, b, m in list(zip(probes, base_out, new_out))[:3]],
    }
    write_json(Path(cfg.output_dir) / "verify.json", verify)
    commit()
    if n_diff < cfg.min_differing_probes or max_logit_delta < 1e-3:
        raise RuntimeError(f"merged model is indistinguishable from base: {verify}")

    if cfg.hub_repo:
        from huggingface_hub import HfApi

        api = HfApi()
        api.create_repo(cfg.hub_repo, private=cfg.hub_private, exist_ok=True)
        api.upload_folder(folder_path=cfg.output_dir, repo_id=cfg.hub_repo,
                          commit_message=f"merged weights: {cfg.run_name}")
        if cfg.push_adapter:
            api.upload_folder(folder_path=cfg.adapter_dir, repo_id=cfg.hub_repo, path_in_repo="adapter",
                              commit_message=f"LoRA adapter: {cfg.run_name}")
        verify["hub_repo"] = cfg.hub_repo
    return verify


@app.function(image=IMAGES["trl"], volumes=VOLUMES, secrets=SECRETS, gpu="L4", timeout=3600)
def merge_remote(cfg_dict: dict, probes: list) -> dict:
    checkpoints.reload()  # see the adapter written by the training run
    return merge_and_verify(_build(MergeCfg, cfg_dict), probes, commit=checkpoints.commit)


@app.local_entrypoint()
def main(config: str = "step5_training/configs/merge.yaml", dry_run: bool = False):
    cfg = load_config(config, MergeCfg)
    require_no_placeholders(cfg)
    if cfg.probe_file and Path(cfg.probe_file).exists():
        probes = probe_prompts(read_jsonl(cfg.probe_file), cfg.n_probes)
    else:
        print("[merge] no probe_file; using built-in toy probes")
        probes = TOY_PROBES
    print(f"[merge] {cfg.run_name}: {cfg.adapter_dir} + {cfg.base_model} -> {cfg.output_dir} "
          f"(hub: {cfg.hub_repo or 'no push'}), {len(probes)} probes")
    if dry_run:
        return
    res = merge_remote.with_options(gpu=cfg.gpu, timeout=int(cfg.timeout_hours * 3600)).remote(
        dataclasses.asdict(cfg), probes)
    print(json.dumps(res, indent=1, default=str))
