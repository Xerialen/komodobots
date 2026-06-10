"""freeroam_tws: free-roam sanctioning must keep the whole run without ever
counting a teleport throw as movement.

Free-roam has no route, so every teleporter is sanctioned (entrances derived
from the run's own teleport steps, once per use). The metric itself stays
route_metrics.time_weighted_speed -- this only locks the parameterization,
including that repeated use of the SAME teleporter does not truncate (the
route-gate guard would; free-roam must not)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from freeroam_tws import freeroam_tws, observed_teleport_entrances  # noqa: E402
from route_metrics import time_weighted_speed  # noqa: E402

TICK = 0.01
STEP = 10.0  # qu per tick of plain walking -> 1000 qu/s


def walk(n, x0=0.0, t0=0.0):
    return [{"t": t0 + i * TICK, "x": x0 + i * STEP, "y": 0.0, "z": 0.0,
             "vh": STEP / TICK} for i in range(n)]


class TestFreeRoamConvention(unittest.TestCase):
    def test_plain_walk_unchanged(self):
        rows = walk(101)  # 1000 qu over 1.0 s
        self.assertEqual(observed_teleport_entrances(rows), ())
        self.assertAlmostEqual(freeroam_tws(rows), 1000.0, places=6)

    def test_teleport_kept_but_throw_not_counted(self):
        # 0.5 s walking, 800 qu teleport throw, 0.5 s more walking.
        pre = walk(51)
        post = walk(51, x0=pre[-1]["x"] + 800.0, t0=pre[-1]["t"] + TICK)
        rows = pre + post
        # route-gate behaviour would truncate this as a stray teleport:
        self.assertAlmostEqual(time_weighted_speed(rows), 1000.0, places=6)
        # free-roam sanctions it: full duration counted, throw excluded.
        self.assertAlmostEqual(freeroam_tws(rows), 1000.0 / 1.01, places=6)

    def test_same_teleporter_reused_does_not_truncate(self):
        # Two throws from the SAME entrance pad (free-roam loops do this).
        a = walk(51)
        b = walk(51, x0=a[-1]["x"] + 800.0, t0=a[-1]["t"] + TICK)
        # walk back to the same pad x, then teleport again
        backpad = [{"t": b[-1]["t"] + (i + 1) * TICK,
                    "x": a[-1]["x"], "y": 0.0, "z": 0.0, "vh": 0.0}
                   for i in range(2)]
        c = walk(51, x0=a[-1]["x"] + 800.0, t0=backpad[-1]["t"] + TICK)
        rows = a + b[:1] + backpad + c   # jump, land, snap back, jump again
        ents = observed_teleport_entrances(rows)
        self.assertGreaterEqual(len(ents), 2, "each use sanctioned separately")
        # whole segment kept: tws strictly positive and uses full duration
        tws = freeroam_tws(rows)
        dt = rows[-1]["t"] - rows[0]["t"]
        self.assertAlmostEqual(tws, (500.0 + 500.0) / dt, places=6)


if __name__ == "__main__":
    unittest.main()
