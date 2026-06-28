"""Unit tests for experiments/route_observatory/build_route_canon.py (#420 Route Canon DB).

Stdlib `unittest`, synthetic demos only (no decoder / no 42 MB analysis JSON) so this runs in the
gating CI floor. Mirrors the sys.path pattern of tests/test_pov_fuse_extract.py.
"""
import logging
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROUTE_OBS = HERE.parent / "experiments" / "route_observatory"
if str(ROUTE_OBS) not in sys.path:
    sys.path.insert(0, str(ROUTE_OBS))

import build_route_canon as B  # noqa: E402

logging.getLogger("build_route_canon").setLevel(logging.CRITICAL)   # quiet expected WARN diagnostics

COORDS = {"A": (0.0, 0.0), "B": (1000.0, 0.0)}
_KEYS = ["t", "x", "y", "z", "vx", "vy", "vz", "vya"]


def _player(pts):
    pos = {k: [] for k in _KEYS}
    for row in pts:
        d = dict(zip(_KEYS, row))
        pos["t"].append(round(d["t"] * 1000))   # real MVD pos.t is integer ms; player_ticks /1000
        for k in _KEYS[1:]:
            pos[k].append(d[k])
    return {"name": "p1", "pos": pos}


_UNSET = object()


def _build(pts, start_s, end_s, coords=None, dmg=_UNSET, route_class="base", label="L"):
    d = {"streams": {"players": [_player(pts)]}}
    mark = {"demo": "test.mvd", "player": "p1", "start_s": start_s, "end_s": end_s,
            "label": label, "route_class": route_class}
    events = [] if dmg is _UNSET else dmg          # default [] = available-empty; None = unavailable
    return B.build_highway(d, mark, coords or COORDS, events)


def _straight(t0, n, x0, dx, dt=0.1, y=0.0, z=0.0, vx=500.0, vy=0.0, vz=100.0, vya=0.0):
    # step=dx/tick; with vx=500,dt=0.1 the split threshold is max(150, 4*500*0.1)=200, so dx<200 is
    # continuous and a jump>200 is a teleport.
    return [(t0 + i * dt, x0 + i * dx, y, z, vx, vy, vz, vya) for i in range(n)]


class TestBuildRouteCanon(unittest.TestCase):
    def test_window_slice_boundary_and_signature(self):
        pts = ([(0.9, -50.0, 0, 0, 500, 0, 100, 0)]           # before window -> excluded
               + _straight(1.0, 20, 0.0, 50.0)                # 1.0 .. 2.9, 20 ticks
               + [(3.0, 1000.0, 0, 0, 500, 0, 100, 0)])       # after window -> excluded
        hw = _build(pts, 1.0, 2.9)
        self.assertEqual(hw["n_segments"], 1)
        seg = hw["segments"][0]
        self.assertEqual(len(seg["trajectory"]), 20)          # boundaries excluded, inclusive ends
        self.assertEqual(hw["from_resource"], "A")
        self.assertEqual(hw["to_resource"], "B")
        for f in ("hs_mean", "jumps", "straightness", "dur_s"):
            self.assertIn(f, seg["signature"])
        self.assertFalse(hw["suspect_trick"])

    def test_internal_teleport_two_segments(self):
        pts = _straight(1.0, 18, 0.0, 50.0) + _straight(2.8, 18, 1400.0, 50.0)  # jump 550 > 200
        hw = _build(pts, 1.0, 4.5)
        self.assertEqual(hw["n_segments"], 2)
        # trajectory never spans the teleport leap (per-run storage)
        self.assertEqual(len(hw["segments"]), 2)

    def test_pre_respawn_gib_dropped(self):
        # short gib run (16 ticks, survives MIN_RUN) + long real run (90) separated by a respawn jump
        pts = _straight(1.0, 16, 5000.0, 50.0) + _straight(2.6, 90, 0.0, 50.0)
        hw = _build(pts, 1.0, 11.6)
        self.assertEqual(hw["n_segments"], 1)                 # 16 < 0.2*90 -> dropped
        self.assertEqual(len(hw["segments"][0]["trajectory"]), 90)

    def test_minrun_fallback_keeps_longest(self):
        pts = _straight(1.0, 5, 0.0, 50.0) + _straight(1.6, 5, 1000.0, 50.0)   # both < MIN_RUN
        hw = _build(pts, 1.0, 2.1)
        self.assertEqual(hw["n_segments"], 1)
        self.assertEqual(len(hw["segments"][0]["trajectory"]), 5)

    def test_far_endpoint_labels_and_records_distance(self):
        pts = [(1.0 + i * 0.1, 500.0, i * 150.0, 0.0, 0.0, 500.0, 100.0, 0.0) for i in range(20)]
        hw = _build(pts, 1.0, 2.9)
        self.assertIn(hw["to_resource"], ("A", "B"))          # still labelled
        self.assertGreater(hw["to_dist_qu"], 200)             # but flagged-far, distance persisted

    def test_suspect_on_self_damage_with_launch(self):
        # explosive jump = in-band self-damage AND a coincident upward launch (both required)
        pts = _straight(1.0, 20, 0.0, 50.0)
        pts[5] = (pts[5][0], pts[5][1], 0.0, 0.0, 500.0, 0.0, 600.0, 0.0)   # vz 600 launch at t=1.5s
        dmg = [{"attacker": "p1", "victim": "p1", "weapon": "rl", "damage": 40, "time": 1500}]
        hw = _build(pts, 1.0, 2.9, dmg=dmg)
        self.assertTrue(hw["suspect_trick"])
        self.assertTrue(any("explosive jump" in r for r in hw["suspect_reasons"]))

    def test_self_damage_without_launch_stays_clean(self):
        # in-band self-damage but flat low vz = combat splash (a rocket eaten mid-fight) -> NOT a jump
        dmg = [{"attacker": "p1", "victim": "p1", "weapon": "rl", "damage": 40, "time": 1500}]
        hw = _build(_straight(1.0, 20, 0.0, 50.0), 1.0, 2.9, dmg=dmg)   # vz constant 100 < LAUNCH_VZ
        self.assertFalse(hw["suspect_trick"])

    def test_vz_launch_without_self_damage_stays_clean(self):
        # vz alone no longer flags (hills/lifts reach ~615); max_vz still recorded descriptively
        pts = _straight(1.0, 20, 0.0, 50.0)
        pts[10] = (pts[10][0], pts[10][1], 0.0, 0.0, 500.0, 0.0, 1000.0, 0.0)
        hw = _build(pts, 1.0, 2.9, dmg=[])             # available stream, no self-damage
        self.assertFalse(hw["suspect_trick"])
        self.assertEqual(hw["segments"][0]["max_vz"], 1000)

    def test_launch_outside_window_stays_clean(self):
        # F2 — locks the temporal window: in-band self-damage with low vz near the hit, but the only
        # vz>=LAUNCH_VZ tick is OUTSIDE [time-200, time+400]ms (far end of the run) -> clean.
        pts = _straight(1.0, 20, 0.0, 50.0)
        pts[18] = (pts[18][0], pts[18][1], 0.0, 0.0, 500.0, 0.0, 800.0, 0.0)  # launch t=2.8s, >400ms after hit
        dmg = [{"attacker": "p1", "victim": "p1", "weapon": "rl", "damage": 40, "time": 1500}]
        hw = _build(pts, 1.0, 2.9, dmg=dmg)
        self.assertFalse(hw["suspect_trick"])

    def test_below_min_dmg_stays_clean(self):
        # F3 — locks the lower bound: a scratch (< SELF_DMG_MIN) even with a launch -> clean
        pts = _straight(1.0, 20, 0.0, 50.0)
        pts[5] = (pts[5][0], pts[5][1], 0.0, 0.0, 500.0, 0.0, 600.0, 0.0)
        dmg = [{"attacker": "p1", "victim": "p1", "weapon": "rl", "damage": 10, "time": 1500}]
        hw = _build(pts, 1.0, 2.9, dmg=dmg)
        self.assertFalse(hw["suspect_trick"])

    def test_above_max_dmg_stays_clean(self):
        # an explosive death/suicide (> SELF_DMG_MAX) even with a launch -> not a survivable jump
        pts = _straight(1.0, 20, 0.0, 50.0)
        pts[5] = (pts[5][0], pts[5][1], 0.0, 0.0, 500.0, 0.0, 600.0, 0.0)
        dmg = [{"attacker": "p1", "victim": "p1", "weapon": "rl", "damage": 115, "time": 1500}]
        hw = _build(pts, 1.0, 2.9, dmg=dmg)
        self.assertFalse(hw["suspect_trick"])

    def test_non_explosive_self_damage_stays_clean(self):
        # contract: an explosive jump is rocket/grenade ONLY — a non-explosive self-damage event
        # (even in-band + a coincident launch) must NOT flag as an explosive jump
        pts = _straight(1.0, 20, 0.0, 50.0)
        pts[5] = (pts[5][0], pts[5][1], 0.0, 0.0, 500.0, 0.0, 600.0, 0.0)
        dmg = [{"attacker": "p1", "victim": "p1", "weapon": "sg", "damage": 40, "time": 1500}]
        hw = _build(pts, 1.0, 2.9, dmg=dmg)
        self.assertFalse(hw["suspect_trick"])

    def test_fail_closed_on_unavailable_damage(self):
        # missing/malformed damage stream must NOT be passed as clean (absence != trick-free)
        hw = _build(_straight(1.0, 20, 0.0, 50.0), 1.0, 2.9, dmg=None)
        self.assertTrue(hw["suspect_trick"])
        self.assertTrue(any("unavailable" in r for r in hw["suspect_reasons"]))

    def test_authoritative_empty_damage_stays_clean(self):
        # an available, genuinely-empty damage stream ([]) is a real "no self-damage" -> clean
        hw = _build(_straight(1.0, 20, 0.0, 50.0), 1.0, 2.9, dmg=[])
        self.assertFalse(hw["suspect_trick"])


if __name__ == "__main__":
    unittest.main()
