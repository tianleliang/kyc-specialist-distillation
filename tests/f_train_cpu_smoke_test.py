"""Session F: runs step5_training/cpu_smoke.py (SFT -> merge -> DPO -> merge on a tiny offline model).
Skipped unless torch, transformers, trl, peft and tokenizers are installed (training envs only)."""

import pytest

for mod in ("torch", "transformers", "trl", "peft", "tokenizers", "datasets", "modal"):
    pytest.importorskip(mod)


def test_cpu_smoke(tmp_path):
    from step5_training.cpu_smoke import run

    res = run(tmp_path)
    assert res["sft"]["loss_last"] < res["sft"]["loss_first"]
    assert res["merge_sft"]["n_outputs_differ"] >= 1 and res["merge_sft"]["lora_b_norm"] > 0
    assert res["dpo"]["loss_first"] == pytest.approx(0.6931, abs=1e-3)  # log 2 at init: ref == policy
    assert res["merge_dpo"]["max_next_token_logit_delta"] > 1e-3
    assert (tmp_path / "merged-sft" / "verify.json").exists()
    assert (tmp_path / "sft" / "smoke" / "run.json").exists()


def test_merge_refuses_untrained_adapter(tmp_path):
    from peft import get_peft_model
    from transformers import AutoModelForCausalLM, AutoTokenizer

    from step5_training.common import LoraCfg, MergeCfg, TOY_PROBES
    from step5_training.cpu_smoke import build_tiny_model
    from step5_training.gpu import lora_config
    from step5_training.merge import merge_and_verify

    base = build_tiny_model(tmp_path, ["toy text for a tokenizer"] * 20)
    m = get_peft_model(AutoModelForCausalLM.from_pretrained(base), lora_config(LoraCfg(r=4, alpha=8)))
    m.save_pretrained(tmp_path / "adapter")  # lora_B initialises to zero: a no-op adapter
    AutoTokenizer.from_pretrained(base).save_pretrained(tmp_path / "adapter")
    cfg = MergeCfg(run_name="noop", base_model=base, adapter_dir=str(tmp_path / "adapter"),
                   output_dir=str(tmp_path / "merged"), max_new_tokens=4)
    with pytest.raises(RuntimeError, match="all zero"):
        merge_and_verify(cfg, TOY_PROBES)
