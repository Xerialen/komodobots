"""Throwaway local smoke: drive the sidecar's control channel over a real websocket."""
import base64
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

repo = Path(__file__).resolve().parent
tmp = Path(tempfile.mkdtemp())
runs = tmp / "runs"
runs.mkdir()
# fresh harness lock -> every mutating op must refuse
(tmp / "lab.lock").write_text(
    json.dumps({"owner": "harness", "run_id": "smoke", "pid": os.getpid(),
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}) + "\n")

proc = subprocess.Popen(
    [sys.executable, str(repo / "scripts" / "telemetry_ws.py"), "--host", "127.0.0.1",
     "--port", "8771", "--runs-dir", str(runs), "--lab-home", str(tmp)],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
time.sleep(2.0)

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

try:
    s = socket.create_connection(("127.0.0.1", 8771), timeout=5)
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
    proc.terminate()
