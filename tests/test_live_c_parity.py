#!/usr/bin/env python3
"""C<->Python byte-match parity gate (bot-program T0.3 -- docs/18 wall #2).

T0.3 gives KTX a "live mode" that, in C, computes the world-view and talks to the
MoveMLP sidecar over the T0.2 POSIX-shm transport. For that to be safe the C side
must agree with the Python source of truth BIT-FOR-BIT:

  * the 6 world-view features      == scripts/move_world_view.py:state_features
  * the shm layout + odd/even seqlock + VIEW/MOVE records
                                    == scripts/move_policy_sidecar.py

This test compiles the standalone C unit (experiments/ktx_moveprobe/live/*.c) and
drives it against the Python modules over a shared /dev/shm region in BOTH
production directions:

  * C writes the VIEW (KTX writer role)  -> Python read_view decodes == inputs
  * Python writes the MOVE (sidecar role) -> C read_move decodes == inputs

plus a feature-parity grid (exact at f32 wire precision) and deterministic
seqlock-retry checks. This is the CI gate that makes train/serve skew impossible
before any KTX wiring lands (PR-B).

Skips cleanly (does NOT fail) only when no C compiler is present -- the
test_physent_collision.py "skip if a dep is absent" pattern. GitHub's
ubuntu-latest runner has cc, so this runs as a real gate in CI.

Run locally:  python3 -m unittest tests.test_live_c_parity -v
"""
from __future__ import annotations

import os
import struct
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))  # tests/ for _live_c_harness
sys.path.insert(0, str(ROOT / "scripts"))

import move_policy_sidecar as sc  # noqa: E402
import move_world_view as mwv  # noqa: E402

# The C compile harness + f32-bit helper are shared with
# tests/test_golden_vector_parity.py so the two world-view parity gates build and
# invoke the C unit through one contract (no drift). See tests/_live_c_harness.py;
# it cleans up its build tmpdir via atexit.
from _live_c_harness import (  # noqa: E402
    f32_bits as _f32_bits,
    require_harness as _require_harness,
    run as _run,
)


def _unique_name(tag: str) -> str:
    return f"komodo_t03_parity_{tag}_{os.getpid()}_{int(time.time() * 1e6) % 1_000_000}"


# A grid that hits the parity-fragile regions: negative yaw + wrap boundaries
# (exercises wrap180's floored modulo, where C fmod would diverge), the moving
# epsilon, standstill (heading undefined), steep pitch, and overspeed.
def _feature_grid():
    states = []
    vxs = [-700.0, -320.0, -100.0, -1.0, 0.0, 0.7, 1.0, 100.0, 320.0, 700.0]
    vys = [-321.0, -50.0, 0.0, 50.0, 321.0]
    vzs = [-200.0, 0.0, 250.0]
    yaws = [-180.0, -179.5, -90.0, -1.0, 0.0, 1.0, 90.0, 179.5, 180.0, 270.0, -271.0]
    pitches = [-90.0, -30.0, 0.0, 30.0, 88.0]
    # full product is large; stride the slow axes to keep it a few thousand rows
    for vx in vxs:
        for vy in vys:
            for vz in vzs:
                for yaw in yaws:
                    for pitch in pitches:
                        states.append((vx, vy, vz, yaw, pitch))
    return states


class TestLayoutConstants(unittest.TestCase):
    def setUp(self):
        _require_harness(self)

    def test_c_sizes_match_sidecar(self):
        fields = dict(tok.split("=") for tok in _run("sizes").split())
        self.assertEqual(int(fields["VIEW_BODY"]), sc.VIEW_BODY_SIZE)
        self.assertEqual(int(fields["MOVE_BODY"]), sc.MOVE_BODY_SIZE)
        self.assertEqual(int(fields["VIEW_SLOT"]), sc.VIEW_SLOT_SIZE)
        self.assertEqual(int(fields["MOVE_SLOT"]), sc.MOVE_SLOT_SIZE)
        self.assertEqual(int(fields["VIEW_BLOCK"]), sc.VIEW_BLOCK_SIZE)
        self.assertEqual(int(fields["MOVE_BLOCK"]), sc.MOVE_BLOCK_SIZE)
        self.assertEqual(int(fields["REGION"]), sc.REGION_SIZE)
        self.assertEqual(int(fields["FEATURE_DIM"]), mwv.FEATURE_DIM)
        self.assertEqual(int(fields["MAX_SLOTS"]), sc.MAX_SLOTS)


class TestFeatureParity(unittest.TestCase):
    def setUp(self):
        _require_harness(self)

    def test_features_match_python_at_f32_on_grid(self):
        states = _feature_grid()
        stdin = "".join(f"{vx} {vy} {vz} {yaw} {pitch}\n"
                        for (vx, vy, vz, yaw, pitch) in states)
        out_lines = _run("features_batch", stdin=stdin).splitlines()
        self.assertEqual(len(out_lines), len(states),
                         "harness produced one line per grid row")
        mismatches = 0
        first = None
        for st, line in zip(states, out_lines):
            c_bits = [int(tok, 16) for tok in line.split()]
            py_bits = [_f32_bits(v) for v in mwv.state_features(*st)]
            if c_bits != py_bits:
                mismatches += 1
                if first is None:
                    first = (st, c_bits, py_bits)
        detail = ("" if first is None else
                  f"; first at state={first[0]} C={first[1]} PY={first[2]}")
        self.assertEqual(mismatches, 0,
                         f"{mismatches}/{len(states)} feature mismatches{detail}")

    def test_wrap180_negative_branch_specifically(self):
        # A left-of-heading look: velocity heading ~45 deg, view yaw 0 -> the
        # (yaw - vhead) fed to wrap180 is negative, the exact case C fmod would
        # get wrong. Pin it independently of the grid.
        st = (100.0, 100.0, 0.0, 0.0, 0.0)
        c_bits = [int(t, 16) for t in _run("features", *map(str, st)).split()]
        py_bits = [_f32_bits(v) for v in mwv.state_features(*st)]
        self.assertEqual(c_bits, py_bits)


class TestViewInterop(unittest.TestCase):
    """C writes the VIEW (KTX role) -> Python read_view (sidecar role) decodes."""

    def setUp(self):
        _require_harness(self)
        self.name = _unique_name("view")
        sc.create_region(self.name).close()

    def tearDown(self):
        sc.unlink_region(self.name)

    def test_c_written_view_reads_back_in_python(self):
        st = (240.0, 180.0, 90.0, 30.0, -5.0)
        slot, req = 2, 4242
        _run("write_view", self.name, str(slot), str(req), *map(str, st), "1")
        mm = sc.open_region(self.name)
        try:
            got_req, feats, valid = sc.read_view(mm, slot)
        finally:
            mm.close()
        self.assertEqual(got_req, req)
        self.assertTrue(valid)
        py_feats = mwv.state_features(*st)
        self.assertEqual([_f32_bits(a) for a in feats],
                         [_f32_bits(b) for b in py_feats],
                         "C-written VIEW features != Python state_features at f32")

    def test_c_written_view_feats_roundtrip(self):
        # Isolates the shm layout from the feature math: known f32 vector in,
        # same vector out through the Python reader.
        slot, req = 1, 9
        feats = [0.125, -0.5, 0.75, -0.25, 1.0, 0.5]  # exact in binary32
        _run("write_view_feats", self.name, str(slot), str(req),
             *(str(f) for f in feats), "1")
        mm = sc.open_region(self.name)
        try:
            got_req, got, valid = sc.read_view(mm, slot)
        finally:
            mm.close()
        self.assertEqual(got_req, req)
        self.assertTrue(valid)
        self.assertEqual([_f32_bits(a) for a in got], [_f32_bits(b) for b in feats])

    def test_invalid_flag_propagates(self):
        slot, req = 0, 3
        st = (10.0, 0.0, 0.0, 0.0, 0.0)
        _run("write_view", self.name, str(slot), str(req), *map(str, st), "0")
        mm = sc.open_region(self.name)
        try:
            _, _, valid = sc.read_view(mm, slot)
        finally:
            mm.close()
        self.assertFalse(valid)


class TestMoveInterop(unittest.TestCase):
    """Python writes the MOVE (sidecar role) -> C read_move (KTX role) decodes."""

    def setUp(self):
        _require_harness(self)
        self.name = _unique_name("move")
        sc.create_region(self.name).close()

    def tearDown(self):
        sc.unlink_region(self.name)

    def _c_read_move(self, slot):
        toks = _run("read_move", self.name, str(slot)).split()
        return {
            "fresh": int(toks[0]),
            "ans_seq": int(toks[1]),
            "fwd": int(toks[2]),
            "side": int(toks[3]),
            "jump": int(toks[4]),
            "move_bits": [int(toks[5], 16), int(toks[6], 16), int(toks[7], 16)],
        }

    def test_python_written_move_reads_back_in_c(self):
        for slot, (ans, fwd, side, jump) in enumerate(
                [(11, 1, -1, 1), (12, -1, 0, 0), (13, 0, 1, 1), (14, 1, 1, 0)]):
            mm = sc.open_region(self.name)
            try:
                sc.write_move(mm, slot, ans, fwd, side, jump)
            finally:
                mm.close()
            got = self._c_read_move(slot)
            self.assertEqual(got["fresh"], 1, f"slot {slot} read torn")
            self.assertEqual(got["ans_seq"], ans)
            self.assertEqual((got["fwd"], got["side"], got["jump"]), (fwd, side, jump))
            # the sidecar packs move = (fwd*320, side*320, 0.0) as f32
            self.assertEqual(got["move_bits"], [
                _f32_bits(fwd * sc.MOVE_MAG), _f32_bits(side * sc.MOVE_MAG),
                _f32_bits(0.0)])


class TestSeqlockRetry(unittest.TestCase):
    """The C reader honours the odd/even guard protocol the sidecar writes."""

    def setUp(self):
        _require_harness(self)
        self.name = _unique_name("seq")
        sc.create_region(self.name).close()
        self.slot = 1
        self.base = sc._move_base(self.slot)
        self.tail = self.base + 4 + sc.MOVE_BODY_SIZE
        # lay down a consistent record first
        mm = sc.open_region(self.name)
        try:
            sc.write_move(mm, self.slot, 5, 1, -1, 1)
        finally:
            mm.close()

    def tearDown(self):
        sc.unlink_region(self.name)

    def _poke(self, off, val):
        mm = sc.open_region(self.name)
        try:
            struct.pack_into("<I", mm, off, val)
            mm.flush()
        finally:
            mm.close()

    def _fresh(self):
        return int(_run("read_move", self.name, str(self.slot)).split()[0])

    def test_consistent_record_is_fresh(self):
        self.assertEqual(self._fresh(), 1)

    def test_odd_leading_guard_is_not_fresh(self):
        self._poke(self.base, 7)  # writer-in-flight -> reader must retry-fail
        self.assertEqual(self._fresh(), 0)

    def test_mismatched_even_guards_not_fresh(self):
        self._poke(self.base, 8)
        self._poke(self.tail, 6)  # both even but unequal -> torn -> not fresh
        self.assertEqual(self._fresh(), 0)


class TestCreatedRegion(unittest.TestCase):
    """A region CREATED by the C side (KTX owns creation) is sized + seeded
    exactly as the Python sidecar expects to attach to."""

    def setUp(self):
        _require_harness(self)
        self.name = _unique_name("create")

    def tearDown(self):
        sc.unlink_region(self.name)

    def test_c_created_region_attaches_clean_in_python(self):
        out = _run("create", self.name).split()
        self.assertEqual(out[0], "ok")
        self.assertEqual(int(out[1]), sc.REGION_SIZE)
        # the sidecar attaches and sees every slot seeded invalid (no request)
        mm = sc.open_region(self.name)
        try:
            for slot in range(sc.MAX_SLOTS):
                req, _feats, valid = sc.read_view(mm, slot)
                self.assertFalse(valid, f"slot {slot} not seeded invalid")
                self.assertEqual(req, 0)
                mv = sc.read_move(mm, slot)
                self.assertTrue(mv["fresh"])
                self.assertEqual(mv["ans_seq"], 0)
        finally:
            mm.close()


if __name__ == "__main__":
    unittest.main()
