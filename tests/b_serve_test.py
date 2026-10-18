"""Offline checks for Session B's serving code (no Modal calls, no GPU)."""
import json

import pytest

modal = pytest.importorskip("modal")

import step7_serving.modal_vllm as mv  # noqa: E402
from step7_serving import setup_secrets  # noqa: E402
from step7_serving.smoke import TOY_SCHEMA, pct  # noqa: E402


def test_vllm_cmd_has_auth_thinking_off_and_no_mm():
    cmd = mv.vllm_cmd("tok")
    assert cmd[:3] == ["vllm", "serve", mv.MODEL]
    assert cmd[cmd.index("--api-key") + 1] == "tok"
    assert json.loads(cmd[cmd.index("--default-chat-template-kwargs") + 1]) == {"enable_thinking": False}
    assert json.loads(cmd[cmd.index("--limit-mm-per-prompt") + 1]) == {"image": 0, "video": 0}
    assert cmd[cmd.index("--served-model-name") + 1] == mv.SERVED


def test_defaults_scale_to_zero():
    assert mv.MODEL == "Qwen/Qwen3.5-0.8B"
    assert mv.MIN == 0  # never a warm GPU unless asked for explicitly


def test_baked_env_round_trips_settings():
    # containers re-import the module; the image env must reproduce the deploy-time values
    assert mv._BAKED["ZORBE_SERVE_MODEL"] == mv.MODEL
    assert mv._BAKED["ZORBE_SERVE_APP"] == mv.APP
    assert mv._BAKED["ZORBE_SERVE_MIN"] == str(mv.MIN)


def test_pct():
    xs = list(range(1, 21))
    assert pct(xs, 0.5) == 10.5
    assert pct(xs, 0.95) == pytest.approx(19.05, abs=0.1)


def test_toy_schema_is_restrictive():
    import jsonschema

    jsonschema.validate({"color": "teal", "count": 3, "code": "ZK-0042"}, TOY_SCHEMA)
    for bad in ({"color": "red", "count": 3, "code": "ZK-0042"},
                {"color": "teal", "count": 42, "code": "ZK-0042"},
                {"color": "teal", "count": 3, "code": "42"}):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(bad, TOY_SCHEMA)


def test_setup_secrets_reads_env_and_adds_tokens(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("HF_TOKEN=abc\n# comment\nOTHER='x'", encoding="utf-8")
    monkeypatch.setattr(setup_secrets, "ENV", env)
    d = setup_secrets.read_env()
    assert d == {"HF_TOKEN": "abc", "OTHER": "x"}
    added = setup_secrets.ensure_tokens(d)
    assert added == ["VLLM_API_KEY", "PROXY_API_KEY"]
    again = setup_secrets.read_env()
    assert again["VLLM_API_KEY"].startswith("zk-") and again["VLLM_API_KEY"] != again["PROXY_API_KEY"]
    assert setup_secrets.ensure_tokens(again) == []  # idempotent
