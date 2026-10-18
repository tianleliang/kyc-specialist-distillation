"""Run any OpenAI-compatible endpoint over a JSONL of cases.

Works against our proxy, a bare vLLM server, or a frontier API with an
OpenAI-compatible surface. Writes exactly what ``step6_evaluation/report.py`` reads::

    <out>/predictions.jsonl   {"case_id", "output", "latency_ms", "usage", ...extras}
    <out>/run.json            report metadata (only keys step6_evaluation/report.py knows)
    <out>/endpoint_run.json   provenance: endpoint, prompt hashes, cases sha256, counts, timing

Examples::

    # our proxy, bare packets (the proxy injects prompt + schema)
    python -m step2_benchmarking.run_endpoint --cases data/draft/cases.jsonl --out outputs/ours-draft \\
        --base-url http://localhost:8080/v1 --model zorbe-kyc --api-key-env PROXY_API_KEY \\
        --prompt none --response-format none --concurrency 8

    # a bare vLLM server or a frontier model, with our student / baseline prompt
    python -m step2_benchmarking.run_endpoint --cases ... --out outputs/qwen-0.8b-zs --base-url http://.../v1 \\
        --model Qwen/... --prompt baseline_zero_shot --schema step0_rules/schema/v1.json \\
        --extra-body '{"chat_template_kwargs": {"enable_thinking": false}}'

Rules:
* A failed case is still written (``output: null`` plus ``error``) so the report
  scores it as zero instead of dropping it.
* ``--resume`` keeps finished cases and re-runs only missing or failed ones.
* ``--cache`` reuses the on-disk cache from ``shared/frontier_api/clients.py`` (keyed by endpoint +
  payload). Use it for paid APIs; leave it off when measuring latency. Cached
  records keep their original latency and are flagged ``cached: true``.
* The API key is read from the env var named by ``--api-key-env`` and is never
  written anywhere.
* ``--prompt teacher`` refuses eval case files (teachers never see eval cases).
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from step6_evaluation.report import RUN_META_KEYS

RETRY_STATUS = {408, 409, 429}
PROXY_HEADERS = {"x-kyc-fallback": "fallback", "x-kyc-repaired": "repaired",
                 "x-kyc-schema-valid": "schema_valid", "x-kyc-attempts": "proxy_attempts",
                 "x-kyc-upstream-ms": "upstream_ms"}


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_jsonl(path: str | Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def _is_eval_path(path: str | Path) -> bool:
    return any(s.lower() == "eval" or s.lower().startswith(("eval_", "eval-"))
               for s in Path(path).resolve().parts)


def percentile(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    k = (len(s) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


# ---------------------------------------------------------------------------
# Request building
# ---------------------------------------------------------------------------

class RequestBuilder:
    """case packet -> chat-completions payload."""

    def __init__(self, model: str, *, prompt: str = "none", schema: str | None = None,
                 policy: str | None = None, pool: str | None = None, k: int = 2, seed: int = 0,
                 response_format: str = "schema", max_tokens: int | None = 2048,
                 max_tokens_param: str = "max_tokens", temperature: float | None = 0.0,
                 extra_body: dict | None = None, eval_manifests: list[str] | None = None,
                 frontier_prompt: bool = False, prechecks: bool = False):
        from step0_rules.prompts.render import PromptBuilder, load_examples, load_schema

        self.model = model
        self.prechecks = prechecks  # add the code-computed PRE-CHECKS block (Final B)
        self.schema = load_schema(schema) if schema else None
        self.prompt = prompt
        self.builder = None
        if frontier_prompt:
            # byte-identical to run_frontier (open-vs-frontier fairness); --schema only sets response_format
            if prompt == "none":
                raise SystemExit("--frontier-prompt needs --prompt")
            from step2_benchmarking.run_frontier import build_prompt

            self.builder = build_prompt(prompt, pool or "data/train/cases.jsonl", seed)
        elif prompt != "none":
            examples = None
            if prompt in ("baseline_best", "teacher"):
                if not pool:
                    raise SystemExit(f"--prompt {prompt} needs --pool (a DEV JSONL)")
                examples = load_examples(pool, k, seed, purpose="teacher" if prompt == "teacher" else "baseline",
                                         eval_manifests=eval_manifests or [])
            self.builder = PromptBuilder(prompt, schema=self.schema, policy=policy, examples=examples)
        if response_format == "schema":
            if self.schema is None:
                raise SystemExit("--response-format schema needs --schema")
            self.response_format: dict | None = {"type": "json_schema", "json_schema": {
                "name": "kyc_decision", "schema": self.schema, "strict": True}}
        elif response_format == "json_object":
            self.response_format = {"type": "json_object"}
        else:
            self.response_format = None
        self.max_tokens, self.max_tokens_param = max_tokens, max_tokens_param
        self.temperature = temperature
        self.extra_body = extra_body or {}

    def payload(self, packet: str) -> dict:
        msgs = self.builder.messages(packet) if self.builder else [{"role": "user", "content": packet}]
        if self.prechecks:
            from step7_serving.prechecks import apply_prechecks

            msgs = apply_prechecks(msgs)
        p: dict[str, Any] = {"model": self.model, "messages": msgs}
        if self.response_format is not None:
            p["response_format"] = self.response_format
        if self.max_tokens is not None:
            p[self.max_tokens_param] = self.max_tokens
        if self.temperature is not None:
            p["temperature"] = self.temperature
        p.update(self.extra_body)
        return p

    def provenance(self) -> dict:
        d: dict[str, Any] = {"prompt": self.prompt, "response_format": (self.response_format or {}).get("type"),
                             "max_tokens": self.max_tokens, "temperature": self.temperature,
                             "extra_body": self.extra_body, "prechecks": self.prechecks}
        if self.builder:
            d.update(self.builder.provenance())
        if self.schema is not None:
            d["schema_sha256"] = hashlib.sha256(
                json.dumps(self.schema, sort_keys=True).encode()).hexdigest()
        return d


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

class EndpointRunner:
    def __init__(self, base_url: str, api_key: str | None, *, concurrency: int = 8,
                 timeout_s: float = 600.0, max_attempts: int = 4, base_delay: float = 1.0,
                 cache_dir: str | Path | None = None, transport: httpx.AsyncBaseTransport | None = None,
                 sleep=asyncio.sleep):
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.base_url = base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.concurrency = concurrency
        self.timeout_s = timeout_s
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.transport = transport
        self.sleep = sleep
        self.cache = None
        if cache_dir is not None:
            from shared.frontier_api.clients import DiskCache

            self.cache = DiskCache(cache_dir)

    def cache_key(self, payload: dict) -> str:
        blob = json.dumps({"endpoint": self.base_url, "payload": payload}, sort_keys=True,
                          ensure_ascii=False, separators=(",", ":"))
        return "endpoint-" + hashlib.sha256(blob.encode("utf-8")).hexdigest()

    async def one(self, client: httpx.AsyncClient, case_id: Any, payload: dict) -> dict:
        key = self.cache_key(payload) if self.cache else None
        if key:
            hit = self.cache.get(key)
            if hit is not None:
                return {**hit, "case_id": case_id, "cached": True}
        err, status, attempts = None, None, 0
        for attempt in range(1, self.max_attempts + 1):
            attempts = attempt
            t0 = time.perf_counter()
            retry_after = None
            try:
                r = await client.post(self.url, json=payload, headers=self.headers)
                latency_ms = (time.perf_counter() - t0) * 1000
                status = r.status_code
                if status < 400:
                    rec = self._record(case_id, r, latency_ms, attempts)
                    if key and rec["error"] is None:
                        self.cache.put(key, {k: v for k, v in rec.items() if k != "case_id"})
                    return rec
                err = f"http {status}: {r.text[:300]}"
                if not (status in RETRY_STATUS or status >= 500):
                    break
                try:
                    retry_after = float(r.headers.get("retry-after")) if r.headers.get("retry-after") else None
                except ValueError:
                    retry_after = None
            except (httpx.TimeoutException, httpx.TransportError) as e:
                err, status = f"{type(e).__name__}: {e}", None
            if attempt < self.max_attempts:
                delay = retry_after if retry_after is not None else \
                    min(60.0, self.base_delay * 2 ** (attempt - 1)) * (0.5 + random.random() / 2)
                await self.sleep(delay)
        return {"case_id": case_id, "output": None, "latency_ms": None, "usage": None,
                "error": err, "http_status": status, "attempts": attempts, "cached": False}

    @staticmethod
    def _record(case_id: Any, r: httpx.Response, latency_ms: float, attempts: int) -> dict:
        try:
            body = r.json()
        except ValueError:
            return {"case_id": case_id, "output": None, "latency_ms": latency_ms, "usage": None,
                    "error": "response is not JSON", "http_status": r.status_code,
                    "attempts": attempts, "cached": False}
        ctype = r.headers.get("content-type", "")
        choice = (body.get("choices") or [{}])[0] if isinstance(body, dict) else {}
        msg = choice.get("message") or {}
        content = msg.get("content")
        if isinstance(content, list):
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        u = body.get("usage") or {}
        usage = {"prompt_tokens": u.get("prompt_tokens"), "completion_tokens": u.get("completion_tokens")}
        rt = (u.get("completion_tokens_details") or {}).get("reasoning_tokens")
        if rt is not None:
            usage["reasoning_tokens"] = rt
        rec = {"case_id": case_id, "output": content, "latency_ms": round(latency_ms, 2),
               "usage": usage, "error": None if content is not None else "no content in response",
               "http_status": r.status_code, "attempts": attempts,
               "finish_reason": choice.get("finish_reason"), "response_model": body.get("model"),
               "cached": False}
        if "json" not in ctype:
            rec["error"] = f"unexpected content-type {ctype!r}"
        proxy = {name: r.headers[h] for h, name in PROXY_HEADERS.items() if h in r.headers}
        if proxy:
            rec["proxy"] = proxy
        return rec

    async def run(self, items: list[tuple[Any, dict]], on_result=None) -> list[dict]:
        sem = asyncio.Semaphore(self.concurrency)
        limits = httpx.Limits(max_connections=self.concurrency, max_keepalive_connections=self.concurrency)
        async with httpx.AsyncClient(timeout=self.timeout_s, transport=self.transport, limits=limits) as client:
            async def guarded(cid, payload):
                async with sem:
                    rec = await self.one(client, cid, payload)
                if on_result:
                    on_result(rec)
                return rec

            return list(await asyncio.gather(*(guarded(c, p) for c, p in items)))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Run an OpenAI-compatible endpoint over JSONL cases.")
    ap.add_argument("--cases", required=True, help="JSONL with case id + packet (e.g. data/<split>/cases.jsonl)")
    ap.add_argument("--out", required=True, type=Path, help="run dir, e.g. outputs/<run_id>")
    ap.add_argument("--base-url", required=True, help="e.g. http://localhost:8080/v1")
    ap.add_argument("--model", required=True)
    ap.add_argument("--api-key-env", help="NAME of the env var holding the bearer token (never the token)")
    ap.add_argument("--prompt", default="none",
                    choices=["none", "student", "student_short", "baseline_zero_shot", "baseline_best", "teacher"],
                    help="none = send the bare packet (our proxy injects its own prompt)")
    ap.add_argument("--frontier-prompt", action="store_true",
                    help="build the prompt with run_frontier.build_prompt (same text as the frontier runs; "
                         "--pool defaults to data/train/cases.jsonl, k=2)")
    ap.add_argument("--schema", help="output JSON Schema (for the prompt and/or response_format)")
    ap.add_argument("--policy", help="policy file or module:<name>")
    ap.add_argument("--pool", help="DEV JSONL for few-shot examples (baseline_best / teacher)")
    ap.add_argument("--k", type=int, default=2)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--eval-manifest", action="append", default=[],
                    help="frozen eval manifest(s); few-shot examples are checked against them")
    ap.add_argument("--prechecks", action="store_true",
                    help="add the PRE-CHECKS block (step7_serving.prechecks.apply_prechecks) to every request")
    ap.add_argument("--response-format", default="schema", choices=["schema", "json_object", "none"])
    ap.add_argument("--max-tokens", type=int, default=2048)
    ap.add_argument("--max-tokens-param", default="max_tokens", choices=["max_tokens", "max_completion_tokens"])
    ap.add_argument("--temperature", type=float, default=0.0, help="use -1 to omit")
    ap.add_argument("--extra-body", default="{}", help="JSON merged into every payload")
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--timeout", type=float, default=600.0)
    ap.add_argument("--max-attempts", type=int, default=4)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--resume", action="store_true", help="keep finished cases, rerun missing/failed ones")
    ap.add_argument("--cache", action="store_true", help="reuse shared/frontier_api/ disk cache (not for latency runs)")
    ap.add_argument("--cache-dir", default="outputs/llm_cache")
    ap.add_argument("--warmup", type=int, default=0, help="untimed requests before the run (cold start)")
    ap.add_argument("--id-key", default="case_id")
    ap.add_argument("--packet-key", default="packet")
    ap.add_argument("--gold", help="gold JSONL for run.json (default: --cases if it has expected outputs)")
    ap.add_argument("--display-name", help="model name shown in the report (default --model)")
    ap.add_argument("--meta", action="append", default=[], metavar="KEY=VALUE",
                    help=f"extra run.json keys; allowed: {sorted(RUN_META_KEYS)}")
    return ap.parse_args(argv)


def _meta_value(v: str) -> Any:
    try:
        return json.loads(v)
    except ValueError:
        return v


def main(argv: list[str] | None = None, transport: httpx.AsyncBaseTransport | None = None,
         sleep=asyncio.sleep) -> int:
    a = parse_args(argv)
    if a.prompt == "teacher" and _is_eval_path(a.cases):
        raise SystemExit("refusing: teacher prompts never see eval cases")
    meta_extra = {}
    for kv in a.meta:
        k, _, v = kv.partition("=")
        if k not in RUN_META_KEYS:
            raise SystemExit(f"--meta {k}: not a run.json key step6_evaluation/report.py knows ({sorted(RUN_META_KEYS)})")
        meta_extra[k] = _meta_value(v)
    api_key = None
    if a.api_key_env:
        api_key = os.environ.get(a.api_key_env)
        if not api_key:
            try:
                from dotenv import load_dotenv
                load_dotenv(override=False)
            except ImportError:
                pass
            api_key = os.environ.get(a.api_key_env)
        if not api_key:
            raise SystemExit(f"env var {a.api_key_env} is not set")

    rb = RequestBuilder(a.model, prompt=a.prompt, schema=a.schema, policy=a.policy, pool=a.pool, k=a.k,
                        seed=a.seed, response_format=a.response_format, max_tokens=a.max_tokens,
                        max_tokens_param=a.max_tokens_param,
                        temperature=None if a.temperature < 0 else a.temperature,
                        extra_body=json.loads(a.extra_body), eval_manifests=a.eval_manifest,
                        frontier_prompt=a.frontier_prompt, prechecks=a.prechecks)
    cases = read_jsonl(a.cases)
    if a.limit:
        cases = cases[: a.limit]
    ids = [c[a.id_key] for c in cases]
    if len(set(map(str, ids))) != len(ids):
        raise SystemExit("duplicate case ids in --cases")

    a.out.mkdir(parents=True, exist_ok=True)
    pred_path = a.out / "predictions.jsonl"
    done: dict[str, dict] = {}
    if pred_path.exists():
        if not a.resume:
            raise SystemExit(f"{pred_path} exists; pass --resume to continue it or pick a new --out")
        for rec in read_jsonl(pred_path):
            if rec.get("error") is None and rec.get("output") is not None:
                done[str(rec["case_id"])] = rec
    todo = [c for c in cases if str(c[a.id_key]) not in done]

    runner = EndpointRunner(a.base_url, api_key, concurrency=a.concurrency, timeout_s=a.timeout,
                            max_attempts=a.max_attempts, cache_dir=a.cache_dir if a.cache else None,
                            transport=transport, sleep=sleep)
    # keep finished records, then append as results arrive so a crash loses nothing
    with open(pred_path, "w", encoding="utf-8") as f:
        for rec in done.values():
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    fh = open(pred_path, "a", encoding="utf-8")

    def on_result(rec: dict) -> None:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        fh.flush()

    t0 = time.perf_counter()
    try:
        if a.warmup and todo:
            warm = [(f"warmup-{i}", rb.payload(todo[0][a.packet_key])) for i in range(a.warmup)]
            asyncio.run(EndpointRunner(a.base_url, api_key, concurrency=1, timeout_s=a.timeout,
                                       max_attempts=a.max_attempts, transport=transport,
                                       sleep=sleep).run(warm))
            t0 = time.perf_counter()
        asyncio.run(runner.run([(c[a.id_key], rb.payload(c[a.packet_key])) for c in todo], on_result))
    finally:
        fh.close()
    wall = time.perf_counter() - t0

    # rewrite in input order (deterministic file), keeping the last record per case
    latest = {str(r["case_id"]): r for r in read_jsonl(pred_path)}
    ordered = [latest[str(i)] for i in ids if str(i) in latest]
    tmp = pred_path.with_suffix(".jsonl.tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in ordered), encoding="utf-8")
    os.replace(tmp, pred_path)

    # run.json for step6_evaluation/report.py (merge with an existing one)
    run_path = a.out / "run.json"
    run_meta = json.loads(run_path.read_text(encoding="utf-8")) if run_path.exists() else {}
    run_meta["model"] = a.display_name or run_meta.get("model") or a.model
    gold = a.gold or (a.cases if any("expected" in c for c in cases[:5]) else None)
    if gold:
        run_meta["gold"] = str(gold)
    run_meta.update(meta_extra)
    run_path.write_text(json.dumps(run_meta, indent=2) + "\n", encoding="utf-8")

    lat = [r["latency_ms"] for r in ordered if r.get("latency_ms") is not None and not r.get("cached")]
    errors = [r for r in ordered if r.get("error")]
    fallbacks = [r for r in ordered if (r.get("proxy") or {}).get("fallback") not in (None, "0")]
    prov = {
        "started_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "base_url": a.base_url, "model": a.model, "api_key_env": a.api_key_env,
        "cases": str(a.cases), "cases_sha256": sha256_file(a.cases), "n_cases": len(ids),
        "n_written": len(ordered), "n_errors": len(errors), "n_proxy_fallbacks": len(fallbacks),
        "n_cached": sum(1 for r in ordered if r.get("cached")), "n_resumed": len(done),
        "concurrency": a.concurrency, "warmup": a.warmup, "wall_s": round(wall, 3),
        "throughput_cases_per_s": round(len(todo) / wall, 3) if wall > 0 and todo else None,
        "latency_p50_ms": percentile(lat, 0.5), "latency_p95_ms": percentile(lat, 0.95),
        "request": rb.provenance(), "argv": sys.argv[1:] if argv is None else argv,
    }
    (a.out / "endpoint_run.json").write_text(json.dumps(prov, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"{len(ordered)}/{len(ids)} written, {len(errors)} errors, {len(fallbacks)} proxy fallbacks, "
          f"p50 {prov['latency_p50_ms'] or 0:.0f} ms, p95 {prov['latency_p95_ms'] or 0:.0f} ms -> {a.out}",
          file=sys.stderr)
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
