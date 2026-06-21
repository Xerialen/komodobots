#!/usr/bin/env python3
"""Score mode 25 runs against the getandmaintainspeed human reference.

The benchmark is not "touch a route marker"; it is sustained bunnyhop speed
with the recorded human mouse/input rhythm.  This scorer keeps that target
explicit so repeated live attempts can be compared without hand scoring.
"""

from __future__ import annotations

import logging
import argparse
import json
import math
import sys
from pathlib import Path
from typing import Iterable

from extract_movement_metrics import coerce_origin, coerce_time_ms, percentile



LOGGER = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARTIFACTS_ROOT = REPO_ROOT / "artifacts" / "lab-runs"
DEFAULT_REFERENCE = REPO_ROOT / "artifacts" / "qwd-getandmaintainspeed" / "mouse-analysis.json"
DEFAULT_HIGH_SPEED = 900.0
DEFAULT_MAX_DT_MS = 200
DEFAULT_MAX_DXY = 250.0
DEFAULT_MAX_DZ = 160.0
DEFAULT_MAX_SPEED = 1500.0
DEFAULT_CURSOR_WINDOWS = [
    (1634, 1648),
    (1655, 1953),
    (2044, 2087),
    (2097, 2104),
    (2106, 2230),
]


def load_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def round_float(value: float | None, digits: int = 3) -> float | None:
    if value is None:
        return None
    if not math.isfinite(value):
        return 0.0
    return round(value, digits)


def angle_delta_deg(current: float, previous: float) -> float:
    return (current - previous + 180.0) % 360.0 - 180.0


def sign(value: float) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def iter_json_events(path: Path) -> Iterable[dict]:
    if not path.is_file():
        return []
    rows = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def choose_player_slot(run_dir: Path) -> int | None:
    metrics = load_json(run_dir / "movement-metrics.json")
    players = metrics.get("players") or []
    if not players:
        return None
    return int(players[0]["slot"])


def event_speed_segments(
    run_dir: Path,
    *,
    slot: int | None = None,
    max_dt_ms: int = DEFAULT_MAX_DT_MS,
    max_dxy: float = DEFAULT_MAX_DXY,
    max_dz: float = DEFAULT_MAX_DZ,
    max_speed: float = DEFAULT_MAX_SPEED,
) -> list[dict[str, float]]:
    player_slot = choose_player_slot(run_dir) if slot is None else slot
    if player_slot is None:
        return []

    samples: list[tuple[int, list[float]]] = []
    for event in iter_json_events(run_dir / "events.txt"):
        if event.get("kind") != 5:
            continue
        data = event.get("data") or {}
        if int(data.get("PlayerNum", -1)) != player_slot:
            continue
        origin = coerce_origin(data.get("Origin"))
        if origin is None:
            continue
        samples.append((coerce_time_ms(event, data), origin))

    samples.sort(key=lambda item: item[0])
    segments: list[dict[str, float]] = []
    for (start_ms, start_origin), (end_ms, end_origin) in zip(samples, samples[1:]):
        dt_ms = end_ms - start_ms
        if dt_ms <= 0 or dt_ms > max_dt_ms:
            continue
        dx = end_origin[0] - start_origin[0]
        dy = end_origin[1] - start_origin[1]
        dz = end_origin[2] - start_origin[2]
        dxy = math.hypot(dx, dy)
        if dxy > max_dxy or abs(dz) > max_dz:
            continue
        speed = dxy / (dt_ms / 1000.0)
        if speed > max_speed:
            continue
        segments.append(
            {
                "start_ms": float(start_ms),
                "end_ms": float(end_ms),
                "dt_ms": float(dt_ms),
                "speed": speed,
                "start_x": start_origin[0],
                "start_y": start_origin[1],
                "start_z": start_origin[2],
                "end_x": end_origin[0],
                "end_y": end_origin[1],
                "end_z": end_origin[2],
            }
        )
    return segments


def summarize_event_speeds(segments: list[dict[str, float]], *, high_speed: float) -> dict:
    speeds = [segment["speed"] for segment in segments]
    high_ms = sum(segment["dt_ms"] for segment in segments if segment["speed"] > high_speed)
    total_ms = sum(segment["dt_ms"] for segment in segments)
    return {
        "segment_count": len(segments),
        "total_time_s": round_float(total_ms / 1000.0),
        "avg_speed": round_float(sum(speeds) / len(speeds) if speeds else 0.0),
        "p50_speed": round_float(percentile(speeds, 50)),
        "p95_speed": round_float(percentile(speeds, 95)),
        "max_speed": round_float(max(speeds) if speeds else 0.0),
        "time_above_high_s": round_float(high_ms / 1000.0),
        "ratio_above_high": round_float(high_ms / total_ms if total_ms else 0.0),
    }


def summarize_command_stream(
    run_dir: Path,
    *,
    high_speed: float,
    cursor_windows: list[tuple[int, int]],
) -> dict:
    commands = load_json(run_dir / "moveprobe-commands.json").get("commands") or []
    rows = [row for row in commands if isinstance(row.get("s25_state"), dict)]
    speeds = [float(row["s25_state"]["speed"]) for row in rows]

    yaw_rates: list[float] = []
    yaw_reversals = 0
    previous_yaw_rate_sign = 0
    previous_row = None
    for row in rows:
        if previous_row is not None:
            dt = float(row["time_s"]) - float(previous_row["time_s"])
            if 0.005 <= dt <= 0.03:
                dyaw = angle_delta_deg(float(row["angles"]["yaw"]), float(previous_row["angles"]["yaw"]))
                rate = dyaw / dt
                yaw_rates.append(abs(rate))
                current_sign = sign(rate)
                if current_sign and previous_yaw_rate_sign and current_sign != previous_yaw_rate_sign:
                    yaw_reversals += 1
                if current_sign:
                    previous_yaw_rate_sign = current_sign
        previous_row = row

    side_values = [float(row["move"]["side"]) for row in rows]
    side_changes = 0
    previous_side_sign = 0
    for side_value in side_values:
        current_sign = sign(side_value)
        if current_sign and previous_side_sign and current_sign != previous_side_sign:
            side_changes += 1
        if current_sign:
            previous_side_sign = current_sign

    windows = []
    for start, end in cursor_windows:
        window_rows = [
            row
            for row in rows
            if start <= int((row.get("replay_state") or {}).get("cursor", -1)) <= end
        ]
        window_speeds = [float(row["s25_state"]["speed"]) for row in window_rows]
        windows.append(
            {
                "cursor_start": start,
                "cursor_end": end,
                "sample_count": len(window_rows),
                "avg_speed": round_float(sum(window_speeds) / len(window_speeds) if window_speeds else 0.0),
                "p95_speed": round_float(percentile(window_speeds, 95)),
                "max_speed": round_float(max(window_speeds) if window_speeds else 0.0),
                "time_s": round_float(sum(float(row["msec"]) for row in window_rows) / 1000.0),
            }
        )

    total_time_s = sum(float(row["msec"]) for row in rows) / 1000.0
    high_time_s = sum(float(row["msec"]) for row in rows if float(row["s25_state"]["speed"]) > high_speed) / 1000.0
    duration_s = max(0.0, float(rows[-1]["time_s"]) - float(rows[0]["time_s"])) if rows else 0.0
    return {
        "sample_count": len(rows),
        "total_command_time_s": round_float(total_time_s),
        "avg_speed": round_float(sum(speeds) / len(speeds) if speeds else 0.0),
        "p50_speed": round_float(percentile(speeds, 50)),
        "p95_speed": round_float(percentile(speeds, 95)),
        "max_speed": round_float(max(speeds) if speeds else 0.0),
        "time_above_high_s": round_float(high_time_s),
        "ratio_above_high": round_float(high_time_s / total_time_s if total_time_s else 0.0),
        "yaw_rate_abs_p95_deg_s": round_float(percentile(yaw_rates, 95)),
        "yaw_reversals": yaw_reversals,
        "yaw_reversals_per_s": round_float(yaw_reversals / duration_s if duration_s else 0.0),
        "side_sign_changes": side_changes,
        "cursor_windows": windows,
    }


def movement_summary(run_dir: Path) -> dict:
    player = (load_json(run_dir / "movement-metrics.json").get("players") or [{}])[0]
    return {
        "p50_speed": player.get("p50_horizontal_speed_qu_per_s"),
        "p90_speed": player.get("p90_horizontal_speed_qu_per_s"),
        "p95_speed": player.get("p95_horizontal_speed_qu_per_s"),
        "max_speed": player.get("max_horizontal_speed_qu_per_s"),
        "avg_speed": player.get("avg_horizontal_speed_qu_per_s"),
        "active_time_s": player.get("active_time_s"),
    }


def score_run(
    run_dir: Path,
    *,
    reference_path: Path = DEFAULT_REFERENCE,
    high_speed: float = DEFAULT_HIGH_SPEED,
    cursor_windows: list[tuple[int, int]] | None = None,
) -> dict:
    reference = load_json(reference_path)
    reference_speed = reference.get("speed_qu_per_s") or {}
    reference_mouse = reference.get("mouse") or {}
    windows = DEFAULT_CURSOR_WINDOWS if cursor_windows is None else cursor_windows
    event_summary = summarize_event_speeds(
        event_speed_segments(run_dir),
        high_speed=high_speed,
    )
    command_summary = summarize_command_stream(run_dir, high_speed=high_speed, cursor_windows=windows)
    movement = movement_summary(run_dir)

    target_p95 = float(reference_speed.get("p95") or 0.0)
    target_max = float(reference_speed.get("max") or 0.0)
    target_high_time = float((reference_speed.get("time_above") or {}).get(str(int(high_speed))) or 0.0)
    target_yaw_p95 = float(reference_mouse.get("yaw_rate_abs_p95_deg_s") or 0.0)
    target_reversals = float(reference_mouse.get("yaw_reversals_per_s") or 0.0)

    checks = {
        "event_p95_beats_human": float(event_summary["p95_speed"] or 0.0) > target_p95,
        "event_max_beats_human": float(event_summary["max_speed"] or 0.0) > target_max,
        "event_high_time_beats_human": float(event_summary["time_above_high_s"] or 0.0) > target_high_time,
        "command_high_time_beats_human": float(command_summary["time_above_high_s"] or 0.0) > target_high_time,
        "mouse_yaw_p95_within_20pct": (
            target_yaw_p95 > 0
            and abs(float(command_summary["yaw_rate_abs_p95_deg_s"] or 0.0) - target_yaw_p95)
            <= target_yaw_p95 * 0.2
        ),
        "mouse_reversal_rate_within_50pct": (
            target_reversals > 0
            and abs(float(command_summary["yaw_reversals_per_s"] or 0.0) - target_reversals)
            <= max(0.5, target_reversals * 0.5)
        ),
    }
    verdict = "PASS" if all(checks.values()) else "FAIL"
    return {
        "schema": "komodobots.getandmaintainspeed_score.v1",
        "run_id": run_dir.name,
        "reference": {
            "path": str(reference_path),
            "source_sha256": reference.get("source_sha256"),
            "p95_speed": target_p95,
            "max_speed": target_max,
            f"time_above_{int(high_speed)}_s": target_high_time,
            "yaw_rate_abs_p95_deg_s": target_yaw_p95,
            "yaw_reversals_per_s": target_reversals,
        },
        "movement_metrics": movement,
        "event_speed": event_summary,
        "command_speed": command_summary,
        "checks": checks,
        "verdict": verdict,
    }


def render_markdown(report: dict) -> str:
    high_time_key = next(key for key in report["reference"] if key.startswith("time_above_"))
    lines = [
        f"# getandmaintainspeed score: {report['run_id']} -> {report['verdict']}",
        "",
        "| metric | human | event | command |",
        "|---|---:|---:|---:|",
        (
            f"| p95 speed | {report['reference']['p95_speed']:.1f} | "
            f"{report['event_speed']['p95_speed']:.1f} | {report['command_speed']['p95_speed']:.1f} |"
        ),
        (
            f"| max speed | {report['reference']['max_speed']:.1f} | "
            f"{report['event_speed']['max_speed']:.1f} | {report['command_speed']['max_speed']:.1f} |"
        ),
        (
            f"| time >900 | {report['reference'][high_time_key]:.3f}s | "
            f"{report['event_speed']['time_above_high_s']:.3f}s | "
            f"{report['command_speed']['time_above_high_s']:.3f}s |"
        ),
        (
            f"| yaw p95 | {report['reference']['yaw_rate_abs_p95_deg_s']:.1f} |  | "
            f"{report['command_speed']['yaw_rate_abs_p95_deg_s']:.1f} |"
        ),
        (
            f"| yaw reversals/s | {report['reference']['yaw_reversals_per_s']:.2f} |  | "
            f"{report['command_speed']['yaw_reversals_per_s']:.2f} |"
        ),
        "",
        "## Checks",
        "",
    ]
    for name, passed in report["checks"].items():
        lines.append(f"- {'PASS' if passed else 'FAIL'} `{name}`")
    lines.extend(["", "## Cursor Windows", ""])
    lines.append("| cursor | samples | avg | p95 | max |")
    lines.append("|---|---:|---:|---:|---:|")
    for window in report["command_speed"]["cursor_windows"]:
        lines.append(
            f"| {window['cursor_start']}-{window['cursor_end']} | {window['sample_count']} | "
            f"{window['avg_speed']:.1f} | {window['p95_speed']:.1f} | {window['max_speed']:.1f} |"
        )
    return "\n".join(lines) + "\n"


def parse_cursor_window(raw: str) -> tuple[int, int]:
    try:
        start, end = raw.split("-", 1)
        return int(start), int(end)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("cursor windows must look like START-END") from exc


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Score a mode 25 run against getandmaintainspeed.qwd.")
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--run-id", help="Lab run id under artifacts/lab-runs/.")
    g.add_argument("--run-dir", type=Path, help="Explicit run directory.")
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--high-speed", type=float, default=DEFAULT_HIGH_SPEED)
    parser.add_argument(
        "--cursor-window",
        dest="cursor_windows",
        type=parse_cursor_window,
        action="append",
        help="Cursor window as START-END. May be repeated; defaults to human >900 windows.",
    )
    return parser.parse_args(list(argv))


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    run_dir = args.run_dir or (DEFAULT_ARTIFACTS_ROOT / args.run_id)
    if not run_dir.is_dir():
        print(f"Run directory not found: {run_dir}", file=sys.stderr)
        return 2
    report = score_run(
        run_dir,
        reference_path=args.reference,
        high_speed=args.high_speed,
        cursor_windows=args.cursor_windows,
    )
    (run_dir / "getandmaintainspeed-score.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (run_dir / "getandmaintainspeed-score.md").write_text(render_markdown(report), encoding="utf-8")
    print(render_markdown(report), end="")
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
