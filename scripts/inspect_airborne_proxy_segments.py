#!/usr/bin/env python3
"""Inspect raw airborne-proxy segment distributions for S7f."""

from __future__ import annotations

import logging
import argparse
import json
import math
import sys
from pathlib import Path
from typing import Iterable

from analyze_human_mvd import format_comparison_value, load_json_if_present, pct
from extract_movement_metrics import (
    DEFAULT_AIRBORNE_MIN_DURATION_MS,
    DEFAULT_AIRBORNE_MIN_Z_DELTA,
    DEFAULT_HIGH_SPEED,
    DEFAULT_LANDING_WINDOW_MS,
    DEFAULT_LOW_SPEED,
    DEFAULT_STATIONARY_SPEED,
    DEFAULT_TELEPORT_SPEED,
    DEFAULT_VERTICAL_EPSILON,
    DEFAULT_VERTICAL_SPEED,
    Sample,
    build_speed_window_index,
    coerce_origin,
    coerce_time_ms,
    percentile,
    read_json_if_present,
    weighted_speed_for_indexed_window,
)
from summarize_reference_aggregate import portable_path



LOGGER = logging.getLogger(__name__)
SCHEMA = "komodobots.airborne_proxy_segments.v1"
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REFERENCE_AGGREGATE = (
    REPO_ROOT
    / "experiments"
    / "human_comparison"
    / "evidence"
    / "human-reference-s7c-bot-comparable-cadence-dm3-aggregate.json"
)
DEFAULT_BOT_EVIDENCE = (
    REPO_ROOT
    / "experiments"
    / "human_comparison"
    / "evidence"
    / "cadence-evidence-s7e-dm3.json"
)


class ReportInputError(RuntimeError):
    """Raised when the requested evidence inputs cannot produce a full report."""


def optional_float(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def rounded(value: object, digits: int = 3) -> float | None:
    number = optional_float(value)
    if number is None:
        return None
    return round(number, digits)


def repo_path(value: object) -> Path:
    text = str(value or "").replace("\\", "/")
    path = Path(text)
    if path.is_absolute():
        return path
    return REPO_ROOT / path


def summarize_values(values: list[float]) -> dict[str, object]:
    if not values:
        return {"count": 0, "min": None, "mean": None, "p50": None, "p90": None, "p95": None, "max": None}
    return {
        "count": len(values),
        "min": round(min(values), 3),
        "mean": round(sum(values) / len(values), 3),
        "p50": round(percentile(values, 50), 3),
        "p90": round(percentile(values, 90), 3),
        "p95": round(percentile(values, 95), 3),
        "max": round(max(values), 3),
    }


def compare_percentile_ratio(bot: dict[str, object], reference: dict[str, object], percentile_key: str) -> float | None:
    bot_value = optional_float(bot.get(percentile_key))
    reference_value = optional_float(reference.get(percentile_key))
    if bot_value is None or reference_value is None or reference_value <= 0:
        return None
    return round(bot_value / reference_value, 3)


def compact_run(run: dict[str, object]) -> dict[str, object]:
    return {
        "start_ms": run.get("start_ms"),
        "end_ms": run.get("end_ms"),
        "duration_ms": rounded(run.get("duration_ms")),
        "z_delta_qu": rounded(run.get("z_delta_qu")),
        "avg_airborne_speed_qu_per_s": rounded(run.get("avg_airborne_speed_qu_per_s")),
        "landing_pre_speed_qu_per_s": rounded(run.get("landing_pre_speed_qu_per_s")),
        "landing_post_speed_qu_per_s": rounded(run.get("landing_post_speed_qu_per_s")),
        "landing_delta_qu_per_s": rounded(run.get("landing_delta_qu_per_s")),
    }


def thresholds() -> dict[str, float]:
    return {
        "stationary_speed_qu_per_s": float(DEFAULT_STATIONARY_SPEED),
        "low_speed_qu_per_s": float(DEFAULT_LOW_SPEED),
        "high_speed_qu_per_s": float(DEFAULT_HIGH_SPEED),
        "teleport_speed_qu_per_s": float(DEFAULT_TELEPORT_SPEED),
        "vertical_epsilon_qu": float(DEFAULT_VERTICAL_EPSILON),
        "vertical_speed_qu_per_s": float(DEFAULT_VERTICAL_SPEED),
        "airborne_min_duration_ms": float(DEFAULT_AIRBORNE_MIN_DURATION_MS),
        "airborne_min_z_delta_qu": float(DEFAULT_AIRBORNE_MIN_Z_DELTA),
        "landing_window_ms": float(DEFAULT_LANDING_WINDOW_MS),
    }


def coerce_optional_int(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def load_player_samples(run_dir: Path, player_name: str) -> tuple[dict[str, object], list[Sample]]:
    events_path = run_dir / "events.txt"
    if not events_path.exists():
        raise FileNotFoundError(events_path)

    analysis = read_json_if_present(run_dir / "analysis.json")
    match = analysis.get("match", {}) if isinstance(analysis, dict) else {}
    match_duration_ms = coerce_optional_int(match.get("duration"))
    players: dict[int, dict[str, object]] = {}
    samples_by_slot: dict[int, list[Sample]] = {}

    with events_path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            data = event.get("data") or {}
            kind = event.get("kind")
            if kind == 1 and isinstance(data.get("Player"), dict):
                player = data["Player"]
                try:
                    slot = int(player["Slot"])
                except (KeyError, TypeError, ValueError):
                    continue
                info = players.setdefault(
                    slot,
                    {
                        "slot": slot,
                        "name": "",
                        "spectator": bool(player.get("Spectator", False)),
                        "first_named_time_ms": None,
                    },
                )
                info["spectator"] = bool(player.get("Spectator", False))
                name = str(player.get("Name") or "")
                if name:
                    info["name"] = name
                    if info["first_named_time_ms"] is None:
                        info["first_named_time_ms"] = coerce_time_ms(event, data)
            elif kind == 5:
                try:
                    slot = int(data["PlayerNum"])
                except (KeyError, TypeError, ValueError):
                    continue
                origin = coerce_origin(data.get("Origin"))
                if origin is None:
                    continue
                samples_by_slot.setdefault(slot, []).append(
                    {
                        "time_ms": coerce_time_ms(event, data),
                        "origin": origin,
                    }
                )

    wanted = player_name.strip().lower()
    for slot, info in players.items():
        if str(info.get("name", "")).strip().lower() != wanted:
            continue
        samples = samples_by_slot.get(slot, [])
        first_named_time_ms = info.get("first_named_time_ms")
        if first_named_time_ms is not None:
            samples = [sample for sample in samples if sample["time_ms"] >= int(first_named_time_ms)]
        if match_duration_ms is not None:
            samples = [sample for sample in samples if sample["time_ms"] <= match_duration_ms]
        return info, samples
    raise ValueError(f"Could not find player {player_name!r} in {portable_path(run_dir)}")


def build_segments(samples: list[Sample], threshold_values: dict[str, float]) -> tuple[list[dict[str, object]], int]:
    ordered = sorted(samples, key=lambda sample: sample["time_ms"])
    if not ordered:
        return [], 0

    accepted_segments: list[dict[str, object]] = []
    dropped_teleports = 0
    previous = ordered[0]
    for current in ordered[1:]:
        dt_ms = current["time_ms"] - previous["time_ms"]
        if dt_ms <= 0:
            previous = current
            continue

        dx = current["origin"][0] - previous["origin"][0]
        dy = current["origin"][1] - previous["origin"][1]
        dz = current["origin"][2] - previous["origin"][2]
        horizontal_distance = math.hypot(dx, dy)
        horizontal_speed = horizontal_distance / (dt_ms / 1000.0)
        vertical_speed = dz / (dt_ms / 1000.0)
        if horizontal_speed > threshold_values["teleport_speed_qu_per_s"] or abs(vertical_speed) > threshold_values["teleport_speed_qu_per_s"]:
            dropped_teleports += 1
            previous = current
            continue

        vertical_motion = (
            abs(dz) >= threshold_values["vertical_epsilon_qu"]
            or abs(vertical_speed) >= threshold_values["vertical_speed_qu_per_s"]
        )
        accepted_segments.append(
            {
                "start_ms": previous["time_ms"],
                "end_ms": current["time_ms"],
                "dt_ms": dt_ms,
                "horizontal_distance_qu": horizontal_distance,
                "horizontal_speed_qu_per_s": horizontal_speed,
                "start_z": previous["origin"][2],
                "end_z": current["origin"][2],
                "vertical_motion": vertical_motion,
            }
        )
        previous = current
    return accepted_segments, dropped_teleports


def finalize_airborne_run(current: dict[str, object], threshold_values: dict[str, float]) -> dict[str, object] | None:
    duration_ms = int(current["end_ms"]) - int(current["start_ms"])
    z_delta = float(current["z_max"]) - float(current["z_min"])
    if duration_ms < int(threshold_values["airborne_min_duration_ms"]):
        return None
    if z_delta < threshold_values["airborne_min_z_delta_qu"]:
        return None
    total_ms = int(current["total_ms"])
    return {
        "start_ms": int(current["start_ms"]),
        "end_ms": int(current["end_ms"]),
        "duration_ms": duration_ms,
        "z_delta_qu": z_delta,
        "avg_airborne_speed_qu_per_s": float(current["weighted_speed"]) / total_ms if total_ms > 0 else 0.0,
    }


def extract_airborne_runs(segments: list[dict[str, object]], threshold_values: dict[str, float]) -> list[dict[str, object]]:
    runs: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    for segment in segments:
        if segment["vertical_motion"]:
            if current is None:
                current = {
                    "start_ms": segment["start_ms"],
                    "end_ms": segment["end_ms"],
                    "z_min": min(float(segment["start_z"]), float(segment["end_z"])),
                    "z_max": max(float(segment["start_z"]), float(segment["end_z"])),
                    "total_ms": int(segment["dt_ms"]),
                    "weighted_speed": float(segment["horizontal_speed_qu_per_s"]) * int(segment["dt_ms"]),
                }
            else:
                current["end_ms"] = segment["end_ms"]
                current["z_min"] = min(float(current["z_min"]), float(segment["start_z"]), float(segment["end_z"]))
                current["z_max"] = max(float(current["z_max"]), float(segment["start_z"]), float(segment["end_z"]))
                current["total_ms"] = int(current["total_ms"]) + int(segment["dt_ms"])
                current["weighted_speed"] = float(current["weighted_speed"]) + (
                    float(segment["horizontal_speed_qu_per_s"]) * int(segment["dt_ms"])
                )
        elif current is not None:
            run = finalize_airborne_run(current, threshold_values)
            if run is not None:
                runs.append(run)
            current = None

    if current is not None:
        run = finalize_airborne_run(current, threshold_values)
        if run is not None:
            runs.append(run)

    speed_index = build_speed_window_index(segments)
    landing_window_ms = int(threshold_values["landing_window_ms"])
    previous_end_ms: int | None = None
    for run in runs:
        landing_ms = int(run["end_ms"])
        pre_speed = weighted_speed_for_indexed_window(speed_index, landing_ms - landing_window_ms, landing_ms)
        post_speed = weighted_speed_for_indexed_window(speed_index, landing_ms, landing_ms + landing_window_ms)
        run["landing_pre_speed_qu_per_s"] = pre_speed if pre_speed is not None else 0.0
        run["landing_post_speed_qu_per_s"] = post_speed if post_speed is not None else 0.0
        run["landing_delta_qu_per_s"] = run["landing_post_speed_qu_per_s"] - run["landing_pre_speed_qu_per_s"]
        run["gap_since_previous_airborne_ms"] = (
            int(run["start_ms"]) - previous_end_ms if previous_end_ms is not None else None
        )
        previous_end_ms = int(run["end_ms"])
    return runs


def run_distribution(runs: list[dict[str, object]]) -> dict[str, object]:
    fields = (
        "duration_ms",
        "z_delta_qu",
        "avg_airborne_speed_qu_per_s",
        "landing_pre_speed_qu_per_s",
        "landing_post_speed_qu_per_s",
        "landing_delta_qu_per_s",
        "gap_since_previous_airborne_ms",
    )
    return {field: summarize_values([float(run[field]) for run in runs if optional_float(run.get(field)) is not None]) for field in fields}


def compact_player_report(
    *,
    group: str,
    identity: str,
    run_id: str,
    run_dir: Path,
    source_path: Path,
    metrics_row: dict[str, object],
    threshold_values: dict[str, float],
) -> dict[str, object]:
    player_info, samples = load_player_samples(run_dir, identity)
    segments, dropped_teleports = build_segments(samples, threshold_values)
    runs = extract_airborne_runs(segments, threshold_values)
    active_ms = sum(int(segment["dt_ms"]) for segment in segments)
    horizontal_distance = sum(float(segment["horizontal_distance_qu"]) for segment in segments)
    active_s = active_ms / 1000.0
    segment_speeds = [float(segment["horizontal_speed_qu_per_s"]) for segment in segments]
    return {
        "group": group,
        "identity": identity,
        "matched_name": player_info.get("name", identity),
        "run_id": run_id,
        "source_path": portable_path(source_path),
        "events_path": portable_path(run_dir / "events.txt"),
        "sample_count": len(samples),
        "accepted_segment_count": len(segments),
        "dropped_teleport_segments": dropped_teleports,
        "active_time_s": rounded(active_s),
        "airborne_proxy_count": len(runs),
        "raw_active_avg_speed_qu_per_s": rounded(horizontal_distance / active_s if active_s else 0.0),
        "raw_segment_p95_speed_qu_per_s": rounded(percentile(segment_speeds, 95) if segment_speeds else 0.0),
        "metrics_avg_horizontal_speed_qu_per_s": rounded(metrics_row.get("avg_horizontal_speed_qu_per_s")),
        "metrics_p95_horizontal_speed_qu_per_s": rounded(metrics_row.get("p95_horizontal_speed_qu_per_s")),
        "metrics_airborne_proxy_time_ratio": rounded(metrics_row.get("airborne_proxy_time_ratio")),
        "metrics_jump_cadence_per_min": rounded(metrics_row.get("jump_cadence_per_min")),
        "airborne_distribution": run_distribution(runs),
        "sample_airborne_runs_by_duration": [compact_run(run) for run in sorted(runs, key=lambda row: float(row["duration_ms"]), reverse=True)[:5]],
    }


def reference_run_dir(reference_row: dict[str, object]) -> tuple[Path, Path]:
    summary_path = repo_path(reference_row.get("summary_path"))
    summary = load_json_if_present(summary_path)
    artifact_dir = summary.get("artifact_dir") if isinstance(summary, dict) else None
    if artifact_dir:
        return repo_path(artifact_dir), summary_path
    if summary_path.parent.joinpath("events.txt").exists():
        return summary_path.parent, summary_path
    run_id = str(reference_row.get("run_id", ""))
    for candidate in (REPO_ROOT / "artifacts" / "human-demos").rglob(run_id):
        if candidate.is_dir() and candidate.joinpath("events.txt").exists():
            return candidate, summary_path
    raise FileNotFoundError(f"Could not resolve artifact directory for reference row `{run_id}`.")


def metric_row_from_run_dir(run_dir: Path, identity: str) -> dict[str, object]:
    metrics = load_json_if_present(run_dir / "movement-metrics.json")
    for player in metrics.get("players", []) if isinstance(metrics, dict) else []:
        if isinstance(player, dict) and str(player.get("name", "")).strip().lower() == identity.strip().lower():
            return player
    return {}


def reference_reports(aggregate: dict[str, object], threshold_values: dict[str, float]) -> tuple[list[dict[str, object]], list[str]]:
    reports = []
    warnings = []
    for row in aggregate.get("reference_rows", []):
        if not isinstance(row, dict):
            continue
        try:
            run_dir, summary_path = reference_run_dir(row)
            identity = str(row.get("matched_player") or row.get("target_player") or "")
            metrics_row = metric_row_from_run_dir(run_dir, identity)
            reports.append(
                compact_player_report(
                    group="reference",
                    identity=identity,
                    run_id=str(row.get("run_id", "")),
                    run_dir=run_dir,
                    source_path=summary_path,
                    metrics_row=metrics_row or row,
                    threshold_values=threshold_values,
                )
            )
        except (FileNotFoundError, ValueError) as exc:
            warnings.append(str(exc))
    return reports, warnings


def bot_reports(bot_evidence: dict[str, object], threshold_values: dict[str, float]) -> tuple[list[dict[str, object]], list[str]]:
    reports = []
    warnings = []
    for row in bot_evidence.get("bot_rows", []):
        if not isinstance(row, dict):
            continue
        try:
            metrics_path = repo_path(row.get("source_metrics_path"))
            run_dir = metrics_path.parent
            identity = str(row.get("player") or "")
            reports.append(
                compact_player_report(
                    group="bot",
                    identity=identity,
                    run_id=str(row.get("run_id", "")),
                    run_dir=run_dir,
                    source_path=metrics_path,
                    metrics_row=row,
                    threshold_values=threshold_values,
                )
            )
        except (FileNotFoundError, ValueError) as exc:
            warnings.append(str(exc))
    return reports, warnings


def collect_group_runs(players: list[dict[str, object]]) -> dict[str, list[float]]:
    values: dict[str, list[float]] = {
        "duration_ms": [],
        "z_delta_qu": [],
        "avg_airborne_speed_qu_per_s": [],
        "landing_pre_speed_qu_per_s": [],
        "landing_post_speed_qu_per_s": [],
        "landing_delta_qu_per_s": [],
    }
    for player in players:
        distribution = player.get("airborne_distribution", {})
        if not isinstance(distribution, dict):
            continue
        # Aggregate player-level medians so one long reference row cannot dominate the group comparison.
        for field in values:
            summary = distribution.get(field, {}) if isinstance(distribution.get(field), dict) else {}
            value = optional_float(summary.get("p50"))
            if value is not None:
                values[field].append(value)
    return values


def group_summary(players: list[dict[str, object]]) -> dict[str, object]:
    fields = (
        "airborne_proxy_count",
        "raw_active_avg_speed_qu_per_s",
        "raw_segment_p95_speed_qu_per_s",
        "metrics_airborne_proxy_time_ratio",
        "metrics_jump_cadence_per_min",
    )
    summary: dict[str, object] = {
        "player_count": len(players),
        "airborne_proxy_total_count": sum(int(player.get("airborne_proxy_count", 0)) for player in players),
    }
    for field in fields:
        summary[field] = summarize_values(
            [float(player[field]) for player in players if optional_float(player.get(field)) is not None]
        )
    for field, values in collect_group_runs(players).items():
        summary[f"player_p50_{field}"] = summarize_values(values)
    return summary


def build_comparison(reference_summary: dict[str, object], bot_summary: dict[str, object]) -> dict[str, object]:
    fields = (
        "player_p50_duration_ms",
        "player_p50_z_delta_qu",
        "player_p50_avg_airborne_speed_qu_per_s",
        "player_p50_landing_pre_speed_qu_per_s",
        "raw_active_avg_speed_qu_per_s",
        "raw_segment_p95_speed_qu_per_s",
    )
    comparison = {}
    for field in fields:
        reference = reference_summary.get(field, {}) if isinstance(reference_summary.get(field), dict) else {}
        bot = bot_summary.get(field, {}) if isinstance(bot_summary.get(field), dict) else {}
        comparison[field] = {
            "reference": reference,
            "bot": bot,
            "bot_to_reference_p50_ratio": compare_percentile_ratio(bot, reference, "p50"),
        }
    return comparison


def make_decision(comparison: dict[str, object]) -> dict[str, object]:
    duration_ratio = optional_float(
        comparison.get("player_p50_duration_ms", {}).get("bot_to_reference_p50_ratio")
        if isinstance(comparison.get("player_p50_duration_ms"), dict)
        else None
    )
    z_ratio = optional_float(
        comparison.get("player_p50_z_delta_qu", {}).get("bot_to_reference_p50_ratio")
        if isinstance(comparison.get("player_p50_z_delta_qu"), dict)
        else None
    )
    air_speed_ratio = optional_float(
        comparison.get("player_p50_avg_airborne_speed_qu_per_s", {}).get("bot_to_reference_p50_ratio")
        if isinstance(comparison.get("player_p50_avg_airborne_speed_qu_per_s"), dict)
        else None
    )
    active_speed_ratio = optional_float(
        comparison.get("raw_active_avg_speed_qu_per_s", {}).get("bot_to_reference_p50_ratio")
        if isinstance(comparison.get("raw_active_avg_speed_qu_per_s"), dict)
        else None
    )
    if (
        duration_ratio is not None
        and z_ratio is not None
        and air_speed_ratio is not None
        and duration_ratio < 0.75
        and z_ratio < 0.35
        and air_speed_ratio < 0.45
    ):
        return {
            "verdict": "pivot_from_cadence_to_air_rhythm_and_land_speed_gap",
            "reason": (
                "Raw airborne-proxy segments are not human-like jumps: bot player-median airborne runs are "
                "shorter, much lower-Z, and much slower than the exact-player references. The high "
                "airborne-proxy-normalized cadence is therefore a symptom of broken air/land rhythm, not a "
                "controller-ready cadence target."
            ),
            "next_goal": (
                "S7g should characterize the land-speed gap around route and air segments before another "
                "controller probe. Cadence should stay diagnostic until bots can produce human-scale "
                "airborne segments and horizontal speed."
            ),
            "duration_p50_ratio": duration_ratio,
            "z_delta_p50_ratio": z_ratio,
            "airborne_speed_p50_ratio": air_speed_ratio,
            "active_speed_p50_ratio": active_speed_ratio,
        }
    return {
        "verdict": "needs_more_airborne_segment_evidence",
        "reason": "The raw airborne-proxy segment distributions do not yet justify a clear pivot.",
        "next_goal": "Add more raw segment evidence before controller work.",
        "duration_p50_ratio": duration_ratio,
        "z_delta_p50_ratio": z_ratio,
        "airborne_speed_p50_ratio": air_speed_ratio,
        "active_speed_p50_ratio": active_speed_ratio,
    }


def build_report(
    reference_aggregate: dict[str, object],
    bot_evidence: dict[str, object],
    *,
    stage: str,
    reference_aggregate_path: Path | None = None,
    bot_evidence_path: Path | None = None,
) -> dict[str, object]:
    threshold_values = thresholds()
    references, reference_warnings = reference_reports(reference_aggregate, threshold_values)
    bots, bot_warnings = bot_reports(bot_evidence, threshold_values)
    reference_summary = group_summary(references)
    bot_summary = group_summary(bots)
    comparison = build_comparison(reference_summary, bot_summary)
    decision = make_decision(comparison)
    return {
        "schema": SCHEMA,
        "stage": stage,
        "map": reference_aggregate.get("map", ""),
        "source_reference_aggregate_path": portable_path(reference_aggregate_path) if reference_aggregate_path else "",
        "source_reference_aggregate_stage": reference_aggregate.get("stage", ""),
        "source_bot_evidence_path": portable_path(bot_evidence_path) if bot_evidence_path else "",
        "source_bot_evidence_stage": bot_evidence.get("stage", ""),
        "method": (
            "S7f replays the movement-metrics airborne proxy over raw events.txt kind 5 samples, then records "
            "compact per-player distributions for the exact-player dm3 reference rows and unchanged mode-7 bot rows."
        ),
        "thresholds": threshold_values,
        "warnings": reference_warnings + bot_warnings,
        "reference_players": references,
        "bot_players": bots,
        "reference_summary": reference_summary,
        "bot_summary": bot_summary,
        "comparison": comparison,
        "decision": decision,
    }


def validate_report_inputs(report: dict[str, object]) -> None:
    reference_players = report.get("reference_players", [])
    bot_players = report.get("bot_players", [])
    warnings = report.get("warnings", [])
    warning_text = "; ".join(str(warning) for warning in warnings if warning)
    if warnings:
        raise ReportInputError(f"Could not resolve every requested S7f input row: {warning_text}")
    if not isinstance(reference_players, list) or not reference_players:
        raise ReportInputError("No reference player rows resolved; refusing to write empty S7f evidence.")
    if not isinstance(bot_players, list) or not bot_players:
        raise ReportInputError("No bot rows resolved; refusing to write empty S7f evidence.")


def format_summary(summary: dict[str, object], field: str) -> str:
    values = summary.get(field, {}) if isinstance(summary.get(field), dict) else {}
    if not values.get("count"):
        return ""
    return (
        f"{format_comparison_value(field, values.get('p50'))} p50 / "
        f"{format_comparison_value(field, values.get('p95'))} p95"
    )


def write_markdown(report: dict[str, object], output_path: Path) -> None:
    reference_summary = report.get("reference_summary", {}) if isinstance(report.get("reference_summary"), dict) else {}
    bot_summary = report.get("bot_summary", {}) if isinstance(report.get("bot_summary"), dict) else {}
    comparison = report.get("comparison", {}) if isinstance(report.get("comparison"), dict) else {}
    lines = [
        f"# Airborne Proxy Segment Inspection {report.get('stage', '')}",
        "",
        "## Scope",
        "",
        f"- Map: `{report.get('map', '')}`",
        f"- Source reference aggregate: `{report.get('source_reference_aggregate_path', '')}`",
        f"- Source bot evidence: `{report.get('source_bot_evidence_path', '')}`",
        f"- Reference players: `{reference_summary.get('player_count', 0)}`",
        f"- Bot rows: `{bot_summary.get('player_count', 0)}`",
        f"- {report.get('method', '')}",
        "",
        "## Group Comparison",
        "",
        "| Axis | Reference | Bot | Bot/ref p50 |",
        "|---|---:|---:|---:|",
    ]
    table_fields = (
        ("player_p50_duration_ms", "Player-median air duration"),
        ("player_p50_z_delta_qu", "Player-median air Z range"),
        ("player_p50_avg_airborne_speed_qu_per_s", "Player-median air speed"),
        ("player_p50_landing_pre_speed_qu_per_s", "Player-median pre-landing speed"),
        ("raw_active_avg_speed_qu_per_s", "Raw active avg speed"),
        ("raw_segment_p95_speed_qu_per_s", "Raw segment p95 speed"),
    )
    for field, label in table_fields:
        row = comparison.get(field, {}) if isinstance(comparison.get(field), dict) else {}
        reference = row.get("reference", {}) if isinstance(row.get("reference"), dict) else {}
        bot = row.get("bot", {}) if isinstance(row.get("bot"), dict) else {}
        ratio = row.get("bot_to_reference_p50_ratio")
        lines.append(
            "| "
            f"{label} | "
            f"{format_comparison_value(field, reference.get('p50'))} | "
            f"{format_comparison_value(field, bot.get('p50'))} | "
            f"{format_comparison_value(field, ratio)} |"
        )

    lines.extend(
        [
            "",
            "## Player Rows",
            "",
            "| Group | Player | Run | Air runs | Air duration | Air Z | Air speed | Active avg | Segment p95 | Air ratio | Cadence |",
            "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for player in [*report.get("reference_players", []), *report.get("bot_players", [])]:
        if not isinstance(player, dict):
            continue
        distribution = player.get("airborne_distribution", {}) if isinstance(player.get("airborne_distribution"), dict) else {}
        lines.append(
            "| "
            f"`{player.get('group', '')}` | "
            f"`{player.get('identity', '')}` | "
            f"`{player.get('run_id', '')}` | "
            f"{player.get('airborne_proxy_count', 0)} | "
            f"{format_summary(distribution, 'duration_ms')} | "
            f"{format_summary(distribution, 'z_delta_qu')} | "
            f"{format_summary(distribution, 'avg_airborne_speed_qu_per_s')} | "
            f"{format_comparison_value('avg_horizontal_speed_qu_per_s', player.get('raw_active_avg_speed_qu_per_s'))} | "
            f"{format_comparison_value('p95_horizontal_speed_qu_per_s', player.get('raw_segment_p95_speed_qu_per_s'))} | "
            f"{pct(player.get('metrics_airborne_proxy_time_ratio'))} | "
            f"{format_comparison_value('jump_cadence_per_min', player.get('metrics_jump_cadence_per_min'))} |"
        )

    warnings = report.get("warnings", []) if isinstance(report.get("warnings"), list) else []
    if warnings:
        lines.extend(["", "## Warnings", ""])
        for warning in warnings:
            lines.append(f"- {warning}")

    decision = report.get("decision", {}) if isinstance(report.get("decision"), dict) else {}
    lines.extend(
        [
            "",
            "## Decision",
            "",
            f"- Verdict: `{decision.get('verdict', '')}`",
            f"- Duration p50 ratio: `{decision.get('duration_p50_ratio', '')}`",
            f"- Z-delta p50 ratio: `{decision.get('z_delta_p50_ratio', '')}`",
            f"- Airborne-speed p50 ratio: `{decision.get('airborne_speed_p50_ratio', '')}`",
            f"- Active-speed p50 ratio: `{decision.get('active_speed_p50_ratio', '')}`",
            f"- Reason: {decision.get('reason', '')}",
            f"- Next goal: {decision.get('next_goal', '')}",
        ]
    )
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect raw airborne-proxy segment distributions.")
    parser.add_argument("--stage", default="s7f-airborne-segments-dm3", help="Evidence stage label.")
    parser.add_argument(
        "--reference-aggregate",
        type=Path,
        default=DEFAULT_REFERENCE_AGGREGATE,
        help="S7c bot-comparable cadence aggregate JSON.",
    )
    parser.add_argument(
        "--bot-evidence",
        type=Path,
        default=DEFAULT_BOT_EVIDENCE,
        help="S7e broadened bot cadence evidence JSON.",
    )
    parser.add_argument("--output-json", type=Path, required=True, help="Output evidence JSON.")
    parser.add_argument("--output-md", type=Path, required=True, help="Output evidence Markdown.")
    return parser.parse_args(list(argv))


def main(argv: Iterable[str] = sys.argv[1:]) -> int:
    args = parse_args(argv)
    reference_aggregate = load_json_if_present(args.reference_aggregate)
    if not reference_aggregate:
        raise FileNotFoundError(args.reference_aggregate)
    bot_evidence = load_json_if_present(args.bot_evidence)
    if not bot_evidence:
        raise FileNotFoundError(args.bot_evidence)
    report = build_report(
        reference_aggregate,
        bot_evidence,
        stage=args.stage,
        reference_aggregate_path=args.reference_aggregate,
        bot_evidence_path=args.bot_evidence,
    )
    validate_report_inputs(report)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_markdown(report, args.output_md)
    print(f"Wrote airborne proxy segment inspection: {args.output_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
