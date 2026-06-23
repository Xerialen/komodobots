#!/usr/bin/env python3
"""Per-tick onground derivation + interpolation-carry tests (#316).

The POV .qwd svc_playerinfo stream does NOT carry a usable server-side FL_ONGROUND
flag (the PF_ONGROUND bit is never set), so every raw `onground` is False for the
ego-self spine AND every observed-other. The catalog therefore DERIVES onground
geometrically: trace the player hull straight down against the real map BSP at each
recovered origin (pmove_sim.derive_onground = the floor branch of mvdsv
PM_CategorizePosition).

These tests have NO catalog / no .qwd / no real-BSP dependency so they run on the
hosted CI stdlib floor (`python3 -m unittest discover`). They cover:

  1. derive_onground's decision rule, exercised against a hand-built FLAT-FLOOR world
     using the REAL player_trace machinery (not a mock): on-floor -> True, in open air
     -> False, strongly-ascending -> False (the vz short-circuit), buried-in-solid ->
     False.
  2. derive_onground's normal-threshold + miss branches via a mocked player_trace, so a
     too-steep face is airborne and a fraction==1.0 miss is airborne regardless of normal.
  3. build_replay_command_file.interpolated_reference: an interpolated (state-dropped)
     frame carries the NEAREST matched frame's discrete flags (onground/solid/pm_code),
     NOT the old conservative `prev AND next` that mashed onground toward False on every
     boundary tick.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
sys.setrecursionlimit(20000)

import pmove_sim as P  # noqa: E402
import build_replay_command_file as brc  # noqa: E402
import probe_qwd_route_applicability as probe  # noqa: E402
from tools.qwd_usercmd import qwd_usercmd  # noqa: E402


def _flat_floor_world():
    """A minimal WorldModel: solid half-space z<0, empty z>=0 (one axial-Z plane).

    Shared hull0/hull1 (a point-plane is enough for a flat floor test). With the REAL
    player_trace, a state at small z>0 traced down 1 qu crosses z=0 and reports a floor
    hit (normal +Z); a state high above misses within 1 qu (fraction 1.0)."""
    planes = [(0.0, 0.0, 1.0, 0.0, 2)]                       # nx,ny,nz,dist,ptype(axial Z)
    clipnodes = [(0, P.CONTENTS_EMPTY, P.CONTENTS_SOLID)]    # child0: z>=0 EMPTY, child1: z<0 SOLID
    hull = P.Hull(planes=planes, clipnodes=clipnodes, firstclipnode=0)
    return P.WorldModel(
        hull0=hull, hull1=hull,
        world_mins=(-1000.0, -1000.0, -1000.0),
        world_maxs=(1000.0, 1000.0, 1000.0),
        submodels=[],
    )


def _trace(fraction, normal, *, startsolid=False, allsolid=False):
    """Build a Trace stand-in for mocking player_trace."""
    tr = P.Trace((0.0, 0.0, 0.0))
    tr.fraction = fraction
    tr.normal = list(normal)
    tr.startsolid = startsolid
    tr.allsolid = allsolid
    return tr


class DeriveOngroundGeometryTest(unittest.TestCase):
    """derive_onground against a real flat-floor trace (no BSP needed)."""

    @classmethod
    def setUpClass(cls):
        cls.world = _flat_floor_world()

    def test_on_floor_is_grounded(self):
        # origin just above the floor (within the 1 qu down-trace) -> grounded.
        self.assertTrue(P.derive_onground(self.world, (0.0, 0.0, 0.5), (0.0, 0.0, 0.0)))
        self.assertTrue(P.derive_onground(self.world, (10.0, -7.0, 0.0), (50.0, -30.0, 0.0)))

    def test_open_air_is_airborne(self):
        # well above the floor -> the 1 qu down-trace misses -> airborne.
        self.assertFalse(P.derive_onground(self.world, (0.0, 0.0, 5.0), (0.0, 0.0, 0.0)))
        self.assertFalse(P.derive_onground(self.world, (0.0, 0.0, 100.0), (0.0, 0.0, 0.0)))

    def test_buried_in_solid_is_not_grounded(self):
        # origin below the floor (inside solid): startsolid, no standable floor normal.
        self.assertFalse(P.derive_onground(self.world, (0.0, 0.0, -0.5), (0.0, 0.0, 0.0)))

    def test_strongly_ascending_short_circuits_to_airborne(self):
        # vz > 180 (MAXGROUNDSPEED_DEFAULT): airborne even though the hull still overlaps
        # the floor this tick. This is the "just left the ground" case pmove models.
        self.assertGreater(201.0, P.MAXGROUNDSPEED_DEFAULT)
        self.assertFalse(P.derive_onground(self.world, (0.0, 0.0, 0.5), (0.0, 0.0, 201.0)))
        # at/under the threshold, with the floor present, it is grounded.
        self.assertTrue(P.derive_onground(self.world, (0.0, 0.0, 0.5), (0.0, 0.0, 180.0)))
        # descending fast but on the floor -> grounded (vz only gates the UP case).
        self.assertTrue(P.derive_onground(self.world, (0.0, 0.0, 0.5), (0.0, 0.0, -260.0)))

    def test_caller_contract_uses_min_step_normal_constant(self):
        # Pin the engine constants the derivation depends on (regression tripwire).
        self.assertEqual(P.MIN_STEP_NORMAL, 0.7)
        self.assertEqual(P.MAXGROUNDSPEED_DEFAULT, 180.0)


class DeriveOngroundDecisionBranchTest(unittest.TestCase):
    """derive_onground's floor-normal / miss branches, isolated via a mocked trace."""

    def setUp(self):
        self.world = object()  # never touched: player_trace is patched

    def test_floor_hit_with_standable_normal_is_grounded(self):
        with mock.patch.object(P, "player_trace",
                               return_value=_trace(0.5, (0.0, 0.0, 1.0))):
            self.assertTrue(P.derive_onground(self.world, (0, 0, 30), (0, 0, 0)))

    def test_floor_hit_with_too_steep_normal_is_airborne(self):
        # normal.z below MIN_STEP_NORMAL (0.7): a wall/steep ramp you slide off, not floor.
        with mock.patch.object(P, "player_trace",
                               return_value=_trace(0.5, (0.6, 0.0, 0.69))):
            self.assertFalse(P.derive_onground(self.world, (0, 0, 30), (0, 0, 0)))

    def test_trace_miss_is_airborne(self):
        # fraction == 1.0 -> nothing within 1 qu below -> airborne (normal irrelevant).
        with mock.patch.object(P, "player_trace",
                               return_value=_trace(1.0, (0.0, 0.0, 1.0))):
            self.assertFalse(P.derive_onground(self.world, (0, 0, 30), (0, 0, 0)))

    def test_ascending_does_not_even_trace(self):
        # the vz short-circuit must return before calling player_trace at all.
        with mock.patch.object(P, "player_trace",
                               side_effect=AssertionError("must not trace when ascending")):
            self.assertFalse(P.derive_onground(self.world, (0, 0, 30), (0, 0, 500)))


def _cmd(time_s, *, msec=13, yaw=90.0):
    return qwd_usercmd.UsercmdRecord(
        file_offset=0, frame=0, time_s=time_s, msec=msec,
        view_angles=(0.0, yaw, 0.0), forwardmove=400, sidemove=0, upmove=0, buttons=2,
        impulse=0, cmd_angles=(0.0, yaw, 0.0),
    )


def _state(time_s, *, onground, solid=True, pm_code=0, ox=0.0):
    return probe.PlayerInfoSample(
        record_index=0, time_s=time_s, playernum=1, flags=0,
        origin=(ox, 0.0, 24.0), velocity=(320, 0, 0), frame=0,
        onground=onground, solid=solid, pm_code=pm_code, payload_len=0, parsed_len=0,
    )


class InterpolationCarriesNearestFlagTest(unittest.TestCase):
    """interpolated_reference carries the NEAREST matched frame's discrete flags, not a
    conservative prev-AND-next (the latent #316 bug: AND mashed onground toward False)."""

    def test_interpolated_frame_carries_nearer_endpoint_flags(self):
        # commands at t=0.00, 0.013, 0.026; the MIDDLE command (idx 1) has no matched
        # state (state-drop), so it interpolates between idx 0 and idx 2.
        commands = [_cmd(0.000), _cmd(0.013), _cmd(0.026)]
        states = [_state(0.000, onground=True, solid=True, pm_code=1),
                  _state(0.026, onground=False, solid=False, pm_code=2)]
        state_for_cmd = {0: 0, 2: 1}  # idx 1 unmatched -> interpolated

        # idx-1 command time 0.013 sits exactly halfway (frac 0.5) -> rounds to the NEXT
        # endpoint (idx 2): onground False, solid False, pm_code 2.
        _o, _v, ong, solid, pmc, kind = brc.interpolated_reference(1, commands, states, state_for_cmd)
        self.assertEqual(kind, "interpolated")
        self.assertFalse(ong)
        self.assertFalse(solid)
        self.assertEqual(pmc, 2)

    def test_interpolated_frame_nearer_to_prev_carries_prev_flags(self):
        # Move the dropped command's time closer to the PREV endpoint (frac < 0.5) so it
        # carries idx-0's grounded/solid/pm_code=1 — the case the old AND wrongly zeroed.
        commands = [_cmd(0.000), _cmd(0.004), _cmd(0.026)]
        states = [_state(0.000, onground=True, solid=True, pm_code=1),
                  _state(0.026, onground=False, solid=False, pm_code=2)]
        state_for_cmd = {0: 0, 2: 1}

        _o, _v, ong, solid, pmc, kind = brc.interpolated_reference(1, commands, states, state_for_cmd)
        self.assertEqual(kind, "interpolated")
        self.assertTrue(ong, "grounded prev neighbour must survive (old AND wrongly zeroed it)")
        self.assertTrue(solid)
        self.assertEqual(pmc, 1)

    def test_old_and_logic_would_have_been_wrong_here(self):
        # Both endpoints grounded EXCEPT we make prev grounded, next airborne, and the
        # frame leans toward prev: nearest -> grounded. (prev AND next) would be False.
        commands = [_cmd(0.000), _cmd(0.004), _cmd(0.026)]
        states = [_state(0.000, onground=True), _state(0.026, onground=False)]
        _o, _v, ong, _s, _p, _k = brc.interpolated_reference(1, commands, states, {0: 0, 2: 1})
        and_logic = bool(states[0].onground and states[1].onground)
        self.assertFalse(and_logic)        # what the old code produced
        self.assertTrue(ong)               # what nearest-carry correctly produces

    def test_matched_frame_passes_flag_through_untouched(self):
        commands = [_cmd(0.000), _cmd(0.013)]
        states = [_state(0.000, onground=True, pm_code=3)]
        _o, _v, ong, _s, pmc, kind = brc.interpolated_reference(0, commands, states, {0: 0})
        self.assertEqual(kind, "matched")
        self.assertTrue(ong)
        self.assertEqual(pmc, 3)


if __name__ == "__main__":
    unittest.main()
