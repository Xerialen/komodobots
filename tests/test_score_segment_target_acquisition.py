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


def command(time_s: float, x: float, y: float, z: float, *, active: bool, qwd_index: int) -> dict:
    return {
        "time_s": time_s,
        "origin": {"x": x, "y": y, "z": z},
        "qwd_state": {"active": active, "control_point_index": qwd_index},
    }


if __name__ == "__main__":
    unittest.main()
