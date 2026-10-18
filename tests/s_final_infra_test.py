"""Session S: final-run infra. PRE-CHECKS block in training data, dev eval and the proxy
(byte-identical text), final A/B configs, launch scripts. No network, no GPU."""

import json
import subprocess
from pathlib import Path

import pytest
import yaml

from step7_serving.prechecks import HEADER, SYSTEM_NOTE, apply_prechecks, apply_prechecks_with_result

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "data" / "sft" / "gold_train.jsonl"
TRAIN_CASES = ROOT / "data" / "train" / "cases.jsonl"
SERVING_SCHEMA = ROOT / "step0_rules" / "schema" / "v1_serving.json"
WINNERS = ["distill_floor_sol", "distill_reject_sol", "distill_arbitrate_splice", "distill_arbitrate_plus_twins"]

needs_data = pytest.mark.skipif(not (GOLD.exists() and TRAIN_CASES.exists()), reason="data/ not generated")


def _rows(path, n):
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            out.append(json.loads(line))
            if len(out) == n:
                break
    return out


def _packet(case_id):
    with open(TRAIN_CASES, encoding="utf-8") as f:
        for line in f:
            c = json.loads(line)
            if c["case_id"] == case_id:
                return c["packet"]
    raise KeyError(case_id)


# ---------------------------------------------------------------- apply_prechecks
@needs_data
def test_apply_prechecks_adds_block_after_packet_and_note_to_system():
    row = _rows(GOLD, 1)[0]
    before = json.loads(json.dumps(row["messages"]))
    new = apply_prechecks(row["messages"])
    assert row["messages"] == before                       # input not mutated
    assert [m["role"] for m in new] == ["system", "user", "assistant"]
    assert new[0]["content"] == before[0]["content"] + "\n\n" + SYSTEM_NOTE
    user = new[1]["content"]
    assert user.startswith(before[1]["content"].rstrip("\n") + "\n\n" + HEADER)
    assert user.index("</packet>") < user.index(HEADER)     # block is outside the packet
    assert "- As-of date: " in user and "- Proof-of-address date: " in user
    assert new[2] == before[2]                             # assistant target unchanged
    assert apply_prechecks(new) == new                     # idempotent


def test_apply_prechecks_without_system_prepends_note_and_skips_content_parts():
    new, res = apply_prechecks_with_result([{"role": "user", "content": "As-of date: 2026-02-23\nno packet tags"}])
    assert res is not None and res["as_of"].isoformat() == "2026-02-23"
    assert new[0] == {"role": "system", "content": SYSTEM_NOTE}
    assert HEADER in new[1]["content"]
    parts = [{"role": "user", "content": [{"type": "text", "text": "x"}]}]
    assert apply_prechecks_with_result(parts) == (parts, None)


# ---------------------------------------------------------------- byte-identity
@needs_data
def test_training_eval_and_proxy_prompts_are_byte_identical(tmp_path, monkeypatch):
    from step2_benchmarking.run_endpoint import RequestBuilder
    from step4_distillation.add_prechecks import add_prechecks

    out = tmp_path / "gold_pc.jsonl"
    add_prechecks(GOLD, out, limit=3)
    pc_rows = _rows(out, 3)
    rb = RequestBuilder("m", prompt="student_short", schema=str(SERVING_SCHEMA), prechecks=True)
    for r in pc_rows:
        assert rb.payload(_packet(r["case_id"]))["messages"] == r["messages"][:2]

    # the proxy with ZORBE_PRECHECKS=1 sends the same messages for a bare packet
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from step7_serving.proxy import ProxyConfig, create_app
    from tests.i_proxy_test import MockUpstream

    monkeypatch.setenv("PROXY_API_KEYS", "tok")
    monkeypatch.setenv("ZORBE_PRECHECKS", "1")
    up = MockUpstream("{}")
    app = create_app(ProxyConfig.load(ROOT / "step7_serving" / "proxy_config.example.yaml",
                                      upstream_model="m", log_path=str(tmp_path / "p.jsonl")), upstream=up)
    r = pc_rows[0]
    resp = TestClient(app).post("/v1/chat/completions", headers={"Authorization": "Bearer tok"},
                                json={"messages": [{"role": "user", "content": _packet(r["case_id"])}]})
    assert resp.headers["x-kyc-prechecks"] == "1"
    assert up.payloads[0]["messages"] == r["messages"][:2]


def test_proxy_prechecks_default_off(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from step7_serving.proxy import ProxyConfig, create_app
    from tests.i_proxy_test import MockUpstream

    monkeypatch.setenv("PROXY_API_KEYS", "tok")
    monkeypatch.delenv("ZORBE_PRECHECKS", raising=False)
    up = MockUpstream("{}")
    app = create_app(ProxyConfig.load(ROOT / "step7_serving" / "proxy_config.example.yaml",
                                      upstream_model="m", log_path=str(tmp_path / "p.jsonl")), upstream=up)
    resp = TestClient(app).post("/v1/chat/completions", headers={"Authorization": "Bearer tok"},
                                json={"messages": [{"role": "user", "content": "As-of date: 2026-01-01"}]})
    assert resp.headers["x-kyc-prechecks"] == "0"
    assert all(HEADER not in m["content"] and SYSTEM_NOTE not in m["content"] for m in up.payloads[0]["messages"])


def test_run_endpoint_prechecks_flag():
    from step2_benchmarking.run_endpoint import RequestBuilder, parse_args

    assert parse_args(["--cases", "c", "--out", "o", "--base-url", "u", "--model", "m", "--prechecks"]).prechecks
    assert not parse_args(["--cases", "c", "--out", "o", "--base-url", "u", "--model", "m"]).prechecks
    rb = RequestBuilder("m", prompt="student_short", schema=str(SERVING_SCHEMA))
    assert HEADER not in rb.payload("As-of date: 2026-01-01")["messages"][1]["content"]
    assert rb.provenance()["prechecks"] is False


# ---------------------------------------------------------------- add_prechecks
def test_add_prechecks_refuses_eval_ids(tmp_path):
    from step4_distillation.add_prechecks import add_prechecks

    p = tmp_path / "x.jsonl"
    p.write_text(json.dumps({"id": "a", "case_id": "eid-1", "messages": [
        {"role": "system", "content": "s"}, {"role": "user", "content": "<packet>\nx\n</packet>"},
        {"role": "assistant", "content": "{}"}]}) + "\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="CONTAMINATION"):
        add_prechecks(p, tmp_path / "y.jsonl")


@needs_data
def test_add_prechecks_stats(tmp_path):
    from step4_distillation.add_prechecks import add_prechecks

    out = tmp_path / "o.jsonl"
    s = add_prechecks(GOLD, out, limit=5)
    assert s["rows"] == s["blocks_added"] == 5 and s["assistant_targets_changed"] == 0
    assert set(s["nd_counts"]) == {"as_of", "mrz", "expiry", "poa_date", "integrity"}
    assert json.loads(Path(str(out) + ".stats.json").read_text(encoding="utf-8"))["rows"] == 5


@needs_data
@pytest.mark.parametrize("name", WINNERS + ["gold_train", "gold_train_solnarr"])
def test_pc_files_match_their_source(name):
    src, pc = ROOT / "data" / "sft" / f"{name}.jsonl", ROOT / "data" / "sft" / f"{name}_pc.jsonl"
    if not pc.exists():
        pytest.skip("run python -m step4_distillation.add_prechecks --all")
    a, b = _rows(src, 20), _rows(pc, 20)
    for x, y in zip(a, b):
        assert y["messages"] == apply_prechecks(x["messages"])
        assert {k: v for k, v in y.items() if k != "messages"} == {k: v for k, v in x.items() if k != "messages"}


# ---------------------------------------------------------------- configs + scripts
def _cfg(name):
    from step5_training.common import SFTCfg, load_config

    return load_config(ROOT / "step5_training" / "configs" / name, SFTCfg)


@pytest.mark.parametrize("x", ["A", "B"])
def test_final_configs(x):
    from step5_training.common import placeholders

    suf = "_pc" if x == "B" else ""
    s3, s4 = _cfg(f"final_{x}_s3.yaml"), _cfg(f"final_{x}_s4.yaml")
    ref = _cfg("distill_4b_floor.yaml")
    assert s3.base_model == "/vol/ckpt/merged/adapter-qwen35-4b"
    assert s3.train_file == f"data/sft/PLACEHOLDER_WINNER{suf}.jsonl" and placeholders(s3) == ["train_file"]
    assert s4.base_model == f"/vol/ckpt/merged/final-{x}-s3" and s4.train_file == f"data/sft/gold_train_solnarr{suf}.jsonl"
    assert (s3.run_name, s4.run_name) == (f"final-{x}-s3", f"final-{x}-s4")
    assert (s3.epochs, s3.learning_rate, s4.epochs, s4.learning_rate) == (2, 2e-4, 1, 1e-4)
    for c in (s3, s4):  # everything else as distill_4b_*
        assert (c.lora, c.seed, c.gpu, c.batch_size, c.grad_accum, c.max_seq_len, c.backend) == \
               (ref.lora, ref.seed, ref.gpu, ref.batch_size, ref.grad_accum, ref.max_seq_len, ref.backend)
    for w in WINNERS:  # the launcher's fill-in works for every candidate
        filled = yaml.safe_load((ROOT / "step5_training" / "configs" / f"final_{x}_s3.yaml")
                                .read_text(encoding="utf-8").replace("PLACEHOLDER_WINNER", w))
        assert filled["train_file"] == f"data/sft/{w}{suf}.jsonl"


@pytest.mark.parametrize("script", ["launch_final.sh", "eval_on_dev.sh", "eval_frozen.sh", "final_lib.sh"])
def test_scripts_parse(script):
    try:
        r = subprocess.run(["bash", "-n", str(ROOT / "step5_training" / script)], capture_output=True, text=True)
    except OSError:
        pytest.skip("bash not available")
    assert r.returncode == 0, r.stderr


def test_launch_final_rejects_unknown_winner():
    try:
        r = subprocess.run(["bash", "step5_training/launch_final.sh", "nope"], cwd=ROOT, capture_output=True, text=True)
    except OSError:
        pytest.skip("bash not available")
    assert r.returncode == 2 and "usage" in r.stdout
