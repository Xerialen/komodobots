"""Tests for the features package (C3). Pure stdlib; runs under `python -m unittest`."""
import math
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from features import transforms as T   # noqa: E402
from features import egocentric as E   # noqa: E402


class TestScalarTransforms(unittest.TestCase):
    def test_zscore(self):
        self.assertAlmostEqual(T.zscore(312.5, 2.1, 310.4), 1.0, places=6)
        self.assertEqual(T.zscore(5.0, 5.0, 0.0), 0.0)  # zero-std guard

    def test_minmax_maps_aabb_to_unit(self):
        self.assertAlmostEqual(T.minmax(-984.0, -984.0, 2048.0), 0.0)
        self.assertAlmostEqual(T.minmax(2048.0, -984.0, 2048.0), 1.0)
        self.assertAlmostEqual(T.minmax(1499.0, -984.0, 2048.0), 2483.0 / 3032.0, places=6)
        self.assertEqual(T.minmax(1.0, 5.0, 5.0), 0.0)  # zero-span guard

    def test_robust(self):
        self.assertAlmostEqual(T.robust(530.0, 320.0, 210.0), 1.0, places=6)
        self.assertEqual(T.robust(1.0, 0.0, 0.0), 0.0)  # zero-iqr guard

    def test_log1p_zscore(self):
        # x=0 -> log1p(0)=0 -> (0-mean)/std
        self.assertAlmostEqual(T.log1p_zscore(0.0, 1.94, 0.71), (0 - 1.94) / 0.71, places=6)
        self.assertEqual(T.log1p_zscore(-5.0, 0.0, 1.0), 0.0)  # negatives clamped to 0

    def test_divide_period(self):
        self.assertAlmostEqual(T.divide_period(60.0, 60.0), 1.0)
        self.assertAlmostEqual(T.divide_period(250.0, 250.0), 1.0)

    def test_sincos_continuous(self):
        s0, c0 = T.sincos(0.0)
        self.assertAlmostEqual(s0, 0.0, places=6)
        self.assertAlmostEqual(c0, 1.0, places=6)
        s90, c90 = T.sincos(90.0)
        self.assertAlmostEqual(s90, 1.0, places=6)
        self.assertAlmostEqual(c90, 0.0, places=6)
        # 0 and 360 encode identically (the whole point)
        self.assertAlmostEqual(T.sincos(0.0)[0], T.sincos(360.0)[0], places=6)
        self.assertAlmostEqual(T.sincos(0.0)[1], T.sincos(360.0)[1], places=6)

    def test_apply_clip(self):
        self.assertEqual(T.apply_clip(5000.0, [-2500.0, 2500.0]), 2500.0)
        self.assertEqual(T.apply_clip(-5000.0, [-2500.0, 2500.0]), -2500.0)
        self.assertEqual(T.apply_clip(100.0, None), 100.0)


class TestNormalizeDispatch(unittest.TestCase):
    """normalize() must equal calling the underlying function directly (clip first)."""

    def test_dispatch_parity(self):
        cases = [
            ({"method": "zscore", "mean": 2.1, "std": 310.4}, 312.5, T.zscore(312.5, 2.1, 310.4)),
            ({"method": "minmax", "min": -984.0, "max": 2048.0}, 1499.0, T.minmax(1499.0, -984.0, 2048.0)),
            ({"method": "robust", "median": 320.0, "iqr": 210.0}, 530.0, T.robust(530.0, 320.0, 210.0)),
            ({"method": "divide_period", "period": 60.0}, 60.0, 1.0),
            ({"method": "identity"}, 7.0, 7.0),
        ]
        for spec, val, expected in cases:
            self.assertAlmostEqual(T.normalize(val, spec), expected, places=9, msg=spec["method"])

    def test_clip_applied_before_transform(self):
        spec = {"method": "zscore", "mean": 0.0, "std": 100.0, "clip": [-2500.0, 2500.0]}
        # raw 5000 clips to 2500 then /100 = 25.0
        self.assertAlmostEqual(T.normalize(5000.0, spec), 25.0, places=6)

    def test_sincos_via_dispatch_returns_pair(self):
        out = T.normalize(90.0, {"method": "sincos"})
        self.assertEqual(len(out), 2)
        self.assertAlmostEqual(out[0], 1.0, places=6)

    def test_unknown_method_raises(self):
        with self.assertRaises(ValueError):
            T.normalize(1.0, {"method": "bogus"})


class TestEgocentric(unittest.TestCase):
    # Fixture-grounded: Milton at bridge.high observing Zepp at RL (t=130 snapshot).
    MILTON = (1499.0, -176.0, -78.0)
    ZEPP = (1812.0, 431.0, -88.0)

    def test_distance_matches_world(self):
        d = E.rel_distance(self.ZEPP, self.MILTON)
        self.assertAlmostEqual(d, math.dist(self.MILTON, self.ZEPP), places=6)
        self.assertAlmostEqual(d, 683.0, delta=1.0)

    def test_bearing_zero_when_facing_target(self):
        # yaw that points exactly at Zepp -> bearing ~0
        yaw = math.degrees(math.atan2(self.ZEPP[1] - self.MILTON[1],
                                      self.ZEPP[0] - self.MILTON[0]))
        self.assertAlmostEqual(E.rel_bearing_deg(self.ZEPP, self.MILTON, yaw), 0.0, places=4)

    def test_bearing_left_right_sign(self):
        # facing +x (yaw 0); Zepp is to the +y side -> left -> positive bearing
        self.assertGreater(E.rel_bearing_deg(self.ZEPP, self.MILTON, 0.0), 0.0)

    def test_egocentric_vec_rotation_preserves_length(self):
        v = (300.0, -120.0)
        fwd, left = E.egocentric_vec(v, 37.0)
        self.assertAlmostEqual(math.hypot(fwd, left), math.hypot(*v), places=6)

    def test_pitch_sign(self):
        above = (self.MILTON[0], self.MILTON[1], self.MILTON[2] + 200.0)
        below = (self.MILTON[0], self.MILTON[1], self.MILTON[2] - 200.0)
        self.assertGreater(E.rel_pitch_deg(above, self.MILTON), 0.0)
        self.assertLess(E.rel_pitch_deg(below, self.MILTON), 0.0)


if __name__ == "__main__":
    unittest.main()
