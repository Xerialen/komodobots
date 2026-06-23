"""ml/tests/test_optimal_aim.py — proves CL.optimal_strafe_yaw against the EXACT sim.

The perfect-aim diagnostic overrides the executed view yaw with the speed-optimal
air-strafe angle (wishdir _|_ horizontal velocity). This test pins that helper's
correctness WITHOUT torch/BSP: for a spread of velocities and key combos it checks the
returned yaw makes the wishdir perpendicular to velocity AND that running it through the
real pmove_sim._air_accelerate yields the maximal post-tick horizontal speed (>= a fine
brute-force sweep). Pure stdlib (math + pmove_sim).
"""
import math
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ML = HERE.parent
REPO_ROOT = ML.parent
sys.path.insert(0, str(ML))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import eval_broad_closedloop as CL   # noqa: E402  (pure glue; the helper under test)
import pmove_sim as PM               # noqa: E402  (the exact engine = ground truth)

VELS = [(300.0, 0.0), (0.0, 250.0), (200.0, 200.0), (-150.0, 80.0), (400.0, -300.0),
        (50.0, 0.0), (600.0, 10.0)]
KEYS = [(0.0, 400.0), (400.0, 400.0), (400.0, 0.0), (-400.0, 400.0), (400.0, -400.0)]


def _wishdir(yaw, fwd, side):
    """Replicate pmove_sim._air_move's horizontal wishdir from a view yaw + move keys."""
    f, r = PM.angle_vectors((0.0, yaw, 0.0))
    f = [f[0], f[1], 0.0]
    r = [r[0], r[1], 0.0]
    nf = math.hypot(f[0], f[1]) or 1.0
    nr = math.hypot(r[0], r[1]) or 1.0
    f = [f[0] / nf, f[1] / nf, 0.0]
    r = [r[0] / nr, r[1] / nr, 0.0]
    wv = [f[0] * fwd + r[0] * side, f[1] * fwd + r[1] * side, 0.0]
    ws = math.hypot(wv[0], wv[1])
    if ws == 0:
        return [0.0, 0.0, 0.0]
    return [wv[0] / ws, wv[1] / ws, 0.0]


def _post_hspeed(vx, vy, wishdir, fwd, side):
    """Horizontal speed after ONE real _air_accelerate tick (wishspeed capped like the sim)."""
    pm = PM.Pmove(None)            # world unused by _air_accelerate
    pm.frametime = 0.013
    s = PM.PlayerState([0.0, 0.0, 0.0], [float(vx), float(vy), 0.0])
    ws = min(math.hypot(fwd, side), 320.0)
    pm._air_accelerate(s, wishdir, ws, 10.0)
    return math.hypot(s.velocity[0], s.velocity[1])


class TestOptimalStrafeYaw(unittest.TestCase):
    def test_perpendicular_and_sim_maximal(self):
        for vx, vy in VELS:
            for fwd, side in KEYS:
                y = CL.optimal_strafe_yaw(vx, vy, fwd, side, 0.0)
                wd = _wishdir(y, fwd, side)
                speed = math.hypot(vx, vy)
                # (1) wishdir is perpendicular to the horizontal velocity
                dot = wd[0] * vx + wd[1] * vy
                self.assertLess(abs(dot), 1e-4 * max(1.0, speed),
                                msg=f"not perpendicular: v=({vx},{vy}) keys=({fwd},{side}) y={y} dot={dot}")
                # (2) it maximizes the EXACT sim's post-tick horizontal speed
                got = _post_hspeed(vx, vy, wd, fwd, side)
                best = max(_post_hspeed(vx, vy, _wishdir(i * 0.5, fwd, side), fwd, side)
                           for i in range(720))
                self.assertGreaterEqual(got, best - 0.05,
                                        msg=f"not maximal: v=({vx},{vy}) keys=({fwd},{side}) got={got} best={best}")
                # (3) and it matches the closed-form analytic optimum sqrt(s^2+900)
                self.assertAlmostEqual(got, math.sqrt(speed * speed + 900.0), places=3)

    def test_fallback_when_stopped_or_no_keys(self):
        self.assertEqual(CL.optimal_strafe_yaw(0.0, 0.0, 400.0, 400.0, 42.0), 42.0)   # stopped
        self.assertEqual(CL.optimal_strafe_yaw(300.0, 0.0, 0.0, 0.0, 17.0), 17.0)     # no keys

    def test_branch_nearest_fallback(self):
        # the two perpendicular branches are 180 apart; the helper must pick the one
        # closest to the fallback (route-following) yaw.
        ya = CL.optimal_strafe_yaw(300.0, 0.0, 0.0, 400.0, 0.0)
        yb = CL.optimal_strafe_yaw(300.0, 0.0, 0.0, 400.0, 180.0)
        self.assertAlmostEqual(abs(((ya - yb) % 360.0)), 180.0, places=3)


if __name__ == "__main__":
    unittest.main()
