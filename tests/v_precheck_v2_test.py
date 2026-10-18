"""Session V: pre-checker v2 (policy_v1 §3 integrity classes), the stage-4 Sol-narrative file,
the frozen-eval script and the launcher's resume / retry. No network, no GPU."""

import json
import subprocess
from datetime import date
from pathlib import Path

import pytest

from step1_data_generation.lib import mrz as M
from step7_serving import prechecks as P

ROOT = Path(__file__).resolve().parents[1]

FIELDS = M.MRZFields(doc_type="P", issuing_state="UTO", surname="DOE", given_names="JANE",
                     doc_number="X1234567", nationality="UTO", birth_date=date(1990, 1, 15), sex="F",
                     expiry_date=date(2030, 1, 9))
MRZ = M.build_td3(FIELDS)   # line 2: doc 0-8 cd 9 | dob 13-18 cd 19 | expiry 21-26 cd 27


def _sub(line: str, pos: int, ch: str) -> str:
    return line[:pos] + ch + line[pos + 1:]


def packet(dob="1990-01-15", issue="2020-01-10", expiry="2030-01-09", docno="X1234567",
           mrz=MRZ, dob_line=None) -> str:
    id_lines = ["PASSPORT", "Issuing state: UTO", "Surname: DOE", "Given names: JANE",
                dob_line if dob_line is not None else f"Date of birth: {dob}", "Sex: F",
                f"Date of issue: {issue}", f"Date of expiry: {expiry}", f"Passport No.: {docno}"]
    out = ["KYC case", "", "[CTX] Case context", "As-of date: 2026-03-31", "",
           "[ID] ID document scan - OCR text", *id_lines]
    if mrz:
        out += ["[MRZ] Machine-readable zone", *mrz]
    out += ["", "[POA] Proof of address", "No document provided.", ""]
    return "\n".join(out)


def integ(text):
    return P.run_prechecks(text)["integrity"]


def cls(text, fld):
    f = integ(text)["fields"][fld]
    return f["class"] if f else None


# ---------------------------------------------------------------- §3 table, row by row
def test_consistent():
    i = integ(packet())
    assert {k: v["class"] for k, v in i["fields"].items()} == {"birth_date": "consistent", "doc_number": "consistent",
                                                               "expiry_date": "consistent"}
    assert i["overall"] == "consistent"


def test_glyph_noise_is_readable_noise():
    l2 = _sub(MRZ[1], 14, "O")             # 900115 printed as 9O0115
    t = packet(mrz=[MRZ[0], l2])
    assert cls(t, "birth_date") == "noise" and integ(t)["overall"] == "noise only"


def test_one_lookalike_digit_pair_with_failing_check_is_ambiguous():
    l2 = _sub(MRZ[1], 3, "8")              # X1234567 -> X1284567 in the MRZ only (3/8)
    assert not M.is_valid_check(l2[0:9], l2[9])
    t = packet(mrz=[MRZ[0], l2])
    assert cls(t, "doc_number") == "ambiguous" and integ(t)["overall"] == "ambiguous"
    assert "AMBIGUOUS (OCR or tamper)" in P.precheck_block(t)
    assert "- Document integrity (policy §3): ambiguous" in P.precheck_block(t)


def test_mrz_valid_visual_differs_is_clear_tamper():
    t = packet(dob="1990-01-16")
    assert cls(t, "birth_date") == "tamper" and integ(t)["overall"] == "clear tamper"


def test_same_value_failing_check_is_clear_tamper():
    l2 = _sub(MRZ[1], 19, "3" if MRZ[1][19] != "3" else "4")
    t = packet(mrz=[MRZ[0], l2])
    assert cls(t, "birth_date") == "tamper"


def test_other_difference_failing_check_is_clear_tamper():
    l2 = _sub(MRZ[1], 3, "2")              # 3 -> 2 is not a look-alike pair
    if M.is_valid_check(l2[0:9], l2[9]):
        pytest.skip("check digit passes by chance")
    assert cls(packet(mrz=[MRZ[0], l2]), "doc_number") == "tamper"


def test_impossible_expiry_is_clear_tamper():
    f = M.MRZFields(**{**FIELDS.__dict__, "expiry_date": date(2019, 1, 9)})
    t = packet(expiry="2019-01-09", mrz=M.build_td3(f))
    i = integ(t)
    assert i["fields"]["expiry_date"]["class"] == "tamper" and "impossible" in i["fields"]["expiry_date"]["detail"]
    assert i["overall"] == "clear tamper"


def test_illegible_visual_zone():
    assert cls(packet(dob="[illegible]"), "birth_date") == "consistent"          # MRZ passes: MRZ value used
    l2 = _sub(MRZ[1], 19, "3" if MRZ[1][19] != "3" else "4")
    t = packet(dob="[illegible]", mrz=[MRZ[0], l2])
    assert cls(t, "birth_date") == "unreadable"
    assert integ(t)["overall"] == "consistent"     # missing evidence is not an integrity finding


def test_no_mrz_single_source():
    i = integ(packet(mrz=None))
    assert {v["class"] for v in i["fields"].values()} == {"no_mrz"} and i["overall"] == "consistent"


def test_mrz_text_that_does_not_fit_is_nd():
    t = packet(mrz=[MRZ[0], MRZ[1][:30]])
    assert integ(t)["overall"] is None


# ---------------------------------------------------------------- conservative parsing
def test_ambiguous_numeric_dates_are_nd_unless_the_document_proves_the_order():
    # every ID date has day and month <= 12: D.M.Y vs M.D.Y unknown, readings disagree -> n/d
    f = M.MRZFields(**{**FIELDS.__dict__, "birth_date": date(1990, 3, 5), "expiry_date": date(2030, 1, 9)})
    m = M.build_td3(f)
    # (reader v3: the expiry is the only other MRZ date and is written with a month name, so it proves nothing)
    t = packet(dob="05.03.1990", issue="10.01.2020", expiry="09 JAN 2030", mrz=m)
    assert cls(t, "birth_date") is None and integ(t)["overall"] is None
    # reader v3: the expiry 09.01.2030 equals the MRZ expiry only as D.M.Y, which proves the document's order
    t = packet(dob="05.03.1990", issue="10.01.2020", expiry="09.01.2030", mrz=m)
    assert cls(t, "birth_date") == "consistent"
    # an issue date with day 15 proves D.M.Y for the whole document
    t = packet(dob="05.03.1990", issue="15.01.2020", expiry="09.01.2030", mrz=m)
    assert cls(t, "birth_date") == "consistent" and integ(t)["overall"] == "consistent"


def test_label_broken_over_two_lines():
    t = packet(dob_line="Date of birth:\n1990-01-15")
    assert cls(t, "birth_date") == "consistent"


def test_noisy_label_still_read_and_apps_dob_not_used():
    t = packet(dob_line="Date of b1rth: 1990-01-15")
    assert cls(t, "birth_date") == "consistent"
    t = packet(dob_line="Place of birth: TOWN")   # no DOB line in the ID zone -> n/d, not the APP one
    assert cls(t, "birth_date") is None


def test_block_lines_and_note():
    b = P.precheck_block(packet())
    assert "- Date of birth: visual zone 1990-01-15 vs MRZ 900115, equal, check digit OK -> CONSISTENT" in b
    assert b.splitlines()[-1].startswith("- Proof-of-address date:")
    assert "§3" in P.SYSTEM_NOTE


# ---------------------------------------------------------------- stage-4 file
def _sft(cid, target):
    return {"id": f"sft_floor:{cid}:gold:0", "case_id": cid, "source": "sft_floor", "teacher": "gold",
            "messages": [{"role": "system", "content": "s"}, {"role": "user", "content": "u"},
                         {"role": "assistant", "content": json.dumps(target)}]}


def test_gold_with_teacher_narrative(tmp_path):
    from step4_distillation.gold_with_teacher_narrative import build

    g = {"schema_version": "1.0", "risk_tier": "low", "decision": "approve", "narrative": [{"sentence": "gold"}]}
    gold = [_sft("trn-1", g), _sft("trn-2", g), _sft("trn-3", g)]
    sol = [_sft("trn-1", {**g, "narrative": [{"sentence": "sol"}]}),
           _sft("trn-2", {**g, "decision": "escalate", "narrative": [{"sentence": "sol"}]})]
    (tmp_path / "g.jsonl").write_text("".join(json.dumps(r) + "\n" for r in gold), encoding="utf-8")
    (tmp_path / "s.jsonl").write_text("".join(json.dumps(r) + "\n" for r in sol), encoding="utf-8")
    st = build(tmp_path / "g.jsonl", tmp_path / "s.jsonl", tmp_path / "o.jsonl")
    assert (st["rows"], st["narratives_replaced"], st["kept_gold_narrative"]) == (3, 1, 2)
    assert st["kept_why"] == {"decision_differs": 1, "no_teacher_row": 1}
    out = [json.loads(l) for l in (tmp_path / "o.jsonl").read_text(encoding="utf-8").splitlines()]
    t = [json.loads(r["messages"][-1]["content"]) for r in out]
    assert [x["narrative"][0]["sentence"] for x in t] == ["sol", "gold", "gold"]
    assert all(x["decision"] == "approve" for x in t)
    assert out[0]["messages"][:2] == gold[0]["messages"][:2]


def test_gold_with_teacher_narrative_refuses_eval_ids(tmp_path):
    from step4_distillation.gold_with_teacher_narrative import build

    p = tmp_path / "g.jsonl"
    p.write_text(json.dumps(_sft("eid-1", {"decision": "approve"})) + "\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="CONTAMINATION"):
        build(p, p, tmp_path / "o.jsonl")


@pytest.mark.skipif(not (ROOT / "data/sft/gold_train_solnarr.jsonl").exists(), reason="data/ not generated")
def test_solnarr_file_changes_only_narratives():
    gold = (ROOT / "data/sft/gold_train.jsonl").read_text(encoding="utf-8").splitlines()[:50]
    new = (ROOT / "data/sft/gold_train_solnarr.jsonl").read_text(encoding="utf-8").splitlines()[:50]
    for a, b in zip(gold, new):
        a, b = json.loads(a), json.loads(b)
        assert a["messages"][:-1] == b["messages"][:-1]
        x, y = json.loads(a["messages"][-1]["content"]), json.loads(b["messages"][-1]["content"])
        assert list(x) == list(y)
        x.pop("narrative"), y.pop("narrative")
        assert x == y


# ---------------------------------------------------------------- scripts
def _bash(script: str, cwd=ROOT):
    try:
        return subprocess.run(["bash", "-c", script], cwd=cwd, capture_output=True, text=True)
    except OSError:
        pytest.skip("bash not available")


def test_preds_done(tmp_path):
    d = tmp_path / "run"
    d.mkdir()
    (d / "predictions.jsonl").write_text('{"case_id": "a"}\n{"case_id": "b"}\n', encoding="utf-8")
    prov = {"n_cases": 2, "n_written": 2, "n_errors": 0}
    (d / "endpoint_run.json").write_text(json.dumps(prov), encoding="utf-8")
    lib = (ROOT / "step5_training/final_lib.sh").as_posix()
    check = f'. "{lib}"; preds_done "{d.as_posix()}" && echo DONE || echo TODO'
    assert _bash(check).stdout.strip() == "DONE"
    (d / "endpoint_run.json").write_text(json.dumps({**prov, "n_errors": 1}), encoding="utf-8")
    assert _bash(check).stdout.strip() == "TODO"
    (d / "endpoint_run.json").write_text(json.dumps({**prov, "n_cases": 3, "n_written": 3}), encoding="utf-8")
    assert _bash(check).stdout.strip() == "TODO"


def test_eval_frozen_flags_match_dev():
    fz = (ROOT / "step5_training/eval_frozen.sh").read_text(encoding="utf-8")
    dev = (ROOT / "step5_training/eval_on_dev.sh").read_text(encoding="utf-8")
    flags = "--prompt student_short --schema step0_rules/schema/v1_serving.json --warmup 2 --concurrency 16"
    assert flags in fz and flags in dev
    for s in ("eval_id", "eval_ood_template", "eval_ood_hand", "eval_ood_llm", "eval_hard"):
        assert s in fz
    assert "trap 'python -m modal app stop" in fz and "--limit 5" in fz


def test_launch_final_wires_frozen_eval_resume_and_retry():
    lf = (ROOT / "step5_training/launch_final.sh").read_text(encoding="utf-8")
    assert lf.count('evals "$X" "$S3"') == 1 and lf.count('evals "$X" "$S4"') == 1
    assert "bash step5_training/eval_frozen.sh" in lf
    assert "adapter/adapter_config.json" in lf and "/merged/$S4/config.json" in lf
    assert "RETRY" in lf and "sleep 75" in lf
