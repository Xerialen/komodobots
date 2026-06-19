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

_HAVE_TORCH = importlib.util.find_spec("torch") is not None


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
                   "run_policy_rollout", "run_controls_only", "run_eval",
                   "load_route_with_human", "build_report"):
            self.assertTrue(callable(getattr(DR, fn)), fn)
        self.assertEqual(DR.GATE_ROUTE_PCT, 80.0)
        self.assertEqual(DR.GATE_SPEED_PCT, 80.0)


if __name__ == "__main__":
    unittest.main()
