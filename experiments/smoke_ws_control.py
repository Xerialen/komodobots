"""Local smoke client for the control bridge (LD-F2, #96).

Boots the real telemetry sidecar websocket handler in-process against a temp
lab home seeded with a FRESH harness lock, then drives the control channel over
a real hand-rolled websocket: handshake, hello, lock_status, and the refusal
paths (session_start under harness lock, rcon cvar, bad JSON), and finally
prints the audit log. No lab host involved -- everything runs on 127.0.0.1.

This is the manual evidence tool, not part of the unit suite (the suite covers
the same logic via tests/test_control_bridge.py and
tests/test_control_channel_wiring.py). The send/recv helpers mirror the wire
format used against servexeri:8770 during the lab-slot end-to-end check.

Usage: python experiments/smoke_ws_control.py
"""
import asyncio
import base64
import json
import os
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

repo = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo / "scripts"))
sys.path.insert(1, str(repo / "lab" / "server"))

import telemetry_ws as tw  # noqa: E402
from control_bridge import ControlBridge  # noqa: E402

tmp = Path(tempfile.mkdtemp())
runs = tmp / "runs"
runs.mkdir()
# fresh harness lock -> every mutating op must refuse
(tmp / "lab.lock").write_text(
    json.dumps({"owner": "harness", "run_id": "smoke", "pid": os.getpid(),
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}) + "\n")

server_ready = threading.Event()
server_errors: list[BaseException] = []
loop_holder: dict[str, asyncio.AbstractEventLoop] = {}
server_holder: dict[str, asyncio.AbstractServer] = {}
port_holder: dict[str, int] = {}


def run_sidecar() -> None:
    loop = asyncio.new_event_loop()
    loop_holder["loop"] = loop
    asyncio.set_event_loop(loop)
    hub = tw.Hub()
    bridge = ControlBridge(lab_home=tmp)

    async def start_server() -> None:
        server = await asyncio.start_server(
            lambda reader, writer: tw.handle_client(hub, reader, writer, bridge=bridge),
            "127.0.0.1",
            0,
        )
        server_holder["server"] = server
        assert server.sockets is not None
        port_holder["port"] = int(server.sockets[0].getsockname()[1])
        server_ready.set()

    try:
        loop.run_until_complete(start_server())
        loop.run_forever()
    except BaseException as exc:
        server_errors.append(exc)
        server_ready.set()
    finally:
        server = server_holder.get("server")
        if server is not None:
            server.close()
            loop.run_until_complete(server.wait_closed())
        loop.close()


thread = threading.Thread(target=run_sidecar, daemon=True)
thread.start()
if not server_ready.wait(timeout=5):
    raise RuntimeError("sidecar smoke server did not start")
if server_errors:
    raise RuntimeError(f"sidecar smoke server failed: {server_errors[0]}")
port = port_holder["port"]

def send_text(sock, payload: str) -> None:
    data = payload.encode()
    mask = b"\x01\x02\x03\x04"
    frame = bytes((0x81, 0x80 | len(data))) + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data))
    sock.sendall(frame)

def recv_text(sock) -> str:
    head = sock.recv(2)
    length = head[1] & 0x7F
    if length == 126:
        length = int.from_bytes(sock.recv(2), "big")
    payload = b""
    while len(payload) < length:
        payload += sock.recv(length - len(payload))
    return payload.decode()

s = None

try:
    s = socket.create_connection(("127.0.0.1", port), timeout=5)
    key = base64.b64encode(os.urandom(16)).decode()
    s.sendall((f"GET / HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
               f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
    resp = b""
    while b"\r\n\r\n" not in resp:
        resp += s.recv(1024)
    print("HANDSHAKE:", resp.split(b"\r\n")[0].decode())
    print("HELLO:", recv_text(s))
    send_text(s, '{"op":"lock_status","req_id":"a"}')
    print("LOCK_STATUS:", recv_text(s))
    send_text(s, '{"op":"session_start","map":"dm3","req_id":"b"}')
    print("SESSION_START (must refuse, harness lock):", recv_text(s))
    send_text(s, '{"op":"set_cvar","name":"rcon_password","value":"x","req_id":"c"}')
    print("SET_CVAR rcon (must refuse):", recv_text(s))
    send_text(s, "not json")
    print("BAD JSON:", recv_text(s))
    audit = (tmp / "control-audit.log")
    print("AUDIT LINES:")
    print(audit.read_text() if audit.is_file() else "<none>")
finally:
    if s is not None:
        try:
            s.close()
        except OSError:
            pass
    loop = loop_holder.get("loop")
    if loop is not None and loop.is_running():
        loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=5)
    if thread.is_alive():
        raise RuntimeError("sidecar smoke thread did not stop")
