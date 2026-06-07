from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import inspect_qwd_sng_mvd_crossings as crossings


def write_design(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "control_points": [
                    {"qwd_origin": [0.0, 0.0, 0.0]},
                    {"qwd_origin": [100.0, 0.0, 0.0]},
                    {"qwd_origin": [200.0, 0.0, 0.0]},
                    {"qwd_origin": [300.0, 0.0, 0.0]},
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


def write_result(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "decision": {
                    "verdict": "qwd_sng_hybrid_probe_rejected_by_guardrails",
                    "failed_stop_conditions": [
                        "phase_target_progression",
                        "waypoint_only_slow_success",
                    ],
                    "inconclusive_stop_conditions": ["tight_start_activation"],
                }
            }
        ),
        encoding="utf-8",
    )


def write_run(root: Path) -> None:
    run_dir = root / "run1"
    run_dir.mkdir()
    (run_dir / "run.env").write_text(
        (
            "MAP=dm3\n"
            "MOVEPROBE_MODE=9\n"
            "MOVEPROBE_QWD_START_RADIUS=192\n"
            "MOVEPROBE_QWD_POINT_RADIUS=96\n"
            "MOVEPROBE_LOG_INTERVAL=0.1\n"
        ),
        encoding="utf-8",
    )
    (run_dir / "analysis.json").write_text(json.dumps({"match": {"duration": 10000}}), encoding="utf-8")
    (run_dir / "moveprobe-commands.json").write_text(
        json.dumps(
            {
                "commands": [
                    {
                        "ed": 2,
                        "name": "/ bot",
                        "time_s": 10.5,
                        "qwd_state": {
                            "active": True,
                            "control_point_index": 2,
                            "advanced_control_points": 2,
                            "distance_qu": 80.0,
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    lines = [
        {"kind": 0, "time": 0, "data": {"Data": {"ServerTime": 10.0}, "Time": 0}},
        {
            "kind": 1,
            "time": 0,
            "data": {"Player": {"Slot": 1, "UserID": 2, "Name": "/ bot", "Spectator": False}, "Time": 0},
        },
    ]
    for time_ms, origin in [
        (100, [0, 0, 0]),
        (200, [100, 0, 0]),
        (300, [200, 0, 0]),
        (400, [300, 0, 0]),
    ]:
        lines.append(
            {
                "kind": 5,
                "time": time_ms / 1000.0,
                "data": {"PlayerNum": 1, "Origin": origin, "TimeMs": time_ms},
            }
        )
    (run_dir / "events.txt").write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")


class InspectQwdSngMvdCrossingsTests(unittest.TestCase):
    def test_physical_crossing_with_sampled_advance_keeps_start_unresolved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            design_path = root / "design.json"
            result_path = root / "result.json"
            write_design(design_path)
            write_result(result_path)
            write_run(root)

            report = crossings.build_report(
                design_path=design_path,
                result_path=result_path,
                run_id="run1",
                artifacts_root=root,
                stage="test",
            )

        player = report["players"][0]
        self.assertEqual(player["mvd_sequential_point_radius_reached"], 4)
        self.assertEqual(player["first_mvd_cp0_start_radius_entry"]["time_ms"], 100)
        self.assertEqual(player["first_active_qwd_sample_status"], "sampled_after_internal_advancement")
        self.assertTrue(player["assessment"]["physical_minimum_advancement_reached"])
        self.assertFalse(player["assessment"]["sampled_command_start_proven"])
        self.assertEqual(
            report["decision"]["verdict"],
            "qwd_sng_mvd_crossing_progress_but_start_instrumentation_needed",
        )

    def test_transition_speed_is_reported_between_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            design_path = root / "design.json"
            result_path = root / "result.json"
            write_design(design_path)
            write_result(result_path)
            write_run(root)

            report = crossings.build_report(
                design_path=design_path,
                result_path=result_path,
                run_id="run1",
                artifacts_root=root,
                stage="test",
            )

        entries = report["players"][0]["mvd_sequential_point_radius_entries"]
        transition = entries[1]["transition_from_previous"]
        self.assertEqual(transition["duration_s"], 0.1)
        self.assertEqual(transition["straight_horizontal_speed_qu_per_s"], 1000.0)
        self.assertEqual(transition["movement_window"]["p50_horizontal_speed_qu_per_s"], 1000.0)


if __name__ == "__main__":
    unittest.main()
