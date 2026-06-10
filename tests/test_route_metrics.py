"""route_metrics: the headline metric must count player movement only.

Locks the Codex PR #60 P2: a SANCTIONED teleport's landing stays in the
segment (legit_segment keeps it), but its instantaneous entrance->exit
displacement is not player movement and must not inflate
time_weighted_speed. Also re-locks the stray-teleport truncation guard
(see MEMORY: "Preserve validator guards on rewrite").
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from route_metrics import legit_segment, time_weighted_speed  # noqa: E402

TICK = 0.01
STEP = 10.0  # qu per tick of plain walking -> 1000 qu/s


def walk(n, x0=0.0, t0=0.0):
    """n ticks of straight +x walking at STEP qu/tick."""
    return [{"t": t0 + i * TICK, "x": x0 + i * STEP, "y": 0.0, "z": 0.0,
             "vh": STEP / TICK, "dist_goal": 9999.0} for i in range(n)]


class TestTeleportExclusion(unittest.TestCase):
    def test_plain_walk_speed(self):
        rows = walk(101)  # 1000 qu over 1.0 s
        self.assertAlmostEqual(time_weighted_speed(rows), 1000.0, places=6)

    def test_sanctioned_teleport_throw_not_counted(self):
        # 50 ticks walking, sanctioned teleport throw of 800 qu, 50 more ticks.
        pre = walk(51)
        ent = (pre[-1]["x"], pre[-1]["y"])
        post = walk(51, x0=pre[-1]["x"] + 800.0, t0=pre[-1]["t"] + TICK)
        rows = pre + post
        seg = legit_segment(rows, tele_entrances=(ent,))
        self.assertEqual(len(seg), len(rows), "sanctioned landing must be kept")
        # 1000 qu of real walking over 1.01 s; the 800 qu throw is excluded.
        tws = time_weighted_speed(rows, tele_entrances=(ent,))
        self.assertAlmostEqual(tws, 1000.0 / 1.01, places=6)
        # Regression guard: the pre-fix value (throw counted) was ~1782 qu/s.
        self.assertLess(tws, 1100.0)

    def test_stray_teleport_still_truncates(self):
        pre = walk(51)
        post = walk(51, x0=pre[-1]["x"] + 800.0, t0=pre[-1]["t"] + TICK)
        rows = pre + post
        seg = legit_segment(rows)  # no sanctioned entrances
        self.assertEqual(len(seg), len(pre), "stray teleport must truncate")
        self.assertAlmostEqual(time_weighted_speed(rows), 1000.0, places=6)


if __name__ == "__main__":
    unittest.main()
