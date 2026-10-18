"""Table 2 S6 (correction half): the on-policy correction loop scaffold.

student outputs -> programmatic failures -> correction requests to a teacher -> corrected
outputs re-checked like rejection sampling -> corrected SFT records (and optional DPO pairs:
student output rejected, correction chosen).

    # 1. failures -> requests (LLMRequest JSONL; run with shared.frontier_api.batch or step 2)
    python -m step4_distillation.onpolicy requests --gold data/train/cases.jsonl --fieldmap step6_evaluation/fieldmap_v1.yaml \
        --student outputs/train/student_v1/predictions.jsonl \
        --teacher-provider gemini --teacher-model gemini-4-argon --schema step0_rules/schema/v1.json \
        --system-file step0_rules/prompts/out/teacher_system.txt --out outputs/distill/correct_reqs.jsonl
    # 2a. live (with cache, retries, cost ledger) ...
    python -m step4_distillation.onpolicy run --requests outputs/distill/correct_reqs.jsonl \
        --out outputs/distill/correct_resps.jsonl [--mock]
    # 2b. ... or batch: python -m shared.frontier_api.batch run --job outputs/batches/correct_v1 --requests ...
    # 3. corrections -> SFT (+ DPO)
    python -m step4_distillation.onpolicy collect --gold ... --student ... \
        --corrections outputs/distill/correct_resps.jsonl \
        --system-file step0_rules/prompts/out/student_system.txt --out data/sft/onpolicy.jsonl \
        [--pairs-out data/dpo/onpolicy_pairs.jsonl]
    # or all three at once (live): python -m step4_distillation.onpolicy loop ...

The teacher sees the packet, the student's output and the *names* of the failed checks
("decision", "screening hit H2", "identity field dob"), never the gold values, unless
``--reveal-gold`` is set (experiment_plan R12 says never; distillation_options 2.6 lists it as
an option). Teacher requests carry purpose="teacher", so LLMClient's EvalGuard (enabled
automatically when a frozen eval manifest exists) refuses any request overlapping eval.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from step4_distillation.common import (Checker, StudentPrompt, Tally, add_check_args, add_common_args,
                            add_prompt_args, check_cfg_from_args, discover_manifests, dump_json,
                            dpo_record, group_by_case, load_fieldmap, load_gold,
                            load_samples, read_jsonl, refuse_eval_ids, setup_logging, sft_record,
                            write_jsonl, write_training_file)

CORRECTION_TEMPLATE = """Below is a KYC case packet and a draft decision record written by a junior \
reviewer. Automated checks found problems with the parts listed under PROBLEMS. Re-examine the \
packet and return a complete corrected record in the same JSON format. Fix the listed parts; \
keep the parts that are right; every narrative sentence must cite evidence that is in the packet.

PACKET:
{packet}

DRAFT RECORD:
{draft}

PROBLEMS:
{problems}"""


def correction_prompt(packet: str, draft: str, problems: list[str], template: str = CORRECTION_TEMPLATE,
                      gold_hint: str | None = None) -> str:
    text = (template.replace("{packet}", packet).replace("{draft}", draft)
            .replace("{problems}", "\n".join(f"- {p}" for p in problems)))
    if gold_hint:
        text += "\n\nREFERENCE ANSWER FOR THE STRUCTURED FIELDS:\n" + gold_hint
    return text


def student_failures(gold: dict, student, checker: Checker, tally: Tally):
    """-> list of (case_id, sample, CheckResult) for failing student outputs (first sample per case)."""
    out = []
    for cid, ss in group_by_case(student).items():
        if cid not in gold:
            tally.drop("case_not_in_gold")
            continue
        s = sorted(ss, key=lambda x: x.sample)[0]
        r = checker.check(s.raw, gold[cid]) if s.raw is not None else None
        if r is not None and r.passed:
            tally.drop("student_passes")
            continue
        out.append((cid, s, r))
    return out


def make_requests(gold: dict, student, checker: Checker, fm, *, provider: str, model: str,
                  schema: dict | None, system: str | None, template: str = CORRECTION_TEMPLATE,
                  reveal_gold: bool = False, max_tokens: int = 4096, tally: Tally | None = None):
    from shared.frontier_api.clients import make_request

    tally = tally or Tally("onpolicy_requests")
    reqs, reasons = [], Counter()
    for cid, s, r in student_failures(gold, student, checker, tally):
        g = gold[cid]
        draft = s.raw if isinstance(s.raw, str) else dump_json(s.raw) if s.raw is not None else "(no output)"
        problems = (r.details if r is not None else ["no output"]) or ["the record failed validation"]
        if r is not None:
            reasons.update(r.reasons)
        hint = None
        if reveal_gold:
            exp = g.get(fm.gold_expected_key, {})
            hint = dump_json({k: v for k, v in exp.items() if k != fm.narrative_path.split(".")[0]})
        reqs.append(make_request(provider, model, correction_prompt(g[fm.gold_packet_key], draft, problems,
                                                                      template, hint),
                                 system=system, json_schema=schema, max_tokens=max_tokens,
                                 reasoning_effort="low", purpose="teacher",
                                 metadata={"case_id": cid, "student_sample": s.sample,
                                           "failed": r.reasons if r is not None else ["no_output"],
                                           "teacher": model, "step": "onpolicy_correction"}))
        tally.keep()
    tally.extra.update({"student_failure_reasons": dict(reasons.most_common()), "reveal_gold": reveal_gold})
    return reqs, tally


def make_client(mock: bool | None, manifests):
    from shared.frontier_api.clients import LLMClient
    guard = None
    found = discover_manifests(manifests)
    if found:
        from step6_evaluation.split_guard import EvalGuard
        guards = [EvalGuard.from_manifest(m) for m in found]

        class _All:
            def check(self, text):
                for gd in guards:
                    gd.check(text)
        guard = _All()
    return LLMClient(mock=mock, guard=guard)


def run(reqs, client, max_workers: int = 8) -> list[dict]:
    """Live calls; rows in shared/frontier_api/batch.py results format so `collect` reads either."""
    resps = client.complete_many(reqs, max_workers=max_workers)
    return [{"custom_id": r.request_key, "metadata": dict(q.metadata), "response": r.to_dict()}
            for q, r in zip(reqs, resps)]


def collect(gold: dict, student, corrections, prompt: StudentPrompt, checker: Checker, fm,
            tally: Tally | None = None):
    tally = tally or Tally("onpolicy_collect")
    stu = {cid: sorted(ss, key=lambda x: x.sample)[0] for cid, ss in group_by_case(student).items()}
    sft, pairs, fixed_reasons = [], [], Counter()
    for cid, cs in group_by_case(corrections).items():
        if cid not in gold:
            tally.drop("case_not_in_gold")
            continue
        g = gold[cid]
        best = None
        for c in cs:
            if c.error or c.raw is None:
                tally.drop("api_error")
                continue
            r = checker.check(c.raw, g)
            if not r.passed:
                tally.drop("correction_fails:" + ",".join(r.reasons))
                continue
            if best is None or r.score > best[1].score:
                best = (c, r)
        if best is None:
            continue
        c, r = best
        sft.append(sft_record("onpolicy", cid, prompt, g[fm.gold_packet_key], r.obj, teacher=c.teacher,
                              sample=c.sample, corrected_from=c.meta.get("failed")))
        fixed_reasons.update(c.meta.get("failed") or [])
        s = stu.get(cid)
        if s is not None and s.raw is not None:
            rej = s.raw if isinstance(s.raw, str) else dump_json(s.raw)
            if rej.strip() and rej != dump_json(r.obj):
                pairs.append(dpo_record("onpolicy_pair", cid, prompt, g[fm.gold_packet_key], r.obj, rej,
                                        chosen_from=c.teacher, rejected_from=s.teacher))
        tally.keep()
    tally.extra.update({"fixed_failure_reasons": dict(fixed_reasons.most_common()),
                        "dpo_pairs": len(pairs), "student_cases": len(stu)})
    return sft, pairs, tally


def _load_schema(fm):
    return json.loads(Path(fm.schema_path).read_text(encoding="utf-8")) if fm.schema_path else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    rq = sub.add_parser("requests")
    rn = sub.add_parser("run")
    co = sub.add_parser("collect")
    lp = sub.add_parser("loop")
    for q in (rq, lp):
        q.add_argument("--teacher-provider", required=True)
        q.add_argument("--teacher-model", required=True)
        q.add_argument("--teacher-system-file", help="system prompt for the teacher (default: none)")
        q.add_argument("--correction-template-file", help="template with {packet} {draft} {problems}")
        q.add_argument("--reveal-gold", action="store_true")
        q.add_argument("--max-tokens", type=int, default=4096)
    for q in (rq, co, lp):
        add_common_args(q)
        add_check_args(q)
        q.add_argument("--student", action="append", required=True, metavar="PATH[=NAME]")
    for q in (co, lp):
        add_prompt_args(q)
        q.add_argument("--pairs-out")
    co.add_argument("--corrections", action="append", required=True, metavar="PATH[=NAME]")
    for q in (rn, lp):
        q.add_argument("--mock", action="store_true")
        q.add_argument("--workers", type=int, default=8)
    rn.add_argument("--requests", required=True)
    rn.add_argument("--eval-manifest", action="append", default=None)
    rn.add_argument("-v", "--verbose", action="store_true")
    lp.add_argument("--responses-out", help="also keep the raw teacher responses")
    for q in (rq, rn, co, lp):
        q.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    setup_logging(a.verbose)

    if a.cmd == "run":
        from shared.frontier_api.clients import LLMRequest
        reqs = [LLMRequest.from_dict(d) for d in read_jsonl(a.requests)]
        client = make_client(True if a.mock else None, a.eval_manifest)
        rows = run(reqs, client, a.workers)
        write_jsonl(a.out, rows)
        print(json.dumps({"responses": len(rows), "cost": client.ledger.summary()["total_usd"]}))
        return 0

    fm = load_fieldmap(a.fieldmap, a.schema)
    gold = load_gold(a.gold, fm)
    refuse_eval_ids(gold, what=a.gold)
    checker = Checker(fm, check_cfg_from_args(a))
    student = load_samples(a.student)

    if a.cmd in ("requests", "loop"):
        tsys = Path(a.teacher_system_file).read_text(encoding="utf-8") if a.teacher_system_file else None
        tpl = (Path(a.correction_template_file).read_text(encoding="utf-8")
               if a.correction_template_file else CORRECTION_TEMPLATE)
        reqs, rtally = make_requests(gold, student, checker, fm, provider=a.teacher_provider,
                                     model=a.teacher_model, schema=_load_schema(fm), system=tsys,
                                     template=tpl, reveal_gold=a.reveal_gold, max_tokens=a.max_tokens)
        if a.cmd == "requests":
            write_jsonl(a.out, [q.to_dict() for q in reqs])
            rtally.save(a.out)
            return 0
        client = make_client(True if a.mock else None, a.eval_manifest)
        rows = run(reqs, client, a.workers)
        if a.responses_out:
            write_jsonl(a.responses_out, rows)
        corr_path = Path(a.out).with_name(Path(a.out).name + ".responses.tmp.jsonl")
        write_jsonl(corr_path, rows)
        corrections = load_samples([str(corr_path)])
        corr_path.unlink()
    else:
        corrections = load_samples(a.corrections)

    sft, pairs, tally = collect(gold, student, corrections,
                                StudentPrompt.from_files(a.system_file, a.user_template_file), checker, fm)
    write_training_file(a.out, sft, a.eval_manifest, tally)
    if a.pairs_out:
        write_training_file(a.pairs_out, pairs, a.eval_manifest)
    tally.save(a.out)
    print(json.dumps({"corrected": tally.kept, "pairs": len(pairs), "dropped": dict(tally.dropped)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
