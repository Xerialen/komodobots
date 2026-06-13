from __future__ import annotations

import struct
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import build_replay_command_file as builder
import probe_qwd_route_applicability as probe
from tools.qwd_usercmd import qwd_usercmd


def record_header(time_s: float, message_type: int) -> bytes:
    return struct.pack(qwd_usercmd.RECORD_HEADER_FORMAT, time_s, message_type)


def dem_read_record(time_s: float, payload: bytes) -> bytes:
    return record_header(time_s, qwd_usercmd.DEM_READ) + struct.pack("<i", len(payload)) + payload


def dem_cmd_record(
    time_s: float,
    *,
    msec: int = 13,
    pitch: float = 0.0,
    view_yaw: float = 90.0,
    forward: int = 400,
    side: int = 0,
    up: int = 0,
    buttons: int = 2,
) -> bytes:
    payload = struct.pack(
        qwd_usercmd.USERCMD_STRUCT_FORMAT,
        msec,
        pitch,
        view_yaw,
        0.0,
        forward,
        side,
        up,
        buttons,
        0,
    )
    return record_header(time_s, qwd_usercmd.DEM_CMD) + payload + struct.pack(
        qwd_usercmd.VIEW_ANGLES_FORMAT, pitch, view_yaw, 0.0
    )


def coord(value: float) -> bytes:
    return struct.pack("<h", round(value * 8))


def playerinfo_payload(
    *,
    playernum: int = 1,
    origin: tuple[float, float, float] = (0.0, 0.0, 24.0),
    velocity: tuple[int, int, int] = (320, 0, 0),
    frame: int = 9,
) -> bytes:
    flags = probe.PF_VELOCITY1 | probe.PF_VELOCITY2 | probe.PF_VELOCITY3
    body = (
        bytes([probe.SVC_PLAYERINFO, playernum])
        + struct.pack("<H", flags)
        + b"".join(coord(value) for value in origin)
        + bytes([frame])
        + struct.pack("<hhh", *velocity)
    )
    return b"\x01\x00\x00\x00\x01\x00\x00\x00" + body


def synthetic_demo() -> bytes:
    return b"".join(
        [
            dem_cmd_record(0.000, msec=13, pitch=5.0, view_yaw=90.0, forward=0, side=0, buttons=0),
            dem_read_record(0.000, playerinfo_payload(origin=(0.0, 0.0, 24.0), velocity=(0, 0, 0))),
            dem_cmd_record(0.013, msec=13, view_yaw=91.0, forward=400, side=200, buttons=2),
            dem_read_record(0.013, playerinfo_payload(origin=(8.0, 0.0, 24.0), velocity=(320, 0, 0))),
            dem_cmd_record(0.026, msec=13, view_yaw=92.0, forward=400, side=-200, up=10, buttons=3),
            dem_read_record(0.026, playerinfo_payload(origin=(16.0, 0.0, 24.0), velocity=(400, 0, 0))),
        ]
    )


def synthetic_demo_missing_state() -> bytes:
    return b"".join(
        [
            dem_cmd_record(0.000, msec=13, view_yaw=90.0, forward=0, side=0, buttons=0),
            dem_read_record(0.000, playerinfo_payload(origin=(0.0, 0.0, 24.0), velocity=(0, 0, 0))),
            dem_cmd_record(0.013, msec=13, view_yaw=91.0, forward=400, side=200, buttons=2),
            dem_read_record(0.013, playerinfo_payload(origin=(10.0, 0.0, 24.0), velocity=(320, 0, 0))),
            dem_cmd_record(0.026, msec=13, view_yaw=92.0, forward=400, side=-200, buttons=2),
            dem_cmd_record(0.039, msec=13, view_yaw=93.0, forward=400, side=-200, buttons=2),
            dem_read_record(0.039, playerinfo_payload(origin=(30.0, 0.0, 24.0), velocity=(520, 0, 0))),
        ]
    )


class BuildReplayCommandFileTests(unittest.TestCase):
    def test_frames_match_commands_and_capture_frame0(self) -> None:
        data = synthetic_demo()
        with self._tempfile(data) as path:
            frames, meta = builder.build_replay_frames(path)

        self.assertEqual(len(frames), 3)
        self.assertEqual(meta["command_frames"], 3)
        self.assertEqual(meta["state_frames"], 3)
        self.assertEqual(meta["paired_frames"], 3)
        self.assertEqual(meta["paired_coverage"], 1.0)
        self.assertEqual(meta["reference_frames"], 3)
        self.assertEqual(meta["state_alignment"]["method"], "time")
        self.assertEqual(meta["reference_source_counts"], {"matched": 3})
        self.assertEqual(meta["interpolated_command_indices"], [])
        self.assertEqual(meta["angle_channel_delta_deg"]["yaw"]["max"], 0.0)
        # frame 0 is the snap state: human origin/velocity/angles before any input.
        self.assertEqual(frames[0]["origin"], [0.0, 0.0, 24.0])
        self.assertEqual(frames[0]["velocity"], [0, 0, 0])
        self.assertEqual(frames[0]["angles"][0], 5.0)
        self.assertEqual(frames[0]["angles"][1], 90.0)
        self.assertEqual(frames[0]["move"], [0, 0, 0])
        # later frames carry the real inputs and trajectory reference.
        self.assertEqual(frames[1]["move"], [400, 200, 0])
        self.assertEqual(frames[2]["move"], [400, -200, 10])
        self.assertEqual(frames[2]["buttons"], 3)
        self.assertEqual(frames[1]["origin"], [8.0, 0.0, 24.0])

    def test_time_alignment_interpolates_dropped_state_without_shifting_inputs(self) -> None:
        data = synthetic_demo_missing_state()
        with self._tempfile(data) as path:
            frames, meta = builder.build_replay_frames(path)

        self.assertEqual(len(frames), 4)
        self.assertEqual(meta["command_frames"], 4)
        self.assertEqual(meta["state_frames"], 3)
        self.assertEqual(meta["paired_frames"], 3)
        self.assertEqual(meta["state_alignment"]["unmatched_command_frames"], 1)
        self.assertEqual(meta["state_alignment"]["dropped_cmd_indices"], [2])
        self.assertEqual(meta["interpolated_command_indices"], [2])
        self.assertEqual(meta["reference_source_counts"]["interpolated"], 1)
        self.assertEqual(frames[2]["reference_source"], "interpolated")
        self.assertTrue(frames[2]["reference_interpolated"])
        # The missing state row is reconstructed halfway between the adjacent
        # timed references; the command itself remains the original command 2.
        self.assertEqual(frames[2]["origin"], [20.0, 0.0, 24.0])
        self.assertEqual(frames[2]["velocity"], [420, 0, 0])
        self.assertEqual(frames[2]["angles"][1], 92.0)
        self.assertEqual(frames[2]["move"], [400, -200, 0])

    def test_legacy_zip_alignment_marks_dropped_state_unsafe(self) -> None:
        data = synthetic_demo_missing_state()
        with self._tempfile(data) as path:
            frames, meta = builder.build_replay_frames(path, alignment="zip")

        self.assertEqual(len(frames), 4)
        self.assertTrue(meta["state_alignment"]["unsafe_zip_pairing"])
        self.assertEqual(meta["state_alignment"]["dropped_cmd_indices"], [3])
        # Zip pairing assigns the third state to command 2, shifting the
        # reference that actually belongs to command 3.
        self.assertEqual(frames[2]["origin"], [30.0, 0.0, 24.0])

    def test_cli_refuses_unsafe_zip_without_explicit_opt_in(self) -> None:
        import io
        import tempfile
        from contextlib import redirect_stderr, redirect_stdout

        data = synthetic_demo_missing_state()
        with tempfile.TemporaryDirectory() as tmp:
            demo = Path(tmp) / "sample.qwd"
            out_cmds = Path(tmp) / "sample.cmds"
            out_json = Path(tmp) / "sample.json"
            demo.write_bytes(data)

            stderr = io.StringIO()
            with redirect_stderr(stderr):
                code = builder.main(
                    [
                        "--demo",
                        str(demo),
                        "--alignment",
                        "zip",
                        "--output",
                        str(out_cmds),
                        "--output-json",
                        str(out_json),
                    ]
                )

            self.assertEqual(code, 2)
            self.assertIn("Refusing unsafe zip alignment", stderr.getvalue())
            self.assertFalse(out_cmds.exists())
            self.assertFalse(out_json.exists())

            stdout = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                code = builder.main(
                    [
                        "--demo",
                        str(demo),
                        "--alignment",
                        "zip",
                        "--allow-unsafe-zip",
                        "--output",
                        str(out_cmds),
                        "--output-json",
                        str(out_json),
                    ]
                )

            self.assertEqual(code, 0)
            self.assertTrue(out_cmds.exists())
            self.assertTrue(out_json.exists())

    def test_render_is_round_trippable_per_line(self) -> None:
        data = synthetic_demo()
        with self._tempfile(data) as path:
            frames, meta = builder.build_replay_frames(path)
        text = builder.render_replay_file(frames, meta)

        lines = text.splitlines()
        self.assertTrue(lines[0].startswith("# komodobots.replay.v1"))
        data_lines = [ln for ln in lines if ln and not ln.startswith("#")]
        self.assertEqual(len(data_lines), 3)
        # Every data line must carry the 14 fields the C parser reads with sscanf.
        for ln in data_lines:
            self.assertEqual(len(ln.split()), 14)
        # Spot-check the third frame round-trips to the source values.
        fields = data_lines[2].split()
        self.assertEqual(int(fields[0]), 13)  # msec
        self.assertEqual([int(round(float(fields[1]))), int(round(float(fields[2]))), int(round(float(fields[3])))], [16, 0, 24])
        self.assertEqual([int(fields[10]), int(fields[11]), int(fields[12])], [400, -200, 10])
        self.assertEqual(int(fields[13]), 3)  # buttons

    def _tempfile(self, data: bytes):
        import tempfile
        from contextlib import contextmanager

        @contextmanager
        def _cm():
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "sample.qwd"
                path.write_bytes(data)
                yield path

        return _cm()


if __name__ == "__main__":
    unittest.main()
