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


def _summary(faster_frac, ratio=0.5, rmse=50.0, n=8, n_ref_invalid=0, n_ref_degenerate=0):
    """A minimal aggregate_route_grades-shaped summary for the rank_by_route_grade tests."""
    return {"n_segments": n, "seg_faster_frac": faster_frac, "median_speedup_ratio": ratio,
            "median_route_rmse_qu": rmse, "n_ref_invalid": n_ref_invalid,
            "n_ref_degenerate": n_ref_degenerate, "superhuman_claim": False}


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

    # --- #428: RELATIVE faster-than-human bar (beat the sim-human, cancel the sim-fidelity factor) ---

    def test_relative_gate_passes_beating_slow_sim_human(self):
        # THE #428 recalibration. A bot SLOWER than the raw human (ratio 0.625 < 1.0 -> the ABSOLUTE bar
        # fails) but FASTER than the sim-human control (0.49) PASSES the relative bar: the offline sim
        # only reproduces ~half the real speed, so "beat the sim-human" is the trustworthy in-sim verdict.
        traj = [tick(x, 0.0, 250.0, 0.0, onground=False, fwd_am=0) for x in _XS]
        absolute = G.grade_trajectory(traj, ROUTE)
        self.assertAlmostEqual(absolute["median_speedup_ratio"], 0.625, places=3)
        self.assertFalse(absolute["faster_than_human"], "0.625 < 1.0 -> absolute bar fails")
        self.assertEqual(absolute["faster_basis"], "absolute")
        rel = G.grade_trajectory(traj, ROUTE, human_ref_ratio=0.49)
        self.assertEqual(rel["faster_basis"], "relative")
        self.assertTrue(rel["faster_than_human"], "0.625 >= 0.49 sim-human -> relative bar passes")
        self.assertTrue(rel["faster_than_sim_human"])
        self.assertFalse(rel["superhuman_claim"], "relative verdict is never an absolute superhuman claim")
        self.assertTrue(rel["passed"])

    def test_relative_gate_still_fails_slow_hybrid(self):
        # The R5-style hybrid (slow 0.375 + airborne +forward) must FAIL even RELATIVE to the 0.49
        # sim-human -> the relative bar does NOT rescue a genuinely-slow / bulldoze run.
        traj = [tick(x, 0.0, 150.0, 0.0, onground=False, fwd_am=2) for x in _XS]
        rel = G.grade_trajectory(traj, ROUTE, human_ref_ratio=0.49)
        self.assertFalse(rel["faster_than_human"], "0.375 < 0.49 sim-human")
        self.assertFalse(rel["clean_mechanism"])
        self.assertFalse(rel["passed"])

    def test_degenerate_reference_not_a_pass(self):
        # MUST-FIX (auditor L1): if the sim-human control ~stalled on a segment (ref <= min_ref_ratio), a
        # fast bot must NOT auto-PASS the relative bar (bot >= ~0 is trivially true exactly where the
        # instrument is least trustworthy). It is REFUSED + tagged, not passed.
        fast = [tick(x, 0.0, 600.0, 0.0, onground=False, fwd_am=0) for x in _XS]   # ratio 1.5, clearly fast
        deg = G.grade_trajectory(fast, ROUTE, human_ref_ratio=0.0)
        self.assertEqual(deg["faster_basis"], "relative_ref_degenerate")
        self.assertFalse(deg["faster_than_human"], "degenerate reference is refused, not auto-passed")
        self.assertFalse(deg["passed"])
        ok = G.grade_trajectory(fast, ROUTE, human_ref_ratio=0.06)   # just above the floor -> real compare
        self.assertEqual(ok["faster_basis"], "relative")
        self.assertTrue(ok["faster_than_human"])

    def test_invalid_reference_not_a_pass(self):
        # Codex #471 P1: an off-route / incomplete sim-human control with a HEALTHY ratio (0.49, NOT
        # degenerate) must NOT license an on-route policy to pass relative to it. The caller flags the
        # reference invalid (control not on_route/completed) -> refuse, distinct from low-ratio degeneracy.
        fast_on_route = [tick(x, 0.0, 600.0, 0.0, onground=False, fwd_am=0) for x in _XS]
        bad = G.grade_trajectory(fast_on_route, ROUTE, human_ref_ratio=0.49, human_ref_valid=False)
        self.assertEqual(bad["faster_basis"], "relative_ref_invalid")
        self.assertFalse(bad["faster_than_human"], "an invalid control reference is refused, not passed")
        self.assertFalse(bad["passed"])
        # the SAME policy + ratio with a VALID reference passes -> the refusal is the validity flag, not
        # the ratio (proves the guard is the control's route-validity, not a numeric accident).
        ok = G.grade_trajectory(fast_on_route, ROUTE, human_ref_ratio=0.49, human_ref_valid=True)
        self.assertEqual(ok["faster_basis"], "relative")
        self.assertTrue(ok["passed"])
        agg = G.aggregate_route_grades([bad, ok])
        self.assertEqual(agg["n_ref_invalid"], 1)
        self.assertFalse(agg["all_passed"], "an invalid-reference segment is refused -> not all passed")

    def test_relative_tag_is_machine_readable(self):
        # #428 provenance: a downstream selector (#429) must tell relative from absolute and never read the
        # relative verdict as an absolute superhuman claim.
        traj = [tick(x, 0.0, 600.0, 0.0, onground=False, fwd_am=0) for x in _XS]
        absi = G.grade_trajectory(traj, ROUTE)
        self.assertEqual(absi["faster_basis"], "absolute")
        self.assertIsNone(absi["faster_than_sim_human"])
        self.assertIsNone(absi["human_ref_ratio"])
        self.assertFalse(absi["superhuman_claim"])
        rel = G.grade_trajectory(traj, ROUTE, human_ref_ratio=0.49)
        self.assertEqual(rel["human_ref_ratio"], 0.49)
        self.assertIs(rel["faster_than_sim_human"], True)
        self.assertFalse(rel["superhuman_claim"])

    def test_aggregate_surfaces_sim_fidelity_ceiling(self):
        # The route summary surfaces the sim-fidelity ceiling (median human_ref_ratio) + the count of
        # segments the relative bar could not judge (degenerate), and never claims superhuman.
        g_ok = G.grade_trajectory([tick(x, 0.0, 250.0, 0.0, onground=False, fwd_am=0)
                                   for x in range(50, 951, 50)], ROUTE, human_ref_ratio=0.49)
        g_deg = G.grade_trajectory([tick(x, 0.0, 600.0, 0.0, onground=False, fwd_am=0)
                                    for x in range(50, 951, 50)], ROUTE, human_ref_ratio=0.0)
        self.assertTrue(g_ok["passed"])
        self.assertFalse(g_deg["passed"])
        agg = G.aggregate_route_grades([g_ok, g_deg])
        self.assertEqual(agg["n_ref_degenerate"], 1)
        self.assertEqual(agg["median_human_ref_ratio"], G._median([0.49, 0.0]))
        self.assertFalse(agg["superhuman_claim"])
        self.assertFalse(agg["all_passed"], "a degenerate-reference segment is refused -> not all passed")

    def test_display_rounding_cannot_flip_the_relative_gate(self):
        # Codex #471 P1 (2nd round): the relative bar must anchor on the UNROUNDED control median
        # (median_speedup_ratio_raw), never the 4-dp display field -> else a policy genuinely SLOWER than the
        # control false-passes when both collapse to the same rounded value. Build a control whose raw median
        # rounds DOWN (0.490149 -> 0.4901), opening a [rounded, raw) gap, and a policy sitting in that gap.
        ctrl = [tick(x, 0.0, 196.0596, 0.0, onground=False, fwd_am=0) for x in _XS]
        cg = G.grade_trajectory(ctrl, ROUTE)
        raw, disp = cg["median_speedup_ratio_raw"], cg["median_speedup_ratio"]
        self.assertGreater(raw, disp, "boundary needs a control whose raw median rounds DOWN")
        pol = [tick(x, 0.0, ((raw + disp) / 2.0) * 400.0, 0.0, onground=False, fwd_am=0) for x in _XS]
        self.assertFalse(G.grade_trajectory(pol, ROUTE, human_ref_ratio=raw)["faster_than_human"],
                         "policy is slower than the UNROUNDED control -> must fail")
        self.assertTrue(G.grade_trajectory(pol, ROUTE, human_ref_ratio=disp)["faster_than_human"],
                        "the rounded control would wrongly PASS it -> exactly why eval reads the raw field")


class TestRankByRouteGrade(unittest.TestCase):
    """B1 (#428->#429 bridge): checkpoint SELECTION ranks retained snapshots by the honest relative grade."""

    def test_picks_highest_faster_frac(self):
        cands = [{"tag": "a", "summary": _summary(0.25)},
                 {"tag": "b", "summary": _summary(0.5)},
                 {"tag": "c", "summary": _summary(0.125)}]
        best, reason = G.rank_by_route_grade(cands)
        self.assertEqual(best, 1, "the candidate beating the most sim-human controls wins")
        self.assertIn("superhuman_claim=false", reason)

    def test_tie_break_ratio_then_rmse(self):
        # equal seg_faster_frac -> higher absolute median_speedup_ratio wins.
        cands = [{"tag": "slow", "summary": _summary(0.5, ratio=0.40)},
                 {"tag": "fast", "summary": _summary(0.5, ratio=0.60)}]
        self.assertEqual(G.rank_by_route_grade(cands)[0], 1)
        # equal frac AND ratio -> lower route rmse (tighter to the route) wins.
        cands = [{"tag": "loose", "summary": _summary(0.5, ratio=0.5, rmse=90.0)},
                 {"tag": "tight", "summary": _summary(0.5, ratio=0.5, rmse=40.0)}]
        self.assertEqual(G.rank_by_route_grade(cands)[0], 1)

    def test_refuses_too_few_valid_refs(self):
        # A candidate with the HIGHEST faster_frac but whose sim-human controls were ALL invalid
        # (0 valid refs) must NOT win over a slower candidate with trustworthy references.
        high_but_invalid = {"tag": "phantom", "summary": _summary(1.0, n=8, n_ref_invalid=8)}
        honest_slower = {"tag": "honest", "summary": _summary(0.375, n=8, n_ref_invalid=0)}
        best, _ = G.rank_by_route_grade([high_but_invalid, honest_slower], min_valid_segments=4)
        self.assertEqual(best, 1, "phantom fraction on 0 valid refs is refused, not selected")
        # if NONE clears the valid-ref floor -> no selection (None), surfaced honestly.
        none_valid = [{"tag": "x", "summary": _summary(0.9, n=8, n_ref_invalid=6, n_ref_degenerate=2)}]
        best, reason = G.rank_by_route_grade(none_valid, min_valid_segments=4)
        self.assertIsNone(best)
        self.assertIn("valid-reference", reason)

    def test_ranking_only_never_promotes_superhuman(self):
        cands = [{"tag": "a", "summary": _summary(0.5)}]
        best, _ = G.rank_by_route_grade(cands)
        self.assertFalse(cands[best]["summary"]["superhuman_claim"], "selection is ranking, NOT a claim")


if __name__ == "__main__":
    unittest.main()
