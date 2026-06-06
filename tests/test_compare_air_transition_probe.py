from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import compare_air_transition_probe as probe_result


def change(bucket: str, baseline: float, current: float | None, *, count: int = 2) -> dict[str, object]:
    return {
        "bucket": bucket,
        "baseline_bot_p50_speed_qu_per_s": baseline,
        "current_bot_p50_speed_qu_per_s": current,
        "current_bot_player_count": count if current is not None else 0,
        "ratio_to_s7g_baseline": round(current / baseline, 3) if current is not None else None,
        "improved_vs_s7g_baseline": current is not None and current > baseline,
        "regressed_more_than_5pct": current is not None and current < baseline * 0.95,
    }


def complete_changes(**overrides: float | None) -> list[dict[str, object]]:
    values = {
        "pre_air_window_segments": (200.0, 205.0),
        "airborne_proxy_segments": (120.0, 130.0),
        "post_air_window_segments": (180.0, 185.0),
        "all_segments": (220.0, 225.0),
        "non_airborne_segments": (310.0, 310.0),
        "route_low_dir_speed_segments": (140.0, 142.0),
        "route_water_path_segments": (95.0, 95.0),
    }
    return [
        change(bucket, baseline, overrides.get(bucket, current))
        for bucket, (baseline, current) in values.items()
    ]


def cadence_axes() -> list[dict[str, object]]:
    return [
        {"field": field, "bot": {"count": 2, "min": 1.0, "max": 2.0}}
        for field in probe_result.CADENCE_FIELDS
    ]


def activation(sample_count: int = 12, active_count: int = 6) -> dict[str, object]:
    return {
        "sample_count": sample_count,
        "transition_active_count": active_count,
        "transition_active_ratio": round(active_count / sample_count, 3) if sample_count else None,
    }


class AirTransitionProbeResultTests(unittest.TestCase):
    def test_all_segment_win_without_air_gain_rejects(self) -> None:
        changes = complete_changes(
            pre_air_window_segments=200.0,
            airborne_proxy_segments=120.0,
            post_air_window_segments=180.0,
            all_segments=230.0,
        )

        conditions = probe_result.evaluate_stop_conditions(changes, cadence_axes(), activation())
        decision = probe_result.make_decision(changes, conditions)

        by_id = {condition["id"]: condition for condition in conditions}
        self.assertEqual(by_id["all_segment_proxy_win"]["status"], "reject")
        self.assertEqual(decision["verdict"], "air_transition_probe_rejected_by_s7i_stop_conditions")

    def test_missing_probe_activation_is_inconclusive(self) -> None:
        conditions = probe_result.evaluate_stop_conditions(complete_changes(), cadence_axes(), activation(0, 0))
        decision = probe_result.make_decision(complete_changes(), conditions)

        by_id = {condition["id"]: condition for condition in conditions}
        self.assertEqual(by_id["probe_activation_reporting"]["status"], "inconclusive")
        self.assertEqual(decision["verdict"], "air_transition_probe_inconclusive")

    def test_missing_water_path_reporting_is_inconclusive(self) -> None:
        changes = complete_changes(route_water_path_segments=None)
        conditions = probe_result.evaluate_stop_conditions(changes, cadence_axes(), activation())
        decision = probe_result.make_decision(changes, conditions)

        by_id = {condition["id"]: condition for condition in conditions}
        self.assertEqual(by_id["water_path_guardrail"]["status"], "inconclusive")
        self.assertIn("water_path_guardrail", decision["inconclusive_stop_conditions"])


if __name__ == "__main__":
    unittest.main()
