"""Generator config (v1): one YAML file per split under ``step1_data_generation/configs/``.

A config says *how* to sample (seed range, entity partition, nationality
pools, layout families, noise switches, injection pool, off-by-default
augmentation). It never says what the right answer is: labels still come
from ``step1_data_generation/project.py``.

    from step1_data_generation.config import load_config
    cfg = load_config("step1_data_generation/configs/train.yaml")

``GenConfig()`` with no arguments is the v1 default used by
``step1_data_generation.sample.sample_cases`` when no config is passed (A's draft behaviour
plus the wave-2 fixes, with no entity partition).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, fields
from datetime import date
from pathlib import Path
from typing import Any

import yaml

SEEN_STYLES = ("kv", "form", "prose", "mixed")
HELDOUT_STYLES = ("email", "ocr_dump")
SPLITS = ("train", "dev", "eval_id", "eval_ood_template", "eval_hard", "pilot", "draft")
EVAL_SPLITS = ("eval_id", "eval_ood_template", "eval_hard")


class Partition:
    """Stable hash partition of reusable entities: an item belongs to this
    split iff ``sha256(pool:item) mod modulus`` is in ``buckets``.
    ``Partition(None)`` accepts everything."""

    def __init__(self, buckets: list[int] | None, modulus: int = 10):
        self.buckets = None if buckets is None else frozenset(buckets)
        self.modulus = modulus

    @staticmethod
    def bucket(pool: str, item: str, modulus: int = 10) -> int:
        h = hashlib.sha256(f"{pool}:{item.casefold()}".encode("utf-8")).hexdigest()
        return int(h[:12], 16) % modulus

    def ok(self, pool: str, item: str) -> bool:
        return self.buckets is None or self.bucket(pool, item, self.modulus) in self.buckets


@dataclass
class GenConfig:
    config_id: str = "v1-default"
    split: str = "draft"
    case_id_prefix: str = "draft"
    seed_range: tuple[int, int] | None = None        # inclusive; every case seed must fall inside
    default_seed: int = 20261017
    partition_buckets: list[int] | None = None       # None = no entity partition
    partition_modulus: int = 10
    nationality_pools: dict[str, list[str]] | None = None   # origin -> ISO3 list; None = step1_data_generation.lib.names default
    styles: dict[str, float] = field(default_factory=lambda: {s: 1.0 for s in SEEN_STYLES})
    mix: dict[str, float] | None = None              # None = step1_data_generation.sample.DEFAULT_MIX
    p_secondary: float = 0.25
    p_tertiary: float = 0.0                          # eval_hard: chance of a THIRD stacked difficulty (0 = off, RNG untouched)
    ocr_scale: float = 1.0                           # eval_hard: multiplies ID-document OCR noise (1.0 = unchanged)
    as_of_range: tuple[date, date] = (date(2026, 1, 5), date(2026, 10, 9))
    as_of_lag_days: tuple[int, int] = (0, 0)         # application_date = as_of_date - lag
    plausibility: bool = True                        # age/occupation, issuer/nationality, residence/onboarding
    ocr_digit_to_digit_in_numeric: bool = True       # may OCR noise turn one digit into another inside a numeric MRZ field?
    injection_pool: list[list[str]] | None = None    # [technique, target, text]; None = step1_data_generation.sample.INJECTIONS
    twins: dict[str, Any] = field(default_factory=lambda: {"enabled": False})
    knockout: dict[str, Any] = field(default_factory=lambda: {"enabled": False})
    notes: str = ""
    source_path: str | None = None
    source_sha256: str | None = None

    def __post_init__(self):
        if self.split not in SPLITS:
            raise ValueError(f"unknown split {self.split!r}; expected one of {SPLITS}")
        if self.seed_range is not None:
            self.seed_range = (int(self.seed_range[0]), int(self.seed_range[1]))
        self.as_of_range = tuple(d if isinstance(d, date) else date.fromisoformat(str(d)) for d in self.as_of_range)
        self.as_of_lag_days = (int(self.as_of_lag_days[0]), int(self.as_of_lag_days[1]))
        unknown = set(self.styles) - set(SEEN_STYLES) - set(HELDOUT_STYLES)
        if unknown:
            raise ValueError(f"unknown styles {sorted(unknown)}")
        if self.split in ("train", "dev") and set(self.styles) & set(HELDOUT_STYLES):
            raise ValueError(f"held-out layout families {HELDOUT_STYLES} may not be used in {self.split}")
        if self.split in EVAL_SPLITS and (self.twins.get("enabled") or self.knockout.get("enabled")):
            raise ValueError("twins/knockout augmentation is train-side only")

    @property
    def partition(self) -> Partition:
        return Partition(self.partition_buckets, self.partition_modulus)

    def check_seed(self, seed: int, n: int = 1) -> None:
        """Assert that seeds ``seed .. seed+n-1`` fall in this split's range."""
        if self.seed_range is None:
            return
        lo, hi = self.seed_range
        if not (lo <= seed and seed + max(n, 1) - 1 <= hi):
            raise ValueError(f"seeds {seed}..{seed + n - 1} fall outside the {self.split} range {lo}..{hi}")

    def to_dict(self) -> dict:
        d = {f.name: getattr(self, f.name) for f in fields(self)}
        d["as_of_range"] = [x.isoformat() for x in self.as_of_range]
        d["as_of_lag_days"] = list(self.as_of_lag_days)
        d["seed_range"] = list(self.seed_range) if self.seed_range else None
        return d


def load_config(path: str | Path) -> GenConfig:
    p = Path(path)
    raw = p.read_bytes()
    d = yaml.safe_load(raw.decode("utf-8")) or {}
    known = {f.name for f in fields(GenConfig)}
    bad = set(d) - known
    if bad:
        raise ValueError(f"{p}: unknown config keys {sorted(bad)}")
    d["source_path"] = str(p)
    d["source_sha256"] = hashlib.sha256(raw).hexdigest()
    return GenConfig(**d)
