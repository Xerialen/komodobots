"""Tests for pov_fuse_extract signature math (route_observatory pov_fuse tool).

Pure stdlib unittest. Follows the komodobots convention: put the module's dir on sys.path,
import top-level. Covers the parts that are easy to get subtly wrong and that the signature
(BC target + believability rubric) depends on:
  - vya quake-angle-units -> degrees
  - look-vs-move angular wraparound
  - the DEBOUNCED jump detector (must not inflate on ramp/stairs flicker)
  - straightness (net/path)
"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROUTE_OBS = HERE.parent / "experiments" / "route_observatory"
for _p in (str(ROUTE_OBS), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pov_fuse_extract as M  # noqa: E402


def mk(t, vz, x=0.0, y=0.0, hs=400, yaw=0.0, mdir=0.0):
    return {"t": t, "x": x, "y": y, "z": 0.0, "hs": hs, "yaw": yaw, "mdir": mdir, "vz": vz}


class TestAngles(unittest.TestCase):
    def test_yaw_deg(self):
        self.assertAlmostEqual(M.yaw_deg(0), 0.0)
        self.assertAlmostEqual(M.yaw_deg(16384), 90.0)     # quarter turn
        self.assertAlmostEqual(M.yaw_deg(-16384), -90.0)
        self.assertAlmostEqual(abs(M.yaw_deg(32768)), 180.0)  # half turn -> +/-180

    def test_move_dir(self):
        self.assertAlmostEqual(M.move_dir_deg(100, 0), 0.0)
        self.assertAlmostEqual(M.move_dir_deg(0, 100), 90.0)
        self.assertIsNone(M.move_dir_deg(0, 0))            # stationary -> None

    def test_look_vs_move_wraparound(self):
        self.assertAlmostEqual(M.look_vs_move(170, -170), 20.0)  # crosses +/-180, not 340
        self.assertAlmostEqual(M.look_vs_move(10, 10), 0.0)
        self.assertIsNone(M.look_vs_move(None, 5))
        self.assertIsNone(M.look_vs_move(5, None))


class TestJumpDetector(unittest.TestCase):
    def test_debounce_ignores_ramp_flicker(self):
        # grounded -> takeoff -> vz oscillates across +240 (ramp/stairs) -> land -> takeoff again.
        ticks = [
            mk(0.000, -10), mk(0.013, -10),     # grounded
            mk(0.026, 270),                     # TAKEOFF 1
            mk(0.039, 255), mk(0.052, 235), mk(0.065, 260),  # flicker: recent vz high -> blocked
            mk(0.400, -20),                     # landed (near ground)
            mk(0.413, 280),                     # TAKEOFF 2 (>0.22s later, recent near-ground)
        ]
        jumps = M.detect_jumps(ticks)
        self.assertEqual(len(jumps), 2, f"expected 2 debounced takeoffs, got {jumps}")

    def test_no_jump_without_near_ground(self):
        # vz crosses +240 but never came near the ground -> not a takeoff (airborne bump).
        ticks = [mk(0, 100), mk(0.05, 200), mk(0.10, 300), mk(0.15, 320)]
        self.assertEqual(M.detect_jumps(ticks), [])


class TestSignature(unittest.TestCase):
    def test_straight_leg(self):
        ticks = [mk(0, 0, x=0), mk(1, 0, x=100), mk(2, 0, x=200), mk(3, 0, x=300)]
        sig = M.compute_signature(ticks)
        self.assertEqual(sig["straightness"], 1.0)   # net == path on a straight line
        self.assertEqual(sig["hs_mean"], 400)
        self.assertEqual(sig["jumps"], 0)
        self.assertEqual(sig["dur_s"], 3.0)

    def test_bent_leg_is_not_straight(self):
        # an L: 100 right then 200 up -> path 300, net hypot(100,200)=223.6 -> ~0.745
        ticks = [mk(0, 0, x=0, y=0), mk(1, 0, x=100, y=0),
                 mk(2, 0, x=100, y=100), mk(3, 0, x=100, y=200)]
        sig = M.compute_signature(ticks)
        self.assertLess(sig["straightness"], 0.8)
        self.assertGreater(sig["straightness"], 0.6)


if __name__ == "__main__":
    unittest.main()
