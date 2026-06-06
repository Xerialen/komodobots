from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import summarize_player_movement_signatures as signatures


def sample_aggregate() -> dict[str, object]:
    return {
        "stage": "s5b-test",
        "map": "dm3",
        "reference_rows": [
            {
                "target_player": "Milton",
                "matched_player": "Milton",
                "demo": "milton.mvd",
                "run_id": "m",
                "avg_horizontal_speed_qu_per_s": 314.0,
                "p95_horizontal_speed_qu_per_s": 535.0,
                "stationary_time_ratio": 0.05,
                "low_speed_time_ratio": 0.10,
                "airborne_proxy_time_ratio": 0.35,
                "jump_cadence_per_min": 45.0,
            },
            {
                "target_player": "carapace",
                "matched_player": "carapace",
                "demo": "carapace.mvd",
                "run_id": "c",
                "avg_horizontal_speed_qu_per_s": 284.0,
                "p95_horizontal_speed_qu_per_s": 525.0,
                "stationary_time_ratio": 0.12,
                "low_speed_time_ratio": 0.20,
                "airborne_proxy_time_ratio": 0.34,
                "jump_cadence_per_min": 44.0,
            },
            {
                "target_player": "yeti",
                "matched_player": "yeti",
                "demo": "yeti.mvd",
                "run_id": "y",
                "avg_horizontal_speed_qu_per_s": 292.0,
                "p95_horizontal_speed_qu_per_s": 506.0,
                "stationary_time_ratio": 0.08,
                "low_speed_time_ratio": 0.15,
                "airborne_proxy_time_ratio": 0.36,
                "jump_cadence_per_min": 49.0,
            },
        ],
        "bot_rows": [
            {
                "run_id": "bot",
                "player": "/ bro",
                "avg_horizontal_speed_qu_per_s": 190.0,
                "p95_horizontal_speed_qu_per_s": 361.0,
                "stationary_time_ratio": 0.004,
                "low_speed_time_ratio": 0.26,
                "airborne_proxy_time_ratio": 0.44,
            },
            {
                "run_id": "bot",
                "player": "/ goldenboy",
                "avg_horizontal_speed_qu_per_s": 248.0,
                "p95_horizontal_speed_qu_per_s": 375.0,
                "stationary_time_ratio": 0.025,
                "low_speed_time_ratio": 0.19,
                "airborne_proxy_time_ratio": 0.25,
            },
        ],
    }


class PlayerMovementSignatureTests(unittest.TestCase):
    def test_build_report_keeps_land_speed_as_generic_gap(self) -> None:
        report = signatures.build_signature_report(sample_aggregate(), stage="s7a-test")

        axes = {axis["field"]: axis for axis in report["feature_axes"]}
        self.assertEqual(
            axes["p95_horizontal_speed_qu_per_s"]["interpretation"],
            "generic_human_vs_bot_land_speed_gap",
        )
        self.assertEqual(
            axes["p95_horizontal_speed_qu_per_s"]["bot_relation"]["relation"],
            "all_bots_below_reference_range",
        )
        gap = next(row for row in report["headline_gaps"] if row["field"] == "p95_horizontal_speed_qu_per_s")
        self.assertEqual(gap["gap_from_best_bot_to_reference_min"], 131.0)

    def test_build_report_marks_mixed_thin_axes_as_candidates(self) -> None:
        report = signatures.build_signature_report(sample_aggregate(), stage="s7a-test")
        axes = {axis["field"]: axis for axis in report["feature_axes"]}

        self.assertEqual(
            axes["low_speed_time_ratio"]["interpretation"],
            "candidate_player_style_axis_but_thin",
        )
        self.assertIn("low_speed_time_ratio", report["evidence_summary"]["candidate_player_style_axes"])
        self.assertTrue(report["stop_condition_triggered"])
        self.assertIn("single-demo", report["stop_condition_reason"])

    def test_missing_values_are_excluded_from_reference_spread(self) -> None:
        aggregate = sample_aggregate()
        aggregate["reference_rows"][2].pop("p95_horizontal_speed_qu_per_s")

        report = signatures.build_signature_report(aggregate, stage="s7a-test")
        p95_axis = next(axis for axis in report["feature_axes"] if axis["field"] == "p95_horizontal_speed_qu_per_s")

        self.assertEqual(p95_axis["reference"]["count"], 2)
        self.assertEqual(p95_axis["reference"]["min"], 525.0)
        player = next(row for row in report["player_signatures"] if row["player"] == "yeti")
        self.assertIsNone(player["values"]["p95_horizontal_speed_qu_per_s"])

    def test_reference_only_cadence_axis_is_not_compared_to_bots(self) -> None:
        report = signatures.build_signature_report(sample_aggregate(), stage="s7a-test")
        cadence_axis = next(axis for axis in report["feature_axes"] if axis["field"] == "jump_cadence_per_min")

        self.assertEqual(cadence_axis["interpretation"], "reference_only_candidate_style_axis")
        self.assertIsNone(cadence_axis["bot"])
        self.assertNotIn("bot_rows", cadence_axis)


if __name__ == "__main__":
    unittest.main()
