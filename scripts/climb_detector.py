#!/usr/bin/env python3
"""Stairs/climb detector for komodobots lab runs (Phase 0.4).

Segments "climb periods" from a run's trace.csv (+ optionally
moveprobe-commands.json for jump buttons and waterlevel): contiguous spans
where the GROUND-CONTACT height rises > 40 qu net while xy-progressing,
excluding teleporter jumps (>100 qu single-tick origin discontinuities) and
water (waterlevel >= 2).

Why ground-contact height and not raw z: a 43 qu z rise in 0.33 s is just a
jump apex over a flat floor (and the mode-23 bouncing bot spends most ticks
airborne with height_above_floor up to ~77 qu), so the detector chains
CONTACT events -- ticks with onground==1 or height_above_floor < 4 -- and
tracks gz = z - height_above_floor (the floor under the feet). The trace's
onground flag alone is unreliable for the server-side bot (often 0 on real
landings), hence the height_above_floor fallback.

Jump inputs: buttons bit 2 == +jump, VERIFIED on run 20260609T193831Z (all 64
grounded rising edges of buttons&2 are followed within 3 ticks by vz > 200,
the QW jump impulse). n_jump_inputs counts rising edges inside the climb span.

Output JSON: {"run": ..., "climbs": [{t_start, t_end, z_gain, xy_dist,
n_jump_inputs, start_xyz, end_xyz}, ...]}

Usage:
  python climb_detector.py <run_id> [--out FILE]
  python climb_detector.py <path/to/trace.csv> [--commands FILE] [--out FILE]
"""

from __future__ import annotations

import logging
import csv
import json
import math
import sys
from pathlib import Path


LOGGER = logging.getLogger(__name__)
REPO = Path(__file__).resolve().parent.parent
RUNS = REPO / "artifacts" / "lab-runs"

# ---------------------------------------------------------------------------
# LOCKED thresholds -- tuned ONCE (2026-06-09) against the hand labels in
# artifacts/metrics-lock/labels.json (runs 20260609T193831Z mode-23 and
# 20260609T193434Z vanilla) and then frozen. Detector-vs-label agreement at
# lock time: 1/1 climb detected in the vanilla run (IoU ~0.9 on the SE
# staircase walk), 0/0 in the mode-23 run (its mid-bowl bunnyhop attempts
# net only +25..+32 qu, correctly below MIN_Z_GAIN_QU; its water-pit ascent
# and teleporter entry are correctly excluded). Do not retune without
# re-labeling; see artifacts/metrics-lock/labels.json "derivation".
# ---------------------------------------------------------------------------
CONTACT_HAF_MAX = 4.0    # LOCKED: tick is a ground contact if onground==1 or haf < this
MAX_CONTACT_GAP_S = 1.5  # LOCKED: max airborne time between contacts in one climb
MAX_DIP_QU = 16.0        # LOCKED: contact may sit at most this far below the chain's max gz
MIN_Z_GAIN_QU = 40.0     # LOCKED: net contact-height gain that defines a climb (spec)
MIN_XY_DIST_QU = 50.0    # LOCKED: minimum xy path length (the "while xy-progressing" gate)
TELEPORT_QU = 100.0      # LOCKED: single-tick origin discontinuity = teleport (spec)
WATER_LEVEL_EXCLUDE = 2  # LOCKED: ticks with waterlevel >= this break a climb (swimming)
START_TRIM_TOL_QU = 2.0  # LOCKED: trim flat lead-in: start at last contact within this of the chain's base


def load_trace(path):
    rows = []
    for r in csv.DictReader(open(path)):
        rows.append({k: (float(v) if v != "" else None) for k, v in r.items()})
    return rows


def load_commands(path):
    return json.load(open(path))["commands"]


def detect_climbs(rows, cmds=None):
    """Return the list of climb periods (see module docstring)."""
    n = len(rows)
    if cmds is not None and len(cmds) != n:
        # alignment is 1:1 by construction (build_trace.py consumes the same
        # command log); refuse to silently mis-attribute buttons/water.
        raise SystemExit(f"trace ({n}) and commands ({len(cmds)}) tick counts differ")

    waterlevel = [c["water_state"]["waterlevel"] for c in cmds] if cmds else [0] * n
    jumpbit = [1 if int(c["buttons"]) & 2 else 0 for c in cmds] if cmds else [0] * n

    teleport = [False] * n
    for i in range(1, n):
        d = (math.hypot(rows[i]["x"] - rows[i - 1]["x"], rows[i]["y"] - rows[i - 1]["y"])
             + abs(rows[i]["z"] - rows[i - 1]["z"]))
        teleport[i] = d > TELEPORT_QU

    # ground-contact events
    contacts = []
    for i, r in enumerate(rows):
        haf = r["height_above_floor"]
        if int(r["onground"]) == 1 or (haf is not None and haf < CONTACT_HAF_MAX):
            contacts.append((i, r["z"] - (haf or 0.0)))

    # chain contacts: stop at long airborne gaps, teleports, water, or dips
    # below (chain max - MAX_DIP_QU)
    chains, cur = [], []
    for i, gz in contacts:
        if cur:
            p, _ = cur[-1]
            cmax = max(g for _, g in cur)
            ok = (rows[i]["t"] - rows[p]["t"] <= MAX_CONTACT_GAP_S
                  and not any(teleport[j] for j in range(p + 1, i + 1))
                  and not any(waterlevel[j] >= WATER_LEVEL_EXCLUDE for j in range(p, i + 1))
                  and gz > cmax - MAX_DIP_QU)
            if not ok:
                chains.append(cur)
                cur = []
        cur.append((i, gz))
    if cur:
        chains.append(cur)

    climbs = []
    for ch in chains:
        if len(ch) < 2:
            continue
        # end the climb at the highest contact reached
        peak = max(range(len(ch)), key=lambda k: ch[k][1])
        base_gz = min(g for _, g in ch[:peak + 1]) if peak else ch[0][1]
        # trim the flat lead-in: start at the LAST contact still at base height
        start = 0
        for k in range(peak + 1):
            if ch[k][1] <= base_gz + START_TRIM_TOL_QU:
                start = k
        a, ga = ch[start]
        b, gb = ch[peak]
        z_gain = gb - ga
        if z_gain <= MIN_Z_GAIN_QU:
            continue
        xy = sum(math.hypot(rows[m]["x"] - rows[m - 1]["x"], rows[m]["y"] - rows[m - 1]["y"])
                 for m in range(a + 1, b + 1))
        if xy < MIN_XY_DIST_QU:
            continue
        jumps, prev = 0, 0
        for j in range(a, b + 1):
            if jumpbit[j] and not prev:
                jumps += 1
            prev = jumpbit[j]
        climbs.append({
            "t_start": round(rows[a]["t"], 3),
            "t_end": round(rows[b]["t"], 3),
            "z_gain": round(z_gain, 1),
            "xy_dist": round(xy, 1),
            "n_jump_inputs": jumps,
            "start_xyz": [round(rows[a]["x"], 1), round(rows[a]["y"], 1), round(rows[a]["z"], 1)],
            "end_xyz": [round(rows[b]["x"], 1), round(rows[b]["y"], 1), round(rows[b]["z"], 1)],
        })
    return climbs


def main():
    args = sys.argv[1:]
    out = None
    cmds_path = None
    pos = []
    i = 0
    while i < len(args):
        if args[i] == "--out":
            out = Path(args[i + 1]); i += 2
        elif args[i] == "--commands":
            cmds_path = Path(args[i + 1]); i += 2
        else:
            pos.append(args[i]); i += 1
    if not pos:
        print(__doc__)
        sys.exit(1)
    target = pos[0]
    if target.endswith(".csv"):
        trace_path = Path(target)
        run = trace_path.parent.name
        if cmds_path is None:
            cand = trace_path.parent / "moveprobe-commands.json"
            cmds_path = cand if cand.exists() else None
    else:
        run = target
        trace_path = RUNS / run / "trace.csv"
        if cmds_path is None:
            cand = RUNS / run / "moveprobe-commands.json"
            cmds_path = cand if cand.exists() else None
    rows = load_trace(trace_path)
    cmds = load_commands(cmds_path) if cmds_path else None
    if cmds is None:
        print("WARNING: no moveprobe-commands.json; water exclusion and jump "
              "counts disabled", file=sys.stderr)
    result = {"run": run, "climbs": detect_climbs(rows, cmds)}
    text = json.dumps(result, indent=2)
    if out:
        out.write_text(text + "\n")
        print(f"wrote {out} ({len(result['climbs'])} climbs)")
    else:
        print(text)


if __name__ == "__main__":
    main()
