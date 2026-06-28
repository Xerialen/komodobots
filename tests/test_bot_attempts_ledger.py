"""Attempt-ledger emitter tests for scripts/prewar_movecheck.py (#424).

Pure-logic + file-IO contract for the komodobots.bot_attempts.v1 ledger that
indexes every live attempt for the dashboard gallery. Stdlib only — no live
server, no box, no torch.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
# prewar_movecheck imports run_4v4_validation_lab at module load, which needs
# both scripts/ and lab/server/ on the path (the script inserts them itself, but
# the very first import must resolve from here).
for sub in ("scripts", "lab/server"):
    p = str(REPO / sub)
    if p not in sys.path:
        sys.path.insert(0, p)

import prewar_movecheck as pw  # noqa: E402


def freshness_report(*, ok: bool, fractions: dict[int, float], min_fraction: float = 0.5) -> dict:
    """A minimal evaluate_live_freshness-shaped report (only keys the summary reads)."""
    return {
        "ok": ok,
        "min_fraction": min_fraction,
        "slots": {str(slot): {"fraction": frac, "ok": frac >= min_fraction}
                  for slot, frac in fractions.items()},
    }


class FreshnessSummaryTest(unittest.TestCase):
    def test_min_fraction_over_slots_is_the_conservative_summary(self):
        report = freshness_report(ok=True, fractions={1: 0.95, 2: 0.71})
        summary = pw._freshness_summary(report)
        self.assertTrue(summary["ok"])
        self.assertEqual(summary["live_fraction"], 0.71)  # weakest-driven bot
        self.assertEqual(summary["min_fraction"], 0.5)

    def test_no_slots_gives_null_fraction_never_raises(self):
        summary = pw._freshness_summary({"ok": False, "min_fraction": 0.5, "slots": {}})
        self.assertFalse(summary["ok"])
        self.assertIsNone(summary["live_fraction"])

    def test_missing_keys_degrade_to_red_not_crash(self):
        summary = pw._freshness_summary({})
        self.assertFalse(summary["ok"])
        self.assertIsNone(summary["live_fraction"])
        self.assertIsNone(summary["min_fraction"])


class BuildRecordTest(unittest.TestCase):
    def test_green_record_carries_served_watch_url(self):
        rec = pw.build_attempt_record(
            run_id="20260628T120000Z", ts_utc="2026-06-28T12:01:00+00:00",
            map_name="dm3", n_bots=1,
            demo_name="prewar_movecheck_dm3_20260628T120000Z.mvd",
            demo_url="/demos/online/prewar_movecheck_dm3_20260628T120000Z.mvd",
            freshness_report=freshness_report(ok=True, fractions={1: 0.95}),
            verdict_green=True,
            artifact_dir="experiments/prewar-movecheck/20260628T120000Z",
        )
        self.assertEqual(rec["verdict"], "GREEN")
        self.assertEqual(rec["mode"], "prewar-movecheck")
        # The watch URL must use the served /demos/online/ route (the /demos/files/
        # prefix 404s — same regression class as the #259 demo link).
        self.assertTrue(rec["demo"]["url"].startswith("/demos/online/"))
        self.assertNotIn("/demos/files/", rec["demo"]["url"])
        self.assertEqual(rec["demo"]["name"], "prewar_movecheck_dm3_20260628T120000Z.mvd")

    def test_red_attempt_with_no_demo_is_null_not_fabricated(self):
        rec = pw.build_attempt_record(
            run_id="r2", ts_utc="2026-06-28T12:05:00+00:00", map_name="dm3", n_bots=2,
            demo_name=None, demo_url=None,
            freshness_report=freshness_report(ok=False, fractions={1: 0.2, 2: 0.1}),
            verdict_green=False, artifact_dir="experiments/prewar-movecheck/r2",
        )
        self.assertEqual(rec["verdict"], "RED")
        self.assertIsNone(rec["demo"])  # absence is the accountability signal
        self.assertEqual(rec["n_bots"], 2)


class EmitLedgerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="bot-attempts-"))
        self.ledger = self.tmp / "data" / "bot-attempts.json"

    def _record(self, run_id: str, *, green: bool = True) -> dict:
        return pw.build_attempt_record(
            run_id=run_id, ts_utc=f"2026-06-28T12:00:00+00:00", map_name="dm3", n_bots=1,
            demo_name=f"{run_id}.mvd" if green else None,
            demo_url=f"/demos/online/{run_id}.mvd" if green else None,
            freshness_report=freshness_report(ok=green, fractions={1: 0.9 if green else 0.1}),
            verdict_green=green, artifact_dir=f"experiments/prewar-movecheck/{run_id}",
        )

    def test_creates_ledger_with_schema_and_one_attempt(self):
        out = pw._emit_attempt_ledger(self.ledger, self._record("run1"), map_name="dm3")
        self.assertEqual(out["schema"], "komodobots.bot_attempts.v1")
        self.assertEqual(out["map"], "dm3")
        self.assertEqual(len(out["attempts"]), 1)
        # Persisted to disk identically.
        on_disk = json.loads(self.ledger.read_text(encoding="utf-8"))
        self.assertEqual(on_disk, out)

    def test_append_is_newest_first_and_preserves_prior(self):
        pw._emit_attempt_ledger(self.ledger, self._record("run1"), map_name="dm3")
        out = pw._emit_attempt_ledger(self.ledger, self._record("run2"), map_name="dm3")
        self.assertEqual([a["run_id"] for a in out["attempts"]], ["run2", "run1"])

    def test_corrupt_ledger_is_replaced_not_fatal(self):
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        self.ledger.write_text("{ this is not json", encoding="utf-8")
        out = pw._emit_attempt_ledger(self.ledger, self._record("run1"), map_name="dm3")
        self.assertEqual(len(out["attempts"]), 1)
        self.assertEqual(out["schema"], "komodobots.bot_attempts.v1")


if __name__ == "__main__":
    unittest.main()
