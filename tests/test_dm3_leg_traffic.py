"""Tests for dm3_leg_traffic --max-snap-qu zero-disables-cutoff handling (#315).

Anti-recurrence test for the falsey-0.0 bug: `--max-snap-qu 0` is DOCUMENTED to disable
the snap-radius cutoff (treat as no cap = None). The original `if args.max_snap_qu`
guard let 0.0 fall through (0.0 is falsey), leaving a 0-radius cutoff that snaps a
position ONLY when it sits exactly on a landmark — so the no-cutoff mode silently
returned empty/badly-undercounted traffic. The fix makes the check explicit
(`is not None and <= 0` -> None).

Pure stdlib; runs under `python -m unittest`. Follows the komodobots convention:
scripts/ on sys.path, module imported top-level.
"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
for _p in (str(SCRIPTS), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import dm3_leg_traffic as M  # noqa: E402

# A tiny landmark set; the position under test is deliberately FAR from both points.
LANDMARKS = [
    ("ROCKET", 0.0, 0.0, 0.0),
    ("QUAD", 100.0, 0.0, 0.0),
]
# ~224 qu from the nearest landmark (QUAD at (100,0,0)): well outside any small cutoff.
FAR_POS = (200.0, 200.0, 0.0)


class TestResolveMaxSnap(unittest.TestCase):
    """The CLI arg-handling site: 0 (and any non-positive) disables the cutoff -> None."""

    def test_zero_disables_cutoff(self):
        # the documented sentinel: 0 means "no cap". 0.0 is falsey, so this is exactly
        # the case the buggy `if args.max_snap_qu` guard got wrong.
        self.assertIsNone(M.resolve_max_snap(0.0))
        self.assertIsNone(M.resolve_max_snap(0))

    def test_negative_disables_cutoff(self):
        self.assertIsNone(M.resolve_max_snap(-1.0))

    def test_none_passes_through_as_no_cutoff(self):
        self.assertIsNone(M.resolve_max_snap(None))

    def test_positive_value_is_kept(self):
        self.assertEqual(M.resolve_max_snap(600.0), 600.0)
        self.assertEqual(M.resolve_max_snap(50.0), 50.0)


class TestNearestLandmarkCutoffSemantics(unittest.TestCase):
    """The behavioral contract the bug broke: disabled cutoff still snaps far positions."""

    def test_far_position_snaps_when_cutoff_disabled(self):
        # cutoff disabled (None) -> a far position STILL snaps to its nearest landmark.
        got = M.nearest_landmark(*FAR_POS, LANDMARKS, max_snap_qu=None)
        self.assertEqual(got, "QUAD")

    def test_far_position_rejected_with_small_positive_cutoff(self):
        # with a small positive cutoff the same far position does NOT snap (returns None),
        # proving the disabled-cutoff path above is doing real work.
        got = M.nearest_landmark(*FAR_POS, LANDMARKS, max_snap_qu=10.0)
        self.assertIsNone(got)

    def test_zero_radius_cutoff_only_snaps_exact_hits(self):
        # the BUG symptom in isolation: a literal 0.0 cutoff (what the old code left in
        # place for `--max-snap-qu 0`) rejects the far position outright...
        self.assertIsNone(M.nearest_landmark(*FAR_POS, LANDMARKS, max_snap_qu=0.0))
        # ...and snaps only a position sitting exactly on a landmark. This is why 0 had to
        # be mapped to None (no cutoff) rather than passed through as a 0-radius cutoff.
        self.assertEqual(
            M.nearest_landmark(0.0, 0.0, 0.0, LANDMARKS, max_snap_qu=0.0), "ROCKET")


if __name__ == "__main__":
    unittest.main()
