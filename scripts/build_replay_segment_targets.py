#!/usr/bin/env python3
"""Build controller-ready segment acquisition targets from a replay .cmds file.

The output is not a controller by itself. It is the durable target contract a
future live KTX probe can consume: acquire these route states within tolerance,
then resume replay or another phase controller.
"""

from __future__ import annotations

import logging
import argparse
import json
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence



LOGGER = logging.getLogger(__name__)
SCHEMA = "komodobots.replay_segment_targets.v1"
REPLAY_SCHEMA_PREFIX = "# komodobots.replay.v1"


@dataclass(frozen=True)
class ReplayFrame:
    msec: int
    origin: tuple[float, float, float]
    velocity: tuple[float, float, float]
    angles: tuple[float, float, float]
    move: tuple[int, int, int]
    buttons: int
    cumulative_ms: int


def rounded(value: float, digits: int = 3) -> float:
    return round(float(value), digits)


def anglemod(value: float) -> float:
    return float(value) % 360.0


def angle_delta_deg(a: float, b: float) -> float:
    return ((a - b + 180.0) % 360.0) - 180.0


def yaw_from_xy(x: float, y: float) -> float | None:
    if abs(x) < 1e-9 and abs(y) < 1e-9:
        return None
    return anglemod(math.degrees(math.atan2(y, x)))


def horizontal_length(vec: Sequence[float]) -> float:
    return math.hypot(float(vec[0]), float(vec[1]))


def parse_header(line: str) -> dict[str, object]:
    meta: dict[str, object] = {}
    if not line.startswith(REPLAY_SCHEMA_PREFIX):
        return meta
    for key, value in re.findall(r"(\w+)=([^ ]+)", line):
        if key in {"frames", "state_shift"}:
            try:
                meta[key] = int(value)
            except ValueError:
                meta[key] = value
        elif key == "fps":
            try:
                meta[key] = float(value)
            except ValueError:
                meta[key] = value
        else:
            meta[key] = value
    return meta


def parse_replay(path: Path) -> tuple[dict[str, object], list[ReplayFrame]]:
    header: dict[str, object] = {}
    frames: list[ReplayFrame] = []
    cumulative = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            if not header:
                header = parse_header(stripped)
            continue
        parts = stripped.split()
        if len(parts) != 14:
            raise ValueError(f"expected 14 columns in {path}, got {len(parts)}: {line!r}")
        msec = int(float(parts[0]))
        cumulative += msec
        frames.append(
            ReplayFrame(
                msec=msec,
                origin=(float(parts[1]), float(parts[2]), float(parts[3])),
                velocity=(float(parts[4]), float(parts[5]), float(parts[6])),
                angles=(float(parts[7]), float(parts[8]), float(parts[9])),
                move=(int(float(parts[10])), int(float(parts[11])), int(float(parts[12]))),
                buttons=int(float(parts[13])),
                cumulative_ms=cumulative,
            )
        )
    if not frames:
        raise ValueError(f"no replay frames in {path}")
    return header, frames


def frame_dict(frame: ReplayFrame) -> dict[str, object]:
    velocity_yaw = yaw_from_xy(frame.velocity[0], frame.velocity[1])
    horizontal_speed = horizontal_length(frame.velocity)
    yaw_lead = None
    if velocity_yaw is not None:
        yaw_lead = angle_delta_deg(frame.angles[1], velocity_yaw)
    return {
        "msec": frame.msec,
        "time_ms": frame.cumulative_ms,
        "origin": {
            "x": rounded(frame.origin[0]),
            "y": rounded(frame.origin[1]),
            "z": rounded(frame.origin[2]),
        },
        "velocity": {
            "x": rounded(frame.velocity[0]),
            "y": rounded(frame.velocity[1]),
            "z": rounded(frame.velocity[2]),
        },
        "angles_deg": {
            "pitch": rounded(frame.angles[0], 4),
            "yaw": rounded(frame.angles[1], 4),
            "roll": rounded(frame.angles[2], 4),
        },
        "move": {
            "forward": frame.move[0],
            "side": frame.move[1],
            "up": frame.move[2],
        },
        "buttons": frame.buttons,
        "jump": bool(frame.buttons & 2),
        "horizontal_speed": rounded(horizontal_speed),
        "velocity_yaw_deg": rounded(velocity_yaw, 3) if velocity_yaw is not None else None,
        "view_vs_velocity_yaw_lead_deg": rounded(yaw_lead, 3) if yaw_lead is not None else None,
    }


def vector_between(a: ReplayFrame, b: ReplayFrame) -> tuple[float, float, float]:
    return (
        b.origin[0] - a.origin[0],
        b.origin[1] - a.origin[1],
        b.origin[2] - a.origin[2],
    )


def segment_context(frames: Sequence[ReplayFrame], cursor: int, window: int) -> dict[str, object]:
    start = max(0, cursor - window)
    end = min(len(frames) - 1, cursor + window)
    before = frames[start]
    target = frames[cursor]
    after = frames[end]
    incoming = vector_between(before, target)
    outgoing = vector_between(target, after)
    incoming_yaw = yaw_from_xy(incoming[0], incoming[1])
    outgoing_yaw = yaw_from_xy(outgoing[0], outgoing[1])
    return {
        "window": {
            "start_cursor": start,
            "end_cursor": end,
            "samples": end - start + 1,
        },
        "incoming": {
            "from_cursor": start,
            "distance_h_qu": rounded(horizontal_length(incoming)),
            "delta_z_qu": rounded(incoming[2]),
            "yaw_deg": rounded(incoming_yaw, 3) if incoming_yaw is not None else None,
        },
        "outgoing": {
            "to_cursor": end,
            "distance_h_qu": rounded(horizontal_length(outgoing)),
            "delta_z_qu": rounded(outgoing[2]),
            "yaw_deg": rounded(outgoing_yaw, 3) if outgoing_yaw is not None else None,
        },
    }


def build_report(
    cmds_path: Path,
    *,
    route: str,
    map_name: str,
    cursors: Sequence[int],
    window: int,
    acquire_radius_h: float,
    acquire_radius_v: float,
    resume_radius_h: float,
    source_note: str | None = None,
) -> dict[str, object]:
    header, frames = parse_replay(cmds_path)
    targets = []
    for order, cursor in enumerate(cursors, start=1):
        if cursor < 0 or cursor >= len(frames):
            raise ValueError(f"target cursor {cursor} outside replay range 0..{len(frames) - 1}")
        frame = frames[cursor]
        targets.append(
            {
                "order": order,
                "cursor": cursor,
                "target": frame_dict(frame),
                "context": segment_context(frames, cursor, window),
                "acquisition_gate": {
                    "horizontal_radius_qu": acquire_radius_h,
                    "vertical_radius_qu": acquire_radius_v,
                    "resume_replay_when_horizontal_le_qu": resume_radius_h,
                    "policy": "acquire_target_before_resuming_replay",
                },
            }
        )

    return {
        "schema": SCHEMA,
        "route": route,
        "map": map_name,
        "source": {
            "cmds": str(cmds_path).replace("\\", "/"),
            "demo": header.get("demo"),
            "sha256": header.get("sha256"),
            "frames": len(frames),
            "header_frames": header.get("frames"),
            "fps": header.get("fps"),
            "aligned": header.get("aligned"),
            "state_shift": header.get("state_shift"),
            "note": source_note,
        },
        "target_count": len(targets),
        "target_cursors": list(cursors),
        "interpolation": {
            "source": "time-aligned replay rows",
            "segment_context": f"linear deltas over +/-{window} replay cursors",
            "buttons": "discrete edges preserved",
        },
        "targets": targets,
    }


def render_markdown(report: dict[str, object]) -> str:
    lines = [
        f"# Segment targets: {report['map']} / {report['route']}",
        "",
        f"- Source replay: `{report['source']['cmds']}`",
        f"- Source demo: `{report['source'].get('demo')}`",
        f"- SHA-256: `{report['source'].get('sha256')}`",
        f"- Targets: `{report['target_count']}`",
    ]
    if report["source"].get("note"):
        lines.append(f"- Note: {report['source']['note']}")
    lines.extend(
        [
            "",
            "| order | cursor | origin | velocity | speed | view yaw | vel yaw | yaw lead | gate |",
            "| ---: | ---: | --- | --- | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for target in report["targets"]:
        t = target["target"]
        origin = t["origin"]
        velocity = t["velocity"]
        angles = t["angles_deg"]
        gate = target["acquisition_gate"]
        lines.append(
            "| {order} | {cursor} | {origin} | {velocity} | {speed} | {view_yaw} | {vel_yaw} | {lead} | H<={h}, V<={v} |".format(
                order=target["order"],
                cursor=target["cursor"],
                origin=f"{origin['x']},{origin['y']},{origin['z']}",
                velocity=f"{velocity['x']},{velocity['y']},{velocity['z']}",
                speed=t["horizontal_speed"],
                view_yaw=angles["yaw"],
                vel_yaw=t["velocity_yaw_deg"],
                lead=t["view_vs_velocity_yaw_lead_deg"],
                h=gate["horizontal_radius_qu"],
                v=gate["vertical_radius_qu"],
            )
        )
    lines.extend(
        [
            "",
            "## Controller Use",
            "",
            "A live segment-acquisition mode should drive the bot into each target",
            "state inside the horizontal/vertical gate before allowing timed replay",
            "or phase recovery to continue. These targets do not prove a route by",
            "themselves; they make the next live controller attempt explicit and",
            "repeatable.",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cmds", type=Path, required=True)
    parser.add_argument("--route", required=True)
    parser.add_argument("--map", dest="map_name", required=True)
    parser.add_argument("--target-cursors", type=int, nargs="+", required=True)
    parser.add_argument("--window", type=int, default=4)
    parser.add_argument("--acquire-radius-h", type=float, default=64.0)
    parser.add_argument("--acquire-radius-v", type=float, default=64.0)
    parser.add_argument("--resume-radius-h", type=float, default=32.0)
    parser.add_argument("--source-note", default=None)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, default=None)
    return parser.parse_args(list(argv))


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    report = build_report(
        args.cmds,
        route=args.route,
        map_name=args.map_name,
        cursors=args.target_cursors,
        window=args.window,
        acquire_radius_h=args.acquire_radius_h,
        acquire_radius_v=args.acquire_radius_v,
        resume_radius_h=args.resume_radius_h,
        source_note=args.source_note,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.output_md:
        args.output_md.parent.mkdir(parents=True, exist_ok=True)
        args.output_md.write_text(render_markdown(report), encoding="utf-8")
    else:
        print(render_markdown(report), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
