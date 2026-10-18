"""Smoke test for the Modal serving stack (step7_serving/modal_vllm.py). One command:

    python -m step7_serving.smoke                         # app zorbe-serve, 20 warm requests
    python -m step7_serving.smoke --app zorbe-serve --n 20 --skip-cold

Checks, against both the raw vLLM endpoint and the proxy:
  1. auth: no token -> 401, wrong token -> 401, right token -> 200
  2. structured output: a toy `json_schema` (enum + integer bounds + regex pattern) on a
     prompt that pulls the other way; the output must validate. A control call without
     `response_format` shows the constraint is doing the work.
  3. thinking off: no <think> in content, no reasoning field
  4. latency: cold start (first request after scale-to-zero, unless --skip-cold) and warm
     p50/p95 over --n sequential requests

Tokens come from .env (VLLM_API_KEY, PROXY_API_KEY) and are never printed. Results are
written to outputs/smoke/<timestamp>.json; the summary is printed.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import jsonschema
from dotenv import load_dotenv
from openai import APIStatusError, OpenAI

ROOT = Path(__file__).resolve().parents[1]

TOY_SCHEMA = {
    "type": "object",
    "properties": {
        "color": {"type": "string", "enum": ["teal", "mauve", "ochre"]},
        "count": {"type": "integer", "minimum": 3, "maximum": 7},
        "code": {"type": "string", "pattern": "^ZK-[0-9]{4}$"},
    },
    "required": ["color", "count", "code"],
    "additionalProperties": False,
}
TOY_PROMPT = ("Write a two-line poem about the color red and the number 42. "
              "Do not use JSON.")
WARM_PROMPT = "Reply with one short sentence: what is a passport MRZ?"


def resolve_urls(app: str) -> dict[str, str]:
    """Look the web URLs up from the deployed app (no hard-coded workspace)."""
    import modal

    out = {}
    for fn in ("vllm", "proxy"):
        out[fn] = modal.Function.from_name(app, fn).get_web_url().rstrip("/")
    return out


def pct(xs: list[float], q: float) -> float:
    s = sorted(xs)
    k = (len(s) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return round(s[lo] + (s[hi] - s[lo]) * (k - lo), 1)


def client(base: str, key: str | None, timeout: float = 900) -> OpenAI:
    return OpenAI(base_url=base + "/v1", api_key=key or "none", timeout=timeout, max_retries=0)


def check_auth(base: str, key: str) -> dict:
    res = {}
    for label, k in (("no_token", None), ("wrong_token", "zk-wrong-token")):
        headers = {} if k is None else {"Authorization": f"Bearer {k}"}
        r = httpx.post(base + "/v1/chat/completions", headers=headers, timeout=900,
                       json={"model": "x", "messages": [{"role": "user", "content": "hi"}],
                             "max_tokens": 4})
        res[label] = r.status_code
    try:
        client(base, key).models.list()
        res["right_token"] = 200
    except APIStatusError as e:
        res["right_token"] = e.status_code
    res["ok"] = res["no_token"] == 401 and res["wrong_token"] == 401 and res["right_token"] == 200
    return res


def chat(c: OpenAI, model: str, prompt: str, rf: dict | None, max_tokens: int = 128,
         system: str | None = None):
    msgs = ([{"role": "system", "content": system}] if system else []) + \
           [{"role": "user", "content": prompt}]
    kw = {"response_format": rf} if rf else {}
    t = time.perf_counter()
    raw = c.chat.completions.with_raw_response.create(
        model=model, messages=msgs, max_tokens=max_tokens, temperature=0.0,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}}, **kw)
    ms = (time.perf_counter() - t) * 1000
    r = raw.parse()
    return r, ms, dict(raw.headers)


def check_schema(c: OpenAI, model: str) -> dict:
    rf = {"type": "json_schema", "json_schema": {"name": "toy", "schema": TOY_SCHEMA, "strict": True}}
    # system message: the proxy then forwards as-is instead of injecting the KYC prompt
    sysmsg = "You are a helpful assistant."
    out = {}
    r, _, _ = chat(c, model, TOY_PROMPT, rf, system=sysmsg)
    text = r.choices[0].message.content or ""
    try:
        jsonschema.validate(json.loads(text), TOY_SCHEMA)
        out["constrained_valid"] = True
    except Exception as e:  # noqa: BLE001
        out["constrained_valid"], out["constrained_error"] = False, str(e)[:200]
    out["constrained_output"] = text[:300]
    r, _, _ = chat(c, model, TOY_PROMPT, None, system=sysmsg)
    text = r.choices[0].message.content or ""
    try:
        jsonschema.validate(json.loads(text), TOY_SCHEMA)
        out["control_valid"] = True
    except Exception:  # noqa: BLE001
        out["control_valid"] = False
    out["control_output"] = text[:200]
    out["ok"] = out["constrained_valid"] and not out["control_valid"]
    return out


def check_thinking(r) -> dict:
    msg = r.choices[0].message
    content = msg.content or ""
    extra = getattr(msg, "model_extra", None) or {}
    reasoning = extra.get("reasoning_content") or extra.get("reasoning")
    return {"think_tag": "<think>" in content, "reasoning_field": bool(reasoning),
            "ok": "<think>" not in content and not reasoning}


def warm_latency(c: OpenAI, model: str, n: int, system: str | None) -> dict:
    """Same request on both endpoints: toy json_schema (so the proxy validates the caller's
    schema instead of injecting the KYC one), short output. Proxy minus vLLM = proxy overhead."""
    rf = {"type": "json_schema", "json_schema": {"name": "toy", "schema": TOY_SCHEMA, "strict": True}}
    lat, comp, headers, attempts = [], [], [], []
    for _ in range(n):
        r, ms, h = chat(c, model, TOY_PROMPT, rf, max_tokens=64, system=system)
        lat.append(ms)
        comp.append(r.usage.completion_tokens if r.usage else None)
        if "x-kyc-upstream-ms" in h:
            headers.append(float(h["x-kyc-upstream-ms"]))
            attempts.append(int(h.get("x-kyc-attempts", 0)))
    out = {"n": n, "p50_ms": pct(lat, 0.5), "p95_ms": pct(lat, 0.95), "mean_ms": round(statistics.mean(lat), 1),
           "max_tokens": 64, "completion_tokens_mean": round(statistics.mean([x for x in comp if x]), 1)}
    if headers:
        out["upstream_p50_ms"] = pct(headers, 0.5)
        out["proxy_attempts_max"] = max(attempts)
    return out


def containers_running(app: str) -> int:
    r = subprocess.run(["modal", "container", "list", "--json"], capture_output=True, text=True)
    try:
        rows = json.loads(r.stdout or "[]")
    except json.JSONDecodeError:
        return -1
    return sum(1 for x in rows if app in json.dumps(x))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", default="zorbe-serve")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--skip-cold", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "outputs" / "smoke"))
    a = ap.parse_args()
    load_dotenv(ROOT / ".env")
    vkey, pkey = os.environ.get("VLLM_API_KEY"), os.environ.get("PROXY_API_KEY")
    if not vkey or not pkey:
        sys.exit("VLLM_API_KEY / PROXY_API_KEY missing from .env: run python -m step7_serving.setup_secrets")

    urls = resolve_urls(a.app)
    served = None
    rec: dict = {"app": a.app, "started": datetime.now(timezone.utc).isoformat(), "urls": urls}

    # 1. cold start: first request with nothing running
    if not a.skip_cold:
        n_up = containers_running(a.app)
        rec["containers_before_cold"] = n_up
        c = client(urls["vllm"], vkey)
        t = time.perf_counter()
        served = c.models.list().data[0].id
        rec["cold_start_models_s"] = round(time.perf_counter() - t, 1)
        r, ms, _ = chat(c, served, WARM_PROMPT, None, max_tokens=48)
        rec["cold_start_total_s"] = round(rec["cold_start_models_s"] + ms / 1000, 1)
        rec["first_completion_ms"] = round(ms, 1)
        print(f"cold start: {rec['cold_start_total_s']}s (containers before: {n_up})")
    vc = client(urls["vllm"], vkey)
    served = served or vc.models.list().data[0].id
    rec["served_model"] = served

    for name, base, key in (("vllm", urls["vllm"], vkey), ("proxy", urls["proxy"], pkey)):
        res: dict = {}
        res["auth"] = check_auth(base, key)
        c = client(base, key)
        res["schema"] = check_schema(c, served)
        r, _, h = chat(c, served, WARM_PROMPT, None, max_tokens=48, system="You are a helpful assistant.")
        res["thinking"] = check_thinking(r)
        res["sample"] = (r.choices[0].message.content or "")[:200]
        res["warm"] = warm_latency(c, served, a.n, system="You are a helpful assistant.")
        rec[name] = res
        print(f"[{name}] auth={res['auth']} schema_ok={res['schema']['ok']} "
              f"thinking_off={res['thinking']['ok']} warm p50={res['warm']['p50_ms']}ms "
              f"p95={res['warm']['p95_ms']}ms")

    # the proxy's own path: bare packet -> injected prompt + KYC schema
    draft = ROOT / "data" / "draft" / "cases.jsonl"
    if draft.exists():
        case = json.loads(draft.read_text(encoding="utf-8").splitlines()[0])
        packet = case.get("packet") or ""
        if packet:
            pc = client(urls["proxy"], pkey)
            t = time.perf_counter()
            raw = pc.chat.completions.with_raw_response.create(
                model="zorbe-kyc", messages=[{"role": "user", "content": packet}])
            h = dict(raw.headers)
            rec["proxy_kyc_packet"] = {
                "case_id": case.get("case_id") or case.get("id"),
                "latency_ms": round((time.perf_counter() - t) * 1000, 1),
                **{k: h.get(k) for k in ("x-kyc-fallback", "x-kyc-schema-valid", "x-kyc-attempts",
                                         "x-kyc-prompt-injected", "x-kyc-upstream-ms")},
                "output_head": (raw.parse().choices[0].message.content or "")[:300]}
            print(f"[proxy kyc packet] {json.dumps({k: v for k, v in rec['proxy_kyc_packet'].items() if k != 'output_head'})}")

    rec["ok"] = all(rec[n]["auth"]["ok"] and rec[n]["schema"]["ok"] and rec[n]["thinking"]["ok"]
                    for n in ("vllm", "proxy"))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{a.app}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(rec, indent=1), encoding="utf-8")
    print(f"{'PASS' if rec['ok'] else 'FAIL'} -> {path.relative_to(ROOT)}")
    sys.exit(0 if rec["ok"] else 1)


if __name__ == "__main__":
    main()
