from datetime import date

import pytest

from step1_data_generation.lib import mrz

# Specimens from ICAO Doc 9303 (Part 4 Appendix A, Part 5 Appendix A),
# fictional state "Utopia" (UTO).
TD3_SPEC = [
    "P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<",
    "L898902C36UTO7408122F1204159ZE184226B<<<<<10",
]
TD1_SPEC = [
    "I<UTOD231458907<<<<<<<<<<<<<<<",
    "7408122F1204159UTO<<<<<<<<<<<6",
    "ERIKSSON<<ANNA<MARIA<<<<<<<<<<",
]
TODAY = date(2010, 1, 1)  # specimen expiry 2012-04-15 is valid relative to this


def test_check_digit_spec_values():
    assert mrz.check_digit("L898902C3") == "6"
    assert mrz.check_digit("740812") == "2"
    assert mrz.check_digit("120415") == "9"
    assert mrz.check_digit("ZE184226B<<<<<") == "1"
    assert mrz.check_digit("D23145890") == "7"
    assert mrz.check_digit("<<<") == "0"


def test_char_values():
    assert mrz.char_value("A") == 10 and mrz.char_value("Z") == 35
    assert mrz.char_value("<") == 0
    with pytest.raises(mrz.MRZError):
        mrz.char_value("a")


def spec_fields_td3():
    return mrz.MRZFields(
        doc_type="P", issuing_state="UTO", surname="Eriksson",
        given_names="Anna Maria", doc_number="L898902C3", nationality="UTO",
        birth_date=date(1974, 8, 12), sex="F", expiry_date=date(2012, 4, 15),
        optional1="ZE184226B")


def test_build_td3_matches_spec():
    assert mrz.build_td3(spec_fields_td3()) == TD3_SPEC


def test_build_td1_matches_spec():
    f = mrz.MRZFields(
        doc_type="I", issuing_state="UTO", surname="ERIKSSON",
        given_names="ANNA MARIA", doc_number="D23145890", nationality="UTO",
        birth_date=date(1974, 8, 12), sex="F", expiry_date=date(2012, 4, 15))
    assert mrz.build_td1(f) == TD1_SPEC


def test_parse_td3_spec():
    p = mrz.parse(TD3_SPEC, today=TODAY)
    assert p.format == "TD3" and p.valid, p
    assert p.fields.surname == "ERIKSSON"
    assert p.fields.given_names == "ANNA MARIA"
    assert p.fields.doc_number == "L898902C3"
    assert p.fields.birth_date == date(1974, 8, 12)
    assert p.fields.expiry_date == date(2012, 4, 15)
    assert p.fields.optional1 == "ZE184226B"


def test_parse_td1_spec():
    p = mrz.parse("\n".join(TD1_SPEC), today=TODAY)
    assert p.format == "TD1" and p.valid, p
    assert p.fields.doc_number == "D23145890"
    assert p.fields.nationality == "UTO"


def test_roundtrip_td3_and_td1():
    f = mrz.MRZFields(
        doc_type="P", issuing_state="UTO", surname="Al-Rahimi",
        given_names="Mukhammad Karim", doc_number="X12345678", nationality="UTO",
        birth_date=date(1988, 2, 29), sex="M", expiry_date=date(2031, 6, 30))
    for fmt in ("TD3", "TD1"):
        lines = mrz.build(f, fmt)
        p = mrz.parse(lines, today=date(2026, 10, 17))
        assert p.valid, (fmt, p)
        assert p.fields.surname == "AL RAHIMI"
        assert p.fields.given_names == "MUKHAMMAD KARIM"
        assert p.fields.birth_date == f.birth_date
        assert p.fields.expiry_date == f.expiry_date


@pytest.mark.parametrize("pos", [0, 5, 13, 21, 30])
def test_single_char_change_breaks_checks(pos):
    l2 = TD3_SPEC[1]
    new = "7" if l2[pos] != "7" else "3"
    bad = l2[:pos] + new + l2[pos + 1:]
    assert not mrz.parse([TD3_SPEC[0], bad], today=TODAY).valid


def test_name_truncation_and_diacritics():
    s = mrz.format_name("Müller-Lüdenscheidt", "Ö" * 50, 39)
    assert len(s) == 39 and s.startswith("MUELLER<LUEDENSCHEIDT<<OE")


def test_bad_line_count():
    assert not mrz.parse(["ABC"]).valid
