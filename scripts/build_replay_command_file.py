#!/usr/bin/env python3
"""Build an open-loop replay command file from a human POV .qwd demo.

The KTX moveprobe replay mode (mode 10) needs the exact human per-frame inputs
plus the human trajectory, in a compact text form it can read with
`trap_FS_OpenFile`/`trap_FS_ReadFile`. A cvar is far too small for a full trick
(~700 frames, ~10 KB), so the data goes in a file and only the filename rides a
cvar.

Each output line is one replay frame:

    msec ox oy oz vx vy vz pitch yaw roll fwd side up buttons

- `msec`            command frame duration (ms), used to resample onto the server tick
- `ox oy oz`        human origin at that frame (qu); frame 0 is the snap state and
                    every frame is the divergence reference the live run logs against
- `vx vy vz`        human velocity (qu/s); frame 0 is the snap velocity
- `pitch yaw roll`  human view angles (deg) to drive the bot's desired_angle
- `fwd side up`      human movement command
- `buttons`         human buttons (replay uses the jump bit)

The command stream comes from `tools/qwd_usercmd` (ground truth: ezQuake
`CL_WriteDemoCmd`). The per-frame origin/velocity come from the anchored
`svc_playerinfo` recovery in `probe_qwd_route_applicability`, paired to commands
by frame order exactly as that probe pairs them.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from tools.qwd_usercmd import qwd_usercmd
import probe_qwd_route_applicability as probe


SCHEMA = "komodobots.replay_build.v1"
REPLAY_FILE_SCHEMA = "komodobots.replay.v1"
# Mirrors MOVEPROBE_REPLAY_MAX_FRAMES in the KTX patch. The longest local dm3
# trick (dm3_water_rjumps.qwd) is 2753 frames, so 3000 leaves headroom.
MAX_REPLAY_FRAMES = 3000

DEFAULT_DEMO = (
    Path("C:/Users/benya/projects/quakeworld/data/quake-development/clients")
    / "xerialqw-bench"
    / "qw"
    / "matchinfo"
    / "demos"
    / "tricks"
    / "dm3_sng_to_rl.qwd"
)


def build_replay_frames(demo: Path) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Return (frames, meta) paired by frame order, mirroring the route probe."""
    data = demo.read_bytes()
    parsed = qwd_usercmd.parse_qwd_bytes(data, source_path=demo)
    commands = parsed.commands
    states, serverdata, _scan = probe.extract_playerinfo_samples(data)

    paired_count = min(len(commands), len(states))
    coverage = paired_count / len(commands) if commands else 0.0

    frames: list[dict[str, object]] = []
    for command, state in zip(commands, states):
        pitch, yaw, roll = command.view_angles
        frames.append(
            {
                "msec": int(command.msec),
                "origin": [float(state.origin[0]), float(state.origin[1]), float(state.origin[2])],
                "velocity": [int(state.velocity[0]), int(state.velocity[1]), int(state.velocity[2])],
                "angles": [float(pitch), float(yaw), float(roll)],
                "move": [int(command.forwardmove), int(command.sidemove), int(command.upmove)],
                "buttons": int(command.buttons),
                # Ground-state carried for the imitation training set (separate from the
                # fixed 14-col replay .cmds, which render_replay_file leaves unchanged).
                # onground/pm_code separate the air-accel regime from the landing regime
                # the retention work hinges on.
                "onground": bool(state.onground),
                "pm_code": int(state.pm_code),
            }
        )

    meta = {
        "schema": SCHEMA,
        "demo": demo.name,
        "source_sha256": parsed.header["source_sha256"],
        "command_frames": len(commands),
        "state_frames": len(states),
        "paired_frames": paired_count,
        "paired_coverage": round(coverage, 3),
        "command_rate_fps": parsed.header["command_rate_fps"],
        "total_duration_s": parsed.header["total_duration_s"],
        "frame0": frames[0] if frames else None,
        "map_level": serverdata.level_name if serverdata else None,
        "playernum": serverdata.playernum if serverdata else None,
        "exceeds_max_replay_frames": paired_count > MAX_REPLAY_FRAMES,
    }
    return frames, meta


def render_replay_file(frames: list[dict[str, object]], meta: dict[str, object]) -> str:
    header = (
        f"# {REPLAY_FILE_SCHEMA} demo={meta['demo']} frames={len(frames)} "
        f"sha256={meta['source_sha256']} fps={meta['command_rate_fps']}"
    )
    lines = [header]
    for f in frames:
        ox, oy, oz = f["origin"]
        vx, vy, vz = f["velocity"]
        pitch, yaw, roll = f["angles"]
        fwd, side, up = f["move"]
        lines.append(
            f"{f['msec']} {ox:.3f} {oy:.3f} {oz:.3f} {vx} {vy} {vz} "
            f"{pitch:.4f} {yaw:.4f} {roll:.4f} {fwd} {side} {up} {f['buttons']}"
        )
    return "\n".join(lines) + "\n"


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a KTX open-loop replay command file from a POV .qwd.")
    parser.add_argument("--demo", type=Path, default=DEFAULT_DEMO, help="Human POV .qwd to replay.")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Replay .cmds output path. Defaults to artifacts/replay/<demo_stem>.cmds.",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=None,
        help="Build-evidence JSON path. Defaults to artifacts/replay/replay-build-<demo_stem>.json.",
    )
    return parser.parse_args(list(argv))


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    demo = args.demo
    stem = demo.stem
    out_cmds = args.output or (REPO_ROOT / "artifacts" / "replay" / f"{stem}.cmds")
    out_json = args.output_json or (REPO_ROOT / "artifacts" / "replay" / f"replay-build-{stem}.json")

    frames, meta = build_replay_frames(demo)
    if not frames:
        print(f"No replay frames built from {demo}", file=sys.stderr)
        return 1
    if meta["exceeds_max_replay_frames"]:
        print(
            f"WARNING: {meta['paired_frames']} frames exceeds MAX_REPLAY_FRAMES={MAX_REPLAY_FRAMES}; "
            "raise the KTX buffer before replaying this demo.",
            file=sys.stderr,
        )

    out_cmds.parent.mkdir(parents=True, exist_ok=True)
    out_cmds.write_text(render_replay_file(frames, meta), encoding="utf-8")
    meta_out = dict(meta)
    try:
        meta_out["output_cmds"] = out_cmds.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        meta_out["output_cmds"] = str(out_cmds)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(meta_out, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"Wrote replay command file: {out_cmds} ({len(frames)} frames, coverage {meta['paired_coverage']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
