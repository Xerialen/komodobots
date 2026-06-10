#!/usr/bin/env python3
"""A3 #75 live scoring — the A2 rung-B surrogate + the stairs regression.

EDGE (the pre-registered A3 measurement, identical conditioning to the A2
sim sweep): per run, `mode23_sweep.edge_objective` — route_metrics.edge_speed
at the census sng_to_rl final hard gap, over legit_segment(rows, ()) (NO
sanctioned teleporters; any teleport truncates — the stray-teleport guard is
load-bearing, DO NOT weaken) truncated at the first row within 60 qu (3D) of
the pin marker's nav position (marker 148, the A2 surrogate goal). Rows come
from the run's trace.csv with dist_goal computed against the SAME graph nav
position the sim used (FBMARKER live dump). None = never crossed (absence of
measurement, never 0).

STAIRS (the P1 regression, c5-era convention "zero journey presses; a single
press AT crest = legit hop resume"): pin marker 75, spawn "1984 -108 -144";
rows+commands truncated at first arrival (<60 qu 3D of marker 75 nav), then
climb_detector.detect_climbs (LOCKED thresholds). A jump rising edge inside
a climb span is PRE-CREST iff the REMAINING RISE to the climb's peak contact
height at press time (peak_gz - (z - height_above_floor)) exceeds 18 qu —
the mode-23 delegation dz threshold (DELEG_DZ), the law's own constant:
within 18 qu of the top the grounded-walk doctrine no longer applies and the
hop resume is the law working as designed (the c5-era "single press AT crest
= legit resume": delegation/climb-guard disengage at marker_dz <= 18 and the
resume hop mounts the final <=18 qu step). A press deeper than 18 qu below
the peak is a doctrine violation. Verdict PASS = arrived AND zero pre-crest
presses. Validated on the three c5-era stairs runs
20260610T013814Z/013849Z/013924Z (ledger verdict: 3/3 zero journey presses;
two carry the single crest resume press, remaining rise 16.2 qu): this
scoring reproduces 3/3 PASS, and any press at or below the previous stair
step (>= 1 step = ~24-32 qu remaining, e.g. the v4-era mid-climb presses)
counts as a violation.

Metric semantics are IMPORTED (mode23_sweep / route_metrics /
climb_detector) — never re-implemented.

Usage:
  python a3_surrogate.py edge <run_id> [...]
  python a3_surrogate.py stairs <run_id> [...]

Note (C1 #65 instrument quirk): the c5-family module double-logs delegated/
grounded command frames. Everything here is time/geometry-based (crossing
detection, arrival truncation, contact chaining, jump rising edges over
identical duplicate rows) — row-count rates are never used.
"""

from __future__ import annotations

import csv
import json
import math
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from climb_detector import detect_climbs            # noqa: E402
from mode23_sim import build_world_and_graph, load_route_cfg  # noqa: E402
from mode23_sweep import ARRIVE_R, DEFAULT_BSP, RUNG_B, edge_objective  # noqa: E402

REPO = SCRIPTS.parent
RUNS = REPO / "artifacts" / "lab-runs"

STAIRS_GOAL_MARKER = 75      # SE staircase top (the P1 deterministic stair test)


def load_rows(run_id, goal_pos):
    """trace.csv -> metric rows; dist_goal = 3D distance to the pin nav
    (the sim convention: mode23_sim run loop, math.dist(origin, goal_pos))."""
    gx, gy, gz = goal_pos
    rows = []
    for r in csv.DictReader(open(RUNS / run_id / "trace.csv")):
        rows.append({
            "t": float(r["t"]), "x": float(r["x"]), "y": float(r["y"]),
            "z": float(r["z"]), "vh": float(r["vh"]),
            "onground": int(r["onground"]),
            "height_above_floor": (float(r["height_above_floor"])
                                   if r["height_above_floor"] != "" else None),
            "dist_goal": math.sqrt((float(r["x"]) - gx) ** 2
                                   + (float(r["y"]) - gy) ** 2
                                   + (float(r["z"]) - gz) ** 2),
        })
    return rows


def load_cmds(run_id):
    """moveprobe-commands.json filtered+sorted EXACTLY like build_trace.py,
    so commands align 1:1 with trace.csv rows."""
    cmds = json.loads((RUNS / run_id / "moveprobe-commands.json").read_text())["commands"]
    cmds = [c for c in cmds if "origin" in c]
    cmds.sort(key=lambda c: c["time_s"])
    return cmds


def graph_nav(marker):
    _world, graph = build_world_and_graph(DEFAULT_BSP, None)
    return graph.markers[marker].nav


def cmd_edge(run_ids):
    gap = load_route_cfg("sng_to_rl")["gap"]
    goal = graph_nav(RUNG_B["goal_marker"])
    print(f"# pin marker {RUNG_B['goal_marker']} nav {tuple(round(v,1) for v in goal)}; "
          f"gap edge {gap['edge']}; ARRIVE_R {ARRIVE_R}; "
          f"window {RUNG_B['budget_s']} s from trace start (the sim budget)")
    for rid in run_ids:
        rows = load_rows(rid, goal)
        # identical conditioning to the sim: exactly budget_s seconds of bot
        # control (live runs are started a touch longer; the window equalizes)
        t0 = rows[0]["t"]
        rows = [r for r in rows if r["t"] - t0 <= RUNG_B["budget_s"]]
        v = edge_objective(rows, gap)
        arrived = any(r["dist_goal"] < ARRIVE_R for r in rows)
        closest = min(r["dist_goal"] for r in rows)
        maxvh = max(r["vh"] for r in rows)
        print(f"{rid}  edge={'None' if v is None else f'{v:.1f}'}  "
              f"arrived={arrived}  closest={closest:.1f}  max_vh={maxvh:.1f}")


DELEG_DZ_QU = 18.0   # mode-23 delegation dz threshold (bot_movement.c, the
                     # `marker_dz > 18.0f` constant): grounded-walk doctrine
                     # applies only to rises beyond this


def pre_crest_presses(rows, cmds, climbs):
    """Jump rising edges inside climb spans with more than DELEG_DZ_QU of
    rise still to go at press time (see module docstring)."""
    jb = [1 if int(c["buttons"]) & 2 else 0 for c in cmds]
    n = 0
    for c in climbs:
        # Peak contact height the way the detector itself computes contact
        # height: gz = z - height_above_floor (contacts may carry haf up to
        # CONTACT_HAF_MAX, so raw end z would overstate the peak by ~0-4 qu).
        end_rows = [r for r in rows
                    if abs(r["t"] - c["t_end"]) < 1e-9]
        peak_gz = min(r["z"] - (r["height_above_floor"] or 0.0)
                      for r in end_rows) if end_rows else c["end_xyz"][2]
        for i in range(len(rows)):
            if not (c["t_start"] <= rows[i]["t"] <= c["t_end"]):
                continue
            if not jb[i] or (i and jb[i - 1]):
                continue                      # not a rising edge
            haf = rows[i]["height_above_floor"]
            gz = rows[i]["z"] - (haf if haf is not None else 0.0)
            if peak_gz - gz > DELEG_DZ_QU:
                n += 1
    return n


def cmd_stairs(run_ids):
    goal = graph_nav(STAIRS_GOAL_MARKER)
    print(f"# pin marker {STAIRS_GOAL_MARKER} nav {tuple(round(v,1) for v in goal)}; "
          f"truncate at first <{ARRIVE_R} qu, then detect_climbs")
    for rid in run_ids:
        rows = load_rows(rid, goal)
        cmds = load_cmds(rid)
        if len(cmds) != len(rows):
            raise SystemExit(f"{rid}: trace ({len(rows)}) vs commands ({len(cmds)}) mismatch")
        end = len(rows)
        arrive_t = None
        for i, r in enumerate(rows):
            if r["dist_goal"] < ARRIVE_R:
                end = i + 1
                arrive_t = r["t"] - rows[0]["t"]
                break
        climbs = detect_climbs(rows[:end], cmds[:end])
        span_presses = sum(c["n_jump_inputs"] for c in climbs)
        presses = pre_crest_presses(rows[:end], cmds[:end], climbs)
        verdict = "PASS" if (arrive_t is not None and presses == 0) else "FAIL"
        print(f"{rid}  arrived={'%.1fs' % arrive_t if arrive_t is not None else 'NO'}  "
              f"climbs={len(climbs)}  span_presses={span_presses}  "
              f"pre_crest_presses={presses}  {verdict}")


def main():
    if len(sys.argv) < 3 or sys.argv[1] not in ("edge", "stairs"):
        print(__doc__)
        sys.exit(1)
    (cmd_edge if sys.argv[1] == "edge" else cmd_stairs)(sys.argv[2:])


if __name__ == "__main__":
    main()
