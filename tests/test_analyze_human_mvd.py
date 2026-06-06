from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import analyze_human_mvd


class HumanMvdAnalysisTests(unittest.TestCase):
    def test_infer_map_prefers_frobodm2_over_dm2_substring(self) -> None:
        self.assertEqual(analyze_human_mvd.infer_map_from_text("ffa_frobodm2_20260606.mvd"), "frobodm2")
        self.assertEqual(analyze_human_mvd.infer_map_from_text("4on4_red_vs_blue_dm2.mvd"), "dm2")
        self.assertEqual(analyze_human_mvd.infer_map_from_text("1on1_reppie_vs_locust_aerowalk.mvd"), "aerowalk")
        self.assertEqual(analyze_human_mvd.infer_map_from_match_title("The Abandoned Base"), "dm3")
        self.assertEqual(analyze_human_mvd.infer_map_from_match_title("Frogbotrophobopolis"), "frobodm2")
        self.assertEqual(analyze_human_mvd.format_stage_label("s4b-dm2"), "S4b-dm2")

    def test_inventory_records_dm2_gap_and_hashes_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "1on1_a_vs_b_aerowalk.mvd").write_bytes(b"aero")
            (root / "4on4_a_vs_b_dm2.mvd").write_bytes(b"dm2")
            (root / "ffa_frobodm2.mvd").write_bytes(b"frobodm2")

            inventory = analyze_human_mvd.build_inventory(root)

        self.assertEqual(inventory["demo_count"], 3)
        self.assertTrue(inventory["has_dm2_candidate"])
        self.assertEqual(inventory["dm2_candidate_count"], 1)
        self.assertEqual(inventory["map_inference_method"], "filename_token_heuristic")
        maps = {demo["name"]: demo["inferred_map"] for demo in inventory["demos"]}
        self.assertEqual(maps["ffa_frobodm2.mvd"], "frobodm2")
        self.assertTrue(all(demo["sha256"] for demo in inventory["demos"]))

    def test_comparison_note_distinguishes_dm2_anchor_from_parser_proof(self) -> None:
        verdict = analyze_human_mvd.comparison_verdict("dm2", ["dm3", "frobodm2"], True)

        self.assertEqual(verdict, "human_dm2_available_but_s3g_not_dm2")
        self.assertIn("true-DM2 human anchor", analyze_human_mvd.comparison_note(verdict))

    def test_build_summary_marks_aerowalk_as_parser_proof_only_against_s3g(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            source_demo = run_dir / "1on1_reppie_vs_locust_aerowalk.mvd"
            source_demo.write_bytes(b"demo")
            (run_dir / "analysis.json").write_text(
                json.dumps({"match": {"map": "Aerowalk", "duration": 600057}, "frags": [{}, {}]}),
                encoding="utf-8",
            )
            (run_dir / "movement-metrics.json").write_text(
                json.dumps(
                    {
                        "parser": {"event_count": 10, "position_event_count": 8},
                        "players": [
                            {
                                "slot": 1,
                                "name": "reppie",
                                "sample_count": 40,
                                "active_time_s": 3,
                                "horizontal_distance_qu": 960,
                                "avg_horizontal_speed_qu_per_s": 320,
                                "p95_horizontal_speed_qu_per_s": 420,
                                "max_horizontal_speed_qu_per_s": 500,
                                "stationary_time_ratio": 0.01,
                                "low_speed_time_ratio": 0.02,
                                "airborne_proxy_time_ratio": 0.3,
                                "jump_cadence_per_min": 60,
                            },
                            {
                                "slot": 2,
                                "name": "inactive",
                                "sample_count": 2,
                                "active_time_s": 0,
                                "horizontal_distance_qu": 0,
                                "avg_horizontal_speed_qu_per_s": 0,
                                "p95_horizontal_speed_qu_per_s": 0,
                                "max_horizontal_speed_qu_per_s": 0,
                                "stationary_time_ratio": 0,
                                "low_speed_time_ratio": 0,
                                "airborne_proxy_time_ratio": 0,
                                "jump_cadence_per_min": 0,
                            },
                            {
                                "slot": 3,
                                "name": "idle",
                                "sample_count": 40,
                                "active_time_s": 3,
                                "horizontal_distance_qu": 0,
                                "avg_horizontal_speed_qu_per_s": 0,
                                "p95_horizontal_speed_qu_per_s": 0,
                                "max_horizontal_speed_qu_per_s": 0,
                                "stationary_time_ratio": 1,
                                "low_speed_time_ratio": 1,
                                "airborne_proxy_time_ratio": 0,
                                "jump_cadence_per_min": 0,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            bot_summary = run_dir / "moveprobe-s3g-summary.json"
            bot_summary.write_text(
                json.dumps({"schema": "komodobots.moveprobe_plausibility.v1", "runs": [{"map": "dm3"}]}),
                encoding="utf-8",
            )

            summary = analyze_human_mvd.build_human_summary(
                run_dir=run_dir,
                source_demo=source_demo,
                inventory={"demo_count": 1, "dm2_candidate_count": 0, "has_dm2_candidate": False, "root": "root"},
                parser_exits={"json": 0, "md": 0, "events": 1},
                bot_summary_path=bot_summary,
                stage="s4a",
            )

        self.assertEqual(summary["stage"], "s4a")
        self.assertEqual(summary["demo"]["map"], "aerowalk")
        self.assertEqual(summary["match"]["frag_count"], 2)
        self.assertFalse(summary["comparison_context"]["same_map_comparable_to_s3g"])
        self.assertEqual(summary["comparison_context"]["verdict"], "parser_proof_only_no_local_dm2")
        self.assertEqual(summary["movement_players"][0]["name"], "reppie")
        self.assertEqual(len(summary["movement_players"]), 1)
        self.assertEqual([row["name"] for row in summary["ignored_named_slots"]], ["inactive", "idle"])
        self.assertIn("parser proof", summary["comparison_context"]["note"])
        self.assertFalse(summary["same_map_movement_comparison"]["available"])

    def test_build_summary_compares_same_map_bot_rows_against_human_range(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            source_demo = run_dir / "4on4_blue_vs_red[dm3]20260426-0307.mvd"
            source_demo.write_bytes(b"demo")
            (run_dir / "analysis.json").write_text(
                json.dumps({"match": {"map": "The Abandoned Base", "duration": 729226}, "frags": [{}]}),
                encoding="utf-8",
            )
            (run_dir / "movement-metrics.json").write_text(
                json.dumps(
                    {
                        "parser": {"event_count": 10, "position_event_count": 8},
                        "players": [
                            {
                                "slot": 1,
                                "name": "fast",
                                "sample_count": 40,
                                "active_time_s": 3,
                                "horizontal_distance_qu": 960,
                                "avg_horizontal_speed_qu_per_s": 320,
                                "p95_horizontal_speed_qu_per_s": 500,
                                "max_horizontal_speed_qu_per_s": 700,
                                "stationary_time_ratio": 0.05,
                                "low_speed_time_ratio": 0.10,
                                "airborne_proxy_time_ratio": 0.35,
                                "jump_cadence_per_min": 60,
                            },
                            {
                                "slot": 2,
                                "name": "slow",
                                "sample_count": 40,
                                "active_time_s": 3,
                                "horizontal_distance_qu": 720,
                                "avg_horizontal_speed_qu_per_s": 240,
                                "p95_horizontal_speed_qu_per_s": 390,
                                "max_horizontal_speed_qu_per_s": 600,
                                "stationary_time_ratio": 0.12,
                                "low_speed_time_ratio": 0.22,
                                "airborne_proxy_time_ratio": 0.20,
                                "jump_cadence_per_min": 30,
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            bot_summary = run_dir / "moveprobe-s3g-summary.json"
            bot_summary.write_text(
                json.dumps(
                    {
                        "schema": "komodobots.moveprobe_plausibility.v1",
                        "runs": [
                            {
                                "run_id": "20260606T003718Z",
                                "map": "dm3",
                                "players": [
                                    {
                                        "player": "/ bro",
                                        "avg_horizontal_speed_qu_per_s": 190,
                                        "p95_horizontal_speed_qu_per_s": 361,
                                        "stationary_time_ratio": 0.004,
                                        "low_speed_time_ratio": 0.261,
                                        "airborne_proxy_time_ratio": 0.442,
                                    },
                                    {
                                        "player": "/ goldenboy",
                                        "avg_horizontal_speed_qu_per_s": 248,
                                        "p95_horizontal_speed_qu_per_s": 375,
                                        "stationary_time_ratio": 0.025,
                                        "low_speed_time_ratio": 0.189,
                                        "airborne_proxy_time_ratio": 0.248,
                                    },
                                ],
                            },
                            {
                                "run_id": "20260606T003808Z",
                                "map": "frobodm2",
                                "players": [],
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            summary = analyze_human_mvd.build_human_summary(
                run_dir=run_dir,
                source_demo=source_demo,
                inventory={"demo_count": 2, "dm2_candidate_count": 1, "has_dm2_candidate": True, "root": "root"},
                parser_exits={"json": 0, "md": 0, "events": 1},
                bot_summary_path=bot_summary,
                stage="s4c-dm3",
            )

        comparison = summary["same_map_movement_comparison"]
        self.assertTrue(summary["comparison_context"]["same_map_comparable_to_s3g"])
        self.assertEqual(summary["comparison_context"]["verdict"], "same_map_human_reference_available")
        self.assertTrue(comparison["available"])
        self.assertEqual(comparison["human_player_count"], 2)
        self.assertEqual(comparison["bot_player_count"], 2)
        bro = comparison["bot_players"][0]
        self.assertEqual(bro["player"], "/ bro")
        self.assertEqual(bro["against_human_range"]["avg_horizontal_speed_qu_per_s"], "below_human_min")
        self.assertEqual(bro["against_human_range"]["airborne_proxy_time_ratio"], "above_human_max")


if __name__ == "__main__":
    unittest.main()
