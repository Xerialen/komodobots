#!/usr/bin/env python3
"""A4 #116 work item 1 — rung-1 gap geometry vs the live FBMARKER graph.

Offline only. Answers, with numbers committed to geometry.json:
  * nearest EXISTING markers to the census launch edge and landing point
    (ids, coords, distances, path lists, free path slots vs NUMBER_PATHS=8);
  * the D1-style pre-checks transposed to rung 1:
      (a) does the directed walkable route to the pin traverse the would-be
          source marker? (it must, or an at-speed re-link can never trigger)
      (b) NUMBER_PATHS free-slot check on the would-be source marker(s);
  * floor profiles (bsp_geom hull-1 rest heights) along the human launch
    line and the marker-to-marker line, locating the lip, the gap width,
    the landing strip, and the z=184 block that bounds the aim corridor;
  * VERDICT: trick link between two EXISTING markers (zero marker-slot
    cost) or needs dm3's ONE free marker slot.

Usage:  python rung1_geometry.py [--out geometry.json]
"""

from __future__ import annotations

import logging
import argparse
import math
import sys
from pathlib import Path


LOGGER = logging.getLogger(__name__)
EXP = Path(__file__).resolve().parent
sys.path.insert(0, str(EXP))

from rung1_lib import (  # noqa: E402
    REPO, SCRIPTS, edge_point, load_route, rung1_gap, write_json,
)

sys.path.insert(0, str(SCRIPTS))
from mode23_sim import NUMBER_PATHS, build_world_and_graph  # noqa: E402
from bsp_geom import Bsp  # noqa: E402

DEFAULT_BSP = r"C:\nQuake\qw\maps\dm3.bsp"

# The P2 decomposition's arriving-corridor marker skeleton (the walkable
# route of record to the pin): p2-variance-decomposition.md §2.
WALKABLE_SKELETON = [214, 208, 210, 209, 211, 206, 207, 191]

SRC_CANDIDATE = 210     # the Gate-1 lip marker (P2 §1)
DST_CANDIDATE = 97      # the landing-strip marker


def marker_row(graph, num, ref):
    m = graph.markers[num]
    return {
        "num": num, "cls": m.cls,
        "org": [round(v, 1) for v in m.org],
        "nav": [round(v, 1) for v in m.nav],
        "dist_to_ref": round(math.dist(m.org, ref), 1),
        "paths": [[p, hex(f)] for p, f in m.paths],
        "paths_used": len(m.paths),
        "paths_free": NUMBER_PATHS - len(m.paths),
    }


def nearest(graph, ref, n=6):
    ds = sorted(graph.markers.values(), key=lambda m: math.dist(m.org, ref))
    return [marker_row(graph, m.num, ref) for m in ds[:n]]


def floor_profile(bsp, a, b, steps=24, z0=170.0):
    out = []
    for i in range(steps + 1):
        f = i / steps
        x = a[0] + f * (b[0] - a[0])
        y = a[1] + f * (b[1] - a[1])
        fz = bsp.floor_z(x, y, z0)
        out.append({"f": round(f, 3), "x": round(x, 1), "y": round(y, 1),
                    "rest_z": None if fz is None else round(fz, 1)})
    return out


def gap_extent(profile, ledge_z=100.0):
    """First leaves-the-ledge point and first back-on-120 point on a profile
    (rest z < ledge_z = over the low floor)."""
    off = next((p for p in profile if p["rest_z"] is not None and p["rest_z"] < ledge_z), None)
    if off is None:
        return None
    back = next((p for p in profile if p["f"] > off["f"]
                 and p["rest_z"] is not None and p["rest_z"] >= ledge_z), None)
    if back is None:
        return {"off": off, "back": None, "void_qu": None}
    return {"off": off, "back": back,
            "void_qu": round(math.hypot(back["x"] - off["x"], back["y"] - off["y"]), 1)}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bsp", default=DEFAULT_BSP)
    ap.add_argument("--out", default=str(EXP / "geometry.json"))
    args = ap.parse_args()

    route = load_route()
    gap = rung1_gap(route)
    edge = edge_point(gap)
    land = tuple(float(v) for v in gap["land"][:3])

    _world, graph = build_world_and_graph(args.bsp, None)
    bsp = Bsp.load(args.bsp)

    src = marker_row(graph, SRC_CANDIDATE, edge)
    dst = marker_row(graph, DST_CANDIDATE, land)

    # D1-style pre-check (a): source marker on the directed walkable route.
    precheck_a = SRC_CANDIDATE in WALKABLE_SKELETON
    # pre-check (b): free path slot on the source.
    precheck_b = src["paths_free"] >= 1
    # landing side: existing onward path dst -> goal marker.
    dst_to_goal = any(p == 191 for p, _f in graph.markers[DST_CANDIDATE].paths)

    src_nav = graph.markers[SRC_CANDIDATE].nav
    dst_nav = graph.markers[DST_CANDIDATE].nav

    # Human launch line: censused jump point (human pressed jump at frame 130,
    # (-137.8, 747.4, rest 120)) through edge to land.
    human_jump = (-137.8, 747.4, 120.0)
    profiles = {
        "human_line_jump_to_land": floor_profile(bsp, human_jump, land),
        "marker_line_210_to_97": floor_profile(bsp, src_nav, dst_nav),
        "edge_to_land_census": floor_profile(bsp, edge, land),
    }
    gaps = {k: gap_extent(v) for k, v in profiles.items()}

    # The z=184 block that bounds the aim corridor west of the landing strip:
    # probe its east edge at the strip latitude.
    block_probe = [{"x": x, "y": y, "rest_z": bsp.floor_z(x, y, 170.0)}
                   for y in (560, 540, 530, 520)
                   for x in (-330, -320, -310, -300, -290)]

    verdict = {
        "link": f"{SRC_CANDIDATE} -> {DST_CANDIDATE}",
        "marker_slot_cost": 0 if (precheck_b and dst_to_goal) else "NEEDS THE FREE SLOT",
        "uses_free_path_slot_on": SRC_CANDIDATE,
        "precheck_a_source_on_walkable_route": precheck_a,
        "precheck_b_source_free_path_slot": precheck_b,
        "dst_has_existing_path_to_goal_191": dst_to_goal,
    }

    out = {
        "route": route["name"],
        "census_gap": {"edge": list(edge), "land": list(land),
                       "span_qu": gap["span_qu"], "required_speed": gap["required_speed"],
                       "human_speed_at_edge": gap["human_speed_at_edge"],
                       "vz_at_edge": gap["vz_at_edge"],
                       "void_floor_z": gap["void_floor_z"],
                       "landing_floor_z": gap["landing_floor_z"],
                       "landing_area_qu2": gap["landing_area_qu2"]},
        "nearest_to_edge": nearest(graph, edge),
        "nearest_to_land": nearest(graph, land),
        "src": src, "dst": dst,
        "src_to_dst_hdist": round(math.hypot(dst_nav[0] - src_nav[0],
                                             dst_nav[1] - src_nav[1]), 1),
        "verdict": verdict,
        "floor_profiles": profiles,
        "gap_extents": gaps,
        "block_184_probe": block_probe,
        "number_paths": NUMBER_PATHS,
        "graph_marker_count": len(graph.markers),
        "graph_max_marker": max(graph.markers),
    }
    write_json(args.out, out)

    print(f"\nsrc m{SRC_CANDIDATE}: org {src['org']} paths {src['paths_used']}/{NUMBER_PATHS} "
          f"(free {src['paths_free']}), dist to census edge {src['dist_to_ref']}")
    print(f"dst m{DST_CANDIDATE}: org {dst['org']} paths {dst['paths_used']}/{NUMBER_PATHS} "
          f"(free {dst['paths_free']}), dist to census land {dst['dist_to_ref']}, "
          f"existing path to 191: {dst_to_goal}")
    print(f"pre-check (a) src on walkable route: {precheck_a}")
    print(f"pre-check (b) src free path slot:    {precheck_b}")
    print(f"VERDICT: marker_slot_cost = {verdict['marker_slot_cost']}")
    for k, g in gaps.items():
        print(f"gap extent [{k}]: {g}")


if __name__ == "__main__":
    main()
