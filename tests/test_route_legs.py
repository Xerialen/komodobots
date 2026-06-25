#!/usr/bin/env python3
"""Unit tests for the dm3 route-leg segmenter + signature envelope (experiments/route_observatory).

Covers the correctness claims of the position-based segmenter (#319):
  - resource_visits() detects item visits by POSITION (rho radius), collapsing consecutive
    same-item ticks and skipping the gap — the flicker-immune replacement for pos.li legs;
  - pctl()/band() percentile aggregation;
  - route_env() per-route banding over per-leg signatures;
  - route_condition.goal_vector() points the egocentric heading AT the goal and clamps distance.
Stdlib only (unittest) — same floor as the rest of tests/.
"""
import os
import sys
import unittest

_RO = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "..", "experiments", "route_observatory")
sys.path.insert(0, os.path.abspath(_RO))

import route_legs as RL          # noqa: E402
import route_condition as RC     # noqa: E402


class TestResourceVisits(unittest.TestCase):
    """Position-based item-visit detection (the core of the flicker fix)."""

    def _ticks(self, xs):
        return [{"t": float(i), "x": float(x), "y": 0.0} for i, x in enumerate(xs)]

    def test_visits_are_position_based_and_deduped(self):
        coords = {"A": (0.0, 0.0), "B": (600.0, 0.0)}
        # walk: in A (0,50,150), still-in-A re-dip (120), gap (300,450), into B (560,600)
        ticks = self._ticks([0, 50, 150, 120, 300, 450, 560, 600])
        visits = RL.resource_visits(ticks, coords, rho=200.0)
        # exactly one A then one B — the re-dip into A's radius must NOT double-count,
        # and the gap ticks (300,450) belong to no item.
        self.assertEqual([v[2] for v in visits], ["A", "B"])
        self.assertEqual(visits[0][0], 0)   # A first entered at index 0
        self.assertEqual(visits[1][0], 5)   # B first entered at index 5 (x=450, dist 150 < rho)

    def test_nearest_item_within_rho_wins(self):
        coords = {"A": (0.0, 0.0), "B": (300.0, 0.0)}
        # x=160 is within rho of both A(160) and B(140) -> nearest (B) is chosen
        ticks = self._ticks([0, 160])
        visits = RL.resource_visits(ticks, coords, rho=200.0)
        self.assertEqual([v[2] for v in visits], ["A", "B"])

    def test_no_visit_outside_rho(self):
        coords = {"A": (0.0, 0.0)}
        ticks = self._ticks([500, 600, 700])  # never within 200 qu of A
        self.assertEqual(RL.resource_visits(ticks, coords, rho=200.0), [])


class TestAggregation(unittest.TestCase):
    def test_pctl(self):
        self.assertEqual(RL.pctl([1, 2, 3, 4, 5], 0.5), 3)
        self.assertEqual(RL.pctl([10, 20], 0.0), 10)
        self.assertEqual(RL.pctl([10, 20], 1.0), 20)
        self.assertIsNone(RL.pctl([], 0.5))

    def test_band(self):
        b = RL.band([1, 2, 3, 4, 5])
        self.assertEqual(b["n"], 5)
        self.assertEqual(b["median"], 3)
        self.assertEqual(b["min"], 1)
        self.assertEqual(b["max"], 5)
        self.assertEqual(b["mean"], 3.0)
        self.assertIsNone(RL.band([None, None]))   # all-None -> no band

    def test_route_env(self):
        legs = [
            {"dur_s": 2.0, "hs_mean": 400, "hs_max": 500, "jumps": 3,
             "jump_interval_mean_s": 0.30, "lookmove_mean_deg": 10, "straightness": 0.90},
            {"dur_s": 3.0, "hs_mean": 420, "hs_max": 520, "jumps": 4,
             "jump_interval_mean_s": 0.36, "lookmove_mean_deg": 12, "straightness": 0.85},
        ]
        env = RL.route_env(legs)
        self.assertEqual(env["dur_s"]["n"], 2)
        self.assertEqual(env["hs_mean"]["median"], 410)
        self.assertIsNotNone(env["jump_interval_s"])
        self.assertEqual(env["jump_interval_s"]["n"], 2)

    def test_route_env_handles_missing_jump_interval(self):
        # legs with no detected jump cadence (jump_interval_mean_s=None) -> band is None, no crash
        legs = [{"dur_s": 1.0, "hs_mean": 300, "hs_max": 350, "jumps": 0,
                 "jump_interval_mean_s": None, "lookmove_mean_deg": 5, "straightness": 0.7}]
        env = RL.route_env(legs)
        self.assertIsNone(env["jump_interval_s"])


class TestGoalVector(unittest.TestCase):
    """route_condition.goal_vector — the v4 route-conditioning trained features."""

    def test_heading_points_at_goal(self):
        # goal due +y of origin -> heading sin=1, cos=0
        gv = RC.goal_vector(0.0, 0.0, 0.0, 100.0)
        self.assertAlmostEqual(gv["goal_heading_sin"], 1.0, places=3)
        self.assertAlmostEqual(gv["goal_heading_cos"], 0.0, places=3)
        # goal due +x -> sin=0, cos=1
        gv2 = RC.goal_vector(0.0, 0.0, 100.0, 0.0)
        self.assertAlmostEqual(gv2["goal_heading_sin"], 0.0, places=3)
        self.assertAlmostEqual(gv2["goal_heading_cos"], 1.0, places=3)

    def test_distance_is_normalized_and_clamped(self):
        gv = RC.goal_vector(0.0, 0.0, 100.0, 0.0)
        self.assertAlmostEqual(gv["goal_dist_norm"],
                               round(100.0 / RC.MAP_DIAGONAL_DM3, 4), places=4)
        far = RC.goal_vector(0.0, 0.0, 99999.0, 0.0)
        self.assertEqual(far["goal_dist_norm"], 1.0)   # clamped to map diagonal


class TestPhaseSegmentLeg(unittest.TestCase):
    """(T7 #395) per-tick leg-phase: launch | cruise | approach | land within one leg."""

    def test_full_profile(self):
        # cruise = the contiguous >=400 run (420,500,480); 300 decelerates -> approach.
        hs = [100, 250, 420, 500, 480, 300, 120, 0]
        og = [True, False, False, False, False, False, True, True]
        self.assertEqual(RL.phase_segment_leg(hs, og),
                         ["launch", "launch", "cruise", "cruise", "cruise",
                          "approach", "land", "land"])

    def test_cruise_band_is_the_widest_run(self):
        # two >=gate runs: the segmenter labels the WIDER one cruise; the narrower lone 450
        # stays launch (it precedes the cruise band).
        hs = [450, 200, 410, 420, 430, 440]
        og = [False] * 6
        ph = RL.phase_segment_leg(hs, og)
        self.assertEqual(ph.count("cruise"), 4)        # the 4-wide run, not the lone 450
        self.assertEqual(ph[2:6], ["cruise"] * 4)

    def test_no_cruise_band(self):
        hs = [50, 120, 200, 150, 80]
        og = [True, False, False, False, True]
        ph = RL.phase_segment_leg(hs, og)
        self.assertEqual(ph[2], "launch")   # peak tick is the last launch tick
        self.assertEqual(ph[-1], "land")

    def test_empty(self):
        self.assertEqual(RL.phase_segment_leg([], []), [])


if __name__ == "__main__":
    unittest.main()
