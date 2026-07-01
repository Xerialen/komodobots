"""Gating stdlib tests for the #427 (T5.1) Phase-2 reward (`reward_onspeed.py`).

No torch/numpy — runs in the merge-gate floor (`python -m unittest discover -s tests`). Validates
the NEW docs/28 terms (Velocity+ uncap, Progress+ arc-length, Collision−, Time−), the anti-reward-hack
property (the docs/28 "vibrating in a corner for speed" loophole closed by route-projection), and that
the extracted reward is pure (same inputs → same outputs, no hidden state).
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "experiments" / "route_observatory"))

import reward_onspeed as R  # noqa: E402

# A straight human-reference route along +x, 0..1000 qu, cruising at 400 qu/s.
POLYLINE = [(float(i * 100), 0.0, 0.0) for i in range(11)]
SPEEDS = [400.0] * 11
TOTAL_LEN = 1000.0
ROUTE = {"polyline": POLYLINE, "speeds": SPEEDS, "total_len": TOTAL_LEN}


def mk_cfg(**over):
    cfg = dict(R.DEFAULT_WEIGHTS)
    cfg.update(over)
    return cfg


def mk_carry(**over):
    carry = {"prev_hspeed": 0.0, "prev_arc": 50.0,  # bot starts at arc 50 (origin (50,0,0))
             "prev_strafe_sign": 0, "strafe_hold": 0, "ap_rate": 0.40}
    carry.update(over)
    return carry


def mk_cur(**over):
    """A tick at (50,0,0); airborne by default so the air mechanism terms are active."""
    vx = over.pop("vx", 0.0)
    vy = over.pop("vy", 0.0)
    import math
    cur = {"hspeed": math.hypot(vx, vy), "vx": vx, "vy": vy, "onground": False,
           "ox": 50.0, "oy": 0.0, "oz": 0.0, "perp_frac": 0.0, "side_am_mag": 0,
           "fwd_am": 0, "yaw_delta_deg": 0.0, "msec": 13, "blocked": 0}
    cur.update(over)
    if "vx" in over or "vy" in over:
        cur["hspeed"] = math.hypot(cur["vx"], cur["vy"])
    return cur


class TestVelocityReward(unittest.TestCase):
    def test_monotone_increasing(self):
        ratios = [-3, -1, -0.5, 0.0, 0.5, 1.0, 1.5, 3.0, 10.0]
        vals = [R.velocity_reward(r) for r in ratios]
        self.assertEqual(vals, sorted(vals))

    def test_superhuman_beats_human(self):
        # The whole point of #427: faster-than-human is rewarded MORE, not capped/penalized.
        self.assertGreater(R.velocity_reward(1.5), R.velocity_reward(1.0))
        self.assertGreater(R.velocity_reward(2.0), R.velocity_reward(1.5))

    def test_continuous_and_unit_at_human(self):
        self.assertAlmostEqual(R.velocity_reward(1.0), 1.0, places=9)

    def test_bounded_both_ends(self):
        # Upper: asymptote 1+v_sat. Lower: floored at -1 (no unbounded-negative PPO outlier).
        self.assertLessEqual(R.velocity_reward(1e6), 1.0 + 1.5 + 1e-9)
        self.assertEqual(R.velocity_reward(-1e6), -1.0)

    def test_anti_hack_backward_or_perp_is_nonpositive(self):
        self.assertLessEqual(R.velocity_reward(0.0), 0.0)
        self.assertLessEqual(R.velocity_reward(-0.3), 0.0)


class TestProgressReward(unittest.TestCase):
    def test_forward_positive(self):
        self.assertGreater(R.progress_reward(100.0, 50.0), 0.0)

    def test_no_move_neutral(self):
        self.assertEqual(R.progress_reward(50.0, 50.0), 0.0)

    def test_backward_negative(self):
        self.assertLess(R.progress_reward(40.0, 50.0), 0.0)

    def test_clamped(self):
        self.assertEqual(R.progress_reward(1e6, 0.0), 1.0)
        self.assertEqual(R.progress_reward(0.0, 1e6), -1.0)


class TestCollisionPenalty(unittest.TestCase):
    def test_wall_penalized(self):
        self.assertEqual(R.collision_penalty(R.BLOCKED_STEP), 1.0)
        self.assertEqual(R.collision_penalty(R.BLOCKED_OTHER), 1.0)
        self.assertEqual(R.collision_penalty(R.BLOCKED_STEP | R.BLOCKED_FLOOR), 1.0)

    def test_floor_landing_not_penalized(self):
        self.assertEqual(R.collision_penalty(R.BLOCKED_FLOOR), 0.0)
        self.assertEqual(R.collision_penalty(0), 0.0)


class TestRouteSpeedup(unittest.TestCase):
    def test_along_route_positive(self):
        v_along, v_ref, ratio, arc = R.route_speedup(50, 0, 0, 600.0, 0.0, POLYLINE, SPEEDS, TOTAL_LEN)
        self.assertAlmostEqual(v_along, 600.0, places=6)
        self.assertAlmostEqual(v_ref, 400.0, places=6)
        self.assertAlmostEqual(ratio, 1.5, places=6)
        self.assertAlmostEqual(arc, 50.0, places=6)

    def test_backward_negative(self):
        v_along, _, ratio, _ = R.route_speedup(50, 0, 0, -400.0, 0.0, POLYLINE, SPEEDS, TOTAL_LEN)
        self.assertAlmostEqual(v_along, -400.0, places=6)
        self.assertAlmostEqual(ratio, -1.0, places=6)

    def test_perpendicular_is_zero_along(self):
        # Vibrating sideways at high speed → ZERO along-route → the speed-hack earns nothing.
        v_along, _, ratio, _ = R.route_speedup(50, 0, 0, 0.0, 900.0, POLYLINE, SPEEDS, TOTAL_LEN)
        self.assertAlmostEqual(v_along, 0.0, places=6)
        self.assertAlmostEqual(ratio, 0.0, places=6)

    def test_degenerate_route_none_arc(self):
        v_along, v_ref, ratio, arc = R.route_speedup(0, 0, 0, 100.0, 0.0, [(0, 0, 0)], [400.0], 0.0)
        self.assertIsNone(arc)


class TestComputeStepReward(unittest.TestCase):
    def test_superhuman_tick_beats_human_tick(self):
        # End-to-end: a 600 qu/s along-route tick out-rewards a 400 qu/s one (cap is gone).
        cfg, carry = mk_cfg(), mk_carry()
        r_human, _, _ = R.compute_step_reward(mk_cur(vx=400.0), carry, ROUTE, cfg)
        r_super, _, _ = R.compute_step_reward(mk_cur(vx=600.0), carry, ROUTE, cfg)
        self.assertGreater(r_super, r_human)

    def test_first_step_progress_neutral(self):
        # Bot still at arc 50 (== prev_arc) → no spurious progress reward.
        _, info, _ = R.compute_step_reward(mk_cur(vx=400.0), mk_carry(prev_arc=50.0), ROUTE, mk_cfg())
        self.assertAlmostEqual(info["r_prog"], 0.0, places=6)

    def test_time_penalty_always_applied(self):
        # A perfectly still bot (no positive terms) nets at least the time penalty negative.
        r, _, _ = R.compute_step_reward(mk_cur(vx=0.0, vy=0.0), mk_carry(), ROUTE, mk_cfg())
        self.assertLessEqual(r, -mk_cfg()["w_time"] + 1e-9)

    def test_corner_vibrate_reward_hack_is_net_negative(self):
        # The docs/28 loophole: spin/jitter in a corner for "speed". Route-projection zeroes r_vel,
        # collision + spin penalties pile on → strongly negative, far below a genuine along-route tick.
        cfg = mk_cfg()
        genuine, _, _ = R.compute_step_reward(mk_cur(vx=600.0), mk_carry(), ROUTE, cfg)
        vibrate, vinfo, _ = R.compute_step_reward(
            mk_cur(vx=0.5, vy=0.0, yaw_delta_deg=25.0, blocked=R.BLOCKED_STEP), mk_carry(), ROUTE, cfg)
        self.assertEqual(vinfo["p_hack"], 1.0)       # spin-in-place caught
        self.assertEqual(vinfo["p_collide"], 1.0)    # wall grind caught
        self.assertLess(vibrate, 0.0)
        self.assertLess(vibrate, genuine)

    def test_rcad_dropped_by_default(self):
        # With w_cad=0 (default), a cadence flip must not change the reward (the believability
        # rhythm is OFF); the r_cad metric is still emitted for observability.
        cfg = mk_cfg()
        # a flip: prev sign -1, now +1, held within the human window → r_cad would be +1 if weighted
        carry = mk_carry(prev_strafe_sign=-1, strafe_hold=100)
        r_off, info, _ = R.compute_step_reward(mk_cur(vx=400.0, side_am_mag=300), carry, ROUTE, cfg)
        r_on, _, _ = R.compute_step_reward(mk_cur(vx=400.0, side_am_mag=300), carry, ROUTE,
                                           mk_cfg(w_cad=1.0))
        self.assertEqual(info["r_cad"], 1.0)          # metric still computed
        self.assertAlmostEqual(r_on - r_off, 1.0, places=6)  # only the WEIGHT differs
        self.assertNotAlmostEqual(r_off, r_on)        # w_cad=0 path genuinely excludes it

    def test_pure_same_inputs_same_outputs(self):
        cfg = mk_cfg()
        cur, carry = mk_cur(vx=500.0), mk_carry()
        r1, i1, c1 = R.compute_step_reward(cur, carry, ROUTE, cfg)
        r2, i2, c2 = R.compute_step_reward(cur, carry, ROUTE, cfg)
        self.assertEqual(r1, r2)
        self.assertEqual(i1, i2)
        self.assertEqual(c1, c2)

    def test_carry_threads_prev_hspeed_and_arc(self):
        # next_carry must capture this tick's hspeed + arc so the next step's r_phi/r_prog are correct.
        _, _, nxt = R.compute_step_reward(mk_cur(vx=600.0), mk_carry(prev_arc=50.0), ROUTE, mk_cfg())
        self.assertAlmostEqual(nxt["prev_hspeed"], 600.0, places=6)
        self.assertAlmostEqual(nxt["prev_arc"], 50.0, places=6)  # didn't move → arc unchanged


class TestGroundForwardBulldoze(unittest.TestCase):
    """#427-R2: the `+forward` hole. A sustained GROUND +forward at speed used to slip past the
    air-only press barrier (r_press≈0), so the forward-bulldoze ran free (ROUND-4 / R1). It is now
    penalized like an air press; low-speed ground acceleration stays free; the air path is unchanged."""

    def test_ground_forward_at_speed_now_penalized(self):
        # On ground, holding +forward, already fast (>band_lo*0.5≈126). carry ap_rate seeded at the
        # threshold so a single press tick crosses it. (Air-only code froze ap_rate on ground → 0.)
        cfg = mk_cfg()
        cur = mk_cur(vx=400.0, onground=True, fwd_am=2)
        _, info, nxt = R.compute_step_reward(cur, mk_carry(ap_rate=cfg["air_press_thresh"]), ROUTE, cfg)
        self.assertGreater(info["r_press"], 0.0)
        self.assertGreater(nxt["ap_rate"], cfg["air_press_thresh"])

    def test_low_speed_ground_accel_not_penalized(self):
        # Below the strafe-speed gate = legit early acceleration → must stay free (ap_rate decays).
        cfg = mk_cfg()
        cur = mk_cur(vx=50.0, onground=True, fwd_am=2)
        _, info, nxt = R.compute_step_reward(cur, mk_carry(ap_rate=cfg["air_press_thresh"]), ROUTE, cfg)
        self.assertEqual(info["r_press"], 0.0)
        self.assertLessEqual(nxt["ap_rate"], cfg["air_press_thresh"])

    def test_air_press_behavior_preserved(self):
        # Regression guard: the original air path is unchanged — an airborne +forward still accrues.
        cfg = mk_cfg()
        cur = mk_cur(vx=400.0, onground=False, fwd_am=2)
        _, _, nxt = R.compute_step_reward(cur, mk_carry(ap_rate=cfg["air_press_thresh"]), ROUTE, cfg)
        self.assertGreater(nxt["ap_rate"], cfg["air_press_thresh"])

    def test_no_forward_press_not_penalized(self):
        # Not pressing +forward (the bhop case) at speed on ground → no press accrual.
        cfg = mk_cfg()
        cur = mk_cur(vx=400.0, onground=True, fwd_am=0)
        _, info, nxt = R.compute_step_reward(cur, mk_carry(ap_rate=cfg["air_press_thresh"]), ROUTE, cfg)
        self.assertEqual(info["r_press"], 0.0)
        self.assertLess(nxt["ap_rate"], cfg["air_press_thresh"])


if __name__ == "__main__":
    unittest.main()
