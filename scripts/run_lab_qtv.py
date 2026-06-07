#!/usr/bin/env python3
"""Bring up a browser-spectatable QTV stream for the Komodobots lab.

This is a *standalone* launcher, deliberately separate from
``scripts/run_bot_lab.py`` / ``scripts/run_frobodm2_lab.py`` so it cannot disturb
the proven measurement pipeline or the ongoing movement experiments. It only adds
a dedicated, lifecycle-bound MVDSV/KTX process on its own ports and screen
session, and it never edits nQuake-managed configs, ``~/.nquakesv/ports/*``, or
the existing live QTV/QWFWD.

Why this exists
---------------
You want to watch what the bots are doing on the lab server from a browser.
QuakeWorld does this with QTV (QuakeTV): the server exposes a TCP **QTV stream**
and a viewer connects to it. MVDSV has a *built-in* QTV server, so no separate
proxy is required for a single lab server. The exact cvars are confirmed in
``QW-Group/mvdsv`` ``src/sv_demo_qtv.c``:

    qtv_streamport   TCP port the built-in QTV stream listens on
    qtv_password     stream password ("" = open)
    qtv_maxstreams   max concurrent proxy/viewer connections
    qtv_pendingtimeout / qtv_streamtimeout / qtv_sayenabled

``sv_mvdhost`` advertises the public ``host:port`` of the stream so the
QuakeWorld Hub (https://hub.quakeworld.nu/) and clients can link it. We rely on
the same master-server heartbeats MVDSV already sends (we do not override
``sv_master``), so the lab server appears on the Hub like the box's other public
servers and becomes watchable in the browser.

Two guaranteed-correct ways to watch the printed stream:

    * ezQuake (desktop):  /qtvplay tcp:<public-host>:<qtv-port>
    * Browser:            open https://hub.quakeworld.nu/ and click the lab
                          server's "watch" (eye) action, or use a qtvplay link.

Usage
-----
    python scripts/run_lab_qtv.py up   --map dm3 --bot-count 4
    python scripts/run_lab_qtv.py status
    python scripts/run_lab_qtv.py down            # stops all lab QTV sessions
    python scripts/run_lab_qtv.py down --session komodobots_qtv_dm3_28599_<run-id>

``up`` starts the server, populates it with Frogbots, keeps a thin connected
client alive for ``--duration`` so the match stays populated (QTV spectators do
not count as players), prints the watch URLs, and returns immediately leaving the
session running. ``down`` stops only sessions whose names start with
``komodobots_qtv`` and removes only the ``kqtv_*.cfg`` files this launcher wrote.

Verification note: this orchestration talks to ``servexeri`` over SSH and cannot
be exercised from an offline sandbox. The pure helpers (port selection, config
generation, watch-URL building, validation) are covered by
``tests/test_run_lab_qtv.py``; live-server behavior must be confirmed on a host
that can reach ``servexeri`` (see ``docs/05_HEADLESS_TEST_ENV.md``).
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
SHIM_PATH = REPO_ROOT / "experiments" / "qw_min_client.py"

SESSION_PREFIX = "komodobots_qtv"
HUB_URL = "https://hub.quakeworld.nu/"
DEFAULT_GAME_PORT = 28599
# QTV TCP port offset from the game UDP port. Keeps the lab stream clear of the
# conventional 28000 QTV port that nQuake's live QTV/QWFWD may already use.
QTV_PORT_OFFSET = 100


# --------------------------------------------------------------------------- #
# Pure helpers (no network / no side effects) — these are what the unit suite
# exercises, so the deterministic CI floor proves the launcher's logic.
# --------------------------------------------------------------------------- #
def session_name(map_name: str, game_port: int, run_id: str) -> str:
    """Stable, lab-owned screen-session name. The ``komodobots_qtv`` prefix is
    what ``down``/``status`` match on, so it must never overlap nQuake names."""
    return f"{SESSION_PREFIX}_{map_name}_{game_port}_{run_id}"


def derive_qtv_port(game_port: int, qtv_port: int | None) -> int:
    """Resolve the QTV TCP port: explicit value, else game_port + offset."""
    if qtv_port:
        return qtv_port
    return game_port + QTV_PORT_OFFSET


def next_free_port(is_free: Callable[[int], bool], start: int, span: int = 50) -> int:
    """Return the first free port in ``[start, start+span]`` per ``is_free``.

    Network probing is injected as ``is_free`` so this stays pure and testable.
    """
    for candidate in range(start, start + span + 1):
        if is_free(candidate):
            return candidate
    raise RuntimeError(f"No free port found in {start}-{start + span}.")


def build_watch_info(
    public_host: str,
    qtv_port: int,
    server_hostname: str,
    hub_url: str = HUB_URL,
) -> dict[str, str]:
    """Build the viewer-facing connection details for a live stream."""
    tcp = f"tcp:{public_host}:{qtv_port}"
    return {
        "server_hostname": server_hostname,
        "tcp_stream": tcp,
        "ezquake_command": f"qtvplay {tcp}",
        "hub_url": hub_url,
    }


def build_qtv_cfg(
    *,
    run_id: str,
    game_port: int,
    qtv_port: int,
    qtv_password: str,
    public_host: str,
    map_name: str,
    hostname: str,
    skill: int = 10,
) -> str:
    """Generate the dedicated lab KTX config text.

    This config is written under a unique ``kqtv_<map>_<port>.cfg`` name and is
    removed by ``down``. It mirrors the matchless FFA settings the measurement
    lab uses, drops all moveprobe cvars (bots run stock for spectating), and adds
    the built-in QTV stream cvars. ``timelimit 0`` keeps the FFA running so the
    stream stays interesting for as long as the session is up.
    """
    pw = qtv_password.replace('"', "")
    return "\n".join(
        [
            f"// Auto-generated Komodobots QTV spectate lab config {run_id}",
            "// Dedicated lab process. Does NOT modify nQuake-managed configs,",
            "// ~/.nquakesv/ports/*, or the existing live QTV/QWFWD.",
            f'hostname "{hostname}"',
            f'set k_motd1 "Komodobots QTV lab {run_id}"',
            "set k_matchless 1",
            "set k_use_matchless_dir 1",
            "set k_defmode ffa",
            "set k_mode 3",
            f"set k_defmap {map_name}",
            "set k_fb_enabled 0",
            "set k_count 0",
            "set k_matchless_countdown 0",
            f"set k_fb_skill {skill}",
            "timelimit 0",
            "fraglimit 0",
            "samelevel 1",
            "set demo_tmp_record 1",
            "set k_demo_mintime 0",
            "set k_demotxt_format json",
            "sv_demotxt 2",
            "sv_demofps 77",
            "sv_demodir demos",
            "// --- built-in MVDSV QTV stream (QW-Group/mvdsv src/sv_demo_qtv.c) ---",
            f"qtv_streamport {qtv_port}",
            f'qtv_password "{pw}"',
            "qtv_maxstreams 100",
            f'sv_mvdhost "{public_host}:{qtv_port}"',
            f'serverinfo hostname "{hostname}"',
            "",
        ]
    )


def validate_map_name(map_name: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_+-]+", map_name):
        raise argparse.ArgumentTypeError(
            "Map names may only contain letters, digits, underscore, plus, or dash."
        )
    return map_name


def validate_run_id(run_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
        raise argparse.ArgumentTypeError(
            "Run IDs may only contain letters, digits, underscore, or dash."
        )
    return run_id


def validate_session(session: str) -> str:
    if not session.startswith(SESSION_PREFIX + "_"):
        raise argparse.ArgumentTypeError(
            f"Refusing to target a session that is not lab-owned "
            f"(must start with '{SESSION_PREFIX}_'): {session}"
        )
    if not re.fullmatch(r"[A-Za-z0-9_+-]+", session):
        raise argparse.ArgumentTypeError(
            "Session names may only contain letters, digits, underscore, plus, or dash."
        )
    return session


def validate_public_host(value: str) -> str:
    if value == "auto":
        return value
    if not re.fullmatch(r"[A-Za-z0-9_.:-]+", value):
        raise argparse.ArgumentTypeError(
            "Public host must be an IP/DNS name (letters, digits, dot, dash, colon) or 'auto'."
        )
    return value


def validate_port(value: str) -> int:
    port = int(value)
    if not (1 <= port <= 65535):
        raise argparse.ArgumentTypeError("Port must be in 1-65535.")
    return port


def utc_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# --------------------------------------------------------------------------- #
# Remote orchestration (mirrors scripts/run_frobodm2_lab.py conventions:
# `ssh host bash -s -- args...` with the script piped on stdin).
# --------------------------------------------------------------------------- #
REMOTE_UP_SCRIPT = r"""#!/usr/bin/env bash
set -euo pipefail

run_id="$1"
game_port="$2"
qtv_port="$3"
map_name="$4"
bot_count="$5"
bot_spacing="$6"
duration="$7"
cfg_b64="$8"

session="komodobots_qtv_${map_name}_${game_port}_${run_id}"
rundir="$HOME/komodobots-lab/qtv/$run_id"
nq="$HOME/nquakesv"
cfg_name="kqtv_${map_name}_${game_port}.cfg"
cfg_path="$nq/ktx/$cfg_name"

log() { printf '[remote] %s\n' "$*"; }
session_exists() { screen -ls | grep -q "[.]${session}[[:space:]]"; }
send_cmd() {
  local cmd="$1"; local delay="${2:-0.5}"
  screen -S "$session" -p 0 -X stuff "$(printf '\025%s\r' "$cmd")"
  sleep "$delay"
}

if session_exists; then echo "Session already running: $session" >&2; exit 2; fi
if [ ! -x "$nq/mvdsv" ]; then echo "Missing executable: $nq/mvdsv" >&2; exit 3; fi
if [ ! -f "$nq/qw/maps/${map_name}.bsp" ]; then echo "Missing map: $nq/qw/maps/${map_name}.bsp" >&2; exit 4; fi
if [ ! -f "$rundir/qw_min_client.py" ]; then echo "Missing uploaded shim: $rundir/qw_min_client.py" >&2; exit 6; fi

mkdir -p "$rundir"
printf '%s' "$cfg_b64" | base64 -d > "$cfg_path"
cp "$cfg_path" "$rundir/lab.cfg"

log "starting $session on game port $game_port (qtv tcp $qtv_port)"
cd "$nq"
screen -L -Logfile "$rundir/screen.log" -dmS "$session" ./mvdsv -port "$game_port" -mem 64 -game ktx +exec "$cfg_name"

server_up=0
for _ in $(seq 1 40); do
  qs="$(quakestat -qws "localhost:$game_port" -P -nh 2>/dev/null || true)"
  if [ -n "$qs" ] && ! printf '%s' "$qs" | grep -q 'DOWN'; then server_up=1; break; fi
  sleep 0.5
done
if [ "$server_up" -ne 1 ]; then echo "Server did not come up on port $game_port" >&2; screen -S "$session" -X quit || true; exit 7; fi

send_cmd "set k_fb_enabled 1"
send_cmd "set k_fb_autoadd_limit 0"
send_cmd "set k_fb_auto_delay 1"
send_cmd "map $map_name" 1.0
send_cmd "sv_democancel"
send_cmd "sv_demoeasyrecord komodobots_qtv_${map_name}_${run_id}" 1.0

# Confirm the QTV stream port is actually listening before we advertise it.
qtv_listening=0
if command -v ss >/dev/null 2>&1; then
  if ss -Hltn 2>/dev/null | grep -q ":${qtv_port} "; then qtv_listening=1; fi
fi

# Keep a thin connected client alive for the spectate window so the match stays
# populated (QTV spectators do not count as server players, so without this the
# Frogbots would drain once no human is present). Detached with setsid so it
# survives the SSH channel closing.
log "launching keepalive client shim in background for ${duration}s"
setsid bash -c "python3 '$rundir/qw_min_client.py' '$game_port' --host 127.0.0.1 --run-for '$duration' --bot-count '$bot_count' --bot-spacing '$bot_spacing' > '$rundir/pyclient.stdout' 2> '$rundir/pyclient.stderr'" < /dev/null &
shim_pid=$!
echo "$shim_pid" > "$rundir/shim.pid"

screen -S "$session" -p 0 -X hardcopy "$rundir/hardcopy.up.txt"

cat > "$rundir/session.json" <<EOF
{
  "run_id": "$run_id",
  "session": "$session",
  "game_port": $game_port,
  "qtv_port": $qtv_port,
  "map": "$map_name",
  "bot_count": $bot_count,
  "duration_s": $duration,
  "qtv_listening": $qtv_listening,
  "shim_pid": $shim_pid,
  "cfg_path": "$cfg_path",
  "started_utc": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF

log "QTV_LISTENING=$qtv_listening"
log "SESSION=$session"
log "GAME_PORT=$game_port"
log "QTV_PORT=$qtv_port"
echo "OK"
"""


REMOTE_DOWN_SCRIPT = r"""#!/usr/bin/env bash
set -euo pipefail
target="${1:-}"
nq="$HOME/nquakesv"

mapfile -t sessions < <(screen -ls 2>/dev/null | sed -n 's/^[[:space:]]*[0-9]\+\.\(komodobots_qtv[A-Za-z0-9_+-]*\).*/\1/p' | sort -u)

stopped=0
for s in "${sessions[@]}"; do
  [ -n "$s" ] || continue
  if [ -n "$target" ] && [ "$s" != "$target" ]; then continue; fi
  # Best-effort: stop recording, then quit only this lab session.
  screen -S "$s" -p 0 -X stuff "$(printf '\025%s\r' "sv_demostop")" 2>/dev/null || true
  sleep 0.5
  screen -S "$s" -X quit 2>/dev/null || true
  echo "stopped $s"
  stopped=$((stopped + 1))
done

# Remove only the configs this launcher writes.
if [ -d "$nq/ktx" ]; then
  find "$nq/ktx" -maxdepth 1 -type f -name 'kqtv_*.cfg' -delete 2>/dev/null || true
fi

echo "STOPPED=$stopped"
"""


REMOTE_STATUS_SCRIPT = r"""#!/usr/bin/env bash
set -euo pipefail
mapfile -t sessions < <(screen -ls 2>/dev/null | sed -n 's/^[[:space:]]*[0-9]\+\.\(komodobots_qtv[A-Za-z0-9_+-]*\).*/\1/p' | sort -u)
if [ "${#sessions[@]}" -eq 0 ]; then echo "NO_SESSIONS"; exit 0; fi
for s in "${sessions[@]}"; do
  [ -n "$s" ] || continue
  port="$(printf '%s' "$s" | sed -n 's/.*_\([0-9]\+\)_[^_]*$/\1/p')"
  qs="$(quakestat -qws "localhost:${port}" -P -nh 2>/dev/null || true)"
  echo "SESSION=$s PORT=$port STATUS=${qs:-unknown}"
done
"""


def run(args: list[str], *, input_text: str | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    if input_text is None:
        proc = subprocess.run(args, text=True, capture_output=True)
    else:
        raw = subprocess.run(
            args,
            input=input_text.replace("\r\n", "\n").encode("utf-8"),
            capture_output=True,
        )
        proc = subprocess.CompletedProcess(
            raw.args,
            raw.returncode,
            raw.stdout.decode("utf-8", "replace"),
            raw.stderr.decode("utf-8", "replace"),
        )
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"Command failed ({proc.returncode}): {' '.join(args)}\n"
            f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
    return proc


def require_tool(name: str) -> None:
    if shutil.which(name) is None:
        raise RuntimeError(f"Required tool not found on PATH: {name}")


def udp_port_free(host: str, port: int) -> bool:
    proc = run(
        ["ssh", host, f"quakestat -qws localhost:{port} -P -nh 2>/dev/null || true"],
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Could not query UDP port {port} on {host}: {proc.stderr.strip()}")
    out = proc.stdout.strip()
    return not out or "DOWN" in out


def tcp_port_free(host: str, port: int) -> bool:
    proc = run(
        ["ssh", host, f"ss -Hltn 2>/dev/null | grep -q ':{port} ' && echo BUSY || echo FREE"],
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Could not query TCP port {port} on {host}: {proc.stderr.strip()}")
    return "BUSY" not in proc.stdout


def detect_public_host(host: str) -> str:
    proc = run(
        ["ssh", host, "curl -s --max-time 5 https://api.ipify.org || hostname -I | awk '{print $1}'"],
        check=False,
    )
    detected = (proc.stdout or "").strip().split()
    if not detected:
        raise RuntimeError(
            "Could not auto-detect the public host. Pass --public-host <ip-or-dns> explicitly."
        )
    return detected[0]


def ensure_prereqs(host: str, map_name: str) -> None:
    for tool in ("ssh", "scp"):
        require_tool(tool)
    if not SHIM_PATH.is_file():
        raise RuntimeError(f"Missing shim: {SHIM_PATH}")
    remote_check = (
        "python3 --version >/dev/null && "
        "command -v screen >/dev/null && "
        "command -v quakestat >/dev/null && "
        "command -v base64 >/dev/null && "
        "command -v ss >/dev/null && "
        "test -x ~/nquakesv/mvdsv && "
        f"test -f ~/nquakesv/qw/maps/{map_name}.bsp"
    )
    run(["ssh", host, remote_check])


def upload_shim(host: str, run_id: str) -> None:
    remote_dir = f"komodobots-lab/qtv/{run_id}"
    run(["ssh", host, f"mkdir -p {remote_dir}"])
    run(["scp", str(SHIM_PATH.resolve()), f"{host}:{remote_dir}/qw_min_client.py"])


def print_watch_block(watch: dict[str, str], qtv_listening: bool) -> None:
    print()
    print("=" * 70)
    print("  Komodobots lab QTV stream is up")
    print("=" * 70)
    print(f"  Server on Hub : {watch['server_hostname']}")
    print(f"  Browser       : {watch['hub_url']}")
    print("                  (find the server above, click its watch/eye action)")
    print(f"  ezQuake       : /{watch['ezquake_command']}")
    print(f"  Raw stream    : {watch['tcp_stream']}")
    if not qtv_listening:
        print()
        print("  NOTE: the QTV stream port was not yet confirmed listening when")
        print("        the server came up. Give it a few seconds and re-check with")
        print("        'python scripts/run_lab_qtv.py status'. If it stays down,")
        print("        the deployed MVDSV build may lack QTV support or the TCP")
        print("        port may be firewalled.")
    print("=" * 70)
    print()


def cmd_up(args: argparse.Namespace) -> int:
    run_id = args.run_id or utc_run_id()
    ensure_prereqs(args.host, args.map_name)

    public_host = args.public_host
    if public_host == "auto":
        public_host = detect_public_host(args.host)
        print(f"Auto-detected public host: {public_host}")

    game_port = next_free_port(lambda p: udp_port_free(args.host, p), args.game_port)
    if args.strict_port and game_port != args.game_port:
        raise RuntimeError(f"Requested game port {args.game_port} is already in use on {args.host}.")
    qtv_start = derive_qtv_port(game_port, args.qtv_port)
    qtv_port = next_free_port(lambda p: tcp_port_free(args.host, p), qtv_start)

    hostname = f"komodobots-lab-qtv:{game_port}"
    cfg = build_qtv_cfg(
        run_id=run_id,
        game_port=game_port,
        qtv_port=qtv_port,
        qtv_password=args.qtv_password,
        public_host=public_host,
        map_name=args.map_name,
        hostname=hostname,
        skill=args.skill,
    )

    upload_shim(args.host, run_id)
    proc = run(
        [
            "ssh", args.host, "bash", "-s", "--",
            run_id,
            str(game_port),
            str(qtv_port),
            args.map_name,
            str(args.bot_count),
            str(args.bot_spacing),
            str(args.duration),
            base64.b64encode(cfg.encode("utf-8")).decode("ascii"),
        ],
        input_text=REMOTE_UP_SCRIPT,
        check=False,
    )
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    if proc.returncode != 0:
        raise RuntimeError(f"Remote 'up' failed with exit {proc.returncode}.")

    qtv_listening = "QTV_LISTENING=1" in proc.stdout
    watch = build_watch_info(public_host, qtv_port, hostname)
    print_watch_block(watch, qtv_listening)
    print("To stop this stream later:")
    print(f"  python scripts/run_lab_qtv.py down --session {session_name(args.map_name, game_port, run_id)}")
    return 0


def cmd_down(args: argparse.Namespace) -> int:
    require_tool("ssh")
    target = args.session or ""
    proc = run(["ssh", args.host, "bash", "-s", "--", target], input_text=REMOTE_DOWN_SCRIPT, check=False)
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    if proc.returncode != 0:
        raise RuntimeError(f"Remote 'down' failed with exit {proc.returncode}.")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    require_tool("ssh")
    proc = run(["ssh", args.host, "bash", "-s"], input_text=REMOTE_STATUS_SCRIPT, check=False)
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    if proc.returncode != 0:
        raise RuntimeError(f"Remote 'status' failed with exit {proc.returncode}.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="servexeri", help="SSH host. Defaults to servexeri.")
    sub = parser.add_subparsers(dest="command", required=True)

    up = sub.add_parser("up", help="Start a dedicated, spectatable QTV lab session.")
    up.add_argument("--map", dest="map_name", type=validate_map_name, default="dm3", help="Map to load (needs a Frogbot route). Defaults to dm3.")
    up.add_argument("--bot-count", type=int, default=4, help="Frogbots to spawn. Defaults to 4.")
    up.add_argument("--bot-spacing", type=float, default=8.0, help="Seconds between bot adds. Defaults to 8.")
    up.add_argument("--duration", type=float, default=3600.0, help="Seconds to keep the match populated. Defaults to 3600.")
    up.add_argument("--game-port", type=validate_port, default=DEFAULT_GAME_PORT, help="Preferred MVDSV UDP game port. Defaults to 28599.")
    up.add_argument("--qtv-port", type=validate_port, default=None, help="QTV TCP stream port. Defaults to game-port + 100.")
    up.add_argument("--public-host", type=validate_public_host, default="auto", help="Public IP/DNS advertised for the stream, or 'auto'. Defaults to auto.")
    up.add_argument("--qtv-password", default="", help="QTV stream password. Default empty (open).")
    up.add_argument("--skill", type=int, default=10, help="Frogbot skill. Defaults to 10.")
    up.add_argument("--run-id", type=validate_run_id, default=None, help="Run ID. Defaults to current UTC timestamp.")
    up.add_argument("--strict-port", action="store_true", help="Fail instead of auto-bumping if the preferred game port is busy.")
    up.set_defaults(func=cmd_up)

    down = sub.add_parser("down", help="Stop lab QTV sessions and remove lab configs.")
    down.add_argument("--session", type=validate_session, default=None, help="Stop only this lab session. Default: all komodobots_qtv sessions.")
    down.set_defaults(func=cmd_down)

    status = sub.add_parser("status", help="Show running lab QTV sessions.")
    status.set_defaults(func=cmd_status)

    return parser


def main(argv: Iterable[str] = sys.argv[1:]) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv))
    try:
        return args.func(args)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
