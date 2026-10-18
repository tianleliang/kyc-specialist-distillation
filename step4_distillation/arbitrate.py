"""Table 2 S4: multi-teacher arbitration (2-3 teachers per case).

    python -m step4_distillation.arbitrate --mode gold_select|vote|splice --gold data/train/cases.jsonl \
        --fieldmap step6_evaluation/fieldmap_v1.yaml \
        --teacher-outputs outputs/batches/argon/results.jsonl=argon \
        --teacher-outputs outputs/batches/sol/results.jsonl=sol \
        --teacher-priority argon,sol --system-file step0_rules/prompts/out/student_system.txt \
        --out data/sft/arbitrate_splice.jsonl [--report outputs/distill/agreement.json]

Modes
  gold_select  the whole output of the teacher closest to gold wins (score from
               step4_distillation.common.Checker; ties -> --teacher-priority). ``--require-pass`` keeps a
               case only if the winner passes every rejection-sampling check.
  vote         no gold used for selection: field-wise majority over the schema-valid teachers
               (decision, risk tier, each hit's disposition, each identity field, actions).
               The teacher agreeing with the majority most often is the base; units where it
               is outvoted are copied from a majority teacher. Ties: --tie priority|drop.
  splice       field-wise best-of against gold: each unit comes from a teacher that got it
               right; the narrative comes from a teacher whose narrative is fully grounded
               and whose decision equals the spliced decision. A unit no teacher got right is
               dropped (--repair drop, default) or set to the gold label (--repair gold,
               experiment_plan R10). The spliced object is re-validated and re-checked.

A "unit" is the smallest object that owns a label: for ``identity.name.status`` it is
``identity.name`` (status + reason move together); a screening hit is the hit object. When the
parent is shared with other labels (``identity.verified`` -> ``identity``) only the leaf moves.

Every mode writes teacher agreement rates (pairwise and all-agree, per unit kind, plus each
teacher's agreement with gold) into the stats file, and lists label-audit cases: all teachers
agree with each other on the decision but not with gold (a generator/policy bug signal).
"""
from __future__ import annotations

import argparse
import copy
import itertools
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from step4_distillation.common import (MISSING, Checker, StudentPrompt, Tally, add_check_args, add_common_args,
                            add_prompt_args, check_cfg_from_args, get_path, group_by_case,
                            load_fieldmap, load_gold, load_samples, parent_path, refuse_eval_ids,
                            set_path, setup_logging, sft_record, write_training_file)

MODES = ("gold_select", "vote", "splice")


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------

@dataclass
class Unit:
    name: str                 # "decision", "risk_tier", "field:dob", "hit:H1", "actions"
    kind: str                 # decision | risk | field | hit | actions
    label_path: str | None    # path to the label leaf (None for hits/actions)
    unit_path: str | None     # path of the object moved when splicing (None = move the leaf only)


def static_units(fm) -> list[Unit]:
    units = [Unit("decision", "decision", fm.decision_path, None),
             Unit("risk_tier", "risk", fm.risk_path, None)]
    paths = list(fm.identity_fields.values())
    for name, p in fm.identity_fields.items():
        par = parent_path(p)
        leaf_only = par is None or _is_shared(par, p, paths)
        units.append(Unit(f"field:{name}", "field", p, None if leaf_only else par))
    return units


def _is_shared(par: str, p: str, paths: list[str]) -> bool:
    return any(q != p and (q.startswith(par + ".") or q.startswith(par + "[")) for q in paths)


def hit_list(obj: dict, fm) -> list[dict]:
    lst = get_path(obj, fm.screening_path)
    return [h for h in lst if isinstance(h, dict)] if isinstance(lst, list) else []


def hit_key(h: dict, i: int, fm) -> str:
    return str(i) if fm.screening_id_key is None else str(h.get(fm.screening_id_key))


def hits_by_id(obj: dict, fm) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for i, h in enumerate(hit_list(obj, fm)):
        out.setdefault(hit_key(h, i, fm), h)
    return out


def action_set(obj: dict, fm) -> frozenset:
    lst = get_path(obj, fm.actions_path)
    if not isinstance(lst, list):
        return frozenset()
    vals = [(it.get(fm.actions_item_key) if fm.actions_item_key and isinstance(it, dict) else it) for it in lst]
    return frozenset(v for v in (fm.lab(x) for x in vals) if isinstance(v, str))


def unit_value(obj: dict, u: Unit, fm):
    if u.kind == "actions":
        return action_set(obj, fm)
    if u.kind == "hit":
        h = hits_by_id(obj, fm).get(u.name[4:])
        return MISSING if h is None else fm.lab(h.get(fm.screening_label_key))
    return fm.lab(get_path(obj, u.label_path))


def case_units(objs: list[dict], fm, gold_exp: dict | None) -> list[Unit]:
    ids: list[str] = []
    for o in ([gold_exp] if gold_exp else []) + objs:
        for k in hits_by_id(o, fm):
            if k not in ids:
                ids.append(k)
    return static_units(fm) + [Unit(f"hit:{k}", "hit", None, None) for k in ids] + \
        [Unit("actions", "actions", fm.actions_path, None)]


def copy_unit(dst: dict, src: dict, u: Unit, fm) -> bool:
    """Copy unit ``u`` from ``src`` into ``dst`` in place."""
    if u.kind == "actions":
        v = get_path(src, fm.actions_path)
        return v is not MISSING and set_path(dst, fm.actions_path, copy.deepcopy(v))
    if u.kind == "hit":
        hid = u.name[4:]
        h = hits_by_id(src, fm).get(hid)
        lst = get_path(dst, fm.screening_path)
        if h is None or not isinstance(lst, list):
            return False
        for i, cur in enumerate(lst):
            if isinstance(cur, dict) and hit_key(cur, i, fm) == hid:
                lst[i] = copy.deepcopy(h)
                return True
        lst.append(copy.deepcopy(h))
        return True
    path = u.unit_path or u.label_path
    v = get_path(src, path)
    return v is not MISSING and set_path(dst, path, copy.deepcopy(v))


def set_label(dst: dict, u: Unit, value, raw_gold, fm) -> bool:
    """Set a unit's label to the gold value (repair). ``raw_gold`` is the un-normalized value."""
    if u.kind == "actions":
        return raw_gold is not MISSING and set_path(dst, fm.actions_path, copy.deepcopy(raw_gold))
    if u.kind == "hit":
        h = hits_by_id(dst, fm).get(u.name[4:])
        if h is None:
            return False
        h[fm.screening_label_key] = raw_gold
        return True
    return set_path(dst, u.label_path, copy.deepcopy(raw_gold))


def raw_gold_value(gexp: dict, u: Unit, fm):
    if u.kind == "actions":
        return get_path(gexp, fm.actions_path)
    if u.kind == "hit":
        h = hits_by_id(gexp, fm).get(u.name[4:])
        return MISSING if h is None else h.get(fm.screening_label_key, MISSING)
    return get_path(gexp, u.label_path)


def keep_only_hits(dst: dict, ids: list[str], fm) -> None:
    lst = get_path(dst, fm.screening_path)
    if isinstance(lst, list):
        lst[:] = [h for i, h in enumerate(lst) if not isinstance(h, dict) or hit_key(h, i, fm) in ids]


# ---------------------------------------------------------------------------
# Agreement report
# ---------------------------------------------------------------------------

class Agreement:
    def __init__(self):
        self.pair = defaultdict(lambda: [0, 0])      # (kind, t1, t2) -> [agree, total]
        self.all = defaultdict(lambda: [0, 0])       # kind -> [all agree, total]
        self.gold = defaultdict(lambda: [0, 0])      # (kind, t) -> [agree, total]
        self.audit: list[str] = []

    def add(self, objs: dict[str, dict], units: list[Unit], fm, gexp: dict | None, cid: str):
        ts = sorted(objs)
        for u in units:
            vals = {t: unit_value(objs[t], u, fm) for t in ts}
            if u.kind == "hit" and all(v is MISSING for v in vals.values()):
                continue
            for a, b in itertools.combinations(ts, 2):
                r = self.pair[(u.kind, a, b)]
                r[0] += vals[a] == vals[b]
                r[1] += 1
            if len(ts) >= 2:
                r = self.all[u.kind]
                r[0] += len(set(map(_hashable, vals.values()))) == 1
                r[1] += 1
            if gexp is not None:
                g = unit_value(gexp, u, fm)
                if g is MISSING or (u.kind == "actions" and not g and not get_path(gexp, fm.actions_path)):
                    continue
                for t in ts:
                    r = self.gold[(u.kind, t)]
                    r[0] += vals[t] == g
                    r[1] += 1
                if u.kind == "decision" and len(ts) >= 2 and len(set(vals.values())) == 1 and vals[ts[0]] != g:
                    self.audit.append(cid)

    def summary(self) -> dict:
        rate = lambda r: round(r[0] / r[1], 4) if r[1] else None  # noqa: E731
        return {
            "pairwise": {f"{k}:{a}~{b}": {"rate": rate(r), "n": r[1]} for (k, a, b), r in sorted(self.pair.items())},
            "all_agree": {k: {"rate": rate(r), "n": r[1]} for k, r in sorted(self.all.items())},
            "vs_gold": {f"{k}:{t}": {"rate": rate(r), "n": r[1]} for (k, t), r in sorted(self.gold.items())},
            "label_audit_case_ids": self.audit[:200],
            "label_audit_count": len(self.audit),
        }


def _hashable(v):
    return v if not isinstance(v, (list, dict, set)) else json.dumps(sorted(v) if isinstance(v, (set, frozenset)) else v, sort_keys=True)


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------

def _pri(t: str, priority: list[str]) -> int:
    return priority.index(t) if t in priority else len(priority)


def gold_select(cands, gold_rec, checker, priority, require_pass, tally):
    scored = [(t, checker.check(o, gold_rec)) for t, o in cands.items()]
    scored.sort(key=lambda tr: (-tr[1].score, _pri(tr[0], priority)))
    t, res = scored[0]
    if require_pass and not res.passed:
        tally.drop("no_teacher_passes")
        return None
    return res.obj, t, {"winner": t, "score": res.score}


def vote(cands, units, fm, priority, tie, narrative_conflict, tally):
    ts = sorted(cands, key=lambda t: _pri(t, priority))
    majority: dict[str, object] = {}
    for u in units:
        vals = {t: unit_value(cands[t], u, fm) for t in ts}
        if u.kind == "hit":
            present = [t for t in ts if vals[t] is not MISSING]
            if len(present) * 2 <= len(ts):          # hit not listed by a majority: remove it
                majority[u.name] = None
                continue
        c = Counter(_hashable(v) for v in vals.values())
        top = c.most_common()
        best_n = top[0][1]
        winners = [k for k, n in top if n == best_n]
        if best_n * 2 <= len(ts) and tie == "drop":      # no strict majority
            tally.drop(f"vote_tie:{u.kind}")
            return None
        # among tied values, the one the highest-priority teacher gave
        pick = next(t for t in ts if _hashable(vals[t]) in winners)
        majority[u.name] = (vals[pick], [t for t in ts if _hashable(vals[t]) == _hashable(vals[pick])])
    agree = {t: sum(1 for u in units if majority.get(u.name) and t in majority[u.name][1]) for t in ts}
    base_t = max(ts, key=lambda t: (agree[t], -_pri(t, priority)))
    out = copy.deepcopy(cands[base_t])
    prov = {}
    for u in units:
        m = majority.get(u.name)
        if m is None:
            continue
        if base_t not in m[1]:
            donor = m[1][0]
            if not copy_unit(out, cands[donor], u, fm):
                tally.drop("splice_failed")
                return None
            prov[u.name] = donor
    keep_ids = [u.name[4:] for u in units if u.kind == "hit" and majority.get(u.name) is not None]
    keep_only_hits(out, keep_ids, fm)
    if "decision" in prov and narrative_conflict == "drop":
        tally.drop("narrative_decision_conflict")
        return None
    return out, "vote", {"base": base_t, "outvoted_units": prov}


def splice(cands, units, fm, gold_rec, checker, priority, repair, tally):
    gexp = gold_rec.get(fm.gold_expected_key, {})
    scored = {t: checker.check(o, gold_rec) for t, o in cands.items()}
    order = sorted(cands, key=lambda t: (-scored[t].score, _pri(t, priority)))
    base_t = order[0]
    out = copy.deepcopy(cands[base_t])
    prov, repaired = {}, []
    gold_hit_ids = list(hits_by_id(gexp, fm))
    for u in units:
        g = unit_value(gexp, u, fm)
        if g is MISSING or (u.kind == "hit" and u.name[4:] not in gold_hit_ids):
            continue
        donors = [t for t in order if unit_value(cands[t], u, fm) == g]
        if donors:
            if donors[0] != base_t and not copy_unit(out, cands[donors[0]], u, fm):
                tally.drop("splice_failed")
                return None
            prov[u.name] = donors[0]
            continue
        if repair == "drop":
            tally.drop(f"no_teacher_right:{u.kind}")
            return None
        if u.kind == "hit" and u.name[4:] not in hits_by_id(out, fm):
            donor = next((t for t in order if u.name[4:] in hits_by_id(cands[t], fm)), None)
            if donor is None or not copy_unit(out, cands[donor], u, fm):
                tally.drop("repair_failed:hit_missing")
                return None
        if not set_label(out, u, g, raw_gold_value(gexp, u, fm), fm):
            tally.drop(f"repair_failed:{u.kind}")
            return None
        prov[u.name] = "gold"
        repaired.append(u.name)
    keep_only_hits(out, gold_hit_ids, fm)
    # narrative: fully grounded, from a teacher whose decision equals the spliced decision
    final_dec = fm.lab(get_path(out, fm.decision_path))
    narr = [t for t in order if scored[t].parts.get("grounding") == 1.0
            and fm.lab(get_path(cands[t], fm.decision_path)) == final_dec
            and get_path(cands[t], fm.narrative_path) is not MISSING]
    if not narr:
        tally.drop("no_grounded_consistent_narrative")
        return None
    set_path(out, fm.narrative_path, copy.deepcopy(get_path(cands[narr[0]], fm.narrative_path)))
    prov["narrative"] = narr[0]
    return out, "splice", {"base": base_t, "units": prov, "repaired": repaired}


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def build(gold: dict, samples, prompt: StudentPrompt, checker: Checker, fm, *, mode: str,
          priority: list[str] | None = None, require_pass: bool = False, tie: str = "priority",
          repair: str = "drop", narrative_conflict: str = "drop", min_teachers: int = 2,
          tally: Tally | None = None):
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    tally = tally or Tally(f"arbitrate_{mode}")
    priority = priority or []
    agreement = Agreement()
    rows, winners = [], Counter()
    for cid, ss in group_by_case(samples).items():
        if cid not in gold:
            tally.drop("case_not_in_gold")
            continue
        g = gold[cid]
        cands: dict[str, dict] = {}
        for s in sorted(ss, key=lambda s: s.sample):
            if s.teacher in cands or s.error or s.raw is None:
                continue
            obj, _ = checker.parse(s.raw)
            if obj is not None:
                cands[s.teacher] = obj
        gexp = g.get(fm.gold_expected_key)
        units = case_units(list(cands.values()), fm, gexp)
        agreement.add(cands, units, fm, gexp, cid)
        if len(cands) < (1 if mode == "gold_select" else min_teachers):
            tally.drop("too_few_valid_teachers")
            continue
        if mode == "gold_select":
            res = gold_select(cands, g, checker, priority, require_pass, tally)
        elif mode == "vote":
            res = vote(cands, case_units(list(cands.values()), fm, None), fm, priority, tie,
                       narrative_conflict, tally)
        else:
            res = splice(cands, units, fm, g, checker, priority, repair, tally)
        if res is None:
            continue
        obj, who, prov = res
        if checker.validator(obj):
            tally.drop("revalidation_failed")
            continue
        if mode == "splice":
            chk = checker.check(obj, g)
            if not chk.passed:
                tally.drop("splice_fails_checks:" + ",".join(chk.reasons))
                continue
        if mode == "vote" and gexp is not None:
            tally.extra.setdefault("vote_vs_gold_decision", [0, 0])
            v = tally.extra["vote_vs_gold_decision"]
            v[0] += fm.lab(get_path(obj, fm.decision_path)) == fm.lab(get_path(gexp, fm.decision_path))
            v[1] += 1
        winners[who if mode != "gold_select" else prov["winner"]] += 1
        rows.append(sft_record(f"arbitrate_{mode}", cid, prompt, g[fm.gold_packet_key], obj,
                               teacher=who, provenance=prov))
        tally.keep()
    tally.extra.update({"mode": mode, "winners": dict(winners), "agreement": agreement.summary()})
    return rows, tally


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_common_args(ap)
    add_prompt_args(ap)
    add_check_args(ap)
    ap.add_argument("--mode", choices=MODES, required=True)
    ap.add_argument("--teacher-outputs", action="append", required=True, metavar="PATH[=NAME]")
    ap.add_argument("--teacher-priority", default="")
    ap.add_argument("--require-pass", action="store_true", help="gold_select: winner must pass all checks")
    ap.add_argument("--tie", choices=["priority", "drop"], default="priority", help="vote: no majority")
    ap.add_argument("--repair", choices=["drop", "gold"], default="drop", help="splice: unit no teacher got right")
    ap.add_argument("--narrative-conflict", choices=["drop", "keep"], default="drop",
                    help="vote: base narrative's teacher was outvoted on the decision")
    ap.add_argument("--min-teachers", type=int, default=2)
    ap.add_argument("--report", help="also write the agreement report here")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    setup_logging(a.verbose)
    fm = load_fieldmap(a.fieldmap, a.schema)
    gold = load_gold(a.gold, fm)
    refuse_eval_ids(gold, what=a.gold)
    rows, tally = build(gold, load_samples(a.teacher_outputs),
                        StudentPrompt.from_files(a.system_file, a.user_template_file),
                        Checker(fm, check_cfg_from_args(a)), fm, mode=a.mode,
                        priority=[t for t in a.teacher_priority.split(",") if t],
                        require_pass=a.require_pass, tie=a.tie, repair=a.repair,
                        narrative_conflict=a.narrative_conflict, min_teachers=a.min_teachers)
    write_training_file(a.out, rows, a.eval_manifest, tally)
    tally.save(a.out)
    if a.report:
        Path(a.report).parent.mkdir(parents=True, exist_ok=True)
        Path(a.report).write_text(json.dumps(tally.extra["agreement"], indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"kept": tally.kept, "dropped": dict(tally.dropped)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
