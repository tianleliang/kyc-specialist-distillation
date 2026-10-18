"""Session I: step7_serving/proxy.py against a mock upstream. No network, no GPU."""

import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from step7_serving.proxy import ProxyConfig, UpstreamError, build_fallback, check_output, create_app  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
from tests.l_v1_cases import V1_SERVING, v1_cases  # noqa: E402

# the example proxy config serves the v1 serving schema (Session L)
SCHEMA = json.loads(V1_SERVING.read_text(encoding="utf-8"))
TOKEN = "test-token-123"


def draft_case(i=0):
    return json.loads(json.dumps(v1_cases()[i]))


class MockUpstream:
    """Returns scripted outputs in order (str content, dict raw response, or an exception)."""

    def __init__(self, *outputs):
        self.outputs = list(outputs)
        self.payloads = []

    async def __call__(self, payload):
        self.payloads.append(payload)
        out = self.outputs.pop(0) if len(self.outputs) > 1 else self.outputs[0]
        if isinstance(out, Exception):
            raise out
        if isinstance(out, dict) and "choices" in out:
            return out
        content = out if isinstance(out, str) else json.dumps(out)
        return {"id": "up-1", "object": "chat.completion", "created": 1, "model": "upstream-x",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": content,
                                                     "reasoning_content": "hidden"},
                             "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}}


@pytest.fixture
def make(monkeypatch, tmp_path):
    monkeypatch.setenv("PROXY_API_KEYS", f"other-key, {TOKEN}")

    def _make(*outputs, **cfg):
        up = MockUpstream(*outputs)
        cfg.setdefault("upstream_model", "merged-student")
        cfg.setdefault("log_path", str(tmp_path / "proxy.jsonl"))
        app = create_app(ProxyConfig.load(ROOT / "step7_serving" / "proxy_config.example.yaml", **cfg), upstream=up)
        return TestClient(app), up

    return _make


AUTH = {"Authorization": f"Bearer {TOKEN}"}


def test_bare_packet_gets_prompt_schema_and_valid_json(make, tmp_path):
    case = draft_case()
    client, up = make(case["expected"])
    r = client.post("/v1/chat/completions", headers=AUTH,
                    json={"model": "zorbe-kyc", "messages": [{"role": "user", "content": case["packet"]}]})
    assert r.status_code == 200
    body = r.json()
    out = json.loads(body["choices"][0]["message"]["content"])
    assert out == case["expected"]
    assert "reasoning_content" not in body["choices"][0]["message"]
    assert body["model"] == "zorbe-kyc" and body["usage"]["completion_tokens"] == 50
    assert r.headers["x-kyc-fallback"] == "0" and r.headers["x-kyc-schema-valid"] == "1"
    assert r.headers["x-kyc-prompt-injected"] == "1" and r.headers["x-kyc-response-format-injected"] == "1"
    assert float(r.headers["x-kyc-latency-ms"]) >= 0
    # what the upstream saw
    p = up.payloads[0]
    # D21b: the trained model's prompt is student_short (policy learned in training, not sent per call)
    assert p["messages"][0]["role"] == "system" and "KYC onboarding analyst" in p["messages"][0]["content"]
    assert p["messages"][1]["content"].startswith("<packet>\n") and case["packet"] in p["messages"][1]["content"]
    assert p["response_format"]["type"] == "json_schema" and p["response_format"]["json_schema"]["schema"] == SCHEMA
    assert p["chat_template_kwargs"] == {"enable_thinking": False}
    assert p["model"] == "merged-student" and p["stream"] is False and p["temperature"] == 0.0
    # log line: latency, no packet text
    rec = json.loads((tmp_path / "proxy.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert rec["event"] == "completion" and rec["latency_ms"] >= 0 and rec["fallback"] is None
    assert case["packet"][:40] not in (tmp_path / "proxy.jsonl").read_text(encoding="utf-8")


def test_caller_system_prompt_and_format_are_kept_but_thinking_forced_off(make):
    case = draft_case()
    client, up = make(case["expected"])
    rf = {"type": "json_schema", "json_schema": {"name": "x", "schema": SCHEMA, "strict": True}}
    r = client.post("/v1/chat/completions", headers=AUTH, json={
        "model": "anything", "temperature": 0.3, "max_tokens": 99999, "response_format": rf,
        "chat_template_kwargs": {"enable_thinking": True, "foo": 1},
        "messages": [{"role": "system", "content": "CALLER SYSTEM"}, {"role": "user", "content": case["packet"]}]})
    assert r.status_code == 200 and r.headers["x-kyc-prompt-injected"] == "0"
    p = up.payloads[0]
    assert p["messages"][0]["content"] == "CALLER SYSTEM" and p["messages"][1]["content"] == case["packet"]
    assert p["response_format"] == rf and p["temperature"] == 0.3
    assert p["chat_template_kwargs"] == {"enable_thinking": False, "foo": 1}
    assert p["max_tokens"] == 4096  # capped


def test_content_parts_are_accepted(make):
    case = draft_case()
    client, up = make(case["expected"])
    r = client.post("/v1/chat/completions", headers=AUTH, json={"messages": [
        {"role": "user", "content": [{"type": "text", "text": case["packet"]}]}]})
    assert r.status_code == 200 and case["packet"] in up.payloads[0]["messages"][1]["content"]


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong"}, {"Authorization": TOKEN},
                                     {"Authorization": "Basic " + TOKEN}, {"Authorization": "Bearer "}])
def test_missing_or_wrong_token_is_401(make, headers):
    client, up = make({})
    r = client.post("/v1/chat/completions", headers=headers, json={"messages": [{"role": "user", "content": "x"}]})
    assert r.status_code == 401 and r.json()["error"]["type"] == "authentication_error"
    assert up.payloads == []
    assert client.get("/v1/models", headers=headers).status_code == 401


def test_health_needs_no_auth_and_models_lists_served_name(make):
    client, _ = make({})
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/v1/models", headers=AUTH).json()["data"][0]["id"] == "zorbe-kyc"


def test_refuses_to_start_without_keys(monkeypatch):
    monkeypatch.delenv("PROXY_API_KEYS", raising=False)
    with pytest.raises(RuntimeError, match="PROXY_API_KEYS"):
        create_app(ProxyConfig.load(ROOT / "step7_serving" / "proxy_config.example.yaml"), upstream=MockUpstream({}))


def test_invalid_then_valid_retries_once(make):
    case = draft_case()
    client, up = make("not json at all", case["expected"])
    r = client.post("/v1/chat/completions", headers=AUTH, json={"messages": [{"role": "user", "content": case["packet"]}]})
    assert r.status_code == 200 and r.headers["x-kyc-attempts"] == "2" and r.headers["x-kyc-fallback"] == "0"
    assert json.loads(r.json()["choices"][0]["message"]["content"]) == case["expected"]
    assert r.json()["usage"]["prompt_tokens"] == 200  # usage summed over both attempts (honest cost)


def test_invalid_twice_gives_flagged_escalate_fallback(make, tmp_path):
    bad = dict(draft_case()["expected"], decision="maybe")
    client, up = make(bad)
    r = client.post("/v1/chat/completions", headers=AUTH, json={"messages": [{"role": "user", "content": "pkt"}]})
    assert r.status_code == 200 and len(up.payloads) == 2
    assert r.headers["x-kyc-fallback"] == "invalid_output" and r.headers["x-kyc-schema-valid"] == "1"
    out = json.loads(r.json()["choices"][0]["message"]["content"])
    assert out["decision"] == "escalate" and check_output(json.dumps(out), _validator(), False)[0]
    rec = json.loads((tmp_path / "proxy.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert rec["fallback"] == "invalid_output" and rec["last_error"].startswith("schema")


def test_upstream_errors(make):
    case = draft_case()
    client, up = make(UpstreamError(503, "overloaded"), case["expected"])
    r = client.post("/v1/chat/completions", headers=AUTH, json={"n": None, "messages": [{"role": "user", "content": "p"}]})
    assert r.status_code == 200 and r.headers["x-kyc-attempts"] == "2" and r.headers["x-kyc-fallback"] == "0"

    client, up = make(UpstreamError(None, "connect timeout"))
    r = client.post("/v1/chat/completions", headers=AUTH, json={"messages": [{"role": "user", "content": "p"}]})
    assert r.status_code == 200 and r.headers["x-kyc-fallback"] == "upstream_error"
    assert json.loads(r.json()["choices"][0]["message"]["content"])["decision"] == "escalate"

    client, up = make(UpstreamError(None, "down"), fallback_on_upstream_error=False)
    r = client.post("/v1/chat/completions", headers=AUTH, json={"messages": [{"role": "user", "content": "p"}]})
    assert r.status_code == 502 and r.json()["error"]["type"] == "upstream_error"

    other = {"type": "object", "required": ["a"], "properties": {"a": {"type": "string"}}}
    client, up = make(UpstreamError(None, "down"))
    r = client.post("/v1/chat/completions", headers=AUTH, json={
        "response_format": {"type": "json_schema", "json_schema": {"name": "o", "schema": other}},
        "messages": [{"role": "user", "content": "p"}]})
    assert r.status_code == 502  # no fallback exists for a caller's own schema

    client, up = make(UpstreamError(400, "context too long"))
    r = client.post("/v1/chat/completions", headers=AUTH, json={"messages": [{"role": "user", "content": "p"}]})
    assert r.status_code == 400 and len(up.payloads) == 1  # caller errors pass through, no retry


def test_code_fence_is_repaired_and_flagged(make):
    case = draft_case()
    client, _ = make("```json\n" + json.dumps(case["expected"]) + "\n```")
    r = client.post("/v1/chat/completions", headers=AUTH, json={"messages": [{"role": "user", "content": "p"}]})
    assert r.headers["x-kyc-repaired"] == "1" and r.headers["x-kyc-attempts"] == "1"
    assert json.loads(r.json()["choices"][0]["message"]["content"]) == case["expected"]
    client, _ = make("```json\n" + json.dumps(case["expected"]) + "\n```", repair_fences=False)
    r = client.post("/v1/chat/completions", headers=AUTH, json={"messages": [{"role": "user", "content": "p"}]})
    assert r.headers["x-kyc-fallback"] == "invalid_output"


def test_streaming_is_buffered_sse(make):
    case = draft_case()
    client, up = make(case["expected"])
    with client.stream("POST", "/v1/chat/completions", headers=AUTH,
                       json={"stream": True, "messages": [{"role": "user", "content": case["packet"]}]}) as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        assert r.headers["x-kyc-stream"] == "buffered"
        lines = [l for l in r.iter_lines() if l.startswith("data: ")]
    assert lines[-1] == "data: [DONE]"
    chunks = [json.loads(l[6:]) for l in lines[:-1]]
    content = "".join(c["choices"][0]["delta"].get("content", "") for c in chunks)
    assert json.loads(content) == case["expected"]
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"
    assert up.payloads[0]["stream"] is False  # upstream is always called non-streaming


@pytest.mark.parametrize("body", [{"messages": []}, {"messages": "x"}, {"n": 2, "messages": [{"role": "user", "content": "x"}]},
                                  {"tools": [{"type": "function"}], "messages": [{"role": "user", "content": "x"}]},
                                  {"max_tokens": "lots", "messages": [{"role": "user", "content": "x"}]}])
def test_bad_requests_are_400(make, body):
    client, up = make({})
    r = client.post("/v1/chat/completions", headers=AUTH, json=body)
    assert r.status_code == 400 and up.payloads == []


def test_build_fallback_auto_escalates_and_validates():
    tiny = {"type": "object", "additionalProperties": False, "required": ["decision", "n"],
            "properties": {"decision": {"enum": ["approve", "escalate"]}, "n": {"type": "integer", "minimum": 1}}}
    assert build_fallback(tiny, {}) == {"decision": "escalate", "n": 1}
    with pytest.raises(ValueError, match="does not escalate"):
        build_fallback({"type": "object", "required": ["x"], "properties": {"x": {"type": "string"}}}, {})
    with pytest.raises(Exception):
        build_fallback(tiny, {"n": 0})  # override breaks the schema -> fails at startup


def _validator():
    import jsonschema
    return jsonschema.validators.validator_for(SCHEMA)(SCHEMA)
