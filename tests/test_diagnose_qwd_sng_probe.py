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
                    {"qwd_origin": [1300.0, 0.0, 0.0]},
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


def write_result(
    path: Path,
    *,
    verdict: str = "qwd_sng_hybrid_probe_inconclusive",
    failed_stop_conditions: list[str] | None = None,
    inconclusive_stop_conditions: list[str] | None = None,
) -> None:
    decision: dict[str, object] = {"verdict": verdict}
    if failed_stop_conditions is not None:
        decision["failed_stop_conditions"] = failed_stop_conditions
    if inconclusive_stop_conditions is not None:
        decision["inconclusive_stop_conditions"] = inconclusive_stop_conditions
    path.write_text(
        json.dumps({"decision": decision}),
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


def write_run(
    root: Path,
    *,
    commands: list[dict[str, object]],
    origins: list[list[float]],
    start_radius: float = 192,
    point_radius: float = 96,
) -> None:
    run_dir = root / "run1"
    run_dir.mkdir()
    (run_dir / "run.env").write_text(
        (
            "MAP=dm3\n"
            "MOVEPROBE_MODE=9\n"
            f"MOVEPROBE_QWD_START_RADIUS={start_radius}\n"
            f"MOVEPROBE_QWD_POINT_RADIUS={point_radius}\n"
        ),
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

    def test_run_env_start_radius_overrides_design_default(self) -> None:
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
                start_radius=320,
            )

            report = diagnosis.build_diagnosis(
                design_path=design_path,
                result_path=result_path,
                run_id="run1",
                artifacts_root=root,
                stage="test",
            )

        self.assertEqual(report["control_point_radii"]["start_radius_qu"], 320.0)
        self.assertEqual(report["players"][0]["classification"], "not_enough_qwd_activation_evidence")

    def test_rejected_guardrail_decision_after_timing_repair(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            design_path = root / "design.json"
            result_path = root / "result.json"
            write_design(design_path)
            write_result(
                result_path,
                verdict="qwd_sng_hybrid_probe_rejected_by_guardrails",
                failed_stop_conditions=["waypoint_only_slow_success"],
            )
            write_run(
                root,
                commands=[command_row(active=True, time_s=11.0, advanced=4, distance=80.0)],
                origins=[[1000, 0, 0], [1100, 0, 0], [1200, 0, 0], [1300, 0, 0]],
                start_radius=320,
            )

            report = diagnosis.build_diagnosis(
                design_path=design_path,
                result_path=result_path,
                run_id="run1",
                artifacts_root=root,
                stage="test",
            )

        self.assertEqual(
            report["decision"]["verdict"],
            "qwd_sng_setup_repaired_but_rejected_by_guardrails",
        )
        self.assertIn("waypoint_only_slow_success", report["decision"]["reason"])

    def test_inconclusive_tight_start_preserves_start_evidence_gap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            design_path = root / "design.json"
            result_path = root / "result.json"
            write_design(design_path)
            write_result(
                result_path,
                verdict="qwd_sng_hybrid_probe_rejected_by_guardrails",
                failed_stop_conditions=[
                    "phase_target_progression",
                    "waypoint_only_slow_success",
                ],
                inconclusive_stop_conditions=["tight_start_activation"],
            )
            write_run(
                root,
                commands=[command_row(active=True, time_s=11.0, advanced=4, distance=80.0)],
                origins=[[1000, 0, 0], [1100, 0, 0], [1200, 0, 0], [1300, 0, 0]],
                start_radius=192,
            )

            report = diagnosis.build_diagnosis(
                design_path=design_path,
                result_path=result_path,
                run_id="run1",
                artifacts_root=root,
                stage="test",
            )

        self.assertEqual(
            report["source_result_inconclusive_stop_conditions"],
            ["tight_start_activation"],
        )
        self.assertEqual(
            report["decision"]["verdict"],
            "qwd_sng_start_evidence_inconclusive",
        )
        self.assertIn("pre-advance CP0", report["decision"]["reason"])
        self.assertIn("denser or event-level", report["decision"]["next_goal"])
        self.assertTrue(
            any("pre-advance CP0" in line for line in report["interpretation"])
        )

    def test_malformed_position_rows_do_not_crash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run1"
            run_dir.mkdir()
            (run_dir / "analysis.json").write_text(json.dumps({"match": {"duration": 5000}}), encoding="utf-8")
            lines = [
                {
                    "kind": 1,
                    "time": 0,
                    "data": {"Player": {"Slot": 1, "UserID": 2, "Name": "/ bot", "Spectator": False}, "Time": 0},
                },
                {"kind": 5, "time": 1, "data": {"PlayerNum": 1, "Origin": [1, 2, 3], "TimeMs": "bad"}},
                {"kind": 5, "time": 2, "data": {"PlayerNum": 1, "Origin": [1, 2], "TimeMs": 2000}},
            ]
            (run_dir / "events.txt").write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")

            players, samples = diagnosis.load_position_samples(run_dir)

        self.assertEqual(players[1]["name"], "/ bot")
        self.assertEqual(samples, {})
        self.assertEqual(diagnosis.closest_approaches([{"time_ms": 0, "origin": [1, 2]}], [[0, 0, 0]])[0]["min_distance_qu"], None)
        self.assertEqual(diagnosis.sequential_reach_count([{"time_ms": 0, "origin": [1, 2]}], [[0, 0, 0]], radius=96), 0)

    def test_safe_time_ms_tolerates_key_error(self) -> None:
        original = diagnosis.coerce_time_ms

        def raising_key_error(event: dict[str, object], data: dict[str, object]) -> int:
            raise KeyError("TimeMs")

        try:
            diagnosis.coerce_time_ms = raising_key_error
            self.assertIsNone(diagnosis.safe_time_ms({}, {}))
        finally:
            diagnosis.coerce_time_ms = original


if __name__ == "__main__":
    unittest.main()
