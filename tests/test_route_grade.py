"""Gating stdlib tests for the honest offline route-grade (`route_grade.py`, D1/D2).

No torch/numpy — runs in the merge-gate floor (`python -m unittest discover -s tests`). The load-bearing
test is `test_r5_hybrid_fails_despite_low_rmse`: it proves the three-criterion gate catches the non-bhop
forward+strafe hybrid that route-shape MSE ALONE would pass (the whole reason D2 is not MSE-only).
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "experiments" / "route_observatory"))

import route_grade as G  # noqa: E402

# A straight human-reference route along +x, 0..1000 qu, cruising at 400 qu/s.
POLYLINE = [(float(i * 100), 0.0, 0.0) for i in range(11)]
SPEEDS = [400.0] * 11
ROUTE = {"polyline": POLYLINE, "speeds": SPEEDS, "total_len": 1000.0}

_XS = [float(x) for x in range(100, 901, 100)]  # 100..900 on the route


def tick(x, y, vx, vy, onground=False, fwd_am=0, z=0.0):
    return {"ox": x, "oy": y, "oz": z, "vx": vx, "vy": vy, "onground": onground, "fwd_am": fwd_am}


class TestRouteGrade(unittest.TestCase):
    def test_clean_fast_bhop_passes(self):
        # On the line, 1.5x human speed, airborne, forward RELEASED, vertical bounce present.
        bounce = [0.0, 20.0, 40.0, 20.0]
        traj = [tick(x, 0.0, 600.0, 0.0, onground=False, fwd_am=0, z=bounce[i % 4])
                for i, x in enumerate(_XS)]
        g = G.grade_trajectory(traj, ROUTE)
        self.assertLess(g["route_rmse_qu"], 1.0)          # vertical bounce does NOT inflate lateral rmse
        self.assertGreaterEqual(g["median_speedup_ratio"], 1.49)
        self.assertTrue(g["on_route"])
        self.assertTrue(g["faster_than_human"])
        self.assertTrue(g["clean_mechanism"])
        self.assertTrue(g["passed"])

    def test_r5_hybrid_fails_despite_low_rmse(self):
        # THE honesty guarantee. Hugs the human line (low rmse -> on_route TRUE, so MSE-alone passes it),
        # but is SLOW (ratio 0.375 < 1) AND holds +forward airborne (bulldoze-hybrid). Must FAIL overall.
        traj = [tick(x, 0.0, 150.0, 0.0, onground=False, fwd_am=2) for x in _XS]
        g = G.grade_trajectory(traj, ROUTE)
        self.assertTrue(g["on_route"], "hybrid hugs the line -> route-MSE alone would PASS it")
        self.assertFalse(g["faster_than_human"])          # slow
        self.assertFalse(g["clean_mechanism"])            # forward held in the air
        self.assertFalse(g["passed"], "the paired criteria must catch the hybrid MSE-alone misses")

    def test_off_route_fails_on_route(self):
        # Fast + clean, but 300 qu off the line -> lateral rmse > tol.
        traj = [tick(x, 300.0, 600.0, 0.0, onground=False, fwd_am=0) for x in _XS]
        g = G.grade_trajectory(traj, ROUTE)
        self.assertGreater(g["route_rmse_qu"], G.DEFAULT_GRADE_CFG["rmse_tol"])
        self.assertFalse(g["on_route"])
        self.assertFalse(g["passed"])

    def test_backward_fails_faster_than_human(self):
        # On the line + clean, but moving BACKWARD along the route (v_along < 0 -> ratio < 0).
        traj = [tick(x, 0.0, -300.0, 0.0, onground=False, fwd_am=0) for x in _XS]
        g = G.grade_trajectory(traj, ROUTE)
        self.assertTrue(g["on_route"])
        self.assertFalse(g["faster_than_human"])
        self.assertFalse(g["passed"])

    def test_ground_forward_not_penalized_by_mechanism(self):
        # A fast on-route run held on the GROUND with +forward: ground forward is the legit builder
        # (D6), so it must NOT trip the air-forward mechanism check (which counts airborne ticks only).
        traj = [tick(x, 0.0, 500.0, 0.0, onground=True, fwd_am=2) for x in _XS]
        g = G.grade_trajectory(traj, ROUTE)
        self.assertEqual(g["air_frac"], 0.0)
        self.assertEqual(g["air_forward_press_frac"], 0.0)
        self.assertTrue(g["clean_mechanism"])
        self.assertTrue(g["faster_than_human"])
        self.assertTrue(g["passed"])

    def test_min_ratio_is_tunable(self):
        # A 1.25x run passes at the default floor (1.0) but fails a strictly-superhuman floor (1.5).
        traj = [tick(x, 0.0, 500.0, 0.0, onground=False, fwd_am=0) for x in _XS]
        self.assertTrue(G.grade_trajectory(traj, ROUTE)["passed"])
        g = G.grade_trajectory(traj, ROUTE, cfg={"min_ratio": 1.5})
        self.assertFalse(g["faster_than_human"])
        self.assertFalse(g["passed"])

    def test_empty_and_degenerate(self):
        self.assertFalse(G.grade_trajectory([], ROUTE)["passed"])
        self.assertEqual(G.grade_trajectory([], ROUTE)["n_ticks"], 0)
        one_pt = {"polyline": [(0.0, 0.0, 0.0)], "speeds": [400.0], "total_len": 0.0}
        self.assertFalse(G.grade_trajectory([tick(1, 0, 600, 0)], one_pt)["passed"])

    def test_determinism(self):
        traj = [tick(x, 0.0, 600.0, 0.0, onground=False, fwd_am=0) for x in _XS]
        self.assertEqual(G.grade_trajectory(traj, ROUTE), G.grade_trajectory(traj, ROUTE))


if __name__ == "__main__":
    unittest.main()
