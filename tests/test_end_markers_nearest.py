"""Anti-drift lock for the directed-eval end_marker pins (#460).

Asserts every base highway's committed `end_marker` IS the nearest live FBMARKER of
ANY class to its END (2-D) -- the stated selection rule -- and that the pin is unique
within the gate's R_GOAL=256qu of exactly one END. This is the locking test the
Codex r1 BLOCK on PR #463 required: it fails the moment an authored end_marker drifts
from the reproducible rule (it would have caught the original ra_tunnel_mega_rl=69,
whose nearest-ANY is 291). Mirrors derive_end_markers.py --check.
"""
import logging
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "experiments" / "route_observatory"))

import derive_end_markers as D  # noqa: E402

logging.getLogger("derive_end_markers").setLevel(logging.CRITICAL)


class TestEndMarkersAreNearestAny(unittest.TestCase):
    def setUp(self):
        self.markers = D.load_markers()
        self.ends = D.load_base_ends()
        self.rows = D.derive(self.markers, self.ends)

    def test_committed_dump_is_the_299_marker_dm3_graph(self):
        self.assertEqual(len(self.markers), 299)

    def test_every_base_end_marker_is_nearest_any(self):
        for hid, r in self.rows.items():
            with self.subTest(highway=hid):
                self.assertIsNotNone(r["authored"], f"{hid} missing end_marker")
                self.assertEqual(
                    r["authored"], r["nearest"],
                    f"{hid}: end_marker {r['authored']} != nearest-ANY {r['nearest']} "
                    f"({r['dist']:.1f}qu)")

    def test_each_pin_uniquely_latches_one_highway(self):
        for hid, r in self.rows.items():
            with self.subTest(highway=hid):
                self.assertTrue(
                    r["unique_within_R_GOAL"],
                    f"{hid}: pin {r['nearest']} is within R_GOAL of >1 END")

    def test_known_authored_values(self):
        # The four base pins after the Codex r1 fix (ra: 69 -> 291).
        got = {hid: r["authored"] for hid, r in self.rows.items()}
        self.assertEqual(got, {
            "ra_tunnel_mega_rl": 291,
            "enter_ra_mid_ledge_top": 54,
            "low_bridge_stairs_ya": 131,
            "rl_high_bridge_window_lifts": 87,
        })

    def test_check_mode_passes_on_committed_data(self):
        self.assertEqual(D.main(["derive_end_markers.py", "--check"]), 0)


if __name__ == "__main__":
    unittest.main()
