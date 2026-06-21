#!/usr/bin/env python3
"""Inspect MVD-derived QWD SNG control-point crossings."""

from __future__ import annotations

import logging
import argparse
import json
import math
import statistics
import sys
from pathlib import Path
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
    distance,
    group_commands,
    load_position_samples,
    valid_origin3,
)
from run_frobodm2_lab import validate_run_id
from summarize_reference_aggregate import portable_path



LOGGER = logging.getLogger(__name__)
SCHEMA = "komodobots.qwd_sng_mvd_crossings.v1"
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DESIGN = (
    REPO_ROOT / "experiments" / "qwd_route_probe" / "evidence" / "qwd-sng-hybrid-probe-design-dm3.json"
)
DEFAULT_RESULT = (
    REPO_ROOT / "experiments" / "qwd_route_probe" / "evidence" / "qwd-sng-tight-start-rerun-dm3.json"
)
DEFAULT_ARTIFACTS_ROOT = REPO_ROOT / "artifacts" / "lab-runs"
DEFAULT_OUTPUT_JSON = (
    REPO_ROOT / "experiments" / "qwd_route_probe" / "evidence" / "qwd-sng-tight-start-mvd-crossings-dm3.json"
)
DEFAULT_OUTPUT_MD = (
    REPO_ROOT / "experiments" / "qwd_route_probe" / "evidence" / "qwd-sng-tight-start-mvd-crossings-dm3.md"
)


def rounded(value: object, digits: int = 3) -> float | None:
    number = optional_float(value)
    if number is None:
        return None
    return round(number, digits)


def horizontal_distance(a: list[float], b: list[float]) -> float:
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2)


def load_control_points(design: dict[str, object]) -> list[list[float]]:
    points: list[list[float]] = []
    for item in design.get("control_points", []) if isinstance(design.get("control_points"), list) else []:
        if not isinstance(item, dict):
            continue
        origin = valid_origin3(item.get("qwd_origin"))
        if origin is not None:
            points.append(origin)
    if not points:
        raise QwdSngProbeInputError("Design did not contain QWD control points.")
    return points


def first_entry_event(
    samples: list[dict[str, object]],
    point: list[float],
    *,
    radius: float,
) -> dict[str, object] | None:
    for sample in samples:
        origin = valid_origin3(sample.get("origin"))
        if origin is None:
            continue
        current_distance = distance(origin, point)
        if current_distance <= radius:
            return {
                "time_ms": int(sample["time_ms"]),
                "distance_qu": round(current_distance, 3),
                "origin": [round(float(part), 3) for part in origin],
                "radius_qu": radius,
            }
    return None


def sequential_entry_events(
    samples: list[dict[str, object]],
    control_points: list[list[float]],
    *,
    radius: float,
) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    index = 0
    for sample in samples:
        if index >= len(control_points):
            break
        origin = valid_origin3(sample.get("origin"))
        if origin is None:
            continue
        current_distance = distance(origin, control_points[index])
        if current_distance <= radius:
            events.append(
                {
                    "control_point_index": index,
                    "time_ms": int(sample["time_ms"]),
                    "distance_qu": round(current_distance, 3),
                    "origin": [round(float(part), 3) for part in origin],
                    "radius_qu": radius,
                }
            )
            index += 1
    return events


def nearest_sample(samples: list[dict[str, object]], time_ms: int) -> dict[str, object] | None:
    best: tuple[int, dict[str, object]] | None = None
    for sample in samples:
        sample_time = optional_int(sample.get("time_ms"))
        if sample_time is None:
            continue
        delta = abs(sample_time - time_ms)
        if best is None or delta < best[0]:
            best = (delta, sample)
    return best[1] if best else None


def speeds_between(
    samples: list[dict[str, object]],
    *,
    start_ms: int,
    end_ms: int,
) -> list[float]:
    values: list[float] = []
    window = [
        sample
        for sample in samples
        if (time_ms := optional_int(sample.get("time_ms"))) is not None and start_ms <= time_ms <= end_ms
    ]
    previous: dict[str, object] | None = None
    for sample in window:
        if previous is None:
            previous = sample
            continue
        previous_time = optional_int(previous.get("time_ms"))
        current_time = optional_int(sample.get("time_ms"))
        previous_origin = valid_origin3(previous.get("origin"))
        current_origin = valid_origin3(sample.get("origin"))
        if (
            previous_time is None
            or current_time is None
            or current_time <= previous_time
            or previous_origin is None
            or current_origin is None
        ):
            previous = sample
            continue
        values.append(horizontal_distance(current_origin, previous_origin) / ((current_time - previous_time) / 1000.0))
        previous = sample
    return values


def summarize_speed_window(values: list[float]) -> dict[str, object]:
    if not values:
        return {
            "sample_count": 0,
            "p50_horizontal_speed_qu_per_s": None,
            "avg_horizontal_speed_qu_per_s": None,
            "low_speed_ratio": None,
        }
    return {
        "sample_count": len(values),
        "p50_horizontal_speed_qu_per_s": round(statistics.median(values), 3),
        "avg_horizontal_speed_qu_per_s": round(sum(values) / len(values), 3),
        "low_speed_ratio": round(sum(1 for value in values if value < 100.0) / len(values), 3),
    }


def annotate_transitions(
    samples: list[dict[str, object]],
    entries: list[dict[str, object]],
) -> list[dict[str, object]]:
    annotated: list[dict[str, object]] = []
    previous: dict[str, object] | None = None
    for entry in entries:
        row = dict(entry)
        if previous is None:
            row["transition_from_previous"] = None
        else:
            previous_time = int(previous["time_ms"])
            current_time = int(entry["time_ms"])
            previous_origin = valid_origin3(previous.get("origin"))
            current_origin = valid_origin3(entry.get("origin"))
            duration_s = (current_time - previous_time) / 1000.0
            straight_speed = None
            if previous_origin is not None and current_origin is not None and duration_s > 0:
                straight_speed = horizontal_distance(current_origin, previous_origin) / duration_s
            row["transition_from_previous"] = {
                "from_control_point_index": previous.get("control_point_index"),
                "duration_s": round(duration_s, 3),
                "straight_horizontal_speed_qu_per_s": round(straight_speed, 3) if straight_speed is not None else None,
                "movement_window": summarize_speed_window(
                    speeds_between(samples, start_ms=previous_time, end_ms=current_time)
                ),
            }
        annotated.append(row)
        previous = entry
    return annotated


def first_active_qwd_sample(
    command_rows: list[dict[str, object]],
    timing: dict[str, object],
    match_duration_ms: int | None,
) -> dict[str, object] | None:
    for row in command_rows:
        qwd_state = dict_or_empty(row.get("qwd_state"))
        if not qwd_state.get("active"):
            continue
        aligned = qwd_aligned_mvd_time_ms(row, timing)
        if aligned is None:
            continue
        if match_duration_ms is not None and not (0 <= aligned <= match_duration_ms):
            continue
        return {
            "aligned_mvd_time_ms": aligned,
            "command_time_s": rounded(row.get("time_s")),
            "control_point_index": optional_int(qwd_state.get("control_point_index")),
            "advanced_control_points": optional_int(qwd_state.get("advanced_control_points")),
            "distance_qu": rounded(qwd_state.get("distance_qu")),
        }
    return None


def classify_first_active(first_active: dict[str, object] | None, start_radius: float) -> str:
    if first_active is None:
        return "no_active_qwd_sample_inside_mvd"
    index = optional_int(first_active.get("control_point_index"))
    advanced = optional_int(first_active.get("advanced_control_points")) or 0
    distance_qu = optional_float(first_active.get("distance_qu"))
    if (index is not None and index > 0) or advanced > 0:
        return "sampled_after_internal_advancement"
    if distance_qu is not None and distance_qu <= start_radius:
        return "sampled_preadvance_cp0_inside_start_radius"
    if distance_qu is not None:
        return "sampled_preadvance_cp0_outside_start_radius"
    return "sampled_preadvance_cp0_distance_missing"


def nearest_mvd_context(
    samples: list[dict[str, object]],
    first_active: dict[str, object] | None,
    control_points: list[list[float]],
) -> dict[str, object]:
    if first_active is None:
        return {}
    aligned = optional_int(first_active.get("aligned_mvd_time_ms"))
    target_index = optional_int(first_active.get("control_point_index"))
    if aligned is None:
        return {}
    sample = nearest_sample(samples, aligned)
    origin = valid_origin3(sample.get("origin")) if sample else None
    if sample is None or origin is None:
        return {}
    context: dict[str, object] = {
        "time_ms": sample.get("time_ms"),
        "delta_from_command_ms": int(sample["time_ms"]) - aligned,
        "origin": [round(float(part), 3) for part in origin],
        "distance_to_cp0_qu": round(distance(origin, control_points[0]), 3),
    }
    if target_index is not None and 0 <= target_index < len(control_points):
        context["distance_to_sampled_target_qu"] = round(distance(origin, control_points[target_index]), 3)
    return context


def summarize_player(
    *,
    info: dict[str, object],
    samples: list[dict[str, object]],
    command_rows: list[dict[str, object]],
    control_points: list[list[float]],
    timing: dict[str, object],
    start_radius: float,
    point_radius: float,
) -> dict[str, object]:
    match_duration_ms = optional_int(timing.get("match_duration_ms"))
    start_entry = first_entry_event(samples, control_points[0], radius=start_radius)
    point_entries = sequential_entry_events(samples, control_points, radius=point_radius)
    first_active = first_active_qwd_sample(command_rows, timing, match_duration_ms)
    first_active_status = classify_first_active(first_active, start_radius)
    nearest_context = nearest_mvd_context(samples, first_active, control_points)
    return {
        "player": info.get("name", ""),
        "slot": info.get("slot"),
        "user_id": info.get("user_id"),
        "mvd_sample_count": len(samples),
        "mvd_time_range_ms": {
            "min": int(samples[0]["time_ms"]) if samples else None,
            "max": int(samples[-1]["time_ms"]) if samples else None,
        },
        "first_mvd_cp0_start_radius_entry": start_entry,
        "mvd_sequential_point_radius_entries": annotate_transitions(samples, point_entries),
        "mvd_sequential_point_radius_reached": len(point_entries),
        "first_active_qwd_sample": first_active,
        "first_active_qwd_sample_status": first_active_status,
        "nearest_mvd_sample_at_first_active_qwd": nearest_context,
        "assessment": {
            "physical_start_radius_reached": start_entry is not None,
            "physical_minimum_advancement_reached": len(point_entries) >= 4,
            "sampled_command_start_proven": first_active_status == "sampled_preadvance_cp0_inside_start_radius",
            "sampled_command_start_unresolved": first_active_status == "sampled_after_internal_advancement",
        },
    }


def build_decision(players: list[dict[str, object]], result: dict[str, object]) -> dict[str, object]:
    physical_reached = [
        player["player"]
        for player in players
        if dict_or_empty(player.get("assessment")).get("physical_minimum_advancement_reached")
    ]
    command_start_unresolved = [
        player["player"]
        for player in players
        if dict_or_empty(player.get("assessment")).get("sampled_command_start_unresolved")
    ]
    failed = dict_or_empty(result.get("decision")).get("failed_stop_conditions", [])
    failed_ids = [str(item) for item in failed] if isinstance(failed, list) else []
    if physical_reached and command_start_unresolved:
        return {
            "verdict": "qwd_sng_mvd_crossing_progress_but_start_instrumentation_needed",
            "reason": (
                "MVD position samples independently show tight CP0 approach and sequential point-radius traversal, "
                "but the first sampled QWD command rows are already after internal advancement. This preserves the "
                "start-proof uncertainty while narrowing it to instrumentation/timing correlation rather than route geometry."
            ),
            "physical_minimum_advancement_players": physical_reached,
            "sampled_command_start_unresolved_players": command_start_unresolved,
            "source_failed_stop_conditions": failed_ids,
            "next_goal": (
                "Add event-level QWD activation/advance logging or unsampled advancement rows, then rescore active-window "
                "movement quality before changing projection policy or trying other DM3 QWD moves."
            ),
        }
    if physical_reached:
        return {
            "verdict": "qwd_sng_mvd_crossing_progress_needs_movement_quality_review",
            "reason": "MVD samples show physical control-point traversal; remaining guardrails should be evaluated on active-window movement quality.",
            "physical_minimum_advancement_players": physical_reached,
            "sampled_command_start_unresolved_players": command_start_unresolved,
            "source_failed_stop_conditions": failed_ids,
            "next_goal": "Score active-window movement quality before expanding to other QWD moves.",
        }
    return {
        "verdict": "qwd_sng_mvd_crossing_not_proven",
        "reason": "MVD samples did not show enough sequential point-radius traversal to support a tighter SNG claim.",
        "physical_minimum_advancement_players": physical_reached,
        "sampled_command_start_unresolved_players": command_start_unresolved,
        "source_failed_stop_conditions": failed_ids,
        "next_goal": "Repair setup or route context before changing projection policy.",
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
    control_points = load_control_points(design)
    contract = dict_or_empty(design.get("probe_contract"))
    suggested_cvars = dict_or_empty(contract.get("suggested_cvars"))
    run_env = load_run_env(run_dir)
    timing = load_run_timing(run_dir)
    start_radius = (
        optional_float(run_env.get("MOVEPROBE_QWD_START_RADIUS"))
        or optional_float(suggested_cvars.get("k_fb_moveprobe_qwd_start_radius"))
        or 192.0
    )
    point_radius = (
        optional_float(run_env.get("MOVEPROBE_QWD_POINT_RADIUS"))
        or optional_float(suggested_cvars.get("k_fb_moveprobe_qwd_point_radius"))
        or 96.0
    )
    players, samples_by_slot = load_position_samples(run_dir)
    commands_doc = load_json(run_dir / "moveprobe-commands.json")
    commands = commands_doc.get("commands", [])
    if not isinstance(commands, list):
        raise QwdSngProbeInputError("moveprobe-commands.json did not contain a commands list.")
    by_ed, by_name = group_commands(commands)
    player_rows: list[dict[str, object]] = []
    for slot, samples in sorted(samples_by_slot.items()):
        info = players.get(slot, {})
        if not info:
            continue
        command_rows = commands_for_player(info, by_ed, by_name)
        player_rows.append(
            summarize_player(
                info=info,
                samples=samples,
                command_rows=command_rows,
                control_points=control_points,
                timing=timing,
                start_radius=start_radius,
                point_radius=point_radius,
            )
        )

    return {
        "schema": SCHEMA,
        "stage": stage,
        "run_id": run_id,
        "source_design_path": portable_path(design_path),
        "source_result_path": portable_path(result_path),
        "source_result_verdict": dict_or_empty(result.get("decision")).get("verdict", ""),
        "run_config": {
            "map": run_env.get("MAP", ""),
            "moveprobe_mode": run_env.get("MOVEPROBE_MODE", ""),
            "qwd_start_radius": run_env.get("MOVEPROBE_QWD_START_RADIUS", ""),
            "qwd_point_radius": run_env.get("MOVEPROBE_QWD_POINT_RADIUS", ""),
            "command_log_interval": run_env.get("MOVEPROBE_LOG_INTERVAL", ""),
        },
        "timing": timing,
        "control_point_radii": {
            "start_radius_qu": start_radius,
            "point_radius_qu": point_radius,
        },
        "method": (
            "Use MVD position samples to derive first CP0 start-radius entry and sequential point-radius "
            "control-point entries, then compare those physical crossings with the first sampled QWD command row."
        ),
        "players": player_rows,
        "interpretation": [
            "MVD-derived crossings can prove physical traversal of QWD control-point geometry, but they do not by themselves prove internal mode-9 activation timing.",
            "If the first sampled QWD row is already after internal advancement, the remaining gap is event-level QWD activation/advance instrumentation, not another projection change.",
            "Movement-quality conclusions must still respect the source scorer guardrails; control-point count alone is not movement realism.",
        ],
        "decision": build_decision(player_rows, result),
    }


def write_markdown(report: dict[str, object], output_path: Path) -> None:
    decision = dict_or_empty(report.get("decision"))
    radii = dict_or_empty(report.get("control_point_radii"))
    lines = [
        f"# QWD SNG MVD Crossing Diagnosis {report.get('stage', '')}",
        "",
        "## Scope",
        "",
        f"- Run: `{report.get('run_id', '')}`",
        f"- Source result: `{report.get('source_result_path', '')}`",
        f"- Source verdict: `{report.get('source_result_verdict', '')}`",
        f"- Start radius: `{radii.get('start_radius_qu', '')}` qu",
        f"- Point radius: `{radii.get('point_radius_qu', '')}` qu",
        f"- {report.get('method', '')}",
        "",
        "## Player Summary",
        "",
        "| Player | Start entry | Sequential CPs | First sampled QWD | Nearest MVD at first QWD | Status |",
        "|---|---:|---:|---|---|---|",
    ]
    for player in report.get("players", []) if isinstance(report.get("players"), list) else []:
        if not isinstance(player, dict):
            continue
        start = dict_or_empty(player.get("first_mvd_cp0_start_radius_entry"))
        first = dict_or_empty(player.get("first_active_qwd_sample"))
        nearest = dict_or_empty(player.get("nearest_mvd_sample_at_first_active_qwd"))
        first_text = (
            f"t={first.get('aligned_mvd_time_ms')}ms cp={first.get('control_point_index')} "
            f"adv={first.get('advanced_control_points')} dist={first.get('distance_qu')}"
            if first
            else ""
        )
        nearest_text = (
            f"t={nearest.get('time_ms')}ms d_cp0={nearest.get('distance_to_cp0_qu')} "
            f"d_target={nearest.get('distance_to_sampled_target_qu')}"
            if nearest
            else ""
        )
        lines.append(
            "| "
            f"`{player.get('player', '')}` | "
            f"{start.get('time_ms', '')} ms / {start.get('distance_qu', '')} qu | "
            f"{player.get('mvd_sequential_point_radius_reached', '')} | "
            f"`{first_text}` | "
            f"`{nearest_text}` | "
            f"`{player.get('first_active_qwd_sample_status', '')}` |"
        )
    lines.extend(["", "## Sequential MVD Entries", ""])
    for player in report.get("players", []) if isinstance(report.get("players"), list) else []:
        if not isinstance(player, dict):
            continue
        lines.extend(
            [
                f"### {player.get('player', '')}",
                "",
                "| CP | Time | Distance | Transition s | Straight speed | Window p50 | Window low ratio |",
                "|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        entries = player.get("mvd_sequential_point_radius_entries", [])
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict):
                continue
            transition = dict_or_empty(entry.get("transition_from_previous"))
            window = dict_or_empty(transition.get("movement_window"))
            lines.append(
                "| "
                f"{entry.get('control_point_index', '')} | "
                f"{entry.get('time_ms', '')} | "
                f"{entry.get('distance_qu', '')} | "
                f"{transition.get('duration_s', '') if transition else ''} | "
                f"{transition.get('straight_horizontal_speed_qu_per_s', '') if transition else ''} | "
                f"{window.get('p50_horizontal_speed_qu_per_s', '') if window else ''} | "
                f"{window.get('low_speed_ratio', '') if window else ''} |"
            )
        lines.append("")
    lines.extend(["## Interpretation", ""])
    for note in report.get("interpretation", []) if isinstance(report.get("interpretation"), list) else []:
        lines.append(f"- {note}")
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
    parser = argparse.ArgumentParser(description="Inspect MVD-derived QWD SNG control-point crossings.")
    parser.add_argument("--design-json", type=Path, default=DEFAULT_DESIGN)
    parser.add_argument("--result-json", type=Path, default=DEFAULT_RESULT)
    parser.add_argument("--artifacts-root", type=Path, default=DEFAULT_ARTIFACTS_ROOT)
    parser.add_argument("--bot-run-id", type=validate_run_id, required=True)
    parser.add_argument("--stage", default="qwd-sng-tight-start-mvd-crossings-dm3")
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
