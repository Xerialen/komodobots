"""run_pmove_validation default inputs must resolve from a clean checkout
(Codex PR #60 P2): human cmds fall back to the committed sng_to_rl evidence,
the default botlog falls back to the committed gzipped 2148 log, and a
NON-default missing botlog is a hard error (never silently swapped for the
committed one -- every run dir has a moveprobe-commands.json).
"""

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import run_pmove_validation as rpv  # noqa: E402


class TestPmoveValidationInputs(unittest.TestCase):
    def test_committed_botlog_evidence_exists(self):
        self.assertTrue(rpv.COMMITTED_BOTLOG_GZ.exists())

    def test_default_cmds_resolves(self):
        p = rpv.resolve_cmds("artifacts/replay/dm3_sng_to_rl.cmds")
        self.assertTrue(p.exists())

    def test_cmds_falls_back_to_evidence_when_artifacts_absent(self):
        with mock.patch.object(Path, "exists",
                               lambda self: "artifacts" not in str(self)):
            p = rpv.resolve_cmds("artifacts/replay/dm3_sng_to_rl.cmds")
        self.assertIn("evidence", str(p))
        self.assertTrue(p.exists())

    def test_default_botlog_resolves_and_parses(self):
        p = rpv.resolve_botlog(rpv.DEFAULT_BOTLOG)
        self.assertTrue(p.exists())
        with open(p) as fh:
            first = fh.readline()
        self.assertTrue(first.strip(), "decompressed/located botlog is empty")

    def test_nondefault_missing_botlog_is_hard_error(self):
        with self.assertRaises(SystemExit):
            rpv.resolve_botlog("artifacts/lab-runs/_no_such_run/moveprobe-commands.json")


if __name__ == "__main__":
    unittest.main()
