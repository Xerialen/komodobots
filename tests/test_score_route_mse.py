"""tests/test_score_route_mse.py — gated (stdlib-only) tests for the T3.2 route-MSE scorer
(experiments/route_observatory/score_route_mse.py). Synthetic fixtures: NO MVD, NO torch, NO
duckdb — runs in the merge-gating `python -m unittest discover -s tests` floor.

Covers: identical -> MSE~0; a constant +D offset -> rmse~D; resample endpoint inclusivity; both
grids run; a known 3-point path vs a midpoint-shifted copy -> exact rmse; empty/one-point attempt
-> clear error; the P1 unit-guard fires on an ~8x span mismatch; a multi-segment highway
concatenates its segment trajectories IN ORDER; and a real-canon self-score is ~0.
"""
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "experiments" / "route_observatory"))

import score_route_mse as SR   # noqa: E402


def _traj(xyz, t0=0.0, dt=0.013):
    """[(x,y,z),...] -> [[t,x,y,z],...] with uniform timestamps (the on-wire row shape)."""
    return [[t0 + i * dt, p[0], p[1], p[2]] for i, p in enumerate(xyz)]


def _canon(highways, map_name="dm3"):
    return {"schema": "komodobots.route_canon.v1", "map": map_name, "highways": highways}


def _highway(hid, segments_xyz, **meta):
    segs = [{"from_resource": "A", "to_resource": "B",
             "trajectory": _traj(seg)} for seg in segments_xyz]
    h = {"id": hid, "label": meta.get("label", hid),
         "route_class": meta.get("route_class", "base"),
         "from_resource": "A", "to_resource": "B",
         "seed": {"demo": "demo0", "player": "Milton"}, "segments": segs}
    return h


class TestResampleHelpers(unittest.TestCase):
    def test_resample_endpoint_inclusivity_both_grids(self):
        pts = [(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (10.0, 20.0, 5.0), (30.0, 20.0, 5.0)]
        ts = [0.0, 1.0, 2.0, 3.0]
        for grid in ("arclen", "time"):
            out = SR.resample(pts, ts, grid, m=16)
            self.assertEqual(len(out), 16)
            self.assertEqual(tuple(round(v, 6) for v in out[0]), pts[0],
                             f"{grid}: first sample must be the first point")
            self.assertEqual(tuple(round(v, 6) for v in out[-1]), pts[-1],
                             f"{grid}: last sample must be the last point")

    def test_resample_single_point(self):
        out = SR.resample([(3.0, 4.0, 5.0)], [0.0], "arclen", m=8)
        self.assertEqual(out, [(3.0, 4.0, 5.0)] * 8)


class TestScoring(unittest.TestCase):
    def test_identical_is_zero(self):
        seed = [(0.0, 0.0, 0.0), (100.0, 0.0, 0.0), (100.0, 100.0, 0.0), (200.0, 100.0, 50.0)]
        ts = [p[0] for p in _traj(seed)]
        s = SR.score(seed, list(seed), "arclen", ts, ts)
        self.assertLess(s["rmse_xyz"], 1e-9)
        self.assertLess(s["mse_xyz"], 1e-9)

    def test_constant_offset_rmse_equals_offset(self):
        seed = [(0.0, 0.0, 0.0), (100.0, 0.0, 0.0), (100.0, 100.0, 0.0), (200.0, 100.0, 0.0)]
        D = 12.5
        attempt = [(x + D, y, z) for (x, y, z) in seed]   # pure translation in +x
        ts = [p[0] for p in _traj(seed)]
        s = SR.score(seed, attempt, "arclen", ts, ts)
        # a translation preserves arc-length parameterization -> every paired sample differs by
        # exactly (D,0,0): rmse_xyz == rmse_xy == D, rmse_z == 0.
        self.assertAlmostEqual(s["rmse_xyz"], D, places=6)
        self.assertAlmostEqual(s["rmse_xy"], D, places=6)
        self.assertAlmostEqual(s["rmse_z"], 0.0, places=9)

    def test_known_triangle_midpoint_shift_exact_rmse(self):
        # 3 points, m=3, TIME grid with uniform t -> samples are EXACTLY the 3 vertices, so a
        # midpoint shift of +30 in y gives per-point y-diffs [0,30,0]: mse = 900/3 = 300,
        # rmse = sqrt(300) = 30/sqrt(3).
        seed = [(0.0, 0.0, 0.0), (50.0, 0.0, 0.0), (100.0, 0.0, 0.0)]
        attempt = [(0.0, 0.0, 0.0), (50.0, 30.0, 0.0), (100.0, 0.0, 0.0)]
        ts = [0.0, 1.0, 2.0]
        s = SR.score(seed, attempt, "time", ts, ts, m=3)
        self.assertAlmostEqual(s["mse_xyz"], 300.0, places=6)
        self.assertAlmostEqual(s["rmse_xyz"], 30.0 / math.sqrt(3.0), places=6)
        self.assertAlmostEqual(s["per_axis_mse"]["y"], 300.0, places=6)
        self.assertAlmostEqual(s["per_axis_mse"]["x"], 0.0, places=9)

    def test_both_grids_run_in_build_artifact(self):
        canon = _canon([_highway("hw", [[(0.0, 0.0, 0.0), (10.0, 5.0, 1.0),
                                         (20.0, 5.0, 1.0)]])])
        seed_xyz, meta = SR.load_highway_seed(canon, "hw")
        attempt = [(0.0, 0.0, 0.0), (10.0, 8.0, 1.0), (20.0, 5.0, 1.0)]
        seed_ts = [p[0] for h in canon["highways"] for seg in h["segments"]
                   for p in seg["trajectory"]]
        att_ts = [p[0] for p in _traj(attempt)]
        for grid in ("arclen", "time"):
            art = SR.build_artifact("hw", seed_xyz, meta, attempt, "synthetic",
                                    grid, seed_ts, att_ts)
            self.assertEqual(art["schema"], "komodobots.route_mse.v1")
            self.assertEqual(art["highway_id"], "hw")
            self.assertEqual(art["grid"]["kind"], grid)
            self.assertTrue(math.isfinite(art["rmse_xyz"]))
            self.assertIn("qu", art["_scoring"])           # unit is documented as qu


class TestUnitGuard(unittest.TestCase):
    def test_unit_guard_fires_on_8x_span(self):
        seed = [(0.0, 0.0, 0.0), (100.0, 0.0, 0.0), (100.0, 100.0, 50.0)]
        attempt = [(x * 8.0, y * 8.0, z * 8.0) for (x, y, z) in seed]   # raw 1/8-qu wire scale
        with self.assertRaises(SystemExit):
            SR.unit_guard(seed, attempt)

    def test_unit_guard_passes_same_units(self):
        seed = [(0.0, 0.0, 0.0), (100.0, 0.0, 0.0), (100.0, 100.0, 50.0)]
        attempt = [(5.0, 5.0, 5.0), (110.0, 3.0, 2.0), (95.0, 120.0, 44.0)]  # same scale, diff path
        SR.unit_guard(seed, attempt)   # must NOT raise

    def test_unit_guard_passes_short_low_progress_attempt(self):
        # the D3 case: a LONG seed vs a SHORT same-unit attempt (small coords WITHIN the seed bbox).
        # A smaller attempt is low-progress, not a unit error -> the guard must NOT fire.
        seed = [(float(i * 60), 0.0, -176.0) for i in range(50)]            # x 0..2940 qu
        attempt = [(0.0, 0.0, -176.0), (40.0, 5.0, -176.0), (55.0, 3.0, -170.0)]  # stalled near start
        SR.unit_guard(seed, attempt)   # must NOT raise

    def test_short_low_progress_attempt_scores_not_raises_d3_case(self):
        # End-to-end D3 regression: the frozen 6-feat mover stalls, so build_artifact must return a
        # FINITE route_mse.v1 (a large MSE is a PASS for plumbing) and NOT raise the unit-guard.
        long_seed = [(float(i * 60), 0.0, -176.0) for i in range(50)]       # long highway, x 0..2940
        canon = _canon([_highway("hw", [long_seed])])
        seed_xyz, meta = SR.load_highway_seed(canon, "hw")
        short_attempt = [(0.0, 0.0, -176.0), (40.0, 5.0, -176.0), (55.0, 3.0, -170.0)]
        seed_ts = [p[0] for h in canon["highways"] for seg in h["segments"]
                   for p in seg["trajectory"]]
        att_ts = [p[0] for p in _traj(short_attempt)]
        art = SR.build_artifact("hw", seed_xyz, meta, short_attempt, "stalled-6feat",
                                "arclen", seed_ts, att_ts)
        self.assertEqual(art["schema"], "komodobots.route_mse.v1")
        self.assertTrue(math.isfinite(art["rmse_xyz"]))
        self.assertGreater(art["rmse_xyz"], 0.0)   # far from the seed (large MSE) — but finite


class TestLoaders(unittest.TestCase):
    def _write(self, obj):
        tf = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump(obj, tf)
        tf.close()
        self.addCleanup(lambda: Path(tf.name).unlink(missing_ok=True))
        return tf.name

    def test_empty_attempt_errors(self):
        with self.assertRaises(SystemExit):
            SR.load_attempt(self._write([]))

    def test_one_point_attempt_errors(self):
        with self.assertRaises(SystemExit):
            SR.load_attempt(self._write([[0.0, 1.0, 2.0, 3.0]]))

    def test_unknown_highway_errors(self):
        canon = _canon([_highway("hw", [[(0.0, 0.0, 0.0), (1.0, 1.0, 1.0)]])])
        with self.assertRaises(SystemExit):
            SR.load_highway_seed(canon, "nope")

    def test_attempt_dict_wrapper_accepted(self):
        rows = [[0.0, 1.0, 2.0, 3.0], [0.013, 4.0, 5.0, 6.0]]
        xyz, raw = SR.load_attempt(self._write({"trajectory": rows}))
        self.assertEqual(xyz, [(1.0, 2.0, 3.0), (4.0, 5.0, 6.0)])


class TestMultiSegmentConcat(unittest.TestCase):
    def test_multi_segment_concatenates_in_order(self):
        seg0 = [(0.0, 0.0, 0.0), (10.0, 0.0, 0.0)]
        seg1 = [(500.0, 500.0, 0.0), (510.0, 500.0, 0.0)]   # post-teleport, far away
        canon = _canon([_highway("tele", [seg0, seg1])])
        seed_xyz, meta = SR.load_highway_seed(canon, "tele")
        self.assertEqual(seed_xyz, seg0 + seg1)             # exact, in order
        self.assertEqual(meta["n_segments"], 2)


class TestRealCanon(unittest.TestCase):
    def test_real_canon_self_score_is_zero(self):
        canon_path = REPO / "data" / "catalog" / "route_canon.dm3.json"
        if not canon_path.exists():
            self.skipTest("route_canon.dm3.json not present")
        canon = json.loads(canon_path.read_text(encoding="utf-8"))
        hid = canon["highways"][0]["id"]                    # a real single-segment highway
        seed_xyz, meta = SR.load_highway_seed(canon, hid)
        # attempt = the seed's own [t,x,y,z] rows -> a self-score must be ~0.
        rows = [p for seg in canon["highways"][0]["segments"] for p in seg["trajectory"]]
        attempt_xyz = [(float(p[1]), float(p[2]), float(p[3])) for p in rows]
        ts = [float(p[0]) for p in rows]
        art = SR.build_artifact(hid, seed_xyz, meta, attempt_xyz, "self", "arclen", ts, ts)
        self.assertLess(art["rmse_xyz"], 1e-6)
        self.assertGreater(art["ground_truth"]["n_pts"], 0)


if __name__ == "__main__":
    unittest.main()
