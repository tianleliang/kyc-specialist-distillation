"""Session M: stage 2 domain adapter (step3_domain_adapter/). Pure-python parts always run; the CPU
smoke (tiny offline model: train -> measure) runs only where torch/transformers/peft/datasets/modal exist."""
import re
import subprocess
from pathlib import Path

import pytest

from step1_data_generation.lib.mrz import check_digit
from step3_domain_adapter import common as C
from step3_domain_adapter import probe as P

ROOT = Path(__file__).resolve().parents[1]


def _cfg(**kw):
    return C.AdapterCfg(run_name="t", base_model="x", **kw)


def test_chunking_respects_target_and_keeps_text():
    text = "\n\n".join(f"para {i} " + "w" * (i * 37 % 900) for i in range(200)) + "\n\n" + "z" * 9000
    ch = C.chunk_text(text, 1000)
    assert all(len(c) <= 1000 for c in ch)
    assert "".join("".join(ch).split()) == "".join(text.split())


def test_split_deterministic_disjoint_about_ten_percent():
    a, b = C.split_corpus(_cfg()), C.split_corpus(_cfg())
    assert a == b
    assert not set(a["train"]) & set(a["heldout"])
    n = len(a["train"]) + len(a["heldout"])
    assert 0.04 < len(a["heldout"]) / n < 0.2
    assert all(f["train_chunks"] > 0 for f in a["files"].values())
    assert C.split_corpus(_cfg(exclude_files=["address_formats"]))["files"].keys() == \
        set(a["files"]) - {"address_formats"}


def test_cap_per_file():
    s = C.split_corpus(_cfg(max_chars_per_file=10000))
    assert all(f["chars"] <= 10000 for f in s["files"].values())


def test_configs_load_and_real_one_needs_decisions():
    from step5_training.common import require_no_placeholders

    real = C.load_cfg(ROOT / "step3_domain_adapter/configs/adapter.yaml")
    with pytest.raises(SystemExit, match="placeholders"):
        require_no_placeholders(real)
    toy = C.load_cfg(ROOT / "step3_domain_adapter/configs/adapter_toy.yaml")
    require_no_placeholders(toy)
    assert real.lora.r == 32 and toy.backend == "trl"


def test_probe_shape():
    its = P.items()
    assert len(its) == 30 and len({i["id"] for i in its}) == 30
    assert {t: sum(i["topic"] == t for i in its) for t in ("mrz", "pep", "alias")} == {"mrz": 10, "pep": 10, "alias": 10}
    for i in its:
        assert len(i["options"]) == 4 and len(set(i["options"])) == 4 and 0 <= i["answer"] < 4
        assert i["source"] and i["evidence"]


def test_probe_check_digits_correct():
    for i in P.items():
        if i["id"].startswith("mrz_cd_"):
            s = re.search(r"field '([^']+)'", i["question"]).group(1)
            assert i["options"][i["answer"]] == check_digit(s)


def test_probe_not_in_corpus():
    """The probe questions are not copied into the training text."""
    blob = " ".join(" ".join(C.split_corpus(_cfg())["train"]).split()).casefold()
    for i in P.items():
        assert " ".join(i["question"].split()).casefold()[:60] not in blob


def test_answerability_reflects_corpus_on_disk(tmp_path):
    on_disk = P.answerability(C.CORPUS_DIR)
    assert on_disk["cdd_threshold"] and on_disk["alias_weak"]          # files in the repo today
    (tmp_path / "icao9303_p3.txt").write_text("The check digit uses weights 7, 3, 1 and the filler <.")
    a = P.answerability(tmp_path)
    assert a["mrz_weights"] and a["mrz_cd_1"] and not a["cdd_threshold"]


def test_fetch_script_syntax_and_every_url_tagged():
    sh = ROOT / "step3_domain_adapter/corpus/fetch_corpus.sh"
    subprocess.run(["bash", "-n", str(sh)], check=True)
    for line in sh.read_text().splitlines():
        if re.match(r"^(pdf|txt) \w+", line):
            block_end = line.rstrip().endswith("\\")
            assert block_end or "VERIFIED-SEARCH" in line or "UNVERIFIED" in line, line


def test_verdict_logic():
    from step3_domain_adapter.common import verdict

    def rep(ppl, acc):
        return {"perplexity": {"overall": ppl}, "probe": {"all": {"n": 30, "accuracy": acc, "mean_margin": 0.0},
                                                          "answerable": {"n": 12, "accuracy": acc, "mean_margin": 0.0}}}

    assert verdict(rep(10.0, 0.5), rep(9.0, 0.5))["moved"]
    assert not verdict(rep(10.0, 0.5), rep(9.9, 0.6))["moved"]      # perplexity barely moved
    assert not verdict(rep(10.0, 0.5), rep(8.0, 0.4))["moved"]      # knowledge went down
    assert verdict(rep(10.0, 0.5), rep(9.0, 0.5))["probe_subset"] == "answerable"


def test_cpu_smoke(tmp_path):
    for mod in ("torch", "transformers", "peft", "datasets", "tokenizers", "modal", "trl"):
        pytest.importorskip(mod)
    from step3_domain_adapter.cpu_smoke import run

    res = run(tmp_path)
    assert res["ppl_after"] < res["ppl_before"]
    assert res["probe_n"] == 30 and res["train"]["params_trainable"] > 0
    assert (tmp_path / "adapter" / "smoke" / "run.json").exists()
    assert (tmp_path / "adapter" / "smoke" / "measure.json").exists()
