#!/usr/bin/env python3
"""Live bot-lab telemetry websocket sidecar.

Runs on the lab host (servexeri) beside the lab. Tails the newest
~/komodobots-lab/runs/<run_id>/screen.log (the live, line-buffered KTX log
written by `screen -L -Logfile`), parses each FBMOVEPROBE_CMD line with the
SAME parser as the post-run pipeline (moveprobe_parse.py — keep that file next
to this one), and pushes one JSON frame per command tick to every connected
websocket client. The local-hub /botlab page is the consumer.

Stdlib only (hand-rolled RFC6455 server frames) so it runs on a bare python3 —
no pip install on the lab host. Server->client push only; client frames are
consumed just enough to answer ping and close.

Protocol (JSON text frames):
  {"type": "hello",       "run_id", "port", "map", "live"}   on connect
  {"type": "new_attempt", "run_id", "port", "map"}           when a new run dir appears
  {"type": "status",      "live": false}                     ~2s heartbeat while no run is active
  {"type": "frame",       "run_id", "t", "ed", "name",
   "origin": {x,y,z}, "vel": {x,y,z}, "vh", "yaw", "pitch",
   "move": {"fwd","side","up"}, "buttons", "onground",
   "dir_speed", "dist_to_rl"}                                 per FBMOVEPROBE_CMD tick

Usage (manual v1, e.g. inside screen/tmux on servexeri):
  python3 telemetry_ws.py [--runs-dir ~/komodobots-lab/runs] [--host 0.0.0.0] [--port 8770]
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from moveprobe_parse import parse_moveprobe_command_line  # noqa: E402

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
        for writer in self.clients:
            try:
                writer.write(frame)
                await asyncio.wait_for(writer.drain(), timeout=1.0)
            except (ConnectionError, TimeoutError, OSError):
                dead.append(writer)
        for writer in dead:
            self.clients.discard(writer)
            writer.close()


async def ws_handshake(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> bool:
    request = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=5.0)
    key = None
    for line in request.decode("latin-1").split("\r\n"):
        if line.lower().startswith("sec-websocket-key:"):
            key = line.split(":", 1)[1].strip()
    if not key:
        writer.write(b"HTTP/1.1 400 Bad Request\r\n\r\n")
        await writer.drain()
        return False
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
    return True


async def consume_client_frames(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """Read client frames just enough to answer ping/close; returns on close/EOF."""
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


async def handle_client(hub: Hub, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    peer = writer.get_extra_info("peername")
    try:
        if not await ws_handshake(reader, writer):
            return
        print(f"[ws] client connected: {peer}", flush=True)
        hub.clients.add(writer)
        writer.write(encode_ws_text(json.dumps(hub.hello_payload(), separators=(",", ":"))))
        await writer.drain()
        await consume_client_frames(reader, writer)
    except (asyncio.IncompleteReadError, ConnectionError, TimeoutError, OSError):
        pass
    finally:
        hub.clients.discard(writer)
        writer.close()
        print(f"[ws] client gone: {peer}", flush=True)


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
    # run ids are UTC timestamps (20260609T172810Z) so name order == time order
    return max(candidates, key=lambda p: p.name)


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
                            row = parse_moveprobe_command_line(
                                raw.decode("utf-8", errors="replace")
                            )
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
    args = parser.parse_args()

    hub = Hub()
    server = await asyncio.start_server(
        lambda r, w: handle_client(hub, r, w), args.host, args.port
    )
    print(f"[ws] listening on {args.host}:{args.port}, watching {args.runs_dir}", flush=True)
    async with server:
        await asyncio.gather(server.serve_forever(), tail_runs(hub, Path(args.runs_dir)))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
