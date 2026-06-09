#!/usr/bin/env python3
"""Goal-true scorer for dm3 SNG->RL bot lab runs.

Replaces the old route%=max(nearest-human-index) metric, which could not tell
"tracked the path toward the bridge" from "reached RL" -- a run that stalled at
the ledge and never jumped scored ~77% and read as near-success.

This version consumes the unified per-tick trace (trace.csv, built by
build_trace.py from the command log: actual origin, velocity, onground,
over_void, dist_to_rl) plus the validated jump geometry (dm3_jump_geom.json).
Per attempt it reports:

  * an explicit CLASSIFICATION:
      REACHED_RL              - got within 60 qu (3D) of the RL
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

Usage:
  python verify_route.py <run_id>
"""

from __future__ import annotations

import csv
import json
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RUNS = REPO / "artifacts" / "lab-runs"
EVID = REPO / "experiments" / "dm3_sng_to_rl_observability" / "evidence"


def _resolve(live: Path, committed: Path) -> Path:
    """Prefer a freshly-regenerated input under artifacts/ (gitignored); fall
    back to the committed copy in the experiment evidence dir so the scorer is
    reproducible from a clean checkout (Codex PR #58 P1)."""
    return live if live.exists() else committed


HUMAN = _resolve(REPO / "artifacts" / "replay" / "dm3_sng_to_rl.cmds",
                 EVID / "dm3_sng_to_rl.cmds")
GEOM = _resolve(REPO / "artifacts" / "bsp" / "dm3" / "dm3_jump_geom.json",
                EVID / "dm3_jump_geom.json")

SNG = (-895.0, -129.0)
RL = (1591.0, 526.0, -88.0)
TELE_ENT = (-539.0, -454.0)   # the ONE legit SNG->exit teleporter entrance
SNG_R = 90.0          # within this xy of SNG = at the start pad
REACH_RL = 60.0       # within this 3D of RL = arrived
LEDGE_R = 110.0       # within this xy of the launch edge = reached the ledge
TELEPORT_JUMP = 250.0  # single-frame origin jump beyond this = a teleport


def load_human():
    H, HS = [], []
    for ln in open(HUMAN):
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
    # human active-mean speed: start until first within 60 qu (3D) of RL
    arrive = len(H)
    for i, (x, y, z) in enumerate(H):
        if math.sqrt((x - RL[0]) ** 2 + (y - RL[1]) ** 2 + (z - RL[2]) ** 2) < REACH_RL:
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


def load_trace(run_id):
    path = RUNS / run_id / "trace.csv"
    if not path.exists():
        raise SystemExit(f"{path} missing -- run build_trace.py {run_id} first")
    rows = []
    for r in csv.DictReader(open(path)):
        rows.append({
            "t": float(r["t"]), "x": float(r["x"]), "y": float(r["y"]), "z": float(r["z"]),
            "vh": float(r["vh"]), "onground": int(r["onground"]),
            "over_void": int(r["over_void"]), "dist_to_rl": float(r["dist_to_rl"]),
        })
    return rows


def legit_segment(seg):
    """Truncate an attempt at the first STRAY teleport. dm3 has one legit
    SNG->exit teleporter (entrance ~TELE_ENT); any OTHER large single-frame
    origin jump means the bot took a wrong teleporter and left the intended
    route, so we stop counting there. Without this, a stray teleporter that
    dumps the bot near RL's xy (but at the wrong height) is a false positive
    -- the exact trap the old scorer guarded against."""
    if not seg:
        return seg
    out = [seg[0]]
    seen_legit = False
    for a, b in zip(seg, seg[1:]):
        jump = math.hypot(b["x"] - a["x"], b["y"] - a["y"]) + abs(b["z"] - a["z"])
        if jump > TELEPORT_JUMP:
            near_ent = math.hypot(a["x"] - TELE_ENT[0], a["y"] - TELE_ENT[1]) < TELEPORT_JUMP
            if near_ent and not seen_legit:
                seen_legit = True
                out.append(b)        # accept the one legit teleport landing
                continue
            break                    # stray teleport -> truncate the attempt
        out.append(b)
    return out


def segment_attempts(rows):
    """Split the run into attempts at SNG snaps (bot resets to the start pad)."""
    at_sng = [i for i, r in enumerate(rows) if math.hypot(r["x"] - SNG[0], r["y"] - SNG[1]) < SNG_R]
    starts, prev = [], -99
    for i in at_sng:
        if i != prev + 1:
            starts.append(i)
        prev = i
    segs = []
    for k, s in enumerate(starts):
        e = starts[k + 1] if k + 1 < len(starts) else len(rows)
        segs.append((s, e))
    return segs


def classify(seg, geom):
    edge = geom["launch_edge"]
    ex, ey = edge["x"], edge["y"]
    vreq = geom["required_launch_speed_qu_s"]

    closest_rl = min(r["dist_to_rl"] for r in seg)
    route_max = max((r for r in seg), key=lambda r: r["x"] + r["y"])  # rough far point

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


def active_mean_speed(seg):
    """Mean vh from start until first within 60 qu of RL (excludes idle tail)."""
    end = len(seg)
    for i, r in enumerate(seg):
        if r["dist_to_rl"] < REACH_RL:
            end = i + 1
            break
    sp = [r["vh"] for r in seg[:end] if r["vh"] > 1]
    return sum(sp) / len(sp) if sp else 0.0


def main():
    run_id = sys.argv[1] if len(sys.argv) > 1 else None
    if not run_id:
        print(__doc__)
        sys.exit(1)
    H, cum, hmean = load_human()
    geom = json.loads(GEOM.read_text())
    rows = load_trace(run_id)
    segs = segment_attempts(rows)

    print(f"RUN {run_id}")
    print(f"human baseline: active-mean speed {hmean:.0f} qu/s | route arc-length {cum[-1]:.0f} qu")
    print(f"leap: launch edge ({geom['launch_edge']['x']:.0f},{geom['launch_edge']['y']:.0f}) "
          f"requires >= {geom['required_launch_speed_qu_s']:.0f} qu/s (human had "
          f"{geom['human_launch_speed_qu_s']:.0f}); void floor {geom['void_floor_z']:.0f}")
    print(f"attempts: {len(segs)}\n")

    best = None
    for k, (s, e) in enumerate(segs):
        seg = legit_segment(rows[s:e])
        if len(seg) < 3:
            continue
        route = route_progress(H, cum, seg)
        ms = active_mean_speed(seg)
        speedpct = 100.0 * ms / hmean
        cls, crl, edge_speed, vreq = classify(seg, geom)
        passed = cls == "REACHED_RL" and route >= 80 and speedpct >= 80
        leap = (f"edge_speed={edge_speed:.0f}/{vreq:.0f}qu/s" if edge_speed else "no ledge approach")
        print(f"  #{k:2d} {cls:25s} route={route:5.1f}% speed={speedpct:4.0f}% "
              f"closestRL={crl:6.0f}qu  {leap}  {'*** PASS ***' if passed else ''}")
        score = (cls == "REACHED_RL", route, speedpct)
        if best is None or score > best[0]:
            best = (score, k, cls, route, speedpct, crl, edge_speed)

    if best:
        _, k, cls, route, speedpct, crl, edge_speed = best
        print(f"\nBEST attempt #{k}: {cls}  route={route:.1f}%  speed={speedpct:.0f}%  closestRL={crl:.0f}qu")
        if cls != "REACHED_RL":
            gap = geom["required_launch_speed_qu_s"] - edge_speed
            print(f"  NOT a completion. Binding constraint: "
                  + (f"edge speed {edge_speed:.0f} qu/s is {gap:.0f} short of the {geom['required_launch_speed_qu_s']:.0f} needed to clear the void."
                     if edge_speed and gap > 0 else
                     f"classification {cls} -- see per-attempt leap diagnostics."))


if __name__ == "__main__":
    main()
