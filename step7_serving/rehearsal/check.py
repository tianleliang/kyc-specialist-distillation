"""Rehearsal step 3, last leg: is the *served* merged model different from the served base?

    python -m step7_serving.rehearsal.check --base-app zorbe-serve --merged-app zorbe-serve-rehearsal

Sends the same held-out toy packets (not in step5_training/toy/sft_toy.jsonl) with the toy system
prompt to the raw vLLM endpoint of each app, greedy, no response_format. Passes when the
merged model emits the trained marker ("ZORBE-TOY") on most probes, the base emits it on
none, and the outputs differ. Writes outputs/rehearsal/<timestamp>.json.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

import modal
from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[2]
SYSTEM = "Toy rehearsal. Reply with JSON only."
PROBES = [  # fictional, held out from the 24 training rows
    "TOY PACKET 901\nApplicant: Velmora Tasquin\nPassport expiry: 2031-02-11\nScreening hit score: 12",
    "TOY PACKET 902\nApplicant: Orrin Hadleck\nPassport expiry: 2022-09-30\nScreening hit score: 41",
    "TOY PACKET 903\nApplicant: Saffi Dromund\nPassport expiry: 2029-07-04\nScreening hit score: 99",
    "TOY PACKET 904\nApplicant: Ilvar Kestrow\nPassport expiry: 2027-12-19\nScreening hit score: 63",
    "TOY PACKET 905\nApplicant: Nerys Obbleton\nPassport expiry: 2024-01-15\nScreening hit score: 88",
    "TOY PACKET 906\nApplicant: Tavish Quorle\nPassport expiry: 2030-05-23\nScreening hit score: 5",
]
MARKER = "ZORBE-TOY"


def outputs(app: str, key: str) -> tuple[str, list[str]]:
    url = modal.Function.from_name(app, "vllm").get_web_url().rstrip("/")
    c = OpenAI(base_url=url + "/v1", api_key=key, timeout=900, max_retries=0)
    model = c.models.list().data[0].id
    outs = []
    for p in PROBES:
        r = c.chat.completions.create(
            model=model, temperature=0.0, max_tokens=64,
            messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": p}],
            extra_body={"chat_template_kwargs": {"enable_thinking": False}})
        outs.append(r.choices[0].message.content or "")
    return model, outs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-app", default="zorbe-serve")
    ap.add_argument("--merged-app", default="zorbe-serve-rehearsal")
    a = ap.parse_args()
    load_dotenv(ROOT / ".env")
    key = os.environ["VLLM_API_KEY"]
    base_model, base = outputs(a.base_app, key)
    merged_model, merged = outputs(a.merged_app, key)
    n_marker_merged = sum(MARKER in o for o in merged)
    n_marker_base = sum(MARKER in o for o in base)
    n_diff = sum(b != m for b, m in zip(base, merged))
    ok = n_marker_merged >= len(PROBES) - 1 and n_marker_base == 0 and n_diff == len(PROBES)
    rec = {"base_app": a.base_app, "base_model": base_model, "merged_app": a.merged_app,
           "merged_model": merged_model, "n_probes": len(PROBES), "n_outputs_differ": n_diff,
           "marker_in_merged": n_marker_merged, "marker_in_base": n_marker_base, "ok": ok,
           "examples": [{"probe": p, "base": b, "merged": m} for p, b, m in zip(PROBES, base, merged)]}
    out = ROOT / "outputs" / "rehearsal"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"check-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(rec, indent=1, ensure_ascii=False), encoding="utf-8")
    for e in rec["examples"][:3]:
        print(f"base:   {e['base'][:100]!r}\nmerged: {e['merged'][:100]!r}\n")
    print(f"differ {n_diff}/{len(PROBES)}, marker merged {n_marker_merged}, base {n_marker_base}: "
          f"{'PASS' if ok else 'FAIL'} -> {path.relative_to(ROOT)}")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
