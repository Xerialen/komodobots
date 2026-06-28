#!/usr/bin/env python3
"""Round-trip gate for the generated route-canon header (#422 T3.1).

experiments/route_observatory/gen_route_canon_header.py derives the committed C header
experiments/ktx_moveprobe/live/route_canon_dm3.h from data/catalog/route_canon.dm3.json. This test
pins the generate-first contract (mirroring scripts/generate_from_registry.py's --check guard):

  * base-only: the header carries the `route_class=='base'` highways ONLY (shortcut excluded);
  * downsample keeps the first + last trajectory point of every base highway;
  * --check passes on the committed header and fails on a mutated one (the anti-drift guard);
  * the committed header is byte-identical to a fresh regen (zero-drift);
  * the overlap WARN fires when two base polylines pass within 2*R_OFF in (x,y).

Pure standard library (CI floor: Python 3.12).
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "route_observatory"))

import gen_route_canon_header as gen  # noqa: E402

COMMITTED_H = ROOT / "experiments" / "ktx_moveprobe" / "live" / "route_canon_dm3.h"


class TestBaseOnlyFilter(unittest.TestCase):
    def setUp(self):
        self.canon = gen.load_canon()

    def test_base_filter_drops_non_base(self):
        base = gen.base_highways(self.canon)
        self.assertTrue(base, "expected at least one base highway")
        self.assertTrue(all(h["route_class"] == "base" for h in base))
        # the canon has at least one non-base highway (a shortcut) that must NOT be emitted
        non_base = [h for h in self.canon["highways"] if h.get("route_class") != "base"]
        self.assertTrue(non_base, "fixture should contain a non-base highway to exclude")
        header = gen.build_header(self.canon)
        self.assertIn(f"#define MHW_N_BASE {len(base)}", header)
        for h in non_base:
            self.assertNotIn(str(h.get("id", "")), header,
                             f"non-base highway {h.get('id')!r} leaked into the header")


class TestDownsample(unittest.TestCase):
    def test_small_polyline_passthrough(self):
        pts = [(0.0, 0.0), (1.0, 1.0), (2.0, 2.0)]
        self.assertEqual(gen.downsample(pts, 72), pts)

    def test_cap_and_endpoints(self):
        pts = [(float(i), float(2 * i)) for i in range(500)]
        out = gen.downsample(pts, 72)
        self.assertLessEqual(len(out), 72)
        self.assertEqual(out[0], pts[0])
        self.assertEqual(out[-1], pts[-1])

    def test_real_base_trajectories_keep_endpoints(self):
        canon = gen.load_canon()
        for h in gen.base_highways(canon):
            xy = gen.traj_xy(h)
            out = gen.downsample(xy, gen.DEFAULT_MAX_PTS)
            self.assertEqual(out[0], xy[0])
            self.assertEqual(out[-1], xy[-1])
            self.assertLessEqual(len(out), gen.DEFAULT_MAX_PTS)


class TestCheckMode(unittest.TestCase):
    def test_committed_header_is_fresh(self):
        # the committed header must equal a fresh regen (zero-drift)
        canon = gen.load_canon()
        self.assertEqual(COMMITTED_H.read_text(encoding="utf-8"), gen.build_header(canon))

    def test_check_passes_on_committed(self):
        self.assertEqual(gen.main(["--check"]), 0)

    def test_check_fails_on_drift(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "route_canon_dm3.h"
            self.assertEqual(gen.main(["-o", str(out)]), 0)
            self.assertEqual(gen.main(["--check", "-o", str(out)]), 0)
            out.write_text(out.read_text(encoding="utf-8") + "\n/* drift */\n", encoding="utf-8")
            self.assertEqual(gen.main(["--check", "-o", str(out)]), 1)

    def test_check_fails_when_missing(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(gen.main(["--check", "-o", str(Path(d) / "absent.h")]), 1)


class TestOverlapWarn(unittest.TestCase):
    def test_close_polylines_flagged(self):
        a = [(0.0, 0.0), (0.0, 100.0)]
        b = [(10.0, 0.0), (10.0, 100.0)]   # ~10 qu apart < 2*R_OFF
        self.assertTrue(gen.check_overlaps([a, b]))

    def test_far_polylines_not_flagged(self):
        a = [(0.0, 0.0), (0.0, 100.0)]
        b = [(5000.0, 0.0), (5000.0, 100.0)]
        self.assertEqual(gen.check_overlaps([a, b]), [])

    def test_build_header_emits_warning_on_synthetic_overlap(self):
        canon = {
            "schema": "komodobots.route_canon.v1", "map": "dm3",
            "_provenance": {"date": "2026-01-01"},
            "highways": [
                {"id": "ovl_a", "route_class": "base", "end_xyz": [0.0, 100.0, 0.0],
                 "segments": [{"trajectory": [[0, 0.0, 0.0, 0], [0, 0.0, 100.0, 0]]}]},
                {"id": "ovl_b", "route_class": "base", "end_xyz": [10.0, 100.0, 0.0],
                 "segments": [{"trajectory": [[0, 10.0, 0.0, 0], [0, 10.0, 100.0, 0]]}]},
            ],
        }
        with self.assertLogs(gen.LOGGER, level="WARNING") as cm:
            gen.build_header(canon)
        self.assertTrue(any("pass within" in m for m in cm.output))


if __name__ == "__main__":
    unittest.main()
