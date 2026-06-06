#!/usr/bin/env python3
"""Score the QWD-derived SNG hybrid probe against its design guardrails."""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterable

from run_frobodm2_lab import validate_run_id
from summarize_reference_aggregate import portable_path


SCHEMA = "komodobots.qwd_sng_hybrid_probe_result.v1"
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DESIGN = (
    REPO_ROOT / "experiments" / "qwd_route_probe" / "evidence" / "qwd-sng-hybrid-probe-design-dm3.json"
)
DEFAULT_ARTIFACTS_ROOT = REPO_ROOT / "artifacts" / "lab-runs"
DEFAULT_OUTPUT_JSON = (
    REPO_ROOT / "experiments" / "qwd_route_probe" / "evidence" / "qwd-sng-hybrid-probe-result-dm3.json"
)
DEFAULT_OUTPUT_MD = (
    REPO_ROOT / "experiments" / "qwd_route_probe" / "evidence" / "qwd-sng-hybrid-probe-result-dm3.md"
)
WATER_PATH_FLAG = 32768


class QwdSngProbeInputError(RuntimeError):
    """Raised when the QWD SNG probe cannot resolve required evidence."""


def load_json(path: Path) -> dict[str, object]:
    with path.open("r", encoding="utf-8") as handle:
        loaded = json.load(handle)
    if not isinstance(loaded, dict):
        raise QwdSngProbeInputError(f"{portable_path(path)} did not contain a JSON object.")
    return loaded


def optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def dict_or_empty(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def rounded(value: object, digits: int = 3) -> float | None:
    number = optional_float(value)
    if number is None:
        return None
    return round(number, digits)


def compact_unique(values: Iterable[object], limit: int = 12) -> list[object]:
    unique = sorted(set(values), key=lambda value: (str(type(value)), value))
    if len(unique) <= limit:
        return list(unique)
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


def load_run_timing(run_dir: Path) -> dict[str, object]:
    server_start_time_s: float | None = None
    events_path = run_dir / "events.txt"
    if events_path.exists():
        with events_path.open("r", encoding="utf-8", errors="replace") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                data = dict_or_empty(event.get("data"))
                server_data = dict_or_empty(data.get("Data"))
                if event.get("kind") == 0 and server_data:
                    server_start_time_s = optional_float(server_data.get("ServerTime"))
                    break
    analysis = load_json(run_dir / "analysis.json") if (run_dir / "analysis.json").exists() else {}
    match = dict_or_empty(analysis.get("match"))
    return {
        "server_start_time_s": server_start_time_s,
        "match_duration_ms": optional_int(match.get("duration")),
    }


def qwd_aligned_mvd_time_ms(row: dict[str, object], timing: dict[str, object]) -> int | None:
    command_time_s = optional_float(row.get("time_s"))
    server_start_time_s = optional_float(timing.get("server_start_time_s"))
    if command_time_s is None or server_start_time_s is None:
        return None
    return int(round((command_time_s - server_start_time_s) * 1000.0))


def load_movement_players(run_dir: Path) -> dict[str, dict[str, object]]:
    path = run_dir / "movement-metrics.json"
    if not path.exists():
        return {}
    loaded = load_json(path)
    players = loaded.get("players", [])
    if not isinstance(players, list):
        return {}
    return {
        str(player.get("name", "")): player
        for player in players
        if isinstance(player, dict) and not bool(player.get("spectator", False))
    }


def summarize_player_commands(
    run_id: str,
    player: str,
    commands: list[dict[str, object]],
    movement: dict[str, object],
    timing: dict[str, object],
) -> dict[str, object]:
    qwd_states = [row.get("qwd_state", {}) for row in commands if isinstance(row.get("qwd_state"), dict)]
    route_states = [row.get("route_state", {}) for row in commands if isinstance(row.get("route_state"), dict)]
    water_states = [row.get("water_state", {}) for row in commands if isinstance(row.get("water_state"), dict)]
    probe_states = [row.get("probe_state", {}) for row in commands if isinstance(row.get("probe_state"), dict)]
    active = [state for state in qwd_states if bool(state.get("active", False))]
    complete = [state for state in qwd_states if bool(state.get("complete", False))]
    distances = [
        value
        for state in qwd_states
        if (value := optional_float(state.get("distance_qu"))) is not None and value < 999999.0
    ]
    active_seconds = [
        value
        for state in qwd_states
        if (value := optional_float(state.get("active_seconds"))) is not None
    ]
    path_state_values = [optional_int(state.get("path_state")) or 0 for state in route_states]
    water_path_count = sum(1 for value in path_state_values if value & WATER_PATH_FLAG)
    low_dir_count = sum(
        1
        for state in route_states
        if (value := optional_float(state.get("dir_speed"))) is not None and value < 0.25
    )
    side_nonzero = sum(1 for row in commands if abs(optional_int(dict_or_empty(row.get("move")).get("side")) or 0) > 0)
    forward_nonzero = sum(
        1 for row in commands if abs(optional_int(dict_or_empty(row.get("move")).get("forward")) or 0) > 0
    )
    jump_button = sum(1 for row in commands if (optional_int(row.get("buttons")) or 0) & 2)
    active_commands = [
        row
        for row in commands
        if isinstance(row.get("qwd_state"), dict) and bool(row["qwd_state"].get("active", False))
    ]
    active_side_nonzero = sum(
        1 for row in active_commands if abs(optional_int(dict_or_empty(row.get("move")).get("side")) or 0) > 0
    )
    active_jump_button = sum(1 for row in active_commands if (optional_int(row.get("buttons")) or 0) & 2)
    sample_count = len(commands)
    qwd_count = len(qwd_states)
    active_aligned_times = [
        aligned
        for row in active_commands
        if (aligned := qwd_aligned_mvd_time_ms(row, timing)) is not None
    ]
    match_duration_ms = optional_int(timing.get("match_duration_ms"))
    active_inside_mvd = [
        aligned
        for aligned in active_aligned_times
        if match_duration_ms is not None and 0 <= aligned <= match_duration_ms
    ]

    return {
        "run_id": run_id,
        "player": player,
        "command_samples": sample_count,
        "qwd_sample_count": qwd_count,
        "qwd_active_count": len(active),
        "qwd_active_ratio": round(len(active) / qwd_count, 3) if qwd_count else None,
        "qwd_complete_count": len(complete),
        "qwd_complete_ratio": round(len(complete) / qwd_count, 3) if qwd_count else None,
        "max_control_point_index": max((int(state.get("control_point_index", 0)) for state in qwd_states), default=0),
        "max_advanced_control_points": max(
            (int(state.get("advanced_control_points", 0)) for state in qwd_states),
            default=0,
        ),
        "control_point_count_values": compact_unique(
            int(state.get("control_point_count", 0)) for state in qwd_states
        )
        if qwd_states
        else [],
        "min_qwd_distance_qu": round(min(distances), 3) if distances else None,
        "max_qwd_active_seconds": round(max(active_seconds), 3) if active_seconds else 0.0,
        "qwd_active_aligned_mvd_time_range_ms": {
            "min": min(active_aligned_times) if active_aligned_times else None,
            "max": max(active_aligned_times) if active_aligned_times else None,
        },
        "qwd_active_inside_mvd_count": len(active_inside_mvd),
        "qwd_active_inside_mvd_ratio": round(len(active_inside_mvd) / len(active_commands), 3)
        if active_commands and match_duration_ms is not None
        else None,
        "match_duration_ms": match_duration_ms,
        "server_start_time_s": rounded(timing.get("server_start_time_s"), 3),
        "side_nonzero_ratio": round(side_nonzero / sample_count, 3) if sample_count else None,
        "forward_nonzero_ratio": round(forward_nonzero / sample_count, 3) if sample_count else None,
        "jump_button_ratio": round(jump_button / sample_count, 3) if sample_count else None,
        "active_side_nonzero_ratio": round(active_side_nonzero / len(active_commands), 3) if active_commands else None,
        "active_jump_button_ratio": round(active_jump_button / len(active_commands), 3) if active_commands else None,
        "route_state_sample_count": len(route_states),
        "water_state_sample_count": len(water_states),
        "probe_state_sample_count": len(probe_states),
        "water_path_ratio": round(water_path_count / len(route_states), 3) if route_states else None,
        "low_dir_speed_ratio": round(low_dir_count / len(route_states), 3) if route_states else None,
        "stationary_time_ratio": rounded(movement.get("stationary_time_ratio")),
        "low_speed_time_ratio": rounded(movement.get("low_speed_time_ratio")),
        "avg_horizontal_speed_qu_per_s": rounded(movement.get("avg_horizontal_speed_qu_per_s")),
        "p95_horizontal_speed_qu_per_s": rounded(movement.get("p95_horizontal_speed_qu_per_s")),
        "jump_cadence_per_min": rounded(movement.get("jump_cadence_per_min")),
        "airborne_proxy_time_ratio": rounded(movement.get("airborne_proxy_time_ratio")),
    }


def summarize_runs(run_ids: list[str], artifacts_root: Path) -> tuple[list[dict[str, object]], list[dict[str, object]], list[str]]:
    players: list[dict[str, object]] = []
    run_configs: list[dict[str, object]] = []
    warnings: list[str] = []
    for run_id in run_ids:
        run_dir = artifacts_root / run_id
        command_path = run_dir / "moveprobe-commands.json"
        if not command_path.exists():
            warnings.append(f"Missing moveprobe command log for `{run_id}` at `{portable_path(command_path)}`.")
            continue
        env = load_run_env(run_dir)
        timing = load_run_timing(run_dir)
        run_configs.append(
            {
                "run_id": run_id,
                "map": env.get("MAP", ""),
                "moveprobe_mode": env.get("MOVEPROBE_MODE", ""),
                "forwardmove": env.get("MOVEPROBE_FORWARDMOVE", ""),
                "sidemove": env.get("MOVEPROBE_SIDEMOVE", ""),
                "qwd_waypoint_chars": len(env.get("MOVEPROBE_QWD_WAYPOINTS", "")),
                "qwd_point_radius": env.get("MOVEPROBE_QWD_POINT_RADIUS", ""),
                "qwd_start_radius": env.get("MOVEPROBE_QWD_START_RADIUS", ""),
                "command_logging": env.get("MOVEPROBE_LOG_COMMANDS", ""),
                "command_log_interval": env.get("MOVEPROBE_LOG_INTERVAL", ""),
                "server_start_time_s": timing.get("server_start_time_s"),
                "match_duration_ms": timing.get("match_duration_ms"),
            }
        )
        if env.get("MAP", "") != "dm3":
            warnings.append(f"Run `{run_id}` is `{env.get('MAP', '')}`, not `dm3`.")
        if env.get("MOVEPROBE_MODE", "") != "9":
            warnings.append(f"Run `{run_id}` is mode `{env.get('MOVEPROBE_MODE', '')}`, not mode `9`.")
        movement_players = load_movement_players(run_dir)
        loaded = load_json(command_path)
        grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
        for command in loaded.get("commands", []) if isinstance(loaded.get("commands"), list) else []:
            if not isinstance(command, dict):
                continue
            grouped[str(command.get("name", ""))].append(command)
        for player, commands in sorted(grouped.items()):
            players.append(summarize_player_commands(run_id, player, commands, movement_players.get(player, {}), timing))
    return players, run_configs, warnings


def aggregate_players(players: list[dict[str, object]]) -> dict[str, object]:
    if not players:
        return {
            "player_count": 0,
            "command_samples": 0,
            "qwd_sample_count": 0,
            "qwd_active_count": 0,
            "max_advanced_control_points": 0,
            "max_control_point_index": 0,
            "max_qwd_active_seconds": 0.0,
        }
    qwd_samples = sum(int(player.get("qwd_sample_count", 0) or 0) for player in players)
    active_count = sum(int(player.get("qwd_active_count", 0) or 0) for player in players)
    command_samples = sum(int(player.get("command_samples", 0) or 0) for player in players)
    return {
        "player_count": len(players),
        "command_samples": command_samples,
        "qwd_sample_count": qwd_samples,
        "qwd_active_count": active_count,
        "qwd_active_ratio": round(active_count / qwd_samples, 3) if qwd_samples else None,
        "max_advanced_control_points": max(
            int(player.get("max_advanced_control_points", 0) or 0) for player in players
        ),
        "max_control_point_index": max(int(player.get("max_control_point_index", 0) or 0) for player in players),
        "max_qwd_active_seconds": max(float(player.get("max_qwd_active_seconds", 0.0) or 0.0) for player in players),
        "min_qwd_distance_qu": min(
            value
            for player in players
            if (value := optional_float(player.get("min_qwd_distance_qu"))) is not None
        )
        if any(optional_float(player.get("min_qwd_distance_qu")) is not None for player in players)
        else None,
    }


def evaluate_stop_conditions(players: list[dict[str, object]], aggregate: dict[str, object]) -> list[dict[str, object]]:
    diagnostics_missing = [
        player["player"]
        for player in players
        if not player.get("route_state_sample_count")
        or not player.get("water_state_sample_count")
        or player.get("jump_cadence_per_min") is None
    ]
    active_seconds = optional_float(aggregate.get("max_qwd_active_seconds")) or 0.0
    advanced = int(aggregate.get("max_advanced_control_points", 0) or 0)
    activated = int(aggregate.get("qwd_active_count", 0) or 0) > 0
    active_but_outside_mvd = [
        player["player"]
        for player in players
        if int(player.get("qwd_active_count", 0) or 0) > 0
        and int(player.get("qwd_active_inside_mvd_count", 0) or 0) == 0
    ]
    slow_success_players = [
        player["player"]
        for player in players
        if int(player.get("max_advanced_control_points", 0) or 0) >= 4
        and (
            (optional_float(player.get("stationary_time_ratio")) or 0.0) > 0.25
            or (optional_float(player.get("low_speed_time_ratio")) or 0.0) > 0.40
        )
    ]
    route_dirty_players = [
        player["player"]
        for player in players
        if (
            (optional_float(player.get("water_path_ratio")) or 0.0) >= 0.50
            or (optional_float(player.get("low_dir_speed_ratio")) or 0.0) >= 0.50
        )
        and int(player.get("max_advanced_control_points", 0) or 0) >= 4
    ]
    weak_command_players = [
        player["player"]
        for player in players
        if int(player.get("qwd_active_count", 0) or 0) > 0
        and (
            (optional_float(player.get("active_side_nonzero_ratio")) or 0.0) < 0.80
            or (optional_float(player.get("active_jump_button_ratio")) or 0.0) < 0.80
        )
    ]
    return [
        {
            "id": "qwd_probe_activation",
            "status": "pass" if activated and active_seconds >= 1.0 else "inconclusive",
            "details": {
                "active_samples": aggregate.get("qwd_active_count"),
                "max_active_seconds": aggregate.get("max_qwd_active_seconds"),
                "required_active_seconds": 1.0,
            },
        },
        {
            "id": "control_point_advancement",
            "status": "pass" if advanced >= 4 else "inconclusive",
            "details": {
                "max_advanced_control_points": advanced,
                "required_advanced_control_points": 4,
            },
        },
        {
            "id": "qwd_activation_mvd_overlap",
            "status": "pass" if not active_but_outside_mvd and activated else "inconclusive",
            "details": {
                "players_with_active_qwd_outside_mvd_window": active_but_outside_mvd,
                "rule": "QWD activation/advancement must overlap the parsed MVD movement window before movement guardrails can support a positive claim.",
            },
        },
        {
            "id": "diagnostic_preservation",
            "status": "pass" if not diagnostics_missing and players else "inconclusive",
            "details": {"players_missing_route_water_or_cadence": diagnostics_missing},
        },
        {
            "id": "qwd_command_profile_present",
            "status": "pass" if not weak_command_players and players else "inconclusive",
            "details": {"players_with_weak_active_side_or_jump_profile": weak_command_players},
        },
        {
            "id": "waypoint_only_slow_success",
            "status": "reject" if slow_success_players else "pass",
            "details": {
                "players_reaching_points_while_slow_or_stuck": slow_success_players,
                "stationary_threshold": 0.25,
                "low_speed_threshold": 0.40,
            },
        },
        {
            "id": "route_dirty_success_guardrail",
            "status": "reject" if route_dirty_players else "pass",
            "details": {
                "players_reaching_points_with_dirty_route_context": route_dirty_players,
                "water_path_or_low_dir_threshold": 0.50,
            },
        },
    ]


def make_decision(stop_conditions: list[dict[str, object]]) -> dict[str, object]:
    reject_ids = [condition["id"] for condition in stop_conditions if condition.get("status") == "reject"]
    inconclusive_ids = [
        condition["id"] for condition in stop_conditions if condition.get("status") == "inconclusive"
    ]
    if reject_ids:
        return {
            "verdict": "qwd_sng_hybrid_probe_rejected_by_guardrails",
            "reason": f"The server-loop probe produced evidence, but guardrails failed: {', '.join(reject_ids)}.",
            "next_goal": "Diagnose whether the failure is route/context contamination or controller command policy before widening QWD control.",
            "failed_stop_conditions": reject_ids,
            "inconclusive_stop_conditions": inconclusive_ids,
        }
    if inconclusive_ids:
        return {
            "verdict": "qwd_sng_hybrid_probe_inconclusive",
            "reason": f"The server-loop probe lacked required evidence for: {', '.join(inconclusive_ids)}.",
            "next_goal": "Repair activation, instrumentation, or spawn/context setup before trying other DM3 QWD moves.",
            "failed_stop_conditions": [],
            "inconclusive_stop_conditions": inconclusive_ids,
        }
    return {
        "verdict": "qwd_sng_hybrid_probe_positive_bounded_evidence",
        "reason": "The probe activated, advanced at least four control points, preserved diagnostics, and avoided slow/dirty success guardrails.",
        "next_goal": "Repeat or extend the QWD-derived method to the next clean DM3 QWD move before broadening beyond temporary moveprobe control.",
        "failed_stop_conditions": [],
        "inconclusive_stop_conditions": [],
    }


def build_report(
    design: dict[str, object],
    *,
    stage: str,
    bot_run_ids: list[str],
    artifacts_root: Path,
    design_path: Path,
) -> dict[str, object]:
    players, run_configs, warnings = summarize_runs(bot_run_ids, artifacts_root)
    aggregate = aggregate_players(players)
    stop_conditions = evaluate_stop_conditions(players, aggregate)
    return {
        "schema": SCHEMA,
        "stage": stage,
        "map": "dm3",
        "source_design_path": portable_path(design_path),
        "source_design_stage": design.get("stage", ""),
        "bot_run_ids": bot_run_ids,
        "run_configs": run_configs,
        "warnings": warnings,
        "method": (
            "Score temporary mode-9 SNG hybrid waypoint/controller runs by QWD activation, control-point "
            "advancement, command profile, and route/water/cadence guardrails. Speed alone cannot pass."
        ),
        "probe_contract": design.get("probe_contract", {}),
        "aggregate": aggregate,
        "players": players,
        "stop_condition_results": stop_conditions,
        "decision": make_decision(stop_conditions),
    }


def validate_report(report: dict[str, object]) -> None:
    warnings = report.get("warnings", [])
    if warnings:
        raise QwdSngProbeInputError("; ".join(str(warning) for warning in warnings))
    if not report.get("players"):
        raise QwdSngProbeInputError("No player command rows resolved for QWD SNG probe.")


def write_markdown(report: dict[str, object], output_path: Path) -> None:
    decision = report.get("decision", {}) if isinstance(report.get("decision"), dict) else {}
    aggregate = report.get("aggregate", {}) if isinstance(report.get("aggregate"), dict) else {}
    lines = [
        f"# QWD SNG Hybrid Probe Result {report.get('stage', '')}",
        "",
        "## Scope",
        "",
        f"- Map: `{report.get('map', '')}`",
        f"- Source design: `{report.get('source_design_path', '')}`",
        f"- Bot run IDs: `{', '.join(report.get('bot_run_ids', []))}`",
        f"- {report.get('method', '')}",
        "",
        "## Aggregate",
        "",
        f"- Command samples: `{aggregate.get('command_samples', 0)}`",
        f"- QWD samples: `{aggregate.get('qwd_sample_count', 0)}`",
        f"- QWD active samples: `{aggregate.get('qwd_active_count', 0)}`",
        f"- Max active seconds: `{aggregate.get('max_qwd_active_seconds', 0.0)}`",
        f"- Max advanced control points: `{aggregate.get('max_advanced_control_points', 0)}`",
        f"- Max control-point index: `{aggregate.get('max_control_point_index', 0)}`",
        f"- Min QWD target distance: `{aggregate.get('min_qwd_distance_qu', '')}` qu",
        "",
        "## Players",
        "",
        "| Run | Player | Cmds | Active | Active in MVD | Advanced | Active s | Min dist | Low | Stationary | Water path | Low-dir | Active side | Active jump |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for player in report.get("players", []) if isinstance(report.get("players"), list) else []:
        if not isinstance(player, dict):
            continue
        lines.append(
            f"| `{player.get('run_id', '')}` | `{player.get('player', '')}` | "
            f"{player.get('command_samples', 0)} | {player.get('qwd_active_count', 0)} | "
            f"{player.get('qwd_active_inside_mvd_count', '')} | {player.get('max_advanced_control_points', 0)} | "
            f"{player.get('max_qwd_active_seconds', 0.0)} | "
            f"{player.get('min_qwd_distance_qu', '')} | {player.get('low_speed_time_ratio', '')} | "
            f"{player.get('stationary_time_ratio', '')} | {player.get('water_path_ratio', '')} | "
            f"{player.get('low_dir_speed_ratio', '')} | {player.get('active_side_nonzero_ratio', '')} | "
            f"{player.get('active_jump_button_ratio', '')} |"
        )
    lines.extend(
        [
            "",
            "## Stop Conditions",
            "",
            "| Condition | Status | Details |",
            "|---|---|---|",
        ]
    )
    for condition in report.get("stop_condition_results", []) if isinstance(report.get("stop_condition_results"), list) else []:
        if isinstance(condition, dict):
            lines.append(
                f"| `{condition.get('id', '')}` | `{condition.get('status', '')}` | `{json.dumps(condition.get('details', {}), sort_keys=True)}` |"
            )
    lines.extend(
        [
            "",
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
    parser = argparse.ArgumentParser(description="Compare QWD SNG hybrid probe runs against the design contract.")
    parser.add_argument("--design-json", type=Path, default=DEFAULT_DESIGN)
    parser.add_argument("--artifacts-root", type=Path, default=DEFAULT_ARTIFACTS_ROOT)
    parser.add_argument("--bot-run-id", action="append", type=validate_run_id, required=True)
    parser.add_argument("--stage", default="qwd-sng-hybrid-probe-dm3")
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    parser.add_argument("--allow-warnings", action="store_true")
    return parser.parse_args(list(argv))


def main(argv: Iterable[str] = sys.argv[1:]) -> int:
    args = parse_args(argv)
    design = load_json(args.design_json)
    report = build_report(
        design,
        stage=args.stage,
        bot_run_ids=args.bot_run_id,
        artifacts_root=args.artifacts_root,
        design_path=args.design_json,
    )
    if not args.allow_warnings:
        validate_report(report)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    write_markdown(report, args.output_md)
    print(f"output_json={args.output_json}")
    print(f"output_md={args.output_md}")
    print(f"verdict={report['decision']['verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
