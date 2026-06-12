import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import ztricks_reference_trace as trace  # noqa: E402


class TestZtricksReferenceTrace(unittest.TestCase):
    def test_unwrap_angles_crosses_zero_smoothly(self) -> None:
        self.assertEqual(trace.unwrap_angles([358.0, 359.0, 1.0, 3.0]), [358.0, 359.0, 361.0, 363.0])

    def test_quadratic_lagrange_hits_curve_midpoint(self) -> None:
        value = trace.quadratic_lagrange(1.5, [(1.0, 1.0), (2.0, 4.0), (3.0, 9.0)])
        self.assertAlmostEqual(value, 2.25)

    def test_build_trace_has_interpolated_lip_and_quadratic_controller_curve(self) -> None:
        report = trace.build_trace()
        events = report["events"]

        self.assertEqual(report["schema"], "komodobots.ztricks_reference_trace.v1")
        self.assertEqual(report["source"]["attempt"], 11)
        self.assertEqual(report["interpolation"]["controller_curve"], "local_quadratic_lagrange_by_time_on_successful_attempt")
        self.assertEqual(events["release_jump"]["source_row"], 1918)
        self.assertEqual(events["physical_lip_x_crossing"]["source_row"], "1920..1921")
        self.assertAlmostEqual(events["physical_lip_x_crossing"]["origin"]["x"], -3348.0, places=3)
        self.assertGreater(len(report["controller_curve"]["samples"]), 10)
        sample = report["controller_curve"]["samples"][0]
        self.assertIn("support_rows", sample)
        self.assertIn("view_yaw_deg", sample)


if __name__ == "__main__":
    unittest.main()
