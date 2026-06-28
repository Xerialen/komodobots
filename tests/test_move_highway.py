#!/usr/bin/env python3
"""Standalone-C gate for the handoff geometry + latch (#422 T3.1).

Compiles experiments/ktx_moveprobe/live/move_highway.c via tests/_live_c_harness.py (the same
harness that runs the world-view parity gate) and drives it through the selftest `radii` /
`nearest` / `engaged_seq` commands. Asserts:

  * a point ON a base trajectory is a member (nearest ~ 0); a far point + a SHORTCUT point are not
    (base-only filter honoured -- the shortcut is excluded from the generated geometry);
  * the latched CONJUNCTION: engage needs Commander intent AND on-line membership; stay engaged
    through the hysteresis band with no flicker; hand back on drift, arrival, and intent loss.

The geometry is read from data/catalog/route_canon.dm3.json so the test points are derived, not
magic, and the radii are read from the C unit itself (no duplicated constants). Skips cleanly when
no C compiler is present (the _live_c_harness contract).

Run locally:  python3 -m unittest tests.test_move_highway -v
"""
from __future__ import annotations

import json
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))  # tests/ for _live_c_harness

import _live_c_harness as _harness  # noqa: E402
from _live_c_harness import run as _run  # noqa: E402

sys.path.insert(0, str(ROOT / "experiments" / "route_observatory"))
import gen_route_canon_header as _gen  # noqa: E402

CANON = json.loads((ROOT / "data" / "catalog" / "route_canon.dm3.json").read_text(encoding="utf-8"))


def _base():
    return [h for h in CANON["highways"] if h["route_class"] == "base"]


def _xy(h):
    return [(float(p[1]), float(p[2])) for p in h["segments"][0]["trajectory"]]


def _perp_from_start(xy):
    """Unit perpendicular to the first non-degenerate segment at xy[0] (so a point offset by d
    along it sits exactly d qu off the polyline near the start)."""
    sx, sy = xy[0]
    for (x, y) in xy[1:]:
        L = math.hypot(x - sx, y - sy)
        if L > 5.0:
            ux, uy = (x - sx) / L, (y - sy) / L
            return (-uy, ux)
    raise AssertionError("base[0] has no non-degenerate segment near its start")


class TestHandoffGate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Mirror require_harness's contract at class scope: skip with no compiler, hard-error on a
        # present-but-failing compile (a real defect must not silently skip).
        if _harness.HARNESS is None:
            if _harness.SKIP_REASON is not None:
                raise unittest.SkipTest(_harness.SKIP_REASON)
            raise RuntimeError("C live unit failed to compile (compiler present):\n"
                               + _harness.BUILD_LOG)
        cls.R_ON, cls.R_OFF, cls.R_ARRIVE, cls.R_GOAL = (float(t) for t in _run("radii").split())

        b0 = _base()[0]
        xy = _xy(b0)
        cls.start = xy[0]
        cls.end = (float(b0["end_xyz"][0]), float(b0["end_xyz"][1]))
        px, py = _perp_from_start(xy)
        sx, sy = cls.start
        # on-line / hysteresis-band / off-line points, perpendicular to the start segment
        cls.p_on = (sx, sy)
        cls.p_hyst = (sx + px * 70.0, sy + py * 70.0)   # in (R_ON, R_OFF)
        cls.p_off = (sx + px * 150.0, sy + py * 150.0)  # > R_OFF
        cls.goal_end = cls.end
        cls.goal_far = (sx + 5000.0, sy)                # far from the highway end -> no intent
        cls.shortcut_start = next(
            (float(h["segments"][0]["trajectory"][0][1]),
             float(h["segments"][0]["trajectory"][0][2]))
            for h in CANON["highways"] if h["route_class"] != "base")

    def _nearest(self, pt):
        dist, which = _run("nearest", f"{pt[0]}", f"{pt[1]}").split()
        return float(dist), int(which)

    def _seq(self, steps):
        """steps: list of (slot, (bx,by), have_goal, (gx,gy)); returns the 0/1 result list."""
        lines = "".join(
            f"{slot} {bx} {by} {hg} {gx} {gy}\n"
            for (slot, (bx, by), hg, (gx, gy)) in steps)
        out = _run("engaged_seq", stdin=lines).split()
        return [int(v) for v in out]

    # -- membership ----------------------------------------------------------
    def test_on_route_point_is_member(self):
        dist, which = self._nearest(self.p_on)
        self.assertLess(dist, 1.0, "a base trajectory vertex should be ~0 from the polyline")
        self.assertEqual(which, 0)

    def test_far_point_not_member(self):
        dist, _ = self._nearest((self.start[0] + 5000.0, self.start[1]))
        self.assertGreater(dist, self.R_OFF)

    def test_shortcut_point_not_member(self):
        # the shortcut highway is excluded from the base geometry, so its trajectory sits well off
        # every base polyline (base-only filter honoured).
        dist, _ = self._nearest(self.shortcut_start)
        self.assertGreater(dist, self.R_OFF)

    def test_measurement_bands(self):
        # the points the latch tests rely on really fall in the intended bands
        d_on, _ = self._nearest(self.p_on)
        d_hyst, _ = self._nearest(self.p_hyst)
        d_off, _ = self._nearest(self.p_off)
        self.assertLess(d_on, self.R_ON)
        self.assertTrue(self.R_ON < d_hyst < self.R_OFF, f"hyst dist {d_hyst} not in band")
        self.assertGreater(d_off, self.R_OFF)

    # -- latched conjunction -------------------------------------------------
    def test_engage_requires_intent_and_online(self):
        # only the step with BOTH on-line membership AND a goal toward the end engages
        res = self._seq([
            (0, self.p_on, 0, (0.0, 0.0)),       # on-line, no goal -> no intent
            (0, self.p_off, 1, self.goal_end),   # off-line, goal=end -> geometry fails
            (0, self.p_on, 1, self.goal_far),    # on-line, goal far -> intent fails
            (0, self.p_on, 1, self.goal_end),    # both satisfied -> engage
        ])
        self.assertEqual(res, [0, 0, 0, 1])

    def test_no_fresh_engage_inside_hysteresis_band(self):
        # the bot cannot engage from R_ON..R_OFF; it must reach R_ON first (then hysteresis holds)
        res = self._seq([
            (0, self.p_hyst, 1, self.goal_end),  # d in (R_ON,R_OFF), fresh -> no engage
            (0, self.p_on, 1, self.goal_end),    # reach the line -> engage
        ])
        self.assertEqual(res, [0, 1])

    def test_hysteresis_no_flicker(self):
        # once engaged, moving within the band (<= R_OFF) does not drop the latch
        res = self._seq([
            (0, self.p_on, 1, self.goal_end),
            (0, self.p_hyst, 1, self.goal_end),
            (0, self.p_on, 1, self.goal_end),
            (0, self.p_hyst, 1, self.goal_end),
        ])
        self.assertEqual(res, [1, 1, 1, 1])

    def test_disengage_on_drift(self):
        res = self._seq([
            (0, self.p_on, 1, self.goal_end),
            (0, self.p_off, 1, self.goal_end),   # drifted > R_OFF -> hand back
        ])
        self.assertEqual(res, [1, 0])

    def test_disengage_on_arrival(self):
        res = self._seq([
            (0, self.p_on, 1, self.goal_end),
            (0, self.end, 1, self.goal_end),     # at the end (<= R_ARRIVE) -> arrival hand-back
        ])
        self.assertEqual(res, [1, 0])

    def test_arrival_is_sticky_no_reengage_at_endpoint(self):
        # Codex round-3: arrival must STAY a hand-back. Sitting at the endpoint with the goal still
        # there, the fresh-engage scan must NOT re-latch (the endpoint is on the polyline + within
        # R_GOAL of its own end), else DISENGAGED/ENGAGED oscillates at the destination.
        res = self._seq([
            (0, self.p_on, 1, self.goal_end),    # engage
            (0, self.end, 1, self.goal_end),     # arrive -> hand back
            (0, self.end, 1, self.goal_end),     # still at endpoint -> stays Commander
            (0, self.end, 1, self.goal_end),     # ... and stays (no re-engage)
        ])
        self.assertEqual(res, [1, 0, 0, 0])

    def test_disengage_on_intent_loss(self):
        res = self._seq([
            (0, self.p_on, 1, self.goal_end),
            (0, self.p_on, 0, (0.0, 0.0)),       # goal gone -> intent lost -> hand back
        ])
        self.assertEqual(res, [1, 0])

    def test_per_slot_independence(self):
        # engaging slot 0 must not engage slot 1
        res = self._seq([
            (0, self.p_on, 1, self.goal_end),    # slot 0 engages
            (1, self.p_off, 1, self.goal_end),   # slot 1 off-line -> stays disengaged
        ])
        self.assertEqual(res, [1, 0])

    @staticmethod
    def _closest_overlap_vertex():
        """The base-highway downsampled vertex closest to a DIFFERENT base highway's polyline.
        Returns (vertex, i, j, end_i, end_j, gap): vertex lies on highway i (its global-nearest)
        but within `gap` of highway j. Mirrors the geometry the committed header encodes."""
        base = _base()
        polys = [_gen.downsample(_xy(h), _gen.DEFAULT_MAX_PTS) for h in base]
        ends = [(float(h["end_xyz"][0]), float(h["end_xyz"][1])) for h in base]
        best = None
        for i in range(len(polys)):
            for j in range(len(polys)):
                if i == j:
                    continue
                for v in polys[i]:
                    gap = _gen._min_poly_dist([v], polys[j])
                    if best is None or gap < best[0]:
                        best = (gap, i, j, v)
        gap, i, j, v = best
        return v, i, j, ends[i], ends[j], gap

    def test_engage_picks_intended_highway_on_overlap(self):
        # Fix 2 (Codex P2): on overlapping dm3 corridors a bot can be globally-nearest to highway i
        # yet intend highway j (goal at j's end). Intent-first selection must engage j, NOT refuse
        # because i's end != the goal (the global-nearest-first bug).
        v, i, j, end_i, end_j, gap = self._closest_overlap_vertex()
        self.assertNotEqual(i, j)
        dist, which = self._nearest(v)
        self.assertEqual(which, i, "overlap vertex must be globally nearest to highway i")
        self.assertLess(dist, self.R_ON)
        self.assertLessEqual(gap, self.R_ON, "vertex must also be within R_ON of highway j")
        # premise: i's end is far from the goal, so global-nearest-first would have refused here
        self.assertGreater(math.dist(end_i, end_j), self.R_GOAL,
                           "test needs distinct highway ends to exercise the bug")
        res = self._seq([(0, v, 1, end_j)])  # goal targets highway j's end
        self.assertEqual(res, [1],
                         "bot on highway i but intending highway j must engage j, not be refused")


if __name__ == "__main__":
    unittest.main()
