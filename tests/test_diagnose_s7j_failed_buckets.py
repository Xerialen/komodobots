from __future__ import annotations

import sys
import tempfile
import unittest
import json
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
    def test_load_context_source_supplies_committed_reproducibility_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "context.json"
            path.write_text(
                '{"player_bucket_context": [{"bucket": "pre_air_window_segments", "segment_count": 1}]}',
                encoding="utf-8",
            )

            rows = s7k.load_context_source(path)

        self.assertEqual(rows[0]["bucket"], "pre_air_window_segments")

    def test_output_markdown_parent_is_created_for_custom_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            s7j = root / "s7j.json"
            s7g = root / "s7g.json"
            context_source = root / "context" / "source.json"
            output_json = root / "json" / "out.json"
            output_md = root / "md" / "out.md"
            s7j.write_text(
                json.dumps(
                    {
                        "map": "dm3",
                        "bucket_changes": [
                            failed_change("pre_air_window_segments"),
                            failed_change("airborne_proxy_segments"),
                            failed_change("non_airborne_segments"),
                        ],
                        "decision": {},
                        "land_speed_comparison": {"bot_players": []},
                    }
                ),
                encoding="utf-8",
            )
            s7g.write_text('{"decision": {}}', encoding="utf-8")
            context_source.parent.mkdir()
            context_source.write_text(
                json.dumps(
                    {
                        "player_bucket_context": [
                            context("pre_air_window_segments"),
                            context("airborne_proxy_segments"),
                            context("non_airborne_segments", low_dir=0.8, water=0.7),
                        ]
                    }
                ),
                encoding="utf-8",
            )

            s7k.main(
                [
                    "--s7j",
                    str(s7j),
                    "--s7g",
                    str(s7g),
                    "--context-source",
                    str(context_source),
                    "--output-json",
                    str(output_json),
                    "--output-md",
                    str(output_md),
                ]
            )

            self.assertTrue(output_md.exists())

    def test_context_source_payload_records_source_and_rows(self) -> None:
        payload = s7k.context_source_payload(
            [{"bucket": "non_airborne_segments"}],
            stage="s7k-test",
            s7j_path=REPO_ROOT / "s7j.json",
            transition_window_ms=400,
            command_margin_ms=150,
        )

        self.assertEqual(payload["schema"], "komodobots.s7j_failed_bucket_context_source.v1")
        self.assertEqual(payload["player_bucket_context"][0]["bucket"], "non_airborne_segments")

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
