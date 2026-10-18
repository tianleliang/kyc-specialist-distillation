"""Table 2 S3: rejection sampling against programmatic checks.

    python -m step4_distillation.reject_sample --gold data/train/cases.jsonl --fieldmap step6_evaluation/fieldmap_v1.yaml \
        --teacher-outputs outputs/batches/teacher_argon/results.jsonl=argon \
        --teacher-outputs outputs/batches/teacher_sol/results.jsonl=sol \
        --system-file step0_rules/prompts/out/student_system.txt --out data/sft/reject.jsonl \
        [--rejects-out data/sft/reject.failures.jsonl]

A teacher output is kept only if it
  * parses and validates against the schema (FieldMap ``schema_path`` / ``--schema``),
  * matches gold on the decision, the risk tier and every screening disposition,
  * has identity-field findings matching gold on >= ``--min-field-acc`` of the fields,
  * passes the ``evidence_refs`` check (every narrative sentence cites refs that resolve to
    packet section ids or verbatim packet text), and
  * optionally (``--actions superset|exact``) lists the required actions.

k samples per case (from one or several teachers): every sample is checked, and with
``--keep best`` (default) the best passing one is kept: highest closeness-to-gold score,
then ``--teacher-priority`` order, then the shortest target. ``--keep all`` keeps every
passing sample. Cases with no passing sample drop out; the stats file gives drop counts per
failure reason, per teacher, and the per-tag case drop rate (where teachers fail).
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict

from step4_distillation.common import (Checker, CheckResult, StudentPrompt, Tally, add_check_args,
                            add_common_args, add_prompt_args, check_cfg_from_args, dump_json,
                            gold_tags, group_by_case, load_fieldmap, load_gold, load_samples,
                            refuse_eval_ids, setup_logging, sft_record, write_jsonl,
                            write_training_file)


def rank_key(s, res: CheckResult, priority: list[str]):
    pri = priority.index(s.teacher) if s.teacher in priority else len(priority)
    return (-res.score, pri, len(dump_json(res.obj)) if res.obj is not None else 1 << 30, s.sample)


def check_all(gold: dict, samples, checker: Checker, tally: Tally):
    """-> {case_id: [(sample, CheckResult)]}, counting per-sample failure reasons."""
    out: dict[str, list] = defaultdict(list)
    for cid, ss in group_by_case(samples).items():
        if cid not in gold:
            tally.drop("case_not_in_gold", len(ss))
            continue
        for s in ss:
            if s.error or s.raw is None:
                res = CheckResult(False, ["api_error"], [s.error or "no output"], 0.0, None)
            else:
                res = checker.check(s.raw, gold[cid])
            out[cid].append((s, res))
    return out


def build(gold: dict, samples, prompt: StudentPrompt, checker: Checker, fm, *, keep="best",
          priority: list[str] | None = None, tally: Tally | None = None):
    tally = tally or Tally("reject_sample")
    priority = priority or []
    checked = check_all(gold, samples, checker, tally)
    rows, rejects = [], []
    sample_fail = Counter()                 # per-sample failure reasons (a sample may have several)
    teacher_n, teacher_pass = Counter(), Counter()
    tag_n, tag_drop = Counter(), Counter()
    k_hist = Counter()
    for cid in gold:
        cands = checked.get(cid, [])
        if not cands:                       # not sent to a teacher (e.g. a later tranche)
            continue
        tags = gold_tags(gold[cid], fm)
        for t in tags:
            tag_n[t] += 1
        k_hist[len(cands)] += 1
        passing = []
        for s, res in cands:
            teacher_n[s.teacher] += 1
            if res.passed:
                teacher_pass[s.teacher] += 1
                passing.append((s, res))
            else:
                sample_fail.update(res.reasons)
                rejects.append({"case_id": cid, "teacher": s.teacher, "sample": s.sample,
                                "reasons": res.reasons, "details": res.details, "score": res.score,
                                "output": s.raw})
        if not passing:
            tally.drop("no_passing_sample")
            for t in tags:
                tag_drop[t] += 1
            continue
        passing.sort(key=lambda sr: rank_key(sr[0], sr[1], priority))
        for s, res in (passing[:1] if keep == "best" else passing):
            rows.append(sft_record("reject_sample", cid, prompt, gold[cid][fm.gold_packet_key], res.obj,
                                   teacher=s.teacher, sample=s.sample, check_score=res.score))
            tally.keep()
    tally.extra.update({
        "gold_cases": len(gold),
        "cases_with_samples": len(checked),
        "cases_kept": len({r["case_id"] for r in rows}),
        "samples_checked": sum(teacher_n.values()),
        "sample_failure_reasons": dict(sample_fail.most_common()),
        "teacher_pass_rate": {t: round(teacher_pass[t] / n, 4) for t, n in sorted(teacher_n.items())},
        "samples_per_case_hist": {str(k): v for k, v in sorted(k_hist.items())},
        "case_drop_rate_by_tag": {t: {"n": tag_n[t], "dropped": tag_drop[t],
                                      "rate": round(tag_drop[t] / tag_n[t], 4)}
                                  for t in sorted(tag_n, key=lambda t: (-tag_drop[t] / tag_n[t], t))},
        "kept_per_teacher": dict(Counter(r["teacher"] for r in rows)),
    })
    return rows, rejects, tally


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_common_args(ap)
    add_prompt_args(ap)
    add_check_args(ap)
    ap.add_argument("--teacher-outputs", action="append", required=True, metavar="PATH[=NAME]")
    ap.add_argument("--keep", choices=["best", "all"], default="best")
    ap.add_argument("--teacher-priority", default="", help="comma-separated tie-break order")
    ap.add_argument("--out", required=True)
    ap.add_argument("--rejects-out", help="write failing samples with reasons (label audit, DPO, on-policy)")
    a = ap.parse_args(argv)
    setup_logging(a.verbose)
    fm = load_fieldmap(a.fieldmap, a.schema)
    gold = load_gold(a.gold, fm)
    refuse_eval_ids(gold, what=a.gold)
    rows, rejects, tally = build(gold, load_samples(a.teacher_outputs),
                                 StudentPrompt.from_files(a.system_file, a.user_template_file),
                                 Checker(fm, check_cfg_from_args(a)), fm, keep=a.keep,
                                 priority=[t for t in a.teacher_priority.split(",") if t])
    tally.extra["check_cfg"] = vars(check_cfg_from_args(a))
    write_training_file(a.out, rows, a.eval_manifest, tally)
    if a.rejects_out:
        write_jsonl(a.rejects_out, rejects)
    tally.save(a.out)
    print(json.dumps({"kept": tally.kept, "cases_kept": tally.extra["cases_kept"],
                      "gold_cases": len(gold)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
