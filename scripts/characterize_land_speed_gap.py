#!/usr/bin/env python3
"""Characterize S7g land-speed gaps around air and route segments."""

from __future__ import annotations

import argparse
import bisect
import json
import math
import sys
from pathlib import Path
from typing import Iterable

from analyze_human_mvd import format_comparison_value
from inspect_airborne_proxy_segments import (
    build_segments,
    extract_airborne_runs,
    load_player_samples,
    percentile,
    repo_path,
    rounded,
    thresholds,
)
from summarize_reference_aggregate import portable_path


SCHEMA = "komodobots.land_speed_gap.v1"
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = REPO_ROOT / "experiments" / "human_comparison" / "evidence" / "airborne-segments-s7f-dm3.json"
DEFAULT_OUTPUT_JSON = REPO_ROOT / "experiments" / "human_comparison" / "evidence" / "land-speed-gap-s7g-dm3.json"
DEFAULT_OUTPUT_MD = REPO_ROOT / "experiments" / "human_comparison" / "evidence" / "land-speed-gap-s7g-dm3.md"
DEFAULT_TRANSITION_WINDOW_MS = 400
DEFAULT_COMMAND_MARGIN_MS = 150
STRONG_COMMAND_QU_PER_S = 400.0
LOW_ROUTE_DIR_SPEED = 0.25
WATER_PATH = 1 << 15

BUCKETS = (
    ("all_segments", "All accepted segments"),
    ("airborne_proxy_segments", "Airborne-proxy segments"),
    ("non_airborne_segments", "Non-airborne segments"),
    ("pre_air_window_segments", "Pre-air window"),
    ("post_air_window_segments", "Post-air window"),
    ("sampled_strong_command_segments", "Sampled strong-command segments"),
    ("sampled_weak_command_segments", "Sampled weak-command segments"),
    ("route_low_dir_speed_segments", "Route low-dir-speed segments"),
    ("route_water_path_segments", "Route WATER_PATH segments"),
)


class ReportInputError(RuntimeError):
    """Raised when S7g source rows cannot be resolved into evidence."""


def optional_float(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def summarize_values(values: list[float]) -> dict[str, object]:
    clean = [value for value in values if math.isfinite(value)]
    if not clean:
        return {"count": 0, "min": None, "mean": None, "p50": None, "p90": None, "p95": None, "max": None}
    return {
        "count": len(clean),
        "min": round(min(clean), 3),
        "mean": round(sum(clean) / len(clean), 3),
        "p50": round(percentile(clean, 50), 3),
        "p90": round(percentile(clean, 90), 3),
        "p95": round(percentile(clean, 95), 3),
        "max": round(max(clean), 3),
    }


def ratio(bot: dict[str, object], reference: dict[str, object], key: str = "p50") -> float | None:
    bot_value = optional_float(bot.get(key))
    reference_value = optional_float(reference.get(key))
    if bot_value is None or reference_value is None or reference_value <= 0:
        return None
    return round(bot_value / reference_value, 3)


def segment_midpoint_ms(segment: dict[str, object]) -> float:
    return (float(segment["start_ms"]) + float(segment["end_ms"])) / 2.0


def interval_flags(segments: list[dict[str, object]], intervals: list[tuple[float, float]]) -> list[bool]:
    ordered = sorted(interval for interval in intervals if interval[1] > interval[0])
    flags: list[bool] = []
    index = 0
    for segment in segments:
        while index < len(ordered) and ordered[index][1] <= float(segment["start_ms"]):
            index += 1
        flags.append(
            index < len(ordered)
            and ordered[index][0] < float(segment["end_ms"])
            and ordered[index][1] > float(segment["start_ms"])
        )
    return flags


def midpoint_window_flags(
    segments: list[dict[str, object]],
    intervals: list[tuple[float, float]],
) -> list[bool]:
    ordered = sorted(interval for interval in intervals if interval[1] > interval[0])
    flags: list[bool] = []
    index = 0
    for segment in segments:
        midpoint = segment_midpoint_ms(segment)
        while index < len(ordered) and ordered[index][1] <= midpoint:
            index += 1
        flags.append(index < len(ordered) and ordered[index][0] <= midpoint < ordered[index][1])
    return flags


def read_commands(run_dir: Path, identity: str) -> list[dict[str, object]]:
    path = run_dir / "moveprobe-commands.json"
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        loaded = json.load(handle)
    commands = []
    wanted = identity.strip().lower()
    for row in loaded.get("commands", []) if isinstance(loaded, dict) else []:
        if not isinstance(row, dict) or str(row.get("name", "")).strip().lower() != wanted:
            continue
        try:
            time_ms = int(round(float(row.get("time_s")) * 1000.0))
        except (TypeError, ValueError):
            continue
        commands.append({**row, "_time_ms": time_ms})
    return sorted(commands, key=lambda row: int(row["_time_ms"]))


def nearest_commands(
    commands: list[dict[str, object]],
    segment_midpoints: list[float],
    *,
    margin_ms: int,
) -> list[dict[str, object] | None]:
    if not commands:
        return [None for _ in segment_midpoints]
    times = [int(row["_time_ms"]) for row in commands]
    nearest: list[dict[str, object] | None] = []
    for midpoint in segment_midpoints:
        pos = bisect.bisect_left(times, midpoint)
        best_row = None
        best_delta = margin_ms + 1
        for index in (pos - 1, pos):
            if 0 <= index < len(commands):
                delta = abs(times[index] - midpoint)
                if delta < best_delta:
                    best_row = commands[index]
                    best_delta = delta
        nearest.append(best_row if best_delta <= margin_ms else None)
    return nearest


def command_magnitude(command: dict[str, object]) -> float:
    move = command.get("move", {}) if isinstance(command.get("move"), dict) else {}
    try:
        return math.hypot(float(move.get("forward", 0.0)), float(move.get("side", 0.0)))
    except (TypeError, ValueError):
        return 0.0


def command_route_state(command: dict[str, object] | None) -> dict[str, object]:
    if not command or not isinstance(command.get("route_state"), dict):
        return {}
    return command["route_state"]


def route_dir_speed(route_state: dict[str, object]) -> float | None:
    return optional_float(route_state.get("dir_speed"))


def path_state(route_state: dict[str, object]) -> int:
    try:
        return int(route_state.get("path_state", 0))
    except (TypeError, ValueError):
        return 0


def player_report(
    row: dict[str, object],
    *,
    transition_window_ms: int,
    command_margin_ms: int,
) -> dict[str, object]:
    run_dir = repo_path(row.get("events_path", "")).parent
    _info, samples = load_player_samples(run_dir, str(row.get("identity", "")))
    segments, dropped_teleports = build_segments(samples, thresholds())
    airborne_runs = sorted(extract_airborne_runs(segments, thresholds()), key=lambda run: int(run["start_ms"]))
    air_flags = interval_flags(
        segments,
        [(float(run["start_ms"]), float(run["end_ms"])) for run in airborne_runs],
    )
    pre_flags = midpoint_window_flags(
        segments,
        [(float(run["start_ms"]) - transition_window_ms, float(run["start_ms"])) for run in airborne_runs],
    )
    post_flags = midpoint_window_flags(
        segments,
        [(float(run["end_ms"]), float(run["end_ms"]) + transition_window_ms) for run in airborne_runs],
    )
    midpoints = [segment_midpoint_ms(segment) for segment in segments]
    commands = read_commands(run_dir, str(row.get("identity", "")))
    nearest = nearest_commands(commands, midpoints, margin_ms=command_margin_ms)

    buckets: dict[str, list[float]] = {key: [] for key, _label in BUCKETS}
    route_state_count = 0
    strong_command_count = 0
    for index, segment in enumerate(segments):
        speed = float(segment["horizontal_speed_qu_per_s"])
        buckets["all_segments"].append(speed)
        buckets["airborne_proxy_segments" if air_flags[index] else "non_airborne_segments"].append(speed)
        if pre_flags[index]:
            buckets["pre_air_window_segments"].append(speed)
        if post_flags[index]:
            buckets["post_air_window_segments"].append(speed)
        command = nearest[index]
        if not command:
            continue
        magnitude = command_magnitude(command)
        if magnitude >= STRONG_COMMAND_QU_PER_S:
            buckets["sampled_strong_command_segments"].append(speed)
            strong_command_count += 1
        else:
            buckets["sampled_weak_command_segments"].append(speed)
        state = command_route_state(command)
        if not state:
            continue
        route_state_count += 1
        dir_speed = route_dir_speed(state)
        if dir_speed is not None and dir_speed < LOW_ROUTE_DIR_SPEED:
            buckets["route_low_dir_speed_segments"].append(speed)
        if path_state(state) & WATER_PATH:
            buckets["route_water_path_segments"].append(speed)

    bucket_summaries = {key: summarize_values(values) for key, values in buckets.items()}
    return {
        "group": row.get("group", ""),
        "identity": row.get("identity", ""),
        "run_id": row.get("run_id", ""),
        "events_path": row.get("events_path", ""),
        "segment_count": len(segments),
        "airborne_proxy_count": len(airborne_runs),
        "dropped_teleport_segments": dropped_teleports,
        "moveprobe_command_count": len(commands),
        "sampled_strong_command_segment_count": strong_command_count,
        "route_state_segment_count": route_state_count,
        "speed_buckets": bucket_summaries,
    }


def group_summary(players: list[dict[str, object]]) -> dict[str, object]:
    summary: dict[str, object] = {"player_count": len(players)}
    for key, _label in BUCKETS:
        values = []
        for player in players:
            bucket = player.get("speed_buckets", {}).get(key, {}) if isinstance(player.get("speed_buckets"), dict) else {}
            if isinstance(bucket, dict) and bucket.get("count"):
                value = optional_float(bucket.get("p50"))
                if value is not None:
                    values.append(value)
        summary[key] = summarize_values(values)
    return summary


def build_comparison(reference_summary: dict[str, object], bot_summary: dict[str, object]) -> dict[str, object]:
    comparison = {}
    for key, label in BUCKETS:
        reference = reference_summary.get(key, {}) if isinstance(reference_summary.get(key), dict) else {}
        bot = bot_summary.get(key, {}) if isinstance(bot_summary.get(key), dict) else {}
        comparison[key] = {
            "label": label,
            "reference_player_p50_speed": reference,
            "bot_player_p50_speed": bot,
            "bot_to_reference_p50_ratio": ratio(bot, reference),
        }
    return comparison


def make_decision(comparison: dict[str, object]) -> dict[str, object]:
    def bucket_ratio(key: str) -> float | None:
        row = comparison.get(key, {}) if isinstance(comparison.get(key), dict) else {}
        return optional_float(row.get("bot_to_reference_p50_ratio"))

    air_ratio = bucket_ratio("airborne_proxy_segments")
    pre_ratio = bucket_ratio("pre_air_window_segments")
    post_ratio = bucket_ratio("post_air_window_segments")
    non_air_ratio = bucket_ratio("non_airborne_segments")
    water_speed = (
        comparison.get("route_water_path_segments", {})
        .get("bot_player_p50_speed", {})
        .get("p50")
        if isinstance(comparison.get("route_water_path_segments", {}), dict)
        and isinstance(comparison.get("route_water_path_segments", {}).get("bot_player_p50_speed"), dict)
        else None
    )
    water_speed_value = optional_float(water_speed)

    if (
        air_ratio is not None
        and pre_ratio is not None
        and post_ratio is not None
        and non_air_ratio is not None
        and air_ratio < 0.45
        and pre_ratio < 0.6
        and post_ratio < 0.6
        and non_air_ratio >= 0.85
    ):
        return {
            "verdict": "land_speed_gap_concentrates_around_air_transitions_and_route_low_dir_speed",
            "reason": (
                "The broad all-segment speed gap is not equally distributed. Bot non-airborne p50 speed is close "
                "to the exact-player non-airborne p50, but bot pre-air, airborne, and post-air windows are far "
                "below reference speed. Route-state samples also expose very slow WATER_PATH/low-dir-speed spans, "
                "so the next controller evidence should target speed production around air transitions and route "
                "primitives rather than cadence."
            ),
            "next_goal": (
                "S7h should decide whether the first controller probe targets air-transition horizontal speed "
                "production or a narrow route primitive such as WATER_PATH low-dir-speed recovery."
            ),
            "airborne_p50_ratio": air_ratio,
            "pre_air_p50_ratio": pre_ratio,
            "post_air_p50_ratio": post_ratio,
            "non_air_p50_ratio": non_air_ratio,
            "route_water_path_bot_p50_speed_qu_per_s": rounded(water_speed_value),
        }
    return {
        "verdict": "needs_more_land_speed_context",
        "reason": "The current segment buckets do not isolate a clear speed-gap target.",
        "next_goal": "Broaden or refine S7g segment context before a controller probe.",
        "airborne_p50_ratio": air_ratio,
        "pre_air_p50_ratio": pre_ratio,
        "post_air_p50_ratio": post_ratio,
        "non_air_p50_ratio": non_air_ratio,
        "route_water_path_bot_p50_speed_qu_per_s": rounded(water_speed_value),
    }


def build_report(
    source: dict[str, object],
    *,
    source_path: Path | None = None,
    stage: str,
    transition_window_ms: int,
    command_margin_ms: int,
) -> dict[str, object]:
    warnings = []
    players = []
    for row in [*source.get("reference_players", []), *source.get("bot_players", [])]:
        if not isinstance(row, dict):
            continue
        try:
            players.append(
                player_report(
                    row,
                    transition_window_ms=transition_window_ms,
                    command_margin_ms=command_margin_ms,
                )
            )
        except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
            warnings.append(f"{row.get('group', '')} `{row.get('identity', '')}` `{row.get('run_id', '')}`: {exc}")

    reference_players = [player for player in players if player.get("group") == "reference"]
    bot_players = [player for player in players if player.get("group") == "bot"]
    reference_summary = group_summary(reference_players)
    bot_summary = group_summary(bot_players)
    comparison = build_comparison(reference_summary, bot_summary)
    decision = make_decision(comparison)
    return {
        "schema": SCHEMA,
        "stage": stage,
        "source_airborne_segments_path": portable_path(source_path) if source_path else "",
        "source_airborne_segments_stage": source.get("stage", ""),
        "map": source.get("map", ""),
        "method": (
            "S7g reuses the S7f exact-player and unchanged mode-7 bot rows, then buckets accepted movement "
            "segments by airborne-proxy overlap, pre/post-air transition windows, sampled moveprobe command "
            "strength, and route-state hints when available."
        ),
        "transition_window_ms": transition_window_ms,
        "command_margin_ms": command_margin_ms,
        "strong_command_qu_per_s": STRONG_COMMAND_QU_PER_S,
        "low_route_dir_speed": LOW_ROUTE_DIR_SPEED,
        "warnings": warnings,
        "reference_players": reference_players,
        "bot_players": bot_players,
        "reference_summary": reference_summary,
        "bot_summary": bot_summary,
        "comparison": comparison,
        "decision": decision,
    }


def validate_report(report: dict[str, object]) -> None:
    warnings = report.get("warnings", [])
    if warnings:
        raise ReportInputError("; ".join(str(warning) for warning in warnings))
    if not report.get("reference_players"):
        raise ReportInputError("No reference players resolved for S7g.")
    if not report.get("bot_players"):
        raise ReportInputError("No bot players resolved for S7g.")


def fmt_speed(value: object) -> str:
    return format_comparison_value("avg_horizontal_speed_qu_per_s", value)


def fmt_ratio(value: object) -> str:
    number = optional_float(value)
    if number is None:
        return ""
    return f"{number:.3f}"


def write_markdown(report: dict[str, object], output_path: Path) -> None:
    comparison = report.get("comparison", {}) if isinstance(report.get("comparison"), dict) else {}
    lines = [
        f"# Land-Speed Gap Characterization {report.get('stage', '')}",
        "",
        "## Scope",
        "",
        f"- Map: `{report.get('map', '')}`",
        f"- Source S7f evidence: `{report.get('source_airborne_segments_path', '')}`",
        f"- Reference players: `{len(report.get('reference_players', []))}`",
        f"- Bot rows: `{len(report.get('bot_players', []))}`",
        f"- Transition window: `{report.get('transition_window_ms')}` ms",
        f"- Command match margin: `{report.get('command_margin_ms')}` ms",
        f"- {report.get('method', '')}",
        "",
        "## Group Comparison",
        "",
        "Group values are player-level p50 segment speeds summarized across players/rows, so one long human trace does not dominate.",
        "",
        "| Segment bucket | Reference p50 | Bot p50 | Bot/ref p50 |",
        "|---|---:|---:|---:|",
    ]
    for key, label in BUCKETS:
        row = comparison.get(key, {}) if isinstance(comparison.get(key), dict) else {}
        reference = row.get("reference_player_p50_speed", {}) if isinstance(row.get("reference_player_p50_speed"), dict) else {}
        bot = row.get("bot_player_p50_speed", {}) if isinstance(row.get("bot_player_p50_speed"), dict) else {}
        lines.append(
            "| "
            f"{label} | "
            f"{fmt_speed(reference.get('p50'))} | "
            f"{fmt_speed(bot.get('p50'))} | "
            f"{fmt_ratio(row.get('bot_to_reference_p50_ratio'))} |"
        )

    lines.extend(
        [
            "",
            "## Bot Route Context",
            "",
            "| Player | Run | Strong-command p50 | Low-dir-speed p50 | WATER_PATH p50 |",
            "|---|---|---:|---:|---:|",
        ]
    )
    for player in report.get("bot_players", []):
        if not isinstance(player, dict):
            continue
        buckets = player.get("speed_buckets", {}) if isinstance(player.get("speed_buckets"), dict) else {}
        lines.append(
            "| "
            f"`{player.get('identity', '')}` | "
            f"`{player.get('run_id', '')}` | "
            f"{fmt_speed(buckets.get('sampled_strong_command_segments', {}).get('p50') if isinstance(buckets.get('sampled_strong_command_segments'), dict) else None)} | "
            f"{fmt_speed(buckets.get('route_low_dir_speed_segments', {}).get('p50') if isinstance(buckets.get('route_low_dir_speed_segments'), dict) else None)} | "
            f"{fmt_speed(buckets.get('route_water_path_segments', {}).get('p50') if isinstance(buckets.get('route_water_path_segments'), dict) else None)} |"
        )

    decision = report.get("decision", {}) if isinstance(report.get("decision"), dict) else {}
    lines.extend(
        [
            "",
            "## Decision",
            "",
            f"- Verdict: `{decision.get('verdict', '')}`",
            f"- Airborne p50 ratio: `{decision.get('airborne_p50_ratio', '')}`",
            f"- Pre-air p50 ratio: `{decision.get('pre_air_p50_ratio', '')}`",
            f"- Post-air p50 ratio: `{decision.get('post_air_p50_ratio', '')}`",
            f"- Non-air p50 ratio: `{decision.get('non_air_p50_ratio', '')}`",
            f"- Route WATER_PATH bot p50 speed: `{decision.get('route_water_path_bot_p50_speed_qu_per_s', '')}` qu/s",
            f"- Reason: {decision.get('reason', '')}",
            f"- Next goal: {decision.get('next_goal', '')}",
        ]
    )
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Characterize S7g land-speed gaps around air and route segments.")
    parser.add_argument("--stage", default="s7g-land-speed-gap-dm3", help="Evidence stage label.")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help="S7f airborne segment evidence JSON.")
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON, help="Output evidence JSON.")
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD, help="Output evidence Markdown.")
    parser.add_argument("--transition-window-ms", type=int, default=DEFAULT_TRANSITION_WINDOW_MS)
    parser.add_argument("--command-margin-ms", type=int, default=DEFAULT_COMMAND_MARGIN_MS)
    return parser.parse_args(list(argv))


def main(argv: Iterable[str] = sys.argv[1:]) -> int:
    args = parse_args(argv)
    with args.source.open("r", encoding="utf-8") as handle:
        source = json.load(handle)
    if not isinstance(source, dict):
        raise ReportInputError(f"{args.source} did not contain a JSON object.")
    report = build_report(
        source,
        source_path=args.source,
        stage=args.stage,
        transition_window_ms=args.transition_window_ms,
        command_margin_ms=args.command_margin_ms,
    )
    validate_report(report)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_markdown(report, args.output_md)
    print(f"Wrote land-speed gap characterization: {args.output_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
