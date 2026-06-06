from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import attribute_route_state_windows as attribute


class RouteStateAttributionTests(unittest.TestCase):
    def test_decode_path_state_water_path(self) -> None:
        decoded = attribute.decode_flags(32768, attribute.PATH_FLAG_SPECS)

        self.assertEqual(decoded["names"], ["WATER_PATH"])
        self.assertEqual(decoded["unknown_mask"], 0)

    def test_portable_path_serializes_sibling_ktx_paths(self) -> None:
        path = attribute.REPO_ROOT.parent / "engine" / "ktx" / "include" / "fb_globals.h"

        self.assertEqual(attribute.portable_path(path), "../engine/ktx/include/fb_globals.h")

    def test_parse_bot_map_records_paths_and_flags(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bot_map = Path(temp_dir) / "test.bot"
            bot_map.write_text(
                "\n".join(
                    [
                        "CreateMarker 0 0 0",
                        "CreateMarker 10 0 0",
                        "SetGoal 1 5",
                        "SetZone 1 17",
                        "SetMarkerPath 1 0 2",
                        "SetMarkerPathFlags 1 0 rj",
                    ]
                ),
                encoding="utf-8",
            )

            parsed = attribute.parse_bot_map(bot_map)

        self.assertEqual(parsed["markers"][1]["origin"], [0.0, 0.0, 0.0])
        self.assertEqual(parsed["markers"][1]["goal"], 5)
        self.assertEqual(parsed["markers"][1]["zone"], 17)
        self.assertEqual(parsed["paths"][(1, 2)]["path_indexes"], [0])
        self.assertEqual(parsed["paths"][(1, 2)]["explicit_flags"], ["ROCKET_JUMP", "JUMP_LEDGE"])
        self.assertIn("marker->fb.index + 1", parsed["marker_index_invariant"])
        self.assertEqual(parsed["static_create_marker_count"], 2)
        self.assertEqual(parsed["referenced_marker_count"], 2)

    def test_command_rows_for_window_skips_missing_time_s(self) -> None:
        commands = {
            "commands": [
                {"name": "/ bro", "route_state": {}},
                {"time_s": 1.0, "name": "/ bro", "route_state": {}},
            ]
        }

        rows = attribute.command_rows_for_window(commands, "/ bro", 950, 1050, 75)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["time_s"], 1.0)

    def test_default_commands_path_rejects_unsafe_run_id_from_diagnosis(self) -> None:
        with self.assertRaises(ValueError):
            attribute.default_commands_path("../escape")

    def test_build_attribution_groups_water_path_without_obstruction(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            diagnosis_path = root / "diagnosis.json"
            commands_path = root / "moveprobe-commands.json"
            bot_map_path = root / "test.bot"
            bot_map_path.write_text(
                "\n".join(
                    [
                        "CreateMarker 0 0 0",
                        "CreateMarker 10 0 0",
                        "SetZone 1 17",
                        "SetZone 2 17",
                        "SetMarkerPath 1 0 2",
                    ]
                ),
                encoding="utf-8",
            )
            diagnosis_path.write_text(
                json.dumps(
                    {
                        "run": {"run_id": "run", "map": "dm3", "map_title": "The Abandoned Base"},
                        "players": [
                            {
                                "name": "/ bro",
                                "top_windows": [
                                    {
                                        "rank": 1,
                                        "start_ms": 950,
                                        "end_ms": 1050,
                                        "avg_low_speed_qu_per_s": 20.0,
                                        "nearest_start": [{"loc": "water.LG"}],
                                        "command_summary": {
                                            "avg_horizontal_command": 824.0,
                                            "sample_window_ms": {"margin_ms": 75},
                                        },
                                    }
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            commands_path.write_text(
                json.dumps(
                    {
                        "commands": [
                            {
                                "time_s": 1.0,
                                "name": "/ bro",
                                "route_state": {
                                    "linked_marker": 2,
                                    "touch_marker": 1,
                                    "goal_ed": 42,
                                    "goal_marker": 2,
                                    "path_state": 32768,
                                    "bot_state": 128,
                                    "blocked": False,
                                    "dir_speed": 0.05,
                                },
                                "water_state": {
                                    "waterlevel": 3,
                                    "watertype": -3,
                                    "flags": 528,
                                    "swim_arrow": 16,
                                    "emitted_upmove": 120.0,
                                    "velocity": {"x": 1.0, "y": 2.0, "z": 80.0},
                                    "dir_move": {"x": 0.1, "y": 0.2, "z": 0.3},
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            args = SimpleNamespace(
                stage="test",
                diagnosis_json=diagnosis_path,
                commands_json=commands_path,
                bot_map=bot_map_path,
            )

            attribution = attribute.build_attribution(args)

        self.assertEqual(attribution["patterns"][0]["classification"], "water_path_without_obstruction")
        self.assertEqual(attribution["patterns"][0]["linked_marker_values"], [2])
        self.assertEqual(attribution["patterns"][0]["goal_marker_values"], [2])
        self.assertTrue(attribution["patterns"][0]["contains_water_path"])
        self.assertEqual(attribution["patterns"][0]["blocked_ratio"], 0.0)
        self.assertEqual(attribution["patterns"][0]["water_state"]["waterlevel_values"], [3])
        self.assertEqual(attribution["patterns"][0]["water_state"]["watertype_names"], ["CONTENT_WATER"])
        self.assertEqual(attribution["patterns"][0]["water_state"]["swim_arrow_names"], ["UP"])
        self.assertEqual(attribution["patterns"][0]["water_state"]["emitted_upmove_nonzero_ratio"], 1.0)
        self.assertEqual(attribution["windows"][0]["water_state"]["dir_move_z_avg"], 0.3)
        self.assertEqual(attribution["windows"][0]["route_samples"][0]["touch_to_link_path"]["path_indexes"], [0])
        self.assertEqual(
            attribution["windows"][0]["route_samples"][0]["water_state"]["flags"]["names"],
            ["FL_INWATER", "FL_ONGROUND"],
        )


if __name__ == "__main__":
    unittest.main()
