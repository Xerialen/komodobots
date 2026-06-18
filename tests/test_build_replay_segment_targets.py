import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_replay_segment_targets as targets  # noqa: E402


FIXTURE = """# komodobots.replay.v1 demo=mini.qwd frames=4 sha256=abc fps=77.0 aligned=time state_shift=0
13 0 0 0 0 0 0 0 0 0 0 0 0 0
13 10 0 0 100 0 0 0 0 0 320 0 0 0
13 20 10 0 200 100 0 0 45 0 320 320 0 2
13 40 10 5 300 0 0 0 90 0 0 320 0 0
"""


class SegmentTargetTests(unittest.TestCase):
    def test_parses_replay_and_derives_target_context(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "mini.cmds"
            path.write_text(FIXTURE, encoding="utf-8")

            report = targets.build_report(
                path,
                route="mini_route",
                map_name="ztricks",
                cursors=[2],
                window=1,
                acquire_radius_h=64.0,
                acquire_radius_v=48.0,
                resume_radius_h=32.0,
            )

        target = report["targets"][0]
        self.assertEqual(report["schema"], targets.SCHEMA)
        self.assertEqual(report["source"]["demo"], "mini.qwd")
        self.assertEqual(report["source"]["sha256"], "abc")
        self.assertEqual(target["cursor"], 2)
        self.assertEqual(target["target"]["origin"], {"x": 20.0, "y": 10.0, "z": 0.0})
        self.assertEqual(target["target"]["move"], {"forward": 320, "side": 320, "up": 0})
        self.assertTrue(target["target"]["jump"])
        self.assertAlmostEqual(target["target"]["horizontal_speed"], 223.607, places=3)
        self.assertAlmostEqual(target["target"]["velocity_yaw_deg"], 26.565, places=3)
        self.assertAlmostEqual(target["target"]["view_vs_velocity_yaw_lead_deg"], 18.435, places=3)
        self.assertEqual(target["context"]["window"], {"start_cursor": 1, "end_cursor": 3, "samples": 3})
        self.assertAlmostEqual(target["context"]["incoming"]["yaw_deg"], 45.0)
        self.assertAlmostEqual(target["context"]["outgoing"]["distance_h_qu"], 20.0)
        self.assertEqual(target["acquisition_gate"]["vertical_radius_qu"], 48.0)

    def test_rejects_target_cursor_outside_replay(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "mini.cmds"
            path.write_text(FIXTURE, encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "outside replay range"):
                targets.build_report(
                    path,
                    route="mini_route",
                    map_name="ztricks",
                    cursors=[99],
                    window=1,
                    acquire_radius_h=64.0,
                    acquire_radius_v=64.0,
                    resume_radius_h=32.0,
                )

    def test_cli_writes_json_and_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cmds = root / "mini.cmds"
            out_json = root / "targets.json"
            out_md = root / "targets.md"
            cmds.write_text(FIXTURE, encoding="utf-8")

            rc = targets.main(
                [
                    "--cmds",
                    str(cmds),
                    "--route",
                    "mini_route",
                    "--map",
                    "ztricks",
                    "--target-cursors",
                    "1",
                    "2",
                    "--output-json",
                    str(out_json),
                    "--output-md",
                    str(out_md),
                ]
            )

            self.assertEqual(rc, 0)
            data = json.loads(out_json.read_text(encoding="utf-8"))
            self.assertEqual(data["target_count"], 2)
            self.assertIn("Segment targets: ztricks / mini_route", out_md.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
