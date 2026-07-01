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

    def test_one_tick_start_probe_fails_no_completion(self):
        # THE Codex P1 adversarial case: a ONE-TICK probe at the route START — fast (1.5x), on the line,
        # clean air-strafe — trips on_route/faster_than_human/clean_mechanism but traverses ZERO route
        # arc. Without the completion criterion this false-certifies a non-completing local speed sample.
        traj = [tick(0.0, 0.0, 600.0, 0.0, onground=False, fwd_am=0)]
        g = G.grade_trajectory(traj, ROUTE)
        self.assertTrue(g["on_route"])
        self.assertTrue(g["faster_than_human"])
        self.assertTrue(g["clean_mechanism"])
        self.assertEqual(g["route_coverage_frac"], 0.0)
        self.assertFalse(g["completed_route"])
        self.assertFalse(g["passed"], "a one-tick start probe completes nothing -> must FAIL")

    def test_short_prefix_fails(self):
        # Fast, clean, on the line, but only traverses ~10% of the route arc (x=0..100 of 0..1000).
        xs = [0.0, 20.0, 40.0, 60.0, 80.0, 100.0]
        traj = [tick(x, 0.0, 600.0, 0.0, onground=False, fwd_am=0) for x in xs]
        g = G.grade_trajectory(traj, ROUTE)
        self.assertAlmostEqual(g["route_coverage_frac"], 0.1, places=3)
        self.assertTrue(g["on_route"])
        self.assertTrue(g["faster_than_human"])
        self.assertTrue(g["clean_mechanism"])
        self.assertFalse(g["completed_route"])
        self.assertFalse(g["passed"])

    def test_full_traversal_completes(self):
        # A genuine traversal: x=50..950 of the 0..1000 route ≈ 0.9 coverage, fast+clean+on-line -> PASS.
        xs = [float(x) for x in range(50, 951, 50)]
        traj = [tick(x, 0.0, 600.0, 0.0, onground=False, fwd_am=0) for x in xs]
        g = G.grade_trajectory(traj, ROUTE)
        self.assertAlmostEqual(g["route_coverage_frac"], 0.9, places=3)
        self.assertTrue(g["completed_route"])
        self.assertTrue(g["on_route"])
        self.assertTrue(g["faster_than_human"])
        self.assertTrue(g["clean_mechanism"])
        self.assertTrue(g["passed"])

    def test_coverage_metric_and_tunable(self):
        # route_coverage_frac is reported; min_coverage_frac is a tunable knob (#428). The x=100..900 run
        # is 0.8 coverage: clears the default 0.5 floor but fails a raised 0.95 floor (only completion moves).
        traj = [tick(x, 0.0, 600.0, 0.0, onground=False, fwd_am=0) for x in _XS]
        g = G.grade_trajectory(traj, ROUTE)
        self.assertAlmostEqual(g["route_coverage_frac"], 0.8, places=3)
        self.assertTrue(g["completed_route"])
        self.assertTrue(g["passed"])
        g2 = G.grade_trajectory(traj, ROUTE, cfg={"min_coverage_frac": 0.95})
        self.assertFalse(g2["completed_route"])
        self.assertFalse(g2["passed"])

    def test_empty_and_degenerate(self):
        self.assertFalse(G.grade_trajectory([], ROUTE)["passed"])
        self.assertEqual(G.grade_trajectory([], ROUTE)["n_ticks"], 0)
        one_pt = {"polyline": [(0.0, 0.0, 0.0)], "speeds": [400.0], "total_len": 0.0}
        self.assertFalse(G.grade_trajectory([tick(1, 0, 600, 0)], one_pt)["passed"])

    def test_determinism(self):
        traj = [tick(x, 0.0, 600.0, 0.0, onground=False, fwd_am=0) for x in _XS]
        self.assertEqual(G.grade_trajectory(traj, ROUTE), G.grade_trajectory(traj, ROUTE))

    # --- D1 wiring helpers: prep_traj_for_grade (guards iii/iv) + aggregate_route_grades ---

    def test_prep_rescues_superhuman_overrun(self):
        # Guard (iii), THE top misgrade risk. A faster bot reaches the route END and overruns past it
        # (x=0..1500 on a 0..1000 route). project_onto_polyline clamps the overrun ticks to the final
        # vertex, so their off-route distance = the overrun -> raw RMSE inflates -> on_route FALSE-FAILs
        # the SUPERHUMAN behaviour. prep truncates at the route end -> on_route holds.
        traj = [tick(float(x), 0.0, 600.0, 0.0, onground=False, fwd_am=0) for x in range(0, 1501, 100)]
        raw = G.grade_trajectory(traj, ROUTE)
        kept = G.prep_traj_for_grade(traj, ROUTE)
        prepped = G.grade_trajectory(kept, ROUTE)
        self.assertFalse(raw["on_route"], "overrun clamped to the endpoint inflates RMSE -> raw FALSE-FAILs")
        self.assertTrue(prepped["on_route"], "prep truncates at the route end -> on_route holds")
        self.assertLessEqual(max(t["ox"] for t in kept), 1000.0 + 1e-6)

    def test_prep_keeps_clean_in_route_run(self):
        # A run that stays within the route (x=100..900) is returned intact — prep is a no-op there.
        traj = [tick(x, 0.0, 600.0, 0.0, onground=False, fwd_am=0) for x in _XS]
        self.assertEqual(len(G.prep_traj_for_grade(traj, ROUTE)), len(traj))

    def test_prep_drops_zero_vref_ticks(self):
        # Guard (iv): a route whose human speed dips to ~0 over a stretch (a pause) -> route_speedup
        # gives ratio 0 there, which would drag the speedup median. prep drops those ticks.
        route = {"polyline": [(float(i * 100), 0.0, 0.0) for i in range(11)],
                 "speeds": [400.0] * 4 + [0.0, 0.0, 0.0] + [400.0] * 4, "total_len": 1000.0}
        traj = [tick(float(x), 0.0, 600.0, 0.0, onground=False, fwd_am=0) for x in range(0, 1001, 100)]
        kept = G.prep_traj_for_grade(traj, route)
        self.assertLess(len(kept), len(traj))
        self.assertNotIn(500.0, [t["ox"] for t in kept], "the paused (v_ref~0) tick is dropped")

    def test_none_fwd_am_is_safe(self):
        # The recorded positive control stores fwd_am=None (the human press-class is untracked in the
        # sim); grading must NOT crash on int(None) — None is treated as not-pressed.
        traj = [{"ox": x, "oy": 0.0, "oz": 0.0, "vx": 600.0, "vy": 0.0, "onground": False, "fwd_am": None}
                for x in _XS]
        g = G.grade_trajectory(traj, ROUTE)          # must not raise
        self.assertTrue(g["clean_mechanism"])        # None -> not pressed -> clean

    def test_aggregate_all_pass(self):
        g = G.grade_trajectory([tick(x, 0.0, 600.0, 0.0, onground=False, fwd_am=0)
                                for x in range(50, 951, 50)], ROUTE)
        self.assertTrue(g["passed"])
        agg = G.aggregate_route_grades([g, g, g])
        self.assertEqual(agg["n_segments"], 3)
        self.assertTrue(agg["all_passed"])
        self.assertEqual(agg["seg_passed_frac"], 1.0)

    def test_aggregate_mixed_and_empty(self):
        good = G.grade_trajectory([tick(x, 0.0, 600.0, 0.0, onground=False, fwd_am=0)
                                   for x in range(50, 951, 50)], ROUTE)
        bad = G.grade_trajectory([tick(x, 0.0, 150.0, 0.0, onground=False, fwd_am=2) for x in _XS], ROUTE)
        self.assertTrue(good["passed"])
        self.assertFalse(bad["passed"])
        agg = G.aggregate_route_grades([good, bad])
        self.assertEqual(agg["seg_passed_frac"], 0.5)
        self.assertFalse(agg["all_passed"])
        self.assertEqual(G.aggregate_route_grades([])["n_segments"], 0)
        self.assertFalse(G.aggregate_route_grades([])["all_passed"])


if __name__ == "__main__":
    unittest.main()
