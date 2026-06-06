from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import characterize_land_speed_gap as land_speed


def write_event(handle, kind: int, time_ms: int, data: dict[str, object]) -> None:
    handle.write(json.dumps({"kind": kind, "time": time_ms / 1000.0, "data": data}) + "\n")


def write_run(root: Path, run_id: str, player_name: str, origins: list[tuple[int, float, float, float]]) -> Path:
    run_dir = root / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "analysis.json").write_text(
        json.dumps({"match": {"duration": origins[-1][0], "map": "dm3"}}),
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


def write_commands(run_dir: Path, player_name: str, rows: list[tuple[float, int, int, dict[str, object]]]) -> None:
    commands = []
    for time_s, forward, side, route_state in rows:
        commands.append(
            {
                "name": player_name,
                "time_s": time_s,
                "move": {"forward": forward, "side": side, "up": 0},
                "route_state": route_state,
            }
        )
    (run_dir / "moveprobe-commands.json").write_text(json.dumps({"commands": commands}), encoding="utf-8")


class LandSpeedGapCharacterizationTests(unittest.TestCase):
    def test_build_report_isolates_air_transition_gap_without_generic_non_air_gap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reference = write_run(
                root,
                "ref-run",
                "Milton",
                [
                    (0, 0, 0, 0),
                    (100, 40, 0, 0),
                    (200, 80, 0, 0),
                    (300, 120, 0, 20),
                    (400, 160, 0, 40),
                    (500, 200, 0, 20),
                    (600, 240, 0, 0),
                    (700, 280, 0, 0),
                    (800, 320, 0, 0),
                    (900, 360, 0, 0),
                    (1000, 400, 0, 0),
                    (1100, 440, 0, 0),
                    (1200, 480, 0, 0),
                    (1300, 520, 0, 0),
                    (1400, 560, 0, 0),
                    (1500, 600, 0, 0),
                    (1600, 640, 0, 0),
                    (1700, 680, 0, 0),
                    (1800, 720, 0, 0),
                ],
            )
            bot = write_run(
                root,
                "bot-run",
                "/ bro",
                [
                    (0, 0, 0, 0),
                    (100, 10, 0, 0),
                    (200, 20, 0, 0),
                    (300, 25, 0, 5),
                    (400, 30, 0, 10),
                    (500, 35, 0, 5),
                    (600, 40, 0, 0),
                    (700, 50, 0, 0),
                    (800, 60, 0, 0),
                    (900, 70, 0, 0),
                    (1000, 80, 0, 0),
                    (1100, 120, 0, 0),
                    (1200, 160, 0, 0),
                    (1300, 200, 0, 0),
                    (1400, 240, 0, 0),
                    (1500, 280, 0, 0),
                    (1600, 320, 0, 0),
                    (1700, 360, 0, 0),
                    (1800, 400, 0, 0),
                ],
            )
            write_commands(
                bot,
                "/ bro",
                [
                    (0.25, 800, 0, {"dir_speed": 0.0, "path_state": land_speed.WATER_PATH}),
                    (0.35, 800, 0, {"dir_speed": 0.0, "path_state": land_speed.WATER_PATH}),
                    (0.45, 800, 0, {"dir_speed": 0.0, "path_state": land_speed.WATER_PATH}),
                    (0.55, 800, 0, {"dir_speed": 0.0, "path_state": land_speed.WATER_PATH}),
                ],
            )
            source = {
                "stage": "s7f-test",
                "map": "dm3",
                "reference_players": [
                    {
                        "group": "reference",
                        "identity": "Milton",
                        "run_id": "ref-run",
                        "events_path": str(reference / "events.txt"),
                    }
                ],
                "bot_players": [
                    {
                        "group": "bot",
                        "identity": "/ bro",
                        "run_id": "bot-run",
                        "events_path": str(bot / "events.txt"),
                    }
                ],
            }

            report = land_speed.build_report(
                source,
                stage="s7g-test",
                transition_window_ms=400,
                command_margin_ms=150,
            )

        land_speed.validate_report(report)
        self.assertEqual(
            report["decision"]["verdict"],
            "land_speed_gap_concentrates_around_air_transitions_and_route_low_dir_speed",
        )
        self.assertLess(report["decision"]["airborne_p50_ratio"], 0.2)
        self.assertGreaterEqual(report["decision"]["non_air_p50_ratio"], 0.85)
        self.assertEqual(
            report["bot_players"][0]["speed_buckets"]["route_water_path_segments"]["p50"],
            50.0,
        )

    def test_main_fails_before_writing_when_source_rows_are_unresolved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "source.json"
            output_json = root / "out" / "land-speed.json"
            output_md = root / "out" / "land-speed.md"
            source_path.write_text(
                json.dumps(
                    {
                        "stage": "s7f-test",
                        "map": "dm3",
                        "reference_players": [
                            {
                                "group": "reference",
                                "identity": "Milton",
                                "run_id": "missing-ref",
                                "events_path": str(root / "missing-ref" / "events.txt"),
                            }
                        ],
                        "bot_players": [],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(land_speed.ReportInputError):
                land_speed.main(
                    [
                        "--source",
                        str(source_path),
                        "--output-json",
                        str(output_json),
                        "--output-md",
                        str(output_md),
                    ]
                )

            self.assertFalse(output_json.exists())
            self.assertFalse(output_md.exists())


if __name__ == "__main__":
    unittest.main()
