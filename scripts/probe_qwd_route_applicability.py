#!/usr/bin/env python3
"""Probe whether QWD POV demos can yield route/controller-ready movement data.

This is intentionally narrower than a production QWD parser. It measures whether
the locally available POV demos expose a source-grounded pair of:

- exact outgoing `dem_cmd` usercmd rows, and
- self-player `svc_playerinfo` origin/velocity rows anchored after the QWD
  network-message sequence header.

The output is a compact evidence summary. Raw paired samples and waypoint
exports should stay under ignored `artifacts/`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.qwd_usercmd import qwd_usercmd


SCHEMA = "komodobots.qwd_route_probe.v1"

SVC_SERVERDATA = 11
SVC_PLAYERINFO = 42
QWD_NET_MESSAGE_BODY_OFFSET = 8

PF_MSEC = 1 << 0
PF_COMMAND = 1 << 1
PF_VELOCITY1 = 1 << 2
PF_VELOCITY2 = 1 << 3
PF_VELOCITY3 = 1 << 4
PF_MODEL = 1 << 5
PF_SKINNUM = 1 << 6
PF_EFFECTS = 1 << 7
PF_WEAPONFRAME = 1 << 8
PF_PMC_SHIFT = 11
PF_PMC_MASK = 7
PF_ONGROUND_16 = 1 << 14
PF_SOLID_16 = 1 << 15

MAX_REASONABLE_COORD = 8192.0
MAX_PLAYERINFO_BYTES = 32
DISCONTINUITY_SPEED_QU_PER_S = 3000.0
DISCONTINUITY_DISTANCE_QU = 256.0
DISCONTINUITY_MAX_DT_S = 0.25
DUPLICATE_TIME_MAX_DISTANCE_QU = 16.0
MIN_SPEED_DT_S = 0.001


@dataclass(frozen=True)
class QwdPayloadRecord:
    index: int
    file_offset: int
    time_s: float
    message_type: int
    payload: bytes | None


@dataclass(frozen=True)
class ServerData:
    protocol: int
    playernum: int
    spectator: bool
    gamedir: str
    level_name: str


@dataclass(frozen=True)
class PlayerInfoSample:
    record_index: int
    time_s: float
    playernum: int
    flags: int
    origin: tuple[float, float, float]
    velocity: tuple[int, int, int]
    frame: int
    onground: bool
    solid: bool
    pm_code: int
    payload_len: int
    parsed_len: int

    def to_json_obj(self) -> dict[str, object]:
        return {
            "record_index": self.record_index,
            "time_s": round(self.time_s, 6),
            "playernum": self.playernum,
            "flags": self.flags,
            "origin": [round(value, 3) for value in self.origin],
            "velocity": list(self.velocity),
            "frame": self.frame,
            "onground": self.onground,
            "solid": self.solid,
            "pm_code": self.pm_code,
        }


@dataclass(frozen=True)
class PairedSample:
    frame: int
    time_s: float
    state_time_s: float
    time_delta_s: float
    origin: tuple[float, float, float]
    velocity: tuple[int, int, int]
    view_yaw: float
    forwardmove: int
    sidemove: int
    upmove: int
    buttons: int
    impulse: int

    def to_json_obj(self) -> dict[str, object]:
        return {
            "frame": self.frame,
            "time_s": round(self.time_s, 6),
            "state_time_s": round(self.state_time_s, 6),
            "time_delta_s": round(self.time_delta_s, 6),
            "origin": [round(value, 3) for value in self.origin],
            "velocity": list(self.velocity),
            "view_yaw": round(self.view_yaw, 6),
            "forwardmove": self.forwardmove,
            "sidemove": self.sidemove,
            "upmove": self.upmove,
            "buttons": self.buttons,
            "impulse": self.impulse,
        }


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def iter_qwd_payload_records(data: bytes) -> Iterator[QwdPayloadRecord]:
    cursor = 0
    index = 0
    while cursor < len(data):
        record_offset = cursor
        qwd_usercmd.require_available(data, cursor, qwd_usercmd.RECORD_HEADER_SIZE, "reading QWD record header")
        demotime, raw_type = struct.unpack_from(qwd_usercmd.RECORD_HEADER_FORMAT, data, cursor)
        cursor += qwd_usercmd.RECORD_HEADER_SIZE
        message_type = raw_type & 7

        payload: bytes | None = None
        if message_type == qwd_usercmd.DEM_CMD:
            cursor += qwd_usercmd.USERCMD_STRUCT_SIZE + qwd_usercmd.VIEW_ANGLES_SIZE
        elif message_type == qwd_usercmd.DEM_SET:
            cursor += 8
        elif message_type == qwd_usercmd.DEM_MULTIPLE:
            cursor += 4
            payload, cursor = read_length_prefixed_payload(data, cursor, "dem_multiple payload")
        elif message_type in (
            qwd_usercmd.DEM_READ,
            qwd_usercmd.DEM_SINGLE,
            qwd_usercmd.DEM_STATS,
            qwd_usercmd.DEM_ALL,
        ):
            payload, cursor = read_length_prefixed_payload(data, cursor, "length-prefixed payload")
        else:
            raise qwd_usercmd.QwdUsercmdError(
                f"Unsupported QWD record type {message_type} at offset {record_offset}."
            )

        yield QwdPayloadRecord(
            index=index,
            file_offset=record_offset,
            time_s=demotime,
            message_type=message_type,
            payload=payload,
        )
        index += 1


def read_length_prefixed_payload(data: bytes, cursor: int, context: str) -> tuple[bytes, int]:
    qwd_usercmd.require_available(data, cursor, 4, f"reading {context} length")
    length, = struct.unpack_from("<i", data, cursor)
    cursor += 4
    if length < 0:
        raise qwd_usercmd.QwdUsercmdError(f"Negative {context} length {length} at offset {cursor - 4}.")
    if length > qwd_usercmd.MAX_REASONABLE_MESSAGE_BYTES:
        raise qwd_usercmd.QwdUsercmdError(f"Unreasonable {context} length {length} at offset {cursor - 4}.")
    qwd_usercmd.require_available(data, cursor, length, f"reading {context}")
    return data[cursor : cursor + length], cursor + length


def read_c_string(data: bytes, cursor: int) -> tuple[str, int]:
    end = data.index(0, cursor)
    return data[cursor:end].decode("latin1", "replace"), end + 1


def parse_serverdata_candidates(payload: bytes) -> list[ServerData]:
    candidates: list[ServerData] = []
    for offset, value in enumerate(payload):
        if value != SVC_SERVERDATA:
            continue
        try:
            cursor = offset + 1
            protocol, = struct.unpack_from("<i", payload, cursor)
            cursor += 4
            _server_count, = struct.unpack_from("<i", payload, cursor)
            cursor += 4
            gamedir, cursor = read_c_string(payload, cursor)
            raw_playernum = payload[cursor]
            cursor += 1
            level_name, cursor = read_c_string(payload, cursor)
        except (IndexError, ValueError, struct.error):
            continue
        playernum = raw_playernum & 0x7F
        if 20 <= protocol <= 30 and playernum <= 31 and len(gamedir) <= 64 and len(level_name) <= 128:
            candidates.append(
                ServerData(
                    protocol=protocol,
                    playernum=playernum,
                    spectator=bool(raw_playernum & 0x80),
                    gamedir=gamedir,
                    level_name=level_name,
                )
            )
    return candidates


def read_coord(payload: bytes, cursor: int) -> tuple[float, int]:
    value, = struct.unpack_from("<h", payload, cursor)
    return value / 8.0, cursor + 2


def parse_anchored_playerinfo(payload: bytes, *, offset: int = QWD_NET_MESSAGE_BODY_OFFSET) -> PlayerInfoSample | None:
    if len(payload) <= offset or payload[offset] != SVC_PLAYERINFO:
        return None

    cursor = offset + 1
    if cursor + 1 + 2 + 6 + 1 > len(payload):
        return None

    playernum = payload[cursor]
    cursor += 1
    flags, = struct.unpack_from("<H", payload, cursor)
    cursor += 2
    if playernum > 31:
        return None
    # The source-backed self-player path clears PF_COMMAND/PF_MSEC. Rejecting
    # command-bearing candidates keeps this probe scoped to the tracked player.
    if flags & PF_COMMAND:
        return None

    origin_values: list[float] = []
    for _ in range(3):
        coord, cursor = read_coord(payload, cursor)
        origin_values.append(coord)
    if any(abs(value) > MAX_REASONABLE_COORD for value in origin_values):
        return None

    frame = payload[cursor]
    cursor += 1
    if flags & PF_MSEC:
        if cursor >= len(payload):
            return None
        cursor += 1

    velocity_values: list[int] = []
    for bit in (PF_VELOCITY1, PF_VELOCITY2, PF_VELOCITY3):
        if flags & bit:
            if cursor + 2 > len(payload):
                return None
            velocity, = struct.unpack_from("<h", payload, cursor)
            cursor += 2
            velocity_values.append(velocity)
        else:
            velocity_values.append(0)

    for bit in (PF_MODEL, PF_SKINNUM, PF_EFFECTS, PF_WEAPONFRAME):
        if flags & bit:
            if cursor >= len(payload):
                return None
            cursor += 1

    parsed_len = cursor - offset
    if parsed_len < 11 or parsed_len > MAX_PLAYERINFO_BYTES:
        return None

    return PlayerInfoSample(
        record_index=-1,
        time_s=0.0,
        playernum=playernum,
        flags=flags,
        origin=(origin_values[0], origin_values[1], origin_values[2]),
        velocity=(velocity_values[0], velocity_values[1], velocity_values[2]),
        frame=frame,
        onground=bool(flags & PF_ONGROUND_16),
        solid=bool(flags & PF_SOLID_16),
        pm_code=(flags >> PF_PMC_SHIFT) & PF_PMC_MASK,
        payload_len=len(payload),
        parsed_len=parsed_len,
    )


def extract_playerinfo_samples(data: bytes) -> tuple[list[PlayerInfoSample], ServerData | None, dict[str, int]]:
    samples: list[PlayerInfoSample] = []
    serverdata: ServerData | None = None
    scan_counts = {
        "payload_records": 0,
        "anchored_playerinfo_records": 0,
        "rejected_playerinfo_playernum_mismatch": 0,
        "suspicious_later_playerinfo_markers": 0,
    }

    for record in iter_qwd_payload_records(data):
        if record.payload is None:
            continue
        scan_counts["payload_records"] += 1
        if serverdata is None:
            candidates = parse_serverdata_candidates(record.payload)
            if candidates:
                serverdata = candidates[0]

        later_payload = record.payload[QWD_NET_MESSAGE_BODY_OFFSET + 1 :]
        if SVC_PLAYERINFO in later_payload:
            scan_counts["suspicious_later_playerinfo_markers"] += later_payload.count(bytes([SVC_PLAYERINFO]))

        sample = parse_anchored_playerinfo(record.payload)
        if sample is None:
            continue
        if serverdata is not None and sample.playernum != serverdata.playernum:
            scan_counts["rejected_playerinfo_playernum_mismatch"] += 1
            continue
        scan_counts["anchored_playerinfo_records"] += 1
        samples.append(
            PlayerInfoSample(
                record_index=record.index,
                time_s=record.time_s,
                playernum=sample.playernum,
                flags=sample.flags,
                origin=sample.origin,
                velocity=sample.velocity,
                frame=sample.frame,
                onground=sample.onground,
                solid=sample.solid,
                pm_code=sample.pm_code,
                payload_len=sample.payload_len,
                parsed_len=sample.parsed_len,
            )
        )

    return samples, serverdata, scan_counts


def percentile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * q
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[int(rank)]
    weight = rank - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


def rounded(value: float | None, digits: int = 3) -> float | None:
    if value is None:
        return None
    return round(value, digits)


def distance_3d(a: Sequence[float], b: Sequence[float]) -> float:
    return math.dist(a, b)


def pair_commands_to_states(
    commands: Sequence[qwd_usercmd.UsercmdRecord],
    states: Sequence[PlayerInfoSample],
) -> list[PairedSample]:
    pairs: list[PairedSample] = []
    for index, (command, state) in enumerate(zip(commands, states)):
        pairs.append(
            PairedSample(
                frame=index,
                time_s=command.time_s,
                state_time_s=state.time_s,
                time_delta_s=state.time_s - command.time_s,
                origin=state.origin,
                velocity=state.velocity,
                view_yaw=command.view_angles[1],
                forwardmove=command.forwardmove,
                sidemove=command.sidemove,
                upmove=command.upmove,
                buttons=command.buttons,
                impulse=command.impulse,
            )
        )
    return pairs


def split_continuous_segments(pairs: Sequence[PairedSample]) -> tuple[list[list[PairedSample]], list[dict[str, object]]]:
    if not pairs:
        return [], []
    segments: list[list[PairedSample]] = [[pairs[0]]]
    discontinuities: list[dict[str, object]] = []

    for prev, current in zip(pairs, pairs[1:]):
        dt = current.state_time_s - prev.state_time_s
        distance = distance_3d(prev.origin, current.origin)
        if dt <= 0 and distance <= DUPLICATE_TIME_MAX_DISTANCE_QU:
            segments[-1].append(current)
            continue
        speed = distance / dt if dt > MIN_SPEED_DT_S else None
        reasons: list[str] = []
        if dt <= 0:
            reasons.append("non_monotonic_state_time")
        elif dt > DISCONTINUITY_MAX_DT_S:
            reasons.append("large_time_gap")
        if distance > DISCONTINUITY_DISTANCE_QU:
            reasons.append("large_position_gap")
        if speed is not None and speed > DISCONTINUITY_SPEED_QU_PER_S:
            reasons.append("implausible_speed")

        if reasons:
            discontinuities.append(
                {
                    "frame": current.frame,
                    "prev_state_time_s": round(prev.state_time_s, 6),
                    "state_time_s": round(current.state_time_s, 6),
                    "dt_s": round(dt, 6),
                    "distance_qu": round(distance, 3),
                    "speed_qu_per_s": rounded(speed, 3),
                    "reasons": reasons,
                }
            )
            segments.append([current])
        else:
            segments[-1].append(current)

    return segments, discontinuities


def summarize_motion(pairs: Sequence[PairedSample]) -> dict[str, object]:
    step_speeds: list[float] = []
    step_distances: list[float] = []
    total_distance = 0.0
    for prev, current in zip(pairs, pairs[1:]):
        dt = current.state_time_s - prev.state_time_s
        distance = distance_3d(prev.origin, current.origin)
        speed = distance / dt if dt > MIN_SPEED_DT_S else None
        if speed is not None and speed <= DISCONTINUITY_SPEED_QU_PER_S and distance <= DISCONTINUITY_DISTANCE_QU:
            step_speeds.append(speed)
            step_distances.append(distance)
            total_distance += distance

    displacement = 0.0
    if len(pairs) >= 2:
        displacement = distance_3d(pairs[0].origin, pairs[-1].origin)
    active_duration = 0.0
    if len(pairs) >= 2:
        active_duration = max(0.0, pairs[-1].state_time_s - pairs[0].state_time_s)

    return {
        "duration_s": round(active_duration, 3),
        "accepted_step_count": len(step_speeds),
        "path_distance_qu": round(total_distance, 3),
        "displacement_qu": round(displacement, 3),
        "path_efficiency": rounded(displacement / total_distance if total_distance > 0 else None, 3),
        "speed_qu_per_s": {
            "avg": rounded(statistics.fmean(step_speeds) if step_speeds else None, 3),
            "p50": rounded(percentile(step_speeds, 0.50), 3),
            "p95": rounded(percentile(step_speeds, 0.95), 3),
            "max": rounded(max(step_speeds) if step_speeds else None, 3),
        },
    }


def build_waypoints(
    segments: Sequence[Sequence[PairedSample]],
    *,
    spacing_qu: float,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    waypoints: list[dict[str, object]] = []
    segment_lengths: list[float] = []
    for segment_index, segment in enumerate(segments):
        if len(segment) < 2:
            continue
        segment_distance = 0.0
        last_point = segment[0]
        segment_waypoint_count = 0
        waypoints.append(
            {
                "segment": segment_index,
                "frame": last_point.frame,
                "time_s": round(last_point.state_time_s, 6),
                "origin": [round(value, 3) for value in last_point.origin],
            }
        )
        segment_waypoint_count += 1
        for prev, current in zip(segment, segment[1:]):
            step = distance_3d(prev.origin, current.origin)
            segment_distance += step
            if distance_3d(last_point.origin, current.origin) >= spacing_qu:
                waypoints.append(
                    {
                        "segment": segment_index,
                        "frame": current.frame,
                        "time_s": round(current.state_time_s, 6),
                        "origin": [round(value, 3) for value in current.origin],
                    }
                )
                last_point = current
                segment_waypoint_count += 1
        if segment_waypoint_count == 1 or distance_3d(last_point.origin, segment[-1].origin) >= spacing_qu * 0.25:
            waypoints.append(
                {
                    "segment": segment_index,
                    "frame": segment[-1].frame,
                    "time_s": round(segment[-1].state_time_s, 6),
                    "origin": [round(value, 3) for value in segment[-1].origin],
                }
            )
            segment_waypoint_count += 1
        segment_lengths.append(segment_distance)

    edge_count = max(0, len(waypoints) - len([segment for segment in segments if len(segment) >= 2]))
    metadata = {
        "spacing_qu": spacing_qu,
        "waypoint_count": len(waypoints),
        "edge_count": edge_count,
        "segment_count": len([segment for segment in segments if len(segment) >= 2]),
        "max_segment_distance_qu": rounded(max(segment_lengths) if segment_lengths else None, 3),
        "median_segment_distance_qu": rounded(percentile(segment_lengths, 0.50), 3),
    }
    return waypoints, metadata


def summarize_commands(pairs: Sequence[PairedSample]) -> dict[str, object]:
    if not pairs:
        return {
            "nonzero_forward_ratio": None,
            "nonzero_side_ratio": None,
            "jump_button_ratio": None,
            "attack_button_ratio": None,
            "forwardmove_values": [],
            "sidemove_values": [],
        }
    count = len(pairs)
    forward_values = sorted({pair.forwardmove for pair in pairs})
    side_values = sorted({pair.sidemove for pair in pairs})
    return {
        "nonzero_forward_ratio": round(sum(pair.forwardmove != 0 for pair in pairs) / count, 3),
        "nonzero_side_ratio": round(sum(pair.sidemove != 0 for pair in pairs) / count, 3),
        "jump_button_ratio": round(sum(bool(pair.buttons & 2) for pair in pairs) / count, 3),
        "attack_button_ratio": round(sum(bool(pair.buttons & 1) for pair in pairs) / count, 3),
        "forwardmove_values": forward_values[:20],
        "sidemove_values": side_values[:20],
        "forwardmove_abs_p50": rounded(percentile([abs(pair.forwardmove) for pair in pairs], 0.50), 3),
        "sidemove_abs_p50": rounded(percentile([abs(pair.sidemove) for pair in pairs], 0.50), 3),
    }


def summarize_demo(path: Path, *, waypoint_spacing_qu: float, raw_output_dir: Path | None = None) -> dict[str, object]:
    data = path.read_bytes()
    command_result = qwd_usercmd.parse_qwd_bytes(data, source_path=path, strict_plausibility=True)
    states, serverdata, scan_counts = extract_playerinfo_samples(data)
    commands = command_result.commands
    pairs = pair_commands_to_states(commands, states)
    segments, discontinuities = split_continuous_segments(pairs)
    waypoints, waypoint_metadata = build_waypoints(segments, spacing_qu=waypoint_spacing_qu)
    motion = summarize_motion(pairs)
    command_summary = summarize_commands(pairs)
    time_deltas = [abs(pair.time_delta_s) for pair in pairs]
    coverage = len(pairs) / len(commands) if commands else 0.0
    route_candidate = (
        coverage >= 0.98
        and waypoint_metadata["waypoint_count"] >= 3
        and (waypoint_metadata["max_segment_distance_qu"] or 0) >= waypoint_spacing_qu
    )

    if raw_output_dir is not None:
        raw_output_dir.mkdir(parents=True, exist_ok=True)
        pairs_path = raw_output_dir / f"{path.stem}.paired.ndjson"
        pairs_path.write_text(
            "\n".join(json.dumps(pair.to_json_obj(), sort_keys=True) for pair in pairs) + ("\n" if pairs else ""),
            encoding="utf-8",
        )
        waypoint_path = raw_output_dir / f"{path.stem}.waypoints.json"
        waypoint_path.write_text(json.dumps(waypoints, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    return {
        "demo": path.name,
        "source_sha256": sha256_bytes(data),
        "map_marker_dm3": b"\\map\\dm3\\" in data.lower(),
        "serverdata": {
            "protocol": serverdata.protocol,
            "playernum": serverdata.playernum,
            "spectator": serverdata.spectator,
            "gamedir": serverdata.gamedir,
            "level_name": serverdata.level_name,
        }
        if serverdata is not None
        else None,
        "command_frames": len(commands),
        "state_frames": len(states),
        "paired_frames": len(pairs),
        "paired_coverage": round(coverage, 3),
        "pair_time_delta_abs_s": {
            "p50": rounded(percentile(time_deltas, 0.50), 6),
            "p95": rounded(percentile(time_deltas, 0.95), 6),
            "max": rounded(max(time_deltas) if time_deltas else None, 6),
        },
        "scan_counts": scan_counts,
        "motion": motion,
        "commands": command_summary,
        "continuity": {
            "discontinuity_count": len(discontinuities),
            "discontinuities": discontinuities[:10],
        },
        "route_probe": {
            **waypoint_metadata,
            "candidate": route_candidate,
            "status": "trajectory_route_candidate" if route_candidate else "diagnostic_only",
        },
    }


def aggregate_summary(demos: Sequence[dict[str, object]]) -> dict[str, object]:
    demo_count = len(demos)
    paired_coverages = [float(demo["paired_coverage"]) for demo in demos]
    route_candidates = [demo for demo in demos if demo["route_probe"]["candidate"]]
    no_discontinuity_count = sum(int(demo["continuity"]["discontinuity_count"]) == 0 for demo in demos)
    exact_pair_count = sum(int(demo["paired_frames"]) == int(demo["command_frames"]) for demo in demos)
    return {
        "demo_count": demo_count,
        "exact_command_state_pair_count": exact_pair_count,
        "coverage_ge_98_count": sum(value >= 0.98 for value in paired_coverages),
        "route_candidate_count": len(route_candidates),
        "no_discontinuity_count": no_discontinuity_count,
        "paired_coverage_p50": rounded(percentile(paired_coverages, 0.50), 3),
        "paired_coverage_min": rounded(min(paired_coverages) if paired_coverages else None, 3),
        "total_command_frames": sum(int(demo["command_frames"]) for demo in demos),
        "total_paired_frames": sum(int(demo["paired_frames"]) for demo in demos),
        "verdict": "partial_success",
        "verdict_detail": (
            "QWD can provide exact actions plus anchored self trajectory for these DM3 POV demos. "
            "The output is route/controller-ready evidence, but not yet a Frogbot .bot route or "
            "a proven replay controller."
        ),
    }


def render_markdown(report: dict[str, object]) -> str:
    summary = report["summary"]
    lines = [
        "# QWD trajectory and route applicability probe",
        "",
        "## Verdict",
        "",
        f"- Status: `{summary['verdict']}`.",
        f"- Demos measured: `{summary['demo_count']}`.",
        f"- Exact command/state frame matches: `{summary['exact_command_state_pair_count']}`.",
        f"- Coverage >= 98%: `{summary['coverage_ge_98_count']}`.",
        f"- Route candidates after waypoint downsampling: `{summary['route_candidate_count']}`.",
        f"- No-discontinuity demos: `{summary['no_discontinuity_count']}`.",
        "",
        summary["verdict_detail"],
        "",
        "## Method",
        "",
        "- Decode exact outgoing commands with `tools/qwd_usercmd/qwd_usercmd.py`.",
        "- Recover self-player `svc_playerinfo` only at QWD network-body offset `8`.",
        "- Pair commands and states by QWD frame order and measure absolute time deltas.",
        "- Split discontinuities instead of hiding teleport, respawn, or parser-confidence breaks.",
        "- Downsample continuous trajectories into geometric waypoints at the configured spacing.",
        "",
        "## Per-demo results",
        "",
        "| demo | commands | states | paired | coverage | p50 speed | p95 speed | discontinuities | waypoints | status |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for demo in report["demos"]:
        speed = demo["motion"]["speed_qu_per_s"]
        route = demo["route_probe"]
        lines.append(
            "| {demo} | {commands} | {states} | {paired} | {coverage:.3f} | {p50} | {p95} | {disc} | {waypoints} | {status} |".format(
                demo=demo["demo"],
                commands=demo["command_frames"],
                states=demo["state_frames"],
                paired=demo["paired_frames"],
                coverage=demo["paired_coverage"],
                p50=speed["p50"],
                p95=speed["p95"],
                disc=demo["continuity"]["discontinuity_count"],
                waypoints=route["waypoint_count"],
                status=route["status"],
            )
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "This works as a measurement bridge: POV QWDs can provide exact human action labels and a plausible self trajectory on the same frames. The result can seed route and controller probes.",
            "",
            "This does not yet mean a Frogbot can replay the movement. Applying it to Frogbots still needs semantic route mapping, controller execution under server physics, and stop conditions that reject route or combat regressions.",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Measure QWD POV trajectory/route applicability.")
    parser.add_argument("--demo-root", type=Path, required=True, help="Directory containing local QWD demos.")
    parser.add_argument("--pattern", default="dm3_*.qwd", help="Glob pattern relative to --demo-root.")
    parser.add_argument("--output-json", type=Path, required=True, help="Write compact evidence JSON.")
    parser.add_argument("--output-md", type=Path, required=True, help="Write compact evidence Markdown.")
    parser.add_argument(
        "--raw-output-dir",
        type=Path,
        help="Optional ignored artifact directory for paired sample NDJSON and waypoint JSON exports.",
    )
    parser.add_argument("--waypoint-spacing", type=float, default=64.0, help="Waypoint downsampling spacing in qu.")
    return parser.parse_args(list(argv))


def main(argv: Iterable[str] = sys.argv[1:]) -> int:
    args = parse_args(argv)
    demos = sorted(args.demo_root.glob(args.pattern))
    if not demos:
        raise SystemExit(f"No demos matched {args.demo_root / args.pattern}.")

    results = [
        summarize_demo(path, waypoint_spacing_qu=args.waypoint_spacing, raw_output_dir=args.raw_output_dir)
        for path in demos
    ]
    report = {
        "schema": SCHEMA,
        "source": {
            "demo_root_label": str(args.demo_root.name),
            "pattern": args.pattern,
            "waypoint_spacing_qu": args.waypoint_spacing,
        },
        "summary": aggregate_summary(results),
        "demos": results,
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.output_md.write_text(render_markdown(report) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
