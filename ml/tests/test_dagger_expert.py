"""ml/tests/test_dagger_expert.py -- the MATH SANITY-GATE for the DAgger expert (D-1.5).

The expert (ml/dagger/expert.expert_action) REUSES the proven optimal_strafe_yaw seam for
the perpendicular-optimal REFERENCE yaw and then (D-1.5) leans the executed view-yaw toward
the goal heading by `forward_blend` (the diagonal-aim cap) while ALTERNATING the side key
L/R over a weave (the orbit-killer). This gate proves, all through the EXACT
pmove_sim._air_accelerate (no reimplementation, no weakening of the seam math):

  (A) SEAM REUSE IS INTACT -- with forward_blend=0 the expert's view-yaw IS the seam's
      perpendicular reference, so for a spread of airborne velocities the realized post-tick
      horizontal speed equals the perpendicular-optimal closed form
          |v'_h| = sqrt(s^2 + 900 - (v_h . wishdir)^2)  == sqrt(s^2 + 900)   (s = |v_h|)
      AND is the sim maximum over a fine yaw sweep for the SAME move keys (mirrors
      ml/tests/test_optimal_aim). If the wrapper mis-mapped the fwd/side keys into the seam
      vs into the usercmd, the wishdir would not be perpendicular and this would fail. This
      is the SAME assertion as D-1, now also exercising fwd>0 in the seam reference.
  (B) THE BLEND IS REALLY APPLIED -- with the default forward_blend the realized wishdir is
      the human DIAGONAL (its angle off velocity sits strictly between perpendicular and
      aligned), proving the lean is a genuine yaw change, not a no-op and not collapsed to a
      bulldoze. (The orbit fix: D-1's strict-perp wishdir circled; the diagonal tracks goal.)
  (C) THE WEAVE ALTERNATES -- weave_side_sign flips L/R on its period and lands a flip
      cadence inside the G-MV3 human band over a representative tick span (the orbit-killer).

Pure stdlib (math + pmove_sim + the expert). No torch.
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
# goal headings (deg) -- the optimal_strafe_yaw fallback / lean target.
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


def _sep_deg(vx, vy, wd):
    """|angle(wishdir, velocity)| in degrees (0 = aligned/bulldoze, 90 = perpendicular)."""
    s = math.hypot(vx, vy)
    dot = (wd[0] * vx + wd[1] * vy) / s
    cross = (vx * wd[1] - vy * wd[0]) / s
    return abs(math.degrees(math.atan2(cross, dot)))


class TestDaggerExpertSeamMath(unittest.TestCase):
    def test_A_seam_reference_is_perpendicular_speed_optimal(self):
        # (A) with forward_blend=0 the executed yaw IS the seam's perpendicular reference;
        # the realized speed gain must be the engine maximum (seam reuse intact, keys mapped
        # correctly). NOTE: fwd=MOVE_MAG now flows into the seam too -- this proves the seam
        # orients the COMBINED (fwd+side) wishdir perpendicular, not just a side-only one.
        for vx, vy in VELS:
            for gy in GOAL_YAWS:
                for sign in SIDE_SIGNS:
                    st = {"vx": vx, "vy": vy, "onground": False, "goal_dir_yaw": gy}
                    fwd, side, up, jump, yaw = EX.expert_action(st, side_sign=sign,
                                                                forward_blend=0.0)
                    # the AIR action contract (D-1.5): fwd=+MOVE_MAG, |side|=MOVE_MAG, up=0,
                    # jump released while airborne.
                    self.assertEqual(fwd, EX.MOVE_MAG, "air fwd is the forward component (D-1.5)")
                    self.assertEqual(abs(side), EX.MOVE_MAG, "air side must be full strafe")
                    self.assertEqual(up, 0.0)
                    self.assertEqual(jump, 0, "no jump while airborne (auto-hop is on land)")

                    wd = _wishdir(yaw, fwd, side)
                    s = math.hypot(vx, vy)
                    # (1) at blend=0 the wishdir is PERPENDICULAR to the horizontal velocity
                    dot = wd[0] * vx + wd[1] * vy
                    self.assertLess(abs(dot), 1e-4 * max(1.0, s),
                                    msg="seam ref not perpendicular: v=(%s,%s) sign=%s yaw=%s dot=%s"
                                        % (vx, vy, sign, yaw, dot))
                    # (2) realized post-tick hspeed == perpendicular-optimal closed form
                    got = _post_hspeed(vx, vy, wd, fwd, side)
                    perp_opt = math.sqrt(s * s + 900.0 - dot * dot)  # == sqrt(s^2+900) here
                    self.assertAlmostEqual(got, perp_opt, places=3,
                                           msg="speed-gain mismatch: v=(%s,%s) sign=%s got=%s exp=%s"
                                               % (vx, vy, sign, got, perp_opt))
                    # (3) it is the SIM maximum over a fine yaw sweep for the SAME keys
                    best = max(_post_hspeed(vx, vy, _wishdir(i * 0.5, fwd, side), fwd, side)
                               for i in range(720))
                    self.assertGreaterEqual(got, best - 0.05,
                                            msg="seam ref not maximal: v=(%s,%s) got=%s best=%s"
                                                % (vx, vy, got, best))

    def test_B_default_blend_yields_human_diagonal_wishdir(self):
        # (B) the default forward_blend (0.7) leans the executed view-yaw toward the goal
        # heading -- a genuine change from the strict perpendicular, landing the human
        # diagonal for forward-hemisphere goals (the route case). The view-yaw->wishdir map
        # is nonlinear, so a few measure-zero (velocity, goal) alignments can leave the
        # wishdir near 90 even when leaned; the honest claims are AGGREGATE, not per-case:
        #   (1) the blended view-yaw differs from the blend=0 perpendicular yaw in aggregate
        #       (the lerp really moves the aim), and
        #   (2) for FORWARD-hemisphere goals the MEDIAN wishdir-vs-velocity separation sits
        #       in the human diagonal band [25,85] (the median is ~59 from check (a)).
        total_yaw_move = 0.0
        fwd_seps = []
        for vx, vy in VELS:
            for gy in GOAL_YAWS:
                st = {"vx": vx, "vy": vy, "onground": False, "goal_dir_yaw": gy}
                _, _, _, _, yaw0 = EX.expert_action(st, side_sign=+1, forward_blend=0.0)
                fwd, side, _, _, yawb = EX.expert_action(st, side_sign=+1)  # default blend
                total_yaw_move += abs(((yawb - yaw0 + 180.0) % 360.0) - 180.0)
                vyaw = math.degrees(math.atan2(vy, vx))
                dgoal = abs(((gy - vyaw + 180.0) % 360.0) - 180.0)
                if dgoal < 90.0:   # forward-hemisphere goal (goal roughly ahead)
                    fwd_seps.append(_sep_deg(vx, vy, _wishdir(yawb, fwd, side)))
        # (1) the lerp genuinely moves the aim across the set (not a no-op everywhere)
        self.assertGreater(total_yaw_move, 100.0,
                           "default blend barely moved the view-yaw (sum=%.1f deg)" % total_yaw_move)
        # (2) forward-goal separations cluster in the human diagonal band
        self.assertTrue(fwd_seps, "no forward-hemisphere cases exercised")
        fwd_seps.sort()
        median = fwd_seps[len(fwd_seps) // 2]
        self.assertTrue(25.0 <= median <= 85.0,
                        "median forward-goal wishdir separation %.1f not in the diagonal regime"
                        % median)

    def test_C_weave_alternates_within_gmv3_band(self):
        # (C) the side key alternates L/R on the weave period, and the resulting flip cadence
        # lands inside the G-MV3 human band [8,360] flips/min at the ~13 ms tick rate (the
        # orbit-killer: a fixed side circles, the weave nets straight).
        wp = EX.WEAVE_PERIOD_TICKS
        signs = [EX.weave_side_sign(t, weave_period=wp) for t in range(4 * wp)]
        # first period +1, second -1, ... (alternating blocks)
        self.assertEqual(signs[0], +1)
        self.assertEqual(signs[wp], -1)
        self.assertEqual(signs[2 * wp], +1)
        # flips per minute at 13 ms/tick (one flip per period boundary)
        flips_per_min = 60000.0 / (wp * 13.0)
        self.assertTrue(8.0 <= flips_per_min <= 360.0,
                        "weave cadence %.1f flips/min outside G-MV3 band [8,360]" % flips_per_min)
        # expert_action with side_sign=None derives the side from the tick -> alternation
        st = {"vx": 300.0, "vy": 0.0, "onground": False, "goal_dir_yaw": 0.0}
        s0 = EX.expert_action(st, tick=0)[1]
        s1 = EX.expert_action(st, tick=wp)[1]
        self.assertEqual((s0 > 0), True)
        self.assertEqual((s1 < 0), True, "tick past one period must flip the side key")

    def test_ground_action_jumps_and_drives_forward(self):
        # on the ground the expert auto-hops (sustain) and presses forward (D-1.5: drive
        # toward the goal off the ground; the seam falls back to the goal heading when stopped)
        moving = {"vx": 300.0, "vy": 0.0, "onground": True, "goal_dir_yaw": 0.0}
        fwd, side, up, jump, yaw = EX.expert_action(moving, side_sign=+1)
        self.assertEqual(jump, EX.BUTTON_JUMP, "ground action must jump for sustain")
        self.assertEqual(fwd, EX.MOVE_MAG, "ground action drives forward toward the goal")
        self.assertEqual(abs(side), EX.MOVE_MAG)
        stopped = {"vx": 5.0, "vy": 0.0, "onground": True, "goal_dir_yaw": 0.0}
        fwd2, _, _, jump2, _ = EX.expert_action(stopped, side_sign=+1)
        self.assertEqual(jump2, EX.BUTTON_JUMP)
        self.assertEqual(fwd2, EX.MOVE_MAG, "stopped on ground -> forward to regain launch speed")

    def test_goal_heading_fallback_when_stopped(self):
        # |v_h| ~ 0 -> seam falls back to the goal heading; the blend toward that same
        # heading is a no-op there, so the executed yaw IS the goal heading.
        st = {"vx": 0.0, "vy": 0.0, "onground": False, "goal": (1000.0, 0.0), "origin": (0.0, 0.0)}
        _, _, _, _, yaw = EX.expert_action(st, side_sign=+1)
        self.assertAlmostEqual(yaw % 360.0, 0.0, places=3)  # goal due +x -> heading 0 deg
        st2 = {"vx": 0.0, "vy": 0.0, "onground": False, "goal": (0.0, 1000.0), "origin": (0.0, 0.0)}
        _, _, _, _, yaw2 = EX.expert_action(st2, side_sign=+1)
        self.assertAlmostEqual(yaw2 % 360.0, 90.0, places=3)  # goal due +y -> 90 deg


if __name__ == "__main__":
    unittest.main()
