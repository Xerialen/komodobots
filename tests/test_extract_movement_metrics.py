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
    bin_samples,
    compute_movement_metrics,
    compute_slot_metrics,
    derive_deaths,
    percentile,
    summarize_airborne_proxy,
    weighted_speed_for_window,
    weighted_speed_for_window_slow,
    _heatmap_grid,
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
                "8",
                "--moveprobe-yaw",
                "90",
                "--moveprobe-forwardmove",
                "700",
                "--moveprobe-sidemove",
                "120",
                "--moveprobe-upmove",
                "0",
                "--moveprobe-transition-scale",
                "1.4",
                "--moveprobe-transition-window",
                "0.35",
                "--moveprobe-qwd-waypoints",
                "1,2,3;4,5,6",
                "--moveprobe-qwd-point-radius",
                "88",
                "--moveprobe-qwd-start-radius",
                "176",
            ]
        )

        self.assertEqual(args.moveprobe_mode, 8)
        self.assertEqual(args.moveprobe_yaw, 90.0)
        self.assertEqual(args.moveprobe_forwardmove, 700)
        self.assertEqual(args.moveprobe_sidemove, 120)
        self.assertEqual(args.moveprobe_upmove, 0)
        self.assertEqual(args.moveprobe_transition_scale, 1.4)
        self.assertEqual(args.moveprobe_transition_window, 0.35)
        self.assertEqual(args.moveprobe_qwd_waypoints, "1,2,3;4,5,6")
        self.assertEqual(args.moveprobe_qwd_point_radius, 88.0)
        self.assertEqual(args.moveprobe_qwd_start_radius, 176.0)

    def test_runner_rejects_unsafe_qwd_waypoints(self) -> None:
        with self.assertRaises(argparse.ArgumentTypeError):
            run_frobodm2_lab.validate_qwd_waypoints('1,2,3";exec bad')

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
                    'FBMOVEPROBE_CMD time=12.500 ed=3 name=/ goldenboy mode=9 msec=12 angles=0.0,90.0,0.0 move=-200,400,0 buttons=2 impulse=7 diag=270.0,90.0,180.0,1 route=12,10,42,14,524288,8192,1,1.250 water=3,-3,528,16,120.0,25.5,-4.0,80.0,0.100,0.200,0.300 probe=0,0,999.000,999.000,1.000 qwd=1,3,14,72.250,4,0,1.375 origin=-3360.800,3777.200,-488.000 zjump=2,12.800,475.200,-11.3,-3.0,8.3,-7.7,1,1 s25=1,1,5,888.2,924.4,36.2,-1,89.5,215.3,181.2,204.4,23.2,12.5,-399.8',
                ]
            )
        )

        self.assertEqual(len(commands), 2)
        self.assertEqual(commands[0]["name"], "/ goldenboy")
        self.assertEqual(commands[0]["mode"], 2)
        self.assertEqual(commands[0]["msec"], 13)
        self.assertEqual(commands[0]["angles"], {"pitch": 0.0, "yaw": 90.0, "roll": 0.0})
        self.assertEqual(commands[1]["mode"], 9)
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
        self.assertEqual(
            commands[1]["probe_state"],
            {
                "transition_active": False,
                "on_ground": False,
                "since_ground_s": 999.0,
                "since_air_s": 999.0,
                "transition_scale": 1.0,
            },
        )
        self.assertEqual(
            commands[1]["qwd_state"],
            {
                "active": True,
                "control_point_index": 3,
                "control_point_count": 14,
                "distance_qu": 72.25,
                "advanced_control_points": 4,
                "complete": False,
                "active_seconds": 1.375,
            },
        )
        self.assertEqual(commands[1]["origin"], {"x": -3360.8, "y": 3777.2, "z": -488.0})
        self.assertEqual(
            commands[1]["zjump_state"],
            {
                "phase": 2,
                "d_lip_qu": 12.8,
                "horizontal_speed": 475.2,
                "velocity_yaw_deg": -11.3,
                "target_yaw_deg": -3.0,
                "target_error_deg": 8.3,
                "yaw_lead_deg": -7.7,
                "armed": True,
                "release_rule": 1,
            },
        )
        self.assertEqual(
            commands[1]["s25_state"],
            {
                "active": True,
                "engaged": True,
                "reason": 5,
                "speed": 888.2,
                "target_speed": 924.4,
                "speed_gap": 36.2,
                "sign": -1,
                "rotation_deg": 89.5,
                "wish_yaw_deg": 215.3,
                "velocity_yaw_deg": 181.2,
                "target_velocity_yaw_deg": 204.4,
                "target_velocity_error_deg": 23.2,
                "projected_forward": 12.5,
                "projected_side": -399.8,
            },
        )

        summary = run_frobodm2_lab.summarize_moveprobe_commands(commands)
        zjump_summary = summary["players"][0]["zjump_state"]
        self.assertEqual(zjump_summary["sample_count"], 1)
        self.assertEqual(zjump_summary["phase_values"], [2])
        self.assertEqual(zjump_summary["release_rule_values"], [1])
        self.assertAlmostEqual(zjump_summary["max_horizontal_speed"], 475.2, places=1)

    def test_parse_moveprobe_qwd_event_logs(self) -> None:
        events = run_frobodm2_lab.parse_moveprobe_qwd_event_logs(
            "\n".join(
                [
                    "noise before",
                    "FBMOVEPROBE_QWD_EVENT time=12.125 ed=2 name=/ bro event=activate "
                    "target=0 next=0 count=14 distance=83.482 advanced=0 active=1 "
                    "complete=0 active_seconds=0.000 origin=-24.500,120.000,32.000",
                    "FBMOVEPROBE_QWD_EVENT time=12.250 ed=2 name=/ bro event=advance "
                    "target=0 next=1 count=14 distance=72.250 advanced=1 active=1 "
                    "complete=0 active_seconds=0.125 origin=-20.000,128.000,32.000",
                ]
            )
        )

        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["name"], "/ bro")
        self.assertEqual(events[0]["event"], "activate")
        self.assertEqual(events[0]["target_index"], 0)
        self.assertEqual(events[0]["next_index"], 0)
        self.assertEqual(events[0]["control_point_count"], 14)
        self.assertEqual(events[0]["distance_qu"], 83.482)
        self.assertEqual(events[0]["advanced_control_points"], 0)
        self.assertTrue(events[0]["active"])
        self.assertFalse(events[0]["complete"])
        self.assertEqual(events[0]["origin"], {"x": -24.5, "y": 120.0, "z": 32.0})
        self.assertEqual(events[1]["event"], "advance")
        self.assertEqual(events[1]["target_index"], 0)
        self.assertEqual(events[1]["next_index"], 1)
        self.assertEqual(events[1]["advanced_control_points"], 1)

        summary = run_frobodm2_lab.summarize_moveprobe_qwd_events(events)
        self.assertEqual(summary["schema"], "komodobots.moveprobe_qwd_events.v1")
        self.assertEqual(summary["event_count"], 2)
        self.assertEqual(summary["players"][0]["event_counts"], {"activate": 1, "advance": 1})
        self.assertEqual(summary["players"][0]["max_advanced_control_points"], 1)

    def test_parse_moveprobe_s23_event_logs(self) -> None:
        events = run_frobodm2_lab.parse_moveprobe_s23_event_logs(
            "\n".join(
                [
                    "FBMOVEPROBE_S23 time=42.000 ed=2 name=/ bro event=attempt "
                    "attempt=1 armed=0 done=0 vh=0.000 herr=999.000 d_lip=168.125 "
                    "origin=-3516.125,3712.000,-453.125 velocity=0.000,0.000,0.000",
                    "FBMOVEPROBE_S23 time=43.250 ed=2 name=/ bro event=release "
                    "attempt=1 armed=0 done=1 vh=475.250 herr=8.750 d_lip=12.000 "
                    "origin=-3360.000,3700.000,-488.000 velocity=470.000,-70.000,0.000",
                ]
            )
        )

        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["event"], "attempt")
        self.assertEqual(events[0]["attempt"], 1)
        self.assertFalse(events[0]["armed"])
        self.assertEqual(events[0]["distance_to_lip_qu"], 168.125)
        self.assertEqual(events[1]["event"], "release")
        self.assertTrue(events[1]["done"])
        self.assertEqual(events[1]["vh_qu_per_s"], 475.25)
        self.assertEqual(events[1]["velocity"], {"x": 470.0, "y": -70.0, "z": 0.0})

        summary = run_frobodm2_lab.summarize_moveprobe_s23_events(events)
        self.assertEqual(summary["schema"], "komodobots.moveprobe_s23_events.v1")
        self.assertEqual(summary["event_count"], 2)
        self.assertEqual(summary["players"][0]["event_counts"], {"attempt": 1, "release": 1})
        self.assertEqual(summary["players"][0]["max_vh_qu_per_s"], 475.25)

    def test_parse_moveprobe_replay_state_and_events(self) -> None:
        commands = run_frobodm2_lab.parse_moveprobe_command_logs(
            "FBMOVEPROBE_CMD time=13.000 ed=2 name=/ bro mode=10 msec=13 "
            "angles=10.8,-42.6,0.0 move=0,508,0 buttons=2 impulse=0 "
            "diag=270.0,-42.6,312.6,0 "
            "route=12,10,42,14,32768,8192,0,1.250 "
            "water=1,-3,528,0,0.000,25.5,-4.0,80.0,0.100,0.200,0.300 "
            "probe=0,0,999.000,999.000,1.000 "
            "qwd=0,0,0,999999.000,0,0,0.000 "
            "replay=1,0,42,692,18.375,-800.000,-120.000,-15.000,17.625,5.250"
        )
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0]["mode"], 10)
        self.assertEqual(
            commands[0]["replay_state"],
            {
                "active": True,
                "complete": False,
                "cursor": 42,
                "frame_count": 692,
                "divergence_qu": 18.375,
                "divergence_h_qu": 17.625,
                "divergence_v_qu": 5.25,
                "expected_origin": {"x": -800.0, "y": -120.0, "z": -15.0},
            },
        )
        summary = run_frobodm2_lab.summarize_moveprobe_commands(commands)
        replay_summary = summary["players"][0]["replay_state"]
        self.assertEqual(replay_summary["max_divergence_qu"], 18.375)
        self.assertEqual(replay_summary["max_divergence_h_qu"], 17.625)
        self.assertEqual(replay_summary["max_divergence_v_qu"], 5.25)
        self.assertEqual(replay_summary["frame_count"], 692)

        events = run_frobodm2_lab.parse_moveprobe_replay_event_logs(
            "\n".join(
                [
                    "FBMOVEPROBE_REPLAY_EVENT time=13.000 ed=2 name=/ bro event=activate "
                    "cursor=0 count=692 divergence=0.000 divergence_h=0.000 divergence_v=0.000 "
                    "origin=-895.375,-129.125,-15.875 expected=-895.375,-129.125,-15.875",
                    "FBMOVEPROBE_REPLAY_EVENT time=22.000 ed=2 name=/ bro event=complete "
                    "cursor=691 count=692 divergence=512.250 divergence_h=500.000 divergence_v=110.000 "
                    "origin=100.000,200.000,40.000 expected=-50.000,300.000,24.000",
                ]
            )
        )
        self.assertEqual([e["event"] for e in events], ["activate", "complete"])
        self.assertEqual(events[1]["divergence_qu"], 512.25)
        self.assertEqual(events[1]["divergence_h_qu"], 500.0)
        self.assertEqual(events[1]["divergence_v_qu"], 110.0)
        self.assertEqual(events[1]["cursor"], 691)

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


class PositionHeatmapTests(unittest.TestCase):
    def test_bin_samples_clamps_corners_and_centre(self) -> None:
        grid = _heatmap_grid(nx=64, ny=64)
        # mins -> (0,0); maxs -> (63,63); a sample beyond maxs clamps to the edge
        # cell rather than being dropped.
        samples = [
            {"time_ms": 0, "origin": [-984.0, -960.0, 0.0]},
            {"time_ms": 1, "origin": [2048.0, 1136.0, 0.0]},
            {"time_ms": 2, "origin": [9999.0, 9999.0, 0.0]},  # out of bounds -> clamped
            {"time_ms": 3, "origin": [-984.0, -960.0, 0.0]},  # same cell as first
        ]
        bins = bin_samples(samples, grid)
        # Sparse, sorted, summed: (0,0) seen twice, (63,63) twice (maxs + clamp).
        self.assertEqual(bins, [[0, 0, 2], [63, 63, 2]])

    def test_bin_samples_robust_to_garbled_rows(self) -> None:
        grid = _heatmap_grid()
        samples = [
            {"time_ms": 0, "origin": [0.0, 0.0, 0.0]},
            {"time_ms": 1, "origin": "nope"},          # bad origin type
            {"time_ms": 2, "origin": [1.0]},            # too short
            {"time_ms": 3, "origin": ["x", "y", "z"]},  # non-numeric
            "not-a-dict",
        ]
        bins = bin_samples(samples, grid)
        # Only the one valid sample bins; the rest are skipped (never raises).
        self.assertEqual(len(bins), 1)
        self.assertEqual(bins[0][2], 1)

    def test_derive_deaths_joins_victim_name_to_nearest_sample(self) -> None:
        analysis = {
            "frags": {
                "totalFrags": 2,
                "frags": [
                    {"time": 1000, "killer": "/ bot", "victim": "/ bot", "weapon": "rl"},
                    {"time": 5000, "killer": "/ enemy", "victim": "/ bot", "weapon": "lg"},
                ],
            }
        }
        samples_by_slot = {
            1: [
                {"time_ms": 0, "origin": [10.0, 20.0, 30.0]},
                {"time_ms": 1100, "origin": [40.0, 50.0, 60.0]},  # nearest to t=1000
                {"time_ms": 5000, "origin": [70.0, 80.0, 90.0]},  # exact match t=5000
            ]
        }
        deaths = derive_deaths(analysis, samples_by_slot, {"/ bot": 1})
        self.assertEqual(
            deaths[1],
            [
                {"t_ms": 1000, "origin": [40.0, 50.0, 60.0]},
                {"t_ms": 5000, "origin": [70.0, 80.0, 90.0]},
            ],
        )

    def test_derive_deaths_empty_on_missing_or_garbled_frags(self) -> None:
        samples = {1: [{"time_ms": 0, "origin": [0.0, 0.0, 0.0]}]}
        names = {"/ bot": 1}
        self.assertEqual(derive_deaths({}, samples, names), {})
        self.assertEqual(derive_deaths({"frags": None}, samples, names), {})
        self.assertEqual(derive_deaths({"frags": {"frags": "nope"}}, samples, names), {})
        self.assertEqual(derive_deaths("not-a-dict", samples, names), {})
        # A death for an unknown victim name contributes nothing.
        analysis = {"frags": {"frags": [{"time": 1, "victim": "/ ghost", "weapon": "sg"}]}}
        self.assertEqual(derive_deaths(analysis, samples, names), {})

    def test_compute_movement_metrics_emits_position_density(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            (run_dir / "run.env").write_text("MAP=dm3\n", encoding="utf-8")
            (run_dir / "analysis.json").write_text(
                json.dumps(
                    {
                        "match": {"map": "dm3", "duration": 10000},
                        "frags": {
                            "totalFrags": 1,
                            "frags": [{"time": 1000, "killer": "/ a", "victim": "/ bot", "weapon": "rl"}],
                        },
                    }
                ),
                encoding="utf-8",
            )
            events_path = run_dir / "events.txt"
            events = [
                {"kind": 0, "time": 0, "data": {"Data": {"MaxSpeed": 320, "LevelName": "dm3"}, "Time": 0}},
                {"kind": 1, "time": 0, "data": {"Player": {"Slot": 1, "UserID": 2, "Name": "/ bot", "Spectator": False}, "Time": 0}},
                {"kind": 5, "time": 0, "data": {"PlayerNum": 1, "Origin": [-984, -960, 0], "TimeMs": 0}},
                {"kind": 5, "time": 1, "data": {"PlayerNum": 1, "Origin": [1000, 100, 40], "TimeMs": 1100}},
            ]
            events_path.write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")

            metrics = compute_movement_metrics(events_path, run_dir=run_dir)

        self.assertEqual(metrics["schema"], "komodobots.movement_metrics.v3")
        density = metrics["position_density"]
        self.assertEqual(density["schema"], "komodobots.position_density.v1")
        self.assertEqual(density["grid"]["nx"], 64)
        self.assertEqual(density["grid"]["origin"], [-984.0, -960.0])
        row = next(p for p in density["players"] if p["slot"] == 1)
        self.assertEqual(row["name"], "/ bot")
        self.assertEqual(row["bins"], [[0, 0, 1], [41, 32, 1]])
        # Death at t=1000 snaps to the nearest sample (t=1100, origin [1000,100,40]).
        self.assertEqual(row["deaths"], [[1000.0, 100.0, 40.0]])

    def test_position_density_excludes_out_of_match_samples(self) -> None:
        # Regression: the heatmap must clamp to the SAME in-match window the
        # speed metrics use. A pre-name sample (t=0) and a post-duration sample
        # (t=5000) sit in a different grid cell than the in-match samples; only
        # the in-match (t=600/900) cell may appear in the bins, and the death
        # snap must use an in-match sample, not the out-of-window ones.
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            (run_dir / "run.env").write_text("MAP=dm3\n", encoding="utf-8")
            (run_dir / "analysis.json").write_text(
                json.dumps(
                    {
                        "match": {"map": "dm3", "duration": 1000},
                        "frags": {
                            "totalFrags": 1,
                            "frags": [{"time": 700, "killer": "/ a", "victim": "/ bot", "weapon": "rl"}],
                        },
                    }
                ),
                encoding="utf-8",
            )
            events_path = run_dir / "events.txt"
            events = [
                {"kind": 0, "time": 0, "data": {"Data": {"MaxSpeed": 320, "LevelName": "dm3"}, "Time": 0}},
                {"kind": 1, "time": 0, "data": {"Player": {"Slot": 1, "UserID": 2, "Name": "/ bot", "Spectator": False}, "TimeMs": 500}},
                # Pre-name sample (before first_named_time_ms=500) -> out-of-window cell [41,32].
                {"kind": 5, "time": 0, "data": {"PlayerNum": 1, "Origin": [1000, 100, 40], "TimeMs": 0}},
                # Valid in-match samples -> cell [0,0].
                {"kind": 5, "time": 0.6, "data": {"PlayerNum": 1, "Origin": [-984, -960, 0], "TimeMs": 600}},
                {"kind": 5, "time": 0.9, "data": {"PlayerNum": 1, "Origin": [-984, -960, 0], "TimeMs": 900}},
                # Post-duration sample (after match_duration_ms=1000) -> out-of-window cell [41,32].
                {"kind": 5, "time": 5, "data": {"PlayerNum": 1, "Origin": [1000, 100, 40], "TimeMs": 5000}},
            ]
            events_path.write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")

            metrics = compute_movement_metrics(events_path, run_dir=run_dir)

        density = metrics["position_density"]
        row = next(p for p in density["players"] if p["slot"] == 1)
        # Only the in-match (t=600/900) cell survives; both edge samples sit in
        # cell [41,32], which must be absent.
        self.assertEqual(row["bins"], [[0, 0, 2]])
        self.assertNotIn([41, 32, 1], row["bins"])
        self.assertNotIn([41, 32, 2], row["bins"])
        # Death at t=700 snaps to the nearest IN-WINDOW sample (t=600, [-984,-960,0]),
        # never the closer-in-time out-of-window samples.
        self.assertEqual(row["deaths"], [[-984.0, -960.0, 0.0]])


if __name__ == "__main__":
    unittest.main()
