"""Split-aware configs (step1_data_generation/configs/*.yaml) and the step1_data_generation/build.py CLI.
Disjointness is proven two ways: entity pools directly, and
step6_evaluation/split_guard.py check (as a subprocess) on small built samples."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from step1_data_generation import build as B
from step1_data_generation.config import HELDOUT_STYLES, SEEN_STYLES, GenConfig, Partition, load_config
from step1_data_generation.sample import sample_cases

ROOT = Path(__file__).resolve().parents[1]
SPLITS = ("train", "dev", "eval_id", "eval_ood_template")
CFG = {s: load_config(ROOT / "step1_data_generation" / "configs" / f"{s}.yaml") for s in SPLITS}


def test_configs_load_and_name_their_split():
    for s, c in CFG.items():
        assert c.split == s and c.source_sha256
        assert c.seed_range[0] <= c.default_seed <= c.seed_range[1]
        assert not c.twins.get("enabled") and not c.knockout.get("enabled")   # off by default


def test_seed_ranges_and_buckets_disjoint():
    cs = list(CFG.values())
    for i, a in enumerate(cs):
        for b in cs[i + 1:]:
            assert a.seed_range[1] < b.seed_range[0] or b.seed_range[1] < a.seed_range[0]
            assert not set(a.partition_buckets) & set(b.partition_buckets)
    assert set().union(*(c.partition_buckets for c in cs)) == set(range(10))


def test_heldout_layouts_never_in_train_or_dev():
    for s in ("train", "dev"):
        assert set(CFG[s].styles) <= set(SEEN_STYLES)
    assert set(CFG["eval_ood_template"].styles) == set(HELDOUT_STYLES)
    assert set(HELDOUT_STYLES) <= set(CFG["eval_id"].styles)
    with pytest.raises(ValueError):
        GenConfig(split="train", styles={"kv": 1, "email": 1})


def test_nationality_pools_and_injections_differ_for_eval():
    tr = CFG["train"]
    for s in ("eval_id", "eval_ood_template"):
        ev = CFG[s]
        assert ev.nationality_pools != tr.nationality_pools
        assert any(set(ev.nationality_pools[o]) - set(tr.nationality_pools[o]) for o in tr.nationality_pools)
        assert not {x[2] for x in ev.injection_pool} & {x[2] for x in tr.injection_pool}
    assert CFG["dev"].nationality_pools == tr.nationality_pools   # dev = train distribution


def test_augmentation_refused_for_eval():
    with pytest.raises(ValueError):
        GenConfig(split="eval_id", twins={"enabled": True})


def test_seed_out_of_range_refused():
    with pytest.raises(ValueError):
        sample_cases(3, 3000000, cfg=CFG["train"])


def test_partition_is_stable():
    p = Partition([0, 1, 2])
    assert Partition.bucket("person_name", "Wei Zhang") == Partition.bucket("person_name", "wei zhang")
    assert p.ok("x", "y") == Partition([0, 1, 2]).ok("x", "y")
    assert Partition(None).ok("anything", "at all")


@pytest.fixture(scope="module")
def truths():
    return {s: sample_cases(150, c.default_seed, cfg=c) for s, c in CFG.items()}


def test_entity_pools_disjoint_across_splits(truths):
    sets = {s: B.entity_sets(ts) for s, ts in truths.items()}
    for i, a in enumerate(SPLITS):
        for b in SPLITS[i + 1:]:
            for pool in sets[a]:
                if pool == "injection_text" and {a, b} == {"train", "dev"}:
                    continue   # dev shares train's injection pool by design (same distribution)
                common = sets[a][pool] & sets[b].get(pool, set())
                assert not common, (a, b, pool, sorted(common)[:3])


def test_case_ids_embed_split(truths):
    pref = {"train": "trn-", "dev": "dev-", "eval_id": "eid-", "eval_ood_template": "ood-"}
    for s, ts in truths.items():
        assert all(t.case_id.startswith(pref[s]) and t.split == s and t.knobs["split"] == s for t in ts)


# ---- build CLI -------------------------------------------------------------
def _run_build(*args):
    return subprocess.run([sys.executable, "-m", "step1_data_generation.build", *args], cwd=ROOT, capture_output=True, text=True)


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    d = tmp_path_factory.mktemp("built")
    out = {}
    for s, n in (("train", 60), ("dev", 30), ("eval_id", 40), ("eval_ood_template", 40)):
        extra = ["--allow-eval"] if s.startswith("eval") else []
        r = _run_build("--config", f"step1_data_generation/configs/{s}.yaml", "--n", str(n), "--out", str(d / s), *extra)
        assert r.returncode == 0, r.stderr
        out[s] = d / s
    return out


def test_build_writes_files_and_manifest(built):
    m = json.loads((built["train"] / "manifest.json").read_text(encoding="utf-8"))
    assert m["split"] == "train" and m["n_total"] == 60 and m["config_sha256"] == CFG["train"].source_sha256
    for name, h in m["sha256"].items():
        assert hashlib.sha256((built["train"] / name).read_bytes()).hexdigest() == h
    rows = [json.loads(l) for l in (built["train"] / "cases.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {"case_id", "split", "knobs", "packet", "expected", "style"} <= set(rows[0])
    assert all(r["style"] == r["knobs"]["style"] for r in rows)
    sg = m["split_guard"]  # before the freeze: a "no frozen eval manifest" note; after: a clean check
    assert "no frozen eval manifest" in json.dumps(sg) or sg.get("contaminated_eval_records") == 0


def test_build_is_reproducible(built, tmp_path):
    r = _run_build("--config", "step1_data_generation/configs/train.yaml", "--n", "60", "--out", str(tmp_path / "again"))
    assert r.returncode == 0, r.stderr
    a = json.loads((built["train"] / "manifest.json").read_text(encoding="utf-8"))["sha256"]
    b = json.loads((tmp_path / "again" / "manifest.json").read_text(encoding="utf-8"))["sha256"]
    assert a == b


def test_build_refuses_eval_without_flag_and_overwrites(built, tmp_path):
    r = _run_build("--config", "step1_data_generation/configs/eval_id.yaml", "--n", "5", "--out", str(tmp_path / "e"))
    assert r.returncode != 0 and "refusing" in (r.stderr + r.stdout)
    assert not (tmp_path / "e" / "cases.jsonl").exists()
    r = _run_build("--config", "step1_data_generation/configs/train.yaml", "--n", "5", "--out", str(built["train"]))
    assert r.returncode != 0 and "refusing to overwrite" in (r.stderr + r.stdout)


def test_build_overrides(tmp_path):
    r = _run_build("--config", "step1_data_generation/configs/train.yaml", "--n", "40", "--out", str(tmp_path / "o"),
                   "--set", "ocr_digit_to_digit_in_numeric=false", "--set", "styles={kv: 1.0}")
    assert r.returncode == 0, r.stderr
    m = json.loads((tmp_path / "o" / "manifest.json").read_text(encoding="utf-8"))
    assert m["config"]["ocr_digit_to_digit_in_numeric"] is False and m["style_counts"] == {"kv": 40}
    assert "--set ocr_digit_to_digit_in_numeric=false" in m["command"]


def _guard(train, eval_):
    return subprocess.run([sys.executable, "-m", "step6_evaluation.split_guard", "check", "--train", *map(str, train),
                           "--eval", *map(str, eval_)], cwd=ROOT, capture_output=True, text=True)


def test_split_guard_finds_no_overlap_between_splits(built):
    r = _guard([built["train"] / "cases.jsonl", built["dev"] / "cases.jsonl"],
               [built["eval_id"] / "cases.jsonl", built["eval_ood_template"] / "cases.jsonl"])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "OK: 0/80" in r.stdout
    r = _guard([built["train"] / "cases.jsonl"], [built["dev"] / "cases.jsonl"])
    assert r.returncode == 0, r.stdout


def test_split_guard_positive_control(built, tmp_path):
    """A leaked eval case inside the training file is caught."""
    leaked = tmp_path / "leaky_train.jsonl"
    ev_line = (built["eval_id"] / "cases.jsonl").read_text(encoding="utf-8").splitlines()[3]
    leaked.write_text((built["train"] / "cases.jsonl").read_text(encoding="utf-8") + ev_line + "\n", encoding="utf-8")
    r = _guard([leaked], [built["eval_id"] / "cases.jsonl"])
    assert r.returncode == 1 and "CONTAMINATION" in r.stdout


def test_build_aborts_on_frozen_eval_overlap(built, tmp_path, monkeypatch):
    """With a frozen eval manifest present, a train build that contains an eval packet is refused."""
    from step6_evaluation import split_guard as SG
    frozen = tmp_path / "repo" / "data" / "eval_id"
    frozen.mkdir(parents=True)
    dev_cases = (built["dev"] / "cases.jsonl").read_text(encoding="utf-8")
    (frozen / "cases.jsonl").write_text(dev_cases, encoding="utf-8")
    SG.freeze([str(frozen / "cases.jsonl")], frozen / "MANIFEST.json")
    files = B._frozen_eval_files(tmp_path / "repo")
    assert files and Path(files[0]).exists()
    monkeypatch.setattr(B, "_frozen_eval_files", lambda root: files)
    with pytest.raises(SystemExit, match="split_guard"):
        B.build(CFG["dev"], 30, None, tmp_path / "dev_again")      # same seed -> same packets as the "eval" file
    m = B.build(CFG["train"], 30, None, tmp_path / "train_ok")
    assert m["split_guard"]["contaminated_eval_records"] == 0
