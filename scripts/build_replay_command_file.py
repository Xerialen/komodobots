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
`svc_playerinfo` recovery in `probe_qwd_route_applicability`. Commands and
states are matched by demo time by default. This avoids the old plain-zip
failure mode where a dropped state frame shifted every later row.
"""

from __future__ import annotations

import argparse
import bisect
import json
import math
import sys
from pathlib import Path
from typing import Iterable, Sequence


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


def angle_delta_deg(a: float, b: float) -> float:
    """Smallest absolute angle difference in degrees."""
    return abs(((a - b + 180.0) % 360.0) - 180.0)


def percentile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * q
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[low]
    weight = rank - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


def rounded(value: float | None, digits: int = 6) -> float | None:
    if value is None:
        return None
    return round(value, digits)


def summarize_values(values: Sequence[float], *, digits: int = 6) -> dict[str, object]:
    return {
        "count": len(values),
        "min": rounded(min(values) if values else None, digits),
        "p50": rounded(percentile(values, 0.50), digits),
        "p95": rounded(percentile(values, 0.95), digits),
        "max": rounded(max(values) if values else None, digits),
    }


def summarize_msec(commands: Sequence[qwd_usercmd.UsercmdRecord]) -> dict[str, object]:
    values = [int(command.msec) for command in commands]
    counts = {str(value): values.count(value) for value in sorted(set(values))}
    summary = summarize_values([float(value) for value in values], digits=3)
    summary["counts"] = counts
    return summary


def summarize_angle_channels(commands: Sequence[qwd_usercmd.UsercmdRecord]) -> dict[str, object]:
    axes = {"pitch": 0, "yaw": 1, "roll": 2}
    out: dict[str, object] = {}
    for name, index in axes.items():
        deltas = [
            angle_delta_deg(command.view_angles[index], command.cmd_angles[index])
            for command in commands
        ]
        summary = summarize_values(deltas, digits=6)
        summary["over_0_01_deg"] = sum(value > 0.01 for value in deltas)
        out[name] = summary
    return out


def nearest_time_index(times: Sequence[float], target: float, start: int = 0) -> tuple[int, float]:
    if not times:
        raise ValueError("cannot match against an empty time sequence")
    start = max(0, min(start, len(times) - 1))
    pos = bisect.bisect_left(times, target, lo=start)
    candidates = []
    if pos < len(times):
        candidates.append(pos)
    if pos > 0:
        candidates.append(pos - 1)
    if not candidates:
        candidates.append(len(times) - 1)
    index = min(candidates, key=lambda i: abs(times[i] - target))
    return index, abs(times[index] - target)


def estimate_state_cmd_offset_s(
    commands: Sequence[qwd_usercmd.UsercmdRecord],
    states: Sequence[probe.PlayerInfoSample],
    *,
    window: int = 40,
) -> float:
    head = min(window, len(commands), len(states))
    if head == 0:
        return 0.0
    deltas = [states[index].time_s - commands[index].time_s for index in range(head)]
    return float(percentile(deltas, 0.50) or 0.0)


def match_states_by_time(
    commands: Sequence[qwd_usercmd.UsercmdRecord],
    states: Sequence[probe.PlayerInfoSample],
    *,
    state_shift: int = 0,
    offset_s: float | None = None,
) -> tuple[dict[int, int], dict[str, object]]:
    """Return command-index -> state-index using QWD time, not row order.

    `state_shift` intentionally remains explicit. A5/getspeed used shift=2 after
    an anchored replay scan; other demos should record the chosen shift in the
    sidecar rather than inheriting that value invisibly.
    """
    if offset_s is None:
        offset_s = estimate_state_cmd_offset_s(commands, states)
    cmd_times = [command.time_s for command in commands]
    state_for_cmd: dict[int, int] = {}
    residual_for_cmd: dict[int, float] = {}
    residuals: list[float] = []
    ambiguous = 0
    search_from = 0

    for state_index, state in enumerate(states):
        if not cmd_times:
            break
        target = state.time_s - offset_s
        command_index, residual = nearest_time_index(cmd_times, target, start=search_from)
        if residual > 0.0065:
            ambiguous += 1
        existing = state_for_cmd.get(command_index)
        if existing is None or residual < residual_for_cmd[command_index]:
            state_for_cmd[command_index] = state_index
            residual_for_cmd[command_index] = residual
        search_from = command_index
        residuals.append(residual)

    if state_shift:
        shifted: dict[int, int] = {}
        shifted_residuals: dict[int, float] = {}
        for command_index, state_index in state_for_cmd.items():
            shifted_index = command_index + state_shift
            if 0 <= shifted_index < len(commands):
                shifted[shifted_index] = state_index
                shifted_residuals[shifted_index] = residual_for_cmd[command_index]
        state_for_cmd = shifted
        residual_for_cmd = shifted_residuals

    matched = sorted(state_for_cmd)
    missing = [index for index in range(len(commands)) if index not in state_for_cmd]
    meta = {
        "method": "time",
        "state_shift": state_shift,
        "estimated_offset_s": round(offset_s, 6),
        "matched_state_frames": len(matched),
        "unmatched_command_frames": len(missing),
        "dropped_cmd_indices": missing,
        "max_match_residual_s": rounded(max(residuals) if residuals else None, 6),
        "match_residual_abs_s": summarize_values(residuals, digits=6),
        "ambiguous_matches_gt_half_frame": ambiguous,
    }
    return state_for_cmd, meta


def lerp(a: float, b: float, frac: float) -> float:
    return a + frac * (b - a)


def interpolated_reference(
    command_index: int,
    commands: Sequence[qwd_usercmd.UsercmdRecord],
    states: Sequence[probe.PlayerInfoSample],
    state_for_cmd: dict[int, int],
) -> tuple[list[float], list[int], bool, bool, int, str]:
    """Return origin, velocity, onground, solid, pm_code, source_kind."""
    state_index = state_for_cmd.get(command_index)
    if state_index is not None:
        state = states[state_index]
        return (
            [float(state.origin[0]), float(state.origin[1]), float(state.origin[2])],
            [int(state.velocity[0]), int(state.velocity[1]), int(state.velocity[2])],
            bool(state.onground),
            bool(state.solid),
            int(state.pm_code),
            "matched",
        )

    matched = sorted(state_for_cmd)
    prev_command = next((index for index in reversed(matched) if index < command_index), None)
    next_command = next((index for index in matched if index > command_index), None)

    if prev_command is None and next_command is None:
        return [0.0, 0.0, 0.0], [0, 0, 0], False, False, 0, "missing"
    if prev_command is None:
        state = states[state_for_cmd[next_command]]
        return (
            [float(state.origin[0]), float(state.origin[1]), float(state.origin[2])],
            [int(state.velocity[0]), int(state.velocity[1]), int(state.velocity[2])],
            bool(state.onground),
            bool(state.solid),
            int(state.pm_code),
            "nearest_next",
        )
    if next_command is None:
        state = states[state_for_cmd[prev_command]]
        return (
            [float(state.origin[0]), float(state.origin[1]), float(state.origin[2])],
            [int(state.velocity[0]), int(state.velocity[1]), int(state.velocity[2])],
            bool(state.onground),
            bool(state.solid),
            int(state.pm_code),
            "nearest_previous",
        )

    prev_state = states[state_for_cmd[prev_command]]
    next_state = states[state_for_cmd[next_command]]
    denom = commands[next_command].time_s - commands[prev_command].time_s
    if denom <= 0:
        frac = (command_index - prev_command) / max(1, next_command - prev_command)
    else:
        frac = (commands[command_index].time_s - commands[prev_command].time_s) / denom
    frac = max(0.0, min(1.0, frac))
    origin = [
        lerp(float(prev_state.origin[axis]), float(next_state.origin[axis]), frac)
        for axis in range(3)
    ]
    velocity = [
        round(lerp(float(prev_state.velocity[axis]), float(next_state.velocity[axis]), frac))
        for axis in range(3)
    ]
    # onground/solid/pm_code are DISCRETE flags — you can't lerp a boolean, so carry the
    # NEAREST matched frame's value (the endpoint this command's time is closer to), not a
    # conservative `prev AND next`. The old AND mashed onground toward False on every
    # boundary tick (a single airborne neighbour zeroed an otherwise-grounded run); nearest
    # keeps the flag whichever way the frame actually leans. (This path only matters when a
    # source stream carries a real ground flag; the dm3 catalog re-derives onground
    # geometrically downstream, so this is correctness hardening, not the #316 fix.)
    near = prev_state if frac < 0.5 else next_state
    onground = bool(near.onground)
    solid = bool(near.solid)
    pm_code = int(near.pm_code)
    return origin, velocity, onground, solid, pm_code, "interpolated"


def zip_states_to_commands(
    commands: Sequence[qwd_usercmd.UsercmdRecord],
    states: Sequence[probe.PlayerInfoSample],
) -> tuple[dict[int, int], dict[str, object]]:
    paired_count = min(len(commands), len(states))
    time_deltas = [states[index].time_s - commands[index].time_s for index in range(paired_count)]
    abs_deltas = [abs(value) for value in time_deltas]
    unsafe = len(commands) != len(states) or (max(abs_deltas) if abs_deltas else 0.0) > 0.020
    return (
        {index: index for index in range(paired_count)},
        {
            "method": "zip",
            "state_shift": 0,
            "matched_state_frames": paired_count,
            "unmatched_command_frames": max(0, len(commands) - paired_count),
            "dropped_cmd_indices": list(range(paired_count, len(commands))),
            "zip_time_delta_s": summarize_values(time_deltas, digits=6),
            "zip_time_delta_abs_s": summarize_values(abs_deltas, digits=6),
            "unsafe_zip_pairing": unsafe,
        },
    )


def build_replay_frames(
    demo: Path,
    *,
    alignment: str = "time",
    state_shift: int = 0,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Return (frames, meta), one replay row per command."""
    data = demo.read_bytes()
    parsed = qwd_usercmd.parse_qwd_bytes(data, source_path=demo)
    commands = parsed.commands
    states, serverdata, scan = probe.extract_playerinfo_samples(data)

    if alignment == "zip":
        state_for_cmd, alignment_meta = zip_states_to_commands(commands, states)
    elif alignment == "time":
        state_for_cmd, alignment_meta = match_states_by_time(
            commands,
            states,
            state_shift=state_shift,
        )
    else:
        raise ValueError(f"unsupported alignment method: {alignment}")

    paired_count = int(alignment_meta["matched_state_frames"])
    coverage = paired_count / len(commands) if commands else 0.0

    frames: list[dict[str, object]] = []
    reference_source_counts: dict[str, int] = {}
    interpolated_command_indices: list[int] = []
    for command_index, command in enumerate(commands):
        pitch, yaw, roll = command.view_angles
        origin, velocity, onground, solid, pm_code, source_kind = interpolated_reference(
            command_index,
            commands,
            states,
            state_for_cmd,
        )
        reference_source_counts[source_kind] = reference_source_counts.get(source_kind, 0) + 1
        if source_kind != "matched":
            interpolated_command_indices.append(command_index)
        frames.append(
            {
                "msec": int(command.msec),
                "origin": origin,
                "velocity": velocity,
                "angles": [float(pitch), float(yaw), float(roll)],
                "move": [int(command.forwardmove), int(command.sidemove), int(command.upmove)],
                "buttons": int(command.buttons),
                # Ground-state carried for the imitation training set (separate from the
                # fixed 14-col replay .cmds, which render_replay_file leaves unchanged).
                # onground/pm_code separate the air-accel regime from the landing regime
                # the retention work hinges on.
                "onground": onground,
                "solid": solid,
                "pm_code": pm_code,
                "reference_source": source_kind,
                "reference_interpolated": source_kind != "matched",
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
        "reference_frames": len(frames),
        "reference_source_counts": reference_source_counts,
        "interpolated_command_indices": interpolated_command_indices,
        "state_alignment": alignment_meta,
        "angle_channel_delta_deg": summarize_angle_channels(commands),
        "command_msec": summarize_msec(commands),
        "scan_counts": scan,
        "command_rate_fps": parsed.header["command_rate_fps"],
        "total_duration_s": parsed.header["total_duration_s"],
        "frame0": frames[0] if frames else None,
        "map_level": serverdata.level_name if serverdata else None,
        "playernum": serverdata.playernum if serverdata else None,
        "exceeds_max_replay_frames": len(frames) > MAX_REPLAY_FRAMES,
    }
    return frames, meta


def render_replay_file(frames: list[dict[str, object]], meta: dict[str, object]) -> str:
    alignment = meta.get("state_alignment") or {}
    aligned_label = alignment.get("method", "unknown")
    shift_label = alignment.get("state_shift", 0)
    header = (
        f"# {REPLAY_FILE_SCHEMA} demo={meta['demo']} frames={len(frames)} "
        f"sha256={meta['source_sha256']} fps={meta['command_rate_fps']} "
        f"aligned={aligned_label} state_shift={shift_label}"
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
        "--alignment",
        choices=("time", "zip"),
        default="time",
        help=(
            "Command/state pairing method. 'time' matches svc_playerinfo samples by QWD time "
            "and interpolates missing references. 'zip' preserves the old frame-order behavior "
            "and is refused when unsafe unless --allow-unsafe-zip is set."
        ),
    )
    parser.add_argument(
        "--state-shift",
        type=int,
        default=0,
        help=(
            "Shift matched states forward by N command rows after time matching. "
            "Use explicit evidence for nonzero values, e.g. A5 getspeed validated --state-shift 2."
        ),
    )
    parser.add_argument(
        "--allow-unsafe-zip",
        action="store_true",
        help="Allow old frame-order zip output even when counts or time deltas show it is unsafe.",
    )
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

    frames, meta = build_replay_frames(demo, alignment=args.alignment, state_shift=args.state_shift)
    if not frames:
        print(f"No replay frames built from {demo}", file=sys.stderr)
        return 1
    alignment_meta = meta.get("state_alignment") or {}
    if args.alignment == "zip" and alignment_meta.get("unsafe_zip_pairing") and not args.allow_unsafe_zip:
        print(
            "Refusing unsafe zip alignment: command/state counts or time deltas indicate drift. "
            "Use the default --alignment time, or pass --allow-unsafe-zip only for legacy reproduction.",
            file=sys.stderr,
        )
        return 2
    if meta["exceeds_max_replay_frames"]:
        print(
            f"WARNING: {meta['paired_frames']} frames exceeds MAX_REPLAY_FRAMES={MAX_REPLAY_FRAMES}; "
            "raise the KTX buffer before replaying this demo.",
            file=sys.stderr,
        )
    unmatched = int(alignment_meta.get("unmatched_command_frames") or 0)
    if unmatched:
        print(
            f"NOTE: {unmatched} command rows have interpolated or nearest-state references; "
            "see the JSON sidecar before treating divergence as lockstep evidence.",
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
