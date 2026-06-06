from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import design_qwd_sng_hybrid_probe as design


def sequence_row(index: int) -> dict[str, object]:
    return {
        "first_frame": index * 10,
        "last_frame": index * 10 + 5,
        "first_time_s": index * 0.1,
        "last_time_s": index * 0.1 + 0.05,
        "first_waypoint_origin": [float(index * 64), 128.0, 56.0],
        "marker_id": 100 + index,
        "nearest_distance_qu": 64.0,
        "max_nearest_distance_qu": 80.0,
        "waypoint_count": 2,
    }


def hybrid_mapping(*, sequence_count: int = 4, next_probe: str = "hybrid_waypoint_controller_probe") -> dict[str, object]:
    return {
        "schema": "komodobots.qwd_frogbot_route_mapping.v1",
        "source": {
            "demo": "dm3_sng_shortcut.qwd",
            "demo_sha256": "abc123",
        },
        "mapping_summary": {
            "waypoint_count": 33,
            "collapsed_marker_count": sequence_count,
            "transition_count": max(sequence_count - 1, 0),
            "nearest_marker_distance_qu": {
                "p50": 70.0,
                "p95": 120.0,
                "max": 143.0,
                "within_128_ratio": 0.94,
            },
            "bot_graph_alignment": {
                "direct_edge_ratio": 0.0,
                "graph_reachable_ratio": 1.0,
                "shortest_path_edges_p50": 5.0,
            },
        },
        "qwd_demo_summary": {
            "commands": {
                "nonzero_forward_ratio": 0.089,
                "nonzero_side_ratio": 0.718,
                "jump_button_ratio": 0.284,
                "sidemove_abs_p50": 508.0,
            },
            "motion": {"speed_qu_per_s": {"p50": 466.0, "p95": 548.0}},
        },
        "nearest_marker_sequence": [sequence_row(index) for index in range(sequence_count)],
        "recommendation": {"next_probe": next_probe, "confidence": "medium"},
    }


class QwdSngHybridProbeDesignTests(unittest.TestCase):
    def test_build_report_preserves_hybrid_waypoints_and_command_profile(self) -> None:
        report = design.build_report(hybrid_mapping(), stage="qwd-sng-test")

        design.validate_report(report)

        self.assertEqual(
            report["decision"]["verdict"],
            "ready_to_implement_qwd_sng_hybrid_server_loop_probe",
        )
        self.assertEqual(len(report["control_points"]), 4)
        contract = report["probe_contract"]
        cvars = contract["suggested_cvars"]
        self.assertEqual(cvars["k_fb_moveprobe_mode"], 9)
        self.assertEqual(cvars["k_fb_moveprobe_sidemove"], 508)
        self.assertIn("0.000,128.000,56.000", cvars["k_fb_moveprobe_qwd_waypoints"])
        self.assertEqual(report["qwd_command_profile"]["recommended_qwd_strafe_sidemove"], 508)

    def test_validate_blocks_non_hybrid_mapping_recommendation(self) -> None:
        report = design.build_report(hybrid_mapping(next_probe="route_following_probe"), stage="qwd-sng-test")

        with self.assertRaisesRegex(design.QwdHybridProbeDesignError, "hybrid"):
            design.validate_report(report)

    def test_control_point_sequence_must_be_bounded(self) -> None:
        with self.assertRaisesRegex(design.QwdHybridProbeDesignError, "above max"):
            design.build_report(hybrid_mapping(sequence_count=17), stage="qwd-sng-test")

    def test_control_point_sequence_must_have_minimum_advance_targets(self) -> None:
        with self.assertRaisesRegex(design.QwdHybridProbeDesignError, "at least"):
            design.build_report(hybrid_mapping(sequence_count=3), stage="qwd-sng-test")

    def test_sidemove_falls_back_to_standard_command_when_missing(self) -> None:
        source = hybrid_mapping()
        commands = source["qwd_demo_summary"]["commands"]
        assert isinstance(commands, dict)
        commands["sidemove_abs_p50"] = 0

        report = design.build_report(source, stage="qwd-sng-test")

        self.assertEqual(report["qwd_command_profile"]["recommended_qwd_strafe_sidemove"], 400)

    def test_main_writes_custom_json_and_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mapping_path = root / "mapping.json"
            output_json = root / "evidence" / "out.json"
            output_md = root / "evidence" / "out.md"
            mapping_path.write_text(json.dumps(hybrid_mapping()), encoding="utf-8")

            design.main(
                [
                    "--mapping",
                    str(mapping_path),
                    "--output-json",
                    str(output_json),
                    "--output-md",
                    str(output_md),
                ]
            )

            self.assertTrue(output_json.exists())
            self.assertTrue(output_md.exists())


if __name__ == "__main__":
    unittest.main()
