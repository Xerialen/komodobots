#!/usr/bin/env python3
"""Live bot-lab telemetry websocket sidecar.

Runs on the lab host (servexeri) beside the lab. Tails the newest
~/komodobots-lab/runs/<run_id>/screen.log (the live, line-buffered KTX log
written by `screen -L -Logfile`), parses each FBMOVEPROBE_CMD line with the
SAME parser as the post-run pipeline (moveprobe_parse.py — keep that file next
to this one), and pushes one JSON frame per command tick to every connected
websocket client. The local-hub /botlab page is the consumer.

Stdlib only (hand-rolled RFC6455 server frames) so it runs on a bare python3 —
no pip install on the lab host. The telemetry direction is push-only; client
text frames carry control-bridge commands (LD-F2, #96) and ping/close are
answered as before.

Protocol (JSON text frames):
  {"type": "hello",       "run_id", "port", "map", "live"}   on connect
  {"type": "new_attempt", "run_id", "port", "map"}           when a new run dir appears
  {"type": "status",      "live": false}                     ~2s heartbeat while no run is active
  {"type": "frame",       "run_id", "t", "ed", "name",
   "origin": {x,y,z}, "vel": {x,y,z}, "vh", "yaw", "pitch",
   "move": {"fwd","side","up"}, "buttons", "onground",
   "dir_speed", "dist_to_rl"}                                 per FBMOVEPROBE_CMD tick
  {"type": "assign",      "run_id", "ed", "name", "mode",
   "replay_file", "fixed_goal", "spawn_origin"}               per FBMOVEPROBE_ASSIGN row

Control channel (client -> server text frames, see lab/server/control_bridge.py):
  {"op", "req_id", ...}        command request
  {"re", "ok", "detail", ...}  response to the requesting client only
  {"type": "control_event", "event", ...}  broadcast to every client on success

Control authorization (Codex P1, #129) -- telemetry stays open, mutation does not:
  - mutating ops are authorized by the bridge: loopback peer (operator on the
    lab host or an `ssh -L 8770:localhost:8770` tunnel) OR a request "token"
    matching the per-deploy secret at <lab-home>/control.token (auto-generated
    0600 on first start; override with --control-token-file);
  - browser CSRF gate: a connection that sent an Origin header only reaches the
    control channel when that origin is allowlisted via --allow-origin
    (repeatable; default empty = browser clients are telemetry-only). This is
    defense in depth on top of the bridge check, never a substitute.

Deploy control_bridge.py (and qw_min_client.py for bot ops) flat next to this
file on the lab host; without it the sidecar degrades to telemetry-only.

Usage (manual v1, e.g. inside screen/tmux on servexeri):
  python3 telemetry_ws.py [--runs-dir ~/komodobots-lab/runs] [--host 0.0.0.0] [--port 8770]
                          [--lab-home ~/komodobots-lab] [--no-control]
                          [--control-token-file <path>] [--allow-origin <origin> ...]
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import math
import os
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# repo layout: the control bridge lives in lab/server/; deployed flat it sits
# next to this file (first sys.path entry above already covers that).
sys.path.insert(1, str(Path(__file__).resolve().parents[1] / "lab" / "server"))
from moveprobe_parse import (  # noqa: E402
    parse_moveprobe_command_line,
    parse_moveprobe_assign_line,
)

try:
    from control_bridge import ControlBridge  # noqa: E402
except ImportError:  # not deployed beside the sidecar -> telemetry-only mode
    ControlBridge = None

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

# dm3 RL pickup, mirrors build_trace.py RL — keep in sync (the live dist_to_rl
# must match the post-run trace.csv column).
RL_BY_MAP = {"dm3": (1591.0, 526.0, -88.0)}

POLL_INTERVAL_S = 0.25
STATUS_INTERVAL_S = 2.0
# A run dir is "live" while its screen.log keeps growing; after this long with
# no new bytes the attempt is over and we go back to waiting.
STALE_AFTER_S = 10.0


def encode_ws_text(payload: str) -> bytes:
    data = payload.encode("utf-8")
    n = len(data)
    if n < 126:
        header = bytes((0x81, n))
    elif n < 65536:
        header = bytes((0x81, 126)) + n.to_bytes(2, "big")
    else:
        header = bytes((0x81, 127)) + n.to_bytes(8, "big")
    return header + data


class Hub:
    """Connected clients + current attempt state."""

    def __init__(self) -> None:
        self.clients: set[asyncio.StreamWriter] = set()
        self.run_id: str | None = None
        self.port: int | None = None
        self.map_name: str | None = None
        self.live = False

    def hello_payload(self) -> dict[str, object]:
        return {
            "type": "hello",
            "run_id": self.run_id,
            "port": self.port,
            "map": self.map_name,
            "live": self.live,
        }

    async def broadcast(self, message: dict[str, object]) -> None:
        if not self.clients:
            return
        frame = encode_ws_text(json.dumps(message, separators=(",", ":")))
        dead = []
        # snapshot: handle_client() can discard from self.clients while we
        # await drain(), and mutating a set mid-iteration raises RuntimeError
        for writer in list(self.clients):
            try:
                writer.write(frame)
                await asyncio.wait_for(writer.drain(), timeout=1.0)
            except (ConnectionError, TimeoutError, OSError):
                dead.append(writer)
        for writer in dead:
            self.clients.discard(writer)
            writer.close()


async def ws_handshake(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter
) -> tuple[bool, str | None]:
    """Returns (ok, origin). origin is the raw Origin header value when present.

    A present Origin marks a browser connection; the control channel only
    accepts it when allowlisted (see handle_client). The handshake itself is
    never rejected on Origin: telemetry stays open to the LAN as before.
    """
    request = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=5.0)
    key = None
    origin = None
    for line in request.decode("latin-1").split("\r\n"):
        low = line.lower()
        if low.startswith("sec-websocket-key:"):
            key = line.split(":", 1)[1].strip()
        elif low.startswith("origin:"):
            origin = line.split(":", 1)[1].strip()
    if not key:
        writer.write(b"HTTP/1.1 400 Bad Request\r\n\r\n")
        await writer.drain()
        return False, None
    accept = base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()
    writer.write(
        (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
        ).encode()
    )
    await writer.drain()
    return True, origin


async def consume_client_frames(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    on_text=None,
) -> None:
    """Read client frames: answer ping/close; deliver text frames to on_text.

    Returns on close/EOF. Fragmented client messages (opcode 0x0 continuations)
    are not supported; control commands are small single-frame JSON.
    """
    while True:
        head = await reader.readexactly(2)
        opcode = head[0] & 0x0F
        masked = bool(head[1] & 0x80)
        length = head[1] & 0x7F
        if length == 126:
            length = int.from_bytes(await reader.readexactly(2), "big")
        elif length == 127:
            length = int.from_bytes(await reader.readexactly(8), "big")
        mask = await reader.readexactly(4) if masked else b""
        payload = await reader.readexactly(length) if length else b""
        if masked and payload:
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        if opcode == 0x8:  # close
            writer.write(bytes((0x88, 0)))
            await writer.drain()
            return
        if opcode == 0x9:  # ping -> pong
            writer.write(bytes((0x8A, len(payload))) + payload)
            await writer.drain()
        if opcode == 0x1 and on_text is not None:  # text -> control channel
            await on_text(payload.decode("utf-8", errors="replace"))


async def handle_client(
    hub: Hub,
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    bridge=None,
    allowed_origins: frozenset[str] = frozenset(),
) -> None:
    peer = writer.get_extra_info("peername")
    peer_host = peer[0] if isinstance(peer, tuple) and peer else None
    origin: str | None = None  # set by the handshake before any on_text call

    async def on_text(payload: str) -> None:
        # Control channel (LD-F2 #96). bridge.handle blocks (screen/subprocess,
        # session_start waits for the server) -> run it in a worker thread so
        # telemetry frames keep flowing to every client meanwhile.
        try:
            request = json.loads(payload)
        except json.JSONDecodeError:
            request = None
        req_id = request.get("req_id") if isinstance(request, dict) else None
        broadcast = None
        if origin is not None and origin not in allowed_origins:
            # Browser CSRF gate (Codex P1, #129): a page from a non-allowlisted
            # origin keeps its telemetry stream but never reaches the control
            # bridge. Defense in depth on top of the bridge's loopback/token
            # authorization, not a substitute for it.
            response = {"re": req_id, "ok": False, "detail": "origin not allowed for control"}
            print(
                f"[bridge] refused control frame from {peer}: origin {origin!r} not allowlisted",
                flush=True,
            )
        elif bridge is None:
            response = {"re": req_id, "ok": False, "detail": "control bridge not deployed"}
        elif request is None:
            response = {"re": None, "ok": False, "detail": "invalid JSON"}
        else:
            response, broadcast = await asyncio.get_running_loop().run_in_executor(
                None, lambda: bridge.handle(request, str(peer), peer_host=peer_host)
            )
        writer.write(encode_ws_text(json.dumps(response, separators=(",", ":"))))
        await writer.drain()
        if broadcast is not None:
            await hub.broadcast(broadcast)

    try:
        ok, origin = await ws_handshake(reader, writer)
        if not ok:
            return
        print(f"[ws] client connected: {peer}", flush=True)
        hub.clients.add(writer)
        writer.write(encode_ws_text(json.dumps(hub.hello_payload(), separators=(",", ":"))))
        await writer.drain()
        await consume_client_frames(reader, writer, on_text=on_text)
    except (asyncio.IncompleteReadError, ConnectionError, TimeoutError, OSError):
        pass
    finally:
        hub.clients.discard(writer)
        writer.close()
        print(f"[ws] client gone: {peer}", flush=True)


def load_or_create_control_token(path: Path) -> tuple[str, bool]:
    """Returns (token, created). The per-deploy control secret (Codex P1, #129).

    Generated once per deploy with 256 bits of entropy and written 0600; remote
    (non-loopback) control clients must present it in each mutating request.
    The value is never printed -- the operator reads the file on the lab host.
    """
    try:
        token = path.read_text(encoding="utf-8").strip()
        if token:
            return token, False
    except FileNotFoundError:
        pass
    token = secrets.token_hex(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(token + "\n")
    return token, True


def read_run_env(run_dir: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    env_path = run_dir / "run.env"
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                env[key.strip()] = value.strip()
    return env


def newest_run_dir(runs_dir: Path) -> Path | None:
    candidates = [p for p in runs_dir.iterdir() if p.is_dir()] if runs_dir.is_dir() else []
    if not candidates:
        return None
    # newest by mtime, NOT by name: the runs dir also holds older hand-named
    # dirs (e.g. solo_realip_d180) that sort after the timestamp run ids
    def mtime(path: Path) -> float:
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0

    return max(candidates, key=mtime)


def command_row_to_frame(row: dict[str, object], hub: Hub) -> dict[str, object] | None:
    origin = row.get("origin")
    water = row.get("water_state")
    if not isinstance(origin, dict) or not isinstance(water, dict):
        return None  # needs --moveprobe-log-commands with the origin/water fields
    vel = water["velocity"]
    vh = math.hypot(vel["x"], vel["y"])
    rl = RL_BY_MAP.get(hub.map_name or "")
    dist_to_rl = None
    if rl is not None:
        dist_to_rl = math.sqrt(
            (origin["x"] - rl[0]) ** 2 + (origin["y"] - rl[1]) ** 2 + (origin["z"] - rl[2]) ** 2
        )
    route = row.get("route_state")
    return {
        "type": "frame",
        "run_id": hub.run_id,
        "t": row["time_s"],
        "ed": row["ed"],
        "name": row["name"],
        "origin": origin,
        "vel": vel,
        "vh": round(vh, 1),
        "yaw": row["angles"]["yaw"],
        "pitch": row["angles"]["pitch"],
        "move": {
            "fwd": row["move"]["forward"],
            "side": row["move"]["side"],
            "up": row["move"]["up"],
        },
        "buttons": row["buttons"],
        # real FL_ONGROUND (512) from the player flags, same as build_trace.py
        "onground": int(bool(int(water["flags"]) & 512)),
        "dir_speed": route.get("dir_speed") if isinstance(route, dict) else None,
        "dist_to_rl": round(dist_to_rl, 1) if dist_to_rl is not None else None,
    }


async def tail_runs(hub: Hub, runs_dir: Path) -> None:
    current_dir: Path | None = None
    log_pos = 0
    pending = b""
    last_data_t = 0.0
    last_status_t = 0.0
    loop = asyncio.get_event_loop()

    while True:
        newest = newest_run_dir(runs_dir)
        if newest is not None and newest != current_dir:
            current_dir = newest
            log_pos = 0
            pending = b""
            env = read_run_env(current_dir)
            hub.run_id = env.get("RUN_ID", current_dir.name)
            hub.port = int(env["PORT"]) if env.get("PORT", "").isdigit() else None
            hub.map_name = env.get("MAP")
            hub.live = True
            last_data_t = loop.time()
            print(f"[tail] new attempt: {hub.run_id} port={hub.port} map={hub.map_name}", flush=True)
            await hub.broadcast(
                {"type": "new_attempt", "run_id": hub.run_id, "port": hub.port, "map": hub.map_name}
            )

        if current_dir is not None:
            # run.env can land after the dir; refresh until port/map are known
            if hub.port is None or hub.map_name is None:
                env = read_run_env(current_dir)
                if env.get("PORT", "").isdigit():
                    hub.port = int(env["PORT"])
                hub.map_name = hub.map_name or env.get("MAP")

            log_path = current_dir / "screen.log"
            if log_path.is_file():
                try:
                    size = log_path.stat().st_size
                    if size > log_pos:
                        with log_path.open("rb") as handle:
                            handle.seek(log_pos)
                            chunk = handle.read(size - log_pos)
                        log_pos = size
                        last_data_t = loop.time()
                        if not hub.live:
                            hub.live = True
                        pending += chunk
                        *lines, pending = pending.split(b"\n")
                        for raw in lines:
                            line = raw.decode("utf-8", errors="replace")
                            # LD-F3 (#105): ASSIGN rows expose per-bot route
                            # assignment (server truth) to connected clients.
                            assign_row = parse_moveprobe_assign_line(line)
                            if assign_row is not None:
                                await hub.broadcast({
                                    "type": "assign",
                                    "run_id": hub.run_id,
                                    "ed": assign_row["ed"],
                                    "name": assign_row["name"],
                                    "mode": assign_row["mode"],
                                    "replay_file": assign_row["replay_file"],
                                    "fixed_goal": assign_row["fixed_goal"],
                                    "spawn_origin": assign_row["spawn_origin"],
                                })
                            row = parse_moveprobe_command_line(line)
                            if row is None:
                                continue
                            frame = command_row_to_frame(row, hub)
                            if frame is not None:
                                await hub.broadcast(frame)
                except OSError:
                    pass

        now = loop.time()
        if hub.live and now - last_data_t > STALE_AFTER_S:
            hub.live = False
            print(f"[tail] attempt {hub.run_id} went quiet; waiting", flush=True)
        if not hub.live and now - last_status_t > STATUS_INTERVAL_S:
            last_status_t = now
            await hub.broadcast({"type": "status", "live": False})

        await asyncio.sleep(POLL_INTERVAL_S)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runs-dir",
        default=str(Path.home() / "komodobots-lab" / "runs"),
        help="Lab runs dir to watch. Defaults to ~/komodobots-lab/runs.",
    )
    parser.add_argument("--host", default="0.0.0.0", help="Bind address. Defaults to 0.0.0.0.")
    parser.add_argument("--port", type=int, default=8770, help="Websocket port. Defaults to 8770.")
    parser.add_argument(
        "--lab-home",
        default=str(Path.home() / "komodobots-lab"),
        help="Lab home for the control bridge lock/audit. Defaults to ~/komodobots-lab.",
    )
    parser.add_argument(
        "--no-control",
        action="store_true",
        help="Disable the control bridge command channel (telemetry-only).",
    )
    parser.add_argument(
        "--control-token-file",
        default=None,
        help=(
            "Per-deploy control token file (created 0600 with a random secret on "
            "first start). Remote control clients must send its value as 'token' "
            "in each mutating request. Defaults to <lab-home>/control.token."
        ),
    )
    parser.add_argument(
        "--allow-origin",
        action="append",
        default=[],
        metavar="ORIGIN",
        help=(
            "Browser Origin allowed to use the control channel (repeatable, exact "
            "match, e.g. http://192.168.86.33:8095). Browser connections from any "
            "other origin stay telemetry-only."
        ),
    )
    args = parser.parse_args()

    bridge = None
    if args.no_control:
        print("[bridge] control channel disabled (--no-control)", flush=True)
    elif ControlBridge is None:
        print("[bridge] control_bridge.py not found beside the sidecar; telemetry-only", flush=True)
    else:
        token_path = (
            Path(args.control_token_file)
            if args.control_token_file
            else Path(args.lab_home) / "control.token"
        )
        token, created = load_or_create_control_token(token_path)
        bridge = ControlBridge(lab_home=Path(args.lab_home), control_token=token)
        print(f"[bridge] control channel up (lab home {args.lab_home})", flush=True)
        print(
            f"[bridge] control token {'generated at' if created else 'loaded from'} "
            f"{token_path}; mutating ops need loopback or this token",
            flush=True,
        )
        if args.allow_origin:
            print(f"[bridge] control origins allowlisted: {', '.join(args.allow_origin)}", flush=True)
        else:
            print("[bridge] no --allow-origin given: browser clients are telemetry-only", flush=True)

    hub = Hub()
    allowed_origins = frozenset(args.allow_origin)
    server = await asyncio.start_server(
        lambda r, w: handle_client(hub, r, w, bridge=bridge, allowed_origins=allowed_origins),
        args.host,
        args.port,
    )
    print(f"[ws] listening on {args.host}:{args.port}, watching {args.runs_dir}", flush=True)
    async with server:
        await asyncio.gather(server.serve_forever(), tail_runs(hub, Path(args.runs_dir)))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
