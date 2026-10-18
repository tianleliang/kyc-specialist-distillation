"""LLM-written OOD packets: a frontier model renders eval truths in novel layouts (D13/D14: 100 cases).

    python -m step1_data_generation.ood_llm --allow-eval                       # real run on the laptop (~$5)
    python -m step1_data_generation.ood_llm --allow-eval --mock --out /tmp/x   # plumbing check, no network
    python -m step1_data_generation.ood_llm --allow-eval --dry-run             # print plan + one prompt, no calls

Truths come from ``configs/eval_ood_template.yaml`` (entity bucket 9, OOD pools) with their own seed
(4020000) and case-id prefix (``oodl``), disjoint from the hand-template set (4010000) and L's
``eval_ood_template`` build (4000000). Renderers alternate by case index between
``claude-sonnet-5-5`` (Anthropic) and ``gemini-3.8-flash`` (Gemini), through ``shared/frontier_api``
(disk cache, retries, cost ledger), using the eval-only ``step0_rules/prompts/ood_renderer`` template.

What the model sees: a *visible* truth view only (what the packet must show: context, application,
the ID document's visual zone and MRZ exactly as OCR'd, the proof of address, every hit as the vendor
lists it, the injected text and where it goes). Never scenario names, relations, defect/tamper notes,
same-person flags or risk facts, so it cannot leak or "explain" them. The label still comes from the
full truth through ``project.py``.

Every packet is checked before it is kept:
  * ``check_ood_packet`` on the verbatim strings (names, document number, MRZ lines, address lines,
    occupation/employer/activity, hit ids, list sources, record ids, listed names, aliases, listed DOBs,
    the injected text, the illegible marker);
  * every date in an unambiguous form (ISO, or day + month name + year in any order);
  * the expected monthly volume (with or without thousands separators);
  * no hidden-truth words (``tamper``, ``expired``, ``true match`` ...) outside the injected text.
A packet failing any check is dropped (its gold label may no longer hold), and the drop reason is
logged per model and per scenario. ``--oversample`` samples extra truths so ~n survive; the first n
survivors in index order are kept.

Outputs (``data/eval_ood_llm/``): ``cases.jsonl`` (build.py's row format plus renderer/model),
``truth.jsonl``, ``dropped.jsonl`` (case id, model, reasons; for the audit), ``manifest.json``
(counts, drop log, cost, prompt hashes, sha256 of every file).
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import re
import sys
from datetime import date
from pathlib import Path

from step1_data_generation import ood_templates as H
from step1_data_generation.truth import GENERATOR_VERSION, CaseTruth

DEFAULT_OUT = Path("data") / "eval_ood_llm"
DEFAULT_SEED = 4020000
DEFAULT_N = 100
SPLIT = "eval_ood_llm"
RENDERER = "llm_ood_renderer_v1"
ILLEGIBLE = "[illegible]"
MODELS = [("anthropic", "claude-sonnet-5-5"), ("gemini", "gemini-3.8-flash")]
MAX_TOKENS = 3000

DATE_RULE = ("Write every date either as YYYY-MM-DD or with the month spelled out (e.g. 4 March 2026); "
             "never in a numeric day/month form such as 04/03/2026.")
STYLE_BRIEFS = [
    "An XML message exported from a legacy core-banking system: elements and attributes for the application "
    "and context, the ID and proof-of-address OCR text inside CDATA blocks, screening hits as repeated elements.",
    "A CSV export with a header row 'section,field,value' and one quoted row per fact; OCR text and MRZ lines "
    "go in their own rows, one row per line.",
    "An internal messenger chat between a branch officer and a back-office colleague, with timestamps and short "
    "messages; the officer pastes the application details, the OCR of each uploaded document and the screening "
    "printout as attachments.",
    "A credit-union member intake worksheet with checkbox lines ('[x]') and fill-in blanks transcribed from a "
    "paper form, followed by the OCR of the attached documents and the screening report.",
    "A YAML dossier produced by a workflow tool: nested keys, OCR text and MRZ lines as literal block scalars, "
    "screening hits as a list of mappings.",
    "A memo written in full sentences by a junior analyst summarising what was received (no judgement, no "
    "conclusions), with the document OCR and the screening report reproduced in appendices A to C.",
    "A mobile-app onboarding event log: one line per event with an ISO timestamp, an event name and key=value "
    "payload; document captures carry their OCR text and the screening call carries its results.",
    "A referral letter from an introducer firm, followed by transcriptions of the enclosed documents and the "
    "screening vendor's plain-text report in fixed-width columns.",
    "Text extracted from an intranet case page: section headings in capitals, tab- or pipe-separated tables, "
    "and the screening results as a grid.",
    "A packet from an overseas branch with field labels in Spanish or French (values exactly as given), the "
    "document OCR in its original layout, and the screening results with English column headers.",
]


# --------------------------------------------------------------------------
# what the model is allowed to see
# --------------------------------------------------------------------------
def _lines(addr, style: str = "postal", abbreviate: bool = False) -> list[str]:
    return [l.strip() for l in addr.render(style, abbreviate=abbreviate).splitlines() if l.strip()]


def visible_truth(t: CaseTruth) -> dict:
    """The facts the packet must show, and nothing that explains them."""
    c, a, d, p, inj = t.context, t.application, t.id_doc, t.poa, t.injection
    viz = {k: (v if v else ILLEGIBLE) for k, v in d.viz.items()}
    if not p.present:
        poa = {"provided": False}
    elif not p.legible:
        poa = {"provided": True, "document_type": p.kind, "scan_quality": "unreadable: render the document body as "
               "OCR garbage symbols; include no name, address, issuer or date from it"}
    else:
        poa = {"provided": True, "document_type": p.kind, "issuer": p.issuer, "document_date": p.issue_date.isoformat(),
               "addressed_to": p.name_on_doc, "address_lines": _lines(p.address, p.render_style, p.abbreviated)}
    hits = [{"hit_id": h.hit_id, "list_type": h.list_type, "list_source": h.entry["list_source"],
             "record_id": h.entry["entry_id"], "listed_name": h.entry["primary_name"],
             "aliases": [{"name": n, "quality": q} for n, q in zip(h.entry.get("aliases") or [],
                                                                    h.entry.get("alias_quality") or [])],
             "listed_dob": h.entry.get("dob") or "unknown",
             "listed_nationality": h.entry.get("nationality") or "not listed",
             "vendor_score": h.score, "matched_on": h.matched_on,
             "details": {k: v for k, v in (h.entry.get("details") or {}).items() if v not in ("", None, [])}}
            for h in t.hits]
    out = {
        "context": {"case_ref": c.case_ref, "onboarding_country": c.onboarding_country, "product": c.product,
                    "channel": c.channel, "application_date": c.application_date.isoformat(),
                    "review_as_of_date": c.as_of_date.isoformat()},
        "applicant_profile": {"full_name": a.full_name, "date_of_birth": a.dob.isoformat(), "nationality": a.nationality,
                              "residential_address_lines": _lines(a.address, "postal", a.address_abbreviated),
                              "occupation": a.occupation, "employer": a.employer,
                              "source_of_funds": a.source_of_funds, "expected_monthly_volume": a.expected_monthly_volume,
                              "currency": a.currency, "expected_activity": a.expected_activity},
        "identity_document": {"document_type": d.kind, "issuing_state": d.issuing_state, "visual_zone_ocr": viz,
                              "mrz_lines_ocr": list(d.mrz_lines) if d.mrz_lines else None},
        "proof_of_address": poa,
        "screening_hits": hits,
    }
    if inj.present:
        out["injected_text"] = {"place_it_in": inj.location, "text": inj.text}
    return out


def required_strings(t: CaseTruth) -> list[str]:
    """Strings that must appear verbatim (passed to the prompt and to check_ood_packet)."""
    v = visible_truth(t)
    a, d, p = v["applicant_profile"], v["identity_document"], v["proof_of_address"]
    req = [v["context"]["case_ref"], a["full_name"], a["occupation"], a["employer"], a["expected_activity"],
           *a["residential_address_lines"], a["nationality"], d["issuing_state"]]
    req += [d["visual_zone_ocr"][k] for k in ("surname", "given_names", "doc_number", "nationality")]
    if ILLEGIBLE in d["visual_zone_ocr"].values():
        req.append(ILLEGIBLE)
    req += d["mrz_lines_ocr"] or []
    if p.get("address_lines"):
        req += [p["addressed_to"], p["issuer"], *p["address_lines"]]
    for h in v["screening_hits"]:
        req += [h["hit_id"], h["list_source"], h["record_id"], h["listed_name"], h["listed_dob"],
                *[x["name"] for x in h["aliases"]]]
        req += [str(x) for k, x in h["details"].items() if k in ("relationship", "related_pep", "position",
                                                                   "age_reported", "city_reported",
                                                                   "occupation_reported", "remarks")]
    if "injected_text" in v:
        req.append(v["injected_text"]["text"])
    return list(dict.fromkeys(s for s in req if s))


def required_dates(t: CaseTruth) -> list[str]:
    v = visible_truth(t)
    ds = [v["context"]["application_date"], v["context"]["review_as_of_date"], v["applicant_profile"]["date_of_birth"]]
    ds += [v["identity_document"]["visual_zone_ocr"][k] for k in ("birth_date", "expiry_date", "issue_date")]
    if v["proof_of_address"].get("document_date"):
        ds.append(v["proof_of_address"]["document_date"])
    return list(dict.fromkeys(x for x in ds if x != ILLEGIBLE))


# --------------------------------------------------------------------------
# checks
# --------------------------------------------------------------------------
_MON = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
_MON_LONG = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
             "november", "december"]


def date_forms(iso: str) -> list[str]:
    """Unambiguous renderings of an ISO date that we accept (compared case-insensitively)."""
    d = date.fromisoformat(iso)
    forms = {iso, f"{d.year}/{d.month:02d}/{d.day:02d}", f"{d.year}.{d.month:02d}.{d.day:02d}"}
    for m in (_MON[d.month - 1], _MON_LONG[d.month - 1]):
        for day in (str(d.day), f"{d.day:02d}"):
            forms |= {f"{day} {m} {d.year}", f"{day}-{m}-{d.year}", f"{m} {day}, {d.year}", f"{m} {day} {d.year}",
                      f"{day} {m}. {d.year}", f"{day}. {m} {d.year}"}
    return sorted(forms)


def date_present(iso: str, packet: str) -> bool:
    low = " ".join(packet.casefold().split())
    return any(f.casefold() in low for f in date_forms(iso))


def number_present(n: int, packet: str) -> bool:
    forms = {str(n), f"{n:,}", f"{n:,}".replace(",", " "), f"{n:,}".replace(",", "."), f"{n:,}".replace(",", " ")}
    return any(re.search(rf"(?<![\d.,]){re.escape(f)}(?![\d])", packet) for f in forms)


def strip_fences(text: str) -> str:
    m = re.fullmatch(r"\s*```[a-zA-Z]*\n(.*?)\n?```\s*", text, re.S)
    return m.group(1) if m else text.strip()


def check_llm_packet(packet: str, t: CaseTruth) -> dict[str, list[str]]:
    """Drop reasons by kind (empty dict = keep)."""
    from step0_rules.prompts.render import check_ood_packet

    probs: dict[str, list[str]] = {}
    miss = check_ood_packet(packet, required_strings(t))
    if miss:
        probs["missing_or_fixed"] = miss
    bad_dates = [x for x in required_dates(t) if not date_present(x, packet)]
    if bad_dates:
        probs["date_missing"] = bad_dates
    if not number_present(t.application.expected_monthly_volume, packet):
        probs["volume_missing"] = [str(t.application.expected_monthly_volume)]
    scrub = packet.replace(t.injection.text, " ") if t.injection.present else packet
    leaks = [w for w in H.LEAK_WORDS if w in scrub.casefold()]
    if leaks:
        probs["leak"] = leaks
    return probs


# --------------------------------------------------------------------------
# run
# --------------------------------------------------------------------------
def plan(n: int, seed: int, oversample: float = 1.25) -> list[dict]:
    m = max(n, math.ceil(n * oversample))
    truths = H.sample_truths(m, seed, "oodl")
    out = []
    for i, t in enumerate(truths):
        provider, model = MODELS[i % len(MODELS)]
        out.append({"truth": t, "provider": provider, "model": model,
                    "style": STYLE_BRIEFS[(i // len(MODELS)) % len(STYLE_BRIEFS)]})
    return out


def build_request(item: dict):
    from shared.frontier_api.clients import make_request
    from step0_rules.prompts.render import render_ood

    t = item["truth"]
    rp = render_ood(visible_truth(t), item["style"] + " " + DATE_RULE, required_strings(t))
    req = make_request(item["provider"], item["model"], user=rp.user, system=rp.system, max_tokens=MAX_TOKENS,
                       reasoning_effort="low", purpose="other", metadata={"case_id": t.case_id})
    return req, rp


def mock_responder(items: list[dict], style: str = "case_ticket"):
    """For --mock and tests: answer each request with a hand-template packet of its truth."""
    by_id = {it["truth"].case_id: it["truth"] for it in items}

    def respond(req):
        return H.render_hand(by_id[req.metadata["case_id"]], style)[0]

    return respond


def run(n: int = DEFAULT_N, seed: int = DEFAULT_SEED, out: Path = DEFAULT_OUT, *, allow_eval: bool = False,
        force: bool = False, client=None, oversample: float = 1.25, mock: bool = False, log=print) -> dict:
    H.guard_out(out, allow_eval, force)
    import jsonschema

    project, schema, schema_id = H.labeller()
    validator = jsonschema.Draft202012Validator(schema)
    items = plan(n, seed, oversample)
    if client is None:
        from shared.frontier_api.clients import LLMClient

        client = LLMClient(mock=mock, mock_responder=mock_responder(items) if mock else None)
    built = [build_request(it) for it in items]
    resps = client.complete_many([r for r, _ in built], max_workers=4)

    rows, truth_rows, dropped = [], [], []
    log_counts: dict = {"by_model": collections.defaultdict(collections.Counter),
                        "by_scenario": collections.defaultdict(collections.Counter)}
    for it, (req, rp), resp in zip(items, built, resps):
        t = it["truth"]
        key = (it["model"], t.scenarios[0])
        if getattr(resp, "error", None) or not (resp.text or "").strip():
            reasons = {"error": [resp.error or "empty response"]}
        else:
            packet = strip_fences(resp.text)
            reasons = check_llm_packet(packet, t)
        if not reasons and len(rows) >= n:
            reasons = {"surplus": ["target n already reached"]}
        status = next(iter(reasons), "kept")
        log_counts["by_model"][key[0]][status] += 1
        log_counts["by_scenario"][key[1]][status] += 1
        if reasons:
            dropped.append({"case_id": t.case_id, "model": it["model"], "scenarios": t.scenarios, "reasons": reasons,
                            "packet": None if "error" in reasons else packet})
            continue
        expected = project(t)
        errs = list(validator.iter_errors(expected))
        if errs:
            raise ValueError(f"{t.case_id}: expected output fails schema: {errs[0].message}")
        t.split = "eval_ood_template"
        t.knobs = {**t.knobs, "style": f"llm_brief_{STYLE_BRIEFS.index(it['style'])}", "style_family": "ood_llm",
                   "renderer": RENDERER, "render_model": it["model"]}
        rows.append({"case_id": t.case_id, "split": SPLIT, "config_id": t.config_id, "schema": schema_id,
                     "style": t.knobs["style"], "renderer": RENDERER, "render_model": it["model"],
                     "scenarios": t.scenarios, "knobs": t.knobs, "packet": packet, "expected": expected,
                     "render_prompt": rp.provenance(), "render_cost_usd": resp.cost_usd})
        truth_rows.append({"case_id": t.case_id, "truth": t.to_dict()})

    out.mkdir(parents=True, exist_ok=True)
    sha = H.write_jsonl_files(out, {"cases.jsonl": rows, "truth.jsonl": truth_rows, "dropped.jsonl": dropped})
    totals = collections.Counter()
    for c in log_counts["by_model"].values():
        totals.update(c)
    manifest = {
        "split": SPLIT, "renderer": RENDERER, "models": [m for _, m in MODELS], "mock": bool(getattr(client, "mock", mock)),
        "config_path": str(H.CONFIG.relative_to(H.ROOT)), "generator_version": GENERATOR_VERSION,
        "git_commit": H._git_commit(), "schema": schema_id, "seed": seed, "n_target": n, "n_rendered": len(items),
        "n_kept": len(rows), "oversample": oversample,
        "command": f"python -m step1_data_generation.ood_llm --allow-eval --n {n} --seed {seed}",
        "status_totals": dict(totals),
        "status_by_model": {k: dict(v) for k, v in log_counts["by_model"].items()},
        "status_by_primary_scenario": {k: dict(v) for k, v in sorted(log_counts["by_scenario"].items())},
        "decision_counts": dict(collections.Counter(r["expected"].get("decision") for r in rows)),
        "kept_by_model": dict(collections.Counter(r["render_model"] for r in rows)),
        "cost": client.ledger.summary() if hasattr(client, "ledger") else None,
        "prompt": built[0][1].provenance() if built else None,
        "sha256": sha,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False, default=str)
                                       + "\n", encoding="utf-8", newline="\n")
    log(f"[ood_llm] rendered {len(items)}, kept {len(rows)} (target {n}); status {dict(totals)}")
    for m_, c in manifest["status_by_model"].items():
        log(f"[ood_llm]   {m_}: {c}")
    return manifest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=DEFAULT_N, help="cases to keep")
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--oversample", type=float, default=1.25, help="render ceil(n*x) truths so ~n survive the checks")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--allow-eval", action="store_true", help="required: this writes an eval set")
    ap.add_argument("--force", action="store_true", help="overwrite an unfrozen manifest.json")
    ap.add_argument("--mock", action="store_true", help="no network: hand-template packets stand in for the model")
    ap.add_argument("--dry-run", action="store_true", help="print the plan and the first prompt; no calls, no files")
    a = ap.parse_args(argv)
    if a.dry_run:
        items = plan(a.n, a.seed, a.oversample)
        print(json.dumps(dict(collections.Counter(it["model"] for it in items))), file=sys.stderr)
        req, rp = build_request(items[0])
        sys.stdout.write(f"=== system ===\n{rp.system}\n\n=== user ===\n{rp.user}\n")
        return 0
    run(a.n, a.seed, a.out, allow_eval=a.allow_eval, force=a.force, oversample=a.oversample, mock=a.mock)
    return 0


if __name__ == "__main__":
    sys.exit(main())
