#!/usr/bin/env python3
"""Summarize moveprobe command coverage and movement plausibility for lab runs."""

from __future__ import annotations

import logging
import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Iterable



LOGGER = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = REPO_ROOT / "artifacts" / "lab-runs"


def read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def read_run_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


def ratio(count: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return count / total


def dict_or_empty(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def int_value(value: object, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def float_value(value: object, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def move_value(row: dict, key: str) -> int:
    return int_value(dict_or_empty(row.get("move")).get(key))


def percentile(values: Iterable[float], percent: float) -> float:
    sorted_values = sorted(values)
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    index = (len(sorted_values) - 1) * percent
    lower = int(index)
    upper = min(lower + 1, len(sorted_values) - 1)
    fraction = index - lower
    return sorted_values[lower] + ((sorted_values[upper] - sorted_values[lower]) * fraction)


def command_rows_by_player(commands: dict) -> dict[str, list[dict]]:
    rows_by_player: dict[str, list[dict]] = {}
    for row in commands.get("commands", []):
        if not isinstance(row, dict):
            continue
        name = str(row.get("name", "")).strip()
        if name:
            rows_by_player.setdefault(name, []).append(row)
    return rows_by_player


def command_rows_by_ed(commands: dict) -> dict[int, list[dict]]:
    rows_by_ed: dict[int, list[dict]] = {}
    for row in commands.get("commands", []):
        if not isinstance(row, dict):
            continue
        ed = int_value(row.get("ed"))
        if not ed:
            continue
        rows_by_ed.setdefault(ed, []).append(row)
    return rows_by_ed


def command_rows_for_player(
    movement_row: dict,
    rows_by_ed: dict[int, list[dict]],
    rows_by_player: dict[str, list[dict]],
) -> list[dict]:
    ed = int_value(movement_row.get("user_id"))
    if ed:
        return rows_by_ed.get(ed, [])

    name = str(movement_row.get("name", "")).strip()
    return rows_by_player.get(name, [])


def resolve_expected_forward(expected_forward: int | None, run_env: dict[str, str]) -> int:
    if expected_forward is not None:
        return expected_forward
    try:
        return int(float(run_env.get("MOVEPROBE_FORWARDMOVE", "")))
    except (TypeError, ValueError):
        return 800


def duplicate_names(rows: Iterable[dict]) -> list[str]:
    names = [str(row.get("name", "")).strip() for row in rows]
    counts = Counter(name for name in names if name)
    return sorted(name for name, count in counts.items() if count > 1)


def summarize_player(
    movement_row: dict,
    command_rows: list[dict],
    *,
    expected_forward: int,
    max_stationary_ratio: float,
    max_low_speed_ratio: float,
    min_forward_ratio: float,
    min_horizontal_ratio: float,
    min_jump_ratio: float,
    min_side_ratio: float,
    min_yaw_unique: int,
) -> dict[str, object]:
    command_count = len(command_rows)
    forward_counts = Counter(move_value(row, "forward") for row in command_rows)
    horizontal_count = sum(
        1
        for row in command_rows
        if move_value(row, "forward") != 0
        or move_value(row, "side") != 0
    )
    side_nonzero_count = sum(1 for row in command_rows if move_value(row, "side") != 0)
    backward_count = sum(1 for row in command_rows if move_value(row, "forward") < 0)
    jump_count = sum(1 for row in command_rows if int_value(row.get("buttons")) & 2)
    move_vectors = [
        (
            move_value(row, "forward"),
            move_value(row, "side"),
        )
        for row in command_rows
    ]
    yaw_values = {
        round(float_value(dict_or_empty(row.get("angles")).get("yaw")), 1)
        for row in command_rows
    }
    yaw_delta_values = [
        abs(float_value(dict_or_empty(row.get("diagnostics")).get("yaw_delta")))
        for row in command_rows
        if "yaw_delta" in dict_or_empty(row.get("diagnostics"))
    ]

    stationary_ratio = float_value(movement_row.get("stationary_time_ratio"))
    low_speed_ratio = float_value(movement_row.get("low_speed_time_ratio"))
    forward_expected_ratio = ratio(forward_counts[expected_forward], command_count)
    horizontal_move_ratio = ratio(horizontal_count, command_count)
    side_nonzero_ratio = ratio(side_nonzero_count, command_count)
    backward_ratio = ratio(backward_count, command_count)
    jump_button_ratio = ratio(jump_count, command_count)
    yaw_unique_count = len(yaw_values)
    yaw_delta_abs_avg = sum(yaw_delta_values) / len(yaw_delta_values) if yaw_delta_values else 0.0
    yaw_delta_abs_p90 = percentile(yaw_delta_values, 0.90)
    yaw_delta_over_90_ratio = ratio(sum(1 for value in yaw_delta_values if value > 90.0), len(yaw_delta_values))
    max_abs_forward_command = max((abs(forward) for forward, _side in move_vectors), default=0)
    max_abs_side_command = max((abs(side) for _forward, side in move_vectors), default=0)
    max_horizontal_command = max(
        (math.hypot(forward, side) for forward, side in move_vectors),
        default=0.0,
    )

    reasons: list[str] = []
    if command_count == 0:
        reasons.append("no command rows")
    if forward_expected_ratio < min_forward_ratio:
        reasons.append(f"forward coverage {forward_expected_ratio:.1%} < {min_forward_ratio:.1%}")
    if horizontal_move_ratio < min_horizontal_ratio:
        reasons.append(f"horizontal command coverage {horizontal_move_ratio:.1%} < {min_horizontal_ratio:.1%}")
    if jump_button_ratio < min_jump_ratio:
        reasons.append(f"jump coverage {jump_button_ratio:.1%} < {min_jump_ratio:.1%}")
    if side_nonzero_ratio < min_side_ratio:
        reasons.append(f"side coverage {side_nonzero_ratio:.1%} < {min_side_ratio:.1%}")
    if yaw_unique_count < min_yaw_unique:
        reasons.append(f"yaw variety {yaw_unique_count} < {min_yaw_unique}")
    if stationary_ratio > max_stationary_ratio:
        reasons.append(f"stationary {stationary_ratio:.1%} > {max_stationary_ratio:.1%}")
    if low_speed_ratio > max_low_speed_ratio:
        reasons.append(f"low-speed {low_speed_ratio:.1%} > {max_low_speed_ratio:.1%}")

    return {
        "player": movement_row.get("name", ""),
        "slot": movement_row.get("slot"),
        "command_count": command_count,
        "forward_expected_ratio": round(forward_expected_ratio, 3),
        "horizontal_move_ratio": round(horizontal_move_ratio, 3),
        "side_nonzero_ratio": round(side_nonzero_ratio, 3),
        "backward_command_ratio": round(backward_ratio, 3),
        "jump_button_ratio": round(jump_button_ratio, 3),
        "yaw_unique_count": yaw_unique_count,
        "yaw_delta_sample_count": len(yaw_delta_values),
        "yaw_delta_abs_avg": round(yaw_delta_abs_avg, 1),
        "yaw_delta_abs_p90": round(yaw_delta_abs_p90, 1),
        "yaw_delta_over_90_ratio": round(yaw_delta_over_90_ratio, 3),
        "max_abs_forward_command": max_abs_forward_command,
        "max_abs_side_command": max_abs_side_command,
        "max_horizontal_command": round(max_horizontal_command, 1),
        "avg_horizontal_speed_qu_per_s": movement_row.get("avg_horizontal_speed_qu_per_s", 0.0),
        "p95_horizontal_speed_qu_per_s": movement_row.get("p95_horizontal_speed_qu_per_s", 0.0),
        "stationary_time_ratio": movement_row.get("stationary_time_ratio", 0.0),
        "low_speed_time_ratio": movement_row.get("low_speed_time_ratio", 0.0),
        "airborne_proxy_time_ratio": movement_row.get("airborne_proxy_time_ratio", 0.0),
        "jump_cadence_per_min": movement_row.get("jump_cadence_per_min", 0.0),
        "passes_gate": not reasons,
        "failure_reasons": reasons,
    }


def summarize_run(
    run_dir: Path,
    *,
    expected_forward: int | None,
    max_stationary_ratio: float,
    max_low_speed_ratio: float,
    min_forward_ratio: float,
    min_horizontal_ratio: float,
    min_jump_ratio: float,
    min_side_ratio: float,
    min_yaw_unique: int,
) -> dict[str, object]:
    if not run_dir.is_dir():
        raise FileNotFoundError(f"Missing run directory: {run_dir}")

    movement = read_json(run_dir / "movement-metrics.json")
    commands = read_json(run_dir / "moveprobe-commands.json")
    run_env = read_run_env(run_dir / "run.env")
    expected_forward_value = resolve_expected_forward(expected_forward, run_env)
    movement_rows = movement.get("players", [])
    duplicate_movement_names = duplicate_names(movement_rows)
    warnings = []
    if duplicate_movement_names:
        warnings.append(
            "duplicate player names present; command matching prefers movement user_id "
            "to command ed, then falls back to netname for older artifacts: "
            + ", ".join(duplicate_movement_names)
        )
    rows_by_ed = command_rows_by_ed(commands)
    rows_by_player = command_rows_by_player(commands)

    players = []
    for movement_row in movement_rows:
        players.append(
            summarize_player(
                movement_row,
                command_rows_for_player(movement_row, rows_by_ed, rows_by_player),
                expected_forward=expected_forward_value,
                max_stationary_ratio=max_stationary_ratio,
                max_low_speed_ratio=max_low_speed_ratio,
                min_forward_ratio=min_forward_ratio,
                min_horizontal_ratio=min_horizontal_ratio,
                min_jump_ratio=min_jump_ratio,
                min_side_ratio=min_side_ratio,
                min_yaw_unique=min_yaw_unique,
            )
        )

    return {
        "run_id": run_dir.name,
        "map": run_env.get("MAP", ""),
        "moveprobe_mode": run_env.get("MOVEPROBE_MODE", ""),
        "expected_forward": expected_forward_value,
        "warnings": warnings,
        "players": players,
        "passes_gate": all(player["passes_gate"] for player in players) and bool(players),
    }


def fmt_percent(value: object) -> str:
    try:
        return f"{float(value) * 100.0:.1f}%"
    except (TypeError, ValueError):
        return ""


def fmt_number(value: object, digits: int = 1) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return ""


def build_markdown(summary: dict[str, object]) -> str:
    lines = [
        "# Moveprobe Plausibility Summary",
        "",
        "Gate: command coverage and movement plausibility, not speed alone.",
        "",
        "Expected forward defaults to each run's `MOVEPROBE_FORWARDMOVE`, falling back to `800`.",
        "For aim-independent probes with variable local forward values, set `--min-forward-ratio 0` and use `--min-horizontal-ratio` instead.",
        "",
        "| Run | Map | Mode | Player | Gate | Cmds | Forward | Move | Side | Back | Jump | Yaws | MaxF | MaxS | MaxMove | Abs delta avg | Abs delta p90 | >90 | Avg | P95 | Stationary | Low | Air | Cadence/min | Reasons |",
        "|---|---|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for run in summary.get("runs", []):
        for warning in run.get("warnings", []):
            lines.append(f"> Warning for `{run.get('run_id')}`: {warning}")
        for player in run.get("players", []):
            reasons = "; ".join(player.get("failure_reasons", []))
            gate = "PASS" if player.get("passes_gate") else "FAIL"
            lines.append(
                f"| `{run.get('run_id')}` | `{run.get('map')}` | `{run.get('moveprobe_mode')}` | "
                f"`{player.get('player')}` | {gate} | `{player.get('command_count')}` | "
                f"{fmt_percent(player.get('forward_expected_ratio'))} | "
                f"{fmt_percent(player.get('horizontal_move_ratio'))} | "
                f"{fmt_percent(player.get('side_nonzero_ratio'))} | "
                f"{fmt_percent(player.get('backward_command_ratio'))} | "
                f"{fmt_percent(player.get('jump_button_ratio'))} | "
                f"`{player.get('yaw_unique_count')}` | "
                f"`{player.get('max_abs_forward_command')}` | "
                f"`{player.get('max_abs_side_command')}` | "
                f"`{fmt_number(player.get('max_horizontal_command'))}` | "
                f"`{fmt_number(player.get('yaw_delta_abs_avg'))}` | "
                f"`{fmt_number(player.get('yaw_delta_abs_p90'))}` | "
                f"{fmt_percent(player.get('yaw_delta_over_90_ratio'))} | "
                f"`{fmt_number(player.get('avg_horizontal_speed_qu_per_s'))}` | "
                f"`{fmt_number(player.get('p95_horizontal_speed_qu_per_s'))}` | "
                f"{fmt_percent(player.get('stationary_time_ratio'))} | "
                f"{fmt_percent(player.get('low_speed_time_ratio'))} | "
                f"{fmt_percent(player.get('airborne_proxy_time_ratio'))} | "
                f"`{fmt_number(player.get('jump_cadence_per_min'))}` | {reasons} |"
            )
    lines.append("")
    return "\n".join(lines)


def build_summary(args: argparse.Namespace) -> dict[str, object]:
    runs = []
    for run_id in args.run_ids:
        run_path = Path(run_id)
        if not run_path.is_dir():
            run_path = args.artifacts_root / run_id
        runs.append(
            summarize_run(
                run_path,
                expected_forward=args.expected_forward,
                max_stationary_ratio=args.max_stationary_ratio,
                max_low_speed_ratio=args.max_low_speed_ratio,
                min_forward_ratio=args.min_forward_ratio,
                min_horizontal_ratio=args.min_horizontal_ratio,
                min_jump_ratio=args.min_jump_ratio,
                min_side_ratio=args.min_side_ratio,
                min_yaw_unique=args.min_yaw_unique,
            )
        )

    return {
        "schema": "komodobots.moveprobe_plausibility.v1",
        "thresholds": {
            "expected_forward": args.expected_forward,
            "expected_forward_default": "run_env_MOVEPROBE_FORWARDMOVE_or_800",
            "max_stationary_ratio": args.max_stationary_ratio,
            "max_low_speed_ratio": args.max_low_speed_ratio,
            "min_forward_ratio": args.min_forward_ratio,
            "min_horizontal_ratio": args.min_horizontal_ratio,
            "min_jump_ratio": args.min_jump_ratio,
            "min_side_ratio": args.min_side_ratio,
            "min_yaw_unique": args.min_yaw_unique,
        },
        "runs": runs,
        "passes_gate": all(run["passes_gate"] for run in runs) and bool(runs),
    }


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize moveprobe plausibility across lab runs.")
    parser.add_argument("run_ids", nargs="+", help="Run IDs under artifacts/lab-runs, or explicit run directories.")
    parser.add_argument("--artifacts-root", type=Path, default=ARTIFACT_ROOT, help="Lab artifact root.")
    parser.add_argument(
        "--expected-forward",
        type=int,
        default=None,
        help="Expected forward command value. Defaults to MOVEPROBE_FORWARDMOVE from run.env, falling back to 800.",
    )
    parser.add_argument("--max-stationary-ratio", type=float, default=0.25, help="Maximum acceptable stationary time ratio.")
    parser.add_argument("--max-low-speed-ratio", type=float, default=0.40, help="Maximum acceptable low-speed time ratio.")
    parser.add_argument("--min-forward-ratio", type=float, default=0.80, help="Minimum expected-forward command coverage.")
    parser.add_argument(
        "--min-horizontal-ratio",
        type=float,
        default=0.0,
        help="Minimum nonzero horizontal command coverage. Useful when local forward/side values vary by view angle.",
    )
    parser.add_argument("--min-jump-ratio", type=float, default=0.80, help="Minimum jump-button command coverage.")
    parser.add_argument("--min-side-ratio", type=float, default=0.0, help="Minimum nonzero-side command coverage. Defaults to 0 for non-strafe probes.")
    parser.add_argument("--min-yaw-unique", type=int, default=10, help="Minimum distinct sampled yaw values per player.")
    parser.add_argument("--output-json", type=Path, help="Optional JSON output path.")
    parser.add_argument("--output-md", type=Path, help="Optional Markdown output path.")
    return parser.parse_args(list(argv))


def main(argv: Iterable[str] = sys.argv[1:]) -> int:
    args = parse_args(argv)
    summary = build_summary(args)
    markdown = build_markdown(summary)

    if args.output_json:
        args.output_json.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.output_md:
        args.output_md.write_text(markdown, encoding="utf-8")

    print(markdown)
    return 0 if summary["passes_gate"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
