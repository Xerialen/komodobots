from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import map_qwd_route_to_frogbot as mapper


class QwdRouteToFrogbotMappingTests(unittest.TestCase):
    def test_direct_edges_recommend_route_following(self) -> None:
        mapping_summary = {
            "nearest_marker_distance_qu": {"p95": 40.0, "within_128_ratio": 1.0},
            "bot_graph_alignment": {
                "direct_edge_ratio": 1.0,
                "graph_reachable_ratio": 1.0,
                "shortest_path_edges_p50": 1.0,
            },
        }
        demo_summary = {"commands": {"nonzero_side_ratio": 0.2, "nonzero_forward_ratio": 0.9}}

        recommendation = mapper.choose_probe_recommendation(mapping_summary, demo_summary)

        self.assertEqual(recommendation["next_probe"], "route_following_probe")
        self.assertIn("direct Frogbot edges", recommendation["reason"])

    def test_spatial_fit_without_direct_edges_recommends_hybrid(self) -> None:
        mapping_summary = {
            "nearest_marker_distance_qu": {"p95": 115.0, "within_128_ratio": 0.95},
            "bot_graph_alignment": {
                "direct_edge_ratio": 0.0,
                "graph_reachable_ratio": 1.0,
                "shortest_path_edges_p50": 5.0,
            },
        }
        demo_summary = {"commands": {"nonzero_side_ratio": 0.72, "nonzero_forward_ratio": 0.09}}

        recommendation = mapper.choose_probe_recommendation(mapping_summary, demo_summary)

        self.assertEqual(recommendation["next_probe"], "hybrid_waypoint_controller_probe")
        self.assertIn("side-move dominant", recommendation["reason"])

    def test_collapses_consecutive_duplicate_markers(self) -> None:
        mapped = [
            {"frame": 1, "time_s": 0.1, "waypoint_origin": [0, 0, 0], "nearest_marker": {"id": 1, "origin": [0, 0, 0], "distance_qu": 0}},
            {"frame": 2, "time_s": 0.2, "waypoint_origin": [8, 0, 0], "nearest_marker": {"id": 1, "origin": [0, 0, 0], "distance_qu": 8}},
            {"frame": 3, "time_s": 0.3, "waypoint_origin": [64, 0, 0], "nearest_marker": {"id": 2, "origin": [64, 0, 0], "distance_qu": 0}},
        ]

        collapsed = mapper.collapse_marker_sequence(mapped)

        self.assertEqual([row["marker_id"] for row in collapsed], [1, 2])
        self.assertEqual(collapsed[0]["waypoint_count"], 2)
        self.assertEqual(collapsed[0]["max_nearest_distance_qu"], 8)


if __name__ == "__main__":
    unittest.main()
