"""Thin OpenAI-compatible proxy in front of the model server (vLLM).

    POST /v1/chat/completions   (bearer token required)
    GET  /v1/models             (bearer token required)
    GET  /health                (no auth; for warm-up / readiness probes)

What it adds on top of the upstream server:

* **Auth**: `Authorization: Bearer <token>` checked in constant time against
  the keys in `PROXY_API_KEYS` (comma-separated). Missing or wrong -> 401.
* **Prompt injection of our own prompt**: if the caller sends no system
  message, the proxy inserts the student system prompt (`step0_rules/prompts/student.md`
  rendered with our schema and policy) and wraps the packet in the same user
  template the model was trained on. A bare packet just works.
* **Structured output**: if the caller omits `response_format`, the proxy
  adds `json_schema` (strict) with our schema, so vLLM constrains decoding.
* **Thinking off**: `chat_template_kwargs.enable_thinking = false` is forced.
* **Pre-checks (Final B)**: env `ZORBE_PRECHECKS=1` adds the code-computed PRE-CHECKS
  block to every request via `step7_serving.prechecks.apply_prechecks` (the same function
  that built the training data, so the text is byte-identical). Default off.
* **Validation**: the output is parsed and validated against the schema
  (ours, or the caller's own `json_schema` if they sent one). If invalid, one
  retry. If still invalid, a schema-valid `escalate` fallback is returned,
  flagged in the `x-kyc-fallback` header and logged. Upstream 5xx / timeouts
  get the same one-retry-then-fallback treatment (config switch).
* **Latency logging**: one JSON log line per request (no packet text; only
  its sha256), plus `x-kyc-latency-ms` / `x-kyc-upstream-ms` headers.
* **Streaming**: supported in buffered form. With `stream: true` the proxy
  still validates the whole output first, then sends it as one SSE content
  chunk, a finish chunk and `[DONE]` (header `x-kyc-stream: buffered`).

Run locally (the upstream can be any OpenAI-compatible server):

    PROXY_API_KEYS=dev-token PROXY_CONFIG=step7_serving/proxy_config.example.yaml \
        uvicorn step7_serving.proxy:app_from_env --factory --port 8080

On Modal, mount it with `@modal.asgi_app()` returning `create_app(ProxyConfig.load(...))`.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import hmac
import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Awaitable, Callable

import jsonschema
import yaml
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

log = logging.getLogger("kyc.proxy")

Upstream = Callable[[dict], Awaitable[dict]]


class UpstreamError(Exception):
    def __init__(self, status: int | None, message: str):
        super().__init__(message)
        self.status = status  # None = connection error / timeout

    @property
    def retryable(self) -> bool:
        return self.status is None or self.status in (408, 429) or self.status >= 500


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class ProxyConfig:
    upstream_url: str = "http://localhost:8000/v1"   # OpenAI-compatible base URL (vLLM)
    upstream_model: str = "PLACEHOLDER"              # model name the upstream serves
    served_model: str = "zorbe-kyc"                  # model name callers see
    upstream_api_key_env: str | None = None          # env var NAME holding the upstream key, if any
    schema_path: str = "step0_rules/schema/v0_provisional.json"
    policy: str = "module:step1_data_generation.project"               # file path or module:<name>
    template: str = "student"
    api_keys_env: str = "PROXY_API_KEYS"             # env var NAME holding comma-separated bearer tokens
    default_max_tokens: int = 2048
    max_tokens_cap: int = 4096
    default_temperature: float | None = 0.0
    max_attempts: int = 2                            # 1 try + 1 retry
    fallback_overrides: dict = field(default_factory=dict)  # dotted path -> value
    fallback_on_upstream_error: bool = True
    repair_fences: bool = True                       # accept ```json ...``` / surrounding prose, flagged
    timeout_s: float = 600.0                         # generous: the first request after a cold start
    log_path: str | None = None                      # extra JSONL request log
    allow_no_auth: bool = False                      # local experiments only

    @classmethod
    def load(cls, path: str | Path | None = None, **overrides: Any) -> "ProxyConfig":
        d: dict = {}
        if path:
            d = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        d.update(overrides)
        unknown = set(d) - {f.name for f in fields(cls)}
        if unknown:
            raise ValueError(f"unknown proxy config keys: {sorted(unknown)}")
        return cls(**d)

    def api_keys(self) -> list[str]:
        raw = os.environ.get(self.api_keys_env, "")
        return [k.strip() for k in raw.split(",") if k.strip()]


# ---------------------------------------------------------------------------
# Output handling
# ---------------------------------------------------------------------------

_FENCE = re.compile(r"\A\s*```(?:json)?\s*(.*?)\s*```\s*\Z", re.S)


def check_output(text: str, validator: jsonschema.protocols.Validator,
                 repair: bool) -> tuple[str | None, str | None, bool]:
    """-> (valid_json_text or None, error, repaired). Strict first; then, if `repair`,
    strip a code fence or take the outermost {...}."""
    candidates = [(text, False)]
    if repair:
        m = _FENCE.match(text or "")
        if m:
            candidates.append((m.group(1), True))
        i, j = (text or "").find("{"), (text or "").rfind("}")
        if 0 <= i < j:
            candidates.append((text[i:j + 1], True))
    err = "empty output"
    for cand, repaired in candidates:
        try:
            obj = json.loads(cand)
        except (json.JSONDecodeError, TypeError) as e:
            err = f"json: {e}"
            continue
        errors = sorted(validator.iter_errors(obj), key=lambda e: list(e.path))
        if errors:
            err = f"schema: {errors[0].message}"
            continue
        return cand.strip(), None, repaired
    return None, err, False


def _set_path(obj: Any, dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    cur = obj
    for p in parts[:-1]:
        cur = cur[int(p)] if isinstance(cur, list) else cur[p]
    last = parts[-1]
    if isinstance(cur, list):
        cur[int(last)] = value
    else:
        cur[last] = value


def build_fallback(schema: dict, overrides: dict) -> dict:
    """A schema-valid output whose decision is escalate.

    Starts from the minimal instance of the schema, sets every top-level enum
    property that offers "escalate" to it, then applies the configured dotted-path
    overrides (e.g. risk tier, a narrative sentence). Raises if the result is not
    schema-valid or does not escalate, so a bad config fails at startup, not at 3am."""
    from shared.frontier_api.clients import schema_instance

    resolved = _deref(schema, schema)
    fb = schema_instance(resolved)
    escalates = False
    for k, sub in (resolved.get("properties") or {}).items():
        if "escalate" in (sub.get("enum") or []):
            fb[k] = "escalate"
            escalates = True
    for path, value in (overrides or {}).items():
        _set_path(fb, path, copy.deepcopy(value))
        escalates = escalates or value == "escalate"
    jsonschema.validators.validator_for(schema)(schema).validate(fb)
    if not escalates:
        raise ValueError("fallback does not escalate: no top-level enum offers 'escalate'; "
                         "set fallback_overrides (e.g. {'decision': 'escalate'})")
    return fb


def _deref(node: Any, root: dict, depth: int = 0) -> Any:
    """Inline local $refs (for schema_instance, which does not follow them)."""
    if depth > 50:
        raise ValueError("$ref too deep")
    if isinstance(node, dict):
        if "$ref" in node and str(node["$ref"]).startswith("#/"):
            target: Any = root
            for part in node["$ref"][2:].split("/"):
                target = target[part]
            rest = {k: v for k, v in node.items() if k != "$ref"}
            return _deref({**target, **rest}, root, depth + 1)
        return {k: _deref(v, root, depth + 1) for k, v in node.items()}
    if isinstance(node, list):
        return [_deref(v, root, depth + 1) for v in node]
    return node


def _text_of(content: Any) -> str:
    """OpenAI content may be a string or a list of parts."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
    return ""


def _add_usage(total: dict, u: dict | None) -> None:
    for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
        if u and isinstance(u.get(k), int):
            total[k] = total.get(k, 0) + u[k]


# ---------------------------------------------------------------------------
# Upstream
# ---------------------------------------------------------------------------

class HTTPUpstream:
    """POST {base}/chat/completions with httpx. Errors -> UpstreamError."""

    def __init__(self, base_url: str, api_key: str | None = None, timeout_s: float = 600.0):
        import httpx

        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.client = httpx.AsyncClient(timeout=timeout_s, headers=headers)

    async def __call__(self, payload: dict) -> dict:
        import httpx

        try:
            r = await self.client.post(self.url, json=payload)
        except httpx.HTTPError as e:
            raise UpstreamError(None, f"{type(e).__name__}: {e}") from None
        if r.status_code >= 400:
            raise UpstreamError(r.status_code, r.text[:500])
        return r.json()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

def _error(status: int, message: str, etype: str, headers: dict | None = None):
    return JSONResponse({"error": {"message": message, "type": etype, "code": status}},
                        status_code=status, headers=headers)


def create_app(cfg: ProxyConfig, upstream: Upstream | None = None):
    from step0_rules.prompts.render import PromptBuilder, load_schema

    keys = cfg.api_keys()
    if not keys and not cfg.allow_no_auth:
        raise RuntimeError(f"no bearer tokens: set {cfg.api_keys_env} (comma-separated)")
    schema = load_schema(cfg.schema_path)
    validator_cls = jsonschema.validators.validator_for(schema)
    validator_cls.check_schema(schema)
    our_validator = validator_cls(schema)
    builder = PromptBuilder(cfg.template, schema=schema, policy=cfg.policy)
    system_prompt = builder.system()
    fallback_text = json.dumps(build_fallback(schema, cfg.fallback_overrides), ensure_ascii=False)
    our_rf = {"type": "json_schema",
              "json_schema": {"name": "kyc_decision", "schema": schema, "strict": True}}
    if upstream is None:
        key = os.environ.get(cfg.upstream_api_key_env) if cfg.upstream_api_key_env else None
        upstream = HTTPUpstream(cfg.upstream_url, key, cfg.timeout_s)
    log_file = Path(cfg.log_path) if cfg.log_path else None
    prechecks_on = os.environ.get("ZORBE_PRECHECKS", "0") == "1"
    if prechecks_on:
        from step7_serving.prechecks import apply_prechecks

    app = FastAPI(title="zorbe-kyc proxy", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.cfg, app.state.stats = cfg, {"requests": 0, "fallbacks": 0, "retries": 0}

    def authorized(request: Request) -> bool:
        if not keys:
            return True
        auth = request.headers.get("authorization", "")
        scheme, _, token = auth.partition(" ")
        if scheme.lower() != "bearer" or not token:
            return False
        tok = token.strip().encode()
        # compare against every key (no early exit) so timing doesn't leak which key matched
        ok = False
        for k in keys:
            ok |= hmac.compare_digest(tok, k.encode())
        return ok

    def emit(rec: dict) -> None:
        line = json.dumps(rec, ensure_ascii=False, sort_keys=True)
        log.info(line)
        if log_file is not None:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(line + "\n")

    @app.get("/health")
    async def health():
        return {"status": "ok", "model": cfg.served_model}

    @app.get("/v1/models")
    async def models(request: Request):
        if not authorized(request):
            return _error(401, "invalid or missing bearer token", "authentication_error",
                          {"WWW-Authenticate": "Bearer"})
        return {"object": "list", "data": [{"id": cfg.served_model, "object": "model",
                                            "owned_by": "zorbe-kyc"}]}

    @app.post("/v1/chat/completions")
    async def chat(request: Request):
        t0 = time.perf_counter()
        rid = request.headers.get("x-request-id") or f"req-{uuid.uuid4().hex[:16]}"
        if not authorized(request):
            emit({"event": "auth_failed", "request_id": rid})
            return _error(401, "invalid or missing bearer token", "authentication_error",
                          {"WWW-Authenticate": "Bearer"})
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return _error(400, "body must be JSON", "invalid_request_error")
        msgs = body.get("messages") if isinstance(body, dict) else None
        if not isinstance(msgs, list) or not msgs or not all(isinstance(m, dict) for m in msgs):
            return _error(400, "`messages` must be a non-empty list of objects", "invalid_request_error")
        if body.get("n") not in (None, 1):
            return _error(400, "only n=1 is supported", "invalid_request_error")
        if body.get("tools") or body.get("functions"):
            return _error(400, "tools are not supported by this endpoint", "invalid_request_error")
        stream = bool(body.get("stream"))

        payload = {k: v for k, v in body.items() if k not in ("stream", "stream_options", "model", "n")}
        msgs = [dict(m) for m in msgs]
        injected_prompt = not any(m.get("role") in ("system", "developer") for m in msgs)
        if injected_prompt:
            # Wrap the packet exactly as in training (student user template) unless already wrapped.
            for m in reversed(msgs):
                if m.get("role") == "user":
                    text = _text_of(m.get("content"))
                    if "<packet>" not in text:
                        m["content"] = builder.wrap_user(text)
                    break
            msgs.insert(0, {"role": "system", "content": system_prompt})
        if prechecks_on:
            msgs = apply_prechecks(msgs)
        payload["messages"] = msgs
        packet_hash = hashlib.sha256(
            "\n".join(_text_of(m.get("content")) for m in msgs if m.get("role") == "user").encode()).hexdigest()

        injected_rf = "response_format" not in body or body.get("response_format") is None
        if injected_rf:
            payload["response_format"] = our_rf
        rf = payload["response_format"]
        validator, ours = our_validator, True
        if isinstance(rf, dict) and rf.get("type") == "json_schema":
            their = (rf.get("json_schema") or {}).get("schema")
            if their is not None and their != schema:
                try:
                    validator, ours = jsonschema.validators.validator_for(their)(their), False
                except Exception:  # noqa: BLE001
                    return _error(400, "response_format.json_schema.schema is not a valid JSON Schema",
                                  "invalid_request_error")
        payload["model"] = cfg.upstream_model
        payload["stream"] = False
        payload["chat_template_kwargs"] = {**(body.get("chat_template_kwargs") or {}),
                                           "enable_thinking": False}
        mt = body.get("max_completion_tokens") or body.get("max_tokens") or cfg.default_max_tokens
        if not isinstance(mt, int) or isinstance(mt, bool) or mt < 1:
            return _error(400, "max_tokens must be a positive integer", "invalid_request_error")
        payload.pop("max_completion_tokens", None)
        payload["max_tokens"] = min(mt, cfg.max_tokens_cap)
        if "temperature" not in body and cfg.default_temperature is not None:
            payload["temperature"] = cfg.default_temperature

        usage: dict = {}
        upstream_ms: list[float] = []
        final: str | None = None
        last_raw: dict | None = None
        err: str | None = None
        repaired = False
        fallback_reason = ""
        for attempt in range(1, cfg.max_attempts + 1):
            ts = time.perf_counter()
            try:
                raw = await upstream(copy.deepcopy(payload))
            except UpstreamError as e:
                upstream_ms.append((time.perf_counter() - ts) * 1000)
                err = f"upstream {e.status}: {e}"
                if not e.retryable:
                    emit({"event": "upstream_rejected", "request_id": rid, "status": e.status})
                    return _error(e.status or 502, f"upstream rejected the request: {e}",
                                  "invalid_request_error")
                fallback_reason = "upstream_error"
                continue
            except asyncio.TimeoutError:
                upstream_ms.append((time.perf_counter() - ts) * 1000)
                err, fallback_reason = "upstream timeout", "upstream_error"
                continue
            upstream_ms.append((time.perf_counter() - ts) * 1000)
            last_raw = raw
            _add_usage(usage, raw.get("usage"))
            choice = (raw.get("choices") or [{}])[0]
            text = _text_of((choice.get("message") or {}).get("content"))
            final, err, repaired = check_output(text, validator, cfg.repair_fences)
            if final is not None:
                fallback_reason = ""
                break
            fallback_reason = "invalid_output"
        attempts = len(upstream_ms)

        if final is None:
            if fallback_reason == "upstream_error" and (not cfg.fallback_on_upstream_error or not ours):
                emit({"event": "upstream_failed", "request_id": rid, "error": err, "attempts": attempts})
                return _error(502, f"upstream failed after {attempts} attempts: {err}", "upstream_error")
            if not ours:
                # The caller's own schema: we can't build a fallback for it; return the last output.
                final = _text_of(((last_raw or {}).get("choices") or [{}])[0].get("message", {}).get("content"))
                fallback_reason = ""
            else:
                final = fallback_text
                app.state.stats["fallbacks"] += 1
        app.state.stats["requests"] += 1
        app.state.stats["retries"] += max(0, attempts - 1)
        latency_ms = (time.perf_counter() - t0) * 1000
        schema_valid = check_output(final, validator, False)[0] is not None

        resp = copy.deepcopy(last_raw) if last_raw else {
            "id": f"chatcmpl-{uuid.uuid4().hex}", "object": "chat.completion", "created": int(time.time()),
            "choices": [{"index": 0, "message": {"role": "assistant", "content": ""}, "finish_reason": "stop"}]}
        resp["model"] = cfg.served_model
        resp.setdefault("object", "chat.completion")
        if not resp.get("created"):
            resp["created"] = int(time.time())
        resp["choices"] = [{**(resp.get("choices") or [{}])[0], "index": 0}]
        msg = dict(resp["choices"][0].get("message") or {})
        msg.update({"role": "assistant", "content": final})
        msg.pop("reasoning_content", None)
        msg.pop("reasoning", None)
        resp["choices"][0]["message"] = msg
        if fallback_reason:
            resp["choices"][0]["finish_reason"] = "stop"
        resp["usage"] = usage or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

        headers = {
            "x-request-id": rid,
            "x-kyc-fallback": fallback_reason or "0",
            "x-kyc-attempts": str(attempts),
            "x-kyc-schema-valid": "1" if schema_valid else "0",
            "x-kyc-repaired": "1" if repaired and not fallback_reason else "0",
            "x-kyc-prompt-injected": "1" if injected_prompt else "0",
            "x-kyc-response-format-injected": "1" if injected_rf else "0",
            "x-kyc-prechecks": "1" if prechecks_on else "0",
            "x-kyc-latency-ms": f"{latency_ms:.1f}",
            "x-kyc-upstream-ms": f"{sum(upstream_ms):.1f}",
        }
        emit({"event": "completion", "request_id": rid, "latency_ms": round(latency_ms, 1),
              "upstream_ms": [round(x, 1) for x in upstream_ms], "attempts": attempts,
              "fallback": fallback_reason or None, "last_error": err if fallback_reason else None,
              "repaired": repaired and not fallback_reason, "schema_valid": schema_valid,
              "prompt_injected": injected_prompt, "response_format_injected": injected_rf,
              "prechecks": prechecks_on,
              "packet_sha256": packet_hash, "usage": resp["usage"], "stream": stream})

        if not stream:
            return JSONResponse(resp, headers=headers)
        headers["x-kyc-stream"] = "buffered"
        return StreamingResponse(_sse(resp), media_type="text/event-stream", headers=headers)

    return app


async def _sse(resp: dict):
    base = {"id": resp.get("id"), "object": "chat.completion.chunk", "created": resp.get("created"),
            "model": resp.get("model")}
    content = resp["choices"][0]["message"]["content"]
    chunks = [
        {**base, "choices": [{"index": 0, "delta": {"role": "assistant", "content": content},
                              "finish_reason": None}]},
        {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": resp["choices"][0].get("finish_reason")
                              or "stop"}], "usage": resp.get("usage")},
    ]
    for c in chunks:
        yield f"data: {json.dumps(c, ensure_ascii=False)}\n\n"
    yield "data: [DONE]\n\n"


def app_from_env():
    """uvicorn factory: config file from PROXY_CONFIG (optional), keys from PROXY_API_KEYS."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    return create_app(ProxyConfig.load(os.environ.get("PROXY_CONFIG")))
