#!/usr/bin/env python3
"""Diagnose corrected S7j failed buckets before another controller probe."""

from __future__ import annotations

import logging
import argparse
import json
import math
import sys
from pathlib import Path
from typing import Iterable

from analyze_human_mvd import format_comparison_value
from characterize_land_speed_gap import (
    LOW_ROUTE_DIR_SPEED,
    WATER_PATH,
    build_segments,
    command_magnitude,
    command_route_state,
    extract_airborne_runs,
    interval_flags,
    load_player_samples,
    midpoint_window_flags,
    nearest_commands,
    optional_float,
    path_state,
    read_commands,
    repo_path,
    route_dir_speed,
    segment_midpoint_ms,
    summarize_values,
    thresholds,
)
from summarize_reference_aggregate import portable_path



LOGGER = logging.getLogger(__name__)
SCHEMA = "komodobots.s7j_failed_bucket_diagnosis.v1"
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_S7J = REPO_ROOT / "experiments" / "human_comparison" / "evidence" / "air-transition-probe-s7j-dm3.json"
DEFAULT_S7G = REPO_ROOT / "experiments" / "human_comparison" / "evidence" / "land-speed-gap-s7g-dm3.json"
DEFAULT_OUTPUT_JSON = (
    REPO_ROOT / "experiments" / "human_comparison" / "evidence" / "failed-bucket-diagnosis-s7k-dm3.json"
)
DEFAULT_OUTPUT_MD = (
    REPO_ROOT / "experiments" / "human_comparison" / "evidence" / "failed-bucket-diagnosis-s7k-dm3.md"
)
DEFAULT_CONTEXT_SOURCE = (
    REPO_ROOT / "experiments" / "human_comparison" / "evidence" / "failed-bucket-context-source-s7k-dm3.json"
)

FAILED_BUCKETS = ("pre_air_window_segments", "airborne_proxy_segments", "non_airborne_segments")
BUCKET_LABELS = {
    "pre_air_window_segments": "Pre-air window",
    "airborne_proxy_segments": "Airborne-proxy segments",
    "post_air_window_segments": "Post-air window",
    "non_airborne_segments": "Non-airborne segments",
}
AIR_BUCKETS = ("pre_air_window_segments", "airborne_proxy_segments", "post_air_window_segments")


class S7kInputError(RuntimeError):
    """Raised when S7k cannot resolve the committed or local evidence inputs."""


def load_json(path: Path) -> dict[str, object]:
    with path.open("r", encoding="utf-8") as handle:
        loaded = json.load(handle)
    if not isinstance(loaded, dict):
        raise S7kInputError(f"{portable_path(path)} did not contain a JSON object.")
    return loaded


def rounded(value: object, digits: int = 3) -> float | None:
    number = optional_float(value)
    if number is None:
        return None
    return round(number, digits)


def ratio(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 3)


def safe_bool(value: object) -> bool:
    return bool(value) if isinstance(value, bool) else False


def compact_unique(values: Iterable[object], limit: int = 10) -> list[object]:
    clean = sorted({value for value in values if value not in ("", None)}, key=str)
    if len(clean) <= limit:
        return clean
    return [*clean[:limit], f"... {len(clean) - limit} more"]


def bucket_changes_by_key(s7j: dict[str, object]) -> dict[str, dict[str, object]]:
    rows = s7j.get("bucket_changes", [])
    if not isinstance(rows, list):
        return {}
    return {
        str(row.get("bucket")): row
        for row in rows
        if isinstance(row, dict) and row.get("bucket")
    }


def bucket_flags(
    bucket: str,
    air_flags: list[bool],
    pre_flags: list[bool],
    post_flags: list[bool],
) -> list[bool]:
    if bucket == "airborne_proxy_segments":
        return air_flags
    if bucket == "pre_air_window_segments":
        return pre_flags
    if bucket == "post_air_window_segments":
        return post_flags
    if bucket == "non_airborne_segments":
        return [not flag for flag in air_flags]
    raise S7kInputError(f"Unsupported bucket for S7k diagnosis: {bucket}")


def command_probe_state(command: dict[str, object] | None) -> dict[str, object]:
    if not command or not isinstance(command.get("probe_state"), dict):
        return {}
    return command["probe_state"]


def summarize_bucket_context(
    row: dict[str, object],
    bucket: str,
    *,
    transition_window_ms: int,
    command_margin_ms: int,
) -> dict[str, object]:
    events_path = row.get("events_path") or ""
    run_dir = repo_path(events_path).parent
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
    selected_flags = bucket_flags(bucket, air_flags, pre_flags, post_flags)
    midpoints = [segment_midpoint_ms(segment) for segment in segments]
    commands = read_commands(run_dir, str(row.get("identity", "")))
    nearest = nearest_commands(commands, midpoints, margin_ms=command_margin_ms)

    speeds: list[float] = []
    active_speeds: list[float] = []
    inactive_speeds: list[float] = []
    command_magnitudes: list[float] = []
    path_states: list[int] = []
    dir_speeds: list[float] = []
    sampled_count = 0
    strong_count = 0
    weak_count = 0
    probe_state_count = 0
    probe_active_count = 0
    probe_on_ground_count = 0
    water_path_count = 0
    low_dir_speed_count = 0

    for index, segment in enumerate(segments):
        if not selected_flags[index]:
            continue
        speed = optional_float(segment.get("horizontal_speed_qu_per_s"))
        if speed is None:
            continue
        speeds.append(speed)
        command = nearest[index]
        if command is None:
            continue
        sampled_count += 1
        magnitude = command_magnitude(command)
        command_magnitudes.append(magnitude)
        if magnitude >= 400.0:
            strong_count += 1
        else:
            weak_count += 1
        probe_state = command_probe_state(command)
        if probe_state:
            probe_state_count += 1
            if safe_bool(probe_state.get("transition_active")):
                probe_active_count += 1
                active_speeds.append(speed)
            else:
                inactive_speeds.append(speed)
            if safe_bool(probe_state.get("on_ground")):
                probe_on_ground_count += 1
        state = command_route_state(command)
        if state:
            p_state = path_state(state)
            if p_state is not None:
                path_states.append(p_state)
                if p_state & WATER_PATH:
                    water_path_count += 1
            dir_speed = route_dir_speed(state)
            if dir_speed is not None:
                dir_speeds.append(dir_speed)
                if dir_speed < LOW_ROUTE_DIR_SPEED:
                    low_dir_speed_count += 1

    segment_count = len(speeds)
    return {
        "bucket": bucket,
        "label": BUCKET_LABELS.get(bucket, bucket),
        "run_id": row.get("run_id", ""),
        "player": row.get("identity", ""),
        "segment_count": segment_count,
        "dropped_teleport_segments": dropped_teleports,
        "speed": summarize_values(speeds),
        "sampled_command_count": sampled_count,
        "sampled_command_ratio": ratio(sampled_count, segment_count),
        "strong_command_count": strong_count,
        "strong_command_ratio": ratio(strong_count, sampled_count),
        "weak_command_count": weak_count,
        "probe_state_count": probe_state_count,
        "probe_active_count": probe_active_count,
        "probe_active_ratio": ratio(probe_active_count, probe_state_count),
        "probe_on_ground_ratio": ratio(probe_on_ground_count, probe_state_count),
        "probe_active_speed": summarize_values(active_speeds),
        "probe_inactive_speed": summarize_values(inactive_speeds),
        "command_magnitude": summarize_values(command_magnitudes),
        "low_dir_speed_count": low_dir_speed_count,
        "low_dir_speed_ratio": ratio(low_dir_speed_count, sampled_count),
        "water_path_count": water_path_count,
        "water_path_ratio": ratio(water_path_count, sampled_count),
        "route_dir_speed": summarize_values(dir_speeds),
        "path_state_values": compact_unique(path_states),
    }


def combine_context(player_rows: list[dict[str, object]], bucket: str) -> dict[str, object]:
    selected = [row for row in player_rows if row.get("bucket") == bucket]
    segment_count = sum(int(row.get("segment_count", 0) or 0) for row in selected)
    sampled_count = sum(int(row.get("sampled_command_count", 0) or 0) for row in selected)
    probe_state_count = sum(int(row.get("probe_state_count", 0) or 0) for row in selected)
    p50_values = [
        value
        for row in selected
        if (value := optional_float(row.get("speed", {}).get("p50") if isinstance(row.get("speed"), dict) else None))
        is not None
    ]
    max_low_dir_ratio = max((optional_float(row.get("low_dir_speed_ratio")) or 0.0 for row in selected), default=0.0)
    max_water_ratio = max((optional_float(row.get("water_path_ratio")) or 0.0 for row in selected), default=0.0)
    route_dominated_players = [
        {
            "player": row.get("player", ""),
            "run_id": row.get("run_id", ""),
            "p50_speed_qu_per_s": row.get("speed", {}).get("p50") if isinstance(row.get("speed"), dict) else None,
            "low_dir_speed_ratio": row.get("low_dir_speed_ratio"),
            "water_path_ratio": row.get("water_path_ratio"),
        }
        for row in selected
        if (optional_float(row.get("low_dir_speed_ratio")) or 0.0) >= 0.5
        or (optional_float(row.get("water_path_ratio")) or 0.0) >= 0.5
    ]
    return {
        "bucket": bucket,
        "label": BUCKET_LABELS.get(bucket, bucket),
        "player_row_count": len(selected),
        "segment_count": segment_count,
        "sampled_command_count": sampled_count,
        "sampled_command_ratio": ratio(sampled_count, segment_count),
        "strong_command_count": sum(int(row.get("strong_command_count", 0) or 0) for row in selected),
        "strong_command_ratio": ratio(
            sum(int(row.get("strong_command_count", 0) or 0) for row in selected),
            sampled_count,
        ),
        "probe_state_count": probe_state_count,
        "probe_active_count": sum(int(row.get("probe_active_count", 0) or 0) for row in selected),
        "probe_active_ratio": ratio(
            sum(int(row.get("probe_active_count", 0) or 0) for row in selected),
            probe_state_count,
        ),
        "low_dir_speed_count": sum(int(row.get("low_dir_speed_count", 0) or 0) for row in selected),
        "low_dir_speed_ratio": ratio(
            sum(int(row.get("low_dir_speed_count", 0) or 0) for row in selected),
            sampled_count,
        ),
        "water_path_count": sum(int(row.get("water_path_count", 0) or 0) for row in selected),
        "water_path_ratio": ratio(
            sum(int(row.get("water_path_count", 0) or 0) for row in selected),
            sampled_count,
        ),
        "max_player_low_dir_speed_ratio": round(max_low_dir_ratio, 3),
        "max_player_water_path_ratio": round(max_water_ratio, 3),
        "route_dominated_players": route_dominated_players,
        "player_p50_speed_summary": summarize_values(p50_values),
    }


def classify_bucket_failure(change: dict[str, object], context: dict[str, object]) -> dict[str, object]:
    bucket = str(change.get("bucket", ""))
    water_ratio = optional_float(context.get("water_path_ratio")) or 0.0
    low_dir_ratio = optional_float(context.get("low_dir_speed_ratio")) or 0.0
    strong_ratio = optional_float(context.get("strong_command_ratio")) or 0.0
    sampled_ratio = optional_float(context.get("sampled_command_ratio")) or 0.0
    probe_active_ratio = optional_float(context.get("probe_active_ratio")) or 0.0
    max_player_water_ratio = optional_float(context.get("max_player_water_path_ratio"))
    if max_player_water_ratio is None:
        max_player_water_ratio = water_ratio
    max_player_low_dir_ratio = optional_float(context.get("max_player_low_dir_speed_ratio"))
    if max_player_low_dir_ratio is None:
        max_player_low_dir_ratio = low_dir_ratio
    regressed = bool(change.get("regressed_more_than_5pct", False))

    if sampled_ratio < 0.5:
        return {
            "cause_class": "measurement_alignment_risk",
            "confidence": "medium",
            "reason": "Too few bucket segments had nearby sampled command/probe rows for a strong cause claim.",
        }
    if bucket == "non_airborne_segments" and regressed and (
        water_ratio >= 0.25
        or low_dir_ratio >= 0.25
        or max_player_water_ratio >= 0.5
        or max_player_low_dir_ratio >= 0.5
    ):
        return {
            "cause_class": "route_or_map_context_guardrail_contamination",
            "confidence": "high",
            "reason": (
                "The non-airborne guardrail regression is concentrated in route low-dir-speed and/or WATER_PATH "
                "context, so it should not be read as a pure air-transition controller failure."
            ),
        }
    if bucket in AIR_BUCKETS and regressed and strong_ratio >= 0.75:
        if water_ratio >= 0.25 or low_dir_ratio >= 0.25:
            return {
                "cause_class": "mixed_controller_and_route_context",
                "confidence": "medium",
                "reason": (
                    "The failed air bucket has strong command coverage but also substantial route low-dir-speed "
                    "or WATER_PATH context."
                ),
            }
        return {
            "cause_class": "controller_policy_or_physics_timing",
            "confidence": "medium",
            "reason": (
                "The failed air bucket had nearby strong commands and probe reporting, but speed still regressed; "
                "that points at command policy/timing rather than missing command emission."
            ),
        }
    if regressed and probe_active_ratio > 0.0:
        return {
            "cause_class": "controller_probe_interaction",
            "confidence": "medium",
            "reason": "The bucket regressed with observed transition-probe activation, but the context is not clean enough to isolate.",
        }
    return {
        "cause_class": "mixed_or_unclassified",
        "confidence": "low",
        "reason": "The available S7j artifacts do not isolate a single dominant cause for this bucket.",
    }


def decision_gates() -> list[dict[str, object]]:
    return [
        {
            "gate": "engine_native_substrate",
            "continue_frogbots_if": (
                "KTX/Frogbots continue to spawn, fight, accept controller overrides, emit command diagnostics, "
                "and produce MVD evidence without rebuilding physics/collision/combat."
            ),
            "abandon_or_rebuild_if": (
                "The needed movement evidence cannot be gathered inside KTX/Frogbots, or controller hooks corrupt "
                "core server-native behavior."
            ),
        },
        {
            "gate": "isolated_movement_primitive",
            "continue_frogbots_if": (
                "A tiny movement primitive improves a target human-comparable bucket while preserving non-target "
                "guardrails and route/cadence diagnostics."
            ),
            "abandon_or_rebuild_if": (
                "Multiple bounded primitives cannot improve target buckets without broad regressions that cannot be "
                "attributed or gated."
            ),
        },
        {
            "gate": "route_and_map_context",
            "continue_frogbots_if": (
                "Route/map failures can be exposed as guardrails or corrected with narrow route/context changes."
            ),
            "abandon_or_rebuild_if": (
                "Frogbot route state is too opaque or too static to separate movement-controller failures from "
                "map-understanding failures."
            ),
        },
    ]


def load_context_source(path: Path) -> list[dict[str, object]]:
    loaded = load_json(path)
    rows = loaded.get("player_bucket_context", [])
    if not isinstance(rows, list):
        raise S7kInputError(f"{portable_path(path)} did not contain a `player_bucket_context` list.")
    return [row for row in rows if isinstance(row, dict)]


def context_source_payload(
    player_context: list[dict[str, object]],
    *,
    stage: str,
    s7j_path: Path,
    transition_window_ms: int,
    command_margin_ms: int,
) -> dict[str, object]:
    return {
        "schema": "komodobots.s7j_failed_bucket_context_source.v1",
        "stage": f"{stage}-context-source",
        "source_s7j_path": portable_path(s7j_path),
        "transition_window_ms": transition_window_ms,
        "command_margin_ms": command_margin_ms,
        "player_bucket_context": player_context,
    }


def make_decision(bucket_diagnoses: list[dict[str, object]]) -> dict[str, object]:
    cause_classes = {str(row.get("classification", {}).get("cause_class", "")) for row in bucket_diagnoses}
    if "measurement_alignment_risk" in cause_classes:
        return {
            "verdict": "repair_measurement_before_frogbots_decision",
            "reason": "S7k found a measurement alignment risk, so the next step must repair evidence before changing movement.",
            "next_goal": "Fix the missing/weak S7j diagnosis path, then rerun S7k.",
            "frogbots_vs_from_scratch": "no_decision",
        }
    controller_or_mixed = bool(
        {"controller_policy_or_physics_timing", "mixed_controller_and_route_context", "controller_probe_interaction"}
        & cause_classes
    )
    if controller_or_mixed and (
        "route_or_map_context_guardrail_contamination" in cause_classes
        or "mixed_controller_and_route_context" in cause_classes
    ):
        return {
            "verdict": "continue_frogbots_with_context_gated_probe",
            "reason": (
                "S7k separates the corrected S7j failure into a controller/timing problem in the intended air "
                "buckets plus route/map-context contamination in the non-airborne guardrail. This does not disprove "
                "the KTX/Frogbots substrate; it says the next probe must be narrower and context-gated."
            ),
            "next_goal": (
                "S7l should design a smaller air-transition probe that either excludes low-dir-speed/WATER_PATH "
                "contexts or treats them as hard stop-condition slices before another lab rerun."
            ),
            "frogbots_vs_from_scratch": "continue_frogbots_for_next_bounded_stage",
        }
    return {
        "verdict": "continue_diagnosis_before_frogbots_decision",
        "reason": "S7k did not trigger a from-scratch decision; the evidence still needs a narrower movement primitive.",
        "next_goal": "Choose the next smallest diagnostic or context-gated movement primitive.",
        "frogbots_vs_from_scratch": "no_abandon_trigger",
    }


def build_report(
    s7j: dict[str, object],
    s7g: dict[str, object],
    *,
    s7j_path: Path,
    s7g_path: Path,
    context_source_path: Path | None,
    refresh_context_source: bool,
    stage: str,
    transition_window_ms: int,
    command_margin_ms: int,
) -> dict[str, object]:
    changes = bucket_changes_by_key(s7j)
    land_speed = s7j.get("land_speed_comparison", {}) if isinstance(s7j.get("land_speed_comparison"), dict) else {}
    bot_players = [row for row in land_speed.get("bot_players", []) if isinstance(row, dict)]
    player_context: list[dict[str, object]] = []
    warnings: list[str] = []
    context_source_mode = "raw_artifacts"
    if context_source_path and context_source_path.exists() and not refresh_context_source:
        player_context = load_context_source(context_source_path)
        context_source_mode = "committed_context_source"
    else:
        for row in bot_players:
            for bucket in FAILED_BUCKETS:
                try:
                    player_context.append(
                        summarize_bucket_context(
                            row,
                            bucket,
                            transition_window_ms=transition_window_ms,
                            command_margin_ms=command_margin_ms,
                        )
                    )
                except (FileNotFoundError, ValueError, TypeError, json.JSONDecodeError) as exc:
                    warnings.append(f"{row.get('identity', '')} `{row.get('run_id', '')}` {bucket}: {exc}")

    bucket_contexts = [combine_context(player_context, bucket) for bucket in FAILED_BUCKETS]
    bucket_diagnoses = []
    for context in bucket_contexts:
        bucket = str(context.get("bucket", ""))
        change = changes.get(bucket, {"bucket": bucket})
        bucket_diagnoses.append(
            {
                "bucket": bucket,
                "label": BUCKET_LABELS.get(bucket, bucket),
                "s7g_bot_p50_speed_qu_per_s": rounded(change.get("baseline_bot_p50_speed_qu_per_s")),
                "s7j_bot_p50_speed_qu_per_s": rounded(change.get("current_bot_p50_speed_qu_per_s")),
                "ratio_to_s7g_baseline": rounded(change.get("ratio_to_s7g_baseline")),
                "current_bot_to_reference_p50_ratio": rounded(change.get("current_bot_to_reference_p50_ratio")),
                "regressed_more_than_5pct": bool(change.get("regressed_more_than_5pct", False)),
                "context": context,
                "classification": classify_bucket_failure(change, context),
            }
        )

    s7g_decision = s7g.get("decision", {}) if isinstance(s7g.get("decision"), dict) else {}
    return {
        "schema": SCHEMA,
        "stage": stage,
        "map": s7j.get("map", "dm3"),
        "source_s7j_path": portable_path(s7j_path),
        "source_s7j_stage": s7j.get("stage", ""),
        "source_s7g_path": portable_path(s7g_path),
        "source_s7g_stage": s7g.get("stage", ""),
        "context_source_path": portable_path(context_source_path) if context_source_path else "",
        "context_source_mode": context_source_mode,
        "transition_window_ms": transition_window_ms,
        "command_margin_ms": command_margin_ms,
        "warnings": warnings,
        "method": (
            "S7k reuses corrected S7j artifacts and recomputes per-segment command/probe/route context for the "
            "failed pre-air, airborne-proxy, and non-airborne buckets. It does not rerun the lab or add a movement mode."
        ),
        "decision_gates": decision_gates(),
        "s7j_stop_condition_verdict": s7j.get("decision", {}),
        "s7g_context_decision": s7g_decision,
        "bucket_diagnoses": bucket_diagnoses,
        "player_bucket_context": player_context,
        "decision": make_decision(bucket_diagnoses),
    }


def validate_report(report: dict[str, object]) -> None:
    warnings = report.get("warnings", [])
    if warnings:
        raise S7kInputError("; ".join(str(warning) for warning in warnings))
    if not report.get("bucket_diagnoses"):
        raise S7kInputError("No S7k bucket diagnoses were produced.")


def fmt_speed(value: object) -> str:
    return format_comparison_value("avg_horizontal_speed_qu_per_s", value)


def fmt_ratio(value: object) -> str:
    number = optional_float(value)
    if number is None:
        return ""
    return f"{number:.3f}"


def write_markdown(report: dict[str, object], output_path: Path) -> None:
    lines = [
        f"# S7j Failed-Bucket Diagnosis {report.get('stage', '')}",
        "",
        "## Scope",
        "",
        f"- Map: `{report.get('map', '')}`",
        f"- Source S7j result: `{report.get('source_s7j_path', '')}`",
        f"- Source S7g baseline: `{report.get('source_s7g_path', '')}`",
        f"- Context source: `{report.get('context_source_path', '')}` (`{report.get('context_source_mode', '')}`)",
        f"- Transition window: `{report.get('transition_window_ms')}` ms",
        f"- Command match margin: `{report.get('command_margin_ms')}` ms",
        f"- {report.get('method', '')}",
        "",
        "## Frogbots-Vs-From-Scratch Gates",
        "",
        "| Gate | Continue Frogbots/KTX if | Abandon or rebuild if |",
        "|---|---|---|",
    ]
    for gate in report.get("decision_gates", []):
        if not isinstance(gate, dict):
            continue
        lines.append(
            "| "
            f"`{gate.get('gate', '')}` | "
            f"{gate.get('continue_frogbots_if', '')} | "
            f"{gate.get('abandon_or_rebuild_if', '')} |"
        )

    lines.extend(
        [
            "",
            "## Failed Buckets",
            "",
            "| Bucket | S7g p50 | S7j p50 | S7j/S7g | Bot/ref | Context | Classification |",
            "|---|---:|---:|---:|---:|---|---|",
        ]
    )
    for row in report.get("bucket_diagnoses", []):
        if not isinstance(row, dict):
            continue
        context = row.get("context", {}) if isinstance(row.get("context"), dict) else {}
        classification = row.get("classification", {}) if isinstance(row.get("classification"), dict) else {}
        context_text = (
            f"strong `{fmt_ratio(context.get('strong_command_ratio'))}`, "
            f"active `{fmt_ratio(context.get('probe_active_ratio'))}`, "
            f"low-dir `{fmt_ratio(context.get('low_dir_speed_ratio'))}`, "
            f"WATER_PATH `{fmt_ratio(context.get('water_path_ratio'))}`"
        )
        lines.append(
            "| "
            f"{row.get('label', row.get('bucket', ''))} | "
            f"{fmt_speed(row.get('s7g_bot_p50_speed_qu_per_s'))} | "
            f"{fmt_speed(row.get('s7j_bot_p50_speed_qu_per_s'))} | "
            f"{fmt_ratio(row.get('ratio_to_s7g_baseline'))} | "
            f"{fmt_ratio(row.get('current_bot_to_reference_p50_ratio'))} | "
            f"{context_text} | "
            f"`{classification.get('cause_class', '')}` |"
        )

    lines.extend(
        [
            "",
            "## Per-Player Context",
            "",
            "| Bucket | Player | Run | Segments | p50 | Strong | Active | Low-dir | WATER_PATH |",
            "|---|---|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in report.get("player_bucket_context", []):
        if not isinstance(row, dict):
            continue
        speed = row.get("speed", {}) if isinstance(row.get("speed"), dict) else {}
        lines.append(
            "| "
            f"{row.get('label', row.get('bucket', ''))} | "
            f"`{row.get('player', '')}` | "
            f"`{row.get('run_id', '')}` | "
            f"{row.get('segment_count', 0)} | "
            f"{fmt_speed(speed.get('p50'))} | "
            f"{fmt_ratio(row.get('strong_command_ratio'))} | "
            f"{fmt_ratio(row.get('probe_active_ratio'))} | "
            f"{fmt_ratio(row.get('low_dir_speed_ratio'))} | "
            f"{fmt_ratio(row.get('water_path_ratio'))} |"
        )

    decision = report.get("decision", {}) if isinstance(report.get("decision"), dict) else {}
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- Water is not the whole S7j problem. `WATER_PATH`/low-dir context explains the non-airborne guardrail contamination, especially where route context dominates, but the intended air-transition buckets still fail under strong command/probe coverage.",
            "- This is not yet evidence that Frogbots lack strategic intelligence. The current split is lower-level: controller timing/physics interaction for air transitions, plus route/map-context guardrails around low-dir-speed and `WATER_PATH`.",
            "- The from-scratch trigger is not reached while the KTX/Frogbots shell still supports spawning, combat, command overrides, diagnostics, and MVD evidence.",
            "",
            "## Decision",
            "",
            f"- Verdict: `{decision.get('verdict', '')}`",
            f"- Frogbots-vs-from-scratch: `{decision.get('frogbots_vs_from_scratch', '')}`",
            f"- Reason: {decision.get('reason', '')}",
            f"- Next goal: {decision.get('next_goal', '')}",
        ]
    )
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diagnose corrected S7j failed buckets before another probe.")
    parser.add_argument("--stage", default="s7k-failed-bucket-diagnosis-dm3", help="Evidence stage label.")
    parser.add_argument("--s7j", type=Path, default=DEFAULT_S7J, help="Corrected S7j result JSON.")
    parser.add_argument("--s7g", type=Path, default=DEFAULT_S7G, help="S7g baseline/context JSON.")
    parser.add_argument(
        "--context-source",
        type=Path,
        default=DEFAULT_CONTEXT_SOURCE,
        help="Committed compact per-player context source for clean-checkout reproducibility.",
    )
    parser.add_argument(
        "--refresh-context-source",
        action="store_true",
        help="Recompute the compact context source from local raw lab artifacts.",
    )
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON, help="Output evidence JSON.")
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD, help="Output evidence Markdown.")
    parser.add_argument("--transition-window-ms", type=int, default=400)
    parser.add_argument("--command-margin-ms", type=int, default=150)
    return parser.parse_args(list(argv))


def main(argv: Iterable[str] = sys.argv[1:]) -> int:
    args = parse_args(argv)
    s7j = load_json(args.s7j)
    s7g = load_json(args.s7g)
    report = build_report(
        s7j,
        s7g,
        s7j_path=args.s7j,
        s7g_path=args.s7g,
        context_source_path=args.context_source,
        refresh_context_source=args.refresh_context_source,
        stage=args.stage,
        transition_window_ms=args.transition_window_ms,
        command_margin_ms=args.command_margin_ms,
    )
    validate_report(report)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    if report.get("context_source_mode") == "raw_artifacts" and args.context_source:
        args.context_source.parent.mkdir(parents=True, exist_ok=True)
        args.context_source.write_text(
            json.dumps(
                context_source_payload(
                    report.get("player_bucket_context", []),
                    stage=args.stage,
                    s7j_path=args.s7j,
                    transition_window_ms=args.transition_window_ms,
                    command_margin_ms=args.command_margin_ms,
                ),
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    args.output_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_markdown(report, args.output_md)
    print(f"Wrote S7j failed-bucket diagnosis: {args.output_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
