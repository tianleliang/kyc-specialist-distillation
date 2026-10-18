"""Run a frontier model (OpenAI / Anthropic / Gemini, native structured output) over a case file.

Writes predictions in the record format step6_evaluation/report.py reads:
    outputs/<run_id>/predictions.jsonl   {case_id, output, latency_ms, usage, error}
    outputs/<run_id>/run.json            {model, gold, params}
    outputs/<run_id>/ledger.json         API cost summary

Prompts (decision D21): schema field descriptions off; policy in best/teacher prompts, not zero-shot.
Few-shot examples for baseline_best / teacher come from data/train (never eval).

    python -m step2_benchmarking.run_frontier --cases data/dev/cases.jsonl \
        --model gemini:gemini-4-argon --prompt baseline_best --limit 100 --run-id pilot_argon_best
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from shared.frontier_api.clients import LLMClient, LLMRequest
from step0_rules.prompts.render import PromptBuilder, load_examples

SCHEMA = "step0_rules/schema/v1.json"
POLICY = "step0_rules/policy_v1.md"
PURPOSE = {"baseline_zero_shot": "baseline", "baseline_best": "baseline", "teacher": "teacher"}


def api_schema(schema: dict, provider: str) -> dict:
    """Anthropic structured output rejects minItems > 1, maxItems and length/range bounds. Send it a relaxed copy; every
    prediction is still scored against the full v1 schema by step6_evaluation."""
    if provider != "anthropic":
        return schema

    def walk(o):
        if isinstance(o, dict):
            o = {k: walk(v) for k, v in o.items()}
            if isinstance(o.get("minItems"), int) and o["minItems"] > 1:
                o["minItems"] = 1
            for k in ("maxItems", "minLength", "maxLength", "minimum", "maximum"):
                o.pop(k, None)  # unsupported by Anthropic structured output
            return o
        if isinstance(o, list):
            return [walk(v) for v in o]
        return o

    return walk(schema)


def build_prompt(name: str, examples_pool: str, seed: int) -> PromptBuilder:
    # field guide dropped: it restates the policy (13k chars) and roughly doubled input cost
    kw: dict = {"schema": SCHEMA, "schema_descriptions": False,
                "field_guide_text": "Every field and code is defined in the policy above."}
    if name != "baseline_zero_shot":
        kw["policy"] = POLICY
        kw["examples"] = load_examples(examples_pool, k=2, seed=seed, purpose=PURPOSE[name])
    return PromptBuilder(name, **kw)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cases", required=True)
    ap.add_argument("--model", required=True, help="provider:model, e.g. openai:gpt-6-astra")
    ap.add_argument("--prompt", default="baseline_best", choices=sorted(PURPOSE))
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--effort", default="low")
    ap.add_argument("--max-tokens", type=int, default=6000)
    ap.add_argument("--examples-pool", default="data/train/cases.jsonl")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out-root", default="outputs")
    a = ap.parse_args(argv)

    provider, model = a.model.split(":", 1)
    schema = json.loads(Path(SCHEMA).read_text(encoding="utf-8"))
    pb = build_prompt(a.prompt, a.examples_pool, a.seed)
    rows = [json.loads(l) for l in Path(a.cases).read_text(encoding="utf-8").splitlines() if l.strip()]
    if a.limit:
        rows = rows[: a.limit]
    reqs = []
    for r in rows:
        rp = pb.render(r["packet"])
        reqs.append(LLMRequest(provider=provider, model=model, system=rp.system,
                               messages=[{"role": "user", "content": rp.user}],
                               json_schema=api_schema(schema, provider),
                               schema_name="kyc_decision", max_tokens=a.max_tokens, reasoning_effort=a.effort,
                               purpose=PURPOSE[a.prompt], metadata={"case_id": r["case_id"]}))
    client = LLMClient()
    t0 = time.time()
    resps = client.complete_many(reqs, max_workers=a.workers)
    out = Path(a.out_root) / a.run_id
    out.mkdir(parents=True, exist_ok=True)
    n_valid = 0
    with open(out / "predictions.jsonl", "w", encoding="utf-8", newline="\n") as f:
        for r, x in zip(rows, resps):
            output = x.parsed if x.parsed is not None else (x.text or None)
            n_valid += bool(x.schema_valid)
            f.write(json.dumps({"case_id": r["case_id"], "output": output,
                                "latency_ms": round((x.latency_s or 0) * 1000, 1),
                                "usage": {"prompt_tokens": x.usage.input_tokens,
                                          "completion_tokens": x.usage.output_tokens},
                                "error": x.error or x.parse_error}, ensure_ascii=False) + "\n")
    (out / "run.json").write_text(json.dumps({"model": f"{model} ({a.prompt})", "gold": a.cases,
                                              "params": "frontier"}, indent=2) + "\n", encoding="utf-8", newline="\n")
    ledger = client.ledger.summary()
    (out / "ledger.json").write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8", newline="\n")
    errs = sum(1 for x in resps if x.error)
    print(f"{a.run_id}: {len(rows)} cases, schema-valid {n_valid}, errors {errs}, "
          f"cost ${ledger['total_usd']:.2f}, {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
