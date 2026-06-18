"""normalize_fit.py — fit the frozen normalization artifact (D2). WSL2 / ml venv only.

Streams the TRAIN split with Welford (online mean/std) and Chan parallel-merge across
shards, then writes a normalization_stats.json that scripts/features reads byte-identically
at val/test/inference. ddof=0 (population std) to match sklearn StandardScaler.

This is the *fitting* side; the *applying* side is the shared stdlib scripts/features.
Kept in ml/ because production fits stream large Parquet corpora (numpy/pyarrow), but the
Welford core below is dependency-free so the unit-style smoke test can exercise it.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field


@dataclass
class Welford:
    """Online mean/variance (Welford). Mergeable via Chan's parallel algorithm."""
    n: int = 0
    mean: float = 0.0
    m2: float = 0.0
    lo: float = field(default=math.inf)
    hi: float = field(default=-math.inf)

    def update(self, x: float) -> None:
        self.n += 1
        d = x - self.mean
        self.mean += d / self.n
        self.m2 += d * (x - self.mean)
        if x < self.lo:
            self.lo = x
        if x > self.hi:
            self.hi = x

    def merge(self, other: "Welford") -> "Welford":
        if other.n == 0:
            return self
        if self.n == 0:
            return other
        n = self.n + other.n
        delta = other.mean - self.mean
        mean = self.mean + delta * other.n / n
        m2 = self.m2 + other.m2 + delta * delta * self.n * other.n / n
        return Welford(n=n, mean=mean, m2=m2, lo=min(self.lo, other.lo), hi=max(self.hi, other.hi))

    @property
    def std(self) -> float:
        return math.sqrt(self.m2 / self.n) if self.n > 0 else 0.0

    def zscore_spec(self, clip=None) -> dict:
        s = {"method": "zscore", "mean": self.mean, "std": self.std,
             "computed_from": {"n": self.n}}
        if clip is not None:
            s["clip"] = clip
        return s

    def minmax_spec(self, clip=None) -> dict:
        s = {"method": "minmax", "min": self.lo, "max": self.hi,
             "computed_from": {"n": self.n}}
        if clip is not None:
            s["clip"] = clip
        return s


def fit_feature(values) -> Welford:
    w = Welford()
    for v in values:
        w.update(float(v))
    return w


def write_stats(per_map_fits: dict, out_path, **meta) -> None:
    """Assemble a normalization_stats.json from fitted Welford accumulators."""
    doc = {
        "schema": "komodobots.normalization_stats.v1",
        "artifact_version": meta.get("artifact_version", "0.0.0-fit"),
        "registry_version": 2,
        "fitted_on": meta.get("fitted_on", "UNSET"),
        "computed_with": {"algorithm": "welford_online + chan_parallel_merge", "ddof": 0},
        "per_map": {m: {k: w for k, w in feats.items()} for m, feats in per_map_fits.items()},
    }
    from pathlib import Path
    Path(out_path).write_text(json.dumps(doc, indent=2), encoding="utf-8")
