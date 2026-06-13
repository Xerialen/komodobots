from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(REPO_ROOT), str(REPO_ROOT / "scripts"), str(REPO_ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import qwd_seam_validator as validator
import test_build_replay_command_file as fixtures


class QwdSeamValidatorTests(unittest.TestCase):
    def test_reports_angle_channel_and_unsafe_zip_pairing(self) -> None:
        data = fixtures.synthetic_demo_missing_state()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.qwd"
            path.write_bytes(data)
            report = validator.validate_demo(path)

        self.assertFalse(report["raw_mouse_deltas_available"])
        self.assertEqual(report["angle_label_kind"], "per-frame absolute view-angle result")
        self.assertEqual(report["authoritative_angle_channel"], "view_angles")
        self.assertEqual(report["command_frames"], 4)
        self.assertEqual(report["state_frames"], 3)
        self.assertTrue(report["zip_pairing"]["unsafe_zip_pairing"])
        self.assertEqual(report["time_alignment"]["unmatched_command_frames"], 1)
        self.assertEqual(report["time_alignment"]["dropped_cmd_indices"], [2])
        self.assertEqual(report["angle_channel_delta_deg"]["yaw"]["max"], 0.0)

    def test_markdown_names_mouse_delta_limitation(self) -> None:
        report = {
            "schema": validator.SCHEMA,
            "demos": [
                {
                    "demo": "sample.qwd",
                    "command_frames": 4,
                    "state_frames": 3,
                    "angle_channel_delta_deg": {"yaw": {"p95": 0.0}},
                    "command_msec": {"p50": 13.0},
                    "zip_pairing": {"paired_coverage": 0.75, "unsafe_zip_pairing": True},
                    "time_alignment": {"unmatched_command_frames": 1},
                }
            ],
        }

        rendered = validator.render_markdown(report)

        self.assertIn("does not provide raw device mouse deltas", rendered)
        self.assertIn("view_angles", rendered)
        self.assertIn("sample.qwd", rendered)


if __name__ == "__main__":
    unittest.main()
