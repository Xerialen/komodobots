from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from score_getandmaintainspeed import score_run


class ScoreGetAndMaintainSpeedTests(unittest.TestCase):
    def test_scores_event_and_command_speed_against_reference(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "synthetic-run"
            run_dir.mkdir()
            reference = Path(temp_dir) / "mouse-analysis.json"
            reference.write_text(
                json.dumps(
                    {
                        "source_sha256": "abc",
                        "speed_qu_per_s": {
                            "p95": 900.0,
                            "max": 930.0,
                            "time_above": {"900": 0.1},
                        },
                        "mouse": {
                            "yaw_rate_abs_p95_deg_s": 100.0,
                            "yaw_reversals_per_s": 66.7,
                        },
                    }
                ),
                encoding="utf-8",
            )
            (run_dir / "movement-metrics.json").write_text(
                json.dumps(
                    {
                        "players": [
                            {
                                "slot": 1,
                                "p50_horizontal_speed_qu_per_s": 910.0,
                                "p90_horizontal_speed_qu_per_s": 930.0,
                                "p95_horizontal_speed_qu_per_s": 940.0,
                                "max_horizontal_speed_qu_per_s": 950.0,
                                "avg_horizontal_speed_qu_per_s": 920.0,
                                "active_time_s": 0.3,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            events = [
                {"kind": 5, "time": 0.0, "data": {"PlayerNum": 1, "Origin": [0, 0, 0], "TimeMs": 0}},
                {"kind": 5, "time": 0.1, "data": {"PlayerNum": 1, "Origin": [95, 0, 0], "TimeMs": 100}},
                {"kind": 5, "time": 0.2, "data": {"PlayerNum": 1, "Origin": [190, 0, 0], "TimeMs": 200}},
                {"kind": 5, "time": 0.3, "data": {"PlayerNum": 1, "Origin": [285, 0, 0], "TimeMs": 300}},
            ]
            (run_dir / "events.txt").write_text(
                "\n".join(json.dumps(event) for event in events) + "\n",
                encoding="utf-8",
            )
            commands = []
            for index, yaw in enumerate([0.0, 1.0, 0.0, 1.0]):
                commands.append(
                    {
                        "time_s": index * 0.01,
                        "msec": 100,
                        "angles": {"yaw": yaw},
                        "move": {"side": 950 if index % 2 == 0 else -950},
                        "replay_state": {"cursor": 1655 + index},
                        "s25_state": {"speed": 950.0},
                    }
                )
            (run_dir / "moveprobe-commands.json").write_text(
                json.dumps({"commands": commands}),
                encoding="utf-8",
            )

            report = score_run(run_dir, reference_path=reference)

        self.assertEqual(report["event_speed"]["time_above_high_s"], 0.3)
        self.assertEqual(report["command_speed"]["time_above_high_s"], 0.4)
        self.assertTrue(report["checks"]["event_high_time_beats_human"])
        self.assertEqual(report["verdict"], "PASS")

    def test_rejects_runs_that_only_hit_peak_without_sustaining_speed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "synthetic-run"
            run_dir.mkdir()
            reference = Path(temp_dir) / "mouse-analysis.json"
            reference.write_text(
                json.dumps(
                    {
                        "speed_qu_per_s": {
                            "p95": 900.0,
                            "max": 930.0,
                            "time_above": {"900": 1.0},
                        },
                        "mouse": {
                            "yaw_rate_abs_p95_deg_s": 100.0,
                            "yaw_reversals_per_s": 1.0,
                        },
                    }
                ),
                encoding="utf-8",
            )
            (run_dir / "movement-metrics.json").write_text(
                json.dumps({"players": [{"slot": 1}]}),
                encoding="utf-8",
            )
            events = [
                {"kind": 5, "time": 0.0, "data": {"PlayerNum": 1, "Origin": [0, 0, 0], "TimeMs": 0}},
                {"kind": 5, "time": 0.1, "data": {"PlayerNum": 1, "Origin": [95, 0, 0], "TimeMs": 100}},
                {"kind": 5, "time": 0.2, "data": {"PlayerNum": 1, "Origin": [96, 0, 0], "TimeMs": 200}},
            ]
            (run_dir / "events.txt").write_text(
                "\n".join(json.dumps(event) for event in events) + "\n",
                encoding="utf-8",
            )
            commands = [
                {
                    "time_s": 0.0,
                    "msec": 100,
                    "angles": {"yaw": 0.0},
                    "move": {"side": 950},
                    "replay_state": {"cursor": 1655},
                    "s25_state": {"speed": 950.0},
                },
                {
                    "time_s": 0.01,
                    "msec": 100,
                    "angles": {"yaw": 1.0},
                    "move": {"side": -950},
                    "replay_state": {"cursor": 1656},
                    "s25_state": {"speed": 10.0},
                },
            ]
            (run_dir / "moveprobe-commands.json").write_text(
                json.dumps({"commands": commands}),
                encoding="utf-8",
            )

            report = score_run(run_dir, reference_path=reference)

        self.assertFalse(report["checks"]["event_high_time_beats_human"])
        self.assertEqual(report["verdict"], "FAIL")


if __name__ == "__main__":
    unittest.main()
