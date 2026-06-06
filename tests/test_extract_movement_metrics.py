from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import run_frobodm2_lab
from extract_movement_metrics import (
    compute_movement_metrics,
    compute_slot_metrics,
    percentile,
    summarize_airborne_proxy,
    weighted_speed_for_window,
    weighted_speed_for_window_slow,
)


THRESHOLDS = {
    "stationary_speed_qu_per_s": 10.0,
    "low_speed_qu_per_s": 100.0,
    "maxspeed_qu_per_s": 320.0,
    "high_speed_qu_per_s": 400.0,
    "teleport_speed_qu_per_s": 2500.0,
    "vertical_epsilon_qu": 0.25,
    "vertical_speed_qu_per_s": 40.0,
    "airborne_min_duration_ms": 120.0,
    "airborne_min_z_delta_qu": 4.0,
    "landing_window_ms": 250.0,
}


class MovementMetricsTests(unittest.TestCase):
    def test_percentile_interpolates(self) -> None:
        self.assertEqual(percentile([], 95), 0.0)
        self.assertEqual(percentile([10.0], 95), 10.0)
        self.assertEqual(percentile([0.0, 10.0], 50), 5.0)
        self.assertEqual(percentile([0.0, 10.0], 90), 9.0)

    def test_empty_slot_metrics_keep_schema(self) -> None:
        populated = compute_slot_metrics(
            slot=1,
            name="/ bot",
            samples=[
                {"time_ms": 0, "origin": [0.0, 0.0, 0.0]},
                {"time_ms": 1000, "origin": [100.0, 0.0, 0.0]},
            ],
            thresholds=THRESHOLDS,
        )
        empty = compute_slot_metrics(slot=1, name="/ bot", samples=[], thresholds=THRESHOLDS)

        self.assertEqual(set(empty), set(populated))
        self.assertEqual(empty["sample_count"], 0)
        self.assertEqual(empty["start_origin"], [])
        self.assertIsNone(empty["first_time_ms"])

    def test_slot_metrics_skip_duplicate_times_and_teleports(self) -> None:
        metrics = compute_slot_metrics(
            slot=1,
            name="/ bot",
            samples=[
                {"time_ms": 0, "origin": [0.0, 0.0, 0.0]},
                {"time_ms": 1000, "origin": [100.0, 0.0, 0.0]},
                {"time_ms": 1000, "origin": [150.0, 0.0, 0.0]},
                {"time_ms": 2000, "origin": [5150.0, 0.0, 0.0]},
                {"time_ms": 3000, "origin": [5200.0, 0.0, 0.0]},
            ],
            thresholds=THRESHOLDS,
        )

        self.assertEqual(metrics["segment_count"], 2)
        self.assertEqual(metrics["dropped_teleport_segments"], 1)
        self.assertAlmostEqual(metrics["horizontal_distance_qu"], 150.0)
        self.assertAlmostEqual(metrics["avg_horizontal_speed_qu_per_s"], 75.0)
        self.assertAlmostEqual(metrics["max_horizontal_speed_qu_per_s"], 100.0)
        self.assertAlmostEqual(metrics["low_speed_time_ratio"], 0.5)

    def test_slot_metrics_reports_airborne_proxy_and_landing_speed_loss(self) -> None:
        metrics = compute_slot_metrics(
            slot=1,
            name="/ hopper",
            samples=[
                {"time_ms": 0, "origin": [0.0, 0.0, 0.0]},
                {"time_ms": 100, "origin": [40.0, 0.0, 10.0]},
                {"time_ms": 200, "origin": [80.0, 0.0, 20.0]},
                {"time_ms": 300, "origin": [120.0, 0.0, 10.0]},
                {"time_ms": 400, "origin": [160.0, 0.0, 0.0]},
                {"time_ms": 650, "origin": [240.0, 0.0, 0.0]},
            ],
            thresholds=THRESHOLDS,
        )

        self.assertEqual(metrics["airborne_proxy_count"], 1)
        self.assertAlmostEqual(metrics["airborne_proxy_time_s"], 0.4)
        self.assertAlmostEqual(metrics["airborne_proxy_time_ratio"], 0.615)
        self.assertAlmostEqual(metrics["jump_cadence_per_min"], 92.308)
        self.assertEqual(metrics["landing_speed_window_count"], 1)
        self.assertAlmostEqual(metrics["avg_landing_pre_speed_qu_per_s"], 400.0)
        self.assertAlmostEqual(metrics["avg_landing_post_speed_qu_per_s"], 320.0)
        self.assertAlmostEqual(metrics["avg_post_landing_speed_delta_qu_per_s"], -80.0)
        self.assertAlmostEqual(metrics["avg_post_landing_speed_loss_ratio"], 0.2)

    def test_indexed_weighted_speed_matches_slow_window_scan(self) -> None:
        segments = [
            {"start_ms": 0, "end_ms": 100, "horizontal_speed_qu_per_s": 100.0},
            {"start_ms": 150, "end_ms": 300, "horizontal_speed_qu_per_s": 300.0},
            {"start_ms": 300, "end_ms": 500, "horizontal_speed_qu_per_s": 500.0},
        ]

        for start_ms, end_ms in [(0, 100), (50, 250), (100, 150), (225, 425), (600, 700)]:
            self.assertEqual(
                weighted_speed_for_window(segments, start_ms, end_ms),
                weighted_speed_for_window_slow(segments, start_ms, end_ms),
            )

    def test_airborne_proxy_landing_speed_loss_ratio_is_mean_of_per_landing_ratios(self) -> None:
        segments = [
            {
                "start_ms": 300,
                "end_ms": 400,
                "vertical_motion": True,
                "start_z": 0.0,
                "end_z": 10.0,
                "horizontal_speed_qu_per_s": 100.0,
            },
            {
                "start_ms": 400,
                "end_ms": 500,
                "vertical_motion": True,
                "start_z": 10.0,
                "end_z": 0.0,
                "horizontal_speed_qu_per_s": 100.0,
            },
            {
                "start_ms": 500,
                "end_ms": 750,
                "vertical_motion": False,
                "start_z": 0.0,
                "end_z": 0.0,
                "horizontal_speed_qu_per_s": 50.0,
            },
            {
                "start_ms": 1250,
                "end_ms": 1350,
                "vertical_motion": True,
                "start_z": 0.0,
                "end_z": 12.0,
                "horizontal_speed_qu_per_s": 1000.0,
            },
            {
                "start_ms": 1350,
                "end_ms": 1500,
                "vertical_motion": True,
                "start_z": 12.0,
                "end_z": 0.0,
                "horizontal_speed_qu_per_s": 1000.0,
            },
            {
                "start_ms": 1500,
                "end_ms": 1750,
                "vertical_motion": False,
                "start_z": 0.0,
                "end_z": 0.0,
                "horizontal_speed_qu_per_s": 900.0,
            },
        ]

        summary = summarize_airborne_proxy(segments, THRESHOLDS)

        self.assertEqual(summary["landing_speed_window_count"], 2)
        self.assertAlmostEqual(summary["avg_landing_pre_speed_qu_per_s"], 550.0)
        self.assertAlmostEqual(summary["avg_landing_post_speed_qu_per_s"], 475.0)
        self.assertAlmostEqual(summary["avg_post_landing_speed_loss_qu_per_s"], 75.0)
        self.assertAlmostEqual(summary["avg_post_landing_speed_loss_ratio"], 0.3)

    def test_compute_movement_metrics_excludes_unnamed_slots(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            (run_dir / "run.env").write_text("MAP=synthetic\n", encoding="utf-8")
            events_path = run_dir / "events.txt"
            events = [
                {"kind": 0, "time": 0, "data": {"Data": {"MaxSpeed": 320, "LevelName": "Synthetic"}, "Time": 0}},
                {
                    "kind": 1,
                    "time": 0,
                    "data": {
                        "Player": {"Slot": 0, "UserID": 1, "Name": "", "Spectator": False},
                        "Time": 0,
                    },
                },
                {
                    "kind": 1,
                    "time": 0,
                    "data": {
                        "Player": {"Slot": 1, "UserID": 2, "Name": "/ bot", "Spectator": False},
                        "Time": 0,
                    },
                },
                {"kind": 5, "time": 0, "data": {"PlayerNum": 0, "Origin": [0, 0, 0], "TimeMs": 0}},
                {"kind": 5, "time": 1, "data": {"PlayerNum": 0, "Origin": [1000, 0, 0], "TimeMs": 1000}},
                {"kind": 5, "time": 0, "data": {"PlayerNum": 1, "Origin": [0, 0, 0], "TimeMs": 0}},
                {"kind": 5, "time": 1, "data": {"PlayerNum": 1, "Origin": [320, 0, 0], "TimeMs": 1000}},
            ]
            events_path.write_text("\n".join(json.dumps(event) for event in events), encoding="utf-8")

            metrics = compute_movement_metrics(events_path, run_dir=run_dir)

        self.assertEqual(metrics["parser"]["position_event_count"], 4)
        self.assertEqual(len(metrics["players"]), 1)
        player = metrics["players"][0]
        self.assertEqual(player["name"], "/ bot")
        self.assertAlmostEqual(player["avg_horizontal_speed_qu_per_s"], 320.0)
        self.assertAlmostEqual(player["over_maxspeed_time_ratio"], 0.0)

    def test_compute_movement_metrics_clamps_samples_to_match_duration(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            (run_dir / "run.env").write_text("MAP=synthetic\n", encoding="utf-8")
            (run_dir / "analysis.json").write_text(
                json.dumps({"match": {"map": "Synthetic", "duration": 1000}}),
                encoding="utf-8",
            )
            events_path = run_dir / "events.txt"
            events = [
                {"kind": 0, "time": 0, "data": {"Data": {"MaxSpeed": 320, "LevelName": "Synthetic"}, "Time": 0}},
                {
                    "kind": 1,
                    "time": 0,
                    "data": {
                        "Player": {"Slot": 1, "UserID": 2, "Name": "/ bot", "Spectator": False},
                        "Time": 0,
                    },
                },
                {"kind": 5, "time": 0, "data": {"PlayerNum": 1, "Origin": [0, 0, 0], "TimeMs": 0}},
                {"kind": 5, "time": 1, "data": {"PlayerNum": 1, "Origin": [320, 0, 0], "TimeMs": 1000}},
                {"kind": 5, "time": 1.5, "data": {"PlayerNum": 1, "Origin": [800, 0, 0], "TimeMs": 1500}},
            ]
            events_path.write_text("\n".join(json.dumps(event) for event in events), encoding="utf-8")

            metrics = compute_movement_metrics(events_path, run_dir=run_dir)

        self.assertEqual(metrics["sample_window"]["match_duration_clamp_ms"], 1000)
        player = metrics["players"][0]
        self.assertEqual(player["last_time_ms"], 1000)
        self.assertEqual(player["match_duration_clamp_ms"], 1000)
        self.assertAlmostEqual(player["active_time_s"], 1.0)
        self.assertAlmostEqual(player["avg_horizontal_speed_qu_per_s"], 320.0)

    def test_run_id_validator_rejects_shell_metacharacters(self) -> None:
        self.assertEqual(run_frobodm2_lab.validate_run_id("20260605T201313Z_ok-1"), "20260605T201313Z_ok-1")
        with self.assertRaises(argparse.ArgumentTypeError):
            run_frobodm2_lab.validate_run_id("bad;touch nope")

    def test_runner_accepts_moveprobe_options(self) -> None:
        args = run_frobodm2_lab.parse_args(
            [
                "--moveprobe-mode",
                "7",
                "--moveprobe-yaw",
                "90",
                "--moveprobe-forwardmove",
                "700",
                "--moveprobe-sidemove",
                "120",
                "--moveprobe-upmove",
                "0",
            ]
        )

        self.assertEqual(args.moveprobe_mode, 7)
        self.assertEqual(args.moveprobe_yaw, 90.0)
        self.assertEqual(args.moveprobe_forwardmove, 700)
        self.assertEqual(args.moveprobe_sidemove, 120)
        self.assertEqual(args.moveprobe_upmove, 0)

    def test_runner_accepts_moveprobe_command_logging_options(self) -> None:
        args = run_frobodm2_lab.parse_args(
            [
                "--moveprobe-log-commands",
                "--moveprobe-log-interval",
                "0.5",
            ]
        )

        self.assertTrue(args.moveprobe_log_commands)
        self.assertEqual(args.moveprobe_log_interval, 0.5)

    def test_parse_moveprobe_command_logs(self) -> None:
        commands = run_frobodm2_lab.parse_moveprobe_command_logs(
            "\n".join(
                [
                    "noise before",
                    'FBMOVEPROBE_CMD time=12.250 ed=3 name=/ goldenboy mode=2 msec=13 angles=0.0,90.0,0.0 move=800,0,0 buttons=3 impulse=0',
                    'FBMOVEPROBE_CMD time=12.500 ed=3 name=/ goldenboy mode=5 msec=12 angles=0.0,90.0,0.0 move=-200,400,0 buttons=2 impulse=7 diag=270.0,90.0,180.0,1 route=12,10,42,14,524288,8192,1,1.250 water=3,-3,528,16,120.0,25.5,-4.0,80.0,0.100,0.200,0.300',
                ]
            )
        )

        self.assertEqual(len(commands), 2)
        self.assertEqual(commands[0]["name"], "/ goldenboy")
        self.assertEqual(commands[0]["mode"], 2)
        self.assertEqual(commands[0]["msec"], 13)
        self.assertEqual(commands[0]["angles"], {"pitch": 0.0, "yaw": 90.0, "roll": 0.0})
        self.assertEqual(commands[1]["mode"], 5)
        self.assertEqual(commands[1]["move"], {"forward": -200, "side": 400, "up": 0})
        self.assertEqual(commands[1]["buttons"], 2)
        self.assertEqual(commands[1]["impulse"], 7)
        self.assertEqual(
            commands[1]["diagnostics"],
            {"route_yaw": 270.0, "view_yaw": 90.0, "yaw_delta": 180.0, "backward": True},
        )
        self.assertEqual(
            commands[1]["route_state"],
            {
                "linked_marker": 12,
                "touch_marker": 10,
                "goal_ed": 42,
                "goal_marker": 14,
                "path_state": 524288,
                "bot_state": 8192,
                "blocked": True,
                "dir_speed": 1.25,
            },
        )
        self.assertEqual(commands[1]["water_state"]["waterlevel"], 3)
        self.assertEqual(commands[1]["water_state"]["watertype"], -3)
        self.assertEqual(commands[1]["water_state"]["flags"], 528)
        self.assertEqual(commands[1]["water_state"]["swim_arrow"], 16)
        self.assertEqual(commands[1]["water_state"]["emitted_upmove"], 120.0)
        self.assertEqual(commands[1]["water_state"]["velocity"], {"x": 25.5, "y": -4.0, "z": 80.0})
        self.assertEqual(commands[1]["water_state"]["dir_move"], {"x": 0.1, "y": 0.2, "z": 0.3})

    def test_remote_port_down_treats_empty_or_down_as_free(self) -> None:
        original_run = run_frobodm2_lab.run

        def fake_run(stdout: str, returncode: int = 0, stderr: str = ""):
            def inner(*args, **kwargs):
                return subprocess.CompletedProcess(args, returncode, stdout, stderr)

            return inner

        try:
            run_frobodm2_lab.run = fake_run("")
            self.assertTrue(run_frobodm2_lab.remote_port_is_down("host", 28599))

            run_frobodm2_lab.run = fake_run("localhost:28599        DOWN\n")
            self.assertTrue(run_frobodm2_lab.remote_port_is_down("host", 28599))

            run_frobodm2_lab.run = fake_run("localhost:28599        qws  0/16 dm3\n")
            self.assertFalse(run_frobodm2_lab.remote_port_is_down("host", 28599))

            run_frobodm2_lab.run = fake_run("", returncode=255, stderr="ssh failed")
            with self.assertRaises(RuntimeError):
                run_frobodm2_lab.remote_port_is_down("host", 28599)
        finally:
            run_frobodm2_lab.run = original_run


if __name__ == "__main__":
    unittest.main()
