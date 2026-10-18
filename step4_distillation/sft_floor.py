"""Table 2 floor (S2): teacher outputs -> SFT records, no filtering.

    python -m step4_distillation.sft_floor --gold data/train/cases.jsonl \
        --teacher-outputs outputs/batches/teacher_argon/results.jsonl=argon \
        --system-file step0_rules/prompts/out/student_system.txt --out data/sft/floor.jsonl

prompt = student prompt + packet, completion = the teacher's JSON (re-serialized compactly
when it parses; the raw text otherwise). By default nothing is filtered except rows that
cannot become a training example at all (API error, empty text, case not in gold). Each
of those is counted per reason in ``<out>.stats.json``. ``--require-parse`` /
``--require-schema`` exist for a "floor + validity" variant; they are off for the floor.

``--from-gold`` builds the gold-label SFT control instead (distillation_options §1, Q-DS1):
the target is the gold ``expected`` object (generator labels + template narrative), no teacher.

``--samples first`` (default) keeps one sample per (case, teacher), matching
experiment_plan S2 ("one sample per case, unfiltered"); ``all`` keeps every sample.
"""
from __future__ import annotations

import argparse
from collections import Counter

from step6_evaluation.metrics import parse_output

from step4_distillation.common import (Checker, Sample, StudentPrompt, Tally, add_common_args, add_prompt_args,
                            load_fieldmap, load_gold, load_samples, refuse_eval_ids, setup_logging,
                            sft_record, write_training_file)


def build(gold: dict, samples, prompt: StudentPrompt, checker: Checker, fm, *, samples_mode="first",
          teachers=None, require_parse=False, require_schema=False, tally: Tally | None = None):
    tally = tally or Tally("sft_floor")
    rows, per_teacher, invalid_kept = [], Counter(), Counter()
    seen = set()
    for s in samples:
        if teachers and s.teacher not in teachers:
            tally.drop("teacher_not_selected")
            continue
        if s.case_id not in gold:
            tally.drop("case_not_in_gold")
            continue
        if samples_mode == "first" and (s.case_id, s.teacher) in seen:
            tally.drop("extra_sample")
            continue
        if s.error or s.raw is None or (isinstance(s.raw, str) and not s.raw.strip()):
            tally.drop("api_error_or_empty")
            continue
        obj, _ = checker.parse(s.raw)
        target = obj
        if obj is None:
            parsed_only, _ = parse_output(s.raw, fm.strip_code_fences)
            if parsed_only is None:
                if require_parse or require_schema:
                    tally.drop("unparseable")
                    continue
                invalid_kept["unparseable"] += 1
                target = s.raw
            else:
                if require_schema:
                    tally.drop("schema_invalid")
                    continue
                invalid_kept["schema_invalid"] += 1
                target = parsed_only
        seen.add((s.case_id, s.teacher))
        g = gold[s.case_id]
        rows.append(sft_record("sft_floor", s.case_id, prompt, g[fm.gold_packet_key], target,
                               teacher=s.teacher, sample=s.sample))
        per_teacher[s.teacher] += 1
        tally.keep()
    tally.extra.update({"per_teacher": dict(per_teacher), "invalid_kept": dict(invalid_kept),
                        "gold_cases": len(gold),
                        "gold_cases_covered": len({r["case_id"] for r in rows})})
    return rows, tally


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_common_args(ap)
    add_prompt_args(ap)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--teacher-outputs", action="append", metavar="PATH[=NAME]")
    src.add_argument("--from-gold", action="store_true", help="gold-label SFT control (no teacher)")
    ap.add_argument("--teachers", help="comma-separated teacher names to keep (default all)")
    ap.add_argument("--samples", choices=["first", "all"], default="first")
    ap.add_argument("--require-parse", action="store_true")
    ap.add_argument("--require-schema", action="store_true")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    setup_logging(a.verbose)
    fm = load_fieldmap(a.fieldmap, a.schema)
    gold = load_gold(a.gold, fm)
    refuse_eval_ids(gold, what=a.gold)
    samples = ([Sample(cid, "gold", 0, g.get(fm.gold_expected_key)) for cid, g in gold.items()]
               if a.from_gold else load_samples(a.teacher_outputs))
    rows, tally = build(gold, samples, StudentPrompt.from_files(a.system_file, a.user_template_file),
                        Checker(fm), fm, samples_mode=a.samples,
                        teachers=set(a.teachers.split(",")) if a.teachers else None,
                        require_parse=a.require_parse, require_schema=a.require_schema)
    write_training_file(a.out, rows, a.eval_manifest, tally)
    tally.save(a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
