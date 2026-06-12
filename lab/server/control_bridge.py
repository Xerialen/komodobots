#!/usr/bin/env python3
"""Control bridge for the lab telemetry sidecar (LD-F2, #96).

Adds a browser -> lab-server command channel to `scripts/telemetry_ws.py`
(decision D4: extend the existing sidecar, no new service). The sidecar stays
read-only for telemetry; everything mutating goes through this module.

Protocol (JSON text frames over the existing websocket):

  client -> server   {"op": <str>, "req_id": <str>, ...op args}
  server -> client   {"re": <req_id>, "ok": <bool>, "detail": <str>, ...}
  server -> all      {"type": "control_event", "event": <op>, ...}   on success

Ops: session_start {map, force?} / session_stop {port?, force?} / set_map {map}
/ addbot {count?} / removebot {slot?|all?} / set_cvar {name, value, slot?}
/ console {line} / game_command {action, value?} / lock_status
/ verdict {map, route, note?} (LD-F5 #106 — user certifies route reached human-level).

SECURITY IS BINDING (all gates enforced server-side, the UI is courtesy):

- caller authorization (Codex P1, #129): every mutating op requires a TRUSTED
  caller -- a loopback peer (operator on the lab host, or an `ssh -L` tunnel)
  or a request "token" matching the per-deploy control token (constant-time
  compare; redacted in the audit log). With no token configured, remote peers
  can never mutate. The sidecar's Origin allowlist is browser CSRF defense ON
  TOP of this, never a substitute;
- target port allowlist 28599-28609 ONLY;
- flat deny of production ports 28501/28502/28503 and screen names `qw_*`
  anywhere in any command path (substring deny, deliberately over-broad);
- cvar allowlist (`k_fb_*`, `timelimit`, `fraglimit`, explicit safe set);
- console command allowlist + denylist (rcon*, exec, alias, sv_crypt*, quit,
  anything path-like or chained with `;`);
- LAN-only exposure: this module never opens a listener; the sidecar keeps its
  existing bind and no tunnel/ingress route may be added;
- every mutating command attempt (allowed AND refused) is appended with
  timestamp + peer + op to ~/komodobots-lab/control-audit.log.

Lock protocol (experiment harness has absolute priority):

- JSON lock at ~/komodobots-lab/lab.lock: {owner, run_id, pid, ts, port?, map?}
  with owner in {"harness", "dashboard"}.
- The harness (scripts/run_frobodm2_lab.py remote script) writes owner=harness
  at server start and removes it in cleanup, including failure paths.
- While a FRESH harness lock exists (pid alive and age <= 2 h) the bridge
  refuses every mutating op with reason "experiment harness owns the lab".
- A lock with a dead pid or age > 2 h is STALE and may be taken over ONLY with
  an explicit force=true on session_start/session_stop (UI confirm in LD-F3).
- Telemetry streaming continues regardless of lock owner.

Stdlib only -- this runs on the bare python3 of the lab host (servexeri),
deployed flat next to telemetry_ws.py (see lab/README.md).
"""

from __future__ import annotations

import hmac
import ipaddress
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Security constants
# ---------------------------------------------------------------------------

# The lab port family. Production 28501/28502/28503 ARE UNTOUCHABLE.
ALLOWED_LAB_PORTS: tuple[int, ...] = tuple(range(28599, 28610))  # 28599..28609
DENIED_PORTS: tuple[int, ...] = (28501, 28502, 28503)
# Flat substring deny: these may never appear in anything we send or target.
DENIED_SUBSTRINGS: tuple[str, ...] = ("28501", "28502", "28503", "qw_")

LAB_SCREEN_PREFIX = "komodobots_lab_"
BOTCMD_SHIM_RUN_FOR = "5"
CLIENT_SHIM_RUN_FOR = "2"

# Cvar allowlist: prefix family + explicit safe set. Everything else refused.
CVAR_ALLOWED_PREFIXES: tuple[str, ...] = ("k_fb_",)
CVAR_ALLOWED_EXACT: frozenset[str] = frozenset({"timelimit", "fraglimit", "samelevel"})

# First-class game-control buttons. These intentionally do not widen the raw
# console allowlist: each action maps to a tiny, source-checked KTX command set.
GAME_MODE_COMMANDS: dict[str, str] = {
    "1on1": "1on1",
    "2on2": "2on2",
    "4on4": "4on4",
    "ffa": "ffa",
}
GAME_DMM_COMMANDS: dict[str, str] = {
    "1": "dmm1",
    "2": "dmm2",
    "3": "dmm3",
    "4": "dmm4",
}
POWERUP_CVARS: tuple[str, ...] = ("k_pow", "k_pow_q", "k_pow_p", "k_pow_r", "k_pow_s")
GAME_BOTCMDS: frozenset[str] = frozenset(
    {"removeall", "weapon 1", "weapon random"}
    | {f"removebot {slot}" for slot in range(32)}
)
ZTRICKS_DISTANCE_STANDSTILL_STEPS: tuple[tuple[str, str], ...] = (
    # One visible attempt: clear any older dashboard bots first so the spawn
    # snap is not polluted by telefragging or stale per-bot state.
    ("botcmd", "removeall"),
    # A5 Distance start: teleport deposit at t5, zero velocity via spawn-snap.
    ("console", 'set k_fb_moveprobe_spawn_origin "-3516.125 3712 -453.125"'),
    # Mode 23 is the deployed frogbot-nav + bunnyhop-weave controller. Marker
    # 8 in the generated ztricks.bot graph is the far-platform landing marker
    # for the first getspeed attempt family.
    ("console", "set k_fb_moveprobe_mode 23"),
    ("console", "set k_fb_moveprobe_fixed_goal 8"),
    # Deployed circle-jump launch knobs from the A5 round-2 standstill ledger.
    ("console", "set k_fb_moveprobe_s23_launch_vh 430"),
    ("console", "set k_fb_moveprobe_s23_launch_angle 50"),
    ("console", "set k_fb_moveprobe_s21_swing 8"),
    ("console", "set k_fb_moveprobe_log_commands 1"),
    ("console", "set k_fb_moveprobe_log_interval 0"),
    ("addbot", "1"),
)

# Console: first token must be allowlisted AND must not hit the denylist.
CONSOLE_ALLOWED_FIRST_TOKENS: frozenset[str] = frozenset(
    {"status", "map", "set", "timelimit", "fraglimit", "sv_demostop", "sv_democancel"}
)
CONSOLE_DENIED_TOKEN_PREFIXES: tuple[str, ...] = ("rcon", "sv_crypt")
CONSOLE_DENIED_TOKENS: frozenset[str] = frozenset({"exec", "alias", "quit"})

# \Z, not $: a $ would also match just before a trailing newline, letting
# "dm3\n" through into a screen-stuffed command line.
TOKEN_RE = re.compile(r"^[A-Za-z0-9_]+\Z")
CVAR_VALUE_RE = re.compile(r"^[A-Za-z0-9_. -]*\Z")
MAX_SLOT = 31

LOCK_STALE_AGE_S = 2 * 3600
LOCK_TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

MUTATING_OPS: frozenset[str] = frozenset(
    {
        "session_start",
        "session_stop",
        "set_map",
        "addbot",
        "removebot",
        "set_cvar",
        "console",
        "game_command",
        "verdict",
    }
)
# Ops that require a running dashboard-owned session.
SESSION_OPS: frozenset[str] = frozenset(
    {"set_map", "addbot", "removebot", "set_cvar", "console", "game_command"}
)

# Ops that are EXEMPT from the harness lock: verdict writes only to the local
# verdicts store, never to a running lab server, so it must not be blocked when
# the user is watching a run that the harness currently owns.
LOCK_EXEMPT_OPS: frozenset[str] = frozenset({"verdict"})

# LD-F5 (#106): verdicts.json schema.
# v2: sparse certification events — the user declares human-level reached.
# (v1 was pass/close/fail three-state; replaced by the 2026-06-10 user decision.)
VERDICTS_FILENAME = "verdicts.json"
VERDICTS_SCHEMA = "komodobots.verdicts.v2"

MVDSV_LAB_BIN = "mvdsv-lab"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime(LOCK_TS_FORMAT)


# ---------------------------------------------------------------------------
# Validation helpers (pure -- unit tested directly)
# ---------------------------------------------------------------------------


def hits_flat_deny(text: str) -> bool:
    """True when a production port or qw_* screen name appears ANYWHERE."""
    return any(bad in text for bad in DENIED_SUBSTRINGS)


def is_path_like(text: str) -> bool:
    return "/" in text or "\\" in text or ".." in text


def is_loopback_host(host: object) -> bool:
    """True only for a loopback peer address (127.0.0.0/8 or ::1).

    The IPv4-mapped form ::ffff:127.0.0.1 unwraps to its IPv4 address first
    (Python's IPv6Address.is_loopback is False for mapped addresses). Anything
    unparseable -- including None, empty, or hostnames -- is NOT loopback:
    authorization must fail closed.
    """
    if not isinstance(host, str) or not host:
        return False
    try:
        addr = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    return addr.is_loopback


def validate_lab_port(port: object) -> int | None:
    """Returns the port as int when in the lab allowlist, else None."""
    if isinstance(port, bool) or not isinstance(port, int):
        if isinstance(port, str) and port.isdigit():
            port = int(port)
        else:
            return None
    if port in DENIED_PORTS or port not in ALLOWED_LAB_PORTS:
        return None
    return int(port)


def validate_map_name(name: object) -> str | None:
    if not isinstance(name, str) or not TOKEN_RE.match(name) or hits_flat_deny(name):
        return None
    return name


def validate_cvar(name: object, value: object, slot: object = None) -> tuple[str, str] | str:
    """Returns (final_name, final_value) or an error string."""
    if not isinstance(name, str) or not TOKEN_RE.match(name):
        return "invalid cvar name"
    allowed = name in CVAR_ALLOWED_EXACT or any(name.startswith(p) for p in CVAR_ALLOWED_PREFIXES)
    if not allowed:
        return f"cvar not on the allowlist: {name}"
    if slot is not None:
        if isinstance(slot, bool) or not isinstance(slot, int) or not (0 <= slot <= MAX_SLOT):
            return "invalid slot"
        name = f"{name}_s{slot}"  # LD-F1 per-slot form (#95)
    value_text = str(value) if value is not None else ""
    if not CVAR_VALUE_RE.match(value_text) or is_path_like(value_text):
        return "invalid cvar value"
    if hits_flat_deny(name) or hits_flat_deny(value_text):
        return "value or name references a denied port/screen"
    return name, value_text


def validate_console_line(line: object) -> str | None:
    """Returns the validated line or None when refused."""
    if not isinstance(line, str):
        return None
    line = line.strip()
    if not line or ";" in line or "\n" in line or "\r" in line or '"' in line:
        return None
    if is_path_like(line) or hits_flat_deny(line):
        return None
    tokens = line.split()
    first = tokens[0].lower()
    if first in CONSOLE_DENIED_TOKENS:
        return None
    if any(first.startswith(p) for p in CONSOLE_DENIED_TOKEN_PREFIXES):
        return None
    if first not in CONSOLE_ALLOWED_FIRST_TOKENS:
        return None
    if first == "set":
        if len(tokens) < 2:
            return None
        result = validate_cvar(tokens[1], " ".join(tokens[2:]))
        if isinstance(result, str):
            return None
    if first == "map":
        if len(tokens) != 2 or validate_map_name(tokens[1]) is None:
            return None
    return line


def validate_game_command(action: object, value: object = None) -> list[tuple[str, str]] | str:
    """Return executor steps for an allowlisted game control, or an error."""
    if not isinstance(action, str):
        return "invalid game action"
    action = action.strip().lower()

    if action == "gamemode":
        if not isinstance(value, str):
            return "invalid gamemode"
        mode = value.strip().lower()
        command = GAME_MODE_COMMANDS.get(mode)
        if command is None:
            return "gamemode must be one of 1on1, 2on2, 4on4, ffa"
        return [("client", command)]

    if action == "deathmatch":
        value_text = str(value).strip() if value is not None else ""
        command = GAME_DMM_COMMANDS.get(value_text)
        if command is None:
            return "deathmatch must be one of 1, 2, 3, 4"
        return [("client", command)]

    if action == "powerups":
        if not isinstance(value, str) or value.strip().lower() not in ("on", "off"):
            return "powerups must be on or off"
        enabled = "1" if value.strip().lower() == "on" else "0"
        return [("console", f"set {name} {enabled}") for name in POWERUP_CVARS]

    if action == "start":
        return [("client", "ready")]

    if action == "stop":
        return [("client", "break")]

    if action == "prewar":
        # k_prewar=0 means pre-match players may not fire; break returns the
        # running game to prewar first when possible.
        return [("client", "break"), ("console", "set k_prewar 0")]

    if action == "bot_respawn":
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            return "bot respawn needs a bot slot"
        value_text = str(value).strip()
        if not value_text.isdigit():
            return "bot respawn needs a bot slot"
        slot = int(value_text)
        if not (0 <= slot <= MAX_SLOT):
            return "bot slot must be in 0..31"
        # KTX's removebot command is not reliably slot-addressable in this
        # lab build. The dashboard only enables this when one live bot is
        # present, so clear-all + add-one is the precise single-bot respawn.
        return [("botcmd", "removeall"), ("addbot", "1")]

    if action == "bot_weapon_lock":
        return [("botcmd", "weapon 1")]

    if action == "bot_weapon_unlock":
        return [("botcmd", "weapon random")]

    if action == "trick_pause":
        return [("botcmd", "removeall")]

    if action == "ztricks_distance_standstill":
        return list(ZTRICKS_DISTANCE_STANDSTILL_STEPS)

    return "unknown game action"


def validate_verdict_args(
    map_name: object,
    route: object,
    note: object,
) -> str | None:
    """Returns an error string if any field is invalid, else None.

    LD-F5 (#106): validates the verdict (certification) op fields.
    User decision 2026-06-10: certification is binary (human-level reached),
    no pass/close/fail three-state.
    - map: TOKEN_RE (same as validate_map_name, stored for context)
    - route: TOKEN_RE
    - note: optional str, limited length, no control chars
    """
    if validate_map_name(map_name) is None:
        return "invalid map name"
    if not isinstance(route, str) or not TOKEN_RE.match(route) or hits_flat_deny(route):
        return "invalid route name"
    if note is not None:
        if not isinstance(note, str):
            return "note must be a string or null"
        if len(note) > 1000:
            return "note too long (max 1000 characters)"
        if any(ord(c) < 32 and c not in ("\t",) for c in note):
            return "note contains invalid control characters"
    return None


def lab_session_name(port: int) -> str:
    name = f"{LAB_SCREEN_PREFIX}{port}"
    if hits_flat_deny(name) or validate_lab_port(port) is None:
        raise ValueError(f"refusing screen target: {name}")
    return name


# ---------------------------------------------------------------------------
# Lock protocol
# ---------------------------------------------------------------------------


def default_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return True  # exists but not ours
    return True


def read_lock(lock_path: Path) -> dict[str, object] | None:
    """The parsed lock, {"_corrupt": True} for unparseable content, None when absent."""
    try:
        text = lock_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError:
        return {"_corrupt": True}
    try:
        lock = json.loads(text)
    except json.JSONDecodeError:
        return {"_corrupt": True}
    if not isinstance(lock, dict):
        return {"_corrupt": True}
    return lock


def classify_lock(lock: dict[str, object], *, now: float, pid_alive) -> str:
    """"fresh" (owner is alive and recent) or "stale" (takeover needs force=true).

    A corrupt/unreadable lock classifies as stale: it cannot be proven fresh,
    and takeover still demands the explicit force step.
    """
    if lock.get("_corrupt"):
        return "stale"
    pid = lock.get("pid")
    if not isinstance(pid, int) or not pid_alive(pid):
        return "stale"
    ts = lock.get("ts")
    if not isinstance(ts, str):
        return "stale"
    try:
        born = datetime.strptime(ts, LOCK_TS_FORMAT).replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return "stale"
    if now - born > LOCK_STALE_AGE_S:
        return "stale"
    return "fresh"


def write_lock(lock_path: Path, lock: dict[str, object]) -> None:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = lock_path.with_suffix(".lock.tmp")
    tmp.write_text(json.dumps(lock, separators=(",", ":")) + "\n", encoding="utf-8")
    tmp.replace(lock_path)


def remove_lock(lock_path: Path) -> None:
    try:
        lock_path.unlink()
    except FileNotFoundError:
        pass


# ---------------------------------------------------------------------------
# Session config (mirrors the harness's proven minimal lab config)
# ---------------------------------------------------------------------------


def build_session_config(map_name: str, port: int) -> str:
    """Minimal dashboard-session lab config: autoadd off, QTV on the game port.

    Mirrors scripts/run_frobodm2_lab.py REMOTE_SCRIPT: matchless (the proven
    non-crashing flow on this KTX build), demo autorecording, and mvdsv's
    built-in QTV stream on the game port so the Live Game pane can attach.
    """
    if validate_map_name(map_name) is None or validate_lab_port(port) is None:
        raise ValueError("invalid map or port for session config")
    return f"""// Auto-generated Komodobots dashboard session config (control bridge, LD-F2)
hostname "komodobots-lab:{port}"
set k_motd1 "Komodobots dashboard session"
set k_matchless 1
set k_use_matchless_dir 1
set k_defmode ffa
set k_mode 3
set k_defmap {map_name}
set k_fb_enabled 0
set k_count 0
set k_matchless_countdown 0
timelimit 60
fraglimit 0
samelevel 1
set demo_tmp_record 1
set k_demo_mintime 0
set k_demotxt_format json
sv_demotxt 2
sv_demofps 77
sv_demodir demos
set qtv_streamport {port}
set qtv_maxstreams 8
set qtv_password ""
serverinfo hostname "komodobots-lab:{port}"
"""


def build_session_setup_cmds(map_name: str) -> list[str]:
    """Console lines stuffed after the server is up (same flow as the harness).

    k_fb_enabled flips AFTER world spawn (flipping at spawn segfaults this KTX
    build outside matchless); autoadd/autoremove stay off so the roster is
    exactly what addbot creates; sv_getrealip 0 + timeouts keep the connected
    client shim (and with it the demo recording) alive past 60 s.
    """
    if validate_map_name(map_name) is None:
        raise ValueError("invalid map for session setup")
    return [
        "set k_fb_enabled 1",
        "set k_fb_autoadd_limit 0",
        "set k_fb_auto_delay 1",
        "set k_fb_skill 10",
        f"map {map_name}",
        "set k_fb_autoadd_limit 0",
        "set k_fb_autoremove_at 0",
        "set sv_getrealip 0",
        "set sv_timeout 3600",
        "set k_idletime 0",
        "set k_matchless_max_idle_time 0",
        # LD-F3 (#105) Codex P1 fix: ASSIGN rows require k_fb_moveprobe_log_commands=1.
        # Without this the FBMOVEPROBE_ASSIGN emitter in the KTX patch returns early
        # (frogbot-moveprobe-perslot.patch line 650) and the sidecar never broadcasts
        # an assign frame, so the roster stays at s?? with assignment disabled forever.
        # The interval (0.25 s) matches the harness default.
        "set k_fb_moveprobe_log_commands 1",
        "set k_fb_moveprobe_log_interval 0.25",
    ]


# ---------------------------------------------------------------------------
# Executor: the only component that touches screen/processes. Injectable so
# the bridge logic is fully unit-testable; live behavior is verified in the
# declared lab slot (see the LD-F2 PR).
# ---------------------------------------------------------------------------


class LabExecutor:
    """Real lab-host executor: screen sessions + the qw_min_client shim.

    botcmd is NOT a server-console command (decision log 2026-05): bot ops go
    through a connected client, so addbot keeps one persistent shim per port
    (which also keeps the server demo recording alive) and later bot commands
    ride short-lived shims with --botcmd.
    """

    def __init__(
        self,
        lab_home: Path | None = None,
        nq_home: Path | None = None,
        mvdsv_bin: str = MVDSV_LAB_BIN,
        shim_path: Path | None = None,
    ) -> None:
        self.lab_home = Path(lab_home) if lab_home else Path.home() / "komodobots-lab"
        self.nq_home = Path(nq_home) if nq_home else Path.home() / "nquakesv"
        self.mvdsv_bin = mvdsv_bin
        if shim_path is None:
            here = Path(__file__).resolve().parent
            flat = here / "qw_min_client.py"  # deployed flat next to the sidecar
            repo = here.parents[1] / "experiments" / "qw_min_client.py"
            shim_path = flat if flat.is_file() else repo
        self.shim_path = Path(shim_path)
        self._persistent_shims: dict[int, subprocess.Popen] = {}

    # -- helpers ------------------------------------------------------------

    def _screen(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        for arg in args:
            if hits_flat_deny(arg):
                raise ValueError(f"refusing screen arg: {arg!r}")
        return subprocess.run(
            ["screen", *args], capture_output=True, text=True, check=check, timeout=30
        )

    def session_exists(self, port: int) -> bool:
        session = lab_session_name(port)
        proc = subprocess.run(["screen", "-ls"], capture_output=True, text=True, timeout=30)
        return re.search(rf"\.{re.escape(session)}\s", proc.stdout or "") is not None

    def port_available(self, port: int) -> bool:
        if validate_lab_port(port) is None:
            return False
        if self.session_exists(port):
            return False
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tcp:
            tcp.settimeout(0.3)
            if tcp.connect_ex(("127.0.0.1", port)) == 0:
                return False  # something (e.g. a QTV stream) listens here
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tcp_bind:
                tcp_bind.bind(("0.0.0.0", port))
        except OSError:
            return False
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
                udp.bind(("0.0.0.0", port))
        except OSError:
            return False
        return True

    def stuff(self, port: int, line: str) -> None:
        session = lab_session_name(port)
        if hits_flat_deny(line):
            raise ValueError(f"refusing console line: {line!r}")
        self._screen("-S", session, "-p", "0", "-X", "stuff", "\x15" + line + "\r")

    # -- session lifecycle ----------------------------------------------------

    def start_session(self, port: int, map_name: str, run_id: str, cfg_text: str, setup_cmds: list[str]) -> None:
        session = lab_session_name(port)
        run_dir = self.lab_home / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        cfg_name = f"kbot_dash_{port}.cfg"
        (self.nq_home / "ktx" / cfg_name).write_text(cfg_text, encoding="utf-8", newline="\n")
        # run.env makes the telemetry tailer pick the session up like a harness run
        (run_dir / "run.env").write_text(
            f"RUN_ID={run_id}\nSESSION={session}\nPORT={port}\nMAP={map_name}\n"
            f"OWNER=dashboard\nSTART_UTC={utc_now_iso()}\n",
            encoding="utf-8",
            newline="\n",
        )
        subprocess.run(
            [
                "screen", "-L", "-Logfile", str(run_dir / "screen.log"), "-dmS", session,
                f"./{self.mvdsv_bin}", "-port", str(port), "-mem", "64", "-game", "ktx",
                "+exec", cfg_name,
            ],
            cwd=str(self.nq_home),
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        deadline = time.time() + 20.0
        up = False
        while time.time() < deadline:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tcp:
                tcp.settimeout(0.5)
                if tcp.connect_ex(("127.0.0.1", port)) == 0:  # qtv stream = server up
                    up = True
                    break
            time.sleep(0.5)
        if not up:
            self._screen("-S", session, "-X", "quit", check=False)
            raise RuntimeError(f"lab server did not come up on port {port}")
        for line in setup_cmds:
            self.stuff(port, line)
            time.sleep(0.5)

    def stop_session(self, port: int) -> None:
        session = lab_session_name(port)
        shim = self._persistent_shims.pop(port, None)
        if shim is not None and shim.poll() is None:
            shim.terminate()
        if self.session_exists(port):
            self.stuff(port, "sv_demostop")
            time.sleep(1.0)
            self._screen("-S", session, "-X", "quit", check=False)

    # -- bot ops --------------------------------------------------------------

    def _shim_cmd(self, port: int, extra: list[str]) -> list[str]:
        if validate_lab_port(port) is None:
            raise ValueError(f"refusing shim port: {port}")
        return [sys.executable, str(self.shim_path), str(port), "--host", "127.0.0.1", "--quiet", *extra]

    def add_bots(self, port: int, count: int) -> None:
        shim = self._persistent_shims.get(port)
        if shim is not None and shim.poll() is None:
            self.send_botcmds(port, ["addbot"] * count)
            return
        self._persistent_shims[port] = subprocess.Popen(
            self._shim_cmd(
                port,
                ["--run-for", "86400", "--bot-count", str(count), "--bot-spacing", "2"],
            ),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def send_botcmds(self, port: int, botcmds: list[str]) -> None:
        extra = ["--run-for", BOTCMD_SHIM_RUN_FOR, "--bot-count", "0"]
        for cmd in botcmds:
            if not TOKEN_RE.match(cmd.replace(" ", "_")) or hits_flat_deny(cmd):
                raise ValueError(f"refusing botcmd: {cmd!r}")
            extra += ["--botcmd", cmd]
        subprocess.run(self._shim_cmd(port, extra), check=True, capture_output=True, timeout=60)

    def send_client_cmds(self, port: int, commands: list[str]) -> None:
        extra = ["--run-for", CLIENT_SHIM_RUN_FOR, "--bot-count", "0"]
        for cmd in commands:
            if not TOKEN_RE.match(cmd.replace(" ", "_")) or hits_flat_deny(cmd):
                raise ValueError(f"refusing client command: {cmd!r}")
            extra += ["--cmd", cmd]
        subprocess.run(self._shim_cmd(port, extra), check=True, capture_output=True, timeout=60)


# ---------------------------------------------------------------------------
# The bridge
# ---------------------------------------------------------------------------


class ControlBridge:
    """Validates, locks, audits, and dispatches dashboard control commands."""

    def __init__(
        self,
        lab_home: Path | None = None,
        executor: object | None = None,
        *,
        now_fn=time.time,
        pid_alive=default_pid_alive,
        own_pid: int | None = None,
        control_token: str | None = None,
    ) -> None:
        self.lab_home = Path(lab_home) if lab_home else Path.home() / "komodobots-lab"
        self.lock_path = self.lab_home / "lab.lock"
        self.audit_path = self.lab_home / "control-audit.log"
        self.executor = executor if executor is not None else LabExecutor(lab_home=self.lab_home)
        self._now = now_fn
        self._pid_alive = pid_alive
        self._own_pid = own_pid if own_pid is not None else os.getpid()
        self._control_token = control_token or None  # empty string == not configured
        self._mutex = threading.Lock()

    # -- plumbing -------------------------------------------------------------

    def handle(
        self, request: object, peer: str, peer_host: str | None = None
    ) -> tuple[dict[str, object], dict[str, object] | None]:
        """Returns (response, broadcast_or_None). Serialized: one command at a time.

        peer_host is the raw remote IP of the websocket connection (used for the
        loopback trust check); omitting it means the caller is treated as remote.
        """
        with self._mutex:
            return self._handle_locked(request, peer, peer_host)

    def _handle_locked(self, request: object, peer: str, peer_host: str | None):
        if not isinstance(request, dict) or not isinstance(request.get("op"), str):
            return self._refuse(None, "request must be a JSON object with an 'op' string"), None
        req_id = request.get("req_id")
        op = request["op"]
        if op == "lock_status":
            return self._lock_status(req_id), None
        if op not in MUTATING_OPS:
            return self._refuse(req_id, f"unknown op: {op}"), None
        auth_error = self._authorize(request, peer_host)
        if auth_error is not None:
            response = self._refuse(req_id, auth_error)
            self._audit(peer, op, request, response)
            return response, None
        try:
            response, broadcast = self._mutating(op, request, peer)
        except Exception as exc:  # executor failures must answer, not kill the sidecar
            response, broadcast = self._refuse(req_id, f"{type(exc).__name__}: {exc}"), None
        self._audit(peer, op, request, response)
        return response, broadcast

    def _authorize(self, request: dict, peer_host: str | None) -> str | None:
        """None when the caller may mutate, else the refusal detail (Codex P1, #129).

        Trust requires ONE of:
        - a loopback peer (operator on the lab host, or an `ssh -L` tunnel), or
        - request["token"] matching the per-deploy control token (constant-time
          compare). With no token configured, remote peers can never mutate.

        The Origin allowlist in telemetry_ws.py is browser CSRF defense on top
        of this check, never a substitute for it.
        """
        if is_loopback_host(peer_host):
            return None
        supplied = request.get("token")
        if (
            self._control_token is not None
            and isinstance(supplied, str)
            and hmac.compare_digest(supplied.encode(), self._control_token.encode())
        ):
            return None
        if self._control_token is None:
            return "unauthorized: no control token configured; mutating ops are loopback-only"
        return "unauthorized: mutating ops require a loopback connection or a valid control token"

    def _refuse(self, req_id: object, detail: str, **extra) -> dict[str, object]:
        return {"re": req_id, "ok": False, "detail": detail, **extra}

    def _ok(self, req_id: object, detail: str, **extra) -> dict[str, object]:
        return {"re": req_id, "ok": True, "detail": detail, **extra}

    def _audit(self, peer: str, op: str, request: dict, response: dict) -> None:
        entry = {
            "ts": utc_now_iso(),
            "peer": peer,
            "op": op,
            # the control token is a secret: never write its value to the log
            "request": {
                k: ("<redacted>" if k == "token" else v)
                for k, v in request.items()
                if k != "req_id"
            },
            "ok": bool(response.get("ok")),
            "detail": response.get("detail"),
        }
        try:
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)
            with self.audit_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, separators=(",", ":")) + "\n")
        except OSError as exc:
            print(f"[bridge] audit write failed: {exc}", file=sys.stderr, flush=True)

    # -- lock helpers -----------------------------------------------------------

    def _lock_view(self) -> tuple[dict[str, object] | None, str | None]:
        lock = read_lock(self.lock_path)
        if lock is None:
            return None, None
        return lock, classify_lock(lock, now=self._now(), pid_alive=self._pid_alive)

    def _lock_status(self, req_id: object) -> dict[str, object]:
        lock, state = self._lock_view()
        if lock is None:
            return self._ok(req_id, "lab is free", lock=None, state="free")
        public = {k: v for k, v in lock.items() if not k.startswith("_")}
        return self._ok(req_id, f"lock held by {lock.get('owner', 'unknown')} ({state})", lock=public, state=state)

    # -- mutating dispatch -------------------------------------------------------

    def _mutating(self, op: str, request: dict, peer: str):
        req_id = request.get("req_id")
        force = request.get("force") is True

        # LD-F5 (#106): verdict is lock-exempt — it writes only to the local
        # verdicts store and never touches a running lab server.  Dispatch it
        # before the lock check so the operator can record verdicts while the
        # experiment harness owns the lab.
        if op == "verdict":
            return self._verdict(req_id, request)

        lock, state = self._lock_view()

        if lock is not None:
            owner = lock.get("owner")
            if state == "fresh" and owner == "harness":
                return self._refuse(req_id, "experiment harness owns the lab"), None
            if state == "stale":
                if not (force and op in ("session_start", "session_stop")):
                    return self._refuse(
                        req_id,
                        f"stale lab lock (owner={owner}); takeover requires force=true on session_start/session_stop",
                    ), None
            # fresh dashboard lock: our own session, fall through

        if op == "session_start":
            return self._session_start(req_id, request, lock, state, force)
        if op == "session_stop":
            return self._session_stop(req_id, request, lock, state, force)

        # Session-scoped ops need a fresh dashboard lock with a valid port.
        if lock is None or state != "fresh" or lock.get("owner") != "dashboard":
            return self._refuse(req_id, "no dashboard session (start one with session_start)"), None
        port = validate_lab_port(lock.get("port"))
        if port is None:
            return self._refuse(req_id, "dashboard lock has no valid lab port"), None

        if op == "set_map":
            map_name = validate_map_name(request.get("map"))
            if map_name is None:
                return self._refuse(req_id, "invalid map name"), None
            self.executor.stuff(port, f"map {map_name}")
            return (
                self._ok(req_id, f"map {map_name}", port=port),
                {"type": "control_event", "event": "set_map", "port": port, "map": map_name},
            )

        if op == "addbot":
            count = request.get("count", 1)
            if isinstance(count, bool) or not isinstance(count, int) or not (1 <= count <= 8):
                return self._refuse(req_id, "count must be an int in 1..8"), None
            self.executor.add_bots(port, count)
            return (
                self._ok(req_id, f"addbot x{count}", port=port),
                {"type": "control_event", "event": "addbot", "port": port, "count": count},
            )

        if op == "removebot":
            slot = request.get("slot")
            if slot == "all":
                botcmd = "removeall"
            elif slot is None:
                botcmd = "removebot"
            elif isinstance(slot, int) and not isinstance(slot, bool) and 0 <= slot <= MAX_SLOT:
                botcmd = f"removebot {slot}"
            else:
                return self._refuse(req_id, "slot must be an int in 0..31 or 'all'"), None
            self.executor.send_botcmds(port, [botcmd])
            return (
                self._ok(req_id, f"botcmd {botcmd}", port=port),
                {"type": "control_event", "event": "removebot", "port": port, "slot": slot},
            )

        if op == "set_cvar":
            result = validate_cvar(request.get("name"), request.get("value"), request.get("slot"))
            if isinstance(result, str):
                return self._refuse(req_id, result), None
            name, value = result
            self.executor.stuff(port, f"set {name} {value}".rstrip())
            return (
                self._ok(req_id, f"set {name} {value}", port=port),
                {"type": "control_event", "event": "set_cvar", "port": port, "name": name, "value": value},
            )

        if op == "console":
            line = validate_console_line(request.get("line"))
            if line is None:
                return self._refuse(req_id, "console line refused by the allowlist"), None
            self.executor.stuff(port, line)
            return (
                self._ok(req_id, f"console: {line}", port=port),
                {"type": "control_event", "event": "console", "port": port, "line": line},
            )

        if op == "game_command":
            raw_action = request.get("action")
            action = raw_action.strip().lower() if isinstance(raw_action, str) else ""
            if action == "ztricks_distance_standstill" and lock.get("map") != "ztricks":
                return self._refuse(req_id, "ztricks Distance standstill requires a ztricks session"), None
            steps = validate_game_command(raw_action, request.get("value"))
            if isinstance(steps, str):
                return self._refuse(req_id, steps), None
            client_commands: list[str] = []
            console_lines: list[str] = []
            botcmds: list[str] = []
            addbot_count = 0
            for kind, line in steps:
                if kind == "client":
                    client_commands.append(line)
                elif kind == "console":
                    console_lines.append(line)
                elif kind == "botcmd":
                    if line not in GAME_BOTCMDS:
                        return self._refuse(req_id, "invalid botcmd game command step"), None
                    botcmds.append(line)
                elif kind == "addbot":
                    if line != "1":
                        return self._refuse(req_id, "invalid addbot game command step"), None
                    addbot_count += 1
                else:
                    return self._refuse(req_id, "invalid game command step"), None
            if client_commands:
                self.executor.send_client_cmds(port, client_commands)
            if botcmds:
                self.executor.send_botcmds(port, botcmds)
            for line in console_lines:
                self.executor.stuff(port, line)
            if addbot_count:
                self.executor.add_bots(port, addbot_count)
            value = request.get("value")
            detail = f"game {action}" + (f" {value}" if value is not None else "")
            return (
                self._ok(req_id, detail, port=port),
                {
                    "type": "control_event",
                    "event": "game_command",
                    "port": port,
                    "action": action,
                    "value": value,
                },
            )

        return self._refuse(req_id, f"unhandled op: {op}"), None

    # -- verdict op (LD-F5 #106) -----------------------------------------------

    @property
    def _verdicts_path(self) -> Path:
        """Path to the verdicts.json file on the lab SSD.

        The path mirrors the layout used by records_build.py --publish: the
        same directory that holds records.json on the lab host.  The bridge
        writes verdicts.json into `~/komodobots-lab/records/` (the LabExecutor
        default), keeping it co-located with records.json and reachable at the
        same `/demos/records/verdicts.json` HTTP path the scoreboard fetches.
        """
        return self.lab_home / "records" / VERDICTS_FILENAME

    def _verdict(self, req_id: object, request: dict):
        """LD-F5 (#106): certify that a route has reached human-level movement.

        User decision 2026-06-10: no pass/close/fail three-state; the user
        declares human-level reached (one action).  Each certification is a
        sparse dated event appended to certifications[route]; the scoreboard
        reads the latest entry.  Lock-exempt: the operator certifies while
        watching a run; the harness lock must not block this.
        Atomic write via temp-file+rename.
        """
        map_name = request.get("map")
        route = request.get("route")
        note = request.get("note")

        error = validate_verdict_args(map_name, route, note)
        if error is not None:
            return self._refuse(req_id, error), None

        # Normalise optional note.
        note_val: str | None = str(note).strip() if isinstance(note, str) and note.strip() else None
        certification: dict[str, object] = {
            "date": utc_now_iso()[:10],  # ISO date YYYY-MM-DD
        }
        if note_val is not None:
            certification["note"] = note_val

        verdicts_path = self._verdicts_path
        verdicts_path.parent.mkdir(parents=True, exist_ok=True)

        # Load existing file; initialise a fresh schema if absent or wrong version.
        try:
            existing_text = verdicts_path.read_text(encoding="utf-8")
            existing: dict[str, object] = json.loads(existing_text)
            if not isinstance(existing, dict) or existing.get("schema") != VERDICTS_SCHEMA:
                existing = {"schema": VERDICTS_SCHEMA, "certifications": {}}
        except FileNotFoundError:
            existing = {"schema": VERDICTS_SCHEMA, "certifications": {}}
        except (OSError, json.JSONDecodeError) as exc:
            return self._refuse(req_id, f"could not read verdicts.json: {exc}"), None

        certifications: dict[str, object] = existing.get("certifications", {})
        if not isinstance(certifications, dict):
            certifications = {}

        # Append this certification event to the route's list (sparse, dated).
        route_certs: list[object] = list(certifications.get(route) or [])  # type: ignore[arg-type]
        route_certs.append(certification)
        certifications[route] = route_certs
        existing["certifications"] = certifications

        # Atomic write.
        tmp_path = verdicts_path.with_suffix(".json.tmp")
        try:
            tmp_path.write_text(
                json.dumps(existing, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            tmp_path.replace(verdicts_path)
        except OSError as exc:
            return self._refuse(req_id, f"could not write verdicts.json: {exc}"), None

        detail = f"certified human-level for {map_name}/{route} on {certification['date']}"
        return (
            self._ok(req_id, detail, map=map_name, route=route, date=certification["date"]),
            {
                "type": "control_event",
                "event": "verdict",
                "map": map_name,
                "route": route,
                "date": certification["date"],
            },
        )

    # -- session lifecycle -----------------------------------------------------

    def _session_start(self, req_id, request, lock, state, force):
        if lock is not None and state == "fresh" and lock.get("owner") == "dashboard":
            return self._refuse(
                req_id, f"dashboard session already running on port {lock.get('port')}"
            ), None
        map_name = validate_map_name(request.get("map"))
        if map_name is None:
            return self._refuse(req_id, "invalid map name"), None
        # Codex P2 (#129): a stale dashboard lock can still have a live
        # komodobots_lab_<port> screen, because staleness tracks the bridge
        # pid/age, not the MVDSV screen. Without a sweep, that port reads as
        # occupied, a NEW port gets allocated, and overwriting the lock
        # orphans the old screen (a later session_stop only reaches the new
        # port). Stop the stale lock's session first so the screen is swept
        # and the port can be reused. Harness screens use a different name
        # shape (komodobots_lab_<map>_<port>_<run>), which stop_session's
        # exact komodobots_lab_<port> match never touches.
        if lock is not None and state == "stale":
            stale_port = validate_lab_port(lock.get("port"))
            if stale_port is not None:
                self.executor.stop_session(stale_port)
        failures: list[str] = []
        saw_available = False
        for port in ALLOWED_LAB_PORTS:
            if not self.executor.port_available(port):
                continue
            saw_available = True
            run_id = "dash_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            cfg = build_session_config(map_name, port)
            setup = build_session_setup_cmds(map_name)
            try:
                self.executor.start_session(port, map_name, run_id, cfg, setup)
            except Exception as exc:
                failures.append(f"{port}: {type(exc).__name__}: {exc}")
                try:
                    self.executor.stop_session(port)
                except Exception:
                    pass
                continue
            write_lock(
                self.lock_path,
                {
                    "owner": "dashboard",
                    "run_id": run_id,
                    "pid": self._own_pid,
                    "ts": utc_now_iso(),
                    "port": port,
                    "map": map_name,
                },
            )
            return (
                self._ok(req_id, f"session started on port {port}", port=port, map=map_name, run_id=run_id),
                {"type": "control_event", "event": "session_start", "port": port, "map": map_name, "run_id": run_id},
            )
        if failures:
            return self._refuse(req_id, "no lab port started (" + "; ".join(failures[-3:]) + ")"), None
        if not saw_available:
            return self._refuse(req_id, "no free lab port in the 28599-28609 allowlist"), None
        return self._refuse(req_id, "no lab port started"), None

    def _session_stop(self, req_id, request, lock, state, force):
        port = None
        if lock is not None and lock.get("owner") == "dashboard":
            port = validate_lab_port(lock.get("port"))
        if port is None and "port" in request:
            port = validate_lab_port(request.get("port"))
            if port is None:
                return self._refuse(req_id, "port must be in the 28599-28609 allowlist"), None
        if lock is None and not force:
            return self._refuse(req_id, "no session lock; nothing to stop (use force=true to sweep a port)"), None
        if port is None:
            return self._refuse(req_id, "no port to stop: lock has none and none was given"), None
        self.executor.stop_session(port)
        if lock is not None:
            remove_lock(self.lock_path)
        return (
            self._ok(req_id, f"session on port {port} stopped", port=port),
            {"type": "control_event", "event": "session_stop", "port": port},
        )
