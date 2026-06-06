from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import broaden_cadence_evidence as broadening


def reference_aggregate() -> dict[str, object]:
    return {
        "stage": "s7c-test",
        "map": "dm3",
        "reference_rows": [
            {
                "target_player": "Milton",
                "run_id": "m1",
                "jump_cadence_per_min": 44.9,
                "stationary_time_ratio": 0.059,
                "low_speed_time_ratio": 0.124,
                "airborne_proxy_time_ratio": 0.351,
            },
            {
                "target_player": "carapace",
                "run_id": "c1",
                "jump_cadence_per_min": 40.4,
                "stationary_time_ratio": 0.087,
                "low_speed_time_ratio": 0.171,
                "airborne_proxy_time_ratio": 0.282,
            },
            {
                "target_player": "yeti",
                "run_id": "y1",
                "jump_cadence_per_min": 51.0,
                "stationary_time_ratio": 0.083,
                "low_speed_time_ratio": 0.168,
                "airborne_proxy_time_ratio": 0.360,
            },
        ],
    }


def write_metrics(root: Path, run_id: str, players: list[dict[str, object]]) -> None:
    run_dir = root / run_id
    run_dir.mkdir(parents=True)
    payload = {
        "run": {"run_id": run_id, "map_command": "dm3"},
        "players": players,
    }
    (run_dir / "movement-metrics.json").write_text(json.dumps(payload), encoding="utf-8")


def player(name: str, cadence: float, air_ratio: float, low_ratio: float = 0.1) -> dict[str, object]:
    return {
        "name": name,
        "spectator": False,
        "avg_horizontal_speed_qu_per_s": 200.0,
        "p95_horizontal_speed_qu_per_s": 360.0,
        "stationary_time_ratio": 0.02,
        "low_speed_time_ratio": low_ratio,
        "airborne_proxy_time_ratio": air_ratio,
        "airborne_proxy_count": 10,
        "jump_cadence_per_min": cadence,
        "avg_airborne_proxy_duration_ms": 250.0,
        "avg_airborne_proxy_z_delta_qu": 12.0,
        "avg_landing_pre_speed_qu_per_s": 100.0,
        "avg_landing_post_speed_qu_per_s": 120.0,
        "avg_post_landing_speed_delta_qu_per_s": 20.0,
        "avg_post_landing_speed_loss_ratio": -0.1,
    }


class CadenceEvidenceBroadeningTests(unittest.TestCase):
    def test_broadened_mode7_rows_keep_air_proxy_cadence_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_metrics(root, "r1", [player("/ bro", 90.0, 0.45), player("/ goldenboy", 43.0, 0.25)])
            write_metrics(root, "r2", [player("/ bro", 120.0, 0.50), player("/ goldenboy", 25.0, 0.15)])
            write_metrics(root, "r3", [player("/ bro", 110.0, 0.49), player("/ goldenboy", 20.0, 0.10)])

            report = broadening.build_report(
                reference_aggregate(),
                stage="s7e-test",
                bot_run_ids=["r1", "r2", "r3"],
                artifacts_root=root,
            )

        axes = {axis["field"]: axis for axis in report["cadence_axes"]}
        self.assertEqual(report["bot_count"], 6)
        self.assertEqual(
            axes["jump_cadence_per_airborne_proxy_min"]["bot_relation"],
            "all_bots_above_reference_range",
        )
        self.assertEqual(
            report["decision"]["verdict"],
            "cadence_stays_diagnostic_after_broadened_mode7_rows",
        )

    def test_missing_run_records_warning_without_fake_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = broadening.build_report(
                reference_aggregate(),
                stage="s7e-test",
                bot_run_ids=["missing-run"],
                artifacts_root=Path(tmp),
            )

        self.assertEqual(report["bot_count"], 0)
        self.assertIn("missing-run", report["warnings"][0])


if __name__ == "__main__":
    unittest.main()
