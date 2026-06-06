#!/usr/bin/env python3
"""Attribute the QWD SNG slow-success guardrail failure."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from statistics import median
from typing import Iterable

from compare_qwd_sng_hybrid_probe import (
    QwdSngProbeInputError,
    dict_or_empty,
    load_json,
    load_run_env,
    load_run_timing,
    optional_float,
    optional_int,
    qwd_aligned_mvd_time_ms,
)
from diagnose_qwd_sng_probe import (
    commands_for_player,
    configured_radius,
    distance,
    group_commands,
    load_position_samples,
    valid_origin3,
)
from run_frobodm2_lab import validate_run_id
from summarize_reference_aggregate import portable_path


SCHEMA = "komodobots.qwd_sng_slow_success_diagnosis.v1"
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DESIGN = (
    REPO_ROOT / "experiments" / "qwd_route_probe" / "evidence" / "qwd-sng-hybrid-probe-design-dm3.json"
)
DEFAULT_RESULT = (
    REPO_ROOT / "experiments" / "qwd_route_probe" / "evidence" / "qwd-sng-setup-repair-result-dm3.json"
)
DEFAULT_ARTIFACTS_ROOT = REPO_ROOT / "artifacts" / "lab-runs"
DEFAULT_OUTPUT_JSON = (
    REPO_ROOT / "experiments" / "qwd_route_probe" / "evidence" / "qwd-sng-slow-success-diagnosis-dm3.json"
)
DEFAULT_OUTPUT_MD = (
    REPO_ROOT / "experiments" / "qwd_route_probe" / "evidence" / "qwd-sng-slow-success-diagnosis-dm3.md"
)
WATER_PATH_FLAG = 32768
DEFAULT_RADIUS_SENSITIVITY = (320.0, 256.0, 192.0, 160.0, 128.0, 96.0)


def rounded(value: object, digits: int = 3) -> float | None:
    number = optional_float(value)
    if number is None:
        return None
    return round(number, digits)


def percentile(values: list[float], percent: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    index = (len(ordered) - 1) * percent / 100.0
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[int(index)]
    return ordered[lower] * (upper - index) + ordered[upper] * (index - lower)


def load_control_points(design: dict[str, object]) -> list[list[float]]:
    points: list[list[float]] = []
    for item in design.get("control_points", []) if isinstance(design.get("control_points"), list) else []:
        if not isinstance(item, dict):
            continue
        origin = item.get("qwd_origin")
        if isinstance(origin, list) and len(origin) >= 3:
            try:
                points.append([float(part) for part in origin[:3]])
            except (TypeError, ValueError):
                continue
    if not points:
        raise QwdSngProbeInputError("Design did not contain valid QWD control points.")
    return points


def movement_segments(samples: list[dict[str, object]]) -> list[dict[str, object]]:
    segments: list[dict[str, object]] = []
    ordered = sorted(samples, key=lambda sample: int(sample.get("time_ms", 0) or 0))
    for before, after in zip(ordered, ordered[1:]):
        start = optional_int(before.get("time_ms"))
        end = optional_int(after.get("time_ms"))
        origin_before = valid_origin3(before.get("origin"))
        origin_after = valid_origin3(after.get("origin"))
        if start is None or end is None or end <= start or origin_before is None or origin_after is None:
            continue
        duration_s = (end - start) / 1000.0
        horizontal_distance = math.hypot(origin_after[0] - origin_before[0], origin_after[1] - origin_before[1])
        speed = horizontal_distance / duration_s
        # Mirror the movement metric's teleport/respawn guard so phase summaries are not dominated by jumps.
        if speed > 2500.0:
            continue
        segments.append(
            {
                "start_ms": start,
                "end_ms": end,
                "mid_ms": (start + end) // 2,
                "duration_s": duration_s,
                "horizontal_distance_qu": horizontal_distance,
                "horizontal_speed_qu_per_s": speed,
            }
        )
    return segments


def summarize_segments(segments: list[dict[str, object]]) -> dict[str, object]:
    if not segments:
        return {
            "segment_count": 0,
            "duration_s": 0.0,
            "horizontal_distance_qu": 0.0,
            "avg_speed_qu_per_s": None,
            "p50_speed_qu_per_s": None,
            "p95_speed_qu_per_s": None,
            "low_speed_ratio": None,
            "stationary_ratio": None,
        }
    duration = sum(float(segment["duration_s"]) for segment in segments)
    distance_qu = sum(float(segment["horizontal_distance_qu"]) for segment in segments)
    speeds = [float(segment["horizontal_speed_qu_per_s"]) for segment in segments]
    low_duration = sum(float(segment["duration_s"]) for segment in segments if float(segment["horizontal_speed_qu_per_s"]) < 100.0)
    stationary_duration = sum(
        float(segment["duration_s"]) for segment in segments if float(segment["horizontal_speed_qu_per_s"]) < 10.0
    )
    return {
        "segment_count": len(segments),
        "duration_s": round(duration, 3),
        "horizontal_distance_qu": round(distance_qu, 3),
        "avg_speed_qu_per_s": round(distance_qu / duration, 3) if duration else None,
        "p50_speed_qu_per_s": rounded(percentile(speeds, 50)),
        "p95_speed_qu_per_s": rounded(percentile(speeds, 95)),
        "low_speed_ratio": round(low_duration / duration, 3) if duration else None,
        "stationary_ratio": round(stationary_duration / duration, 3) if duration else None,
    }


def first_entry_for_radius(
    samples: list[dict[str, object]], point: list[float], radius: float
) -> dict[str, object]:
    for sample in sorted(samples, key=lambda item: int(item.get("time_ms", 0) or 0)):
        origin = valid_origin3(sample.get("origin"))
        time_ms = optional_int(sample.get("time_ms"))
        if origin is None or time_ms is None:
            continue
        current = distance(origin, point)
        if current <= radius:
            return {
                "radius_qu": radius,
                "first_time_ms": time_ms,
                "distance_qu": round(current, 3),
                "origin": [round(part, 3) for part in origin],
            }
    return {"radius_qu": radius, "first_time_ms": None, "distance_qu": None, "origin": []}


def closest_distance_in_range(
    samples: list[dict[str, object]], point: list[float], start_ms: int | None, end_ms: int | None
) -> dict[str, object]:
    best: tuple[float, dict[str, object]] | None = None
    for sample in samples:
        time_ms = optional_int(sample.get("time_ms"))
        origin = valid_origin3(sample.get("origin"))
        if time_ms is None or origin is None:
            continue
        if start_ms is not None and time_ms < start_ms:
            continue
        if end_ms is not None and time_ms > end_ms:
            continue
        current = distance(origin, point)
        if best is None or current < best[0]:
            best = (current, sample)
    if best is None:
        return {"distance_qu": None, "time_ms": None, "origin": []}
    origin = valid_origin3(best[1].get("origin")) or []
    return {
        "distance_qu": round(best[0], 3),
        "time_ms": optional_int(best[1].get("time_ms")),
        "origin": [round(part, 3) for part in origin],
    }


def ratio(count: int, total: int) -> float | None:
    return round(count / total, 3) if total else None


def command_horizontal(row: dict[str, object]) -> float:
    move = dict_or_empty(row.get("move"))
    return math.hypot(optional_float(move.get("forward")) or 0.0, optional_float(move.get("side")) or 0.0)


def summarize_command_rows(rows: list[dict[str, object]]) -> dict[str, object]:
    if not rows:
        return {
            "command_rows": 0,
            "side_nonzero_ratio": None,
            "jump_ratio": None,
            "median_horizontal_command": None,
            "blocked_ratio": None,
            "low_dir_speed_ratio": None,
            "water_path_ratio": None,
            "waterlevel_gt0_ratio": None,
        }
    side_count = 0
    jump_count = 0
    blocked_count = 0
    low_dir_count = 0
    water_path_count = 0
    waterlevel_count = 0
    horizontal_commands: list[float] = []
    distances: list[float] = []
    for row in rows:
        move = dict_or_empty(row.get("move"))
        if abs(optional_float(move.get("side")) or 0.0) > 0.0:
            side_count += 1
        if (optional_int(row.get("buttons")) or 0) & 2:
            jump_count += 1
        horizontal_commands.append(command_horizontal(row))
        qwd_state = dict_or_empty(row.get("qwd_state"))
        distance_qu = optional_float(qwd_state.get("distance_qu"))
        if distance_qu is not None and distance_qu < 999999.0:
            distances.append(distance_qu)
        route_state = dict_or_empty(row.get("route_state"))
        if bool(route_state.get("blocked", False)):
            blocked_count += 1
        dir_speed = optional_float(route_state.get("dir_speed"))
        if dir_speed is not None and dir_speed < 0.25:
            low_dir_count += 1
        if (optional_int(route_state.get("path_state")) or 0) & WATER_PATH_FLAG:
            water_path_count += 1
        water_state = dict_or_empty(row.get("water_state"))
        if (optional_int(water_state.get("waterlevel")) or 0) > 0:
            waterlevel_count += 1
    return {
        "command_rows": len(rows),
        "side_nonzero_ratio": ratio(side_count, len(rows)),
        "jump_ratio": ratio(jump_count, len(rows)),
        "median_horizontal_command": rounded(median(horizontal_commands)),
        "qwd_distance_qu": {
            "min": rounded(min(distances)) if distances else None,
            "p50": rounded(median(distances)) if distances else None,
            "max": rounded(max(distances)) if distances else None,
        },
        "blocked_ratio": ratio(blocked_count, len(rows)),
        "low_dir_speed_ratio": ratio(low_dir_count, len(rows)),
        "water_path_ratio": ratio(water_path_count, len(rows)),
        "waterlevel_gt0_ratio": ratio(waterlevel_count, len(rows)),
    }


def grouped_active_phases(
    command_rows: list[dict[str, object]],
    timing: dict[str, object],
    samples: list[dict[str, object]],
    control_points: list[list[float]],
) -> list[dict[str, object]]:
    match_duration = optional_int(timing.get("match_duration_ms"))
    rows_by_index: dict[int, list[tuple[int, dict[str, object]]]] = {}
    for row in command_rows:
        qwd_state = dict_or_empty(row.get("qwd_state"))
        if not bool(qwd_state.get("active", False)):
            continue
        aligned = qwd_aligned_mvd_time_ms(row, timing)
        if aligned is None or match_duration is None or not (0 <= aligned <= match_duration):
            continue
        index = optional_int(qwd_state.get("control_point_index"))
        if index is None:
            continue
        rows_by_index.setdefault(index, []).append((aligned, row))

    segments = movement_segments(samples)
    phases: list[dict[str, object]] = []
    for index in sorted(rows_by_index):
        rows_with_time = sorted(rows_by_index[index], key=lambda item: item[0])
        times = [item[0] for item in rows_with_time]
        rows = [item[1] for item in rows_with_time]
        start_ms = min(times)
        end_ms = max(times)
        overlapping_segments = [
            segment for segment in segments if start_ms <= int(segment["mid_ms"]) <= end_ms
        ]
        target = control_points[index] if 0 <= index < len(control_points) else control_points[-1]
        command_summary = summarize_command_rows(rows)
        phases.append(
            {
                "control_point_index": index,
                "active_mvd_range_ms": {"min": start_ms, "max": end_ms},
                "active_duration_s": round((end_ms - start_ms) / 1000.0, 3),
                "commands": command_summary,
                "movement": summarize_segments(overlapping_segments),
                "closest_target_during_phase": closest_distance_in_range(samples, target, start_ms, end_ms),
            }
        )
    return phases


def slow_success_players(result: dict[str, object]) -> set[str]:
    players: set[str] = set()
    conditions = result.get("stop_condition_results", [])
    if not isinstance(conditions, list):
        return players
    for condition in conditions:
        if not isinstance(condition, dict) or condition.get("id") != "waypoint_only_slow_success":
            continue
        details = dict_or_empty(condition.get("details"))
        raw_players = details.get("players_reaching_points_while_slow_or_stuck")
        if isinstance(raw_players, list):
            players.update(str(player) for player in raw_players)
    return players


def phase_by_index(phases: list[dict[str, object]], index: int) -> dict[str, object]:
    for phase in phases:
        if optional_int(phase.get("control_point_index")) == index:
            return phase
    return {}


def classify_player(
    *,
    player: dict[str, object],
    run_start_radius: float,
    design_start_radius: float,
    point_radius: float,
    slow_success_candidate: bool = True,
) -> dict[str, object]:
    flags: list[str] = []
    phases = player.get("active_phases", []) if isinstance(player.get("active_phases"), list) else []
    radius_rows = player.get("start_radius_sensitivity", []) if isinstance(player.get("start_radius_sensitivity"), list) else []
    by_radius = {
        optional_float(row.get("radius_qu")): optional_int(row.get("first_time_ms"))
        for row in radius_rows
        if isinstance(row, dict)
    }
    run_first = by_radius.get(run_start_radius)
    design_first = by_radius.get(design_start_radius)
    if run_first is not None and design_first is not None and design_first - run_first >= 5000:
        flags.append("loose_start_radius_contaminated_active_window")

    cp0 = phase_by_index(phases, 0)
    cp0_commands = dict_or_empty(cp0.get("commands"))
    cp0_movement = dict_or_empty(cp0.get("movement"))
    if (optional_float(cp0_movement.get("low_speed_ratio")) or 0.0) >= 0.40:
        flags.append("cp0_phase_low_speed_before_tight_start")
    if (optional_float(cp0_movement.get("stationary_ratio")) or 0.0) >= 0.25:
        flags.append("cp0_phase_stationary_before_tight_start")
    if (optional_float(cp0_commands.get("blocked_ratio")) or 0.0) >= 0.25:
        flags.append("cp0_route_blocked_context")

    max_index = max((optional_int(phase.get("control_point_index")) or 0 for phase in phases), default=0)
    final_phase = phase_by_index(phases, max_index)
    final_closest = dict_or_empty(final_phase.get("closest_target_during_phase"))
    if max_index >= 4 and (optional_float(final_closest.get("distance_qu")) or 999999.0) > point_radius:
        flags.append("post_cp3_target_gap_remains_outside_point_radius")

    command_profiles = [dict_or_empty(phase.get("commands")) for phase in phases]
    if command_profiles and all((optional_float(profile.get("side_nonzero_ratio")) or 0.0) >= 0.80 for profile in command_profiles):
        flags.append("strong_qwd_side_profile_present")
    if command_profiles and all((optional_float(profile.get("jump_ratio")) or 0.0) >= 0.80 for profile in command_profiles):
        flags.append("strong_jump_profile_present")
    if command_profiles and max((optional_float(profile.get("water_path_ratio")) or 0.0 for profile in command_profiles), default=0.0) < 0.10:
        flags.append("water_path_not_primary")
    if command_profiles and max((optional_float(profile.get("low_dir_speed_ratio")) or 0.0 for profile in command_profiles), default=0.0) < 0.10:
        flags.append("low_dir_speed_not_primary")

    if not slow_success_candidate:
        return {"verdict": "not_slow_success_candidate", "flags": flags}

    if "loose_start_radius_contaminated_active_window" in flags and "post_cp3_target_gap_remains_outside_point_radius" in flags:
        verdict = "loose_setup_radius_plus_post_cp3_progression_gap"
    elif "cp0_route_blocked_context" in flags:
        verdict = "route_blocked_context_before_clean_activation"
    elif "strong_qwd_side_profile_present" not in flags or "strong_jump_profile_present" not in flags:
        verdict = "weak_command_profile"
    else:
        verdict = "mixed_controller_and_setup_context"

    return {"verdict": verdict, "flags": flags}


def build_decision(players: list[dict[str, object]]) -> dict[str, object]:
    slow_players = [player for player in players if bool(player.get("slow_success_candidate"))]
    verdicts = {dict_or_empty(player.get("classification")).get("verdict") for player in slow_players}
    if "loose_setup_radius_plus_post_cp3_progression_gap" in verdicts:
        return {
            "verdict": "qwd_sng_slow_success_attributed_to_loose_setup_and_post_cp3_gap",
            "reason": (
                "The advancing bot was activated by the widened start radius long before a tight start-radius "
                "crossing, then still failed to enter the next target radius after CP3. This is not learned SNG."
            ),
            "next_goal": (
                "Tighten SNG activation around the real CP0 approach and add phase-level success gates before "
                "changing projection policy or trying other DM3 QWD moves."
            ),
        }
    return {
        "verdict": "qwd_sng_slow_success_needs_mixed_followup",
        "reason": "The slow-success rejection did not isolate to a single setup or controller cause.",
        "next_goal": "Keep the next follow-up diagnostic and do not expand to other QWD moves yet.",
    }


def build_report(
    *,
    design_path: Path,
    result_path: Path,
    run_id: str,
    artifacts_root: Path,
    stage: str,
) -> dict[str, object]:
    run_dir = artifacts_root / run_id
    if not run_dir.is_dir():
        raise QwdSngProbeInputError(f"Missing run directory: {portable_path(run_dir)}")
    design = load_json(design_path)
    result = load_json(result_path)
    commands_doc = load_json(run_dir / "moveprobe-commands.json")
    commands = commands_doc.get("commands", [])
    if not isinstance(commands, list):
        raise QwdSngProbeInputError("moveprobe-commands.json did not contain a commands list.")
    control_points = load_control_points(design)
    run_env = load_run_env(run_dir)
    timing = load_run_timing(run_dir)
    players_info, samples_by_slot = load_position_samples(run_dir)
    by_ed, by_name = group_commands(commands)
    suggested_cvars = dict_or_empty(dict_or_empty(design.get("probe_contract")).get("suggested_cvars"))
    run_start_radius = configured_radius(
        run_env=run_env,
        suggested_cvars=suggested_cvars,
        env_key="MOVEPROBE_QWD_START_RADIUS",
        cvar_key="k_fb_moveprobe_qwd_start_radius",
        fallback=192.0,
    )
    design_start_radius = optional_float(suggested_cvars.get("k_fb_moveprobe_qwd_start_radius")) or 192.0
    point_radius = configured_radius(
        run_env=run_env,
        suggested_cvars=suggested_cvars,
        env_key="MOVEPROBE_QWD_POINT_RADIUS",
        cvar_key="k_fb_moveprobe_qwd_point_radius",
        fallback=96.0,
    )
    slow_players = slow_success_players(result)

    player_reports: list[dict[str, object]] = []
    for slot, samples in sorted(samples_by_slot.items()):
        info = players_info.get(slot, {})
        name = str(info.get("name") or "")
        if not name:
            continue
        player_commands = commands_for_player(info, by_ed, by_name)
        active_phases = grouped_active_phases(player_commands, timing, samples, control_points)
        player_report = {
            "player": name,
            "slot": slot,
            "user_id": info.get("user_id"),
            "slow_success_candidate": name in slow_players,
            "start_radius_sensitivity": [
                first_entry_for_radius(samples, control_points[0], radius)
                for radius in DEFAULT_RADIUS_SENSITIVITY
            ],
            "active_phases": active_phases,
        }
        player_report["classification"] = classify_player(
            player=player_report,
            run_start_radius=run_start_radius,
            design_start_radius=design_start_radius,
            point_radius=point_radius,
            slow_success_candidate=name in slow_players,
        )
        player_reports.append(player_report)

    decision = build_decision(player_reports)
    return {
        "schema": SCHEMA,
        "stage": stage,
        "run_id": run_id,
        "source_result_path": portable_path(result_path),
        "source_result_verdict": dict_or_empty(result.get("decision")).get("verdict", ""),
        "run_config": {
            "map": run_env.get("MAP", ""),
            "moveprobe_mode": run_env.get("MOVEPROBE_MODE", ""),
            "qwd_start_radius": run_env.get("MOVEPROBE_QWD_START_RADIUS", ""),
            "design_start_radius": design_start_radius,
            "qwd_point_radius": run_env.get("MOVEPROBE_QWD_POINT_RADIUS", ""),
        },
        "method": (
            "Offline attribution of the setup-repaired SNG run. It splits active QWD commands by current "
            "control-point target, joins each phase to MVD movement segments, and checks whether the slow "
            "guardrail failure is setup, route/map context, or command-profile weakness."
        ),
        "players": player_reports,
        "decision": decision,
    }


def write_markdown(report: dict[str, object], output_path: Path) -> None:
    decision = dict_or_empty(report.get("decision"))
    config = dict_or_empty(report.get("run_config"))
    lines = [
        f"# QWD SNG Slow-Success Diagnosis {report.get('stage', '')}",
        "",
        "## Scope",
        "",
        f"- Run: `{report.get('run_id', '')}`",
        f"- Source result: `{report.get('source_result_path', '')}`",
        f"- Source verdict: `{report.get('source_result_verdict', '')}`",
        f"- Start radius used: `{config.get('qwd_start_radius', '')}` qu",
        f"- Design start radius: `{config.get('design_start_radius', '')}` qu",
        f"- Point radius: `{config.get('qwd_point_radius', '')}` qu",
        f"- {report.get('method', '')}",
        "",
        "## Player Classification",
        "",
        "| Player | Slow candidate | Verdict | Flags |",
        "|---|---:|---|---|",
    ]
    for player in report.get("players", []) if isinstance(report.get("players"), list) else []:
        if not isinstance(player, dict):
            continue
        classification = dict_or_empty(player.get("classification"))
        flags = ", ".join(str(flag) for flag in classification.get("flags", []) if flag)
        lines.append(
            f"| `{player.get('player', '')}` | `{player.get('slow_success_candidate', False)}` | "
            f"`{classification.get('verdict', '')}` | `{flags}` |"
        )

    lines.extend(["", "## Start Radius Sensitivity", ""])
    for player in report.get("players", []) if isinstance(report.get("players"), list) else []:
        if not isinstance(player, dict):
            continue
        lines.append(f"### {player.get('player', '')}")
        lines.extend(["", "| Radius | First time | Distance | Origin |", "|---:|---:|---:|---|"])
        for row in player.get("start_radius_sensitivity", []) if isinstance(player.get("start_radius_sensitivity"), list) else []:
            if isinstance(row, dict):
                lines.append(
                    f"| {row.get('radius_qu', '')} | {row.get('first_time_ms', '')} | "
                    f"{row.get('distance_qu', '')} | `{row.get('origin', [])}` |"
                )
        lines.append("")

    lines.extend(["## Active Phases", ""])
    for player in report.get("players", []) if isinstance(report.get("players"), list) else []:
        if not isinstance(player, dict):
            continue
        lines.append(f"### {player.get('player', '')}")
        lines.extend(
            [
                "",
                "| CP target | Active range | Commands | MVD p50 | Low | Stationary | QWD dist p50 | Closest target | Blocked | Water path | Low-dir | Cmd h50 |",
                "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for phase in player.get("active_phases", []) if isinstance(player.get("active_phases"), list) else []:
            if not isinstance(phase, dict):
                continue
            time_range = dict_or_empty(phase.get("active_mvd_range_ms"))
            movement = dict_or_empty(phase.get("movement"))
            commands = dict_or_empty(phase.get("commands"))
            qwd_distance = dict_or_empty(commands.get("qwd_distance_qu"))
            closest = dict_or_empty(phase.get("closest_target_during_phase"))
            lines.append(
                f"| {phase.get('control_point_index', '')} | "
                f"`{time_range.get('min', '')}-{time_range.get('max', '')}` | "
                f"{commands.get('command_rows', '')} | {movement.get('p50_speed_qu_per_s', '')} | "
                f"{movement.get('low_speed_ratio', '')} | {movement.get('stationary_ratio', '')} | "
                f"{qwd_distance.get('p50', '')} | {closest.get('distance_qu', '')} | "
                f"{commands.get('blocked_ratio', '')} | {commands.get('water_path_ratio', '')} | "
                f"{commands.get('low_dir_speed_ratio', '')} | {commands.get('median_horizontal_command', '')} |"
            )
        lines.append("")

    lines.extend(
        [
            "## Decision",
            "",
            f"- Verdict: `{decision.get('verdict', '')}`",
            f"- Reason: {decision.get('reason', '')}",
            f"- Next goal: {decision.get('next_goal', '')}",
            "",
        ]
    )
    output_path.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diagnose QWD SNG slow-success attribution.")
    parser.add_argument("--design-json", type=Path, default=DEFAULT_DESIGN)
    parser.add_argument("--result-json", type=Path, default=DEFAULT_RESULT)
    parser.add_argument("--artifacts-root", type=Path, default=DEFAULT_ARTIFACTS_ROOT)
    parser.add_argument("--bot-run-id", type=validate_run_id, required=True)
    parser.add_argument("--stage", default="qwd-sng-slow-success-diagnosis-dm3")
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    return parser.parse_args(list(argv))


def main(argv: Iterable[str] = sys.argv[1:]) -> int:
    args = parse_args(argv)
    report = build_report(
        design_path=args.design_json,
        result_path=args.result_json,
        run_id=args.bot_run_id,
        artifacts_root=args.artifacts_root,
        stage=args.stage,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_markdown(report, args.output_md)
    print(f"output_json={args.output_json}")
    print(f"output_md={args.output_md}")
    print(f"verdict={report['decision']['verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
