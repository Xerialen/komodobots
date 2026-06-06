from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import inspect_airborne_proxy_segments as inspector


def write_event(handle, kind: int, time_ms: int, data: dict[str, object]) -> None:
    handle.write(json.dumps({"kind": kind, "time": time_ms / 1000.0, "data": data}) + "\n")


def write_run(root: Path, run_id: str, player_name: str, origins: list[tuple[int, float, float, float]]) -> Path:
    run_dir = root / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "analysis.json").write_text(json.dumps({"match": {"duration": origins[-1][0], "map": "dm3"}}), encoding="utf-8")
    (run_dir / "movement-metrics.json").write_text(
        json.dumps(
            {
                "players": [
                    {
                        "name": player_name,
                        "avg_horizontal_speed_qu_per_s": 100.0,
                        "p95_horizontal_speed_qu_per_s": 200.0,
                        "airborne_proxy_time_ratio": 0.25,
                        "jump_cadence_per_min": 30.0,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with (run_dir / "events.txt").open("w", encoding="utf-8") as handle:
        write_event(
            handle,
            1,
            0,
            {
                "Player": {
                    "Slot": 2,
                    "Name": player_name,
                    "Spectator": False,
                },
                "TimeMs": 0,
            },
        )
        for time_ms, x, y, z in origins:
            write_event(handle, 5, time_ms, {"PlayerNum": 2, "Origin": [x, y, z], "TimeMs": time_ms})
    return run_dir


class AirborneProxySegmentInspectionTests(unittest.TestCase):
    def test_extract_airborne_runs_keeps_raw_duration_z_and_landing_speed(self) -> None:
        samples = [
            {"time_ms": 0, "origin": [0.0, 0.0, 0.0]},
            {"time_ms": 100, "origin": [10.0, 0.0, 0.0]},
            {"time_ms": 220, "origin": [30.0, 0.0, 6.0]},
            {"time_ms": 360, "origin": [60.0, 0.0, 12.0]},
            {"time_ms": 500, "origin": [80.0, 0.0, 6.0]},
            {"time_ms": 650, "origin": [100.0, 0.0, 0.0]},
            {"time_ms": 800, "origin": [130.0, 0.0, 0.0]},
        ]
        segments, dropped = inspector.build_segments(samples, inspector.thresholds())
        runs = inspector.extract_airborne_runs(segments, inspector.thresholds())

        self.assertEqual(dropped, 0)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["duration_ms"], 550)
        self.assertEqual(runs[0]["z_delta_qu"], 12.0)
        self.assertGreater(runs[0]["landing_pre_speed_qu_per_s"], 0)
        self.assertGreater(runs[0]["landing_post_speed_qu_per_s"], 0)

    def test_build_report_pivots_when_bot_air_segments_are_short_low_and_slow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ref_run = write_run(
                root,
                "ref-run",
                "Milton",
                [
                    (0, 0, 0, 0),
                    (100, 45, 0, 0),
                    (230, 100, 0, 45),
                    (430, 190, 0, 90),
                    (620, 280, 0, 45),
                    (800, 360, 0, 0),
                ],
            )
            bot_run = write_run(
                root,
                "bot-run",
                "/ bro",
                [
                    (0, 0, 0, 0),
                    (100, 8, 0, 0),
                    (240, 20, 0, 5),
                    (380, 32, 0, 0),
                    (520, 44, 0, 0),
                    (700, 60, 0, 0),
                ],
            )
            summary_path = root / "ref-summary.json"
            summary_path.write_text(json.dumps({"artifact_dir": str(ref_run)}), encoding="utf-8")
            reference_aggregate = {
                "stage": "s7c-test",
                "map": "dm3",
                "reference_rows": [
                    {
                        "matched_player": "Milton",
                        "target_player": "Milton",
                        "run_id": "ref-run",
                        "summary_path": str(summary_path),
                    }
                ],
            }
            bot_evidence = {
                "stage": "s7e-test",
                "bot_rows": [
                    {
                        "player": "/ bro",
                        "run_id": "bot-run",
                        "source_metrics_path": str(bot_run / "movement-metrics.json"),
                    }
                ],
            }

            report = inspector.build_report(reference_aggregate, bot_evidence, stage="s7f-test")

        self.assertEqual(report["warnings"], [])
        self.assertEqual(
            report["decision"]["verdict"],
            "pivot_from_cadence_to_air_rhythm_and_land_speed_gap",
        )


if __name__ == "__main__":
    unittest.main()
