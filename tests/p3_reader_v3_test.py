"""Session P3: pre-checker reader v3 (layout-free readers + vote) and the blank-block option."""

import json
from datetime import date

from step1_data_generation.lib import mrz as M
from step4_distillation.add_prechecks import add_prechecks, is_blanked
from step7_serving import prechecks as P

FIELDS = M.MRZFields(doc_type="P", issuing_state="UTO", surname="DOE", given_names="JANE",
                     doc_number="X1234567", nationality="UTO", birth_date=date(1990, 1, 15), sex="F",
                     expiry_date=date(2030, 1, 9))
MRZ = M.build_td3(FIELDS)


def d2(s, order=None):
    m = P.DATE2_RE.fullmatch(s)
    return set(P.date2_candidates(m, order)) if m else None


# ---------------------------------------------------------------- universal date reader
def test_date_reader_formats():
    one = {"2026-01-14": date(2026, 1, 14), "14.01.2026": date(2026, 1, 14), "14/01/2026": date(2026, 1, 14),
           "14-01-2026": date(2026, 1, 14), "14 JAN 2026": date(2026, 1, 14), "14 january 2026": date(2026, 1, 14),
           "JAN 14 2026": date(2026, 1, 14), "January 14th, 2026": date(2026, 1, 14),
           "3rd March 2026": date(2026, 3, 3), "March 3rd, 2026": date(2026, 3, 3), "20260114": date(2026, 1, 14),
           "14-Jan-2026": date(2026, 1, 14), "2026/01/14": date(2026, 1, 14)}
    for s, d in one.items():
        assert d2(s) == {d}, s


def test_date_reader_ambiguity_gives_candidates():
    assert d2("03.04.2026") == {date(2026, 4, 3), date(2026, 3, 4)}
    assert d2("03.04.2026", "DMY") == {date(2026, 4, 3)}
    assert d2("14.01.26") == {date(1926, 1, 14), date(2026, 1, 14)}      # century not proven
    assert d2("31.02.2026") == set()                                      # date-shaped, invalid


def test_numeric_order_proof():
    assert P.numeric_order("issued 14.01.2020, expires 03.04.2030") == "DMY"
    assert P.numeric_order("issued 01/14/2020") == "MDY"
    assert P.numeric_order("03.04.2030") is None


# ---------------------------------------------------------------- flat text, parts, cue roles
def test_flatten_drops_mrz_and_layout():
    f = P.flatten("Date of expiry\n" + "MRZ\n" + "\n".join(MRZ) + "\n09.01.2030")
    assert "<" not in f and f == "Date of expiry 09.01.2030"


def test_parts_and_roles_without_headers():
    flat = ("CTX Assessed as of 31 MAR 2026 APP Applicant name Jane Doe Date of birth 15 JAN 1990 "
            "ID PASSPORT Date of birth 15.01.1990 Date of issue 10.01.2020 Date of expiry 09.01.2030 "
            "Passport No. X1234567 POA Utility bill Date: 14.02.2026 Amount due 12.00 SCR no hits")
    kinds = [k for _, _, k in P.parts(flat)]
    assert kinds[:5] == ["CTX", "APP", "ID", "POA", "SCR"]
    roles = [(r["role"], r["part"]) for r in P.role_dates(flat)]
    assert roles == [("asof", "CTX"), ("dob", "APP"), ("dob", "ID"), ("issue", "ID"), ("expiry", "ID"),
                     ("poa", "POA")]
    assert P.cue_as_of(flat) == date(2026, 3, 31)
    assert P.cue_poa_date(flat, date(2026, 3, 31)) == date(2026, 2, 14)
    v = P.cue_viz_fields(flat)
    assert v["birth_date"] == {date(1990, 1, 15)} and v["doc_number"] == "X1234567"


def test_place_of_birth_is_not_a_dob_cue_and_printed_dates_are_not_poa():
    flat = "POA Utility bill Printed on 02.03.2026 Bill date: 14.02.2026"
    assert P.cue_poa_date(flat, date(2026, 3, 31)) == date(2026, 2, 14)
    flat = "POA Utility bill Bill date: 14.02.2026 Statement date: 15.02.2026"
    assert P.cue_poa_date(flat, date(2026, 3, 31)) == P.CONFLICT          # two PoA dates compete -> n/d


def test_poa_tie_break_only_drops_impossible_reading():
    # 05.04.2026 vs as-of 2026-03-10: 4 May would be 55 days after as-of (> 31) -> 5 April... also after;
    # 02.12.2026 vs as-of 2026-03-10: 2 Dec is impossible, 12 Feb is the only reading left
    flat = "POA Utility bill Bill date: 12.02.2026"
    assert P.cue_poa_date(flat, date(2026, 3, 10)) == date(2026, 2, 12)
    flat = "POA Utility bill Bill date: 02.12.2026"
    assert P.cue_poa_date(flat, date(2026, 3, 10)) == date(2026, 2, 12)
    flat = "POA Utility bill Bill date: 02.01.2026"
    assert P.cue_poa_date(flat, date(2026, 3, 10)) is None                # both readings possible -> n/d


# ---------------------------------------------------------------- MRZ by shape
def test_mrz_by_shape_inline_and_glued_self_verified():
    for t in ("ID MRZ: " + " ".join(MRZ) + " end", "".join(MRZ)):
        assert P.find_mrz_shape(t) == ("TD3", MRZ)
        assert P.has_mrz_text(t)
    # a check digit that fails: found by shape but not confirmed -> not used, still MRZ-looking text
    bad = MRZ[1][:9] + str((int(MRZ[1][9]) + 1) % 10) + MRZ[1][10:]
    assert P.find_mrz_shape("MRZ: " + MRZ[0] + " " + bad) is None
    assert P.has_mrz_text("MRZ: " + MRZ[0] + " " + bad)


def test_inline_mrz_never_gives_single_source():
    pkt = ("CTX As-of date 2026-03-31 ID PASSPORT Date of birth 1990-01-15 Date of issue 2020-01-10 "
           "Date of expiry 2030-01-09 Passport No. X1234567 MRZ: " + " ".join(MRZ) + " POA none")
    r = P.run_prechecks(pkt)
    assert r["mrz"]["status"] == "valid" and r["expiry"] == date(2030, 1, 9)
    assert r["integrity"]["overall"] == "consistent"
    # MRZ-looking text that cannot be confirmed: never "single source (no MRZ)", never a visual expiry
    pkt2 = pkt.replace(MRZ[1], MRZ[1][:30] + "<<")
    r2 = P.run_prechecks(pkt2)
    assert r2["expiry"] is None
    assert all(f is None or f["class"] != P.NO_MRZ for f in r2["integrity"]["fields"].values())


# ---------------------------------------------------------------- the vote
def test_conflict_is_a_veto():
    assert P._agree({date(2026, 1, 2)}, P.CONFLICT) is None
    assert P.cue_poa_date("POA bill Bill date: 14.02.2026 Bill date: 15.02.2026", date(2026, 3, 1)) == P.CONFLICT


def test_agree():
    assert P._agree(None, None) is None
    assert P._agree({date(2026, 1, 2)}, None) == {date(2026, 1, 2)}
    assert P._agree({date(2026, 1, 2), date(2026, 2, 1)}, {date(2026, 1, 2)}) == {date(2026, 1, 2)}
    assert P._agree({date(2026, 1, 2)}, {date(2026, 1, 3)}) is None
    assert P._agree("X1", "X1") == "X1" and P._agree("X1", "X2") is None


def test_readers_disagree_is_nd():
    # label reader sees one DOB, the cue reader (flat text) another one later in the ID part
    pkt = ("[CTX]\nAs-of date: 2026-03-31\n[ID] scan\nDate of birth: 1990-01-15\nDate of issue: 2020-01-10\n"
           "Date of expiry: 2030-01-09\nPassport No.: X1234567\nborn 1991-01-15\n" + "\n".join(MRZ) + "\n")
    r = P.run_prechecks(pkt)
    assert r["integrity"]["fields"]["birth_date"] is None


def test_anchor_vetoes_a_competing_token():
    pkt = ("[CTX]\nAs-of date: 2026-03-31\n[ID] scan\nDate of birth: 1990-01-15\nDate of issue: 2020-01-10\n"
           "Date of expiry: 2030-01-09\nPassport No.: X1234568\nRef X1234567\n" + "\n".join(MRZ) + "\n")
    r = P.run_prechecks(pkt)
    assert r["integrity"]["fields"]["doc_number"] is None


def test_mrz_proves_order_of_the_other_field_only():
    f = M.MRZFields(**{**FIELDS.__dict__, "birth_date": date(1990, 3, 5), "expiry_date": date(2030, 1, 9)})
    m = M.build_td3(f)
    base = ("[CTX]\nAs-of date: 2026-03-31\n[ID] scan\nDate of birth: {dob}\nDate of issue: 10.01.2020\n"
            "Date of expiry: {exp}\nPassport No.: X1234567\n" + "\n".join(m) + "\n")
    # expiry matches the MRZ only as D.M.Y -> DOB read D.M.Y -> consistent
    r = P.run_prechecks(base.format(dob="05.03.1990", exp="09.01.2030"))
    assert r["integrity"]["fields"]["birth_date"]["class"] == P.CONSISTENT
    # same document order, DOB swapped (03.05 read D.M.Y = 3 May != 5 Mar) -> not consistent
    r = P.run_prechecks(base.format(dob="03.05.1990", exp="09.01.2030"))
    f = r["integrity"]["fields"]["birth_date"]
    assert f is None or f["class"] != P.CONSISTENT


# ---------------------------------------------------------------- API unchanged
def test_block_header_and_lines_unchanged():
    b = P.format_block(P.run_prechecks("nothing here"))
    assert b.splitlines()[0] == P.HEADER and len(b.splitlines()) == 9
    assert P.format_block(P.blank_result()).count("n/d") == 9     # header + 8 items


# ---------------------------------------------------------------- blank-block option
def test_blank_rate_deterministic_and_counted(tmp_path):
    rows = [{"case_id": f"trn-1-{i:06d}", "messages": [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "<packet>\nAs-of date: 2026-03-31\n</packet>"},
        {"role": "assistant", "content": "{}"}]} for i in range(200)]
    inp = tmp_path / "in.jsonl"
    inp.write_text("".join(json.dumps(r) + "\n" for r in rows))
    s1 = add_prechecks(inp, tmp_path / "a.jsonl", blank_rate=0.25, seed=17)
    s2 = add_prechecks(inp, tmp_path / "b.jsonl", blank_rate=0.25, seed=17)
    assert (tmp_path / "a.jsonl").read_text() == (tmp_path / "b.jsonl").read_text()
    assert s1["blanked_rows"] == s2["blanked_rows"] and 30 <= s1["blanked_rows"] <= 70
    out = [json.loads(l) for l in (tmp_path / "a.jsonl").read_text().splitlines()]
    blanked = [r for r in out if "- As-of date: n/d" in r["messages"][1]["content"]]
    assert len(blanked) == s1["blanked_rows"]
    assert all(P.HEADER in r["messages"][1]["content"] for r in out)
    assert add_prechecks(inp, tmp_path / "c.jsonl")["blanked_rows"] == 0
    assert is_blanked("x", 0.25, 17) == is_blanked("x", 0.25, 17)
