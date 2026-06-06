from __future__ import annotations

import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools.qwd_usercmd import qwd_usercmd


def record_header(time_s: float, message_type: int) -> bytes:
    return struct.pack("<fB", time_s, message_type)


def usercmd_payload(
    *,
    msec: int = 13,
    angles: tuple[float, float, float] = (1.0, 90.0, 0.0),
    forward: int = 400,
    side: int = -200,
    up: int = 0,
    buttons: int = 3,
    impulse: int = 7,
) -> bytes:
    return struct.pack(qwd_usercmd.USERCMD_STRUCT_FORMAT, msec, *angles, forward, side, up, buttons, impulse)


def dem_cmd_record(
    time_s: float,
    *,
    msec: int = 13,
    angles: tuple[float, float, float] = (1.0, 90.0, 0.0),
    view_angles: tuple[float, float, float] = (2.0, 91.0, 0.0),
    forward: int = 400,
    side: int = -200,
    up: int = 0,
    buttons: int = 3,
    impulse: int = 7,
) -> bytes:
    return (
        record_header(time_s, qwd_usercmd.DEM_CMD)
        + usercmd_payload(
            msec=msec,
            angles=angles,
            forward=forward,
            side=side,
            up=up,
            buttons=buttons,
            impulse=impulse,
        )
        + struct.pack(qwd_usercmd.VIEW_ANGLES_FORMAT, *view_angles)
    )


class QwdUsercmdTests(unittest.TestCase):
    def test_usercmd_struct_size_matches_ezquake_layout(self) -> None:
        self.assertEqual(qwd_usercmd.USERCMD_STRUCT_SIZE, 24)
        self.assertEqual(struct.calcsize("<BxxxfffhhhBB"), 24)

    def test_extracts_synthetic_dem_cmd_exactly(self) -> None:
        data = (
            record_header(0.0, qwd_usercmd.DEM_SET)
            + struct.pack("<ii", 123, 456)
            + dem_cmd_record(0.013)
            + record_header(0.026, qwd_usercmd.DEM_READ)
            + struct.pack("<i", 3)
            + b"abc"
            + dem_cmd_record(0.039, msec=26, view_angles=(4.0, 92.5, 0.0), forward=800, side=0, buttons=2)
        )

        result = qwd_usercmd.parse_qwd_bytes(data)

        self.assertTrue(result.header["eof_clean"])
        self.assertEqual(result.header["bytes_read"], len(data))
        self.assertEqual(result.header["total_frames"], 2)
        self.assertEqual(result.header["record_counts"]["dem_cmd"], 2)
        self.assertEqual(result.commands[0].msec, 13)
        self.assertEqual(result.commands[0].view_angles, (2.0, 91.0, 0.0))
        self.assertEqual(result.commands[0].cmd_angles, (1.0, 90.0, 0.0))
        self.assertEqual(result.commands[0].forwardmove, 400)
        self.assertEqual(result.commands[0].sidemove, -200)
        self.assertEqual(result.commands[0].buttons, 3)
        self.assertEqual(result.commands[0].impulse, 7)
        self.assertEqual(result.commands[1].msec, 26)
        self.assertEqual(result.commands[1].forwardmove, 800)

    def test_ndjson_header_then_usercmd_rows(self) -> None:
        result = qwd_usercmd.parse_qwd_bytes(dem_cmd_record(1.0))
        rows = [json.loads(line) for line in qwd_usercmd.iter_ndjson(result)]

        self.assertEqual(rows[0]["record_type"], "header")
        self.assertEqual(rows[0]["schema"], "komodobots.qwd_usercmd.v1")
        self.assertEqual(rows[1]["record_type"], "usercmd")
        self.assertEqual(rows[1]["view_angles"], [2.0, 91.0, 0.0])
        self.assertNotIn("cmd_angles", rows[1])

    def test_include_cmd_angles_is_explicit(self) -> None:
        result = qwd_usercmd.parse_qwd_bytes(dem_cmd_record(1.0))
        rows = [json.loads(line) for line in qwd_usercmd.iter_ndjson(result, include_cmd_angles=True)]

        self.assertEqual(rows[1]["cmd_angles"], [1.0, 90.0, 0.0])

    def test_truncated_dem_cmd_fails_instead_of_silent_desync(self) -> None:
        data = record_header(0.0, qwd_usercmd.DEM_CMD) + usercmd_payload()[:-1]

        with self.assertRaises(qwd_usercmd.QwdUsercmdError):
            qwd_usercmd.parse_qwd_bytes(data)

    def test_cli_writes_output_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            qwd = root / "sample.qwd"
            out = root / "out.ndjson"
            qwd.write_bytes(dem_cmd_record(1.0))

            rc = qwd_usercmd.main([str(qwd), "--output", str(out), "--include-cmd-angles"])

            self.assertEqual(rc, 0)
            rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(rows[0]["source_filename"], "sample.qwd")
            self.assertEqual(rows[1]["cmd_angles"], [1.0, 90.0, 0.0])


if __name__ == "__main__":
    unittest.main()

