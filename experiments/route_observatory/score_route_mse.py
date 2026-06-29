#!/usr/bin/env python3
"""score_route_mse.py — T3.2 (#423) the route-MSE scorer (the gated PLUMBING keystone).

Grade a recorded bot ATTEMPT trajectory against a #420 Route-Canon SEED line: resample BOTH
to a common grid and report the mean squared per-point L2 (+ RMSE, per-axis, xy/z splits) in
QUAKE UNITS (qu). This is the one number the owner watches for the T3.2 plumbing test — a
*plumbing* number (do the pipes carry a trajectory and a score come out), NOT a quality verdict
and NOT the rigorous variable-dt alignment (that is #428 / T5.2).

Pure STDLIB (math/json/argparse only) so it runs in the merge-gating floor with no numpy/duckdb/
torch. The arc-fraction resample is the 3-D extension of
`experiments/route_observatory/route_canon_band.py:_resample_xy` (mirrored, NOT imported, to keep
this tool dependency-free).

GROUND TRUTH: `data/catalog/route_canon.dm3.json` — `highways[].segments[].trajectory = [[t,x,y,z],
...]`. A highway's segments are concatenated IN ORDER (a teleport chain has >1 segment; the seed
line is the joined runs).

ATTEMPT: a JSON file holding `[[t,x,y,z], ...]` (or `{"trajectory": [...]}`). The MVD-extraction
path that produces it (`qw-analyze -view full -include positions,view,velocity` -> per-tick xyz, in
QU) is documented in `experiments/ktx_moveprobe/T3.2_PLUMBING.md`; this tool stays stdlib and takes
the already-extracted JSON.

Usage:
  score_route_mse.py --canon data/catalog/route_canon.dm3.json --highway <id> \
      --attempt <traj.json> [--grid arclen|time] -o <out.json>
"""
import argparse
import json
import logging
import math
import sys

LOGGER = logging.getLogger(__name__)

SCHEMA = "komodobots.route_mse.v1"
GRID_N = 64                 # common resample point count (mirrors route_canon_band CORRIDOR_M)


def _read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.loads(fh.read())

# Unit-consistency guard (P1): the QW wire scale is EXACTLY 8x qu, so a raw-1/8-qu attempt has
# coordinate MAGNITUDES ~8x the (committed-qu) seed's. Guard ONE-DIRECTIONALLY on max-absolute
# coordinate: raise only when the attempt is implausibly LARGER than the seed (>= this ratio, toward
# the 8x wire scale) — NEVER when it is smaller. A stalled/low-progress same-unit attempt (the
# expected D3 case: the frozen 6-feat mover covers only a short fraction of the long seed) keeps its
# coordinates WITHIN the seed's range, so it must SCORE, not raise. Map-agnostic (relative to the
# seed; no hardcoded bounds). 4x sits between same-scale (~1x) and the 8x wire scale.
UNIT_GUARD_RATIO = 4.0

_SCORING_NOTE = (
    "Minimal honest plumbing MSE: resample BOTH trajectories to a common arc-fraction grid, "
    "mean of squared per-point L2 over (x,y,z) in QUAKE UNITS (qu). Arc-fraction makes this "
    "PATH-SHAPE only -- BLIND to speed/timing (two runs of the same path at different speeds "
    "score ~0); use --grid time for timing-sensitive scoring. NOT the rigorous variable-dt "
    "alignment -- #428 (T5.2) owns that. Scored vs ONE human SEED line (#420), not the band "
    "(#421, a Phase-1 M2 artifact whose believability-envelope use is a later concern). "
    "A plumbing number, not a quality verdict."
)
_MATCH_NOTE = (
    "highway_id is passed in (the live run knows which highway it drove) -- NEVER auto-matched "
    "by (from,to) resource pair (#421 _match_key / move_highway.h)."
)


def load_highway_seed(canon, highway_id):
    """Return (seed_xyz, meta) for the named highway: its segments[].trajectory concatenated IN
    ORDER as [(x,y,z), ...] (qu), plus provenance meta. Raises SystemExit on an unknown id."""
    by_id = {h["id"]: h for h in canon["highways"]}
    if highway_id not in by_id:
        raise SystemExit(
            f"highway {highway_id!r} not in canon (have: {', '.join(sorted(by_id))})")
    h = by_id[highway_id]
    seed_xyz = []
    for seg in h["segments"]:
        for p in seg["trajectory"]:            # rows are [t, x, y, z]
            seed_xyz.append((float(p[1]), float(p[2]), float(p[3])))
    meta = {
        "demo": h["seed"]["demo"], "player": h["seed"]["player"],
        "label": h.get("label"), "route_class": h.get("route_class"),
        "from_resource": h.get("from_resource"), "to_resource": h.get("to_resource"),
        "n_segments": len(h["segments"]),
    }
    return seed_xyz, meta


def load_attempt(path):
    """Load an attempt trajectory JSON -> [(x,y,z), ...] (qu). Accepts a bare [[t,x,y,z],...]
    list or a {"trajectory": [...]} wrapper. Raises SystemExit on empty / <2 points / bad rows."""
    doc = _read_json(path)
    rows = doc["trajectory"] if isinstance(doc, dict) else doc
    if not isinstance(rows, list) or len(rows) < 2:
        raise SystemExit(
            f"attempt {path!r}: need a trajectory of >= 2 [t,x,y,z] points, got "
            f"{len(rows) if isinstance(rows, list) else type(rows).__name__}")
    out = []
    for p in rows:
        if not isinstance(p, (list, tuple)) or len(p) < 4:
            raise SystemExit(f"attempt {path!r}: each row must be [t,x,y,z], got {p!r}")
        out.append((float(p[1]), float(p[2]), float(p[3])))
    return out, rows


def _cum_arclen(pts):
    """Cumulative 3-D path length at each point: [0, d01, d01+d12, ...] (len == len(pts))."""
    cum = [0.0]
    for i in range(1, len(pts)):
        (x0, y0, z0), (x1, y1, z1) = pts[i - 1], pts[i]
        cum.append(cum[-1] + math.sqrt((x1 - x0) ** 2 + (y1 - y0) ** 2 + (z1 - z0) ** 2))
    return cum


def _interp_at(pts, keys, u):
    """The (x,y,z) point at normalized parameter u in [0,1] along the polyline `pts`, where
    `keys` is the monotonic per-point parameter NORMALIZED to [0,1]. Linear interpolation;
    endpoints are inclusive (u<=0 -> first point, u>=1 -> last)."""
    n = len(pts)
    if u <= keys[0]:
        seg, f = 0, 0.0
    elif u >= keys[-1]:
        seg, f = n - 2, 1.0
    else:
        seg = 0
        while seg < n - 2 and keys[seg + 1] < u:
            seg += 1
        k0, k1 = keys[seg], keys[seg + 1]
        f = (u - k0) / (k1 - k0) if k1 > k0 else 0.0
    p0, p1 = pts[seg], pts[seg + 1]
    return tuple(p0[d] + f * (p1[d] - p0[d]) for d in range(3))


def resample(pts, ts, grid, m=GRID_N):
    """Resample pts=[(x,y,z),...] to m points evenly spaced over a normalized parameter.

    grid='arclen' -> the parameter is the cumulative 3-D arc length (path-shape alignment,
    speed/timing-blind; the duration/tick-rate-robust default). grid='time' -> the parameter is
    the trajectory's own t column (timing-sensitive). Both normalize the parameter to [0,1], so
    unequal absolute durations/lengths don't bias the per-point error. The 3-D extension of
    route_canon_band._resample_xy."""
    n = len(pts)
    if n == 1:
        return [tuple(pts[0])] * m
    raw = _cum_arclen(pts) if grid == "arclen" else list(ts)
    lo, hi = raw[0], raw[-1]
    span = hi - lo
    if span <= 0:                          # zero length / zero or non-monotonic time -> index grid
        raw, lo, span = list(range(n)), 0, float(n - 1)
    keys = [(k - lo) / span for k in raw]
    return [_interp_at(pts, keys, s / (m - 1)) for s in range(m)]


def _max_abs_coord(pts):
    """Largest absolute (x,y,z) coordinate over the trajectory — a units-scale MAGNITUDE proxy,
    robust to a near-zero axis (unlike a per-axis span)."""
    return max(max(abs(p[0]), abs(p[1]), abs(p[2])) for p in pts)


def unit_guard(seed_xyz, attempt_xyz):
    """P1 unit-consistency guard: fail loudly ONLY when the ATTEMPT's coordinate magnitude is
    implausibly LARGER than the (committed-qu) SEED's (>= UNIT_GUARD_RATIO x, toward the 8x
    qu<->1/8-qu wire scale) — i.e. the attempt looks like raw 1/8-qu. A SMALLER attempt is a
    legitimate low-progress/stalled run (the D3 case where the frozen 6-feat mover barely moves),
    NOT a unit error, and is never rejected. Both inputs MUST be in qu."""
    seed_mag = _max_abs_coord(seed_xyz)
    att_mag = _max_abs_coord(attempt_xyz)
    if seed_mag <= 1e-6:
        return                                  # degenerate near-origin seed; let MSE speak
    if att_mag >= UNIT_GUARD_RATIO * seed_mag:
        raise SystemExit(
            f"unit mismatch: attempt max|coord| {att_mag:.0f} is {att_mag / seed_mag:.1f}x the "
            f"seed's {seed_mag:.0f} (~ the 8x qu<->1/8-qu wire scale). Both trajectories must be in "
            f"QUAKE UNITS (qu); the attempt looks like raw 1/8-qu. Re-extract in qu "
            f"(see experiments/ktx_moveprobe/T3.2_PLUMBING.md).")


def score(seed_xyz, attempt_xyz, grid, seed_ts, attempt_ts, m=GRID_N):
    """Resample both to a common grid and compute the MSE/RMSE family over (x,y,z) in qu."""
    a = resample(seed_xyz, seed_ts, grid, m)
    b = resample(attempt_xyz, attempt_ts, grid, m)
    dx = [a[k][0] - b[k][0] for k in range(m)]
    dy = [a[k][1] - b[k][1] for k in range(m)]
    dz = [a[k][2] - b[k][2] for k in range(m)]
    pa = {"x": sum(v * v for v in dx) / m,
          "y": sum(v * v for v in dy) / m,
          "z": sum(v * v for v in dz) / m}
    mse_xyz = pa["x"] + pa["y"] + pa["z"]      # mean of squared L2 == sum of per-axis mean-sq
    return {
        "mse_xyz": mse_xyz, "rmse_xyz": math.sqrt(mse_xyz),
        "rmse_xy": math.sqrt(pa["x"] + pa["y"]), "rmse_z": math.sqrt(pa["z"]),
        "per_axis_mse": pa,
    }


def build_artifact(highway_id, seed_xyz, seed_meta, attempt_xyz, attempt_src, grid,
                   seed_ts, attempt_ts, map_name="dm3", m=GRID_N):
    unit_guard(seed_xyz, attempt_xyz)
    s = score(seed_xyz, attempt_xyz, grid, seed_ts, attempt_ts, m)
    return {
        "schema": SCHEMA, "map": map_name, "highway_id": highway_id,
        "ground_truth": {"source": "route_canon.dm3.json", "seed": seed_meta,
                         "n_pts": len(seed_xyz)},
        "attempt": {"source": attempt_src, "n_pts": len(attempt_xyz)},
        "grid": {"kind": grid, "n": m},
        "mse_xyz": s["mse_xyz"], "rmse_xyz": s["rmse_xyz"],
        "rmse_xy": s["rmse_xy"], "rmse_z": s["rmse_z"],
        "per_axis_mse": s["per_axis_mse"],
        "_scoring": _SCORING_NOTE, "_match": _MATCH_NOTE,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="T3.2 route-MSE scorer (attempt vs #420 seed line)")
    ap.add_argument("--canon", required=True, help="route_canon.dm3.json")
    ap.add_argument("--highway", required=True, help="highway id the bot drove (EXPLICIT)")
    ap.add_argument("--attempt", required=True, help="attempt trajectory JSON ([[t,x,y,z],...])")
    ap.add_argument("--grid", choices=("arclen", "time"), default="arclen",
                    help="arclen = arc-fraction (path-shape, speed-blind; default); "
                         "time = the t column (timing-sensitive)")
    ap.add_argument("-o", "--out", required=True, help="output route_mse.v1 JSON")
    args = ap.parse_args(argv)

    canon = _read_json(args.canon)
    seed_xyz, seed_meta = load_highway_seed(canon, args.highway)
    attempt_xyz, attempt_rows = load_attempt(args.attempt)
    seed_ts = [float(p[0]) for h in canon["highways"] if h["id"] == args.highway
               for seg in h["segments"] for p in seg["trajectory"]]
    attempt_ts = [float(p[0]) for p in attempt_rows]

    art = build_artifact(args.highway, seed_xyz, seed_meta, attempt_xyz, args.attempt,
                         args.grid, seed_ts, attempt_ts, map_name=canon.get("map", "dm3"))
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(art, indent=1) + "\n")
    summary = (f"{args.highway} rmse_xyz={art['rmse_xyz']:.1f} rmse_xy={art['rmse_xy']:.1f} "
               f"rmse_z={art['rmse_z']:.1f} n={art['grid']['n']} grid={args.grid} "
               f"(seed {art['ground_truth']['n_pts']}pts vs attempt {art['attempt']['n_pts']}pts)")
    LOGGER.info("route-mse: %s", summary)
    print("WROTE " + args.out + "  " + summary)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    raise SystemExit(main())
