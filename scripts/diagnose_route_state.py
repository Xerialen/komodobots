#!/usr/bin/env python3
"""Diagnose route-state gaps from bot movement and command artifacts.

S6a is intentionally a trace diagnosis, not another movement heuristic. It
joins MVD-derived position segments with sampled `FBMOVEPROBE_CMD` rows to see
whether low-speed stretches happen despite strong emitted movement commands,
and to record whether route node/segment state is actually present.
"""

from __future__ import annotations

import logging
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
    read_run_env,
    round_float,
)



LOGGER = logging.getLogger(__name__)
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
    "bot_state",
    "dir_speed",
    "goal",
    "goal_ent",
    "goal_ed",
    "goal_marker",
    "linked_marker",
    "next_marker",
    "obstruction",
    "path_state",
    "route_index",
    "route_node",
    "route_segment",
    "target",
    "target_ent",
    "touch_marker",
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


def read_artifact_json(path: Path, *, artifact_name: str | None = None, warnings: list[str] | None = None) -> dict:
    if not path.exists():
        return {}
    label = artifact_name or path.name
    try:
        with path.open("r", encoding="utf-8") as handle:
            loaded = json.load(handle)
    except json.JSONDecodeError as exc:
        if warnings is not None:
            warnings.append(f"{label} could not be parsed as JSON: {exc.msg} at line {exc.lineno}, column {exc.colno}.")
        return {}
    except OSError as exc:
        if warnings is not None:
            warnings.append(f"{label} could not be read: {exc}.")
        return {}
    if not isinstance(loaded, dict):
        if warnings is not None:
            warnings.append(f"{label} did not contain a JSON object; ignoring it.")
        return {}
    return loaded


def dict_or_empty(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def int_value(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


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


def compact_unique_values(values: Iterable[object], limit: int = 12) -> list[object]:
    unique = sorted(set(values))
    if len(unique) <= limit:
        return list(unique)
    return list(unique[:limit]) + [f"... {len(unique) - limit} more"]


def command_time_ms(row: dict) -> int | None:
    if not isinstance(row, dict):
        return None
    try:
        return int(round(float(row.get("time_s")) * 1000.0))
    except (TypeError, ValueError):
        return None


def load_position_trace(
    events_path: Path,
    run_dir: Path,
    *,
    analysis: dict | None = None,
    warnings: list[str] | None = None,
) -> tuple[dict[int, SlotInfo], dict[int, list[Sample]], dict]:
    if analysis is None:
        analysis = read_artifact_json(run_dir / "analysis.json", artifact_name="analysis.json", warnings=warnings)
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
        if not isinstance(row, dict):
            continue
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
    def sort_key(row: dict) -> int:
        time_ms = command_time_ms(row)
        return time_ms if time_ms is not None else -1

    try:
        user_id = int(info.get("user_id"))
    except (TypeError, ValueError):
        user_id = 0
    if user_id and user_id in by_ed:
        return sorted(by_ed[user_id], key=sort_key)
    return sorted(by_name.get(str(info.get("name", "")).strip(), []), key=sort_key)


def time_range_summary(times: list[int]) -> dict[str, object]:
    if not times:
        return {"count": 0}
    return {"count": len(times), "min_ms": min(times), "max_ms": max(times)}


def command_times_ms(commands: dict) -> list[int]:
    times = []
    for row in commands.get("commands", []):
        if not isinstance(row, dict):
            continue
        try:
            times.append(int(round(float(row.get("time_s")) * 1000.0)))
        except (TypeError, ValueError):
            continue
    return times


def sample_times_ms(samples_by_slot: dict[int, list[Sample]]) -> list[int]:
    return [int(sample["time_ms"]) for samples in samples_by_slot.values() for sample in samples]


def summarize_clock_overlap(samples_by_slot: dict[int, list[Sample]], commands: dict, *, margin_ms: int) -> dict:
    sample_times = sample_times_ms(samples_by_slot)
    command_times = command_times_ms(commands)
    summary = {
        "sample_time_range_ms": time_range_summary(sample_times),
        "command_time_range_ms": time_range_summary(command_times),
        "margin_ms": margin_ms,
        "overlaps": False,
        "overlap_ms": 0,
        "status": "missing_samples_or_commands",
    }
    if not sample_times:
        summary["status"] = "no_position_samples"
        return summary
    if not command_times:
        summary["status"] = "no_commands"
        return summary

    sample_min = min(sample_times)
    sample_max = max(sample_times)
    command_min = min(command_times) - margin_ms
    command_max = max(command_times) + margin_ms
    overlap_start = max(sample_min, command_min)
    overlap_end = min(sample_max, command_max)
    overlaps = overlap_start <= overlap_end
    summary.update(
        {
            "overlaps": overlaps,
            "overlap_ms": max(0, overlap_end - overlap_start),
            "status": "ok" if overlaps else "no_clock_overlap",
        }
    )
    return summary


def summarize_route_states(route_states: list[dict]) -> dict[str, object]:
    if not route_states:
        return {"sample_count": 0}

    blocked_count = sum(1 for state in route_states if bool(state.get("blocked", False)))
    dir_speeds = [round(float(state.get("dir_speed", 0.0)), 3) for state in route_states]
    return {
        "sample_count": len(route_states),
        "linked_marker_values": compact_unique_values(
            int(state.get("linked_marker", -1)) for state in route_states
        ),
        "touch_marker_values": compact_unique_values(
            int(state.get("touch_marker", -1)) for state in route_states
        ),
        "goal_ed_values": compact_unique_values(int(state.get("goal_ed", -1)) for state in route_states),
        "goal_marker_values": compact_unique_values(
            int(state.get("goal_marker", -1)) for state in route_states
        ),
        "path_state_values": compact_unique_values(int(state.get("path_state", 0)) for state in route_states),
        "bot_state_values": compact_unique_values(int(state.get("bot_state", 0)) for state in route_states),
        "blocked_ratio": round_float(blocked_count / len(route_states)),
        "dir_speed_avg": round_float(sum(dir_speeds) / len(dir_speeds) if dir_speeds else 0.0, 3),
        "dir_speed_values": compact_unique_values(dir_speeds),
    }


def summarize_commands_for_window(
    command_rows: list[dict],
    *,
    start_ms: int,
    end_ms: int,
    margin_ms: int = DEFAULT_COMMAND_MARGIN_MS,
    strong_command: float = DEFAULT_STRONG_COMMAND,
) -> dict:
    timed_rows: list[tuple[int, dict]] = []
    for row in command_rows:
        if not isinstance(row, dict):
            continue
        time_ms = command_time_ms(row)
        if time_ms is None:
            continue
        timed_rows.append((time_ms, row))
    exact_rows = [
        row for time_ms, row in timed_rows if start_ms <= time_ms <= end_ms
    ]
    rows = [
        row
        for time_ms, row in timed_rows
        if start_ms - margin_ms <= time_ms <= end_ms + margin_ms
    ]
    magnitudes = []
    for row in rows:
        move = dict_or_empty(row.get("move", {}))
        magnitudes.append(vector_length(move.get("forward", 0), move.get("side", 0)))
    yaw_deltas = [
        abs(float(dict_or_empty(row.get("diagnostics", {})).get("yaw_delta", 0.0)))
        for row in rows
        if "yaw_delta" in dict_or_empty(row.get("diagnostics", {}))
    ]
    route_states = [
        row.get("route_state", {})
        for row in rows
        if isinstance(row.get("route_state", {}), dict) and row.get("route_state")
    ]
    jump_count = sum(1 for row in rows if int_value(row.get("buttons", 0)) & 2)
    backward_count = sum(1 for row in rows if bool(dict_or_empty(row.get("diagnostics", {})).get("backward", False)))
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
        "route_state": summarize_route_states(route_states),
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
        if not isinstance(entity, dict):
            continue
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
        if not isinstance(row, dict):
            continue
        command_count += 1
        for key in row.keys():
            if key in ROUTE_STATE_KEYS:
                route_state_keys.add(key)
        diagnostics = row.get("diagnostics", {})
        if isinstance(diagnostics, dict):
            diagnostic_keys.update(str(key) for key in diagnostics.keys())
            route_state_keys.update(str(key) for key in diagnostics.keys() if str(key) in ROUTE_STATE_KEYS)
        route_state = row.get("route_state", {})
        if isinstance(route_state, dict):
            route_state_keys.update(str(key) for key in route_state.keys() if str(key) in ROUTE_STATE_KEYS)

    entities = load_map_entities(analysis)
    notes = [
        "Artifacts expose position traces, sampled final commands, view yaw, route yaw, and backward-command diagnostics when command logging is enabled.",
    ]
    if route_state_keys:
        notes.append(
            "Command rows also expose route-state context such as marker ids, goal entity/marker ids, path/bot state flags, blocked state, and route dir_speed."
        )
    else:
        notes.append(
            "They do not expose Frogbot route node, next waypoint, target entity, obstruction, or route primitive state."
        )
    return {
        "position_trace_available": True,
        "command_trace_available": command_count > 0,
        "command_count": command_count,
        "command_diagnostic_keys": sorted(diagnostic_keys),
        "route_direction_available": "route_yaw" in diagnostic_keys,
        "route_node_or_goal_state_available": bool(route_state_keys),
        "route_state_keys": sorted(route_state_keys),
        "map_entity_locations_available": bool(entities),
        "notes": notes,
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

    warnings: list[str] = []
    analysis = read_artifact_json(run_dir / "analysis.json", artifact_name="analysis.json", warnings=warnings)
    commands = read_artifact_json(
        run_dir / "moveprobe-commands.json",
        artifact_name="moveprobe-commands.json",
        warnings=warnings,
    )
    run_env = read_run_env(run_dir)
    players, samples_by_slot, trace_meta = load_position_trace(
        run_dir / "events.txt",
        run_dir,
        analysis=analysis,
        warnings=warnings,
    )
    samples_by_slot = filtered_named_samples(
        players,
        samples_by_slot,
        match_duration_ms=trace_meta["match_duration_clamp_ms"],
    )
    clock_overlap = summarize_clock_overlap(samples_by_slot, commands, margin_ms=args.command_margin_ms)
    trace_meta["clock_overlap"] = clock_overlap
    if clock_overlap.get("status") == "no_clock_overlap":
        warnings.append(
            "Command timestamps do not overlap filtered position-sample timestamps; low-speed windows may show no sampled commands because artifact clocks use different epochs."
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
        "This diagnosis used MVD position samples plus sampled final moveprobe commands; no new controller heuristic was added.",
        "The artifacts can show where low-speed spans happen and whether strong commands were sampled nearby.",
    ]
    if not route_state_available:
        interpretation.append(
            "Current artifacts cannot attribute those spans to a Frogbot route node, next waypoint, obstruction, or route primitive."
        )
    else:
        interpretation.append(
            "Route-state logging can now tag low-speed spans with marker, goal, path-state, bot-state, blocked, and dir_speed context."
        )
    if windows_with_strong_commands:
        interpretation.append(
            f"{windows_with_strong_commands} of {total_top_windows} analyzed low-speed windows show low speed despite average sampled horizontal command >= {args.strong_command:.0f}."
        )
    if clock_overlap.get("status") == "no_clock_overlap":
        interpretation.append(
            "Command/sample clock overlap failed, so command-window joins should be treated as a clock sanity failure rather than movement evidence."
        )
    next_goal = (
        "S6c should use route-state-tagged low-speed windows to identify repeated marker/path-state/blocked patterns "
        "before changing mode 7 or adding another movement-command heuristic."
        if route_state_available
        else "S6b should add minimal route-state logging around the Frogbot command boundary "
        "so low-speed windows can be tagged with route node/goal/obstruction context before "
        "changing the movement controller again."
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
        "warnings": warnings,
        "capabilities": capabilities,
        "players": player_summaries,
        "interpretation": interpretation,
        "next_goal": next_goal,
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


def route_state_label(route_state: dict) -> str:
    if not route_state or not route_state.get("sample_count"):
        return ""
    linked = route_state.get("linked_marker_values", [])
    touch = route_state.get("touch_marker_values", [])
    goal = route_state.get("goal_marker_values", [])
    path = route_state.get("path_state_values", [])
    return f"`L{linked} T{touch} G{goal} P{path}`"


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
    clock_overlap = diagnosis.get("trace", {}).get("clock_overlap", {})
    if isinstance(clock_overlap, dict) and clock_overlap:
        lines.extend(
            [
                f"- Command/sample clock overlap: `{clock_overlap.get('status', '')}` "
                f"(overlap `{clock_overlap.get('overlap_ms', 0)}` ms, margin `{clock_overlap.get('margin_ms', '')}` ms).",
            ]
        )
    warnings = diagnosis.get("warnings", [])
    if warnings:
        lines.extend(["", "## Warnings", ""])
        for warning in warnings:
            lines.append(f"- {warning}")
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
            "| Player | Rank | Window | Low ms | Avg low | From | To | Cmds | Avg cmd | Strong | Jump | Abs delta p90 | Route | Blocked | Hint |",
            "|---|---:|---|---:|---:|---|---|---:|---:|---:|---:|---:|---|---:|---|",
        ]
    )
    for player in diagnosis.get("players", []):
        for window in player.get("top_windows", []):
            command = window.get("command_summary", {})
            route_state = command.get("route_state", {}) if isinstance(command.get("route_state"), dict) else {}
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
                f"{route_state_label(route_state)} | "
                f"{pct(route_state.get('blocked_ratio'))} | "
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
    parser.add_argument(
        "--run-id",
        required=True,
        help="Run id under --artifacts-root, or an explicit existing run directory to read by design.",
    )
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
