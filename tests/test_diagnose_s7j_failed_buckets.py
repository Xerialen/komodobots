from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import diagnose_s7j_failed_buckets as s7k


def failed_change(bucket: str) -> dict[str, object]:
    return {
        "bucket": bucket,
        "regressed_more_than_5pct": True,
        "baseline_bot_p50_speed_qu_per_s": 200.0,
        "current_bot_p50_speed_qu_per_s": 100.0,
        "ratio_to_s7g_baseline": 0.5,
    }


def context(
    bucket: str,
    *,
    sampled: float = 1.0,
    strong: float = 0.9,
    active: float = 0.4,
    low_dir: float = 0.0,
    water: float = 0.0,
) -> dict[str, object]:
    return {
        "bucket": bucket,
        "sampled_command_ratio": sampled,
        "strong_command_ratio": strong,
        "probe_active_ratio": active,
        "low_dir_speed_ratio": low_dir,
        "water_path_ratio": water,
    }


class S7jFailedBucketDiagnosisTests(unittest.TestCase):
    def test_non_airborne_water_context_is_route_guardrail_contamination(self) -> None:
        classification = s7k.classify_bucket_failure(
            failed_change("non_airborne_segments"),
            context("non_airborne_segments", low_dir=0.8, water=0.7),
        )

        self.assertEqual(classification["cause_class"], "route_or_map_context_guardrail_contamination")
        self.assertEqual(classification["confidence"], "high")

    def test_air_bucket_with_strong_commands_is_controller_policy_or_timing(self) -> None:
        classification = s7k.classify_bucket_failure(
            failed_change("airborne_proxy_segments"),
            context("airborne_proxy_segments", strong=0.95, active=0.3),
        )

        self.assertEqual(classification["cause_class"], "controller_policy_or_physics_timing")

    def test_air_bucket_with_route_context_is_mixed(self) -> None:
        classification = s7k.classify_bucket_failure(
            failed_change("pre_air_window_segments"),
            context("pre_air_window_segments", strong=0.95, low_dir=0.5),
        )

        self.assertEqual(classification["cause_class"], "mixed_controller_and_route_context")

    def test_low_sample_coverage_stays_measurement_risk(self) -> None:
        classification = s7k.classify_bucket_failure(
            failed_change("airborne_proxy_segments"),
            context("airborne_proxy_segments", sampled=0.2, strong=1.0),
        )

        self.assertEqual(classification["cause_class"], "measurement_alignment_risk")

    def test_decision_continues_frogbots_for_mixed_controller_route_failure(self) -> None:
        decision = s7k.make_decision(
            [
                {
                    "classification": {
                        "cause_class": "controller_policy_or_physics_timing",
                    }
                },
                {
                    "classification": {
                        "cause_class": "route_or_map_context_guardrail_contamination",
                    }
                },
            ]
        )

        self.assertEqual(decision["frogbots_vs_from_scratch"], "continue_frogbots_for_next_bounded_stage")


if __name__ == "__main__":
    unittest.main()
