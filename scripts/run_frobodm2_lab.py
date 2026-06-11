#!/usr/bin/env python3
"""Run the repeatable Komodobots bot smoke lab.

This script is intentionally one-command from the repo root. Prefer the neutral
entry point:

    python scripts/run_bot_lab.py --map dm3

The original frobodm2 path remains valid:

    python scripts/run_frobodm2_lab.py

It starts a temporary MVDSV/KTX server on servexeri, drives Frogbot spawning via
the minimal QuakeWorld client shim, copies the resulting MVD back under
artifacts/lab-runs/<run-id>/, parses it with qw-analyze-v20 in WSL, writes a
small Markdown summary, and stops only the lab screen session it created.

The default map remains frobodm2 because it has a known route file. Use
`--map <name>` for other maps that already have Frogbot route files, such as
`dm3`. Stock `dm2` is intentionally not a Frogbot target here.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from demo_archive import archive_run_demo
from extract_movement_metrics import write_movement_metrics
from moveprobe_parse import (
    parse_moveprobe_assign_logs,
    parse_moveprobe_command_logs,
    parse_moveprobe_perslot_error_logs,
    parse_moveprobe_qwd_event_logs,
    parse_moveprobe_replay_event_logs,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
SHIM_PATH = REPO_ROOT / "experiments" / "qw_min_client.py"
ARTIFACT_ROOT = REPO_ROOT / "artifacts" / "lab-runs"
DEFAULT_ANALYZER = "/home/xerial/qw-sim/bin/qw-analyze-v20"
# Recorded trick attempts are committed under tricks/dm3/ and mirrored into the
# local nQuake demo tree so they are watchable in ezQuake beside the human tricks.
TRICKS_DM3_DIR = REPO_ROOT / "tricks" / "dm3"
NQUAKE_TRICKS_DM3_DIR = Path(r"C:\nQuake\qw\matchinfo\demos\tricks\dm3")


REMOTE_SCRIPT = r"""#!/usr/bin/env bash
set -euo pipefail

run_id="$1"
port="$2"
duration="$3"
bot_count="$4"
bot_spacing="$5"
map_name="$6"
moveprobe_mode="$7"
moveprobe_yaw="$8"
moveprobe_forwardmove="$9"
moveprobe_sidemove="${10}"
moveprobe_upmove="${11}"
moveprobe_log_commands="${12}"
moveprobe_log_interval="${13}"
moveprobe_transition_scale="${14}"
moveprobe_transition_window="${15}"
moveprobe_qwd_waypoints_b64="${16}"
moveprobe_qwd_point_radius="${17}"
moveprobe_qwd_start_radius="${18}"
if [ "$moveprobe_qwd_waypoints_b64" = "-" ]; then
  moveprobe_qwd_waypoints=""
else
  moveprobe_qwd_waypoints="$(printf '%s' "$moveprobe_qwd_waypoints_b64" | base64 -d)"
fi
moveprobe_replay_file="${19:-}"
if [ "$moveprobe_replay_file" = "-" ]; then
  moveprobe_replay_file=""
fi
moveprobe_lookahead_frames="${20:-4}"
moveprobe_corr_deadband="${21:-16}"
moveprobe_corr_yaw_max="${22:-3}"
moveprobe_extra_cvars_b64="${23:-}"
timelimit_min="${24:-1}"
matchless_val="${25:-1}"
mvdsv_bin="${26:-mvdsv}"

session="komodobots_lab_${map_name}_${port}_${run_id}"
rundir="$HOME/komodobots-lab/runs/$run_id"
nq="$HOME/nquakesv"
# Keep the +exec filename short. The deployed MVDSV/KTX build crashed before
# executing very long generated config names.
cfg_name="kbot_${map_name}_${port}.cfg"
cfg_path="$nq/ktx/$cfg_name"

mkdir -p "$rundir"
touch "$rundir/start.marker"

log() {
  printf '[remote] %s\n' "$*"
}

session_exists() {
  screen -ls | grep -q "[.]${session}[[:space:]]"
}

send_cmd() {
  local cmd="$1"
  local delay="${2:-0.5}"
  screen -S "$session" -p 0 -X stuff "$(printf '\025%s\r' "$cmd")"
  sleep "$delay"
}

# Lab lock (LD-F2 #96): the experiment harness has absolute priority on the
# serial lab queue. While this lock is fresh, the dashboard control bridge
# refuses every mutating op. Written at server start, removed in cleanup
# (the EXIT trap covers the failure paths) and again on the success path.
lab_lock="$HOME/komodobots-lab/lab.lock"
acquire_lab_lock() {
  mkdir -p "$HOME/komodobots-lab"
  printf '{"owner":"harness","run_id":"%s","pid":%s,"ts":"%s"}\n' \
    "$run_id" "$$" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$lab_lock"
}
release_lab_lock() {
  # Only remove a lock this run wrote; never clobber another owner's lock.
  if [ -f "$lab_lock" ] && grep -q "\"run_id\":\"${run_id}\"" "$lab_lock"; then
    rm -f -- "$lab_lock"
  fi
}

cleanup() {
  set +e
  if session_exists; then
    send_cmd "sv_demostop" 0.5
    screen -S "$session" -p 0 -X hardcopy "$rundir/hardcopy.cleanup.txt"
    screen -S "$session" -X quit
  fi
  release_lab_lock
}
trap cleanup EXIT

if session_exists; then
  echo "Screen session already exists: $session" >&2
  exit 2
fi

# Dashboard sessions (control bridge, LD-F2 #96) use the bare screen name
# komodobots_lab_<port>; the harness must not start on a port one occupies.
if screen -ls | grep -q "[.]komodobots_lab_${port}[[:space:]]"; then
  echo "Lab port $port is held by a dashboard session (komodobots_lab_${port}); pick another port or stop it" >&2
  exit 2
fi

if [ ! -x "$nq/$mvdsv_bin" ]; then
  echo "Missing executable: $nq/$mvdsv_bin" >&2
  exit 3
fi
if [ ! -f "$nq/qw/maps/${map_name}.bsp" ]; then
  echo "Missing map: $nq/qw/maps/${map_name}.bsp" >&2
  exit 4
fi
if [ ! -f "$rundir/qw_min_client.py" ]; then
  echo "Missing uploaded shim: $rundir/qw_min_client.py" >&2
  exit 6
fi

route_file="$nq/ktx/bots/maps/${map_name}.bot"
route_file_present_original=0
route_file_used=0
if [ -f "$route_file" ]; then
  route_file_present_original=1
  route_file_used=1
else
  log "warning: missing route file $route_file; attempting map anyway"
fi

# Prewar (k_matchless 0): k_fb_enabled MUST be 1 at world spawn. Flipping it at
# runtime with no players triggers a changelevel in client.c that segfaults this
# KTX build in non-matchless mode (fault at gedict+0x2ac8, hoonymode spawn-assign
# region; 100% reproducible 2026-06-09). Matchless keeps the proven flip flow.
fb_enabled_at_spawn=0
if [ "$matchless_val" = "0" ]; then
  fb_enabled_at_spawn=1
fi

cat > "$cfg_path" <<EOF
// Auto-generated Komodobots $map_name lab config $run_id
hostname "komodobots-lab:$port"
set k_motd1 "Komodobots lab $run_id"
set k_matchless $matchless_val
set k_use_matchless_dir 1
set k_defmode ffa
set k_mode 3
set k_defmap $map_name
set k_fb_enabled $fb_enabled_at_spawn
set k_count 0
set k_matchless_countdown 0
set k_fb_moveprobe_mode $moveprobe_mode
set k_fb_moveprobe_yaw $moveprobe_yaw
set k_fb_moveprobe_forwardmove $moveprobe_forwardmove
set k_fb_moveprobe_sidemove $moveprobe_sidemove
set k_fb_moveprobe_upmove $moveprobe_upmove
set k_fb_moveprobe_log_commands $moveprobe_log_commands
set k_fb_moveprobe_log_interval $moveprobe_log_interval
set k_fb_moveprobe_transition_scale $moveprobe_transition_scale
set k_fb_moveprobe_transition_window $moveprobe_transition_window
set k_fb_moveprobe_qwd_waypoints "$moveprobe_qwd_waypoints"
set k_fb_moveprobe_qwd_point_radius $moveprobe_qwd_point_radius
set k_fb_moveprobe_qwd_start_radius $moveprobe_qwd_start_radius
set k_fb_moveprobe_replay_file "$moveprobe_replay_file"
set k_fb_moveprobe_lookahead_frames $moveprobe_lookahead_frames
set k_fb_moveprobe_corr_deadband $moveprobe_corr_deadband
set k_fb_moveprobe_corr_yaw_max $moveprobe_corr_yaw_max
timelimit $timelimit_min
fraglimit 0
samelevel 1
set demo_tmp_record 1
set k_demo_mintime 0
set k_demotxt_format json
sv_demotxt 2
sv_demofps 77
sv_demodir demos
// QTV: serve mvdsv's built-in spectator stream on the game port. This is a passive
// re-broadcast of the MVD the run already records (sv_demoeasyrecord); a QTV viewer
// is not a player and sends no input, so bots, physics, and the measurement are
// unchanged (only marginal broadcast CPU). Game-port == stream-port matches the live
// servexeri model (ktx/port_2850x.cfg) and is the one port ufw opens (28599/tcp, LAN).
// Watch in ezQuake: /qtvplay <host>:$port  -- bare host:port, NO "tcp:" prefix.
// QTV is a passive read-only re-broadcast of the MVD the server already records;
// relays/spectators connect over TCP and never enter the match, so bot physics and
// all measurements are unchanged. maxstreams>0 + empty password let the local-hub
// relay connect unauthenticated over loopback. (Mirrors the 28610 lab's qtv block.)
set qtv_streamport $port
set qtv_maxstreams 8
set qtv_password ""
serverinfo hostname "komodobots-lab:$port"
EOF
if [ -n "${moveprobe_extra_cvars_b64:-}" ] && [ "${moveprobe_extra_cvars_b64:-}" != "-" ]; then
  printf '%s' "$moveprobe_extra_cvars_b64" | base64 -d >> "$cfg_path"
fi
cp "$cfg_path" "$rundir/lab.cfg"

cat > "$rundir/run.env" <<EOF
RUN_ID=$run_id
SESSION=$session
PORT=$port
MAP=$map_name
RUNDIR=$rundir
CFG=$cfg_path
ROUTE_FILE=$route_file
ROUTE_FILE_PRESENT_ORIGINAL=$route_file_present_original
ROUTE_FILE_USED=$route_file_used
MOVEPROBE_MODE=$moveprobe_mode
MOVEPROBE_YAW=$moveprobe_yaw
MOVEPROBE_FORWARDMOVE=$moveprobe_forwardmove
MOVEPROBE_SIDEMOVE=$moveprobe_sidemove
MOVEPROBE_UPMOVE=$moveprobe_upmove
MOVEPROBE_LOG_COMMANDS=$moveprobe_log_commands
MOVEPROBE_LOG_INTERVAL=$moveprobe_log_interval
MOVEPROBE_TRANSITION_SCALE=$moveprobe_transition_scale
MOVEPROBE_TRANSITION_WINDOW=$moveprobe_transition_window
MOVEPROBE_QWD_WAYPOINTS=$moveprobe_qwd_waypoints
MOVEPROBE_QWD_POINT_RADIUS=$moveprobe_qwd_point_radius
MOVEPROBE_QWD_START_RADIUS=$moveprobe_qwd_start_radius
MOVEPROBE_REPLAY_FILE=$moveprobe_replay_file
START_UTC=$(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF

acquire_lab_lock
log "starting $session on port $port"
cd "$nq"
screen -L -Logfile "$rundir/screen.log" -dmS "$session" "./$mvdsv_bin" -port "$port" -mem 64 -game ktx +exec "$cfg_name"

server_up=0
for _ in $(seq 1 40); do
  qs="$(quakestat -qws "localhost:$port" -P -nh 2>/dev/null || true)"
  printf '%s\n' "$qs" > "$rundir/quakestat.last"
  if [ -n "$qs" ] && ! printf '%s' "$qs" | grep -q 'DOWN'; then
    server_up=1
    break
  fi
  sleep 0.5
done

if [ "$server_up" -ne 1 ]; then
  echo "Server did not come up on port $port" >&2
  exit 7
fi

send_cmd "set k_fb_enabled 1"
send_cmd "set k_fb_autoadd_limit 0"
send_cmd "set k_fb_auto_delay 1"
send_cmd "set k_fb_skill 10"
send_cmd "map $map_name" 1.0
# Re-assert after map load: the map's mode config re-execs and resets these, so
# the pre-map values are lost. With autoadd_limit/autoremove_at at 0 the Frogbot
# auto-fill stays off, keeping exactly the bots the client shim adds (no extra
# bots crowding a single-bot acceleration measurement).
send_cmd "set k_fb_autoadd_limit 0"
send_cmd "set k_fb_autoremove_at 0"
# Keep the idle client shim connected for the whole run. The shim never moves,
# so KTX/mvdsv drop it around 60s, which stops the server demo (recording is
# tied to the connected client). Raise the network timeout (needs the `set`
# prefix -- a bare `sv_timeout` is an unknown command) and disable the idle
# kicks so long single-bot acceleration runs record past 60s.
# sv_getrealip 0 is the load-bearing one: with it at the default 1, mvdsv waits
# on a real-IP handshake the minimal client shim never completes, so the shim
# never reaches SV_Login, keeps cl->logged==0, and is dropped at the hardcoded
# 60s login timeout (which also stops the server demo and bot simulation). With
# it off the connect flow logs the shim in immediately and it stays for the run.
send_cmd "set sv_getrealip 0"
send_cmd "set sv_timeout 3600"
send_cmd "set k_idletime 0"
send_cmd "set k_matchless_max_idle_time 0"
send_cmd "sv_democancel"
send_cmd "sv_demoeasyrecord komodobots_${map_name}_${run_id}" 1.0
send_cmd "status"
screen -S "$session" -p 0 -X hardcopy "$rundir/hardcopy.before-client.txt"

log "running client shim"
python3 "$rundir/qw_min_client.py" "$port" \
  --host 127.0.0.1 \
  --run-for "$duration" \
  --bot-count "$bot_count" \
  --bot-spacing "$bot_spacing" \
  > "$rundir/pyclient.stdout" \
  2> "$rundir/pyclient.stderr"

send_cmd "status"
screen -S "$session" -p 0 -X hardcopy "$rundir/hardcopy.after-client.txt"
send_cmd "sv_demostop" 2.0
send_cmd "status"
screen -S "$session" -p 0 -X hardcopy "$rundir/hardcopy.final.txt"

demo="$(
  find "$nq/ktx/demos" -maxdepth 1 -type f -name '*.mvd' -newer "$rundir/start.marker" -printf '%T@ %p\n' \
    | sort -n \
    | tail -1 \
    | cut -d' ' -f2-
)"

if [ -z "$demo" ] || [ ! -s "$demo" ]; then
  echo "No non-empty MVD was produced after $rundir/start.marker" >&2
  exit 8
fi

cp -- "$demo" "$rundir/demo.mvd"
printf '%s\n' "$demo" > "$rundir/demo.remote-path.txt"
if [ -f "${demo%.mvd}.txt" ]; then
  cp -- "${demo%.mvd}.txt" "$rundir/demo.txt"
fi
stat -c '%s' "$rundir/demo.mvd" > "$rundir/demo.size"
sha256sum "$rundir/demo.mvd" > "$rundir/demo.sha256"

log "stopping $session"
screen -S "$session" -X quit
trap - EXIT
release_lab_lock

cat >> "$rundir/run.env" <<EOF
END_UTC=$(date -u +%Y-%m-%dT%H:%M:%SZ)
DEMO_REMOTE_PATH=$demo
EOF
"""


def run(
    args: list[str],
    *,
    input_text: str | None = None,
    cwd: Path | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    if input_text is None:
        proc = subprocess.run(
            args,
            cwd=str(cwd) if cwd else None,
            text=True,
            capture_output=True,
        )
    else:
        raw_proc = subprocess.run(
            args,
            input=input_text.replace("\r\n", "\n").encode("utf-8"),
            cwd=str(cwd) if cwd else None,
            capture_output=True,
        )
        proc = subprocess.CompletedProcess(
            raw_proc.args,
            raw_proc.returncode,
            raw_proc.stdout.decode("utf-8", "replace"),
            raw_proc.stderr.decode("utf-8", "replace"),
        )
    if check and proc.returncode != 0:
        rendered = " ".join(args)
        raise RuntimeError(
            f"Command failed ({proc.returncode}): {rendered}\n"
            f"stdout:\n{proc.stdout}\n"
            f"stderr:\n{proc.stderr}"
        )
    return proc


def require_tool(name: str) -> None:
    if shutil.which(name) is None:
        raise RuntimeError(f"Required tool not found on PATH: {name}")


def utc_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def powershell_safe_path(path: Path) -> str:
    return str(path.resolve())


def to_wsl_path(path: Path) -> str:
    resolved = path.resolve()
    drive = resolved.drive.rstrip(":").lower()
    if not drive:
        raise RuntimeError(f"Cannot convert path to WSL form: {resolved}")
    rest = resolved.relative_to(resolved.anchor).as_posix()
    return f"/mnt/{drive}/{rest}"


def remote_port_is_down(host: str, port: int) -> bool:
    proc = run(
        ["ssh", host, f"quakestat -qws localhost:{port} -P -nh 2>/dev/null || true"],
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Could not query port {port} on {host}: {proc.stderr.strip()}")
    output = proc.stdout.strip()
    return not output or "DOWN" in output


def choose_port(host: str, requested_port: int, explicit: bool) -> int:
    if remote_port_is_down(host, requested_port):
        return requested_port
    if explicit:
        raise RuntimeError(f"Requested port {requested_port} is already in use on {host}.")

    for port in range(requested_port + 1, requested_port + 51):
        if remote_port_is_down(host, port):
            return port
    raise RuntimeError(f"No free lab port found in {requested_port}-{requested_port + 50}.")


def scp_from_remote(host: str, run_id: str, local_run_dir: Path) -> None:
    local_run_dir.mkdir(parents=True, exist_ok=True)
    source = f"{host}:komodobots-lab/runs/{run_id}/*"
    proc = run(["scp", source, powershell_safe_path(local_run_dir)], check=False)
    (local_run_dir / "scp.stdout").write_text(proc.stdout, encoding="utf-8")
    (local_run_dir / "scp.stderr").write_text(proc.stderr, encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(f"scp failed with exit {proc.returncode}; see scp.stderr")


def run_analyzer(local_run_dir: Path, distro: str, analyzer: str) -> dict[str, int]:
    demo = local_run_dir / "demo.mvd"
    if not demo.is_file() or demo.stat().st_size == 0:
        raise RuntimeError(f"Missing non-empty demo: {demo}")

    wsl_demo = to_wsl_path(demo)
    exits: dict[str, int] = {}
    for mode, output_name in (
        ("json", "analysis.json"),
        ("md", "analysis.md"),
        ("events", "events.txt"),
    ):
        output = local_run_dir / output_name
        error = local_run_dir / f"{output_name}.stderr"
        proc = run(
            ["wsl", "-d", distro, "--", analyzer, "-format", mode, wsl_demo],
            check=False,
        )
        output.write_text(proc.stdout, encoding="utf-8")
        error.write_text(proc.stderr, encoding="utf-8")
        exits[mode] = proc.returncode

    if exits["json"] != 0:
        raise RuntimeError(f"JSON parser failed with exit {exits['json']}; see analysis.json.stderr")
    if exits["md"] != 0:
        raise RuntimeError(f"Markdown parser failed with exit {exits['md']}; see analysis.md.stderr")
    if exits["events"] not in (0, 1):
        raise RuntimeError(f"Events parser failed unexpectedly with exit {exits['events']}; see events.txt.stderr")
    return exits


def first_line(path: Path) -> str:
    if not path.exists():
        return ""
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        return handle.readline().strip()


def read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def compact_unique(values: Iterable[object], limit: int = 12) -> list[object]:
    unique = sorted(set(values))
    if len(unique) <= limit:
        return list(unique)
    return list(unique[:limit]) + [f"... {len(unique) - limit} more"]


def summarize_moveprobe_commands(commands: list[dict[str, object]]) -> dict[str, object]:
    players: dict[tuple[int, str], list[dict[str, object]]] = {}
    for command in commands:
        key = (int(command["ed"]), str(command["name"]))
        players.setdefault(key, []).append(command)

    player_rows = []
    for (ed, name), rows in sorted(players.items()):
        msec_values = [int(row["msec"]) for row in rows]
        angles = [row["angles"] for row in rows]
        moves = [row["move"] for row in rows]
        diagnostics = [row.get("diagnostics", {}) for row in rows]
        route_states = [
            row.get("route_state", {})
            for row in rows
            if isinstance(row.get("route_state", {}), dict) and row.get("route_state")
        ]
        water_states = [
            row.get("water_state", {})
            for row in rows
            if isinstance(row.get("water_state", {}), dict) and row.get("water_state")
        ]
        probe_states = [
            row.get("probe_state", {})
            for row in rows
            if isinstance(row.get("probe_state", {}), dict) and row.get("probe_state")
        ]
        qwd_states = [
            row.get("qwd_state", {})
            for row in rows
            if isinstance(row.get("qwd_state", {}), dict) and row.get("qwd_state")
        ]
        replay_states = [
            row.get("replay_state", {})
            for row in rows
            if isinstance(row.get("replay_state", {}), dict) and row.get("replay_state")
        ]
        yaw_deltas = [
            round(float(diagnostic["yaw_delta"]), 1)
            for diagnostic in diagnostics
            if "yaw_delta" in diagnostic
        ]
        backward_count = sum(
            1
            for row in rows
            if int(row["move"]["forward"]) < 0
            or bool(row.get("diagnostics", {}).get("backward", False))
        )
        player_rows.append(
            {
                "ed": ed,
                "name": name,
                "count": len(rows),
                "first_time_s": rows[0]["time_s"],
                "last_time_s": rows[-1]["time_s"],
                "msec_min": min(msec_values),
                "msec_max": max(msec_values),
                "yaw_values": compact_unique(round(float(angle["yaw"]), 1) for angle in angles),
                "forward_values": compact_unique(int(move["forward"]) for move in moves),
                "side_values": compact_unique(int(move["side"]) for move in moves),
                "up_values": compact_unique(int(move["up"]) for move in moves),
                "yaw_delta_values": compact_unique(yaw_deltas) if yaw_deltas else [],
                "backward_ratio": round(backward_count / len(rows), 3),
                "route_state": summarize_route_states(route_states),
                "water_state": summarize_water_states(water_states),
                "probe_state": summarize_probe_states(probe_states),
                "qwd_state": summarize_qwd_states(qwd_states),
                "replay_state": summarize_replay_states(replay_states),
                "button_values": compact_unique(int(row["buttons"]) for row in rows),
                "impulse_values": compact_unique(int(row["impulse"]) for row in rows),
            }
        )

    return {
        "command_count": len(commands),
        "players": player_rows,
        "commands": commands,
    }


def summarize_moveprobe_qwd_events(events: list[dict[str, object]]) -> dict[str, object]:
    players: dict[tuple[int, str], list[dict[str, object]]] = {}
    for event in events:
        key = (int(event["ed"]), str(event["name"]))
        players.setdefault(key, []).append(event)

    player_rows = []
    for (ed, name), rows in sorted(players.items()):
        event_counts: dict[str, int] = {}
        distances = [round(float(row["distance_qu"]), 3) for row in rows]
        active_seconds = [
            round(float(row["active_seconds"]), 3)
            for row in rows
            if bool(row.get("active", False)) or bool(row.get("complete", False))
        ]
        for row in rows:
            event_name = str(row["event"])
            event_counts[event_name] = event_counts.get(event_name, 0) + 1
        player_rows.append(
            {
                "ed": ed,
                "name": name,
                "count": len(rows),
                "first_time_s": rows[0]["time_s"],
                "last_time_s": rows[-1]["time_s"],
                "event_counts": dict(sorted(event_counts.items())),
                "target_index_values": compact_unique(int(row["target_index"]) for row in rows),
                "next_index_values": compact_unique(int(row["next_index"]) for row in rows),
                "control_point_count_values": compact_unique(int(row["control_point_count"]) for row in rows),
                "max_advanced_control_points": max(int(row["advanced_control_points"]) for row in rows),
                "min_distance_qu": min(distances) if distances else None,
                "max_active_seconds": max(active_seconds) if active_seconds else 0.0,
                "complete_events": sum(1 for row in rows if bool(row.get("complete", False))),
            }
        )

    return {
        "schema": "komodobots.moveprobe_qwd_events.v1",
        "event_count": len(events),
        "players": player_rows,
        "events": events,
    }


def summarize_route_states(route_states: list[dict[str, object]]) -> dict[str, object]:
    if not route_states:
        return {"sample_count": 0}

    blocked_count = sum(1 for state in route_states if bool(state.get("blocked", False)))
    return {
        "sample_count": len(route_states),
        "linked_marker_values": compact_unique(int(state.get("linked_marker", -1)) for state in route_states),
        "touch_marker_values": compact_unique(int(state.get("touch_marker", -1)) for state in route_states),
        "goal_ed_values": compact_unique(int(state.get("goal_ed", -1)) for state in route_states),
        "goal_marker_values": compact_unique(int(state.get("goal_marker", -1)) for state in route_states),
        "path_state_values": compact_unique(int(state.get("path_state", 0)) for state in route_states),
        "bot_state_values": compact_unique(int(state.get("bot_state", 0)) for state in route_states),
        "blocked_ratio": round(blocked_count / len(route_states), 3),
        "dir_speed_values": compact_unique(round(float(state.get("dir_speed", 0.0)), 3) for state in route_states),
    }


def summarize_water_states(water_states: list[dict[str, object]]) -> dict[str, object]:
    if not water_states:
        return {"sample_count": 0}

    waterlevel_gt1 = sum(1 for state in water_states if int(state.get("waterlevel", 0)) > 1)
    waterlevel_gt2 = sum(1 for state in water_states if int(state.get("waterlevel", 0)) > 2)
    swim_nonzero = sum(1 for state in water_states if int(state.get("swim_arrow", 0)) != 0)
    upmove_nonzero = sum(1 for state in water_states if abs(float(state.get("emitted_upmove", 0.0))) > 0.01)
    velocity_z = [
        round(float(state.get("velocity", {}).get("z", 0.0)), 1)
        for state in water_states
        if isinstance(state.get("velocity", {}), dict)
    ]
    dir_move_z = [
        round(float(state.get("dir_move", {}).get("z", 0.0)), 3)
        for state in water_states
        if isinstance(state.get("dir_move", {}), dict)
    ]
    return {
        "sample_count": len(water_states),
        "waterlevel_values": compact_unique(int(state.get("waterlevel", 0)) for state in water_states),
        "watertype_values": compact_unique(int(state.get("watertype", 0)) for state in water_states),
        "flags_values": compact_unique(int(state.get("flags", 0)) for state in water_states),
        "swim_arrow_values": compact_unique(int(state.get("swim_arrow", 0)) for state in water_states),
        "emitted_upmove_values": compact_unique(round(float(state.get("emitted_upmove", 0.0)), 1) for state in water_states),
        "waterlevel_gt1_ratio": round(waterlevel_gt1 / len(water_states), 3),
        "waterlevel_gt2_ratio": round(waterlevel_gt2 / len(water_states), 3),
        "swim_arrow_nonzero_ratio": round(swim_nonzero / len(water_states), 3),
        "emitted_upmove_nonzero_ratio": round(upmove_nonzero / len(water_states), 3),
        "velocity_z_values": compact_unique(velocity_z),
        "dir_move_z_values": compact_unique(dir_move_z),
    }


def summarize_probe_states(probe_states: list[dict[str, object]]) -> dict[str, object]:
    if not probe_states:
        return {"sample_count": 0}

    active_count = sum(1 for state in probe_states if bool(state.get("transition_active", False)))
    on_ground_count = sum(1 for state in probe_states if bool(state.get("on_ground", False)))
    active_scales = [
        round(float(state.get("transition_scale", 1.0)), 3)
        for state in probe_states
        if bool(state.get("transition_active", False))
    ]
    return {
        "sample_count": len(probe_states),
        "transition_active_ratio": round(active_count / len(probe_states), 3),
        "on_ground_ratio": round(on_ground_count / len(probe_states), 3),
        "active_scale_values": compact_unique(active_scales),
        "since_ground_values": compact_unique(
            round(float(state.get("since_ground_s", 999.0)), 3) for state in probe_states
        ),
        "since_air_values": compact_unique(
            round(float(state.get("since_air_s", 999.0)), 3) for state in probe_states
        ),
    }


def summarize_qwd_states(qwd_states: list[dict[str, object]]) -> dict[str, object]:
    if not qwd_states:
        return {"sample_count": 0}

    active_count = sum(1 for state in qwd_states if bool(state.get("active", False)))
    complete_count = sum(1 for state in qwd_states if bool(state.get("complete", False)))
    distances = [
        round(float(state.get("distance_qu", 999999.0)), 3)
        for state in qwd_states
        if float(state.get("distance_qu", 999999.0)) < 999999.0
    ]
    active_seconds = [
        round(float(state.get("active_seconds", 0.0)), 3)
        for state in qwd_states
        if bool(state.get("active", False)) or bool(state.get("complete", False))
    ]
    return {
        "sample_count": len(qwd_states),
        "active_ratio": round(active_count / len(qwd_states), 3),
        "complete_ratio": round(complete_count / len(qwd_states), 3),
        "control_point_count_values": compact_unique(
            int(state.get("control_point_count", 0)) for state in qwd_states
        ),
        "max_control_point_index": max(int(state.get("control_point_index", 0)) for state in qwd_states),
        "max_advanced_control_points": max(int(state.get("advanced_control_points", 0)) for state in qwd_states),
        "min_distance_qu": min(distances) if distances else None,
        "max_active_seconds": max(active_seconds) if active_seconds else 0.0,
    }


def summarize_replay_states(replay_states: list[dict[str, object]]) -> dict[str, object]:
    if not replay_states:
        return {"sample_count": 0}

    active = [s for s in replay_states if bool(s.get("active", False))]
    divergences = [round(float(s.get("divergence_qu", 0.0)), 3) for s in active]
    div_h = [round(float(s.get("divergence_h_qu", 0.0)), 3) for s in active]
    div_v = [round(float(s.get("divergence_v_qu", 0.0)), 3) for s in active]
    cursors = [int(s.get("cursor", 0)) for s in replay_states]
    frame_counts = [int(s.get("frame_count", 0)) for s in replay_states]
    return {
        "sample_count": len(replay_states),
        "active_ratio": round(len(active) / len(replay_states), 3),
        "complete_ratio": round(
            sum(1 for s in replay_states if bool(s.get("complete", False))) / len(replay_states), 3
        ),
        "frame_count": max(frame_counts) if frame_counts else 0,
        "max_cursor": max(cursors) if cursors else 0,
        "max_divergence_qu": max(divergences) if divergences else None,
        "max_divergence_h_qu": max(div_h) if div_h else None,
        "max_divergence_v_qu": max(div_v) if div_v else None,
        "final_divergence_qu": divergences[-1] if divergences else None,
        "final_divergence_h_qu": div_h[-1] if div_h else None,
        "final_divergence_v_qu": div_v[-1] if div_v else None,
    }


def write_moveprobe_command_logs(local_run_dir: Path) -> dict[str, object]:
    screen_log = (local_run_dir / "screen.log").read_text(encoding="utf-8", errors="replace")
    commands = parse_moveprobe_command_logs(screen_log)
    summary = summarize_moveprobe_commands(commands)

    json_path = local_run_dir / "moveprobe-commands.json"
    md_path = local_run_dir / "moveprobe-commands.md"
    json_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")

    lines = [
        "# Moveprobe Command Log",
        "",
        f"- Commands parsed: `{summary['command_count']}`",
        "",
    ]
    players = summary.get("players", [])
    if players:
        lines.extend(["## Players", ""])
        for player in players:
            lines.append(
                f"- `{player['name']}` ed `{player['ed']}`: `{player['count']}` commands, "
                f"time `{fmt_number(player['first_time_s'], 3)}`-`{fmt_number(player['last_time_s'], 3)}`s, "
                f"msec `{player['msec_min']}`-`{player['msec_max']}`, "
                f"yaw `{player['yaw_values']}`, "
                f"forward `{player['forward_values']}`, "
                f"side `{player['side_values']}`, "
                f"up `{player['up_values']}`, "
                f"yawDelta `{player['yaw_delta_values']}`, "
                f"backward `{fmt_percent(player['backward_ratio'])}`, "
                f"route `{player['route_state']}`, "
                f"water `{player['water_state']}`, "
                f"probe `{player['probe_state']}`, "
                f"qwd `{player['qwd_state']}`, "
                f"replay `{player['replay_state']}`, "
                f"buttons `{player['button_values']}`, "
                f"impulses `{player['impulse_values']}`"
            )
    else:
        lines.append("- No `FBMOVEPROBE_CMD` lines found in `screen.log`.")

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


def write_moveprobe_qwd_event_logs(local_run_dir: Path) -> dict[str, object]:
    screen_log = (local_run_dir / "screen.log").read_text(encoding="utf-8", errors="replace")
    events = parse_moveprobe_qwd_event_logs(screen_log)
    summary = summarize_moveprobe_qwd_events(events)

    json_path = local_run_dir / "moveprobe-qwd-events.json"
    md_path = local_run_dir / "moveprobe-qwd-events.md"
    json_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")

    lines = [
        "# Moveprobe QWD Event Log",
        "",
        f"- Events parsed: `{summary['event_count']}`",
        "",
    ]
    players = summary.get("players", [])
    if players:
        lines.extend(["## Players", ""])
        for player in players:
            lines.append(
                f"- `{player['name']}` ed `{player['ed']}`: `{player['count']}` events, "
                f"time `{fmt_number(player['first_time_s'], 3)}`-`{fmt_number(player['last_time_s'], 3)}`s, "
                f"events `{player['event_counts']}`, "
                f"targets `{player['target_index_values']}`, "
                f"next `{player['next_index_values']}`, "
                f"controlPointCounts `{player['control_point_count_values']}`, "
                f"maxAdvanced `{player['max_advanced_control_points']}`, "
                f"minDistance `{player['min_distance_qu']}`, "
                f"maxActiveSeconds `{player['max_active_seconds']}`, "
                f"completeEvents `{player['complete_events']}`"
            )
    else:
        lines.append("- No `FBMOVEPROBE_QWD_EVENT` lines found in `screen.log`.")

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


def write_moveprobe_replay_event_logs(local_run_dir: Path) -> dict[str, object]:
    screen_log = (local_run_dir / "screen.log").read_text(encoding="utf-8", errors="replace")
    events = parse_moveprobe_replay_event_logs(screen_log)

    players: dict[tuple[int, str], list[dict[str, object]]] = {}
    for event in events:
        players.setdefault((int(event["ed"]), str(event["name"])), []).append(event)

    player_rows = []
    for (ed, name), rows in sorted(players.items()):
        complete = [r for r in rows if r["event"] == "complete"]
        player_rows.append(
            {
                "ed": ed,
                "name": name,
                "event_counts": compact_unique(r["event"] for r in rows),
                "frame_count": max(int(r["frame_count"]) for r in rows),
                "max_cursor": max(int(r["cursor"]) for r in rows),
                "final_divergence_qu": round(float(complete[-1]["divergence_qu"]), 3) if complete else None,
                "final_divergence_h_qu": round(float(complete[-1]["divergence_h_qu"]), 3) if complete else None,
                "final_divergence_v_qu": round(float(complete[-1]["divergence_v_qu"]), 3) if complete else None,
                "final_cursor": int(complete[-1]["cursor"]) if complete else None,
            }
        )

    summary = {"event_count": len(events), "players": player_rows, "events": events}
    json_path = local_run_dir / "moveprobe-replay-events.json"
    md_path = local_run_dir / "moveprobe-replay-events.md"
    json_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")

    lines = ["# Moveprobe Replay Event Log", "", f"- Events parsed: `{len(events)}`", ""]
    if player_rows:
        lines.extend(["## Players", ""])
        for player in player_rows:
            lines.append(
                f"- `{player['name']}` ed `{player['ed']}`: events `{player['event_counts']}`, "
                f"frameCount `{player['frame_count']}`, maxCursor `{player['max_cursor']}`, "
                f"finalCursor `{player['final_cursor']}`, "
                f"finalDivergence `{player['final_divergence_qu']}` qu"
            )
    else:
        lines.append("- No `FBMOVEPROBE_REPLAY_EVENT` lines found in `screen.log`.")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


def write_moveprobe_assign_logs(local_run_dir: Path) -> dict[str, object]:
    """LD-F1 (#95): per-bot assignment evidence.

    FBMOVEPROBE_ASSIGN rows expose which mode/route/goal/spawn each bot
    actually resolved (per-slot `_s<N>` cvar vs global fallback) and
    FBMOVEPROBE_PERSLOT_ERROR rows are the loud-fail evidence for malformed
    per-slot values. Both land in moveprobe-assignments.json/md.
    """
    screen_log = (local_run_dir / "screen.log").read_text(encoding="utf-8", errors="replace")
    assignments = parse_moveprobe_assign_logs(screen_log)
    errors = parse_moveprobe_perslot_error_logs(screen_log)

    latest: dict[tuple[int, str], dict[str, object]] = {}
    for row in assignments:
        latest[(int(row["ed"]), str(row["name"]))] = row

    summary = {
        "assignment_count": len(assignments),
        "perslot_error_count": len(errors),
        "latest_assignments": [latest[key] for key in sorted(latest)],
        "assignments": assignments,
        "perslot_errors": errors,
    }

    json_path = local_run_dir / "moveprobe-assignments.json"
    md_path = local_run_dir / "moveprobe-assignments.md"
    json_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")

    lines = [
        "# Moveprobe Per-Bot Assignments",
        "",
        f"- Assignment rows parsed: `{summary['assignment_count']}`",
        f"- Per-slot error rows parsed: `{summary['perslot_error_count']}`",
        "",
    ]
    if latest:
        lines.extend(["## Latest assignment per bot", ""])
        for (ed, name), row in sorted(latest.items()):
            lines.append(
                f"- `{name}` ed `{ed}`: mode `{row['mode']}` ({row['mode_src']}), "
                f"replay_file `{row['replay_file'] or '-'}` ({row['replay_src']}), "
                f"fixed_goal `{row['fixed_goal']}` ({row['goal_src']}), "
                f"spawn_origin `{row['spawn_origin'] or '-'}` ({row['spawn_src']})"
            )
    else:
        lines.append("- No `FBMOVEPROBE_ASSIGN` lines found in `screen.log`.")
    if errors:
        lines.extend(["", "## Per-slot loud failures", ""])
        for err in errors:
            lines.append(
                f"- `{err['name']}` ed `{err['ed']}` at `{fmt_number(err['time_s'], 3)}`s: "
                f"param `{err['param']}` value `{err['value']}` reason `{err['reason']}`"
            )

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


def find_bot_entries(screen_log: str) -> list[str]:
    entries = []
    for line in screen_log.splitlines():
        match = re.search(r"\] (/[^ ]+|/ [^ ]+) entered the game", line)
        if match:
            name = match.group(1).strip()
            if name not in entries:
                entries.append(name)
    return entries


def fmt_number(value: object, digits: int = 1) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return ""


def fmt_percent(value: object) -> str:
    try:
        return f"{float(value) * 100.0:.1f}%"
    except (TypeError, ValueError):
        return ""


def write_summary(
    local_run_dir: Path,
    host: str,
    port: int,
    run_id: str,
    map_name: str,
    parser_exits: dict[str, int],
) -> None:
    analysis = read_json(local_run_dir / "analysis.json")
    match = analysis.get("match", {})
    frags = analysis.get("frags", {})
    frag_rows = frags.get("frags", []) or []
    screen_log = (local_run_dir / "screen.log").read_text(encoding="utf-8", errors="replace")
    bots = find_bot_entries(screen_log)
    movement_path = local_run_dir / "movement-metrics.json"
    movement = read_json(movement_path) if movement_path.exists() else {}
    movement_rows = movement.get("players", []) if isinstance(movement, dict) else []
    demo_sha = first_line(local_run_dir / "demo.sha256")
    demo_size = first_line(local_run_dir / "demo.size")
    remote_demo = first_line(local_run_dir / "demo.remote-path.txt")
    route_present_original = ""
    route_used = ""
    route_file = ""
    moveprobe = {
        "mode": "",
        "yaw": "",
        "forwardmove": "",
        "sidemove": "",
        "upmove": "",
        "log_commands": "",
        "log_interval": "",
        "transition_scale": "",
        "transition_window": "",
        "qwd_waypoints": "",
        "qwd_point_radius": "",
        "qwd_start_radius": "",
    }
    run_env = local_run_dir / "run.env"
    if run_env.exists():
        for line in run_env.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("ROUTE_FILE_PRESENT_ORIGINAL="):
                route_present_original = line.split("=", 1)[1]
            elif line.startswith("ROUTE_FILE_USED="):
                route_used = line.split("=", 1)[1]
            elif line.startswith("ROUTE_FILE="):
                route_file = line.split("=", 1)[1]
            elif line.startswith("MOVEPROBE_MODE="):
                moveprobe["mode"] = line.split("=", 1)[1]
            elif line.startswith("MOVEPROBE_YAW="):
                moveprobe["yaw"] = line.split("=", 1)[1]
            elif line.startswith("MOVEPROBE_FORWARDMOVE="):
                moveprobe["forwardmove"] = line.split("=", 1)[1]
            elif line.startswith("MOVEPROBE_SIDEMOVE="):
                moveprobe["sidemove"] = line.split("=", 1)[1]
            elif line.startswith("MOVEPROBE_UPMOVE="):
                moveprobe["upmove"] = line.split("=", 1)[1]
            elif line.startswith("MOVEPROBE_LOG_COMMANDS="):
                moveprobe["log_commands"] = line.split("=", 1)[1]
            elif line.startswith("MOVEPROBE_LOG_INTERVAL="):
                moveprobe["log_interval"] = line.split("=", 1)[1]
            elif line.startswith("MOVEPROBE_TRANSITION_SCALE="):
                moveprobe["transition_scale"] = line.split("=", 1)[1]
            elif line.startswith("MOVEPROBE_TRANSITION_WINDOW="):
                moveprobe["transition_window"] = line.split("=", 1)[1]
            elif line.startswith("MOVEPROBE_QWD_WAYPOINTS="):
                moveprobe["qwd_waypoints"] = line.split("=", 1)[1]
            elif line.startswith("MOVEPROBE_QWD_POINT_RADIUS="):
                moveprobe["qwd_point_radius"] = line.split("=", 1)[1]
            elif line.startswith("MOVEPROBE_QWD_START_RADIUS="):
                moveprobe["qwd_start_radius"] = line.split("=", 1)[1]
    events_stderr = (local_run_dir / "events.txt.stderr").read_text(encoding="utf-8", errors="replace").strip()
    command_log_path = local_run_dir / "moveprobe-commands.json"
    command_log = read_json(command_log_path) if command_log_path.exists() else {}
    command_count = command_log.get("command_count", 0) if isinstance(command_log, dict) else 0
    qwd_event_log_path = local_run_dir / "moveprobe-qwd-events.json"
    qwd_event_log = read_json(qwd_event_log_path) if qwd_event_log_path.exists() else {}
    qwd_event_count = qwd_event_log.get("event_count", 0) if isinstance(qwd_event_log, dict) else 0

    lines = [
        f"# {map_name} lab run {run_id}",
        "",
        "## Run",
        "",
        f"- Host: `{host}`",
        f"- Port: `{port}`",
        f"- Map command: `{map_name}`",
        f"- Route file originally present: `{route_present_original}`",
        f"- Route file used: `{route_used}`",
        f"- Route file: `{route_file}`",
        f"- Movement probe mode: `{moveprobe['mode']}`",
        f"- Movement probe command: `yaw={moveprobe['yaw']} forwardmove={moveprobe['forwardmove']} sidemove={moveprobe['sidemove']} upmove={moveprobe['upmove']}`",
        f"- Movement probe transition: `scale={moveprobe['transition_scale']} window={moveprobe['transition_window']}`",
        f"- Movement probe QWD: `waypoint_chars={len(moveprobe['qwd_waypoints'])} point_radius={moveprobe['qwd_point_radius']} start_radius={moveprobe['qwd_start_radius']}`",
        f"- Movement probe command logging: `enabled={moveprobe['log_commands']} interval={moveprobe['log_interval']}`",
        f"- Movement probe commands parsed: `{command_count}`",
        f"- Movement probe QWD events parsed: `{qwd_event_count}`",
        f"- Remote demo: `{remote_demo}`",
        f"- Local demo: `{local_run_dir / 'demo.mvd'}`",
        f"- Demo size: `{demo_size}` bytes",
        f"- Demo SHA-256: `{demo_sha.split()[0] if demo_sha else ''}`",
        f"- SSD archive: `{first_line(local_run_dir / 'archive.result.txt')}`",
        "",
        "## Parser",
        "",
        f"- JSON exit: `{parser_exits['json']}`",
        f"- Markdown exit: `{parser_exits['md']}`",
        f"- Events exit: `{parser_exits['events']}`",
    ]
    if events_stderr:
        lines.append(f"- Events stderr: `{events_stderr}`")

    lines.extend(
        [
            "",
            "## Analysis",
            "",
            f"- Map title: `{match.get('map', '')}`",
            f"- Duration: `{match.get('duration', '')}` ms",
            f"- Total frags: `{frags.get('totalFrags', '')}`",
            f"- Bots observed in server log: `{', '.join(bots)}`",
            "",
            "## Movement",
            "",
            f"- Movement metrics: `{local_run_dir / 'movement-metrics.md'}`",
        ]
    )

    if movement_rows:
        for player in movement_rows:
            try:
                over_maxspeed = f"{float(player.get('over_maxspeed_time_ratio', 0.0)) * 100.0:.1f}%"
            except (TypeError, ValueError):
                over_maxspeed = ""
            lines.append(
                f"- `{player.get('name')}`: avg `{fmt_number(player.get('avg_horizontal_speed_qu_per_s'))}` qu/s, "
                f"max `{fmt_number(player.get('max_horizontal_speed_qu_per_s'))}` qu/s, "
                f"p95 `{fmt_number(player.get('p95_horizontal_speed_qu_per_s'))}` qu/s, "
                f"over maxspeed `{over_maxspeed}`, "
                f"air proxy `{fmt_percent(player.get('airborne_proxy_time_ratio'))}`, "
                f"cadence `{fmt_number(player.get('jump_cadence_per_min'))}`/min"
            )
    else:
        lines.append("- No named-player movement metrics recorded.")

    lines.extend(
        [
            "",
            "## Frags",
            "",
        ]
    )

    if frag_rows:
        for frag in frag_rows:
            lines.append(
                f"- `{frag.get('time')}` ms: `{frag.get('killer')}` killed "
                f"`{frag.get('victim')}` with `{frag.get('weapon')}`"
            )
    else:
        lines.append("- No frags recorded in parser summary.")

    lines.extend(
        [
            "",
            "## Verdict",
            "",
            f"One-command {map_name} lab run completed: server started, MVD copied, parser summary written, and the lab screen session stopped.",
            "",
        ]
    )
    (local_run_dir / "run-summary.md").write_text("\n".join(lines), encoding="utf-8")


def ensure_prereqs(host: str, distro: str, analyzer: str, map_name: str) -> None:
    for tool in ("ssh", "scp", "wsl", "python"):
        require_tool(tool)
    if not SHIM_PATH.is_file():
        raise RuntimeError(f"Missing shim: {SHIM_PATH}")

    remote_check = (
        "python3 --version >/dev/null && "
        "command -v screen >/dev/null && "
        "command -v quakestat >/dev/null && "
        "command -v base64 >/dev/null && "
        "test -x ~/nquakesv/mvdsv && "
        f"test -f ~/nquakesv/qw/maps/{map_name}.bsp"
    )
    run(["ssh", host, remote_check])
    run(["wsl", "-d", distro, "--", "bash", "-lc", f"test -x {analyzer!r}"])


def upload_shim(host: str, run_id: str) -> None:
    remote_dir = f"komodobots-lab/runs/{run_id}"
    run(["ssh", host, f"mkdir -p {remote_dir}"])
    run(["scp", powershell_safe_path(SHIM_PATH), f"{host}:{remote_dir}/qw_min_client.py"])


def upload_replay_cmds(host: str, local_cmds: Path) -> str:
    """Upload a replay .cmds to the KTX replay dir; return the KTX-relative path."""
    if not local_cmds.is_file():
        raise RuntimeError(f"--replay-cmds not found: {local_cmds}")
    name = local_cmds.name
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
        raise RuntimeError(f"Unsafe replay file name: {name}")
    run(["ssh", host, "mkdir -p ~/nquakesv/ktx/bots/replay"])
    run(["scp", powershell_safe_path(local_cmds), f"{host}:nquakesv/ktx/bots/replay/{name}"])
    return f"bots/replay/{name}"


def dual_write_demo(local_run_dir: Path, record_name: str, run_id: str) -> list[Path]:
    """Copy the run's demo.mvd to the committed tricks dir and the nQuake watch mirror."""
    demo = local_run_dir / "demo.mvd"
    if not demo.is_file():
        print("WARNING: no demo.mvd to record into tricks/dm3", file=sys.stderr)
        return []
    out_name = f"{record_name}__{run_id}.mvd"
    written: list[Path] = []
    for dst_dir in (TRICKS_DM3_DIR, NQUAKE_TRICKS_DM3_DIR):
        try:
            dst_dir.mkdir(parents=True, exist_ok=True)
            dst = dst_dir / out_name
            shutil.copy2(demo, dst)
            written.append(dst)
        except OSError as exc:
            print(f"WARNING: could not write demo to {dst_dir}: {exc}", file=sys.stderr)
    return written


def run_remote_lab(
    host: str,
    run_id: str,
    port: int,
    duration: float,
    bot_count: int,
    bot_spacing: float,
    map_name: str,
    moveprobe_mode: int,
    moveprobe_yaw: float,
    moveprobe_forwardmove: int,
    moveprobe_sidemove: int,
    moveprobe_upmove: int,
    moveprobe_log_commands: bool,
    moveprobe_log_interval: float,
    moveprobe_transition_scale: float,
    moveprobe_transition_window: float,
    moveprobe_qwd_waypoints: str,
    moveprobe_qwd_point_radius: float,
    moveprobe_qwd_start_radius: float,
    moveprobe_replay_file: str,
    moveprobe_lookahead_frames: int,
    moveprobe_corr_deadband: float,
    moveprobe_corr_yaw_max: float,
    moveprobe_extra_cvars: str,
    timelimit_min: int,
    matchless_val: int,
    mvdsv_bin: str,
    local_run_dir: Path,
) -> None:
    proc = run(
        [
            "ssh",
            host,
            "bash",
            "-s",
            "--",
            run_id,
            str(port),
            str(duration),
            str(bot_count),
            str(bot_spacing),
            map_name,
            str(moveprobe_mode),
            str(moveprobe_yaw),
            str(moveprobe_forwardmove),
            str(moveprobe_sidemove),
            str(moveprobe_upmove),
            "1" if moveprobe_log_commands else "0",
            str(moveprobe_log_interval),
            str(moveprobe_transition_scale),
            str(moveprobe_transition_window),
            base64.b64encode(moveprobe_qwd_waypoints.encode("utf-8")).decode("ascii") or "-",
            str(moveprobe_qwd_point_radius),
            str(moveprobe_qwd_start_radius),
            moveprobe_replay_file or "-",
            str(moveprobe_lookahead_frames),
            str(moveprobe_corr_deadband),
            str(moveprobe_corr_yaw_max),
            base64.b64encode(moveprobe_extra_cvars.encode("utf-8")).decode("ascii") or "-",
            str(timelimit_min),
            str(matchless_val),
            mvdsv_bin,
        ],
        input_text=REMOTE_SCRIPT,
        check=False,
    )
    local_run_dir.mkdir(parents=True, exist_ok=True)
    (local_run_dir / "remote.stdout").write_text(proc.stdout, encoding="utf-8")
    (local_run_dir / "remote.stderr").write_text(proc.stderr, encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(f"Remote lab failed with exit {proc.returncode}; see remote.stdout and remote.stderr")


def validate_map_name(map_name: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_+-]+", map_name):
        raise argparse.ArgumentTypeError("Map names may only contain letters, digits, underscore, plus, or dash.")
    return map_name


def validate_run_id(run_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
        raise argparse.ArgumentTypeError("Run IDs may only contain letters, digits, underscore, or dash.")
    return run_id


def validate_qwd_waypoints(value: str) -> str:
    if value and not re.fullmatch(r"[0-9,.;+\- ]+", value):
        raise argparse.ArgumentTypeError("QWD waypoint strings may only contain numbers, commas, semicolons, spaces, plus, minus, and dots.")
    return value


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a one-command Komodobots bot lab.")
    parser.add_argument("--host", default="servexeri", help="SSH host. Defaults to servexeri.")
    parser.add_argument("--port", type=int, default=28599, help="Preferred MVDSV UDP port. Defaults to 28599.")
    parser.add_argument("--map", dest="map_name", type=validate_map_name, default="frobodm2", help="Map to load. Defaults to frobodm2.")
    parser.add_argument("--run-id", type=validate_run_id, default=None, help="Run ID. Defaults to current UTC timestamp.")
    parser.add_argument("--duration", type=float, default=45.0, help="Client run duration in seconds. Defaults to 45.")
    parser.add_argument(
        "--lab-mvdsv",
        dest="lab_mvdsv",
        default="mvdsv",
        help=(
            "Name of the MVDSV binary under ~/nquakesv to launch. Defaults to the "
            "production 'mvdsv'. Use 'mvdsv-lab' for the lab-only build whose 60s "
            "login-timeout is gated on sv_login, so the headless client shim survives "
            "long acceleration runs. Production servers keep using 'mvdsv'."
        ),
    )
    parser.add_argument(
        "--prewar",
        action="store_true",
        help=(
            "Run in prewar instead of matchless (sets k_matchless 0). No match starts, "
            "so there is no match timer and no insufficient-players abort: a single bot "
            "keeps moving and the server keeps recording even after the idle client shim "
            "is dropped. Use for long single-bot acceleration runs (>60s)."
        ),
    )
    parser.add_argument(
        "--timelimit",
        type=int,
        default=1,
        help=(
            "KTX match timelimit in minutes written into the lab cfg. Defaults to 1. "
            "Raise it for long acceleration runs (a >60s --duration needs --timelimit >=2, "
            "or the match hits intermission, stops the demo, and removes the bot)."
        ),
    )
    parser.add_argument("--bot-count", type=int, default=2, help="Number of botcmd addbot commands. Defaults to 2.")
    parser.add_argument("--bot-spacing", type=float, default=8.0, help="Seconds between bot adds. Defaults to 8.")
    parser.add_argument(
        "--moveprobe-mode",
        type=int,
        choices=(0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23),
        default=0,
        help=(
            "Set k_fb_moveprobe_mode in the generated KTX lab config. "
            "Requires the S2 KTX patch to affect behavior. "
            "0=off, 1=force jump, 2=fixed movement command, "
            "3=route-yaw movement command, 4=route-yaw alternating strafe, "
            "5=aim-independent route/strafe projection, "
            "6=mode 5 with negative forward folded into sidemove, "
            "7=mode 6 with bounded horizontal command magnitude, "
            "8=mode 7 with transition-only horizontal command-budget scaling, "
            "9=QWD SNG hybrid waypoint/controller probe, "
        "10=open-loop replay of an exact human POV command file."
        ),
    )
    parser.add_argument(
        "--replay-cmds",
        type=Path,
        default=None,
        help=(
            "Local replay .cmds file (from build_replay_command_file.py) for mode 10. "
            "Uploaded to ~/nquakesv/ktx/bots/replay/ and exposed via k_fb_moveprobe_replay_file."
        ),
    )
    parser.add_argument(
        "--record-trick-name",
        type=validate_run_id,
        default=None,
        help=(
            "If set, the run's demo.mvd is also copied to komodobots/tricks/dm3/ and the "
            "nQuake watch mirror as <name>__<run_id>.mvd."
        ),
    )
    parser.add_argument(
        "--moveprobe-yaw",
        type=float,
        default=0.0,
        help=(
            "Yaw used only by movement-probe mode 2. Modes 3 and 4 derive yaw "
            "from Frogbot route intent; modes 5, 6, and 7 preserve combat view yaw. "
            "Defaults to 0."
        ),
    )
    parser.add_argument(
        "--moveprobe-forwardmove",
        type=int,
        default=800,
        help="forwardmove used by movement-probe modes 2, 3, 4, 5, 6, and 7. Defaults to 800.",
    )
    parser.add_argument(
        "--moveprobe-sidemove",
        type=int,
        default=0,
        help="sidemove used by movement-probe modes 2, 3, 4, 5, 6, and 7. Mode 4 treats 0 as 400. Defaults to 0.",
    )
    parser.add_argument(
        "--moveprobe-upmove",
        type=int,
        default=0,
        help="upmove used by movement-probe modes 2, 3, 4, 5, 6, 7, 8, and 9. Defaults to 0.",
    )
    parser.add_argument(
        "--moveprobe-transition-scale",
        type=float,
        default=1.25,
        help="Mode 8 transition-only horizontal budget scale. Defaults to 1.25.",
    )
    parser.add_argument(
        "--moveprobe-transition-window",
        type=float,
        default=0.4,
        help="Mode 8 takeoff/air/landing transition window in seconds. Defaults to 0.4.",
    )
    parser.add_argument(
        "--moveprobe-qwd-waypoints",
        type=validate_qwd_waypoints,
        default="",
        help="Mode 9 semicolon-separated QWD control points as x,y,z triples.",
    )
    parser.add_argument(
        "--moveprobe-qwd-point-radius",
        type=float,
        default=96.0,
        help="Mode 9 control-point advance radius in qu. Defaults to 96.",
    )
    parser.add_argument(
        "--moveprobe-qwd-start-radius",
        type=float,
        default=192.0,
        help="Mode 9 activation radius around the first control point in qu. Defaults to 192.",
    )
    parser.add_argument(
        "--moveprobe-lookahead-frames",
        type=int,
        default=4,
        help=(
            "Mode 11 (closed-loop steering) lookahead: aim at the human origin this "
            "many replay frames ahead of the current time cursor. Defaults to 4."
        ),
    )
    parser.add_argument(
        "--moveprobe-corr-deadband",
        type=float,
        default=16.0,
        help=(
            "Mode 12 (corrective replay) deadband in qu: only apply the yaw nudge "
            "once horizontal divergence exceeds this. Defaults to 16."
        ),
    )
    parser.add_argument(
        "--moveprobe-corr-yaw-max",
        type=float,
        default=3.0,
        help=(
            "Mode 12 (corrective replay) per-frame yaw correction clamp in degrees. "
            "Defaults to 3."
        ),
    )
    parser.add_argument(
        "--extra-replay-cmds",
        type=Path,
        action="append",
        default=None,
        help=(
            "Additional local replay .cmds file uploaded to ~/nquakesv/ktx/bots/replay/ "
            "WITHOUT touching the global k_fb_moveprobe_replay_file cvar. Repeatable. "
            "Pair with per-slot cvars (LD-F1 #95), e.g. --ktx-extra-cvars "
            "'k_fb_moveprobe_replay_file_s3 bots/replay/dm3_hilljump.cmds' so two bots "
            "can run two different routes in one session."
        ),
    )
    parser.add_argument(
        "--ktx-extra-cvars",
        default="",
        help=(
            "Semicolon-separated 'name value' pairs appended to the KTX lab config as "
            "`set name value` lines. Used for the live retry harness, e.g. "
            "'k_fb_moveprobe_replay_loop 1;k_fb_moveprobe_replay_map trick;"
            "k_fb_moveprobe_corridor 64;k_fb_moveprobe_kill_div 400'."
        ),
    )
    parser.add_argument(
        "--moveprobe-log-commands",
        action="store_true",
        help=(
            "Enable KTX moveprobe command logging when the S2 patch is applied. "
            "The runner parses FBMOVEPROBE_CMD lines from screen.log."
        ),
    )
    parser.add_argument(
        "--moveprobe-log-interval",
        type=float,
        default=0.25,
        help="Minimum seconds between command log samples per bot. Defaults to 0.25.",
    )
    parser.add_argument("--wsl-distro", default="Ubuntu-24.04", help="WSL distro for parser. Defaults to Ubuntu-24.04.")
    parser.add_argument("--analyzer", default=DEFAULT_ANALYZER, help="Path to qw-analyze-v20 inside WSL.")
    parser.add_argument(
        "--strict-port",
        action="store_true",
        help="Fail if --port is in use instead of automatically trying the next 50 ports.",
    )
    parser.add_argument(
        "--skip-prereq-check",
        action="store_true",
        help="Skip local/remote prerequisite checks.",
    )
    return parser.parse_args(list(argv))


def main(argv: Iterable[str] = sys.argv[1:]) -> int:
    args = parse_args(argv)
    run_id = args.run_id or utc_run_id()
    local_run_dir = ARTIFACT_ROOT / run_id
    local_run_dir.mkdir(parents=True, exist_ok=True)

    try:
        if not args.skip_prereq_check:
            ensure_prereqs(args.host, args.wsl_distro, args.analyzer, args.map_name)

        port = choose_port(args.host, args.port, explicit=args.strict_port)
        upload_shim(args.host, run_id)
        if args.moveprobe_mode in (10, 11, 12, 21, 22) and args.replay_cmds is None:
            raise RuntimeError(
                f"--moveprobe-mode {args.moveprobe_mode} (replay-backed) requires "
                "--replay-cmds; without it KTX loads no frames and silently falls "
                "back to normal Frogbot movement while artifacts would still report "
                "the mode."
            )
        replay_remote = ""
        if args.replay_cmds is not None:
            replay_remote = upload_replay_cmds(args.host, args.replay_cmds)
        for extra_cmds in args.extra_replay_cmds or []:
            uploaded = upload_replay_cmds(args.host, extra_cmds)
            print(f"extra_replay_cmds={uploaded}")
        extra_cvars_blob = ""
        if args.ktx_extra_cvars:
            _lines = []
            for p in args.ktx_extra_cvars.split(";"):
                p = p.strip()
                if not p:
                    continue
                name, _, value = p.partition(" ")
                # Quote multi-word values ("name x y z") or the cfg parser truncates
                # the cvar at the first space.
                if " " in value.strip():
                    _lines.append(f'set {name} "{value.strip()}"')
                else:
                    _lines.append(f"set {p}")
            extra_cvars_blob = ("\n".join(_lines) + "\n") if _lines else ""
        run_remote_lab(
            args.host,
            run_id,
            port,
            args.duration,
            args.bot_count,
            args.bot_spacing,
            args.map_name,
            args.moveprobe_mode,
            args.moveprobe_yaw,
            args.moveprobe_forwardmove,
            args.moveprobe_sidemove,
            args.moveprobe_upmove,
            args.moveprobe_log_commands,
            args.moveprobe_log_interval,
            args.moveprobe_transition_scale,
            args.moveprobe_transition_window,
            args.moveprobe_qwd_waypoints,
            args.moveprobe_qwd_point_radius,
            args.moveprobe_qwd_start_radius,
            replay_remote,
            args.moveprobe_lookahead_frames,
            args.moveprobe_corr_deadband,
            args.moveprobe_corr_yaw_max,
            extra_cvars_blob,
            args.timelimit,
            0 if args.prewar else 1,
            args.lab_mvdsv,
            local_run_dir,
        )
        # B5 (#64): every lab attempt's MVD is archived to the servexeri demo
        # SSD, server-side, sha256-verified, idempotent. Never fatal: an SSD
        # hiccup must not lose the run (it only warns; backfill recovers later).
        archive_run_demo(args.host, run_id, args.map_name, local_run_dir=local_run_dir)
        scp_from_remote(args.host, run_id, local_run_dir)
        parser_exits = run_analyzer(local_run_dir, args.wsl_distro, args.analyzer)
        movement_metrics = write_movement_metrics(local_run_dir)
        write_moveprobe_command_logs(local_run_dir)
        write_moveprobe_qwd_event_logs(local_run_dir)
        write_moveprobe_replay_event_logs(local_run_dir)
        write_moveprobe_assign_logs(local_run_dir)
        write_summary(local_run_dir, args.host, port, run_id, args.map_name, parser_exits)

        if args.record_trick_name:
            recorded = dual_write_demo(local_run_dir, args.record_trick_name, run_id)
            for dst in recorded:
                print(f"recorded_demo={dst}")

        summary = local_run_dir / "run-summary.md"
        metrics_summary = local_run_dir / "movement-metrics.md"
        print(f"run_id={run_id}")
        print(f"port={port}")
        print(f"map={args.map_name}")
        print(f"artifacts={summary.parent}")
        print(f"summary={summary}")
        print(f"movement_metrics={metrics_summary}")
        print(f"movement_players={len(movement_metrics.get('players', []))}")
        print(f"parser_exits={parser_exits}")
        return 0
    except Exception as exc:
        (local_run_dir / "runner.error.txt").write_text(f"{exc}\n", encoding="utf-8")
        print(f"ERROR: {exc}", file=sys.stderr)
        print(f"artifacts={local_run_dir}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
