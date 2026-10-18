"""Table 2 S5 (if counterfactual twins is the invented technique): pair-level rejection filter.

    python -m step4_distillation.twins_filter --gold data/twins/cases.jsonl --fieldmap step6_evaluation/fieldmap_v1.yaml \
        --teacher-outputs outputs/batches/twins_argon/results.jsonl=argon \
        --system-file step0_rules/prompts/out/student_system.txt --out data/sft/twins.jsonl \
        [--pairs-out data/dpo/twin_pairs.jsonl]

Gold records of a twin pair share a pair id (``--pair-key``; also tried: pair_id, twin_pair_id,
twin_of) as written by step1_data_generation/twins.py (Session J). A pair is kept only if, for **both** twins, some
teacher sample passes every rejection-sampling check (so the teacher's decision flips the way the
labels flip). This is stricter than per-case filtering: it drops teachers that are right on one
twin for the wrong reason. Both twins' best passing outputs become SFT records.

``--pairs-out`` writes twin hard negatives for DPO: for twin A, chosen = A's passing output,
rejected = B's passing output (right for B's packet, wrong for A's).

Stats include the teacher's flip consistency: the share of pairs where its first-sample decisions
on the two twins differ exactly as the gold decisions do.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict

from step4_distillation.common import (Checker, StudentPrompt, Tally, add_check_args, add_common_args,
                            add_prompt_args, check_cfg_from_args, dpo_record, dump_json, get_path,
                            load_fieldmap, load_gold, load_samples, refuse_eval_ids, setup_logging,
                            sft_record, write_training_file)
from step4_distillation.reject_sample import check_all, rank_key

PAIR_KEYS = ("pair_id", "twin_pair_id", "twin_of")


def pair_id(rec: dict, key: str | None):
    for k in ((key,) if key else ()) + PAIR_KEYS:
        v = rec.get(k) if k else None
        if v is None and isinstance(rec.get("truth"), dict):
            v = rec["truth"].get(k)
        if v is not None:
            return str(v) if k != "twin_of" else "|".join(sorted([str(v), str(rec.get("case_id"))]))
    return None


def build(gold: dict, samples, prompt: StudentPrompt, checker: Checker, fm, *, pair_key: str | None = None,
          priority: list[str] | None = None, tally: Tally | None = None):
    tally = tally or Tally("twins_filter")
    priority = priority or []
    pairs = defaultdict(list)
    for cid, g in gold.items():
        pid = pair_id(g, pair_key)
        if pid is None:
            tally.drop("no_pair_id")
        else:
            pairs[pid].append(cid)
    checked = check_all(gold, samples, checker, tally)
    sft, dpo = [], []
    first_dec: dict[str, object] = {}
    n_scored = n_consistent = n_gold_flips = 0
    for pid, cids in sorted(pairs.items()):
        if len(cids) != 2:
            tally.drop("pair_not_size_2", len(cids))
            continue
        best = {}
        for cid in cids:
            cands = checked.get(cid, [])
            if cands:
                first = sorted(cands, key=lambda sr: sr[0].sample)[0][1]
                first_dec[cid] = fm.lab(get_path(first.obj, fm.decision_path)) if first.obj is not None else None
            ok = sorted([sr for sr in cands if sr[1].passed], key=lambda sr: rank_key(sr[0], sr[1], priority))
            if ok:
                best[cid] = ok[0]
        a, b = cids
        gd = {c: fm.lab(get_path(gold[c].get(fm.gold_expected_key, {}), fm.decision_path)) for c in cids}
        n_gold_flips += gd[a] != gd[b]
        if first_dec.get(a) is not None and first_dec.get(b) is not None:
            n_scored += 1
            n_consistent += first_dec[a] == gd[a] and first_dec[b] == gd[b]
        if len(best) < 2:
            tally.drop({0: "both_twins_fail", 1: "one_twin_fails"}[len(best)])
            continue
        for cid in cids:
            s, r = best[cid]
            sft.append(sft_record("twins", cid, prompt, gold[cid][fm.gold_packet_key], r.obj,
                                  teacher=s.teacher, sample=s.sample, pair_id=pid))
        for x, y in ((a, b), (b, a)):
            cx, cy = dump_json(best[x][1].obj), dump_json(best[y][1].obj)
            if cx != cy:
                dpo.append(dpo_record("twin_pair", x, prompt, gold[x][fm.gold_packet_key], cx, cy,
                                      pair_id=pid, rejected_is_twin=y))
        tally.keep()
    tally.extra.update({"pairs": len(pairs), "pairs_kept": tally.kept, "sft_records": len(sft),
                        "dpo_pairs": len(dpo), "gold_decision_flips": n_gold_flips,
                        "teacher_flip_consistency": round(n_consistent / n_scored, 4) if n_scored else None})
    return sft, dpo, tally


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_common_args(ap)
    add_prompt_args(ap)
    add_check_args(ap)
    ap.add_argument("--teacher-outputs", action="append", required=True, metavar="PATH[=NAME]")
    ap.add_argument("--pair-key", help=f"gold key holding the twin pair id (default: first of {PAIR_KEYS})")
    ap.add_argument("--teacher-priority", default="")
    ap.add_argument("--out", required=True)
    ap.add_argument("--pairs-out")
    a = ap.parse_args(argv)
    setup_logging(a.verbose)
    fm = load_fieldmap(a.fieldmap, a.schema)
    gold = load_gold(a.gold, fm)
    refuse_eval_ids(gold, what=a.gold)
    sft, dpo, tally = build(gold, load_samples(a.teacher_outputs),
                            StudentPrompt.from_files(a.system_file, a.user_template_file),
                            Checker(fm, check_cfg_from_args(a)), fm, pair_key=a.pair_key,
                            priority=[t for t in a.teacher_priority.split(",") if t])
    write_training_file(a.out, sft, a.eval_manifest, tally)
    if a.pairs_out:
        write_training_file(a.pairs_out, dpo, a.eval_manifest)
    tally.save(a.out)
    print(json.dumps({"pairs_kept": tally.kept, "dropped": dict(tally.dropped)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
