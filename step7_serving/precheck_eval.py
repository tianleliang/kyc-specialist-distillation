"""Accuracy and coverage of the deterministic pre-checker vs the latent truth.

    python -m step7_serving.precheck_eval                    # data/train + data/dev
    python -m step7_serving.precheck_eval --splits dev --show-errors 5

This is the ONLY script allowed to read ``truth.jsonl``; ``prechecks.py``
itself only sees the packet text. It refuses eval splits (anything whose
directory name starts with ``eval``) so the frozen eval sets stay unseen.

Fields scored (coverage = share of cases where the pre-checker produced a
value; accuracy = share of covered cases where that value matches truth):

* as_of    : as-of date == truth.context.as_of_date
* mrz      : MRZ status (valid / ocr_repairable / invalid / unreadable) ==
             truth.id_doc.mrz_check; a document with no MRZ must yield none
* expiry   : expiry date == the expiry the document prints in its
             authoritative zone (MRZ field of truth.id_doc.mrz_lines, after
             the lib's OCR repair, when its check digit passes; visual-zone
             date when there is no MRZ)
* expired  : EXPIRED / NOT EXPIRED == (that expiry < truth as-of); also
             counted: cases whose expected label is ``document_expired`` but
             the pre-checker said NOT EXPIRED (must be 0)
* poa_date : POA date == truth.poa.issue_date (POA present only)
* poa_window: WITHIN 90 / OLDER THAN 90 / AFTER == truth window

Document integrity (pre-checker v2, policy_v1 §3), scored against the GOLD
identity reason codes in ``expected`` (n = every case; coverage = not n/d):

* integ_<field> for date_of_birth / document_number / expiry: the computed
  class must be the one the gold reason implies (all_sources_agree ->
  consistent, or single source for a no-MRZ date of birth;
  ocr_confusable_resolved -> noise; ocr_or_tamper_ambiguous -> ambiguous;
  viz_mrz_disagree / check_digit_failed / impossible_date -> tamper;
  field_illegible -> unreadable; no_mrz_single_source -> single source;
  application_document_disagree / document_expired, decided after §3 ->
  any zone-fine class: consistent, noise or single source)
* integ_overall: clear tamper if any gold field is clear tamper, else
  ambiguous, else noise only, else consistent (a field whose gold reason is
  decided after §3 may be noise or consistent)

    python -m step7_serving.precheck_eval --md step7_serving/results/precheck_v2_eval_train_dev.md \
        --json step7_serving/results/precheck_v2_eval_train_dev.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from step1_data_generation.lib import mrz as M  # noqa: E402
from step1_data_generation.lib import ocr as O  # noqa: E402
from step7_serving import prechecks as P  # noqa: E402
from step7_serving.prechecks import POA_WINDOW_DAYS, run_prechecks  # noqa: E402

FIELDS = ("as_of", "mrz", "expiry", "expired", "poa_date", "poa_window")
INTEG_MAP = {"birth_date": "date_of_birth", "doc_number": "document_number", "expiry_date": "expiry"}
INTEG_FIELDS = tuple(f"integ_{v}" for v in INTEG_MAP.values()) + ("integ_overall",)
_ZONE_FINE = {P.CONSISTENT, P.NOISE, P.NO_MRZ}
_GOLD_CLASS = {"all_sources_agree": {P.CONSISTENT}, "ocr_confusable_resolved": {P.NOISE},
               "ocr_or_tamper_ambiguous": {P.AMBIGUOUS}, "viz_mrz_disagree": {P.TAMPER},
               "check_digit_failed": {P.TAMPER}, "impossible_date": {P.TAMPER},
               "field_illegible": {P.UNREADABLE}, "no_mrz_single_source": {P.NO_MRZ},
               "application_document_disagree": _ZONE_FINE, "document_expired": _ZONE_FINE}
CLEAR_TAMPER = ("viz_mrz_disagree", "check_digit_failed", "impossible_date")


def gold_classes(expected: dict, field: str, has_mrz: bool) -> set[str]:
    """The computed classes that agree with the gold reason code of one field."""
    ok = set(_GOLD_CLASS[expected[f"{field}_reason"]])
    if field == "date_of_birth" and not has_mrz and P.CONSISTENT in ok:
        ok.add(P.NO_MRZ)    # §2.2 step 5: the application is a DOB's second source
    return ok


def gold_overall(expected: dict) -> set[str]:
    rs = [expected[f"{f}_reason"] for f in INTEG_MAP.values()]
    if any(r in CLEAR_TAMPER for r in rs):
        return {"clear tamper"}
    if "ocr_or_tamper_ambiguous" in rs:
        return {"ambiguous"}
    if "ocr_confusable_resolved" in rs:
        return {"noise only"}
    if any(r in ("application_document_disagree", "document_expired") for r in rs):
        return {"noise only", "consistent"}
    return {"consistent"}


def _d(s):
    return date.fromisoformat(s) if s else None


def window(days: int) -> str:
    if days < 0:
        return "DATED AFTER AS-OF"
    return "WITHIN 90 DAYS" if days <= POA_WINDOW_DAYS else "OLDER THAN 90 DAYS"


def truth_expiry(t: dict, as_of: date) -> date | None:
    idd = t["id_doc"]
    if idd.get("mrz_lines"):
        fmt, lines = idd["mrz_format"], idd["mrz_lines"]
        for ls in (lines, O.repair_mrz(lines, fmt)):
            p = M.parse_td3(ls, as_of) if fmt == "TD3" else M.parse_td1(ls, as_of)
            if p.checks.get("expiry_date") and p.fields:
                return p.fields.expiry_date
        return None
    return _d((idd.get("viz") or {}).get("expiry_date"))


def score_split(split_dir: Path, show_errors: int = 0, style: str | None = None) -> dict:
    if split_dir.name.lower().startswith("eval"):
        raise SystemExit(f"refusing to read eval split {split_dir}")
    truths = {}
    with open(split_dir / "truth.jsonl", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            truths[r["case_id"]] = r["truth"]
    stats = {k: defaultdict(int) for k in FIELDS + INTEG_FIELDS}
    confusions = defaultdict(int)       # (field, gold, computed) for every wrong call
    stats["expired_label_missed"] = defaultdict(int)
    stats["poa_nd"] = defaultdict(int)
    errors = defaultdict(list)

    def tally(field, truth_val, pred_val, cid):
        s = stats[field]
        if truth_val is None:  # nothing to score against
            return
        s["n"] += 1
        if pred_val is None:
            return
        s["covered"] += 1
        if pred_val == truth_val:
            s["correct"] += 1
        elif len(errors[field]) < show_errors:
            errors[field].append((cid, truth_val, pred_val))

    def tally_set(field, ok_vals, pred_val, cid, gold_label):
        s = stats[field]
        s["n"] += 1
        if pred_val is None:
            return
        s["covered"] += 1
        if pred_val in ok_vals:
            s["correct"] += 1
            return
        confusions[(field, gold_label, pred_val)] += 1
        if len(errors[field]) < show_errors:
            errors[field].append((cid, gold_label, pred_val))

    with open(split_dir / "cases.jsonl", encoding="utf-8") as f:
        for line in f:
            case = json.loads(line)
            if style is not None and case.get("style") != style:
                continue
            cid = case["case_id"]
            t = truths[cid]
            res = run_prechecks(case["packet"])
            as_of = _d(t["context"]["as_of_date"])
            tally("as_of", as_of, res["as_of"], cid)

            tm = t["id_doc"].get("mrz_check") or "none"
            pm = res["mrz"]["status"] if res["mrz"] else None
            if tm == "none":
                # no MRZ: the pre-checker must not invent one
                stats["mrz"]["no_mrz_cases"] += 1
                if pm is not None:
                    stats["mrz"]["invented"] += 1
            else:
                tally("mrz", tm, pm, cid)

            te = truth_expiry(t, as_of)
            tally("expiry", te, res["expiry"], cid)
            tally("expired", (te < as_of) if te else None, res["expired"], cid)
            exp_reason = (case.get("expected") or {}).get("expiry_reason")
            if exp_reason == "document_expired":
                stats["expired_label_missed"]["n"] += 1
                if res["expired"] is False:
                    stats["expired_label_missed"]["missed"] += 1

            poa = t.get("poa") or {}
            tp = _d(poa.get("issue_date")) if poa.get("present") else None
            tally("poa_date", tp, res["poa_date"], cid)
            tally("poa_window", window((as_of - tp).days) if tp else None, res["poa_window"], cid)
            exp_d = case["expected"]
            integ = res.get("integrity") or {}
            has_mrz = bool(t["id_doc"].get("mrz_lines"))
            for fk, ek in INTEG_MAP.items():
                f = (integ.get("fields") or {}).get(fk)
                tally_set(f"integ_{ek}", gold_classes(exp_d, ek, has_mrz), f["class"] if f else None,
                          cid, exp_d[f"{ek}_reason"])
            go = gold_overall(exp_d)
            tally_set("integ_overall", go, integ.get("overall"), cid, "/".join(sorted(go)))
            if tp and res["poa_date"] is None:
                why = "illegible_scan" if not poa.get("legible", True) else (
                    "ambiguous_dmy" if any("ambiguous" in n for n in res["notes"]) else "other")
                stats["poa_nd"][why] += 1
    return {"stats": stats, "errors": errors, "confusions": dict(confusions)}


def fmt_table(rows: list[tuple[str, dict]], fields=FIELDS) -> str:
    out = ["| split | field | n | coverage | accuracy (when determinable) | errors |",
           "|---|---|---:|---:|---:|---:|"]
    for split, stats in rows:
        for k in fields:
            s = stats[k]
            n, cov, ok = s["n"], s["covered"], s["correct"]
            out.append(f"| {split} | {k} | {n} | {cov / n:.1%} | "
                       f"{(ok / cov if cov else float('nan')):.2%} | {cov - ok} |")
    return "\n".join(out)


TWINS_DEV_PREDS = ROOT / "step5_training/results/dev_evals/distill-4b-twins__dev/predictions.jsonl"


def decision_errors(preds: Path, data: Path) -> list[dict]:
    """Dev cases a model decided wrongly, with the v2 integrity line next to the
    gold decision, and whether the block now states the deciding fact (§7: P2
    clear tamper -> reject, P4 ambiguous -> escalate)."""
    cases = {}
    with open(data / "dev" / "cases.jsonl", encoding="utf-8") as f:
        for line in f:
            c = json.loads(line)
            cases[c["case_id"]] = c
    out = []
    with open(preds, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            c = cases[r["case_id"]]
            try:
                pred = json.loads(r["output"]).get("decision")
            except Exception:
                pred = "unparseable"
            gold = c["expected"]["decision"]
            if pred == gold:
                continue
            go = gold_overall(c["expected"])
            ov = (run_prechecks(c["packet"]).get("integrity") or {}).get("overall")
            deciding = (gold == "reject" and go == {"clear tamper"}) or (gold == "escalate" and go == {"ambiguous"})
            out.append({"case_id": r["case_id"], "pred": pred, "gold": gold, "integrity": ov or "n/d",
                        "integrity_is_deciding": deciding, "resolved": deciding and ov in go})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data", default=str(ROOT / "data"))
    ap.add_argument("--splits", nargs="+", default=["train", "dev"])
    ap.add_argument("--show-errors", type=int, default=0)
    ap.add_argument("--by-style", action="store_true", help="score each generator style of a split separately")
    ap.add_argument("--json", help="also write the raw stats here")
    ap.add_argument("--md", help="also write the tables (markdown) here")
    ap.add_argument("--decision-errors", default=str(TWINS_DEV_PREDS),
                    help="dev predictions.jsonl whose wrong decisions get the integrity line ('' to skip)")
    a = ap.parse_args(argv)
    rows, raw, conf = [], {}, {}
    units = []
    for sp in a.splits:
        if a.by_style:
            with open(Path(a.data) / sp / "cases.jsonl", encoding="utf-8") as f:
                styles = sorted({json.loads(line).get("style") for line in f if line.strip()})
            units += [(f"{sp}:{st}", sp, st) for st in styles]
        else:
            units.append((sp, sp, None))
    for name, sp, st in units:
        r = score_split(Path(a.data) / sp, a.show_errors, st)
        sp = name
        rows.append((sp, r["stats"]))
        raw[sp] = {k: dict(v) for k, v in r["stats"].items()}
        conf[sp] = r["confusions"]
        raw[sp]["integ_confusions"] = [{"field": k[0], "gold": k[1], "computed": k[2], "n": v}
                                       for k, v in sorted(r["confusions"].items())]
        for field, errs in r["errors"].items():
            for cid, tv, pv in errs:
                print(f"[{sp}] {field} {cid}: truth={tv} pred={pv}")
    print(fmt_table(rows))
    integ_table = fmt_table(rows, INTEG_FIELDS)
    print(integ_table)
    for sp in conf:
        for (field, gold, pred), n in sorted(conf[sp].items()):
            print(f"[{sp}] CONFUSION {field}: gold {gold} -> computed {pred}: {n}")
    errs = decision_errors(Path(a.decision_errors), Path(a.data)) if a.decision_errors else []
    err_md = []
    if errs:
        err_md = ["| case | predicted | gold | v2 integrity line | integrity decides it | block states it |",
                  "|---|---|---|---|---|---|"]
        err_md += [f"| {e['case_id']} | {e['pred']} | {e['gold']} | {e['integrity']} | "
                   f"{'yes' if e['integrity_is_deciding'] else 'no'} | {'yes' if e['resolved'] else 'no'} |"
                   for e in errs]
        nres = sum(e["resolved"] for e in errs)
        err_md += ["", f"{nres} of {len(errs)} wrong decisions now have the deciding fact stated in the block "
                       f"({sum(e['integrity_is_deciding'] for e in errs)} of {len(errs)} are decided by §3)."]
        print("\n".join(err_md))
        raw["decision_errors"] = {"predictions": Path(a.decision_errors).relative_to(ROOT).as_posix()
                                  if Path(a.decision_errors).resolve().is_relative_to(ROOT) else a.decision_errors,
                                  "cases": errs, "resolved": nres}
    if a.md:
        wrong = [f"{sp} {k[0]}: gold {k[1]} -> {k[2]} x{v}" for sp in conf for k, v in sorted(conf[sp].items())]
        md = ["# Pre-checker v2: document integrity (policy_v1 §3) vs gold, train + dev", "",
              "`python -m step7_serving.precheck_eval --md step7_serving/results/precheck_v2_eval_train_dev.md "
              "--json step7_serving/results/precheck_v2_eval_train_dev.json`", "",
              "Computed integrity class vs the gold identity reason code; coverage = share not n/d.", "",
              integ_table, "", "Confusions (wrong when determinable): " + ("; ".join(wrong) or "none") + ".", "",
              "v1 fields (same run):", "", fmt_table(rows), ""]
        if err_md:
            md += [f"## Wrong dev decisions of `{raw['decision_errors']['predictions']}`", ""] + err_md + [""]
        Path(a.md).write_text("\n".join(md), encoding="utf-8")
    for sp, stats in rows:
        m, x = stats["mrz"], stats["expired_label_missed"]
        print(f"[{sp}] no-MRZ docs: {m['no_mrz_cases']}, MRZ invented: {m['invented']}; "
              f"expected=document_expired: {x['n']}, said NOT EXPIRED: {x['missed']}; "
              f"PoA n/d reasons: {dict(stats['poa_nd'])}")
    if a.json:
        Path(a.json).write_text(json.dumps(raw, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
