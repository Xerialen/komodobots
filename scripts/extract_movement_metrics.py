#!/usr/bin/env python3
"""Derive first-pass movement metrics from qw-analyze event output.

The input is the line-delimited JSON produced by:

    qw-analyze-v20 -format events demo.mvd

Player movement is derived from kind:5 events, which carry player slot, origin,
and timestamp. The extractor intentionally ignores unnamed slots by default so
the control client shim does not pollute bot movement numbers.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Iterable, TypedDict


SCHEMA = "komodobots.movement_metrics.v2"
DEFAULT_STATIONARY_SPEED = 10.0
DEFAULT_LOW_SPEED = 100.0
DEFAULT_HIGH_SPEED = 400.0
DEFAULT_TELEPORT_SPEED = 2500.0
DEFAULT_MAXSPEED = 320.0
DEFAULT_VERTICAL_EPSILON = 0.25
DEFAULT_VERTICAL_SPEED = 40.0
DEFAULT_AIRBORNE_MIN_DURATION_MS = 120
DEFAULT_AIRBORNE_MIN_Z_DELTA = 4.0
DEFAULT_LANDING_WINDOW_MS = 250


class Sample(TypedDict):
    time_ms: int
    origin: list[float]


def read_json_if_present(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def read_run_env(run_dir: Path) -> dict[str, str]:
    env_path = run_dir / "run.env"
    values: dict[str, str] = {}
    if not env_path.exists():
        return values
    for raw_line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" not in raw_line or raw_line.startswith("#"):
            continue
        key, value = raw_line.split("=", 1)
        values[key] = value
    return values


def coerce_optional_int(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def coerce_time_ms(event: dict, data: dict) -> int:
    time_ms = data.get("TimeMs")
    if time_ms is not None:
        return int(round(float(time_ms)))
    data_time = data.get("Time")
    if data_time is not None:
        return int(round(float(data_time) * 1000.0))
    return int(round(float(event.get("time", 0.0)) * 1000.0))


def coerce_origin(value: object) -> list[float] | None:
    if not isinstance(value, list) or len(value) < 3:
        return None
    try:
        return [float(value[0]), float(value[1]), float(value[2])]
    except (TypeError, ValueError):
        return None


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * (pct / 100.0)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[int(rank)]
    weight = rank - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def round_float(value: float, digits: int = 3) -> float:
    if math.isfinite(value):
        return round(value, digits)
    return 0.0


def weighted_speed_for_window(segments: list[dict], start_ms: int, end_ms: int) -> float | None:
    total_ms = 0
    weighted_speed = 0.0
    for segment in segments:
        overlap_ms = max(0, min(segment["end_ms"], end_ms) - max(segment["start_ms"], start_ms))
        if overlap_ms <= 0:
            continue
        total_ms += overlap_ms
        weighted_speed += segment["horizontal_speed_qu_per_s"] * overlap_ms
    if total_ms <= 0:
        return None
    return weighted_speed / total_ms


def summarize_airborne_proxy(segments: list[dict], thresholds: dict[str, float]) -> dict:
    min_duration_ms = int(thresholds["airborne_min_duration_ms"])
    min_z_delta = thresholds["airborne_min_z_delta_qu"]
    landing_window_ms = int(thresholds["landing_window_ms"])

    runs: list[dict] = []
    current: dict | None = None
    for segment in segments:
        if segment["vertical_motion"]:
            if current is None:
                current = {
                    "start_ms": segment["start_ms"],
                    "end_ms": segment["end_ms"],
                    "z_min": min(segment["start_z"], segment["end_z"]),
                    "z_max": max(segment["start_z"], segment["end_z"]),
                }
            else:
                current["end_ms"] = segment["end_ms"]
                current["z_min"] = min(current["z_min"], segment["start_z"], segment["end_z"])
                current["z_max"] = max(current["z_max"], segment["start_z"], segment["end_z"])
        elif current is not None:
            duration_ms = current["end_ms"] - current["start_ms"]
            z_delta = current["z_max"] - current["z_min"]
            if duration_ms >= min_duration_ms and z_delta >= min_z_delta:
                runs.append({**current, "duration_ms": duration_ms, "z_delta_qu": z_delta})
            current = None

    if current is not None:
        duration_ms = current["end_ms"] - current["start_ms"]
        z_delta = current["z_max"] - current["z_min"]
        if duration_ms >= min_duration_ms and z_delta >= min_z_delta:
            runs.append({**current, "duration_ms": duration_ms, "z_delta_qu": z_delta})

    pre_speeds: list[float] = []
    post_speeds: list[float] = []
    post_deltas: list[float] = []
    post_losses: list[float] = []
    post_loss_ratios: list[float] = []
    for run in runs:
        landing_ms = run["end_ms"]
        pre_speed = weighted_speed_for_window(segments, landing_ms - landing_window_ms, landing_ms)
        post_speed = weighted_speed_for_window(segments, landing_ms, landing_ms + landing_window_ms)
        if pre_speed is None or post_speed is None:
            continue
        pre_speeds.append(pre_speed)
        post_speeds.append(post_speed)
        delta = post_speed - pre_speed
        post_deltas.append(delta)
        loss = pre_speed - post_speed
        post_losses.append(loss)
        if pre_speed > 0:
            post_loss_ratios.append(loss / pre_speed)

    durations = [run["duration_ms"] for run in runs]
    z_deltas = [run["z_delta_qu"] for run in runs]
    avg_pre_speed = sum(pre_speeds) / len(pre_speeds) if pre_speeds else 0.0
    avg_post_speed = sum(post_speeds) / len(post_speeds) if post_speeds else 0.0
    avg_loss = sum(post_losses) / len(post_losses) if post_losses else 0.0
    avg_loss_ratio = sum(post_loss_ratios) / len(post_loss_ratios) if post_loss_ratios else 0.0

    return {
        "airborne_proxy_count": len(runs),
        "airborne_proxy_time_ms": sum(durations),
        "avg_airborne_proxy_duration_ms": sum(durations) / len(durations) if durations else 0.0,
        "max_airborne_proxy_duration_ms": max(durations) if durations else 0,
        "avg_airborne_proxy_z_delta_qu": sum(z_deltas) / len(z_deltas) if z_deltas else 0.0,
        "max_airborne_proxy_z_delta_qu": max(z_deltas) if z_deltas else 0.0,
        "landing_speed_window_count": len(post_deltas),
        "avg_landing_pre_speed_qu_per_s": avg_pre_speed,
        "avg_landing_post_speed_qu_per_s": avg_post_speed,
        "avg_post_landing_speed_delta_qu_per_s": sum(post_deltas) / len(post_deltas) if post_deltas else 0.0,
        "avg_post_landing_speed_loss_qu_per_s": avg_loss if post_losses else 0.0,
        "avg_post_landing_speed_loss_ratio": avg_loss_ratio if post_losses else 0.0,
    }


def compute_slot_metrics(
    *,
    slot: int,
    name: str,
    samples: list[Sample],
    thresholds: dict[str, float],
) -> dict:
    ordered = sorted(samples, key=lambda sample: sample["time_ms"])
    if not ordered:
        return {
            "slot": slot,
            "name": name,
            "sample_count": 0,
            "segment_count": 0,
            "first_time_ms": None,
            "last_time_ms": None,
            "active_time_s": 0.0,
            "horizontal_distance_qu": 0.0,
            "net_horizontal_displacement_qu": 0.0,
            "path_efficiency": 0.0,
            "avg_horizontal_speed_qu_per_s": 0.0,
            "max_horizontal_speed_qu_per_s": 0.0,
            "max_horizontal_speed_time_ms": None,
            "p50_horizontal_speed_qu_per_s": 0.0,
            "p90_horizontal_speed_qu_per_s": 0.0,
            "p95_horizontal_speed_qu_per_s": 0.0,
            "stationary_time_s": 0.0,
            "stationary_time_ratio": 0.0,
            "low_speed_time_s": 0.0,
            "low_speed_time_ratio": 0.0,
            "over_maxspeed_time_s": 0.0,
            "over_maxspeed_time_ratio": 0.0,
            "over_400_time_s": 0.0,
            "over_400_time_ratio": 0.0,
            "vertical_motion_time_s": 0.0,
            "vertical_motion_time_ratio": 0.0,
            "airborne_proxy_time_s": 0.0,
            "airborne_proxy_time_ratio": 0.0,
            "airborne_proxy_count": 0,
            "jump_cadence_per_min": 0.0,
            "avg_airborne_proxy_duration_ms": 0.0,
            "max_airborne_proxy_duration_ms": 0,
            "avg_airborne_proxy_z_delta_qu": 0.0,
            "max_airborne_proxy_z_delta_qu": 0.0,
            "landing_speed_window_count": 0,
            "avg_landing_pre_speed_qu_per_s": 0.0,
            "avg_landing_post_speed_qu_per_s": 0.0,
            "avg_post_landing_speed_delta_qu_per_s": 0.0,
            "avg_post_landing_speed_loss_qu_per_s": 0.0,
            "avg_post_landing_speed_loss_ratio": 0.0,
            "dropped_teleport_segments": 0,
            "start_origin": [],
            "end_origin": [],
        }

    active_ms = 0
    horizontal_distance = 0.0
    stationary_ms = 0
    low_speed_ms = 0
    over_maxspeed_ms = 0
    over_high_speed_ms = 0
    vertical_motion_ms = 0
    dropped_teleport_segments = 0
    speeds: list[float] = []
    accepted_segments: list[dict] = []
    max_speed = 0.0
    max_speed_time_ms = 0
    segment_count = 0

    previous = ordered[0]
    for current in ordered[1:]:
        dt_ms = current["time_ms"] - previous["time_ms"]
        if dt_ms <= 0:
            previous = current
            continue

        dx = current["origin"][0] - previous["origin"][0]
        dy = current["origin"][1] - previous["origin"][1]
        dz = current["origin"][2] - previous["origin"][2]
        distance = math.hypot(dx, dy)
        speed = distance / (dt_ms / 1000.0)
        vertical_speed = dz / (dt_ms / 1000.0)

        if speed > thresholds["teleport_speed_qu_per_s"] or abs(vertical_speed) > thresholds["teleport_speed_qu_per_s"]:
            dropped_teleport_segments += 1
            previous = current
            continue

        vertical_motion = (
            abs(dz) >= thresholds["vertical_epsilon_qu"]
            or abs(vertical_speed) >= thresholds["vertical_speed_qu_per_s"]
        )

        segment_count += 1
        active_ms += dt_ms
        horizontal_distance += distance
        speeds.append(speed)
        accepted_segments.append(
            {
                "start_ms": previous["time_ms"],
                "end_ms": current["time_ms"],
                "dt_ms": dt_ms,
                "horizontal_speed_qu_per_s": speed,
                "start_z": previous["origin"][2],
                "end_z": current["origin"][2],
                "vertical_speed_qu_per_s": vertical_speed,
                "vertical_motion": vertical_motion,
            }
        )

        if speed > max_speed:
            max_speed = speed
            max_speed_time_ms = current["time_ms"]
        if speed < thresholds["stationary_speed_qu_per_s"]:
            stationary_ms += dt_ms
        if speed < thresholds["low_speed_qu_per_s"]:
            low_speed_ms += dt_ms
        if speed > thresholds["maxspeed_qu_per_s"]:
            over_maxspeed_ms += dt_ms
        if speed > thresholds["high_speed_qu_per_s"]:
            over_high_speed_ms += dt_ms
        if vertical_motion:
            vertical_motion_ms += dt_ms

        previous = current

    active_s = active_ms / 1000.0
    avg_speed = horizontal_distance / active_s if active_s > 0 else 0.0
    first_origin = ordered[0]["origin"]
    last_origin = ordered[-1]["origin"]
    net_distance = math.hypot(last_origin[0] - first_origin[0], last_origin[1] - first_origin[1])
    path_efficiency = net_distance / horizontal_distance if horizontal_distance > 0 else 0.0
    airborne = summarize_airborne_proxy(accepted_segments, thresholds)
    airborne_ms = airborne["airborne_proxy_time_ms"]

    return {
        "slot": slot,
        "name": name,
        "sample_count": len(ordered),
        "segment_count": segment_count,
        "first_time_ms": ordered[0]["time_ms"],
        "last_time_ms": ordered[-1]["time_ms"],
        "active_time_s": round_float(active_s),
        "horizontal_distance_qu": round_float(horizontal_distance),
        "net_horizontal_displacement_qu": round_float(net_distance),
        "path_efficiency": round_float(path_efficiency),
        "avg_horizontal_speed_qu_per_s": round_float(avg_speed),
        "max_horizontal_speed_qu_per_s": round_float(max_speed),
        "max_horizontal_speed_time_ms": max_speed_time_ms,
        "p50_horizontal_speed_qu_per_s": round_float(percentile(speeds, 50)),
        "p90_horizontal_speed_qu_per_s": round_float(percentile(speeds, 90)),
        "p95_horizontal_speed_qu_per_s": round_float(percentile(speeds, 95)),
        "stationary_time_s": round_float(stationary_ms / 1000.0),
        "stationary_time_ratio": round_float(stationary_ms / active_ms if active_ms else 0.0),
        "low_speed_time_s": round_float(low_speed_ms / 1000.0),
        "low_speed_time_ratio": round_float(low_speed_ms / active_ms if active_ms else 0.0),
        "over_maxspeed_time_s": round_float(over_maxspeed_ms / 1000.0),
        "over_maxspeed_time_ratio": round_float(over_maxspeed_ms / active_ms if active_ms else 0.0),
        "over_400_time_s": round_float(over_high_speed_ms / 1000.0),
        "over_400_time_ratio": round_float(over_high_speed_ms / active_ms if active_ms else 0.0),
        "vertical_motion_time_s": round_float(vertical_motion_ms / 1000.0),
        "vertical_motion_time_ratio": round_float(vertical_motion_ms / active_ms if active_ms else 0.0),
        "airborne_proxy_time_s": round_float(airborne_ms / 1000.0),
        "airborne_proxy_time_ratio": round_float(airborne_ms / active_ms if active_ms else 0.0),
        "airborne_proxy_count": airborne["airborne_proxy_count"],
        "jump_cadence_per_min": round_float(
            airborne["airborne_proxy_count"] / active_s * 60.0 if active_s else 0.0
        ),
        "avg_airborne_proxy_duration_ms": round_float(airborne["avg_airborne_proxy_duration_ms"]),
        "max_airborne_proxy_duration_ms": airborne["max_airborne_proxy_duration_ms"],
        "avg_airborne_proxy_z_delta_qu": round_float(airborne["avg_airborne_proxy_z_delta_qu"]),
        "max_airborne_proxy_z_delta_qu": round_float(airborne["max_airborne_proxy_z_delta_qu"]),
        "landing_speed_window_count": airborne["landing_speed_window_count"],
        "avg_landing_pre_speed_qu_per_s": round_float(airborne["avg_landing_pre_speed_qu_per_s"]),
        "avg_landing_post_speed_qu_per_s": round_float(airborne["avg_landing_post_speed_qu_per_s"]),
        "avg_post_landing_speed_delta_qu_per_s": round_float(airborne["avg_post_landing_speed_delta_qu_per_s"]),
        "avg_post_landing_speed_loss_qu_per_s": round_float(airborne["avg_post_landing_speed_loss_qu_per_s"]),
        "avg_post_landing_speed_loss_ratio": round_float(airborne["avg_post_landing_speed_loss_ratio"]),
        "dropped_teleport_segments": dropped_teleport_segments,
        "start_origin": [round_float(part) for part in first_origin],
        "end_origin": [round_float(part) for part in last_origin],
    }


def compute_movement_metrics(
    events_path: Path,
    *,
    run_dir: Path | None = None,
    include_empty: bool = False,
    stationary_speed: float = DEFAULT_STATIONARY_SPEED,
    low_speed: float = DEFAULT_LOW_SPEED,
    high_speed: float = DEFAULT_HIGH_SPEED,
    teleport_speed: float = DEFAULT_TELEPORT_SPEED,
    vertical_epsilon: float = DEFAULT_VERTICAL_EPSILON,
    vertical_speed: float = DEFAULT_VERTICAL_SPEED,
    airborne_min_duration_ms: int = DEFAULT_AIRBORNE_MIN_DURATION_MS,
    airborne_min_z_delta: float = DEFAULT_AIRBORNE_MIN_Z_DELTA,
    landing_window_ms: int = DEFAULT_LANDING_WINDOW_MS,
) -> dict:
    if run_dir is None:
        run_dir = events_path.parent

    run_env = read_run_env(run_dir)
    analysis = read_json_if_present(run_dir / "analysis.json")
    match = analysis.get("match", {}) if isinstance(analysis, dict) else {}
    match_duration_ms = coerce_optional_int(match.get("duration"))

    players: dict[int, dict] = {}
    samples_by_slot: dict[int, list[Sample]] = {}
    server_data: dict = {}
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
            if kind == 0 and isinstance(data.get("Data"), dict):
                server_data = data["Data"]
                continue

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

            if kind == 5:
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
                    }
                )

    maxspeed = server_data.get("MaxSpeed", DEFAULT_MAXSPEED)
    try:
        maxspeed = float(maxspeed)
    except (TypeError, ValueError):
        maxspeed = DEFAULT_MAXSPEED

    thresholds = {
        "stationary_speed_qu_per_s": float(stationary_speed),
        "low_speed_qu_per_s": float(low_speed),
        "maxspeed_qu_per_s": float(maxspeed),
        "high_speed_qu_per_s": float(high_speed),
        "teleport_speed_qu_per_s": float(teleport_speed),
        "vertical_epsilon_qu": float(vertical_epsilon),
        "vertical_speed_qu_per_s": float(vertical_speed),
        "airborne_min_duration_ms": float(airborne_min_duration_ms),
        "airborne_min_z_delta_qu": float(airborne_min_z_delta),
        "landing_window_ms": float(landing_window_ms),
    }

    player_metrics = []
    for slot, samples in sorted(samples_by_slot.items()):
        info = players.get(slot, {})
        name = str(info.get("name") or "")
        first_named_time_ms = info.get("first_named_time_ms")
        if not include_empty and not name:
            continue
        if first_named_time_ms is not None:
            samples = [sample for sample in samples if sample["time_ms"] >= first_named_time_ms]
        if match_duration_ms is not None:
            samples = [sample for sample in samples if sample["time_ms"] <= match_duration_ms]
        if not samples:
            continue

        metric = compute_slot_metrics(
            slot=slot,
            name=name,
            samples=samples,
            thresholds=thresholds,
        )
        metric["user_id"] = info.get("user_id")
        metric["spectator"] = bool(info.get("spectator", False))
        metric["first_named_time_ms"] = first_named_time_ms
        metric["match_duration_clamp_ms"] = match_duration_ms
        player_metrics.append(metric)

    return {
        "schema": SCHEMA,
        "source": {
            "events": str(events_path),
            "analysis": str(run_dir / "analysis.json") if (run_dir / "analysis.json").exists() else "",
        },
        "run": {
            "run_id": run_dir.name,
            "map_command": run_env.get("MAP", ""),
            "map_title": match.get("map", server_data.get("LevelName", "")),
            "duration_ms": match.get("duration", ""),
        },
        "parser": {
            "event_count": event_count,
            "position_event_count": position_event_count,
        },
        "thresholds": thresholds,
        "sample_window": {
            "match_duration_clamp_ms": match_duration_ms,
            "notes": "Named player samples are clamped to match.duration when analysis.json provides it.",
        },
        "players": player_metrics,
    }


def pct(value: float) -> str:
    return f"{value * 100.0:.1f}%"


def write_markdown(metrics: dict, output_path: Path) -> None:
    thresholds = metrics["thresholds"]
    run = metrics["run"]
    lines = [
        f"# Movement metrics {run.get('run_id', '')}",
        "",
        "## Run",
        "",
        f"- Map command: `{run.get('map_command', '')}`",
        f"- Map title: `{run.get('map_title', '')}`",
        f"- Duration: `{run.get('duration_ms', '')}` ms",
        f"- Position events: `{metrics['parser'].get('position_event_count', 0)}`",
        f"- Match-duration clamp: `{metrics.get('sample_window', {}).get('match_duration_clamp_ms', '')}` ms",
        "",
        "## Method",
        "",
        "- Source: `events.txt` kind `5` player origin samples.",
        "- Average speed is distance over active time; percentiles are unweighted per accepted segment.",
        f"- Stationary: horizontal speed < `{thresholds['stationary_speed_qu_per_s']}` qu/s.",
        f"- Low speed: horizontal speed < `{thresholds['low_speed_qu_per_s']}` qu/s.",
        f"- Over maxspeed: horizontal speed > `{thresholds['maxspeed_qu_per_s']}` qu/s.",
        f"- High speed: horizontal speed > `{thresholds['high_speed_qu_per_s']}` qu/s.",
        f"- Teleport guard: segments > `{thresholds['teleport_speed_qu_per_s']}` qu/s are excluded.",
        f"- Vertical motion proxy: abs(delta Z) >= `{thresholds['vertical_epsilon_qu']}` qu or vertical speed >= `{thresholds['vertical_speed_qu_per_s']}` qu/s.",
        f"- Airborne proxy run: vertical-motion run lasting >= `{thresholds['airborne_min_duration_ms']}` ms with Z range >= `{thresholds['airborne_min_z_delta_qu']}` qu.",
        f"- Landing speed delta window: `{thresholds['landing_window_ms']}` ms before/after each airborne-proxy run end.",
        "",
        "## Speed",
        "",
    ]

    players = metrics.get("players", [])
    if not players:
        lines.append("No named players had movement samples.")
    else:
        lines.extend(
            [
                "| Slot | Player | Samples | Active s | Distance | Avg | Max | P95 | >Max | >400 | Stationary | Teleports |",
                "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for player in players:
            lines.append(
                "| "
                f"{player['slot']} | "
                f"`{player['name']}` | "
                f"{player['sample_count']} | "
                f"{player['active_time_s']:.3f} | "
                f"{player['horizontal_distance_qu']:.1f} | "
                f"{player['avg_horizontal_speed_qu_per_s']:.1f} | "
                f"{player['max_horizontal_speed_qu_per_s']:.1f} | "
                f"{player['p95_horizontal_speed_qu_per_s']:.1f} | "
                f"{pct(player['over_maxspeed_time_ratio'])} | "
                f"{pct(player['over_400_time_ratio'])} | "
                f"{pct(player['stationary_time_ratio'])} | "
                f"{player['dropped_teleport_segments']} |"
            )

        lines.extend(
            [
                "",
                "## Airborne Proxy",
                "",
                "| Slot | Player | Vertical | Air | Runs | Cadence/min | Avg air ms | Max Z | Post delta | Loss | Loss % | Windows |",
                "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for player in players:
            lines.append(
                "| "
                f"{player['slot']} | "
                f"`{player['name']}` | "
                f"{pct(player['vertical_motion_time_ratio'])} | "
                f"{pct(player['airborne_proxy_time_ratio'])} | "
                f"{player['airborne_proxy_count']} | "
                f"{player['jump_cadence_per_min']:.1f} | "
                f"{player['avg_airborne_proxy_duration_ms']:.1f} | "
                f"{player['max_airborne_proxy_z_delta_qu']:.1f} | "
                f"{player['avg_post_landing_speed_delta_qu_per_s']:.1f} | "
                f"{player['avg_post_landing_speed_loss_qu_per_s']:.1f} | "
                f"{pct(player['avg_post_landing_speed_loss_ratio'])} | "
                f"{player['landing_speed_window_count']} |"
            )

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_movement_metrics(
    run_dir: Path,
    *,
    events_path: Path | None = None,
    include_empty: bool = False,
    stationary_speed: float = DEFAULT_STATIONARY_SPEED,
    low_speed: float = DEFAULT_LOW_SPEED,
    high_speed: float = DEFAULT_HIGH_SPEED,
    teleport_speed: float = DEFAULT_TELEPORT_SPEED,
    vertical_epsilon: float = DEFAULT_VERTICAL_EPSILON,
    vertical_speed: float = DEFAULT_VERTICAL_SPEED,
    airborne_min_duration_ms: int = DEFAULT_AIRBORNE_MIN_DURATION_MS,
    airborne_min_z_delta: float = DEFAULT_AIRBORNE_MIN_Z_DELTA,
    landing_window_ms: int = DEFAULT_LANDING_WINDOW_MS,
) -> dict:
    if events_path is None:
        events_path = run_dir / "events.txt"
    if not events_path.exists():
        raise RuntimeError(f"Missing events file: {events_path}")

    metrics = compute_movement_metrics(
        events_path,
        run_dir=run_dir,
        include_empty=include_empty,
        stationary_speed=stationary_speed,
        low_speed=low_speed,
        high_speed=high_speed,
        teleport_speed=teleport_speed,
        vertical_epsilon=vertical_epsilon,
        vertical_speed=vertical_speed,
        airborne_min_duration_ms=airborne_min_duration_ms,
        airborne_min_z_delta=airborne_min_z_delta,
        landing_window_ms=landing_window_ms,
    )

    json_path = run_dir / "movement-metrics.json"
    md_path = run_dir / "movement-metrics.md"
    json_path.write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_markdown(metrics, md_path)
    return metrics


def resolve_input(path_text: str) -> tuple[Path, Path]:
    path = Path(path_text)
    if path.is_file():
        return path.parent, path
    return path, path / "events.txt"


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract movement metrics from a Komodobots lab run.")
    parser.add_argument("path", help="Run directory or events.txt path.")
    parser.add_argument("--include-empty", action="store_true", help="Include unnamed slots such as the control shim.")
    parser.add_argument("--stationary-speed", type=float, default=DEFAULT_STATIONARY_SPEED)
    parser.add_argument("--low-speed", type=float, default=DEFAULT_LOW_SPEED)
    parser.add_argument("--high-speed", type=float, default=DEFAULT_HIGH_SPEED)
    parser.add_argument("--teleport-speed", type=float, default=DEFAULT_TELEPORT_SPEED)
    parser.add_argument("--vertical-epsilon", type=float, default=DEFAULT_VERTICAL_EPSILON)
    parser.add_argument("--vertical-speed", type=float, default=DEFAULT_VERTICAL_SPEED)
    parser.add_argument("--airborne-min-duration-ms", type=int, default=DEFAULT_AIRBORNE_MIN_DURATION_MS)
    parser.add_argument("--airborne-min-z-delta", type=float, default=DEFAULT_AIRBORNE_MIN_Z_DELTA)
    parser.add_argument("--landing-window-ms", type=int, default=DEFAULT_LANDING_WINDOW_MS)
    return parser.parse_args(list(argv))


def main(argv: Iterable[str] = sys.argv[1:]) -> int:
    args = parse_args(argv)
    run_dir, events_path = resolve_input(args.path)
    metrics = write_movement_metrics(
        run_dir,
        events_path=events_path,
        include_empty=args.include_empty,
        stationary_speed=args.stationary_speed,
        low_speed=args.low_speed,
        high_speed=args.high_speed,
        teleport_speed=args.teleport_speed,
        vertical_epsilon=args.vertical_epsilon,
        vertical_speed=args.vertical_speed,
        airborne_min_duration_ms=args.airborne_min_duration_ms,
        airborne_min_z_delta=args.airborne_min_z_delta,
        landing_window_ms=args.landing_window_ms,
    )
    print(f"players={len(metrics.get('players', []))}")
    print(f"json={run_dir / 'movement-metrics.json'}")
    print(f"markdown={run_dir / 'movement-metrics.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
