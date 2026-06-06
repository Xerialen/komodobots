from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import diagnose_route_state


class RouteStateDiagnosisTests(unittest.TestCase):
    def test_low_windows_merge_nearby_low_segments_and_filter_short_ones(self) -> None:
        segments = [
            {
                "start_ms": 0,
                "end_ms": 100,
                "dt_ms": 100,
                "start_origin": [0.0, 0.0, 0.0],
                "end_origin": [5.0, 0.0, 0.0],
                "horizontal_distance_qu": 5.0,
                "horizontal_speed_qu_per_s": 50.0,
            },
            {
                "start_ms": 160,
                "end_ms": 260,
                "dt_ms": 100,
                "start_origin": [5.0, 0.0, 0.0],
                "end_origin": [14.0, 0.0, 0.0],
                "horizontal_distance_qu": 9.0,
                "horizontal_speed_qu_per_s": 90.0,
            },
            {
                "start_ms": 500,
                "end_ms": 560,
                "dt_ms": 60,
                "start_origin": [14.0, 0.0, 0.0],
                "end_origin": [15.0, 0.0, 0.0],
                "horizontal_distance_qu": 1.0,
                "horizontal_speed_qu_per_s": 16.7,
            },
        ]

        windows = diagnose_route_state.detect_low_windows(
            segments,
            low_speed=100.0,
            min_duration_ms=150,
            merge_gap_ms=80,
        )

        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0]["start_ms"], 0)
        self.assertEqual(windows[0]["end_ms"], 260)
        self.assertEqual(windows[0]["low_duration_ms"], 200)
        self.assertAlmostEqual(windows[0]["avg_low_speed_qu_per_s"], 70.0)

    def test_command_summary_flags_strong_commands_near_window(self) -> None:
        commands = [
            {
                "time_s": 1.0,
                "buttons": 2,
                "move": {"forward": 600, "side": 600},
                "diagnostics": {"yaw_delta": 120.0, "backward": False},
                "route_state": {
                    "linked_marker": 12,
                    "touch_marker": 10,
                    "goal_ed": 42,
                    "goal_marker": 14,
                    "path_state": 524288,
                    "bot_state": 8192,
                    "blocked": True,
                    "dir_speed": 1.25,
                },
            },
            {
                "time_s": 1.2,
                "buttons": 0,
                "move": {"forward": 0, "side": 0},
                "diagnostics": {"yaw_delta": 10.0, "backward": False},
            },
        ]

        summary = diagnose_route_state.summarize_commands_for_window(
            commands,
            start_ms=950,
            end_ms=1050,
            margin_ms=75,
            strong_command=400,
        )

        self.assertEqual(summary["command_count"], 1)
        self.assertEqual(summary["exact_command_count"], 1)
        self.assertEqual(summary["strong_command_ratio"], 1.0)
        self.assertEqual(summary["jump_button_ratio"], 1.0)
        self.assertEqual(summary["yaw_delta_abs_p90"], 120.0)
        self.assertEqual(summary["route_state"]["sample_count"], 1)
        self.assertEqual(summary["route_state"]["linked_marker_values"], [12])
        self.assertEqual(summary["route_state"]["blocked_ratio"], 1.0)

    def test_command_summary_tolerates_non_dict_move_and_diagnostics(self) -> None:
        summary = diagnose_route_state.summarize_commands_for_window(
            [{"time_s": 1.0, "buttons": None, "move": None, "diagnostics": None}],
            start_ms=950,
            end_ms=1050,
            margin_ms=75,
            strong_command=400,
        )

        self.assertEqual(summary["command_count"], 1)
        self.assertEqual(summary["avg_horizontal_command"], 0.0)
        self.assertEqual(summary["jump_button_ratio"], 0.0)
        self.assertEqual(summary["yaw_delta_sample_count"], 0)

    def test_command_summary_skips_untimestamped_rows(self) -> None:
        summary = diagnose_route_state.summarize_commands_for_window(
            [
                {"buttons": 2, "move": {"forward": 800, "side": 0}},
                {"time_s": 0.0, "buttons": 0, "move": {"forward": 400, "side": 0}},
            ],
            start_ms=0,
            end_ms=10,
            margin_ms=0,
            strong_command=400,
        )

        self.assertEqual(summary["command_count"], 1)
        self.assertEqual(summary["exact_command_count"], 1)
        self.assertEqual(summary["avg_horizontal_command"], 400.0)
        self.assertEqual(summary["jump_button_ratio"], 0.0)

    def test_load_map_entities_skips_non_dict_entities(self) -> None:
        entities = diagnose_route_state.load_map_entities(
            {
                "mapEntities": {
                    "entities": [
                        None,
                        {"type": "item", "kind": "rl", "name": "RL", "loc": "RL", "x": 1, "y": 2, "z": 3},
                    ]
                }
            }
        )

        self.assertEqual(len(entities), 1)
        self.assertEqual(entities[0]["origin"], [1.0, 2.0, 3.0])

    def test_read_artifact_json_warns_on_corrupt_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "bad.json"
            path.write_text("{", encoding="utf-8")
            warnings: list[str] = []

            loaded = diagnose_route_state.read_artifact_json(path, artifact_name="bad.json", warnings=warnings)

        self.assertEqual(loaded, {})
        self.assertIn("bad.json could not be parsed as JSON", warnings[0])

    def test_clock_overlap_flags_mismatched_command_epoch(self) -> None:
        samples = {1: [{"time_ms": 0, "origin": [0, 0, 0], "yaw": None}]}
        commands = {"commands": [{"time_s": 100.0}]}

        overlap = diagnose_route_state.summarize_clock_overlap(samples, commands, margin_ms=150)

        self.assertFalse(overlap["overlaps"])
        self.assertEqual(overlap["status"], "no_clock_overlap")

    def test_capabilities_distinguish_route_yaw_from_route_state(self) -> None:
        commands = {
            "commands": [
                {
                    "diagnostics": {
                        "route_yaw": 90.0,
                        "view_yaw": 180.0,
                        "yaw_delta": 90.0,
                        "backward": False,
                    }
                }
            ]
        }

        capabilities = diagnose_route_state.detect_capabilities(commands, {"mapEntities": {"entities": []}})

        self.assertTrue(capabilities["route_direction_available"])
        self.assertFalse(capabilities["route_node_or_goal_state_available"])

    def test_capabilities_detect_nested_route_state(self) -> None:
        commands = {
            "commands": [
                {
                    "diagnostics": {"route_yaw": 90.0},
                    "route_state": {
                        "linked_marker": 12,
                        "touch_marker": 10,
                        "goal_ed": 42,
                        "goal_marker": 14,
                        "path_state": 524288,
                        "bot_state": 8192,
                        "blocked": True,
                        "dir_speed": 1.25,
                    },
                }
            ]
        }

        capabilities = diagnose_route_state.detect_capabilities(commands, {"mapEntities": {"entities": []}})

        self.assertTrue(capabilities["route_node_or_goal_state_available"])
        self.assertIn("linked_marker", capabilities["route_state_keys"])
        self.assertIn("blocked", capabilities["route_state_keys"])

    def test_build_diagnosis_from_minimal_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "run"
            run_dir.mkdir()
            (run_dir / "run.env").write_text("MAP=dm3\nMOVEPROBE_MODE=7\n", encoding="utf-8")
            (run_dir / "analysis.json").write_text(
                json.dumps(
                    {
                        "match": {"map": "The Abandoned Base", "duration": 1000},
                        "mapEntities": {
                            "entities": [
                                {"type": "item", "kind": "rl", "name": "RL", "loc": "RL", "x": 0, "y": 0, "z": 0}
                            ]
                        },
                    }
                ),
                encoding="utf-8",
            )
            events = [
                {"kind": 1, "time": 0, "data": {"Player": {"Slot": 1, "UserID": 2, "Name": "/ bot"}}},
                {"kind": 5, "time": 0, "data": {"PlayerNum": 1, "Origin": [0, 0, 0], "Angles": [0, 90, 0], "TimeMs": 0}},
                {"kind": 5, "time": 0.5, "data": {"PlayerNum": 1, "Origin": [25, 0, 0], "Angles": [0, 90, 0], "TimeMs": 500}},
                {"kind": 5, "time": 1.0, "data": {"PlayerNum": 1, "Origin": [50, 0, 0], "Angles": [0, 90, 0], "TimeMs": 1000}},
            ]
            (run_dir / "events.txt").write_text("\n".join(json.dumps(event) for event in events), encoding="utf-8")
            (run_dir / "moveprobe-commands.json").write_text(
                json.dumps(
                    {
                        "commands": [
                            {
                                "time_s": 0.5,
                                "ed": 2,
                                "name": "/ bot",
                                "buttons": 2,
                                "move": {"forward": 600, "side": 600},
                                "diagnostics": {"route_yaw": 90.0, "view_yaw": 90.0, "yaw_delta": 0.0},
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            args = diagnose_route_state.parse_args(
                [
                    "--run-id",
                    str(run_dir),
                    "--min-low-window-ms",
                    "250",
                    "--output-json",
                    str(run_dir / "out.json"),
                    "--output-md",
                    str(run_dir / "out.md"),
                ]
            )

            diagnosis = diagnose_route_state.build_diagnosis(args)

        self.assertEqual(diagnosis["run"]["run_id"], "run")
        self.assertEqual(diagnosis["trace"]["clock_overlap"]["status"], "ok")
        self.assertEqual(diagnosis["warnings"], [])
        self.assertFalse(diagnosis["capabilities"]["route_node_or_goal_state_available"])
        self.assertEqual(diagnosis["players"][0]["low_windows"]["count"], 1)
        self.assertEqual(
            diagnosis["players"][0]["top_windows"][0]["hint"],
            "low_speed_despite_strong_commands",
        )

    def test_build_diagnosis_warns_when_command_clock_does_not_overlap_samples(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "run"
            run_dir.mkdir()
            (run_dir / "run.env").write_text("MAP=dm3\nMOVEPROBE_MODE=7\n", encoding="utf-8")
            (run_dir / "analysis.json").write_text(json.dumps({"match": {"duration": 1000}}), encoding="utf-8")
            events = [
                {"kind": 1, "time": 0, "data": {"Player": {"Slot": 1, "UserID": 2, "Name": "/ bot"}}},
                {"kind": 5, "time": 0, "data": {"PlayerNum": 1, "Origin": [0, 0, 0], "TimeMs": 0}},
                {"kind": 5, "time": 1.0, "data": {"PlayerNum": 1, "Origin": [10, 0, 0], "TimeMs": 1000}},
            ]
            (run_dir / "events.txt").write_text("\n".join(json.dumps(event) for event in events), encoding="utf-8")
            (run_dir / "moveprobe-commands.json").write_text(
                json.dumps({"commands": [{"time_s": 100.0, "ed": 2, "name": "/ bot", "move": {"forward": 600, "side": 0}}]}),
                encoding="utf-8",
            )
            args = diagnose_route_state.parse_args(
                [
                    "--run-id",
                    str(run_dir),
                    "--min-low-window-ms",
                    "250",
                    "--output-json",
                    str(run_dir / "out.json"),
                    "--output-md",
                    str(run_dir / "out.md"),
                ]
            )

            diagnosis = diagnose_route_state.build_diagnosis(args)

        self.assertEqual(diagnosis["trace"]["clock_overlap"]["status"], "no_clock_overlap")
        self.assertTrue(any("Command timestamps do not overlap" in warning for warning in diagnosis["warnings"]))


if __name__ == "__main__":
    unittest.main()
