from __future__ import annotations

import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import compare_qwd_sng_hybrid_probe as qwd_probe


def command_row(
    *,
    name: str = "/ goldenboy",
    active: bool = True,
    advanced: int = 4,
    index: int = 4,
    active_seconds: float = 1.25,
    side: int = 508,
    buttons: int = 2,
    path_state: int = 0,
    dir_speed: float = 1.0,
) -> dict[str, object]:
    return {
        "name": name,
        "buttons": buttons,
        "move": {"forward": 320, "side": side, "up": 0},
        "qwd_state": {
            "active": active,
            "control_point_index": index,
            "control_point_count": 14,
            "distance_qu": 72.0,
            "advanced_control_points": advanced,
            "complete": False,
            "active_seconds": active_seconds,
        },
        "route_state": {"path_state": path_state, "dir_speed": dir_speed},
        "water_state": {"waterlevel": 1},
        "probe_state": {"transition_active": False},
    }


def write_fake_run(
    root: Path,
    run_id: str,
    *,
    commands: list[dict[str, object]],
    low_speed: float = 0.10,
    stationary: float = 0.02,
) -> None:
    run_dir = root / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "run.env").write_text(
        "\n".join(
            [
                "MAP=dm3",
                "MOVEPROBE_MODE=9",
                "MOVEPROBE_FORWARDMOVE=320",
                "MOVEPROBE_SIDEMOVE=508",
                "MOVEPROBE_QWD_WAYPOINTS=1,2,3;4,5,6",
                "MOVEPROBE_QWD_POINT_RADIUS=96",
                "MOVEPROBE_QWD_START_RADIUS=192",
                "MOVEPROBE_LOG_COMMANDS=1",
                "MOVEPROBE_LOG_INTERVAL=0.1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "moveprobe-commands.json").write_text(
        json.dumps({"commands": commands}),
        encoding="utf-8",
    )
    (run_dir / "movement-metrics.json").write_text(
        json.dumps(
            {
                "players": [
                    {
                        "name": "/ goldenboy",
                        "stationary_time_ratio": stationary,
                        "low_speed_time_ratio": low_speed,
                        "avg_horizontal_speed_qu_per_s": 300.0,
                        "p95_horizontal_speed_qu_per_s": 420.0,
                        "jump_cadence_per_min": 44.0,
                        "airborne_proxy_time_ratio": 0.2,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


class QwdSngHybridProbeTests(unittest.TestCase):
    def test_parse_args_rejects_bad_run_id(self) -> None:
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            qwd_probe.parse_args(["--bot-run-id", "bad;touch nope"])

    def test_positive_bounded_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_fake_run(root, "run1", commands=[command_row(), command_row(active_seconds=1.6)])

            report = qwd_probe.build_report(
                {},
                stage="test",
                bot_run_ids=["run1"],
                artifacts_root=root,
                design_path=REPO_ROOT / "design.json",
            )

        self.assertEqual(report["decision"]["verdict"], "qwd_sng_hybrid_probe_positive_bounded_evidence")
        by_id = {condition["id"]: condition for condition in report["stop_condition_results"]}
        self.assertEqual(by_id["control_point_advancement"]["status"], "pass")
        self.assertEqual(by_id["diagnostic_preservation"]["status"], "pass")

    def test_no_activation_is_inconclusive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_fake_run(
                root,
                "run1",
                commands=[command_row(active=False, advanced=0, index=0, active_seconds=0.0)],
            )

            report = qwd_probe.build_report(
                {},
                stage="test",
                bot_run_ids=["run1"],
                artifacts_root=root,
                design_path=REPO_ROOT / "design.json",
            )

        self.assertEqual(report["decision"]["verdict"], "qwd_sng_hybrid_probe_inconclusive")
        by_id = {condition["id"]: condition for condition in report["stop_condition_results"]}
        self.assertEqual(by_id["qwd_probe_activation"]["status"], "inconclusive")
        self.assertEqual(by_id["control_point_advancement"]["status"], "inconclusive")

    def test_slow_point_advancement_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_fake_run(root, "run1", commands=[command_row()], low_speed=0.55, stationary=0.30)

            report = qwd_probe.build_report(
                {},
                stage="test",
                bot_run_ids=["run1"],
                artifacts_root=root,
                design_path=REPO_ROOT / "design.json",
            )

        self.assertEqual(report["decision"]["verdict"], "qwd_sng_hybrid_probe_rejected_by_guardrails")
        by_id = {condition["id"]: condition for condition in report["stop_condition_results"]}
        self.assertEqual(by_id["waypoint_only_slow_success"]["status"], "reject")


if __name__ == "__main__":
    unittest.main()
