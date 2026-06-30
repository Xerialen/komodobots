#!/usr/bin/env python3
"""Reproducible derivation + drift gate for the directed-eval `end_marker` pins (#460).

Each base Route-Canon highway carries an `end_marker`: the 1-based live FBMARKER
index the handoff gate consumes (k_fb_moveprobe_fixed_goal_s<edict>) to latch a bot
onto that highway. The selection rule is **the nearest live FBMARKER of ANY class
to the highway END (end_xyz), measured in 2-D (x,y)** -- because the gate
(experiments/ktx_moveprobe/live/move_highway.c, mhw_handoff_engaged) tests the goal
origin against MHW_END in 2-D, R_GOAL=256qu, and `fixed_goal` accepts any marker
class (the marker is an intent signal, never a nav target -- the Motor Cortex drives
the polyline once latched). 2-D and 3-D agree on all four, but the gate is 2-D so the
rule is 2-D.

Sources (committed, map-deterministic): the live FBMARKER dump
experiments/p3b_calibration/evidence/fbmarker-dm3.txt and the per-highway end_xyz in
data/catalog/route_canon.dm3.json.

Usage:
  derive_end_markers.py            # print the derivation table
  derive_end_markers.py --check    # exit nonzero if any committed end_marker drifts
                                   # from the nearest-ANY rule (CI / anti-drift gate)
"""
import json
import logging
import math
import re
import sys
from pathlib import Path

LOGGER = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
DUMP = ROOT / "experiments" / "p3b_calibration" / "evidence" / "fbmarker-dm3.txt"
CANON = ROOT / "data" / "catalog" / "route_canon.dm3.json"

R_GOAL = 256.0  # MHW_R_GOAL (move_highway.h): gate admits a goal within this of an END.

_MARK_RE = re.compile(
    r"^FBMARKER\s+(\d+)\s+(\S+)\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+G(\d+)\s+Z(\d+)")


def load_markers(path=DUMP):
    out = []
    for line in Path(path).read_text().splitlines():
        m = _MARK_RE.match(line)
        if m:
            num, cls, x, y, z, g, zo = m.groups()
            out.append({"num": int(num), "cls": cls,
                        "xy": (float(x), float(y)), "z": float(z),
                        "goal": int(g), "zone": int(zo)})
    return out


def load_base_ends(path=CANON):
    """{highway_id: (end_xy, authored_end_marker_or_None)} for route_class=='base'."""
    canon = json.loads(Path(path).read_text())
    ends = {}
    for h in canon["highways"]:
        if h.get("route_class") != "base":
            continue
        end = (h.get("segments") or [{}])[-1].get("end_xyz")
        ends[h["id"]] = ((float(end[0]), float(end[1])), h.get("end_marker"))
    return ends


def _d2(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def nearest_any(markers, end_xy):
    """The nearest FBMARKER of ANY class to end_xy in 2-D -> (num, dist_qu)."""
    best = min(markers, key=lambda m: _d2(m["xy"], end_xy))
    return best["num"], _d2(best["xy"], end_xy)


def derive(markers=None, ends=None):
    """{highway_id: dict(nearest, dist, authored, unique_within_R_GOAL)}."""
    markers = markers if markers is not None else load_markers()
    ends = ends if ends is not None else load_base_ends()
    all_ends = [xy for xy, _ in ends.values()]
    out = {}
    for hid, (end_xy, authored) in ends.items():
        num, dist = nearest_any(markers, end_xy)
        mk = next(m for m in markers if m["num"] == num)
        within = sum(1 for e in all_ends if _d2(mk["xy"], e) <= R_GOAL)
        out[hid] = {"nearest": num, "dist": dist, "authored": authored,
                    "unique_within_R_GOAL": within == 1}
    return out


def main(argv):
    check = "--check" in argv[1:]
    rows = derive()
    drift = []
    print(f"{'highway':<30} {'nearest-ANY':>11} {'dist':>8}  {'authored':>8}  unique  status")
    for hid, r in rows.items():
        ok = (r["authored"] == r["nearest"]) and r["unique_within_R_GOAL"]
        if not ok:
            drift.append(hid)
        print(f"{hid:<30} {r['nearest']:>11} {r['dist']:>7.1f}q  {str(r['authored']):>8}  "
              f"{'yes' if r['unique_within_R_GOAL'] else 'NO ':>6}  {'OK' if ok else 'DRIFT'}")
    if check and drift:
        LOGGER.error("end_marker drift on: %s", ", ".join(drift))
        print(f"\nFAIL: {len(drift)} highway(s) drift from the nearest-ANY rule.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
