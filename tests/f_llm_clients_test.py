"""Session F: shared/frontier_api/clients.py. Mocks only; no network, no keys."""

import json
import sys
import types

import pytest

from shared.frontier_api.clients import (
    ENV_KEYS, AnthropicProvider, ContaminationError, CostLedger, DiskCache, GeminiProvider, LLMClient,
    LLMResponse, OpenAIProvider, PriceTable, RateLimiter, RetryableError, Usage, is_retryable,
    make_request, schema_instance, validate_output, with_retries,
)

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["decision", "risk_tier", "verified"],
    "properties": {
        "decision": {"type": "string", "enum": ["approve", "reject", "escalate"]},
        "risk_tier": {"type": "string", "enum": ["low", "medium", "high"]},
        "verified": {"type": "boolean"},
    },
}


def req(provider="openai", model="gpt-6-astra", user="packet text", **kw):
    return make_request(provider, model, user=user, system="sys", json_schema=SCHEMA, **kw)


@pytest.fixture
def client(tmp_path):
    return LLMClient(mock=True, cache_dir=tmp_path / "cache", sleep=lambda s: None)


# --- request builders / parsers (pure) ------------------------------------

def test_openai_build_and_parse():
    kw = OpenAIProvider().build(req(reasoning_effort="low"))
    assert kw["messages"][0] == {"role": "system", "content": "sys"}
    assert kw["response_format"]["type"] == "json_schema"
    assert kw["response_format"]["json_schema"]["strict"] is True
    assert kw["reasoning_effort"] == "low" and "temperature" not in kw
    raw = {"id": "c1", "choices": [{"message": {"content": '{"a":1}'}, "finish_reason": "stop"}],
           "usage": {"prompt_tokens": 100, "completion_tokens": 50,
                     "completion_tokens_details": {"reasoning_tokens": 20},
                     "prompt_tokens_details": {"cached_tokens": 10}}}
    text, u, stop, rid = OpenAIProvider().parse(raw)
    assert text == '{"a":1}' and stop == "stop" and rid == "c1"
    assert (u.input_tokens, u.output_tokens, u.reasoning_tokens, u.cached_input_tokens) == (100, 50, 20, 10)


def test_openai_refusal():
    raw = {"choices": [{"message": {"content": None, "refusal": "no"}, "finish_reason": "stop"}]}
    text, _, stop, _ = OpenAIProvider().parse(raw)
    assert text == "" and stop == "refusal"


def test_anthropic_build_and_parse():
    kw = AnthropicProvider().build(req("anthropic", "claude-opus-5-5", reasoning_effort="low"))
    assert kw["system"] == "sys"
    assert kw["output_config"] == {"format": {"type": "json_schema", "schema": SCHEMA}, "effort": "low"}
    assert "temperature" not in kw and "thinking" not in kw
    raw = {"id": "m1", "stop_reason": "end_turn",
           "content": [{"type": "thinking", "thinking": ""}, {"type": "text", "text": "{}"}],
           "usage": {"input_tokens": 10, "output_tokens": 7, "cache_read_input_tokens": 90,
                     "cache_creation_input_tokens": 0}}
    text, u, stop, rid = AnthropicProvider().parse(raw)
    assert text == "{}" and u.input_tokens == 100 and u.cached_input_tokens == 90 and u.output_tokens == 7


def test_gemini_build_and_parse():
    r = req("gemini", "gemini-4-argon")
    r.messages.append({"role": "assistant", "content": "prev"})
    kw = GeminiProvider().build(r)
    assert [c["role"] for c in kw["contents"]] == ["user", "model"]
    cfg = kw["config"]
    assert cfg["response_mime_type"] == "application/json" and cfg["response_json_schema"] == SCHEMA
    assert cfg["system_instruction"] == "sys" and cfg["thinking_config"] == {"thinking_level": "low"}
    raw = {"response_id": "g1", "candidates": [{"finish_reason": "STOP", "content": {"parts": [
        {"text": "thinking...", "thought": True}, {"text": '{"x":'}, {"text": "1}"}]}}],
        "usage_metadata": {"prompt_token_count": 40, "candidates_token_count": 5,
                           "thoughts_token_count": 15}}
    text, u, stop, rid = GeminiProvider().parse(raw)
    assert text == '{"x":1}' and u.output_tokens == 20 and u.reasoning_tokens == 15 and rid == "g1"


def test_request_validation():
    with pytest.raises(ValueError):
        make_request("cohere", "m", user="x")
    with pytest.raises(ValueError):
        make_request("openai", "m", user="x", purpose="training")


def test_cache_key_ignores_metadata_and_purpose():
    a = req(metadata={"case_id": 1}, purpose="baseline")
    b = req(metadata={"case_id": 2}, purpose="judge")
    assert a.cache_key() == b.cache_key()
    assert req(max_tokens=10).cache_key() != req(max_tokens=11).cache_key()
    assert req(user="a").cache_key() != req(user="b").cache_key()


# --- validation / pricing ---------------------------------------------------

def test_validate_output():
    assert validate_output("free text", None) == (None, None, None)
    p, ok, err = validate_output('{"decision":"approve","risk_tier":"low","verified":true}', SCHEMA)
    assert ok and err is None and p["decision"] == "approve"
    _, ok, err = validate_output("```json\n{}\n```", SCHEMA)
    assert ok is False and err.startswith("json")
    _, ok, err = validate_output('{"decision":"maybe","risk_tier":"low","verified":true}', SCHEMA)
    assert ok is False and err.startswith("schema")


def test_schema_instance_is_valid():
    assert validate_output(json.dumps(schema_instance(SCHEMA)), SCHEMA)[1] is True
    nested = {"type": "object", "required": ["hits"], "properties": {"hits": {
        "type": "array", "minItems": 2, "items": {"type": ["string", "null"], "minLength": 3}}}}
    assert validate_output(json.dumps(schema_instance(nested)), nested)[1] is True


def test_prices():
    pt = PriceTable.load()
    u = Usage(input_tokens=1_000_000, output_tokens=1_000_000)
    assert pt.cost("claude-opus-5-5", u) == pytest.approx(24.0)
    assert pt.cost("claude-opus-5-5", u, batch=True) == pytest.approx(12.0)
    assert pt.cost("gpt-6-astra-2026-10-01", u) == pytest.approx(60.0)  # prefix match
    assert pt.cost("unknown-model", u) is None
    cached = Usage(input_tokens=1_000_000, cached_input_tokens=1_000_000)
    assert pt.cost("claude-opus-5-5", cached) == pytest.approx(0.20)


def test_ledger_counts_cache_hits_as_free():
    led = CostLedger()
    led.record(LLMResponse("k", "openai", "m", "", usage=Usage(10, 5), cost_usd=1.0))
    led.record(LLMResponse("k", "openai", "m", "", usage=Usage(10, 5), cost_usd=1.0, cached=True))
    led.record(LLMResponse("k", "openai", "m", "", cost_usd=None))
    r = led.summary()["by_model"]["m"]
    assert led.total_usd() == 1.0 and r["calls"] == 3 and r["cache_hits"] == 1
    assert r["saved_by_cache_usd"] == 1.0 and r["unpriced_calls"] == 1 and r["input_tokens"] == 10


# --- retry / rate limit -------------------------------------------------------

class HTTPErr(Exception):
    def __init__(self, status):
        self.status_code = status


def test_is_retryable():
    assert is_retryable(RetryableError())
    assert is_retryable(HTTPErr(429)) and is_retryable(HTTPErr(503)) and is_retryable(HTTPErr(529))
    assert not is_retryable(HTTPErr(400)) and not is_retryable(HTTPErr(401))
    assert is_retryable(type("APITimeoutError", (Exception,), {})())
    assert not is_retryable(ValueError("bad"))


def test_with_retries_backs_off_then_succeeds():
    calls, sleeps = [], []

    def fn():
        calls.append(1)
        if len(calls) < 3:
            raise HTTPErr(429)
        return "ok"

    assert with_retries(fn, sleep=sleeps.append, base_delay=1.0) == "ok"
    assert len(calls) == 3 and len(sleeps) == 2 and sleeps[1] > sleeps[0] * 0.9


def test_with_retries_gives_up_and_does_not_retry_fatal():
    sleeps = []
    with pytest.raises(HTTPErr):
        with_retries(lambda: (_ for _ in ()).throw(HTTPErr(500)), max_attempts=3, sleep=sleeps.append)
    assert len(sleeps) == 2
    sleeps.clear()
    with pytest.raises(HTTPErr):
        with_retries(lambda: (_ for _ in ()).throw(HTTPErr(400)), sleep=sleeps.append)
    assert sleeps == []


def test_retry_after_honored():
    sleeps = []
    n = []

    def fn():
        n.append(1)
        if len(n) == 1:
            raise RetryableError(retry_after=7.0)
        return 1

    with_retries(fn, sleep=sleeps.append)
    assert sleeps == [7.0]


def test_rate_limiter():
    t = [0.0]
    sleeps = []

    def sleep(s):
        sleeps.append(s)
        t[0] += s

    rl = RateLimiter(rpm=60, burst=2, clock=lambda: t[0], sleep=sleep)
    for _ in range(5):
        rl.acquire()
    # burst of 2 is free, then 1/s for the remaining 3
    assert sum(sleeps) == pytest.approx(3.0, abs=1e-6)


# --- client end to end (mock) -------------------------------------------------

def test_mock_complete_valid_and_cached(client):
    r1 = client.complete(req())
    assert r1.schema_valid is True and r1.parsed["decision"] == "approve" and not r1.cached
    assert r1.cost_usd > 0  # mock tokens priced at the named model's rate (dry-run estimate)
    r2 = client.complete(req(metadata={"case_id": "c9"}))
    assert r2.cached and r2.text == r1.text and r2.metadata == {"case_id": "c9"}
    assert client._mock_provider.calls == 1
    s = client.ledger.summary()["by_model"]["gpt-6-astra"]
    assert s["calls"] == 2 and s["cache_hits"] == 1
    assert client.ledger.total_usd() == pytest.approx(r1.cost_usd)


def test_cache_persists_across_clients(tmp_path):
    c1 = LLMClient(mock=True, cache_dir=tmp_path)
    c1.complete(req())
    c2 = LLMClient(mock=True, cache_dir=tmp_path)
    assert c2.complete(req()).cached and c2._mock_provider.calls == 0


def test_cache_corrupt_file_is_a_miss(tmp_path):
    c = DiskCache(tmp_path)
    c.put("ab" + "0" * 62, {"x": 1})
    (tmp_path / "ab" / ("ab" + "0" * 62 + ".json")).write_text("{trunc")
    assert c.get("ab" + "0" * 62) is None


def test_mock_invalid_output_is_returned_not_raised(tmp_path):
    c = LLMClient(mock=True, cache_dir=tmp_path, mock_responder=lambda r: "not json")
    r = c.complete(req())
    assert r.schema_valid is False and r.parse_error.startswith("json") and r.parsed is None


def test_mock_transient_errors_are_retried(tmp_path):
    n = []

    def flaky(r):
        n.append(1)
        if len(n) < 3:
            raise RetryableError("overloaded")
        return {"decision": "escalate", "risk_tier": "high", "verified": False}

    c = LLMClient(mock=True, cache_dir=tmp_path, mock_responder=flaky, sleep=lambda s: None)
    assert c.complete(req()).parsed["decision"] == "escalate" and len(n) == 3


def test_complete_many_preserves_order_and_captures_errors(tmp_path):
    def resp(r):
        u = r.messages[0]["content"]
        if u == "boom":
            raise ValueError("fatal")
        return {"decision": "reject" if u == "b" else "approve", "risk_tier": "low", "verified": True}

    c = LLMClient(mock=True, cache_dir=None, mock_responder=resp)
    out = c.complete_many([req(user="a"), req(user="boom"), req(user="b")], max_workers=3)
    assert [o.parsed and o.parsed["decision"] for o in out] == ["approve", None, "reject"]
    assert out[1].error.startswith("ValueError") and out[1].schema_valid is False


def test_env_flag_enables_mock(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_MOCK", "1")
    assert LLMClient(cache_dir=tmp_path).mock is True


def test_missing_key_errors_cleanly(monkeypatch, tmp_path):
    # Independent of a local .env: disable dotenv loading *before* the client is built
    # (the constructor loads it), and clear every key the client might read.
    monkeypatch.setattr("shared.frontier_api.clients._load_dotenv", lambda: None)
    for keys in ENV_KEYS.values():
        for k in keys:
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("LLM_MOCK", "0")
    # ...and of whether the openai SDK is installed: the key check is what's under test.
    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=lambda **kw: None))
    c = LLMClient(cache_dir=tmp_path, max_attempts=1)
    with pytest.raises(Exception, match="no API key for openai"):
        c.complete(req())


def test_mock_and_real_cache_namespaces_differ(tmp_path):
    LLMClient(mock=True, cache_dir=tmp_path).complete(req())
    files = list(tmp_path.rglob("*.json"))
    assert len(files) == 1 and files[0].name.startswith("mock-")


def test_guard_blocks_teacher_only(tmp_path):
    class Guard:
        def check(self, text):
            if "EVAL" in text:
                raise ContaminationError("overlap")

    c = LLMClient(mock=True, cache_dir=None, guard=Guard())
    with pytest.raises(ContaminationError):
        c.complete(req(user="EVAL case", purpose="teacher"))
    assert c.complete(req(user="EVAL case", purpose="baseline")).schema_valid


# --- built kwargs match the installed SDKs (skipped when an SDK is absent) -----

def test_kwargs_match_sdk_signatures():
    import inspect

    openai = pytest.importorskip("openai")
    anthropic = pytest.importorskip("anthropic")
    types = pytest.importorskip("google.genai.types")
    oa = inspect.signature(openai.resources.chat.Completions.create).parameters
    assert set(OpenAIProvider().build(req())) <= set(oa)
    an = inspect.signature(anthropic.resources.Messages.create).parameters
    assert set(AnthropicProvider().build(req("anthropic", "claude-opus-5-5"))) <= set(an)
    kw = GeminiProvider().build(req("gemini", "gemini-4-argon"))
    types.GenerateContentConfig(**kw["config"])  # pydantic raises on unknown/invalid fields
    [types.Content(**c) for c in kw["contents"]]
