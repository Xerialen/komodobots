#!/usr/bin/env python3
"""A5 #118 step 2: extract the human's EXACT per-attempt start on ztricks.bsp.

The "Distance" trick attempt boundary is the map's teleport reset: miss ->
fall into the gap -> the catcher trigger_teleport throws the player back.
The START of every attempt is therefore the teleport DEPOSIT point. Two
independent sources, cross-checked here:

  1. the demo: the aligned getspeed cmds teleport discontinuities
     (detect_teleports; consecutive detections are ONE reset — the rebuild
     interpolates the state dropped at each teleport, producing a midpoint
     row — so runs are merged and the arrival is the row after the run);
  2. the map: ztricks.bsp trigger_teleport/info_teleport_destination
     entities (mode23_sim.load_teleporters semantics: deposit z = entity
     z + 27, facing = destination "angle").

Writes start-point.json next to this script.

Usage: python a5_start_point.py [--cmds <aligned.cmds>] [--bsp <ztricks.bsp>]
"""
from __future__ import annotations

import logging
import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path


LOGGER = logging.getLogger(__name__)
HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from pmove_sim import detect_teleports, load_cmds_file  # noqa: E402
from mode23_sim import load_teleporters  # noqa: E402

# the TIME-ALIGNED rebuild (a5_rebuild_cmds.py) — the committed
# start-point.json comes from it; the original bunnyhop-evidence
# getspeed.cmds carries the zip-pairing misalignment (identical arrival
# POSITIONS — state stream — but stale view angles next to them)
DEFAULT_CMDS = HERE / "getspeed-aligned.cmds"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cmds", default=str(DEFAULT_CMDS))
    # ztricks.bsp = the demo's actual map (the A5 correction; running this
    # against trick.bsp is exactly the wrong-map analysis this experiment
    # retired - Codex PR #120 P2 caught the stale default)
    ap.add_argument("--bsp", default=r"C:\nQuake\qw\maps\ztricks.bsp")
    ap.add_argument("--out", default=str(HERE / "start-point.json"))
    args = ap.parse_args()

    frames = load_cmds_file(args.cmds)
    tele = detect_teleports(frames)

    # collapse runs of consecutive detections into ONE reset each: the
    # aligned rebuild interpolates the state frame dropped at every
    # teleport, so each reset shows up as (midpoint jump, deposit jump) —
    # counting both would double the resets and mix midpoint z/yaw into
    # the start-point evidence (Codex PR #120 round 3)
    resets = []
    for k in tele:
        if resets and k == resets[-1][-1] + 1:
            resets[-1].append(k)
        else:
            resets.append([k])

    # demo side: arrival state right after each reset's LAST jump
    arrivals = []
    for run in resets:
        k = run[-1]
        a = frames[k + 1]
        arrivals.append({
            "frame": k + 1,
            "t": round(sum(f["msec"] for f in frames[1:k + 2]) / 1000.0, 2),
            "origin": a["origin"],
            "yaw": a["angles"][1],
            "pitch": a["angles"][0],
        })

    # demo side: frame 0 (the recording starts already parked at the spot)
    f0 = frames[0]

    # map side: which trigger_teleport destination matches the arrivals?
    teles = load_teleporters(args.bsp)
    # cluster arrival origins (x, y) -- all resets should hit ONE destination
    xy = Counter((round(a["origin"][0], 3), round(a["origin"][1], 3))
                 for a in arrivals)
    main_xy, main_n = (xy.most_common(1)[0] if xy else ((None, None), 0))

    matched = None
    if main_xy[0] is not None:
        best_d = 1e9
        for tp in teles:
            d = math.hypot(tp.dest[0] - main_xy[0], tp.dest[1] - main_xy[1])
            if d < best_d:
                best_d = d
                matched = {
                    "dest": list(tp.dest),       # z already +27
                    "dest_xy_err_vs_demo": round(d, 3),
                    "mangle_yaw": tp.mangle_yaw,
                    "trigger_absmin": list(tp.absmin),
                    "trigger_absmax": list(tp.absmax),
                }

    arrival_yaws = [a["yaw"] for a in arrivals]
    arrival_zs = [a["origin"][2] for a in arrivals]

    out = {
        "cmds": str(args.cmds),
        "bsp": args.bsp,
        "n_frames": len(frames),
        "teleport_frames": tele,
        "n_teleport_resets": len(arrivals),
        "frame0": {"origin": f0["origin"], "yaw": f0["angles"][1],
                   "pitch": f0["angles"][0]},
        "arrivals": arrivals,
        "arrival_xy_mode": {"xy": list(main_xy), "count": main_n},
        "arrival_z_range": [min(arrival_zs), max(arrival_zs)] if arrival_zs else None,
        "arrival_yaw_all": arrival_yaws,
        "matched_map_destination": matched,
        "n_map_teleporters": len(teles),
    }
    Path(args.out).write_text(json.dumps(out, indent=1))

    print(f"frames={len(frames)}  teleport resets={len(arrivals)}")
    print(f"frame0 (recording starts parked): org=({f0['origin'][0]:.3f}, "
          f"{f0['origin'][1]:.3f}, {f0['origin'][2]:.3f})  "
          f"yaw={f0['angles'][1]:.2f} pitch={f0['angles'][0]:.2f}")
    print("\nper-reset arrivals (frame, t, origin, yaw):")
    for a in arrivals:
        o = a["origin"]
        print(f"  f{a['frame']:5d} t={a['t']:6.2f}  ({o[0]:9.3f},{o[1]:9.3f},"
              f"{o[2]:8.3f})  yaw={a['yaw']:7.2f}")
    print(f"\narrival xy mode: {main_xy} ({main_n}/{len(arrivals)})")
    if matched:
        print(f"map destination match: dest={matched['dest']} "
              f"(xy err {matched['dest_xy_err_vs_demo']} qu), "
              f"angle={matched['mangle_yaw']}")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
