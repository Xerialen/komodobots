#!/usr/bin/env python3
"""Compare the S7j air-transition probe against S7i guardrails."""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterable

from analyze_human_mvd import format_comparison_value
from characterize_land_speed_gap import (
    build_report as build_land_speed_report,
    optional_float,
)
from decide_cadence_normalization import add_derived_axes
from run_frobodm2_lab import validate_run_id
from summarize_reference_aggregate import portable_path


SCHEMA = "komodobots.air_transition_probe_result.v1"
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DESIGN = (
    REPO_ROOT / "experiments" / "human_comparison" / "evidence" / "air-transition-probe-design-s7i-dm3.json"
)
DEFAULT_S7F = REPO_ROOT / "experiments" / "human_comparison" / "evidence" / "airborne-segments-s7f-dm3.json"
DEFAULT_ARTIFACTS_ROOT = REPO_ROOT / "artifacts" / "lab-runs"
DEFAULT_OUTPUT_JSON = (
    REPO_ROOT / "experiments" / "human_comparison" / "evidence" / "air-transition-probe-s7j-dm3.json"
)
DEFAULT_OUTPUT_MD = (
    REPO_ROOT / "experiments" / "human_comparison" / "evidence" / "air-transition-probe-s7j-dm3.md"
)

AIR_BUCKETS = ("pre_air_window_segments", "airborne_proxy_segments", "post_air_window_segments")
GUARDRAIL_BUCKETS = (
    "all_segments",
    "non_airborne_segments",
    "route_low_dir_speed_segments",
    "route_water_path_segments",
)
REQUIRED_BUCKETS = (*AIR_BUCKETS, *GUARDRAIL_BUCKETS)
CADENCE_FIELDS = (
    "jump_cadence_per_min",
    "jump_cadence_per_non_low_speed_min",
    "jump_cadence_per_airborne_proxy_min",
)
BOT_ROW_FIELDS = (
    "avg_horizontal_speed_qu_per_s",
    "p95_horizontal_speed_qu_per_s",
    "stationary_time_ratio",
    "low_speed_time_ratio",
    "airborne_proxy_time_ratio",
    "airborne_proxy_count",
    "jump_cadence_per_min",
    "avg_airborne_proxy_duration_ms",
    "avg_airborne_proxy_z_delta_qu",
    "avg_landing_pre_speed_qu_per_s",
    "avg_landing_post_speed_qu_per_s",
    "avg_post_landing_speed_delta_qu_per_s",
    "avg_post_landing_speed_loss_ratio",
)


class ProbeResultInputError(RuntimeError):
    """Raised when S7j cannot resolve the requested evidence inputs."""


def rounded(value: object, digits: int = 3) -> float | None:
    number = optional_float(value)
    if number is None:
        return None
    return round(number, digits)


def load_json(path: Path) -> dict[str, object]:
    with path.open("r", encoding="utf-8") as handle:
        loaded = json.load(handle)
    if not isinstance(loaded, dict):
        raise ProbeResultInputError(f"{portable_path(path)} did not contain a JSON object.")
    return loaded


def summarize_numbers(values: list[float]) -> dict[str, object]:
    clean = [value for value in values if math.isfinite(value)]
    if not clean:
        return {"count": 0, "min": None, "mean": None, "max": None}
    return {
        "count": len(clean),
        "min": round(min(clean), 3),
        "mean": round(sum(clean) / len(clean), 3),
        "max": round(max(clean), 3),
    }


def compact_unique(values: Iterable[object], limit: int = 12) -> list[object]:
    def sort_key(value: object) -> tuple[int, float | str]:
        number = optional_float(value)
        if number is not None:
            return (0, number)
        return (1, str(value))

    unique = sorted(set(values), key=sort_key)
    if len(unique) <= limit:
        return unique
    return [*unique[:limit], f"... {len(unique) - limit} more"]


def load_run_env(run_dir: Path) -> dict[str, str]:
    path = run_dir / "run.env"
    if not path.exists():
        return {}
    env: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" not in raw_line:
            continue
        key, value = raw_line.split("=", 1)
        env[key.strip()] = value.strip()
    return env


def compact_probe_bot_row(
    player: dict[str, object],
    *,
    run_id: str,
    run_dir: Path,
    metrics_path: Path,
    map_command: str,
) -> dict[str, object]:
    row: dict[str, object] = {
        "group": "bot",
        "identity": player.get("name", ""),
        "matched_name": player.get("name", ""),
        "run_id": run_id,
        "map": map_command,
        "events_path": portable_path(run_dir / "events.txt"),
        "source_metrics_path": portable_path(metrics_path),
        "mode_family": "dm3_mode8_air_transition_probe",
    }
    for field in BOT_ROW_FIELDS:
        row[field] = rounded(player.get(field))
    return add_derived_axes(row)


def load_probe_bot_rows(
    run_ids: list[str],
    artifacts_root: Path,
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]], list[str]]:
    source_rows: list[dict[str, object]] = []
    cadence_rows: list[dict[str, object]] = []
    run_configs: list[dict[str, object]] = []
    warnings: list[str] = []
    for run_id in run_ids:
        run_dir = artifacts_root / run_id
        metrics_path = run_dir / "movement-metrics.json"
        if not metrics_path.exists():
            warnings.append(f"Missing movement metrics for run `{run_id}` at `{portable_path(metrics_path)}`.")
            continue
        metrics = load_json(metrics_path)
        run = metrics.get("run", {}) if isinstance(metrics.get("run"), dict) else {}
        map_command = str(run.get("map_command", ""))
        env = load_run_env(run_dir)
        run_configs.append(
            {
                "run_id": run_id,
                "map": map_command,
                "source_metrics_path": portable_path(metrics_path),
                "moveprobe_mode": env.get("MOVEPROBE_MODE", ""),
                "forwardmove": env.get("MOVEPROBE_FORWARDMOVE", ""),
                "sidemove": env.get("MOVEPROBE_SIDEMOVE", ""),
                "upmove": env.get("MOVEPROBE_UPMOVE", ""),
                "transition_scale": env.get("MOVEPROBE_TRANSITION_SCALE", ""),
                "transition_window": env.get("MOVEPROBE_TRANSITION_WINDOW", ""),
                "command_logging": env.get("MOVEPROBE_LOG_COMMANDS", ""),
                "command_log_interval": env.get("MOVEPROBE_LOG_INTERVAL", ""),
            }
        )
        if map_command != "dm3":
            warnings.append(f"Run `{run_id}` is `{map_command}`, not `dm3`; row kept but map mismatch should be reviewed.")
        players = metrics.get("players", [])
        if not isinstance(players, list):
            warnings.append(f"Run `{run_id}` has no player list in `{portable_path(metrics_path)}`.")
            continue
        for player in players:
            if not isinstance(player, dict) or player.get("spectator", False):
                continue
            row = compact_probe_bot_row(
                player,
                run_id=run_id,
                run_dir=run_dir,
                metrics_path=metrics_path,
                map_command=map_command,
            )
            source_rows.append(row)
            cadence_rows.append(row)
    return source_rows, cadence_rows, run_configs, warnings


def build_probe_source(
    s7f: dict[str, object],
    bot_rows: list[dict[str, object]],
    *,
    stage: str,
    s7f_path: Path,
) -> dict[str, object]:
    return {
        "schema": "komodobots.air_transition_probe_source.v1",
        "stage": f"{stage}-source",
        "map": s7f.get("map", "dm3"),
        "source_airborne_segments_path": portable_path(s7f_path),
        "source_airborne_segments_stage": s7f.get("stage", ""),
        "reference_players": [row for row in s7f.get("reference_players") or [] if isinstance(row, dict)],
        "bot_players": bot_rows,
    }


def summarize_probe_activation(run_ids: list[str], artifacts_root: Path) -> dict[str, object]:
    players: list[dict[str, object]] = []
    total_states = 0
    total_active = 0
    warnings: list[str] = []
    for run_id in run_ids:
        path = artifacts_root / run_id / "moveprobe-commands.json"
        if not path.exists():
            warnings.append(f"Missing moveprobe command log for run `{run_id}` at `{portable_path(path)}`.")
            continue
        loaded = load_json(path)
        grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
        for command in loaded.get("commands", []) if isinstance(loaded.get("commands"), list) else []:
            if not isinstance(command, dict) or not isinstance(command.get("probe_state"), dict):
                continue
            grouped[str(command.get("name", ""))].append(command["probe_state"])
        for player, states in sorted(grouped.items()):
            active = [state for state in states if bool(state.get("transition_active", False))]
            total_states += len(states)
            total_active += len(active)
            players.append(
                {
                    "run_id": run_id,
                    "player": player,
                    "sample_count": len(states),
                    "transition_active_count": len(active),
                    "transition_active_ratio": round(len(active) / len(states), 3) if states else None,
                    "on_ground_ratio": round(
                        sum(1 for state in states if bool(state.get("on_ground", False))) / len(states), 3
                    )
                    if states
                    else None,
                    "active_scale_values": compact_unique(
                        scale
                        for scale in (
                            rounded(state.get("transition_scale"), 3)
                            for state in active
                        )
                        if scale is not None
                    ),
                }
            )
    return {
        "sample_count": total_states,
        "transition_active_count": total_active,
        "transition_active_ratio": round(total_active / total_states, 3) if total_states else None,
        "players": players,
        "warnings": warnings,
    }


def baseline_map(design: dict[str, object]) -> dict[str, dict[str, object]]:
    baselines: dict[str, dict[str, object]] = {}
    for group_name in ("air_transition_baselines", "guardrail_baselines"):
        group = design.get(group_name, {}) if isinstance(design.get(group_name), dict) else {}
        for key, value in group.items():
            if isinstance(value, dict):
                baselines[str(key)] = value
    return baselines


def bucket_current(land_speed: dict[str, object], key: str) -> dict[str, object]:
    comparison = land_speed.get("comparison", {}) if isinstance(land_speed.get("comparison"), dict) else {}
    bucket = comparison.get(key, {}) if isinstance(comparison.get(key), dict) else {}
    bot = bucket.get("bot_player_p50_speed", {}) if isinstance(bucket.get("bot_player_p50_speed"), dict) else {}
    return {
        "bucket": key,
        "label": bucket.get("label", key),
        "bot_player_count": int(bot.get("count", 0) or 0),
        "bot_p50_speed_qu_per_s": rounded(bot.get("p50")),
        "bot_to_reference_p50_ratio": rounded(bucket.get("bot_to_reference_p50_ratio")),
    }


def bucket_changes(design: dict[str, object], land_speed: dict[str, object]) -> list[dict[str, object]]:
    baselines = baseline_map(design)
    changes = []
    for key in REQUIRED_BUCKETS:
        baseline = baselines.get(key, {})
        current = bucket_current(land_speed, key)
        baseline_p50 = rounded(baseline.get("bot_p50_speed_qu_per_s"))
        current_p50 = rounded(current.get("bot_p50_speed_qu_per_s"))
        ratio_to_baseline = (
            round(current_p50 / baseline_p50, 3)
            if current_p50 is not None and baseline_p50 is not None and baseline_p50 > 0
            else None
        )
        changes.append(
            {
                "bucket": key,
                "label": baseline.get("label", current.get("label", key)),
                "baseline_bot_player_count": int(baseline.get("bot_player_count", 0) or 0),
                "current_bot_player_count": current["bot_player_count"],
                "baseline_bot_p50_speed_qu_per_s": baseline_p50,
                "current_bot_p50_speed_qu_per_s": current_p50,
                "ratio_to_s7g_baseline": ratio_to_baseline,
                "improved_vs_s7g_baseline": (
                    current_p50 is not None and baseline_p50 is not None and current_p50 > baseline_p50
                ),
                "regressed_more_than_5pct": (
                    current_p50 is not None and baseline_p50 is not None and current_p50 < baseline_p50 * 0.95
                ),
                "current_bot_to_reference_p50_ratio": current.get("bot_to_reference_p50_ratio"),
            }
        )
    return changes


def build_cadence_axes(design: dict[str, object], cadence_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    cadence_baselines = design.get("cadence_baselines")
    if not isinstance(cadence_baselines, list):
        cadence_baselines = []
    design_axes = {
        str(axis.get("field")): axis
        for axis in cadence_baselines
        if isinstance(axis, dict) and axis.get("field")
    }
    axes = []
    for field in CADENCE_FIELDS:
        baseline = design_axes.get(field, {})
        reference_range = {
            "min": baseline.get("reference_min"),
            "max": baseline.get("reference_max"),
        }
        values = [value for row in cadence_rows if (value := optional_float(row.get(field))) is not None]
        bot_rows = []
        classifications = []
        ref_min = optional_float(reference_range.get("min"))
        ref_max = optional_float(reference_range.get("max"))
        for row in cadence_rows:
            value = optional_float(row.get(field))
            if value is None or ref_min is None or ref_max is None:
                classification = "unavailable"
            elif value < ref_min:
                classification = "below_reference_min"
            elif value > ref_max:
                classification = "above_reference_max"
            else:
                classification = "within_reference_range"
            classifications.append(classification)
            bot_rows.append(
                {
                    "player": row.get("identity", row.get("player", "")),
                    "run_id": row.get("run_id", ""),
                    "value": rounded(value),
                    "against_reference": classification,
                }
            )
        usable = [classification for classification in classifications if classification != "unavailable"]
        if not usable:
            relation = "no_bot_comparison"
        elif all(classification == "within_reference_range" for classification in usable):
            relation = "all_bots_within_reference_range"
        elif all(classification == "above_reference_max" for classification in usable):
            relation = "all_bots_above_reference_range"
        elif all(classification == "below_reference_min" for classification in usable):
            relation = "all_bots_below_reference_range"
        else:
            relation = "mixed_bot_relation"
        axes.append(
            {
                "field": field,
                "label": baseline.get("label", field),
                "reference": reference_range,
                "bot": summarize_numbers(values),
                "bot_relation": relation,
                "bot_rows": bot_rows,
            }
        )
    return axes


def evaluate_stop_conditions(
    changes: list[dict[str, object]],
    cadence_axes: list[dict[str, object]],
    probe_activation: dict[str, object],
) -> list[dict[str, object]]:
    by_bucket = {str(change.get("bucket")): change for change in changes}
    missing_buckets = [
        key
        for key in REQUIRED_BUCKETS
        if not by_bucket.get(key, {}).get("current_bot_player_count")
        or by_bucket.get(key, {}).get("current_bot_p50_speed_qu_per_s") is None
    ]
    missing_cadence = [
        field
        for field in CADENCE_FIELDS
        if not any(axis.get("field") == field and axis.get("bot", {}).get("count") for axis in cadence_axes)
    ]
    air_regressions = [
        key
        for key in AIR_BUCKETS
        if bool(by_bucket.get(key, {}).get("regressed_more_than_5pct", False))
    ]
    all_improved = bool(by_bucket.get("all_segments", {}).get("improved_vs_s7g_baseline", False))
    air_improved = [
        key
        for key in AIR_BUCKETS
        if bool(by_bucket.get(key, {}).get("improved_vs_s7g_baseline", False))
    ]
    non_air = by_bucket.get("non_airborne_segments", {})
    water = by_bucket.get("route_water_path_segments", {})
    probe_samples = int(probe_activation.get("sample_count", 0) or 0)
    probe_active = int(probe_activation.get("transition_active_count", 0) or 0)

    return [
        {
            "id": "missing_required_reporting",
            "status": "inconclusive" if missing_buckets or missing_cadence else "pass",
            "details": {
                "missing_buckets": missing_buckets,
                "missing_cadence_axes": missing_cadence,
            },
        },
        {
            "id": "probe_activation_reporting",
            "status": "inconclusive" if probe_samples == 0 else "reject" if probe_active == 0 else "pass",
            "details": {
                "sample_count": probe_samples,
                "transition_active_count": probe_active,
                "transition_active_ratio": probe_activation.get("transition_active_ratio"),
            },
        },
        {
            "id": "all_segment_proxy_win",
            "status": "reject" if all_improved and not air_improved else "pass",
            "details": {
                "all_segments_improved": all_improved,
                "air_transition_buckets_improved": air_improved,
            },
        },
        {
            "id": "air_transition_regression",
            "status": "reject" if air_regressions else "pass",
            "details": {"regressed_buckets": air_regressions, "tolerance_ratio": 0.95},
        },
        {
            "id": "non_airborne_guardrail",
            "status": "reject" if bool(non_air.get("regressed_more_than_5pct", False)) else "pass",
            "details": {
                "ratio_to_s7g_baseline": non_air.get("ratio_to_s7g_baseline"),
                "tolerance_ratio": 0.95,
            },
        },
        {
            "id": "water_path_guardrail",
            "status": (
                "inconclusive"
                if not water.get("current_bot_player_count") or water.get("current_bot_p50_speed_qu_per_s") is None
                else "reject"
                if bool(water.get("regressed_more_than_5pct", False))
                else "pass"
            ),
            "details": {
                "ratio_to_s7g_baseline": water.get("ratio_to_s7g_baseline"),
                "current_bot_player_count": water.get("current_bot_player_count"),
                "tolerance_ratio": 0.95,
            },
        },
        {
            "id": "cadence_still_diagnostic",
            "status": "inconclusive" if missing_cadence else "pass",
            "details": {
                "reported_axes": [axis.get("field") for axis in cadence_axes],
                "note": "Cadence remains reporting-only; it is not a success criterion for S7j.",
            },
        },
    ]


def make_decision(changes: list[dict[str, object]], stop_conditions: list[dict[str, object]]) -> dict[str, object]:
    reject_ids = [condition["id"] for condition in stop_conditions if condition.get("status") == "reject"]
    inconclusive_ids = [condition["id"] for condition in stop_conditions if condition.get("status") == "inconclusive"]
    air_improved = [
        change["bucket"]
        for change in changes
        if change.get("bucket") in AIR_BUCKETS and bool(change.get("improved_vs_s7g_baseline", False))
    ]
    if reject_ids:
        return {
            "verdict": "air_transition_probe_rejected_by_s7i_stop_conditions",
            "reason": f"S7j produced evidence, but stop conditions failed: {', '.join(reject_ids)}.",
            "next_goal": (
                "S7k should inspect the failed bucket and command/probe activation context before trying another "
                "controller probe."
            ),
            "failed_stop_conditions": reject_ids,
            "inconclusive_stop_conditions": inconclusive_ids,
            "air_transition_buckets_improved": air_improved,
        }
    if inconclusive_ids:
        return {
            "verdict": "air_transition_probe_inconclusive",
            "reason": f"S7j lacked required evidence for: {', '.join(inconclusive_ids)}.",
            "next_goal": "S7k should repair the missing evidence path before another controller probe.",
            "failed_stop_conditions": [],
            "inconclusive_stop_conditions": inconclusive_ids,
            "air_transition_buckets_improved": air_improved,
        }
    if air_improved:
        return {
            "verdict": "air_transition_probe_preserved_guardrails_with_air_bucket_gain",
            "reason": (
                "The mode-8 probe improved at least one air-transition bucket while preserving S7i guardrails. "
                "This is evidence toward a controller direction, not proof of believable bots."
            ),
            "next_goal": (
                "S7k should rerun or narrow the probe to verify repeatability before promoting behavior beyond a "
                "diagnostic mode."
            ),
            "failed_stop_conditions": [],
            "inconclusive_stop_conditions": [],
            "air_transition_buckets_improved": air_improved,
        }
    return {
        "verdict": "air_transition_probe_preserved_guardrails_without_air_bucket_gain",
        "reason": (
            "The mode-8 probe preserved required reporting and guardrails but did not improve pre-air, airborne, "
            "or post-air p50 speed versus S7g."
        ),
        "next_goal": "S7k should inspect transition timing and per-player bucket context before increasing scope.",
        "failed_stop_conditions": [],
        "inconclusive_stop_conditions": [],
        "air_transition_buckets_improved": [],
    }


def build_report(
    design: dict[str, object],
    s7f: dict[str, object],
    *,
    stage: str,
    bot_run_ids: list[str],
    artifacts_root: Path,
    design_path: Path,
    s7f_path: Path,
) -> dict[str, object]:
    bot_rows, cadence_rows, run_configs, warnings = load_probe_bot_rows(bot_run_ids, artifacts_root)
    source = build_probe_source(s7f, bot_rows, stage=stage, s7f_path=s7f_path)
    land_speed = build_land_speed_report(
        source,
        source_path=s7f_path,
        stage=f"{stage}-land-speed-comparison",
        transition_window_ms=400,
        command_margin_ms=150,
    )
    land_speed["method"] = (
        "S7j reuses the committed exact-player reference rows from S7f and replaces the bot rows with the "
        "mode-8 air-transition probe run, then applies the same S7g segment and route-command bucketing."
    )
    probe_activation = summarize_probe_activation(bot_run_ids, artifacts_root)
    changes = bucket_changes(design, land_speed)
    cadence_axes = build_cadence_axes(design, cadence_rows)
    stop_conditions = evaluate_stop_conditions(changes, cadence_axes, probe_activation)
    return {
        "schema": SCHEMA,
        "stage": stage,
        "map": source.get("map", "dm3"),
        "source_design_path": portable_path(design_path),
        "source_design_stage": design.get("stage", ""),
        "source_airborne_segments_path": portable_path(s7f_path),
        "source_airborne_segments_stage": s7f.get("stage", ""),
        "bot_run_ids": bot_run_ids,
        "run_configs": run_configs,
        "warnings": [*warnings, *land_speed.get("warnings", []), *probe_activation.get("warnings", [])],
        "method": (
            "S7j implements the S7i mode-8 transition-only horizontal command-budget probe, runs it in the "
            "headless dm3 bot lab, and evaluates the result against S7i stop conditions. Passing validation is "
            "evidence, not proof of believable player behavior."
        ),
        "probe_contract": design.get("probe_contract", {}),
        "land_speed_comparison": land_speed,
        "bucket_changes": changes,
        "cadence_axes": cadence_axes,
        "probe_activation": probe_activation,
        "stop_condition_results": stop_conditions,
        "decision": make_decision(changes, stop_conditions),
    }


def validate_report(report: dict[str, object]) -> None:
    warnings = report.get("warnings", [])
    if warnings:
        raise ProbeResultInputError("; ".join(str(warning) for warning in warnings))
    land_speed = report.get("land_speed_comparison", {}) if isinstance(report.get("land_speed_comparison"), dict) else {}
    if not land_speed.get("reference_players"):
        raise ProbeResultInputError("No reference players resolved for S7j.")
    if not land_speed.get("bot_players"):
        raise ProbeResultInputError("No bot players resolved for S7j.")


def fmt_speed(value: object) -> str:
    if value is None:
        return ""
    return format_comparison_value("avg_horizontal_speed_qu_per_s", value)


def fmt_ratio(value: object) -> str:
    number = optional_float(value)
    if number is None:
        return ""
    return f"{number:.3f}"


def write_markdown(report: dict[str, object], output_path: Path) -> None:
    lines = [
        f"# Air-Transition Probe Result {report.get('stage', '')}",
        "",
        "## Scope",
        "",
        f"- Map: `{report.get('map', '')}`",
        f"- Source S7i design: `{report.get('source_design_path', '')}`",
        f"- Source S7f reference rows: `{report.get('source_airborne_segments_path', '')}`",
        f"- Bot run IDs: `{', '.join(report.get('bot_run_ids', []))}`",
        f"- {report.get('method', '')}",
        "",
        "## Run Configuration",
        "",
        "| Run | Mode | Forward | Side | Up | Transition scale | Transition window | Command logging |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for config in report.get("run_configs", []):
        if not isinstance(config, dict):
            continue
        lines.append(
            "| "
            f"`{config.get('run_id', '')}` | "
            f"{config.get('moveprobe_mode', '')} | "
            f"{config.get('forwardmove', '')} | "
            f"{config.get('sidemove', '')} | "
            f"{config.get('upmove', '')} | "
            f"{config.get('transition_scale', '')} | "
            f"{config.get('transition_window', '')} | "
            f"{config.get('command_logging', '')} @ {config.get('command_log_interval', '')}s |"
        )

    lines.extend(
        [
            "",
            "## Bucket Changes",
            "",
            "| Bucket | S7g bot p50 | S7j bot p50 | S7j/S7g | S7j rows | Bot/ref p50 |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for change in report.get("bucket_changes", []):
        if not isinstance(change, dict):
            continue
        lines.append(
            "| "
            f"{change.get('label', change.get('bucket', ''))} | "
            f"{fmt_speed(change.get('baseline_bot_p50_speed_qu_per_s'))} | "
            f"{fmt_speed(change.get('current_bot_p50_speed_qu_per_s'))} | "
            f"{fmt_ratio(change.get('ratio_to_s7g_baseline'))} | "
            f"{change.get('current_bot_player_count', 0)} | "
            f"{fmt_ratio(change.get('current_bot_to_reference_p50_ratio'))} |"
        )

    activation = report.get("probe_activation", {}) if isinstance(report.get("probe_activation"), dict) else {}
    lines.extend(
        [
            "",
            "## Probe Activation",
            "",
            f"- Samples with probe state: `{activation.get('sample_count', 0)}`",
            f"- Transition-active samples: `{activation.get('transition_active_count', 0)}`",
            f"- Transition-active ratio: `{activation.get('transition_active_ratio', '')}`",
            "",
            "| Run | Player | Samples | Active samples | Active ratio | Active scales |",
            "|---|---|---:|---:|---:|---|",
        ]
    )
    for player in activation.get("players", []):
        if not isinstance(player, dict):
            continue
        lines.append(
            "| "
            f"`{player.get('run_id', '')}` | "
            f"`{player.get('player', '')}` | "
            f"{player.get('sample_count', 0)} | "
            f"{player.get('transition_active_count', 0)} | "
            f"{player.get('transition_active_ratio', '')} | "
            f"`{player.get('active_scale_values', [])}` |"
        )

    lines.extend(
        [
            "",
            "## Cadence",
            "",
            "| Axis | Reference range | S7j bot range | Relation |",
            "|---|---:|---:|---|",
        ]
    )
    for axis in report.get("cadence_axes", []):
        if not isinstance(axis, dict):
            continue
        field = str(axis.get("field", ""))
        reference = axis.get("reference", {}) if isinstance(axis.get("reference"), dict) else {}
        bot = axis.get("bot", {}) if isinstance(axis.get("bot"), dict) else {}
        lines.append(
            "| "
            f"{axis.get('label', field)} | "
            f"{format_comparison_value(field, reference.get('min'))}-"
            f"{format_comparison_value(field, reference.get('max'))} | "
            f"{format_comparison_value(field, bot.get('min'))}-"
            f"{format_comparison_value(field, bot.get('max'))} | "
            f"`{axis.get('bot_relation', '')}` |"
        )

    lines.extend(["", "## Stop Conditions", "", "| Condition | Status | Details |", "|---|---|---|"])
    for condition in report.get("stop_condition_results", []):
        if not isinstance(condition, dict):
            continue
        lines.append(
            "| "
            f"`{condition.get('id', '')}` | "
            f"`{condition.get('status', '')}` | "
            f"`{condition.get('details', {})}` |"
        )

    decision = report.get("decision", {}) if isinstance(report.get("decision"), dict) else {}
    lines.extend(
        [
            "",
            "## Decision",
            "",
            f"- Verdict: `{decision.get('verdict', '')}`",
            f"- Air-transition buckets improved: `{decision.get('air_transition_buckets_improved', [])}`",
            f"- Failed stop conditions: `{decision.get('failed_stop_conditions', [])}`",
            f"- Inconclusive stop conditions: `{decision.get('inconclusive_stop_conditions', [])}`",
            f"- Reason: {decision.get('reason', '')}",
            f"- Next goal: {decision.get('next_goal', '')}",
        ]
    )
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare the S7j air-transition probe against S7i guardrails.")
    parser.add_argument("--stage", default="s7j-air-transition-probe-dm3", help="Evidence stage label.")
    parser.add_argument("--design", type=Path, default=DEFAULT_DESIGN, help="S7i probe design JSON.")
    parser.add_argument("--s7f", type=Path, default=DEFAULT_S7F, help="S7f airborne segment evidence JSON.")
    parser.add_argument("--artifacts-root", type=Path, default=DEFAULT_ARTIFACTS_ROOT)
    parser.add_argument("--bot-run-id", action="append", dest="bot_run_ids", type=validate_run_id, required=True)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON, help="Output evidence JSON.")
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD, help="Output evidence Markdown.")
    return parser.parse_args(list(argv))


def main(argv: Iterable[str] = sys.argv[1:]) -> int:
    args = parse_args(argv)
    report = build_report(
        load_json(args.design),
        load_json(args.s7f),
        stage=args.stage,
        bot_run_ids=args.bot_run_ids,
        artifacts_root=args.artifacts_root,
        design_path=args.design,
        s7f_path=args.s7f,
    )
    validate_report(report)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_markdown(report, args.output_md)
    print(f"Wrote air-transition probe result: {args.output_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
