#!/usr/bin/env python3
"""ml/tests/test_route_goals.py — route-conditioning v4 hindsight GOAL labelling.

Pure stdlib (no duckdb/numpy), so it runs even on a deps-free box and is NOT skipped
(unlike the build_features tests, which need duckdb). Covers the position-based, flicker-
immune resource_visits + the per-tick hindsight goal (GCSL) that build_features stamps into
self_state['goal'] for AO.self_features. Mirrors the validated route_legs segmentation.
"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ML = HERE.parent
REPO_ROOT = ML.parent
sys.path.insert(0, str(ML / "pipeline"))

import route_goals as RG   # noqa: E402


class TestResourceVisits(unittest.TestCase):
    """Position-based item-visit detection — the flicker-immune segmentation (mirrors
    experiments/route_observatory/route_legs.resource_visits)."""

    def test_visits_position_based_and_deduped(self):
        coords = {"A": (0.0, 0.0), "B": (600.0, 0.0)}
        # in A (0,50,150), still-in-A re-dip (120), gap (300,450), into B (560,600)
        positions = [(float(x), 0.0) for x in (0, 50, 150, 120, 300, 450, 560, 600)]
        visits = RG.resource_visits(positions, coords, rho=200.0)
        # exactly one A then one B — the re-dip into A's radius must NOT double-count.
        self.assertEqual([v[1] for v in visits], ["A", "B"])
        self.assertEqual(visits[0][0], 0)   # A first entered at index 0
        self.assertEqual(visits[1][0], 5)   # B first entered at index 5 (x=450, dist 150 < rho)

    def test_nearest_within_rho_wins(self):
        coords = {"A": (0.0, 0.0), "B": (300.0, 0.0)}
        # x=160 is within rho of both A(160) and B(140) -> nearest (B) is chosen
        visits = RG.resource_visits([(0.0, 0.0), (160.0, 0.0)], coords, rho=200.0)
        self.assertEqual([v[1] for v in visits], ["A", "B"])

    def test_no_visit_outside_rho(self):
        coords = {"A": (0.0, 0.0)}
        positions = [(500.0, 0.0), (600.0, 0.0), (700.0, 0.0)]  # never within 200 qu
        self.assertEqual(RG.resource_visits(positions, coords, rho=200.0), [])

    def test_none_position_is_no_resource(self):
        coords = {"A": (0.0, 0.0)}
        positions = [(None, None), (0.0, 0.0), (None, None)]
        self.assertEqual(RG.resource_visits(positions, coords, rho=200.0), [(1, "A")])


class TestLabelEpisodeGoals(unittest.TestCase):
    def setUp(self):
        # A -> (out of any radius) -> B; the leg's hindsight goal is B's coords.
        self.coords = {"A": (0.0, 0.0), "B": (1000.0, 0.0)}
        self.positions = [(float(x), 0.0) for x in (0, 250, 500, 750, 1000)]

    def test_leg_ticks_point_at_destination(self):
        # visits A@0, B@4 -> every tick 0..4 is heading to B (hindsight goal).
        goals = RG.label_episode_goals(self.positions, self.coords, rho=200.0)
        self.assertTrue(all(g == (1000.0, 0.0) for g in goals))

    def test_ticks_after_last_visit_are_free_roam(self):
        # extend past B and away -> trailing ticks have no next visit -> None (free-roam).
        positions = self.positions + [(1500.0, 0.0), (2000.0, 0.0)]
        goals = RG.label_episode_goals(positions, self.coords, rho=200.0)
        self.assertEqual(goals[0], (1000.0, 0.0))   # heading to B
        self.assertIsNone(goals[-1])                # past B, no further goal

    def test_single_visit_is_all_free_roam(self):
        # only A is ever visited -> no leg -> every tick free-roam (None).
        positions = [(0.0, 0.0), (50.0, 0.0), (100.0, 0.0)]
        self.assertEqual(RG.label_episode_goals(positions, self.coords, rho=200.0),
                         [None, None, None])

    def test_no_coords_is_all_free_roam(self):
        self.assertEqual(RG.label_episode_goals(self.positions, {}, rho=200.0),
                         [None] * len(self.positions))


class TestLoadResourceCoords(unittest.TestCase):
    def test_loads_committed_dm3_artifact(self):
        coords = RG.load_resource_coords(REPO_ROOT / "data/catalog/resource_coords.dm3.json")
        self.assertEqual(len(coords), 11)        # the 11 dm3 route nodes
        self.assertIn("RL", coords)
        self.assertEqual(len(coords["RL"]), 2)   # (x, y)

    def test_missing_file_is_empty(self):
        self.assertEqual(RG.load_resource_coords("/no/such/resource_coords.json"), {})


if __name__ == "__main__":
    unittest.main()
