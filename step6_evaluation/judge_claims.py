"""LLM judge for the brief's "unsupported claims" metric (narrative sentences not grounded in the packet).

    # smoke: 3 packets, print a few verdicts + cost per call and a full-run estimate
    python -m step6_evaluation.judge_claims <run_dir> ... --limit 3 --smoke
    # full run (resumable; only unjudged sentences are sent)
    python -m step6_evaluation.judge_claims <run_dir> ... --max-usd 50
    # per-run rates from saved verdicts (no API)
    python -m step6_evaluation.judge_claims <run_dir> ... --summary-only

How it stays blind and cheap:
- For each case, the narrative sentences of every given run are pooled, de-duplicated by
  normalized text, shuffled and renamed S1..Sn (``render.judge_items``). The judge never sees
  which run wrote a sentence, or how many runs wrote the same one.
- One Claude Sonnet call per packet, JSON-Schema output, validated with ``render.parse_judgments``
  (every sentence judged exactly once); retried once.
- Prompt: ``judge_unsupported_claims_v2`` (packet + policy v1, the default; the policy is in the
  system part and prompt-cached) or, with ``--policy none``, v1 (packet only). One prompt version
  per ``--out`` dir: verdicts from another version there are refused.
- A verdict is a function of (packet, sentence text) only, so verdicts are keyed by
  (case_id, sha256 of the normalized sentence). Adding a run later (e.g. B-v3) judges only the
  sentences no earlier run wrote; nothing else is re-judged.

Only schema-valid outputs contribute sentences, exactly the sentences ``metrics.score_case``
counts for the programmatic ``evidence_refs`` check, so both columns share a denominator.

Outputs (``--out``, default results/judge/eval_id):
    verdicts.jsonl   one row per (case_id, sentence), sorted, byte-stable
    calls.jsonl      one row per judge call: case, n sentences, tokens, cost, response id
    summary.json/.md per-run unsupported rate + sentences judged
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from shared.frontier_api.clients import LLMClient, make_request
from step0_rules.prompts import render as R
from step6_evaluation import metrics as M

DEFAULT_MODEL = "claude-sonnet-5-5"
DEFAULT_FIELDMAP = Path("step6_evaluation/fieldmap_v1.yaml")
DEFAULT_SCHEMA = Path("step0_rules/schema/v1.json")
DEFAULT_POLICY = "step0_rules/policy_v1.md"


norm, sentence_key = M.norm_sentence, M.sentence_key


def run_sentences(run_dir: Path, golds: list[dict], fm: M.FieldMap, validator) -> dict[str, list[str]]:
    """{case_id: [sentence, ...]}: exactly the sentences metrics.score_case checks
    (schema-valid outputs only), so the judge and evidence_refs columns share a denominator."""
    scores, _ = M.score_run(golds, M.read_jsonl(run_dir / "predictions.jsonl"), fm, validator)
    return {s.case_id: list(s.sentence_texts) for s in scores if s.sentence_texts}


def load_verdicts(path: Path) -> dict[tuple[str, str], dict]:
    if not path.exists():
        return {}
    return {(r["case_id"], r["sentence_sha"]): r for r in M.read_jsonl(path)}


def save_verdicts(path: Path, verdicts: dict[tuple[str, str], dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [verdicts[k] for k in sorted(verdicts)]
    path.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows),
                    encoding="utf-8")


def run_rates(run_sents: dict[str, list[str]], verdicts: dict) -> dict[str, Any]:
    n = unsup = missing = 0
    for cid, sents in run_sents.items():
        for s in sents:
            v = verdicts.get(sentence_key(cid, s))
            if v is None:
                missing += 1
                continue
            n += 1
            unsup += not v["supported"]
    return {"n_sentences_judged": n, "n_unsupported": unsup, "n_unjudged": missing,
            "unsupported_rate": (unsup / n) if n and not missing else None}


def build_request(case: dict, pending: list[tuple[tuple[str, str], str]], model: str,
                  max_tokens_cap: int, policy: str | None = None):
    seed = int(hashlib.sha256(case["case_id"].encode()).hexdigest()[:8], 16)
    rp, id_map = R.render_judge(case["packet"], pending, seed=seed, policy=policy)
    schema = R.load_schema(R.JUDGE_SCHEMA_PATH)
    # thinking (effort=low) + ~60 output tokens per sentence; generous so nothing truncates
    max_tokens = min(max_tokens_cap, 3000 + 150 * len(pending))
    req = make_request("anthropic", model, user=rp.user, system=rp.system, json_schema=schema,
                       schema_name="judge_unsupported_claims", max_tokens=max_tokens,
                       reasoning_effort="low", purpose="judge",
                       metadata={"case_id": case["case_id"]})
    if policy is not None:
        # identical system part (instructions + schema + policy) on every call: cache it
        req.extra = {"system": [{"type": "text", "text": rp.system, "cache_control": {"type": "ephemeral"}}]}
    return req, id_map, rp


def judge_case(client: LLMClient, case: dict, pending, model: str, max_tokens_cap: int,
               policy: str | None = None) -> dict:
    req, id_map, rp = build_request(case, pending, model, max_tokens_cap, policy)
    attempts, last_err, cost, usage = [], None, 0.0, {"input_tokens": 0, "output_tokens": 0}
    for attempt in range(2):  # retry once on invalid output
        resp = client.complete(req, use_cache=(attempt == 0))
        if not resp.cached:
            cost += resp.cost_usd or 0.0
        usage["input_tokens"] += resp.usage.input_tokens
        usage["output_tokens"] += resp.usage.output_tokens
        attempts.append({"response_id": resp.response_id, "cached": resp.cached,
                         "stop_reason": resp.stop_reason, "schema_valid": resp.schema_valid,
                         "cost_usd": resp.cost_usd})
        try:
            if not resp.schema_valid:
                raise ValueError(f"schema invalid: {resp.parse_error}")
            judged = R.parse_judgments(resp.parsed, id_map)
            return {"ok": True, "judged": judged, "attempts": attempts, "cost_usd": cost,
                    "usage": usage, "prompt": rp.provenance()}
        except ValueError as e:
            last_err = str(e)[:300]
    return {"ok": False, "error": last_err, "attempts": attempts, "cost_usd": cost, "usage": usage}


def summarize(run_dirs: list[Path], per_run: dict[str, dict[str, list[str]]], verdicts: dict,
              out: Path, template: str) -> dict:
    # merge: runs judged in an earlier invocation keep their row (verdicts are only ever added,
    # never changed), so judging one new run later does not drop the others
    prev = out / "summary.json"
    summary = json.loads(prev.read_text(encoding="utf-8"))["runs"] if prev.exists() else {}
    summary.update({d.name: run_rates(per_run[d.name], verdicts) for d in run_dirs})
    payload = {"judge_model": DEFAULT_MODEL, "prompt": f"step0_rules/prompts/{template}.md",
               "n_verdicts": len(verdicts), "runs": summary}
    (out / "summary.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = ["| Run | Sentences judged | Unsupported | Unsupported % |", "|---|---:|---:|---:|"]
    for name, s in summary.items():
        rate = "n/a" if s["unsupported_rate"] is None else f"{100 * s['unsupported_rate']:.1f}"
        extra = f" ({s['n_unjudged']} unjudged)" if s["n_unjudged"] else ""
        lines.append(f"| {name} | {s['n_sentences_judged']}{extra} | {s['n_unsupported']} | {rate} |")
    (out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m step6_evaluation.judge_claims",
                                 description=__doc__.split("\n")[0])
    ap.add_argument("runs", nargs="+", type=Path, help="run dirs holding predictions.jsonl")
    ap.add_argument("--gold", type=Path, default=Path("data/eval_id/cases.jsonl"))
    ap.add_argument("--out", type=Path, default=Path("results/judge/eval_id"))
    ap.add_argument("--config", type=Path, default=DEFAULT_FIELDMAP)
    ap.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--policy", default=DEFAULT_POLICY,
                    help="policy file for the v2 judge prompt; 'none' = v1 prompt (packet only)")
    ap.add_argument("--limit", type=int, help="judge only the first N cases (smoke)")
    ap.add_argument("--smoke", action="store_true", help="print sample verdicts and a full-run estimate")
    ap.add_argument("--max-usd", type=float, default=50.0, help="stop before a call would exceed this")
    ap.add_argument("--max-tokens-cap", type=int, default=32000)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--summary-only", action="store_true", help="no API calls; rates from saved verdicts")
    a = ap.parse_args(argv)

    fm = M.FieldMap.load(a.config)
    validator = M.make_validator(a.schema)
    golds = M.read_jsonl(a.gold)
    cases = {str(c["case_id"]): c for c in golds}
    per_run = {d.name: run_sentences(d, golds, fm, validator) for d in a.runs}
    if len(per_run) != len(a.runs):
        raise SystemExit("run dir names must be unique")

    policy = None if a.policy == "none" else R.load_policy(a.policy)
    template = "judge_unsupported_claims" if policy is None else "judge_unsupported_claims_v2"
    template_sha = R.load_template(template).sha256
    verdicts_path = a.out / "verdicts.jsonl"
    verdicts = load_verdicts(verdicts_path)
    other = {v["prompt_sha256"] for v in verdicts.values()} - {template_sha}
    if other:
        raise SystemExit(f"{verdicts_path} holds verdicts from another prompt version; use a new --out")

    # pending sentences per case: pooled across runs, unique by text, not yet judged
    order = list(cases)[: a.limit] if a.limit else list(cases)
    pending: dict[str, dict[tuple[str, str], str]] = {}
    total_unique = 0
    for cid in order:
        uniq: dict[tuple[str, str], str] = {}
        for rs in per_run.values():
            for s in rs.get(cid, []):
                uniq.setdefault(sentence_key(cid, s), norm(s))
        total_unique += len(uniq)
        todo = {k: t for k, t in uniq.items() if k not in verdicts}
        if todo:
            pending[cid] = todo
    n_sent = sum(len(v) for v in pending.values())
    print(f"{len(a.runs)} runs, {len(order)} cases, {total_unique} unique sentences, "
          f"{n_sent} to judge in {len(pending)} calls", file=sys.stderr)

    a.out.mkdir(parents=True, exist_ok=True)
    spent = 0.0
    if not a.summary_only and pending:
        client = LLMClient()
        calls_path = a.out / "calls.jsonl"
        failed, done_calls = [], []

        def one(cid):
            items = sorted(pending[cid].items())  # deterministic input; judge_items shuffles
            return cid, items, judge_case(client, cases[cid], items, a.model, a.max_tokens_cap, policy)

        cids = list(pending)
        with ThreadPoolExecutor(max_workers=a.workers) as ex:
            for start in range(0, len(cids), a.workers):
                if spent >= a.max_usd:
                    print(f"stopping: spent ${spent:.2f} >= cap ${a.max_usd}", file=sys.stderr)
                    break
                for cid, items, res in ex.map(one, cids[start:start + a.workers]):
                    spent += res["cost_usd"]
                    done_calls.append(res)
                    with calls_path.open("a", encoding="utf-8") as f:
                        f.write(json.dumps({"case_id": cid, "n_sentences": len(items), "model": a.model,
                                            **{k: res[k] for k in ("ok", "attempts", "cost_usd", "usage")},
                                            "error": res.get("error")}, ensure_ascii=False) + "\n")
                    if not res["ok"]:
                        failed.append(cid)
                        print(f"  {cid}: FAILED {res['error']}", file=sys.stderr)
                        continue
                    for (k, text) in items:
                        j = res["judged"][k]
                        verdicts[k] = {"case_id": k[0], "sentence_sha": k[1], "sentence": text,
                                       "supported": j["supported"],
                                       "unsupported_claim": j["unsupported_claim"],
                                       "packet_quote": j["packet_quote"],
                                       "quote_in_packet": (R.quote_in_packet(j["packet_quote"], cases[cid]["packet"])
                                                           if j["supported"] else None),
                                       "judge_model": a.model,
                                       "prompt_sha256": res["prompt"]["template_sha256"]}
                save_verdicts(verdicts_path, verdicts)
                print(f"  {min(start + a.workers, len(cids))}/{len(cids)} calls, ${spent:.2f}", file=sys.stderr)
        save_verdicts(verdicts_path, verdicts)
        print(f"spent ${spent:.4f} this invocation; failed calls: {failed or 'none'}", file=sys.stderr)

        if a.smoke:
            mine = done_calls
            per_call = spent / max(1, len(mine))
            per_sent = spent / max(1, n_sent)
            # full-run estimate: same cost per sentence over all unique sentences of all cases
            all_unique = sum(len({sentence_key(cid, s) for rs in per_run.values() for s in rs.get(cid, [])})
                             for cid in cases)
            print(f"\nSMOKE: {len(mine)} calls, ${spent:.4f} total, ${per_call:.4f}/call, "
                  f"${per_sent:.5f}/sentence; tokens per call: "
                  + ", ".join(f"in {c['usage']['input_tokens']} out {c['usage']['output_tokens']}" for c in mine))
            print(f"ESTIMATE full run: {len(cases)} calls, {all_unique} unique sentences -> "
                  f"~${per_sent * all_unique:.2f} (per-sentence) / ~${per_call * len(cases):.2f} (per-call)")
            shown = [v for k, v in verdicts.items() if k[0] in pending]
            for v in [x for x in shown if not x["supported"]][:4] + [x for x in shown if x["supported"]][:4]:
                tag = "SUPPORTED  " if v["supported"] else "UNSUPPORTED"
                why = v["packet_quote"] if v["supported"] else v["unsupported_claim"]
                print(f"\n[{tag}] {v['case_id']}: {v['sentence']}\n    -> {why}")

    summarize(a.runs, per_run, verdicts, a.out, template)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
