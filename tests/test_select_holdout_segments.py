"""Deps-free gating test for the B1 held-out route-grade selection (Codex #472 P1).

The anti-Goodhart claim of `--select-by-route-grade` is that the honest route-grade is computed on routes
DISJOINT from the RL reset episodes. That holds only if the holdout suffix (`select_start_segments(skip=R)`)
skips the SAME qualifying prefix the training resets consume. Qualification is HORIZON-sensitive (an episode
must be at least `horizon+1` ticks), so grading the holdout with a different horizon than `build_segments`
uses (`args.horizon`) can skip a different prefix and leak reset routes into selection. `_route_grade_screen`
now pins `horizon=args.horizon`; these tests lock the two properties that make that correct.

`eval_broad_closedloop` imports deps-free (torch is lazy in run_eval), so we import it directly.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ml"))

import eval_broad_closedloop as CL  # noqa: E402  (module-level is deps-free; torch is lazy in run_eval)


def _ep(n):
    """An episode of n airborne-moving ticks (qualifies for any horizon <= n-1 with min_airborne_moving>=1)."""
    return [{"self": {"onground": False, "hspeed": 999.0}} for _ in range(n)]


class TestHoldoutSegments(unittest.TestCase):
    def test_holdout_suffix_disjoint_from_reset_prefix(self):
        # SAME horizon: resets = first R qualifying episodes; holdout = skip=R -> the NEXT G. Disjoint.
        eps = {f"e{i:02d}": _ep(30) for i in range(20)}
        H, R, G = 20, 8, 6
        resets = CL.select_start_segments(eps, horizon=H, n_segments=R, min_airborne_moving=1)
        holdout = CL.select_start_segments(eps, horizon=H, n_segments=G, skip=R, min_airborne_moving=1)
        self.assertEqual(len(resets), R)
        self.assertEqual(len(holdout), G)
        self.assertEqual({e[0] for e in resets} & {e[0] for e in holdout}, set(),
                         "the holdout suffix must not reuse ANY training-reset episode")

    def test_skip0_is_unchanged_behaviour(self):
        # Back-compat: skip=0 is byte-identical to the historical (skip-less) selection.
        eps = {f"e{i:02d}": _ep(30) for i in range(10)}
        self.assertEqual(
            CL.select_start_segments(eps, horizon=20, n_segments=5, min_airborne_moving=1),
            CL.select_start_segments(eps, horizon=20, n_segments=5, skip=0, min_airborne_moving=1))

    def test_qualifying_prefix_is_horizon_sensitive(self):
        # WHY _route_grade_screen must use the RESET horizon (Codex #472 P1): qualification needs
        # len >= horizon+1, so a different horizon changes which episodes qualify -> a different skipped
        # prefix -> the "holdout" could overlap the resets. Mixed lengths make the prefix shift.
        eps = {"a_len22": _ep(22), "b_len40": _ep(40), "c_len22": _ep(22), "d_len40": _ep(40)}
        p_h20 = [e[0] for e in CL.select_start_segments(eps, horizon=20, n_segments=2, min_airborne_moving=1)]
        p_h30 = [e[0] for e in CL.select_start_segments(eps, horizon=30, n_segments=2, min_airborne_moving=1)]
        self.assertEqual(p_h20, ["a_len22", "b_len40"], "at H=20 all qualify -> first two in sorted order")
        self.assertEqual(p_h30, ["b_len40", "d_len40"], "at H=30 only len>=31 qualify -> the prefix shifts")
        self.assertNotEqual(p_h20, p_h30,
                            "different horizon -> different qualifying prefix (so holdout MUST match resets)")


if __name__ == "__main__":
    unittest.main()
