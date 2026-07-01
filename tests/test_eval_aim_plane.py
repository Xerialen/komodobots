"""Deps-free gating test for the route-grade measurement-plane provenance (Codex #468 P1).

A `--aim policy --grade-route` run must NOT label its report/caveats as replayed-aim — that would make a
self-yaw route-grade look like replayed-human-aim evidence. `eval_broad_closedloop` imports deps-free
(torch is lazy inside run_eval), so we import it and assert the pure aim-plane helpers + `_build_caveats`
reflect the actual `aim_mode`.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ml"))

import eval_broad_closedloop as CL  # noqa: E402  (module-level is deps-free; torch is lazy in run_eval)


class TestAimPlaneProvenance(unittest.TestCase):
    def test_policy_plane_is_self_yaw_not_replayed(self):
        self.assertEqual(CL._aim_head_label("policy"), "POLICY_SELF_YAW")
        self.assertIn("self-yaw", CL._aim_plane_note("policy").lower())
        # the caveats block must carry the self-yaw plane, not the old hard-coded REPLAYED
        self.assertEqual(CL._build_caveats("policy")["aim_head"], "POLICY_SELF_YAW")
        self.assertIn("self-yaw", CL._build_caveats("policy")["aim_head_detail"].lower())

    def test_replayed_and_optimal_labels(self):
        self.assertEqual(CL._aim_head_label("replayed"), "REPLAYED")
        self.assertEqual(CL._aim_head_label("optimal"), "OPTIMAL_ANALYTIC")
        self.assertIn("replayed", CL._build_caveats("replayed")["aim_head_detail"].lower())
        self.assertIn("optimal", CL._aim_plane_note("optimal").lower())

    def test_default_is_replayed(self):
        self.assertEqual(CL._build_caveats()["aim_head"], "REPLAYED")


if __name__ == "__main__":
    unittest.main()
