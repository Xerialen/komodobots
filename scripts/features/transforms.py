"""Per-feature normalization transforms (C3).

Methods mirror normalization_stats.json exactly:
    zscore{mean,std} | minmax{min,max} | robust{median,iqr} |
    log1p_zscore{mean,std} | sincos{} | divide_period{period} | identity{}
`clip` (when present in a spec) is applied BEFORE the transform.

Every function is pure and deterministic. Zero-denominator guards return 0.0 for the
scale term so a degenerate (constant) feature maps to its centered value, never NaN/inf.
"""
from __future__ import annotations

import logging
import math


LOGGER = logging.getLogger(__name__)
_EPS = 1e-12


def apply_clip(x: float, clip):
    """Clamp x to [clip[0], clip[1]] if clip is a 2-list, else return x."""
    if not clip:
        return x
    lo, hi = clip
    if lo is not None and x < lo:
        return lo
    if hi is not None and x > hi:
        return hi
    return x


def zscore(x: float, mean: float, std: float) -> float:
    return (x - mean) / std if abs(std) > _EPS else 0.0


def minmax(x: float, lo: float, hi: float) -> float:
    """Map [lo,hi] -> [0,1]. Constant range -> 0.0."""
    span = hi - lo
    return (x - lo) / span if abs(span) > _EPS else 0.0


def robust(x: float, median: float, iqr: float) -> float:
    return (x - median) / iqr if abs(iqr) > _EPS else 0.0


def log1p_zscore(x: float, mean: float, std: float) -> float:
    """z-score of log1p(x). x must be >= -1 (clip to >=0 upstream)."""
    return zscore(math.log1p(max(x, 0.0)), mean, std)


def divide_period(x: float, period: float) -> float:
    return x / period if abs(period) > _EPS else 0.0


def identity(x: float) -> float:
    return x


def sincos(angle_deg: float) -> tuple[float, float]:
    """Encode an angle (degrees) as (sin, cos) of radians — continuous across the
    0/360 wrap, the only correct encoding for cyclic quantities (yaw, bearing, ...)."""
    r = math.radians(angle_deg)
    return (math.sin(r), math.cos(r))


_SCALAR = {"zscore", "minmax", "robust", "log1p_zscore", "divide_period", "identity"}


def normalize(value: float, spec: dict):
    """Dispatch on spec['method'], applying spec['clip'] first.

    Returns a float for scalar methods, or a (sin, cos) tuple for 'sincos'.
    Raises KeyError/ValueError on an unknown or under-specified method so a
    malformed stats artifact fails loudly rather than silently mis-normalizing.
    """
    method = spec["method"]
    if method == "sincos":
        return sincos(value)  # parameter-free; clip is meaningless for an angle
    x = apply_clip(value, spec.get("clip"))
    if method == "zscore":
        return zscore(x, spec["mean"], spec["std"])
    if method == "minmax":
        return minmax(x, spec["min"], spec["max"])
    if method == "robust":
        return robust(x, spec["median"], spec["iqr"])
    if method == "log1p_zscore":
        return log1p_zscore(x, spec["mean"], spec["std"])
    if method == "divide_period":
        return divide_period(x, spec["period"])
    if method == "identity":
        return identity(x)
    raise ValueError(f"unknown normalization method: {method!r}")
