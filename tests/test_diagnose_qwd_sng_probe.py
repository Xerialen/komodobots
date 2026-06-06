from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import diagnose_qwd_sng_probe as diagnosis


def write_design(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "control_points": [
                    {"qwd_origin": [1000.0, 0.0, 0.0]},
                    {"qwd_origin": [1100.0, 0.0, 0.0]},
                    {"qwd_origin": [1200.0, 0.0, 0.0]},
                ],
                "probe_contract": {
                    "suggested_cvars": {
                        "k_fb_moveprobe_qwd_start_radius": 192.0,
                        "k_fb_moveprobe_qwd_point_radius": 96.0,
                    }
                },
            }
        ),
        encoding="utf-8",
    )


def write_result(path: Path) -> None:
    path.write_text(
        json.dumps({"decision": {"verdict": "qwd_sng_hybrid_probe_inconclusive"}}),
        encoding="utf-8",
    )


def command_row(*, active: bool, time_s: float, advanced: int = 0, distance: float = 250.0) -> dict[str, object]:
    return {
        "ed": 2,
        "name": "/ bot",
        "time_s": time_s,
        "qwd_state": {
            "active": active,
            "control_point_index": 2 if active else 0,
            "advanced_control_points": advanced,
            "distance_qu": distance,
        },
    }


def write_run(root: Path, *, commands: list[dict[str, object]], origins: list[list[float]]) -> None:
    run_dir = root / "run1"
    run_dir.mkdir()
    (run_dir / "run.env").write_text(
        "MAP=dm3\nMOVEPROBE_MODE=9\nMOVEPROBE_QWD_START_RADIUS=192\nMOVEPROBE_QWD_POINT_RADIUS=96\n",
        encoding="utf-8",
    )
    (run_dir / "analysis.json").write_text(json.dumps({"match": {"duration": 5000}}), encoding="utf-8")
    (run_dir / "moveprobe-commands.json").write_text(json.dumps({"commands": commands}), encoding="utf-8")
    lines = [
        {"kind": 0, "time": 0, "data": {"Data": {"ServerTime": 10.0}, "Time": 0}},
        {
            "kind": 1,
            "time": 0,
            "data": {"Player": {"Slot": 1, "UserID": 2, "Name": "/ bot", "Spectator": False}, "Time": 0},
        },
    ]
    for index, origin in enumerate(origins):
        time_ms = index * 1000
        lines.append({"kind": 5, "time": time_ms / 1000.0, "data": {"PlayerNum": 1, "Origin": origin, "TimeMs": time_ms}})
    (run_dir / "events.txt").write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")


class DiagnoseQwdSngProbeTests(unittest.TestCase):
    def test_active_after_mvd_window_classification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            design_path = root / "design.json"
            result_path = root / "result.json"
            write_design(design_path)
            write_result(result_path)
            write_run(
                root,
                commands=[command_row(active=True, time_s=16.2, advanced=2, distance=80.0)],
                origins=[[0, 0, 0], [50, 0, 0], [100, 0, 0]],
            )

            report = diagnosis.build_diagnosis(
                design_path=design_path,
                result_path=result_path,
                run_id="run1",
                artifacts_root=root,
                stage="test",
            )

        self.assertEqual(report["players"][0]["classification"], "qwd_activation_after_mvd_window")
        self.assertEqual(report["players"][0]["qwd_command_summary"]["active_inside_mvd_rows"], 0)

    def test_missed_start_radius_classification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            design_path = root / "design.json"
            result_path = root / "result.json"
            write_design(design_path)
            write_result(result_path)
            write_run(
                root,
                commands=[command_row(active=False, time_s=11.0, advanced=0, distance=250.0)],
                origins=[[0, 0, 0], [50, 0, 0], [100, 0, 0]],
            )

            report = diagnosis.build_diagnosis(
                design_path=design_path,
                result_path=result_path,
                run_id="run1",
                artifacts_root=root,
                stage="test",
            )

        self.assertEqual(report["players"][0]["classification"], "spawn_or_route_context_missed_start_radius")
        self.assertEqual(report["players"][0]["mvd_sequential_control_points_reached"], 0)


if __name__ == "__main__":
    unittest.main()
