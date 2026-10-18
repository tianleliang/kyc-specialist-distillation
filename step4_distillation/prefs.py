"""Table 2 S7 (DPO data): preference pairs for step5_training/dpo.py.

Programmatic pairs (the default; "the schema and labels give a free verifier"):

    python -m step4_distillation.prefs programmatic --gold data/train/cases.jsonl --fieldmap step6_evaluation/fieldmap_v1.yaml \
        --chosen data/sft/reject.jsonl --chosen data/sft/onpolicy_corrected.jsonl \
        --rejected outputs/train/student_v1/predictions.jsonl=student \
        --system-file step0_rules/prompts/out/student_system.txt --out data/dpo/pairs.jsonl

  chosen   = the best gold-passing candidate for the case (teacher outputs, or the SFT files
             written by reject_sample / arbitrate / onpolicy, i.e. corrected outputs)
  rejected = a student output for the same case that fails the checks. ``--rejected-pick
             hardest`` (default) takes the failing sample closest to gold (a near-miss, the most
             informative negative); ``worst`` the furthest; ``all`` one pair per failing sample
             up to ``--max-pairs-per-case``.
  Cases where the student passes produce no pair (counted as ``student_passes``).

Teacher-as-judge pairs (stub, for the narrative; structured fields are judged by code):

    python -m step4_distillation.prefs judge --gold ... --candidates outputs/train/student_samples.jsonl=student \
        --judge-provider anthropic --judge-model claude-opus-5-5 --out data/dpo/judge_pairs.jsonl [--mock]

  For each case, two candidates that both pass the structured checks are shown to the judge
  blind (labelled A/B, order randomized per case with a fixed seed) and then again with the
  order swapped. A pair is kept only if both verdicts pick the same candidate (position-bias
  control). The judge prompt is ``--judge-prompt-file`` (placeholders ``{policy}``, ``{packet}``,
  ``{output_a}``, ``{output_b}``) or a short built-in default; Session I's step0_rules/prompts/ can supply it.
  Calls go through shared.frontier_api.clients.LLMClient (cache, cost ledger, retries); ``--mock`` or LLM_MOCK=1
  needs no key.
"""
from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from pathlib import Path

from step4_distillation.common import (Checker, StudentPrompt, Tally, add_check_args, add_common_args,
                            add_prompt_args, check_cfg_from_args, dump_json, group_by_case,
                            load_fieldmap, load_gold, load_samples, refuse_eval_ids, setup_logging,
                            dpo_record, write_training_file)

DEFAULT_JUDGE_PROMPT = """You compare two KYC case write-ups for the same packet. Both have the same \
structured findings; judge only the narrative.
Prefer the narrative whose every sentence is supported by the packet and cites it correctly, \
that covers the facts the decision depends on, and that adds nothing the packet does not say. \
Length is not a virtue. Ignore which one was shown first.

{policy}

PACKET:
{packet}

OUTPUT A:
{output_a}

OUTPUT B:
{output_b}

Return JSON: {"winner": "A" | "B" | "tie", "reason": "<one sentence>"}"""

JUDGE_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["winner", "reason"],
                "properties": {"winner": {"enum": ["A", "B", "tie"]}, "reason": {"type": "string"}}}


# ---------------------------------------------------------------------------
# Programmatic pairs
# ---------------------------------------------------------------------------

def programmatic(gold: dict, chosen, rejected, prompt: StudentPrompt, checker: Checker, fm, *,
                 pick: str = "hardest", max_pairs: int = 1, rejected_require_valid: bool = False,
                 tally: Tally | None = None):
    tally = tally or Tally("prefs_programmatic")
    ch_by, rej_by = group_by_case(chosen), group_by_case(rejected)
    rows, fail_reasons, chosen_src = [], Counter(), Counter()
    for cid in sorted(set(rej_by) | set(ch_by)):
        if cid not in gold:
            tally.drop("case_not_in_gold")
            continue
        g = gold[cid]
        if cid not in rej_by:
            tally.drop("no_student_output")
            continue
        passing = []
        for s in ch_by.get(cid, []):
            if s.raw is None:
                continue
            r = checker.check(s.raw, g)
            if r.passed:
                passing.append((s, r))
        if not passing:
            tally.drop("no_passing_chosen")
            continue
        passing.sort(key=lambda sr: (-sr[1].score, sr[0].teacher, sr[0].sample))
        cs, cres = passing[0]
        chosen_text = dump_json(cres.obj)
        fails = []
        for s in rej_by[cid]:
            if s.raw is None:
                continue
            r = checker.check(s.raw, g)
            if r.passed:
                continue
            if rejected_require_valid and r.obj is None:
                continue
            text = dump_json(r.obj) if r.obj is not None else str(s.raw if not isinstance(s.raw, dict) else dump_json(s.raw))
            if text.strip() and text != chosen_text:
                fails.append((s, r, text))
        if not fails:
            tally.drop("student_passes" if any(checker.check(s.raw, g).passed for s in rej_by[cid] if s.raw is not None)
                       else "no_usable_rejected")
            continue
        fails.sort(key=lambda f: f[1].score, reverse=(pick != "worst"))
        take = fails[:max_pairs] if pick == "all" else fails[:1]
        for n, (s, r, text) in enumerate(take):
            fail_reasons.update(r.reasons)
            rows.append(dpo_record("prefs_programmatic", cid, prompt, g[fm.gold_packet_key], chosen_text, text,
                                   n=n, chosen_from=cs.teacher, rejected_from=s.teacher,
                                   rejected_reasons=r.reasons))
            chosen_src[cs.teacher] += 1
            tally.keep()
    tally.extra.update({"rejected_failure_reasons": dict(fail_reasons.most_common()),
                        "chosen_from": dict(chosen_src), "pick": pick})
    return rows, tally


# ---------------------------------------------------------------------------
# Teacher-as-judge pairs (stub)
# ---------------------------------------------------------------------------

def judge_prompt(template: str, policy: str, packet: str, a: str, b: str) -> str:
    # plain replace: the template contains literal JSON braces
    return (template.replace("{policy}", policy).replace("{packet}", packet)
            .replace("{output_a}", a).replace("{output_b}", b))


def _verdict(resp) -> str | None:
    obj = resp.parsed if isinstance(resp.parsed, dict) else None
    if obj is None:
        try:
            obj = json.loads(resp.text)
        except (TypeError, ValueError):
            return None
    w = obj.get("winner") if isinstance(obj, dict) else None
    return w if w in ("A", "B", "tie") else None


def judge(gold: dict, candidates, prompt: StudentPrompt, checker: Checker, fm, client, *,
          provider: str, model: str, template: str = DEFAULT_JUDGE_PROMPT, policy: str = "",
          seed: int = 0, max_tokens: int = 300, tally: Tally | None = None):
    from shared.frontier_api.clients import make_request

    tally = tally or Tally("prefs_judge")
    plan = []                                        # (cid, text_x, text_y, swap)
    for cid, ss in sorted(group_by_case(candidates).items()):
        if cid not in gold:
            tally.drop("case_not_in_gold")
            continue
        ok = []
        for s in ss:
            r = checker.check(s.raw, gold[cid]) if s.raw is not None else None
            if r is not None and r.passed:
                t = dump_json(r.obj)
                if t not in [x[1] for x in ok]:
                    ok.append((s, t))
        if len(ok) < 2:
            tally.drop("fewer_than_2_passing_candidates")
            continue
        rng = random.Random(f"judge:{seed}:{cid}")
        x, y = rng.sample(ok, 2)
        plan.append((cid, x, y))
    reqs = []
    for cid, x, y in plan:
        packet = gold[cid][fm.gold_packet_key]
        for a, b, order in ((x, y, "xy"), (y, x, "yx")):
            reqs.append(make_request(provider, model, judge_prompt(template, policy, packet, a[1], b[1]),
                                     json_schema=JUDGE_SCHEMA, schema_name="pairwise_verdict",
                                     max_tokens=max_tokens, reasoning_effort="low", purpose="judge",
                                     metadata={"case_id": cid, "order": order}))
    resps = client.complete_many(reqs) if reqs else []
    rows, verdicts = [], Counter()
    for i, (cid, x, y) in enumerate(plan):
        v1, v2 = _verdict(resps[2 * i]), _verdict(resps[2 * i + 1])
        # v1 judged (A=x, B=y); v2 judged (A=y, B=x)
        w1 = {"A": "x", "B": "y"}.get(v1)
        w2 = {"A": "y", "B": "x"}.get(v2)
        if v1 is None or v2 is None:
            tally.drop("judge_unparseable")
            continue
        if w1 is None or w2 is None:
            tally.drop("judge_tie")
            continue
        if w1 != w2:
            tally.drop("position_inconsistent")
            continue
        win, lose = (x, y) if w1 == "x" else (y, x)
        verdicts[win[0].teacher] += 1
        rows.append(dpo_record("prefs_judge", cid, prompt, gold[cid][fm.gold_packet_key], win[1], lose[1],
                               chosen_from=win[0].teacher, rejected_from=lose[0].teacher, judge=model))
        tally.keep()
    tally.extra.update({"judge_model": model, "judge_calls": len(reqs), "wins_by_source": dict(verdicts)})
    if hasattr(client, "ledger"):
        tally.extra["judge_cost"] = client.ledger.summary()
    return rows, tally


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("programmatic")
    p.add_argument("--chosen", action="append", required=True, metavar="PATH[=NAME]")
    p.add_argument("--rejected", action="append", required=True, metavar="PATH[=NAME]")
    p.add_argument("--rejected-pick", choices=["hardest", "worst", "all"], default="hardest")
    p.add_argument("--max-pairs-per-case", type=int, default=2)
    p.add_argument("--rejected-require-valid", action="store_true")
    j = sub.add_parser("judge")
    j.add_argument("--candidates", action="append", required=True, metavar="PATH[=NAME]")
    j.add_argument("--judge-provider", default="anthropic")
    j.add_argument("--judge-model", default="claude-opus-5-5")
    j.add_argument("--judge-prompt-file")
    j.add_argument("--policy-file", help="policy text for {policy}")
    j.add_argument("--seed", type=int, default=0)
    j.add_argument("--mock", action="store_true")
    for q in (p, j):
        add_common_args(q)
        add_prompt_args(q)
        add_check_args(q)
        q.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    setup_logging(a.verbose)
    fm = load_fieldmap(a.fieldmap, a.schema)
    gold = load_gold(a.gold, fm)
    refuse_eval_ids(gold, what=a.gold)
    prompt = StudentPrompt.from_files(a.system_file, a.user_template_file)
    checker = Checker(fm, check_cfg_from_args(a))
    if a.cmd == "programmatic":
        rows, tally = programmatic(gold, load_samples(a.chosen), load_samples(a.rejected), prompt, checker, fm,
                                   pick=a.rejected_pick, max_pairs=a.max_pairs_per_case,
                                   rejected_require_valid=a.rejected_require_valid)
    else:
        from shared.frontier_api.clients import LLMClient
        client = LLMClient(mock=True if a.mock else None)
        tpl = Path(a.judge_prompt_file).read_text(encoding="utf-8") if a.judge_prompt_file else DEFAULT_JUDGE_PROMPT
        pol = Path(a.policy_file).read_text(encoding="utf-8") if a.policy_file else ""
        rows, tally = judge(gold, load_samples(a.candidates), prompt, checker, fm, client,
                            provider=a.judge_provider, model=a.judge_model, template=tpl, policy=pol,
                            seed=a.seed)
    write_training_file(a.out, rows, a.eval_manifest, tally)
    tally.save(a.out)
    print(json.dumps({"pairs": tally.kept, "dropped": dict(tally.dropped)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
