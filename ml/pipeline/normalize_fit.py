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
from pathlib import Path


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


def robust_spec(values, clip=None) -> dict:
    """Exact median + IQR (q75-q25) of a value stream, for a `robust` feature.

    Streams into a list and sorts — fine for the per-map velocity/speed columns of a
    bounded catalog slice. A production fit over the full silver corpus would use a
    streaming quantile sketch (t-digest) in the heavy path; the artifact shape is
    identical either way.
    """
    xs = sorted(float(v) for v in values)
    n = len(xs)

    def _quantile(q: float) -> float:
        if n == 0:
            return 0.0
        if n == 1:
            return xs[0]
        pos = q * (n - 1)
        lo = int(math.floor(pos))
        hi = min(lo + 1, n - 1)
        frac = pos - lo
        return xs[lo] * (1.0 - frac) + xs[hi] * frac

    median = _quantile(0.5)
    iqr = _quantile(0.75) - _quantile(0.25)
    s = {"method": "robust", "median": median, "iqr": iqr, "computed_from": {"n": n}}
    if clip is not None:
        s["clip"] = clip
    return s


# --- train-only catalog fit ---------------------------------------------------
# The per-map velocity zscore keys (vel_x/y/z) are fitted here; the agent_observation
# transform REUSES them for the egocentric entity_rel_vel_* channels (no separate
# fitted key — feature_registry.yaml). hspeed is robust. Position is the static map
# AABB (minmax), not fitted from data, so it is carried from the template/maps.v1.
# yaw_rate (the turn-direction signal) is zscore, fitted from consecutive-tick view-yaw
# deltas using the SAME AO.yaw_rate_degps the build + inference call (so the fitted
# mean/std match the exact values self_features later z-scores).
_VEL_CLIP = {"vel_x": [-2500.0, 2500.0], "vel_y": [-2500.0, 2500.0], "vel_z": [-1000.0, 1000.0]}
_HSPEED_CLIP = [0.0, 2500.0]
# yaw_rate clip (deg/s): a single ~13ms frame rarely turns more than ~half a circle, so
# +-1500 deg/s bounds physical mouse turns while clipping the rare wrap/teleport spike.
_YAW_RATE_CLIP = [-1500.0, 1500.0]
# fallback per-tick frame time (ms) for yaw_rate when a player_ticks row has no msec —
# mirrors build_features.FRAME_DT_MS (the recorded ~13ms QW tick cadence).
_FRAME_DT_MS = 13.0


def _yaw_rate_helper():
    """Resolve the SHARED agent_observation.yaw_rate_degps (the build + inference helper)
    so the fit computes yaw_rate identically. Adds the in-tree scripts/ dir to sys.path
    (the same shared package build_features imports). Lazy so the module stays import-light
    and degrades gracefully if the layout is unusual."""
    import sys
    from pathlib import Path
    scripts = Path(__file__).resolve().parents[2] / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    from features.agent_observation import yaw_rate_degps  # noqa: E402  (shared, stdlib)
    return yaw_rate_degps


def fit_from_catalog(sqlite_path, split: str = "train", map_name: str = "dm3") -> dict:
    """Fit per-map velocity (zscore) + hspeed (robust) + yaw_rate (zscore) stats from the
    catalog, streaming ONLY the rows whose episode is in `split` (default 'train') — the
    train-only normalization contract. Reads player_ticks (the ego self spine) joined to
    episodes for the split filter.

    Returns {map_name: {"vel_x":spec, "vel_y":spec, "vel_z":spec, "hspeed":spec,
    "yaw_rate":spec}} plus the row count it fitted on. sqlite3 is stdlib; this stays
    import-light, but lives in ml/ because it is the *fitting* side (the applying side
    is scripts/features). yaw_rate is computed per-episode from CONSECUTIVE-tick yaw via
    the shared helper, so its fitted mean/std match what self_features normalizes."""
    import sqlite3

    con = sqlite3.connect(str(sqlite_path))
    try:
        rows = con.execute(
            """SELECT pt.vx, pt.vy, pt.vz, pt.hspeed
                 FROM player_ticks pt
                 JOIN episodes e USING(episode_id)
                WHERE e.split = ?""",
            (split,),
        ).fetchall()
        # yaw_rate spine: episode-ordered (episode, tick) so consecutive rows of one
        # episode are adjacent — the SAME ordering build_features._load_episode_ticks uses.
        yaw_rows = con.execute(
            """SELECT e.episode_id, pt.tick, pt.yaw, pt.msec
                 FROM player_ticks pt
                 JOIN episodes e USING(episode_id)
                WHERE e.split = ?
                ORDER BY e.episode_id, pt.tick""",
            (split,),
        ).fetchall()
    finally:
        con.close()

    wx, wy, wz = Welford(), Welford(), Welford()
    hspeeds = []
    for vx, vy, vz, hsp in rows:
        if vx is not None:
            wx.update(float(vx))
        if vy is not None:
            wy.update(float(vy))
        if vz is not None:
            wz.update(float(vz))
        if hsp is not None:
            hspeeds.append(float(hsp))

    # yaw_rate (zscore): per-episode consecutive-tick turn rate via the SHARED helper.
    # prev_yaw resets at each new episode (first tick -> rate 0.0, the build's convention);
    # the first-tick zeros ARE fed (every tick the build emits is normalized) so the fit
    # distribution matches inference exactly.
    yrd = _yaw_rate_helper()
    wyr = Welford()
    prev_yaw = None
    prev_eid = None
    for eid, _tick, yaw, msec in yaw_rows:
        if eid != prev_eid:
            prev_yaw = None             # new episode -> no previous yaw
            prev_eid = eid
        if yaw is None:
            continue
        dt_s = (float(msec) if msec else _FRAME_DT_MS) / 1000.0
        wyr.update(yrd(float(yaw), prev_yaw, dt_s))
        prev_yaw = float(yaw)

    feats = {
        "vel_x": wx.zscore_spec(clip=_VEL_CLIP["vel_x"]),
        "vel_y": wy.zscore_spec(clip=_VEL_CLIP["vel_y"]),
        "vel_z": wz.zscore_spec(clip=_VEL_CLIP["vel_z"]),
        "hspeed": robust_spec(hspeeds, clip=_HSPEED_CLIP),
        "yaw_rate": wyr.zscore_spec(clip=_YAW_RATE_CLIP),
    }
    return {"map": map_name, "n_rows": len(rows), "feats": feats}


# Static map AABB (qu) -> position minmax specs (from maps.v1; NOT fitted from data).
_POS_AABB = {
    "dm3": {"pos_x": (-984.0, 2048.0), "pos_y": (-960.0, 1136.0), "pos_z": (-416.0, 496.0)},
}


def write_stats(per_map_fits: dict, out_path, **meta) -> None:
    """Assemble a normalization_stats.json from fitted Welford accumulators.

    `per_map_fits[map]` is a dict of feature_key -> a fully-formed spec dict (e.g. from
    Welford.zscore_spec / robust_spec / fit_from_catalog). `computed_from` is stamped
    onto the doc so the train-only provenance is auditable.
    """
    doc = {
        "schema": "komodobots.normalization_stats.v1",
        "artifact_version": meta.get("artifact_version", "0.0.0-fit"),
        # registry_version 3: the fit emits the per_map yaw_rate key the v3 SELF path
        # requires (REQUIRED_NORM_KEYS), so the artifact this writer produces IS a v3
        # artifact — stamp it so shard_contract.check_norm_artifact accepts it (and a
        # stale v2 stamp would be rejected loudly).
        "registry_version": 3,
        "computed_from": meta.get("computed_from", "train"),
        "split_def": meta.get("split_def", "group_by_demo_id"),
        "fitted_on": meta.get("fitted_on", "UNSET"),
        "git_sha": meta.get("git_sha", "UNSET"),
        "dataset_version": meta.get("dataset_version", "UNSET"),
        "computed_with": {"algorithm": "welford_online + chan_parallel_merge", "ddof": 0},
        "constants": {"map_diagonal": meta.get("map_diagonal", {"dm3": 3797.1})},
        "per_map": {m: {k: w for k, w in feats.items()} for m, feats in per_map_fits.items()},
        "sincos": ["yaw", "pitch", "vel_heading", "rel_bearing", "rel_pitch"],
        "divide_period": {"health": 250.0, "armor": 200.0},
    }
    from pathlib import Path
    Path(out_path).write_text(json.dumps(doc, indent=2, sort_keys=True), encoding="utf-8")
    return doc


def fit_stats_doc(sqlite_path, out_path, split: str = "train", map_name: str = "dm3", **meta) -> dict:
    """End-to-end train-only fit -> frozen normalization_stats.json. Combines the
    fitted per-map velocity/hspeed (from the `split` rows) with the static position
    AABB, then writes the artifact. Returns the written doc."""
    fit = fit_from_catalog(sqlite_path, split=split, map_name=map_name)
    feats = dict(fit["feats"])
    aabb = _POS_AABB.get(map_name, _POS_AABB["dm3"])
    for key, (lo, hi) in aabb.items():
        feats[key] = {"method": "minmax", "min": lo, "max": hi,
                      "computed_from": {"source": "maps.v1 AABB"}, "clip": [lo, hi]}
    meta.setdefault("computed_from", split)
    meta.setdefault("fitted_on", f"{split}_split:{Path(str(sqlite_path)).name}")
    doc = write_stats({map_name: feats}, out_path, **meta)
    doc["_fit_n_rows"] = fit["n_rows"]
    return doc


if __name__ == "__main__":
    import argparse
    from pathlib import Path

    ap = argparse.ArgumentParser(description="Fit train-only normalization_stats.json from a catalog")
    ap.add_argument("--db", type=Path, required=True, help="catalog .sqlite")
    ap.add_argument("--out", type=Path, required=True, help="output normalization_stats.json")
    ap.add_argument("--split", default="train")
    ap.add_argument("--map", default="dm3")
    ap.add_argument("--artifact-version", default="0.3.0-v3fit")
    args = ap.parse_args()
    d = fit_stats_doc(args.db, args.out, split=args.split, map_name=args.map,
                      artifact_version=args.artifact_version)
    print(json.dumps({"out": str(args.out), "computed_from": d["computed_from"],
                      "n_rows": d["_fit_n_rows"],
                      "vel_x": d["per_map"][args.map]["vel_x"]}, indent=2))
