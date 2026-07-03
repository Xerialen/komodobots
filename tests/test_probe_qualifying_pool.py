"""Gating stdlib tests for scripts/probe_qualifying_pool.py (plans/instrument-pool-growth.md).

Locks (1) the qualifying-window semantics against adversarial fixtures — the probe must mirror
`ml/eval_broad_closedloop.select_start_segments` (episode >= horizon+1; STRIDE-horizon scan, not
sliding; first window of horizon+1 ticks with >= mv1_min_ticks airborne-moving; one per episode);
(2) the thresholds' single source (imported from scripts/gmv_believability, never re-declared);
(3) a light textual mirror on the eval's own rule so a future eval-side change trips this floor
(the eval module is torch-loaded and cannot be imported here); (4) the exit-code guard.
"""

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import probe_qualifying_pool as PB  # noqa: E402
from gmv_believability import DEFAULT_THRESHOLDS  # noqa: E402


class TestWindowSemantics(unittest.TestCase):
    H = 10          # small horizon keeps fixtures readable; the rule is size-agnostic
    NEED = 4        # min airborne-moving ticks per window (stand-in for mv1_min_ticks)

    def q(self, flags):
        return PB.episode_qualifies(flags, self.H, self.NEED)

    def test_too_short_never_qualifies(self):
        self.assertFalse(self.q([True] * self.H))          # needs horizon+1

    def test_first_window_qualifies(self):
        self.assertTrue(self.q([True] * (self.H + 1)))

    def test_threshold_boundary(self):
        flags = [True] * self.NEED + [False] * (self.H + 1 - self.NEED)
        self.assertTrue(self.q(flags))                      # exactly NEED -> qualifies
        flags = [True] * (self.NEED - 1) + [False] * (self.H + 2 - self.NEED)
        self.assertFalse(self.q(flags))                     # NEED-1 -> not

    def test_stride_scan_not_sliding(self):
        # 21 ticks: window0 = [0..11) has 3 (< NEED); the STRIDE jumps to start=10 ->
        # window1 = [10..21) holds 4 -> qualifies. A SLIDING scan would already have
        # qualified earlier; a single-window scan would have missed it entirely.
        flags = [False] * 7 + [True] * 3 + [False] * 3 + [True] * 4 + [False] * 4
        self.assertEqual(len(flags), 21)
        self.assertTrue(self.q(flags))
        # trailing ticks that only a NON-stride start could reach must NOT count:
        # 20 ticks, all qualifying ticks in [12..16) — window0 [0..11) has 0, and
        # start=10 needs 21 ticks -> no second window -> not qualifying.
        flags = [False] * 12 + [True] * 4 + [False] * 4
        self.assertEqual(len(flags), 20)
        self.assertFalse(self.q(flags))

    def test_eval_rule_textual_mirror(self):
        # the probe cannot import the torch-loaded eval; lock the rule's SHAPE in its source
        # text instead (utf-8 — the Windows floor's default codec would die on this file).
        src = (REPO_ROOT / "ml" / "eval_broad_closedloop.py").read_text(encoding="utf-8")
        for token in ("len(ticks) < horizon + 1",
                      "ticks[start:start + horizon + 1]",
                      "start += horizon"):
            self.assertIn(token, src,
                          "select_start_segments' window rule changed — update the probe "
                          "(scripts/probe_qualifying_pool.py) in the same PR")

    def test_thresholds_single_source(self):
        self.assertIn("mv1_min_ticks", DEFAULT_THRESHOLDS)
        self.assertIn("mv1_min_hspeed_qu_per_s", DEFAULT_THRESHOLDS)


class TestProbeOnDb(unittest.TestCase):
    def _db(self, td):
        db = Path(td) / "cat.sqlite"
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE episodes (episode_id INTEGER PRIMARY KEY, split TEXT)")
        con.execute("CREATE TABLE player_ticks (episode_id INTEGER, tick INTEGER, "
                    "onground INTEGER, hspeed REAL)")
        speed = DEFAULT_THRESHOLDS["mv1_min_hspeed_qu_per_s"]
        need = DEFAULT_THRESHOLDS["mv1_min_ticks"]
        h = 385

        def add(eid, split, n_ticks, n_air_moving):
            con.execute("INSERT INTO episodes VALUES (?, ?)", (eid, split))
            rows = [(eid, t, 0 if t < n_air_moving else 1,
                     speed if t < n_air_moving else 0.0) for t in range(n_ticks)]
            con.executemany("INSERT INTO player_ticks VALUES (?, ?, ?, ?)", rows)

        add(1, "val", h + 1, need)          # qualifies exactly at the bar
        add(2, "val", h + 1, need - 1)      # one tick short
        add(3, "val", h, h)                 # too short an episode
        add(4, "train", h + 1, need + 50)   # qualifies in train
        con.commit()
        con.close()
        return db

    def test_counts_and_guard(self):
        with tempfile.TemporaryDirectory() as td:
            db = self._db(td)
            splits = PB.probe(db, 385)
            self.assertEqual(splits["val"]["episodes"], 3)
            self.assertEqual(splits["val"]["qualifying"], 1)
            self.assertEqual(splits["train"]["qualifying"], 1)
            # the pre-registered guard is an EXIT CODE, not prose
            self.assertEqual(PB.main(["--db", str(db), "--require-val", "1"]), 0)
            self.assertEqual(PB.main(["--db", str(db), "--require-val", "2"]), 1)


if __name__ == "__main__":
    unittest.main()
