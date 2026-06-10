#!/usr/bin/env python3
"""A4 #116 shared library — rung-1 (sng_shortcut2) lip measurement conventions.

ONE set of declared conventions, used by every A4 script (geometry / live /
sim / jump). Metric semantics are IMPORTED from route_metrics / verify_route /
mode23_sim — never re-implemented; the only new definitions here are the
rung-1 LIP-AREA criteria, declared below and in the report.

The censused rung-1 gap (census.json, route sng_shortcut2, its single hard
gap — also its FINAL hard gap, so route_metrics.final_hard_gap picks it):

    edge (-161.0, 728.8, 135.5)  ->  land (-291.2, 529.4, 135.5)
    span 238.2 qu, dz 0, required 437.0 (ballistic), human-at-edge 458.8
    void floor -16 (rest z 8..32 corridor floor below — recoverable, no pit)

Coordinate convention: all z values are PLAYER-ORIGIN resting heights (hull-1
floor space, the bsp_geom.floor_z convention): the launch ledge rests at
z=120, the lower approach steps at 56/72/88/104, the corridor floor below the
gap at 8..32, the landing strip at 120.

LIP-AREA criteria (A4-declared; the report discloses why verify_route's
reached_ledge is NOT reused for the share stat — its z > -30 guard was
designed for sng_to_rl where below-the-edge is the death pit at -168; on
rung 1 the corridor floor below the lip rests at z 8..32, so reached_ledge
counts a bot standing UNDER the lip):

  * LIP_Z_MIN = 96.0   — a row is "on the upper ledge level" iff z > 96
                         (above the 56/72/88 approach steps; the ledge rest
                         levels are 104/120 and jump arcs rise from there).
  * LIP_R    = 80.0    — "reached the lip" iff any upper-level row is within
                         80 qu horizontal of the census edge point.
  * NEAR_R   = 150.0   — the verify_route.classify() near-edge convention
                         (best grounded vh within 150 qu of the edge),
                         restricted to upper-level rows.

  * TAKEOFF-CAPABLE (the PRIMARY grounded convention, Codex PR #119 P2):
    haf < 4 (height_above_floor, the locked climb_detector grounded rule —
    the live trace onground flag is unreliable for bots and was audited
    strictly-conservative vs haf: 0 onground-only rows near the lip). Live
    rows carry haf from trace.csv; sim rows have no haf and fall back to
    the sim's own onground state (authoritative there — it is pmove state,
    not a logged flag). Both conventions are emitted side by side:
    takeoff_near_* (primary) and grounded_near_* (onground, secondary).

Attempt conditioning = the rung-A protocol of record (A1/A2): verify_route
segment_attempts -> legit_segment(rows, ()) (sng_shortcut2 sanctions no
teleporters; the stray-teleport guard is load-bearing, DO NOT weaken) ->
_truncate_at_arrival(REACH_RL=60) vs the route goal (-411.125, 498.0, 120.0).

Edge crossing = route_metrics.edge_speed(seg, RUNG-1 gap), A0 constants
UNCHANGED (corridor 160, z-window 100, eps 0.5, LAST crossing decides).
crossing_details() re-derives the same crossing geometrically for audit
columns (position / cross-track / time) and ASSERTS its vh equals the A0
metric's return — the imported metric stays authoritative.
"""

from __future__ import annotations

import csv
import importlib.util
import json
import math
import sys
from pathlib import Path

EXP = Path(__file__).resolve().parent
REPO = EXP.parents[1]
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))

from route_metrics import (  # noqa: E402
    EDGE_CORRIDOR, EDGE_CROSS_EPS, EDGE_Z_WINDOW, TELEPORT_JUMP,
    _truncate_at_arrival, edge_speed, final_hard_gap, legit_segment,
)

RUNS = REPO / "artifacts" / "lab-runs"
ROUTE_NAME = "sng_shortcut2"

# Rung-A directed-run protocol of record (mode23_sweep.RUNG_A).
SPAWN = (385.5, 614.25, 56.0)
GOAL_MARKER = 191
BUDGET_S = 48.1

# LIP-AREA criteria (declared above).
LIP_Z_MIN = 96.0
LIP_R = 80.0
NEAR_R = 150.0

REQUIRED = 437.0          # census required_speed at the launch edge
HUMAN_AT_EDGE = 458.8     # census human_speed_at_edge


_VR = None


def verify_route_mod():
    global _VR
    if _VR is None:
        spec = importlib.util.spec_from_file_location(
            "verify_route", SCRIPTS / "verify_route.py")
        _VR = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_VR)
    return _VR


def load_route():
    return verify_route_mod().load_route(ROUTE_NAME)


def rung1_gap(route=None):
    """The censused rung-1 gap dict (the route's final hard gap)."""
    route = route or load_route()
    return route["gap"]


def edge_point(gap):
    return tuple(float(v) for v in gap["edge"][:3])


def attempt_segments(rows, route):
    """Protocol-of-record conditioning: verify_route attempt segmentation,
    stray-teleport truncation, arrival truncation (REACH_RL=60)."""
    vr = verify_route_mod()
    out = []
    for s, e in vr.segment_attempts(rows, route):
        seg = legit_segment(rows[s:e], route["tele_entrances"])
        if len(seg) < 3:
            continue
        seg = _truncate_at_arrival(seg, vr.REACH_RL)
        out.append(seg)
    return out


def crossing_details(seg, gap):
    """Audit mirror of route_metrics.edge_speed: the LAST qualifying crossing
    with its position / cross-track / time. Geometry constants are IMPORTED
    from route_metrics; the caller must assert vh agreement with edge_speed.
    Returns None when no qualifying crossing exists."""
    ex, ey, ez = (float(v) for v in gap["edge"][:3])
    ux, uy = float(gap["land"][0]) - ex, float(gap["land"][1]) - ey
    norm = math.hypot(ux, uy)
    ux, uy = ux / norm, uy / norm

    def along(r):
        return (r["x"] - ex) * ux + (r["y"] - ey) * uy

    found = None
    for a, b in zip(seg, seg[1:]):
        if along(a) >= -EDGE_CROSS_EPS or along(b) < -EDGE_CROSS_EPS:
            continue
        step = math.hypot(b["x"] - a["x"], b["y"] - a["y"]) + abs(b["z"] - a["z"])
        if step > TELEPORT_JUMP:
            continue
        cross = abs((b["y"] - ey) * ux - (b["x"] - ex) * uy)
        if cross > EDGE_CORRIDOR or abs(b["z"] - ez) > EDGE_Z_WINDOW:
            continue
        found = {"vh": round(float(b["vh"]), 1), "t": b["t"],
                 "x": round(b["x"], 1), "y": round(b["y"], 1),
                 "z": round(b["z"], 1), "cross_track": round(cross, 1),
                 "edge_hdist": round(math.hypot(b["x"] - ex, b["y"] - ey), 1)}
    return found


def heading_at(seg, i):
    """Movement heading (deg) at row i from xy deltas (trace rows carry no
    velocity vector). Prefers the step leaving i; falls back to the step
    arriving at i; None when both are degenerate (< 0.5 qu)."""
    for a, b in ((i, i + 1), (i - 1, i)):
        if 0 <= a and b < len(seg):
            dx = seg[b]["x"] - seg[a]["x"]
            dy = seg[b]["y"] - seg[a]["y"]
            if math.hypot(dx, dy) >= 0.5:
                return math.degrees(math.atan2(dy, dx))
    return None


def takeoff_capable(row):
    """PRIMARY grounded convention: haf < 4 when the row carries
    height_above_floor (live trace.csv), else the row's onground state
    (sim rows — pmove state, authoritative). See module docstring."""
    haf = row.get("haf")
    if haf is not None:
        return haf < 4.0
    return bool(row.get("onground"))


def lip_attempt_metrics(seg, gap):
    """All A4 per-attempt lip measurements on one conditioned segment."""
    ex, ey, _ez = edge_point(gap)
    edge = edge_speed(seg, gap, ())             # the A0 metric (authoritative)
    det = crossing_details(seg, gap)
    if (edge is None) != (det is None):
        raise AssertionError("crossing_details disagrees with edge_speed presence")
    if det is not None and abs(det["vh"] - edge) > 0.05:
        raise AssertionError(f"crossing_details vh {det['vh']} != edge_speed {edge}")

    upper = [(i, r) for i, r in enumerate(seg) if r["z"] > LIP_Z_MIN]
    approach = None
    if upper:
        i, r = min(upper, key=lambda ir: math.hypot(ir[1]["x"] - ex, ir[1]["y"] - ey))
        hdg = heading_at(seg, i)
        approach = {"hdist": round(math.hypot(r["x"] - ex, r["y"] - ey), 1),
                    "vh": round(r["vh"], 1), "t": r["t"],
                    "x": round(r["x"], 1), "y": round(r["y"], 1),
                    "z": round(r["z"], 1),
                    "onground": int(r.get("onground", 0)),
                    "heading": None if hdg is None else round(hdg, 1)}
    in_near = [r for r in seg if r["z"] > LIP_Z_MIN
               and math.hypot(r["x"] - ex, r["y"] - ey) < NEAR_R]
    takeoff = [r["vh"] for r in in_near if takeoff_capable(r)]
    near = [r["vh"] for r in in_near if r.get("onground")]
    return {
        "edge": None if edge is None else round(edge, 1),
        "crossing": det,
        "lip_approach": approach,
        "reached_lip": bool(approach and approach["hdist"] < LIP_R),
        "takeoff_near_vh_max": round(max(takeoff), 1) if takeoff else None,
        "takeoff_near_n": len(takeoff),
        "grounded_near_vh_max": round(max(near), 1) if near else None,
        "grounded_near_n": len(near),
    }


def load_live_rows(run_id, route):
    """trace.csv -> metric rows, verify_route.load_trace convention
    (dist_goal vs the route goal)."""
    gx, gy, gz = route["goal"]
    rows = []
    with open(RUNS / run_id / "trace.csv", newline="") as fh:
        for r in csv.DictReader(fh):
            row = {"t": float(r["t"]), "x": float(r["x"]), "y": float(r["y"]),
                   "z": float(r["z"]), "vh": float(r["vh"]),
                   "onground": int(r["onground"]),
                   "over_void": int(r["over_void"]),
                   "haf": (float(r["height_above_floor"])
                           if r.get("height_above_floor") not in (None, "")
                           else None)}
            row["dist_goal"] = math.sqrt((row["x"] - gx) ** 2
                                         + (row["y"] - gy) ** 2
                                         + (row["z"] - gz) ** 2)
            rows.append(row)
    return rows


def write_json(path, obj):
    Path(path).write_text(json.dumps(obj, indent=1), encoding="utf-8")
    print(f"wrote {path}")
