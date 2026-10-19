"""Submission benchmark report (plain markdown tables, paste-ready) from the saved results.

    python -m step6_evaluation.make_submission_report      # -> documentation/04_results/benchmark_report_submission.md

Reads results/report_metrics.json (written by make_tables.sh), results/latency/*.json (measured endpoint
latency) and results/runs/*/predictions.jsonl (paired bootstrap for Table 2). No API calls; deterministic.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
M = json.loads((ROOT / "results/report_metrics.json").read_text(encoding="utf-8"))
OUT = ROOT / "documentation/04_results/benchmark_report_submission.md"
LAT = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in (ROOT / "results/latency").glob("*.json")}

FINAL = "final-Brun2-s4"
OPEN = [("qwen35-0.8b", "Qwen3.5-0.8B", "0.8B"), ("qwen35-2b", "Qwen3.5-2B", "2B"), ("qwen35-4b", "Qwen3.5-4B", "4B")]
FRONT = [("gpt-6-astra", "GPT-6 Astra"), ("claude-opus-5-5", "Claude Opus 5.5"), ("gemini-4-argon", "Gemini 4 Argon")]


def m(run: str) -> dict:
    return M[run]["metrics"]


def pct(v, d=1) -> str:
    return "–" if v is None else f"{v * 100:.{d}f}"


def ms(v) -> str:
    return "–" if v is None else f"{v / 1000:.1f} s"


def usd(v) -> str:
    return "–" if v is None else f"${v:.2f}"


def table(header: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(out)


def preds(run: str) -> dict:
    p = ROOT / "results/runs" / run / "predictions.jsonl"
    out = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        try:
            o = json.loads(r["output"]) if isinstance(r["output"], str) else r["output"]
        except Exception:
            o = None
        out[r["case_id"]] = o
    return out


def gold(paths: list[str]) -> dict:
    g = {}
    for p in paths:
        for line in (ROOT / p).read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            g[r["case_id"]] = r["expected"]
    return g


V1 = ["data/eval_id/cases.jsonl", "data/eval_ood_template/cases.jsonl", "data/eval_ood_hand/cases.jsonl",
      "data/eval_ood_llm/cases.jsonl"]


def correct(run: str, g: dict) -> list[int]:
    p = preds(run)
    return [int(isinstance(p.get(c), dict) and p[c].get("decision") == g[c]["decision"]) for c in sorted(g)]


def paired_ci(a: list[int], b: list[int], n_boot=2000, seed=0) -> tuple[float, float, float]:
    d = [x - y for x, y in zip(a, b)]
    n = len(d)
    rng = random.Random(seed)
    bs = sorted(sum(d[rng.randrange(n)] for _ in range(n)) / n for _ in range(n_boot))
    return sum(d) / n, bs[int(0.025 * n_boot)], bs[int(0.975 * n_boot) - 1]


def lat_cells(run: str, model_key: str | None) -> list[str]:
    if run.startswith(FINAL):
        l4, h = LAT.get(FINAL), LAT.get(FINAL + "-h100")
        batched = m(run).get("cost_per_1k_usd")
        return [f"{ms(l4['latency_p50_ms'])} (L4, 1 at a time) / {ms(h['latency_p50_ms'])} (H100, 1 at a time)",
                f"{ms(l4['latency_p95_ms'])} (L4, 1 at a time) / {ms(h['latency_p95_ms'])} (H100, 1 at a time)",
                f"{usd(batched)} (L4, 16 concurrent) / {usd(l4['cost_per_1k_usd'])} (L4, 1 at a time) / "
                f"{usd(h['cost_per_1k_usd'])} (H100, 1 at a time)"]
    x = m(run)
    how = " (API)" if model_key == "frontier" else " (L4, 16 concurrent)"
    return [ms(x.get("latency_p50_ms")) + how, ms(x.get("latency_p95_ms")) + how, usd(x.get("cost_per_1k_usd")) + how]


# ---------------------------------------------------------------- Table 1
T = "eval_id_v2"
G2 = gold(["data/eval_id_v2/cases.jsonl"])
t1_runs = [(f"{FINAL}__{T}", "**Ours: Zorbe KYC specialist (B2), Qwen3.5-4B**", "4B")]
t1_runs += [(f"{k}__baseline_best__{T}", f"{d} (best prompt)", p) for k, d, p in OPEN]
t1_runs += [(f"{k}__baseline_best__{T}", f"{d} (best prompt)", "undisclosed") for k, d in FRONT]
cOURS = correct(f"{FINAL}__{T}", G2)

h1a = ["Model", "Params", "Cases", "Decision acc %", "Their acc − ours (pts) [95% CI, paired]", "Screening macro-F1 %", "Risk exact %", "Risk ±1 %",
       "Actions recall %", "Actions precision %", "Unsupported claims % (LLM judge)", "Schema valid %"]
r1a = []
for run, disp, params in t1_runs:
    x = m(run)
    if run.startswith(FINAL):
        dcell = "–"
    else:
        dl, lo, hi = paired_ci(correct(run, G2), cOURS)
        dcell = f"{dl * 100:+.1f} [{lo * 100:+.1f}, {hi * 100:+.1f}]"
    r1a.append([disp, params, str(x["n_cases"]), pct(x["decision_accuracy"]), dcell, pct(x["screening_macro_f1"]),
                pct(x["risk_exact"]), pct(x["risk_within_one"]), pct(x["actions_recall"]),
                pct(x["actions_precision"]), pct(x.get("judge_unsupported_rate")), pct(x["schema_validity"])])

h1b = ["Model", "Verified %", "Name %", "Date of birth %", "Document no. %", "Expiry %", "Address %",
       "Escalation on injection % (n)", "Escalation on ambiguous % (n)", "p50 latency", "p95 latency", "$ / 1k cases"]
r1b = []
for run, disp, params in t1_runs:
    x = m(run)
    f = lambda k: pct(x.get(f"field_accuracy.{k}"))
    r1b.append([disp, f("verified"), f("name"), f("date_of_birth"), f("document_number"), f("expiry"), f("address"),
                f"{pct(x.get('adv_escalation_rate.injection'))} ({x.get('n_adv.injection')})",
                f"{pct(x.get('adv_escalation_rate.ambiguous'))} ({x.get('n_adv.ambiguous')})"]
               + lat_cells(run, "frontier" if params == "undisclosed" else "open"))

# ---------------------------------------------------------------- Table 2
ladder = [(f"qwen35-4b__baseline_zero_shot__{T}", "Qwen3.5-4B, zero-shot"),
          (f"qwen35-4b__baseline_best__{T}", "+ best prompt (rulebook in the prompt)"),
          (f"final-A-s3__{T}", "+ domain adapter + Counterfactual Twin Distillation (short prompt, no pre-checks)"),
          (f"final-Brun2-s3__{T}", "+ code pre-checker (reader v3, trained with 25% blank blocks)"),
          (f"{FINAL}__{T}", "+ post-train: SFT on exact labels (= final model, B2)")]
g1 = G2
h2 = ["Stage", "Decision acc %", "Δ decision (pts) [95% CI]", "Risk exact %", "Δ risk", "Actions recall %",
      "Δ actions", "Screening macro-F1 %", "Δ screening", "Unsupported claims %", "Δ unsupported"]
r2, prev, prevc = [], None, None
for run, disp in ladder:
    x = m(run)
    c = correct(run, g1)
    if prev is None:
        dcells = ["–"] * 5
    else:
        d, lo, hi = paired_ci(c, prevc)
        dd = lambda k: f"{(x[k] - prev[k]) * 100:+.1f}" if x.get(k) is not None and prev.get(k) is not None else "–"
        dcells = [f"{d * 100:+.1f} [{lo * 100:+.1f}, {hi * 100:+.1f}]", dd("risk_exact"), dd("actions_recall"),
                  dd("screening_macro_f1"), dd("judge_unsupported_rate")]
    r2.append([disp, pct(x["decision_accuracy"]), dcells[0], pct(x["risk_exact"]), dcells[1],
               pct(x["actions_recall"]), dcells[2], pct(x["screening_macro_f1"]), dcells[3],
               pct(x.get("judge_unsupported_rate")), dcells[4]])
    prev, prevc = x, c

# ---------------------------------------------------------------- Appendix A
SPL = [("eval_id", "eval_id (300)"), ("eval_ood_template", "OOD template (50)"), ("eval_ood_hand", "OOD hand (50)"),
       ("eval_ood_llm", "OOD LLM (100)")]


def split_acc(run: str, split: str) -> str:
    g = gold([f"data/{split}/cases.jsonl"])
    p = preds(run)
    return pct(sum(isinstance(p.get(c), dict) and p[c].get("decision") == g[c]["decision"] for c in g) / len(g))


def safe(run):
    return run in M


appA = [("final-A-s4", "A: model alone (Final A)"), ("final-B-s4", "B: model + pre-checker v2 (Final B, pre-diagnosis)"),
        (FINAL, "B2: model + pre-checker v3, blank-block training (shipped model)")]
hA = ["Model"] + [s for _, s in SPL] + ["Frozen 500", "Hard (150)", "Fresh eval_id v2 (300)"]
rA = []
for run, disp in appA:
    rA.append([disp] + [split_acc(f"{run}__eval_v1", s) for s, _ in SPL]
              + [pct(m(f"{run}__eval_v1")["decision_accuracy"]),
                 pct(m(f"{run}__eval_hard")["decision_accuracy"]) if safe(f"{run}__eval_hard") else "–",
                 pct(m(f"{run}__eval_id_v2")["decision_accuracy"]) if safe(f"{run}__eval_id_v2") else "–"])
for k, d in FRONT:
    run = f"{k}__baseline_best"
    rA.append([f"{d} (best prompt)"] + [split_acc(f"{run}__eval_v1", s) for s, _ in SPL]
              + [pct(m(f"{run}__eval_v1")["decision_accuracy"]),
                 pct(m(f"{run}__eval_hard")["decision_accuracy"]) if safe(f"{run}__eval_hard") else "–",
                 pct(m(f"{run}__eval_id_v2")["decision_accuracy"]) if safe(f"{run}__eval_id_v2") else "–"])

g2 = gold(["data/eval_id_v2/cases.jsonl"])
cB2 = correct(f"{FINAL}__eval_id_v2", g2)
hA2 = ["B2 vs", "Decision acc % (frontier)", "B2 decision acc %", "Paired Δ (pts) [95% CI]", "Verdict"]
rA2 = []
for k, d in FRONT:
    run = f"{k}__baseline_best__eval_id_v2"
    dlt, lo, hi = paired_ci(cB2, correct(run, g2))
    verdict = "tie (CI includes 0)" if lo <= 0 <= hi else ("B2 ahead" if lo > 0 else "frontier ahead")
    rA2.append([f"{d} (best prompt)", pct(m(run)["decision_accuracy"]), pct(m(f"{FINAL}__eval_id_v2")["decision_accuracy"]),
                f"{dlt * 100:+.1f} [{lo * 100:+.1f}, {hi * 100:+.1f}]", verdict])

# ---------------------------------------------------------------- Appendix B
hB = ["Model", "Prompt", "Params", "Decision acc %", "Risk exact %", "Actions recall %", "Screening macro-F1 %",
      "Unsupported claims % (LLM judge)", "Schema valid %", "$ / 1k cases"]
rB = []
for k, d in FRONT:
    for pk, pd in (("baseline_zero_shot", "zero-shot"), ("baseline_best", "best prompt")):
        x = m(f"{k}__{pk}__eval_v1")
        rB.append([d, pd, "undisclosed", pct(x["decision_accuracy"]), pct(x["risk_exact"]), pct(x["actions_recall"]),
                   pct(x["screening_macro_f1"]), pct(x.get("judge_unsupported_rate")), pct(x["schema_validity"]),
                   usd(x.get("cost_per_1k_usd"))])
for k, d, p in OPEN:
    for pk, pd in (("baseline_zero_shot", "zero-shot"), ("baseline_best", "best prompt")):
        x = m(f"{k}__{pk}__eval_v1")
        rB.append([d, pd, p, pct(x["decision_accuracy"]), pct(x["risk_exact"]), pct(x["actions_recall"]),
                   pct(x["screening_macro_f1"]), pct(x.get("judge_unsupported_rate")), pct(x["schema_validity"]),
                   usd(x.get("cost_per_1k_usd"))])

# ---------------------------------------------------------------- Appendix C
dev = [("sft-gold-0p8b__dev", "Qwen3.5-0.8B, trained on the answer key"),
       ("sft-gold-qwen35-0p8b-twins__dev", "Qwen3.5-0.8B, answer key + Counterfactual Twins"),
       ("sft-gold-qwen35-2b__dev", "Qwen3.5-2B, trained on the answer key"),
       ("sft-gold-qwen35-4b__dev", "Qwen3.5-4B, trained on the answer key (ceiling / control)"),
       ("distill-4b-floor__dev", "4B distillation: floor (Sol answers)"),
       ("distill-4b-reject__dev", "4B distillation: + rejection sampling (code checks)"),
       ("distill-4b-arbitrate__dev", "4B distillation: + multi-teacher arbitration (Sol / Argon)"),
       ("distill-4b-twins__dev", "4B distillation: + Counterfactual Twin Distillation (chosen)"),
       ("final-A-s3__dev", "4B: twins on the domain-adapted base")]
hC = ["Run (dev, 150 cases)", "Decision acc %", "Risk exact %", "Field acc % (mean)", "Actions recall %", "Screening macro-F1 %"]
rC = []
for run, disp in dev:
    if not safe(run):
        continue
    x = m(run)
    rC.append([disp, pct(x["decision_accuracy"]), pct(x["risk_exact"]), pct(x["field_accuracy_mean"]),
               pct(x["actions_recall"]), pct(x["screening_macro_f1"])])

doc = f"""# Benchmark report

## Table 1. Final model vs open baselines and frontier models (fresh eval_id v2, 300 cases)

### Table 1a. Decision quality

{table(h1a, r1a)}

### Table 1b. Identity fields, adversarial cases, latency and cost

{table(h1b, r1b)}

## Table 2. Gain from each pipeline stage (final model's pipeline, fresh eval_id v2, 300 cases)

{table(h2, r2)}

## Appendix A. A, B and B2 against the frontier, every test set (decision accuracy %)

A = model alone. B = model + code pre-checker (reader v2), the result before the diagnosis. B2 = final model: pre-checker reader v3, trained with 25% blank blocks, after the diagnosis.

{table(hA, rA)}

## Appendix B. Initial benchmark: open and frontier models, zero-shot and best prompt (frozen eval v1, 500 cases)

{table(hB, rB)}

## Appendix C. Model size and distillation ablation (dev, 150 cases; model selection only, never the test sets)

Rejection sampling scored one case higher than Counterfactual Twin Distillation on decision accuracy (a tie within noise); twins was chosen after seeing dev for its required-actions recall and fewest wrong approvals, and that choice is stated as post-hoc.

{table(hC, rC)}
"""
OUT.write_text(doc, encoding="utf-8", newline="\n")
print(f"wrote {OUT.relative_to(ROOT)}")
