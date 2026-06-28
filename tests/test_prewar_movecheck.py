"""Recorder evidence-integrity tests for scripts/prewar_movecheck.py (#453).

Two blockers Codex/@Xerialen flagged on PR #453: (1) the demo artifact could be
attributed to the wrong run, (2) the live sidecar's /dev/shm region was not
isolated per run. These lock the fixes. Stdlib only — no live server.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for sub in ("scripts", "lab/server"):
    p = str(REPO / sub)
    if p not in sys.path:
        sys.path.insert(0, p)

import prewar_movecheck as pw  # noqa: E402


class SelectRunDemoTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="demos-"))
        self.run_id = "20260628T120000Z"
        self.demo_name = f"prewar_movecheck_dm3_{self.run_id}"
        self.after = 1_000_000.0  # the run's start.marker mtime

    def _mvd(self, name: str, mtime: float, size: int = 60_000) -> Path:
        p = self.dir / name
        p.write_bytes(b"x" * size)
        os.utime(p, (mtime, mtime))
        return p

    def test_selects_this_runs_demo_ignoring_a_newer_unrelated_one(self):
        # The exact bug: a concurrent unrelated demo, written LATER, must not be
        # picked just because it is the newest *.mvd in the shared dir.
        mine = self._mvd(f"{self.demo_name}.mvd", self.after + 10)
        self._mvd("4on4_frog_vs_leap[dm3]20260628-1201.mvd", self.after + 100)  # newer, unrelated
        self._mvd(f"prewar_movecheck_dm3_20260628T119999Z.mvd", self.after + 99)  # another run, newer
        got = pw.select_run_demo(self.dir, self.demo_name, self.after)
        self.assertEqual(got, mine)

    def test_matches_a_date_suffixed_variant_by_prefix(self):
        # KTX may append k_demoname_date -> match by prefix, not equality.
        suff = self._mvd(f"{self.demo_name}20260628-1200.mvd", self.after + 5)
        got = pw.select_run_demo(self.dir, self.demo_name, self.after)
        self.assertEqual(got, suff)

    def test_ignores_pre_existing_stale_and_empty_matches(self):
        self._mvd(f"{self.demo_name}.mvd", self.after - 50)          # older than the run -> stale
        self._mvd(f"{self.demo_name}_empty.mvd", self.after + 5, size=0)  # zero-byte -> not a recording
        self.assertIsNone(pw.select_run_demo(self.dir, self.demo_name, self.after))

    def test_none_when_run_produced_nothing(self):
        self._mvd("ffa_4[dm3]20260628-1200.mvd", self.after + 5)  # someone else's demo only
        self.assertIsNone(pw.select_run_demo(self.dir, self.demo_name, self.after))


class DefaultShmNameTest(unittest.TestCase):
    def test_is_per_port_and_per_run(self):
        a = pw.default_shm_name(28599, "20260628T120000Z")
        b = pw.default_shm_name(28600, "20260628T120000Z")  # different port
        c = pw.default_shm_name(28599, "20260628T120500Z")  # different run
        self.assertEqual(len({a, b, c}), 3, "two concurrent runs must not share an shm region")

    def test_not_the_old_shared_constant(self):
        name = pw.default_shm_name(28599, "20260628T120000Z")
        self.assertNotEqual(name, "komodo_move_t07_prewar")
        self.assertTrue(name.startswith("komodo_move_prewar_"))
        self.assertIn("28599", name)


if __name__ == "__main__":
    unittest.main()
