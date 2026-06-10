"""mode23_sim: the pure parts of the control-law port + nav stub (issue #69).

Covers, with no BSP / no lab dependency:
  * FBMARKER dump parsing (live numbering, hex path flags, dedup)
  * marker nav-position model (FL_ITEM abs expansion cancels the 80/80/24
    view_ofs for "marker"-class -> nav == dumped origin; item offsets)
  * frogbot edge times (teleport source 0, RJ excluded, dist/maxspeed)
  * Dijkstra traveltime emulation of the zone tables
  * EvalPath / PathScoringLogic given a fixed RNG (goal-progress dominance,
    ROCKET_JUMP exclusion)
  * ProcessNewLinkedMarker: ExistsPath shortcut, goal-arrival hold
  * the mode-23 law step given fixed state: ground redirect, weave hysteresis,
    hard-corner clamp, pass-through curl hold, jump suppression on corner
    legs, the bunnyhop toggle, delegation early-return + 3 s livelock release,
    and the per-config carrot guards (c1 / c4 / c5)

The closed-loop calibration itself is an analysis run (see
experiments/p3b_calibration/), not a unit test.
"""

import math
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import mode23_sim as M  # noqa: E402
from pmove_sim import PlayerState  # noqa: E402

DUMP = """\
[2026-06-09 21:35:56] FBMARKER 1 weapon_rocketlauncher 1520 496 -111 G17 Z1 P[ 45:0 69:0 46:0 ]
[2026-06-09 21:35:56] FBMARKER 2 marker 100 200 -40 G0 Z2 P[ 3:0 4:200 5:400 ]
[2026-06-09 21:35:56] FBMARKER 2 marker 999 999 999 G9 Z9 P[ ]
[2026-06-09 21:35:56] FBMARKER 3 item_shells 0 0 0 G1 Z2 P[ 2:0 ]
"""


class TestDumpParse(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp()) / "screen.log"
        self.tmp.write_text(DUMP)
        self.markers = M.parse_fbmarker_dump(self.tmp)

    def test_count_and_dedup(self):
        self.assertEqual(set(self.markers), {1, 2, 3})
        # repeated dump lines for the same marker must keep the FIRST record
        self.assertEqual(self.markers[2].org, (100.0, 200.0, -40.0))

    def test_paths_and_hex_flags(self):
        self.assertEqual(self.markers[2].paths,
                         [(3, 0), (4, 0x200), (5, 0x400)])
        self.assertEqual(self.markers[1].cls, "weapon_rocketlauncher")
        self.assertEqual(self.markers[1].Z, 1)
        self.assertEqual(self.markers[1].G, 17)


class FakeGraph:
    """Duck-typed NavGraph for law/selection tests (no BSP)."""

    def __init__(self, markers, edges):
        # markers: num -> (nav xyz); edges: (frm, to, idx) -> (flags, time)
        self.world = None
        self.markers = {}
        for num, nav in markers.items():
            mk = M.Marker(num, "marker", nav, 0, 1, [])
            mk.nav = nav
            mk.absmin = (nav[0] - 80, nav[1] - 80, nav[2] - 24)
            mk.absmax = (nav[0] + 80, nav[1] + 80, nav[2] + 32)
            mk.center = nav
            self.markers[num] = mk
        self.edge_time = {}
        for (frm, to, idx), (flags, t) in edges.items():
            self.markers[frm].paths.append((to, flags))
            self.edge_time[(frm, to, idx)] = t

    def traveltime_to(self, goal):
        return M.NavGraph.traveltime_to(self, goal)


class FixedRng:
    """Deterministic stand-in for g_random."""

    def __init__(self, value=0.5):
        self.value = value

    def random(self):
        return self.value

    def choices(self, pop, weights=None):
        return [pop[0]]


def straight_graph():
    # 1 -> 2 -> 3(goal), plus a slow detour 1 -> 4 -> 3 and an RJ shortcut 1 -> 3
    markers = {1: (0.0, 0.0, 0.0), 2: (320.0, 0.0, 0.0), 3: (640.0, 0.0, 0.0),
               4: (0.0, 640.0, 0.0)}
    edges = {
        (1, 2, 0): (0, 1.0), (2, 3, 0): (0, 1.0),
        (1, 4, 1): (0, 2.0), (4, 3, 0): (0, 2.0),
        (1, 3, 2): (M.ROCKET_JUMP, 100000.0),
        (3, 2, 0): (0, 1.0), (2, 1, 0): (0, 1.0),
    }
    return FakeGraph(markers, edges)


class TestTraveltimeAndSelection(unittest.TestCase):
    def test_dijkstra_times(self):
        g = straight_graph()
        tt = g.traveltime_to(3)
        self.assertAlmostEqual(tt[3], 0.0)
        self.assertAlmostEqual(tt[2], 1.0)
        self.assertAlmostEqual(tt[1], 2.0)   # via 2, not the 4.0 detour
        self.assertAlmostEqual(tt[4], 2.0)

    def test_path_scoring_prefers_goal_progress(self):
        g = straight_graph()
        brain = M.FrogbotBrain(g, 3, FixedRng(0.5))
        linked, state = brain.path_scoring(1, (0.0, 0.0, 0.0), (1.0, 0.0, 0.0))
        self.assertEqual(linked, 2)
        self.assertEqual(state, 0)

    def test_rocket_jump_paths_excluded(self):
        g = straight_graph()
        brain = M.FrogbotBrain(g, 3, FixedRng(0.5))
        score = brain.eval_path(3, M.ROCKET_JUMP, 0.1, (0, 0, 0), (1, 0, 0),
                                10.0, -1e6)
        self.assertEqual(score, M.PATH_SCORE_NULL)

    def test_edge_time_rules(self):
        # real NavGraph path-time rules, no BSP: build via FakeGraph analogue
        mk_tp = M.Marker(1, "trigger_teleport", (0, 0, 0), 0, 1, [(2, 0)])
        mk_b = M.Marker(2, "marker", (320, 0, 0), 0, 1, [(1, M.ROCKET_JUMP)])
        for mk in (mk_tp, mk_b):
            mk.nav = mk.org
            mk.in_water = False
        g = object.__new__(M.NavGraph)
        g.markers = {1: mk_tp, 2: mk_b}
        M.NavGraph._compute_path_times(g)
        self.assertEqual(g.edge_time[(1, 2, 0)], 0.0)          # teleporter src
        self.assertEqual(g.edge_time[(2, 1, 0)], 100000.0)     # RJ excluded


class TestPnlm(unittest.TestCase):
    def test_exists_path_shortcut_keeps_linked(self):
        g = straight_graph()
        brain = M.FrogbotBrain(g, 3, FixedRng(0.5))
        nav = M.NavState()
        nav.old_linked_marker = 1
        nav.touch_marker = 2
        nav.linked_marker = 3
        brain.pnlm(nav, (320.0, 0.0, 0.0), (1.0, 0.0, 0.0), now=10.0)
        self.assertEqual(nav.linked_marker, 3)     # kept, not re-scored
        self.assertEqual(nav.path_state, 0)

    def test_arrival_at_goal_holds(self):
        g = straight_graph()
        brain = M.FrogbotBrain(g, 3, FixedRng(0.5))
        nav = M.NavState()
        nav.touch_marker = 3
        nav.linked_marker = 3
        nav.path_state = 7
        brain.pnlm(nav, (640.0, 0.0, 0.0), (0.0, 0.0, 0.0), now=10.0)
        self.assertEqual(nav.linked_marker, 3)
        self.assertEqual(nav.path_state, 7)        # untouched: early return


def law_setup(linked_nav=(640.0, 0.0, 0.0), origin=(0.0, 0.0, 0.0),
              velocity=(0.0, 0.0, 0.0), onground=False, path_flags=0,
              linked=2, touch=1):
    g = FakeGraph({1: (0.0, 0.0, 0.0), 2: linked_nav, 3: (9999.0, 0.0, 0.0)},
                  {(1, 2, 0): (0, 1.0), (2, 3, 0): (0, 1.0)})
    brain = M.FrogbotBrain(g, 3, FixedRng(0.5))
    law = M.LawState()
    nav = M.NavState()
    nav.touch_marker = touch
    nav.linked_marker = linked
    nav.path_state = path_flags
    st = PlayerState(list(origin), list(velocity))
    st.onground = onground
    st.waterlevel = 0
    return law, nav, brain, st


OPEN = lambda a, b: 1.0     # noqa: E731  open-space traceline stub


class TestMode23Law(unittest.TestCase):
    def test_water_falls_through(self):
        law, nav, brain, st = law_setup()
        st.waterlevel = 2
        self.assertIsNone(M.mode23_step(law, nav, brain, st, 0.0, trace_fn=OPEN))

    def test_ground_full_redirect_and_toggle_jump(self):
        law, nav, brain, st = law_setup(onground=True,
                                        velocity=(300.0, 0.0, 0.0))
        out = M.mode23_step(law, nav, brain, st, 0.0, trace_fn=OPEN)
        yaw, move, jump = out
        self.assertAlmostEqual(yaw, 0.0)           # straight at the marker
        self.assertEqual(move, (M.SV_MAXSPEED, 0, 0))
        self.assertTrue(jump)                      # first grounded frame hops
        out2 = M.mode23_step(law, nav, brain, st, 0.01, trace_fn=OPEN)
        self.assertFalse(out2[2])                  # toggle: release next frame

    def test_air_weave_rotation_is_acos_law(self):
        speed = 400.0
        law, nav, brain, st = law_setup(velocity=(speed, 0.0, 0.0))
        law.strafe_sign = 1
        out = M.mode23_step(law, nav, brain, st, 0.0, trace_fn=OPEN)
        expect = math.degrees(math.acos(M.NUMERATOR / speed))
        self.assertAlmostEqual(out[0], expect % 360.0, places=4)

    def test_air_swing_hysteresis_flips_sign(self):
        # velocity 20 deg LEFT of the marker bearing: signed_to_goal = -20
        # (beyond swing 12) -> a positive curl must flip to -1
        v = (math.cos(math.radians(20)) * 400, math.sin(math.radians(20)) * 400, 0)
        law, nav, brain, st = law_setup(velocity=v)
        law.strafe_sign = 1
        M.mode23_step(law, nav, brain, st, 0.0, trace_fn=OPEN)
        self.assertEqual(law.strafe_sign, -1)

    def test_corner_leg_sets_sign_and_suppresses_jump(self):
        # marker 90 deg left of velocity, NOT in pass-through -> corner mode
        law, nav, brain, st = law_setup(linked_nav=(0.0, 640.0, 0.0),
                                        velocity=(400.0, 0.0, 0.0),
                                        onground=True)
        out = M.mode23_step(law, nav, brain, st, 0.0, trace_fn=OPEN)
        self.assertFalse(out[2])                   # grounded + herr>35: no hop
        law2, nav2, brain2, st2 = law_setup(linked_nav=(0.0, 640.0, 0.0),
                                            velocity=(400.0, 0.0, 0.0))
        out2 = M.mode23_step(law2, nav2, brain2, st2, 0.0, trace_fn=OPEN)
        self.assertEqual(law2.strafe_sign, 1)      # sign aims at the error side
        # hard corner (herr 90 > 58): rotation clamped at corner_aim 68
        self.assertAlmostEqual(out2[0], 68.0, places=4)

    def test_pass_through_holds_curl_and_allows_hop(self):
        # inside pass_r of the linked marker, bearing 90 deg off velocity:
        # weave must HOLD the current curl (no corner reaction, no flips)
        law, nav, brain, st = law_setup(linked_nav=(0.0, 100.0, 0.0),
                                        velocity=(400.0, 0.0, 0.0),
                                        onground=True)
        law.carrot_done = 2                        # edge-trigger already used
        law.strafe_sign = -1
        out = M.mode23_step(law, nav, brain, st, 0.0, trace_fn=OPEN)
        self.assertEqual(law.strafe_sign, -1)      # held, not flipped
        self.assertTrue(out[2])                    # hop NOT suppressed

    def test_delegation_early_return_and_livelock_release(self):
        # grounded, marker 100 qu ahead and 30 up, no jump flags -> delegate
        law, nav, brain, st = law_setup(linked_nav=(100.0, 0.0, 30.0),
                                        onground=True)
        self.assertIsNone(M.mode23_step(law, nav, brain, st, 0.0, trace_fn=OPEN))
        self.assertEqual(law.deleg_marker, 2)
        # still delegated short of the timeout
        self.assertIsNone(M.mode23_step(law, nav, brain, st, 2.9, trace_fn=OPEN))
        # past 3 s on the SAME marker: released to the weave
        self.assertIsNotNone(M.mode23_step(law, nav, brain, st, 3.1, trace_fn=OPEN))

    def test_delegation_skips_jump_flagged_paths(self):
        law, nav, brain, st = law_setup(linked_nav=(100.0, 0.0, 30.0),
                                        onground=True,
                                        path_flags=M.JUMP_LEDGE)
        self.assertIsNotNone(M.mode23_step(law, nav, brain, st, 0.0, trace_fn=OPEN))


class TestCarrotGuards(unittest.TestCase):
    """The c1/c4/c5 difference is ONLY the handover guard."""

    def fire(self, config, onground, dz, path_flags=0):
        nav_z = dz
        law, nav, brain, st = law_setup(linked_nav=(100.0, 0.0, nav_z),
                                        onground=onground,
                                        path_flags=path_flags)
        M.mode23_step(law, nav, brain, st, 0.0, config=config, trace_fn=OPEN)
        return law.carrot_done is not None

    def test_c1_has_no_guard(self):
        self.assertTrue(self.fire("c1", onground=True, dz=30.0))

    def test_c4_broad_guard_blocks_any_close_climb(self):
        self.assertFalse(self.fire("c4", onground=True, dz=30.0))
        self.assertFalse(self.fire("c4", onground=True, dz=30.0,
                                   path_flags=M.JUMP_LEDGE))

    def test_c5_delegation_exact_guard(self):
        # blocks exactly where delegation would run...
        self.assertFalse(self.fire("c5", onground=True, dz=30.0))
        # ...but NOT on jump-flagged paths (delegation never runs there)
        self.assertTrue(self.fire("c5", onground=True, dz=30.0,
                                  path_flags=M.JUMP_LEDGE))
        self.assertTrue(self.fire("c5", onground=True, dz=30.0,
                                  path_flags=M.ROCKET_JUMP))

    def test_airborne_carrot_always_fires(self):
        for cfg in M.CONFIGS:
            self.assertTrue(self.fire(cfg, onground=False, dz=30.0))

    def test_edge_trigger_is_per_marker(self):
        law, nav, brain, st = law_setup(linked_nav=(100.0, 0.0, 0.0))
        M.mode23_step(law, nav, brain, st, 0.0, trace_fn=OPEN)
        self.assertEqual(law.carrot_done, 2)
        # second pass at the same marker: latch holds, pnlm not re-run
        nav.touch_marker = 1
        nav.linked_marker = 2
        before = nav.old_linked_marker
        M.mode23_step(law, nav, brain, st, 0.1, trace_fn=OPEN)
        self.assertEqual(nav.old_linked_marker, before)


class TestTeleporterBoxes(unittest.TestCase):
    """load_teleporters must store the TRIGGER abs box only (resize +-32 xy +
    engine +-1); the player abs box is applied at the intersection test, not
    baked in (Codex PR #83 P2: double expansion)."""

    @staticmethod
    def _mini_bsp(tmpdir):
        import struct
        ents = (b'{\n"classname" "info_teleport_destination"\n'
                b'"targetname" "t1"\n"origin" "100 200 50"\n"angle" "90"\n}\n'
                b'{\n"classname" "trigger_teleport"\n"target" "t1"\n'
                b'"model" "*1"\n}\n\x00')
        # models lump: world (model 0) + the trigger brush (model 1)
        def model(mins, maxs):
            return struct.pack("<9f7i", *mins, *maxs, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
        models = model((0, 0, 0), (0, 0, 0)) + model((-64, -32, 0), (64, 32, 96))
        header_size = 4 + 15 * 8
        lumps = [(header_size, 0)] * 15
        lumps[0] = (header_size, len(ents))                      # entities
        lumps[14] = (header_size + len(ents), len(models))       # models
        blob = struct.pack("<i", 29)
        for off, ln in lumps:
            blob += struct.pack("<ii", off, ln)
        blob += ents + models
        p = Path(tmpdir) / "mini.bsp"
        p.write_bytes(blob)
        return p

    def test_trigger_abs_box_and_destination(self):
        import tempfile
        bsp = self._mini_bsp(tempfile.mkdtemp())
        teles = M.load_teleporters(bsp)
        self.assertEqual(len(teles), 1)
        tp = teles[0]
        # resize +-32 xy (fb_spawn_trigger_teleport) + engine +-1 all axes
        self.assertEqual(tp.absmin, (-64 - 33, -32 - 33, 0 - 1))
        self.assertEqual(tp.absmax, (64 + 33, 32 + 33, 96 + 1))
        # SP_info_teleport_destination raises the spot 27 units
        self.assertEqual(tp.dest, [100.0, 200.0, 50.0 + 27.0])
        self.assertEqual(tp.mangle_yaw, 90.0)


def gov_setup(linked_nav=(100.0, 0.0, 0.0), next_nav=(0.0, 9999.0, 0.0),
              velocity=(400.0, 0.0, 0.0), onground=False):
    """Carrot-handover fixture (A2 #74): bot at origin, linked marker 2
    inside pass_r so the carrot fires and PNLM re-aims at marker 3 (goal)."""
    g = FakeGraph({1: (0.0, 0.0, 0.0), 2: linked_nav, 3: next_nav},
                  {(1, 2, 0): (0, 1.0), (2, 3, 0): (0, 1.0)})
    brain = M.FrogbotBrain(g, 3, FixedRng(0.5))
    law = M.LawState()
    nav = M.NavState()
    nav.touch_marker = 1
    nav.linked_marker = 2
    st = PlayerState([0.0, 0.0, 0.0], list(velocity))
    st.onground = onground
    st.waterlevel = 0
    return law, nav, brain, st


class TestPrecisionGovernor(unittest.TestCase):
    """A2 #74: the two live-rejected governor designs, re-implemented per the
    ledger (c2 velocity-triggered / c3 positional) on the surviving C apply/
    clear block. governor='none' (the default) must leave them fully dead."""

    VEL = M.LawParams(governor="vel")
    POS = M.LawParams(governor="pos")

    def test_none_never_engages(self):
        law, nav, brain, st = gov_setup()
        out = M.mode23_step(law, nav, brain, st, 0.0, trace_fn=OPEN)
        self.assertIsNone(law.prec_marker)
        # handover happened, weave continues: hard corner (herr 90 > 58)
        # clamps the rotation at corner_aim 68
        self.assertEqual(nav.linked_marker, 3)
        self.assertAlmostEqual(out[0], 68.0, places=4)

    def test_vel_engages_on_sharp_leg_turn(self):
        # new leg bearing 90 deg, velocity yaw 0 -> |leg_turn| = 90 > 60
        law, nav, brain, st = gov_setup()
        out = M.mode23_step(law, nav, brain, st, 0.0, trace_fn=OPEN,
                            params=self.VEL)
        self.assertEqual(law.prec_marker, 3)
        self.assertAlmostEqual(out[0], 90.0, places=4)   # straight-aim at 3

    def test_vel_quiet_on_straight_legs(self):
        # next marker straight ahead of the velocity: leg_turn 0 -> no engage
        law, nav, brain, st = gov_setup(next_nav=(9999.0, 0.0, 0.0))
        M.mode23_step(law, nav, brain, st, 0.0, trace_fn=OPEN, params=self.VEL)
        self.assertIsNone(law.prec_marker)

    def test_pos_uses_positional_bearing_not_velocity(self):
        # velocity NORTH (yaw 90) toward the new marker -> the vel variant
        # stays quiet; the pos variant compares old-leg bearing (0 deg,
        # marker 2 east) vs new-leg bearing (90 deg) -> engages.
        law, nav, brain, st = gov_setup(velocity=(0.0, 400.0, 0.0))
        M.mode23_step(law, nav, brain, st, 0.0, trace_fn=OPEN, params=self.VEL)
        self.assertIsNone(law.prec_marker)
        law, nav, brain, st = gov_setup(velocity=(0.0, 400.0, 0.0))
        M.mode23_step(law, nav, brain, st, 0.0, trace_fn=OPEN, params=self.POS)
        self.assertEqual(law.prec_marker, 3)

    def test_pos_never_engages_on_climb_legs(self):
        # new marker 40 up (> 18): c3's climb exemption blocks the engage;
        # c2 has no such exemption.
        law, nav, brain, st = gov_setup(next_nav=(0.0, 9999.0, 40.0))
        M.mode23_step(law, nav, brain, st, 0.0, trace_fn=OPEN, params=self.POS)
        self.assertIsNone(law.prec_marker)
        law, nav, brain, st = gov_setup(next_nav=(0.0, 9999.0, 40.0))
        M.mode23_step(law, nav, brain, st, 0.0, trace_fn=OPEN, params=self.VEL)
        self.assertEqual(law.prec_marker, 3)

    def test_apply_window_suppresses_jump_then_times_out(self):
        # pos engage with velocity ALIGNED to the new leg (herr 0): without
        # the governor the grounded toggle would hop, so out[2] isolates the
        # precision suppression, and the 2 s escape restores it.
        law, nav, brain, st = gov_setup(velocity=(0.0, 400.0, 0.0),
                                        onground=True)
        out = M.mode23_step(law, nav, brain, st, 0.0, trace_fn=OPEN,
                            params=self.POS)
        self.assertEqual(law.prec_marker, 3)
        self.assertFalse(out[2])                  # suppressed by precision
        out = M.mode23_step(law, nav, brain, st, 1.5, trace_fn=OPEN,
                            params=self.POS)
        self.assertEqual(law.prec_marker, 3)
        self.assertFalse(out[2])                  # still inside the window
        out = M.mode23_step(law, nav, brain, st, 2.5, trace_fn=OPEN,
                            params=self.POS)
        self.assertIsNone(law.prec_marker)        # escape: cleared
        self.assertTrue(out[2])                   # bunnyhop toggle resumes

    def test_cleared_when_marker_taken(self):
        law, nav, brain, st = gov_setup()
        M.mode23_step(law, nav, brain, st, 0.0, trace_fn=OPEN, params=self.VEL)
        self.assertEqual(law.prec_marker, 3)
        nav.linked_marker = 2                     # marker changed under us
        nav.touch_marker = 1
        M.mode23_step(law, nav, brain, st, 0.1, trace_fn=OPEN, params=self.VEL)
        self.assertIsNone(law.prec_marker)


class TestCarrotLead(unittest.TestCase):
    """carrot_lead: the handover ALSO fires within vh*lead distance (speed-
    adaptive earlier handover); the pass_through weave zone stays at pass_r."""

    def test_lead_extends_the_handover_trigger(self):
        p = M.LawParams(pass_r=100.0, carrot_lead=0.3)
        # marker 150 away (> pass_r 100), vh 600 -> 600*0.3 = 180 > 150: fires
        law, nav, brain, st = gov_setup(linked_nav=(150.0, 0.0, 0.0),
                                        velocity=(600.0, 0.0, 0.0))
        M.mode23_step(law, nav, brain, st, 0.0, trace_fn=OPEN, params=p)
        self.assertEqual(law.carrot_done, 2)

    def test_lead_zero_keeps_live_behavior(self):
        p = M.LawParams(pass_r=100.0, carrot_lead=0.0)
        law, nav, brain, st = gov_setup(linked_nav=(150.0, 0.0, 0.0),
                                        velocity=(600.0, 0.0, 0.0))
        M.mode23_step(law, nav, brain, st, 0.0, trace_fn=OPEN, params=p)
        self.assertIsNone(law.carrot_done)

    def test_slow_speed_does_not_fire_early(self):
        p = M.LawParams(pass_r=100.0, carrot_lead=0.3)
        # vh 300 -> 90 < 150: no fire
        law, nav, brain, st = gov_setup(linked_nav=(150.0, 0.0, 0.0),
                                        velocity=(300.0, 0.0, 0.0))
        M.mode23_step(law, nav, brain, st, 0.0, trace_fn=OPEN, params=p)
        self.assertIsNone(law.carrot_done)


class TestLawParamsParity(unittest.TestCase):
    """params=None must be byte-identical to explicit LawParams() (the A1
    calibration behavior; the sweep's identity config)."""

    def test_default_params_match_none(self):
        for vel, og in (((400.0, 0.0, 0.0), False),
                        ((100.0, 380.0, 0.0), False),
                        ((300.0, 0.0, 0.0), True)):
            law1, nav1, brain1, st1 = law_setup(velocity=vel, onground=og)
            law2, nav2, brain2, st2 = law_setup(velocity=vel, onground=og)
            out1 = M.mode23_step(law1, nav1, brain1, st1, 0.0, trace_fn=OPEN)
            out2 = M.mode23_step(law2, nav2, brain2, st2, 0.0, trace_fn=OPEN,
                                 params=M.LawParams())
            self.assertEqual(out1, out2)
            self.assertEqual(law1.strafe_sign, law2.strafe_sign)


class TestVectorHelpers(unittest.TestCase):
    def test_vectoyaw_quadrants(self):
        self.assertEqual(M.vectoyaw((1, 0, 0)), 0.0)
        self.assertEqual(M.vectoyaw((0, 1, 0)), 90.0)
        self.assertEqual(M.vectoyaw((-1, 0, 0)), 180.0)
        self.assertEqual(M.vectoyaw((0, -1, 0)), 270.0)
        self.assertEqual(M.vectoyaw((0, 0, 5)), 0.0)   # QC zero-xy rule

    def test_rotate2d(self):
        v = M.rotate2d([1.0, 0.0, 0.0], 90.0)
        self.assertAlmostEqual(v[0], 0.0)
        self.assertAlmostEqual(v[1], 1.0)


class TestNavPositionModel(unittest.TestCase):
    """FL_ITEM abs expansion (xy -15, z unexpanded) + view_ofs 80/80/24:
    for "marker"-class the nav position is exactly the dumped origin."""

    def test_marker_nav_equals_origin(self):
        mk = M.Marker(7, "marker", (100.0, -50.0, 24.0), 0, 1, [])
        g = object.__new__(M.NavGraph)
        g.markers = {7: mk}
        g._point_contents = lambda p: -1     # EMPTY (no BSP)
        M.NavGraph._position_markers(g, [])
        self.assertEqual(mk.nav, (100.0, -50.0, 24.0))
        self.assertEqual(mk.absmin, (100.0 - 80, -50.0 - 80, 24.0 - 24))
        self.assertEqual(mk.absmax, (100.0 + 80, -50.0 + 80, 24.0 + 32))

    def test_ammo_box_nav_offset(self):
        # item_shells: mins (0,0,0), maxs (32,32,56) -> absmin = origin-(15,15,0)
        # -> nav = origin + (65, 65, 24)
        mk = M.Marker(8, "item_shells", (0.0, 0.0, 0.0), 1, 1, [])
        g = object.__new__(M.NavGraph)
        g.markers = {8: mk}
        g._point_contents = lambda p: -1
        M.NavGraph._position_markers(g, [])
        self.assertEqual(mk.nav, (65.0, 65.0, 24.0))


if __name__ == "__main__":
    unittest.main()
