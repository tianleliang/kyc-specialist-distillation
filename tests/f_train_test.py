"""Session F: step5_training/ (configs, data validation, rendering, contamination gate, Modal scripts
import and local prepare). No GPU, no Modal credentials: nothing here calls .remote()."""

import json

import pytest

from step6_evaluation.split_guard import freeze
from step5_training.common import (
    DPOCfg, MergeCfg, SFTCfg, contamination_gate, load_config, placeholders, probe_prompts,
    read_jsonl, render_dpo, render_sft, require_no_placeholders, run_metadata, unsloth_targets,
    validate_dpo, validate_sft,
)


class FakeTok:
    """Minimal stand-in for a HF tokenizer with a ChatML-style template."""
    eos_token = "<|im_end|>"

    def __init__(self):
        self.calls = []

    def apply_chat_template(self, msgs, tokenize, add_generation_prompt, enable_thinking):
        self.calls.append(enable_thinking)
        s = "".join(f"<|im_start|>{m['role']}\n{m['content']}<|im_end|>\n" for m in msgs)
        if add_generation_prompt:
            s += "<|im_start|>assistant\n" + ("" if enable_thinking else "<think>\n\n</think>\n\n")
        return s


SFT_ROW = {"id": "a", "messages": [{"role": "system", "content": "S"}, {"role": "user", "content": "U"},
                                   {"role": "assistant", "content": '{"decision":"approve"}'}]}
DPO_ROW = {"id": "b", "prompt": [{"role": "user", "content": "U"}],
           "chosen": '{"decision":"escalate"}', "rejected": '{"decision":"approve"}'}


@pytest.mark.parametrize("path,cls", [("step5_training/configs/sft.yaml", SFTCfg), ("step5_training/configs/dpo.yaml", DPOCfg),
                                      ("step5_training/configs/merge.yaml", MergeCfg)])
def test_real_configs_load_and_are_placeholder_gated(path, cls):
    cfg = load_config(path, cls)
    assert "base_model" in placeholders(cfg)
    with pytest.raises(SystemExit, match="placeholders"):
        require_no_placeholders(cfg)
    if cls is not MergeCfg:
        assert cfg.enable_thinking is False and cfg.lora.r == 16


@pytest.mark.parametrize("path,cls", [("step5_training/configs/sft_toy.yaml", SFTCfg),
                                      ("step5_training/configs/merge_toy.yaml", MergeCfg)])
def test_toy_configs_complete(path, cls):
    assert placeholders(load_config(path, cls)) == []


def test_unknown_config_key(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("run_name: x\nbase_model: y\ntrain_file: z\nlearning_rat: 1\n")
    with pytest.raises(ValueError, match="learning_rat"):
        load_config(p, SFTCfg)
    p.write_text("run_name: x\nbase_model: y\ntrain_file: z\nlora: {rank: 8}\n")
    with pytest.raises(ValueError, match="rank"):
        load_config(p, SFTCfg)


def test_unsloth_targets():
    cfg = load_config("step5_training/configs/sft.yaml", SFTCfg)
    assert "q_proj" in unsloth_targets(cfg.lora)
    cfg.lora.target_modules = ["q_proj"]
    assert unsloth_targets(cfg.lora) == ["q_proj"]


def test_validate_sft():
    validate_sft([SFT_ROW])
    validate_sft(read_jsonl("step5_training/toy/sft_toy.jsonl"))
    bad = json.loads(json.dumps(SFT_ROW))
    bad["messages"] = bad["messages"][:-1]
    with pytest.raises(ValueError, match="last message"):
        validate_sft([bad])
    with pytest.raises(ValueError, match="no user"):
        validate_sft([{"messages": [{"role": "assistant", "content": "x"}]}])
    with pytest.raises(ValueError, match="bad message"):
        validate_sft([{"messages": [{"role": "tool", "content": "x"}]}])


def test_validate_dpo():
    validate_dpo([DPO_ROW])
    with pytest.raises(ValueError, match="chosen == rejected"):
        validate_dpo([{**DPO_ROW, "rejected": DPO_ROW["chosen"]}])
    with pytest.raises(ValueError, match="missing rejected"):
        validate_dpo([{k: v for k, v in DPO_ROW.items() if k != "rejected"}])
    with pytest.raises(ValueError, match="end on a user"):
        validate_dpo([{**DPO_ROW, "prompt": DPO_ROW["prompt"] + [{"role": "assistant", "content": "a"}]}])


def test_render_sft_thinking_off_single_eos():
    tok = FakeTok()
    r = render_sft(tok, SFT_ROW)
    assert tok.calls == [False]
    assert r["prompt"].endswith("<|im_start|>assistant\n<think>\n\n</think>\n\n")
    assert "approve" not in r["prompt"]  # target never leaks into the prompt
    assert r["completion"] == '{"decision":"approve"}<|im_end|>'
    row = json.loads(json.dumps(SFT_ROW))
    row["messages"][-1]["content"] += "<|im_end|>"
    assert render_sft(tok, row)["completion"].count("<|im_end|>") == 1


def test_render_dpo_leaves_eos_to_trl():
    r = render_dpo(FakeTok(), DPO_ROW)
    assert r["chosen"] == DPO_ROW["chosen"] and r["rejected"] == DPO_ROW["rejected"]
    assert render_dpo(FakeTok(), DPO_ROW, add_eos=True)["chosen"].endswith("<|im_end|>")


def test_probe_prompts():
    p = probe_prompts([SFT_ROW, DPO_ROW], 5)
    assert p[0][-1]["role"] == "user" and len(p[0]) == 2 and p[1] == DPO_ROW["prompt"]


def _write(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return str(path)


def test_contamination_gate(tmp_path):
    cfg = SFTCfg(run_name="r", base_model="m", train_file="t")
    with pytest.raises(SystemExit, match="eval_manifest is required"):
        contamination_gate(cfg, [])
    cfg.allow_no_eval_manifest = True
    assert "skipped" in contamination_gate(cfg, [])

    ev_pkts = [f"Applicant Zorvan Quell{i} born 19{50 + i}-0{1 + i % 9}-1{i % 9} passport P{7000000 + i * 37} "
               f"address {i} Lanternfold Road unit {i * 3} hit score {60 + i}" for i in range(20)]
    tr_pkts = [p.replace("Zorvan", "Imaro").replace("Lanternfold", "Cobberway") + " extra" for p in ev_pkts]
    evp = _write(tmp_path / "eval.jsonl", [{"packet": p} for p in ev_pkts])
    freeze([evp], tmp_path / "MANIFEST.json")
    cfg = SFTCfg(run_name="r", base_model="m", train_file="t", eval_manifest=str(tmp_path / "MANIFEST.json"))

    def sft(p):
        return {"messages": [{"role": "user", "content": p}, {"role": "assistant", "content": "{}"}]}

    clean = _write(tmp_path / "clean.jsonl", [sft(p) for p in tr_pkts])
    rep = contamination_gate(cfg, [clean])
    assert rep["contaminated_eval_records"] == 0 and "findings" not in rep
    meta = run_metadata(cfg, [clean], rep)
    assert len(meta["data_sha256"][clean]) == 64 and meta["config"]["run_name"] == "r"

    dirty = _write(tmp_path / "dirty.jsonl", [sft(p) for p in tr_pkts] + [sft(ev_pkts[7])])
    with pytest.raises(SystemExit, match="CONTAMINATION"):
        contamination_gate(cfg, [dirty])
    with open(evp, "a") as f:
        f.write('{"packet": "edited after freeze"}\n')
    with pytest.raises(SystemExit, match="does not verify"):
        contamination_gate(cfg, [clean])


# --- Modal scripts: import (defines apps/functions lazily, no network) and local prepare ---

def test_modal_scripts_import_and_prepare():
    pytest.importorskip("modal")
    import step5_training.dpo
    import step5_training.merge
    import step5_training.sft

    for mod, fns in ((step5_training.sft, ("sft_unsloth", "sft_trl")), (step5_training.dpo, ("dpo_unsloth", "dpo_trl")),
                     (step5_training.merge, ("merge_remote",))):
        for fn in fns:
            assert hasattr(getattr(mod, fn), "remote")
    cfg, rows, val, meta = step5_training.sft.prepare("step5_training/configs/sft_toy.yaml")
    assert len(rows) == 24 and val == [] and meta["contamination_gate"]["skipped"]
    with pytest.raises(SystemExit, match="placeholders"):
        step5_training.sft.prepare("step5_training/configs/sft.yaml")
    with pytest.raises(SystemExit, match="placeholders"):
        step5_training.dpo.prepare("step5_training/configs/dpo.yaml")
