#!/usr/bin/env python3
"""Run a lab-only KTX 4v4 validation match and build the fixed-roster ledger.

The runner is intentionally narrow:

* allowed lab ports only (28599..28609), never production ports;
* KTX team/4on4 mode on dm3 by default;
* one persistent spectator shim drives `botcmd addbot 20 <team>` and keeps the
  server demo recorder alive while eight Frogbots play;
* the raw KTX JSON sidecar is copied as `ktxstats.json`, then the normal
  `4v4-validation.json` ledger is rebuilt.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts"
LAB_SERVER_DIR = REPO_ROOT / "lab" / "server"
for import_path in (SCRIPT_DIR, LAB_SERVER_DIR):
    path_text = str(import_path)
    if path_text not in sys.path:
        sys.path.insert(0, path_text)

from control_bridge import ALLOWED_LAB_PORTS, DENIED_PORTS, validate_lab_port, validate_map_name
from fourvfour_validation_build import DEFAULT_OUT, build as build_ledger, summarize as summarize_ledger
from fourvfour_validation_runner import DEFAULT_OUT_ROOT, DEFAULT_TEAM_NAMES, write_run_artifacts, utc_run_id
from run_frobodm2_lab import (
    DEFAULT_ANALYZER,
    powershell_safe_path,
    remote_port_is_down,
    require_tool,
    run,
    run_analyzer,
    scp_from_remote,
    upload_shim,
)


REMOTE_SCRIPT = r"""#!/usr/bin/env bash
set -euo pipefail

run_id="$1"
port="$2"
duration="$3"
map_name="$4"
timelimit_min="$5"
mvdsv_bin="$6"
team1="$7"
team2="$8"
live_leap="${9:-0}"
shm_name="${10:-}"
leap_cvars_b64="${11:-}"
sidecar_cmd_b64="${12:-}"
sidecar_pid=""

session="komodobots_lab_4v4_${port}_${run_id}"
rundir="$HOME/komodobots-lab/runs/$run_id"
nq="$HOME/nquakesv"
cfg_name="kbot_4v4_${port}.cfg"
cfg_path="$nq/ktx/$cfg_name"
lab_lock="$HOME/komodobots-lab/lab.lock"

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

acquire_lab_lock() {
  if [ -f "$lab_lock" ]; then
    echo "Lab lock already exists; refusing to clobber it:" >&2
    cat "$lab_lock" >&2 || true
    exit 2
  fi
  mkdir -p "$HOME/komodobots-lab"
  printf '{"owner":"harness","run_id":"%s","pid":%s,"ts":"%s","port":%s,"map":"%s","mode":"4v4"}\n' \
    "$run_id" "$$" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$port" "$map_name" > "$lab_lock"
}

release_lab_lock() {
  if [ -f "$lab_lock" ] && grep -q "\"run_id\":\"${run_id}\"" "$lab_lock"; then
    rm -f -- "$lab_lock"
  fi
}

cleanup() {
  set +e
  if [ -n "$sidecar_pid" ]; then
    kill "$sidecar_pid" 2>/dev/null
  fi
  if [ -n "$shm_name" ]; then
    pkill -f "move_policy_sidecar.py --shm-name $shm_name" 2>/dev/null
    rm -f "/dev/shm/$shm_name" 2>/dev/null
  fi
  if session_exists; then
    send_cmd "status" 0.2
    screen -S "$session" -p 0 -X hardcopy "$rundir/hardcopy.cleanup.txt"
    send_cmd "sv_demostop" 0.5
    screen -S "$session" -X quit
  fi
  release_lab_lock
}
trap cleanup EXIT

case "$port" in
  28599|2860[0-9]) ;;
  *)
    echo "Refusing non-lab port: $port" >&2
    exit 2
    ;;
esac

case "$port" in
  28501|28502|28503)
    echo "Refusing production port: $port" >&2
    exit 2
    ;;
esac

if session_exists; then
  echo "Screen session already exists: $session" >&2
  exit 2
fi
if screen -ls | grep -q "[.]komodobots_lab_${port}[[:space:]]"; then
  echo "Lab port $port is held by dashboard session komodobots_lab_${port}" >&2
  exit 2
fi
qs="$(quakestat -qws "localhost:$port" -P -nh 2>/dev/null || true)"
if [ -n "$qs" ] && ! printf '%s' "$qs" | grep -q 'DOWN'; then
  echo "Port $port is already serving QuakeWorld:" >&2
  printf '%s\n' "$qs" >&2
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
if [ ! -f "$nq/ktx/bots/maps/${map_name}.bot" ]; then
  echo "Missing Frogbot route file: $nq/ktx/bots/maps/${map_name}.bot" >&2
  exit 5
fi
if [ ! -f "$rundir/qw_min_client.py" ]; then
  echo "Missing uploaded shim: $rundir/qw_min_client.py" >&2
  exit 6
fi

mkdir -p "$rundir"
touch "$rundir/start.marker"

cat > "$cfg_path" <<EOF
// Auto-generated Komodobots 4v4 validation config $run_id
hostname "komodobots-4v4:$port"
set k_motd1 "Komodobots 4v4 validation $run_id"
set k_matchless 0
set k_use_matchless_dir 1
set k_allowed_free_modes 4095
set k_defmode 4on4
set k_mode 2
set k_defmap $map_name
set k_fb_enabled 1
set k_count 0
set k_auto_xonx 0
set k_lockmap 1
set k_fb_autoadd_limit 0
set k_fb_autoremove_at 0
set k_fb_auto_delay 1
set k_fb_skill 20
coop 0
maxclients 9
set k_maxclients 8
deathmatch 1
teamplay 2
timelimit $timelimit_min
fraglimit 0
samelevel 1
set k_membercount 3
set k_lockmin 1
set k_lockmax 2
set k_overtime 0
set k_exttime 0
set sv_getrealip 0
set sv_login 0
set sv_timeout 3600
set k_idletime 0
set demo_tmp_record 1
set k_demo_mintime 0
set k_demotxt_format json
sv_demotxt 2
sv_demofps 77
sv_demodir demos
set qtv_streamport $port
set qtv_maxstreams 8
set qtv_password ""
serverinfo hostname "komodobots-4v4:$port"
EOF

# Live-leap: append the per-slot mode-30 cvars (leap bots seat at internal slots
# 1..4 behind the slot-0 spectator; cvar suffix is the 1-based edict). The block
# is built + base64'd by the Python caller so the exact cvar set is unit-tested.
if [ "$live_leap" = "1" ] && [ -n "$leap_cvars_b64" ]; then
  printf '%s\n' "$leap_cvars_b64" | base64 -d >> "$cfg_path"
fi
cp "$cfg_path" "$rundir/lab.cfg"

cat > "$rundir/run.env" <<EOF
RUN_ID=$run_id
SESSION=$session
PORT=$port
MAP=$map_name
TEAM1=$team1
TEAM2=$team2
TIMELIMIT=$timelimit_min
RUNDIR=$rundir
CFG=$cfg_path
START_UTC=$(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF

acquire_lab_lock
log "starting $session on port $port"
cd "$nq"
screen -L -Logfile "$rundir/screen.log" -dmS "$session" "./$mvdsv_bin" -port "$port" -mem 64 -game ktx +exec "$cfg_name"

server_up=0
for _ in $(seq 1 60); do
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

send_cmd "map $map_name" 1.5
send_cmd "set k_fb_enabled 1"
send_cmd "set k_fb_autoadd_limit 0"
send_cmd "set k_fb_autoremove_at 0"
send_cmd "set k_fb_skill 20"
send_cmd "set k_lockmap 1"
send_cmd "set sv_getrealip 0"
send_cmd "set sv_login 0"
send_cmd "set sv_timeout 3600"
send_cmd "set k_idletime 0"
send_cmd "deathmatch 1"
send_cmd "teamplay 2"
send_cmd "maxclients 9"
send_cmd "timelimit $timelimit_min"
send_cmd "fraglimit 0"
send_cmd "set k_overtime 0"
send_cmd "sv_democancel"
send_cmd "sv_demoeasyrecord komodobots_4v4_${run_id}" 1.0
send_cmd "status"
screen -S "$session" -p 0 -X hardcopy "$rundir/hardcopy.before-client.txt"

# Live-leap: KTX creates the /dev/shm region only once a leap bot first hits
# mode 30 (after the shim adds bots). So start a background waiter that attaches
# the sidecar the moment the region appears, then keeps serving for the match.
if [ "$live_leap" = "1" ] && [ -n "$sidecar_cmd_b64" ] && [ -n "$shm_name" ]; then
  sidecar_cmd="$(printf '%s\n' "$sidecar_cmd_b64" | base64 -d)"
  rm -f "/dev/shm/$shm_name" 2>/dev/null || true
  (
    for _ in $(seq 1 120); do
      [ -e "/dev/shm/$shm_name" ] && break
      sleep 0.5
    done
    if [ -e "/dev/shm/$shm_name" ]; then
      echo "[remote] sidecar attaching to /dev/shm/$shm_name"
      eval "$sidecar_cmd"
    else
      echo "[remote] WARN: region /dev/shm/$shm_name never appeared; sidecar not started" >&2
    fi
  ) > "$rundir/sidecar.log" 2>&1 &
  sidecar_pid=$!
  log "live-leap sidecar waiter started (pid $sidecar_pid)"
fi

log "running spectator shim"
python3 "$rundir/qw_min_client.py" "$port" \
  --host 127.0.0.1 \
  --spectator \
  --name Komodo4v4 \
  --run-for "$duration" \
  --bot-count 0 \
  --botcmd removeall \
  --botcmd "addbot 20 $team1" \
  --botcmd "addbot 20 $team1" \
  --botcmd "addbot 20 $team1" \
  --botcmd "addbot 20 $team1" \
  --botcmd "addbot 20 $team2" \
  --botcmd "addbot 20 $team2" \
  --botcmd "addbot 20 $team2" \
  --botcmd "addbot 20 $team2" \
  > "$rundir/pyclient.stdout" \
  2> "$rundir/pyclient.stderr"

# Stop the live-leap sidecar now the match is over (lets its log flush before we
# collect artifacts; cleanup() is the belt-and-braces backstop on any exit path).
if [ -n "$sidecar_pid" ]; then
  kill "$sidecar_pid" 2>/dev/null || true
fi
if [ "$live_leap" = "1" ] && [ -n "$shm_name" ]; then
  pkill -f "move_policy_sidecar.py --shm-name $shm_name" 2>/dev/null || true
fi

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
if [ -f "${demo%.mvd}.json" ]; then
  cp -- "${demo%.mvd}.json" "$rundir/ktxstats.json"
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


DEFAULT_SHM_NAME = "komodo_move_t07"
DEFAULT_STALE_TICKS = 3
DEFAULT_SIDECAR_PYTHON = "~/t0.3-venv/bin/python"
DEFAULT_SIDECAR_SCRIPT = "~/komodo-t0.3/scripts/move_policy_sidecar.py"
DEFAULT_SIDECAR_CKPT = "~/move_bc_policy.pt"
DEFAULT_SIDECAR_HZ = 77
# The leap team is team1, added first; the bot-adding spectator always seats at
# client slot 0, so the four leap bots take client edicts 2..5 (internal slots
# 1..4). The mode-30 per-slot cvar suffix is the 1-based edict, not the slot.
LEAP_EDICTS = (2, 3, 4, 5)


def build_leap_cvar_block(shm_name: str, stale_ticks: int, leap_edicts=LEAP_EDICTS) -> str:
    """KTX cfg lines that turn the live MoveMLP brain ON for the leap bots only.

    One `k_fb_moveprobe_mode_s<edict> 30` per leap edict (2..5) -- never the frog
    edicts (6..9), which must stay stock -- plus the shm name + stale-tick gate.
    """
    lines = [f"set k_fb_moveprobe_mode_s{int(e)} 30" for e in leap_edicts]
    lines.append(f'set k_fb_moveprobe_live_shm_name "{shm_name}"')
    lines.append(f"set k_fb_moveprobe_live_stale_ticks {int(stale_ticks)}")
    return "\n".join(lines) + "\n"


def build_sidecar_command(
    python_path: str, script_path: str, shm_name: str, ckpt: str, hz: int = DEFAULT_SIDECAR_HZ
) -> str:
    """Shell command that serves the MoveMLP sidecar against the live region.

    `cd`s into the script's dir first so its sibling imports resolve, then attaches
    (no --create: KTX owns the region, the sidecar mirrors it).
    """
    import posixpath

    script_dir = posixpath.dirname(script_path) or "."
    return (
        f"cd {script_dir} && {python_path} {script_path} "
        f"--shm-name {shm_name} --ckpt {ckpt} --hz {int(hz)}"
    )


def _b64(text: str) -> str:
    import base64

    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def ensure_prereqs(host: str, distro: str, analyzer: str, map_name: str, mvdsv_bin: str) -> None:
    for tool in ("ssh", "scp", "wsl", "python"):
        require_tool(tool)

    remote_check = (
        "python3 --version >/dev/null && "
        "command -v screen >/dev/null && "
        "command -v quakestat >/dev/null && "
        f"test -x ~/nquakesv/{mvdsv_bin} && "
        f"test -f ~/nquakesv/qw/maps/{map_name}.bsp && "
        f"test -f ~/nquakesv/ktx/bots/maps/{map_name}.bot"
    )
    run(["ssh", host, remote_check])
    run(["wsl", "-d", distro, "--", "bash", "-lc", f"test -x {analyzer!r}"])


def choose_lab_port(host: str, requested_port: int, *, strict: bool) -> int:
    if requested_port in DENIED_PORTS or validate_lab_port(requested_port) is None:
        raise RuntimeError(f"Requested port {requested_port} is not in the lab allowlist.")
    if remote_port_is_down(host, requested_port):
        return requested_port
    if strict:
        raise RuntimeError(f"Requested port {requested_port} is already in use on {host}.")
    for port in ALLOWED_LAB_PORTS:
        if port == requested_port:
            continue
        if remote_port_is_down(host, port):
            return port
    raise RuntimeError(f"No free lab port found in {min(ALLOWED_LAB_PORTS)}-{max(ALLOWED_LAB_PORTS)}.")


def run_remote_4v4_lab(
    *,
    host: str,
    run_id: str,
    port: int,
    duration: float,
    map_name: str,
    timelimit: int,
    mvdsv_bin: str,
    team1: str,
    team2: str,
    local_run_dir: Path,
    live_leap: bool = False,
    shm_name: str = "",
    leap_cvars: str = "",
    sidecar_cmd: str = "",
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
            map_name,
            str(timelimit),
            mvdsv_bin,
            team1,
            team2,
            "1" if live_leap else "0",
            shm_name,
            _b64(leap_cvars),
            _b64(sidecar_cmd),
        ],
        input_text=REMOTE_SCRIPT,
        check=False,
    )
    local_run_dir.mkdir(parents=True, exist_ok=True)
    (local_run_dir / "remote.stdout").write_text(proc.stdout, encoding="utf-8")
    (local_run_dir / "remote.stderr").write_text(proc.stderr, encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(f"Remote 4v4 lab failed with exit {proc.returncode}; see remote.stdout and remote.stderr")


def validate_team_name(value: str) -> str:
    if validate_map_name(value) is None or len(value) > 9:
        raise argparse.ArgumentTypeError("Team names must be KTX-safe and at most 9 chars.")
    return value


def validate_map_arg(value: str) -> str:
    if validate_map_name(value) is None:
        raise argparse.ArgumentTypeError("Invalid map name.")
    return value


def validate_lab_port_arg(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Port must be an integer.") from exc
    if validate_lab_port(port) is None:
        raise argparse.ArgumentTypeError("Port must be in the lab allowlist 28599..28609.")
    return port


def validate_run_id_arg(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise argparse.ArgumentTypeError("Run IDs may only contain letters, digits, underscore, or dash.")
    return value


def validate_remote_bin_arg(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", value):
        raise argparse.ArgumentTypeError("Remote binary names may only contain letters, digits, underscore, dot, or dash.")
    return value


def write_summary(
    local_run_dir: Path,
    *,
    run_id: str,
    host: str,
    port: int,
    map_name: str,
    timelimit: int,
    duration: float,
    ledger_out: Path,
    ledger: dict,
    parser_exits: dict[str, int],
    live_leap: bool = False,
    shm_name: str = "",
    stale_ticks: int = DEFAULT_STALE_TICKS,
) -> None:
    latest_game = next((g for g in ledger.get("games", []) if g.get("run_id") == run_id), None)
    invalid = next((g for g in ledger.get("invalid_games", []) if g.get("run_id") == run_id), None)
    lines = [
        f"# 4v4 Validation Run {run_id}",
        "",
        f"- Host: `{host}`",
        f"- Port: `{port}`",
        f"- Map: `{map_name}`",
        f"- Timelimit: `{timelimit}`",
        f"- Spectator shim duration: `{duration}` seconds",
        (
            f"- Live-leap brain: `ON` (shm `{shm_name}`, stale_ticks `{stale_ticks}`, "
            f"mode-30 on leap edicts {list(LEAP_EDICTS)})"
            if live_leap
            else "- Live-leap brain: `OFF` (both teams move as stock frogbots)"
        ),
        f"- Parser exits: `{parser_exits}`",
        f"- Ledger: `{ledger_out}`",
    ]
    if latest_game:
        bench = latest_game.get("bench", {})
        gate = latest_game.get("damage_matrix", {})
        agg = ledger.get("bench", {})
        lines.extend(
            [
                f"- Ledger verdict: `valid`",
                f"- Previous valid run: `{latest_game.get('previous_valid_run_id')}`",
                f"- Leap-frog frag margin (this game): "
                f"`{bench.get('leap_frags')} - {bench.get('frog_frags')} = {bench.get('frag_margin')}`",
                f"- R-T damage.matrix gate: "
                f"`{'green' if gate.get('gate_pass') else 'RED ' + str(gate.get('reasons'))}` "
                f"(enemy={gate.get('enemy_damage')}, intra-team={gate.get('intra_team_damage')})",
                f"- Bench best-of-{agg.get('games_scored')}: "
                f"`leap-frog margin total={agg.get('leap_frag_margin_total')} "
                f"mean={agg.get('leap_frag_margin_mean')} "
                f"leap_wins={agg.get('leap_wins')}/{agg.get('games_scored')}`",
                f"- Teams: `{json.dumps(latest_game.get('teams', []), sort_keys=True)}`",
            ]
        )
    elif invalid:
        lines.extend(
            [
                f"- Ledger verdict: `invalid`",
                f"- Invalid reasons: `{invalid.get('reasons')}`",
            ]
        )
    else:
        lines.append("- Ledger verdict: `not found in rebuilt ledger`")
    lines.append("")
    (local_run_dir / "run-summary.md").write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a lab-only KTX 4v4 validation match.")
    parser.add_argument("--host", default="servexeri")
    parser.add_argument("--port", type=validate_lab_port_arg, default=28599)
    parser.add_argument("--run-id", type=validate_run_id_arg, default=None)
    parser.add_argument("--map", dest="map_name", type=validate_map_arg, default="dm3")
    parser.add_argument("--timelimit", type=int, default=5, help="KTX timelimit in minutes; must be >=5.")
    parser.add_argument("--duration", type=float, default=None, help="Spectator shim duration; defaults to timelimit*60+90.")
    parser.add_argument("--team1", type=validate_team_name, default=DEFAULT_TEAM_NAMES[0])
    parser.add_argument("--team2", type=validate_team_name, default=DEFAULT_TEAM_NAMES[1])
    parser.add_argument("--controller-version", default="komodobot-dev")
    parser.add_argument("--komodobot-slot", type=int, default=1)
    parser.add_argument(
        "--leap-team",
        action="store_true",
        help=(
            "Score a full frog-vs-leap 4v4: four leap bots (team1) vs four "
            "skill-20 frogbot controls (team2). The ledger then emits the "
            "leap-frog frag margin over best-of-N and the R-T damage.matrix gate."
        ),
    )
    parser.add_argument(
        "--live-leap",
        action="store_true",
        help=(
            "Turn the live MoveMLP brain ON for the four leap bots (KTX mode-30 "
            "per-slot + the move_policy_sidecar). Requires --leap-team. Without "
            "this flag --leap-team only tags the roster and both teams move as "
            "stock frogbots."
        ),
    )
    parser.add_argument("--shm-name", default=DEFAULT_SHM_NAME, type=validate_remote_bin_arg)
    parser.add_argument("--stale-ticks", type=int, default=DEFAULT_STALE_TICKS)
    parser.add_argument("--sidecar-python", default=DEFAULT_SIDECAR_PYTHON)
    parser.add_argument("--sidecar-script", default=DEFAULT_SIDECAR_SCRIPT)
    parser.add_argument("--sidecar-ckpt", default=DEFAULT_SIDECAR_CKPT)
    parser.add_argument("--sidecar-hz", type=int, default=DEFAULT_SIDECAR_HZ)
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    parser.add_argument("--ledger-out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--lab-mvdsv", type=validate_remote_bin_arg, default="mvdsv-lab")
    parser.add_argument("--wsl-distro", default="Ubuntu-24.04")
    parser.add_argument("--analyzer", default=DEFAULT_ANALYZER)
    parser.add_argument("--strict-port", action="store_true")
    parser.add_argument("--skip-prereq-check", action="store_true")
    parser.add_argument("--skip-analyzer", action="store_true")
    parser.add_argument("--skip-ledger", action="store_true")
    return parser.parse_args(list(argv))


def main(argv: Iterable[str] = sys.argv[1:]) -> int:
    args = parse_args(argv)
    if args.timelimit < 5:
        print("ERROR: --timelimit must be >=5 for fixed-roster validation", file=sys.stderr)
        return 2
    if args.team1 == args.team2:
        print("ERROR: --team1 and --team2 must differ", file=sys.stderr)
        return 2
    if not 1 <= args.komodobot_slot <= 8:
        print("ERROR: --komodobot-slot must be in 1..8", file=sys.stderr)
        return 2
    if args.live_leap and not args.leap_team:
        print("ERROR: --live-leap requires --leap-team (the live brain serves the leap roster)", file=sys.stderr)
        return 2
    if args.stale_ticks < 1:
        print("ERROR: --stale-ticks must be >=1", file=sys.stderr)
        return 2

    if args.live_leap:
        leap_cvars = build_leap_cvar_block(args.shm_name, args.stale_ticks)
        sidecar_cmd = build_sidecar_command(
            args.sidecar_python, args.sidecar_script, args.shm_name, args.sidecar_ckpt, args.sidecar_hz
        )
    else:
        leap_cvars = ""
        sidecar_cmd = ""

    run_id = args.run_id or utc_run_id()
    duration = float(args.duration if args.duration is not None else args.timelimit * 60 + 90)
    local_run_dir = args.out_root / run_id
    local_run_dir.mkdir(parents=True, exist_ok=True)

    try:
        if not args.skip_prereq_check:
            ensure_prereqs(args.host, args.wsl_distro, args.analyzer, args.map_name, args.lab_mvdsv)

        port = choose_lab_port(args.host, args.port, strict=args.strict_port)
        paths = write_run_artifacts(
            local_run_dir,
            run_id=run_id,
            port=port,
            controller_version=args.controller_version,
            komodobot_slot=args.komodobot_slot,
            map_name=args.map_name,
            timelimit=args.timelimit,
            team_names=(args.team1, args.team2),
            leap_team=args.leap_team,
        )
        upload_shim(args.host, run_id)
        run_remote_4v4_lab(
            host=args.host,
            run_id=run_id,
            port=port,
            duration=duration,
            map_name=args.map_name,
            timelimit=args.timelimit,
            mvdsv_bin=args.lab_mvdsv,
            team1=args.team1,
            team2=args.team2,
            local_run_dir=local_run_dir,
            live_leap=args.live_leap,
            shm_name=args.shm_name,
            leap_cvars=leap_cvars,
            sidecar_cmd=sidecar_cmd,
        )
        scp_from_remote(args.host, run_id, local_run_dir)
        parser_exits: dict[str, int] = {}
        if not args.skip_analyzer:
            parser_exits = run_analyzer(local_run_dir, args.wsl_distro, args.analyzer)

        sidecar = local_run_dir / "ktxstats.json"
        if not sidecar.is_file() and (local_run_dir / "demo.json").is_file():
            shutil.copyfile(local_run_dir / "demo.json", sidecar)

        ledger: dict = {}
        if not args.skip_ledger:
            ledger = build_ledger(args.out_root)
            args.ledger_out.parent.mkdir(parents=True, exist_ok=True)
            args.ledger_out.write_text(json.dumps(ledger, indent=2, sort_keys=False) + "\n", encoding="utf-8")
            print(summarize_ledger(ledger))

        write_summary(
            local_run_dir,
            run_id=run_id,
            host=args.host,
            port=port,
            map_name=args.map_name,
            timelimit=args.timelimit,
            duration=duration,
            ledger_out=args.ledger_out,
            ledger=ledger,
            parser_exits=parser_exits,
            live_leap=args.live_leap,
            shm_name=args.shm_name,
            stale_ticks=args.stale_ticks,
        )

        print(f"run_id={run_id}")
        print(f"port={port}")
        print(f"artifacts={local_run_dir}")
        print(f"roster={paths['roster']}")
        print(f"plan={paths['plan']}")
        print(f"summary={local_run_dir / 'run-summary.md'}")
        return 0
    except Exception as exc:
        try:
            scp_from_remote(args.host, run_id, local_run_dir)
        except Exception:
            pass
        (local_run_dir / "runner.error.txt").write_text(f"{type(exc).__name__}: {exc}\n", encoding="utf-8")
        print(f"ERROR: {exc}", file=sys.stderr)
        print(f"artifacts={powershell_safe_path(local_run_dir)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
