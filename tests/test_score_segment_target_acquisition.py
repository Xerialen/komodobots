from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from score_segment_target_acquisition import score_run


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


class SegmentTargetAcquisitionScoreTests(unittest.TestCase):
    def test_pass_requires_all_targets_and_complete_event(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            targets = root / "targets.json"
            run = root / "run"
            run.mkdir()
            write_json(targets, target_doc())
            write_json(run / "moveprobe-commands.json", {
                "commands": [
                    command(1.0, 0, 0, 0, active=True, qwd_index=0),
                    command(2.0, 100, 0, 0, active=True, qwd_index=1),
                ]
            })
            write_json(run / "moveprobe-qwd-events.json", {
                "events": [{"event": "complete", "advanced": 2}]
            })

            report = score_run(targets, run)

        self.assertEqual(report["overall"], "PASS")
        self.assertTrue(all(row["acquired"] for row in report["target_results"]))

    def test_missing_later_target_fails_even_with_activation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            targets = root / "targets.json"
            run = root / "run"
            run.mkdir()
            write_json(targets, target_doc())
            write_json(run / "moveprobe-commands.json", {
                "commands": [
                    command(1.0, 0, 0, 0, active=True, qwd_index=0),
                    command(2.0, 40, 0, 0, active=True, qwd_index=1),
                ]
            })
            write_json(run / "moveprobe-qwd-events.json", {
                "events": [{"event": "advance", "advanced": 1}]
            })

            report = score_run(targets, run)

        self.assertEqual(report["overall"], "FAIL")
        self.assertTrue(report["target_results"][0]["acquired"])
        self.assertFalse(report["target_results"][1]["acquired"])
        self.assertFalse(report["qwd_events"]["complete"])

    def test_inactive_gate_hit_is_not_acquired(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            targets = root / "targets.json"
            run = root / "run"
            run.mkdir()
            write_json(targets, target_doc())
            write_json(run / "moveprobe-commands.json", {
                "commands": [
                    command(1.0, 0, 0, 0, active=True, qwd_index=0),
                    command(2.0, 300, 0, 0, active=True, qwd_index=1),
                    command(3.0, 100, 0, 0, active=False, qwd_index=0),
                ]
            })
            write_json(run / "moveprobe-qwd-events.json", {
                "events": [{"event": "advance", "advanced": 1}]
            })

            report = score_run(targets, run)

        self.assertEqual(report["overall"], "FAIL")
        self.assertFalse(report["target_results"][1]["acquired"])
        self.assertTrue(report["target_results"][1]["inactive_gate_hit"])


def target_doc() -> dict:
    return {
        "targets": [
            {
                "order": 1,
                "cursor": 0,
                "target": {"origin": {"x": 0, "y": 0, "z": 0}},
                "gate": {"horizontal_qu": 16, "vertical_qu": 16},
            },
            {
                "order": 2,
                "cursor": 10,
                "target": {"origin": {"x": 100, "y": 0, "z": 0}},
                "gate": {"horizontal_qu": 16, "vertical_qu": 16},
            },
        ]
    }


def command(
    time_s: float,
    x: float,
    y: float,
    z: float,
    *,
    active: bool,
    qwd_index: int,
    ed: int | None = None,
    name: str | None = None,
    velocity: tuple[float, float] | None = None,
) -> dict:
    row: dict = {
        "time_s": time_s,
        "origin": {"x": x, "y": y, "z": z},
        "qwd_state": {"active": active, "control_point_index": qwd_index},
    }
    if ed is not None:
        row["ed"] = ed
    if name is not None:
        row["name"] = name
    if velocity is not None:
        row["water_state"] = {"velocity": {"x": velocity[0], "y": velocity[1], "z": 0.0}}
    return row


class PerPlayerScoringTests(unittest.TestCase):
    def test_cross_player_acquisitions_do_not_pass(self) -> None:
        # Bot ed=2 acquires target 1, bot ed=3 acquires target 2, ed=3 completes.
        # No single bot acquired both targets -> must FAIL.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            targets = root / "targets.json"
            run = root / "run"
            run.mkdir()
            write_json(targets, target_doc())
            write_json(run / "moveprobe-commands.json", {
                "commands": [
                    command(1.0, 0, 0, 0, active=True, qwd_index=0, ed=2),
                    command(2.0, 100, 0, 0, active=True, qwd_index=1, ed=3),
                ]
            })
            write_json(run / "moveprobe-qwd-events.json", {
                "events": [{"event": "complete", "advanced": 2, "ed": 3}]
            })

            report = score_run(targets, run)

        self.assertEqual(report["overall"], "FAIL")
        self.assertEqual(report["player_count"], 2)
        self.assertTrue(all(not p["acquired_all"] for p in report["players"]))

    def test_single_bot_acquires_all_and_completes_passes(self) -> None:
        # ed=2 acquires both targets and completes; ed=3 is noise -> PASS on ed=2.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            targets = root / "targets.json"
            run = root / "run"
            run.mkdir()
            write_json(targets, target_doc())
            write_json(run / "moveprobe-commands.json", {
                "commands": [
                    command(1.0, 0, 0, 0, active=True, qwd_index=0, ed=2),
                    command(2.0, 100, 0, 0, active=True, qwd_index=1, ed=2),
                    command(1.5, 500, 0, 0, active=True, qwd_index=0, ed=3),
                ]
            })
            write_json(run / "moveprobe-qwd-events.json", {
                "events": [{"event": "complete", "advanced": 2, "ed": 2}]
            })

            report = score_run(targets, run)

        self.assertEqual(report["overall"], "PASS")
        self.assertEqual(report["passing_player"]["ed"], 2)

    def test_acquirer_must_be_the_completer(self) -> None:
        # ed=2 acquires both targets but never completes; ed=3 emits complete
        # without acquiring -> must FAIL (complete must come from the acquirer).
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            targets = root / "targets.json"
            run = root / "run"
            run.mkdir()
            write_json(targets, target_doc())
            write_json(run / "moveprobe-commands.json", {
                "commands": [
                    command(1.0, 0, 0, 0, active=True, qwd_index=0, ed=2),
                    command(2.0, 100, 0, 0, active=True, qwd_index=1, ed=2),
                    command(1.5, 900, 0, 0, active=True, qwd_index=0, ed=3),
                ]
            })
            write_json(run / "moveprobe-qwd-events.json", {
                "events": [{"event": "complete", "advanced": 2, "ed": 3}]
            })

            report = score_run(targets, run)

        self.assertEqual(report["overall"], "FAIL")


class HorizontalSpeedTests(unittest.TestCase):
    def test_reads_nested_water_state_velocity(self) -> None:
        from score_segment_target_acquisition import horizontal_speed

        row = {"water_state": {"velocity": {"x": 3.0, "y": 4.0, "z": 1.0}}}
        self.assertEqual(horizontal_speed(row), 5.0)

    def test_legacy_flat_velocity_keys_still_read(self) -> None:
        from score_segment_target_acquisition import horizontal_speed

        row = {"water_state": {"velocity_x": 3.0, "velocity_y": 4.0}}
        self.assertEqual(horizontal_speed(row), 5.0)

    def test_missing_velocity_is_none(self) -> None:
        from score_segment_target_acquisition import horizontal_speed

        self.assertIsNone(horizontal_speed({"water_state": {}}))


if __name__ == "__main__":
    unittest.main()
