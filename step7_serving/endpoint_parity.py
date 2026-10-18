"""Local dry run of the deployed endpoint path, no GPU, no network: does the proxy send vLLM the
exact request the frozen-eval runs of Final B sent?

    python -m step7_serving.endpoint_parity [--cases data/dev/cases.jsonl] [--n 20] [--prechecks 1]

The frozen-eval runs called raw vLLM through ``step2_benchmarking/run_endpoint.py --prompt student_short
--schema step0_rules/schema/v1_serving.json --prechecks``. The hand-over endpoint is the proxy
(``step7_serving/modal_vllm.py`` ``proxy``) in front of the same vLLM, called with a bare packet. This
builds the proxy app exactly as Modal does (``proxy_config.example.yaml``, ``ZORBE_PRECHECKS``) with a
capturing fake upstream, sends N packets as a customer would (bearer token, bare packet, no prompt,
no response_format) and checks, per case, that the upstream request equals run_endpoint's request:
messages (system prompt, student user template, PRE-CHECKS block), response_format schema,
max_tokens, temperature. Also checks: no token -> 401, wrong token -> 401, the response is valid v1.

A throwaway token is generated in-process; no real secret is read or printed.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cases", default="data/dev/cases.jsonl")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--prechecks", choices=["0", "1"], default="1", help="ZORBE_PRECHECKS (1 = Final B)")
    a = ap.parse_args(argv)
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    if "/eval" in a.cases.replace("\\", "/"):
        raise SystemExit("use dev or train cases; eval packets are not used for serving checks")
    token = secrets.token_urlsafe(24)
    os.environ["PROXY_API_KEYS"] = token
    os.environ["ZORBE_PRECHECKS"] = a.prechecks

    from fastapi.testclient import TestClient

    from step2_benchmarking.run_endpoint import RequestBuilder
    from step6_evaluation import metrics as M
    from step7_serving.proxy import ProxyConfig, create_app

    cases = M.read_jsonl(a.cases)[: a.n]
    by_packet = {c["packet"]: c for c in cases}
    sent: list[dict] = []

    async def upstream(payload: dict) -> dict:
        sent.append(payload)
        user = next(m for m in reversed(payload["messages"]) if m["role"] == "user")["content"]
        case = next(c for p, c in by_packet.items() if p in user)
        return {"id": "fake", "object": "chat.completion", "created": 0, "model": "final-B",
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant", "content": json.dumps(case["expected"])}}],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}

    cfg = ProxyConfig.load(ROOT / "step7_serving" / "proxy_config.example.yaml",
                           upstream_url="http://fake/v1", upstream_model="final-B", upstream_api_key_env=None)
    client = TestClient(create_app(cfg, upstream=upstream))
    ref = RequestBuilder("final-B", prompt="student_short", schema="step0_rules/schema/v1_serving.json",
                         prechecks=a.prechecks == "1")
    validator = M.make_validator(ROOT / "step0_rules" / "schema" / "v1.json")

    body = {"model": "zorbe-kyc", "messages": [{"role": "user", "content": cases[0]["packet"]}]}
    s_none = client.post("/v1/chat/completions", json=body).status_code
    s_bad = client.post("/v1/chat/completions", json=body, headers={"Authorization": "Bearer wrong"}).status_code
    sent.clear()
    same_msgs = same_rf = same_params = valid = 0
    for c in cases:
        r = client.post("/v1/chat/completions", headers={"Authorization": f"Bearer {token}"},
                        json={"model": "zorbe-kyc", "messages": [{"role": "user", "content": c["packet"]}]})
        out = r.json()["choices"][0]["message"]["content"] if r.status_code == 200 else None
        valid += out is not None and validator(json.loads(out)) is None
        up, want = sent[-1], ref.payload(c["packet"])
        same_msgs += up["messages"] == want["messages"]
        same_rf += up["response_format"]["json_schema"]["schema"] == want["response_format"]["json_schema"]["schema"]
        same_params += (up.get("max_tokens"), up.get("temperature")) == (want["max_tokens"], want["temperature"])
    n = len(cases)
    has_pre = sum("PRE-CHECKS" in json.dumps(p["messages"]) for p in sent)
    print(f"auth: no token -> {s_none}, wrong token -> {s_bad}")
    print(f"ZORBE_PRECHECKS={a.prechecks}: PRE-CHECKS block present in {has_pre}/{n} upstream requests")
    print(f"messages identical to run_endpoint (frozen-eval path): {same_msgs}/{n}")
    print(f"response_format schema identical (v1_serving): {same_rf}/{n}")
    print(f"max_tokens / temperature identical: {same_params}/{n}")
    print(f"proxy response valid under published v1.json: {valid}/{n}")
    ok = (s_none == 401 and s_bad == 401 and same_msgs == same_rf == same_params == valid == n
          and has_pre == (n if a.prechecks == "1" else 0))
    print("PARITY OK" if ok else "PARITY FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
