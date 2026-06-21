#!/usr/bin/env python3
"""A4 #116 work item 4 — pmove jump test at the rung-1 lip.

Real-collision flights (scripts/pmove_sim.py, the validated mvdsv port; NO
RNG anywhere — fully deterministic, so the declared inputs ARE the seed set):

  A. ENVELOPE — launch grid from the census takeoff geometry: start on the
     launch plateau d_pre qu BEFORE the census edge point along the aim
     heading (rest z from bsp_geom; skipped+flagged if that xy is off the
     plateau), speed 380..500 step 10, heading = aim-at-m97 + err for err in
     {0, +-8, +-15, +-25} deg, d_pre in {10, 25, 40, 60} (the human jumped
     29.7 qu before the edge). Jump injected on frame 0 (grounded, ktjump
     +270), then neutral flight (QW air-accel adds nothing along-velocity:
     wishspeed clamps to 30 < vh). Landing classified by resting height:
       strip      rest z in [114,126], x <= -270, y <= 620  (the landing
                  platform complex; m97 -> existing path -> 191)
       block_top  rest z in [178,190] (the z=184 block: cleared the void,
                  walk-off to the strip is trivial — counted separately)
       short      rest z < 100 (corridor floor below — recoverable, the
                  bot re-routes; NOT a death pit)
       other      anything else (incl. never grounded in 1.6 s)

  B. MEASURED STATES — per directed live run, the fastest takeoff-capable
     row (haf < 4, the locked climb_detector grounded convention) within
     the lip region (z > 96, hdist < 150): inject the jump AT that position
     and speed with heading REPLACED by aim-at-m97 (declared assumption:
     the trick link re-aims the bot at the destination marker at carrot
     handover, ~0.3-0.5 s before the lip; today's measured headings follow
     the detour and say nothing about the post-link line), heading error
     {0, +-8, +-15}. The position is honest: many states sit 60-150 qu
     before the lip, so this asks "can it clear jumping from WHERE it was
     measured at the speed it was measured" — the hop chain would normally
     carry it closer before the actual jump.

  C. MEASURED STATES, advanced — same states, position advanced along the
     aim line to the census takeoff point (d_pre 25), speed kept (no
     further acceleration credited — conservative: the live bot gains
     speed on grounded ledge runs). This isolates speed from position.

  Cross-check (the DoD "verify 437 with the sim's own arc"): analytic
  ballistic span = speed * 0.675 s (flat jump, +270/g800) vs the censused
  238.2 qu void + d_pre; printed next to the pmove result.

Usage:  python rung1_jump_sim.py [--out jump-sim.json]
"""

from __future__ import annotations

import logging
import argparse
import csv
import json
import math
import sys
from collections import Counter
from pathlib import Path
from statistics import median


LOGGER = logging.getLogger(__name__)
EXP = Path(__file__).resolve().parent
sys.path.insert(0, str(EXP))

from rung1_lib import (  # noqa: E402
    LIP_Z_MIN, NEAR_R, REQUIRED, RUNS, SCRIPTS, edge_point, load_route,
    rung1_gap, write_json,
)

sys.path.insert(0, str(SCRIPTS))
from pmove_sim import Cmd, PlayerState, Pmove, WorldModel  # noqa: E402
from bsp_geom import Bsp  # noqa: E402

DEFAULT_BSP = r"C:\nQuake\qw\maps\dm3.bsp"

M97_NAV = (-335.0, 512.0, 120.0)     # dst marker nav (geometry.json)
SPEEDS = tuple(range(340, 501, 10))
HEAD_ERRS = (-16.0, -12.0, -8.0, -4.0, 0.0, 4.0, 8.0, 12.0, 16.0, 20.0)
D_PRES = (10.0, 25.0, 40.0, 60.0)
MEAS_ERRS = (0.0, -8.0, 8.0, -15.0, 15.0)
MSEC = 13                            # 77 Hz cadence norm
MAX_T = 1.6
BALLISTIC_T = 2 * 270.0 / 800.0      # flat-jump air time, s


def aim_heading(x, y):
    return math.degrees(math.atan2(M97_NAV[1] - y, M97_NAV[0] - x))


def fly(world, start, vh, heading, jump=True):
    """One deterministic pmove flight; returns the landing classification."""
    h = math.radians(heading)
    st = PlayerState(list(start), [vh * math.cos(h), vh * math.sin(h), 0.0],
                     onground=True)
    pm = Pmove(world)
    t, grounded_run = 0.0, 0
    while t < MAX_T:
        cmd = Cmd(MSEC, (0.0, heading, 0.0), (800.0, 0.0, 0.0),
                  2 if (jump and t == 0.0) else 0)
        pm.run_frame(st, cmd)
        t += MSEC * 0.001
        grounded_run = grounded_run + 1 if st.onground else 0
        if grounded_run >= 5 and t > 0.2:
            break
    x, y, z = st.origin
    if 114.0 <= z <= 126.0 and x <= -270.0 and y <= 620.0:
        cls = "strip"
    elif 178.0 <= z <= 190.0:
        cls = "block_top"
    elif z < 100.0:
        cls = "short"
    else:
        cls = "other"
    return {"cls": cls, "end": [round(x, 1), round(y, 1), round(z, 1)],
            "t": round(t, 3)}


def envelope(world, bsp, edge):
    ex, ey, _ = edge
    rows, skipped = [], []
    for d_pre in D_PRES:
        for err in HEAD_ERRS:
            base = aim_heading(ex, ey)
            h = base + err
            r = math.radians(h)
            sx, sy = ex - d_pre * math.cos(r), ey - d_pre * math.sin(r)
            rest = bsp.floor_z(sx, sy, 170.0)
            if rest is None or rest < 100.0:
                skipped.append({"d_pre": d_pre, "err": err,
                                "reason": f"start off plateau (rest {rest})"})
                continue
            for vh in SPEEDS:
                res = fly(world, (sx, sy, rest), vh, h)
                rows.append({"d_pre": d_pre, "err": err,
                             "heading": round(h, 1), "vh": vh, **res})
    return rows, skipped


def min_clearing_speed(rows, d_pre, err):
    ok = sorted(r["vh"] for r in rows
                if r["d_pre"] == d_pre and r["err"] == err
                and r["cls"] in ("strip", "block_top"))
    return ok[0] if ok else None


def measured_states(live_lip_path):
    """Per live run: fastest haf<4 row in the lip region."""
    d = json.loads(Path(live_lip_path).read_text())
    route = load_route()
    ex, ey, _ = edge_point(rung1_gap(route))
    states = []
    for r in d["runs"]:
        best = None
        with open(RUNS / r["run_id"] / "trace.csv", newline="") as fh:
            for row in csv.DictReader(fh):
                x, y, z = float(row["x"]), float(row["y"]), float(row["z"])
                hd = math.hypot(x - ex, y - ey)
                if z <= LIP_Z_MIN or hd >= NEAR_R:
                    continue
                haf = (float(row["height_above_floor"])
                       if row["height_above_floor"] != "" else None)
                if haf is None or haf >= 4.0:
                    continue
                vh = float(row["vh"])
                if best is None or vh > best["vh"]:
                    best = {"run_id": r["run_id"], "x": x, "y": y,
                            "z": z - haf, "vh": vh, "hdist": round(hd, 1)}
        if best:
            states.append(best)
    return states


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bsp", default=DEFAULT_BSP)
    ap.add_argument("--live", default=str(EXP / "live-lip.json"))
    ap.add_argument("--out", default=str(EXP / "jump-sim.json"))
    args = ap.parse_args()

    world = WorldModel.load(args.bsp)
    bsp = Bsp.load(args.bsp)
    route = load_route()
    gap = rung1_gap(route)
    edge = edge_point(gap)

    print("=== A. envelope ===")
    env, skipped = envelope(world, bsp, edge)
    mins = {}
    for d_pre in D_PRES:
        for err in HEAD_ERRS:
            mins[f"d{d_pre:g}_e{err:+g}"] = min_clearing_speed(env, d_pre, err)
    for k, v in mins.items():
        print(f"  min clearing speed {k}: {v}")
    analytic = {f"d{d:g}": round((float(gap['span_qu']) + d) / BALLISTIC_T, 1)
                for d in D_PRES}
    print(f"  analytic flat-jump minimum (span {gap['span_qu']} + d_pre)/{BALLISTIC_T:.3f}s: "
          f"{analytic}")

    print("\n=== B. measured states (jump at measured position, aim at m97) ===")
    states = measured_states(args.live)
    print(f"  {len(states)} per-run takeoff-capable states "
          f"(vh median {median(s['vh'] for s in states):.1f})")
    meas = []
    for s in states:
        for err in MEAS_ERRS:
            h = aim_heading(s["x"], s["y"]) + err
            res = fly(world, (s["x"], s["y"], s["z"]), s["vh"], h)
            meas.append({**{k: (round(v, 1) if isinstance(v, float) else v)
                            for k, v in s.items()}, "err": err, **res})
    for err in MEAS_ERRS:
        sub = [m for m in meas if m["err"] == err]
        ok = sum(1 for m in sub if m["cls"] in ("strip", "block_top"))
        print(f"  err {err:+5.1f}: strip+block {ok}/{len(sub)} "
              f"({Counter(m['cls'] for m in sub)})")

    print("\n=== C. measured speeds advanced to the census takeoff point (d_pre 25) ===")
    base = aim_heading(*edge[:2])
    r = math.radians(base)
    tx, ty = edge[0] - 25.0 * math.cos(r), edge[1] - 25.0 * math.sin(r)
    rest = bsp.floor_z(tx, ty, 170.0)
    adv = []
    for s in states:
        for err in MEAS_ERRS:
            res = fly(world, (tx, ty, rest), s["vh"], base + err)
            adv.append({"run_id": s["run_id"], "vh": s["vh"], "err": err, **res})
    for err in MEAS_ERRS:
        sub = [m for m in adv if m["err"] == err]
        ok = sum(1 for m in sub if m["cls"] in ("strip", "block_top"))
        print(f"  err {err:+5.1f}: strip+block {ok}/{len(sub)} "
              f"({Counter(m['cls'] for m in sub)})")

    # D. aim-point comparison at the census takeoff (d_pre 25): the marker
    # aim (what frogbot actually steers at) vs the census landing point (the
    # corridor center per the human line) — quantifies how much of the
    # heading window the marker's westward offset costs.
    print("\n=== D. aim-point heading windows at d_pre 25, vh 440 ===")
    land_pt = (float(gap["land"][0]), float(gap["land"][1]))
    aims = {"m97": aim_heading(tx, ty),
            "census_land": math.degrees(math.atan2(land_pt[1] - ty,
                                                   land_pt[0] - tx))}
    aimcmp = []
    for name, basehdg in aims.items():
        oks = []
        for derr in range(-20, 21, 2):
            res = fly(world, (tx, ty, rest), 440.0, basehdg + derr)
            aimcmp.append({"aim": name, "heading": round(basehdg + derr, 1),
                           "derr": derr, **res})
            if res["cls"] in ("strip", "block_top"):
                oks.append(derr)
        win = f"[{min(oks):+d}..{max(oks):+d}]" if oks else "none"
        print(f"  aim {name} (abs {basehdg:.1f} deg): clearing derr window {win} "
              f"({len(oks)} of 21 grid points)")

    write_json(args.out, {
        "constants": {"speeds": list(SPEEDS), "head_errs": list(HEAD_ERRS),
                      "d_pres": list(D_PRES), "meas_errs": list(MEAS_ERRS),
                      "msec": MSEC, "aim": "m97 nav " + str(M97_NAV),
                      "ballistic_t": BALLISTIC_T},
        "envelope": env, "envelope_skipped": skipped,
        "min_clearing_speed": mins, "analytic_flat_jump_min": analytic,
        "measured_states": states, "measured_flights": meas,
        "advanced_flights": adv, "aim_comparison": aimcmp,
    })


if __name__ == "__main__":
    main()
