"""Control-channel wiring (LD-F2, #96): sidecar text frames + harness lock.

Locks (a) the telemetry sidecar's websocket reader: masked client TEXT frames
reach the control handler while ping/close behave exactly as before and the
no-handler path stays ignore-only (telemetry-only back-compat); (b) the
harness-priority lock lines in run_frobodm2_lab.py's remote script (owner=
harness written before the server screen starts, released in the cleanup trap
AND on the success path, removal guarded by run_id so another owner's lock is
never clobbered, and the dashboard-session port guard); (c) the qw_min_client
--botcmd extension used by the bridge for bot ops.
"""

import asyncio
import sys
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
