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
                min_jump_ratio=0.8,
                min_side_ratio=0.8,
                min_yaw_unique=10,
            )
            markdown = plausibility.build_markdown({"runs": [summary]})

        self.assertFalse(summary["passes_gate"])
        self.assertIn("stationary 60.0% > 25.0%", summary["players"][0]["failure_reasons"])
        self.assertIn("FAIL", markdown)


if __name__ == "__main__":
    unittest.main()
