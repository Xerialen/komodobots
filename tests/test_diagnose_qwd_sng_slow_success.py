from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import diagnose_qwd_sng_slow_success as slow_diag


class QwdSngSlowSuccessDiagnosisTests(unittest.TestCase):
    def test_first_entry_for_radius_finds_later_tight_crossing(self) -> None:
        samples = [
            {"time_ms": 0, "origin": [300.0, 0.0, 0.0]},
            {"time_ms": 5000, "origin": [80.0, 0.0, 0.0]},
        ]

        wide = slow_diag.first_entry_for_radius(samples, [0.0, 0.0, 0.0], 320.0)
        tight = slow_diag.first_entry_for_radius(samples, [0.0, 0.0, 0.0], 96.0)

        self.assertEqual(wide["first_time_ms"], 0)
        self.assertEqual(tight["first_time_ms"], 5000)

    def test_movement_segments_filters_teleport_like_speed(self) -> None:
        samples = [
            {"time_ms": 0, "origin": [0.0, 0.0, 0.0]},
            {"time_ms": 100, "origin": [1000.0, 0.0, 0.0]},
            {"time_ms": 200, "origin": [1020.0, 0.0, 0.0]},
        ]

        segments = slow_diag.movement_segments(samples)

        self.assertEqual(len(segments), 1)
        self.assertAlmostEqual(segments[0]["horizontal_speed_qu_per_s"], 200.0)

    def test_summarize_command_rows_reports_route_context(self) -> None:
        rows = [
            {
                "buttons": 2,
                "move": {"forward": 0, "side": 600},
                "qwd_state": {"distance_qu": 100.0},
                "route_state": {"blocked": True, "dir_speed": 0.0, "path_state": 32768},
                "water_state": {"waterlevel": 1},
            },
            {
                "buttons": 0,
                "move": {"forward": 320, "side": 0},
                "qwd_state": {"distance_qu": 200.0},
                "route_state": {"blocked": False, "dir_speed": 1.0, "path_state": 0},
                "water_state": {"waterlevel": 0},
            },
        ]

        summary = slow_diag.summarize_command_rows(rows)

        self.assertEqual(summary["side_nonzero_ratio"], 0.5)
        self.assertEqual(summary["jump_ratio"], 0.5)
        self.assertEqual(summary["blocked_ratio"], 0.5)
        self.assertEqual(summary["water_path_ratio"], 0.5)
        self.assertEqual(summary["low_dir_speed_ratio"], 0.5)

    def test_classify_player_detects_loose_setup_and_post_cp3_gap(self) -> None:
        player = {
            "start_radius_sensitivity": [
                {"radius_qu": 320.0, "first_time_ms": 0},
                {"radius_qu": 192.0, "first_time_ms": 31000},
            ],
            "active_phases": [
                {
                    "control_point_index": 0,
                    "commands": {
                        "side_nonzero_ratio": 1.0,
                        "jump_ratio": 1.0,
                        "blocked_ratio": 0.3,
                        "water_path_ratio": 0.0,
                        "low_dir_speed_ratio": 0.0,
                    },
                    "movement": {"low_speed_ratio": 0.5, "stationary_ratio": 0.3},
                    "closest_target_during_phase": {"distance_qu": 200.0},
                },
                {
                    "control_point_index": 4,
                    "commands": {
                        "side_nonzero_ratio": 1.0,
                        "jump_ratio": 1.0,
                        "blocked_ratio": 0.0,
                        "water_path_ratio": 0.0,
                        "low_dir_speed_ratio": 0.0,
                    },
                    "movement": {"low_speed_ratio": 0.2, "stationary_ratio": 0.0},
                    "closest_target_during_phase": {"distance_qu": 181.0},
                },
            ],
        }

        classification = slow_diag.classify_player(
            player=player,
            run_start_radius=320.0,
            design_start_radius=192.0,
            point_radius=96.0,
        )

        self.assertEqual(classification["verdict"], "loose_setup_radius_plus_post_cp3_progression_gap")
        self.assertIn("loose_start_radius_contaminated_active_window", classification["flags"])
        self.assertIn("post_cp3_target_gap_remains_outside_point_radius", classification["flags"])

    def test_build_report_uses_slow_success_stop_condition(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "run1"
            run_dir.mkdir()
            design_path = root / "design.json"
            result_path = root / "result.json"
            design_path.write_text(
                json.dumps(
                    {
                        "control_points": [
                            {"qwd_origin": [0.0, 0.0, 0.0]},
                            {"qwd_origin": [100.0, 0.0, 0.0]},
                            {"qwd_origin": [200.0, 0.0, 0.0]},
                            {"qwd_origin": [300.0, 0.0, 0.0]},
                            {"qwd_origin": [400.0, 0.0, 0.0]},
                        ],
                        "probe_contract": {
                            "suggested_cvars": {
                                "k_fb_moveprobe_qwd_start_radius": 192.0,
                                "k_fb_moveprobe_qwd_point_radius": 96.0,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            result_path.write_text(
                json.dumps(
                    {
                        "decision": {"verdict": "qwd_sng_hybrid_probe_rejected_by_guardrails"},
                        "stop_condition_results": [
                            {
                                "id": "waypoint_only_slow_success",
                                "status": "reject",
                                "details": {"players_reaching_points_while_slow_or_stuck": ["/ bot"]},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (run_dir / "run.env").write_text(
                "MAP=dm3\nMOVEPROBE_MODE=9\nMOVEPROBE_QWD_START_RADIUS=320\nMOVEPROBE_QWD_POINT_RADIUS=96\n",
                encoding="utf-8",
            )
            (run_dir / "analysis.json").write_text(json.dumps({"match": {"duration": 5000}}), encoding="utf-8")
            (run_dir / "moveprobe-commands.json").write_text(
                json.dumps(
                    {
                        "commands": [
                            {
                                "ed": 2,
                                "name": "/ bot",
                                "time_s": 10.0,
                                "buttons": 2,
                                "move": {"forward": 0, "side": 600},
                                "qwd_state": {"active": True, "control_point_index": 0, "distance_qu": 250.0},
                                "route_state": {"blocked": True, "dir_speed": 0.0, "path_state": 0},
                                "water_state": {"waterlevel": 0},
                            },
                            {
                                "ed": 2,
                                "name": "/ bot",
                                "time_s": 12.0,
                                "buttons": 2,
                                "move": {"forward": 0, "side": 600},
                                "qwd_state": {"active": True, "control_point_index": 4, "distance_qu": 180.0},
                                "route_state": {"blocked": False, "dir_speed": 1.0, "path_state": 0},
                                "water_state": {"waterlevel": 0},
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            lines = [
                {"kind": 0, "data": {"Data": {"ServerTime": 10.0}}},
                {
                    "kind": 1,
                    "data": {
                        "Player": {"Slot": 1, "UserID": 2, "Name": "/ bot", "Spectator": False},
                        "Time": 0,
                    },
                },
                {"kind": 5, "data": {"PlayerNum": 1, "Origin": [300.0, 0.0, 0.0], "TimeMs": 0}},
                {"kind": 5, "data": {"PlayerNum": 1, "Origin": [80.0, 0.0, 0.0], "TimeMs": 3000}},
                {"kind": 5, "data": {"PlayerNum": 1, "Origin": [220.0, 0.0, 0.0], "TimeMs": 5000}},
            ]
            (run_dir / "events.txt").write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")

            report = slow_diag.build_report(
                design_path=design_path,
                result_path=result_path,
                run_id="run1",
                artifacts_root=root,
                stage="test",
            )

        self.assertTrue(report["players"][0]["slow_success_candidate"])


if __name__ == "__main__":
    unittest.main()
