from __future__ import annotations

import struct
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts import probe_qwd_route_applicability as probe
from tools.qwd_usercmd import qwd_usercmd


def record_header(time_s: float, message_type: int) -> bytes:
    return struct.pack(qwd_usercmd.RECORD_HEADER_FORMAT, time_s, message_type)


def dem_read_record(time_s: float, payload: bytes) -> bytes:
    return record_header(time_s, qwd_usercmd.DEM_READ) + struct.pack("<i", len(payload)) + payload


def dem_cmd_record(
    time_s: float,
    *,
    view_yaw: float = 90.0,
    forward: int = 400,
    side: int = 0,
    buttons: int = 2,
) -> bytes:
    payload = struct.pack(
        qwd_usercmd.USERCMD_STRUCT_FORMAT,
        13,
        0.0,
        view_yaw,
        0.0,
        forward,
        side,
        0,
        buttons,
        0,
    )
    return record_header(time_s, qwd_usercmd.DEM_CMD) + payload + struct.pack(
        qwd_usercmd.VIEW_ANGLES_FORMAT,
        0.0,
        view_yaw,
        0.0,
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


class QwdRouteApplicabilityTests(unittest.TestCase):
    def test_anchored_playerinfo_ignores_later_false_marker(self) -> None:
        payload = playerinfo_payload(origin=(64.0, 0.0, 24.0)) + bytes(
            [probe.SVC_PLAYERINFO, 31, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
        )

        sample = probe.parse_anchored_playerinfo(payload)

        self.assertIsNotNone(sample)
        assert sample is not None
        self.assertEqual(sample.playernum, 1)
        self.assertEqual(sample.origin, (64.0, 0.0, 24.0))

    def test_summarizes_synthetic_command_state_pairs(self) -> None:
        data = b"".join(
            [
                dem_cmd_record(0.000, view_yaw=90.0, forward=400, side=0),
                dem_read_record(0.000, playerinfo_payload(origin=(0.0, 0.0, 24.0))),
                dem_cmd_record(0.013, view_yaw=91.0, forward=400, side=200),
                dem_read_record(0.013, playerinfo_payload(origin=(8.0, 0.0, 24.0))),
                dem_cmd_record(0.026, view_yaw=92.0, forward=400, side=200),
                dem_read_record(0.026, playerinfo_payload(origin=(16.0, 0.0, 24.0))),
            ]
        )

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.qwd"
            path.write_bytes(data)
            summary = probe.summarize_demo(path, waypoint_spacing_qu=8.0)

        self.assertEqual(summary["command_frames"], 3)
        self.assertEqual(summary["state_frames"], 3)
        self.assertEqual(summary["paired_frames"], 3)
        self.assertEqual(summary["paired_coverage"], 1.0)
        self.assertEqual(summary["continuity"]["discontinuity_count"], 0)
        self.assertEqual(summary["route_probe"]["status"], "trajectory_route_candidate")
        self.assertEqual(summary["commands"]["nonzero_side_ratio"], 0.667)


if __name__ == "__main__":
    unittest.main()
