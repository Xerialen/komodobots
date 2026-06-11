"""Control-channel wiring (LD-F2, #96): sidecar text frames + harness lock.

Locks (a) the telemetry sidecar's websocket reader: masked client TEXT frames
reach the control handler while ping/close behave exactly as before and the
no-handler path stays ignore-only (telemetry-only back-compat); (b) the
harness-priority lock lines in run_frobodm2_lab.py's remote script (owner=
harness written before the server screen starts, released in the cleanup trap
AND on the success path, removal guarded by run_id so another owner's lock is
never clobbered, and the dashboard-session port guard); (c) the qw_min_client
--botcmd extension used by the bridge for bot ops; (d) the control auth wiring
(Codex P1, #129): the handshake captures Origin, non-allowlisted browser
origins never reach the bridge, the peer IP is handed to the bridge for its
loopback check, and the per-deploy control token file is created 0600 once.
"""

import asyncio
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "experiments"))

import telemetry_ws as tw  # noqa: E402
import qw_min_client as qmc  # noqa: E402
import run_frobodm2_lab as harness  # noqa: E402


def client_frame(opcode: int, payload: bytes, mask: bytes = b"\x01\x02\x03\x04") -> bytes:
    assert len(payload) < 126
    head = bytes((0x80 | opcode, 0x80 | len(payload)))
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    return head + mask + masked


class FakeWriter:
    def __init__(self) -> None:
        self.data = b""

    def write(self, chunk: bytes) -> None:
        self.data += chunk

    async def drain(self) -> None:
        pass


class TestSidecarTextFrames(unittest.TestCase):
    def run_frames(self, frames: list[bytes], with_handler: bool = True):
        async def scenario():
            reader = asyncio.StreamReader()
            writer = FakeWriter()
            got: list[str] = []

            async def on_text(payload: str) -> None:
                got.append(payload)

            for frame in frames:
                reader.feed_data(frame)
            await tw.consume_client_frames(reader, writer, on_text=on_text if with_handler else None)
            return got, writer.data

        return asyncio.run(scenario())

    def test_text_frame_reaches_handler_ping_and_close_still_work(self):
        got, written = self.run_frames(
            [
                client_frame(0x1, b'{"op":"lock_status","req_id":"1"}'),
                client_frame(0x9, b"hi"),
                client_frame(0x8, b""),
            ]
        )
        self.assertEqual(got, ['{"op":"lock_status","req_id":"1"}'])
        self.assertIn(bytes((0x8A, 2)) + b"hi", written)  # pong
        self.assertTrue(written.endswith(bytes((0x88, 0))))  # close reply

    def test_without_handler_text_frames_are_ignored(self):
        got, written = self.run_frames(
            [client_frame(0x1, b"{}"), client_frame(0x8, b"")], with_handler=False
        )
        self.assertEqual(got, [])
        self.assertEqual(written, bytes((0x88, 0)))


def handshake_bytes(origin: str | None = None) -> bytes:
    lines = [
        "GET / HTTP/1.1",
        "Host: x",
        "Upgrade: websocket",
        "Connection: Upgrade",
        "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==",
        "Sec-WebSocket-Version: 13",
    ]
    if origin is not None:
        lines.append(f"Origin: {origin}")
    return ("\r\n".join(lines) + "\r\n\r\n").encode()


class FakePeerWriter(FakeWriter):
    def __init__(self, peer=("203.0.113.5", 4242)) -> None:
        super().__init__()
        self.peer = peer

    def get_extra_info(self, name):
        return self.peer if name == "peername" else None

    def close(self) -> None:
        pass


class RecordingBridge:
    """Stands in for ControlBridge; records exactly what the sidecar hands over."""

    def __init__(self) -> None:
        self.calls = []

    def handle(self, request, peer, peer_host=None):
        self.calls.append((request, peer, peer_host))
        return {"re": request.get("req_id"), "ok": True, "detail": "recorded"}, None


class TestHandshakeOrigin(unittest.TestCase):
    def hs(self, raw: bytes):
        async def scenario():
            reader = asyncio.StreamReader()
            writer = FakeWriter()
            reader.feed_data(raw)
            ok, origin = await tw.ws_handshake(reader, writer)
            return ok, origin, writer.data

        return asyncio.run(scenario())

    def test_origin_is_captured(self):
        ok, origin, data = self.hs(handshake_bytes(origin="http://192.168.86.33:8095"))
        self.assertTrue(ok)
        self.assertEqual(origin, "http://192.168.86.33:8095")
        self.assertIn(b"101 Switching Protocols", data)

    def test_no_origin_header_means_none(self):
        ok, origin, data = self.hs(handshake_bytes())
        self.assertTrue(ok)
        self.assertIsNone(origin)
        self.assertIn(b"101 Switching Protocols", data)

    def test_missing_key_still_rejected(self):
        ok, origin, data = self.hs(b"GET / HTTP/1.1\r\nHost: x\r\n\r\n")
        self.assertFalse(ok)
        self.assertIsNone(origin)
        self.assertIn(b"400 Bad Request", data)


class TestControlAuthWiring(unittest.TestCase):
    """Codex P1 (#129): origin gate + peer_host hand-off in handle_client."""

    def run_client(self, origin, allowed_origins, peer=("203.0.113.5", 4242)):
        async def scenario():
            reader = asyncio.StreamReader()
            writer = FakePeerWriter(peer)
            bridge = RecordingBridge()
            reader.feed_data(handshake_bytes(origin=origin))
            reader.feed_data(
                client_frame(0x1, b'{"op":"session_start","map":"dm3","req_id":"1"}')
            )
            reader.feed_data(client_frame(0x8, b""))
            await tw.handle_client(
                tw.Hub(), reader, writer, bridge=bridge,
                allowed_origins=frozenset(allowed_origins),
            )
            return bridge, writer.data

        return asyncio.run(scenario())

    def test_unlisted_browser_origin_never_reaches_the_bridge(self):
        bridge, written = self.run_client("http://evil.example", [])
        self.assertEqual(bridge.calls, [])
        self.assertIn(b"origin not allowed for control", written)

    def test_allowlisted_origin_reaches_the_bridge_with_peer_host(self):
        bridge, written = self.run_client(
            "http://192.168.86.33:8095", ["http://192.168.86.33:8095"]
        )
        self.assertEqual(len(bridge.calls), 1)
        request, peer, peer_host = bridge.calls[0]
        self.assertEqual(request["op"], "session_start")
        self.assertEqual(peer_host, "203.0.113.5")
        self.assertIn(b'"detail":"recorded"', written)

    def test_non_browser_client_passes_peer_host_to_the_bridge(self):
        # no Origin header (ssh tunnel / CLI): no origin gate, bridge decides
        bridge, _ = self.run_client(None, [])
        self.assertEqual(len(bridge.calls), 1)
        self.assertEqual(bridge.calls[0][2], "203.0.113.5")


class TestControlTokenFile(unittest.TestCase):
    def test_generated_once_then_reloaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "control.token"
            token, created = tw.load_or_create_control_token(path)
            self.assertTrue(created)
            self.assertGreaterEqual(len(token), 64)  # 256 bits hex
            again, created_again = tw.load_or_create_control_token(path)
            self.assertFalse(created_again)
            self.assertEqual(again, token)
            if os.name == "posix":  # owner-only on the lab host
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)


class TestHarnessLabLock(unittest.TestCase):
    def test_lock_is_written_before_server_start(self):
        script = harness.REMOTE_SCRIPT
        self.assertIn('lab_lock="$HOME/komodobots-lab/lab.lock"', script)
        self.assertIn('"owner":"harness"', script)
        acquire_call = script.index("\nacquire_lab_lock\n")
        server_start = script.index("-dmS")
        self.assertLess(acquire_call, server_start)

    def test_lock_released_in_cleanup_trap_and_on_success(self):
        script = harness.REMOTE_SCRIPT
        cleanup_body = script[script.index("cleanup() {") : script.index("trap cleanup EXIT")]
        self.assertIn("release_lab_lock", cleanup_body)
        # success path: the explicit release after the trap is cleared
        tail = script[script.index("trap - EXIT") :]
        self.assertIn("release_lab_lock", tail)

    def test_release_is_guarded_by_run_id(self):
        # never clobber another owner's lock (e.g. a dashboard session's)
        self.assertIn('grep -q "\\"run_id\\":\\"${run_id}\\""', harness.REMOTE_SCRIPT)

    def test_dashboard_session_port_guard(self):
        script = harness.REMOTE_SCRIPT
        guard = script.index("komodobots_lab_${port}[[:space:]]")
        server_start = script.index("-dmS")
        self.assertLess(guard, server_start)


class TestShimBotcmds(unittest.TestCase):
    def test_signon_botcmds(self):
        self.assertEqual(qmc.signon_botcmds(0, []), [])
        self.assertEqual(qmc.signon_botcmds(2, []), ["botcmd addbot"])
        self.assertEqual(
            qmc.signon_botcmds(0, ["removebot", "removeall"]),
            ["botcmd removebot", "botcmd removeall"],
        )
        self.assertEqual(
            qmc.signon_botcmds(1, ["skill 10"]),
            ["botcmd addbot", "botcmd skill 10"],
        )


if __name__ == "__main__":
    unittest.main()
