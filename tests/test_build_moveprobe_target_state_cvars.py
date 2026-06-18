import json
import tempfile
import unittest
from pathlib import Path

from scripts.build_moveprobe_target_state_cvars import NONE, build_cvars, build_window_schedule, main


class TestBuildMoveprobeTargetStateCvars(unittest.TestCase):
    def sample_report(self) -> dict:
        return {
            "schema": "komodobots.replay_segment_targets.v1",
            "map": "ztricks",
            "route": "sample",
            "targets": [
                {
                    "target": {
                        "origin": {"x": 1.0, "y": 2.5, "z": -3.125},
                        "velocity": {"x": 0.0, "y": 0.0, "z": 111.0},
                        "angles_deg": {"pitch": 0.0, "yaw": 185.6125, "roll": 0.0},
                        "move": {"forward": 508, "side": -508, "up": 0},
                        "jump": False,
                        "velocity_yaw_deg": 202.891,
                        "horizontal_speed": 407.25,
                    }
                },
                {
                    "target": {
                        "origin": {"x": 4.0, "y": 5.0, "z": 6.0},
                        "velocity": {"x": 0.0, "y": 0.0, "z": -71.0},
                        "angles_deg": {"pitch": 0.0, "yaw": 224.3425, "roll": 0.0},
                        "move": {"forward": 0, "side": 508, "up": 0},
                        "jump": True,
                        "velocity_yaw_deg": None,
                        "horizontal_speed": 512.5,
                    }
                },
            ],
        }

    def test_builds_waypoints_and_signed_target_state_schedules(self) -> None:
        built = build_cvars(self.sample_report(), route_yaw_weight=0.125, jump_lookahead=2)

        self.assertEqual(built["schema"], "komodobots.moveprobe_target_state_cvars.v1")
        self.assertEqual(built["target_count"], 2)
        self.assertEqual(built["qwd_waypoints"], "1,2.5,-3.125;4,5,6")
        cvars = built["extra_cvars"]
        self.assertEqual(cvars["k_fb_moveprobe_s26_forwardmove_schedule"], "508,0")
        self.assertEqual(cvars["k_fb_moveprobe_s26_sidemove_schedule"], "-508,508")
        self.assertEqual(cvars["k_fb_moveprobe_s26_jump_schedule"], "0,1")
        self.assertEqual(cvars["k_fb_moveprobe_s28_view_yaw_schedule"], "185.6125,224.3425")
        self.assertEqual(cvars["k_fb_moveprobe_s28_velocity_yaw_schedule"], f"202.891,{NONE:g}")
        self.assertEqual(cvars["k_fb_moveprobe_s28_vertical_velocity_schedule"], "111,-71")
        self.assertEqual(cvars["k_fb_moveprobe_s28_horizontal_speed_schedule"], "407.25,512.5")
        self.assertEqual(cvars["k_fb_moveprobe_s28_route_yaw_weight"], "0.125")
        self.assertEqual(cvars["k_fb_moveprobe_s28_jump_lookahead"], "2")
        self.assertIn("k_fb_moveprobe_s28_view_yaw_schedule 185.6125,224.3425", built["ktx_extra_cvars"])

    def test_builds_phase_gated_catchup_schedules(self) -> None:
        built = build_cvars(
            self.sample_report(),
            route_yaw_weight=0.125,
            jump_lookahead=0,
            catchup_move=950,
            catchup_start_index=1,
            catchup_gap=20,
            catchup_blend=0.5,
            catchup_cap=1000,
            catchup_numerator=8,
            catchup_flip=1,
        )

        cvars = built["extra_cvars"]
        self.assertEqual(cvars["k_fb_moveprobe_s28_catchup_move_schedule"], "0,950")
        self.assertEqual(cvars["k_fb_moveprobe_s28_catchup_gap_schedule"], "20,20")
        self.assertEqual(cvars["k_fb_moveprobe_s28_catchup_blend_schedule"], "1,0.5")
        self.assertEqual(cvars["k_fb_moveprobe_s28_catchup_cap_schedule"], "1000,1000")
        self.assertEqual(cvars["k_fb_moveprobe_s28_catchup_numerator_schedule"], "0,8")
        self.assertEqual(cvars["k_fb_moveprobe_s28_catchup_flip_schedule"], "0,1")
        self.assertIn("k_fb_moveprobe_s28_catchup_move_schedule 0,950", built["ktx_extra_cvars"])

    def test_window_schedule_clamps_indices(self) -> None:
        self.assertEqual(
            build_window_schedule(
                4,
                start_index=-5,
                end_index=99,
                active_value=7,
                inactive_value=0,
            ),
            [7, 7, 7, 7],
        )
        self.assertEqual(
            build_window_schedule(
                4,
                start_index=3,
                end_index=1,
                active_value=7,
                inactive_value=0,
            ),
            [0, 0, 0, 0],
        )

    def test_cli_writes_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target_path = root / "targets.json"
            output_path = root / "cvars.json"
            target_path.write_text(json.dumps(self.sample_report()), encoding="utf-8")

            old_argv = __import__("sys").argv
            try:
                __import__("sys").argv = [
                    "build_moveprobe_target_state_cvars.py",
                    "--targets",
                    str(target_path),
                    "--output-json",
                    str(output_path),
                ]
                self.assertEqual(main(), 0)
            finally:
                __import__("sys").argv = old_argv

            self.assertTrue(output_path.exists())
            data = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(data["route"], "sample")
            self.assertEqual(data["extra_cvars"]["k_fb_moveprobe_s28_jump_lookahead"], "0")


if __name__ == "__main__":
    unittest.main()
