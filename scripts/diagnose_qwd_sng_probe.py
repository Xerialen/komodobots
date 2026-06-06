#!/usr/bin/env python3
"""Diagnose why the QWD-derived SNG hybrid probe did not advance far enough."""

from __future__ import annotations

import argparse
import json
import math
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
from extract_movement_metrics import coerce_origin, coerce_time_ms
from run_frobodm2_lab import validate_run_id
from summarize_reference_aggregate import portable_path


SCHEMA = "komodobots.qwd_sng_probe_diagnosis.v1"
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DESIGN = (
    REPO_ROOT / "experiments" / "qwd_route_probe" / "evidence" / "qwd-sng-hybrid-probe-design-dm3.json"
)
DEFAULT_RESULT = (
    REPO_ROOT / "experiments" / "qwd_route_probe" / "evidence" / "qwd-sng-hybrid-probe-result-dm3.json"
)
DEFAULT_ARTIFACTS_ROOT = REPO_ROOT / "artifacts" / "lab-runs"
DEFAULT_OUTPUT_JSON = (
    REPO_ROOT / "experiments" / "qwd_route_probe" / "evidence" / "qwd-sng-hybrid-probe-diagnosis-dm3.json"
)
DEFAULT_OUTPUT_MD = (
    REPO_ROOT / "experiments" / "qwd_route_probe" / "evidence" / "qwd-sng-hybrid-probe-diagnosis-dm3.md"
)


def distance(a: list[float], b: list[float]) -> float:
    return math.sqrt(sum((a[index] - b[index]) ** 2 for index in range(3)))


def round_value(value: object, digits: int = 3) -> float | None:
    number = optional_float(value)
    if number is None:
        return None
    return round(number, digits)


def safe_time_ms(event: dict[str, object], data: dict[str, object]) -> int | None:
    try:
        return coerce_time_ms(event, data)
    except (KeyError, TypeError, ValueError):
        return None


def valid_origin3(value: object) -> list[float] | None:
    if not isinstance(value, list) or len(value) < 3:
        return None
    try:
        return [float(part) for part in value[:3]]
    except (TypeError, ValueError):
        return None


def load_position_samples(run_dir: Path) -> tuple[dict[int, dict[str, object]], dict[int, list[dict[str, object]]]]:
    events_path = run_dir / "events.txt"
    if not events_path.exists():
        raise QwdSngProbeInputError(f"Missing events file: {portable_path(events_path)}")

    players: dict[int, dict[str, object]] = {}
    samples_by_slot: dict[int, list[dict[str, object]]] = {}
    analysis = load_json(run_dir / "analysis.json") if (run_dir / "analysis.json").exists() else {}
    match = dict_or_empty(analysis.get("match"))
    match_duration_ms = optional_int(match.get("duration"))

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
            if event.get("kind") == 1 and isinstance(data.get("Player"), dict):
                player = data["Player"]
                slot = optional_int(player.get("Slot"))
                if slot is None:
                    continue
                info = players.setdefault(
                    slot,
                    {
                        "slot": slot,
                        "name": "",
                        "user_id": player.get("UserID"),
                        "spectator": bool(player.get("Spectator", False)),
                        "first_named_time_ms": None,
                    },
                )
                info["user_id"] = player.get("UserID")
                info["spectator"] = bool(player.get("Spectator", False))
                name = str(player.get("Name") or "")
                if name:
                    info["name"] = name
                    if info["first_named_time_ms"] is None:
                        info["first_named_time_ms"] = safe_time_ms(event, data)
                continue
            if event.get("kind") != 5:
                continue
            slot = optional_int(data.get("PlayerNum"))
            origin = coerce_origin(data.get("Origin"))
            time_ms = safe_time_ms(event, data)
            if slot is None or origin is None or time_ms is None:
                continue
            samples_by_slot.setdefault(slot, []).append(
                {"time_ms": time_ms, "origin": origin}
            )

    filtered: dict[int, list[dict[str, object]]] = {}
    for slot, samples in samples_by_slot.items():
        info = players.get(slot, {})
        if not str(info.get("name", "")).strip():
            continue
        first_named = optional_int(info.get("first_named_time_ms"))
        kept = samples
        if first_named is not None:
            kept = [sample for sample in kept if int(sample["time_ms"]) >= first_named]
        if match_duration_ms is not None:
            kept = [sample for sample in kept if int(sample["time_ms"]) <= match_duration_ms]
        if kept:
            filtered[slot] = sorted(kept, key=lambda sample: int(sample["time_ms"]))
    return players, filtered


def group_commands(commands: list[dict[str, object]]) -> tuple[dict[int, list[dict[str, object]]], dict[str, list[dict[str, object]]]]:
    by_ed: dict[int, list[dict[str, object]]] = {}
    by_name: dict[str, list[dict[str, object]]] = {}
    for row in commands:
        if not isinstance(row, dict):
            continue
        ed = optional_int(row.get("ed"))
        if ed:
            by_ed.setdefault(ed, []).append(row)
        name = str(row.get("name") or "")
        if name:
            by_name.setdefault(name, []).append(row)
    return by_ed, by_name


def commands_for_player(
    info: dict[str, object],
    by_ed: dict[int, list[dict[str, object]]],
    by_name: dict[str, list[dict[str, object]]],
) -> list[dict[str, object]]:
    user_id = optional_int(info.get("user_id"))
    if user_id and user_id in by_ed:
        return sorted(by_ed[user_id], key=lambda row: optional_float(row.get("time_s")) or 0.0)
    return sorted(by_name.get(str(info.get("name") or ""), []), key=lambda row: optional_float(row.get("time_s")) or 0.0)


def closest_approaches(
    samples: list[dict[str, object]],
    control_points: list[list[float]],
    *,
    limit: int = 6,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index, point in enumerate(control_points[:limit]):
        best: tuple[float, dict[str, object]] | None = None
        for sample in samples:
            origin = valid_origin3(sample.get("origin"))
            if origin is None:
                continue
            current = distance(origin, point)
            if best is None or current < best[0]:
                best = (current, sample)
        rows.append(
            {
                "control_point_index": index,
                "min_distance_qu": round(best[0], 3) if best else None,
                "time_ms": int(best[1]["time_ms"]) if best else None,
                "origin": [round(float(part), 3) for part in best[1]["origin"][:3]] if best else [],
            }
        )
    return rows


def sequential_reach_count(
    samples: list[dict[str, object]],
    control_points: list[list[float]],
    *,
    radius: float,
) -> int:
    index = 0
    for sample in samples:
        if index >= len(control_points):
            break
        origin = valid_origin3(sample.get("origin"))
        if origin is None:
            continue
        if distance(origin, control_points[index]) <= radius:
            index += 1
    return index


def summarize_qwd_commands(
    rows: list[dict[str, object]],
    timing: dict[str, object],
) -> dict[str, object]:
    qwd_rows = [row for row in rows if isinstance(row.get("qwd_state"), dict)]
    active_rows = [row for row in qwd_rows if bool(row["qwd_state"].get("active", False))]
    aligned_active = [
        aligned
        for row in active_rows
        if (aligned := qwd_aligned_mvd_time_ms(row, timing)) is not None
    ]
    match_duration_ms = optional_int(timing.get("match_duration_ms"))
    active_inside = [
        value
        for value in aligned_active
        if match_duration_ms is not None and 0 <= value <= match_duration_ms
    ]
    cp0_distances = [
        value
        for row in qwd_rows
        if optional_int(row["qwd_state"].get("control_point_index")) == 0
        and (value := optional_float(row["qwd_state"].get("distance_qu"))) is not None
    ]
    all_distances = [
        value
        for row in qwd_rows
        if (value := optional_float(row["qwd_state"].get("distance_qu"))) is not None and value < 999999.0
    ]
    command_times = [
        value
        for row in rows
        if (value := optional_float(row.get("time_s"))) is not None
    ]
    advanced_values = [
        optional_int(row["qwd_state"].get("advanced_control_points")) or 0 for row in qwd_rows
    ]
    return {
        "command_rows": len(rows),
        "qwd_rows": len(qwd_rows),
        "active_rows": len(active_rows),
        "active_inside_mvd_rows": len(active_inside),
        "active_aligned_mvd_range_ms": {
            "min": min(aligned_active) if aligned_active else None,
            "max": max(aligned_active) if aligned_active else None,
        },
        "command_time_s_range": {
            "min": round_value(min(command_times)) if command_times else None,
            "max": round_value(max(command_times)) if command_times else None,
        },
        "min_cp0_distance_qu_from_qwd_state": round(min(cp0_distances), 3) if cp0_distances else None,
        "min_any_qwd_distance_qu": round(min(all_distances), 3) if all_distances else None,
        "max_advanced_control_points": max(advanced_values, default=0),
    }


def classify_player(
    *,
    mvd_sequential_reach: int,
    command_summary: dict[str, object],
    start_radius: float,
) -> str:
    active_rows = int(command_summary.get("active_rows", 0) or 0)
    active_inside = int(command_summary.get("active_inside_mvd_rows", 0) or 0)
    min_cp0 = optional_float(command_summary.get("min_cp0_distance_qu_from_qwd_state"))
    if active_rows and not active_inside:
        return "qwd_activation_after_mvd_window"
    if active_rows:
        return "activated_but_failed_control_point_advancement"
    if min_cp0 is not None and min_cp0 > start_radius and mvd_sequential_reach == 0:
        return "spawn_or_route_context_missed_start_radius"
    return "not_enough_qwd_activation_evidence"


def configured_radius(
    *,
    run_env: dict[str, str],
    suggested_cvars: dict[str, object],
    env_key: str,
    cvar_key: str,
    fallback: float,
) -> float:
    return (
        optional_float(run_env.get(env_key))
        or optional_float(suggested_cvars.get(cvar_key))
        or fallback
    )


def failed_stop_condition_ids(result: dict[str, object]) -> list[str]:
    decision = dict_or_empty(result.get("decision"))
    failed = decision.get("failed_stop_conditions")
    if isinstance(failed, list):
        return [str(item) for item in failed if item]

    ids: list[str] = []
    for row in result.get("stop_condition_results", []) if isinstance(result.get("stop_condition_results"), list) else []:
        if isinstance(row, dict) and row.get("status") == "reject" and row.get("id"):
            ids.append(str(row["id"]))
    return ids


def build_decision(
    *,
    result: dict[str, object],
    active_outside_players: list[object],
    missed_start_players: list[object],
) -> dict[str, str]:
    result_decision = dict_or_empty(result.get("decision"))
    result_verdict = str(result_decision.get("verdict") or "")
    failed = failed_stop_condition_ids(result)

    if active_outside_players or missed_start_players:
        return {
            "verdict": "qwd_sng_repair_needs_timing_and_start_context",
            "reason": (
                "The SNG run is still useful, but activation/advancement evidence is not yet cleanly aligned "
                "with the parsed MVD movement window or the configured start context."
            ),
            "next_goal": (
                "Repair mode-9 setup so QWD activation overlaps recorded MVD movement evidence; then decide "
                "whether the control-point radius, start context, or projection policy needs the smallest change."
            ),
        }

    if result_verdict == "qwd_sng_hybrid_probe_rejected_by_guardrails":
        return {
            "verdict": "qwd_sng_setup_repaired_but_rejected_by_guardrails",
            "reason": (
                "QWD activation and control-point advancement now overlap the parsed MVD movement window, "
                f"but guardrails rejected the run: {', '.join(failed) if failed else 'unspecified guardrail'}."
            ),
            "next_goal": (
                "Diagnose whether the remaining failure is controller command policy, route/map context, "
                "or a too-loose setup radius before widening QWD control or trying other DM3 QWD moves."
            ),
        }

    if result_verdict == "qwd_sng_hybrid_probe_inconclusive":
        return {
            "verdict": "qwd_sng_needs_control_point_advancement_repair",
            "reason": (
                "Timing/start context no longer appears to be the primary blocker, but the run still did not "
                "produce enough guarded SNG advancement for a positive claim."
            ),
            "next_goal": (
                "Diagnose command projection and control-point progression before changing controller policy "
                "or expanding to additional DM3 QWD moves."
            ),
        }

    return {
        "verdict": "qwd_sng_probe_ready_for_review",
        "reason": "The scorer did not report timing/start-context blockers or rejected guardrails.",
        "next_goal": "Ask Claude/Code Sentinel to review whether the evidence justifies the next QWD-derived movement step.",
    }


def build_diagnosis(
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
    control_points = [
        [float(part) for part in item["qwd_origin"][:3]]
        for item in design.get("control_points", [])
        if isinstance(item, dict) and isinstance(item.get("qwd_origin"), list) and len(item["qwd_origin"]) >= 3
    ]
    if not control_points:
        raise QwdSngProbeInputError("Design did not contain QWD control points.")

    contract = dict_or_empty(design.get("probe_contract"))
    suggested_cvars = dict_or_empty(contract.get("suggested_cvars"))
    timing = load_run_timing(run_dir)
    run_env = load_run_env(run_dir)
    start_radius = configured_radius(
        run_env=run_env,
        suggested_cvars=suggested_cvars,
        env_key="MOVEPROBE_QWD_START_RADIUS",
        cvar_key="k_fb_moveprobe_qwd_start_radius",
        fallback=192.0,
    )
    point_radius = configured_radius(
        run_env=run_env,
        suggested_cvars=suggested_cvars,
        env_key="MOVEPROBE_QWD_POINT_RADIUS",
        cvar_key="k_fb_moveprobe_qwd_point_radius",
        fallback=96.0,
    )
    players, samples_by_slot = load_position_samples(run_dir)
    by_ed, by_name = group_commands(commands)

    player_rows: list[dict[str, object]] = []
    for slot, samples in sorted(samples_by_slot.items()):
        info = players.get(slot, {})
        if not info:
            continue
        command_rows = commands_for_player(info, by_ed, by_name)
        command_summary = summarize_qwd_commands(command_rows, timing)
        closest = closest_approaches(samples, control_points)
        reached = sequential_reach_count(samples, control_points, radius=point_radius)
        player_rows.append(
            {
                "player": info.get("name", ""),
                "slot": slot,
                "user_id": info.get("user_id"),
                "mvd_sample_count": len(samples),
                "mvd_time_range_ms": {
                    "min": int(samples[0]["time_ms"]) if samples else None,
                    "max": int(samples[-1]["time_ms"]) if samples else None,
                },
                "mvd_sequential_control_points_reached": reached,
                "mvd_closest_control_points": closest,
                "qwd_command_summary": command_summary,
                "classification": classify_player(
                    mvd_sequential_reach=reached,
                    command_summary=command_summary,
                    start_radius=start_radius,
                ),
            }
        )

    active_outside_players = [
        row["player"]
        for row in player_rows
        if row.get("classification") == "qwd_activation_after_mvd_window"
    ]
    missed_start_players = [
        row["player"]
        for row in player_rows
        if row.get("classification") == "spawn_or_route_context_missed_start_radius"
    ]
    interpretation = [
        "This is an offline diagnosis of the already-generated mode-9 run; it does not rerun KTX or change controller behavior.",
        "Command rows use server time, while MVD position rows use demo-relative time. The diagnosis aligns command rows by subtracting the demo start ServerTime from events kind 0.",
    ]
    if active_outside_players:
        interpretation.append(
            "At least one bot activated the QWD probe only after the parsed MVD movement window, so the current run's control-point advancement is command evidence but not clean movement evidence."
        )
    if missed_start_players:
        interpretation.append(
            "At least one bot never reached the configured start radius during the MVD window, pointing at spawn/context setup before controller-policy expansion."
        )
    if not active_outside_players and not missed_start_players:
        interpretation.append(
            "QWD activation now overlaps the parsed MVD movement window, so the remaining blocker is no longer the timing/start-context evidence gate."
        )
    failed = failed_stop_condition_ids(result)
    if failed:
        interpretation.append(
            "The scorer still rejects the run on guardrails: " + ", ".join(failed) + "."
        )

    decision = build_decision(
        result=result,
        active_outside_players=active_outside_players,
        missed_start_players=missed_start_players,
    )

    return {
        "schema": SCHEMA,
        "stage": stage,
        "run_id": run_id,
        "run_config": {
            "map": run_env.get("MAP", ""),
            "moveprobe_mode": run_env.get("MOVEPROBE_MODE", ""),
            "qwd_start_radius": run_env.get("MOVEPROBE_QWD_START_RADIUS", ""),
            "qwd_point_radius": run_env.get("MOVEPROBE_QWD_POINT_RADIUS", ""),
        },
        "source_design_path": portable_path(design_path),
        "source_result_path": portable_path(result_path),
        "source_result_verdict": dict_or_empty(result.get("decision")).get("verdict", ""),
        "timing": timing,
        "control_point_radii": {
            "start_radius_qu": start_radius,
            "point_radius_qu": point_radius,
        },
        "players": player_rows,
        "interpretation": interpretation,
        "decision": decision,
    }


def write_markdown(report: dict[str, object], output_path: Path) -> None:
    decision = dict_or_empty(report.get("decision"))
    timing = dict_or_empty(report.get("timing"))
    lines = [
        f"# QWD SNG Probe Diagnosis {report.get('stage', '')}",
        "",
        "## Scope",
        "",
        f"- Run: `{report.get('run_id', '')}`",
        f"- Source result: `{report.get('source_result_path', '')}`",
        f"- Source verdict: `{report.get('source_result_verdict', '')}`",
        f"- Server start time: `{timing.get('server_start_time_s', '')}` s",
        f"- Match duration: `{timing.get('match_duration_ms', '')}` ms",
        "",
        "## Player Diagnosis",
        "",
        "| Player | Class | MVD window | MVD reached | Active rows | Active in MVD | Active MVD range | Min cp0 from qwd | Min any qwd | Max advanced |",
        "|---|---|---|---:|---:|---:|---|---:|---:|---:|",
    ]
    for player in report.get("players", []) if isinstance(report.get("players"), list) else []:
        if not isinstance(player, dict):
            continue
        command = dict_or_empty(player.get("qwd_command_summary"))
        mvd_window = dict_or_empty(player.get("mvd_time_range_ms"))
        active_range = dict_or_empty(command.get("active_aligned_mvd_range_ms"))
        lines.append(
            "| "
            f"`{player.get('player', '')}` | "
            f"`{player.get('classification', '')}` | "
            f"`{mvd_window.get('min', '')}-{mvd_window.get('max', '')}` | "
            f"{player.get('mvd_sequential_control_points_reached', '')} | "
            f"{command.get('active_rows', '')} | "
            f"{command.get('active_inside_mvd_rows', '')} | "
            f"`{active_range.get('min', '')}-{active_range.get('max', '')}` | "
            f"{command.get('min_cp0_distance_qu_from_qwd_state', '')} | "
            f"{command.get('min_any_qwd_distance_qu', '')} | "
            f"{command.get('max_advanced_control_points', '')} |"
        )

    lines.extend(["", "## Closest MVD Approaches", ""])
    for player in report.get("players", []) if isinstance(report.get("players"), list) else []:
        if not isinstance(player, dict):
            continue
        lines.append(f"### {player.get('player', '')}")
        lines.extend(
            [
                "",
                "| CP | Min distance | Time | Origin |",
                "|---:|---:|---:|---|",
            ]
        )
        for row in player.get("mvd_closest_control_points", []) if isinstance(player.get("mvd_closest_control_points"), list) else []:
            if not isinstance(row, dict):
                continue
            lines.append(
                f"| {row.get('control_point_index', '')} | {row.get('min_distance_qu', '')} | "
                f"{row.get('time_ms', '')} | `{row.get('origin', [])}` |"
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
    parser = argparse.ArgumentParser(description="Diagnose the QWD SNG hybrid probe failure mode.")
    parser.add_argument("--design-json", type=Path, default=DEFAULT_DESIGN)
    parser.add_argument("--result-json", type=Path, default=DEFAULT_RESULT)
    parser.add_argument("--artifacts-root", type=Path, default=DEFAULT_ARTIFACTS_ROOT)
    parser.add_argument("--bot-run-id", type=validate_run_id, required=True)
    parser.add_argument("--stage", default="qwd-sng-repair-diagnosis-dm3")
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    return parser.parse_args(list(argv))


def main(argv: Iterable[str] = sys.argv[1:]) -> int:
    args = parse_args(argv)
    report = build_diagnosis(
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
