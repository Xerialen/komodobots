from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import choose_controller_probe_target as probe_target


def summary(count: int, p50: float | None) -> dict[str, object]:
    return {
        "count": count,
        "min": p50,
        "mean": p50,
        "p50": p50,
        "p90": p50,
        "p95": p50,
        "max": p50,
    }


def comparison_row(reference: float | None, bot: float | None, ratio: float | None, *, count: int = 6) -> dict[str, object]:
    return {
        "label": "test",
        "reference_player_p50_speed": summary(count if reference is not None else 0, reference),
        "bot_player_p50_speed": summary(count if bot is not None else 0, bot),
        "bot_to_reference_p50_ratio": ratio,
    }


def s7g_like_report(*, route_rows: bool = True) -> dict[str, object]:
    bot_players = [
        {
            "group": "bot",
            "identity": "/ bro",
            "run_id": "bot-a",
            "route_state_segment_count": 100 if route_rows else 0,
            "speed_buckets": {
                "route_water_path_segments": summary(10 if route_rows else 0, 95.0 if route_rows else None),
                "route_low_dir_speed_segments": summary(12 if route_rows else 0, 130.0 if route_rows else None),
            },
        },
        {
            "group": "bot",
            "identity": "/ goldenboy",
            "run_id": "bot-b",
            "route_state_segment_count": 50 if route_rows else 0,
            "speed_buckets": {
                "route_water_path_segments": summary(4 if route_rows else 0, 100.0 if route_rows else None),
                "route_low_dir_speed_segments": summary(5 if route_rows else 0, 150.0 if route_rows else None),
            },
        },
    ]
    return {
        "stage": "s7g-test",
        "map": "dm3",
        "warnings": [],
        "bot_players": bot_players,
        "comparison": {
            "pre_air_window_segments": comparison_row(400.0, 200.0, 0.5),
            "airborne_proxy_segments": comparison_row(430.0, 120.0, 0.279),
            "post_air_window_segments": comparison_row(360.0, 180.0, 0.5),
            "non_airborne_segments": comparison_row(320.0, 312.0, 0.975),
            "route_water_path_segments": comparison_row(None, 95.0 if route_rows else None, None, count=2),
            "route_low_dir_speed_segments": comparison_row(None, 140.0 if route_rows else None, None, count=4),
        },
    }


class ControllerProbeTargetDecisionTests(unittest.TestCase):
    def test_build_report_prefers_air_transition_over_narrow_route_context(self) -> None:
        report = probe_target.build_report(s7g_like_report(), stage="s7h-test")

        probe_target.validate_report(report)
        self.assertEqual(report["decision"]["verdict"], "choose_air_transition_horizontal_speed_probe")
        self.assertEqual(report["decision"]["selected_target"], "air_transition_horizontal_speed")

        candidates = {candidate["target"]: candidate for candidate in report["candidates"]}
        self.assertEqual(candidates["air_transition_horizontal_speed"]["priority"], "preferred_first_probe_target")
        self.assertEqual(candidates["water_path_low_dir_speed_recovery"]["priority"], "secondary_guardrail_target")
        self.assertTrue(candidates["air_transition_horizontal_speed"]["human_comparable"])
        self.assertFalse(candidates["water_path_low_dir_speed_recovery"]["human_comparable"])

    def test_missing_route_diagnostics_does_not_block_air_transition_choice(self) -> None:
        report = probe_target.build_report(s7g_like_report(route_rows=False), stage="s7h-test")

        probe_target.validate_report(report)
        candidates = {candidate["target"]: candidate for candidate in report["candidates"]}
        self.assertEqual(report["decision"]["selected_target"], "air_transition_horizontal_speed")
        self.assertEqual(candidates["water_path_low_dir_speed_recovery"]["priority"], "candidate_needs_route_evidence")

    def test_main_fails_before_writing_when_source_warnings_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "source.json"
            output_json = root / "out" / "target.json"
            output_md = root / "out" / "target.md"
            source = s7g_like_report()
            source["warnings"] = ["missing bot row"]
            source_path.write_text(json.dumps(source), encoding="utf-8")

            with self.assertRaises(probe_target.DecisionInputError):
                probe_target.main(
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
