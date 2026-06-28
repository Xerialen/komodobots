"""Unit tests for #421 (T2.2 POV-fusion): the trajectory-similarity gate + band aggregation
(experiments/route_observatory/route_canon_band.py) and the L1 eval-integrity decision logic
(experiments/route_observatory/pov_fuse_pipeline.py).

Stdlib `unittest`, synthetic data only (no 42 MB decode, no render, no Pillow), so this runs in the
gating CI floor. Mirrors the sys.path pattern of tests/test_build_route_canon.py.
"""
import logging
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
for p in (HERE.parent / "experiments" / "route_observatory", HERE.parent / "ml" / "pipeline"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import route_canon_band as RB        # noqa: E402
import pov_fuse_pipeline as PP        # noqa: E402
from pov_fuse_extract import compute_signature  # noqa: E402

logging.getLogger("build_route_canon").setLevel(logging.CRITICAL)
logging.getLogger("route_canon_band").setLevel(logging.CRITICAL)


def _ticks(n=20, x0=0.0, dx=50.0, y=0.0, vz=100.0, t0=1.0, dt=0.1):
    return [{"t": round(t0 + i * dt, 3), "x": x0 + i * dx, "y": y, "z": 0.0,
             "hs": 500.0, "yaw": 0.0, "mdir": 0.0, "vz": vz} for i in range(n)]


def _seed_seg(ticks, fr="A", to="B"):
    return {"from_resource": fr, "to_resource": to,
            "signature": compute_signature(ticks),
            "trajectory": [[t["t"], t["x"], t["y"], t["z"]] for t in ticks]}


class TestSimilarityGate(unittest.TestCase):
    def test_keep_matching_path(self):
        ticks = _ticks()
        seed = _seed_seg(ticks)
        keep, dist, reason = RB.gate_keep(seed, ticks, compute_signature(ticks), self_dmg=[])
        self.assertTrue(keep)
        self.assertAlmostEqual(dist, 0.0, places=3)

    def test_reject_divergent_path(self):
        # same endpoints, but the candidate runs 300 qu off the seed line everywhere -> dissimilar
        seed = _seed_seg(_ticks())
        cand = _ticks(y=300.0)
        keep, dist, reason = RB.gate_keep(seed, cand, compute_signature(cand), self_dmg=[])
        self.assertFalse(keep)
        self.assertGreater(dist, RB.SIM_QU)
        self.assertIn("dissimilar", reason)

    def test_reject_suspect_trick_traversal(self):
        # in-band self-damage (rl 40) + a coincident vz launch on the seed path -> trick, rejected
        seed = _seed_seg(_ticks())
        cand = _ticks()
        cand[5] = {**cand[5], "vz": 600.0}                       # launch at t=1.5s
        dmg = [{"attacker": "p", "victim": "p", "weapon": "rl", "damage": 40, "time": 1500}]
        keep, dist, reason = RB.gate_keep(seed, cand, compute_signature(cand), self_dmg=dmg)
        self.assertFalse(keep)
        self.assertIn("suspect_trick", reason)

    def test_fail_closed_on_unavailable_damage(self):
        # None damage stream = unavailable -> _suspect_trick fails closed -> not pooled
        seed = _seed_seg(_ticks())
        keep, _, reason = RB.gate_keep(seed, _ticks(), compute_signature(_ticks()), self_dmg=None)
        self.assertFalse(keep)
        self.assertIn("suspect_trick", reason)

    def test_reject_on_straightness_backstop(self):
        # path is identical (dist 0) but the signature straightness is far from the seed's (N5)
        seed = _seed_seg(_ticks())
        bad_sig = dict(compute_signature(_ticks()))
        bad_sig["straightness"] = seed["signature"]["straightness"] - 0.5
        keep, _, reason = RB.gate_keep(seed, _ticks(), bad_sig, self_dmg=[])
        self.assertFalse(keep)
        self.assertIn("straightness", reason)

    def test_reject_on_jump_backstop(self):
        seed = _seed_seg(_ticks())
        bad_sig = dict(compute_signature(_ticks()))
        bad_sig["jumps"] = seed["signature"]["jumps"] + 10
        keep, _, reason = RB.gate_keep(seed, _ticks(), bad_sig, self_dmg=[])
        self.assertFalse(keep)
        self.assertIn("jump-count", reason)


class TestResampleAndCorridor(unittest.TestCase):
    def test_resample_length_and_endpoints(self):
        pts = [(0.0, 0.0), (100.0, 0.0), (200.0, 50.0)]
        out = RB._resample_xy(pts, 64)
        self.assertEqual(len(out), 64)
        self.assertEqual(out[0], pts[0])
        self.assertEqual(out[-1], pts[-1])

    def test_median_point_dist_identical_and_shifted(self):
        a = [(i * 50.0, 0.0) for i in range(20)]
        b = [(i * 50.0 + 300.0, 0.0) for i in range(20)]   # constant +300 in x
        self.assertAlmostEqual(RB._median_point_dist(a, a), 0.0, places=3)
        self.assertAlmostEqual(RB._median_point_dist(a, b), 300.0, places=1)

    def test_corridor_spread(self):
        base = [(i * 50.0, 0.0) for i in range(20)]
        legs = [base, [(x, 100.0) for x, _ in base], [(x, -100.0) for x, _ in base]]
        corr = RB.positional_corridor(legs, m=16)
        self.assertEqual(len(corr), 16)
        self.assertEqual(corr[0]["frac"], 0.0)
        self.assertEqual(corr[-1]["frac"], 1.0)
        mid = corr[8]
        self.assertLess(mid["y"]["p10"], mid["y"]["p90"])   # the three legs spread in y


class TestL1Verdict(unittest.TestCase):
    def test_pass(self):
        st, _ = PP.l1_row_verdict(True, 500.0, 25.0, 5, 1.0, 10.0, True)
        self.assertEqual(st, "pass")

    def test_missing_frame_fails(self):
        st, _ = PP.l1_row_verdict(False, None, 25.0, 5, 1.0, 10.0, True)
        self.assertEqual(st, "fail")

    def test_second_outside_window_fails(self):
        st, _ = PP.l1_row_verdict(True, 500.0, 25.0, 50, 1.0, 10.0, True)
        self.assertEqual(st, "fail")

    def test_degenerate_frame_fails(self):
        st, reason = PP.l1_row_verdict(True, 5.0, 25.0, 5, 1.0, 10.0, True)
        self.assertEqual(st, "fail")
        self.assertIn("degenerate", reason)

    def test_unverified_offset_is_flagged_not_passed(self):
        st, _ = PP.l1_row_verdict(True, 500.0, 25.0, 5, 1.0, 10.0, False)
        self.assertEqual(st, "offset-unverified")

    def test_variance_skipped_when_pillow_absent(self):
        # variance None (no Pillow) is not a failure — present + window + verified still pass
        st, reason = PP.l1_row_verdict(True, None, 25.0, 5, 1.0, 10.0, True)
        self.assertEqual(st, "pass")
        self.assertIn("skipped", reason)


class TestSegmentBandIdentity(unittest.TestCase):
    """A multi-segment highway (teleport chain) must be banded PER SEGMENT — each band's id +
    endpoints + seed-window match the segment, never the whole highway (the ML-review regression)."""

    def _seg(self, fr, to, t0, t1):
        return {"from_resource": fr, "to_resource": to,
                "signature": {"straightness": 0.5, "jumps": 2},
                "trajectory": [[t0, 0.0, 0.0, 0.0], [t1, 100.0, 0.0, 0.0]]}

    def _highway(self, segs, rclass="shortcut"):
        return {"id": "hw", "label": "L", "route_class": rclass,
                "seed": {"demo": "d.mvd", "player": "p"}, "segments": segs}

    def test_single_segment_keeps_plain_id(self):
        hw = self._highway([self._seg("A", "B", 1.0, 5.0)], rclass="base")
        ident = RB.segment_band_identity(hw, 0, hw["segments"][0])
        self.assertEqual(ident["id"], "hw")
        self.assertEqual((ident["from_resource"], ident["to_resource"]), ("A", "B"))
        self.assertEqual((ident["seed"]["start_s"], ident["seed"]["end_s"]), (1.0, 5.0))

    def test_multi_segment_scopes_id_endpoints_and_window(self):
        segs = [self._seg("SNG", "SNG", 0.0, 1.4), self._seg("Ring", "Quad", 1.5, 4.5)]
        hw = self._highway(segs)
        i0 = RB.segment_band_identity(hw, 0, segs[0])
        i1 = RB.segment_band_identity(hw, 1, segs[1])
        self.assertEqual((i0["id"], i1["id"]), ("hw#seg0", "hw#seg1"))
        self.assertEqual((i1["from_resource"], i1["to_resource"]), ("Ring", "Quad"))
        self.assertEqual((i0["seed"]["start_s"], i0["seed"]["end_s"]), (0.0, 1.4))
        self.assertEqual((i1["seed"]["start_s"], i1["seed"]["end_s"]), (1.5, 4.5))
        # the seg1 band must NOT advertise the whole-highway 0.0-4.5 span or the seg0 endpoints
        self.assertNotEqual(i1["seed"]["start_s"], 0.0)
        self.assertEqual((i1["parent_highway"], i1["n_segments"]), ("hw", 2))


if __name__ == "__main__":
    unittest.main()
