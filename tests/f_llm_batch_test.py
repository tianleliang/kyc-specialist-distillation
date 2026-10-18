"""Session F: shared/frontier_api/batch.py. Mock backend only."""

import json

import pytest

from shared.frontier_api.batch import BatchRunner, MockBatchBackend, custom_id_for, main
from shared.frontier_api.clients import LLMClient, make_request

SCHEMA = {"type": "object", "required": ["decision"], "additionalProperties": False,
          "properties": {"decision": {"type": "string", "enum": ["approve", "reject", "escalate"]}}}


def reqs(n, provider="anthropic", model="claude-opus-5-5"):
    return [make_request(provider, model, user=f"case {i}", json_schema=SCHEMA,
                         purpose="teacher", metadata={"case_id": i}) for i in range(n)]


@pytest.fixture
def client(tmp_path):
    return LLMClient(mock=True, cache_dir=tmp_path / "cache")


def test_end_to_end_chunks_and_batch_pricing(tmp_path, client):
    be = MockBatchBackend(client, max_per_batch=3, polls_to_finish=2)
    r = BatchRunner(tmp_path / "job", client=client, backend=be)
    assert r.add(reqs(7)) == 7
    st = r.run(poll_interval=0, sleep=lambda s: None)
    assert st["items"] == {"done": 7} and len(be.batches) == 3
    rows = r.results()
    assert len(rows) == 7 and {row["metadata"]["case_id"] for row in rows} == set(range(7))
    resp = rows[0]["response"]
    assert resp["batch"] and resp["schema_valid"]
    assert resp["cost_usd"] > 0
    # every result was written to the cache, so a live call is now free
    assert client.complete(reqs(1)[0]).cached


def test_batch_cost_is_half_live(tmp_path, client):
    r = BatchRunner(tmp_path / "job", client=client, backend=MockBatchBackend(client))
    r.add(reqs(1))
    r.run(poll_interval=0, sleep=lambda s: None)
    batch_cost = r.results()[0]["response"]["cost_usd"]
    live = LLMClient(mock=True, cache_dir=None).complete(reqs(1)[0]).cost_usd
    assert batch_cost == pytest.approx(live * 0.5)


def test_dedupe_and_cache_hits_skip_submission(tmp_path, client):
    client.complete(reqs(2)[1])  # pre-cache case 1
    be = MockBatchBackend(client)
    r = BatchRunner(tmp_path / "job", client=client, backend=be)
    assert r.add(reqs(3)) == 2       # case 1 was a cache hit
    assert r.add(reqs(3)) == 0       # re-adding is a no-op
    r.run(poll_interval=0, sleep=lambda s: None)
    assert custom_id_for(reqs(2)[1]) not in be.submitted_ids
    assert len(be.submitted_ids) == 2 and len(r.results()) == 3


def test_resume_from_disk_after_crash(tmp_path, client):
    be = MockBatchBackend(client, max_per_batch=2, polls_to_finish=3)
    r1 = BatchRunner(tmp_path / "job", client=client, backend=be)
    r1.add(reqs(4))
    r1.submit()
    r1.poll()  # still running; "process dies" here
    r2 = BatchRunner(tmp_path / "job", client=client, backend=be)  # fresh object, same dir
    assert r2.status()["items"] == {"submitted": 4}
    assert r2.submit() == 0          # nothing re-submitted
    st = r2.run(poll_interval=0, sleep=lambda s: None)
    assert st["items"] == {"done": 4} and len(be.submitted_ids) == 4


def test_item_errors_then_retry(tmp_path, client):
    bad = custom_id_for(reqs(3)[2])
    be = MockBatchBackend(client, fail_ids={bad})
    r = BatchRunner(tmp_path / "job", client=client, backend=be)
    r.add(reqs(3))
    st = r.run(poll_interval=0, sleep=lambda s: None)
    assert st["items"] == {"done": 2, "error": 1}
    be.fail_ids.clear()
    assert r.retry_errors() == 1
    st = r.run(poll_interval=0, sleep=lambda s: None)
    assert st["items"] == {"done": 3} and be.submitted_ids.count(bad) == 2


def test_failed_batch_marks_items_error(tmp_path, client):
    r = BatchRunner(tmp_path / "job", client=client, backend=MockBatchBackend(client, fail_batches=True))
    r.add(reqs(2))
    st = r.run(poll_interval=0, sleep=lambda s: None)
    assert st["items"] == {"error": 2} and st["chunks"]["failed"] == 1


def test_one_provider_per_job(tmp_path, client):
    r = BatchRunner(tmp_path / "job", client=client, backend=MockBatchBackend(client))
    r.add(reqs(1))
    with pytest.raises(ValueError):
        r.add(reqs(1, provider="openai", model="gpt-6-astra"))


def test_groups_by_model(tmp_path, client):
    be = MockBatchBackend(client, max_per_batch=10)
    r = BatchRunner(tmp_path / "job", client=client, backend=be)
    r.add(reqs(2, model="claude-opus-5-5") + reqs(2, model="claude-sonnet-5-5"))
    r.submit()
    assert sorted(c["model"] for c in r.state["chunks"]) == ["claude-opus-5-5", "claude-sonnet-5-5"]


def test_guard_applies_to_batch(tmp_path):
    class Guard:
        def check(self, text):
            raise RuntimeError("eval overlap")

    c = LLMClient(mock=True, cache_dir=None, guard=Guard())
    r = BatchRunner(tmp_path / "job", client=c, backend=MockBatchBackend(c))
    with pytest.raises(RuntimeError):
        r.add(reqs(1))


def test_custom_id_rules():
    cid = custom_id_for(reqs(1)[0])
    assert len(cid) <= 64 and cid.replace("-", "").replace("_", "").isalnum()


def test_cli_run_and_status(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)  # cache dir is relative (outputs/llm_cache)
    p = tmp_path / "reqs.jsonl"
    p.write_text("\n".join(json.dumps(r.to_dict()) for r in reqs(3)))
    assert main(["run", "--job", str(tmp_path / "job"), "--requests", str(p), "--mock", "--poll", "0"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["items"] == {"done": 3}
    assert main(["status", "--job", str(tmp_path / "job"), "--mock"]) == 0
