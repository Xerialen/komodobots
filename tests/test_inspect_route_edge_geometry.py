from __future__ import annotations

import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import inspect_route_edge_geometry as geometry


class RouteEdgeGeometryTests(unittest.TestCase):
    def test_parse_edge_spec_accepts_colon_and_arrow(self) -> None:
        self.assertEqual(geometry.parse_edge_spec("276:59"), (276, 59))
        self.assertEqual(geometry.parse_edge_spec("276->59"), (276, 59))

        with self.assertRaises(argparse.ArgumentTypeError):
            geometry.parse_edge_spec("276")

    def test_edge_summary_reports_missing_source_origin(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bot_map_path = Path(temp_dir) / "test.bot"
            bot_map_path.write_text(
                "\n".join(
                    [
                        "CreateMarker 10 20 30",
                        "SetZone 1 17",
                        "SetGoal 1 5",
                        "SetZone 2 17",
                        "SetMarkerPath 2 0 1",
                        "SetMarkerPath 1 0 2",
                    ]
                ),
                encoding="utf-8",
            )
            parsed = geometry.parse_bot_map_geometry(bot_map_path)
            edge = geometry.edge_summary(2, 1, parsed)
            reciprocal = geometry.edge_summary(1, 2, parsed)

        self.assertTrue(edge["defined_in_bot_map"])
        self.assertEqual(edge["path_indexes"], [0])
        self.assertEqual(edge["target_marker"]["origin"], [10.0, 20.0, 30.0])
        self.assertFalse(edge["source_marker"]["has_static_origin"])
        self.assertEqual(edge["static_geometry"]["status"], "incomplete_missing_static_origin")
        self.assertEqual(edge["static_geometry"]["missing_static_origin_markers"], ["2"])
        self.assertTrue(reciprocal["defined_in_bot_map"])

    def test_edge_summary_computes_vector_when_origins_exist(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bot_map_path = Path(temp_dir) / "test.bot"
            bot_map_path.write_text(
                "\n".join(
                    [
                        "CreateMarker 0 0 0",
                        "CreateMarker 3 4 12",
                        "SetMarkerPath 1 0 2",
                    ]
                ),
                encoding="utf-8",
            )
            parsed = geometry.parse_bot_map_geometry(bot_map_path)
            edge = geometry.edge_summary(1, 2, parsed)

        self.assertEqual(edge["static_geometry"]["status"], "computed")
        self.assertEqual(edge["static_geometry"]["horizontal_distance"], 5.0)
        self.assertEqual(edge["static_geometry"]["distance_3d"], 13.0)
        self.assertEqual(edge["static_geometry"]["vertical_delta"], 12.0)

    def test_build_report_summarizes_focus_edge_samples(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bot_map_path = root / "test.bot"
            attribution_path = root / "attribution.json"
            bot_map_path.write_text(
                "\n".join(
                    [
                        "CreateMarker 100 0 0",
                        "SetZone 1 17",
                        "SetGoal 1 5",
                        "SetZone 2 17",
                        "SetMarkerPath 2 0 1",
                        "SetMarkerPath 1 0 2",
                    ]
                ),
                encoding="utf-8",
            )
            attribution_path.write_text(
                json.dumps(
                    {
                        "stage": "s6x-test",
                        "windows": [
                            {
                                "player": "/ bro",
                                "rank": 1,
                                "window_ms": {"start_ms": 1000, "end_ms": 1100},
                                "location": "water.LG",
                                "route_samples": [
                                    {
                                        "time_ms": 1010,
                                        "touch_marker": 2,
                                        "linked_marker": 1,
                                        "goal_marker": 1,
                                        "touch_to_link_path": {
                                            "source": 2,
                                            "target": 1,
                                            "path_indexes": [0],
                                        },
                                        "path_state": {"value": 32768, "names": ["WATER_PATH"]},
                                        "blocked": False,
                                        "dir_speed": 0.05,
                                        "water_state": {
                                            "present": True,
                                            "waterlevel": 2,
                                            "emitted_upmove": -24.0,
                                        },
                                    }
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            args = SimpleNamespace(
                stage="s6f-test",
                bot_map=bot_map_path,
                edge=(2, 1),
                marker=1,
                attribution_json=[attribution_path],
            )

            report = geometry.build_report(args)

        self.assertEqual(report["edge"]["static_geometry"]["status"], "incomplete_missing_static_origin")
        self.assertEqual(report["attribution_summary"]["focus_edge_sample_count"], 1)
        self.assertEqual(report["attribution_summary"]["path_state_names"], ["WATER_PATH"])
        self.assertEqual(report["attribution_summary"]["waterlevel_values"], [2])
        self.assertEqual(report["attribution_summary"]["low_dir_speed_ratio"], 1.0)
        self.assertIn("S7a", report["next_goal"])


if __name__ == "__main__":
    unittest.main()
