"""ml/tests/test_eval_closedloop.py — tests for the CLOSED-LOOP G-MV believability eval.

Two layers, mirroring ml/tests/test_eval_believability.py:
  * DEPS-FREE: the pure-python glue in ml/eval_broad_closedloop.py — the move-head
    decode (sign3 inverse, MAG=400), the gmv-tick builder, the route/anti-stall metric,
    and (load-bearing) the gmv discrimination control: because scripts/gmv_believability
    is pure stdlib, the "known face-and-run path FAILS G-MV1 / human-like PASSES" proof
    runs FOR REAL on this box. These ALWAYS run with NO torch/numpy/duckdb.
  * TORCH+DUCKDB: the end-to-end run_eval is SKIPPED here (needs a real checkpoint +
    catalog + BSP on the GPU host); a smoke check asserts the module imports deps-free
    and run_eval exists.

The glue is factored OUT of the torch CLI precisely so it is importable and checkable
without the heavy deps — decode_move_heads / route_metrics / score_sequence_gmv are the
exact functions the pinnacle run calls.
"""
import importlib.util
import math
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ML = HERE.parent
REPO_ROOT = ML.parent
sys.path.insert(0, str(ML))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import eval_broad_closedloop as CL     # noqa: E402  (deps-free at import time)
import gmv_believability as GMV        # noqa: E402  (pure stdlib)

_HAVE_TORCH = importlib.util.find_spec("torch") is not None
_HAVE_DUCKDB = importlib.util.find_spec("duckdb") is not None


class TestMoveClassToMag(unittest.TestCase):
    """sign3 class -> usercmd magnitude (inverse of shard_contract.encode_sign3).
    The MAG MUST be 400 (the BROAD trainer's /400 move scale), NOT 320."""

    def test_class_mapping_uses_400(self):
        self.assertEqual(CL.MOVE_MAG, 400.0)
        self.assertEqual(CL.move_class_to_mag(2), +400.0)   # fwd/right/up
        self.assertEqual(CL.move_class_to_mag(0), -400.0)   # back/left/down
        self.assertEqual(CL.move_class_to_mag(1), 0.0)      # none

    def test_inverse_of_encode_sign3_sign(self):
        # encode_sign3(+x) -> 2, encode_sign3(-x) -> 0, encode_sign3(0) -> 1; the
        # magnitude inverse must restore the SIGN encode_sign3 read.
        import broad_bc.shard_contract as SC
        self.assertEqual(SC.encode_sign3(0.7), 2)
        self.assertGreater(CL.move_class_to_mag(SC.encode_sign3(0.7)), 0)
        self.assertEqual(SC.encode_sign3(-0.7), 0)
        self.assertLess(CL.move_class_to_mag(SC.encode_sign3(-0.7)), 0)
        self.assertEqual(SC.encode_sign3(0.0), 1)
        self.assertEqual(CL.move_class_to_mag(SC.encode_sign3(0.0)), 0.0)

    def test_custom_mag_override(self):
        self.assertEqual(CL.move_class_to_mag(2, mag=320.0), 320.0)


class TestDecodeMoveHeads(unittest.TestCase):
    def test_known_head_vector(self):
        # fwd=fwd(2) side=left(0) up=none(1) jump=pressed(1) attack=pressed(1)
        fwd, side, up, jump = CL.decode_move_heads([2, 0, 1, 1, 1])
        self.assertEqual(fwd, +400.0)
        self.assertEqual(side, -400.0)
        self.assertEqual(up, 0.0)
        self.assertEqual(jump, CL.BUTTON_JUMP)             # == 2

    def test_jump_not_pressed_is_zero_button(self):
        _, _, _, jump = CL.decode_move_heads([1, 1, 1, 0, 0])
        self.assertEqual(jump, 0)

    def test_attack_is_ignored_for_control(self):
        # attack head class does NOT alter the returned (fwd,side,up,jump) tuple —
        # fire stays stock; decode returns exactly 4 control values.
        out_fire = CL.decode_move_heads([2, 2, 2, 0, 1])
        out_nofire = CL.decode_move_heads([2, 2, 2, 0, 0])
        self.assertEqual(out_fire, out_nofire)
        self.assertEqual(len(out_fire), 4)

    def test_full_forward_right_up(self):
        fwd, side, up, jump = CL.decode_move_heads([2, 2, 2, 1, 0])
        self.assertEqual((fwd, side, up), (+400.0, +400.0, +400.0))
        self.assertEqual(jump, CL.BUTTON_JUMP)


class TestGmvTickFromState(unittest.TestCase):
    def test_builds_expected_keys(self):
        t = CL.gmv_tick_from_state(
            origin=(100.0, 200.0, 24.0), vel=(300.0, 400.0, 0.0),
            onground=False, yaw=42.0, side_mag=400.0, msec=13.0)
        self.assertAlmostEqual(t["vx"], 300.0)
        self.assertAlmostEqual(t["vy"], 400.0)
        self.assertAlmostEqual(t["yaw"], 42.0)
        self.assertEqual(t["onground"], False)
        self.assertAlmostEqual(t["hspeed"], 500.0)         # hypot(300,400)
        self.assertAlmostEqual(t["sidemove"], 400.0)
        self.assertAlmostEqual(t["msec"], 13.0)
        # origin carried (for route metrics) but ignored by the gates
        self.assertAlmostEqual(t["_ox"], 100.0)
        self.assertAlmostEqual(t["_oy"], 200.0)

    def test_tick_is_consumable_by_battery(self):
        # the built tick must normalize cleanly through the gmv battery path.
        t = CL.gmv_tick_from_state((0, 0, 0), (200.0, 0.0, 0.0), False, 30.0, 400.0)
        norm = GMV.normalize_tick(t)
        self.assertAlmostEqual(norm["hspeed"], 200.0)
        self.assertEqual(norm["onground"], False)


class TestRouteMetrics(unittest.TestCase):
    def test_moving_path_length_and_no_stall(self):
        # a straight path stepping +10 qu in x each of 10 ticks -> path length 90,
        # all ticks moving (speed 300) -> not stalled.
        origins = [(float(i * 10), 0.0) for i in range(10)]
        speeds = [300.0] * 10
        msecs = [13.0] * 10
        m = CL.route_metrics(origins, speeds, msecs)
        self.assertAlmostEqual(m["path_len_qu"], 90.0)
        self.assertEqual(m["n_ticks"], 10)
        self.assertFalse(m["stalled"])
        self.assertEqual(m["longest_stall_ticks"], 0)
        self.assertAlmostEqual(m["displacement_qu"], 90.0)

    def test_near_zero_speed_window_flags_stall(self):
        # ~0.5 s of near-zero speed at 13ms/tick needs ~39 ticks; use 60 to be safe.
        n = 60
        origins = [(0.0, 0.0)] * n          # wedged in place
        speeds = [5.0] * n                  # below the 40 qu/s stall floor
        msecs = [13.0] * n
        m = CL.route_metrics(origins, speeds, msecs)
        self.assertTrue(m["stalled"])
        self.assertGreaterEqual(m["longest_stall_s"], 0.5)
        self.assertAlmostEqual(m["path_len_qu"], 0.0)

    def test_brief_stall_does_not_flag(self):
        # 10 near-zero ticks (~0.13 s) < 0.5 s window -> not flagged, even bracketed
        # by motion.
        origins = ([(float(i * 10), 0.0) for i in range(5)]
                   + [(50.0, 0.0)] * 10
                   + [(float(50 + i * 10), 0.0) for i in range(1, 6)])
        speeds = [300.0] * 5 + [5.0] * 10 + [300.0] * 5
        msecs = [13.0] * 20
        m = CL.route_metrics(origins, speeds, msecs)
        self.assertFalse(m["stalled"])
        self.assertLess(m["longest_stall_s"], 0.5)
        self.assertEqual(m["longest_stall_ticks"], 10)

    def test_empty_is_safe(self):
        m = CL.route_metrics([], [], [])
        self.assertEqual(m["path_len_qu"], 0.0)
        self.assertEqual(m["n_ticks"], 0)
        self.assertFalse(m["stalled"])


class TestAggregateRouteMetrics(unittest.TestCase):
    """FIX A: aggregating PER-SEGMENT route dicts must NOT inject a teleport distance
    at segment boundaries, the way running route_metrics on POOLED (concatenated)
    origins from different segments does."""

    def _segment(self, x0, n=10, step=10.0):
        # a straight segment starting at x0, stepping +step qu in x for n origins.
        origins = [(float(x0 + i * step), 0.0) for i in range(n)]
        speeds = [300.0] * n
        msecs = [13.0] * n
        return origins, speeds, msecs

    def test_aggregate_excludes_cross_segment_teleport(self):
        # Segment A near x=0, Segment B FAR away near x=100000 (the bot was re-seeded to
        # a new start state -> a huge map jump between segments). Each segment's OWN path
        # length is 9*10 = 90. Two segments -> the HONEST corpus path length is 180.
        segA = self._segment(0.0)
        segB = self._segment(100000.0)
        routeA = CL.route_metrics(*segA)
        routeB = CL.route_metrics(*segB)
        self.assertAlmostEqual(routeA["path_len_qu"], 90.0)
        self.assertAlmostEqual(routeB["path_len_qu"], 90.0)

        agg = CL.aggregate_route_metrics([routeA, routeB])
        self.assertAlmostEqual(agg["path_len_qu"], 180.0)     # 90 + 90, no teleport
        self.assertEqual(agg["n_ticks"], 20)
        self.assertEqual(agg["n_segments"], 2)

        # the BUGGY path: pool both segments' origins and run route_metrics ONCE. The
        # A->B boundary (x=90 -> x=100000) adds a ~99910 qu teleport into path_len.
        pooled_origins = segA[0] + segB[0]
        pooled_speeds = segA[1] + segB[1]
        pooled_msecs = segA[2] + segB[2]
        pooled = CL.route_metrics(pooled_origins, pooled_speeds, pooled_msecs)
        self.assertGreater(pooled["path_len_qu"], 99000.0)    # teleport contamination
        # the aggregate must be the clean 180, NOT the ~100090 the pooled path reports.
        self.assertLess(agg["path_len_qu"], pooled["path_len_qu"] - 99000.0)

    def test_displacement_is_per_segment_sum_not_endpoint_span(self):
        # pooled displacement would be |last - first| across the teleport (~100090);
        # the aggregate sums per-segment displacements (90 + 90 = 180).
        routeA = CL.route_metrics(*self._segment(0.0))
        routeB = CL.route_metrics(*self._segment(100000.0))
        agg = CL.aggregate_route_metrics([routeA, routeB])
        self.assertAlmostEqual(agg["displacement_qu"], 180.0)

    def test_longest_stall_is_max_not_summed(self):
        # one segment stalls (60 near-zero ticks ~0.78s), one segment moves cleanly.
        n = 60
        stalled_route = CL.route_metrics([(0.0, 0.0)] * n, [5.0] * n, [13.0] * n)
        moving_route = CL.route_metrics(*self._segment(0.0))
        self.assertTrue(stalled_route["stalled"])
        self.assertFalse(moving_route["stalled"])
        agg = CL.aggregate_route_metrics([stalled_route, moving_route])
        # stalled flag propagates (any segment stalled), longest stall is the MAX
        # single-segment stall (not a sum across segments).
        self.assertTrue(agg["stalled"])
        self.assertAlmostEqual(agg["longest_stall_s"], stalled_route["longest_stall_s"])
        self.assertEqual(agg["longest_stall_ticks"], stalled_route["longest_stall_ticks"])

    def test_mean_speed_is_duration_weighted(self):
        # segment A: 10 ticks @ 300; segment B: 30 ticks @ 100. Duration-weighted mean
        # equals the pooled per-tick mean here (uniform 13ms): (10*300 + 30*100)/40 = 150.
        routeA = CL.route_metrics([(float(i), 0.0) for i in range(10)], [300.0] * 10, [13.0] * 10)
        routeB = CL.route_metrics([(float(i), 0.0) for i in range(30)], [100.0] * 30, [13.0] * 30)
        agg = CL.aggregate_route_metrics([routeA, routeB])
        self.assertAlmostEqual(agg["mean_speed_qu_per_s"], 150.0, places=2)
        self.assertEqual(agg["n_ticks"], 40)

    def test_single_segment_matches_route_metrics(self):
        # one segment in -> the aggregate path/ticks/duration must equal that segment's
        # own route_metrics (no double counting, no boundary).
        route = CL.route_metrics(*self._segment(0.0))
        agg = CL.aggregate_route_metrics([route])
        self.assertAlmostEqual(agg["path_len_qu"], route["path_len_qu"])
        self.assertEqual(agg["n_ticks"], route["n_ticks"])
        self.assertAlmostEqual(agg["duration_s"], route["duration_s"])
        self.assertAlmostEqual(agg["displacement_qu"], route["displacement_qu"])

    def test_empty_is_safe(self):
        agg = CL.aggregate_route_metrics([])
        self.assertEqual(agg["path_len_qu"], 0.0)
        self.assertEqual(agg["n_ticks"], 0)
        self.assertEqual(agg["n_segments"], 0)
        self.assertFalse(agg["stalled"])


class TestMv3BoundaryFix(unittest.TestCase):
    """FIX (mirrors d4bcff3 for the OPEN-loop eval): G-MV3 strafe cadence on a POOLED
    multi-segment tick stream counts one spurious L<->R flip at each segment boundary.
    The boundary-safe aggregate sums PER-SEGMENT flips, so a 2-segment pooled cadence
    equals the per-segment flip SUM, not the boundary-inflated count."""

    def _seg_ticks(self, *, first_sign, last_sign, n=80, msec=13.0):
        """A segment of n airborne nonzero-strafe ticks. The FIRST tick strafes
        `first_sign` and the LAST strafes `last_sign`; the interior alternates so the
        segment carries a known, measurable in-segment flip count. Velocity/yaw are
        set human-ish (irrelevant to G-MV3, which keys only on sidemove)."""
        import math
        ticks = []
        for i in range(n):
            if i == 0:
                s = first_sign
            elif i == n - 1:
                s = last_sign
            else:
                s = 1 if (i % 2 == 0) else -1
            heading = i * 5.0
            rad = math.radians(heading)
            vx, vy = 360.0 * math.cos(rad), 360.0 * math.sin(rad)
            ticks.append(CL.gmv_tick_from_state(
                (0.0, 0.0, 0.0), (vx, vy, 0.0), onground=False,
                yaw=heading + 40.0, side_mag=400.0 * s, msec=msec))
        return ticks

    def test_pooled_stream_overcounts_by_one_flip_per_boundary(self):
        # segment A ends on +1 (right); segment B starts on -1 (left). On the POOLED
        # stream that A_last(+1) -> B_first(-1) transition is counted as a real flip,
        # but it spans the segment boundary and is NOT a real L<->R reversal.
        segA = self._seg_ticks(first_sign=+1, last_sign=+1)
        segB = self._seg_ticks(first_sign=-1, last_sign=-1)
        gA = GMV.gate_mv3(GMV.normalize_sequence(segA))
        gB = GMV.gate_mv3(GMV.normalize_sequence(segB))
        pooled = GMV.gate_mv3(GMV.normalize_sequence(segA + segB))
        flips_sum = gA["statistic"]["flips"] + gB["statistic"]["flips"]
        # the pooled flip count is exactly ONE more than the per-segment sum (the
        # single spurious boundary flip).
        self.assertEqual(pooled["statistic"]["flips"], flips_sum + 1)

    def test_aggregate_equals_per_segment_flip_sum(self):
        segA = self._seg_ticks(first_sign=+1, last_sign=+1)
        segB = self._seg_ticks(first_sign=-1, last_sign=-1)
        gA = GMV.gate_mv3(GMV.normalize_sequence(segA))
        gB = GMV.gate_mv3(GMV.normalize_sequence(segB))
        agg = CL.aggregate_mv3_from_segments([gA, gB])
        # boundary-safe: summed flips, NOT the pooled (boundary-inflated) count.
        self.assertEqual(agg["statistic"]["flips"],
                         gA["statistic"]["flips"] + gB["statistic"]["flips"])
        self.assertEqual(agg["statistic"]["eligible_ticks"],
                         gA["statistic"]["eligible_ticks"] + gB["statistic"]["eligible_ticks"])
        self.assertTrue(agg["statistic"]["boundary_safe"])
        # and strictly fewer than the pooled count (the spurious boundary flip is gone).
        pooled = GMV.gate_mv3(GMV.normalize_sequence(segA + segB))
        self.assertEqual(agg["statistic"]["flips"], pooled["statistic"]["flips"] - 1)

    def test_overwrite_pooled_mv3_replaces_boundary_gate(self):
        # build the pooled battery (boundary-contaminated G-MV3), then overwrite with
        # the per-segment sum. G-MV1 and the believable flag must be untouched.
        segA = self._seg_ticks(first_sign=+1, last_sign=+1)
        segB = self._seg_ticks(first_sign=-1, last_sign=-1)
        battery = CL.score_sequence_gmv(segA + segB)
        pooled_flips = battery["gates"]["G-MV3"]["statistic"]["flips"]
        gA = GMV.gate_mv3(GMV.normalize_sequence(segA))
        gB = GMV.gate_mv3(GMV.normalize_sequence(segB))
        believable_before = battery["believable"]
        mv1_before = battery["gates"]["G-MV1"]["passed"]
        CL.overwrite_pooled_mv3(battery, [gA, gB])
        self.assertEqual(battery["gates"]["G-MV3"]["statistic"]["flips"], pooled_flips - 1)
        self.assertTrue(battery["gates"]["G-MV3"]["statistic"]["boundary_safe"])
        # G-MV1 (the HARD gate) and believable are NOT altered by the G-MV3 fix.
        self.assertEqual(battery["believable"], believable_before)
        self.assertEqual(battery["gates"]["G-MV1"]["passed"], mv1_before)

    def test_aggregate_includes_insufficient_segment_flips_and_time(self):
        # P1 FIX: a per-segment-insufficient segment (too few NONZERO-strafe ticks to
        # judge on its own) now EXPOSES its cadence ingredients (statistic is NOT None)
        # and CONTRIBUTES its flips + eligible_ticks + active_s to the pooled sums — its
        # sidemove-carrying wall time is part of the cadence DENOMINATOR and must not be
        # dropped. One real (sufficient) segment + one thin segment: pooled flips =
        # both segments' flip sum, pooled eligible/active = both segments' sums.
        good = self._seg_ticks(first_sign=+1, last_sign=-1)            # 80 ticks, sufficient
        g_good = GMV.gate_mv3(GMV.normalize_sequence(good))
        thin = self._seg_ticks(first_sign=+1, last_sign=+1, n=4)      # < min_strafe_ticks
        g_thin = GMV.gate_mv3(GMV.normalize_sequence(thin))
        # post-fix: thin segment exposes its ingredients (additive, not None).
        self.assertIsNotNone(g_thin["statistic"])
        self.assertEqual(g_thin["statistic"]["eligible_ticks"], 4)
        self.assertTrue(g_thin["statistic"].get("insufficient"))
        agg = CL.aggregate_mv3_from_segments([g_good, g_thin])
        # flips pool (thin holds one sign the whole time -> 0 flips, so the sum is the
        # good segment's flips), and the thin segment's eligible_ticks + active_s ARE
        # added to the pooled denominator (not skipped).
        self.assertEqual(agg["statistic"]["flips"],
                         g_good["statistic"]["flips"] + g_thin["statistic"]["flips"])
        self.assertEqual(agg["statistic"]["eligible_ticks"],
                         g_good["statistic"]["eligible_ticks"] + g_thin["statistic"]["eligible_ticks"])
        self.assertAlmostEqual(agg["statistic"]["active_s"],
                               g_good["statistic"]["active_s"] + g_thin["statistic"]["active_s"],
                               places=3)
        # 80 nonzero (good) + 0..4 (thin) >= the 50 floor -> pooled is JUDGED (not None).
        self.assertIsNotNone(agg["passed"])

    def test_aggregate_all_insufficient_pools_to_insufficient_not_dropped(self):
        # P1 FIX: many individually-thin segments must NOT be silently dropped. Two
        # 4-tick segments -> pooled NONZERO base (8) is still < the 50 floor, so the
        # pooled gate is INSUFFICIENT (passed None) — but it is a real returned gate
        # carrying the pooled ingredients, NOT None, and NOT a spurious pass.
        thin = self._seg_ticks(first_sign=+1, last_sign=+1, n=4)
        g_thin = GMV.gate_mv3(GMV.normalize_sequence(thin))
        agg = CL.aggregate_mv3_from_segments([g_thin, g_thin])
        self.assertIsNotNone(agg)
        self.assertIsNone(agg["passed"])                  # pooled nonzero < floor
        self.assertEqual(agg["status"], "insufficient")
        self.assertEqual(agg["statistic"]["eligible_ticks"], 8)   # 4 + 4, summed
        # overwrite then REPLACES the pooled gate with the boundary-safe insufficient
        # gate (still insufficient, so all_gates_passed stays False / fail-closed).
        battery = CL.score_sequence_gmv(thin + thin)
        CL.overwrite_pooled_mv3(battery, [g_thin, g_thin])
        self.assertIsNone(battery["gates"]["G-MV3"]["passed"])
        self.assertFalse(battery["all_gates_passed"])

    def test_aggregate_returns_none_only_when_no_sidemove_at_all(self):
        # The ONLY None case left: a segment that carried no sidemove-bearing tick at
        # all (e.g. all-MVD frames, sidemove None) -> no cadence base -> None, so the
        # caller keeps the pooled gate's own verdict.
        no_side = [GMV.normalize_tick({"vx": 300.0, "vy": 0.0, "yaw": 0.0,
                                       "onground": False, "msec": 13.0})  # sidemove absent
                   for _ in range(80)]
        g_none = GMV.gate_mv3(no_side)
        # no sidemove-carrying ticks -> eligible_ticks 0 in the statistic.
        self.assertEqual(g_none["statistic"]["eligible_ticks"], 0)
        self.assertIsNone(CL.aggregate_mv3_from_segments([g_none, g_none]))

    def test_gate_mv3_exposes_eligible_ticks(self):
        # the shared gate must now expose eligible_ticks in its statistic (additive,
        # back-compat) so the aggregator can sum the per-segment denominator.
        seg = self._seg_ticks(first_sign=+1, last_sign=-1, n=80)
        g = GMV.gate_mv3(GMV.normalize_sequence(seg))
        self.assertIn("eligible_ticks", g["statistic"])
        self.assertEqual(g["statistic"]["eligible_ticks"], 80)

    def test_gate_mv3_insufficient_still_exposes_ingredients(self):
        # P1 FIX (the shared gate side): even when a segment is INSUFFICIENT (too few
        # nonzero-strafe ticks to judge), gate_mv3 must expose flips + eligible_ticks +
        # active_s in its statistic (NOT None) so the aggregator's pooled denominator
        # includes this segment's wall time. A long all-zero-sidemove segment is the
        # canonical case: it is insufficient (0 nonzero) yet carries a large active_s.
        zero = [GMV.normalize_tick({"vx": 300.0, "vy": 0.0, "yaw": 0.0,
                                    "onground": False, "msec": 13.0, "sidemove": 0.0})
                for _ in range(1000)]
        g = GMV.gate_mv3(zero)
        self.assertIsNone(g["passed"])                        # semantics unchanged
        self.assertEqual(g["status"], "insufficient")         # semantics unchanged
        self.assertIsNotNone(g["statistic"])                  # but ingredients exposed
        self.assertEqual(g["statistic"]["flips"], 0)
        self.assertEqual(g["statistic"]["eligible_ticks"], 1000)   # all carry sidemove
        self.assertAlmostEqual(g["statistic"]["active_s"], 13.0, places=3)
        self.assertEqual(g["n_strafe_ticks"], 0)              # 0 NONZERO-strafe ticks


class TestMv3InsufficientDenominatorFix(unittest.TestCase):
    """P1 (Codex BLOCK) regression: pooling a SHORT real-flip segment with a LONG
    zero-sidemove (per-segment-insufficient) segment must yield the LOW, TRUE pooled
    cadence — because the long segment's active-time stays in the cadence DENOMINATOR.
    Dropping the insufficient segment (the bug) strips that time base and INFLATES the
    pooled flips_per_min, which can flip the corrected G-MV3 verdict FAIL->PASS — the
    exact opposite of the boundary fix's de-biasing purpose.

    Codex repro: one 60-tick segment with 1 flip + one 1000-tick zero-sidemove segment.
      * BUGGY (drop insufficient seg)  -> active_s ~= 0.78s, flips/min ~= 76.92, PASS.
      * CORRECT (keep its active time) -> active_s ~= 13.78s, flips/min ~=  4.35, FAIL.
    """

    def _flip_segment(self, *, n_half=30, msec=13.0):
        """A SHORT segment of 2*n_half NONZERO-strafe ticks with EXACTLY ONE L<->R
        flip: hold +400 for n_half ticks, then -400 for n_half ticks. 60 ticks >= the
        50-nonzero floor, so this segment is SUFFICIENT on its own."""
        ticks = []
        for i in range(2 * n_half):
            s = +400.0 if i < n_half else -400.0
            ticks.append(GMV.normalize_tick({
                "vx": 320.0, "vy": 0.0, "yaw": 40.0, "onground": False,
                "msec": msec, "sidemove": s}))
        return ticks

    def _zero_segment(self, *, n=1000, msec=13.0):
        """A LONG segment of n sidemove==0.0 (active but non-strafing) ticks: it is
        per-segment INSUFFICIENT (0 nonzero-strafe ticks) but carries a large active_s
        (= n*msec) that is part of the pooled cadence denominator."""
        return [GMV.normalize_tick({
            "vx": 320.0, "vy": 0.0, "yaw": 40.0, "onground": False,
            "msec": msec, "sidemove": 0.0}) for _ in range(n)]

    def test_codex_repro_pooled_cadence_is_low_and_fails(self):
        flip_seg = self._flip_segment()        # 60 ticks, 1 flip, sufficient
        zero_seg = self._zero_segment()        # 1000 ticks, 0 nonzero, insufficient
        g_flip = GMV.gate_mv3(flip_seg)
        g_zero = GMV.gate_mv3(zero_seg)
        # sanity on the inputs
        self.assertEqual(g_flip["statistic"]["flips"], 1)
        self.assertIsNotNone(g_flip["passed"])               # flip seg is sufficient
        self.assertIsNone(g_zero["passed"])                  # zero seg is insufficient
        self.assertEqual(g_zero["statistic"]["eligible_ticks"], 1000)

        agg = CL.aggregate_mv3_from_segments([g_flip, g_zero])
        # pooled flips = 1 (only the flip segment), pooled active_s = 0.78 + 13.0.
        self.assertEqual(agg["statistic"]["flips"], 1)
        self.assertEqual(agg["statistic"]["eligible_ticks"], 1060)   # 60 + 1000
        self.assertAlmostEqual(agg["statistic"]["active_s"], 13.78, places=3)
        # the TRUE pooled cadence: 1 / 13.78 * 60 ~= 4.354 flips/min -> below the
        # 8/min floor -> FAIL (NOT the ~76.9 the buggy drop would report).
        self.assertAlmostEqual(agg["statistic"]["flips_per_min"], 4.354, places=2)
        self.assertIs(agg["passed"], False)
        self.assertEqual(agg["status"], "fail")

    def test_dropping_insufficient_segment_would_wrongly_inflate_to_pass(self):
        # Demonstrates the BUG the fix prevents: if the zero (insufficient) segment's
        # active time is OMITTED from the denominator (the old `if not st: continue`
        # behavior), the SAME flip count is divided by only the flip segment's 0.78s,
        # giving ~76.9 flips/min — inside the band -> a spurious PASS. The fix keeps
        # the denominator, so the real verdict is FAIL. (Cross-check the two rates.)
        flip_seg = self._flip_segment()
        zero_seg = self._zero_segment()
        g_flip = GMV.gate_mv3(flip_seg)
        g_zero = GMV.gate_mv3(zero_seg)

        # CORRECT aggregate (both segments' active time) -> FAIL at ~4.35/min.
        correct = CL.aggregate_mv3_from_segments([g_flip, g_zero])
        # BUGGY denominator (flip segment ONLY) -> what cadence_from_flip_sums yields
        # if the zero segment's active_s/eligible were dropped, using ONLY the flip
        # segment's pooled nonzero base so it is still "sufficient".
        buggy = CL.cadence_from_flip_sums(
            flips=g_flip["statistic"]["flips"],
            eligible_ticks=g_flip["statistic"]["eligible_ticks"],
            active_s=g_flip["statistic"]["active_s"],
            nonzero_strafe_ticks=g_flip["n_strafe_ticks"])
        self.assertAlmostEqual(buggy["statistic"]["flips_per_min"], 76.923, places=2)
        self.assertIs(buggy["passed"], True)                 # the spurious PASS

        # the fix flips the verdict back to the correct FAIL, and the corrected rate is
        # strictly far below the inflated one.
        self.assertIs(correct["passed"], False)
        self.assertLess(correct["statistic"]["flips_per_min"],
                        buggy["statistic"]["flips_per_min"] - 50.0)

    def test_overwrite_uses_corrected_low_cadence(self):
        # End-to-end through overwrite_pooled_mv3: the pooled battery's G-MV3 gate is
        # replaced by the boundary-safe + denominator-correct aggregate, so the final
        # gate FAILS (low pooled cadence) and all_gates_passed is fail-closed.
        flip_seg = self._flip_segment()
        zero_seg = self._zero_segment()
        battery = CL.score_sequence_gmv(flip_seg + zero_seg)
        g_flip = GMV.gate_mv3(flip_seg)
        g_zero = GMV.gate_mv3(zero_seg)
        CL.overwrite_pooled_mv3(battery, [g_flip, g_zero])
        gate = battery["gates"]["G-MV3"]
        self.assertIs(gate["passed"], False)
        self.assertAlmostEqual(gate["statistic"]["flips_per_min"], 4.354, places=2)
        self.assertTrue(gate["statistic"]["boundary_safe"])
        self.assertFalse(battery["all_gates_passed"])


class TestGmvDiscriminationDepsFree(unittest.TestCase):
    """THE load-bearing control, run FOR REAL on this box (gmv is pure stdlib):
    a known face-and-run sequence FAILS the HARD G-MV1, a human-like sequence PASSES.
    This is the proof the believability judge discriminates — without it, a bot
    'passing' is meaningless."""

    def test_face_and_run_fails_gmv1(self):
        face = GMV.synth_face_and_run(n=2000)
        battery = CL.score_sequence_gmv(face)
        self.assertIs(battery["gates"]["G-MV1"]["passed"], False)
        # believable is gated on G-MV1 -> must be False for face-and-run.
        self.assertIs(battery["believable"], False)

    def test_human_like_passes_gmv1(self):
        human = GMV.synth_human_like(n=2000)
        battery = CL.score_sequence_gmv(human)
        self.assertIs(battery["gates"]["G-MV1"]["passed"], True)
        self.assertIs(battery["believable"], True)

    def test_summary_reflects_discrimination(self):
        face = CL.summarize_gmv(CL.score_sequence_gmv(GMV.synth_face_and_run(n=2000)))
        human = CL.summarize_gmv(CL.score_sequence_gmv(GMV.synth_human_like(n=2000)))
        self.assertIs(face["believable_G_MV1"], False)
        self.assertIs(human["believable_G_MV1"], True)
        self.assertIs(face["G_MV1"]["passed"], False)
        self.assertIs(human["G_MV1"]["passed"], True)


class TestClosedLoopTicksThroughBattery(unittest.TestCase):
    """Build a closed-loop-style gmv-tick stream from a synthetic sim-state stream via
    gmv_tick_from_state and run it through the battery end-to-end (deps-free): a held
    large yaw-vs-velocity offset (human-like) PASSES G-MV1; yaw == velocity FAILS. This
    exercises the tick builder all the way into the gate the pinnacle run uses."""

    def _stream(self, *, face_and_run):
        import math
        ticks = []
        heading = 0.0
        for i in range(1500):
            heading += 7.0                     # rotate so velocity direction varies
            spd = 360.0
            rad = math.radians(heading)
            vx = spd * math.cos(rad)
            vy = spd * math.sin(rad)
            vel_ang = math.degrees(math.atan2(vy, vx))
            if face_and_run:
                yaw = vel_ang                  # locked to velocity -> collapse
            else:
                # large oscillating offset off velocity, like a human air-strafe.
                phase = 1.0 if (i // 30) % 2 == 0 else -1.0
                yaw = vel_ang + 40.0 * phase
            side_mag = 400.0 if (i // 30) % 2 == 0 else -400.0
            ticks.append(CL.gmv_tick_from_state(
                (0.0, 0.0, 0.0), (vx, vy, 0.0), onground=False,
                yaw=yaw, side_mag=side_mag, msec=13.0))
        return ticks

    def test_built_ticks_human_offset_passes_gmv1(self):
        battery = CL.score_sequence_gmv(self._stream(face_and_run=False))
        self.assertIs(battery["gates"]["G-MV1"]["passed"], True)

    def test_built_ticks_face_and_run_fails_gmv1(self):
        battery = CL.score_sequence_gmv(self._stream(face_and_run=True))
        self.assertIs(battery["gates"]["G-MV1"]["passed"], False)


class TestSelectStartSegments(unittest.TestCase):
    """select_start_segments is pure python over the loaded-episodes structure; verify
    it only returns windows with enough airborne-moving ticks for a gate_mv1 verdict."""

    def _episode(self, n, *, airborne_fast):
        ticks = []
        for i in range(n):
            ticks.append({
                "tick": i,
                "self": {"ox": float(i), "oy": 0.0, "oz": 0.0,
                         "vx": 600.0 if airborne_fast else 0.0, "vy": 0.0, "vz": 0.0,
                         "yaw": 0.0, "pitch": 0.0,
                         "hspeed": 600.0 if airborne_fast else 0.0,
                         "onground": (not airborne_fast)},
                "others": [], "act": None,
            })
        return ticks

    def test_picks_qualifying_episode_only(self):
        episodes = {
            1: self._episode(60, airborne_fast=False),   # grounded/slow -> 0 eligible
            2: self._episode(600, airborne_fast=True),   # airborne+fast -> qualifies
        }
        segs = CL.select_start_segments(episodes, horizon=300, n_segments=5,
                                        min_airborne_moving=200)
        eids = {eid for (eid, _s, _seg) in segs}
        self.assertIn(2, eids)
        self.assertNotIn(1, eids)               # too short / not enough airborne-moving
        # the qualifying segment is horizon+1 long (post-frame headroom).
        for (_eid, _s, seg) in segs:
            self.assertEqual(len(seg), 301)

    def test_too_short_episode_skipped(self):
        episodes = {1: self._episode(100, airborne_fast=True)}
        segs = CL.select_start_segments(episodes, horizon=300, n_segments=5)
        self.assertEqual(segs, [])


class TestRecordedUsercmdControl(unittest.TestCase):
    """_recorded_usercmd is the positive-control decode: raw human magnitudes + jump."""

    def test_reads_raw_magnitudes_and_jump_bit(self):
        fwd, side, up, jump = CL._recorded_usercmd(
            {"forwardmove": 400, "sidemove": -320, "upmove": 0, "buttons": 2})
        self.assertEqual(fwd, 400.0)
        self.assertEqual(side, -320.0)
        self.assertEqual(up, 0.0)
        self.assertEqual(jump, CL.BUTTON_JUMP)

    def test_attack_button_does_not_set_jump(self):
        _, _, _, jump = CL._recorded_usercmd({"buttons": 1})   # attack only
        self.assertEqual(jump, 0)

    def test_none_action_is_idle(self):
        self.assertEqual(CL._recorded_usercmd(None), (0.0, 0.0, 0.0, 0))


@unittest.skipUnless(_HAVE_TORCH and _HAVE_DUCKDB,
                     "run_eval needs torch + duckdb + a BSP (pinnacle GPU host)")
class TestRunEvalGated(unittest.TestCase):
    """End-to-end is exercised on pinnacle with a real checkpoint + catalog + BSP. Here
    we only assert the entrypoint exists; the full run is the orchestrator's job."""

    def test_run_eval_callable(self):
        self.assertTrue(callable(CL.run_eval))


class TestModuleImportsDepsFree(unittest.TestCase):
    """Guard: the module + its glue import on bare stdlib (no torch/numpy/duckdb)."""

    def test_glue_importable_and_run_eval_present(self):
        for fn in ("move_class_to_mag", "decode_move_heads", "gmv_tick_from_state",
                   "route_metrics", "aggregate_route_metrics", "score_sequence_gmv",
                   "select_start_segments", "cadence_from_flip_sums",
                   "aggregate_mv3_from_segments", "overwrite_pooled_mv3"):
            self.assertTrue(callable(getattr(CL, fn)), fn)
        self.assertTrue(hasattr(CL, "run_eval"))


# =============================================================================
# TRAIN/INFERENCE PARITY for the turn-direction features (the important test).
#
# The yaw_rate signal needs the PREVIOUS tick's view yaw, so the offline build and EVERY
# inference call-site must compute + inject it identically. This asserts that, for one
# shared (yaw, prev_yaw, dt, sim-state) fixture, the SELF feature vector is byte-identical
# whether built via:
#   * the TRAINING path's self_state construction (mirrors build_features._load_episode_ticks
#     exactly — see the pinned comment; build_features itself can't be imported here because
#     it pulls duckdb at module load, so the per-tick dict is reproduced and kept in lockstep),
#   * the INFERENCE path's CL._self_state_from_sim (the real closed-loop / dry-route builder).
# Both feed the SAME AO.yaw_rate_degps and the SAME AO.encode_observation, so a divergence
# (different dt convention, different prev-yaw seeding, a dropped key) fails here.
# =============================================================================
from features import agent_observation as AO   # noqa: E402  (pure stdlib)

# the per-map stats the encoder needs (incl. the yaw_rate zscore key). Mirrors the
# template/test_agent_observation fixture shape.
_PARITY_STATS = {
    "per_map": {
        "dm3": {
            "pos_x": {"method": "minmax", "min": -984.0, "max": 2048.0, "clip": [-984.0, 2048.0]},
            "pos_y": {"method": "minmax", "min": -960.0, "max": 1136.0, "clip": [-960.0, 1136.0]},
            "pos_z": {"method": "minmax", "min": -416.0, "max": 496.0, "clip": [-416.0, 496.0]},
            "vel_x": {"method": "zscore", "mean": 0.0, "std": 310.0, "clip": [-2500.0, 2500.0]},
            "vel_y": {"method": "zscore", "mean": 0.0, "std": 310.0, "clip": [-2500.0, 2500.0]},
            "vel_z": {"method": "zscore", "mean": 0.0, "std": 180.0, "clip": [-1000.0, 1000.0]},
            "hspeed": {"method": "robust", "median": 320.0, "iqr": 210.0, "clip": [0.0, 2500.0]},
            "yaw_rate": {"method": "zscore", "mean": 0.0, "std": 220.0, "clip": [-1500.0, 1500.0]},
        }
    }
}


class _FakeSimState:
    """pmove_sim.PlayerState stand-in for CL._self_state_from_sim: just the .origin /
    .velocity / .onground attributes the builder reads."""
    def __init__(self, origin, velocity, onground):
        self.origin = list(origin)
        self.velocity = list(velocity)
        self.onground = onground


class TestTurnDirectionTrainInferenceParity(unittest.TestCase):
    # ONE shared kinematic fixture (qu / qu/s / deg) used to drive BOTH paths.
    OX, OY, OZ = 1499.0, -176.0, -78.0
    VX, VY, VZ = 300.0, 120.0, -40.0
    YAW, PITCH = 33.0, 7.0
    PREV_YAW = 12.0
    DT_S = 0.013
    ONGROUND = False

    def _yaw_rate(self):
        # the SINGLE shared helper both paths call (byte-identical for identical inputs).
        return AO.yaw_rate_degps(self.YAW, self.PREV_YAW, self.DT_S)

    def _training_self_vec(self):
        """SELF vector via the TRAINING path. self_state mirrors build_features.
        _load_episode_ticks EXACTLY (keep in lockstep): the kinematic keys + yaw_rate from
        AO.yaw_rate_degps(yaw, prev_yaw, dt). health/armor/team_id are None here so they
        encode as 0 — isolating the comparison to the kinematic + turn-direction channels
        (the inference builder omits those resource keys; absent and None both encode 0)."""
        self_state = {
            "ox": self.OX, "oy": self.OY, "oz": self.OZ,
            "vx": self.VX, "vy": self.VY, "vz": self.VZ,
            "yaw": self.YAW, "pitch": self.PITCH,
            "hspeed": math.hypot(self.VX, self.VY),
            "onground": self.ONGROUND,
            "health": None, "armor": None,
            "yaw_rate": self._yaw_rate(),
            "team_id": None,
        }
        return AO.encode_observation(self_state, [], _PARITY_STATS, "dm3", 7)["self"]

    def _inference_self_vec(self):
        """SELF vector via the INFERENCE path: the REAL CL._self_state_from_sim with the
        yaw_rate the rollout loop injects (AO.yaw_rate_degps on the replayed view yaw +
        previous yaw + this tick's dt). Same encoder, same stats."""
        st = _FakeSimState((self.OX, self.OY, self.OZ),
                           (self.VX, self.VY, self.VZ), self.ONGROUND)
        self_state = CL._self_state_from_sim(st, self.YAW, self.PITCH,
                                             yaw_rate=self._yaw_rate())
        return AO.encode_observation(self_state, [], _PARITY_STATS, "dm3", 7)["self"]

    def test_self_vectors_are_byte_identical(self):
        train_vec = self._training_self_vec()
        infer_vec = self._inference_self_vec()
        self.assertEqual(len(train_vec), AO.SELF_DIM)
        self.assertEqual(len(infer_vec), AO.SELF_DIM)
        self.assertEqual(train_vec, infer_vec)        # exact equality (no float tolerance)

    def test_yaw_rate_channel_nonzero_and_shared(self):
        # the channel the fix adds is actually populated (not a silent 0) AND matches in
        # both paths — proving the previous-yaw value reached the obs identically.
        i = AO.SELF_FIELDS.index("yaw_rate_z")
        self.assertNotAlmostEqual(self._training_self_vec()[i], 0.0)
        self.assertEqual(self._training_self_vec()[i], self._inference_self_vec()[i])

    def test_inference_builder_carries_yaw_rate_key(self):
        # _self_state_from_sim must surface yaw_rate so encode_observation can read it.
        st = _FakeSimState((0.0, 0.0, 0.0), (300.0, 0.0, 0.0), False)
        ss = CL._self_state_from_sim(st, 33.0, 7.0, yaw_rate=812.5)
        self.assertEqual(ss["yaw_rate"], 812.5)
        # default (no yaw_rate passed) is 0.0, NOT a missing key — so the first-tick / no-prev
        # case is an explicit 0 rather than relying on encode's absent-key fallback.
        ss0 = CL._self_state_from_sim(st, 33.0, 7.0)
        self.assertEqual(ss0["yaw_rate"], 0.0)

    def test_first_tick_parity_rate_zero(self):
        # the build's first tick (prev None) and a rollout's first tick (prev_yaw seeded to
        # the same yaw so delta 0) BOTH yield yaw_rate 0 -> identical self vectors.
        i = AO.SELF_FIELDS.index("yaw_rate_z")
        build_first = AO.yaw_rate_degps(self.YAW, None, self.DT_S)               # build first tick
        rollout_first = AO.yaw_rate_degps(self.YAW, self.YAW, self.DT_S)         # rollout tick 0
        self.assertEqual(build_first, 0.0)
        self.assertEqual(rollout_first, 0.0)
        st = _FakeSimState((self.OX, self.OY, self.OZ),
                           (self.VX, self.VY, self.VZ), self.ONGROUND)
        v_build = AO.encode_observation(
            {"ox": self.OX, "oy": self.OY, "oz": self.OZ, "vx": self.VX, "vy": self.VY,
             "vz": self.VZ, "yaw": self.YAW, "pitch": self.PITCH,
             "hspeed": math.hypot(self.VX, self.VY), "onground": self.ONGROUND,
             "health": None, "armor": None, "yaw_rate": build_first, "team_id": None},
            [], _PARITY_STATS, "dm3", 7)["self"]
        v_roll = AO.encode_observation(
            CL._self_state_from_sim(st, self.YAW, self.PITCH, yaw_rate=rollout_first),
            [], _PARITY_STATS, "dm3", 7)["self"]
        self.assertEqual(v_build, v_roll)
        self.assertEqual(v_build[i], 0.0)


# =============================================================================
# v5 SEQUENCE-HISTORY TRAIN/INFERENCE PARITY (the #1 correctness risk of the redesign).
#
# The policy now consumes a FLAT last-SELF_HISTORY-tick SELF history. Training builds it
# per window-tick (build_features inner loop, reproduced here in lockstep — build_features
# pulls duckdb at module load so it can't be imported deps-free); inference builds it from
# a rolling deque(maxlen=H) reset at rollout start. BOTH call the SAME shared
# AO.assemble_self_history over the SAME per-tick SELF vectors, so the flat history MUST be
# byte-identical at every tick. This asserts exactly that over a synthetic trajectory,
# including the left-pad-repeat-first window-start ticks and the sliding-window late ticks.
# A divergence (different pad rule, wrong order, off-by-one deque seeding, a second copy of
# the assembly) fails here.
# =============================================================================
from collections import deque                  # noqa: E402


class TestSelfHistoryTrainInferenceParity(unittest.TestCase):
    H = AO.SELF_HISTORY

    def _trajectory(self, n):
        """A synthetic per-tick (sim-state, yaw, pitch) trajectory. Distinct per tick so a
        mis-ordered/mis-padded history would show. Mirrors the closed-loop rollout's state
        feed (a moving player whose velocity + view evolve each tick)."""
        traj = []
        for t in range(n):
            ox, oy, oz = 100.0 + 13.0 * t, -50.0 + 5.0 * t, -78.0
            vx, vy, vz = 300.0 + 2.0 * t, 120.0 - 1.5 * t, 0.0
            yaw = 30.0 + 1.7 * t
            pitch = 3.0 + 0.1 * t
            traj.append((ox, oy, oz, vx, vy, vz, yaw, pitch))
        return traj

    def _self_vec_at(self, tick, prev_yaw):
        """ONE per-tick SELF vector via the INFERENCE builder (CL._self_state_from_sim +
        AO.encode_observation) — the same construction both rollouts use. prev_yaw drives
        the shared turn-direction signal (None/first-tick convention via yaw_rate_degps)."""
        ox, oy, oz, vx, vy, vz, yaw, pitch = tick
        yaw_rate = AO.yaw_rate_degps(yaw, prev_yaw, 0.013)
        st = _FakeSimState((ox, oy, oz), (vx, vy, vz), False)
        self_state = CL._self_state_from_sim(st, yaw, pitch, yaw_rate=yaw_rate)
        return AO.encode_observation(self_state, [], _PARITY_STATS, "dm3", 7)["self"]

    def _build_path_histories(self, traj):
        """TRAIN path: reproduce build_features.build_observation_shard's inner loop — for a
        window over `traj`, accumulate per-tick SELF into window_selves and assemble each
        tick's flat history from window_selves[:j+1] via the SHARED helper. The build seeds
        the per-episode prev_yaw across ticks (None on the first), so within one window tick
        j uses tick j-1's yaw as prev (and j=0 uses None)."""
        hist = []
        window_selves = []
        prev_yaw = None
        for tk in traj:
            sv = self._self_vec_at(tk, prev_yaw)
            window_selves.append(sv)
            hist.append(AO.assemble_self_history(window_selves, self.H))
            prev_yaw = tk[6]                       # this tick's yaw -> next tick's prev
        return hist

    def _inference_path_histories(self, traj):
        """INFERENCE path: the EXACT rolling-deque idiom the closed-loop / dry-route rollout
        loops use — deque(maxlen=H) reset at start, append this tick's SELF, assemble the
        flat history via the SHARED helper. prev_yaw is seeded to None on tick 0 here so the
        first-tick turn-direction signal matches the build (the real rollouts seed prev_yaw
        to frame-0 yaw, which makes the first delta 0 — the SAME value as None, asserted by
        test_first_tick_parity_rate_zero)."""
        hist = []
        dq = deque(maxlen=self.H)
        prev_yaw = None
        for tk in traj:
            sv = self._self_vec_at(tk, prev_yaw)
            dq.append(sv)
            hist.append(AO.assemble_self_history(dq, self.H))
            prev_yaw = tk[6]
        return hist

    def test_self_history_train_vs_inference_byte_identical(self):
        # 25 ticks > H, so the first H-1 ticks exercise the left-pad-repeat-first window
        # start AND the later ticks exercise the full sliding window — the whole range.
        traj = self._trajectory(25)
        build_hist = self._build_path_histories(traj)
        infer_hist = self._inference_path_histories(traj)
        self.assertEqual(len(build_hist), len(infer_hist))
        for j, (b, i) in enumerate(zip(build_hist, infer_hist)):
            self.assertEqual(len(b), self.H * AO.SELF_DIM)
            self.assertEqual(b, i, msg=f"history diverged at tick {j} (train vs inference)")

    def test_history_newest_block_is_current_single_tick_self(self):
        # the newest SELF_DIM block of the flat history is EXACTLY the current single-tick
        # SELF (so nothing the v3 single-tick policy saw is lost — only context is added).
        traj = self._trajectory(20)
        build_hist = self._build_path_histories(traj)
        prev_yaw = None
        for j, tk in enumerate(traj):
            cur = self._self_vec_at(tk, prev_yaw)
            self.assertEqual(build_hist[j][-AO.SELF_DIM:], cur)
            prev_yaw = tk[6]

    def test_window_start_left_pads_by_repeating_first_tick(self):
        # at the window start (tick 0), with only 1 SELF available, the history is that
        # SELF repeated H times (the left-pad-repeat-first rule, on the REAL encoder output).
        traj = self._trajectory(1)
        h0 = self._build_path_histories(traj)[0]
        cur = self._self_vec_at(traj[0], None)
        self.assertEqual(h0, cur * self.H)
        # and a 3-tick window left-pads the earliest tick (H-3) times then the 3 real ones.
        traj3 = self._trajectory(3)
        h2 = self._build_path_histories(traj3)[2]           # the last tick's history
        prev = None
        svs = []
        for tk in traj3:
            svs.append(self._self_vec_at(tk, prev)); prev = tk[6]
        expected = [svs[0]] * (self.H - 3) + svs
        self.assertEqual(h2, [x for v in expected for x in v])


if __name__ == "__main__":
    unittest.main()
