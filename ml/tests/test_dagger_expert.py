"""ml/tests/test_dagger_expert.py -- the MATH SANITY-GATE for the DAgger expert.

The expert (ml/dagger/expert.expert_action) wraps the proven optimal_strafe_yaw seam and
overrides the move keys. This gate proves the wrapper CANNOT silently mis-map keys->yaw:
for a spread of airborne velocities (+ goal headings), it feeds the expert's AIR action
through the EXACT pmove_sim._air_accelerate and asserts the realized post-tick horizontal
speed equals the perpendicular-optimal closed form

    |v'_h| = sqrt(s^2 + 900 - (v_h . wishdir)^2)      (s = |v_h|)

which, because the expert orients wishdir _|_ v_h, reduces to sqrt(s^2 + 900) -- the
engine maximum at every speed (mirrors ml/tests/test_optimal_aim). If the wrapper passed
the wrong `side` sign into the seam vs into the usercmd, the realized wishdir would NOT be
perpendicular and this gate would fail. Pure stdlib (math + pmove_sim + the expert).
"""
import math
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ML = HERE.parent
REPO_ROOT = ML.parent
for _p in (str(ML), str(ML / "dagger"), str(REPO_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pmove_sim as PM            # noqa: E402  (the exact engine = ground truth)
from dagger import expert as EX   # noqa: E402  (the wrapper under test)

# airborne velocities (qu/s) -- include axis-aligned, diagonal, slow, fast, negative.
VELS = [(300.0, 0.0), (0.0, 250.0), (200.0, 200.0), (-150.0, 80.0), (400.0, -300.0),
        (50.0, 0.0), (600.0, 10.0), (-220.0, -260.0)]
# goal headings (deg) -- the optimal_strafe_yaw fallback; must not change the speed gain
# (only which perpendicular branch / which side the bot leans).
GOAL_YAWS = [0.0, 90.0, 180.0, -90.0, 45.0, 200.0]
SIDE_SIGNS = (+1, -1)


def _wishdir(yaw, fwd, side):
    """pmove_sim._air_move's horizontal wishdir from a view yaw + move keys (= test_optimal_aim)."""
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


class TestDaggerExpertAirOptimal(unittest.TestCase):
    def test_air_action_is_perpendicular_speed_optimal(self):
        for vx, vy in VELS:
            for gy in GOAL_YAWS:
                for sign in SIDE_SIGNS:
                    st = {"vx": vx, "vy": vy, "onground": False, "goal_dir_yaw": gy}
                    fwd, side, up, jump, yaw = EX.expert_action(st, side_sign=sign)
                    # the AIR action contract: fwd=0, |side|=MOVE_MAG, up=0, jump released
                    self.assertEqual(fwd, 0.0, "air fwd must be 0 (the over-press fix)")
                    self.assertEqual(abs(side), EX.MOVE_MAG, "air side must be full strafe")
                    self.assertEqual(up, 0.0)
                    self.assertEqual(jump, 0, "no jump while airborne (auto-hop is on land)")

                    wd = _wishdir(yaw, fwd, side)
                    s = math.hypot(vx, vy)
                    # (1) wishdir is PERPENDICULAR to the horizontal velocity
                    dot = wd[0] * vx + wd[1] * vy
                    self.assertLess(abs(dot), 1e-4 * max(1.0, s),
                                    msg="not perpendicular: v=(%s,%s) sign=%s yaw=%s dot=%s"
                                        % (vx, vy, sign, yaw, dot))
                    # (2) realized post-tick hspeed == perpendicular-optimal closed form
                    got = _post_hspeed(vx, vy, wd, fwd, side)
                    perp_opt = math.sqrt(s * s + 900.0 - dot * dot)  # == sqrt(s^2+900) here
                    self.assertAlmostEqual(got, perp_opt, places=3,
                                           msg="speed-gain mismatch: v=(%s,%s) sign=%s got=%s exp=%s"
                                               % (vx, vy, sign, got, perp_opt))
                    # (3) it is the SIM maximum over a fine yaw sweep (not just self-consistent)
                    best = max(_post_hspeed(vx, vy, _wishdir(i * 0.5, fwd, side), fwd, side)
                               for i in range(720))
                    self.assertGreaterEqual(got, best - 0.05,
                                            msg="not maximal: v=(%s,%s) got=%s best=%s"
                                                % (vx, vy, got, best))

    def test_ground_action_jumps_and_no_air_bulldoze(self):
        # on the ground the expert auto-hops; when ALREADY moving it does NOT press forward
        moving = {"vx": 300.0, "vy": 0.0, "onground": True, "goal_dir_yaw": 0.0}
        fwd, side, up, jump, yaw = EX.expert_action(moving)
        self.assertEqual(jump, EX.BUTTON_JUMP, "ground action must jump for sustain")
        self.assertEqual(fwd, 0.0, "moving on ground -> no forward (no bulldoze)")
        self.assertEqual(abs(side), EX.MOVE_MAG)
        # nearly stopped on the ground -> a launch push (forward) is allowed
        stopped = {"vx": 5.0, "vy": 0.0, "onground": True, "goal_dir_yaw": 0.0}
        fwd2, _, _, jump2, _ = EX.expert_action(stopped)
        self.assertEqual(jump2, EX.BUTTON_JUMP)
        self.assertEqual(fwd2, EX.MOVE_MAG, "stopped on ground -> forward to regain launch speed")

    def test_goal_heading_fallback_when_stopped(self):
        # |v_h| ~ 0 -> seam falls back to the goal heading (no defined wishdir to optimize)
        st = {"vx": 0.0, "vy": 0.0, "onground": False, "goal": (1000.0, 0.0), "origin": (0.0, 0.0)}
        _, _, _, _, yaw = EX.expert_action(st)
        self.assertAlmostEqual(yaw % 360.0, 0.0, places=3)  # goal due +x -> heading 0 deg
        st2 = {"vx": 0.0, "vy": 0.0, "onground": False, "goal": (0.0, 1000.0), "origin": (0.0, 0.0)}
        _, _, _, _, yaw2 = EX.expert_action(st2)
        self.assertAlmostEqual(yaw2 % 360.0, 90.0, places=3)  # goal due +y -> 90 deg


if __name__ == "__main__":
    unittest.main()
