"""One wrapper for OpenAI, Anthropic and Gemini (plus a mock provider).

    from shared.frontier_api.clients import LLMClient, make_request
    client = LLMClient()                       # LLM_MOCK=1 in the env forces mock mode
    req = make_request("anthropic", "claude-opus-5-5", user=packet, system=prompt,
                       json_schema=schema, max_tokens=2048, reasoning_effort="low")
    resp = client.complete(req)                # resp.parsed, resp.schema_valid, resp.cost_usd
    print(client.ledger.summary())

What it does:
- Structured output via JSON Schema on all three providers (OpenAI `response_format`,
  Anthropic `output_config.format`, Gemini `response_json_schema`). The response is
  parsed and validated locally; invalid output is *returned*, not raised, because the
  eval harness needs it to score schema validity.
- Retry with exponential backoff + jitter on 408/409/429/5xx, timeouts and connection
  errors. SDK-internal retries are off so this is the single retry policy.
- Per-provider token-bucket rate limiting (requests per minute).
- Token and cost accounting from `shared/frontier_api/prices.yaml`; batch calls are priced at the discount.
- On-disk cache keyed by a hash of everything that affects the output, so reruns are free.
- Keys come from the environment (`.env` is loaded if python-dotenv is present). Keys are
  never logged or stored.
- Mock mode: no network, deterministic schema-valid output. Tests use only this.
- Optional contamination guard: requests with purpose="teacher" are refused if their text
  overlaps a frozen eval set (see step6_evaluation/split_guard.py: EvalGuard).

Request builders and response parsers are pure functions of dicts, so they are shared
with shared/frontier_api/batch.py and tested without any SDK or key.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml

log = logging.getLogger(__name__)

PROVIDERS = ("openai", "anthropic", "gemini", "mock")
PURPOSES = ("baseline", "teacher", "judge", "other")
DEFAULT_PRICES = Path(__file__).with_name("prices.yaml")
DEFAULT_CACHE_DIR = Path("outputs/llm_cache")  # outputs/ is gitignored
ENV_KEYS = {
    "openai": ("OPENAI_API_KEY",),
    "anthropic": ("ANTHROPIC_API_KEY",),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
}


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class LLMRequest:
    provider: str
    model: str
    messages: list[dict]                       # [{"role": "user"|"assistant", "content": str}]
    system: str | None = None
    json_schema: dict | None = None
    schema_name: str = "kyc_decision"
    max_tokens: int = 2048
    temperature: float | None = None           # None = provider default (some models reject it)
    reasoning_effort: str | None = "low"       # low | medium | high | None (omit)
    purpose: str = "baseline"                  # baseline | teacher | judge | other
    extra: dict = field(default_factory=dict)  # provider-specific kwargs, passed through
    metadata: dict = field(default_factory=dict)  # never sent, never hashed (e.g. case_id)

    def __post_init__(self) -> None:
        if self.provider not in PROVIDERS:
            raise ValueError(f"unknown provider {self.provider!r}")
        if self.purpose not in PURPOSES:
            raise ValueError(f"unknown purpose {self.purpose!r}")
        for m in self.messages:
            if m.get("role") not in ("user", "assistant"):
                raise ValueError("messages may only hold user/assistant turns; use `system`")

    def cache_key(self) -> str:
        """Hash of every field that can change the output. purpose/metadata are excluded."""
        payload = {
            "provider": self.provider, "model": self.model, "messages": self.messages,
            "system": self.system, "json_schema": self.json_schema,
            "schema_name": self.schema_name, "max_tokens": self.max_tokens,
            "temperature": self.temperature, "reasoning_effort": self.reasoning_effort,
            "extra": self.extra,
        }
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def all_text(self) -> str:
        return "\n".join([self.system or ""] + [m["content"] for m in self.messages])

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "LLMRequest":
        return cls(**d)


def make_request(provider: str, model: str, user: str, **kw: Any) -> LLMRequest:
    """Single-turn convenience constructor."""
    return LLMRequest(provider=provider, model=model,
                      messages=[{"role": "user", "content": user}], **kw)


@dataclass
class Usage:
    input_tokens: int = 0         # all prompt tokens, including cached ones
    output_tokens: int = 0        # all billed output tokens, including reasoning
    reasoning_tokens: int = 0     # subset of output_tokens, when the provider reports it
    cached_input_tokens: int = 0  # subset of input_tokens


@dataclass
class LLMResponse:
    request_key: str
    provider: str
    model: str
    text: str
    parsed: Any = None
    schema_valid: bool | None = None   # None when no schema was requested
    parse_error: str | None = None
    usage: Usage = field(default_factory=Usage)
    cost_usd: float | None = None      # None when the model has no price entry
    latency_s: float | None = None
    stop_reason: str | None = None
    response_id: str | None = None
    cached: bool = False
    batch: bool = False
    error: str | None = None           # set only by complete_many when a call failed
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "LLMResponse":
        d = dict(d)
        d["usage"] = Usage(**d.get("usage", {}))
        return cls(**d)


class LLMError(Exception):
    pass


class RetryableError(LLMError):
    """Raise (e.g. from a mock) to signal a transient failure."""

    def __init__(self, msg: str = "retryable", retry_after: float | None = None):
        super().__init__(msg)
        self.retry_after = retry_after


class ContaminationError(LLMError):
    pass


# ---------------------------------------------------------------------------
# Prices and cost ledger
# ---------------------------------------------------------------------------

class PriceTable:
    def __init__(self, models: dict[str, dict], batch_discount: float = 0.5):
        self.models = models
        self.batch_discount = batch_discount

    @classmethod
    def load(cls, path: str | Path = DEFAULT_PRICES) -> "PriceTable":
        cfg = yaml.safe_load(Path(path).read_text())
        return cls(cfg.get("models", {}), cfg.get("batch_discount", 0.5))

    def lookup(self, model: str) -> dict | None:
        """Exact match, else the longest configured name that prefixes `model`
        (so dated snapshots like `foo-2026-10-01` resolve to `foo`)."""
        if model in self.models:
            return self.models[model]
        hits = [k for k in self.models if model.startswith(k)]
        return self.models[max(hits, key=len)] if hits else None

    def cost(self, model: str, usage: Usage, batch: bool = False) -> float | None:
        p = self.lookup(model)
        if p is None:
            return None
        cached = usage.cached_input_tokens
        cached_rate = p.get("cached_input", p["input"])
        usd = ((usage.input_tokens - cached) * p["input"] + cached * cached_rate
               + usage.output_tokens * p["output"]) / 1e6
        return usd * (self.batch_discount if batch else 1.0)


class CostLedger:
    """Thread-safe running totals per model. Cache hits cost 0 and are counted separately."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.rows: dict[str, dict] = {}

    def record(self, resp: LLMResponse) -> None:
        with self._lock:
            r = self.rows.setdefault(resp.model, {
                "provider": resp.provider, "calls": 0, "cache_hits": 0, "batch_calls": 0,
                "input_tokens": 0, "output_tokens": 0, "reasoning_tokens": 0,
                "cost_usd": 0.0, "saved_by_cache_usd": 0.0, "unpriced_calls": 0,
            })
            r["calls"] += 1
            if resp.cost_usd is None:
                r["unpriced_calls"] += 1
            if resp.cached:
                r["cache_hits"] += 1
                r["saved_by_cache_usd"] += resp.cost_usd or 0.0
                return
            r["batch_calls"] += int(resp.batch)
            r["input_tokens"] += resp.usage.input_tokens
            r["output_tokens"] += resp.usage.output_tokens
            r["reasoning_tokens"] += resp.usage.reasoning_tokens
            r["cost_usd"] += resp.cost_usd or 0.0

    def total_usd(self) -> float:
        with self._lock:
            return sum(r["cost_usd"] for r in self.rows.values())

    def summary(self) -> dict:
        with self._lock:
            return {"total_usd": round(sum(r["cost_usd"] for r in self.rows.values()), 6),
                    "by_model": json.loads(json.dumps(self.rows))}

    def save(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(self.summary(), indent=2))


# ---------------------------------------------------------------------------
# Cache, rate limit, retry
# ---------------------------------------------------------------------------

class DiskCache:
    def __init__(self, root: str | Path = DEFAULT_CACHE_DIR):
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        return self.root / key[:2] / f"{key}.json"

    def get(self, key: str) -> dict | None:
        p = self._path(key)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text())
        except json.JSONDecodeError:  # torn write from a killed process: treat as miss
            return None

    def put(self, key: str, value: dict) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps(value, ensure_ascii=False))
        os.replace(tmp, p)  # atomic


class RateLimiter:
    """Token bucket: `rpm` requests per minute, bursts up to `burst`."""

    def __init__(self, rpm: float, burst: int | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        self.rate = rpm / 60.0
        self.capacity = float(burst if burst is not None else max(1, int(rpm // 10)))
        self.tokens = self.capacity
        self.clock, self.sleep = clock, sleep
        self.last = clock()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = self.clock()
                self.tokens = min(self.capacity, self.tokens + (now - self.last) * self.rate)
                self.last = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
                wait = (1 - self.tokens) / self.rate
            self.sleep(wait)


RETRYABLE_STATUS = {408, 409, 429}


def _status_of(exc: BaseException) -> int | None:
    for attr in ("status_code", "code", "status"):
        v = getattr(exc, attr, None)
        if isinstance(v, int):
            return v
    resp = getattr(exc, "response", None)
    v = getattr(resp, "status_code", None)
    return v if isinstance(v, int) else None


def is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, RetryableError):
        return True
    if isinstance(exc, (LLMError, ValueError, TypeError, KeyError)):
        return False
    status = _status_of(exc)
    if status is not None:
        return status in RETRYABLE_STATUS or status >= 500
    name = type(exc).__name__.lower()
    return any(s in name for s in ("timeout", "connection", "overloaded", "unavailable"))


def _retry_after(exc: BaseException) -> float | None:
    if isinstance(exc, RetryableError):
        return exc.retry_after
    headers = getattr(getattr(exc, "response", None), "headers", None) or {}
    try:
        return float(headers.get("retry-after")) if headers.get("retry-after") else None
    except (TypeError, ValueError):
        return None


def with_retries(fn: Callable[[], Any], *, max_attempts: int = 6, base_delay: float = 1.0,
                 max_delay: float = 60.0, sleep: Callable[[float], None] = time.sleep) -> Any:
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - classified below
            if attempt == max_attempts or not is_retryable(exc):
                raise
            delay = _retry_after(exc)
            if delay is None:
                delay = min(max_delay, base_delay * 2 ** (attempt - 1)) * (0.5 + random.random() / 2)
            log.warning("retryable %s (attempt %d/%d), sleeping %.1fs",
                        type(exc).__name__, attempt, max_attempts, delay)
            sleep(delay)
    raise AssertionError("unreachable")


# ---------------------------------------------------------------------------
# Output validation
# ---------------------------------------------------------------------------

def validate_output(text: str, schema: dict | None) -> tuple[Any, bool | None, str | None]:
    """Strict: the whole text must be one JSON value. Returns (parsed, valid, error)."""
    if schema is None:
        return None, None, None
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError) as e:
        return None, False, f"json: {e}"
    import jsonschema

    try:
        jsonschema.validate(parsed, schema)
    except jsonschema.ValidationError as e:
        return parsed, False, f"schema: {e.message}"
    return parsed, True, None


# ---------------------------------------------------------------------------
# Providers: build (request -> SDK kwargs), send (kwargs -> raw dict), parse (raw -> fields)
# ---------------------------------------------------------------------------

def _api_key(provider: str) -> str:
    for name in ENV_KEYS[provider]:
        if os.environ.get(name):
            return os.environ[name]
    raise LLMError(f"no API key for {provider}; set {' or '.join(ENV_KEYS[provider])} in .env")


class Provider:
    name = ""

    def build(self, req: LLMRequest) -> dict:
        raise NotImplementedError

    def send(self, kwargs: dict, req: LLMRequest) -> dict:
        raise NotImplementedError

    def parse(self, raw: dict) -> tuple[str, Usage, str | None, str | None]:
        """-> (text, usage, stop_reason, response_id)"""
        raise NotImplementedError


class OpenAIProvider(Provider):
    name = "openai"

    def __init__(self, timeout: float = 120.0):
        self.timeout = timeout
        self._client = None

    def build(self, req: LLMRequest) -> dict:
        msgs = ([{"role": "system", "content": req.system}] if req.system else []) + req.messages
        kw: dict[str, Any] = {"model": req.model, "messages": msgs,
                              "max_completion_tokens": req.max_tokens}
        if req.json_schema is not None:
            kw["response_format"] = {"type": "json_schema", "json_schema": {
                "name": req.schema_name, "schema": req.json_schema, "strict": True}}
        if req.temperature is not None:
            kw["temperature"] = req.temperature
        if req.reasoning_effort:
            kw["reasoning_effort"] = req.reasoning_effort
        kw.update(req.extra)
        return kw

    def client(self):
        if self._client is None:
            import openai

            self._client = openai.OpenAI(api_key=_api_key("openai"), max_retries=0,
                                         timeout=self.timeout)
        return self._client

    def send(self, kwargs: dict, req: LLMRequest) -> dict:
        return self.client().chat.completions.create(**kwargs).model_dump()

    def parse(self, raw: dict):
        choice = (raw.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        stop = choice.get("finish_reason")
        if msg.get("refusal"):
            stop = "refusal"
        u = raw.get("usage") or {}
        usage = Usage(
            input_tokens=u.get("prompt_tokens") or 0,
            output_tokens=u.get("completion_tokens") or 0,
            reasoning_tokens=(u.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0,
            cached_input_tokens=(u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0,
        )
        return msg.get("content") or "", usage, stop, raw.get("id")


class AnthropicProvider(Provider):
    name = "anthropic"

    def __init__(self, timeout: float = 300.0):
        self.timeout = timeout
        self._client = None

    def build(self, req: LLMRequest) -> dict:
        kw: dict[str, Any] = {"model": req.model, "max_tokens": req.max_tokens,
                              "messages": req.messages}
        if req.system:
            kw["system"] = req.system
        output_config: dict[str, Any] = {}
        if req.json_schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": req.json_schema}
        if req.reasoning_effort:
            # Opus 5.5 cannot disable thinking; effort is the only lever (its default is medium).
            output_config["effort"] = req.reasoning_effort
        if output_config:
            kw["output_config"] = output_config
        if req.temperature is not None:  # rejected (400) by Opus 5.5 / Fable 5.1; leave None there
            kw["temperature"] = req.temperature
        kw.update(req.extra)
        return kw

    def client(self):
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic(api_key=_api_key("anthropic"), max_retries=0,
                                               timeout=self.timeout)
        return self._client

    def send(self, kwargs: dict, req: LLMRequest) -> dict:
        return self.client().messages.create(**kwargs).model_dump()

    def parse(self, raw: dict):
        text = "".join(b.get("text", "") for b in raw.get("content") or [] if b.get("type") == "text")
        u = raw.get("usage") or {}
        read = u.get("cache_read_input_tokens") or 0
        write = u.get("cache_creation_input_tokens") or 0
        usage = Usage(input_tokens=(u.get("input_tokens") or 0) + read + write,
                      output_tokens=u.get("output_tokens") or 0,
                      cached_input_tokens=read)  # thinking is inside output_tokens, not split out
        return text, usage, raw.get("stop_reason"), raw.get("id")


class GeminiProvider(Provider):
    name = "gemini"

    def __init__(self):
        self._client = None

    def build(self, req: LLMRequest) -> dict:
        contents = [{"role": "model" if m["role"] == "assistant" else "user",
                     "parts": [{"text": m["content"]}]} for m in req.messages]
        config: dict[str, Any] = {"max_output_tokens": req.max_tokens}
        if req.system:
            config["system_instruction"] = req.system
        if req.json_schema is not None:
            config["response_mime_type"] = "application/json"
            config["response_json_schema"] = req.json_schema
        if req.temperature is not None:
            config["temperature"] = req.temperature
        if req.reasoning_effort:
            config["thinking_config"] = {"thinking_level": req.reasoning_effort}
        config.update(req.extra)
        return {"model": req.model, "contents": contents, "config": config}

    _init_lock = threading.Lock()

    def client(self):
        # Locked lazy init: two threads racing here each built a Client; the loser was
        # garbage-collected (and closed) mid-request -> "client has been closed".
        if self._client is None:
            with self._init_lock:
                if self._client is None:
                    from google import genai

                    self._client = genai.Client(api_key=_api_key("gemini"))
        return self._client

    def send(self, kwargs: dict, req: LLMRequest) -> dict:
        return self.client().models.generate_content(**kwargs).model_dump(mode="json")

    def parse(self, raw: dict):
        cand = (raw.get("candidates") or [{}])[0] or {}
        parts = ((cand.get("content") or {}).get("parts")) or []
        text = "".join(p.get("text") or "" for p in parts if not p.get("thought"))
        u = raw.get("usage_metadata") or raw.get("usageMetadata") or {}
        g = lambda *ks: next((u[k] for k in ks if u.get(k)), 0)  # noqa: E731 - snake or camel
        thoughts = g("thoughts_token_count", "thoughtsTokenCount")
        usage = Usage(input_tokens=g("prompt_token_count", "promptTokenCount"),
                      output_tokens=g("candidates_token_count", "candidatesTokenCount") + thoughts,
                      reasoning_tokens=thoughts,
                      cached_input_tokens=g("cached_content_token_count", "cachedContentTokenCount"))
        stop = cand.get("finish_reason") or cand.get("finishReason")
        return text, usage, stop, raw.get("response_id") or raw.get("responseId")


def schema_instance(schema: dict) -> Any:
    """Smallest deterministic instance of a (flat, enum-heavy) JSON Schema. Used by the mock."""
    if "const" in schema:
        return schema["const"]
    if "enum" in schema:
        return schema["enum"][0]
    for k in ("anyOf", "oneOf"):
        if k in schema:
            return schema_instance(schema[k][0])
    t = schema.get("type")
    if isinstance(t, list):
        t = next((x for x in t if x != "null"), "null")
    if t == "object":
        props = schema.get("properties", {})
        return {k: schema_instance(props[k]) for k in schema.get("required", list(props))}
    if t == "array":
        n = schema.get("minItems", 0)
        return [schema_instance(schema.get("items", {}))] * n
    if t == "string":
        return "x" * schema.get("minLength", 0)
    if t in ("integer", "number"):
        return schema.get("minimum", 0)
    if t == "boolean":
        return False
    return None


class MockProvider(Provider):
    """No network. `responder(req)` returns text, a JSON-able object, or raises.
    Default: a schema-valid instance (or 'ok' when no schema). Token counts ~ chars/4."""

    name = "mock"

    def __init__(self, responder: Callable[[LLMRequest], Any] | None = None):
        self.responder = responder
        self.calls = 0
        self._lock = threading.Lock()

    def build(self, req: LLMRequest) -> dict:
        return {"model": req.model, "n_messages": len(req.messages)}

    def send(self, kwargs: dict, req: LLMRequest) -> dict:
        with self._lock:
            self.calls += 1
        if self.responder is not None:
            out = self.responder(req)
        else:
            out = schema_instance(req.json_schema) if req.json_schema else "ok"
        text = out if isinstance(out, str) else json.dumps(out)
        return {"id": f"mock-{self.calls}", "text": text, "stop_reason": "end_turn",
                "input_tokens": max(1, len(req.all_text()) // 4),
                "output_tokens": max(1, len(text) // 4)}

    def parse(self, raw: dict):
        return raw["text"], Usage(raw["input_tokens"], raw["output_tokens"]), raw["stop_reason"], raw["id"]


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(override=False)


class LLMClient:
    def __init__(self, *, mock: bool | None = None, mock_responder: Callable | None = None,
                 cache_dir: str | Path | None = DEFAULT_CACHE_DIR, prices: PriceTable | None = None,
                 rpm: dict[str, float] | None = None, max_attempts: int = 6,
                 providers: dict[str, Provider] | None = None, guard: Any = None,
                 sleep: Callable[[float], None] = time.sleep):
        _load_dotenv()
        if mock is None:
            mock = os.environ.get("LLM_MOCK", "") not in ("", "0", "false")
        self.mock = mock
        self._mock_provider = MockProvider(mock_responder)
        self.providers: dict[str, Provider] = {
            "openai": OpenAIProvider(), "anthropic": AnthropicProvider(),
            "gemini": GeminiProvider(), "mock": self._mock_provider,
        }
        self.providers.update(providers or {})
        self.cache = DiskCache(cache_dir) if cache_dir is not None else None
        self.prices = prices or PriceTable.load()
        rpm = {"openai": 500, "anthropic": 50, "gemini": 150, "mock": 1e9, **(rpm or {})}
        self.limiters = {p: RateLimiter(r, sleep=sleep) for p, r in rpm.items()}
        self.max_attempts = max_attempts
        self.guard = guard  # object with .check(text) raising on eval overlap
        self.sleep = sleep
        self.ledger = CostLedger()

    def provider_for(self, req: LLMRequest) -> Provider:
        return self._mock_provider if self.mock else self.providers[req.provider]

    def complete(self, req: LLMRequest, *, use_cache: bool = True) -> LLMResponse:
        if self.guard is not None and req.purpose == "teacher":
            self.guard.check(req.all_text())  # raises ContaminationError-like on overlap
        key = req.cache_key()
        if self.mock:
            key = "mock-" + key  # mock answers never shadow real ones in the cache
        if use_cache and self.cache is not None:
            hit = self.cache.get(key)
            if hit is not None:
                resp = LLMResponse.from_dict(hit)
                resp.cached, resp.metadata = True, dict(req.metadata)
                self.ledger.record(resp)
                return resp

        prov = self.provider_for(req)
        kwargs = prov.build(req)
        limiter = self.limiters.get(req.provider)

        def call() -> dict:
            if limiter is not None:
                limiter.acquire()
            return prov.send(kwargs, req)

        t0 = time.perf_counter()
        raw = with_retries(call, max_attempts=self.max_attempts, sleep=self.sleep)
        latency = time.perf_counter() - t0
        resp = self.finish(req, key, prov, raw, latency=latency)
        if self.cache is not None:
            self.cache.put(key, resp.to_dict())
        self.ledger.record(resp)
        return resp

    def finish(self, req: LLMRequest, key: str, prov: Provider, raw: dict, *,
               latency: float | None = None, batch: bool = False) -> LLMResponse:
        """raw provider dict -> LLMResponse with validation and cost. Shared with shared/frontier_api/batch.py."""
        text, usage, stop, rid = prov.parse(raw)
        parsed, valid, err = validate_output(text, req.json_schema)
        return LLMResponse(
            request_key=key, provider=req.provider, model=req.model, text=text, parsed=parsed,
            schema_valid=valid, parse_error=err, usage=usage,
            cost_usd=self.prices.cost(req.model, usage, batch=batch), latency_s=latency,
            stop_reason=stop, response_id=rid, batch=batch, metadata=dict(req.metadata))

    def complete_many(self, reqs: list[LLMRequest], max_workers: int = 8) -> list[LLMResponse]:
        """Order-preserving fan-out. Failures come back as responses with `error` set."""

        def one(req: LLMRequest) -> LLMResponse:
            try:
                return self.complete(req)
            except Exception as e:  # noqa: BLE001
                return LLMResponse(request_key=req.cache_key(), provider=req.provider,
                                   model=req.model, text="", error=f"{type(e).__name__}: {e}",
                                   schema_valid=False if req.json_schema else None,
                                   metadata=dict(req.metadata))

        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            return list(ex.map(one, reqs))
