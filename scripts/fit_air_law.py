#!/usr/bin/env python3
"""Pool the corpus (state,action) NDJSON into the velocity-relative AIR-LAW table
that mode 19 will follow, plus the landing/jump-cadence stats.

For each AIRBORNE, moving frame we compute the control quantities that drive QW
air-accel, all VELOCITY-RELATIVE (map-agnostic, so the law transfers off the
source maps):
  |v|       = horizontal speed
  rotation  = signed angle from velocity-heading to WISHDIR-heading (wishdir from
              view-yaw + fwd/side). |rotation| sets cs = |v|*cos(rotation), and the
              per-air-frame |v|^2 gain = 900 - cs^2 (max at cs=0 / rotation=+-90).
  lvm       = signed angle from velocity-heading to VIEW-yaw (the look lead)

Outputs a table binned by |v|: median |rotation|, implied cs, and the serpentine
flip cadence + jump-on-contact stats -- the retention behaviour mode 19 imitates.
"""
from __future__ import annotations
import logging
import argparse, json, math, statistics, sys
from pathlib import Path



LOGGER = logging.getLogger(__name__)
def wrap180(d):
    return (d + 180.0) % 360.0 - 180.0


def frame_quantities(row):
    vx, vy = row["v"][0], row["v"][1]
    hsp = math.hypot(vx, vy)
    if hsp < 1e-6:
        return None
    yaw = row["a"][1]
    fwd, side = row["m"][0], row["m"][1]
    a = math.radians(yaw)
    cy, sy = math.cos(a), math.sin(a)
    # forward=(cy,sy), right=(sy,-cy); wishvel = forward*fwd + right*side
    wvx = cy * fwd + sy * side
    wvy = sy * fwd - cy * side
    wsp = math.hypot(wvx, wvy)
    vhead = math.degrees(math.atan2(vy, vx))
    rotation = None
    if wsp > 1e-6:
        whead = math.degrees(math.atan2(wvy, wvx))
        rotation = wrap180(whead - vhead)
    lvm = wrap180(yaw - vhead)
    cs = hsp * math.cos(math.radians(rotation)) if rotation is not None else None
    return {"hsp": hsp, "rotation": rotation, "lvm": lvm, "cs": cs,
            "side": side, "fwd": fwd, "jump": bool(int(row["buttons"]) & 2),
            "onground": bool(row["onground"])}


def load_demo(path):
    rows = []
    with open(path) as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--ndjson-dir", type=Path, required=True)
    ap.add_argument("--manifest", type=Path, default=None, help="manifest.json to filter by peak_hspeed")
    ap.add_argument("--min-peak", type=float, default=700.0)
    ap.add_argument("--max-peak", type=float, default=1500.0, help="drop corrupt demos above this peak")
    ap.add_argument("--min-air-speed", type=float, default=150.0)
    ap.add_argument("--max-air-speed", type=float, default=1500.0, help="drop corrupt per-frame speeds above this")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)

    files = sorted(args.ndjson_dir.glob("*.ndjson"))
    keep = None
    if args.manifest and args.manifest.exists():
        man = json.loads(args.manifest.read_text())
        keep = {m["ndjson"] for m in man if m.get("ok")
                and args.min_peak <= m.get("peak_hspeed", 0) <= args.max_peak}
        files = [f for f in files if f.name in keep]

    # per-|v| bins
    BIN = 50
    bins = {}  # b -> list of |rotation|, cs
    flip_intervals = []      # serpentine: time between rotation-sign flips (frames @ ~77fps)
    hop_periods = []         # frames between jump presses
    land_events = land_rejump = 0
    n_air = n_demos = 0

    for fp in files:
        rows = load_demo(fp)
        if not rows:
            continue
        n_demos += 1
        prev_sign = 0
        frames_since_flip = 0
        last_jump_frame = None
        prev_onground = True
        prev_jump = False
        for idx, r in enumerate(rows):
            q = frame_quantities(r)
            if q is None:
                continue
            # landing -> rejump tracking (works on all frames)
            if (not prev_onground) and q["onground"]:
                land_events += 1
                # rejump if jump pressed within this or next 2 frames
                for k in range(idx, min(idx + 3, len(rows))):
                    if int(rows[k]["buttons"]) & 2:
                        land_rejump += 1
                        break
            prev_onground = q["onground"]
            # hop cadence = frames between jump-press EDGES; a held +jump is ONE press,
            # not a new hop every ~3 frames (Codex P2 fix).
            if q["jump"] and not prev_jump:
                if last_jump_frame is not None:
                    hop_periods.append(idx - last_jump_frame)
                last_jump_frame = idx
            prev_jump = q["jump"]

            if (q["onground"] or q["hsp"] < args.min_air_speed
                    or q["hsp"] > args.max_air_speed or q["rotation"] is None):
                continue
            n_air += 1
            b = int(q["hsp"] // BIN) * BIN
            bins.setdefault(b, {"rot": [], "cs": []})
            bins[b]["rot"].append(abs(q["rotation"]))
            bins[b]["cs"].append(q["cs"])
            # serpentine flip cadence on rotation sign
            sign = 1 if q["rotation"] > 5 else (-1 if q["rotation"] < -5 else 0)
            frames_since_flip += 1
            if sign != 0 and prev_sign != 0 and sign != prev_sign:
                flip_intervals.append(frames_since_flip)
                frames_since_flip = 0
            if sign != 0:
                prev_sign = sign

    table = {}
    for b in sorted(bins):
        rot = bins[b]["rot"]; cs = bins[b]["cs"]
        if len(rot) < 20:
            continue
        table[b] = {
            "n": len(rot),
            "rot_med": round(statistics.median(rot), 1),
            "rot_p25": round(sorted(rot)[len(rot)//4], 1),
            "rot_p75": round(sorted(rot)[3*len(rot)//4], 1),
            "cs_med": round(statistics.median(cs), 1),
        }

    result = {
        "n_demos": n_demos, "n_air_frames": n_air,
        "filter": {"min_peak": args.min_peak, "min_air_speed": args.min_air_speed},
        "air_law_by_speed": table,
        "serpentine_flip_frames": {
            "n": len(flip_intervals),
            "med": round(statistics.median(flip_intervals), 1) if flip_intervals else None,
            "p10": sorted(flip_intervals)[len(flip_intervals)//10] if flip_intervals else None,
            "p90": sorted(flip_intervals)[9*len(flip_intervals)//10] if flip_intervals else None,
        },
        "hop_period_frames": {
            "n": len(hop_periods),
            "med": round(statistics.median(hop_periods), 1) if hop_periods else None,
            "p10": sorted(hop_periods)[len(hop_periods)//10] if hop_periods else None,
            "p90": sorted(hop_periods)[9*len(hop_periods)//10] if hop_periods else None,
        },
        "landing_rejump_rate": round(land_rejump / land_events, 3) if land_events else None,
        "landings": land_events,
    }
    print(json.dumps(result, indent=1))
    if args.out:
        args.out.write_text(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
