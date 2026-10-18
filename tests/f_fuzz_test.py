"""Session F: format fuzzer + reader bench."""
import json
from pathlib import Path

import pytest

from step7_serving import fuzz_render as FR
from step7_serving import reader_bench as RB

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def dev():
    return RB.load_split(ROOT / "data" / "dev")[:20]


def test_renderer_deterministic_per_seed(dev):
    _, t = dev[0]
    for fam in FR.FAMILIES:
        a, _ = FR.render(t, fam, 5)
        b, _ = FR.render(t, fam, 5)
        assert a == b
    assert len({FR.render(t, "F-noisy", s)[0] for s in range(5)}) > 1


def test_all_families_render_and_self_check(dev):
    for fam in FR.FAMILIES:
        for i, (_, t) in enumerate(dev):
            packet, _ = FR.render(t, fam, i)
            for ml in t["id_doc"].get("mrz_lines") or []:
                assert ml in packet.split("\n")


def test_self_check_catches_broken_packet(dev):
    _, t = next((c, t) for c, t in dev if t["id_doc"].get("mrz_lines"))
    c = FR._Ctx(FR.random.Random(1), FR.FAMILIES["F-kv"])
    packet = FR.finish(c, FR.render_lines(t, c, "kv"), t)
    assert FR.self_check(packet, t, c.dates) == []
    broken = packet.replace(t["id_doc"]["mrz_lines"][0], t["id_doc"]["mrz_lines"][0][:-1] + "X")
    assert any("MRZ" in e for e in FR.self_check(broken, t, c.dates))
    key, fmt, s, d = c.dates[0]
    assert FR.self_check(packet.replace(s, "[gone]"), t, c.dates)


@pytest.mark.parametrize("fmt", sorted(FR.DATE_FORMATS) + sorted(FR.EXTRA_FORMATS))
def test_date_formats_round_trip(fmt):
    fns = dict(FR.DATE_FORMATS, **FR.EXTRA_FORMATS)
    for d in (FR.date(2026, 3, 1), FR.date(1999, 12, 31), FR.date(2031, 4, 23)):
        s = fns[fmt](d, FR.random.Random(0))
        assert FR.parse_rendered(s, fmt, d.year) == d, (fmt, s)


def test_bench_flags_planted_wrong_value(dev):
    case, t = dev[0]

    class Planted:
        @staticmethod
        def run_prechecks(packet):
            from step7_serving import prechecks
            res = prechecks.run_prechecks(packet)
            res["as_of"] = FR.date(1900, 1, 1)
            return res

    tl = RB.bench_family(Planted, "F-kv", [(case, t)] * 3, 3, 0, 1)
    assert tl.s["as_of"]["n"] == 3
    # a planted value counts as wrong whenever it is produced (never None here)
    assert tl.wrong >= 3 and tl.examples["as_of"]


def test_bench_exit_code_nonzero_on_wrong(monkeypatch, tmp_path):
    from step7_serving import prechecks
    real = prechecks.run_prechecks

    def bad(packet):
        r = real(packet)
        r["as_of"] = FR.date(1900, 1, 1)
        return r

    monkeypatch.setattr(prechecks, "run_prechecks", bad)
    assert RB.main(["--splits", "dev", "--families", "F-kv", "--n", "3", "--no-original"]) == 1


def test_bench_refuses_eval():
    with pytest.raises(SystemExit):
        RB.load_split(ROOT / "data" / "eval")


def test_mrz_block_contiguous_outside_noisy(dev):
    for fam in FR.FAMILIES:
        if FR.FAMILIES[fam].get("mrz_gap"):
            continue
        for i, (_, t) in enumerate(dev):
            ml = t["id_doc"].get("mrz_lines") or []
            if ml:
                assert "\n".join(ml) in FR.render(t, fam, i)[0], fam


def test_inject_values_never_equal_truth(dev):
    for i, (_, t) in enumerate(dev):
        c = FR._Ctx(FR.random.Random(i), FR.FAMILIES["F-inject"])
        viz = t["id_doc"]["viz"]
        for key, true in (("as_of", t["context"]["as_of_date"]), ("id_dob", viz["birth_date"]),
                          ("id_expiry", viz["expiry_date"]), ("doc_number", viz["doc_number"])):
            v = FR._false_value(c, key, t)
            assert str(v) != str(true), (key, v)
        packet, _ = FR.render(t, "F-inject", i)
        assert packet
