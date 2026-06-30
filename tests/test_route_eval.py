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
import math
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
    def test_anchor_is_the_following_live_counter_not_the_previous(self):
        # KTX emits the handoff line BEFORE the same-frame live line, so each transition anchors to the
        # NEXT live counter (gate P1-a). The prior FALLBACK frame (400) must be EXCLUDED.
        log = "\n".join([
            _live(1, 400, "FALLBACK"), _handoff(1, "ENGAGED"),
            _live(1, 500), _handoff(1, "DISENGAGED"), _live(1, 700),
        ])
        eng = RE.parse_engaged_window(log, slot=1)
        self.assertEqual(eng["spans_frames"], [[500, 700]])     # NOT [[400, 500]]
        self.assertEqual(eng["engaged_frames"], 200)
        self.assertTrue(all(400 not in span for span in eng["spans_frames"]))

    def test_transitions_give_the_right_frame_window(self):
        log = "\n".join([
            _live(1, 1), _live(1, 2), _handoff(1, "ENGAGED"),
            _live(1, 5), _live(1, 10), _handoff(1, "DISENGAGED"),
            _live(1, 12, "FALLBACK"),
        ])
        eng = RE.parse_engaged_window(log, slot=1)
        self.assertEqual(eng["spans_frames"], [[5, 12]])        # ENGAGED->next live 5; DISENGAGED->next 12
        self.assertEqual(eng["n_engaged_spans"], 1)
        self.assertEqual(eng["engaged_frames"], 7)
        self.assertEqual(eng["total_frames"], 12)
        self.assertEqual(eng["engaged_fraction"], round(7 / 12, 4))

    def test_open_span_closes_at_end_of_log(self):
        log = "\n".join([_live(1, 1), _handoff(1, "ENGAGED"), _live(1, 5), _live(1, 7)])
        eng = RE.parse_engaged_window(log, slot=1)
        self.assertEqual(eng["spans_frames"], [[5, 7]])         # ENGAGED->next live 5; ran off -> last 7

    def test_only_the_requested_slot_is_parsed(self):
        log = "\n".join([
            _live(2, 10), _handoff(2, "ENGAGED"), _live(2, 20), _handoff(2, "DISENGAGED"), _live(2, 30),
            _live(1, 40), _handoff(1, "ENGAGED"), _live(1, 50), _handoff(1, "DISENGAGED"), _live(1, 60),
        ])
        self.assertEqual(RE.parse_engaged_window(log, slot=1)["spans_frames"], [[50, 60]])
        self.assertEqual(RE.parse_engaged_window(log, slot=2)["spans_frames"], [[20, 30]])

    def test_two_spans_are_both_captured(self):
        log = "\n".join([
            _live(1, 1), _handoff(1, "ENGAGED"), _live(1, 5), _handoff(1, "DISENGAGED"),
            _live(1, 10), _handoff(1, "ENGAGED"), _live(1, 15), _live(1, 20),
        ])
        eng = RE.parse_engaged_window(log, slot=1)
        self.assertEqual(eng["spans_frames"], [[5, 10], [15, 20]])
        self.assertEqual(eng["n_engaged_spans"], 2)

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
        ews = art["highway"]["engaged_window_s"]                  # a single contiguous [t0,t1]
        self.assertIsInstance(ews, list)
        self.assertEqual(len(ews), 2)
        self.assertTrue(all(isinstance(v, (int, float)) for v in ews))
        self.assertLess(ews[0], ews[1])
        self.assertIsInstance(art["highway"]["engaged_fraction"], float)
        self.assertEqual(art["highway"]["n_engaged_spans"], 1)    # VALID == exactly one span
        # adherence (the SHAPE proxy) + the explicit velocity scalar both present + consumable
        for k in ("mse_xyz", "rmse_xyz", "rmse_xy", "rmse_z"):
            self.assertIsInstance(art["adherence"][k], (int, float))
        for k in ("duration_s", "path_len_qu", "mean_speed_qu_s", "progress_fraction"):
            self.assertIsInstance(art["velocity"][k], (int, float))
        self.assertGreater(art["velocity"]["mean_speed_qu_s"], 0)
        self.assertFalse(art["degenerate"])

    def test_multi_span_engagement_is_invalid_with_no_consumable_score(self):
        # The bot engages -> DISENGAGES -> re-engages (2 spans). Fail-closed (gate P1-b): scoring a
        # 2-span run would BRIDGE the disengaged off-route gap in velocity/arclen, so it is INVALID
        # (multi_span_engagement) with NO consumable score -- and the ledger gets no rmse/speed.
        traj = _moving_attempt(16)
        log = "\n".join([_live(1, 1), _handoff(1, "ENGAGED")] + [_live(1, t) for t in range(2, 6)]
                        + [_handoff(1, "DISENGAGED")] + [_live(1, t) for t in range(6, 11)]
                        + [_handoff(1, "ENGAGED")] + [_live(1, t) for t in range(11, 17)])
        art = RE.evaluate_analysis(self._canon(), _analysis("Bot", traj), player="Bot", slot=1,
                                   screen_log_text=log, run_id="rm")
        self.assertFalse(art["valid"])
        self.assertIn("multi_span_engagement", art["invalid_reasons"])
        self.assertEqual(art["highway"]["n_engaged_spans"], 2)
        self.assertIsNone(art["highway"]["engaged_window_s"])      # no single contiguous window
        self.assertIsNone(art["adherence"])                        # NO consumable score (no bridge)
        self.assertIsNone(art["velocity"])
        self.assertIsNone(art["degenerate"])
        self.assertIn("non_isolated_debug", art)                   # full-traj numbers quarantined only
        # ...and the ledger merge writes NO rmse/speed for a multi-span (invalid) run
        with tempfile.TemporaryDirectory() as td:
            lp = Path(td) / "bot-attempts.json"
            lp.write_text(json.dumps({"schema": "komodobots.bot_attempts.v1", "map": "dm3",
                                      "attempts": [{"run_id": "rm", "verdict": "GREEN"}]}),
                          encoding="utf-8")
            re_row = RE.merge_score_into_ledger(lp, "rm", art)
            self.assertFalse(re_row["valid"])
            self.assertIn("multi_span_engagement", re_row["invalid_reasons"])
            self.assertNotIn("rmse_xyz", re_row)
            self.assertNotIn("mean_speed_qu_s", re_row)

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
            re_row = row["route_evals"][0]          # single-bot run -> a 1-element route_evals array
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
            on_disk = json.loads(
                ledger_path.read_text(encoding="utf-8"))["attempts"][0]["route_evals"][0]
            self.assertNotIn("rmse_xyz", on_disk)

    def test_merge_skips_when_no_matching_row(self):
        with tempfile.TemporaryDirectory() as td:
            ledger_path = Path(td) / "bot-attempts.json"
            ledger_path.write_text(json.dumps({"schema": "komodobots.bot_attempts.v1",
                                               "map": "dm3", "attempts": []}), encoding="utf-8")
            art = {"valid": True, "highway": {"id": "K"}, "adherence": {"rmse_xyz": 1.0},
                   "velocity": {"mean_speed_qu_s": 2.0}, "degenerate": False}
            self.assertIsNone(RE.merge_score_into_ledger(ledger_path, "missing", art))


# --- multi-bot: seeds + binding + player_contact + evaluate_run_multi (#428 PR2 shape-A) ----------
def _pos(txyz, vya=0):
    return {"t": [int(round(r[0] * 1000)) for r in txyz],
            "x": [r[1] for r in txyz], "y": [r[2] for r in txyz], "z": [r[3] for r in txyz],
            "vx": [100.0] * len(txyz), "vy": [0.0] * len(txyz), "vz": [0.0] * len(txyz),
            "vya": [vya] * len(txyz)}


def _analysis_multi(players):
    """players = [(name, txyz), ...] -> a multi-player qw-analyze JSON (streams.players)."""
    return {"streams": {"players": [{"name": n, "pos": _pos(t)} for n, t in players]}}


def _hug(y, n=11, dx=80.0):
    """A bot path hugging the y=`y` base highway over x=0..(n-1)*dx (covers most of its length)."""
    return [[round(i * 0.1, 3), round(i * dx, 1), float(y), 0.0] for i in range(n)]


class TestBaseHighwaySeeds(unittest.TestCase):
    def test_returns_slot_id_xyz_for_base_only_in_order(self):
        canon = _canon([_highway("A", _line_x(0)),
                        _highway("S", _line_x(50), route_class="shortcut"),
                        _highway("B", _line_x(100))])
        seeds = RE.base_highway_seeds(canon, 2)
        self.assertEqual([(s, hid) for s, hid, _xyz in seeds], [(1, "A"), (2, "B")])  # shortcut skipped
        self.assertEqual(seeds[0][2], (0.0, 0.0, 0.0))           # = A's first trajectory point

    def test_prefers_explicit_3d_start_xyz_over_trajectory(self):
        h = _highway("A", _line_x(0))
        h["start_xyz"] = [7.0, 8.0, 9.0]                          # the 3-D JSON field (z the header lacks)
        seeds = RE.base_highway_seeds(_canon([h]), 1)
        self.assertEqual(seeds[0][2], (7.0, 8.0, 9.0))

    def test_raises_when_more_bots_than_base_highways(self):
        with self.assertRaises(ValueError):
            RE.base_highway_seeds(_canon([_highway("A", _line_x(0))]), 2)


class TestBaseHighwayEndMarkers(unittest.TestCase):
    def test_empty_when_no_highway_carries_an_end_marker(self):
        # Today's reality: the canon has no end_marker on any base highway -> {} -> directed fail-loud.
        canon = _canon([_highway("A", _line_x(0)), _highway("B", _line_x(100))])
        self.assertEqual(RE.base_highway_end_markers(canon), {})

    def test_maps_base_highways_that_have_one_skips_shortcut_and_unmarked(self):
        a = _highway("A", _line_x(0)); a["end_marker"] = 7
        s = _highway("S", _line_x(50), route_class="shortcut"); s["end_marker"] = 99
        b = _highway("B", _line_x(100))                        # base, but no end_marker
        self.assertEqual(RE.base_highway_end_markers(_canon([a, s, b])), {"A": 7})

    def test_rejects_non_positive_or_non_int_markers(self):
        # fixed_goal 0/negative is an engine no-op (= un-directed); a non-int is not a marker index.
        # All must RAISE before the bad value can ever be emitted as a fixed_goal cvar.
        for bad in (0, -1, 7.0, "7", True):
            a = _highway("A", _line_x(0)); a["end_marker"] = bad
            with self.assertRaises(ValueError):
                RE.base_highway_end_markers(_canon([a]))


class TestBindPlayersToSeeds(unittest.TestCase):
    def _pl(self, name, start):
        x, y, z = start
        return (name, [[0.0, x, y, z], [0.1, x + 10, y, z], [0.2, x + 20, y, z]])

    def test_binds_each_slot_to_its_nearest_distinct_player(self):
        seeds = [(1, (0., 0., 0.)), (2, (1000., 0., 0.)), (3, (0., 1000., 0.)), (4, (1000., 1000., 0.))]
        analysis = _analysis_multi([self._pl("fb_a", (0, 0, 0)), self._pl("fb_b", (1000, 0, 0)),
                                    self._pl("fb_c", (0, 1000, 0)), self._pl("fb_d", (1000, 1000, 0))])
        bound = RE.bind_players_to_seeds(analysis, seeds)
        self.assertEqual(bound, {1: "fb_a", 2: "fb_b", 3: "fb_c", 4: "fb_d"})

    def test_uniqueness_two_near_players_bind_to_distinct_slots(self):
        seeds = [(1, (0., 0., 0.)), (2, (50., 0., 0.))]
        analysis = _analysis_multi([self._pl("near1", (0, 0, 0)), self._pl("near2", (60, 0, 0))])
        bound = RE.bind_players_to_seeds(analysis, seeds)
        self.assertEqual(bound[1], "near1")                      # global-nearest pair claimed first
        self.assertEqual({bound[1], bound[2]}, {"near1", "near2"})  # distinct -- never the same player

    def test_spectator_is_excluded_by_name(self):
        seeds = [(1, (0., 0., 0.))]
        analysis = _analysis_multi([self._pl("KomodoPrewar", (0, 0, 0)), self._pl("bot", (5, 0, 0))])
        bound = RE.bind_players_to_seeds(analysis, seeds, exclude_players=("KomodoPrewar",))
        self.assertEqual(bound[1], "bot")                        # the nearer spectator is excluded

    def test_fewer_players_than_seeds_leaves_none(self):
        seeds = [(1, (0., 0., 0.)), (2, (1000., 0., 0.))]
        bound = RE.bind_players_to_seeds(_analysis_multi([self._pl("only", (0, 0, 0))]), seeds)
        self.assertEqual(bound[1], "only")
        self.assertIsNone(bound[2])


class TestDetectPlayerContact(unittest.TestCase):
    def test_two_bots_within_bbox_during_overlap_are_flagged(self):
        a = [[0.0, 0., 0., 0.], [1.0, 0., 0., 0.]]               # static at origin
        b = [[0.0, 100., 0., 0.], [1.0, -100., 0., 0.]]          # sweeps through origin at t=0.5
        contacts = RE.detect_player_contact(
            [{"slot": 1, "player": "a", "valid": True, "window_s": (0.0, 1.0), "rows": a},
             {"slot": 2, "player": "b", "valid": True, "window_s": (0.0, 1.0), "rows": b}])
        self.assertEqual(set(contacts), {1, 2})
        self.assertEqual(contacts[1][0]["slot"], 2)
        self.assertLess(contacts[1][0]["min_dist_qu"], 1.0)        # passes through origin

    def test_vertical_hull_overlap_caught_when_center_distance_would_miss(self):
        # P1-a (review): same XY, origins 40 qu apart in Z. The player hulls overlap (|dz|=40 < 56) ->
        # contact, but a 3-D CENTRE distance (40 qu) exceeds the old 34-qu threshold and would MISS the
        # physics block (two bots blocking on a ramp / stairs).
        a = [[0.0, 0., 0., 0.], [1.0, 0., 0., 0.]]
        b = [[0.0, 0., 0., 40.], [1.0, 0., 0., 40.]]
        contacts = RE.detect_player_contact(
            [{"slot": 1, "player": "a", "valid": True, "window_s": (0.0, 1.0), "rows": a},
             {"slot": 2, "player": "b", "valid": True, "window_s": (0.0, 1.0), "rows": b}])
        self.assertEqual(set(contacts), {1, 2})                   # hull overlap despite a 40-qu Z gap
        self.assertGreater(math.dist((0, 0, 0), (0, 0, 40)), 34.0)  # the old scalar check would not fire

    def test_fast_passthrough_between_coarse_samples_caught(self):
        # P1-b (review): bots cross at t=0.025, BETWEEN the old fixed 50 ms grid nodes (0.0 / 0.05 /
        # 0.1) -- the grid sampled |d|>=200 at every node and returned clean. The swept hull test over
        # the recorded tick interval catches the true crossing.
        a = [[0.0, 0., 0., 0.], [0.1, 0., 0., 0.]]                # static at origin
        b = [[0.0, 200., 0., 0.], [0.1, -600., 0., 0.]]          # x: 200 -> -600, through 0 at t=0.025
        contacts = RE.detect_player_contact(
            [{"slot": 1, "player": "a", "valid": True, "window_s": (0.0, 0.1), "rows": a},
             {"slot": 2, "player": "b", "valid": True, "window_s": (0.0, 0.1), "rows": b}])
        self.assertEqual(set(contacts), {1, 2})
        self.assertLess(contacts[1][0]["min_dist_qu"], 1.0)       # true closest approach ~0 at t~0.025

    def test_far_apart_bots_are_clean(self):
        a = [[0.0, 0., 0., 0.], [1.0, 0., 0., 0.]]
        b = [[0.0, 500., 500., 0.], [1.0, 500., 500., 0.]]
        self.assertEqual(RE.detect_player_contact(
            [{"slot": 1, "player": "a", "valid": True, "window_s": (0.0, 1.0), "rows": a},
             {"slot": 2, "player": "b", "valid": True, "window_s": (0.0, 1.0), "rows": b}]), {})

    def test_disjoint_recordings_never_contact(self):
        # B has no RECORDED position during A's scored window (disjoint recordings) -> no false contact:
        # O is only present where it was recorded; its position is never fabricated by clamping.
        a = [[0.0, 0., 0., 0.], [0.4, 0., 0., 0.]]               # A recorded [0, 0.4]
        b = [[0.6, 0., 0., 0.], [1.0, 0., 0., 0.]]               # B recorded [0.6, 1.0]
        self.assertEqual(RE.detect_player_contact(
            [{"slot": 1, "player": "a", "valid": True, "window_s": (0.0, 0.4), "rows": a},
             {"slot": 2, "player": "b", "valid": True, "window_s": (0.6, 1.0), "rows": b}]), {})


class TestEvaluateRunMulti(unittest.TestCase):
    def setUp(self):
        self._orig = RE.run_qw_analyze

    def tearDown(self):
        RE.run_qw_analyze = self._orig

    def _canon(self):
        return _canon([_highway("K", _line_x(0)), _highway("L", _line_x(1000))])

    def _setup_run(self, td, analysis):
        run_id = "20260629T010101Z-p28599-cafebabe"
        run_dir = td / run_id
        run_dir.mkdir()
        n = len(analysis["streams"]["players"][0]["pos"]["t"])
        log = []
        for slot in (1, 2):                                       # each slot engaged the full window
            log += [_live(slot, 1), _handoff(slot, "ENGAGED")] + [_live(slot, t) for t in range(2, n + 1)]
        (run_dir / "screen.log").write_text("\n".join(log), encoding="utf-8")
        (run_dir / "rec.mvd").write_bytes(b"\x00" * 128)
        canon_path = td / "canon.json"
        canon_path.write_text(json.dumps(self._canon()), encoding="utf-8")
        ledger_path = td / "bot-attempts.json"
        ledger_path.write_text(json.dumps({"schema": "komodobots.bot_attempts.v1", "map": "dm3",
                                           "attempts": [{"run_id": run_id, "verdict": "GREEN"}]}),
                               encoding="utf-8")
        RE.run_qw_analyze = lambda *a, **k: analysis
        return run_dir, canon_path, ledger_path

    def test_two_distinct_bots_each_score_their_own_highway(self):
        analysis = _analysis_multi([("botK", _hug(3)), ("botL", _hug(1003))])
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            run_dir, cp, lp = self._setup_run(td, analysis)
            seeds = RE.base_highway_seeds(json.loads(cp.read_text()), 2)
            res = RE.evaluate_run_multi(run_dir, seeds=seeds, canon_path=cp, demos_dir=run_dir,
                                        ledger_path=lp)
            blocks = {b["slot"]: b for b in res["route_evals"]}
            self.assertTrue(blocks[1]["valid"])
            self.assertEqual(blocks[1]["highway_id"], "K")
            self.assertEqual(blocks[1]["player"], "botK")
            self.assertTrue(blocks[2]["valid"])
            self.assertEqual(blocks[2]["highway_id"], "L")
            self.assertEqual(blocks[2]["player"], "botL")
            self.assertTrue((run_dir / "route_eval.s1.json").exists())
            self.assertTrue((run_dir / "route_eval.s2.json").exists())
            ledger_blocks = json.loads(lp.read_text())["attempts"][0]["route_evals"]
            self.assertEqual(len(ledger_blocks), 2)

    def test_drove_wrong_highway_is_demoted(self):
        # #460 directed-contract guard: seed each slot at one highway's start but ASSIGN it the OTHER
        # highway's id (slot1 @ K's seed tagged 'L', slot2 @ L's seed tagged 'K'). Each bot drives the
        # highway it stands on, so the geometric pin disagrees with the assignment -> fail-closed
        # drove_wrong_highway (no consumable score), and the artifact self-certifies assigned vs driven.
        analysis = _analysis_multi([("botK", _hug(3)), ("botL", _hug(1003))])
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            run_dir, cp, lp = self._setup_run(td, analysis)
            seeds = RE.base_highway_seeds(json.loads(cp.read_text()), 2)   # [(1,'K',xyzK),(2,'L',xyzL)]
            swapped = [(1, "L", seeds[0][2]), (2, "K", seeds[1][2])]        # wrong ids, same seed coords
            res = RE.evaluate_run_multi(run_dir, seeds=swapped, canon_path=cp, demos_dir=run_dir,
                                        ledger_path=lp)
            blocks = {b["slot"]: b for b in res["route_evals"]}
            for s in (1, 2):
                self.assertFalse(blocks[s]["valid"])
                self.assertIn("drove_wrong_highway", blocks[s]["invalid_reasons"])
                self.assertNotIn("rmse_xyz", blocks[s])              # no consumable score on a wrong route
                self.assertFalse(blocks[s]["route_match"])
            self.assertEqual(blocks[1]["assigned_highway_id"], "L")
            art1 = json.loads((run_dir / "route_eval.s1.json").read_text())
            self.assertEqual(art1["highway"]["assigned_highway_id"], "L")
            self.assertIs(art1["highway"]["route_match"], False)
            self.assertEqual(art1["non_isolated_debug"]["driven_highway_id"], "K")

    def test_assigned_route_match_true_when_driven_matches(self):
        # the happy path: each bot drives the highway it was assigned -> route_match True, valid score.
        analysis = _analysis_multi([("botK", _hug(3)), ("botL", _hug(1003))])
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            run_dir, cp, lp = self._setup_run(td, analysis)
            seeds = RE.base_highway_seeds(json.loads(cp.read_text()), 2)
            res = RE.evaluate_run_multi(run_dir, seeds=seeds, canon_path=cp, demos_dir=run_dir,
                                        ledger_path=lp)
            blocks = {b["slot"]: b for b in res["route_evals"]}
            for s in (1, 2):
                self.assertTrue(blocks[s]["valid"])
                self.assertTrue(blocks[s]["route_match"])
            self.assertEqual(blocks[1]["assigned_highway_id"], "K")
            self.assertEqual(blocks[2]["assigned_highway_id"], "L")

    def test_colliding_bots_are_both_player_contact_invalid(self):
        # both bots hug highway K (y=0 and y=5) -> within the player bbox the whole window -> the
        # scored MSE would be physics-contaminated, so BOTH are fail-closed player_contact (no score).
        # Both are ASSIGNED K (the line they drive) so route_match passes and the collision is the ONLY
        # fault -- isolating player_contact from the #460 drove_wrong_highway guard (mirrors the real
        # case: two bots on their CORRECT corridor-sharing highways bumping).
        analysis = _analysis_multi([("botA", _hug(0)), ("botB", _hug(5))])
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            run_dir, cp, lp = self._setup_run(td, analysis)
            base = RE.base_highway_seeds(json.loads(cp.read_text()), 2)
            seeds = [(1, "K", base[0][2]), (2, "K", base[0][2])]   # both assigned K (both drive K)
            res = RE.evaluate_run_multi(run_dir, seeds=seeds, canon_path=cp, demos_dir=run_dir,
                                        ledger_path=lp)
            blocks = {b["slot"]: b for b in res["route_evals"]}
            for s in (1, 2):
                self.assertFalse(blocks[s]["valid"])
                self.assertIn("player_contact", blocks[s]["invalid_reasons"])
                self.assertNotIn("rmse_xyz", blocks[s])          # no consumable score on a bumped run
            art1 = json.loads((run_dir / "route_eval.s1.json").read_text())
            self.assertIn("player_contact", art1["invalid_reasons"])
            self.assertIn("contact_partners", art1["non_isolated_debug"])
            self.assertEqual(art1["non_isolated_debug"]["contact_partners"][0]["slot"], 2)

    def test_invalid_bound_bot_contaminates_valid_bot(self):
        # Codex P1 (round 2): slot 2 NEVER engages (invalid `no_engaged_spans`) but its body overlaps
        # slot 1's hull during slot 1's engaged window -> the VALID slot 1 must be demoted
        # `player_contact` (no consumable score), while slot 2 stays invalid for its OWN reason.
        analysis = _analysis_multi([("botK", _hug(0)), ("botBlock", _hug(5))])
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            run_id = "20260629T020202Z-p28599-feedface"
            run_dir = td / run_id
            run_dir.mkdir()
            n = 11
            log = ([_live(1, 1), _handoff(1, "ENGAGED")] + [_live(1, t) for t in range(2, n + 1)]
                   + [_live(2, t, "FALLBACK") for t in range(1, n + 1)])     # slot 2 never ENGAGED
            (run_dir / "screen.log").write_text("\n".join(log), encoding="utf-8")
            (run_dir / "rec.mvd").write_bytes(b"\x00" * 128)
            canon_path = td / "canon.json"
            canon_path.write_text(json.dumps(self._canon()), encoding="utf-8")
            ledger_path = td / "bot-attempts.json"
            ledger_path.write_text(json.dumps({"schema": "komodobots.bot_attempts.v1", "map": "dm3",
                                               "attempts": [{"run_id": run_id, "verdict": "GREEN"}]}),
                                   encoding="utf-8")
            RE.run_qw_analyze = lambda *a, **k: analysis
            seeds = RE.base_highway_seeds(json.loads(canon_path.read_text()), 2)
            res = RE.evaluate_run_multi(run_dir, seeds=seeds, canon_path=canon_path, demos_dir=run_dir,
                                        ledger_path=ledger_path)
            blocks = {b["slot"]: b for b in res["route_evals"]}
            self.assertFalse(blocks[1]["valid"])                        # the valid bot, physically blocked
            self.assertIn("player_contact", blocks[1]["invalid_reasons"])
            self.assertNotIn("rmse_xyz", blocks[1])                     # no consumable score survives
            self.assertFalse(blocks[2]["valid"])                        # slot 2 invalid for its OWN reason
            self.assertIn("no_engaged_spans", blocks[2]["invalid_reasons"])
            self.assertNotIn("player_contact", blocks[2]["invalid_reasons"])
            art1 = json.loads((run_dir / "route_eval.s1.json").read_text())
            self.assertFalse(art1["non_isolated_debug"]["contact_partners"][0]["partner_valid"])


if __name__ == "__main__":
    unittest.main()
