"""tests/test_route_eval.py — gated (stdlib-only) tests for the T5.2 route-isolated eval harness
(experiments/route_observatory/route_eval.py, #428). Synthetic fixtures: NO MVD, NO qw-analyze
subprocess, NO torch/duckdb -- runs in the merge-gating `python -m unittest discover -s tests` floor.

Covers the plan's Verification §1:
  * pin_driven_highway: an attempt hugging base highway K -> pins K with margin; an equidistant
    attempt -> ambiguous; an off-all-highways attempt -> off_all + WARN.
  * parse_engaged_window: ENGAGED->DISENGAGED transitions -> the right frame window; per-slot
    filtering; none -> a clear error.
  * extract_attempt_trajectory: a synthetic qw-analyze JSON -> the correct qu [[t,x,y,z]] slice,
    window-clipped; the auto-pick-mover default; an unknown player errors.
  * route_eval assembly: evaluate_analysis -> a valid route_eval.v1 (adherence + velocity +
    degenerate); a stalled attempt -> degenerate=true; and evaluate_run on a stub run dir
    (qw-analyze stubbed) -> route_eval.json + a correctly-merged ledger row.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "experiments" / "route_observatory"))

import route_eval as RE   # noqa: E402


# --- fixtures -----------------------------------------------------------------------------------
def _seg(xyz_pts, t0=0.0, dt=0.1):
    """[(x,y,z),...] -> [[t,x,y,z],...] with uniform timestamps (the on-wire seed-row shape)."""
    return [[round(t0 + i * dt, 3), p[0], p[1], p[2]] for i, p in enumerate(xyz_pts)]


def _highway(hid, xyz_pts, route_class="base"):
    return {"id": hid, "label": hid, "route_class": route_class,
            "from_resource": "A", "to_resource": "B", "seed": {"demo": "d", "player": "P"},
            "segments": [{"from_resource": "A", "to_resource": "B", "trajectory": _seg(xyz_pts)}]}


def _canon(highways):
    return {"schema": "komodobots.route_canon.v1", "map": "dm3", "highways": highways}


def _line_x(y, x0=0, x1=1000, step=100):
    """A straight base-highway polyline along the x-axis at height y."""
    return [(float(x), float(y), 0.0) for x in range(x0, x1 + 1, step)]


def _analysis(name, txyz, vya=0):
    """A synthetic qw-analyze full JSON: streams.players[].pos struct-of-arrays (t in MS, qu xyz +
    the velocity/view fields player_ticks reads)."""
    pos = {"t": [int(round(r[0] * 1000)) for r in txyz],
           "x": [r[1] for r in txyz], "y": [r[2] for r in txyz], "z": [r[3] for r in txyz],
           "vx": [100.0] * len(txyz), "vy": [0.0] * len(txyz), "vz": [0.0] * len(txyz),
           "vya": [vya] * len(txyz)}
    return {"streams": {"players": [{"name": name, "pos": pos}]}}


def _live(slot, total, state="LIVE"):
    return f"[moveprobe-live] slot {slot} {state} fwd=1 side=0 jump=0 (req={total} ans={total}) live={total}/{total}"


def _handoff(slot, state):
    return f"[moveprobe-handoff] slot {slot} {state}"


# --- pin_driven_highway -------------------------------------------------------------------------
class TestPinDrivenHighway(unittest.TestCase):
    def test_hugging_highway_pins_it_with_margin(self):
        canon = _canon([_highway("K", _line_x(0)), _highway("L", _line_x(1000))])
        attempt = [[i * 0.1, float(x), 5.0, 0.0] for i, x in enumerate(range(0, 501, 100))]
        pin = RE.pin_driven_highway(canon, attempt)
        self.assertEqual(pin["id"], "K")
        self.assertFalse(pin["ambiguous"])
        self.assertFalse(pin["off_all_highways"])
        self.assertAlmostEqual(pin["mean_dist_qu"], 5.0, places=1)
        self.assertGreater(pin["pin_margin_qu"], RE.PIN_AMBIGUOUS_MARGIN_QU)

    def test_equidistant_attempt_is_ambiguous_but_on_highway(self):
        canon = _canon([_highway("K", _line_x(0)), _highway("L", _line_x(60))])
        attempt = [[i * 0.1, float(x), 30.0, 0.0] for i, x in enumerate(range(0, 501, 100))]
        pin = RE.pin_driven_highway(canon, attempt)
        self.assertTrue(pin["ambiguous"])
        self.assertFalse(pin["off_all_highways"])      # 30 qu < R_OFF=96 -> still on a highway
        self.assertLess(pin["pin_margin_qu"], RE.PIN_AMBIGUOUS_MARGIN_QU)

    def test_off_all_highways_flags_low_confidence_and_warns(self):
        canon = _canon([_highway("K", _line_x(0)), _highway("L", _line_x(1000))])
        attempt = [[i * 0.1, float(x), 5000.0, 0.0] for i, x in enumerate(range(0, 501, 100))]
        with self.assertLogs("route_eval", level="WARNING") as cm:
            pin = RE.pin_driven_highway(canon, attempt)
        self.assertTrue(pin["off_all_highways"])
        self.assertTrue(any("low confidence" in m for m in cm.output))

    def test_no_base_highways_is_a_clear_error(self):
        canon = _canon([_highway("S", _line_x(0), route_class="shortcut")])
        with self.assertRaises(SystemExit):
            RE.pin_driven_highway(canon, [[0.0, 0.0, 0.0, 0.0], [0.1, 10.0, 0.0, 0.0]])

    def test_point_to_polyline_distance_is_perpendicular_and_clamped(self):
        poly = [(0.0, 0.0), (1000.0, 0.0)]
        self.assertAlmostEqual(RE._point_to_polyline_qu(500.0, 5.0, poly), 5.0, places=6)
        self.assertAlmostEqual(RE._point_to_polyline_qu(500.0, -5.0, poly), 5.0, places=6)
        self.assertAlmostEqual(RE._point_to_polyline_qu(-50.0, 0.0, poly), 50.0, places=6)  # clamp t=0


# --- parse_engaged_window -----------------------------------------------------------------------
class TestParseEngagedWindow(unittest.TestCase):
    def test_transitions_give_the_right_frame_window(self):
        log = "\n".join([
            _live(1, 1), _live(1, 2), _handoff(1, "ENGAGED"),
            _live(1, 5), _live(1, 10), _handoff(1, "DISENGAGED"),
            _live(1, 12, "FALLBACK"),
        ])
        eng = RE.parse_engaged_window(log, slot=1)
        self.assertEqual(eng["spans_frames"], [[2, 10]])
        self.assertEqual(eng["n_engaged_spans"], 1)
        self.assertEqual(eng["engaged_frames"], 8)
        self.assertEqual(eng["total_frames"], 12)
        self.assertEqual(eng["engaged_fraction"], round(8 / 12, 4))

    def test_open_span_closes_at_end_of_log(self):
        log = "\n".join([_live(1, 1), _handoff(1, "ENGAGED"), _live(1, 7)])
        eng = RE.parse_engaged_window(log, slot=1)
        self.assertEqual(eng["spans_frames"], [[1, 7]])

    def test_only_the_requested_slot_is_parsed(self):
        log = "\n".join([
            _live(2, 3), _handoff(2, "ENGAGED"), _live(2, 9), _handoff(2, "DISENGAGED"),
            _live(1, 4), _handoff(1, "ENGAGED"), _live(1, 6), _handoff(1, "DISENGAGED"),
        ])
        self.assertEqual(RE.parse_engaged_window(log, slot=1)["spans_frames"], [[4, 6]])
        self.assertEqual(RE.parse_engaged_window(log, slot=2)["spans_frames"], [[3, 9]])

    def test_no_engaged_transition_is_a_clear_error(self):
        log = "\n".join([_live(1, 1, "FALLBACK"), _live(1, 2, "FALLBACK")])
        with self.assertRaises(SystemExit):
            RE.parse_engaged_window(log, slot=1)


# --- extract_attempt_trajectory -----------------------------------------------------------------
class TestExtractAttemptTrajectory(unittest.TestCase):
    def _traj(self):
        return [[i * 0.1, float(i * 10), 0.0, 0.0] for i in range(5)]   # t=0..0.4s, x=0..40 qu

    def test_decodes_to_qu_seconds_rows(self):
        rows = RE.extract_attempt_trajectory(_analysis("Bot", self._traj()), "Bot")
        self.assertEqual(rows[0], [0.0, 0.0, 0.0, 0.0])
        self.assertEqual(rows[-1], [0.4, 40.0, 0.0, 0.0])
        self.assertEqual(len(rows), 5)

    def test_window_clips_inclusively(self):
        rows = RE.extract_attempt_trajectory(_analysis("Bot", self._traj()), "Bot", window=(0.1, 0.3))
        self.assertEqual([r[0] for r in rows], [0.1, 0.2, 0.3])

    def test_player_none_auto_picks_the_mover(self):
        analysis = _analysis("Bot", self._traj())
        # add a stationary spectator; the mover (Bot) must win the auto-pick
        analysis["streams"]["players"].append(
            {"name": "Spec", "pos": {"t": [0, 100], "x": [0, 0], "y": [0, 0], "z": [0, 0],
                                     "vx": [0, 0], "vy": [0, 0], "vz": [0, 0], "vya": [0, 0]}})
        rows = RE.extract_attempt_trajectory(analysis, None)
        self.assertEqual(rows[-1], [0.4, 40.0, 0.0, 0.0])

    def test_unknown_player_errors(self):
        with self.assertRaises(SystemExit):
            RE.extract_attempt_trajectory(_analysis("Bot", self._traj()), "Nobody")


# --- route_eval assembly ------------------------------------------------------------------------
def _moving_attempt(n=11, dx=80.0):
    """A bot path along y~3 over x=0..n*dx (hugs a y=0 base highway, covers most of its length)."""
    return [[round(i * 0.1, 3), round(i * dx, 1), 3.0, 0.0] for i in range(n)]


class TestEvaluateAnalysis(unittest.TestCase):
    def _canon(self):
        return _canon([_highway("K", _line_x(0)), _highway("L", _line_x(1000))])

    def _engaged_log(self, total):
        return "\n".join([_live(1, 1), _handoff(1, "ENGAGED")]
                         + [_live(1, t) for t in range(2, total + 1)])

    def test_valid_artifact_pins_geometrically_and_carries_isolation_evidence(self):
        traj = _moving_attempt()
        art = RE.evaluate_analysis(self._canon(), _analysis("Bot", traj), player="Bot", slot=1,
                                   screen_log_text=self._engaged_log(len(traj)), run_id="r1")
        self.assertEqual(art["schema"], "komodobots.route_eval.v1")
        self.assertTrue(art["valid"])
        self.assertEqual(art["invalid_reasons"], [])
        self.assertNotIn("non_isolated_debug", art)               # no quarantine block on the valid path
        self.assertEqual(art["highway"]["id"], "K")
        self.assertEqual(art["highway"]["pin"], "nearest-base-polyline (geometric)")
        self.assertIsInstance(art["highway"]["engaged_window_s"], list)
        self.assertEqual(len(art["highway"]["engaged_window_s"]), 2)
        self.assertIsInstance(art["highway"]["engaged_fraction"], float)
        self.assertGreaterEqual(art["highway"]["n_engaged_spans"], 1)
        # adherence (the SHAPE proxy) + the explicit velocity scalar both present + consumable
        for k in ("mse_xyz", "rmse_xyz", "rmse_xy", "rmse_z"):
            self.assertIsInstance(art["adherence"][k], (int, float))
        for k in ("duration_s", "path_len_qu", "mean_speed_qu_s", "progress_fraction"):
            self.assertIsInstance(art["velocity"][k], (int, float))
        self.assertGreater(art["velocity"]["mean_speed_qu_s"], 0)
        self.assertFalse(art["degenerate"])

    def test_stalled_attempt_is_valid_but_degenerate(self):
        # barely moves (x 0..6 qu vs the ~1000 qu seed) -> progress < MIN_PROGRESS, but it WAS
        # route-isolated -> valid=true, degenerate=true (quality is orthogonal to isolation).
        traj = [[round(i * 0.1, 3), round(i * 0.6, 1), 3.0, 0.0] for i in range(11)]
        art = RE.evaluate_analysis(self._canon(), _analysis("Bot", traj), player="Bot", slot=1,
                                   screen_log_text=self._engaged_log(len(traj)), run_id="r2")
        self.assertTrue(art["valid"])
        self.assertTrue(art["degenerate"])
        self.assertLess(art["velocity"]["progress_fraction"], RE.MIN_PROGRESS)

    def _assert_invalid(self, art, reason):
        self.assertFalse(art["valid"])
        self.assertIn(reason, art["invalid_reasons"])
        # the consumable score MUST be null on the invalid path...
        self.assertIsNone(art["adherence"])
        self.assertIsNone(art["velocity"])
        self.assertIsNone(art["degenerate"])
        self.assertIsNone(art["highway"]["id"])
        self.assertIsNone(art["highway"]["engaged_window_s"])
        # ...and the full-trajectory numbers are quarantined as non-consumable debug
        self.assertIn("non_isolated_debug", art)
        self.assertEqual(art["non_isolated_debug"]["highway_id"], "K")
        self.assertIn("NOT route-isolated", art["non_isolated_debug"]["_warning"])

    def test_missing_engaged_window_is_invalid(self):
        traj = _moving_attempt()
        log = "\n".join([_live(1, t, "FALLBACK") for t in range(1, len(traj) + 1)])  # no ENGAGED
        art = RE.evaluate_analysis(self._canon(), _analysis("Bot", traj), player="Bot", slot=1,
                                   screen_log_text=log, run_id="r3")
        self._assert_invalid(art, "no_engaged_spans")
        self.assertEqual(art["highway"]["n_engaged_spans"], 0)

    def test_zero_width_engaged_window_is_invalid(self):
        traj = _moving_attempt()
        # ENGAGED and DISENGAGED at the same frame counter -> a window that slices < 2 ticks
        log = "\n".join([_live(1, 5), _handoff(1, "ENGAGED"), _handoff(1, "DISENGAGED")])
        art = RE.evaluate_analysis(self._canon(), _analysis("Bot", traj), player="Bot", slot=1,
                                   screen_log_text=log, run_id="r4")
        self._assert_invalid(art, "engaged_window_too_narrow")

    def test_window_extraction_failure_is_invalid(self):
        traj = _moving_attempt()
        orig = RE.extract_attempt_trajectory

        def boom(analysis, player, window=None):       # full extract ok; the WINDOWED one fails hard
            if window is None:
                return orig(analysis, player, window=None)
            raise RuntimeError("synthetic decode failure")

        RE.extract_attempt_trajectory = boom
        try:
            art = RE.evaluate_analysis(self._canon(), _analysis("Bot", traj), player="Bot", slot=1,
                                       screen_log_text=self._engaged_log(len(traj)), run_id="r5")
        finally:
            RE.extract_attempt_trajectory = orig
        self._assert_invalid(art, "window_extraction_failed")


class TestEvaluateRunAndLedger(unittest.TestCase):
    def setUp(self):
        self._orig = RE.run_qw_analyze

    def tearDown(self):
        RE.run_qw_analyze = self._orig

    def test_stub_run_dir_writes_artifact_and_merges_ledger(self):
        traj = _moving_attempt()
        canon = _canon([_highway("K", _line_x(0)), _highway("L", _line_x(1000))])
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            run_id = "20260629T000000Z-p28599-deadbeef"
            run_dir = td / run_id
            run_dir.mkdir()
            (run_dir / "screen.log").write_text(
                "\n".join([_live(1, 1), _handoff(1, "ENGAGED")]
                          + [_live(1, t) for t in range(2, len(traj) + 1)]), encoding="utf-8")
            (run_dir / "rec.mvd").write_bytes(b"\x00" * 128)
            canon_path = td / "canon.json"
            canon_path.write_text(json.dumps(canon), encoding="utf-8")
            ledger_path = td / "bot-attempts.json"
            ledger_path.write_text(json.dumps({
                "schema": "komodobots.bot_attempts.v1", "map": "dm3",
                "attempts": [{"run_id": run_id, "ts_utc": "t", "map": "dm3", "n_bots": 1,
                              "mode": "prewar-movecheck", "demo": None, "freshness": {},
                              "verdict": "GREEN", "artifact_dir": "x"}]}), encoding="utf-8")

            RE.run_qw_analyze = lambda *a, **k: _analysis("Bot", traj)
            art = RE.evaluate_run(run_dir, slot=1, player="Bot", canon_path=canon_path,
                                  demos_dir=run_dir, ledger_path=ledger_path)

            # artifact written into the run dir
            on_disk = json.loads((run_dir / "route_eval.json").read_text(encoding="utf-8"))
            self.assertEqual(on_disk["schema"], "komodobots.route_eval.v1")
            self.assertEqual(on_disk, art)
            self.assertEqual(art["demo"]["name"], "rec.mvd")

            # the score is merged into that run's ledger row (additive nested key; row keys intact)
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            row = ledger["attempts"][0]
            re_row = row["route_eval"]
            self.assertTrue(re_row["valid"])
            self.assertEqual(re_row["invalid_reasons"], [])
            self.assertEqual(re_row["highway_id"], "K")
            self.assertIn("rmse_xyz", re_row)
            self.assertIn("mean_speed_qu_s", re_row)
            for k in ("n_engaged_spans", "engaged_frames", "engaged_fraction"):
                self.assertIn(k, re_row)            # isolation-proof fields surfaced on the row
            for required in ("run_id", "verdict", "demo", "freshness"):
                self.assertIn(required, row)        # required ledger keys untouched

    def test_invalid_eval_writes_no_consumable_score(self):
        # an INVALID (not route-isolated) artifact must NOT land a normal-looking rmse/speed score
        invalid_art = {
            "valid": False, "invalid_reasons": ["no_engaged_spans"],
            "highway": {"id": None, "n_engaged_spans": 0, "engaged_frames": 0, "engaged_fraction": None},
            "adherence": None, "velocity": None, "degenerate": None,
        }
        with tempfile.TemporaryDirectory() as td:
            ledger_path = Path(td) / "bot-attempts.json"
            ledger_path.write_text(json.dumps({
                "schema": "komodobots.bot_attempts.v1", "map": "dm3",
                "attempts": [{"run_id": "rX", "verdict": "GREEN"}]}), encoding="utf-8")
            re_row = RE.merge_score_into_ledger(ledger_path, "rX", invalid_art)
            self.assertFalse(re_row["valid"])
            self.assertEqual(re_row["invalid_reasons"], ["no_engaged_spans"])
            self.assertNotIn("rmse_xyz", re_row)          # NO consumable score
            self.assertNotIn("mean_speed_qu_s", re_row)
            self.assertNotIn("highway_id", re_row)
            on_disk = json.loads(ledger_path.read_text(encoding="utf-8"))["attempts"][0]["route_eval"]
            self.assertNotIn("rmse_xyz", on_disk)

    def test_merge_skips_when_no_matching_row(self):
        with tempfile.TemporaryDirectory() as td:
            ledger_path = Path(td) / "bot-attempts.json"
            ledger_path.write_text(json.dumps({"schema": "komodobots.bot_attempts.v1",
                                               "map": "dm3", "attempts": []}), encoding="utf-8")
            art = {"valid": True, "highway": {"id": "K"}, "adherence": {"rmse_xyz": 1.0},
                   "velocity": {"mean_speed_qu_s": 2.0}, "degenerate": False}
            self.assertIsNone(RE.merge_score_into_ledger(ledger_path, "missing", art))


if __name__ == "__main__":
    unittest.main()
