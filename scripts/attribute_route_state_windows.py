#!/usr/bin/env python3
"""Attribute S6 route-state windows against KTX/Frogbot route definitions."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable


SCHEMA = "komodobots.route_state_attribution.v2"
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARTIFACT_ROOT = REPO_ROOT / "artifacts" / "lab-runs"
DEFAULT_DIAGNOSIS = REPO_ROOT / "experiments" / "ktx_moveprobe" / "evidence" / "route-state-s6b-diagnosis.json"
DEFAULT_KTX_ROOT = REPO_ROOT.parent / "engine" / "ktx"
DEFAULT_BOT_MAP_ROOT = DEFAULT_KTX_ROOT / "resources" / "example-configs" / "ktx" / "bots" / "maps"
RUN_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")

PATH_FLAG_SPECS = (
    (1 << 1, "WATERJUMP_"),
    (1 << 8, "DM6_DOOR"),
    (1 << 9, "ROCKET_JUMP"),
    (1 << 10, "JUMP_LEDGE"),
    (1 << 11, "VERTICAL_PLATFORM"),
    (1 << 12, "BOTPATH_DOOR"),
    (1 << 13, "BOTPATH_DOOR_CLOSED"),
    (1 << 14, "REVERSIBLE"),
    (1 << 15, "WATER_PATH"),
    (1 << 17, "DELIBERATE_AIR"),
    (1 << 18, "WAIT_GROUND"),
    (1 << 19, "STUCK_PATH"),
    (1 << 20, "AIR_ACCELERATION"),
    (1 << 21, "NO_DODGE"),
    (1 << 22, "DELIBERATE_BACKUP"),
    (1 << 23, "BOTPATH_CURLJUMP_HINT"),
    (1 << 24, "BOTPATH_FULL_AIRCONTROL"),
    (1 << 25, "BOTPATH_RJ_IN_PROGRESS"),
)

BOT_STATE_SPECS = (
    (1, "CAMPBOT"),
    (2, "SHOT_FOR_LUCK"),
    (4, "BACKPACK_IS_UNREACHABLE"),
    (32, "NOTARGET_ENEMY"),
    (128, "AWARE_SURROUNDINGS"),
    (1024, "HURT_SELF"),
    (4096, "RUNAWAY"),
    (8192, "WAIT"),
)

PLAYER_FLAG_SPECS = (
    (1, "FL_FLY"),
    (2, "FL_SWIM"),
    (8, "FL_CLIENT"),
    (16, "FL_INWATER"),
    (32, "FL_MONSTER"),
    (512, "FL_ONGROUND"),
    (1024, "FL_PARTIALGROUND"),
    (2048, "FL_WATERJUMP"),
)

CONTENT_NAMES = {
    -1: "CONTENT_EMPTY",
    -2: "CONTENT_SOLID",
    -3: "CONTENT_WATER",
    -4: "CONTENT_SLIME",
    -5: "CONTENT_LAVA",
    -6: "CONTENT_SKY",
}

SWIM_ARROW_NAMES = {
    0: "none",
    16: "UP",
    32: "DOWN",
}

EXTERNAL_PATH_FLAG_CHARS = {
    "w": "WATERJUMP_",
    "6": "DM6_DOOR",
    "r": "ROCKET_JUMP",
    "j": "JUMP_LEDGE",
    "v": "VERTICAL_PLATFORM",
    "a": "BOTPATH_CURLJUMP_HINT",
}


def portable_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        pass
    try:
        return f"../{resolved.relative_to(REPO_ROOT.parent).as_posix()}"
    except ValueError:
        return resolved.as_posix()


def read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        loaded = json.load(handle)
    if not isinstance(loaded, dict):
        raise ValueError(f"{path} did not contain a JSON object")
    return loaded


def round_float(value: object, digits: int = 3) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(number):
        return 0.0
    return round(number, digits)


def coerce_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def decode_flags(value: object, specs: Iterable[tuple[int, str]]) -> dict[str, object]:
    try:
        flags = int(value)
    except (TypeError, ValueError):
        flags = 0
    decoded = [{"bit": bit, "name": name} for bit, name in specs if flags & bit]
    known_mask = 0
    for bit, _name in specs:
        known_mask |= bit
    return {
        "value": flags,
        "names": [row["name"] for row in decoded],
        "bits": decoded,
        "unknown_mask": flags & ~known_mask,
    }


def decode_external_flag_string(value: str) -> list[str]:
    return [EXTERNAL_PATH_FLAG_CHARS[char] for char in value if char in EXTERNAL_PATH_FLAG_CHARS]


def compact_values(values: Iterable[object]) -> list[object]:
    return sorted(set(values))


def command_time_ms(row: dict) -> int | None:
    try:
        return int(round(float(row.get("time_s")) * 1000.0))
    except (TypeError, ValueError):
        return None


def parse_bot_map(path: Path) -> dict[str, object]:
    # Frogbot logs marker->fb.index + 1. The .bot route commands use the same
    # 1-based ids; CreateMarker gives static origins for only a subset because
    # item/runtime markers can be referenced later by SetZone/SetMarkerPath.
    markers: dict[int, dict[str, object]] = {}
    paths: dict[tuple[int, int], dict[str, object]] = {}
    marker_id = 0
    referenced_markers: set[int] = set()

    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("//"):
            continue
        parts = line.split()
        command = parts[0]
        try:
            if command == "CreateMarker" and len(parts) >= 4:
                marker_id += 1
                markers.setdefault(marker_id, {"id": marker_id})["origin"] = [
                    round_float(parts[1], 1),
                    round_float(parts[2], 1),
                    round_float(parts[3], 1),
                ]
                markers[marker_id]["source"] = "CreateMarker"
            elif command == "SetGoal" and len(parts) >= 3:
                marker = int(parts[1])
                referenced_markers.add(marker)
                markers.setdefault(marker, {"id": marker})["goal"] = int(parts[2])
            elif command == "SetZone" and len(parts) >= 3:
                marker = int(parts[1])
                referenced_markers.add(marker)
                markers.setdefault(marker, {"id": marker})["zone"] = int(parts[2])
            elif command == "SetMarkerPath" and len(parts) >= 4:
                source = int(parts[1])
                path_index = int(parts[2])
                target = int(parts[3])
                referenced_markers.update((source, target))
                path_row = paths.setdefault(
                    (source, target),
                    {"source": source, "target": target, "path_indexes": [], "explicit_flags": []},
                )
                path_row["path_indexes"].append(path_index)
            elif command == "SetMarkerPathFlags" and len(parts) >= 4:
                source = int(parts[1])
                path_index = int(parts[2])
                flag_names = decode_external_flag_string(parts[3])
                for row in paths.values():
                    if row["source"] == source and path_index in row["path_indexes"]:
                        row["explicit_flags"] = flag_names
                        break
        except ValueError:
            continue

    return {
        "path": portable_path(path),
        "marker_count": len(markers),
        "static_create_marker_count": marker_id,
        "referenced_marker_count": len(referenced_markers),
        "markers_without_static_origin": sorted(marker for marker in referenced_markers if marker not in markers or not markers[marker].get("origin")),
        "marker_index_invariant": (
            "Attribution assumes logged marker->fb.index + 1 matches the .bot file's 1-based marker ids. "
            "CreateMarker ids are assigned by file order; item/runtime marker ids can be referenced by route commands without static origins."
        ),
        "markers": markers,
        "paths": paths,
    }


def marker_summary(marker_id: int, bot_map: dict[str, object]) -> dict[str, object]:
    marker = bot_map.get("markers", {}).get(marker_id, {}) if marker_id > 0 else {}
    return {
        "id": marker_id,
        "zone": marker.get("zone", ""),
        "goal": marker.get("goal", ""),
        "origin": marker.get("origin", []),
        "has_static_origin": bool(marker.get("origin")),
    }


def path_between(source: int, target: int, bot_map: dict[str, object]) -> dict[str, object]:
    paths = bot_map.get("paths", {})
    row = paths.get((source, target), {}) if isinstance(paths, dict) else {}
    if not row:
        return {"source": source, "target": target, "defined_in_bot_map": False}
    return {
        "source": source,
        "target": target,
        "defined_in_bot_map": True,
        "path_indexes": row.get("path_indexes", []),
        "explicit_flags": row.get("explicit_flags", []),
    }


def command_rows_for_window(commands: dict, player_name: str, start_ms: int, end_ms: int, margin_ms: int) -> list[dict]:
    rows = []
    for row in commands.get("commands", []):
        if not isinstance(row, dict) or str(row.get("name", "")).strip() != player_name:
            continue
        time_ms = command_time_ms(row)
        if time_ms is None:
            continue
        if start_ms - margin_ms <= time_ms <= end_ms + margin_ms:
            rows.append(row)
    return sorted(rows, key=lambda row: command_time_ms(row) or -1)


def route_sample(row: dict, bot_map: dict[str, object]) -> dict[str, object]:
    state = row.get("route_state", {}) if isinstance(row.get("route_state"), dict) else {}
    linked = int(state.get("linked_marker", -1))
    touch = int(state.get("touch_marker", -1))
    goal_marker = int(state.get("goal_marker", -1))
    path_state = int(state.get("path_state", 0))
    bot_state = int(state.get("bot_state", 0))
    return {
        "time_ms": command_time_ms(row),
        "linked_marker": linked,
        "touch_marker": touch,
        "goal_ed": int(state.get("goal_ed", -1)),
        "goal_marker": goal_marker,
        "path_state": decode_flags(path_state, PATH_FLAG_SPECS),
        "bot_state": decode_flags(bot_state, BOT_STATE_SPECS),
        "blocked": bool(state.get("blocked", False)),
        "dir_speed": round_float(state.get("dir_speed", 0.0), 3),
        "touch_to_link_path": path_between(touch, linked, bot_map),
        "linked_marker_info": marker_summary(linked, bot_map),
        "touch_marker_info": marker_summary(touch, bot_map),
        "goal_marker_info": marker_summary(goal_marker, bot_map),
        "water_state": water_sample(row),
    }


def content_name(value: int) -> str:
    return CONTENT_NAMES.get(value, f"unknown:{value}")


def swim_arrow_name(value: int) -> str:
    return SWIM_ARROW_NAMES.get(value, f"unknown:{value}")


def vector_sample(state: dict[str, object], key: str) -> dict[str, float]:
    vector = state.get(key, {}) if isinstance(state.get(key), dict) else {}
    return {
        "x": round_float(vector.get("x", 0.0), 3),
        "y": round_float(vector.get("y", 0.0), 3),
        "z": round_float(vector.get("z", 0.0), 3),
    }


def water_sample(row: dict) -> dict[str, object]:
    state = row.get("water_state", {}) if isinstance(row.get("water_state"), dict) else {}
    if not state:
        return {"present": False}
    watertype = coerce_int(state.get("watertype", 0))
    swim_arrow = coerce_int(state.get("swim_arrow", 0))
    flags = coerce_int(state.get("flags", 0))
    return {
        "present": True,
        "waterlevel": coerce_int(state.get("waterlevel", 0)),
        "watertype": {"value": watertype, "name": content_name(watertype)},
        "flags": decode_flags(flags, PLAYER_FLAG_SPECS),
        "swim_arrow": {"value": swim_arrow, "name": swim_arrow_name(swim_arrow)},
        "emitted_upmove": round_float(state.get("emitted_upmove", 0.0), 1),
        "velocity": vector_sample(state, "velocity"),
        "dir_move": vector_sample(state, "dir_move"),
    }


def summarize_water_samples(samples: list[dict]) -> dict[str, object]:
    water_samples = [
        sample.get("water_state", {})
        for sample in samples
        if isinstance(sample.get("water_state", {}), dict) and sample.get("water_state", {}).get("present")
    ]
    if not water_samples:
        return {"sample_count": 0}

    waterlevels = [coerce_int(sample.get("waterlevel", 0)) for sample in water_samples]
    swim_arrows = [coerce_int(sample.get("swim_arrow", {}).get("value", 0)) for sample in water_samples]
    emitted_upmoves = [round_float(sample.get("emitted_upmove", 0.0), 1) for sample in water_samples]
    velocity_z = [round_float(sample.get("velocity", {}).get("z", 0.0), 1) for sample in water_samples]
    dir_move_z = [round_float(sample.get("dir_move", {}).get("z", 0.0), 3) for sample in water_samples]
    sample_count = len(water_samples)
    return {
        "sample_count": sample_count,
        "waterlevel_values": compact_values(waterlevels),
        "watertype_values": compact_values(coerce_int(sample.get("watertype", {}).get("value", 0)) for sample in water_samples),
        "watertype_names": compact_values(str(sample.get("watertype", {}).get("name", "")) for sample in water_samples),
        "player_flag_names": compact_values(
            name for sample in water_samples for name in sample.get("flags", {}).get("names", [])
        ),
        "swim_arrow_values": compact_values(swim_arrows),
        "swim_arrow_names": compact_values(str(sample.get("swim_arrow", {}).get("name", "")) for sample in water_samples),
        "emitted_upmove_values": compact_values(emitted_upmoves),
        "waterlevel_gt1_ratio": round_float(sum(1 for value in waterlevels if value > 1) / sample_count),
        "waterlevel_gt2_ratio": round_float(sum(1 for value in waterlevels if value > 2) / sample_count),
        "swim_arrow_nonzero_ratio": round_float(sum(1 for value in swim_arrows if value != 0) / sample_count),
        "emitted_upmove_nonzero_ratio": round_float(
            sum(1 for value in emitted_upmoves if abs(value) > 0.01) / sample_count
        ),
        "velocity_z_avg": round_float(sum(velocity_z) / len(velocity_z) if velocity_z else 0.0, 1),
        "velocity_z_values": compact_values(velocity_z),
        "dir_move_z_avg": round_float(sum(dir_move_z) / len(dir_move_z) if dir_move_z else 0.0),
        "dir_move_z_values": compact_values(dir_move_z),
    }


def default_commands_path(run_id: str) -> Path:
    if not RUN_ID_RE.fullmatch(run_id):
        raise ValueError(f"Diagnosis run_id is not a safe lab run id: {run_id!r}")
    return DEFAULT_ARTIFACT_ROOT / run_id / "moveprobe-commands.json"


def classify_window(samples: list[dict]) -> dict[str, object]:
    path_names = {name for sample in samples for name in sample["path_state"]["names"]}
    blocked = any(sample["blocked"] for sample in samples)
    dir_speeds = [float(sample["dir_speed"]) for sample in samples]
    low_dir_ratio = sum(1 for value in dir_speeds if value < 0.25) / len(dir_speeds) if dir_speeds else 0.0
    water_summary = summarize_water_samples(samples)
    if "WATER_PATH" in path_names and not blocked and "STUCK_PATH" not in path_names:
        classification = "water_path_without_obstruction"
    elif blocked or "STUCK_PATH" in path_names:
        classification = "blocked_or_stuck_path"
    else:
        classification = "route_state_unresolved"
    notes = []
    if "WATER_PATH" in path_names:
        notes.append("Path state includes WATER_PATH, which KTX route_calc sets when either endpoint marker is in water.")
    if not blocked and "STUCK_PATH" not in path_names:
        notes.append("No sampled blocked/STUCK_PATH signal was present.")
    if low_dir_ratio:
        notes.append(f"{low_dir_ratio:.1%} of sampled commands had native dir_speed below 0.25 before the probe normalized direction.")
    if water_summary.get("sample_count"):
        if water_summary.get("waterlevel_gt2_ratio") == 0:
            notes.append("No sampled command was deep water (waterlevel > 2), so BotWaterMove swim_arrow may be inactive.")
        if water_summary.get("swim_arrow_nonzero_ratio") == 0:
            notes.append("No sampled swim_arrow intent was active.")
        if water_summary.get("emitted_upmove_nonzero_ratio") == 0:
            notes.append("No sampled emitted upmove was active.")
    return {
        "classification": classification,
        "contains_water_path": "WATER_PATH" in path_names,
        "contains_stuck_path": "STUCK_PATH" in path_names,
        "blocked_sample_count": sum(1 for sample in samples if sample["blocked"]),
        "low_dir_speed_ratio": round_float(low_dir_ratio),
        "water_state": water_summary,
        "notes": notes,
    }


def location_label(window: dict) -> str:
    nearest = window.get("nearest_start", [])
    if isinstance(nearest, list) and nearest and isinstance(nearest[0], dict):
        return str(nearest[0].get("loc") or nearest[0].get("name") or "")
    return ""


def build_window_attribution(player: dict, window: dict, commands: dict, bot_map: dict[str, object]) -> dict[str, object]:
    command_summary = window.get("command_summary", {}) if isinstance(window.get("command_summary"), dict) else {}
    margin_ms = int(command_summary.get("sample_window_ms", {}).get("margin_ms", 150))
    rows = command_rows_for_window(
        commands,
        str(player.get("name", "")).strip(),
        int(window.get("start_ms", 0)),
        int(window.get("end_ms", 0)),
        margin_ms,
    )
    samples = [route_sample(row, bot_map) for row in rows if isinstance(row.get("route_state"), dict)]
    path_values = compact_values(sample["path_state"]["value"] for sample in samples)
    dir_speeds = [float(sample["dir_speed"]) for sample in samples]
    water_summary = summarize_water_samples(samples)
    return {
        "player": player.get("name", ""),
        "rank": window.get("rank", ""),
        "window_ms": {"start_ms": window.get("start_ms"), "end_ms": window.get("end_ms")},
        "location": location_label(window),
        "avg_low_speed_qu_per_s": window.get("avg_low_speed_qu_per_s", ""),
        "avg_horizontal_command": command_summary.get("avg_horizontal_command", ""),
        "sample_count": len(samples),
        "linked_marker_values": compact_values(sample["linked_marker"] for sample in samples),
        "touch_marker_values": compact_values(sample["touch_marker"] for sample in samples),
        "goal_marker_values": compact_values(sample["goal_marker"] for sample in samples),
        "path_state_values": [
            {"value": value, "names": decode_flags(value, PATH_FLAG_SPECS)["names"]} for value in path_values
        ],
        "bot_state_names": compact_values(name for sample in samples for name in sample["bot_state"]["names"]),
        "blocked_ratio": round_float(sum(1 for sample in samples if sample["blocked"]) / len(samples) if samples else 0.0),
        "dir_speed_avg": round_float(sum(dir_speeds) / len(dir_speeds) if dir_speeds else 0.0),
        "dir_speed_min": round_float(min(dir_speeds) if dir_speeds else 0.0),
        "dir_speed_max": round_float(max(dir_speeds) if dir_speeds else 0.0),
        "water_state": water_summary,
        "route_samples": samples,
        "attribution": classify_window(samples),
    }


def group_patterns(windows: list[dict]) -> list[dict[str, object]]:
    grouped: dict[tuple[object, ...], list[dict]] = defaultdict(list)
    for window in windows:
        key = (
            window["player"],
            tuple(value for value in window["linked_marker_values"] if isinstance(value, int) and value > 0),
            tuple(value for value in window["goal_marker_values"] if isinstance(value, int) and value > 0),
            bool(window["attribution"]["contains_water_path"]),
            bool(window["attribution"]["contains_stuck_path"]),
        )
        grouped[key].append(window)

    patterns = []
    for key, rows in grouped.items():
        _player, linked, goal, contains_water, contains_stuck = key
        sample_count = sum(int(row["sample_count"]) for row in rows)
        dir_values = [
            float(sample["dir_speed"])
            for row in rows
            for sample in row.get("route_samples", [])
        ]
        route_samples = [
            sample
            for row in rows
            for sample in row.get("route_samples", [])
            if isinstance(sample, dict)
        ]
        water_summary = summarize_water_samples(route_samples)
        avg_commands = [float(row.get("avg_horizontal_command") or 0.0) for row in rows]
        blocked_sample_count = sum(
            1
            for row in rows
            for sample in row.get("route_samples", [])
            if sample.get("blocked")
        )
        low_dir_speed_ratio = sum(1 for value in dir_values if value < 0.25) / len(dir_values) if dir_values else 0.0
        notes = []
        if contains_water:
            notes.append("Path state includes WATER_PATH, which KTX route_calc sets when either endpoint marker is in water.")
        if contains_stuck or blocked_sample_count:
            notes.append("At least one sample carried blocked/STUCK_PATH state.")
        else:
            notes.append("No sampled blocked/STUCK_PATH signal was present.")
        if low_dir_speed_ratio:
            notes.append(
                f"{low_dir_speed_ratio:.1%} of grouped command samples had native dir_speed below 0.25 before the probe normalized direction."
            )
        if water_summary.get("sample_count"):
            if water_summary.get("waterlevel_gt2_ratio") == 0:
                notes.append("No grouped command sample was deep water (waterlevel > 2).")
            if water_summary.get("swim_arrow_nonzero_ratio") == 0:
                notes.append("No grouped command sample had swim_arrow intent.")
            if water_summary.get("emitted_upmove_nonzero_ratio") == 0:
                notes.append("No grouped command sample emitted nonzero upmove.")
        patterns.append(
            {
                "player": rows[0]["player"],
                "linked_marker_values": list(linked),
                "goal_marker_values": list(goal),
                "contains_water_path": contains_water,
                "contains_stuck_path": contains_stuck,
                "window_count": len(rows),
                "window_ranks": [row["rank"] for row in rows],
                "locations": compact_values(row["location"] for row in rows if row["location"]),
                "sample_count": sample_count,
                "blocked_ratio": round_float(
                    blocked_sample_count / sample_count if sample_count else 0.0
                ),
                "low_dir_speed_ratio": round_float(low_dir_speed_ratio),
                "dir_speed_avg": round_float(sum(dir_values) / len(dir_values) if dir_values else 0.0),
                "dir_speed_min": round_float(min(dir_values) if dir_values else 0.0),
                "water_state": water_summary,
                "avg_horizontal_command_avg": round_float(
                    sum(avg_commands) / len(avg_commands) if avg_commands else 0.0,
                    1,
                ),
                "classification": rows[0]["attribution"]["classification"],
                "notes": notes,
            }
        )
    return sorted(patterns, key=lambda row: (row["window_count"], row["sample_count"]), reverse=True)


def edge_label(edge: dict[str, object]) -> str:
    if not edge.get("defined_in_bot_map"):
        return f"{edge.get('source')}->{edge.get('target')} missing"
    flags = edge.get("explicit_flags", [])
    flag_label = f" flags={flags}" if flags else ""
    return f"{edge.get('source')}->{edge.get('target')} idx={edge.get('path_indexes', [])}{flag_label}"


def unique_edge_labels(window: dict[str, object]) -> list[str]:
    labels = []
    seen = set()
    for sample in window.get("route_samples", []):
        if not isinstance(sample, dict):
            continue
        edge = sample.get("touch_to_link_path", {})
        if not isinstance(edge, dict):
            continue
        if int(edge.get("source", -1)) <= 0 or int(edge.get("target", -1)) <= 0:
            continue
        label = edge_label(edge)
        if label in seen:
            continue
        seen.add(label)
        labels.append(label)
    return labels


def build_attribution(args: argparse.Namespace) -> dict[str, object]:
    diagnosis = read_json(args.diagnosis_json)
    run_id = str(diagnosis.get("run", {}).get("run_id", ""))
    commands_path = args.commands_json or default_commands_path(run_id)
    commands = read_json(commands_path)
    bot_map = parse_bot_map(args.bot_map)
    run = dict(diagnosis.get("run", {})) if isinstance(diagnosis.get("run", {}), dict) else {}
    if run.get("run_dir"):
        run["run_dir"] = portable_path(Path(str(run["run_dir"])))

    windows = []
    for player in diagnosis.get("players", []):
        if not isinstance(player, dict):
            continue
        for window in player.get("top_windows", []):
            if isinstance(window, dict):
                windows.append(build_window_attribution(player, window, commands, bot_map))

    patterns = group_patterns(windows)
    interpretation = [
        "This attribution is diagnostic-only; it decodes sampled route and water/swim state without adding a new movement mode.",
        "The repeated water.LG low-speed pattern decodes path_state 32768 as WATER_PATH, not STUCK_PATH.",
        "The repeated water-path windows have blocked=0, so obstruction recovery is not the current explanation.",
        "When water_state samples are present, waterlevel/swim_arrow/upmove/velocity/dir_move context can distinguish shallow-water edge handling from active swim intent.",
    ]
    next_goal = (
        "S6e should use the S6d water/swim evidence to choose the smallest targeted fix: swim/upmove handling, route-edge "
        "geometry diagnosis, or a repeated-run check if the water-path pattern is not reproduced."
    )
    return {
        "schema": SCHEMA,
        "stage": args.stage,
        "sources": {
            "diagnosis_json": portable_path(args.diagnosis_json),
            "commands_json": portable_path(commands_path),
            "bot_map": portable_path(args.bot_map),
            "flag_definitions": portable_path(DEFAULT_KTX_ROOT / "include" / "fb_globals.h"),
            "player_flag_definitions": portable_path(DEFAULT_KTX_ROOT / "include" / "g_consts.h"),
            "water_path_assignment": portable_path(DEFAULT_KTX_ROOT / "src" / "route_calc.c"),
            "swim_arrow_assignment": portable_path(DEFAULT_KTX_ROOT / "src" / "bot_botwater.c"),
            "dir_speed_assignment": portable_path(DEFAULT_KTX_ROOT / "src" / "bot_movement.c"),
        },
        "marker_index_invariant": bot_map.get("marker_index_invariant", ""),
        "bot_map_summary": {
            "static_create_marker_count": bot_map.get("static_create_marker_count", 0),
            "referenced_marker_count": bot_map.get("referenced_marker_count", 0),
            "markers_without_static_origin_count": len(bot_map.get("markers_without_static_origin", [])),
        },
        "run": run,
        "flag_decoding": {
            "path_state_32768": decode_flags(32768, PATH_FLAG_SPECS),
            "stuck_path": decode_flags(1 << 19, PATH_FLAG_SPECS),
            "bot_state_128": decode_flags(128, BOT_STATE_SPECS),
        },
        "patterns": patterns,
        "windows": windows,
        "interpretation": interpretation,
        "next_goal": next_goal,
    }


def pct(value: object) -> str:
    try:
        return f"{float(value) * 100.0:.1f}%"
    except (TypeError, ValueError):
        return ""


def water_summary_label(summary: dict[str, object], key: str) -> object:
    if not isinstance(summary, dict) or int(summary.get("sample_count", 0)) <= 0:
        return ""
    return summary.get(key, "")


def write_markdown(attribution: dict[str, object], output_path: Path) -> None:
    lines = [
        f"# Route-State Attribution {attribution.get('stage', '')}",
        "",
        "## Scope",
        "",
        f"- Run: `{attribution.get('run', {}).get('run_id', '')}`",
        f"- Map: `{attribution.get('run', {}).get('map', '')}` / `{attribution.get('run', {}).get('map_title', '')}`",
        "- Controller change: `none`",
        f"- Marker index invariant: {attribution.get('marker_index_invariant', '')}",
        "",
        "## Decoded Flags",
        "",
        f"- `32768` -> `{', '.join(attribution.get('flag_decoding', {}).get('path_state_32768', {}).get('names', []))}`",
        f"- `524288` -> `{', '.join(attribution.get('flag_decoding', {}).get('stuck_path', {}).get('names', []))}`",
        f"- bot state `128` -> `{', '.join(attribution.get('flag_decoding', {}).get('bot_state_128', {}).get('names', []))}`",
        "",
        "## Repeated Patterns",
        "",
        "| Player | Windows | Locations | Linked | Goal | Water path | Water levels | Swim | Upmove | Dir z avg | Blocked | Low dir | Dir speed avg | Avg cmd | Classification |",
        "|---|---:|---|---|---|---:|---|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for pattern in attribution.get("patterns", []):
        water = pattern.get("water_state", {}) if isinstance(pattern.get("water_state"), dict) else {}
        lines.append(
            "| "
            f"`{pattern.get('player', '')}` | "
            f"`{pattern.get('window_count', 0)}` | "
            f"`{pattern.get('locations', [])}` | "
            f"`{pattern.get('linked_marker_values', [])}` | "
            f"`{pattern.get('goal_marker_values', [])}` | "
            f"{'yes' if pattern.get('contains_water_path') else 'no'} | "
            f"`{water_summary_label(water, 'waterlevel_values')}` | "
            f"`{water_summary_label(water, 'swim_arrow_names')}` | "
            f"{pct(water.get('emitted_upmove_nonzero_ratio')) if water else ''} | "
            f"{water_summary_label(water, 'dir_move_z_avg')} | "
            f"{pct(pattern.get('blocked_ratio'))} | "
            f"{pct(pattern.get('low_dir_speed_ratio'))} | "
            f"{pattern.get('dir_speed_avg', 0)} | "
            f"{pattern.get('avg_horizontal_command_avg', 0)} | "
            f"`{pattern.get('classification', '')}` |"
        )

    lines.extend(
        [
            "",
            "## Window Attribution",
            "",
            "| Player | Rank | Window | Location | Avg cmd | Linked | Touch | Goal | Path state | Water levels | Swim | Upmove | Dir z avg | Vel z avg | Blocked | Dir speed avg | Classification |",
            "|---|---:|---|---|---:|---|---|---|---|---|---|---:|---:|---:|---:|---:|---|",
        ]
    )
    for window in attribution.get("windows", []):
        states = [
            f"{row.get('value')}:{','.join(row.get('names', [])) or 'none'}"
            for row in window.get("path_state_values", [])
        ]
        water = window.get("water_state", {}) if isinstance(window.get("water_state"), dict) else {}
        lines.append(
            "| "
            f"`{window.get('player', '')}` | "
            f"`{window.get('rank', '')}` | "
            f"`{window.get('window_ms', {}).get('start_ms', '')}-{window.get('window_ms', {}).get('end_ms', '')}` | "
            f"`{window.get('location', '')}` | "
            f"{window.get('avg_horizontal_command', '')} | "
            f"`{window.get('linked_marker_values', [])}` | "
            f"`{window.get('touch_marker_values', [])}` | "
            f"`{window.get('goal_marker_values', [])}` | "
            f"`{states}` | "
            f"`{water_summary_label(water, 'waterlevel_values')}` | "
            f"`{water_summary_label(water, 'swim_arrow_names')}` | "
            f"{pct(water.get('emitted_upmove_nonzero_ratio')) if water else ''} | "
            f"{water_summary_label(water, 'dir_move_z_avg')} | "
            f"{water_summary_label(water, 'velocity_z_avg')} | "
            f"{pct(window.get('blocked_ratio'))} | "
            f"{window.get('dir_speed_avg', 0)} | "
            f"`{window.get('attribution', {}).get('classification', '')}` |"
        )

    lines.extend(
        [
            "",
            "## Map Edge Evidence",
            "",
            "| Player | Rank | Touch-to-linked edges from `.bot` map |",
            "|---|---:|---|",
        ]
    )
    for window in attribution.get("windows", []):
        lines.append(
            "| "
            f"`{window.get('player', '')}` | "
            f"`{window.get('rank', '')}` | "
            f"`{unique_edge_labels(window)}` |"
        )

    lines.extend(["", "## Interpretation", ""])
    for note in attribution.get("interpretation", []):
        lines.append(f"- {note}")
    lines.extend(["", "## Next Goal", "", f"- {attribution.get('next_goal', '')}", ""])
    output_path.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Attribute S6 route-state windows against Frogbot source/map data.")
    parser.add_argument("--stage", default="s6c-route-attribution", help="Stage label for outputs.")
    parser.add_argument("--diagnosis-json", type=Path, default=DEFAULT_DIAGNOSIS, help="S6 diagnosis JSON.")
    parser.add_argument("--commands-json", type=Path, default=None, help="Optional moveprobe-commands.json path.")
    parser.add_argument("--bot-map", type=Path, default=DEFAULT_BOT_MAP_ROOT / "dm3.bot", help="Frogbot .bot map file.")
    parser.add_argument("--output-json", type=Path, required=True, help="Output JSON path.")
    parser.add_argument("--output-md", type=Path, required=True, help="Output Markdown path.")
    return parser.parse_args(list(argv))


def main(argv: Iterable[str] = sys.argv[1:]) -> int:
    args = parse_args(argv)
    attribution = build_attribution(args)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(attribution, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_markdown(attribution, args.output_md)
    print(f"Wrote route-state attribution: {args.output_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
