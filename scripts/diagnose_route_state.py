#!/usr/bin/env python3
"""Diagnose route-state gaps from bot movement and command artifacts.

S6a is intentionally a trace diagnosis, not another movement heuristic. It
joins MVD-derived position segments with sampled `FBMOVEPROBE_CMD` rows to see
whether low-speed stretches happen despite strong emitted movement commands,
and to record whether route node/segment state is actually present.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Iterable, TypedDict

from extract_movement_metrics import (
    coerce_optional_int,
    coerce_origin,
    coerce_time_ms,
    percentile,
    read_json_if_present,
    read_run_env,
    round_float,
)


SCHEMA = "komodobots.route_state_diagnosis.v1"
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARTIFACT_ROOT = REPO_ROOT / "artifacts" / "lab-runs"
DEFAULT_LOW_SPEED = 100.0
DEFAULT_TELEPORT_SPEED = 2500.0
DEFAULT_MIN_LOW_WINDOW_MS = 250
DEFAULT_MERGE_GAP_MS = 80
DEFAULT_COMMAND_MARGIN_MS = 150
DEFAULT_STRONG_COMMAND = 400.0

ROUTE_STATE_KEYS = {
    "blocked",
    "goal",
    "goal_ent",
    "next_marker",
    "obstruction",
    "route_index",
    "route_node",
    "route_segment",
    "target",
    "target_ent",
    "waypoint",
}


class Sample(TypedDict):
    time_ms: int
    origin: list[float]
    yaw: float | None


class SlotInfo(TypedDict, total=False):
    slot: int
    name: str
    user_id: object
    spectator: bool
    first_named_time_ms: int | None


def read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def coerce_yaw(value: object) -> float | None:
    if not isinstance(value, list) or len(value) < 2:
        return None
    try:
        return float(value[1])
    except (TypeError, ValueError):
        return None


def horizontal_distance(a: list[float], b: list[float]) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def vector_length(forward: object, side: object) -> float:
    try:
        return math.hypot(float(forward), float(side))
    except (TypeError, ValueError):
        return 0.0


def command_time_ms(row: dict) -> int:
    try:
        return int(round(float(row.get("time_s", 0.0)) * 1000.0))
    except (TypeError, ValueError):
        return 0


def load_position_trace(events_path: Path, run_dir: Path) -> tuple[dict[int, SlotInfo], dict[int, list[Sample]], dict]:
    analysis = read_json_if_present(run_dir / "analysis.json")
    match = analysis.get("match", {}) if isinstance(analysis, dict) else {}
    match_duration_ms = coerce_optional_int(match.get("duration"))

    players: dict[int, SlotInfo] = {}
    samples_by_slot: dict[int, list[Sample]] = {}
    event_count = 0
    position_event_count = 0

    with events_path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            event_count += 1
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
                name = str(player.get("Name") or "")
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
                if name:
                    info["name"] = name
                    if info["first_named_time_ms"] is None:
                        info["first_named_time_ms"] = coerce_time_ms(event, data)
                continue

            if kind != 5:
                continue
            try:
                slot = int(data["PlayerNum"])
            except (KeyError, TypeError, ValueError):
                continue
            origin = coerce_origin(data.get("Origin"))
            if origin is None:
                continue
            position_event_count += 1
            samples_by_slot.setdefault(slot, []).append(
                {
                    "time_ms": coerce_time_ms(event, data),
                    "origin": origin,
                    "yaw": coerce_yaw(data.get("Angles")),
                }
            )

    meta = {
        "event_count": event_count,
        "position_event_count": position_event_count,
        "match_duration_clamp_ms": match_duration_ms,
    }
    return players, samples_by_slot, meta


def filtered_named_samples(
    players: dict[int, SlotInfo],
    samples_by_slot: dict[int, list[Sample]],
    *,
    match_duration_ms: int | None,
) -> dict[int, list[Sample]]:
    filtered: dict[int, list[Sample]] = {}
    for slot, samples in samples_by_slot.items():
        info = players.get(slot, {})
        if not str(info.get("name", "")).strip():
            continue
        first_named_time_ms = info.get("first_named_time_ms")
        kept = samples
        if first_named_time_ms is not None:
            kept = [sample for sample in kept if sample["time_ms"] >= first_named_time_ms]
        if match_duration_ms is not None:
            kept = [sample for sample in kept if sample["time_ms"] <= match_duration_ms]
        if kept:
            filtered[slot] = sorted(kept, key=lambda sample: sample["time_ms"])
    return filtered


def build_segments(samples: list[Sample], *, teleport_speed: float = DEFAULT_TELEPORT_SPEED) -> list[dict]:
    segments: list[dict] = []
    if len(samples) < 2:
        return segments

    previous = samples[0]
    for current in samples[1:]:
        dt_ms = current["time_ms"] - previous["time_ms"]
        if dt_ms <= 0:
            previous = current
            continue
        dt_s = dt_ms / 1000.0
        distance = horizontal_distance(previous["origin"], current["origin"])
        horizontal_speed = distance / dt_s
        dz = current["origin"][2] - previous["origin"][2]
        vertical_speed = dz / dt_s
        if horizontal_speed > teleport_speed or abs(vertical_speed) > teleport_speed:
            previous = current
            continue
        segments.append(
            {
                "start_ms": previous["time_ms"],
                "end_ms": current["time_ms"],
                "dt_ms": dt_ms,
                "start_origin": previous["origin"],
                "end_origin": current["origin"],
                "start_yaw": previous.get("yaw"),
                "end_yaw": current.get("yaw"),
                "horizontal_distance_qu": distance,
                "horizontal_speed_qu_per_s": horizontal_speed,
                "vertical_delta_qu": dz,
                "vertical_speed_qu_per_s": vertical_speed,
            }
        )
        previous = current
    return segments


def new_window(segment: dict) -> dict:
    return {
        "start_ms": segment["start_ms"],
        "end_ms": segment["end_ms"],
        "low_duration_ms": 0,
        "low_segment_count": 0,
        "weighted_low_speed": 0.0,
        "horizontal_distance_qu": 0.0,
        "start_origin": segment["start_origin"],
        "end_origin": segment["end_origin"],
        "bbox_min": list(segment["start_origin"]),
        "bbox_max": list(segment["start_origin"]),
    }


def add_segment_to_window(window: dict, segment: dict) -> None:
    window["end_ms"] = segment["end_ms"]
    window["end_origin"] = segment["end_origin"]
    window["low_duration_ms"] += segment["dt_ms"]
    window["low_segment_count"] += 1
    window["weighted_low_speed"] += segment["horizontal_speed_qu_per_s"] * segment["dt_ms"]
    window["horizontal_distance_qu"] += segment["horizontal_distance_qu"]
    for origin in (segment["start_origin"], segment["end_origin"]):
        for index in range(3):
            window["bbox_min"][index] = min(window["bbox_min"][index], origin[index])
            window["bbox_max"][index] = max(window["bbox_max"][index], origin[index])


def finalize_window(window: dict) -> dict:
    low_duration_ms = int(window["low_duration_ms"])
    duration_ms = int(window["end_ms"] - window["start_ms"])
    displacement = horizontal_distance(window["start_origin"], window["end_origin"])
    z_range = window["bbox_max"][2] - window["bbox_min"][2]
    return {
        "start_ms": int(window["start_ms"]),
        "end_ms": int(window["end_ms"]),
        "duration_ms": duration_ms,
        "low_duration_ms": low_duration_ms,
        "low_segment_count": int(window["low_segment_count"]),
        "avg_low_speed_qu_per_s": round_float(
            window["weighted_low_speed"] / low_duration_ms if low_duration_ms else 0.0,
            1,
        ),
        "horizontal_distance_qu": round_float(window["horizontal_distance_qu"], 1),
        "net_displacement_qu": round_float(displacement, 1),
        "start_origin": [round_float(value, 1) for value in window["start_origin"]],
        "end_origin": [round_float(value, 1) for value in window["end_origin"]],
        "bbox": {
            "min": [round_float(value, 1) for value in window["bbox_min"]],
            "max": [round_float(value, 1) for value in window["bbox_max"]],
            "z_range_qu": round_float(z_range, 1),
        },
    }


def detect_low_windows(
    segments: list[dict],
    *,
    low_speed: float = DEFAULT_LOW_SPEED,
    min_duration_ms: int = DEFAULT_MIN_LOW_WINDOW_MS,
    merge_gap_ms: int = DEFAULT_MERGE_GAP_MS,
) -> list[dict]:
    windows: list[dict] = []
    current: dict | None = None

    for segment in segments:
        if segment["horizontal_speed_qu_per_s"] >= low_speed:
            continue
        if current is None or segment["start_ms"] > current["end_ms"] + merge_gap_ms:
            if current is not None:
                windows.append(finalize_window(current))
            current = new_window(segment)
        add_segment_to_window(current, segment)

    if current is not None:
        windows.append(finalize_window(current))

    return sorted(
        [window for window in windows if window["low_duration_ms"] >= min_duration_ms],
        key=lambda window: (window["low_duration_ms"], window["duration_ms"]),
        reverse=True,
    )


def command_rows_by_player(commands: dict) -> tuple[dict[int, list[dict]], dict[str, list[dict]]]:
    by_ed: dict[int, list[dict]] = {}
    by_name: dict[str, list[dict]] = {}
    for row in commands.get("commands", []):
        try:
            ed = int(row.get("ed"))
        except (TypeError, ValueError):
            ed = 0
        if ed:
            by_ed.setdefault(ed, []).append(row)
        name = str(row.get("name", "")).strip()
        if name:
            by_name.setdefault(name, []).append(row)
    return by_ed, by_name


def rows_for_slot(info: SlotInfo, by_ed: dict[int, list[dict]], by_name: dict[str, list[dict]]) -> list[dict]:
    try:
        user_id = int(info.get("user_id"))
    except (TypeError, ValueError):
        user_id = 0
    if user_id and user_id in by_ed:
        return sorted(by_ed[user_id], key=command_time_ms)
    return sorted(by_name.get(str(info.get("name", "")).strip(), []), key=command_time_ms)


def summarize_commands_for_window(
    command_rows: list[dict],
    *,
    start_ms: int,
    end_ms: int,
    margin_ms: int = DEFAULT_COMMAND_MARGIN_MS,
    strong_command: float = DEFAULT_STRONG_COMMAND,
) -> dict:
    exact_rows = [
        row for row in command_rows if start_ms <= command_time_ms(row) <= end_ms
    ]
    rows = [
        row
        for row in command_rows
        if start_ms - margin_ms <= command_time_ms(row) <= end_ms + margin_ms
    ]
    magnitudes = [
        vector_length(row.get("move", {}).get("forward", 0), row.get("move", {}).get("side", 0))
        for row in rows
    ]
    yaw_deltas = [
        abs(float(row.get("diagnostics", {}).get("yaw_delta", 0.0)))
        for row in rows
        if "yaw_delta" in row.get("diagnostics", {})
    ]
    jump_count = sum(1 for row in rows if int(row.get("buttons", 0)) & 2)
    backward_count = sum(1 for row in rows if bool(row.get("diagnostics", {}).get("backward", False)))
    strong_count = sum(1 for magnitude in magnitudes if magnitude >= strong_command)

    return {
        "command_count": len(rows),
        "exact_command_count": len(exact_rows),
        "sample_window_ms": {
            "start_ms": start_ms - margin_ms,
            "end_ms": end_ms + margin_ms,
            "margin_ms": margin_ms,
        },
        "avg_horizontal_command": round_float(sum(magnitudes) / len(magnitudes) if magnitudes else 0.0, 1),
        "max_horizontal_command": round_float(max(magnitudes, default=0.0), 1),
        "strong_command_ratio": round_float(strong_count / len(rows) if rows else 0.0),
        "jump_button_ratio": round_float(jump_count / len(rows) if rows else 0.0),
        "backward_command_ratio": round_float(backward_count / len(rows) if rows else 0.0),
        "yaw_delta_sample_count": len(yaw_deltas),
        "yaw_delta_abs_avg": round_float(sum(yaw_deltas) / len(yaw_deltas) if yaw_deltas else 0.0, 1),
        "yaw_delta_abs_p90": round_float(percentile(yaw_deltas, 90), 1),
        "yaw_delta_over_90_ratio": round_float(
            sum(1 for value in yaw_deltas if value > 90.0) / len(yaw_deltas) if yaw_deltas else 0.0
        ),
    }


def infer_window_hint(window: dict, command_summary: dict, *, strong_command: float) -> str:
    if command_summary["command_count"] == 0:
        return "low_speed_without_sampled_commands"
    if command_summary["avg_horizontal_command"] >= strong_command:
        return "low_speed_despite_strong_commands"
    if command_summary["strong_command_ratio"] >= 0.5:
        return "low_speed_with_mixed_strong_commands"
    return "low_speed_with_weak_or_sparse_commands"


def load_map_entities(analysis: dict) -> list[dict]:
    entities: list[dict] = []
    map_entities = analysis.get("mapEntities", {}) if isinstance(analysis, dict) else {}
    for entity in map_entities.get("entities", []) if isinstance(map_entities, dict) else []:
        try:
            x = float(entity.get("x"))
            y = float(entity.get("y"))
            z = float(entity.get("z"))
        except (TypeError, ValueError):
            continue
        entities.append(
            {
                "name": entity.get("name", ""),
                "kind": entity.get("kind", entity.get("class", "")),
                "type": entity.get("type", ""),
                "loc": entity.get("loc", entity.get("name", "")),
                "origin": [x, y, z],
            }
        )
    return entities


def nearest_entities(origin: list[float], entities: list[dict], *, limit: int = 3) -> list[dict]:
    rows = []
    for entity in entities:
        distance = horizontal_distance(origin, entity["origin"])
        rows.append(
            {
                "loc": entity.get("loc", ""),
                "name": entity.get("name", ""),
                "kind": entity.get("kind", ""),
                "type": entity.get("type", ""),
                "distance_qu": round_float(distance, 1),
            }
        )
    rows.sort(key=lambda row: row["distance_qu"])

    deduped = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (str(row.get("loc", "")), str(row.get("kind", "")))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
        if len(deduped) >= limit:
            break
    return deduped


def detect_capabilities(commands: dict, analysis: dict) -> dict:
    diagnostic_keys: set[str] = set()
    route_state_keys: set[str] = set()
    command_count = 0
    for row in commands.get("commands", []):
        command_count += 1
        for key in row.keys():
            if key in ROUTE_STATE_KEYS:
                route_state_keys.add(key)
        diagnostics = row.get("diagnostics", {})
        if isinstance(diagnostics, dict):
            diagnostic_keys.update(str(key) for key in diagnostics.keys())
            route_state_keys.update(str(key) for key in diagnostics.keys() if str(key) in ROUTE_STATE_KEYS)

    entities = load_map_entities(analysis)
    return {
        "position_trace_available": True,
        "command_trace_available": command_count > 0,
        "command_count": command_count,
        "command_diagnostic_keys": sorted(diagnostic_keys),
        "route_direction_available": "route_yaw" in diagnostic_keys,
        "route_node_or_goal_state_available": bool(route_state_keys),
        "route_state_keys": sorted(route_state_keys),
        "map_entity_locations_available": bool(entities),
        "notes": [
            "Current S3g artifacts expose position traces, sampled final commands, view yaw, route yaw, and backward-command diagnostics.",
            "They do not expose Frogbot route node, next waypoint, target entity, obstruction, or route primitive state.",
        ],
    }


def speed_summary(segments: list[dict], *, low_speed: float) -> dict:
    active_ms = sum(segment["dt_ms"] for segment in segments)
    low_ms = sum(segment["dt_ms"] for segment in segments if segment["horizontal_speed_qu_per_s"] < low_speed)
    speeds = [segment["horizontal_speed_qu_per_s"] for segment in segments]
    distance = sum(segment["horizontal_distance_qu"] for segment in segments)
    active_s = active_ms / 1000.0
    return {
        "active_time_s": round_float(active_s),
        "horizontal_distance_qu": round_float(distance, 1),
        "avg_horizontal_speed_qu_per_s": round_float(distance / active_s if active_s else 0.0, 1),
        "p50_horizontal_speed_qu_per_s": round_float(percentile(speeds, 50), 1),
        "p90_horizontal_speed_qu_per_s": round_float(percentile(speeds, 90), 1),
        "p95_horizontal_speed_qu_per_s": round_float(percentile(speeds, 95), 1),
        "max_horizontal_speed_qu_per_s": round_float(max(speeds, default=0.0), 1),
        "low_speed_time_s": round_float(low_ms / 1000.0),
        "low_speed_time_ratio": round_float(low_ms / active_ms if active_ms else 0.0),
    }


def diagnose_player(
    *,
    info: SlotInfo,
    samples: list[Sample],
    command_rows: list[dict],
    entities: list[dict],
    args: argparse.Namespace,
) -> dict:
    segments = build_segments(samples, teleport_speed=args.teleport_speed)
    windows = detect_low_windows(
        segments,
        low_speed=args.low_speed,
        min_duration_ms=args.min_low_window_ms,
        merge_gap_ms=args.merge_gap_ms,
    )
    top_windows = []
    low_despite_strong = 0
    for index, window in enumerate(windows[: args.top_windows], start=1):
        command_summary = summarize_commands_for_window(
            command_rows,
            start_ms=window["start_ms"],
            end_ms=window["end_ms"],
            margin_ms=args.command_margin_ms,
            strong_command=args.strong_command,
        )
        hint = infer_window_hint(window, command_summary, strong_command=args.strong_command)
        if hint == "low_speed_despite_strong_commands":
            low_despite_strong += 1
        start_nearest = nearest_entities(window["start_origin"], entities, limit=2)
        end_nearest = nearest_entities(window["end_origin"], entities, limit=2)
        top_windows.append(
            {
                "rank": index,
                **window,
                "nearest_start": start_nearest,
                "nearest_end": end_nearest,
                "command_summary": command_summary,
                "hint": hint,
            }
        )

    summary = speed_summary(segments, low_speed=args.low_speed)
    longest_low = windows[0]["low_duration_ms"] if windows else 0
    return {
        "slot": info.get("slot"),
        "name": info.get("name", ""),
        "user_id": info.get("user_id"),
        "sample_count": len(samples),
        "segment_count": len(segments),
        "speed": summary,
        "low_windows": {
            "count": len(windows),
            "total_low_duration_ms": sum(window["low_duration_ms"] for window in windows),
            "longest_low_duration_ms": longest_low,
            "top_windows_analyzed": len(top_windows),
            "top_windows_low_speed_despite_strong_commands": low_despite_strong,
        },
        "top_windows": top_windows,
    }


def build_diagnosis(args: argparse.Namespace) -> dict:
    run_dir = Path(args.run_id)
    if not run_dir.is_dir():
        run_dir = args.artifacts_root / args.run_id
    if not run_dir.is_dir():
        raise FileNotFoundError(f"Missing run directory: {run_dir}")

    analysis = read_json_if_present(run_dir / "analysis.json")
    commands = read_json_if_present(run_dir / "moveprobe-commands.json")
    run_env = read_run_env(run_dir)
    players, samples_by_slot, trace_meta = load_position_trace(run_dir / "events.txt", run_dir)
    samples_by_slot = filtered_named_samples(
        players,
        samples_by_slot,
        match_duration_ms=trace_meta["match_duration_clamp_ms"],
    )
    by_ed, by_name = command_rows_by_player(commands)
    entities = load_map_entities(analysis)

    player_summaries = []
    for slot, samples in sorted(samples_by_slot.items()):
        info = players.get(slot)
        if not info:
            continue
        player_summaries.append(
            diagnose_player(
                info=info,
                samples=samples,
                command_rows=rows_for_slot(info, by_ed, by_name),
                entities=entities,
                args=args,
            )
        )

    match = analysis.get("match", {}) if isinstance(analysis, dict) else {}
    capabilities = detect_capabilities(commands, analysis)
    route_state_available = bool(capabilities["route_node_or_goal_state_available"])
    windows_with_strong_commands = sum(
        player["low_windows"]["top_windows_low_speed_despite_strong_commands"]
        for player in player_summaries
    )
    total_top_windows = sum(player["low_windows"]["top_windows_analyzed"] for player in player_summaries)

    interpretation = [
        "S6a used existing MVD position samples plus sampled final moveprobe commands; no new controller heuristic was added.",
        "Current artifacts can show where low-speed spans happen and whether strong commands were sampled nearby.",
    ]
    if not route_state_available:
        interpretation.append(
            "Current artifacts cannot attribute those spans to a Frogbot route node, next waypoint, obstruction, or route primitive."
        )
    if windows_with_strong_commands:
        interpretation.append(
            f"{windows_with_strong_commands} of {total_top_windows} analyzed low-speed windows show low speed despite average sampled horizontal command >= {args.strong_command:.0f}."
        )

    return {
        "schema": SCHEMA,
        "stage": args.stage,
        "run": {
            "run_id": run_dir.name,
            "run_dir": str(run_dir),
            "map": run_env.get("MAP", ""),
            "map_title": match.get("map", ""),
            "moveprobe_mode": run_env.get("MOVEPROBE_MODE", ""),
            "duration_ms": match.get("duration", ""),
        },
        "thresholds": {
            "low_speed_qu_per_s": args.low_speed,
            "teleport_speed_qu_per_s": args.teleport_speed,
            "min_low_window_ms": args.min_low_window_ms,
            "merge_gap_ms": args.merge_gap_ms,
            "command_margin_ms": args.command_margin_ms,
            "strong_command": args.strong_command,
            "top_windows": args.top_windows,
        },
        "trace": trace_meta,
        "capabilities": capabilities,
        "players": player_summaries,
        "interpretation": interpretation,
        "next_goal": (
            "S6b should add minimal route-state logging around the Frogbot command boundary "
            "so low-speed windows can be tagged with route node/goal/obstruction context before "
            "changing the movement controller again."
        ),
    }


def pct(value: object) -> str:
    try:
        return f"{float(value) * 100.0:.1f}%"
    except (TypeError, ValueError):
        return ""


def number(value: object, digits: int = 1) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return ""


def loc_label(rows: list[dict]) -> str:
    if not rows:
        return ""
    first = rows[0]
    loc = str(first.get("loc") or first.get("name") or "")
    distance = first.get("distance_qu", "")
    return f"`{loc}` ({number(distance, 0)}q)"


def write_markdown(diagnosis: dict, output_path: Path) -> None:
    capabilities = diagnosis.get("capabilities", {})
    route_state = "yes" if capabilities.get("route_node_or_goal_state_available") else "no"
    route_direction = "yes" if capabilities.get("route_direction_available") else "no"
    lines = [
        f"# Route State Diagnosis {diagnosis.get('stage', '')}",
        "",
        "## Scope",
        "",
        f"- Run: `{diagnosis.get('run', {}).get('run_id', '')}`",
        f"- Map: `{diagnosis.get('run', {}).get('map', '')}` / `{diagnosis.get('run', {}).get('map_title', '')}`",
        f"- Moveprobe mode: `{diagnosis.get('run', {}).get('moveprobe_mode', '')}`",
        f"- Low-speed threshold: `{diagnosis.get('thresholds', {}).get('low_speed_qu_per_s', '')}` qu/s",
        f"- Route direction available: `{route_direction}`",
        f"- Route node/goal/obstruction state available: `{route_state}`",
        "",
        "## Artifact Capability",
        "",
    ]
    for note in capabilities.get("notes", []):
        lines.append(f"- {note}")
    lines.extend(
        [
            "",
            "## Player Summary",
            "",
            "| Player | Avg | P95 | Max | Low | Low windows | Longest low | Top windows with strong-command low speed |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for player in diagnosis.get("players", []):
        speed = player.get("speed", {})
        low_windows = player.get("low_windows", {})
        lines.append(
            "| "
            f"`{player.get('name', '')}` | "
            f"{number(speed.get('avg_horizontal_speed_qu_per_s'))} | "
            f"{number(speed.get('p95_horizontal_speed_qu_per_s'))} | "
            f"{number(speed.get('max_horizontal_speed_qu_per_s'))} | "
            f"{pct(speed.get('low_speed_time_ratio'))} | "
            f"`{low_windows.get('count', 0)}` | "
            f"`{low_windows.get('longest_low_duration_ms', 0)}` ms | "
            f"`{low_windows.get('top_windows_low_speed_despite_strong_commands', 0)}` / `{low_windows.get('top_windows_analyzed', 0)}` |"
        )

    lines.extend(
        [
            "",
            "## Top Low-Speed Windows",
            "",
            "| Player | Rank | Window | Low ms | Avg low | From | To | Cmds | Avg cmd | Strong | Jump | Abs delta p90 | Hint |",
            "|---|---:|---|---:|---:|---|---|---:|---:|---:|---:|---:|---|",
        ]
    )
    for player in diagnosis.get("players", []):
        for window in player.get("top_windows", []):
            command = window.get("command_summary", {})
            lines.append(
                "| "
                f"`{player.get('name', '')}` | "
                f"`{window.get('rank')}` | "
                f"`{window.get('start_ms')}-{window.get('end_ms')}` | "
                f"`{window.get('low_duration_ms')}` | "
                f"{number(window.get('avg_low_speed_qu_per_s'))} | "
                f"{loc_label(window.get('nearest_start', []))} | "
                f"{loc_label(window.get('nearest_end', []))} | "
                f"`{command.get('command_count', 0)}` | "
                f"{number(command.get('avg_horizontal_command'))} | "
                f"{pct(command.get('strong_command_ratio'))} | "
                f"{pct(command.get('jump_button_ratio'))} | "
                f"{number(command.get('yaw_delta_abs_p90'))} | "
                f"`{window.get('hint', '')}` |"
            )

    lines.extend(["", "## Interpretation", ""])
    for note in diagnosis.get("interpretation", []):
        lines.append(f"- {note}")
    lines.extend(["", "## Next Goal", "", f"- {diagnosis.get('next_goal', '')}", ""])
    output_path.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diagnose S6 route-state gaps from lab artifacts.")
    parser.add_argument("--stage", default="s6a-route-state", help="Stage label for outputs.")
    parser.add_argument("--run-id", required=True, help="Run id or explicit run directory.")
    parser.add_argument("--artifacts-root", type=Path, default=DEFAULT_ARTIFACT_ROOT, help="Lab run artifact root.")
    parser.add_argument("--low-speed", type=float, default=DEFAULT_LOW_SPEED, help="Low-speed threshold in qu/s.")
    parser.add_argument("--teleport-speed", type=float, default=DEFAULT_TELEPORT_SPEED, help="Teleport guard in qu/s.")
    parser.add_argument("--min-low-window-ms", type=int, default=DEFAULT_MIN_LOW_WINDOW_MS, help="Minimum low-window duration.")
    parser.add_argument("--merge-gap-ms", type=int, default=DEFAULT_MERGE_GAP_MS, help="Merge low windows across small gaps.")
    parser.add_argument("--command-margin-ms", type=int, default=DEFAULT_COMMAND_MARGIN_MS, help="Command sampling margin.")
    parser.add_argument("--strong-command", type=float, default=DEFAULT_STRONG_COMMAND, help="Strong horizontal command threshold.")
    parser.add_argument("--top-windows", type=int, default=5, help="Top low-speed windows per player to report.")
    parser.add_argument("--output-json", type=Path, required=True, help="Output JSON path.")
    parser.add_argument("--output-md", type=Path, required=True, help="Output Markdown path.")
    return parser.parse_args(list(argv))


def main(argv: Iterable[str] = sys.argv[1:]) -> int:
    args = parse_args(argv)
    diagnosis = build_diagnosis(args)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(diagnosis, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_markdown(diagnosis, args.output_md)
    print(f"Wrote route-state diagnosis: {args.output_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
