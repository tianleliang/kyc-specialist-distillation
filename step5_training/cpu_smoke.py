"""CPU pre-flight for the training code: SFT -> merge+verify -> DPO -> merge+verify on a tiny,
randomly initialised Qwen2-architecture model built offline (no downloads, no GPU, ~1 min).

    python -m step5_training.cpu_smoke [--keep DIR]

It runs the *same* functions the Modal jobs run (sft._train, merge.merge_and_verify,
dpo._train), so it catches TRL / PEFT / Transformers API drift and template bugs before any
GPU time is spent. It says nothing about model quality.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import random
import shutil
import tempfile
from pathlib import Path

from step5_training.common import DPOCfg, MergeCfg, SFTCfg, LoraCfg, probe_prompts, read_jsonl

TOY = Path(__file__).with_name("toy") / "sft_toy.jsonl"

CHAT_TEMPLATE = (
    r"{% for m in messages %}{{ '<|im_start|>' + m['role'] + '\n' + m['content'] + '<|im_end|>\n' }}{% endfor %}"
    r"{% if add_generation_prompt %}{{ '<|im_start|>assistant\n' }}"
    r"{% if enable_thinking is defined and enable_thinking is false %}{{ '<think>\n\n</think>\n\n' }}{% endif %}"
    r"{% endif %}"
)


def build_tiny_model(root: Path, texts: list[str]) -> str:
    from tokenizers import Tokenizer, models, pre_tokenizers, trainers
    from transformers import PreTrainedTokenizerFast, Qwen2Config, Qwen2ForCausalLM

    specials = ["<|endoftext|>", "<|im_start|>", "<|im_end|>", "<think>", "</think>"]
    tk = Tokenizer(models.BPE(unk_token=None))
    tk.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
    tk.train_from_iterator(texts, trainers.BpeTrainer(
        vocab_size=600, special_tokens=specials, initial_alphabet=pre_tokenizers.ByteLevel.alphabet()))
    from tokenizers import decoders

    tk.decoder = decoders.ByteLevel()
    tok = PreTrainedTokenizerFast(tokenizer_object=tk, eos_token="<|im_end|>", pad_token="<|endoftext|>",
                                  chat_template=CHAT_TEMPLATE)
    cfg = Qwen2Config(vocab_size=len(tok), hidden_size=64, intermediate_size=128, num_hidden_layers=2,
                      num_attention_heads=4, num_key_value_heads=2, max_position_embeddings=1024,
                      eos_token_id=tok.eos_token_id, pad_token_id=tok.pad_token_id, tie_word_embeddings=True)
    path = root / "tiny-base"
    Qwen2ForCausalLM(cfg).save_pretrained(path)
    tok.save_pretrained(path)
    return str(path)


def dpo_pairs(rows: list[dict]) -> list[dict]:
    flip = {"approve": "reject", "reject": "escalate", "escalate": "approve"}
    out = []
    for r in rows:
        ans = json.loads(r["messages"][-1]["content"])
        bad = dict(ans, decision=flip[ans["decision"]])
        out.append({"id": r["id"], "prompt": r["messages"][:-1], "chosen": json.dumps(ans),
                    "rejected": json.dumps(bad)})
    return out


def run(root: Path) -> dict:
    from step5_training import dpo, merge, sft

    random.seed(0)
    rows = read_jsonl(TOY)
    texts = [m["content"] for r in rows for m in r["messages"]] * 4
    base = build_tiny_model(root, texts)
    lora = LoraCfg(r=8, alpha=16, target_modules="all-linear")
    common = dict(base_model=base, train_file=str(TOY), allow_no_eval_manifest=True, backend="trl",
                  max_seq_len=256, batch_size=4, grad_accum=1, logging_steps=2, output_root=str(root),
                  lora=lora)

    s_cfg = SFTCfg(run_name="smoke", epochs=4, learning_rate=5e-3, **common)
    s_res = sft._train(dataclasses.asdict(s_cfg), rows, rows[:4], {"smoke": True})
    probes = probe_prompts(rows, 4)
    m1 = merge.merge_and_verify(MergeCfg(run_name="smoke", base_model=base, adapter_dir=s_res["adapter_dir"],
                                         output_dir=str(root / "merged-sft"), max_new_tokens=16), probes)

    d_cfg = DPOCfg(run_name="smoke", **{**common, "base_model": str(root / "merged-sft")},
                   epochs=2, learning_rate=5e-3, max_prompt_len=192)
    pairs = dpo_pairs(rows)
    d_res = dpo._train(dataclasses.asdict(d_cfg), pairs, pairs[:4], {"smoke": True})
    m2 = merge.merge_and_verify(MergeCfg(run_name="smoke-dpo", base_model=str(root / "merged-sft"),
                                         adapter_dir=d_res["adapter_dir"], output_dir=str(root / "merged-dpo"),
                                         max_new_tokens=16), probes)
    first = lambda h: next(x["loss"] for x in h if "loss" in x)  # noqa: E731
    last = lambda h: [x["loss"] for x in h if "loss" in x][-1]  # noqa: E731
    s_hist = json.loads((root / "sft" / "smoke" / "run.json").read_text())["log_history"]
    d_hist = json.loads((root / "dpo" / "smoke" / "run.json").read_text())["log_history"]
    return {
        "sft": {"loss_first": first(s_hist), "loss_last": last(s_hist), "trainable": s_res["params_trainable"]},
        "merge_sft": {k: m1[k] for k in ("n_outputs_differ", "n_probes", "max_next_token_logit_delta", "lora_b_norm")},
        "dpo": {"loss_first": first(d_hist), "loss_last": last(d_hist)},
        "merge_dpo": {k: m2[k] for k in ("n_outputs_differ", "n_probes", "max_next_token_logit_delta")},
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", help="write artifacts here instead of a temp dir")
    a = ap.parse_args()
    root = Path(a.keep) if a.keep else Path(tempfile.mkdtemp(prefix="zorbe-smoke-"))
    root.mkdir(parents=True, exist_ok=True)
    try:
        print(json.dumps(run(root), indent=1))
        print("CPU SMOKE OK")
        return 0
    finally:
        if not a.keep:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
