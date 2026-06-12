import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import score_ztricks_batch as scorer  # noqa: E402


def command_row(
    time_s: float,
    *,
    ed: int = 3,
    x: float = -3516.125,
    y: float = 3712.0,
    z: float = -453.125,
    vh: float = 0.0,
    d_lip: float = 999999.0,
    vel_yaw: float = 0.0,
    target_err: float = 0.0,
    yaw_lead: float = 0.0,
    phase: int = 0,
    armed: bool = False,
    release_rule: int = 0,
    buttons: int = 0,
) -> dict:
    return {
        "time_s": time_s,
        "ed": ed,
        "name": "/ bro",
        "mode": 23,
        "msec": 13,
        "angles": {"pitch": 0.0, "yaw": vel_yaw, "roll": 0.0},
        "move": {"forward": 320 if vh > 0 else 0, "side": 0, "up": 0},
        "buttons": buttons,
        "impulse": 0,
        "origin": {"x": x, "y": y, "z": z},
        "zjump_state": {
            "phase": phase,
            "d_lip_qu": d_lip,
            "horizontal_speed": vh,
            "velocity_yaw_deg": vel_yaw,
            "target_yaw_deg": 0.0,
            "target_error_deg": target_err,
            "yaw_lead_deg": yaw_lead,
            "armed": armed,
            "release_rule": release_rule,
        },
    }


class TestScoreZtricksBatch(unittest.TestCase):
    def test_splits_attempts_on_time_gap(self) -> None:
        commands = [
            command_row(1.00, vh=100),
            command_row(1.10, x=-3450, y=3740, z=-488, vh=200),
            command_row(2.40, vh=100),
            command_row(2.50, x=-3450, y=3740, z=-488, vh=210),
        ]

        attempts = scorer.split_attempts(commands, gap_s=0.75)

        self.assertEqual(len(attempts), 2)
        self.assertEqual([len(a["rows"]) for a in attempts], [2, 2])
        self.assertEqual([a["attempt_index"] for a in attempts], [1, 2])

    def test_ignores_unnamed_rows(self) -> None:
        unnamed = command_row(1.00, vh=0)
        unnamed["name"] = ""

        attempts = scorer.split_attempts([unnamed, command_row(1.10, vh=100)])

        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0]["name"], "/ bro")

    def test_splits_attempts_on_spawn_snap_without_time_gap(self) -> None:
        commands = [
            command_row(1.00, vh=100),
            command_row(1.10, x=-3450, y=3740, z=-488, vh=220),
            command_row(1.20, x=-3400, y=3760, z=-488, vh=260),
            command_row(1.30, x=-3380, y=3770, z=-488, vh=280),
            command_row(1.40, x=-3516.125, y=3712.0, z=-453.125, vh=0),
            command_row(1.50, x=-3460, y=3740, z=-488, vh=230),
        ]

        attempts = scorer.split_attempts(commands, gap_s=0.75)

        self.assertEqual(len(attempts), 2)
        self.assertEqual([len(a["rows"]) for a in attempts], [4, 2])

    def test_scores_best_formula_and_classification(self) -> None:
        commands = [
            command_row(1.00, vh=100),
            command_row(
                1.10,
                x=-3360.8,
                y=3777.2,
                z=-488.0,
                vh=475.2,
                d_lip=12.8,
                vel_yaw=-11.3,
                target_err=8.3,
                yaw_lead=-7.7,
                phase=2,
                armed=True,
                release_rule=1,
                buttons=scorer.BUTTON_JUMP,
            ),
            command_row(1.20, x=-3044.1, y=3760.5, z=-488.0, vh=495.5),
        ]

        report = scorer.score_commands(commands, run_id="synthetic")
        attempt = report["attempts"][0]

        self.assertEqual(report["attempt_count"], 1)
        self.assertEqual(report["best_formula_attempt"], 1)
        self.assertEqual(report["best_landing_attempt"], 1)
        self.assertEqual(attempt["classification"], "released")
        self.assertEqual(attempt["armed_rows"], 1)
        self.assertEqual(attempt["release_rows"], 1)
        self.assertEqual(attempt["jump_button_rows"], 1)
        self.assertAlmostEqual(attempt["best_formula"]["formula_score"], 0.0, places=3)
        self.assertAlmostEqual(attempt["closest_landing"]["landing_distance_h_qu"], 0.0, places=3)

    def test_scores_run_dir_outputs_markdown(self) -> None:
        commands = [
            command_row(1.00, vh=120),
            command_row(1.10, x=-3370, y=3770, z=-488, vh=228, d_lip=24, phase=1),
        ]
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            (run_dir / "moveprobe-commands.json").write_text(
                '{"commands": ' + json.dumps(commands) + "}",
                encoding="utf-8",
            )

            report = scorer.score_run_dir(run_dir)
            md = scorer.render_markdown(report)

        self.assertIn("ztricks batch score", md)
        self.assertIn("approach_speed_below_release_floor", md)
        self.assertEqual(report["attempt_count"], 1)


if __name__ == "__main__":
    unittest.main()
