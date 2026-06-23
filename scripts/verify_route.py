#!/usr/bin/env python3
"""Goal-true scorer for dm3 trick-route bot lab runs.

Replaces the old route%=max(nearest-human-index) metric, which could not tell
"tracked the path toward the bridge" from "reached RL" -- a run that stalled at
the ledge and never jumped scored ~77% and read as near-success.

This version consumes the unified per-tick trace (trace.csv, built by
build_trace.py from the command log: actual origin, velocity, onground,
over_void, dist_to_rl) plus the route geometry. Per attempt it reports:

  * an explicit CLASSIFICATION:
      REACHED_RL              - got within 60 qu (3D) of the route goal
      ATTEMPTED_JUMP_FELL_SHORT - launched off the ledge over the void but never landed
      REACHED_LEDGE_NO_JUMP   - reached the launch edge but never went airborne over the void
      LEFT_ROUTE              - diverged from the route (stray teleport / wrong way)
      NEVER_REACHED_LEDGE     - never got to the final ledge
  * route%   = arc-length progress along the human path (uniform in distance)
  * speed%   = bot active-mean horizontal speed / human active-mean
  * leap diagnostics: speed at the launch edge vs the required launch speed

PASS requires REACHED_RL AND route% >= 80 AND speed% >= 80. (The 80/80 criterion
is non-negotiable; reaching RL implies route ~100, so PASS is effectively
REACHED_RL + speed >= 80.)

Speed metrics come from scripts/route_metrics.py (the ONE shared definition).
speed% here uses active_mean_speed for continuity with the human baselines;
pass/fail GATES should use route_metrics.time_weighted_speed as the primary
(dead-stop-proof) metric -- print it per attempt with --metrics.

Routes: default is the original sng_to_rl (byte-identical output to the
pre-parameterization scorer). Any of the 11 censused dm3 trick routes can be
scored the same way with --route <name>; geometry + human baseline are loaded
from artifacts/replay/dm3_<name>.cmds + artifacts/trick-census/census.json
(start = first human point, goal = last human point, launch edge = the final
hard gap, sanctioned teleporters = the census teleport entrances).

Usage:
  python verify_route.py <run_id> [--route <name>] [--metrics]
"""

from __future__ import annotations

import logging
import csv
import json
import math
import sys
from pathlib import Path

from route_metrics import legit_segment, time_weighted_speed, active_mean_speed
# alias: classify() returns a local diagnostic named edge_speed (best grounded
# vh near the ledge); the imported metric is the launch-edge CROSSING speed.
from route_metrics import edge_speed as launch_edge_speed


LOGGER = logging.getLogger(__name__)
REPO = Path(__file__).resolve().parent.parent
RUNS = REPO / "artifacts" / "lab-runs"
EVID = REPO / "experiments" / "dm3_sng_to_rl_observability" / "evidence"
NAV_EVID = REPO / "experiments" / "nav_doctrine" / "evidence"


def _resolve(live: Path, committed: Path) -> Path:
    """Prefer a freshly-regenerated input under artifacts/ (gitignored); fall
    back to the committed copy in the experiment evidence dir so the scorer is
    reproducible from a clean checkout (Codex PR #58 P1)."""
    return live if live.exists() else committed


DEFAULT_ROUTE = "sng_to_rl"

# sng_to_rl constants (the original hardcoded route -- kept verbatim so the
# default invocation is byte-identical to the pre-parameterization scorer).
SNG = (-895.0, -129.0)
RL = (1591.0, 526.0, -88.0)
TELE_ENT = (-539.0, -454.0)   # the ONE legit SNG->exit teleporter entrance
SNG_R = 90.0          # within this xy of the start pad = at the start pad
REACH_RL = 60.0       # within this 3D of the goal = arrived
LEDGE_R = 110.0       # within this xy of the launch edge = reached the ledge


def load_route(name):
    """Build the route config: human path file, start/goal, sanctioned
    teleporter entrances, and leap geometry."""
    if name == DEFAULT_ROUTE:
        human = _resolve(REPO / "artifacts" / "replay" / "dm3_sng_to_rl.cmds",
                         EVID / "dm3_sng_to_rl.cmds")
        geom_path = _resolve(REPO / "artifacts" / "bsp" / "dm3" / "dm3_jump_geom.json",
                             EVID / "dm3_jump_geom.json")
        geom = json.loads(geom_path.read_text())
        # edge_speed() gap geometry from the validated reference (launch edge
        # + landing ledge; agrees with the census final hard gap to <1 qu/s).
        gap = {"edge": [geom["launch_edge"]["x"], geom["launch_edge"]["y"],
                        geom["launch_edge"]["z"]],
               "land": [geom["landing_ledge"]["x"], geom["landing_ledge"]["y"],
                        geom["landing_ledge"]["z"]]}
        return {
            "name": name, "human": human, "start": SNG, "goal": RL,
            "tele_entrances": (TELE_ENT,),
            "geom": geom, "gap": gap,
            "native_dist": True,   # trace.csv dist_to_rl column IS this goal
        }
    # Census + per-route human replays resolve like the default route's inputs:
    # live regenerated artifacts/ first, committed evidence fallback, so every
    # censused route scores from a clean checkout (Codex PR #60 P2).
    census_path = _resolve(REPO / "artifacts" / "trick-census" / "census.json",
                           NAV_EVID / "trick-census" / "census.json")
    census = json.loads(census_path.read_text())
    if name not in census:
        raise SystemExit(f"unknown route {name!r}; censused routes: {', '.join(sorted(census))}")
    human = _resolve(REPO / "artifacts" / "replay" / f"dm3_{name}.cmds",
                     NAV_EVID / "replay" / f"dm3_{name}.cmds")
    if not human.exists():
        raise SystemExit(f"human replay for route {name!r} missing: regenerate it "
                         f"under artifacts/replay/dm3_{name}.cmds or restore the "
                         f"committed copy {NAV_EVID / 'replay' / f'dm3_{name}.cmds'}")
    ent = census[name]
    # leap geometry := the route's FINAL hard gap (the goal-gating leap).
    hard = [g for g in ent["gaps"] if g.get("hard")]
    geom, gap = None, None
    if hard:
        g = hard[-1]
        gap = g     # census gap dict, consumed as-is by route_metrics.edge_speed
        geom = {
            "launch_edge": {"x": g["edge"][0], "y": g["edge"][1]},
            "required_launch_speed_qu_s": g["required_speed"],
            "human_launch_speed_qu_s": g["human_speed_at_edge"],
            "void_floor_z": g["void_floor_z"],
        }
    # start/goal from the human path itself (first/last cmds point)
    pts = _read_cmds_points(human)
    start, goal = pts[0], pts[-1]
    if math.hypot(start[0] - goal[0], start[1] - goal[1]) < 200:
        print(f"WARNING: route {name} start ~= goal (loop route); "
              "arrival truncation and attempt segmentation are unreliable.", file=sys.stderr)
    return {
        "name": name, "human": human, "start": (start[0], start[1]), "goal": goal,
        "tele_entrances": tuple((t["from"][0], t["from"][1]) for t in ent["teleports"]),
        "geom": geom, "gap": gap,
        "native_dist": False,
    }


def _read_cmds_points(path):
    pts = []
    for ln in open(path):
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        p = ln.split()
        if len(p) < 14:
            continue
        pts.append((float(p[1]), float(p[2]), float(p[3])))
    return pts


def load_human(route):
    H, HS = [], []
    for ln in open(route["human"]):
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        p = ln.split()
        if len(p) < 14:
            continue
        H.append((float(p[1]), float(p[2]), float(p[3])))
        HS.append(math.hypot(float(p[4]), float(p[5])))
    # cumulative arc length (xy) along the human path
    cum = [0.0]
    for a, b in zip(H, H[1:]):
        cum.append(cum[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
    # human active-mean speed: start until first within 60 qu (3D) of the goal
    gx, gy, gz = route["goal"]
    arrive = len(H)
    for i, (x, y, z) in enumerate(H):
        if math.sqrt((x - gx) ** 2 + (y - gy) ** 2 + (z - gz) ** 2) < REACH_RL:
            arrive = i
            break
    hmean = sum(HS[:arrive]) / max(1, arrive)
    return H, cum, hmean


def nearest_arc(H, cum, x, y):
    bi, bd = 0, 1e18
    for i, (hx, hy, hz) in enumerate(H):
        dd = (hx - x) ** 2 + (hy - y) ** 2
        if dd < bd:
            bd, bi = dd, i
    return cum[bi], math.sqrt(bd)


def route_progress(H, cum, seg, xtrack_max=150.0):
    """Furthest human-path arc-length the bot reached while ON the route:
    within xtrack_max qu of the path AND not over the void. This refuses to
    credit a bot that flew off into the chasm and happened to pass near a
    late human-path point on the way down."""
    best = 0.0
    for r in seg:
        if r["over_void"]:
            continue
        arc, d = nearest_arc(H, cum, r["x"], r["y"])
        if d <= xtrack_max and arc > best:
            best = arc
    return 100.0 * best / cum[-1]


def load_trace(run_id, route):
    path = RUNS / run_id / "trace.csv"
    if not path.exists():
        raise SystemExit(f"{path} missing -- run build_trace.py {run_id} first")
    gx, gy, gz = route["goal"]
    rows = []
    for r in csv.DictReader(open(path)):
        row = {
            "t": float(r["t"]), "x": float(r["x"]), "y": float(r["y"]), "z": float(r["z"]),
            "vh": float(r["vh"]), "onground": int(r["onground"]),
            "over_void": int(r["over_void"]),
        }
        if route["native_dist"]:
            # trace.csv's dist_to_rl column is exactly distance-to-this-goal
            # (build_trace.py computes it against the sng_to_rl RL).
            row["dist_goal"] = float(r["dist_to_rl"])
        else:
            row["dist_goal"] = math.sqrt(
                (row["x"] - gx) ** 2 + (row["y"] - gy) ** 2 + (row["z"] - gz) ** 2)
        rows.append(row)
    return rows


def segment_attempts(rows, route):
    """Split the run into attempts at start-pad snaps (bot resets to the start)."""
    sx, sy = route["start"]
    at_start = [i for i, r in enumerate(rows) if math.hypot(r["x"] - sx, r["y"] - sy) < SNG_R]
    starts, prev = [], -99
    for i in at_start:
        if i != prev + 1:
            starts.append(i)
        prev = i
    segs = []
    for k, s in enumerate(starts):
        e = starts[k + 1] if k + 1 < len(starts) else len(rows)
        segs.append((s, e))
    return segs


def classify(seg, geom):
    closest_rl = min(r["dist_goal"] for r in seg)
    if geom is None:
        # route has no censused hard gap: no leap geometry to diagnose
        if closest_rl < REACH_RL:
            return "REACHED_RL", closest_rl, 0.0, 0.0
        return ("NEVER_REACHED_LEDGE" if closest_rl > 1500 else "LEFT_ROUTE",
                closest_rl, 0.0, 0.0)

    edge = geom["launch_edge"]
    ex, ey = edge["x"], edge["y"]
    vreq = geom["required_launch_speed_qu_s"]

    reached_ledge = any(
        math.hypot(r["x"] - ex, r["y"] - ey) < LEDGE_R and r["z"] > -30 for r in seg
    )
    # A launch attempt = went over the void FROM at/near the actual launch edge,
    # not merely "over some void at high x". A bot that wanders ~300 qu south of
    # the edge and falls into a different void is NOT a leap attempt (it never
    # reached the ledge), so gate attempted_jump on reached_ledge + edge xy.
    attempted_jump = reached_ledge and any(
        r["over_void"] and r["x"] > ex - 20 and abs(r["y"] - ey) < 160 for r in seg
    )
    # speed carried into the edge: best vh while grounded within ~150 qu of the edge
    near_edge = [r["vh"] for r in seg
                 if math.hypot(r["x"] - ex, r["y"] - ey) < 150 and r["onground"]]
    edge_speed = max(near_edge) if near_edge else 0.0

    if closest_rl < REACH_RL:
        cls = "REACHED_RL"
    elif reached_ledge and attempted_jump:
        cls = "ATTEMPTED_JUMP_FELL_SHORT"
    elif reached_ledge:
        cls = "REACHED_LEDGE_NO_JUMP"
    elif closest_rl > 1500:
        cls = "NEVER_REACHED_LEDGE"
    else:
        cls = "LEFT_ROUTE"
    return cls, closest_rl, edge_speed, vreq


def main():
    args = [a for a in sys.argv[1:]]
    route_name, show_metrics = DEFAULT_ROUTE, False
    pos = []
    i = 0
    while i < len(args):
        if args[i] == "--route":
            route_name = args[i + 1]
            i += 2
        elif args[i] == "--metrics":
            show_metrics = True
            i += 1
        else:
            pos.append(args[i])
            i += 1
    run_id = pos[0] if pos else None
    if not run_id:
        print(__doc__)
        sys.exit(1)

    route = load_route(route_name)
    H, cum, hmean = load_human(route)
    geom = route["geom"]
    rows = load_trace(run_id, route)
    segs = segment_attempts(rows, route)

    print(f"RUN {run_id}")
    print(f"human baseline: active-mean speed {hmean:.0f} qu/s | route arc-length {cum[-1]:.0f} qu")
    if geom is not None:
        print(f"leap: launch edge ({geom['launch_edge']['x']:.0f},{geom['launch_edge']['y']:.0f}) "
              f"requires >= {geom['required_launch_speed_qu_s']:.0f} qu/s (human had "
              f"{geom['human_launch_speed_qu_s']:.0f}); void floor {geom['void_floor_z']:.0f}")
    else:
        print("leap: route has no censused hard gap (no leap geometry)")
    print(f"attempts: {len(segs)}\n")

    best = None
    edge_xs = []   # per scored attempt: route_metrics.edge_speed (None = never crossed)
    for k, (s, e) in enumerate(segs):
        seg = legit_segment(rows[s:e], route["tele_entrances"])
        if len(seg) < 3:
            continue
        rt = route_progress(H, cum, seg)
        ms = active_mean_speed(seg, threshold=1.0, reach=REACH_RL)
        speedpct = 100.0 * ms / hmean if hmean else 0.0
        cls, crl, edge_speed, vreq = classify(seg, geom)
        passed = cls == "REACHED_RL" and rt >= 80 and speedpct >= 80
        ev = launch_edge_speed(seg, route["gap"], route["tele_entrances"])
        edge_xs.append(ev)
        leap = (f"edge_speed={edge_speed:.0f}/{vreq:.0f}qu/s" if edge_speed else "no ledge approach")
        extra = ""
        if show_metrics:
            tws = time_weighted_speed(seg, route["tele_entrances"], reach=REACH_RL)
            extra = f" tws={tws:.0f}qu/s"
            extra += f" edge={ev:.0f}qu/s" if ev is not None else " edge=None"
        print(f"  #{k:2d} {cls:25s} route={rt:5.1f}% speed={speedpct:4.0f}% "
              f"closestRL={crl:6.0f}qu  {leap}  {'*** PASS ***' if passed else ''}" + extra)
        score = (cls == "REACHED_RL", rt, speedpct)
        if best is None or score > best[0]:
            best = (score, k, cls, rt, speedpct, crl, edge_speed)

    if best:
        _, k, cls, rt, speedpct, crl, edge_speed = best
        print(f"\nBEST attempt #{k}: {cls}  route={rt:.1f}%  speed={speedpct:.0f}%  closestRL={crl:.0f}qu")
        if cls != "REACHED_RL" and geom is not None:
            gap = geom["required_launch_speed_qu_s"] - edge_speed
            print(f"  NOT a completion. Binding constraint: "
                  + (f"edge speed {edge_speed:.0f} qu/s is {gap:.0f} short of the {geom['required_launch_speed_qu_s']:.0f} needed to clear the void."
                     if edge_speed and gap > 0 else
                     f"classification {cls} -- see per-attempt leap diagnostics."))
        if route["gap"] is not None and geom is not None:
            # THE launch-edge metric (route_metrics.edge_speed, issue #63):
            # speed carried across the launch edge; None = never crossed it.
            crossed = [v for v in edge_xs if v is not None]
            req = geom["required_launch_speed_qu_s"]
            stat = f"{len(crossed)}/{len(edge_xs)} attempts crossed the launch edge; required >= {req:.1f}"
            if crossed:
                print(f"edge_speed[crossing]: best {max(crossed):.1f} qu/s ({stat})")
            else:
                print(f"edge_speed[crossing]: None ({stat})")
    else:
        # "Never run blind": zero scored attempts is a measurement failure, not
        # a scored run (Codex PR #58 P2). Wrong map/mode, a failed spawn, or an
        # origin stream that never reaches the route start must not exit 0, or
        # run_dm3.py would report a blind run as success.
        print("\nERROR: no route attempt scored -- the trace never produced a "
              "scoreable segment near the SNG start. Check map/mode, spawn "
              "setup, and that the origin stream covers the route.",
              file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
