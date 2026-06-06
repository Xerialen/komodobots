from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import summarize_reference_aggregate


def write_summary(path: Path, *, run_id: str, demo: str, player: str, avg: float, p95: float, air: float) -> None:
    path.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "demo": {"name": demo, "sha256": run_id, "map": "dm3"},
                "match": {"map": "dm3", "map_title": "The Abandoned Base", "duration_ms": 1200000},
                "movement_players": [
                    {
                        "name": player,
                        "avg_horizontal_speed_qu_per_s": avg,
                        "p95_horizontal_speed_qu_per_s": p95,
                        "stationary_time_ratio": 0.05,
                        "low_speed_time_ratio": 0.1,
                        "airborne_proxy_time_ratio": air,
                        "jump_cadence_per_min": 45,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


class ReferenceAggregateTests(unittest.TestCase):
    def test_portable_path_serializes_repo_paths_relative(self) -> None:
        path = REPO_ROOT / "experiments" / "ktx_moveprobe" / "evidence" / "moveprobe-s3g-summary.json"

        self.assertEqual(
            summarize_reference_aggregate.portable_path(path),
            "experiments/ktx_moveprobe/evidence/moveprobe-s3g-summary.json",
        )

    def test_build_aggregate_classifies_bot_rows_against_reference_range(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            milton = root / "milton.json"
            yeti = root / "yeti.json"
            write_summary(milton, run_id="m", demo="m.mvd", player="Milton", avg=310, p95=530, air=0.35)
            write_summary(yeti, run_id="y", demo="y.mvd", player="yeti", avg=280, p95=490, air=0.30)
            bot_summary = root / "bot.json"
            bot_summary.write_text(
                json.dumps(
                    {
                        "runs": [
                            {
                                "run_id": "bot",
                                "map": "dm3",
                                "players": [
                                    {
                                        "player": "/ bro",
                                        "avg_horizontal_speed_qu_per_s": 190,
                                        "p95_horizontal_speed_qu_per_s": 361,
                                        "stationary_time_ratio": 0.004,
                                        "low_speed_time_ratio": 0.261,
                                        "airborne_proxy_time_ratio": 0.442,
                                        "jump_cadence_per_min": 91.7,
                                    }
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            aggregate = summarize_reference_aggregate.build_aggregate(
                targets=[("Milton", milton), ("yeti", yeti)],
                bot_summary_path=bot_summary,
                map_name="dm3",
                stage="s5b-test",
            )

        self.assertEqual(aggregate["reference_count"], 2)
        self.assertEqual(aggregate["reference_rows"][0]["matched_player"], "Milton")
        avg_range = next(row for row in aggregate["ranges"] if row["field"] == "avg_horizontal_speed_qu_per_s")
        self.assertEqual(avg_range["reference"]["min"], 280.0)
        self.assertEqual(avg_range["reference"]["max"], 310.0)
        bro = aggregate["bot_comparison"][0]
        self.assertEqual(bro["against_reference_range"]["avg_horizontal_speed_qu_per_s"], "below_human_min")
        self.assertEqual(bro["against_reference_range"]["airborne_proxy_time_ratio"], "above_human_max")
        self.assertEqual(bro["against_reference_range"]["jump_cadence_per_min"], "above_human_max")
        self.assertEqual(aggregate["bot_rows"][0]["jump_cadence_per_min"], 91.7)
        self.assertEqual(aggregate["bot_source_run_ids"], ["bot"])

    def test_build_aggregate_excludes_missing_reference_metric_from_range(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            milton = root / "milton.json"
            yeti = root / "yeti.json"
            write_summary(milton, run_id="m", demo="m.mvd", player="Milton", avg=310, p95=530, air=0.35)
            write_summary(yeti, run_id="y", demo="y.mvd", player="yeti", avg=280, p95=490, air=0.30)
            yeti_summary = json.loads(yeti.read_text(encoding="utf-8"))
            del yeti_summary["movement_players"][0]["p95_horizontal_speed_qu_per_s"]
            yeti.write_text(json.dumps(yeti_summary), encoding="utf-8")
            bot_summary = root / "bot.json"
            bot_summary.write_text(json.dumps({"runs": []}), encoding="utf-8")

            aggregate = summarize_reference_aggregate.build_aggregate(
                targets=[("Milton", milton), ("yeti", yeti)],
                bot_summary_path=bot_summary,
                map_name="dm3",
                stage="s5b-test",
            )

        p95_range = next(row for row in aggregate["ranges"] if row["field"] == "p95_horizontal_speed_qu_per_s")
        self.assertEqual(p95_range["reference"]["count"], 1)
        self.assertEqual(p95_range["reference"]["min"], 530.0)
        self.assertEqual(p95_range["reference"]["max"], 530.0)
        self.assertIsNone(aggregate["reference_rows"][1]["p95_horizontal_speed_qu_per_s"])

    def test_build_aggregate_warns_when_all_reference_rows_excluded_by_map(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            milton = root / "milton.json"
            write_summary(milton, run_id="m", demo="m.mvd", player="Milton", avg=310, p95=530, air=0.35)
            bot_summary = root / "bot.json"
            bot_summary.write_text(json.dumps({"runs": []}), encoding="utf-8")

            aggregate = summarize_reference_aggregate.build_aggregate(
                targets=[("Milton", milton)],
                bot_summary_path=bot_summary,
                map_name="dm2",
                stage="s5b-test",
            )

        self.assertEqual(aggregate["reference_count"], 0)
        self.assertEqual(len(aggregate["excluded_reference_rows"]), 1)
        self.assertIn("No reference rows matched map 'dm2'", aggregate["warnings"][0])


if __name__ == "__main__":
    unittest.main()
