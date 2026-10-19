"""Package the saved benchmark / student runs into the committed folder ``results/runs/``.

    python -m step6_evaluation.collect_runs --src <main checkout>/outputs [--out results/runs]

One-time packaging step (Sun 10/18): ``outputs/`` is git-ignored, so the runs that feed the
benchmark tables are copied here. Nothing is re-scored or edited:

* single-split runs (dev, eval_hard): ``predictions.jsonl`` is copied byte for byte;
* frozen eval v1 (eval_id + eval_ood_template + eval_ood_hand + eval_ood_llm = 500 cases):
  the four per-split ``predictions.jsonl`` files are concatenated in that order, byte for byte.

Each run dir gets ``run.json`` (read by ``step6_evaluation/report.py``) and ``provenance.json``
(source path + sha256 of every part, and the source ``endpoint_run.json`` / ``ledger.json`` /
``run.json`` of every part). Logs and caches are never copied. Endpoint provenance keeps only
the *name* of the API-key env var, never a value.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path

EVAL_V1 = ["eval_id", "eval_ood_template", "eval_ood_hand", "eval_ood_llm"]
EVAL_V1_GOLD = [f"data/{s}/cases.jsonl" for s in EVAL_V1]

FRONTIER = [  # (dir prefix, display, price_key)
    ("gpt-6-astra", "GPT-6 Astra", "gpt-6-astra"),
    ("claude-opus-5-5", "Claude Opus 5.5", "claude-opus-5-5"),
    ("gemini-4-argon", "Gemini 4 Argon", "gemini-4-argon"),
]
OPEN = [("0.8b", "Qwen3.5-0.8B", "0.8B"), ("2b", "Qwen3.5-2B", "2B"), ("4b", "Qwen3.5-4B", "4B")]
PROMPTS = [("baseline_zero_shot", "zero-shot"), ("baseline_best", "best prompt")]

STUDENTS = {  # run name -> display
    "final-A-s3": "A halfway (adapter + twins distillation, no pre-checks)",
    "final-A-s4": "A: model alone",
    "final-B-s3": "B halfway (+ pre-checks v2)",
    "final-B-s4": "B: model + pre-checker v2 (before diagnosis)",
    "final-Brun2-s3": "B2 halfway (pre-checker reader v3 + 25% blank blocks)",
    "final-Brun2-s4": "B2: shipped model (pre-checker reader v3, after diagnosis)",
}

DEV_ABLATIONS = {  # dir under step5_training/results/dev_evals or outputs/student -> (display, params, stage, order)
    "sft-gold-0p8b__dev": ("gold SFT 0.8B", "0.8B", None, None),
    "sft-gold-qwen35-0p8b-twins__dev": ("gold SFT 0.8B + twins", "0.8B", None, None),
    "sft-gold-qwen35-2b__dev": ("gold SFT 2B", "2B", None, None),
    "sft-gold-qwen35-4b__dev": ("gold SFT 4B (gold-only control)", "4B", "gold-only SFT (control)", 0),
    "distill-4b-floor__dev": ("distill 4B floor (Sol)", "4B", "floor (Sol SFT)", 1),
    "distill-4b-reject__dev": ("distill 4B + rejection", "4B", "+ rejection sampling", 2),
    "distill-4b-arbitrate__dev": ("distill 4B + arbitration", "4B", "+ arbitration", 3),
    "distill-4b-twins__dev": ("distill 4B + Counterfactual Twins", "4B", "+ Counterfactual Twin Distillation", 4),
}

SIDE_FILES = ["endpoint_run.json", "ledger.json", "run.json"]


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def read_json(p: Path) -> dict | None:
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def write_json(p: Path, obj: dict) -> None:
    p.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def package(out: Path, run_id: str, parts: list[Path], meta: dict, src_root: Path) -> None:
    d = out / run_id
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    prov = {"run_id": run_id, "assembled_by": "python -m step6_evaluation.collect_runs",
            "parts": []}
    with open(d / "predictions.jsonl", "wb") as f:
        for p in parts:
            data = (p / "predictions.jsonl").read_bytes()
            if data and not data.endswith(b"\n"):
                data += b"\n"
            f.write(data)
            part = {"source": str(p.relative_to(src_root)).replace("\\", "/"),
                    "predictions_sha256": sha256(p / "predictions.jsonl"),
                    "n_lines": sum(1 for ln in data.splitlines() if ln.strip())}
            for side in SIDE_FILES:
                obj = read_json(p / side)
                if obj is not None:
                    part[side] = obj
            prov["parts"].append(part)
    write_json(d / "run.json", meta)
    write_json(d / "provenance.json", prov)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--src", type=Path, required=True, help="the main checkout's outputs/ dir (read-only)")
    ap.add_argument("--dev-evals", type=Path, default=None,
                    help="step5_training/results/dev_evals (default: <src>/../step5_training/results/dev_evals)")
    ap.add_argument("--out", type=Path, default=Path("results/runs"))
    a = ap.parse_args(argv)
    src = a.src.resolve()
    root = src.parent
    dev_evals = (a.dev_evals or root / "step5_training/results/dev_evals").resolve()
    out = a.out
    out.mkdir(parents=True, exist_ok=True)
    n = 0
    order = 0

    # ---- frozen eval v1 (500) and eval_hard (150): baselines ----
    for prefix, disp, price in FRONTIER:
        for pkey, pdisp in PROMPTS:
            order += 1
            parts = [src / "bench_frontier" / f"{prefix}__{pkey}__{s}" for s in EVAL_V1]
            meta = {"model": f"{disp} ({pdisp})", "params": "frontier (undisclosed)", "price_key": price,
                    "gold": EVAL_V1_GOLD, "table1_group": "eval_v1", "table1_order": order}
            cached = sum(m.get("cache_hits", 0) for p in parts
                         for m in (read_json(p / "ledger.json") or {}).get("by_model", {}).values())
            if cached:
                meta["notes"] = (f"{cached} of 500 responses were reused from the local response cache (same "
                                 "request made earlier) and not billed again; $ / 1k prices every call at list "
                                 "price, so it is slightly above the billed ledger total")
            package(out, f"{prefix}__{pkey}__eval_v1", parts, meta, root)
            n += 1
            hard = next((h for h in (src / "bench_hard" / f"{prefix}__{pkey}__eval_hard",
                                     root / "step2_benchmarking/results/bench_hard" / f"{prefix}__{pkey}__eval_hard")
                         if h.exists()), None)
            if hard is not None:  # only Astra and Opus (best prompt) were run on eval_hard
                package(out, f"{prefix}__{pkey}__eval_hard", [hard], {
                    "model": f"{disp} ({pdisp})", "params": "frontier (undisclosed)", "price_key": price,
                    "gold": "data/eval_hard/cases.jsonl", "table1_group": "eval_hard", "table1_order": order}, root)
                n += 1
    for key, disp, params in OPEN:
        for pkey, pdisp in PROMPTS:
            order += 1
            parts = [src / "bench_open" / f"{key}__{pkey}__{s}" for s in EVAL_V1]
            meta = {"model": f"{disp} ({pdisp})", "params": params, "price_key": "modal-l4-c16",
                    "gold": EVAL_V1_GOLD, "table1_group": "eval_v1", "table1_order": order,
                    "notes": "vLLM on one L4, 16 concurrent requests: latency includes queueing"}
            if key == "4b" and pkey == "baseline_best":
                meta.update({"pipeline": "v1 A: model alone", "stage": "base Qwen3.5-4B, best prompt",
                             "stage_order": 0})
            package(out, f"qwen35-{key}__{pkey}__eval_v1", parts, meta, root)
            n += 1

    # ---- our models ----
    pending = {"latency_p50_ms": "not deployed", "latency_p95_ms": "not deployed",
               "cost_per_1k_usd": "not deployed"}
    lat = {}
    for g in ("", "-h100"):
        f = root / "results" / "latency" / f"final-Brun2-s4{g}.json"
        if f.exists():
            lat[g or "l4"] = read_json(f)
    shipped = dict(pending)
    if "l4" in lat:
        l4, h = lat["l4"], lat.get("-h100")
        tail = lambda k, fmt: f" (H100: {fmt(h[k])})" if h else ""
        shipped = {"latency_p50_ms": f"{l4['latency_p50_ms']:,.0f} on L4{tail('latency_p50_ms', lambda v: f'{v:,.0f}')}",
                   "latency_p95_ms": f"{l4['latency_p95_ms']:,.0f} on L4{tail('latency_p95_ms', lambda v: f'{v:,.0f}')}",
                   "cost_per_1k_usd": f"${l4['cost_per_1k_usd']:.2f} on L4{tail('cost_per_1k_usd', lambda v: f'${v:.2f}')}"}
    stage_meta = {
        "final-A-s3": {"pipeline": "v1 A: model alone", "stage": "+ adapter + twins distillation (halfway)",
                       "stage_order": 1},
        "final-A-s4": {"pipeline": "v1 A: model alone", "stage": "+ post-train (Final A)", "stage_order": 2},
        "final-B-s3": {"pipeline": "v1 B: model + pre-checks", "stage": "+ pre-checks v2 (halfway)",
                       "stage_order": 1, "compare_to": "final-A-s3__eval_v1"},
        "final-B-s4": {"pipeline": "v1 B: model + pre-checks", "stage": "+ post-train (Final B)",
                       "stage_order": 2},
        "final-Brun2-s3": {"pipeline": "B2: model + pre-checks v3 (after diagnosis)",
                           "stage": "+ reader v3 + blank-block training (halfway)", "stage_order": 1,
                           "compare_to": "final-B-s3__eval_v1"},
        "final-Brun2-s4": {"pipeline": "B2: model + pre-checks v3 (after diagnosis)",
                           "stage": "+ post-train (B2)", "stage_order": 2},
    }
    for name, disp in STUDENTS.items():
        order += 1
        parts = [src / "student" / f"{name}__{s}" for s in EVAL_V1]
        package(out, f"{name}__eval_v1", parts, {
            "model": disp, "params": "4B", "price_key": "modal-l4-c16", "gold": EVAL_V1_GOLD,
            "table1_group": "eval_v1", "table1_order": order, "display": shipped if name == "final-Brun2-s4" else pending, **stage_meta[name]}, root)
        n += 1
        package(out, f"{name}__eval_hard", [src / "student" / f"{name}__eval_hard"], {
            "model": disp, "params": "4B", "price_key": "modal-l4-c16", "gold": "data/eval_hard/cases.jsonl",
            "table1_group": "eval_hard", "table1_order": order, "display": pending}, root)
        n += 1
        package(out, f"{name}__dev", [src / "student" / f"{name}__dev"], {
            "model": disp, "params": "4B", "price_key": "modal-l4-c16", "gold": "data/dev/cases.jsonl",
            "table1_group": "dev", "table1_order": 100 + order, "display": pending}, root)
        n += 1

    # ---- fresh eval_id v2 (generated Sun 10/18, seed 3050000, untouched by any development) ----
    V2_GOLD = "data/eval_id_v2/cases.jsonl"
    swap_src = Path(os.environ.get("ZORBE_SWAP_SRC", str(src)))   # swap runs are copied into outputs/student
    v2 = [(src / "bench_frontier" / f"{prefix}__baseline_best__eval_id_v2", f"{disp} (best prompt)",
           "frontier (undisclosed)", price) for prefix, disp, price in FRONTIER]
    v2 += [(src / "bench_open" / f"{key}__{pkey}__eval_id_v2", f"{disp} ({pdisp})", params, "modal-l4-c16",
            f"qwen35-{key}__{pkey}__eval_id_v2") for key, disp, params in OPEN for pkey, pdisp in PROMPTS]
    v2 += [(src / "student" / "final-A-s3__eval_id_v2", STUDENTS["final-A-s3"], "4B", "modal-l4-c16")]
    v2 += [(src / "student" / "final-Brun2-s3__eval_id_v2", STUDENTS["final-Brun2-s3"], "4B", "modal-l4-c16"),
           (src / "student" / "final-Brun2-s4__eval_id_v2", STUDENTS["final-Brun2-s4"], "4B", "modal-l4-c16"),
           (swap_src / "student" / "final-Brun2-s3-r31__eval_id_v2", "B2 halfway, served with reader v3.1", "4B", "modal-l4-c16"),
           (swap_src / "student" / "final-Brun2-s4-r31__eval_id_v2", "B2, served with reader v3.1 (swap test)", "4B", "modal-l4-c16")]
    for i, item in enumerate(v2):
        p, disp, params, price = item[:4]
        rid = item[4] if len(item) > 4 else p.name
        if not (p / "predictions.jsonl").exists():
            continue
        package(out, rid, [p], {"model": disp, "params": params, "price_key": price, "gold": V2_GOLD,
                                   "table1_group": "eval_id_v2", "table1_order": i,
                                   **({"display": shipped if p.name.startswith("final-Brun2-s4__") else pending}
                                      if p.parent.name == "student" else {})}, root)
        n += 1

    # ---- dev ablations (stage-3 distillation on plain 4B, gold-SFT sizes) ----
    for i, (rid, (disp, params, stage, sorder)) in enumerate(DEV_ABLATIONS.items()):
        p = dev_evals / rid if (dev_evals / rid).exists() else src / "student" / rid
        meta = {"model": disp, "params": params, "price_key": "modal-l4-c16", "gold": "data/dev/cases.jsonl",
                "table1_group": "dev", "table1_order": i, "display": pending}
        if stage is not None:
            meta.update({"pipeline": "dev: plain 4B distillation (stage 3)", "stage": stage, "stage_order": sorder})
        package(out, rid, [p], meta, root)
        n += 1

    print(f"packaged {n} runs into {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
