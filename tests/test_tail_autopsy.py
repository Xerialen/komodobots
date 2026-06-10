"""tail_autopsy (A2b #111): the pure feature-extraction helpers.

The crossing-INDEX finder must agree with route_metrics.edge_speed (the one
metric implementation) on every input — that contract is asserted per traced
try in production AND here on synthetic shapes (multi-crossing, teleport
step, corridor/z rejection).
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import tail_autopsy as TA  # noqa: E402
from route_metrics import edge_speed  # noqa: E402

# A gap whose launch plane is x = 100 (land due +x): along = x - 100.
GAP = {"edge": [100.0, 0.0, 0.0], "land": [200.0, 0.0, -10.0]}


def row(t, x, y=0.0, z=0.0, vh=400.0, og=0, **extra):
    d = {"t": t, "x": x, "y": y, "z": z, "vh": vh, "onground": og,
         "dist_goal": 1e6}
    d.update(extra)
    return d


class TestFindCrossings(unittest.TestCase):
    def assert_matches_metric(self, rows):
        idx = TA.find_crossings(rows, GAP)
        v = edge_speed(rows, GAP)
        if idx:
            self.assertIsNotNone(v)
            self.assertEqual(rows[idx[-1]]["vh"], v)
        else:
            self.assertIsNone(v)

    def test_simple_crossing(self):
        rows = [row(0, 80), row(0.1, 95), row(0.2, 105, vh=432.0)]
        idx = TA.find_crossings(rows, GAP)
        self.assertEqual(idx, [2])
        self.assert_matches_metric(rows)

    def test_last_crossing_wins(self):
        rows = [row(0, 95), row(0.1, 105, vh=300.0), row(0.2, 95),
                row(0.3, 106, vh=500.0)]
        idx = TA.find_crossings(rows, GAP)
        self.assertEqual(len(idx), 2)
        self.assertEqual(rows[idx[-1]]["vh"], 500.0)
        self.assert_matches_metric(rows)

    def test_teleport_step_excluded(self):
        rows = [row(0, 95), row(0.1, 700, vh=999.0)]   # 605 qu step
        self.assertEqual(TA.find_crossings(rows, GAP), [])
        self.assert_matches_metric(rows)

    def test_corridor_and_z_rejection(self):
        wide = [row(0, 95, y=300.0), row(0.1, 105, y=300.0)]
        self.assertEqual(TA.find_crossings(wide, GAP), [])
        self.assert_matches_metric(wide)
        deep = [row(0, 95, z=-150.0), row(0.1, 105, z=-150.0)]
        self.assertEqual(TA.find_crossings(deep, GAP), [])
        self.assert_matches_metric(deep)

    def test_no_crossing(self):
        rows = [row(0, 80), row(0.1, 90)]
        self.assertEqual(TA.find_crossings(rows, GAP), [])
        self.assert_matches_metric(rows)


class TestBackdistCheckpoints(unittest.TestCase):
    def test_walkback_accumulates_xy_arc(self):
        # 11 rows, 50 qu apart -> crossing at index 10; backdist 0/100/200
        rows = [row(i * 0.1, i * 50.0, vh=300.0 + i) for i in range(11)]
        cps = TA.backdist_checkpoints(rows, 10, targets=(0.0, 100.0, 200.0))
        self.assertEqual(cps[0.0]["i"], 10)
        self.assertEqual(cps[100.0]["i"], 8)
        self.assertEqual(cps[200.0]["i"], 6)
        self.assertEqual(cps[100.0]["vh"], 308.0)

    def test_short_trace_yields_none(self):
        rows = [row(0, 0), row(0.1, 50)]
        cps = TA.backdist_checkpoints(rows, 1, targets=(0.0, 1000.0))
        self.assertIsNotNone(cps[0.0])
        self.assertIsNone(cps[1000.0])


class TestGroundEpisodes(unittest.TestCase):
    def test_entry_exit_and_loss(self):
        rows = [row(0.00, 0, og=0, vh=400.0),
                row(0.01, 5, og=1, vh=390.0),   # episode 1 (2 frames)
                row(0.02, 10, og=1, vh=380.0),
                row(0.03, 15, og=0, vh=375.0),  # exit row
                row(0.04, 20, og=1, vh=370.0),  # episode 2 (1 frame)
                row(0.05, 25, og=0, vh=372.0)]
        eps = TA.ground_episodes(rows, 0, 5)
        self.assertEqual(len(eps), 2)
        self.assertEqual(eps[0]["n"], 2)
        self.assertEqual(eps[0]["vh_in"], 390.0)
        self.assertEqual(eps[0]["vh_out"], 375.0)
        self.assertAlmostEqual(eps[0]["loss"], 15.0)
        self.assertEqual(eps[1]["n"], 1)

    def test_episode_at_window_end_uses_last_row(self):
        rows = [row(0.00, 0, og=0, vh=400.0), row(0.01, 5, og=1, vh=390.0)]
        eps = TA.ground_episodes(rows, 0, 1)
        self.assertEqual(len(eps), 1)
        self.assertEqual(eps[0]["vh_out"], 390.0)   # no exit row: clamp


class TestBands(unittest.TestCase):
    def test_boundaries(self):
        self.assertEqual(TA.band_of(554.5), "lucky")
        self.assertEqual(TA.band_of(526.0), "lucky")
        self.assertEqual(TA.band_of(525.9), "near")
        self.assertEqual(TA.band_of(490.0), "near")
        self.assertEqual(TA.band_of(489.9), "mid")
        self.assertEqual(TA.band_of(450.0), "mid")
        self.assertEqual(TA.band_of(449.9), "deep")
        self.assertEqual(TA.band_of(None), "none")


class TestSignedErr(unittest.TestCase):
    def test_wraps(self):
        self.assertAlmostEqual(TA.signed_err(170.0, -170.0), -20.0)
        self.assertAlmostEqual(TA.signed_err(-170.0, 170.0), 20.0)
        self.assertAlmostEqual(TA.signed_err(10.0, 350.0), 20.0)


class TestAnalyzeGuard(unittest.TestCase):
    """analyze must refuse to write an empty band summary (Codex P2 on
    PR #112): a missing/empty features.jsonl — analyze before trace, an
    interrupted trace, or a mistyped --out pointing at the committed
    evidence dir — must fail fast, never clobber band-summary.json."""

    def test_missing_features_fails_fast_and_writes_nothing(self):
        import tempfile
        d = Path(tempfile.mkdtemp())
        sentinel = d / "band-summary.json"
        sentinel.write_text('{"keep": "me"}')
        with self.assertRaises(SystemExit):
            TA.analyze(d)
        self.assertEqual(sentinel.read_text(), '{"keep": "me"}')

    def test_empty_features_file_also_fails(self):
        import tempfile
        d = Path(tempfile.mkdtemp())
        (d / "features.jsonl").write_text("")
        with self.assertRaises(SystemExit):
            TA.analyze(d)
        self.assertFalse((d / "band-summary.json").exists())


if __name__ == "__main__":
    unittest.main()
