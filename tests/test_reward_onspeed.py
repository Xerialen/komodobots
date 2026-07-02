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


class TestSustainShaping(unittest.TestCase):
    """D7 (plans/d7-sustain-shaping.md §5): potential-based sustain-speed shaping — every
    pre-registered guard has its enforcing test here. F = γΦ(e′)−Φ(e) over the speed-EMA
    ladder; default w_sustain=0 = OFF."""

    @staticmethod
    def _run_speeds(speeds, cfg, mutate=None):
        """Thread a post-frame hspeed sequence through compute_step_reward (speeds[0] seeds
        the carry) and return the f_sustain series."""
        carry = mk_carry(prev_hspeed=speeds[0])
        fs = []
        for i, s in enumerate(speeds[1:]):
            cur = mk_cur(vx=float(s))
            if mutate:
                mutate(cur, carry, i)
            _, info, carry = R.compute_step_reward(cur, carry, ROUTE, cfg)
            fs.append(info["f_sustain"])
        return fs

    @staticmethod
    def _ema_replay(speeds, alpha):
        e = float(speeds[0])
        for s in speeds[1:]:
            e = e + alpha * (float(s) - e)
        return e

    @staticmethod
    def _run_episode(speeds, cfg):
        """Thread a FULL EPISODE with the env's clock contract: ticks_left counts down to 0
        and the final tick carries done=True (as PmoveEnv.step provides them)."""
        carry = mk_carry(prev_hspeed=speeds[0])
        n = len(speeds) - 1
        fs = []
        for i, s in enumerate(speeds[1:]):
            cur = mk_cur(vx=float(s))
            cur["ticks_left"] = n - (i + 1)
            cur["done"] = (i + 1) == n
            _, info, carry = R.compute_step_reward(cur, carry, ROUTE, cfg)
            fs.append(info["f_sustain"])
        return fs

    def test_sustain_potential_monotone_capped(self):
        cap = 1000.0
        self.assertEqual(R.phi_ladder(0.0, cap), 0.0)
        vals = [R.phi_ladder(h, cap) for h in range(0, 1401, 50)]
        self.assertEqual(vals, sorted(vals), "Phi must be monotone non-decreasing")
        self.assertEqual(R.phi_ladder(cap, cap), R.phi_ladder(1400.0, cap),
                         "Phi must be flat above the cap")
        for h in (50.0, 150.0, 320.0, 600.0):
            eps = 1e-4   # closed form == integral of 1/phi: check dPhi/dh numerically
            num = (R.phi_ladder(h + eps, 1e9) - R.phi_ladder(h - eps, 1e9)) / (2 * eps)
            self.assertAlmostEqual(num, 1.0 / R.phi(h), places=6)
        for h in (30.0, 100.0, 320.0, 600.0):
            # one physics-perfect pump tick raises Phi by ~1 FIRST-ORDER only (1.02 at
            # h=100) — never assert exact 1 (audit note).
            dphi = R.phi_ladder(h + R.phi(h), 1e9) - R.phi_ladder(h, 1e9)
            self.assertGreaterEqual(dphi, 1.0)
            self.assertLessEqual(dphi, 1.16)

    def test_sustain_telescoping_exact(self):
        # gamma-weighted sum of F telescopes EXACTLY to gamma^T*Phi(e_T) - Phi(e_0) on an
        # arbitrary trajectory (gains, decays, a hard stop) — the potential-based property
        # that guarantees the term cannot manufacture net income (the r_cad-trap guard).
        cfg = mk_cfg(w_sustain=0.7)
        g, cap = cfg["sustain_gamma"], cfg["sustain_cap"]
        speeds = [300.0, 310.0, 305.0, 330.0, 350.0, 340.0, 360.0, 200.0, 0.0, 120.0]
        fs = self._run_speeds(speeds, cfg)
        total = sum((g ** t) * f for t, f in enumerate(fs))
        e_t = self._ema_replay(speeds, cfg["sustain_ema"])
        expect = (g ** len(fs)) * R.phi_ladder(e_t, cap) - R.phi_ladder(speeds[0], cap)
        self.assertAlmostEqual(total, expect, places=8)

    def test_sustain_steady_bhop_sawtooth_no_phantom_income(self):
        # THE regression for the clipped-raw-hspeed design rejected at implementation: bhop's
        # routine 1-tick friction bleed (-16.6 qu/s at 320) + gradual air regain, cycled. A
        # per-tick clip below that sawtooth turns the term into ~+8.9 PHANTOM income per hop
        # at CONSTANT average speed. The EMA form must (a) keep per-tick F nearly flat across
        # the sawtooth, (b) net NEGATIVE (drag only, no income), (c) telescope exactly.
        cfg = mk_cfg(w_sustain=1.0)
        g, cap = cfg["sustain_gamma"], cfg["sustain_cap"]
        drop, ticks_up = 16.6, 11
        cycle = [320.0 - drop + (drop / ticks_up) * k for k in range(ticks_up + 1)]
        speeds = [320.0] + cycle * 20
        fs = self._run_speeds(speeds, cfg)
        self.assertLess(max(fs) - min(fs), 1.0,
                        "the EMA must absorb the friction sawtooth (raw-hspeed spread ~13)")
        self.assertLess(sum(fs), 0.0, "steady speed must never earn net sustain income")
        total = sum((g ** t) * f for t, f in enumerate(fs))
        e_t = self._ema_replay(speeds, cfg["sustain_ema"])
        expect = (g ** len(fs)) * R.phi_ladder(e_t, cap) - R.phi_ladder(speeds[0], cap)
        self.assertAlmostEqual(total, expect, places=8)

    def test_sustain_decay_charged_gain_credited(self):
        cfg = mk_cfg()
        g = cfg["sustain_gamma"]
        # sustained decay 320 -> 150: charged as it happens, gamma-weighted total well below 0
        decay = [320.0 - (170.0 / 60.0) * k for k in range(61)]
        fs = self._run_speeds(decay, cfg)
        self.assertLess(sum((g ** t) * f for t, f in enumerate(fs)), -60.0)
        self.assertLess(fs[5], 0.0, "decay must be charged while it happens, not deferred")
        # climb 150 -> 320 then hold: the climb is net-credited; holding pays only the small
        # invariance drag -(1-gamma)*Phi(e) (~-1.16 at 320), never a fresh charge/credit.
        climb = [150.0 + (170.0 / 60.0) * k for k in range(61)] + [320.0] * 80
        fs2 = self._run_speeds(climb, cfg)
        self.assertGreater(sum(fs2[:60]), 5.0)
        self.assertGreater(fs2[-1], -1.3)
        self.assertLess(fs2[-1], 0.0)

    def test_sustain_default_off_parity(self):
        # w_sustain=0 (the DEFAULT): the reward equals the weighted sum of the other terms
        # exactly — the D7 term contributes nothing — while f_sustain stays observable.
        cfg = mk_cfg()
        self.assertEqual(cfg["w_sustain"], 0.0, "D7 ships OFF by default")
        cases = [mk_cur(vx=300.0, perp_frac=0.9),
                 mk_cur(vx=400.0, onground=True, fwd_am=2),
                 mk_cur(vx=250.0, blocked=R.BLOCKED_OTHER),
                 mk_cur(vx=0.0, yaw_delta_deg=15.0)]
        for cur in cases:
            carry = mk_carry(prev_hspeed=280.0, ap_rate=0.5)
            reward, info, _ = R.compute_step_reward(cur, dict(carry), ROUTE, cfg)
            expect = (cfg["w_vel"] * info["r_vel"] + cfg["w_prog"] * info["r_prog"]
                      + cfg["w_phi"] * info["r_phi"] + cfg["w_strafe"] * info["r_strafe"]
                      + cfg["w_cad"] * info["r_cad"]
                      - cfg["w_press"] * info["r_press"]
                      - cfg["w_collide"] * info["p_collide"]
                      - cfg["w_time"] - cfg["w_hack"] * info["p_hack"])
            self.assertAlmostEqual(reward, expect, places=12)
            self.assertIn("f_sustain", info)
            # the same tick with the term live must move the reward (the lever is real)
            reward_on, _, _ = R.compute_step_reward(cur, dict(carry), ROUTE,
                                                    mk_cfg(w_sustain=0.5))
            self.assertNotAlmostEqual(reward, reward_on, places=12)

    def test_sustain_gamma_mirrors_trainer(self):
        # Exact invariance needs shaping-gamma == the trainer's GAE gamma. Lock BOTH the
        # def-site default AND that every call site passes no explicit gamma (else a later
        # --gamma knob silently breaks the mirror with this test green). utf-8 read: the
        # trainer source contains non-ASCII; a Windows cp1252 default read would die.
        import re
        src = (Path(__file__).resolve().parent.parent / "ml" / "rl_onspeed.py").read_text(
            encoding="utf-8")
        m = re.search(r"def compute_gae\([^)]*gamma=([0-9.]+)", src)
        self.assertIsNotNone(m, "compute_gae def-site with a gamma default must exist")
        self.assertEqual(float(m.group(1)), R.DEFAULT_WEIGHTS["sustain_gamma"])
        calls = [ln for ln in src.splitlines()
                 if "compute_gae(" in ln and "def compute_gae" not in ln]
        self.assertGreaterEqual(len(calls), 1)
        for ln in calls:
            self.assertNotIn("gamma", ln.split("compute_gae(", 1)[1],
                             "call sites must inherit the def-site gamma the mirror locks")

    def test_sustain_reads_only_speed(self):
        # Pre-registered ban: NEVER keyed to yaw-rate / hold-length / cadence. Permuting
        # those inputs must leave the f_sustain series bit-identical.
        cfg = mk_cfg(w_sustain=0.4)
        speeds = [300.0, 310.0, 250.0, 330.0, 200.0, 320.0]
        base = self._run_speeds(speeds, cfg)

        def spice(cur, carry, i):
            cur["yaw_delta_deg"] = 45.0 if i % 2 else -30.0
            cur["side_am_mag"] = 1 if i % 2 else -1
            carry["strafe_hold"] = 100 + i

        self.assertEqual(base, self._run_speeds(speeds, cfg, mutate=spice))

    def test_sustain_clip_is_sanity_net_only(self):
        # The clip must NEVER engage on honest dynamics within the cap (an engaging clip
        # re-opens the phantom-income hole on climb-crash cycles). The TRUE one-tick bound
        # has TWO parts: gamma*(max delta-Phi) + (1-gamma)*Phi(cap) — the drag term is NOT
        # negligible (delta audit: dropping it put the bound at 44.5 while e=1000,h=0 gives
        # |F|=54.7, engaging a clip of 50 INSIDE the cap).
        cfg = mk_cfg(w_sustain=1.0)
        g, cap = cfg["sustain_gamma"], cfg["sustain_cap"]
        bound = (g * cfg["sustain_ema"] * cap / R.phi(cap)
                 + (1.0 - g) * R.phi_ladder(cap, cap))
        self.assertLess(bound, cfg["sustain_clip"])
        # the worst within-cap single tick (EMA at the cap, full stop) stays under the net
        worst = mk_carry(prev_hspeed=cap)
        _, info, _ = R.compute_step_reward(mk_cur(vx=0.0), worst, ROUTE, cfg)
        self.assertGreater(info["f_sustain"], -cfg["sustain_clip"])
        self.assertLess(info["f_sustain"], 0.0)
        fs = self._run_speeds([320.0] + [0.0] * 80, cfg)
        self.assertLess(fs[0], -3.0, "a wall-stop must be charged starting the same tick")
        self.assertGreater(fs[0], -8.0, "the EMA spreads the charge — no -115 spike")
        self.assertGreater(min(fs), -cfg["sustain_clip"], "the sanity net never engages")

    def test_sustain_terminal_residual_is_zero(self):
        # THE Codex #478 P1 case: two full episodes, same start EMA and same length — one
        # ENDS FAST (holds 320), one ENDS SLOW (decays to 120). Without terminal
        # cancellation the fast-ender banks gamma^T * Phi(e_T) extra shaping return; with
        # the time-varying ramp the gamma-weighted totals must be IDENTICAL and equal
        # -pot_0 exactly — end-of-episode speed earns NO objective bonus, w_sustain only
        # re-times credit within the episode.
        cfg = mk_cfg(w_sustain=1.0)
        g = cfg["sustain_gamma"]
        n = 120
        fast = [320.0] * (n + 1)
        slow = [320.0] * 41 + [max(120.0, 320.0 - 5.0 * k) for k in range(1, n - 39)]
        self.assertEqual(len(slow), n + 1)
        tot_fast = sum((g ** t) * f for t, f in enumerate(self._run_episode(fast, cfg)))
        tot_slow = sum((g ** t) * f for t, f in enumerate(self._run_episode(slow, cfg)))
        pot0 = R.phi_ladder(320.0, cfg["sustain_cap"])   # ramp(120 ticks left) = 1 at seed
        self.assertAlmostEqual(tot_fast, -pot0, places=8)
        self.assertAlmostEqual(tot_slow, -pot0, places=8)
        self.assertAlmostEqual(tot_fast, tot_slow, places=8)

    def test_sustain_rampdown_spreads_giveback_and_done_zeroes(self):
        cfg = mk_cfg(w_sustain=1.0)
        g = cfg["sustain_gamma"]
        # planned end: inside the ramp window the give-back is gradual — never a -115 spike
        fs = self._run_episode([320.0] * 121, cfg)
        ramp_zone = fs[-int(cfg["sustain_ramp_ticks"]):]
        self.assertLess(max(abs(x) for x in ramp_zone), 6.0,
                        "give-back must spread (~Phi/ramp_ticks + drag per tick)")
        # a segment SHORTER than the ramp window: pot seeds at the episode's own initial
        # ramp (no first-tick over-charge) and the total still telescopes to -pot_0
        n2 = 20
        fs2 = self._run_episode([320.0] * (n2 + 1), cfg)
        pot0 = (n2 / cfg["sustain_ramp_ticks"]) * R.phi_ladder(320.0, cfg["sustain_cap"])
        self.assertAlmostEqual(sum((g ** t) * f for t, f in enumerate(fs2)), -pot0,
                               places=8)
        self.assertLess(max(abs(x) for x in fs2), 6.0)
        # EARLY done (the out-of-bounds crash): the potential zeroes ON that tick; the
        # one-off give-back is attenuated by the sanity net (the documented exception) —
        # the residual can never survive the episode.
        carry = mk_carry(prev_hspeed=320.0)
        cur = mk_cur(vx=320.0)
        cur["ticks_left"], cur["done"] = 199, True
        _, info, nxt = R.compute_step_reward(cur, carry, ROUTE, cfg)
        self.assertEqual(nxt["sustain_pot"], 0.0)
        self.assertEqual(info["f_sustain"], -cfg["sustain_clip"])

    def test_validate_weight_keys(self):
        R.validate_weight_keys({})                       # empty = fine
        R.validate_weight_keys({"w_sustain": 0.3, "w_press": 2.5})
        with self.assertRaises(ValueError) as cm:
            R.validate_weight_keys({"w_sustian": 0.3})   # the typo that trains the control
        self.assertIn("w_sustian", str(cm.exception))
        self.assertIn("w_sustain", str(cm.exception), "the message must name valid keys")


if __name__ == "__main__":
    unittest.main()
