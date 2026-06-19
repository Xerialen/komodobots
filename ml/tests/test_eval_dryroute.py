"""ml/tests/test_eval_dryroute.py — deps-free tests for the DRY-ROUTE robustness gate.

Mirrors how test_eval_closedloop tests the pure glue: NO torch / numpy / duckdb / real
BSP. The torch policy rollout (run_policy_rollout) and the BSP-backed end-to-end
(run_eval) are exercised on pinnacle with a real checkpoint + dm3.bsp; here we prove
the PURE glue that decides the gate:

  * make_row              — the scorer-row builder from a sim state (t/x/y/z/vh/
                            onground/over_void/dist_goal).
  * score_rows            — route% / speed% gate logic (PASS = route% >= 80 AND
                            speed% >= 80 on the dead-stop-proof time_weighted_speed),
                            with the harder REACHED_RL / launch-edge DIAGNOSTICS not
                            gating. Driven by a synthetic straight-line route + FAKE
                            rollout rows (no sim, no BSP).
  * over_void_at          — straight-DOWN trace classification, with a FAKE world whose
                            player_trace returns a controllable fraction.
  * controls_bracket      — the gate is VALID iff human PASSES and stall FAILS; a
                            non-bracketing pair is rejected.

The torch path is FAKE-exercised: a stub model + stub torch drive run_policy_rollout
over a FAKE world so the glue that turns head argmax -> usercmd -> rows is checked
without torch installed.
"""
import importlib.util
import math
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ML = HERE.parent
REPO_ROOT = ML.parent
sys.path.insert(0, str(ML))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import eval_broad_dryroute as DR     # noqa: E402  (deps-free at import time)
import route_metrics as RM           # noqa: E402  (pure-stdlib sibling; TELEPORT_JUMP)
from features import agent_observation as AO   # noqa: E402  (shared SELF transform; floor parity)

_HAVE_TORCH = importlib.util.find_spec("torch") is not None


def _floor_parity_stats():
    """Minimal normalization_stats dict for AO.self_features in the floor-parity test.
    self_features reads per_map[map] keys (pos/vel/hspeed/yaw_rate); identity-ish specs
    are enough — the floor branch zeroes the heading regardless of the fitted values, so
    these only need to be present and well-formed. Pure stdlib."""
    z = {"method": "zscore", "mean": 0.0, "std": 1.0}
    mm = {"method": "minmax", "min": -1.0, "max": 1.0}
    rb = {"method": "robust", "median": 0.0, "iqr": 1.0}
    return {"per_map": {"dm3": {
        "pos_x": mm, "pos_y": mm, "pos_z": mm,
        "vel_x": z, "vel_y": z, "vel_z": z,
        "hspeed": rb, "yaw_rate": z,
    }}}


# --------------------------------------------------------------------------- #
# Synthetic route + fakes (no real BSP, no sim, no torch).
# --------------------------------------------------------------------------- #
def _straight_route(*, n=40, step=100.0, with_gap=True):
    """A synthetic straight-line route along +x from (0,0,0). Human path H has n
    points; cum is its arc length. goal = last point. Optional final hard gap with a
    launch edge near the end (required launch speed 525) so the leap DIAGNOSTIC is
    exercised. No teleporters. Shaped exactly like verify_route.load_route's output
    plus the `_human` (H, cum, hmean) this module attaches."""
    H = [(float(i * step), 0.0, 0.0) for i in range(n)]
    cum = [0.0]
    for a, b in zip(H, H[1:]):
        cum.append(cum[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
    goal = H[-1]
    hmean = 400.0
    edge = [float((n - 3) * step), 0.0, 0.0]
    land = [float((n - 1) * step), 0.0, 0.0]
    geom = gap = None
    if with_gap:
        geom = {"launch_edge": {"x": edge[0], "y": edge[1]},
                "required_launch_speed_qu_s": 525.0,
                "human_launch_speed_qu_s": 528.0,
                "void_floor_z": -392.0}
        gap = {"edge": edge, "land": land, "required_speed": 525.0}
    return {
        "name": "synthetic", "human": None, "start": (0.0, 0.0), "goal": goal,
        "tele_entrances": (), "geom": geom, "gap": gap, "native_dist": False,
        "_human": (H, cum, hmean),
    }


def _rows_along_route(route, *, frac=1.0, speed=400.0, dt=0.013, over_void=0):
    """FAKE rollout rows that traverse the route's straight +x human path covering the
    FIRST `frac` of its arc length at a constant ground `speed` (qu/s), stepping
    speed*dt qu per tick. Because time_weighted_speed derives speed from POSITION
    deltas / wall time (not the vh column), advancing speed*dt per tick makes the
    measured tws ~= `speed` and route% ~= 100*frac. over_void marks every row (0 =
    on ground). Assumes the straight +x route _straight_route builds."""
    H, cum, _ = route["_human"]
    goal = route["goal"]
    target_arc = cum[-1] * frac
    step_qu = speed * dt
    rows = []
    t = 0.0
    x = 0.0
    # always emit at least 2 rows so time_weighted_speed has a span.
    while True:
        t += dt
        rows.append(DR.make_row(t, (x, 0.0, 0.0), (speed, 0.0, 0.0),
                                onground=(over_void == 0), over_void=bool(over_void),
                                goal=goal))
        if x >= target_arc and len(rows) >= 2:
            break
        x += step_qu
    return rows


def _stall_rows(route, *, n=60):
    """FAKE stall rows: wedged at the start origin, zero velocity, for n ticks. route%
    and time_weighted_speed both collapse to ~0 -> the gate must FAIL."""
    H, _, _ = route["_human"]
    goal = route["goal"]
    sx, sy, sz = H[0]
    rows = []
    t = 0.0
    for _ in range(n):
        t += 0.013
        rows.append(DR.make_row(t, (sx, sy, sz), (0.0, 0.0, 0.0),
                                onground=True, over_void=False, goal=goal))
    return rows


def _stray_teleport_rows(route, *, legit_frac=0.10, late_frac=0.90,
                         speed=400.0, dt=0.013):
    """FAKE rows reproducing the teleport-consistency false PASS (Codex P1 on #309):

      (a) LEGIT phase  -- traverse the FIRST `legit_frac` of the straight +x human
          path at human `speed` (so this leg is fast: speed% ~100), then
      (b) STRAY teleport -- ONE single-frame origin jump > route_metrics.TELEPORT_JUMP
          (250 qu) that is NOT at any sanctioned tele_entrance (the synthetic route has
          tele_entrances=(), so any big jump is stray) landing the bot at the LATE human
          point `late_frac` along the path (near, but not at, the goal), then a couple
          of settled rows there.

    With the BUG (route% on the FULL stream) the late post-teleport rows snap to a
    late human vertex -> route% ~= 100*late_frac (~90), so route 90 + speed ~100 = a
    FALSE PASS. With the FIX (legit_segment ONCE, then route% on it) the stream is
    truncated at the stray teleport -> route% ~= 100*legit_frac (~10) -> FAIL. The jump
    distance (~0.8*cum) is far above 250 qu, and z is held at 0 so the jump is purely
    the xy hop route_metrics.legit_segment keys on."""
    H, cum, _ = route["_human"]
    goal = route["goal"]
    legit_arc = cum[-1] * legit_frac
    late_x = cum[-1] * late_frac          # straight +x route: arc == x
    step_qu = speed * dt
    rows = []
    t = 0.0
    x = 0.0
    # (a) legit leg: at least 2 rows so the pre-teleport segment has a time span.
    while True:
        t += dt
        rows.append(DR.make_row(t, (x, 0.0, 0.0), (speed, 0.0, 0.0),
                                onground=True, over_void=False, goal=goal))
        if x >= legit_arc and len(rows) >= 2:
            break
        x += step_qu
    # (b) ONE stray-teleport frame: origin jumps straight to the late human point.
    last_legit_x = rows[-1]["x"]
    assert (late_x - last_legit_x) > RM.TELEPORT_JUMP, "jump must exceed TELEPORT_JUMP"
    for _ in range(3):                    # land + settle on the late point (not goal)
        t += dt
        rows.append(DR.make_row(t, (late_x, 0.0, 0.0), (speed, 0.0, 0.0),
                                onground=True, over_void=False, goal=goal))
    return rows


class _FakeWorld:
    """A pmove_sim.WorldModel stand-in for over_void_at: its player_trace is monkey-
    patched at the module level (DR.PM.player_trace) in the test, so the world object
    itself is only an opaque token here."""


class _FakeTrace:
    def __init__(self, fraction):
        self.fraction = fraction


class _StubLogit:
    """Stands in for one head's logits tensor: .argmax(dim=1).item() returns a fixed
    class, so run_policy_rollout's `[int(lg.argmax(dim=1).item()) for lg in logits]`
    yields a deterministic head vector without torch."""
    def __init__(self, cls):
        self._cls = cls

    def argmax(self, dim=1):
        return self

    def item(self):
        return self._cls


class _StubModel:
    """A fake BroadBCPolicy: ignores its inputs and returns a fixed 5-head class vector
    (fwd/side/up/jump/attack) every forward. Used to drive run_policy_rollout's glue."""
    def __init__(self, head_classes):
        self._hc = list(head_classes)

    def __call__(self, obs_t, ent_t, em_t, aux_t):
        return [_StubLogit(c) for c in self._hc]


class _StubTorch:
    """Minimal torch surface run_policy_rollout uses: tensor/zeros/float32/no_grad."""
    float32 = "float32"

    @staticmethod
    def tensor(data, dtype=None, device=None):
        return data

    @staticmethod
    def zeros(shape, device=None):
        return [shape]

    class no_grad:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False


# --------------------------------------------------------------------------- #
# make_row
# --------------------------------------------------------------------------- #
class TestMakeRow(unittest.TestCase):
    def test_builds_expected_keys(self):
        r = DR.make_row(1.5, (100.0, 200.0, 24.0), (300.0, 400.0, 0.0),
                        onground=True, over_void=False, goal=(100.0, 200.0, 24.0))
        self.assertAlmostEqual(r["t"], 1.5)
        self.assertAlmostEqual(r["x"], 100.0)
        self.assertAlmostEqual(r["y"], 200.0)
        self.assertAlmostEqual(r["z"], 24.0)
        self.assertAlmostEqual(r["vh"], 500.0)         # hypot(300,400)
        self.assertEqual(r["onground"], 1)
        self.assertEqual(r["over_void"], 0)
        self.assertAlmostEqual(r["dist_goal"], 0.0)    # at the goal

    def test_dist_goal_is_3d(self):
        r = DR.make_row(0.0, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0),
                        onground=False, over_void=True, goal=(3.0, 0.0, 4.0))
        self.assertAlmostEqual(r["dist_goal"], 5.0)    # sqrt(3^2+4^2)
        self.assertEqual(r["over_void"], 1)
        self.assertEqual(r["onground"], 0)


# --------------------------------------------------------------------------- #
# over_void_at — straight-down trace classification
# --------------------------------------------------------------------------- #
class TestOverVoidAt(unittest.TestCase):
    def setUp(self):
        self._orig_trace = DR.PM.player_trace

    def tearDown(self):
        DR.PM.player_trace = self._orig_trace

    def test_fraction_full_is_over_void(self):
        # the down-trace reached the endpoint with no solid hit (fraction>=1) -> void.
        DR.PM.player_trace = lambda world, start, end: _FakeTrace(1.0)
        self.assertTrue(DR.over_void_at(_FakeWorld(), (0.0, 0.0, 100.0), -400.0))

    def test_fraction_partial_is_grounded(self):
        # the down-trace hit a solid floor partway (fraction<1) -> NOT over void.
        DR.PM.player_trace = lambda world, start, end: _FakeTrace(0.42)
        self.assertFalse(DR.over_void_at(_FakeWorld(), (0.0, 0.0, 100.0), -400.0))

    def test_floor_z_from_route(self):
        route = _straight_route(with_gap=True)
        # void_floor_z -392 minus the trace margin.
        self.assertAlmostEqual(DR.route_void_floor_z(route),
                               -392.0 - DR.VOID_TRACE_MARGIN)

    def test_floor_z_fallback_without_gap(self):
        route = _straight_route(with_gap=False)
        self.assertEqual(DR.route_void_floor_z(route), DR.VOID_TRACE_FLOOR_FALLBACK)


# --------------------------------------------------------------------------- #
# score_rows — the GATE logic (route% / speed% thresholds) + ungated diagnostics
# --------------------------------------------------------------------------- #
class TestScoreRowsGate(unittest.TestCase):
    def setUp(self):
        self.route = _straight_route(n=40, step=100.0, with_gap=True)
        self.human_rows = _rows_along_route(self.route, frac=1.0, speed=400.0)
        # human time_weighted_speed is the speed% denominator.
        import route_metrics as RM
        self.human_tws = RM.time_weighted_speed(
            self.human_rows, self.route["tele_entrances"], reach=DR.VR.REACH_RL)

    def test_full_fast_traversal_passes(self):
        # follows the whole path at human speed -> route% ~100, speed% ~100 -> PASS.
        res = DR.score_rows(self.human_rows, self.route, self.human_tws)
        self.assertGreaterEqual(res["route_pct"], 99.0)
        self.assertGreaterEqual(res["speed_pct"], 99.0)
        self.assertTrue(res["passed"])

    def test_short_traversal_fails_on_route_pct(self):
        # only the first 50% of the path -> route% ~50 < 80 -> FAIL even at full speed.
        rows = _rows_along_route(self.route, frac=0.5, speed=400.0)
        res = DR.score_rows(rows, self.route, self.human_tws)
        self.assertLess(res["route_pct"], 80.0)
        self.assertGreaterEqual(res["speed_pct"], 80.0)   # speed fine, route short
        self.assertFalse(res["passed"])

    def test_slow_traversal_fails_on_speed_pct(self):
        # full path but at half human speed -> speed% ~50 < 80 -> FAIL even at route 100.
        rows = _rows_along_route(self.route, frac=1.0, speed=200.0)
        res = DR.score_rows(rows, self.route, self.human_tws)
        self.assertGreaterEqual(res["route_pct"], 99.0)
        self.assertLess(res["speed_pct"], 80.0)
        self.assertFalse(res["passed"])

    def test_gate_is_route_and_speed_both(self):
        # exactly at the 80/80 corner passes; just under either fails. Build rows that
        # land route% ~85 and speed% ~85 -> PASS.
        rows = _rows_along_route(self.route, frac=0.86, speed=345.0)
        res = DR.score_rows(rows, self.route, self.human_tws)
        self.assertGreaterEqual(res["route_pct"], 80.0)
        self.assertGreaterEqual(res["speed_pct"], 80.0)
        self.assertTrue(res["passed"])

    def test_reached_rl_is_diagnostic_not_gate(self):
        # the human rows reach the goal -> REACHED_RL true, but the PASS does NOT
        # require it (PASS came from route%/speed%). Assert the diagnostic is present
        # and separate from `passed`.
        res = DR.score_rows(self.human_rows, self.route, self.human_tws)
        diag = res["diagnostics_not_gated"]
        self.assertIn("classify", diag)
        self.assertIn("reached_rl", diag)
        self.assertIn("launch_edge_speed_qu_per_s", diag)
        self.assertIn("launch_required_speed_qu_per_s", diag)
        # the gate field is route%/speed% only — reached_rl is not a gate input.
        self.assertEqual(res["gate"]["criterion"],
                         "route% >= 80 AND speed% >= 80 (time_weighted_speed)")

    def test_over_void_rows_excluded_from_route_pct(self):
        # rows that follow the path but are ALL over the void must NOT be credited for
        # route progress (route_progress refuses over-void ticks). route% -> 0.
        rows = _rows_along_route(self.route, frac=1.0, speed=400.0, over_void=1)
        res = DR.score_rows(rows, self.route, self.human_tws)
        self.assertEqual(res["route_pct"], 0.0)
        self.assertFalse(res["passed"])

    def test_speed_pct_uses_time_weighted_speed_denominator(self):
        # speed% is 100 * tws(rows) / human_tws; with rows == human rows it is ~100.
        res = DR.score_rows(self.human_rows, self.route, self.human_tws)
        self.assertAlmostEqual(res["speed_pct"], 100.0, delta=1.0)
        self.assertAlmostEqual(res["time_weighted_speed_qu_per_s"], self.human_tws,
                               delta=1.0)


# --------------------------------------------------------------------------- #
# Regression: teleport-consistency false PASS (Codex P1 on #309).
#
# score_rows must apply legit_segment ONCE and score route% AND speed% on the SAME
# legit segment. The bug computed route% on the FULL stream (which can include
# positions AFTER a STRAY teleporter near a late human point -> high route%) while
# time_weighted_speed truncated speed% at the first stray teleport (fast pre-teleport
# leg -> high speed%): a run that legitimately covered ~10% then stray-teleported to
# near the goal scored route ~90 / speed ~100 / passed=True -- a FALSE PASS. The fix
# scores both on the legit segment -> route ~10 -> FAIL. Mirrors verify_route.main().
# --------------------------------------------------------------------------- #
class TestStrayTeleportConsistency(unittest.TestCase):
    def setUp(self):
        self.route = _straight_route(n=40, step=100.0, with_gap=True)
        self.human_rows = _rows_along_route(self.route, frac=1.0, speed=400.0)
        self.human_tws = RM.time_weighted_speed(
            self.human_rows, self.route["tele_entrances"], reach=DR.VR.REACH_RL)

    def test_stray_teleport_to_late_point_fails_not_false_pass(self):
        # ~10% legit traversal, then a STRAY teleport to the 90% human point.
        rows = _stray_teleport_rows(self.route, legit_frac=0.10, late_frac=0.90,
                                    speed=400.0)

        # The BUG, reproduced: route% on the FULL stream is dominated by the late
        # post-teleport rows (snap to the ~90% human vertex) -> ~90, and on the SAME
        # full stream speed% ~100, so the OLD logic would have PASSED. We assert the
        # buggy inputs themselves to lock in that this stream is a real false-PASS trap.
        H, cum, _ = self.route["_human"]
        buggy_route_pct = DR.VR.route_progress(H, cum, rows)        # FULL stream
        self.assertGreaterEqual(buggy_route_pct, 85.0)             # Codex repro ~90
        self.assertLess(buggy_route_pct, 100.0)

        # The FIX: score_rows truncates at the stray teleport ONCE, so route% is the
        # legit ~10% and the gate FAILS (no false PASS).
        res = DR.score_rows(rows, self.route, self.human_tws)
        self.assertLessEqual(res["route_pct"], 20.0)              # fixed ~10
        self.assertFalse(res["passed"])
        # the legit pre-teleport leg is fast, so the FALSE pass was a route% lie, not a
        # speed% one: speed% stays high (this is exactly why route%/speed% must agree
        # on which segment is legit).
        self.assertGreaterEqual(res["speed_pct"], 80.0)

    def test_scored_metrics_share_one_legit_segment(self):
        # n_rows is the SCORED (legit) segment, strictly fewer than the full stream,
        # and the diagnostics (closest_rl) are on that legit segment too -- so they
        # never see the post-teleport landing near the goal.
        rows = _stray_teleport_rows(self.route, legit_frac=0.10, late_frac=0.90)
        res = DR.score_rows(rows, self.route, self.human_tws)
        self.assertEqual(res["n_rows_full"], len(rows))
        self.assertLess(res["n_rows"], res["n_rows_full"])        # truncated
        # closest_rl on the legit (~10%) segment is far from the goal: the stray
        # teleport landing near the goal must NOT leak into the diagnostics either.
        self.assertGreater(res["diagnostics_not_gated"]["closest_rl_qu"], 1000.0)

    def test_no_stray_teleport_is_a_noop(self):
        # control: the human path (no stray teleport) is unaffected by the guard --
        # legit_segment is a no-op, so route%/speed% PASS exactly as before, and the
        # scored segment equals the full stream.
        res = DR.score_rows(self.human_rows, self.route, self.human_tws)
        self.assertTrue(res["passed"])
        self.assertGreaterEqual(res["route_pct"], 99.0)
        self.assertEqual(res["n_rows"], res["n_rows_full"])


# --------------------------------------------------------------------------- #
# controls_bracket + the negative (stall) control via score_rows
# --------------------------------------------------------------------------- #
class TestControlsBracket(unittest.TestCase):
    def setUp(self):
        self.route = _straight_route()
        self.human_rows = _rows_along_route(self.route, frac=1.0, speed=400.0)
        import route_metrics as RM
        self.human_tws = RM.time_weighted_speed(
            self.human_rows, self.route["tele_entrances"], reach=DR.VR.REACH_RL)

    def test_human_passes_stall_fails_brackets(self):
        human = DR.score_rows(self.human_rows, self.route, self.human_tws)
        stall = DR.score_rows(_stall_rows(self.route), self.route, self.human_tws)
        self.assertTrue(human["passed"])
        self.assertFalse(stall["passed"])
        self.assertTrue(DR.controls_bracket(human, stall))

    def test_stall_route_and_speed_collapse(self):
        stall = DR.score_rows(_stall_rows(self.route), self.route, self.human_tws)
        self.assertEqual(stall["route_pct"], 0.0)
        self.assertEqual(stall["speed_pct"], 0.0)

    def test_bracket_rejects_human_fail(self):
        # if the positive control did NOT pass, the gate is invalid regardless of stall.
        bad_human = {"passed": False}
        stall = {"passed": False}
        self.assertFalse(DR.controls_bracket(bad_human, stall))

    def test_bracket_rejects_stall_pass(self):
        # if the stall (do-nothing) control PASSED, the gate is invalid.
        human = {"passed": True}
        leaky_stall = {"passed": True}
        self.assertFalse(DR.controls_bracket(human, leaky_stall))


# --------------------------------------------------------------------------- #
# run_policy_rollout glue — FAKE torch + FAKE world (no torch installed needed)
# --------------------------------------------------------------------------- #
class TestPolicyRolloutGlueFake(unittest.TestCase):
    """Exercise run_policy_rollout's pure glue (head argmax -> decode_move_heads ->
    Cmd -> sim step -> row) with a stub model + stub torch + a fake sim world, so the
    wiring is checked deps-free. The REAL forward is a pinnacle job."""

    def setUp(self):
        self._orig_trace = DR.PM.player_trace
        self._orig_pmove = DR.PM.Pmove
        self._orig_ps = DR.PM.PlayerState
        DR.PM.player_trace = lambda world, start, end: _FakeTrace(0.0)  # always grounded

        # a fake sim: each run_frame advances origin +x by a fixed step and sets a
        # nonzero velocity, so the rollout produces moving rows.
        rollout_self = self

        class _FakePlayerState:
            def __init__(self, origin, velocity):
                self.origin = list(origin)
                self.velocity = list(velocity)
                self.onground = True

        class _FakePmove:
            def __init__(self, world):
                self.world = world

            def run_frame(self, st, cmd):
                # move in the commanded forward direction at a fixed speed.
                fwd = cmd.move[0]
                st.origin[0] += (5.0 if fwd > 0 else 0.0)
                st.velocity = [fwd, cmd.move[1], 0.0]

        DR.PM.Pmove = _FakePmove
        DR.PM.PlayerState = _FakePlayerState

    def tearDown(self):
        DR.PM.player_trace = self._orig_trace
        DR.PM.Pmove = self._orig_pmove
        DR.PM.PlayerState = self._orig_ps

    def _frames(self, n=20):
        return [{"msec": 13, "origin": [0.0, 0.0, 0.0], "velocity": [0.0, 0.0, 0.0],
                 "angles": [0.0, 0.0, 0.0], "move": [0, 0, 0], "buttons": 0}
                for _ in range(n)]

    def test_rollout_produces_rows_and_attack(self):
        route = _straight_route()
        dims = {"f_ent": 0, "f_aux": 4, "n_max": 7}
        # head vector fwd=fwd(2) side=none(1) up=none(1) jump=no(0) attack=fire(1)
        model = _StubModel([2, 1, 1, 0, 1])
        # encode_obs stub: returns the minimal enc dict the rollout reads.
        enc = {"self": [0.0], "ents": [], "mask": []}
        rows, atk = DR.run_policy_rollout(
            self._frames(20), _FakeWorld(), route, model=model, dims=dims,
            encode_obs=lambda *a, **k: enc, stats={}, torch_mod=_StubTorch(),
            map_name="dm3", n_max=7, device="cpu")
        # one fewer row than frames (frame[k] view onto bot state), all moved +x.
        self.assertEqual(len(rows), 19)
        self.assertGreater(rows[-1]["x"], rows[0]["x"])    # forward move accumulated
        self.assertEqual(atk, [1] * 19)                    # predicted attack class logged
        for r in rows:
            self.assertIn("dist_goal", r)
            self.assertEqual(r["over_void"], 0)            # fake trace -> grounded


# --------------------------------------------------------------------------- #
# auto_seed_from_human — the cold-start sustain-diagnostic seed picker (pure)
# --------------------------------------------------------------------------- #
class TestAutoSeedFromHuman(unittest.TestCase):
    @staticmethod
    def _frame(vx, vy, vz=0.0):
        return {"msec": 13, "origin": [0.0, 0.0, 0.0], "velocity": [vx, vy, vz],
                "angles": [0.0, 0.0, 0.0], "move": [0, 0, 0], "buttons": 0}

    def test_returns_first_fast_frame_velocity(self):
        # frames ramp up; the FIRST with hspeed >= 200 is the one whose velocity is
        # returned (world-frame 3-vector, unrotated).
        frames = [self._frame(0.0, 0.0), self._frame(100.0, 0.0),   # hspeed 0, 100 < 200
                  self._frame(300.0, 400.0, 5.0),                    # hspeed 500 -> picked
                  self._frame(600.0, 0.0)]
        seed = DR.auto_seed_from_human(frames)
        self.assertEqual(seed, [300.0, 400.0, 5.0])
        self.assertIsInstance(seed, list)

    def test_threshold_is_horizontal_only(self):
        # a big vertical (vz) with slow horizontal does NOT qualify; the next frame's
        # horizontal speed crossing 200 does.
        frames = [self._frame(10.0, 10.0, 900.0),                   # hspeed ~14 < 200
                  self._frame(0.0, 250.0)]                          # hspeed 250 -> picked
        self.assertEqual(DR.auto_seed_from_human(frames), [0.0, 250.0, 0.0])

    def test_respects_min_hspeed_override(self):
        frames = [self._frame(150.0, 0.0), self._frame(220.0, 0.0)]
        # default 200 picks the 220 frame; a 100 floor picks the 150 frame.
        self.assertEqual(DR.auto_seed_from_human(frames), [220.0, 0.0, 0.0])
        self.assertEqual(DR.auto_seed_from_human(frames, min_hspeed=100.0),
                         [150.0, 0.0, 0.0])

    def test_none_when_all_frames_slow(self):
        # every frame below the floor -> None (caller falls back to no seed).
        frames = [self._frame(0.0, 0.0), self._frame(100.0, 100.0)]  # hspeed ~141 < 200
        self.assertIsNone(DR.auto_seed_from_human(frames))

    def test_first_frame_at_exact_threshold_qualifies(self):
        # hypot(200,0) == 200 == min_hspeed -> qualifies (>=).
        frames = [self._frame(200.0, 0.0)]
        self.assertEqual(DR.auto_seed_from_human(frames), [200.0, 0.0, 0.0])


# --------------------------------------------------------------------------- #
# seed_velocity seam — run_policy_rollout initializes the sim at the seed (tick 0)
# --------------------------------------------------------------------------- #
class TestSeedVelocitySeam(unittest.TestCase):
    """The cold-start sustain diagnostic seeds the POLICY rollout's PlayerState with a
    world-frame velocity at tick 0 (instead of the human frame-0 velocity). We capture
    the velocity PlayerState is constructed with — the unrotated seed must reach the sim
    init before any frame is stepped. Deps-free (stub torch + a recording fake sim)."""

    def setUp(self):
        self._orig_trace = DR.PM.player_trace
        self._orig_pmove = DR.PM.Pmove
        self._orig_ps = DR.PM.PlayerState
        DR.PM.player_trace = lambda world, start, end: _FakeTrace(0.0)  # grounded
        rec = self
        self.init_velocities = []

        class _RecordingPlayerState:
            def __init__(self, origin, velocity):
                self.origin = list(origin)
                self.velocity = list(velocity)
                self.onground = True
                rec.init_velocities.append(list(velocity))   # capture the seed at init

        class _NoMutateVelPmove:
            # advances origin +x but LEAVES st.velocity untouched, so the captured
            # rows[0] velocity is the init (seed) velocity, pre-policy-mutation.
            def __init__(self, world):
                self.world = world

            def run_frame(self, st, cmd):
                st.origin[0] += 5.0

        DR.PM.Pmove = _NoMutateVelPmove
        DR.PM.PlayerState = _RecordingPlayerState

    def tearDown(self):
        DR.PM.player_trace = self._orig_trace
        DR.PM.Pmove = self._orig_pmove
        DR.PM.PlayerState = self._orig_ps

    def _frames(self, n=8):
        # human frame-0 velocity is a DISTINCT marker (1,2,3) so a seed override is
        # unambiguous vs the no-seed fallback.
        return [{"msec": 13, "origin": [0.0, 0.0, 0.0], "velocity": [1.0, 2.0, 3.0],
                 "angles": [0.0, 0.0, 0.0], "move": [0, 0, 0], "buttons": 0}
                for _ in range(n)]

    def _run(self, seed):
        route = _straight_route()
        dims = {"f_ent": 0, "f_aux": 4, "n_max": 7}
        model = _StubModel([2, 1, 1, 0, 0])     # fwd>0, no jump, no attack
        enc = {"self": [0.0], "ents": [], "mask": []}
        return DR.run_policy_rollout(
            self._frames(8), _FakeWorld(), route, model=model, dims=dims,
            encode_obs=lambda *a, **k: enc, stats={}, torch_mod=_StubTorch(),
            map_name="dm3", n_max=7, device="cpu", seed_velocity=seed)

    def test_seed_velocity_sets_player_state_at_tick0(self):
        rows, _ = self._run([300.0, 400.0, 0.0])
        # the PlayerState was constructed with the SEED, not the human frame-0 velocity.
        self.assertEqual(self.init_velocities[0], [300.0, 400.0, 0.0])
        # and (since the fake sim does not mutate velocity) the first captured row's
        # horizontal speed reflects the seed at tick 0.
        self.assertAlmostEqual(rows[0]["vh"], math.hypot(300.0, 400.0))   # 500

    def test_seed_velocity_world_frame_not_rotated(self):
        # the seed is passed through verbatim (world-frame); no yaw rotation is applied.
        self._run([-123.0, 456.0, 7.0])
        self.assertEqual(self.init_velocities[0], [-123.0, 456.0, 7.0])

    def test_no_seed_falls_back_to_human_frame0_velocity(self):
        # seed_velocity=None (default) -> PlayerState keeps the human frame-0 velocity.
        rows, _ = self._run(None)
        self.assertEqual(self.init_velocities[0], [1.0, 2.0, 3.0])

    def test_seed_does_not_touch_stall_or_human_controls(self):
        # the stall + human-path control row builders take NO seed argument (the gate
        # controls must keep their recorded/zero start). Guard the signatures so a future
        # edit can't accidentally thread a seed into a control.
        import inspect
        for fn in (DR.stall_rows, DR.human_rows_from_cmds):
            params = set(inspect.signature(fn).parameters)
            self.assertNotIn("seed_velocity", params, fn.__name__)


# --------------------------------------------------------------------------- #
# build_report — records the cold-start seed + mode in inputs (change #5)
# --------------------------------------------------------------------------- #
class TestBuildReportSeed(unittest.TestCase):
    def setUp(self):
        self.route = _straight_route()
        self.human = {"passed": True}
        self.stall = {"passed": False}
        self.base_inputs = {"route": "synthetic", "controls_only": False}

    def _report(self, **kw):
        return DR.build_report(
            "synthetic", self.route, human_result=self.human, stall_result=self.stall,
            policy_result={"passed": False}, human_tws=400.0, agreement={},
            inputs=dict(self.base_inputs), provenance={}, **kw)

    def test_explicit_seed_recorded_rounded(self):
        rep = self._report(seed=[300.04, 400.06, 0.0], seed_mode="explicit")
        self.assertEqual(rep["inputs"]["seed_velocity"], [300.0, 400.1, 0.0])
        self.assertEqual(rep["inputs"]["seed_mode"], "explicit")

    def test_no_seed_defaults_to_none_mode(self):
        # default (controls-only / unseeded) -> seed_velocity None, seed_mode "none".
        rep = self._report()
        self.assertIsNone(rep["inputs"]["seed_velocity"])
        self.assertEqual(rep["inputs"]["seed_mode"], "none")

    def test_from_human_mode_recorded(self):
        rep = self._report(seed=[0.0, 250.0, 0.0], seed_mode="from_human")
        self.assertEqual(rep["inputs"]["seed_velocity"], [0.0, 250.0, 0.0])
        self.assertEqual(rep["inputs"]["seed_mode"], "from_human")

    def test_seed_plumbing_does_not_disturb_controls_bracket(self):
        # the seed only annotates inputs; the bracket verdict is still human PASS ^ stall
        # FAIL, independent of seeding.
        rep = self._report(seed=[300.0, 400.0, 0.0], seed_mode="explicit")
        self.assertTrue(rep["controls"]["bracket_valid"])
        self.assertEqual(rep["controls"]["human_path_positive"], self.human)
        self.assertEqual(rep["controls"]["stall_negative"], self.stall)


# --------------------------------------------------------------------------- #
# ACTION-TRACE — the per-tick POLICY-vs-HUMAN diagnostic (pure glue).
#
#   * _wrap180 / make_trace_row — the per-tick row + its angle derivations
#     (yaw_rate across the +-180 seam, vel_heading, face_vel_angle).
#   * analyze_action_trace      — UNDER-PRODUCTION vs WRONG-SIGN separation: side-sign
#     agreement (airborne, human-strafing only), production fractions, jump cadence,
#     and the airborne-speed outcome. Driven by hand-built synthetic traces.
#   * write/load_trace_csv       — CSV round-trip preserves the analysis (so the runner
#     can analyze a CSV produced on pinnacle).
# --------------------------------------------------------------------------- #
def _trace_row(*, onground=False, yaw=0.0, yaw_prev=0.0, msec=13, vx=0.0, vy=0.0,
               pol_fwd=0.0, pol_side=0.0, pol_up=0.0, pol_jump=0,
               hum_fwd=0.0, hum_side=0.0, hum_jump=0, hum_vh=0.0, t=0.0):
    """Thin keyword wrapper over DR.make_trace_row for terse synthetic traces."""
    return DR.make_trace_row(
        t, onground=onground, yaw=yaw, yaw_prev=yaw_prev, msec=msec, vx=vx, vy=vy,
        pol_fwd=pol_fwd, pol_side=pol_side, pol_up=pol_up, pol_jump=pol_jump,
        hum_fwd=hum_fwd, hum_side=hum_side, hum_jump=hum_jump, hum_vh=hum_vh)


class TestWrap180(unittest.TestCase):
    def test_wraps_into_half_open_180(self):
        self.assertAlmostEqual(DR._wrap180(190.0), -170.0)
        self.assertAlmostEqual(DR._wrap180(-190.0), 170.0)
        self.assertAlmostEqual(DR._wrap180(0.0), 0.0)
        self.assertAlmostEqual(DR._wrap180(45.0), 45.0)

    def test_boundary_180_maps_to_positive_180(self):
        # convention: the half-open wrap keeps +-180 as +180 (not -180).
        self.assertAlmostEqual(DR._wrap180(180.0), 180.0)
        self.assertAlmostEqual(DR._wrap180(-180.0), 180.0)

    def test_large_multiples_wrap(self):
        self.assertAlmostEqual(DR._wrap180(360.0 + 30.0), 30.0)
        self.assertAlmostEqual(DR._wrap180(-720.0 - 10.0), -10.0)


class TestMakeTraceRow(unittest.TestCase):
    def test_columns_and_basic_values(self):
        r = _trace_row(onground=True, yaw=10.0, yaw_prev=10.0, vx=300.0, vy=400.0,
                       pol_fwd=400.0, pol_side=-400.0, pol_up=0.0, pol_jump=2,
                       hum_fwd=508, hum_side=-508, hum_jump=1, hum_vh=520.0)
        # every TRACE_COLUMNS key present, in the row.
        for k in DR.TRACE_COLUMNS:
            self.assertIn(k, r)
        self.assertEqual(r["onground"], 1)
        self.assertAlmostEqual(r["vh"], 500.0)            # hypot(300,400)
        self.assertEqual(r["pol_jump"], 1)                # nonzero jump bit -> 1
        self.assertEqual(r["hum_jump"], 1)
        self.assertAlmostEqual(r["hum_vh"], 520.0)
        self.assertAlmostEqual(r["pol_side"], -400.0)
        self.assertAlmostEqual(r["hum_side"], -508.0)

    def test_yaw_rate_wraps_across_seam(self):
        # yaw 350 -> 10 over 10 ms is a +20 deg turn (not -340): +20/0.01 = 2000 deg/s.
        r = _trace_row(yaw=10.0, yaw_prev=350.0, msec=10)
        self.assertAlmostEqual(r["yaw_rate"], 2000.0)

    def test_first_row_yaw_rate_zero_by_convention(self):
        # yaw_prev == yaw (caller seeds yaw_prev = frame0 yaw for tick 0) -> rate 0.
        r = _trace_row(yaw=42.0, yaw_prev=42.0, msec=13)
        self.assertAlmostEqual(r["yaw_rate"], 0.0)

    def test_face_vel_angle_is_yaw_minus_velocity_heading(self):
        # facing yaw 90, moving +x (heading 0) at 300 qu/s (>= 80 floor) -> 90 deg off.
        r = _trace_row(yaw=90.0, yaw_prev=90.0, vx=300.0, vy=0.0)
        self.assertAlmostEqual(r["vel_heading"], 0.0)
        self.assertAlmostEqual(r["face_vel_angle"], 90.0)

    def test_zero_velocity_heading_and_face_angle_zero_below_floor(self):
        # vh == 0 is below the 80 qu/s floor -> vel_heading AND face_vel_angle both 0
        # (mirrors agent_observation.self_features: zeroed heading sincos + face angle 0;
        # no NaN/atan2(0,0)). NOTE the v3 floor semantics: below the floor vel_heading
        # reads 0 (not the yaw) so the trace matches what the obs scored.
        r = _trace_row(yaw=45.0, yaw_prev=45.0, vx=0.0, vy=0.0)
        self.assertAlmostEqual(r["vel_heading"], 0.0)
        self.assertAlmostEqual(r["face_vel_angle"], 0.0)

    def test_velocity_heading_floor_matches_agent_observation(self):
        # the trace's floor MUST be the SAME constant agent_observation.self_features
        # uses (reused, not re-hardcoded) so train and trace cannot drift.
        self.assertEqual(DR._VEL_HEADING_FLOOR, AO._VEL_HEADING_FLOOR)
        self.assertEqual(DR._VEL_HEADING_FLOOR, 80.0)

    def test_slow_band_below_floor_zeroes_heading_and_face_angle(self):
        """REGRESSION for the P2 floor-mismatch finding: in the 0 < vh < 80 cold-start/
        bleed band, make_trace_row's vel_heading AND face_vel_angle must read 0 — exactly
        what agent_observation.self_features emits there (vel_heading sincos = 0,
        face_vel_angle_norm = 0). Before the fix the trace reported a NONZERO look-vs-move
        angle on these slow ticks, mis-explaining the very low-speed behavior it diagnoses.
        We assert BOTH directly and against what self_features would produce on the SAME
        kinematics, so the parity is checked end-to-end (not just to a magic number)."""
        # a tick squarely inside the band: hspeed = hypot(40, 30) = 50 qu/s (< 80), and
        # the facing (yaw 90) is well off the travel direction (heading atan2(30,40)~36.9).
        vx, vy, yaw = 40.0, 30.0, 90.0
        self.assertLess(math.hypot(vx, vy), DR._VEL_HEADING_FLOOR)
        r = _trace_row(yaw=yaw, yaw_prev=yaw, vx=vx, vy=vy)
        self.assertAlmostEqual(r["vel_heading"], 0.0)
        self.assertAlmostEqual(r["face_vel_angle"], 0.0)
        self.assertAlmostEqual(r["vh"], 50.0)            # vh itself still reported

        # PARITY: self_features on the SAME kinematics emits a zeroed velocity-heading
        # sincos AND face_vel_angle_norm = 0 (the last appended SELF channel). The trace
        # must agree with that, which is the whole point of mirroring the floor.
        stats = _floor_parity_stats()
        sf = AO.self_features(
            {"ox": 0.0, "oy": 0.0, "oz": 0.0, "vx": vx, "vy": vy, "vz": 0.0,
             "yaw": yaw, "pitch": 0.0, "onground": False, "health": 100, "armor": 0,
             "yaw_rate": 0.0}, stats, "dm3")
        # SELF layout: ... vh_sin(7) vh_cos(8) ... face_vel_angle_norm(17, last)
        self.assertAlmostEqual(sf[7], 0.0)               # vel_heading_sin zeroed
        self.assertAlmostEqual(sf[8], 0.0)               # vel_heading_cos zeroed
        self.assertAlmostEqual(sf[AO.SELF_DIM - 1], 0.0)  # face_vel_angle_norm zeroed

    def test_at_floor_is_active_band(self):
        # exactly AT the floor (vh == 80) the heading IS defined (>= floor, mirroring
        # self_features' `hspeed >= _VEL_HEADING_FLOOR`), so face_vel_angle is nonzero.
        r = _trace_row(yaw=90.0, yaw_prev=90.0, vx=80.0, vy=0.0)
        self.assertAlmostEqual(r["vh"], 80.0)
        self.assertAlmostEqual(r["vel_heading"], 0.0)    # moving +x
        self.assertAlmostEqual(r["face_vel_angle"], 90.0)  # defined at the floor


class TestAnalyzeActionTrace(unittest.TestCase):
    def _matched_air_trace(self, n=12, jump_every=3):
        # AIRBORNE trace where the policy strafes the SAME way as the human (+side),
        # holds forward, and re-jumps on the same cadence. pol speed 300 < hum 500.
        rows = []
        t = 0.0
        for i in range(n):
            t += 0.013
            j = 1 if (i % jump_every == 0) else 0
            rows.append(_trace_row(
                t=t, onground=False, yaw=10.0, yaw_prev=10.0, msec=13, vx=300.0, vy=0.0,
                pol_fwd=400.0, pol_side=400.0, pol_up=0.0, pol_jump=(2 if j else 0),
                hum_fwd=508, hum_side=508, hum_jump=j, hum_vh=500.0))
        return rows

    def test_perfect_match_scores_side_sign_one(self):
        a = DR.analyze_action_trace(self._matched_air_trace())
        self.assertAlmostEqual(a["side_sign_match_vs_human"], 1.0)
        self.assertEqual(a["n_airborne_ticks"], a["n_ticks"])         # all airborne
        self.assertGreater(a["n_airborne_human_strafe_ticks"], 0)

    def test_outcome_speed_pol_vs_hum_distinct(self):
        # the OUTCOME the trace explains: pol airborne speed (300) below human (500).
        a = DR.analyze_action_trace(self._matched_air_trace())
        self.assertAlmostEqual(a["mean_airborne_vh_pol"], 300.0)
        self.assertAlmostEqual(a["mean_airborne_vh_hum"], 500.0)

    def test_production_fractions_full_when_policy_active(self):
        a = DR.analyze_action_trace(self._matched_air_trace())
        self.assertAlmostEqual(a["pol_side_active_frac"], 1.0)
        self.assertAlmostEqual(a["hum_side_active_frac"], 1.0)
        self.assertAlmostEqual(a["pol_fwd_press_frac"], 1.0)
        self.assertAlmostEqual(a["hum_fwd_press_frac"], 1.0)

    def test_jump_cadence_matches_human(self):
        # same jump pattern on both sides -> equal per-second cadence and press fraction.
        a = DR.analyze_action_trace(self._matched_air_trace(n=12, jump_every=3))
        self.assertGreater(a["pol_jump_per_s"], 0.0)
        self.assertAlmostEqual(a["pol_jump_per_s"], a["hum_jump_per_s"])
        self.assertAlmostEqual(a["pol_jump_press_frac"], a["hum_jump_press_frac"])

    def test_all_idle_policy_scores_low_production(self):
        # the UNDER-PRODUCTION signature: policy presses NOTHING while the human strafes,
        # holds forward and jumps every tick. Fractions/cadence collapse to 0; and with
        # zero policy strafing the side-sign match is 0 (no agreeing ticks).
        rows = []
        t = 0.0
        for _ in range(10):
            t += 0.013
            rows.append(_trace_row(
                t=t, onground=False, yaw=10.0, yaw_prev=10.0, msec=13, vx=120.0, vy=0.0,
                pol_fwd=0.0, pol_side=0.0, pol_up=0.0, pol_jump=0,
                hum_fwd=508, hum_side=508, hum_jump=1, hum_vh=500.0))
        a = DR.analyze_action_trace(rows)
        self.assertAlmostEqual(a["pol_side_active_frac"], 0.0)
        self.assertAlmostEqual(a["pol_fwd_press_frac"], 0.0)
        self.assertAlmostEqual(a["pol_jump_per_s"], 0.0)
        self.assertAlmostEqual(a["side_sign_match_vs_human"], 0.0)
        # the human side is the reference: it WAS strafing the whole time.
        self.assertAlmostEqual(a["hum_side_active_frac"], 1.0)

    def test_wrong_sign_distinct_from_under_production(self):
        # the WRONG-SIGN signature: policy strafes EVERY tick (high active frac) but
        # always the OPPOSITE way to the human -> side_sign_match 0 with active frac 1.0.
        # This must be distinguishable from the all-idle case (active frac 0).
        rows = []
        t = 0.0
        for _ in range(10):
            t += 0.013
            rows.append(_trace_row(
                t=t, onground=False, yaw=10.0, yaw_prev=10.0, msec=13, vx=200.0, vy=0.0,
                pol_fwd=400.0, pol_side=-400.0, pol_up=0.0, pol_jump=0,   # opposite sign
                hum_fwd=508, hum_side=508, hum_jump=0, hum_vh=500.0))
        a = DR.analyze_action_trace(rows)
        self.assertAlmostEqual(a["pol_side_active_frac"], 1.0)            # strafing a lot
        self.assertAlmostEqual(a["side_sign_match_vs_human"], 0.0)       # but wrong way
        self.assertAlmostEqual(a["pol_side_active_frac_air"], 1.0)

    def test_side_sign_match_is_airborne_and_human_strafing_only(self):
        # GROUNDED ticks and ticks where the human did NOT strafe are excluded from the
        # side-sign denominator. Build: 2 grounded (ignored), 2 airborne hum-not-strafing
        # (ignored), 2 airborne hum-strafing with pol matching (the only counted ticks).
        rows = [
            _trace_row(onground=True, hum_side=508, pol_side=-400.0),     # grounded: skip
            _trace_row(onground=True, hum_side=508, pol_side=-400.0),     # grounded: skip
            _trace_row(onground=False, hum_side=0, pol_side=400.0),       # hum not strafing
            _trace_row(onground=False, hum_side=0, pol_side=-400.0),      # hum not strafing
            _trace_row(onground=False, hum_side=508, pol_side=400.0),     # counted: match
            _trace_row(onground=False, hum_side=508, pol_side=400.0),     # counted: match
        ]
        a = DR.analyze_action_trace(rows)
        self.assertEqual(a["n_airborne_human_strafe_ticks"], 2)          # only the last 2
        self.assertAlmostEqual(a["side_sign_match_vs_human"], 1.0)       # both matched

    def test_partial_side_sign_match_fraction(self):
        # 4 airborne human-strafing ticks, policy matches 3 of 4 -> 0.75.
        rows = [
            _trace_row(onground=False, hum_side=508, pol_side=400.0),     # match
            _trace_row(onground=False, hum_side=508, pol_side=400.0),     # match
            _trace_row(onground=False, hum_side=508, pol_side=400.0),     # match
            _trace_row(onground=False, hum_side=508, pol_side=-400.0),    # mismatch
        ]
        a = DR.analyze_action_trace(rows)
        self.assertAlmostEqual(a["side_sign_match_vs_human"], 0.75)

    def test_empty_trace_is_all_zero(self):
        # deps-free safety: an empty trace returns zeros (no division by zero).
        a = DR.analyze_action_trace([])
        self.assertEqual(a["n_ticks"], 0)
        self.assertEqual(a["n_airborne_ticks"], 0)
        self.assertEqual(a["side_sign_match_vs_human"], 0.0)
        self.assertEqual(a["pol_jump_per_s"], 0.0)
        self.assertEqual(a["mean_airborne_vh_pol"], 0.0)

    def test_all_grounded_airborne_means_zero(self):
        # no airborne ticks -> airborne denominators 0, side-sign 0, but grounded
        # production fractions still computed over ALL ticks.
        rows = [_trace_row(onground=True, hum_side=508, pol_side=400.0, pol_fwd=400.0)
                for _ in range(5)]
        a = DR.analyze_action_trace(rows)
        self.assertEqual(a["n_airborne_ticks"], 0)
        self.assertEqual(a["mean_airborne_vh_pol"], 0.0)
        self.assertEqual(a["side_sign_match_vs_human"], 0.0)
        self.assertAlmostEqual(a["pol_fwd_press_frac"], 1.0)             # over all ticks


class TestTraceCsvRoundTrip(unittest.TestCase):
    def _trace(self, n=8):
        rows = []
        t = 0.0
        for i in range(n):
            t += 0.013
            rows.append(_trace_row(
                t=t, onground=(i % 2 == 0), yaw=10.0 + i, yaw_prev=10.0 + i, msec=13,
                vx=300.0, vy=40.0, pol_fwd=400.0, pol_side=(400.0 if i % 2 else -400.0),
                pol_up=0.0, pol_jump=(2 if i % 3 == 0 else 0),
                hum_fwd=508, hum_side=508, hum_jump=(1 if i % 3 == 0 else 0), hum_vh=480.0))
        return rows

    def test_write_then_load_preserves_analysis(self):
        import tempfile
        rows = self._trace()
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "trace.csv"
            DR.write_trace_csv(rows, p)
            self.assertTrue(p.exists())
            back = DR.load_trace_csv(p)
        self.assertEqual(len(back), len(rows))
        # the analysis on the reloaded CSV equals the analysis on the in-memory rows.
        self.assertEqual(DR.analyze_action_trace(back), DR.analyze_action_trace(rows))

    def test_csv_header_is_trace_columns(self):
        import csv as _csv
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "trace.csv"
            DR.write_trace_csv(self._trace(3), p)
            with p.open() as fh:
                header = next(_csv.reader(fh))
        self.assertEqual(header, DR.TRACE_COLUMNS)


class TestPolicyRolloutTraceOut(unittest.TestCase):
    """run_policy_rollout's trace_out seam: when a list is passed, one trace row per tick
    is appended (policy decode + human usercmd from frames[k]); when None, the rollout is
    unchanged (no trace). Deps-free (stub torch + recording fake sim)."""

    def setUp(self):
        self._orig_trace = DR.PM.player_trace
        self._orig_pmove = DR.PM.Pmove
        self._orig_ps = DR.PM.PlayerState
        DR.PM.player_trace = lambda world, start, end: _FakeTrace(0.0)  # grounded

        class _FakePlayerState:
            def __init__(self, origin, velocity):
                self.origin = list(origin)
                self.velocity = list(velocity)
                self.onground = True

        class _FakePmove:
            def __init__(self, world):
                self.world = world

            def run_frame(self, st, cmd):
                # set a deterministic post-frame velocity from the commanded move so the
                # trace's vh column is the policy's outcome.
                st.origin[0] += 5.0
                st.velocity = [float(cmd.move[0]), float(cmd.move[1]), 0.0]
                st.onground = False                         # airborne so trace counts it

        DR.PM.Pmove = _FakePmove
        DR.PM.PlayerState = _FakePlayerState

    def tearDown(self):
        DR.PM.player_trace = self._orig_trace
        DR.PM.Pmove = self._orig_pmove
        DR.PM.PlayerState = self._orig_ps

    def _frames(self, n=10):
        # human strafes +side (508), holds forward, jumps (buttons & BUTTON_JUMP == 2),
        # and has a recorded speed; angles carry the replayed yaw.
        return [{"msec": 13, "origin": [0.0, 0.0, 0.0], "velocity": [300.0, 0.0, 0.0],
                 "angles": [0.0, 10.0, 0.0], "move": [508, 508, 0], "buttons": 2}
                for _ in range(n)]

    def _run(self, trace_out):
        route = _straight_route()
        dims = {"f_ent": 0, "f_aux": 4, "n_max": 7}
        # policy decode: fwd>0(2) side>0(2) up none(1) jump yes(1) attack no(0).
        model = _StubModel([2, 2, 1, 1, 0])
        enc = {"self": [0.0], "ents": [], "mask": []}
        return DR.run_policy_rollout(
            self._frames(10), _FakeWorld(), route, model=model, dims=dims,
            encode_obs=lambda *a, **k: enc, stats={}, torch_mod=_StubTorch(),
            map_name="dm3", n_max=7, device="cpu", trace_out=trace_out)

    def test_trace_out_collects_one_row_per_tick(self):
        trace = []
        rows, _atk = self._run(trace)
        # one fewer than frames (frame[k] view onto bot state) — matches the scorer rows.
        self.assertEqual(len(trace), len(rows))
        self.assertEqual(len(trace), 9)
        for r in trace:
            for k in DR.TRACE_COLUMNS:
                self.assertIn(k, r)

    def test_trace_captures_policy_decode_and_human_usercmd(self):
        trace = []
        self._run(trace)
        r = trace[0]
        # policy decoded fwd>0 and side>0 to +MOVE_MAG, jump head 1 -> jump bit set.
        self.assertAlmostEqual(r["pol_fwd"], DR.CL.MOVE_MAG)
        self.assertAlmostEqual(r["pol_side"], DR.CL.MOVE_MAG)
        self.assertEqual(r["pol_jump"], 1)
        # human usercmd straight from frames[k]: side 508, jump bit (buttons&2 -> 1).
        self.assertAlmostEqual(r["hum_fwd"], 508.0)
        self.assertAlmostEqual(r["hum_side"], 508.0)
        self.assertEqual(r["hum_jump"], 1)
        self.assertAlmostEqual(r["hum_vh"], 300.0)         # hypot(300,0) recorded speed

    def test_trace_analysis_sees_matching_strafe(self):
        # policy strafes +side, human strafes +side, both airborne -> side_sign_match 1.0.
        trace = []
        self._run(trace)
        a = DR.analyze_action_trace(trace)
        self.assertAlmostEqual(a["side_sign_match_vs_human"], 1.0)
        self.assertEqual(a["n_airborne_ticks"], len(trace))    # fake sim is airborne
        self.assertAlmostEqual(a["pol_jump_press_frac"], 1.0)  # jump head 1 every tick

    def test_none_trace_out_is_noop(self):
        # the default (no trace_out) leaves the rollout unchanged: rows + attack only,
        # and nothing raised for the missing collector.
        rows, atk = self._run(None)
        self.assertEqual(len(rows), 9)
        self.assertEqual(len(atk), 9)


@unittest.skipUnless(_HAVE_TORCH, "run_eval needs torch + a real BSP (pinnacle GPU host)")
class TestRunEvalGated(unittest.TestCase):
    """End-to-end is exercised on pinnacle with a real checkpoint + dm3.bsp; here only
    assert the entrypoints exist."""

    def test_entrypoints_callable(self):
        self.assertTrue(callable(DR.run_eval))
        self.assertTrue(callable(DR.run_controls_only))


class TestModuleImportsDepsFree(unittest.TestCase):
    """Guard: the module + its glue import on bare stdlib (no torch/numpy/duckdb)."""

    def test_glue_importable(self):
        for fn in ("make_row", "score_rows", "over_void_at", "route_void_floor_z",
                   "controls_bracket", "stall_rows", "human_rows_from_cmds",
                   "auto_seed_from_human",
                   "make_trace_row", "analyze_action_trace", "write_trace_csv",
                   "load_trace_csv", "print_action_trace_summary", "main_analyze",
                   "run_policy_rollout", "run_controls_only", "run_eval",
                   "load_route_with_human", "build_report"):
            self.assertTrue(callable(getattr(DR, fn)), fn)
        self.assertEqual(DR.GATE_ROUTE_PCT, 80.0)
        self.assertEqual(DR.GATE_SPEED_PCT, 80.0)


if __name__ == "__main__":
    unittest.main()
