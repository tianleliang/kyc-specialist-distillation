"""Session F: step6_evaluation/split_guard.py."""

import json
import os
import random
import stat

import pytest

from shared.frontier_api.clients import ContaminationError, LLMClient, make_request
from step6_evaluation.split_guard import (
    CheckConfig, Doc, EvalGuard, check_overlap, freeze, load_docs, main, normalize,
    record_text, shingles, verify,
)

FIRST = ["Tavrin", "Oleska", "Muradin", "Xiaolen", "Kezia", "Bronimir", "Saelis", "Odrun", "Velka", "Imaro"]
LAST = ["Quenvald", "Harrowmere", "Zhaoviel", "Mirtanov", "Ebberlund", "Castrovane", "Ilmaris", "Doralsk"]
STREETS = ["Lanternfold", "Cobberway", "Thistlemark", "Juniper Wynd", "Ostrel", "Fennick"]


def packet(rng: random.Random) -> str:
    """Template boilerplate + distinctive fictional fields, like the real generator."""
    name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
    dob = f"{rng.randint(1950, 2004)}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"
    doc = f"P{rng.randint(10**7, 10**8 - 1)}"
    addr = f"{rng.randint(1, 999)} {rng.choice(STREETS)} Road, Unit {rng.randint(1, 80)}"
    score = rng.randint(55, 99)
    occ = rng.choice(["teacher", "welder", "software engineer", "pharmacist", "farmer"])
    funds = rng.choice(["salary", "inheritance", "business income", "property sale"])
    return (
        "APPLICANT PROFILE\nThe applicant submitted the following details for account onboarding.\n"
        f"Full name: {name}\nDate of birth: {dob}\nOccupation: {occ}\nSource of funds: {funds}\n"
        f"Residential address: {addr}\n"
        "IDENTITY DOCUMENT OCR\nThe following text was extracted from the identity document.\n"
        f"Document number {doc} name {name.upper()} born {dob} expires {rng.randint(2025, 2035)}-06-30\n"
        "PROOF OF ADDRESS\nUtility bill issued to the applicant at the residential address.\n"
        f"Billed to {name} at {addr} dated 2026-0{rng.randint(1, 9)}-15 amount {rng.randint(20, 400)}.{rng.randint(10, 99)}\n"
        "SCREENING RESULTS\nThe screening vendor returned the following candidate hits.\n"
        f"Hit 1 listed name {rng.choice(FIRST)} {rng.choice(LAST)} list source synthetic sanctions list score {score}\n"
    )


def write_jsonl(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return str(path)


def sft_row(pkt):
    return {"messages": [{"role": "system", "content": "You are a KYC analyst. Return JSON."},
                         {"role": "user", "content": pkt},
                         {"role": "assistant", "content": '{"decision":"approve"}'}]}


def ocr_noise(text, rng, rate=0.02):
    sub = {"0": "O", "1": "l", "5": "S", "8": "B", "o": "0", "l": "1"}
    return "".join(sub.get(ch, ch) if rng.random() < rate else ch for ch in text)


@pytest.fixture
def sets():
    rng = random.Random(7)
    train = [packet(rng) for _ in range(200)]
    rng = random.Random(99)
    ev = [packet(rng) for _ in range(60)]
    return train, ev


def docs(texts, prefix):
    return [Doc(id=f"{prefix}{i}", text=t) for i, t in enumerate(texts)]


def test_normalize_and_shingles():
    assert normalize("  Full NAME:\tÀbc—déf ") == "full name àbc déf"
    assert len(shingles("a b c", 8)) == 1 and shingles("", 8) == set()
    assert len(shingles(" ".join(map(str, range(10))), 8)) == 3


def test_record_text_variants():
    assert record_text({"packet": "P"}) == "P"
    assert record_text(sft_row("PKT")) == "PKT"  # system + assistant turns excluded
    assert record_text({"prompt": [{"role": "user", "content": "Q"}], "chosen": "x"}) == "Q"
    assert record_text({"a": {"b": "deep"}}, "a.b") == "deep"
    assert json.loads(record_text({"z": 1, "y": 2})) == {"y": 2, "z": 1}


def test_clean_split_has_no_findings(sets):
    train, ev = sets
    rep = check_overlap(docs(train, "t"), docs(ev, "e"))
    assert rep["findings"] == [] and rep["boilerplate_ngrams_dropped"] > 0


def test_boilerplate_filter_matters(sets):
    """Without the df filter, shared template text alone pushes containment up."""
    train, ev = sets
    with_f = check_overlap(docs(train, "t"), docs(ev, "e"), CheckConfig(containment=0.3))
    without = check_overlap(docs(train, "t"), docs(ev, "e"), CheckConfig(containment=0.3, max_df=1.0))
    assert with_f["contaminated_eval_records"] == 0 < without["contaminated_eval_records"]


def test_exact_copy_detected(sets):
    train, ev = sets
    rep = check_overlap(docs(train + [ev[3]], "t"), docs(ev, "e"))
    methods = {f["method"] for f in rep["findings"] if f["eval"] == "e3"}
    assert {"exact", "containment", "minhash"} <= methods
    assert rep["contaminated_eval_records"] == 1


def test_embedded_in_sft_prompt_detected(sets):
    train, ev = sets
    t = docs(train, "t") + [Doc("sft", record_text(sft_row("Please review:\n" + ev[5] + "\nThanks")))]
    rep = check_overlap(t, docs(ev, "e"))
    assert any(f["eval"] == "e5" and f["method"] == "containment" for f in rep["findings"])
    # containment also catches it when the whole SFT record is used as text
    t2 = docs(train, "t") + [Doc("raw", json.dumps(sft_row(ev[5])))]
    assert check_overlap(t2, docs(ev, "e"))["contaminated_eval_records"] == 1


def test_near_duplicate_detected(sets):
    train, ev = sets
    noisy = ocr_noise(ev[10], random.Random(1), rate=0.01)
    assert noisy != ev[10]
    rep = check_overlap(docs(train + [noisy], "t"), docs(ev, "e"), CheckConfig(ngram=5))
    assert {f["eval"] for f in rep["findings"]} == {"e10"}
    assert not any(f["method"] == "exact" for f in rep["findings"])


def test_minhash_estimate_tracks_jaccard(sets):
    train, ev = sets
    rep = check_overlap(docs([ev[0]], "t"), docs(ev, "e"), CheckConfig(jaccard=0.5))
    mh = [f for f in rep["findings"] if f["method"] == "minhash"]
    assert mh and all(abs(f["score"] - f["jaccard"]) < 0.15 for f in mh)


def test_freeze_verify_and_tamper(tmp_path, sets):
    _, ev = sets
    (tmp_path / "eval").mkdir()
    p = write_jsonl(tmp_path / "eval" / "same_method.jsonl", [{"id": i, "packet": t} for i, t in enumerate(ev)])
    m = freeze([p], tmp_path / "eval" / "MANIFEST.json", readonly=True)
    e = m["files"][0]
    assert e["records"] == 60 and len(e["record_sha256"]) == 60 and e["path"] == "same_method.jsonl"
    assert not os.stat(p).st_mode & stat.S_IWUSR
    assert verify(tmp_path / "eval" / "MANIFEST.json") == []
    os.chmod(p, 0o644)
    with open(p, "a") as f:
        f.write('{"id": 999, "packet": "x"}\n')
    assert verify(tmp_path / "eval" / "MANIFEST.json") == ["changed: same_method.jsonl"]
    os.remove(p)
    assert verify(tmp_path / "eval" / "MANIFEST.json") == ["missing: same_method.jsonl"]


def test_cli_exit_codes(tmp_path, sets, capsys):
    train, ev = sets
    tr = write_jsonl(tmp_path / "train.jsonl", [sft_row(t) for t in train])
    bad = write_jsonl(tmp_path / "train_bad.jsonl", [sft_row(t) for t in train] + [sft_row(ev[2])])
    evp = write_jsonl(tmp_path / "eval.jsonl", [{"case_id": f"c{i}", "packet": t} for i, t in enumerate(ev)])
    man = tmp_path / "MANIFEST.json"
    assert main(["freeze", evp, "--manifest", str(man)]) == 0
    assert main(["verify", "--manifest", str(man)]) == 0
    assert main(["check", "--train", tr, "--eval", evp, "--manifest", str(man)]) == 0
    rep = tmp_path / "rep.json"
    assert main(["check", "--train", bad, "--eval", evp, "--report", str(rep)]) == 1
    assert json.loads(rep.read_text())["findings"][0]["eval"].endswith(":c2")
    assert "CONTAMINATION" in capsys.readouterr().out
    assert main(["check", "--train", str(tmp_path / "nope.jsonl"), "--eval", evp]) == 2
    assert main(["bogus"]) == 2
    with open(evp, "a") as f:
        f.write("{}\n")
    assert main(["verify", "--manifest", str(man)]) == 1
    assert main(["check", "--train", tr, "--eval", evp, "--manifest", str(man)]) == 1


def test_eval_guard_blocks_teacher_calls(tmp_path, sets):
    train, ev = sets
    evp = write_jsonl(tmp_path / "eval.jsonl", [{"packet": t} for t in ev])
    freeze([evp], tmp_path / "MANIFEST.json")
    guard = EvalGuard.from_manifest(tmp_path / "MANIFEST.json")
    guard.check(train[0])  # fresh training case passes
    with pytest.raises(ContaminationError, match="eval record"):
        guard.check("System prompt...\n" + ev[4])
    client = LLMClient(mock=True, cache_dir=None, guard=guard)
    with pytest.raises(ContaminationError):
        client.complete(make_request("openai", "gpt-6-luna", user=ev[4], purpose="teacher"))
    assert client.complete(make_request("openai", "gpt-6-luna", user=train[0], purpose="teacher")).text
    # baselines are *supposed* to run on eval cases
    assert client.complete(make_request("openai", "gpt-6-luna", user=ev[4], purpose="baseline")).text


def test_eval_guard_refuses_tampered_manifest(tmp_path, sets):
    _, ev = sets
    evp = write_jsonl(tmp_path / "eval.jsonl", [{"packet": t} for t in ev])
    freeze([evp], tmp_path / "MANIFEST.json")
    with open(evp, "a") as f:
        f.write('{"packet": "late addition"}\n')
    with pytest.raises(RuntimeError, match="does not verify"):
        EvalGuard.from_manifest(tmp_path / "MANIFEST.json")


def test_load_docs_ids(tmp_path):
    p = write_jsonl(tmp_path / "x.jsonl", [{"id": "a", "text": "t"}, {"text": "u"}])
    assert [d.id.split(":")[-1] for d in load_docs([p])] == ["a", "2"]
