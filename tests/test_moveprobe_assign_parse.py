"""LD-F1 (#95): FBMOVEPROBE_ASSIGN / FBMOVEPROBE_PERSLOT_ERROR parsing.

The sample rows below are rendered exactly per the C format strings the
per-slot KTX patch emits (see frogbot-moveprobe-perslot.patch);
test_perslot_moveprobe_patch.py asserts those literals stay in the patch, so
the C emitter and this parser cannot drift apart without a test failing.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from moveprobe_parse import (
    parse_moveprobe_assign_line,
    parse_moveprobe_assign_logs,
    parse_moveprobe_perslot_error_logs,
)


ASSIGN_SLOT_ROW = (
    "FBMOVEPROBE_ASSIGN time=12.250 ed=3 name=/ goldenboy mode=21 mode_src=slot "
    "replay_file=dm3_sng_to_rl.cmds replay_src=slot fixed_goal=42 goal_src=global "
    "spawn_origin=100.0,200.0,-24.0 spawn_src=slot"
)

ASSIGN_GLOBAL_ROW = (
    "FBMOVEPROBE_ASSIGN time=20.500 ed=4 name=/ bro mode=21 mode_src=global "
    "replay_file=dm3_hilljump.cmds replay_src=slot fixed_goal=0 goal_src=global "
    "spawn_origin=- spawn_src=global"
)

ERROR_ROW = (
    "FBMOVEPROBE_PERSLOT_ERROR time=30.125 ed=4 name=/ bro param=replay_file "
    "value=nonexistent.cmds reason=replay_load_failed"
)


class ParseAssignLineTests(unittest.TestCase):
    def test_per_slot_assignment_row(self) -> None:
        row = parse_moveprobe_assign_line(ASSIGN_SLOT_ROW)
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["time_s"], 12.25)
        self.assertEqual(row["ed"], 3)
        self.assertEqual(row["name"], "/ goldenboy")
        self.assertEqual(row["mode"], 21)
        self.assertEqual(row["mode_src"], "slot")
        self.assertEqual(row["replay_file"], "dm3_sng_to_rl.cmds")
        self.assertEqual(row["replay_src"], "slot")
        self.assertEqual(row["fixed_goal"], 42)
        self.assertEqual(row["goal_src"], "global")
        self.assertEqual(row["spawn_origin"], "100.0,200.0,-24.0")
        self.assertEqual(row["spawn_src"], "slot")

    def test_unset_fields_become_none(self) -> None:
        row = parse_moveprobe_assign_line(ASSIGN_GLOBAL_ROW)
        assert row is not None
        self.assertIsNone(row["spawn_origin"])
        self.assertEqual(row["spawn_src"], "global")
        self.assertEqual(row["mode_src"], "global")

    def test_screen_log_prefix_is_tolerated(self) -> None:
        # screen.log lines carry arbitrary prefixes; the regex must .search().
        row = parse_moveprobe_assign_line("[28599] " + ASSIGN_SLOT_ROW)
        assert row is not None
        self.assertEqual(row["ed"], 3)

    def test_non_assign_line_returns_none(self) -> None:
        self.assertIsNone(parse_moveprobe_assign_line("FBMOVEPROBE_CMD time=1 ed=2"))
        self.assertIsNone(parse_moveprobe_assign_line(""))

    def test_two_bots_two_routes_same_log(self) -> None:
        # The LD-F1 acceptance shape: two bots, two different route files.
        log = ASSIGN_SLOT_ROW + "\n" + ASSIGN_GLOBAL_ROW + "\nnoise line\n"
        rows = parse_moveprobe_assign_logs(log)
        self.assertEqual(len(rows), 2)
        self.assertNotEqual(rows[0]["replay_file"], rows[1]["replay_file"])
        self.assertEqual({r["ed"] for r in rows}, {3, 4})


class ParsePerSlotErrorTests(unittest.TestCase):
    def test_error_row(self) -> None:
        errors = parse_moveprobe_perslot_error_logs("prefix " + ERROR_ROW + "\n")
        self.assertEqual(len(errors), 1)
        err = errors[0]
        self.assertEqual(err["time_s"], 30.125)
        self.assertEqual(err["ed"], 4)
        self.assertEqual(err["name"], "/ bro")
        self.assertEqual(err["param"], "replay_file")
        self.assertEqual(err["value"], "nonexistent.cmds")
        self.assertEqual(err["reason"], "replay_load_failed")

    def test_comma_folded_value(self) -> None:
        # The C side folds whitespace to commas so the value stays one token.
        line = (
            "FBMOVEPROBE_PERSLOT_ERROR time=5.000 ed=3 name=/ goldenboy "
            "param=spawn_origin value=100,abc reason=bad_origin_triplet"
        )
        errors = parse_moveprobe_perslot_error_logs(line)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["value"], "100,abc")
        self.assertEqual(errors[0]["reason"], "bad_origin_triplet")

    def test_no_rows(self) -> None:
        self.assertEqual(parse_moveprobe_perslot_error_logs("nothing here\n"), [])


class WriteAssignLogsTests(unittest.TestCase):
    def test_writer_produces_latest_assignments_and_errors(self) -> None:
        import run_frobodm2_lab as runner

        earlier = ASSIGN_SLOT_ROW.replace("time=12.250", "time=2.000").replace(
            "mode=21 mode_src=slot", "mode=0 mode_src=global"
        )
        log = "\n".join([earlier, ASSIGN_SLOT_ROW, ASSIGN_GLOBAL_ROW, ERROR_ROW]) + "\n"
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "screen.log").write_text(log, encoding="utf-8")
            summary = runner.write_moveprobe_assign_logs(run_dir)

            self.assertEqual(summary["assignment_count"], 3)
            self.assertEqual(summary["perslot_error_count"], 1)
            latest = {
                (row["ed"], row["name"]): row for row in summary["latest_assignments"]
            }
            self.assertEqual(len(latest), 2)
            # The later row for ed 3 wins over the earlier one.
            self.assertEqual(latest[(3, "/ goldenboy")]["mode"], 21)
            self.assertEqual(latest[(3, "/ goldenboy")]["mode_src"], "slot")

            on_disk = json.loads(
                (run_dir / "moveprobe-assignments.json").read_text(encoding="utf-8")
            )
            self.assertEqual(on_disk["assignment_count"], 3)
            md = (run_dir / "moveprobe-assignments.md").read_text(encoding="utf-8")
            self.assertIn("dm3_sng_to_rl.cmds", md)
            self.assertIn("dm3_hilljump.cmds", md)
            self.assertIn("Per-slot loud failures", md)
            self.assertIn("replay_load_failed", md)

    def test_writer_empty_log(self) -> None:
        import run_frobodm2_lab as runner

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "screen.log").write_text("no rows\n", encoding="utf-8")
            summary = runner.write_moveprobe_assign_logs(run_dir)
            self.assertEqual(summary["assignment_count"], 0)
            self.assertEqual(summary["perslot_error_count"], 0)
            md = (run_dir / "moveprobe-assignments.md").read_text(encoding="utf-8")
            self.assertIn("No `FBMOVEPROBE_ASSIGN` lines found", md)


if __name__ == "__main__":
    unittest.main()
