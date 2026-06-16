#!/usr/bin/env python3
"""Multi-physent trace foundation tests (pmove_sim).

Guards three things:
  1. REGRESSION — worldmodel-only default (Pmove.physents empty) is byte-
     identical to the validated baseline on the human SNG->RL replay.
  2. BOX HULL — make_player_physent() actually blocks a swept trace that would
     otherwise pass through, and lets a clear trace through untouched.
  3. SUBMODELS — the 6 dm3 brush submodels load, and load_submodels() is opt-in
     (does not perturb the human replay, which never touches them).

Wrapped in a unittest.TestCase so the CI gate (`python3 -m unittest discover`)
actually executes these. They need `dm3.bsp` + the SNG->RL replay cmds; when
those are absent (e.g. the hosted CI runner) the whole case SKIPS cleanly
rather than erroring. Run locally: `python3 -m unittest tests.test_physent_collision -v`.
"""
from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.setrecursionlimit(20000)

import pmove_sim as P  # noqa: E402

_BSP_CANDIDATES = (r"C:\nQuake\qw\maps\dm3.bsp", "/mnt/c/nQuake/qw/maps/dm3.bsp")
_CMDS_CANDIDATES = (
    ROOT / "experiments/dm3_sng_to_rl_observability/evidence/dm3_sng_to_rl.cmds",
    Path("artifacts/replay/dm3_sng_to_rl.cmds"),
    ROOT / "artifacts/replay/dm3_sng_to_rl.cmds",
)


def _find_bsp():
    for p in _BSP_CANDIDATES:
        if Path(p).exists():
            return p
    return None


def _find_cmds():
    for c in _CMDS_CANDIDATES:
        if Path(c).exists():
            return c
    return None


def _human_replay(world, cmds, physents_loader=None):
    frames = P.load_cmds_file(str(cmds))
    tele = set(P.detect_teleports(frames))
    pm = P.Pmove(world)
    if physents_loader:
        physents_loader(pm)
    s = P.PlayerState(frames[0]["origin"], frames[0]["velocity"])
    max_err = 0.0
    n = len(frames) - 1
    for k in range(n):
        f = frames[k]
        if k > 0 and (k - 1) in tele:
            s = P.PlayerState(f["origin"], f["velocity"], jump_held=s.jump_held,
                              waterjumptime=s.waterjumptime)
        pm.run_frame(s, P.Cmd(f["msec"], f["angles"], f["move"], f["buttons"]))
        rec = frames[k + 1]
        if k in tele:
            continue
        err = math.dist(s.origin, rec["origin"])
        max_err = max(max_err, err)
    return max_err


def _open_air_segment(world, cmds):
    """A guaranteed-clear short horizontal trace, anchored to a real airborne
    replay frame (so start/end are provably open space the human moved through)."""
    frames = P.load_cmds_file(str(cmds))
    for f in frames:
        vh = math.hypot(f["velocity"][0], f["velocity"][1])
        if vh > 200:  # moving fast & horizontally -> airborne over open space
            o, v = f["origin"], f["velocity"]
            ux, uy = v[0] / vh, v[1] / vh
            start = [o[0], o[1], o[2]]
            end = [o[0] + ux * 120.0, o[1] + uy * 120.0, o[2]]  # 120 qu along travel
            tr = P.player_trace(world, start, end)
            if tr.fraction == 1.0:
                return start, end, (ux, uy)
    raise AssertionError("no clear open-air segment found in replay")


class PhysentCollisionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        bsp = _find_bsp()
        cmds = _find_cmds()
        if bsp is None or cmds is None:
            raise unittest.SkipTest(
                "dm3.bsp and/or the SNG->RL replay cmds not available — "
                "physent collision tests run only where the QW map + replay exist")
        cls.world = P.WorldModel.load(bsp)
        cls.cmds = cmds

    def test_regression_worldmodel_only(self):
        # default Pmove.physents == [] -> byte-identical to the validated baseline
        max_err = _human_replay(self.world, self.cmds)
        self.assertLess(max_err, 0.3, f"worldmodel-only human replay regressed: max_err={max_err}")

    def test_box_hull_blocks(self):
        start, end, (ux, uy) = _open_air_segment(self.world, self.cmds)
        clear = P.player_trace(self.world, start, end)
        self.assertEqual(clear.fraction, 1.0, f"control trace not clear: {clear.fraction}")
        # Opponent box ~85 qu ahead (beyond the 32 qu Minkowski half-width, so the
        # start is NOT solid) => a genuine swept stop with 0 < fraction < 1.
        ahead = (start[0] + ux * 85.0, start[1] + uy * 85.0, start[2])
        blocked = P.player_trace(self.world, start, end, [P.make_player_physent(ahead, ent=7)])
        self.assertTrue(0.0 < blocked.fraction < 1.0,
                        f"box did not produce a swept stop: frac={blocked.fraction}")
        self.assertEqual(blocked.ent, 7, f"blocked.ent={blocked.ent}, expected opponent ent 7")
        # A box far to the side does not perturb the clear trace.
        side = (start[0] - uy * 400.0, start[1] + ux * 400.0, start[2])
        miss = P.player_trace(self.world, start, end, [P.make_player_physent(side, ent=8)])
        self.assertEqual(miss.fraction, 1.0, f"distant box perturbed the trace: {miss.fraction}")

    def test_submodels_optin(self):
        self.assertEqual(len(self.world.submodels), 6,
                         f"expected 6 dm3 submodels, got {len(self.world.submodels)}")
        # opt-in must not perturb the human SNG->RL route (it touches no submodel)
        max_err = _human_replay(self.world, self.cmds,
                                physents_loader=lambda pm: pm.load_submodels())
        self.assertLess(max_err, 0.3, f"submodels perturbed the human replay: max_err={max_err}")


if __name__ == "__main__":
    unittest.main()
