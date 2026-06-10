#!/usr/bin/env python3
"""Build a unified per-tick trace for a dm3 SNG->RL bot lab run.

Source: artifacts/lab-runs/<run_id>/moveprobe-commands.json — the FBMOVEPROBE_CMD
stream (one record per command frame, ~100 Hz), which now carries the bot's
actual `origin` alongside velocity, onground, the emitted move/angles, and the
replay cursor. Because origin+velocity+commands share one server clock there is
NO cross-stream join: the command log alone is the trace. Each row is enriched
with dm3 collision geometry from bsp_geom (floor_z, over_void, dist_to_RL).

Outputs (in the run dir):
  trace.csv          — one row per command frame
  trace_summary.json — high-level stats + bridge-leap detection

Usage:
  python build_trace.py <run_id> [bsp_path]
"""

from __future__ import annotations

import csv
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bsp_geom import Bsp  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
RUNS = REPO / "artifacts" / "lab-runs"
DEFAULT_BSP = r"C:\nQuake\qw\maps\dm3.bsp"
RL = (1591.0, 526.0, -88.0)

CSV_COLS = [
    "i", "t", "x", "y", "z", "vx", "vy", "vz", "vh", "onground",
    "fwd", "side", "up", "yaw", "yaw_rate", "dir_speed",
    "floor_z", "height_above_floor", "over_void", "dist_to_rl",
    "replay_cursor", "divergence_qu",
]


def _ang_delta(a, b):
    d = (a - b) % 360.0
    if d > 180.0:
        d -= 360.0
    return d


def build(run_id, bsp_path=DEFAULT_BSP):
    run_dir = RUNS / run_id
    cmds = json.loads((run_dir / "moveprobe-commands.json").read_text())["commands"]
    cmds = [c for c in cmds if "origin" in c]   # need actual origin
    cmds.sort(key=lambda c: c["time_s"])
    if not cmds:
        raise SystemExit(f"{run_id}: no command records with origin (rebuild + log-interval 0?)")

    bsp = Bsp.load(bsp_path)
    floor_cache = {}

    def floor_at(x, y, z):
        key = (round(x, 1), round(y, 1))
        if key not in floor_cache:
            floor_cache[key] = bsp.floor_z(x, y, z + 8.0)
        return floor_cache[key]

    rows = []
    prev_yaw = prev_t = None
    for i, c in enumerate(cmds):
        o = c["origin"]
        x, y, z = o["x"], o["y"], o["z"]
        v = c["water_state"]["velocity"]
        vx, vy, vz = v["x"], v["y"], v["z"]
        vh = math.hypot(vx, vy)
        yaw = c["angles"]["yaw"]
        t = c["time_s"]
        yaw_rate = 0.0
        if prev_yaw is not None and t > prev_t:
            yaw_rate = _ang_delta(yaw, prev_yaw) / (t - prev_t)
        prev_yaw, prev_t = yaw, t

        fz = floor_at(x, y, z)
        haf = (z - fz) if fz is not None else None
        over_void = fz is None or fz < -200.0
        drl = math.sqrt((x - RL[0]) ** 2 + (y - RL[1]) ** 2 + (z - RL[2]) ** 2)

        rows.append({
            "i": i, "t": round(t, 4), "x": round(x, 2), "y": round(y, 2), "z": round(z, 2),
            "vx": round(vx, 1), "vy": round(vy, 1), "vz": round(vz, 1), "vh": round(vh, 1),
            # real FL_ONGROUND (512) from the player flags; probe_state.on_ground
            # is the moveprobe transition tracker and is unreliable (always 0 here).
            "onground": int(bool(c["water_state"]["flags"] & 512)),
            "fwd": c["move"]["forward"], "side": c["move"]["side"], "up": c["move"]["up"],
            "yaw": round(yaw, 1), "yaw_rate": round(yaw_rate, 1),
            "dir_speed": round(c.get("route_state", {}).get("dir_speed", 0.0), 1),
            "floor_z": round(fz, 1) if fz is not None else "",
            "height_above_floor": round(haf, 1) if haf is not None else "",
            "over_void": int(over_void),
            "dist_to_rl": round(drl, 1),
            "replay_cursor": c.get("replay_state", {}).get("cursor", ""),
            "divergence_qu": round(c.get("replay_state", {}).get("divergence_qu", 0.0), 1),
        })

    with open(run_dir / "trace.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLS)
        w.writeheader()
        w.writerows(rows)

    summary = {
        "run_id": run_id,
        "records": len(rows),
        "duration_s": round(rows[-1]["t"] - rows[0]["t"], 2),
        "max_vh": max(r["vh"] for r in rows),
        "pct_onground": round(100.0 * sum(r["onground"] for r in rows) / len(rows), 1),
        "closest_dist_to_rl": round(min(r["dist_to_rl"] for r in rows), 1),
        "frames_over_void": sum(r["over_void"] for r in rows),
    }
    (run_dir / "trace_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    s = build(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else DEFAULT_BSP)
    print(json.dumps(s, indent=2))


if __name__ == "__main__":
    main()
