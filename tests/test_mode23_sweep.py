"""mode23_sweep: the pure parts of the A2 #74 pre-registered sweep harness.

Covers, with no BSP / no lab dependency:
  * stage-1 grid: pre-registered size (1944), uniqueness, the live c5
    identity point included exactly once
  * config ids: governor variants carry threshold/timeout, none does not
  * the Gate-2 corner stat helpers (deduped linked sequence, exits, the
    pre-arrival truncation through corner_stats)
  * the rung-B edge objective conditioning: arrival truncation keeps the
    approach crossing and drops post-arrival hover re-crossings; stray
    teleports truncate; None when never crossed (never coerced to 0)
  * eligibility floors + the pre-registered ranking keys (None corner
    conversion sorts last; medians never computed over Nones)
  * transfer-candidate picking (ranks 1-3 + mid, escalation below 4)
  * the stage-2 refinement rule (top-3 marginal dims, +-step neighborhoods,
    governor top-8 threshold/timeout grid, dedup vs stage 1, cap)

The sweep itself is an analysis run (see experiments/p3b_sweep/), not a test.
"""

import sys
import unittest
from dataclasses import asdict, replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import mode23_sweep as SW  # noqa: E402
from mode23_sim import LawParams  # noqa: E402


def row(t, x, y=0.0, z=0.0, vh=0.0, dist_goal=1e6, linked=None):
    return {"t": t, "x": x, "y": y, "z": z, "vh": vh,
            "dist_goal": dist_goal, "linked": linked}


class TestGrid(unittest.TestCase):
    def test_stage1_size_and_uniqueness(self):
        grid = SW.stage1_grid()
        self.assertEqual(len(grid), 1944)   # 3*4*3*3*3*3*2, pre-registered
        ids = [SW.config_id(p) for p in grid]
        self.assertEqual(len(set(ids)), 1944)

    def test_live_point_included_once(self):
        grid = SW.stage1_grid()
        self.assertEqual(sum(1 for p in grid if p == LawParams()), 1)

    def test_config_id_governor_suffix(self):
        none_id = SW.config_id(LawParams())
        self.assertIn("_gnone_", none_id)
        self.assertNotIn("60x2", none_id)
        gov_id = SW.config_id(LawParams(governor="vel"))
        self.assertIn("_gvel60x2_", gov_id)


class TestCornerHelpers(unittest.TestCase):
    def test_dedup_linked_skips_none_and_repeats(self):
        rows = [row(0, 0, linked=None), row(1, 0, linked=206),
                row(2, 0, linked=206), row(3, 0, linked=207),
                row(4, 0, linked=207), row(5, 0, linked=191)]
        self.assertEqual(SW.dedup_linked(rows), [206, 207, 191])

    def test_exits_from_counts_every_visit(self):
        seq = [206, 207, 206, 207, 191]
        self.assertEqual(SW.exits_from(seq, 207), [206, 191])
        self.assertEqual(SW.exits_from(seq, 206), [207, 207])

    def test_corner_stats_truncates_at_arrival(self):
        # one attempt starting at the route start; converts 207->191 and
        # arrives; a post-arrival 207->204 exit must NOT count.
        route = {"start": (0.0, 0.0), "tele_entrances": ()}
        rows = [
            row(0.0, 0.0, linked=206),
            row(0.1, 10.0, linked=207),
            row(0.2, 20.0, linked=191),
            row(0.3, 30.0, dist_goal=10.0, linked=191),   # arrival here
            row(0.4, 40.0, linked=207),                   # post-arrival
            row(0.5, 50.0, linked=204),
        ]
        e207, e206 = SW.corner_stats(rows, route)
        self.assertEqual(e207, [191])
        self.assertEqual(e206, [207])


def gap(edge=(0.0, 0.0, 0.0), land=(100.0, 0.0, 0.0)):
    return {"edge": list(edge), "land": list(land)}


class TestEdgeObjective(unittest.TestCase):
    def test_approach_crossing_kept_hover_dropped(self):
        # crossing at vh 500 BEFORE the 60-qu arrival; a slow re-crossing
        # after arrival must be excluded by the truncation.
        rows = [
            row(0.0, -50.0, vh=480.0),
            row(0.1, -5.0, vh=495.0),
            row(0.2, 5.0, vh=500.0),                      # the crossing
            row(0.3, 100.0, vh=400.0, dist_goal=50.0),    # arrival
            row(0.4, -10.0, vh=120.0, dist_goal=80.0),    # hover back out
            row(0.5, 5.0, vh=100.0, dist_goal=70.0),      # hover re-cross
        ]
        self.assertAlmostEqual(SW.edge_objective(rows, gap()), 500.0)

    def test_none_when_never_crossed(self):
        rows = [row(0.0, -50.0, vh=300.0), row(0.1, -20.0, vh=310.0),
                row(0.2, -1.0, vh=320.0)]
        self.assertIsNone(SW.edge_objective(rows, gap()))

    def test_stray_teleport_truncates_before_crossing(self):
        rows = [
            row(0.0, -50.0, vh=300.0),
            row(0.1, -45.0, vh=300.0),
            row(0.2, 800.0, y=800.0, vh=300.0),           # stray teleport
            row(0.3, -5.0, y=0.0, vh=500.0),
            row(0.4, 5.0, vh=500.0),                      # post-stray cross
        ]
        self.assertIsNone(SW.edge_objective(rows, gap()))


def rec(cid, reach=20, conv=0.5, exits=10, edge_n=20, edge_median=450.0,
        edge_max=470.0, params=None):
    p = params or LawParams()
    return {
        "id": cid, "params": asdict(p),
        "rungA": {"reach": reach, "tws_median": 270.0, "corner_conv": conv,
                  "corner_exits_207": exits, "corner_exits_206": 0,
                  "corner_206_to_207": None, "per_seed": []},
        "rungB": {"edge_n": edge_n, "edge_median": edge_median,
                  "edge_max": edge_max, "arrivals": edge_n,
                  "edge_values": []},
    }


class TestRanking(unittest.TestCase):
    def test_floors(self):
        rs = [rec("a", reach=11, edge_median=500.0),     # reach floor fails
              rec("b", edge_n=7, edge_median=500.0),     # edge_n floor fails
              rec("c", edge_median=440.0)]
        ranked, unranked = SW.split_ranked(rs)
        self.assertEqual([r["id"] for r in ranked], ["c"])
        self.assertEqual({r["id"] for r in unranked}, {"a", "b"})

    def test_primary_then_corner_then_id(self):
        rs = [rec("slow", edge_median=440.0, conv=0.9),
              rec("fast", edge_median=460.0, conv=0.1),
              rec("tie_none", edge_median=460.0, conv=None),
              rec("tie_conv", edge_median=460.0, conv=0.4)]
        ranked, _ = SW.split_ranked(rs)
        self.assertEqual([r["id"] for r in ranked],
                         ["tie_conv", "fast", "tie_none", "slow"])

    def test_aggregate_never_averages_none_as_zero(self):
        a = SW.aggregate("x", LawParams(), [], [], [],
                         [None] * 30, [False] * 30)
        self.assertEqual(a["rungB"]["edge_n"], 0)
        self.assertIsNone(a["rungB"]["edge_median"])
        self.assertIsNone(a["rungB"]["edge_max"])
        b = SW.aggregate("y", LawParams(), [], [], [],
                         [None] * 28 + [500.0, 400.0], [False] * 30)
        self.assertEqual(b["rungB"]["edge_n"], 2)
        self.assertAlmostEqual(b["rungB"]["edge_median"], 450.0)

    def test_candidates_top3_plus_mid(self):
        rs = [rec(f"c{i:02d}", edge_median=500.0 - i) for i in range(10)]
        ranked, _ = SW.split_ranked(rs)
        cands = SW.pick_candidates(ranked)
        self.assertEqual([c["id"] for c in cands],
                         ["c00", "c01", "c02", "c04"])   # mid = rank 5
        self.assertIsNone(SW.pick_candidates(ranked[:3]))  # < 4 -> escalate
        four = SW.pick_candidates(ranked[:4])
        self.assertEqual([c["id"] for c in four],
                         ["c00", "c01", "c02", "c03"])   # mid = max(4, 2)


def rec_sig(cid, per_seed, edge_values, edge_median, params=None, conv=0.5):
    r = rec(cid, edge_median=edge_median, conv=conv, params=params)
    r["rungA"]["per_seed"] = per_seed
    r["rungB"]["edge_values"] = edge_values
    return r


class TestSignatureDedup(unittest.TestCase):
    """Per-seed-identical configs are ONE behavior (the A1 c4≡c5 phenomenon):
    the declared candidate rule collapses them for the top-3 slots and keeps
    the literal pre-registered mid pick."""

    def _trip(self):
        # three governor-timeout variants with IDENTICAL trajectories, one
        # next distinct config, and filler so the literal mid exists
        seeds_a = [{"seed": 1, "reached": True}]
        seeds_b = [{"seed": 1, "reached": False}]
        rs = []
        for t in (1.0, 2.0, 3.0):
            p = replace(LawParams(), governor="pos", prec_timeout=t)
            rs.append(rec_sig(SW.config_id(p), seeds_a, [470.0], 470.0,
                              params=p))
        q = replace(LawParams(), swing=24.0)
        rs.append(rec_sig(SW.config_id(q), seeds_b, [468.0], 468.0, params=q))
        for i in range(6):
            w = replace(LawParams(), pass_r=100.0 + i)
            rs.append(rec_sig(SW.config_id(w), [{"seed": 1, "i": i}],
                              [460.0 - i], 460.0 - i, params=w))
        return rs

    def test_signature_groups(self):
        ranked, _ = SW.split_ranked(self._trip())
        groups, reps = SW.dedup_ranked(ranked)
        self.assertEqual(len(ranked), 10)
        self.assertEqual(len(groups), 8)             # triple collapsed
        self.assertEqual(len(groups[0]), 3)
        self.assertEqual(len(reps), 8)

    def test_canonical_representative_prefers_live_timeout(self):
        ranked, _ = SW.split_ranked(self._trip())
        _, reps = SW.dedup_ranked(ranked)
        p = LawParams(**reps[0]["params"])
        self.assertEqual(p.prec_timeout, 2.0)        # not the id-asc winner

    def test_distinct_candidates_top3_plus_literal_mid(self):
        rs = self._trip()
        ranked, _ = SW.split_ranked(rs)
        lit = SW.pick_candidates(ranked)
        cands, groups = SW.pick_candidates_distinct(ranked)
        self.assertEqual(LawParams(**cands[0]["params"]).prec_timeout, 2.0)
        self.assertEqual(len({SW.signature(c) for c in cands[:3]}), 3)
        self.assertEqual(cands[3]["id"], lit[3]["id"])   # literal mid kept
        self.assertEqual(len(groups[0]), 3)


class TestStage2Rule(unittest.TestCase):
    def _stage1(self):
        # leader: numerator 26 strongly ahead -> numerator is a top dim;
        # pass_r spread small; governor none everywhere (no top-8 governor).
        rs = []
        for nu, med in ((5.0, 430.0), (9.0, 445.0), (16.0, 455.0), (26.0, 470.0)):
            for sw, dm in ((6.0, 0.0), (12.0, -2.0), (24.0, -12.0)):
                p = replace(LawParams(), numerator=nu, swing=sw)
                rs.append(rec(SW.config_id(p), edge_median=med + dm, params=p))
        return rs

    def test_neighborhood_around_leader(self):
        rs = self._stage1()
        grid, meta = SW.stage2_grid(rs)
        self.assertTrue(grid)
        self.assertLessEqual(len(grid), SW.STAGE2_CAP)
        ids = {SW.config_id(p) for p in grid}
        self.assertEqual(len(ids), len(grid))              # unique
        self.assertFalse(ids & {r["id"] for r in rs})      # deduped vs s1
        # the leader is (26, 6): numerator neighborhood 23/26/29 must appear
        self.assertTrue(any(p.numerator == 29.0 for p in grid))
        self.assertTrue(any(p.numerator == 23.0 for p in grid))
        # chosen dims are the top-3 by marginal range
        self.assertIn("numerator", meta["dims"])

    def test_governor_grid_added_when_top8(self):
        rs = self._stage1()
        # make a governor config rank 1st
        p = replace(LawParams(), governor="pos", numerator=26.0)
        rs.append(rec(SW.config_id(p), edge_median=480.0, params=p))
        grid, _ = SW.stage2_grid(rs)
        govs = [q for q in grid if q.governor == "pos"]
        # 3 thresholds x 3 timeouts, minus any id collisions with stage 1
        self.assertGreaterEqual(len(govs), 8)
        self.assertTrue(any(q.prec_thresh == 45.0 and q.prec_timeout == 3.0
                            for q in govs))

    def test_empty_when_nothing_ranked(self):
        rs = [rec("a", reach=0, edge_n=0, edge_median=None, edge_max=None)]
        grid, meta = SW.stage2_grid(rs)
        self.assertEqual(grid, [])


if __name__ == "__main__":
    unittest.main()
