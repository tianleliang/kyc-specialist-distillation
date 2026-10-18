"""Train cases -> teacher LLMRequest JSONL for shared/frontier_api/batch.py (or step4_distillation.onpolicy run).

    python -m step4_distillation.teacher_requests --gold data/train/cases.jsonl --schema step0_rules/schema/v1.json \
        --provider gemini --model gemini-4-argon --k 2 \
        --system-file step0_rules/prompts/out/teacher_system.txt --out outputs/distill/reqs_argon.jsonl
    python -m shared.frontier_api.batch run --job outputs/batches/teacher_argon --requests outputs/distill/reqs_argon.jsonl

Each request carries ``metadata = {case_id, teacher, sample}`` (never sent, never hashed), which
is what the step4_distillation/ steps read back from the batch results. Requests have purpose="teacher",
reasoning effort low and a max_tokens cap (CLAUDE.md spend rules).

k > 1 samples: identical requests share a cache key and a batch custom_id, so sample i > 0
gets a one-line ``[sample i]`` tag appended to the user turn (and ``--temperature`` if the model
accepts one). The teacher prompt is not the student prompt, so the tag never reaches training.

Before writing, the request file goes through the same contamination gate as training files
(split_guard overlap against frozen eval manifests), because ``shared.frontier_api.batch`` itself has no guard:
teachers never see eval cases.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from step4_distillation.common import (StudentPrompt, Tally, add_common_args, add_prompt_args, load_fieldmap,
                            load_gold, refuse_eval_ids, setup_logging, write_training_file)


def build(gold: dict, fm, prompt: StudentPrompt, *, provider: str, model: str, k: int = 1,
          schema: dict | None = None, max_tokens: int = 4096, reasoning_effort: str | None = "low",
          temperature: float | None = None, teacher_name: str | None = None) -> list[dict]:
    from shared.frontier_api.clients import LLMRequest

    out = []
    for cid, g in gold.items():
        msgs = prompt.messages(g[fm.gold_packet_key])
        system = msgs[0]["content"] if msgs[0]["role"] == "system" else None
        user = msgs[-1]["content"]
        for i in range(k):
            req = LLMRequest(provider=provider, model=model,
                             messages=[{"role": "user", "content": user if i == 0 else f"{user}\n\n[sample {i}]"}],
                             system=system, json_schema=schema, max_tokens=max_tokens,
                             temperature=temperature, reasoning_effort=reasoning_effort, purpose="teacher",
                             metadata={"case_id": cid, "teacher": teacher_name or model, "sample": i})
            out.append(req.to_dict())
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_common_args(ap)
    add_prompt_args(ap)
    ap.add_argument("--provider", required=True, choices=["openai", "anthropic", "gemini", "mock"])
    ap.add_argument("--model", required=True)
    ap.add_argument("--teacher-name", help="name used in metadata.teacher (default: the model id)")
    ap.add_argument("--k", type=int, default=1)
    ap.add_argument("--max-tokens", type=int, default=4096)
    ap.add_argument("--reasoning-effort", default="low", help="low|medium|high|none")
    ap.add_argument("--temperature", type=float)
    ap.add_argument("--limit", type=int, help="first N cases only (pilots)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    setup_logging(a.verbose)
    fm = load_fieldmap(a.fieldmap, a.schema)
    gold = load_gold(a.gold, fm)
    refuse_eval_ids(gold, what=a.gold)
    if a.limit:
        gold = dict(list(gold.items())[:a.limit])
    schema = json.loads(Path(fm.schema_path).read_text(encoding="utf-8")) if fm.schema_path else None
    rows = build(gold, fm, StudentPrompt.from_files(a.system_file, a.user_template_file), provider=a.provider,
                 model=a.model, k=a.k, schema=schema, max_tokens=a.max_tokens,
                 reasoning_effort=None if a.reasoning_effort == "none" else a.reasoning_effort,
                 temperature=a.temperature, teacher_name=a.teacher_name)
    tally = Tally("teacher_requests")
    tally.keep(len(rows))
    tally.extra.update({"cases": len(gold), "k": a.k, "provider": a.provider, "model": a.model})
    write_training_file(a.out, rows, a.eval_manifest, tally, id_keys=())
    tally.save(a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
