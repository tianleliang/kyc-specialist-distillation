"""Submit / poll / collect for the OpenAI, Anthropic and Gemini batch APIs (50% off),
with all state on disk so a killed process resumes where it stopped.

    from shared.frontier_api.batch import BatchRunner
    runner = BatchRunner("outputs/batches/teacher_gpt_v1", client=LLMClient())
    runner.add(requests)          # list[LLMRequest], one provider; cache hits are filled in free
    runner.run(poll_interval=60)  # submit -> poll -> collect until every chunk is terminal
    rows = runner.results()       # one dict per request: custom_id, metadata, response

CLI (requests.jsonl holds one LLMRequest dict per line):
    python -m shared.frontier_api.batch run    --job outputs/batches/NAME --requests reqs.jsonl [--mock]
    python -m shared.frontier_api.batch resume --job outputs/batches/NAME [--mock]
    python -m shared.frontier_api.batch status --job outputs/batches/NAME

Job directory layout:
    requests.jsonl   every request added, keyed by custom_id (written once, append-only)
    state.json       item statuses and chunk -> provider batch id (rewritten atomically)
    results.jsonl    one row per finished request (append-only)

Every finished response is also written to the LLMClient disk cache, so a later live call
with the same request is free. custom_id is derived from the request hash, so adding the
same request twice is a no-op and ids satisfy every provider's id rules.
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from shared.frontier_api.clients import LLMClient, LLMRequest, LLMResponse, MockProvider

log = logging.getLogger(__name__)

RUNNING, SUCCEEDED, FAILED = "running", "succeeded", "failed"


# ---------------------------------------------------------------------------
# Backends: submit(items, model) -> batch_id; status(batch_id) -> RUNNING|SUCCEEDED|FAILED;
# fetch(batch_id) -> {custom_id: ("ok", raw_dict) | ("error", message)}
# ---------------------------------------------------------------------------

class BatchBackend:
    provider = ""
    max_per_batch = 1000

    def submit(self, items: list[tuple[str, dict]], model: str) -> str:
        raise NotImplementedError

    def status(self, batch_id: str) -> str:
        raise NotImplementedError

    def fetch(self, batch_id: str) -> dict[str, tuple[str, Any]]:
        raise NotImplementedError


class OpenAIBatchBackend(BatchBackend):
    provider = "openai"
    max_per_batch = 5000  # API limit is 50k requests / 200 MB per file

    def __init__(self, client: LLMClient):
        self.sdk = client.providers["openai"].client()

    def submit(self, items, model):
        lines = "\n".join(json.dumps({"custom_id": cid, "method": "POST",
                                      "url": "/v1/chat/completions", "body": kw})
                          for cid, kw in items)
        f = self.sdk.files.create(file=("batch.jsonl", io.BytesIO(lines.encode())), purpose="batch")
        return self.sdk.batches.create(input_file_id=f.id, endpoint="/v1/chat/completions",
                                       completion_window="24h").id

    def status(self, batch_id):
        b = self.sdk.batches.retrieve(batch_id)
        if b.status == "completed":
            return SUCCEEDED
        if b.status in ("failed", "expired", "cancelled"):
            # expired/cancelled batches still return the requests that did finish
            return SUCCEEDED if (b.output_file_id or b.error_file_id) else FAILED
        return RUNNING

    def fetch(self, batch_id):
        b = self.sdk.batches.retrieve(batch_id)
        out: dict[str, tuple[str, Any]] = {}
        for fid in (b.output_file_id, b.error_file_id):
            if not fid:
                continue
            for line in self.sdk.files.content(fid).text.splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                resp = row.get("response") or {}
                if resp.get("status_code") == 200 and not row.get("error"):
                    out[row["custom_id"]] = ("ok", resp["body"])
                else:
                    out[row["custom_id"]] = ("error", json.dumps(row.get("error") or resp.get("body")))
        return out


class AnthropicBatchBackend(BatchBackend):
    provider = "anthropic"
    max_per_batch = 5000  # API limit is 100k requests / 256 MB

    def __init__(self, client: LLMClient):
        self.sdk = client.providers["anthropic"].client()

    def submit(self, items, model):
        return self.sdk.messages.batches.create(
            requests=[{"custom_id": cid, "params": kw} for cid, kw in items]).id

    def status(self, batch_id):
        b = self.sdk.messages.batches.retrieve(batch_id)
        return SUCCEEDED if b.processing_status == "ended" else RUNNING

    def fetch(self, batch_id):
        out: dict[str, tuple[str, Any]] = {}
        for r in self.sdk.messages.batches.results(batch_id):  # any order: key by custom_id
            if r.result.type == "succeeded":
                out[r.custom_id] = ("ok", r.result.message.model_dump())
            else:
                err = getattr(r.result, "error", None)
                out[r.custom_id] = ("error", f"{r.result.type}: {err}")
        return out


class GeminiBatchBackend(BatchBackend):
    provider = "gemini"
    max_per_batch = 500  # inline requests cap at 20 MB; small chunks also respect the
                         # Tier-1 $10-per-10-min spend cap noted in the research brief

    def __init__(self, client: LLMClient):
        self.sdk = client.providers["gemini"].client()
        self._order: dict[str, list[str]] = {}

    def submit(self, items, model):
        src = [{"contents": kw["contents"], "config": kw["config"], "metadata": {"key": cid}}
               for cid, kw in items]
        job = self.sdk.batches.create(model=model, src=src,
                                      config={"display_name": f"zorbe-{items[0][0][:12]}"})
        self._order[job.name] = [cid for cid, _ in items]
        return job.name

    def status(self, batch_id):
        state = self.sdk.batches.get(name=batch_id).state.name
        if state in ("JOB_STATE_SUCCEEDED", "JOB_STATE_PARTIALLY_SUCCEEDED"):
            return SUCCEEDED
        if state in ("JOB_STATE_FAILED", "JOB_STATE_CANCELLED", "JOB_STATE_EXPIRED"):
            return FAILED
        return RUNNING

    def fetch(self, batch_id, order: list[str] | None = None):
        job = self.sdk.batches.get(name=batch_id)
        order = order or self._order.get(batch_id) or []
        out: dict[str, tuple[str, Any]] = {}
        for i, r in enumerate(job.dest.inlined_responses or []):
            cid = (r.metadata or {}).get("key") or (order[i] if i < len(order) else None)
            if cid is None:
                continue
            if r.response is not None:
                out[cid] = ("ok", r.response.model_dump(mode="json"))
            else:
                out[cid] = ("error", str(r.error))
        return out


class MockBatchBackend(BatchBackend):
    """In-process fake. Finishes after `polls_to_finish` status calls; ids in `fail_ids`
    come back as per-item errors; `fail_batches=True` makes whole batches fail.
    Its batches live in memory, so `resume` across processes only works with real backends."""

    provider = "mock"

    def __init__(self, client: LLMClient, *, max_per_batch: int = 3, polls_to_finish: int = 1,
                 fail_ids: set[str] | None = None, fail_batches: bool = False):
        self.client = client
        self.max_per_batch = max_per_batch
        self.polls_to_finish = polls_to_finish
        self.fail_ids = fail_ids or set()
        self.fail_batches = fail_batches
        self.batches: dict[str, dict] = {}
        self.submitted_ids: list[str] = []

    def submit(self, items, model):
        bid = f"mockbatch-{len(self.batches)}"
        self.batches[bid] = {"items": list(items), "polls": 0}
        self.submitted_ids += [cid for cid, _ in items]
        return bid

    def status(self, batch_id):
        b = self.batches[batch_id]
        b["polls"] += 1
        if b["polls"] < self.polls_to_finish:
            return RUNNING
        return FAILED if self.fail_batches else SUCCEEDED

    def fetch(self, batch_id):
        mock: MockProvider = self.client._mock_provider
        out = {}
        for cid, kw in self.batches[batch_id]["items"]:
            if cid in self.fail_ids:
                out[cid] = ("error", "mock item failure")
            else:
                out[cid] = ("ok", mock.send(kw, kw["_request"]))
        return out


BACKENDS = {"openai": OpenAIBatchBackend, "anthropic": AnthropicBatchBackend,
            "gemini": GeminiBatchBackend}


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def custom_id_for(req: LLMRequest) -> str:
    return "r" + req.cache_key()[:40]  # <=64 chars, [a-zA-Z0-9_-]: valid on all three APIs


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


class BatchRunner:
    def __init__(self, job_dir: str | Path, client: LLMClient | None = None,
                 backend: BatchBackend | None = None):
        self.dir = Path(job_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.client = client or LLMClient()
        self._backend = backend
        self.state_path = self.dir / "state.json"
        self.requests_path = self.dir / "requests.jsonl"
        self.results_path = self.dir / "results.jsonl"
        if self.state_path.exists():
            self.state = json.loads(self.state_path.read_text())
        else:
            self.state = {"provider": None, "items": {}, "chunks": []}
        self._requests: dict[str, LLMRequest] | None = None

    # -- persistence -------------------------------------------------------
    def save(self) -> None:
        _atomic_write(self.state_path, json.dumps(self.state, indent=1))

    def requests(self) -> dict[str, LLMRequest]:
        if self._requests is None:
            self._requests = {}
            if self.requests_path.exists():
                for line in self.requests_path.read_text().splitlines():
                    if line.strip():
                        row = json.loads(line)
                        self._requests[row["custom_id"]] = LLMRequest.from_dict(row["request"])
        return self._requests

    def _append_result(self, cid: str, resp: LLMResponse) -> None:
        with self.results_path.open("a") as f:
            f.write(json.dumps({"custom_id": cid, "metadata": resp.metadata,
                                "response": resp.to_dict()}, ensure_ascii=False) + "\n")

    @property
    def backend(self) -> BatchBackend:
        if self._backend is None:
            if self.client.mock:
                self._backend = MockBatchBackend(self.client)
            else:
                self._backend = BACKENDS[self.state["provider"]](self.client)
        return self._backend

    # -- lifecycle -------------------------------------------------------
    def add(self, reqs: list[LLMRequest]) -> int:
        """Register requests. Duplicates are skipped; cache hits are completed immediately.
        Returns the number of newly pending requests."""
        known = self.requests()
        added = 0
        with self.requests_path.open("a") as f:
            for req in reqs:
                prov = self.state["provider"] or req.provider
                if req.provider != prov:
                    raise ValueError(f"one provider per job: {prov} vs {req.provider}")
                self.state["provider"] = prov
                if self.client.guard is not None and req.purpose == "teacher":
                    self.client.guard.check(req.all_text())
                cid = custom_id_for(req)
                if cid in known:
                    continue
                known[cid] = req
                f.write(json.dumps({"custom_id": cid, "request": req.to_dict()},
                                   ensure_ascii=False) + "\n")
                item = {"status": "pending", "chunk": None, "error": None}
                self.state["items"][cid] = item
                hit = self._cache_get(req)
                if hit is not None:
                    self._append_result(cid, hit)
                    item["status"] = "done"
                    continue
                added += 1
        self.save()
        return added

    def _cache_key(self, req: LLMRequest) -> str:
        return ("mock-" if self.client.mock else "") + req.cache_key()

    def _cache_get(self, req: LLMRequest) -> LLMResponse | None:
        if self.client.cache is None:
            return None
        hit = self.client.cache.get(self._cache_key(req))
        if hit is None:
            return None
        resp = LLMResponse.from_dict(hit)
        resp.cached, resp.metadata = True, dict(req.metadata)
        self.client.ledger.record(resp)
        return resp

    def submit(self) -> int:
        """Submit every pending item, grouped by model, in chunks. State is saved after each
        chunk, so a crash mid-submit never double-submits a finished chunk."""
        reqs = self.requests()
        pending = [cid for cid, it in self.state["items"].items() if it["status"] == "pending"]
        by_model: dict[str, list[str]] = {}
        for cid in pending:
            by_model.setdefault(reqs[cid].model, []).append(cid)
        prov = self.client.provider_for(next(iter(reqs.values()))) if reqs else None
        n = 0
        for model, cids in by_model.items():
            step = self.backend.max_per_batch
            for i in range(0, len(cids), step):
                chunk_ids = cids[i:i + step]
                items = []
                for cid in chunk_ids:
                    kw = prov.build(reqs[cid])
                    if isinstance(self.backend, MockBatchBackend):
                        kw["_request"] = reqs[cid]
                    items.append((cid, kw))
                batch_id = self.backend.submit(items, model)
                self.state["chunks"].append({"batch_id": batch_id, "model": model,
                                             "ids": chunk_ids, "status": RUNNING,
                                             "collected": False, "submitted_at": time.time()})
                for cid in chunk_ids:
                    self.state["items"][cid].update(status="submitted",
                                                    chunk=len(self.state["chunks"]) - 1)
                self.save()
                n += len(chunk_ids)
                log.info("submitted %s (%d requests, model %s)", batch_id, len(chunk_ids), model)
        return n

    def poll(self) -> None:
        for ch in self.state["chunks"]:
            if ch["status"] == RUNNING:
                ch["status"] = self.backend.status(ch["batch_id"])
        self.save()

    def collect(self) -> int:
        reqs = self.requests()
        prov = self.client.provider_for(next(iter(reqs.values()))) if reqs else None
        n = 0
        for ch in self.state["chunks"]:
            if ch["collected"] or ch["status"] == RUNNING:
                continue
            got = self.backend.fetch(ch["batch_id"]) if ch["status"] == SUCCEEDED else {}
            for cid in ch["ids"]:
                item = self.state["items"][cid]
                kind, payload = got.get(cid, ("error", f"missing from batch ({ch['status']})"))
                if kind == "ok":
                    req = reqs[cid]
                    key = self._cache_key(req)
                    resp = self.client.finish(req, key, prov, payload, batch=True)
                    if self.client.cache is not None:
                        self.client.cache.put(key, resp.to_dict())
                    self.client.ledger.record(resp)
                    self._append_result(cid, resp)
                    item.update(status="done", error=None)
                    n += 1
                else:
                    item.update(status="error", error=str(payload)[:500])
            ch["collected"] = True
            self.save()
        return n

    def retry_errors(self) -> int:
        """Move errored items back to pending so the next submit() resends them."""
        n = 0
        for it in self.state["items"].values():
            if it["status"] == "error":
                it.update(status="pending", chunk=None)
                n += 1
        self.save()
        return n

    def done(self) -> bool:
        return all(ch["collected"] for ch in self.state["chunks"]) and not any(
            it["status"] in ("pending", "submitted") for it in self.state["items"].values())

    def run(self, poll_interval: float = 60.0, timeout: float | None = None,
            sleep=time.sleep) -> dict:
        self.submit()
        t0 = time.monotonic()
        while True:
            self.poll()
            self.collect()
            if self.done():
                return self.status()
            if timeout is not None and time.monotonic() - t0 > timeout:
                log.warning("timeout; state saved, resume later")
                return self.status()
            sleep(poll_interval)

    def status(self) -> dict:
        counts: dict[str, int] = {}
        for it in self.state["items"].values():
            counts[it["status"]] = counts.get(it["status"], 0) + 1
        return {"provider": self.state["provider"], "items": counts,
                "chunks": {s: sum(c["status"] == s for c in self.state["chunks"])
                           for s in (RUNNING, SUCCEEDED, FAILED)},
                "spend": self.client.ledger.summary()}

    def results(self) -> list[dict]:
        """Latest row per custom_id (a retried item may appear twice in results.jsonl)."""
        rows: dict[str, dict] = {}
        if self.results_path.exists():
            for line in self.results_path.read_text().splitlines():
                if line.strip():
                    row = json.loads(line)
                    rows[row["custom_id"]] = row
        return list(rows.values())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("cmd", choices=["run", "resume", "status"])
    ap.add_argument("--job", required=True)
    ap.add_argument("--requests", help="JSONL of LLMRequest dicts (run only)")
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--poll", type=float, default=60.0)
    ap.add_argument("--timeout", type=float, default=None)
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    runner = BatchRunner(a.job, client=LLMClient(mock=a.mock or None))
    if a.cmd == "run":
        if not a.requests:
            ap.error("run needs --requests")
        reqs = [LLMRequest.from_dict(json.loads(l))
                for l in Path(a.requests).read_text().splitlines() if l.strip()]
        runner.add(reqs)
    if a.cmd == "resume":
        runner.retry_errors()
    if a.cmd in ("run", "resume"):
        print(json.dumps(runner.run(poll_interval=a.poll, timeout=a.timeout), indent=2))
    else:
        print(json.dumps(runner.status(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
