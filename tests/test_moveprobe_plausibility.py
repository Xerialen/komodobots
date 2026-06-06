from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import summarize_moveprobe_plausibility as plausibility


def write_run(run_dir: Path, stationary_ratio: float) -> None:
    run_dir.mkdir(parents=True)
    (run_dir / "run.env").write_text("MAP=frobodm2\nMOVEPROBE_MODE=3\n", encoding="utf-8")
    (run_dir / "movement-metrics.json").write_text(
        json.dumps(
            {
                "players": [
                    {
                        "slot": 1,
                        "name": "/ bot",
                        "avg_horizontal_speed_qu_per_s": 330.0,
                        "p95_horizontal_speed_qu_per_s": 460.0,
                        "stationary_time_ratio": stationary_ratio,
                        "low_speed_time_ratio": 0.1,
                        "airborne_proxy_time_ratio": 0.2,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "moveprobe-commands.json").write_text(
        json.dumps(
            {
                "commands": [
                    {
                        "name": "/ bot",
                        "buttons": 2,
                        "angles": {"yaw": float(yaw)},
                        "move": {"forward": 800, "side": 400},
                    }
                    for yaw in range(12)
                ]
            }
        ),
        encoding="utf-8",
    )


def write_duplicate_name_run(run_dir: Path) -> None:
    run_dir.mkdir(parents=True)
    (run_dir / "run.env").write_text(
        "MAP=dm3\nMOVEPROBE_MODE=4\nMOVEPROBE_FORWARDMOVE=600\n",
        encoding="utf-8",
    )
    (run_dir / "movement-metrics.json").write_text(
        json.dumps(
            {
                "players": [
                    {
                        "slot": 1,
                        "user_id": 2,
                        "name": "/ bot",
                        "avg_horizontal_speed_qu_per_s": 250.0,
                        "p95_horizontal_speed_qu_per_s": 360.0,
                        "stationary_time_ratio": 0.05,
                        "low_speed_time_ratio": 0.1,
                        "airborne_proxy_time_ratio": 0.2,
                    },
                    {
                        "slot": 2,
                        "user_id": 3,
                        "name": "/ bot",
                        "avg_horizontal_speed_qu_per_s": 260.0,
                        "p95_horizontal_speed_qu_per_s": 370.0,
                        "stationary_time_ratio": 0.04,
                        "low_speed_time_ratio": 0.1,
                        "airborne_proxy_time_ratio": 0.2,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    commands = []
    for ed, yaw_offset in ((2, 0), (3, 100)):
        commands.extend(
            {
                "ed": ed,
                "name": "/ bot",
                "buttons": 2,
                "angles": {"yaw": float(yaw_offset + yaw)},
                "move": {"forward": 600, "side": 200},
            }
            for yaw in range(12)
        )
    (run_dir / "moveprobe-commands.json").write_text(
        json.dumps({"commands": commands}),
        encoding="utf-8",
    )


def write_diagnostic_run(run_dir: Path) -> None:
    write_run(run_dir, stationary_ratio=0.05)
    commands_path = run_dir / "moveprobe-commands.json"
    commands = json.loads(commands_path.read_text(encoding="utf-8"))
    for index, row in enumerate(commands["commands"]):
        row["move"] = {"forward": -400 if index < 6 else 400, "side": 200, "up": 0}
        row["diagnostics"] = {
            "route_yaw": 270.0 if index < 6 else 90.0,
            "view_yaw": 90.0,
            "yaw_delta": 180.0 if index < 6 else 0.0,
            "backward": index < 6,
        }
    commands_path.write_text(json.dumps(commands), encoding="utf-8")


class MoveprobePlausibilityTests(unittest.TestCase):
    def test_summarize_run_passes_gate_for_plausible_player(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "run-pass"
            write_run(run_dir, stationary_ratio=0.05)

            summary = plausibility.summarize_run(
                run_dir,
                expected_forward=800,
                max_stationary_ratio=0.25,
                max_low_speed_ratio=0.4,
                min_forward_ratio=0.8,
                min_horizontal_ratio=0.8,
                min_jump_ratio=0.8,
                min_side_ratio=0.8,
                min_yaw_unique=10,
            )

        self.assertTrue(summary["passes_gate"])
        self.assertTrue(summary["players"][0]["passes_gate"])
        self.assertEqual(summary["players"][0]["yaw_unique_count"], 12)
        self.assertEqual(summary["players"][0]["side_nonzero_ratio"], 1.0)

    def test_summarize_run_fails_gate_for_stationary_player(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "run-fail"
            write_run(run_dir, stationary_ratio=0.6)

            summary = plausibility.summarize_run(
                run_dir,
                expected_forward=800,
                max_stationary_ratio=0.25,
                max_low_speed_ratio=0.4,
                min_forward_ratio=0.8,
                min_horizontal_ratio=0.8,
                min_jump_ratio=0.8,
                min_side_ratio=0.8,
                min_yaw_unique=10,
            )
            markdown = plausibility.build_markdown({"runs": [summary]})

        self.assertFalse(summary["passes_gate"])
        self.assertIn("stationary 60.0% > 25.0%", summary["players"][0]["failure_reasons"])
        self.assertIn("FAIL", markdown)

    def test_summarize_run_prefers_ed_matching_for_duplicate_names(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "run-duplicate-names"
            write_duplicate_name_run(run_dir)

            summary = plausibility.summarize_run(
                run_dir,
                expected_forward=None,
                max_stationary_ratio=0.25,
                max_low_speed_ratio=0.4,
                min_forward_ratio=0.8,
                min_horizontal_ratio=0.8,
                min_jump_ratio=0.8,
                min_side_ratio=0.8,
                min_yaw_unique=10,
            )
            markdown = plausibility.build_markdown({"runs": [summary]})

        self.assertTrue(summary["passes_gate"])
        self.assertEqual(summary["expected_forward"], 600)
        self.assertEqual(summary["players"][0]["command_count"], 12)
        self.assertEqual(summary["players"][1]["command_count"], 12)
        self.assertEqual(summary["players"][0]["forward_expected_ratio"], 1.0)
        self.assertIn("duplicate player names present", summary["warnings"][0])
        self.assertIn("Warning", markdown)

    def test_summarize_run_can_gate_variable_horizontal_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "run-horizontal"
            write_run(run_dir, stationary_ratio=0.05)
            commands_path = run_dir / "moveprobe-commands.json"
            commands = json.loads(commands_path.read_text(encoding="utf-8"))
            for index, row in enumerate(commands["commands"]):
                row["move"] = {"forward": 400 - index, "side": 200 + index}
            commands_path.write_text(json.dumps(commands), encoding="utf-8")

            summary = plausibility.summarize_run(
                run_dir,
                expected_forward=800,
                max_stationary_ratio=0.25,
                max_low_speed_ratio=0.4,
                min_forward_ratio=0.0,
                min_horizontal_ratio=0.8,
                min_jump_ratio=0.8,
                min_side_ratio=0.8,
                min_yaw_unique=10,
            )

        self.assertTrue(summary["passes_gate"])
        self.assertEqual(summary["players"][0]["forward_expected_ratio"], 0.0)
        self.assertEqual(summary["players"][0]["horizontal_move_ratio"], 1.0)

    def test_summarize_run_reports_yaw_delta_and_backward_ratios(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "run-diagnostic"
            write_diagnostic_run(run_dir)

            summary = plausibility.summarize_run(
                run_dir,
                expected_forward=800,
                max_stationary_ratio=0.25,
                max_low_speed_ratio=0.4,
                min_forward_ratio=0.0,
                min_horizontal_ratio=0.8,
                min_jump_ratio=0.8,
                min_side_ratio=0.8,
                min_yaw_unique=10,
            )
            markdown = plausibility.build_markdown({"runs": [summary]})

        player = summary["players"][0]
        self.assertTrue(player["passes_gate"])
        self.assertEqual(player["backward_command_ratio"], 0.5)
        self.assertEqual(player["yaw_delta_sample_count"], 12)
        self.assertEqual(player["yaw_delta_abs_avg"], 90.0)
        self.assertEqual(player["yaw_delta_over_90_ratio"], 0.5)
        self.assertIn("Abs delta avg", markdown)


if __name__ == "__main__":
    unittest.main()
