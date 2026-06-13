#!/usr/bin/env python3
"""Bring up a browser-spectatable QTV stream for the Komodobots lab.

This is a *standalone* launcher, deliberately separate from
``scripts/run_bot_lab.py`` / ``scripts/run_frobodm2_lab.py`` so it cannot disturb
the proven measurement pipeline or the ongoing movement experiments. It only adds
a dedicated, lifecycle-bound MVDSV/KTX process on its own port and screen
session, and it never edits nQuake-managed configs, ``~/.nquakesv/ports/*``, or
the existing live QTV/QWFWD.

Why this exists
---------------
You want to watch what the bots are doing on the lab server from a browser.
QuakeWorld does this with QTV (QuakeTV): the server exposes a TCP **QTV stream**
and a viewer connects to it. MVDSV has a *built-in* QTV server, so no separate
proxy is required for a single lab server. The exact cvars are confirmed in
``QW-Group/mvdsv`` ``src/sv_demo_qtv.c`` and in servexeri's live configs:

    qtv_streamport   TCP port the built-in QTV stream listens on (0 disables it)
    qtv_password     stream password ("" = open)
    qtv_maxstreams   max concurrent proxy/viewer connections

**Port model (matches the live servexeri servers).** Each live server
(``ktx/port_2850x.cfg``) sets ``qtv_streamport`` equal to its game port, and
servexeri's firewall (ufw) only allows the standard QW ports (28501-28503). So
this launcher serves QTV on the *same* port number as the game port -- one port
to firewall-open -- instead of a separate offset port that would never be
reachable. There is **no** ``sv_mvdhost``: that cvar does not exist on this
mvdsv build (it logs ``Unknown command``); the public address is only used to
build the printed ``qtvplay`` link.

Keeping the match populated (the reconnect-loop)
------------------------------------------------
QTV spectators do not count as server players, so the match needs a connected
"player" to hold it and let KTX's auto-add (``k_fb_autoadd_limit``) maintain the
bots -- ``BotStartFrame`` (``ktx/src/bot_commands.c``) only adds bots while a
human is present. But mvdsv **login-times-out a non-logged-in client at exactly
60s** (``SV_LoginCheckTimeOut``, ``sv_login.c``; the minimal keepalive client
isn't a real logged-in account, so it cannot avoid this). A single keepalive
therefore drops at 60s and the match drains.

The fix is a **reconnect LOOP on a cycle shorter than the 60s timeout**
(``KEEPALIVE_CYCLE_S``): the previous connection lingers until its 60s drop while
the next connects at ~45s, so presence overlaps and the server never empties --
no flicker, no bot accumulation. The keepalive adds NO bots itself; autoadd does
(``k_fb_autoadd_limit`` = bot_count + 1, the +1 covering the keepalive human).

Two guaranteed-correct ways to watch the printed stream:

    * ezQuake (desktop):  /qtvplay <public-host>:<qtv-port>   (NO "tcp:" prefix --
                          ezQuake's qtvplay does not parse a tcp: scheme)
    * Browser:            open https://hub.quakeworld.nu/ and click the lab
                          server's "watch" (eye) action, or use a qtvplay link.

If the off-host reachability probe reports NOT reachable, the lab port is
firewalled (see the printed ufw hint) -- until it's opened you can still watch
over an SSH tunnel: ``ssh -N -L <port>:127.0.0.1:<port> servexeri`` then
``/qtvplay 127.0.0.1:<port>``.

Usage
-----
    python scripts/run_lab_qtv.py up   --map dm3 --bot-count 4
    python scripts/run_lab_qtv.py status
    python scripts/run_lab_qtv.py down            # stops all lab QTV sessions
    python scripts/run_lab_qtv.py down --session komodobots_qtv_dm3_28599_<run-id>

``up`` starts the server, launches the reconnect-loop keepalive so KTX keeps the
match populated, prints the watch URLs, runs a real off-host reachability probe,
and returns immediately leaving the session running (it self-terminates after
``--duration``). ``down`` stops only sessions whose names start with
``komodobots_qtv`` and removes only the ``kqtv_*.cfg`` files this launcher wrote.

Verification note: this orchestration talks to ``servexeri`` over SSH and cannot
be exercised from an offline sandbox. The pure helpers (port selection, config
generation, watch-URL building, LAN-IP selection, reachability decision, and
validation) are covered by ``tests/test_run_lab_qtv.py``; live-server behavior
must be confirmed on a host that can reach ``servexeri`` (see
``docs/05_HEADLESS_TEST_ENV.md``).
"""

from __future__ import annotations

import argparse
import base64
import re
import shutil
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
SHIM_PATH = REPO_ROOT / "experiments" / "qw_min_client.py"

SESSION_PREFIX = "komodobots_qtv"
HUB_URL = "https://hub.quakeworld.nu/"
# Dedicated QTV port, deliberately clear of the moveprobe lab's 28599
# (run_frobodm2_lab.py) and the live servers (qtv 28000, game 28501-28503,
# qwfwd 30000). Keeping it distinct means the QTV lab never auto-bumps off a
# busy 28599 onto a non-firewalled port while the movement experiments run.
DEFAULT_GAME_PORT = 28610
# mvdsv drops a non-logged-in client this many seconds after connect
# (SV_LoginCheckTimeOut, QW-Group/mvdsv src/sv_login.c -- hardcoded "> 60").
LOGIN_TIMEOUT_S = 60
# The keepalive must reconnect BEFORE that, so the old connection still lingers
# (until its own 60s drop) when the next one connects -> continuous presence.
KEEPALIVE_CYCLE_S = 45


# --------------------------------------------------------------------------- #
# Pure helpers (no network / no side effects) — these are what the unit suite
# exercises, so the deterministic CI floor proves the launcher's logic.
# --------------------------------------------------------------------------- #
def session_name(map_name: str, game_port: int, run_id: str) -> str:
    """Stable, lab-owned screen-session name. The ``komodobots_qtv`` prefix is
    what ``down``/``status`` match on, so it must never overlap nQuake names."""
    return f"{SESSION_PREFIX}_{map_name}_{game_port}_{run_id}"


def derive_qtv_port(game_port: int, qtv_port: int | None) -> int:
    """Resolve the QTV TCP port.

    Defaults to the **game port** — the proven servexeri model (live
    ``port_2850x.cfg`` set ``qtv_streamport`` equal to the game port), so a
    single port needs firewall-opening. An explicit value still wins.
    """
    if qtv_port:
        return qtv_port
    return game_port


def next_free_port(is_free: Callable[[int], bool], start: int, span: int = 50) -> int:
    """Return the first free port in ``[start, start+span]`` per ``is_free``.

    Network probing is injected as ``is_free`` so this stays pure and testable.
    """
    for candidate in range(start, start + span + 1):
        if is_free(candidate):
            return candidate
    raise RuntimeError(f"No free port found in {start}-{start + span}.")


def pick_lan_ip(hostname_i_output: str) -> str:
    """Pick the routable LAN address from ``hostname -I`` output.

    Prefers an RFC1918 LAN address (192.168/16 first, then 10/8, then 172.16/12)
    over Tailscale CGNAT (100.64/10) and docker bridges, falling back to the
    first token. Used instead of an ipify/ifconfig.me lookup, which on servexeri
    returns the Cloudflare WARP egress IP — a non-inbound address that no viewer
    can connect back to.
    """
    tokens = hostname_i_output.split()
    if not tokens:
        raise RuntimeError("Empty `hostname -I` output; pass --public-host explicitly.")

    def first_with(prefixes: tuple[str, ...]) -> str | None:
        for tok in tokens:
            if any(tok.startswith(p) for p in prefixes):
                return tok
        return None

    for prefixes in (
        ("192.168.",),
        ("10.",),
        tuple(f"172.{n}." for n in range(16, 32)),
    ):
        hit = first_with(prefixes)
        if hit:
            return hit
    return tokens[0]


def build_watch_info(
    public_host: str,
    qtv_port: int,
    server_hostname: str,
    hub_url: str = HUB_URL,
) -> dict[str, str]:
    """Build the viewer-facing connection details for a live stream."""
    stream = f"{public_host}:{qtv_port}"
    return {
        "server_hostname": server_hostname,
        "tcp_stream": f"tcp:{stream}",
        # ezQuake's qtvplay wants a bare host:port -- it does NOT understand a
        # "tcp:" scheme: CL_QTVPlay_f -> NET_StringToSockaddr mis-splits "tcp:"
        # on ':' and tries to resolve "tcp" as a hostname, printing "Couldn't
        # connect to proxy" before opening any socket. (Verified in the source:
        # Xerialen/ezquake-source src/cl_demo.c, src/net.c.) The built-in
        # QTVSV 1 stream itself IS directly watchable -- no proxy required.
        "ezquake_command": f"qtvplay {stream}",
        "hub_url": hub_url,
    }


def build_qtv_cfg(
    *,
    run_id: str,
    game_port: int,
    qtv_port: int,
    qtv_password: str,
    map_name: str,
    hostname: str,
    skill: int = 10,
    bot_count: int = 4,
) -> str:
    """Generate the dedicated lab KTX config text.

    This config is written under a unique ``kqtv_<map>_<port>.cfg`` name and is
    removed by ``down``. It mirrors the matchless FFA settings the measurement
    lab uses, drops all moveprobe cvars (bots run stock for spectating), keeps
    the match populated via KTX auto-add (paired with the reconnect-loop
    keepalive that supplies the required human presence), and adds the built-in
    QTV stream cvars. ``timelimit 0`` keeps the FFA running so the stream stays
    interesting for as long as the session is up.
    """
    pw = sanitize_qtv_password(qtv_password)
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
            "set k_count 0",
            "set k_matchless_countdown 0",
            "// --- bots: KTX auto-add maintains the bot count, but only while a",
            "//     human is present (BotStartFrame requires human_count>0, ktx",
            "//     bot_commands.c). The reconnect-loop keepalive supplies that",
            "//     presence; autoadd_limit is bot_count+1 to account for it. ---",
            "set k_fb_enabled 1",
            f"set k_fb_skill {skill}",
            f"set k_fb_autoadd_limit {bot_count + 1}",
            "set k_fb_auto_delay 1",
            "timelimit 0",
            "fraglimit 0",
            "samelevel 1",
            "set demo_tmp_record 1",
            "set k_demo_mintime 0",
            "set k_demotxt_format json",
            "sv_demotxt 2",
            "sv_demofps 77",
            "sv_demodir demos",
            "// --- built-in MVDSV QTV stream (QW-Group/mvdsv src/sv_demo_qtv.c).",
            "//     qtv_streamport == game port: the proven servexeri model, so a",
            "//     single port needs firewall-opening. No MVD-host advertise",
            "//     cvar: this mvdsv build rejects it (logs Unknown command). ---",
            f"qtv_streamport {qtv_port}",
            f'qtv_password "{pw}"',
            "qtv_maxstreams 100",
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
    if not re.fullmatch(r"[A-Za-z0-9-]+", run_id):
        raise argparse.ArgumentTypeError(
            "Run IDs may only contain letters, digits, or dash."
        )
    return run_id


def sanitize_qtv_password(qtv_password: str) -> str:
    if any(ord(ch) < 32 for ch in qtv_password):
        raise argparse.ArgumentTypeError("QTV password may not contain control characters.")
    return qtv_password.replace('"', "")


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
duration="$5"
cycle="$6"
cfg_b64="$7"

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
if [ ! -f "$rundir/qw_min_client.py" ]; then echo "Missing uploaded keepalive shim: $rundir/qw_min_client.py" >&2; exit 6; fi

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

send_cmd "map $map_name" 1.0
send_cmd "sv_democancel"
send_cmd "sv_demoeasyrecord komodobots_qtv_${map_name}_${run_id}" 1.0

# Local bind check (informational ONLY). A match means the socket is bound on
# the host; it does NOT prove off-host reachability (a firewall sits in between)
# -- the launcher runs a real off-host TCP probe for that.
qtv_bound=0
if command -v ss >/dev/null 2>&1; then
  if ss -Hltn 2>/dev/null | grep -q ":${qtv_port} "; then qtv_bound=1; fi
fi

# --- Keep the match populated with NO flicker. mvdsv login-times-out a
# non-logged-in client at exactly 60s (SV_LoginCheckTimeOut, sv_login.c), so a
# single keepalive drops and drains the match. Instead run a reconnect LOOP on a
# cycle SHORTER than that timeout: the old connection lingers until its 60s drop
# while the next connects at ~cycle s, so presence overlaps and the server never
# empties. The keepalive adds NO bots (--bot-count 0); KTX k_fb_autoadd_limit
# (in the cfg) maintains the bot count while a human is present. When `duration`
# elapses the loop tears the session down. Detached so it survives SSH close. ---
cat > "$rundir/keepalive.sh" <<KEEPALIVE
#!/usr/bin/env bash
end=\$(( \$(date +%s) + ${duration%.*} ))
while [ \$(date +%s) -lt \$end ]; do
  python3 "$rundir/qw_min_client.py" "$game_port" --host 127.0.0.1 --run-for $cycle --bot-count 0 --quiet >> "$rundir/keepalive.log" 2>&1 || true
done
screen -S "$session" -X quit 2>/dev/null || true
rm -f "$cfg_path" 2>/dev/null || true
KEEPALIVE
chmod +x "$rundir/keepalive.sh"
setsid bash "$rundir/keepalive.sh" </dev/null >/dev/null 2>&1 &
echo "$!" > "$rundir/keepalive.pid"
log "keepalive reconnect-loop started (cycle ${cycle}s, runs ${duration}s)"

screen -S "$session" -p 0 -X hardcopy "$rundir/hardcopy.up.txt"

cat > "$rundir/session.json" <<EOF
{
  "run_id": "$run_id",
  "session": "$session",
  "game_port": $game_port,
  "qtv_port": $qtv_port,
  "map": "$map_name",
  "duration_s": $duration,
  "cycle_s": $cycle,
  "qtv_bound": $qtv_bound,
  "cfg_path": "$cfg_path",
  "started_utc": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF

log "QTV_BOUND=$qtv_bound"
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
  # Stop the reconnect-loop keepalive for this run, then the recording, then the
  # session. Only ever touches this run's own rundir + lab-owned session.
  run_id="${s##*_}"
  kp="$HOME/komodobots-lab/qtv/$run_id/keepalive.pid"
  [ -f "$kp" ] && kill "$(cat "$kp")" 2>/dev/null || true
  pkill -f "komodobots-lab/qtv/$run_id/keepalive.sh" 2>/dev/null || true
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


# Live attach/detach: turn the built-in QTV stream ON or OFF on an
# ALREADY-RUNNING komodobots lab server (e.g. a moveprobe experiment) without
# editing run_frobodm2_lab.py. QTV is a passive re-broadcast of the MVD the
# experiment already records, and a spectator is not a player, so this does not
# change the recorded measurement. The script REFUSES unless the port is owned
# by a `komodobots_*` screen session, so it can never touch the live
# qw_2850x / qtv / qwfwd servers.
REMOTE_ATTACH_SCRIPT = r"""#!/usr/bin/env bash
set -euo pipefail
port="$1"
action="$2"   # "on" -> qtv_streamport=port ; "off" -> qtv_streamport 0

# Match the REAL mvdsv process only (pgrep -x on the exact comm), not the
# `SCREEN ... ./mvdsv -port N` wrapper whose argv also contains the string.
mvd_pid=""
for pid in $(pgrep -x mvdsv 2>/dev/null || true); do
  if ps -o args= -p "$pid" 2>/dev/null | grep -q -- "-port ${port} "; then mvd_pid="$pid"; break; fi
done
if [ -z "$mvd_pid" ]; then echo "No mvdsv running on port ${port}." >&2; exit 3; fi
scr_pid="$(ps -o ppid= -p "$mvd_pid" 2>/dev/null | tr -d ' ')"
sess="$(screen -ls 2>/dev/null | sed -n "s/^[[:space:]]*${scr_pid}\.\(komodobots_[A-Za-z0-9_+-]*\).*/\1/p" | head -1)"
if [ -z "$sess" ]; then
  echo "Port ${port} is NOT owned by a komodobots lab screen session -- refusing to touch it." >&2
  exit 4
fi

if [ "$action" = "on" ]; then val="$port"; else val="0"; fi
screen -S "$sess" -p 0 -X stuff "$(printf '\025qtv_streamport %s\r' "$val")"
sleep 0.6

listening=0
if command -v ss >/dev/null 2>&1; then
  if ss -Hltn 2>/dev/null | grep -q ":${port} "; then listening=1; fi
fi
echo "SESSION=$sess"
echo "QTV_STREAMPORT=$val"
echo "TCP_LISTENING=$listening"
echo "OK"
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


def tcp_reachable(
    host: str,
    port: int,
    *,
    timeout: float = 6.0,
    connector: Callable[[tuple[str, int], float], object] | None = None,
) -> bool:
    """Real off-host reachability: can we open a TCP connection to host:port?

    The launcher runs OFF servexeri, so this is an honest end-to-end check that
    a remote viewer (ezQuake / the Hub) could reach the stream — unlike a
    server-side ``ss | grep :port``, which also matches localhost-only binds and
    cannot see a firewall in the way. ``connector`` is injected for testing.
    """
    if connector is None:
        connector = socket.create_connection
    try:
        sock = connector((host, port), timeout)
    except OSError:
        return False
    close = getattr(sock, "close", None)
    if callable(close):
        try:
            close()
        except OSError:
            pass
    return True


def detect_public_host(host: str) -> str:
    proc = run(["ssh", host, "hostname -I"], check=False)
    if proc.returncode != 0:
        raise RuntimeError(
            f"Could not run 'hostname -I' on {host} to auto-detect the LAN address. "
            f"Pass --public-host <ip-or-dns> explicitly. stderr: {proc.stderr.strip()}"
        )
    return pick_lan_ip(proc.stdout or "")


def ensure_prereqs(host: str, map_name: str) -> None:
    for tool in ("ssh", "scp"):
        require_tool(tool)
    if not SHIM_PATH.is_file():
        raise RuntimeError(f"Missing keepalive shim: {SHIM_PATH}")
    remote_check = (
        "python3 --version >/dev/null && "
        "command -v screen >/dev/null && "
        "command -v quakestat >/dev/null && "
        "command -v base64 >/dev/null && "
        "test -x ~/nquakesv/mvdsv && "
        f"test -f ~/nquakesv/qw/maps/{map_name}.bsp"
    )
    run(["ssh", host, remote_check])


def upload_shim(host: str, run_id: str) -> None:
    remote_dir = f"komodobots-lab/qtv/{run_id}"
    run(["ssh", host, f"mkdir -p {remote_dir}"])
    run(["scp", str(SHIM_PATH.resolve()), f"{host}:{remote_dir}/qw_min_client.py"])


def print_watch_block(watch: dict[str, str], reachable: bool, host: str = "servexeri") -> None:
    port = watch["tcp_stream"].rsplit(":", 1)[-1]
    print()
    print("=" * 70)
    print("  Komodobots lab QTV stream is up")
    print("=" * 70)
    print(f"  Server on Hub : {watch['server_hostname']}")
    print(f"  Browser       : {watch['hub_url']}")
    print("                  (find the server above, click its watch/eye action)")
    print(f"  ezQuake       : /{watch['ezquake_command']}")
    print(f"  Raw stream    : {watch['tcp_stream']}")
    print("-" * 70)
    if reachable:
        print("  Reachability  : OK - the QTV port answered an off-host TCP")
        print("                  connect, so a viewer can watch it now.")
    else:
        print("  Reachability  : NOT reachable off-host - a TCP connect to")
        print(f"                  {watch['tcp_stream']} failed. The stream is bound on the")
        print("                  server but a firewall blocks it before any viewer.")
        print("                  servexeri's ufw only allows the standard QW ports")
        print("                  (28501-28503); this lab port needs opening:")
        print(f"                    sudo ufw allow {port}/tcp   # QTV stream")
        print(f"                    sudo ufw allow {port}/udp   # game + master heartbeat")
        print("                  LAN ezQuake watching needs only the ufw rule; for")
        print("                  browser/Hub watching also forward the port on the router.")
        print("                  Or watch now with no firewall change, via an SSH tunnel:")
        print(f"                    ssh -N -L {port}:127.0.0.1:{port} {host}")
        print(f"                    /qtvplay 127.0.0.1:{port}")
    print("=" * 70)
    print()


def cmd_up(args: argparse.Namespace) -> int:
    run_id = args.run_id or utc_run_id()
    ensure_prereqs(args.host, args.map_name)

    public_host = args.public_host
    if public_host == "auto":
        public_host = detect_public_host(args.host)
        print(f"Auto-detected LAN host: {public_host}")

    game_port = next_free_port(lambda p: udp_port_free(args.host, p), args.game_port)
    if args.strict_port and game_port != args.game_port:
        raise RuntimeError(f"Requested game port {args.game_port} is already in use on {args.host}.")
    qtv_port = derive_qtv_port(game_port, args.qtv_port)
    if not tcp_port_free(args.host, qtv_port):
        qtv_port = next_free_port(lambda p: tcp_port_free(args.host, p), qtv_port)

    hostname = f"komodobots-lab-qtv:{game_port}"
    cfg = build_qtv_cfg(
        run_id=run_id,
        game_port=game_port,
        qtv_port=qtv_port,
        qtv_password=args.qtv_password,
        map_name=args.map_name,
        hostname=hostname,
        skill=args.skill,
        bot_count=args.bot_count,
    )

    upload_shim(args.host, run_id)
    proc = run(
        [
            "ssh", args.host, "bash", "-s", "--",
            run_id,
            str(game_port),
            str(qtv_port),
            args.map_name,
            str(args.duration),
            str(KEEPALIVE_CYCLE_S),
            base64.b64encode(cfg.encode("utf-8")).decode("ascii"),
        ],
        input_text=REMOTE_UP_SCRIPT,
        check=False,
    )
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    if proc.returncode != 0:
        raise RuntimeError(f"Remote 'up' failed with exit {proc.returncode}.")

    watch = build_watch_info(public_host, qtv_port, hostname)
    print(f"Probing real off-host reachability at {public_host}:{qtv_port} ...")
    reachable = tcp_reachable(public_host, qtv_port)
    print_watch_block(watch, reachable, args.host)
    print("To stop this stream later:")
    print(f"  python scripts/run_lab_qtv.py down --session {session_name(args.map_name, game_port, run_id)}")
    return 0 if reachable else 8


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


def cmd_attach(args: argparse.Namespace) -> int:
    """Serve QTV from an already-running lab server (e.g. a moveprobe experiment)
    so it can be spectated without disturbing it -- non-invasive and reversible."""
    require_tool("ssh")
    public_host = args.public_host
    if public_host == "auto":
        public_host = detect_public_host(args.host)
        print(f"Auto-detected LAN host: {public_host}")
    proc = run(
        ["ssh", args.host, "bash", "-s", "--", str(args.port), "on"],
        input_text=REMOTE_ATTACH_SCRIPT,
        check=False,
    )
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    if proc.returncode != 0:
        raise RuntimeError(f"attach failed (exit {proc.returncode}). The port must be a running komodobots lab server.")

    watch = build_watch_info(public_host, args.port, f"lab:{args.port}")
    print(f"Probing real off-host reachability at {public_host}:{args.port} ...")
    reachable = tcp_reachable(public_host, args.port)
    print_watch_block(watch, reachable, args.host)
    print("When done, stop serving QTV from the experiment (restores its state) with:")
    print(f"  python scripts/run_lab_qtv.py detach --port {args.port}")
    return 0 if reachable else 8


def cmd_detach(args: argparse.Namespace) -> int:
    """Turn the built-in QTV stream back off on a lab server attached earlier."""
    require_tool("ssh")
    proc = run(
        ["ssh", args.host, "bash", "-s", "--", str(args.port), "off"],
        input_text=REMOTE_ATTACH_SCRIPT,
        check=False,
    )
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    if proc.returncode != 0:
        raise RuntimeError(f"detach failed (exit {proc.returncode}).")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="servexeri", help="SSH host. Defaults to servexeri.")
    sub = parser.add_subparsers(dest="command", required=True)

    up = sub.add_parser("up", help="Start a dedicated, spectatable QTV lab session.")
    up.add_argument("--map", dest="map_name", type=validate_map_name, default="dm3", help="Map to load (needs a Frogbot route). Defaults to dm3.")
    up.add_argument("--bot-count", type=int, default=4, help="Bots KTX keeps in the match (k_fb_autoadd_limit). Defaults to 4.")
    up.add_argument("--duration", type=float, default=3600.0, help="Seconds the keepalive runs before the session self-terminates. Defaults to 3600.")
    up.add_argument("--game-port", type=validate_port, default=DEFAULT_GAME_PORT, help="Preferred MVDSV UDP game port (QTV TCP uses the same number). Defaults to 28610, clear of the moveprobe lab's 28599.")
    up.add_argument("--qtv-port", type=validate_port, default=None, help="QTV TCP stream port. Defaults to the game port (proven servexeri model).")
    up.add_argument("--public-host", type=validate_public_host, default="auto", help="Public IP/DNS advertised in the printed link, or 'auto' (resolves the host's LAN IP). Defaults to auto.")
    up.add_argument("--qtv-password", type=sanitize_qtv_password, default="", help="QTV stream password. Default empty (open).")
    up.add_argument("--skill", type=int, default=10, help="Frogbot skill. Defaults to 10.")
    up.add_argument("--run-id", type=validate_run_id, default=None, help="Run ID. Defaults to current UTC timestamp.")
    up.add_argument("--strict-port", action="store_true", help="Fail instead of auto-bumping if the preferred game port is busy.")
    up.set_defaults(func=cmd_up)

    down = sub.add_parser("down", help="Stop lab QTV sessions and remove lab configs.")
    down.add_argument("--session", type=validate_session, default=None, help="Stop only this lab session. Default: all komodobots_qtv sessions.")
    down.set_defaults(func=cmd_down)

    status = sub.add_parser("status", help="Show running lab QTV sessions.")
    status.set_defaults(func=cmd_status)

    attach = sub.add_parser(
        "attach",
        help="Serve QTV from an already-running komodobots lab server (e.g. a moveprobe experiment) so it can be watched WITHOUT disturbing it. Reversible via 'detach'.",
    )
    attach.add_argument("--port", type=validate_port, default=28599, help="Game port of the running lab server to attach QTV to. Defaults to 28599 (the moveprobe lab).")
    attach.add_argument("--public-host", type=validate_public_host, default="auto", help="Public IP/DNS for the printed link, or 'auto' (resolves the host's LAN IP). Defaults to auto.")
    attach.set_defaults(func=cmd_attach)

    detach = sub.add_parser("detach", help="Stop serving QTV from a lab server attached with 'attach' (sets qtv_streamport 0; restores its state).")
    detach.add_argument("--port", type=validate_port, default=28599, help="Game port of the lab server to detach QTV from. Defaults to 28599.")
    detach.set_defaults(func=cmd_detach)

    return parser


def main(argv: Iterable[str] = sys.argv[1:]) -> int:
    # quakestat output can carry a non-UTF8 byte (decoded to U+FFFD); a Windows
    # cp1252 console can't encode it and would crash on sys.stdout.write. Make
    # the streams replace-on-encode so the launcher is robust there.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass

    parser = build_parser()
    args = parser.parse_args(list(argv))
    try:
        return args.func(args)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
