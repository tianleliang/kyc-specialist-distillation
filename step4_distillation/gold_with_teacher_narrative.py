"""Stage-4 training file: gold decisions with the teacher's (Sol's) narratives.

    python -m step4_distillation.gold_with_teacher_narrative
        # data/sft/gold_train.jsonl + data/sft/distill_floor_sol.jsonl -> data/sft/gold_train_solnarr.jsonl

Per row of the gold file: parse the gold target; if Sol's answer for the same ``case_id``
(the assistant turn in the Sol floor file) parses and has the SAME ``decision`` and
``risk_tier``, only ``narrative`` is replaced with Sol's; otherwise the gold row is kept as
is. Every other field stays gold. Targets are re-serialized with ``dump_json`` (schema key
order = serving grammar order). Prompts (system + user turns) are the gold file's, unchanged.

Contamination: both inputs already passed the contamination gate when they were built
(see their ``.stats.json``), the prompts are copied from the gold file and the narrative
text comes from a gated file, so the output is not re-gated against the eval manifest
(that would read eval data). Rows holding eval case ids are refused. Writes
``<out>.stats.json`` (rows, narratives replaced, kept, and why kept).
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from step4_distillation.common import dump_json, read_jsonl, refuse_eval_ids, write_jsonl

GOLD = "data/sft/gold_train.jsonl"
TEACHER = "data/sft/distill_floor_sol.jsonl"
OUT = "data/sft/gold_train_solnarr.jsonl"


def _assistant(row: dict) -> str:
    return next(m["content"] for m in reversed(row["messages"]) if m["role"] == "assistant")


def _parse(text: str) -> dict | None:
    try:
        obj = json.loads(text)
    except (TypeError, ValueError):
        return None
    return obj if isinstance(obj, dict) else None


def build(gold: str | Path = GOLD, teacher: str | Path = TEACHER, out: str | Path = OUT) -> dict:
    gold_rows, t_rows = read_jsonl(gold), read_jsonl(teacher)
    refuse_eval_ids([r.get("case_id") for r in gold_rows + t_rows if r.get("case_id")], what=f"{gold}, {teacher}")
    sol: dict[str, list[str]] = {}
    for r in t_rows:
        sol.setdefault(r["case_id"], []).append(_assistant(r))
    kept = Counter()
    out_rows = []
    for r in gold_rows:
        g = _parse(_assistant(r))
        if g is None:
            raise SystemExit(f"gold target does not parse: {r.get('id')}")
        texts = sol.get(r["case_id"], [])
        s = _parse(texts[0]) if len(texts) == 1 else None
        if len(texts) != 1:
            why = "no_teacher_row" if not texts else "several_teacher_rows"
        elif s is None:
            why = "teacher_unparseable"
        elif s.get("decision") != g.get("decision"):
            why = "decision_differs"
        elif s.get("risk_tier") != g.get("risk_tier"):
            why = "risk_tier_differs"
        elif not isinstance(s.get("narrative"), list) or not s["narrative"]:
            why = "teacher_narrative_missing"
        else:
            why = None
        if why:
            kept[why] += 1
            new = g
        else:
            new = {**g, "narrative": s["narrative"]}
        msgs = [dict(m) for m in r["messages"]]
        ai = max(i for i, m in enumerate(msgs) if m["role"] == "assistant")
        msgs[ai]["content"] = dump_json(new)
        prompt_same = [m for m in msgs if m["role"] != "assistant"] == [m for m in r["messages"] if m["role"] != "assistant"]
        assert prompt_same, r.get("id")
        out_rows.append({**r, "id": r["id"].replace(":gold:", ":gold_solnarr:", 1) if ":gold:" in r["id"] else r["id"],
                         "teacher": "gold+sol_narrative" if not why else r.get("teacher"),
                         "messages": msgs})
    write_jsonl(out, out_rows)
    stats = {"step": "gold_with_teacher_narrative", "gold": Path(gold).as_posix(), "teacher": Path(teacher).as_posix(),
             "output": Path(out).as_posix(), "rows": len(out_rows),
             "narratives_replaced": len(out_rows) - sum(kept.values()),
             "kept_gold_narrative": sum(kept.values()), "kept_why": dict(sorted(kept.items())),
             "contamination": "inputs gated at build time; prompts copied from the gold file; not re-gated"}
    Path(str(out) + ".stats.json").write_text(json.dumps(stats, indent=1) + "\n", encoding="utf-8")
    return stats


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--gold", default=GOLD)
    ap.add_argument("--teacher", default=TEACHER)
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args(argv)
    s = build(a.gold, a.teacher, a.out)
    print(f"{s['output']}: {s['rows']} rows, {s['narratives_replaced']} narratives replaced, "
          f"{s['kept_gold_narrative']} kept {s['kept_why']}")


if __name__ == "__main__":
    main()
