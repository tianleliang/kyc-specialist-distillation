"""Session I: step2_benchmarking/run_endpoint.py with mock transports (no network)."""

import asyncio
import json
from pathlib import Path

import pytest

httpx = pytest.importorskip("httpx")

from step6_evaluation import metrics as M  # noqa: E402
from step6_evaluation import report as R  # noqa: E402
from step2_benchmarking import run_endpoint as E  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
from tests.l_v1_cases import FIELDMAP_V1, POLICY_V1, V1_SCHEMA, v1_cases  # noqa: E402

V0 = V1_SCHEMA            # name kept; the cases and schema are v1 since Session L
FIELDMAP = FIELDMAP_V1
CASES = [json.loads(json.dumps(c)) for c in v1_cases()]
BY_PACKET = {c["packet"]: c["expected"] for c in CASES}


async def no_sleep(_):
    return None


def completion(content, prompt_tokens=100, completion_tokens=40):
    return {"id": "x", "object": "chat.completion", "model": "m",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens}}


def oracle_for(text):
    for packet, exp in BY_PACKET.items():
        if packet in text:
            return exp
    raise AssertionError("unknown packet")


class Oracle:
    """httpx handler: answers each packet with its gold output; counts calls and concurrency."""

    def __init__(self, fail_first=None):
        self.calls = 0
        self.inflight = 0
        self.max_inflight = 0
        self.bodies = []
        self.fail_first = dict(fail_first or {})  # case index -> list of status codes to return first

    async def __call__(self, request):
        self.calls += 1
        self.inflight += 1
        self.max_inflight = max(self.max_inflight, self.inflight)
        try:
            await asyncio.sleep(0.005)
            body = json.loads(request.content)
            self.bodies.append(body)
            user = body["messages"][-1]["content"]
            for i, c in enumerate(CASES):
                if c["packet"] in user and self.fail_first.get(i):
                    status = self.fail_first[i].pop(0)
                    return httpx.Response(status, json={"error": {"message": "nope"}},
                                          headers={"retry-after": "0"})
            return httpx.Response(200, json=completion(json.dumps(oracle_for(user))))
        finally:
            self.inflight -= 1


def write_cases(tmp_path, sub="dev"):
    p = tmp_path / "data" / sub / "cases.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(c) + "\n" for c in CASES), encoding="utf-8")
    return p


def base_args(cases, out, *extra):
    return ["--cases", str(cases), "--out", str(out), "--base-url", "http://test/v1", "--model", "m",
            "--schema", str(V0), *extra]


def test_oracle_run_writes_report_format_and_scores_100(tmp_path):
    cases = write_cases(tmp_path)
    h = Oracle()
    out = tmp_path / "outputs" / "oracle"
    rc = E.main(base_args(cases, out, "--concurrency", "3", "--meta", "params=\"0.8B\"", "--meta", "stage=sft"),
                transport=httpx.MockTransport(h), sleep=no_sleep)
    assert rc == 0 and h.calls == len(CASES)
    assert 1 < h.max_inflight <= 3  # concurrency is used and respected
    recs = [json.loads(l) for l in (out / "predictions.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["case_id"] for r in recs] == [c["case_id"] for c in CASES]  # input order
    r0 = recs[0]
    assert set(r0) >= {"case_id", "output", "latency_ms", "usage"} and isinstance(r0["output"], str)
    assert r0["usage"] == {"prompt_tokens": 100, "completion_tokens": 40} and r0["latency_ms"] > 0
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run == {"model": "m", "gold": str(cases), "params": "0.8B", "stage": "sft"}
    prov = json.loads((out / "endpoint_run.json").read_text(encoding="utf-8"))
    assert prov["n_errors"] == 0 and prov["latency_p95_ms"] >= prov["latency_p50_ms"] > 0
    assert len(prov["cases_sha256"]) == 64 and prov["request"]["response_format"] == "json_schema"
    # payload shape
    b = h.bodies[0]
    assert b["model"] == "m" and b["response_format"]["json_schema"]["strict"] is True
    assert b["max_tokens"] == 2048 and b["temperature"] == 0.0 and b["messages"][0]["role"] == "user"
    # step6_evaluation/report.py reads it unchanged and the oracle scores 100%
    fm = M.FieldMap.load(FIELDMAP)
    fm.schema_path = str(V0)
    runs = R.load_runs([tmp_path / "outputs"], fm, None, M.DEFAULT_PRICES)
    agg = M.aggregate(runs[0].scores, fm)
    assert agg["schema_validity"] == 1.0 and agg["decision_accuracy"] == 1.0 and agg["field_accuracy_mean"] == 1.0
    assert agg["latency_p50_ms"] > 0
    assert R.main([str(tmp_path / "outputs"), "--config", str(FIELDMAP), "--schema", str(V0),
                   "--n-boot", "20", "--out", str(tmp_path / "t.md")]) == 0


def test_retries_then_records_failures_without_dropping(tmp_path):
    cases = write_cases(tmp_path)
    h = Oracle(fail_first={0: [503, 429], 1: [400], 2: [500, 500, 500, 500]})
    out = tmp_path / "o"
    rc = E.main(base_args(cases, out, "--max-attempts", "4"), transport=httpx.MockTransport(h), sleep=no_sleep)
    assert rc == 2  # some errors
    recs = {r["case_id"]: r for r in map(json.loads, (out / "predictions.jsonl").read_text(encoding="utf-8").splitlines())}
    assert len(recs) == len(CASES)
    assert recs[CASES[0]["case_id"]]["error"] is None and recs[CASES[0]["case_id"]]["attempts"] == 3
    assert recs[CASES[1]["case_id"]]["output"] is None and recs[CASES[1]["case_id"]]["attempts"] == 1  # 400: no retry
    assert recs[CASES[2]["case_id"]]["output"] is None and recs[CASES[2]["case_id"]]["http_status"] == 500
    # resume: only the two failed cases are re-sent
    h2 = Oracle()
    assert E.main(base_args(cases, out, "--resume"), transport=httpx.MockTransport(h2), sleep=no_sleep) == 0
    assert h2.calls == 2
    recs = [json.loads(l) for l in (out / "predictions.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(recs) == len(CASES) and all(r["error"] is None for r in recs)
    assert json.loads((out / "endpoint_run.json").read_text(encoding="utf-8"))["n_resumed"] == len(CASES) - 2


def test_refuses_to_overwrite_without_resume(tmp_path):
    cases = write_cases(tmp_path)
    out = tmp_path / "o"
    E.main(base_args(cases, out), transport=httpx.MockTransport(Oracle()), sleep=no_sleep)
    with pytest.raises(SystemExit, match="--resume"):
        E.main(base_args(cases, out), transport=httpx.MockTransport(Oracle()), sleep=no_sleep)


def test_timeouts_are_retried(tmp_path):
    cases = write_cases(tmp_path)
    n = {"calls": 0}

    def handler(request):
        n["calls"] += 1
        if n["calls"] == 1:
            raise httpx.ReadTimeout("slow", request=request)
        return httpx.Response(200, json=completion(json.dumps(oracle_for(json.loads(request.content)["messages"][-1]["content"]))))

    out = tmp_path / "o"
    assert E.main(base_args(cases, out, "--limit", "1"), transport=httpx.MockTransport(handler), sleep=no_sleep) == 0
    rec = json.loads((out / "predictions.jsonl").read_text(encoding="utf-8"))
    assert rec["attempts"] == 2 and rec["error"] is None


def test_cache_makes_reruns_free(tmp_path):
    cases = write_cases(tmp_path)
    h = Oracle()
    args = ["--cache", "--cache-dir", str(tmp_path / "cache"), "--limit", "4"]
    E.main(base_args(cases, tmp_path / "a", *args), transport=httpx.MockTransport(h), sleep=no_sleep)
    assert h.calls == 4
    E.main(base_args(cases, tmp_path / "b", *args), transport=httpx.MockTransport(h), sleep=no_sleep)
    assert h.calls == 4
    recs = [json.loads(l) for l in (tmp_path / "b" / "predictions.jsonl").read_text(encoding="utf-8").splitlines()]
    assert all(r["cached"] for r in recs) and recs[0]["latency_ms"] > 0
    assert json.loads((tmp_path / "b" / "endpoint_run.json").read_text(encoding="utf-8"))["latency_p50_ms"] is None


def test_api_key_is_sent_but_never_written(tmp_path, monkeypatch):
    cases = write_cases(tmp_path)
    monkeypatch.setenv("I_TEST_KEY", "sk-secret-value-xyz")
    seen = []

    def handler(request):
        seen.append(request.headers.get("authorization"))
        return httpx.Response(200, json=completion(json.dumps(CASES[0]["expected"])))

    out = tmp_path / "o"
    E.main(base_args(cases, out, "--limit", "2", "--api-key-env", "I_TEST_KEY"),
           transport=httpx.MockTransport(handler), sleep=no_sleep)
    assert seen == ["Bearer sk-secret-value-xyz"] * 2
    for f in out.iterdir():
        assert "sk-secret-value-xyz" not in f.read_text(encoding="utf-8")
    monkeypatch.delenv("I_TEST_KEY")
    monkeypatch.setattr("dotenv.load_dotenv", lambda **kw: None, raising=False)
    with pytest.raises(SystemExit, match="I_TEST_KEY"):
        E.main(base_args(cases, tmp_path / "p", "--api-key-env", "I_TEST_KEY"))


def test_guards(tmp_path):
    ev = write_cases(tmp_path, "eval_id")
    with pytest.raises(SystemExit, match="teacher"):
        E.main(base_args(ev, tmp_path / "o", "--prompt", "teacher"))
    with pytest.raises(SystemExit, match="run.json key"):
        E.main(base_args(ev, tmp_path / "o", "--meta", "secret=1"))


def test_prompt_templates_are_applied(tmp_path):
    cases = write_cases(tmp_path)
    h = Oracle()
    E.main(base_args(cases, tmp_path / "o", "--limit", "1", "--prompt", "student", "--policy", str(POLICY_V1),
                     "--response-format", "none", "--temperature", "-1", "--max-tokens-param", "max_completion_tokens",
                     "--extra-body", '{"chat_template_kwargs": {"enable_thinking": false}}'),
           transport=httpx.MockTransport(h), sleep=no_sleep)
    b = h.bodies[0]
    assert [m["role"] for m in b["messages"]] == ["system", "user"] and "Decision policy" in b["messages"][0]["content"]
    assert "response_format" not in b and "temperature" not in b and b["max_completion_tokens"] == 2048
    assert b["chat_template_kwargs"] == {"enable_thinking": False}
    prov = json.loads((tmp_path / "o" / "endpoint_run.json").read_text(encoding="utf-8"))["request"]
    assert prov["template"] == "student" and len(prov["template_sha256"]) == 64


def test_end_to_end_through_proxy(tmp_path, monkeypatch):
    """run_endpoint (bare packets) -> step7_serving/proxy.py (ASGI) -> mock upstream oracle."""
    pytest.importorskip("fastapi")
    from step7_serving.proxy import ProxyConfig, create_app

    monkeypatch.setenv("PROXY_API_KEYS", "tok")
    monkeypatch.setenv("I_PROXY_KEY", "tok")
    calls = []

    async def upstream(payload):
        calls.append(payload)
        user = payload["messages"][-1]["content"]
        out = oracle_for(user) if len(calls) % 5 else "garbage"  # every 5th call is invalid -> retry
        return completion(out if isinstance(out, str) else json.dumps(out))

    app = create_app(ProxyConfig.load(ROOT / "step7_serving" / "proxy_config.example.yaml", upstream_model="u"),
                     upstream=upstream)
    cases = write_cases(tmp_path)
    out = tmp_path / "outputs" / "ours"
    rc = E.main(["--cases", str(cases), "--out", str(out), "--base-url", "http://proxy/v1", "--model", "zorbe-kyc",
                 "--api-key-env", "I_PROXY_KEY", "--prompt", "none", "--response-format", "none", "--concurrency", "1"],
                transport=httpx.ASGITransport(app=app), sleep=no_sleep)
    assert rc == 0
    recs = [json.loads(l) for l in (out / "predictions.jsonl").read_text(encoding="utf-8").splitlines()]
    assert all(r["proxy"]["fallback"] == "0" and r["proxy"]["schema_valid"] == "1" for r in recs)
    assert any(r["proxy"]["proxy_attempts"] == "2" for r in recs)
    assert all(json.loads(r["output"]) == BY_PACKET[c["packet"]] for r, c in zip(recs, CASES))
    assert all(p["messages"][0]["role"] == "system" for p in calls)


@pytest.mark.parametrize("prompt", ["baseline_zero_shot", "baseline_best"])
def test_frontier_prompt_is_byte_identical(tmp_path, monkeypatch, prompt):
    """--frontier-prompt sends exactly the system + user text run_frontier sends (open vs frontier fairness)."""
    if not (ROOT / "data" / "train" / "cases.jsonl").exists():
        pytest.skip("data/train not built")
    from step2_benchmarking.run_frontier import build_prompt

    h = Oracle()
    cases = write_cases(tmp_path)
    serving = ROOT / "step0_rules" / "schema" / "v1_serving.json"
    monkeypatch.chdir(ROOT)  # run_frontier paths are repo-relative
    E.main(["--cases", str(cases), "--out", str(tmp_path / "o"), "--base-url", "http://x/v1", "--model", "m",
            "--prompt", prompt, "--frontier-prompt", "--schema", str(serving), "--limit", "1"],
           transport=httpx.MockTransport(h), sleep=no_sleep)
    rp = build_prompt(prompt, "data/train/cases.jsonl", 0).render(CASES[0]["packet"])
    b = h.bodies[0]
    assert b["messages"] == [{"role": "system", "content": rp.system}, {"role": "user", "content": rp.user}]
    assert b["response_format"]["json_schema"]["schema"] == json.loads(serving.read_text(encoding="utf-8"))
