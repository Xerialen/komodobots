#!/usr/bin/env python3
"""Dynamic real-demo world-view parity gate (bot-program T0.5 -- docs/18 wall #2, #210).

The synthetic grid in tests/test_live_c_parity.py proves C == Python over a
worst-case parameter sweep. This gate proves it over the REAL per-tick
(vx,vy,vz,yaw,pitch) a human produced in a committed dm3 demo, and LOCKS the
expected 6 features as a golden fixture -- so any change to the world-view formula
(or the demo) becomes a deliberate, reviewed re-bake instead of silent train/serve
skew. It also pins the offline builder's .cmds column reading to the feature
formula, so "the columns the dataset builder reads" and "the features the policy
trains on" can never drift apart.

All checks are at exact f32 wire precision (no epsilon -- both sides compute in
double then cast the SAME double to f32, so they are provably bit-identical; an
epsilon would only hide the skew-class bug this gate exists to catch):

  * Python state_features over the demo  == committed golden   (no compiler needed)
  * C features_batch over the demo       == committed golden   (skips if no cc)
  * C features_batch                     == Python state_features, row by row
  * fixture header cmds_sha256           == the committed .cmds (demo-swap guard)

Regenerate the golden with:  python scripts/build_golden_vector_fixture.py
Run locally:                 python3 -m unittest tests.test_golden_vector_parity -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))  # tests/ for _live_c_harness
sys.path.insert(0, str(ROOT / "scripts"))                 # scripts/ for the modules

import build_golden_vector_fixture as baker  # noqa: E402
import move_world_view as mwv  # noqa: E402
from _live_c_harness import f32_bits, require_harness, run  # noqa: E402

DEMO = baker.DEFAULT_DEMO
FIXTURE = ROOT / "tests" / "fixtures" / "golden_vector_parity.tsv"
STALE = ("tests/fixtures/golden_vector_parity.tsv is stale -- rerun "
         "`python scripts/build_golden_vector_fixture.py` and commit")


def _parse_fixture(path: Path):
    """-> (header_fields dict, [(row_idx, [6 int feature-bits]), ...])."""
    header: dict[str, str] = {}
    rows = []
    for ln in path.read_text().splitlines():
        if not ln.strip():
            continue
        if ln.startswith("#"):
            for tok in ln.lstrip("# ").split():
                if "=" in tok:
                    k, v = tok.split("=", 1)
                    header[k] = v
            continue
        p = ln.split("\t")
        rows.append((int(p[0]), [int(t, 16) for t in p[2:8]]))
    return header, rows


def _demo_states():
    return [st for _idx, _msec, st in baker.read_cmds_states(DEMO)]


def _features_batch_stdin(states):
    return "".join("{} {} {} {} {}\n".format(*st) for st in states)


class TestGoldenVectorParity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.header, cls.golden = _parse_fixture(FIXTURE)
        cls.states = _demo_states()

    def test_fixture_nontrivial_and_aligned(self):
        self.assertGreater(len(self.golden), 50, "golden fixture suspiciously small")
        self.assertEqual(len(self.golden), len(self.states),
                         f"golden rows ({len(self.golden)}) != demo rows "
                         f"({len(self.states)}); {STALE}")

    def test_python_matches_committed_golden(self):
        # Independent of the baker: recompute from the canonical module and lock
        # against the committed bytes. A move_world_view.py change fails here.
        for (idx, gbits), st in zip(self.golden, self.states):
            py = [f32_bits(v) for v in mwv.state_features(*st)]
            self.assertEqual(py, gbits, f"row {idx} state={st} Python != golden; {STALE}")

    def test_fixture_header_sha_matches_committed_cmds(self):
        self.assertEqual(self.header.get("cmds_sha256"),
                         baker.normalized_sha256(DEMO),
                         f"the demo .cmds changed; {STALE}")

    def test_c_matches_committed_golden(self):
        require_harness(self)
        out = run("features_batch", stdin=_features_batch_stdin(self.states)).splitlines()
        self.assertEqual(len(out), len(self.golden), "C produced one line per demo row")
        for (idx, gbits), line in zip(self.golden, out):
            cbits = [int(t, 16) for t in line.split()]
            self.assertEqual(cbits, gbits, f"row {idx} C != golden; {STALE}")

    def test_c_matches_python_on_demo_rows(self):
        require_harness(self)
        out = run("features_batch", stdin=_features_batch_stdin(self.states)).splitlines()
        mismatches = 0
        first = None
        for st, line in zip(self.states, out):
            cbits = [int(t, 16) for t in line.split()]
            pybits = [f32_bits(v) for v in mwv.state_features(*st)]
            if cbits != pybits:
                mismatches += 1
                if first is None:
                    first = (st, cbits, pybits)
        detail = "" if first is None else f"; first at state={first[0]} C={first[1]} PY={first[2]}"
        self.assertEqual(mismatches, 0,
                         f"{mismatches}/{len(self.states)} C!=Python on demo rows{detail}")


if __name__ == "__main__":
    unittest.main()
