"""Shared FBMOVEPROBE log parsing.

Single source of truth for the FBMOVEPROBE_CMD / _REPLAY_EVENT / _QWD_EVENT
screen.log line formats. Factored out of run_frobodm2_lab.py so the live
telemetry sidecar (telemetry_ws.py) and the post-run pipeline parse with the
SAME regex + field mapping and cannot drift (the readings must stay
cross-checkable against trace.csv).

parse_moveprobe_command_line() is the per-line primitive used by the live
tailer; parse_moveprobe_command_logs() is the whole-log wrapper the post-run
pipeline always used.
"""

from __future__ import annotations

import re

MOVEPROBE_COMMAND_RE = re.compile(
    r"FBMOVEPROBE_CMD\s+"
    r"time=(?P<time>-?\d+(?:\.\d+)?)\s+"
    r"ed=(?P<ed>\d+)\s+"
    r"name=(?P<name>.*?)\s+"
    r"mode=(?P<mode>-?\d+)\s+"
    r"msec=(?P<msec>-?\d+)\s+"
    r"angles=(?P<pitch>-?\d+(?:\.\d+)?),(?P<yaw>-?\d+(?:\.\d+)?),(?P<roll>-?\d+(?:\.\d+)?)\s+"
    r"move=(?P<forward>-?\d+),(?P<side>-?\d+),(?P<up>-?\d+)\s+"
    r"buttons=(?P<buttons>\d+)\s+"
    r"impulse=(?P<impulse>-?\d+)"
    r"(?:\s+diag=(?P<route_yaw>-?\d+(?:\.\d+)?),(?P<view_yaw>-?\d+(?:\.\d+)?),"
    r"(?P<yaw_delta>-?\d+(?:\.\d+)?),(?P<backward>\d+))?"
    r"(?:\s+route=(?P<linked_marker>-?\d+),(?P<touch_marker>-?\d+),"
    r"(?P<goal_ed>-?\d+),(?P<goal_marker>-?\d+),(?P<path_state>-?\d+),"
    r"(?P<bot_state>-?\d+),(?P<blocked>\d+),(?P<dir_speed>-?\d+(?:\.\d+)?))?"
    r"(?:\s+water=(?P<waterlevel>-?\d+),(?P<watertype>-?\d+),(?P<player_flags>-?\d+),"
    r"(?P<swim_arrow>-?\d+),(?P<emitted_upmove>-?\d+(?:\.\d+)?),"
    r"(?P<velocity_x>-?\d+(?:\.\d+)?),(?P<velocity_y>-?\d+(?:\.\d+)?),(?P<velocity_z>-?\d+(?:\.\d+)?),"
    r"(?P<dir_move_x>-?\d+(?:\.\d+)?),(?P<dir_move_y>-?\d+(?:\.\d+)?),(?P<dir_move_z>-?\d+(?:\.\d+)?))?"
    r"(?:\s+probe=(?P<probe_active>\d+),(?P<probe_on_ground>\d+),"
    r"(?P<probe_since_ground>-?\d+(?:\.\d+)?),(?P<probe_since_air>-?\d+(?:\.\d+)?),"
    r"(?P<probe_scale>-?\d+(?:\.\d+)?))?"
    r"(?:\s+qwd=(?P<qwd_active>\d+),(?P<qwd_index>-?\d+),(?P<qwd_count>-?\d+),"
    r"(?P<qwd_distance>-?\d+(?:\.\d+)?),(?P<qwd_advanced>-?\d+),(?P<qwd_complete>\d+),"
    r"(?P<qwd_active_seconds>-?\d+(?:\.\d+)?))?"
    r"(?:\s+replay=(?P<replay_active>\d+),(?P<replay_complete>\d+),(?P<replay_cursor>-?\d+),"
    r"(?P<replay_count>-?\d+),(?P<replay_divergence>-?\d+(?:\.\d+)?),"
    r"(?P<replay_exp_x>-?\d+(?:\.\d+)?),(?P<replay_exp_y>-?\d+(?:\.\d+)?),(?P<replay_exp_z>-?\d+(?:\.\d+)?),"
    r"(?P<replay_div_h>-?\d+(?:\.\d+)?),(?P<replay_div_v>-?\d+(?:\.\d+)?))?"
    r"(?:\s+origin=(?P<bot_x>-?\d+(?:\.\d+)?),(?P<bot_y>-?\d+(?:\.\d+)?),(?P<bot_z>-?\d+(?:\.\d+)?))?"
)


MOVEPROBE_REPLAY_EVENT_RE = re.compile(
    r"FBMOVEPROBE_REPLAY_EVENT\s+"
    r"time=(?P<time>-?\d+(?:\.\d+)?)\s+"
    r"ed=(?P<ed>\d+)\s+"
    r"name=(?P<name>.*?)\s+"
    r"event=(?P<event>[A-Za-z_]+)\s+"
    r"cursor=(?P<cursor>-?\d+)\s+"
    r"count=(?P<count>-?\d+)\s+"
    r"divergence=(?P<divergence>-?\d+(?:\.\d+)?)\s+"
    r"divergence_h=(?P<divergence_h>-?\d+(?:\.\d+)?)\s+"
    r"divergence_v=(?P<divergence_v>-?\d+(?:\.\d+)?)\s+"
    r"origin=(?P<origin_x>-?\d+(?:\.\d+)?),(?P<origin_y>-?\d+(?:\.\d+)?),(?P<origin_z>-?\d+(?:\.\d+)?)\s+"
    r"expected=(?P<expected_x>-?\d+(?:\.\d+)?),(?P<expected_y>-?\d+(?:\.\d+)?),(?P<expected_z>-?\d+(?:\.\d+)?)"
)


MOVEPROBE_QWD_EVENT_RE = re.compile(
    r"FBMOVEPROBE_QWD_EVENT\s+"
    r"time=(?P<time>-?\d+(?:\.\d+)?)\s+"
    r"ed=(?P<ed>\d+)\s+"
    r"name=(?P<name>.*?)\s+"
    r"event=(?P<event>[A-Za-z_]+)\s+"
    r"target=(?P<target>-?\d+)\s+"
    r"next=(?P<next>-?\d+)\s+"
    r"count=(?P<count>-?\d+)\s+"
    r"distance=(?P<distance>-?\d+(?:\.\d+)?)\s+"
    r"advanced=(?P<advanced>-?\d+)\s+"
    r"active=(?P<active>\d+)\s+"
    r"complete=(?P<complete>\d+)\s+"
    r"active_seconds=(?P<active_seconds>-?\d+(?:\.\d+)?)\s+"
    r"origin=(?P<origin_x>-?\d+(?:\.\d+)?),(?P<origin_y>-?\d+(?:\.\d+)?),(?P<origin_z>-?\d+(?:\.\d+)?)"
)


def parse_moveprobe_command_line(line: str) -> dict[str, object] | None:
    """Parse one screen.log line; None when it is not an FBMOVEPROBE_CMD line."""
    match = MOVEPROBE_COMMAND_RE.search(line)
    if not match:
        return None
    groups = match.groupdict()
    row: dict[str, object] = {
        "time_s": float(groups["time"]),
        "ed": int(groups["ed"]),
        "name": groups["name"].strip(),
        "mode": int(groups["mode"]),
        "msec": int(groups["msec"]),
        "angles": {
            "pitch": float(groups["pitch"]),
            "yaw": float(groups["yaw"]),
            "roll": float(groups["roll"]),
        },
        "move": {
            "forward": int(groups["forward"]),
            "side": int(groups["side"]),
            "up": int(groups["up"]),
        },
        "buttons": int(groups["buttons"]),
        "impulse": int(groups["impulse"]),
    }
    if groups.get("route_yaw") is not None:
        row["diagnostics"] = {
            "route_yaw": float(groups["route_yaw"]),
            "view_yaw": float(groups["view_yaw"]),
            "yaw_delta": float(groups["yaw_delta"]),
            "backward": bool(int(groups["backward"])),
        }
    if groups.get("linked_marker") is not None:
        row["route_state"] = {
            "linked_marker": int(groups["linked_marker"]),
            "touch_marker": int(groups["touch_marker"]),
            "goal_ed": int(groups["goal_ed"]),
            "goal_marker": int(groups["goal_marker"]),
            "path_state": int(groups["path_state"]),
            "bot_state": int(groups["bot_state"]),
            "blocked": bool(int(groups["blocked"])),
            "dir_speed": float(groups["dir_speed"]),
        }
    if groups.get("waterlevel") is not None:
        row["water_state"] = {
            "waterlevel": int(groups["waterlevel"]),
            "watertype": int(groups["watertype"]),
            "flags": int(groups["player_flags"]),
            "swim_arrow": int(groups["swim_arrow"]),
            "emitted_upmove": float(groups["emitted_upmove"]),
            "velocity": {
                "x": float(groups["velocity_x"]),
                "y": float(groups["velocity_y"]),
                "z": float(groups["velocity_z"]),
            },
            "dir_move": {
                "x": float(groups["dir_move_x"]),
                "y": float(groups["dir_move_y"]),
                "z": float(groups["dir_move_z"]),
            },
        }
    if groups.get("probe_active") is not None:
        row["probe_state"] = {
            "transition_active": bool(int(groups["probe_active"])),
            "on_ground": bool(int(groups["probe_on_ground"])),
            "since_ground_s": float(groups["probe_since_ground"]),
            "since_air_s": float(groups["probe_since_air"]),
            "transition_scale": float(groups["probe_scale"]),
        }
    if groups.get("qwd_active") is not None:
        row["qwd_state"] = {
            "active": bool(int(groups["qwd_active"])),
            "control_point_index": int(groups["qwd_index"]),
            "control_point_count": int(groups["qwd_count"]),
            "distance_qu": float(groups["qwd_distance"]),
            "advanced_control_points": int(groups["qwd_advanced"]),
            "complete": bool(int(groups["qwd_complete"])),
            "active_seconds": float(groups["qwd_active_seconds"]),
        }
    if groups.get("replay_active") is not None:
        row["replay_state"] = {
            "active": bool(int(groups["replay_active"])),
            "complete": bool(int(groups["replay_complete"])),
            "cursor": int(groups["replay_cursor"]),
            "frame_count": int(groups["replay_count"]),
            "divergence_qu": float(groups["replay_divergence"]),
            "divergence_h_qu": float(groups["replay_div_h"]),
            "divergence_v_qu": float(groups["replay_div_v"]),
            "expected_origin": {
                "x": float(groups["replay_exp_x"]),
                "y": float(groups["replay_exp_y"]),
                "z": float(groups["replay_exp_z"]),
            },
        }
    if groups.get("bot_x") is not None:
        row["origin"] = {
            "x": float(groups["bot_x"]),
            "y": float(groups["bot_y"]),
            "z": float(groups["bot_z"]),
        }
    return row


def parse_moveprobe_command_logs(screen_log: str) -> list[dict[str, object]]:
    commands: list[dict[str, object]] = []
    for line in screen_log.splitlines():
        row = parse_moveprobe_command_line(line)
        if row is not None:
            commands.append(row)
    return commands


def parse_moveprobe_replay_event_logs(screen_log: str) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for line in screen_log.splitlines():
        match = MOVEPROBE_REPLAY_EVENT_RE.search(line)
        if not match:
            continue
        groups = match.groupdict()
        events.append(
            {
                "time_s": float(groups["time"]),
                "ed": int(groups["ed"]),
                "name": groups["name"].strip(),
                "event": groups["event"],
                "cursor": int(groups["cursor"]),
                "frame_count": int(groups["count"]),
                "divergence_qu": float(groups["divergence"]),
                "divergence_h_qu": float(groups["divergence_h"]),
                "divergence_v_qu": float(groups["divergence_v"]),
                "origin": {
                    "x": float(groups["origin_x"]),
                    "y": float(groups["origin_y"]),
                    "z": float(groups["origin_z"]),
                },
                "expected_origin": {
                    "x": float(groups["expected_x"]),
                    "y": float(groups["expected_y"]),
                    "z": float(groups["expected_z"]),
                },
            }
        )
    return events


def parse_moveprobe_qwd_event_logs(screen_log: str) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for line in screen_log.splitlines():
        match = MOVEPROBE_QWD_EVENT_RE.search(line)
        if not match:
            continue
        groups = match.groupdict()
        events.append(
            {
                "time_s": float(groups["time"]),
                "ed": int(groups["ed"]),
                "name": groups["name"].strip(),
                "event": groups["event"],
                "target_index": int(groups["target"]),
                "next_index": int(groups["next"]),
                "control_point_count": int(groups["count"]),
                "distance_qu": float(groups["distance"]),
                "advanced_control_points": int(groups["advanced"]),
                "active": bool(int(groups["active"])),
                "complete": bool(int(groups["complete"])),
                "active_seconds": float(groups["active_seconds"]),
                "origin": {
                    "x": float(groups["origin_x"]),
                    "y": float(groups["origin_y"]),
                    "z": float(groups["origin_z"]),
                },
            }
        )
    return events
