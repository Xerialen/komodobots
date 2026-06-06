from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import decide_cadence_normalization as cadence


def sample_aggregate() -> dict[str, object]:
    return {
        "stage": "s7c-test",
        "map": "dm3",
        "bot_source_run_ids": ["bot-run"],
        "reference_rows": [
            {
                "target_player": "Milton",
                "matched_player": "Milton",
                "run_id": "m1",
                "jump_cadence_per_min": 44.9,
                "stationary_time_ratio": 0.059,
                "low_speed_time_ratio": 0.124,
                "airborne_proxy_time_ratio": 0.351,
            },
            {
                "target_player": "Milton",
                "matched_player": "Milton",
                "run_id": "m2",
                "jump_cadence_per_min": 42.0,
                "stationary_time_ratio": 0.085,
                "low_speed_time_ratio": 0.156,
                "airborne_proxy_time_ratio": 0.308,
            },
            {
                "target_player": "carapace",
                "matched_player": "carapace",
                "run_id": "c1",
                "jump_cadence_per_min": 44.0,
                "stationary_time_ratio": 0.115,
                "low_speed_time_ratio": 0.196,
                "airborne_proxy_time_ratio": 0.342,
            },
            {
                "target_player": "carapace",
                "matched_player": "carapace",
                "run_id": "c2",
                "jump_cadence_per_min": 40.4,
                "stationary_time_ratio": 0.087,
                "low_speed_time_ratio": 0.171,
                "airborne_proxy_time_ratio": 0.282,
            },
            {
                "target_player": "yeti",
                "matched_player": "yeti",
                "run_id": "y1",
                "jump_cadence_per_min": 48.6,
                "stationary_time_ratio": 0.075,
                "low_speed_time_ratio": 0.154,
                "airborne_proxy_time_ratio": 0.359,
            },
            {
                "target_player": "yeti",
                "matched_player": "yeti",
                "run_id": "y2",
                "jump_cadence_per_min": 51.0,
                "stationary_time_ratio": 0.083,
                "low_speed_time_ratio": 0.168,
                "airborne_proxy_time_ratio": 0.360,
            },
        ],
        "bot_rows": [
            {
                "player": "/ bro",
                "run_id": "bot-run",
                "jump_cadence_per_min": 91.7,
                "stationary_time_ratio": 0.004,
                "low_speed_time_ratio": 0.261,
                "airborne_proxy_time_ratio": 0.442,
            },
            {
                "player": "/ goldenboy",
                "run_id": "bot-run",
                "jump_cadence_per_min": 43.3,
                "stationary_time_ratio": 0.025,
                "low_speed_time_ratio": 0.189,
                "airborne_proxy_time_ratio": 0.248,
            },
        ],
    }


class CadenceNormalizationDecisionTests(unittest.TestCase):
    def test_build_report_keeps_cadence_diagnostic_when_air_proxy_relation_is_high(self) -> None:
        report = cadence.build_report(sample_aggregate(), stage="s7d-test")
        axes = {axis["field"]: axis for axis in report["normalization_axes"]}

        moving_bots = {row["player"]: row for row in axes["jump_cadence_per_non_low_speed_min"]["bot_rows"]}
        self.assertEqual(moving_bots["/ bro"]["against_reference"], "above_reference_max")
        self.assertEqual(moving_bots["/ goldenboy"]["against_reference"], "within_reference_range")

        air_bots = {row["player"]: row for row in axes["jump_cadence_per_airborne_proxy_min"]["bot_rows"]}
        self.assertEqual(air_bots["/ bro"]["against_reference"], "above_reference_max")
        self.assertEqual(air_bots["/ goldenboy"]["against_reference"], "above_reference_max")
        self.assertEqual(
            report["decision"]["verdict"],
            "cadence_stays_diagnostic_not_controller_target",
        )

    def test_zero_denominator_becomes_unavailable(self) -> None:
        aggregate = sample_aggregate()
        aggregate["bot_rows"][0]["airborne_proxy_time_ratio"] = 0.0

        report = cadence.build_report(aggregate, stage="s7d-test")
        axis = next(
            item for item in report["normalization_axes"] if item["field"] == "jump_cadence_per_airborne_proxy_min"
        )
        bro = next(row for row in axis["bot_rows"] if row["player"] == "/ bro")

        self.assertIsNone(bro["value"])
        self.assertEqual(bro["against_reference"], "unavailable")


if __name__ == "__main__":
    unittest.main()
