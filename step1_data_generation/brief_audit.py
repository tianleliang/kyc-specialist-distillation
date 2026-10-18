"""Brief compliance audit: one row per detail in the brief, with where it is generated or scored,
example case ids and counts per split, computed from the built data.

    python -m step1_data_generation.brief_audit          # -> documentation/05_progress_reports/brief_compliance.md

Counts are cases (or hits, where the row says so) in data/<split>/cases.jsonl (+ truth.jsonl).
A row is flagged THIN when it covers < 3% of train cases and MISSING when train has none.
Reading eval files here only counts labels; nothing from them feeds training.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
SPLITS = ["train", "train_twins", "train_knockout", "dev", "eval_id", "eval_ood_template"]
OUT = ROOT / "documentation" / "05_progress_reports" / "brief_compliance.md"
FIELDS = ("name", "date_of_birth", "document_number", "expiry", "address")


class Case:
    def __init__(self, row: dict, truth: dict):
        self.row, self.t, self.o, self.k = row, truth, row["expected"], row.get("knobs", {})
        self.id, self.packet, self.scen = row["case_id"], row["packet"], set(row["scenarios"])

    def hits(self):
        """(hit truth, hit output) pairs."""
        return list(zip(self.t["hits"], self.o["screening"]))


def _load(split: str) -> list[Case]:
    d = ROOT / "data" / split
    if not (d / "cases.jsonl").exists():
        return []
    rows = [json.loads(l) for l in (d / "cases.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    truths = {json.loads(l)["case_id"]: json.loads(l)["truth"]
              for l in (d / "truth.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()}
    return [Case(r, truths[r["case_id"]]) for r in rows]


def _in(c: Case, s) -> bool:
    return bool(s) and str(s) in c.packet


def _hit(c: Case, pred) -> bool:
    return any(pred(h, s) for h, s in c.hits())


Row = tuple[str, str, str, Callable[[Case], bool] | Callable[[Case], int]]
G = "step1_data_generation"
# (detail from the brief, where generated, where scored, predicate)
INPUTS: list[Row] = [
    ("Applicant full name", f"{G}/sample.py `_application`; render APP", "name finding; screening", lambda c: _in(c, c.t["application"]["full_name"])),
    ("Applicant date of birth", f"{G}/sample.py `_application`", "date_of_birth finding", lambda c: True),
    ("Applicant nationality", f"{G}/sample.py; per-split nationality pools", "screening (nationality evidence)", lambda c: _in(c, c.t["application"]["nationality"])),
    ("Residential address", f"{G}/lib/address.py", "address finding", lambda c: True),
    ("Occupation", f"{G}/sample.py `OCCUPATIONS`", "risk drivers (high_risk_occupation)", lambda c: _in(c, c.t["application"]["occupation"])),
    ("Declared source of funds", f"{G}/sample.py `SOF_ALL`", "risk drivers (source_of_funds_inconsistent)", lambda c: True),
    ("Expected account activity (+ monthly volume)", f"{G}/sample.py `ACTIVITY`", "risk drivers (activity_inconsistent)", lambda c: _in(c, c.t["application"]["expected_activity"])),
    ("ID document: passport", f"{G}/sample.py `_id_document`", "identity findings", lambda c: c.k.get("id_kind") == "passport"),
    ("ID document: national ID", f"{G}/sample.py `_id_document`", "identity findings", lambda c: c.k.get("id_kind") == "national_id"),
    ("ID document: driving licence (no MRZ)", f"{G}/sample.py `_id_document`", "identity findings (no_mrz_single_source)", lambda c: c.k.get("id_kind") == "driving_licence"),
    ("MRZ present (TD3 / TD1)", f"{G}/lib/mrz.py", "zone check, check digits", lambda c: c.k.get("mrz_format") is not None),
    ("OCR noise in the ID text (background)", f"{G}/render.py + lib/ocr.py", "robustness (all metrics)", lambda c: (c.k.get("id_ocr_level") or 0) > 0),
    ("OCR glyph noise inside the MRZ", f"{G}/sample.py ocr_looks_like_tamper", "ocr_confusable_resolved", lambda c: "ocr_glyph" in c.k.get("defect_kinds", [])),
    ("Proof of address present, dated inside the 90-day window", f"{G}/sample.py `_poa`", "address finding", lambda c: c.k.get("poa_present") and (c.k.get("poa_age_days") or 999) <= 90),
    ("Screening: sanctions hit", f"{G}/sample.py `_hits`, lib/watchlist.py", "screening macro-F1", lambda c: _hit(c, lambda h, s: h["list_type"] == "sanctions")),
    ("Screening: PEP hit", f"{G}/sample.py `_hits`", "screening macro-F1", lambda c: _hit(c, lambda h, s: h["list_type"] == "pep")),
    ("Screening: adverse-media hit", f"{G}/sample.py `_hits`", "screening macro-F1", lambda c: _hit(c, lambda h, s: h["list_type"] == "adverse_media")),
    ("Hit lists aliases", f"{G}/lib/watchlist.py `make_entry`", "screening evidence", lambda c: _hit(c, lambda h, s: bool(h["entry"]["aliases"]))),
    ("Hit lists a DOB (known)", f"{G}/lib/watchlist.py", "screening evidence", lambda c: _hit(c, lambda h, s: h["entry"]["dob"] not in ("", "unknown"))),
    ("Hit DOB not listed", f"{G}/lib/watchlist.py", "screening evidence (dob_not_listed)", lambda c: _hit(c, lambda h, s: h["list_type"] != "adverse_media" and h["entry"]["dob"] in ("", "unknown"))),
    ("Hit lists a nationality", f"{G}/lib/watchlist.py", "screening evidence", lambda c: _hit(c, lambda h, s: bool(h["entry"].get("nationality")))),
    ("Hit list source (OFAC/UN/EU/UK-structured, PEP DB, media)", f"{G}/lib/watchlist.py `LIST_SOURCES`", "screening list_type", lambda c: _hit(c, lambda h, s: _in(c, h["entry"]["list_source"]))),
    ("Hit vendor similarity score", f"{G}/lib/watchlist.py `score_hit`", "(never decides alone, policy §4)", lambda c: _hit(c, lambda h, s: True)),
    ("No screening hits", f"{G}/sample.py `_hits`", "screening (empty list)", lambda c: not c.t["hits"]),
    ("Context: onboarding country", f"{G}/sample.py", "cross_border driver", lambda c: True),
    ("Context: product type", f"{G}/sample.py `PRODUCTS`", "high_risk_product_remote_channel", lambda c: True),
    ("Context: channel", f"{G}/sample.py `CHANNELS`", "high_risk_product_remote_channel", lambda c: True),
    ("Context: as-of date printed", f"{G}/render.py CTX", "expiry and PoA window", lambda c: _in(c, "as of") or _in(c, "As-of") or _in(c, "as-of")),
]
OUTPUTS: list[Row] = [("identity_verified = true", f"{G}/project.py `verified`", "Table 1b verified acc", lambda c: c.o["identity_verified"]),
                      ("identity_verified = false", f"{G}/project.py `verified`", "Table 1b verified acc", lambda c: not c.o["identity_verified"])]
for f in FIELDS:
    for v in ("consistent", "mismatch", "unreadable"):
        OUTPUTS.append((f"{f} = {v}", f"{G}/project.py `identity`", f"field accuracy ({f})",
                        (lambda f, v: lambda c: c.o[f"{f}_status"] == v)(f, v)))
OUTPUTS.append(("every finding has a reason code", f"{G}/project.py", "schema validity", lambda c: all(c.o[f"{f}_reason"] for f in FIELDS)))
for v in ("true_match", "false_positive", "needs_review"):
    OUTPUTS.append((f"screening disposition = {v} (cases with one)", f"{G}/project.py `_disposition`", "screening macro-F1",
                    (lambda v: lambda c: any(s["disposition"] == v for s in c.o["screening"]))(v)))
OUTPUTS.append(("screening evidence listed for every hit", f"{G}/project.py", "schema validity", lambda c: all(s["evidence"] for s in c.o["screening"])))
for v in ("low", "medium", "high"):
    OUTPUTS.append((f"risk_tier = {v}", f"{G}/project.py `risk`", "risk exact / ±1", (lambda v: lambda c: c.o["risk_tier"] == v)(v)))
OUTPUTS += [
    ("risk drivers listed (tier above low)", f"{G}/project.py `risk`", "(not scored by the brief)", lambda c: bool(c.o["risk_drivers"])),
    ("required actions: at least one", f"{G}/project.py `actions`", "actions recall", lambda c: bool(c.o["required_actions"])),
    ("required actions: none", f"{G}/project.py `actions`", "actions recall", lambda c: not c.o["required_actions"]),
]
for v in ("approve", "reject", "escalate"):
    OUTPUTS.append((f"decision = {v}", f"{G}/project.py `decide`", "decision accuracy", (lambda v: lambda c: c.o["decision"] == v)(v)))
OUTPUTS += [
    ("narrative has 4-8 sentences", f"{G}/project.py `narrative`", "schema validity", lambda c: 4 <= len(c.o["narrative"]) <= 8),
    ("every narrative sentence cites packet sections (refs resolve)", f"{G}/project.py `narrative`, `ref_ids`", "unsupported claims",
     lambda c: all(set(s["evidence_refs"]) | set(s["hit_ids"]) <= set(c.row.get("ref_ids", [])) for s in c.o["narrative"])),
]


def _translit(origin):
    return lambda c: c.o["name_reason"] == "transliteration_variant" and c.k.get("origin") == origin


HARD: list[Row] = [
    ("Transliterated names: Arabic", f"{G}/lib/names.py; scenario translit_name", "name field acc", _translit("arabic")),
    ("Transliterated names: Cyrillic", f"{G}/lib/names.py", "name field acc", _translit("cyrillic")),
    ("Transliterated names: Chinese", f"{G}/lib/names.py", "name field acc", _translit("chinese")),
    ("Reordered names", "scenario reordered_name", "name field acc", lambda c: c.o["name_reason"] == "reordered_tokens"),
    ("Name variants against sanctions aliases: true match", "scenario alias_true_match", "screening F1, decision (reject)",
     lambda c: _hit(c, lambda h, s: h["list_type"] == "sanctions" and s["disposition"] == "true_match")),
    ("Name variants against sanctions aliases: alias / variant-only name match", "watchlist aliases", "screening F1",
     lambda c: _hit(c, lambda h, s: h["list_type"] == "sanctions" and s["evidence"][0] != "name_exact")),
    ("Name variants: sanctions false positive (similar other person)", "scenario sanctions_false_positive", "screening F1",
     lambda c: _hit(c, lambda h, s: h["list_type"] == "sanctions" and s["disposition"] == "false_positive")),
    ("Partial date-of-birth matches", "scenario partial_dob", "screening F1 (needs_review)", lambda c: _hit(c, lambda h, s: "dob_partial" in s["evidence"])),
    ("PEP by family association", "scenario pep_family", "screening F1, decision", lambda c: _hit(c, lambda h, s: h.get("pep_relation") == "family")),
    ("PEP by business association (close associate)", "scenario pep_associate", "screening F1, decision", lambda c: _hit(c, lambda h, s: h.get("pep_relation") == "close_associate")),
    ("PEP self", "scenario pep_self", "screening F1, decision", lambda c: _hit(c, lambda h, s: h["list_type"] == "pep" and h.get("pep_relation") == "self")),
    ("Expired documents", "scenario expired_document", "expiry field acc, decision", lambda c: c.o["expiry_reason"] == "document_expired"),
    ("Address formats that differ by country (same address, different print)", f"{G}/lib/address.py (10 countries)", "address field acc",
     lambda c: c.o["address_reason"] == "country_format_difference"),
    ("Address in a country other than the onboarding country", "scenario foreign_address_format", "address field acc, cross_border",
     lambda c: c.k.get("residence") != c.k.get("onboarding_country")),
    ("Proof of address contradicts the application (address differs)", "scenario poa_contradicts", "address field acc",
     lambda c: c.o["address_reason"] == "poa_address_differs"),
    ("Proof of address addressed to someone else", "scenario poa_name_differs (Session L)", "address field acc",
     lambda c: c.o["address_reason"] == "poa_name_differs"),
    ("Proof of address outside the window (stale)", "scenario poa_stale", "address field acc", lambda c: c.o["address_reason"] == "poa_stale"),
    ("OCR errors that look like tampering: readable noise", "scenario ocr_looks_like_tamper", "field acc (consistent), decision",
     lambda c: any(c.o[f"{f}_reason"] == "ocr_confusable_resolved" for f in FIELDS)),
    ("OCR errors that look like tampering: ambiguous digit misread (no tamper)", "ocr_looks_like_tamper digit_lookalike", "field acc, decision (escalate)",
     lambda c: c.t["id_doc"]["tamper"] is None and any(c.o[f"{f}_reason"] == "ocr_or_tamper_ambiguous" for f in FIELDS)),
    ("Tampering that looks like OCR errors (real tamper, ambiguous or subtle)", "scenario tamper_looks_like_ocr", "field acc, decision",
     lambda c: "tamper_looks_like_ocr" in c.scen),
    ("Clear tamper evidence (reject, D4)", "scenarios tamper_obvious / tamper_looks_like_ocr", "decision (reject)",
     lambda c: any(c.o[f"{f}_reason"] in ("viz_mrz_disagree", "check_digit_failed", "impossible_date") for f in FIELDS)),
    ("Packets with instructions addressed to the model", "scenario prompt_injection (7 locations, 5+ techniques)", "adversarial escalation",
     lambda c: c.t["injection"]["present"]),
    ("Evidence does not support a decision: unreadable field / missing PoA", "scenario insufficient_evidence", "adversarial escalation (ambiguous)",
     lambda c: any(c.o[f"{f}_status"] == "unreadable" for f in FIELDS)),
    ("Evidence does not support a decision: unresolvable hit (needs_review)", "partial_dob, hit_no_identifiers", "adversarial escalation",
     lambda c: any(s["disposition"] == "needs_review" for s in c.o["screening"])),
    ("Application vs document disagree (name or DOB)", "scenarios dob_mismatch, name_mismatch (Session L)", "field acc, decision",
     lambda c: any(c.o[f"{f}_reason"] == "application_document_disagree" for f in FIELDS)),
    ("Adverse media (true match / false positive)", "scenarios adverse_media_true/false", "screening F1, risk", lambda c: _hit(c, lambda h, s: h["list_type"] == "adverse_media")),
    ("Risk profile: source of funds / activity inconsistent", "scenario risk_profile", "risk tier, actions",
     lambda c: bool({"source_of_funds_inconsistent", "activity_inconsistent"} & set(c.o["risk_drivers"]))),
]
METRICS = [
    ("Decision accuracy (approve / reject / escalate)", "step6_evaluation/metrics.py `decision_accuracy`", "cases"),
    ("Screening disposition macro-F1 over 3 dispositions", "`screening_macro_f1` (absent classes excluded, D15)", "hits"),
    ("Field findings: accuracy per identity field", "`field_accuracy.<field>`; mean excludes verified (D15)", "cases × 5"),
    ("Risk tier: exact and off-by-one", "`risk_exact`, `risk_within_one`", "cases"),
    ("Required actions: recall against ground truth", "`actions_recall` (+ precision)", "gold actions"),
    ("Unsupported claims: narrative sentences not grounded", "`unsupported_rate` (programmatic refs + hit_ids; LLM judge prompt in step0_rules/prompts)", "sentences"),
    ("Schema validity: parse and validate", "`schema_validity` (strict parse, D15)", "cases"),
    ("Adversarial: escalation on injected instructions", "`adv_escalation_rate.injection` (gold-escalate cases) + decision acc", "injected cases"),
    ("Adversarial: escalation on ambiguous evidence", "`adv_escalation_rate.ambiguous`", "ambiguous cases"),
    ("Latency p50 / p95, cost per 1,000 cases, parameters", "`latency_p50_ms`, `latency_p95_ms`, `cost_per_1k_usd`; params from run.json", "requests"),
]


def _metric_denoms(cases: list[Case]) -> dict[str, int]:
    return {"cases": len(cases), "hits": sum(len(c.o["screening"]) for c in cases), "cases × 5": 5 * len(cases),
            "gold actions": sum(len(c.o["required_actions"]) for c in cases),
            "sentences": sum(len(c.o["narrative"]) for c in cases),
            "injected cases": sum("prompt_injection" in c.scen for c in cases),
            "ambiguous cases": sum(bool(c.scen & {"insufficient_evidence", "partial_dob"}) for c in cases),
            "requests": len(cases)}


def build(splits=SPLITS) -> str:
    data = {s: _load(s) for s in splits}
    data = {s: v for s, v in data.items() if v}
    tr = data["train"]
    flags: list[str] = []

    def table(title: str, rows: list[Row], flag: bool = True) -> str:
        head = ["Brief detail", "Generated", "Scored by", "Examples (train)"] + [f"{s} (n={len(v)})" for s, v in data.items()] + ["Flag"]
        out = [f"## {title}", "", "| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
        for name, gen, scored, pred in rows:
            counts = {s: sum(1 for c in v if pred(c)) for s, v in data.items()}
            ex = [c.id for c in tr if pred(c)][:2]
            if not ex:
                ex = [f"{c.id} ({s})" for s, v in data.items() for c in v if pred(c)][:2]
            share = counts["train"] / len(tr)
            fl = "MISSING" if counts["train"] == 0 else ("THIN" if share < 0.03 else "")
            if fl and flag:
                flags.append(f"{fl}: {name} ({counts['train']} train cases, {100 * share:.1f}%)")
            cells = [name, gen, scored, ", ".join(f"`{e}`" for e in ex) or "—"]
            cells += [f"{n} ({100 * n / len(data[s]):.1f}%)" for s, n in counts.items()] + [fl if flag else ""]
            out.append("| " + " | ".join(cells) + " |")
        return "\n".join(out)

    from step1_data_generation.sample import BRIEF_COVERAGE
    cov = ["## 0. Brief hard-case items (scenario coverage, primary or stacked secondary)", "",
           "The decision-mix tuning kept every item at >= 4% of train. Rows below in §1-§3 are finer cuts, so a THIN "
           "flag there can sit inside a well-covered item (e.g. PEP family 2.9% + associate 2.7% + self 2.8%).", "",
           "| Brief item | Scenarios | " + " | ".join(data) + " |", "|---|---|" + "---|" * len(data)]
    for item, scens in BRIEF_COVERAGE.items():
        cells = []
        for sp, v in data.items():
            n = sum(1 for c in v if c.scen & set(scens))
            cells.append(f"{n} ({100 * n / len(v):.1f}%)")
        cov.append(f"| {item} | {', '.join(scens)} | " + " | ".join(cells) + " |")
    parts = ["\n".join(cov), table("1. Inputs (the case packet)", INPUTS),
             table("2. Outputs (every field and value)", OUTPUTS),
             table("3. What makes it hard", HARD)]
    den = {s: _metric_denoms(v) for s, v in data.items()}
    m = ["## 4. Metrics", "", "| Brief metric | Implemented as | Denominator | " + " | ".join(data) + " |",
         "|---|---|---|" + "---|" * len(data)]
    for name, impl, unit in METRICS:
        m.append(f"| {name} | {impl} | {unit} | " + " | ".join(str(den[s][unit]) for s in data) + " |")
    parts.append("\n".join(m))
    hdr = [
        "# Brief compliance audit (Session L, policy v1)",
        "",
        "Generated by `python -m step1_data_generation.brief_audit` from `data/<split>/cases.jsonl` + `truth.jsonl`; "
        "rerun it after any rebuild. Counts are **cases** that show the detail (a percentage of the split), except where a row says hits. "
        "**THIN** = under 3% of train cases; **MISSING** = no train case. Examples are train case ids.",
        "",
        "Splits: `train` (3,000 base cases), `train_twins` (1,000 counterfactual twins of train cases), `train_knockout` "
        "(300 evidence knockouts of train cases), `dev` (150), `eval_id` (300), `eval_ood_template` (50, the template part of "
        "the OOD set; the 100 LLM-rendered OOD packets and the 50 hand templates are built by Session M). The eval sets are built "
        "but **not frozen** yet (the freeze follows the dev pilot).",
        "",
        "### Flags (train)",
        "",
    ]
    body = "\n\n".join(parts)
    hdr += [f"- {f}" for f in flags] or ["- none"]
    return "\n".join(hdr) + "\n\n" + body + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args(argv)
    a.out.write_text(build(), encoding="utf-8", newline="\n")
    print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
