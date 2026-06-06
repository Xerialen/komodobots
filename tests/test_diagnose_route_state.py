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
        self.assertFalse(diagnosis["capabilities"]["route_node_or_goal_state_available"])
        self.assertEqual(diagnosis["players"][0]["low_windows"]["count"], 1)
        self.assertEqual(
            diagnosis["players"][0]["top_windows"][0]["hint"],
            "low_speed_despite_strong_commands",
        )


if __name__ == "__main__":
    unittest.main()
