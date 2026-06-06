from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import design_context_gated_probe as s7l


def player_row(
    bucket: str,
    *,
    player: str = "/ bot",
    run_id: str = "run",
    segments: int = 100,
    p50: float = 150.0,
    sampled: float = 0.9,
    strong: float = 0.9,
    low_dir: float = 0.0,
    water: float = 0.0,
) -> dict[str, object]:
    return {
        "bucket": bucket,
        "label": bucket,
        "player": player,
        "run_id": run_id,
        "segment_count": segments,
        "sampled_command_ratio": sampled,
        "strong_command_ratio": strong,
        "probe_active_ratio": 0.1,
        "low_dir_speed_ratio": low_dir,
        "water_path_ratio": water,
        "speed": {"p50": p50},
    }


def s7k_like(rows: list[dict[str, object]]) -> dict[str, object]:
    return {
        "stage": "s7k-test",
        "map": "dm3",
        "warnings": [],
        "decision": {"frogbots_vs_from_scratch": "continue_frogbots_for_next_bounded_stage"},
        "player_bucket_context": rows,
    }


def ready_rows() -> list[dict[str, object]]:
    return [
        player_row("pre_air_window_segments", player="/ bro", run_id="a", segments=80, p50=202.0),
        player_row("pre_air_window_segments", player="/ goldenboy", run_id="a", segments=90, p50=256.0),
        player_row("airborne_proxy_segments", player="/ bro", run_id="a", segments=90, p50=102.0),
        player_row("airborne_proxy_segments", player="/ goldenboy", run_id="a", segments=90, p50=181.0),
        player_row("pre_air_window_segments", player="/ route", run_id="b", segments=300, p50=97.0, low_dir=0.7, water=0.6),
        player_row("airborne_proxy_segments", player="/ route", run_id="b", segments=300, p50=99.0, low_dir=0.7, water=0.6),
        player_row("non_airborne_segments", player="/ route", run_id="b", segments=300, p50=100.0, low_dir=0.7, water=0.6),
    ]


class ContextGatedProbeDesignTests(unittest.TestCase):
    def test_build_report_requires_clean_context_target_slices(self) -> None:
        report = s7l.build_report(s7k_like(ready_rows()), stage="s7l-test")

        s7l.validate_report(report)
        self.assertEqual(report["decision"]["verdict"], "ready_to_implement_context_gated_air_transition_probe")
        contract = report["probe_contract"]
        clean_targets = {row["bucket"]: row for row in contract["required_clean_target_buckets"]}
        self.assertTrue(clean_targets["pre_air_window_segments"]["ready_for_probe_claim"])
        self.assertTrue(clean_targets["airborne_proxy_segments"]["ready_for_probe_claim"])

        route_targets = {row["bucket"]: row for row in contract["route_guardrail_buckets"]}
        self.assertGreater(route_targets["pre_air_window_segments"]["route_segments"], 0)
        self.assertIn("route_context_is_guardrail_not_success", [rule["id"] for rule in report["context_gate_rules"]])

    def test_validate_blocks_when_clean_air_context_is_too_sparse(self) -> None:
        dirty_only = [
            player_row("pre_air_window_segments", low_dir=0.8, water=0.7),
            player_row("airborne_proxy_segments", low_dir=0.8, water=0.7),
            player_row("non_airborne_segments", low_dir=0.8, water=0.7),
        ]
        report = s7l.build_report(s7k_like(dirty_only), stage="s7l-test")

        with self.assertRaises(s7l.ContextGatedProbeInputError):
            s7l.validate_report(report)

    def test_wrong_s7k_decision_blocks_before_writing(self) -> None:
        source = s7k_like(ready_rows())
        source["decision"] = {"frogbots_vs_from_scratch": "no_decision"}
        report = s7l.build_report(source, stage="s7l-test")

        with self.assertRaises(s7l.ContextGatedProbeInputError):
            s7l.validate_report(report)

    def test_main_writes_custom_json_and_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            s7k_path = root / "s7k.json"
            output_json = root / "json" / "out.json"
            output_md = root / "md" / "out.md"
            s7k_path.write_text(json.dumps(s7k_like(ready_rows())), encoding="utf-8")

            s7l.main(
                [
                    "--s7k",
                    str(s7k_path),
                    "--output-json",
                    str(output_json),
                    "--output-md",
                    str(output_md),
                ]
            )

            self.assertTrue(output_json.exists())
            self.assertTrue(output_md.exists())


if __name__ == "__main__":
    unittest.main()
