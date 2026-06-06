from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import design_air_transition_probe as probe_design


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


def s7g_like() -> dict[str, object]:
    return {
        "stage": "s7g-test",
        "map": "dm3",
        "warnings": [],
        "comparison": {
            "all_segments": comparison_row(334.0, 222.0, 0.665),
            "pre_air_window_segments": comparison_row(418.0, 207.0, 0.495),
            "airborne_proxy_segments": comparison_row(434.0, 123.0, 0.283),
            "post_air_window_segments": comparison_row(366.0, 185.0, 0.505),
            "non_airborne_segments": comparison_row(320.0, 312.0, 0.975),
            "route_low_dir_speed_segments": comparison_row(None, 141.0, None, count=4),
            "route_water_path_segments": comparison_row(None, 95.0, None, count=2),
        },
    }


def s7h_like(selected: str = "air_transition_horizontal_speed") -> dict[str, object]:
    return {
        "stage": "s7h-test",
        "map": "dm3",
        "warnings": [],
        "decision": {"selected_target": selected},
    }


def s7e_like() -> dict[str, object]:
    return {
        "stage": "s7e-test",
        "map": "dm3",
        "warnings": [],
        "cadence_axes": [
            {
                "field": "jump_cadence_per_min",
                "label": "Cadence/active min",
                "bot_relation": "mixed_bot_relation",
                "reference": {"min": 40.0, "max": 51.0, "count": 6},
                "bot": {"min": 18.0, "max": 139.0, "count": 6},
            },
            {
                "field": "jump_cadence_per_non_low_speed_min",
                "label": "Cadence/non-low-speed min",
                "bot_relation": "mixed_bot_relation",
                "reference": {"min": 49.0, "max": 61.0, "count": 6},
                "bot": {"min": 20.0, "max": 290.0, "count": 6},
            },
            {
                "field": "jump_cadence_per_airborne_proxy_min",
                "label": "Cadence/air-proxy min",
                "bot_relation": "all_bots_above_reference_range",
                "reference": {"min": 128.0, "max": 143.0, "count": 6},
                "bot": {"min": 164.0, "max": 274.0, "count": 6},
            },
        ],
    }


class AirTransitionProbeDesignTests(unittest.TestCase):
    def test_build_report_keeps_probe_design_narrow_and_guarded(self) -> None:
        report = probe_design.build_report(s7g_like(), s7h_like(), s7e_like(), stage="s7i-test")

        probe_design.validate_report(report)
        self.assertEqual(report["decision"]["verdict"], "ready_to_design_tiny_air_transition_probe")
        self.assertEqual(report["probe_contract"]["status"], "design_only_no_controller_behavior_changed")
        self.assertIn("route_water_path_segments", report["required_post_probe_measurements"])
        self.assertIn("jump_cadence_per_airborne_proxy_min", report["required_post_probe_measurements"])

        conditions = {condition["id"]: condition for condition in report["stop_conditions"]}
        self.assertEqual(conditions["all_segment_proxy_win"]["verdict"], "reject")
        self.assertEqual(conditions["water_path_guardrail"]["baseline_player_count"], 2)
        self.assertEqual(conditions["non_airborne_guardrail"]["baseline_p50_speed_qu_per_s"], 312.0)

    def test_wrong_s7h_target_blocks_design_before_writing(self) -> None:
        report = probe_design.build_report(
            s7g_like(),
            s7h_like("water_path_low_dir_speed_recovery"),
            s7e_like(),
            stage="s7i-test",
        )

        with self.assertRaises(probe_design.ProbeDesignInputError):
            probe_design.validate_report(report)

    def test_main_fails_before_writing_when_source_has_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            s7g_path = root / "s7g.json"
            s7h_path = root / "s7h.json"
            s7e_path = root / "s7e.json"
            output_json = root / "out" / "design.json"
            output_md = root / "out" / "design.md"
            s7g = s7g_like()
            s7g["warnings"] = ["missing rows"]
            s7g_path.write_text(json.dumps(s7g), encoding="utf-8")
            s7h_path.write_text(json.dumps(s7h_like()), encoding="utf-8")
            s7e_path.write_text(json.dumps(s7e_like()), encoding="utf-8")

            with self.assertRaises(probe_design.ProbeDesignInputError):
                probe_design.main(
                    [
                        "--s7g",
                        str(s7g_path),
                        "--s7h",
                        str(s7h_path),
                        "--s7e",
                        str(s7e_path),
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
