"""Build mode-28 target-state cvars from a replay segment target manifest.

The input is the JSON written by ``scripts/build_replay_segment_targets.py``.
Mode 28 consumes the same QWD waypoint string as modes 9/26/27, plus schedules
that preserve the human target state's view yaw, signed movement commands, jump
buttons, and vertical phase.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


SCHEMA = "komodobots.moveprobe_target_state_cvars.v1"
NONE = -99999.0


def fmt_float(value: float, digits: int = 3) -> str:
    text = f"{float(value):.{digits}f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def fmt_point(origin: dict[str, Any]) -> str:
    return ",".join(fmt_float(float(origin[axis])) for axis in ("x", "y", "z"))


def fmt_schedule(values: list[float | int]) -> str:
    out: list[str] = []
    for value in values:
        if isinstance(value, int):
            out.append(str(value))
        else:
            out.append(fmt_float(value, 4))
    return ",".join(out)


def target_value(target: dict[str, Any], key: str, fallback: float = NONE) -> float:
    value = target.get(key)
    return fallback if value is None else float(value)


def build_window_schedule(
    count: int,
    *,
    start_index: int | None,
    end_index: int | None,
    active_value: float | int,
    inactive_value: float | int,
) -> list[float | int]:
    if count <= 0:
        return []
    start = 0 if start_index is None else max(0, int(start_index))
    end = count - 1 if end_index is None else min(count - 1, int(end_index))
    if end < start:
        return [inactive_value for _ in range(count)]
    return [active_value if start <= i <= end else inactive_value for i in range(count)]


def build_cvars(
    report: dict[str, Any],
    *,
    route_yaw_weight: float,
    jump_lookahead: int,
    catchup_move: float = 0.0,
    catchup_start_index: int | None = None,
    catchup_end_index: int | None = None,
    catchup_gap: float = 0.0,
    catchup_blend: float = 1.0,
    catchup_cap: float = 1200.0,
    catchup_numerator: float = 0.0,
    catchup_flip: int = 0,
) -> dict[str, Any]:
    targets = report.get("targets")
    if not isinstance(targets, list) or not targets:
        raise ValueError("target manifest has no targets")

    waypoints: list[str] = []
    forward: list[int] = []
    side: list[int] = []
    jump: list[int] = []
    view_yaw: list[float] = []
    velocity_yaw: list[float] = []
    vertical_velocity: list[float] = []
    horizontal_speed: list[float] = []

    for row in targets:
        if not isinstance(row, dict):
            raise ValueError("target row is not an object")
        target = row.get("target")
        if not isinstance(target, dict):
            raise ValueError("target row is missing target object")
        origin = target.get("origin")
        move = target.get("move")
        angles = target.get("angles_deg")
        velocity = target.get("velocity")
        if not isinstance(origin, dict) or not isinstance(move, dict):
            raise ValueError("target row is missing origin/move")
        if not isinstance(angles, dict) or not isinstance(velocity, dict):
            raise ValueError("target row is missing angles/velocity")

        waypoints.append(fmt_point(origin))
        forward.append(int(move.get("forward", 0)))
        side.append(int(move.get("side", 0)))
        jump.append(1 if target.get("jump") else 0)
        view_yaw.append(float(angles.get("yaw", NONE)))
        velocity_yaw.append(target_value(target, "velocity_yaw_deg"))
        vertical_velocity.append(float(velocity.get("z", 0.0)))
        horizontal_speed.append(float(target.get("horizontal_speed", 0.0)))

    cvars = {
        "k_fb_moveprobe_s26_forwardmove_schedule": fmt_schedule(forward),
        "k_fb_moveprobe_s26_sidemove_schedule": fmt_schedule(side),
        "k_fb_moveprobe_s26_jump_schedule": fmt_schedule(jump),
        "k_fb_moveprobe_s28_view_yaw_schedule": fmt_schedule(view_yaw),
        "k_fb_moveprobe_s28_velocity_yaw_schedule": fmt_schedule(velocity_yaw),
        "k_fb_moveprobe_s28_vertical_velocity_schedule": fmt_schedule(vertical_velocity),
        "k_fb_moveprobe_s28_horizontal_speed_schedule": fmt_schedule(horizontal_speed),
        "k_fb_moveprobe_s28_route_yaw_weight": fmt_float(route_yaw_weight, 4),
        "k_fb_moveprobe_s28_jump_lookahead": str(int(jump_lookahead)),
    }
    if catchup_move > 0.0:
        count = len(targets)
        cvars.update(
            {
                "k_fb_moveprobe_s28_catchup_move_schedule": fmt_schedule(
                    build_window_schedule(
                        count,
                        start_index=catchup_start_index,
                        end_index=catchup_end_index,
                        active_value=float(catchup_move),
                        inactive_value=0.0,
                    )
                ),
                "k_fb_moveprobe_s28_catchup_gap_schedule": fmt_schedule(
                    build_window_schedule(
                        count,
                        start_index=catchup_start_index,
                        end_index=catchup_end_index,
                        active_value=float(catchup_gap),
                        inactive_value=float(catchup_gap),
                    )
                ),
                "k_fb_moveprobe_s28_catchup_blend_schedule": fmt_schedule(
                    build_window_schedule(
                        count,
                        start_index=catchup_start_index,
                        end_index=catchup_end_index,
                        active_value=float(catchup_blend),
                        inactive_value=1.0,
                    )
                ),
                "k_fb_moveprobe_s28_catchup_cap_schedule": fmt_schedule(
                    build_window_schedule(
                        count,
                        start_index=catchup_start_index,
                        end_index=catchup_end_index,
                        active_value=float(catchup_cap),
                        inactive_value=float(catchup_cap),
                    )
                ),
                "k_fb_moveprobe_s28_catchup_numerator_schedule": fmt_schedule(
                    build_window_schedule(
                        count,
                        start_index=catchup_start_index,
                        end_index=catchup_end_index,
                        active_value=float(catchup_numerator),
                        inactive_value=0.0,
                    )
                ),
                "k_fb_moveprobe_s28_catchup_flip_schedule": fmt_schedule(
                    build_window_schedule(
                        count,
                        start_index=catchup_start_index,
                        end_index=catchup_end_index,
                        active_value=int(catchup_flip),
                        inactive_value=0,
                    )
                ),
            }
        )
    return {
        "schema": SCHEMA,
        "source_schema": report.get("schema"),
        "route": report.get("route"),
        "map": report.get("map"),
        "target_count": len(targets),
        "qwd_waypoints": ";".join(waypoints),
        "extra_cvars": cvars,
        "ktx_extra_cvars": ";".join(f"{name} {value}" for name, value in cvars.items()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--targets", type=Path, required=True, help="Replay segment target JSON.")
    parser.add_argument("--output-json", type=Path, required=True, help="Output JSON path.")
    parser.add_argument(
        "--route-yaw-weight",
        type=float,
        default=0.25,
        help="Mode-28 blend from human view/velocity yaw toward active target yaw. Defaults to 0.25.",
    )
    parser.add_argument(
        "--jump-lookahead",
        type=int,
        default=0,
        help="Mode-28 future target rows to inspect for explicit jump labels. Defaults to 0.",
    )
    parser.add_argument(
        "--catchup-move",
        type=float,
        default=0.0,
        help="Emit a mode-28 per-target catch-up move schedule with this active strength.",
    )
    parser.add_argument(
        "--catchup-start-index",
        type=int,
        default=None,
        help="First target index where catch-up should be active. Defaults to 0 when catch-up is enabled.",
    )
    parser.add_argument(
        "--catchup-end-index",
        type=int,
        default=None,
        help="Last target index where catch-up should be active. Defaults to the final target.",
    )
    parser.add_argument(
        "--catchup-gap",
        type=float,
        default=0.0,
        help="Speed gap threshold to emit in the catch-up schedule. Defaults to 0.",
    )
    parser.add_argument(
        "--catchup-blend",
        type=float,
        default=1.0,
        help="Catch-up blend to emit while the window is active. Defaults to 1.",
    )
    parser.add_argument(
        "--catchup-cap",
        type=float,
        default=1200.0,
        help="Direction component cap to emit in the catch-up schedule. Defaults to 1200.",
    )
    parser.add_argument(
        "--catchup-numerator",
        type=float,
        default=0.0,
        help="cs->0 numerator to emit while the window is active. Defaults to 0 for direct target-lane catch-up.",
    )
    parser.add_argument(
        "--catchup-flip",
        type=int,
        default=0,
        help="Flip flag to emit while the window is active. Defaults to 0.",
    )
    args = parser.parse_args()

    report = json.loads(args.targets.read_text(encoding="utf-8"))
    output = build_cvars(
        report,
        route_yaw_weight=args.route_yaw_weight,
        jump_lookahead=args.jump_lookahead,
        catchup_move=args.catchup_move,
        catchup_start_index=args.catchup_start_index,
        catchup_end_index=args.catchup_end_index,
        catchup_gap=args.catchup_gap,
        catchup_blend=args.catchup_blend,
        catchup_cap=args.catchup_cap,
        catchup_numerator=args.catchup_numerator,
        catchup_flip=args.catchup_flip,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(args.output_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
