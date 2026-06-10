"""Gate behavior of the dm3 SNG->RL scorer + one-command wrapper.

Locks the two Codex PR #58 findings:
  * verify_route.py must exit NONZERO when no route attempt is scored
    ("never run blind": a trace that never reaches the SNG start pad is a
    measurement failure, not a scored run).
  * run_dm3.py must default to the replay-backed controller
    (--moveprobe-mode 21); the lab's own default (mode 0 = off) would
    silently ignore the uploaded replay and measure plain Frogbot.
"""

import csv
import shutil
import subprocess
import sys
import unittest
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
RUNS = REPO / "artifacts" / "lab-runs"

sys.path.insert(0, str(SCRIPTS))
import run_dm3  # noqa: E402

TRACE_FIELDS = ["t", "x", "y", "z", "vh", "onground", "over_void", "dist_to_rl"]
SNG = (-895.0, -129.0)


def write_trace(run_id, rows):
    run_dir = RUNS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    with open(run_dir / "trace.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=TRACE_FIELDS)
        w.writeheader()
        w.writerows(rows)
    return run_dir


def run_scorer(run_id):
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "verify_route.py"), run_id],
        cwd=REPO, capture_output=True, text=True,
    )


class TestVerifyRouteGate(unittest.TestCase):
    def setUp(self):
        self.run_id = f"_test_gate_{uuid.uuid4().hex[:8]}"

    def tearDown(self):
        shutil.rmtree(RUNS / self.run_id, ignore_errors=True)

    def test_no_attempt_exits_nonzero(self):
        # Origin stream that never reaches the SNG start pad (e.g. wrong
        # map/mode or failed spawn) -> zero scoreable segments -> must fail.
        rows = [
            {"t": i / 100.0, "x": 1000.0 + i, "y": 1000.0, "z": 0.0,
             "vh": 100.0, "onground": 1, "over_void": 0, "dist_to_rl": 2000.0}
            for i in range(50)
        ]
        write_trace(self.run_id, rows)
        out = run_scorer(self.run_id)
        self.assertNotEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("no route attempt scored", out.stderr)

    def test_scored_attempt_exits_zero(self):
        # A minimal attempt: starts on the SNG pad, walks off it. Scores as a
        # (failed) attempt -- but it IS scored, so the exit code is 0.
        rows = [
            {"t": i / 100.0, "x": SNG[0] + 4.0 * i, "y": SNG[1], "z": 0.0,
             "vh": 200.0, "onground": 1, "over_void": 0, "dist_to_rl": 2400.0}
            for i in range(60)
        ]
        write_trace(self.run_id, rows)
        out = run_scorer(self.run_id)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("BEST attempt", out.stdout)


class TestRunDm3Defaults(unittest.TestCase):
    def test_default_is_replay_backed_mode_21(self):
        cmd = run_dm3.build_cmd([])
        i = cmd.index("--moveprobe-mode")
        self.assertEqual(cmd[i + 1], "21")
        self.assertIn("--replay-cmds", cmd)

    def test_explicit_mode_not_overridden(self):
        cmd = run_dm3.build_cmd(["--moveprobe-mode", "22"])
        self.assertEqual(cmd.count("--moveprobe-mode"), 1)
        i = cmd.index("--moveprobe-mode")
        self.assertEqual(cmd[i + 1], "22")


if __name__ == "__main__":
    unittest.main()
