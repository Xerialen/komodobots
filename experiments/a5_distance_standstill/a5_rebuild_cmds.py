#!/usr/bin/env python3
"""A5 #118: rebuild getspeed.cmds with TIME-ALIGNED state<->cmd pairing.

Why this exists (the bug, plain words): build_replay_command_file.py pairs
the demo's input stream (dem_cmd, one per client frame, COMPLETE: 2145) with
the state stream (svc_playerinfo, 2104 — the server DROPPED 41 frames) by
plain zip order. Every dropped state shifts all later rows: by the winning
attempt the inputs printed next to a position are ~0.2 s stale. The dm3
validation demo had zero drops, so the bug never showed there.

Fix: both streams carry demo time. In a clean stretch state record j arrives
a fixed ~1 frame after cmd j is written; measure that offset on the head of
the streams, then match each state to the nearest cmd time. Cmds with no
state (the dropped frames) get a linearly interpolated reference origin /
velocity and are listed in the sidecar JSON (replay treats them as inputs
like any other; they are only weaker as a comparison REFERENCE).

Output (next to this script):
  getspeed-aligned.cmds   komodobots.replay.v1, one row per CMD (complete)
  alignment-meta.json     offset, matching stats, dropped cmd indices

Usage: python a5_rebuild_cmds.py [--demo <getspeed.qwd>]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
for p in (str(REPO), str(REPO / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from tools.qwd_usercmd import qwd_usercmd  # noqa: E402
import probe_qwd_route_applicability as probe  # noqa: E402

REPLAY_FILE_SCHEMA = "komodobots.replay.v1"
HEAD_N = 40              # offset estimation window (clean head of both streams)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", default=r"C:\nQuake\qw\matchinfo\demos\getspeed.qwd")
    ap.add_argument("--out", default=str(HERE / "getspeed-aligned.cmds"))
    ap.add_argument("--meta", default=str(HERE / "alignment-meta.json"))
    ap.add_argument("--shift", type=int, default=0,
                    help="integer pipeline latency L: state j pairs with cmd "
                         "(nearest-time + L). The replay row convention needs "
                         "state BEFORE cmd; L absorbs the demo's fixed "
                         "cmd->state lag. Determined empirically (anchored "
                         "replay error, see alignment-meta).")
    args = ap.parse_args()

    data = Path(args.demo).read_bytes()
    parsed = qwd_usercmd.parse_qwd_bytes(data, source_path=Path(args.demo))
    cmds = parsed.commands
    states, serverdata, scan = probe.extract_playerinfo_samples(data)

    # 1. offset: state j trails cmd j by ~1 frame in the un-dropped head
    head = min(HEAD_N, len(cmds), len(states))
    offset = statistics.median(states[j].time_s - cmds[j].time_s
                               for j in range(head))

    # 2. match each state to the nearest cmd time (offset-corrected),
    #    enforcing strictly increasing cmd indices
    cmd_times = [c.time_s for c in cmds]
    state_for_cmd = {}
    k_lo = 0
    ambiguous = 0
    max_resid = 0.0
    for j, s in enumerate(states):
        target = s.time_s - offset
        # advance: nearest cmd index by time
        k = min(range(max(k_lo, 0), len(cmds)),
                key=lambda i: abs(cmd_times[i] - target))
        resid = abs(cmd_times[k] - target)
        max_resid = max(max_resid, resid)
        if resid > 0.0065:      # half a 13 ms frame: matching is ambiguous
            ambiguous += 1
        if k in state_for_cmd:  # two states claiming one cmd: keep the closer
            prev_j = state_for_cmd[k]
            prev_resid = abs(cmd_times[k] - (states[prev_j].time_s - offset))
            if resid < prev_resid:
                state_for_cmd[k] = j
        else:
            state_for_cmd[k] = j
        k_lo = k                # monotonic
    if args.shift:
        state_for_cmd = {k + args.shift: j for k, j in state_for_cmd.items()
                         if 0 <= k + args.shift < len(cmds)}
    dropped = [k for k in range(len(cmds)) if k not in state_for_cmd]

    # 3. interpolate reference states for dropped cmds
    rows = []
    for k, c in enumerate(cmds):
        if k in state_for_cmd:
            s = states[state_for_cmd[k]]
            origin = list(s.origin)
            velocity = list(s.velocity)
            interp = False
        else:
            # nearest matched neighbours
            a = next((i for i in range(k - 1, -1, -1) if i in state_for_cmd), None)
            b = next((i for i in range(k + 1, len(cmds)) if i in state_for_cmd), None)
            if a is None or b is None:
                src = a if a is not None else b
                s = states[state_for_cmd[src]]
                origin, velocity = list(s.origin), list(s.velocity)
            else:
                sa, sb = states[state_for_cmd[a]], states[state_for_cmd[b]]
                f = (k - a) / (b - a)
                origin = [sa.origin[i] + f * (sb.origin[i] - sa.origin[i])
                          for i in range(3)]
                velocity = [round(sa.velocity[i] + f * (sb.velocity[i] - sa.velocity[i]))
                            for i in range(3)]
            interp = True
        pitch, yaw, roll = c.view_angles
        rows.append({
            "msec": int(c.msec), "origin": origin, "velocity": velocity,
            "angles": [float(pitch), float(yaw), float(roll)],
            "move": [int(c.forwardmove), int(c.sidemove), int(c.upmove)],
            "buttons": int(c.buttons), "interp": interp,
        })

    sha = hashlib.sha256(data).hexdigest()
    header = (f"# {REPLAY_FILE_SCHEMA} demo={Path(args.demo).name} "
              f"frames={len(rows)} sha256={sha} "
              f"fps={parsed.header['command_rate_fps']} aligned=time")
    lines = [header]
    for f in rows:
        ox, oy, oz = f["origin"]
        vx, vy, vz = f["velocity"]
        pitch, yaw, roll = f["angles"]
        fwd, side, up = f["move"]
        lines.append(f"{f['msec']} {ox:.3f} {oy:.3f} {oz:.3f} {vx} {vy} {vz} "
                     f"{pitch:.4f} {yaw:.4f} {roll:.4f} {fwd} {side} {up} {f['buttons']}")
    Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")

    meta = {
        "demo": str(args.demo), "sha256": sha,
        "n_cmds": len(cmds), "n_states": len(states),
        "shift": args.shift,
        "offset_s": round(offset, 6),
        "max_match_residual_s": round(max_resid, 6),
        "ambiguous_matches_gt_half_frame": ambiguous,
        "dropped_cmd_indices": dropped,
        "n_dropped": len(dropped),
        "map_level": serverdata.level_name if serverdata else None,
        "playernum": serverdata.playernum if serverdata else None,
        "scan": scan,
    }
    Path(args.meta).write_text(json.dumps(meta, indent=1))
    print(f"cmds={len(cmds)} states={len(states)} offset={offset*1000:.1f}ms "
          f"max_resid={max_resid*1000:.1f}ms ambiguous={ambiguous}")
    print(f"dropped cmd rows (interpolated reference): {len(dropped)}")
    print(f"wrote {args.out}")
    print(f"wrote {args.meta}")


if __name__ == "__main__":
    main()
