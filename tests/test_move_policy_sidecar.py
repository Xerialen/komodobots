#!/usr/bin/env python3
"""Policy-sidecar tests (bot-program T0.6 -- docs/18 wall #1 "Live brain pipe").

Proves the two T0.6 done-when criteria:

  1. TRANSPORT ROUND-TRIP (stdlib only -> runs on the CI floor): a mock KTX
     writer publishes a per-slot world-view into the T0.2 POSIX-shm region; the
     sidecar reads it, computes the move, and writes it back; the mock reader
     reads the move through the per-slot seqlock. Asserted across all 4 slots,
     including under a concurrent writer process (no torn reads) and the
     valid/freshness gating.

  2. ARGMAX PARITY with eval_closedloop:
     - STRUCTURAL (always runs, no torch): the sidecar and eval_closedloop share
       the SAME argmax decode (move_policy_sidecar.move_argmax_from_logits
       reproduces policy_step_action's `argmax-1 / argmax-1 / argmax`) and the
       SAME world-view (move_world_view.state_features). A local re-implementation
       of policy_step_action's decode is checked against the sidecar helper over
       a logit sweep, so the decode is pinned bit-for-bit without loading torch.
     - NUMERIC (load-on-demand; skips cleanly when torch OR the checkpoint is
       absent, per the test_physent_collision.py pattern): load the real MoveMLP,
       and for a sample of world-view vectors assert the sidecar's chosen move ==
       the move computed by a direct copy of eval_closedloop.policy_step_action
       on the SAME model + SAME input.

Pure stdlib for everything except the opt-in numeric case. Run locally:
    python3 -m unittest tests.test_move_policy_sidecar -v
"""
from __future__ import annotations

import math
import os
import sys
import time
import unittest
from multiprocessing import Event, Process
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import move_policy_sidecar as sc  # noqa: E402
import move_world_view as mwv  # noqa: E402


def _unique_name(tag: str) -> str:
    return f"komodo_t06_test_{tag}_{os.getpid()}_{int(time.time()*1e6) % 1_000_000}"


# Representative world-view vectors (raw state -> features via the shared module,
# so these are exactly what the offline builder produces).
_SAMPLE_STATES = [
    # (vx, vy, vz, yaw, pitch)
    (240.0, 180.0, 90.0, 30.0, -5.0),    # typical strafe-jump
    (0.0, 0.0, 0.0, 45.0, 0.0),          # standstill (heading undefined)
    (320.0, 320.0, -90.0, 10.0, 88.0),   # fast diagonal, steep pitch, falling
    (-100.0, 0.0, 0.0, 179.0, 12.0),     # near angle-wrap boundary
    (1.0, 0.0, 0.0, 0.0, 0.0),           # exactly at the moving epsilon
    (37.5, -200.0, 200.0, -90.0, -30.0),  # slow, rising, looking down-ish
    (700.0, -50.0, -50.0, 134.0, 17.0),  # overspeed
]
_SAMPLE_FEATURES = [mwv.state_features(*s) for s in _SAMPLE_STATES]


# ---------------------------------------------------------------------------
# Reference decode: a LOCAL copy of eval_closedloop.policy_step_action's argmax
# (kept here as the oracle so parity is proven, not assumed). DO NOT replace
# with a call to the sidecar helper -- that would defeat the test.
# ---------------------------------------------------------------------------
def _ref_argmax(xs):
    best_i, best_v = 0, xs[0]
    for i in range(1, len(xs)):
        if xs[i] > best_v:
            best_v, best_i = xs[i], i
    return best_i


def _ref_policy_decode(lf, ls, lj):
    """eval_closedloop.policy_step_action's decode:
        fwd = argmax(lf) - 1; side = argmax(ls) - 1; jump = argmax(lj)."""
    return _ref_argmax(lf) - 1, _ref_argmax(ls) - 1, _ref_argmax(lj)


# ---------------------------------------------------------------------------
# Multiprocessing worker targets, defined at MODULE scope so they are picklable
# under a `spawn`/`forkserver` start method (Python >= 3.14 default on some
# platforms, or any CI/dev that sets it explicitly). A locally-nested target
# cannot be pickled, so `Process.start()` would raise before the test ran.
# Args are passed via Process(args=...).
# ---------------------------------------------------------------------------
def _torn_read_writer(name, stop_evt, iters):
    """Hammer slot 1's VIEW: stamp k into BOTH req_seq and feats[0] so a torn
    pairing is detectable by the reader. Target for the torn-read stress test."""
    mm = sc.open_region(name)
    try:
        for k in range(1, iters + 1):
            feats = [k / 1000.0, 0.123, -0.456, 0.789, 1.0, 0.5]
            sc.write_view(mm, 1, k, feats, valid=True)
    finally:
        mm.close()
    stop_evt.set()


def _run_sidecar_worker(name, stop_evt):
    """Run the real serve_loop with a torch-free stub policy until stopped.
    Target for the live-sidecar round-trip test."""
    sc.serve_loop(name, _stub_move_const, hz=200.0,
                  stop_predicate=stop_evt.is_set)


def _stub_move_const(_feats):
    """A constant move decision (1, -1, 1); picklable module-level stub policy.
    Must be module scope so _run_sidecar_worker can be pickled under spawn."""
    return (1, -1, 1)


# ===========================================================================
# 1. Transport round-trip over the T0.2 shm seqlock
# ===========================================================================
class TestTransportRoundTrip(unittest.TestCase):
    def setUp(self):
        self.name = _unique_name("rt")

    def tearDown(self):
        sc.unlink_region(self.name)

    def test_layout_constants_sane(self):
        # The transport must address every slot inside the region.
        self.assertEqual(sc.VIEW_BLOCK_SIZE, sc.MAX_SLOTS * sc.VIEW_SLOT_SIZE)
        self.assertEqual(sc.MOVE_BLOCK_SIZE, sc.MAX_SLOTS * sc.MOVE_SLOT_SIZE)
        self.assertEqual(sc.REGION_SIZE, sc.VIEW_BLOCK_SIZE + sc.MOVE_BLOCK_SIZE)
        last_move_end = sc._move_base(sc.MAX_SLOTS - 1) + sc.MOVE_SLOT_SIZE
        self.assertLessEqual(last_move_end, sc.REGION_SIZE)
        # action constants match the offline reference
        self.assertEqual(sc.MOVE_MAG, 320.0)
        self.assertEqual(sc.BUTTON_JUMP, 2)

    def test_view_record_roundtrips(self):
        mm = sc.create_region(self.name)
        try:
            feats = _SAMPLE_FEATURES[0]
            sc.write_view(mm, 2, 7, feats, valid=True)
            req, got, valid = sc.read_view(mm, 2)
            self.assertEqual(req, 7)
            self.assertTrue(valid)
            # f32 storage -> compare at single precision tolerance
            for a, b in zip(got, feats):
                self.assertAlmostEqual(a, b, places=5)
        finally:
            mm.close()

    def test_invalid_view_is_skipped(self):
        mm = sc.create_region(self.name)
        try:
            # fresh region: all views seeded invalid -> nothing to answer
            answered = sc.serve_once(mm, lambda f: (1, 1, 1))
            self.assertEqual(answered, 0)
        finally:
            mm.close()

    def test_full_4slot_roundtrip_with_stub_policy(self):
        """Mock writer -> sidecar -> mock reader, all 4 slots, move survives."""
        def stub(feats):
            fwd = 1 if feats[0] > 0.3 else (-1 if feats[0] < 0.05 else 0)
            side = 1 if feats[2] > 0.2 else (-1 if feats[2] < -0.2 else 0)
            jump = 1 if feats[1] > 0.5 else 0
            return fwd, side, jump

        sc.create_region(self.name)
        with sc.MockKtxWriter(self.name) as ktx:
            # publish a distinct world-view per slot
            reqs = {}
            for slot in range(sc.MAX_SLOTS):
                st = _SAMPLE_STATES[slot]
                reqs[slot] = ktx.publish_state(slot, *st)

            # sidecar services every slot once
            mm = sc.open_region(self.name)
            try:
                answered = sc.serve_once(mm, stub)
            finally:
                mm.close()
            self.assertEqual(answered, sc.MAX_SLOTS)

            # mock reader pulls each move back through the seqlock and checks it
            for slot in range(sc.MAX_SLOTS):
                mv = ktx.await_answer(slot, reqs[slot], timeout=0.5)
                self.assertIsNotNone(mv, f"slot {slot} never answered")
                exp = stub(mwv.state_features(*_SAMPLE_STATES[slot]))
                self.assertEqual((mv["fwd"], mv["side"], mv["jump"]), exp)
                self.assertEqual(mv["ans_seq"], reqs[slot])
                # move floats reflect the +/-320 scaling + jump bit
                self.assertAlmostEqual(mv["move"][0], exp[0] * sc.MOVE_MAG, places=4)
                self.assertAlmostEqual(mv["move"][1], exp[1] * sc.MOVE_MAG, places=4)
                self.assertEqual(mv["buttons"], sc.BUTTON_JUMP if exp[2] else 0)

    def test_freshness_gate_skips_already_answered(self):
        """A slot whose req_seq has not advanced is not re-answered."""
        sc.create_region(self.name)
        with sc.MockKtxWriter(self.name) as ktx:
            ktx.publish_state(0, *_SAMPLE_STATES[0])
            mm = sc.open_region(self.name)
            try:
                last = [-1] * sc.MAX_SLOTS
                self.assertEqual(sc.serve_once(mm, lambda f: (1, 0, 0), last), 1)
                # nothing new published -> second pass answers nothing
                self.assertEqual(sc.serve_once(mm, lambda f: (1, 0, 0), last), 0)
                # new request -> answered again
                ktx.publish_state(0, *_SAMPLE_STATES[2])
                self.assertEqual(sc.serve_once(mm, lambda f: (1, 0, 0), last), 1)
            finally:
                mm.close()

    def test_no_torn_read_under_concurrent_writer(self):
        """A separate process hammers a slot's VIEW; reads are never torn.

        This is the regression guard for the seqlock write/read protocol. The
        body is written by a non-atomic cross-process memcpy, so a reader can
        catch it mid-write; the seqlock must guarantee that any *accepted* read
        is internally consistent (the whole body belongs to a single write). The
        writer encodes its iteration k BOTH into req_seq AND into feats[0]
        (== k/1000), so a consistent read must have feats[0]*1000 == req_seq
        (within f32 rounding); a torn read pairs feats[0] from one write with a
        req_seq from another (or the zero seed) -> the assertion fires.

        The earlier writer set only the LEADING guard odd before mutating the
        body and left the TRAILING guard at its old even value until after the
        body write. A reader that had already loaded the old (even) leading guard
        could then read a half-written body and read the trailing guard while it
        still held the matching old even value -> old_head == old_tail, both even
        -> a torn snapshot was accepted. With N_ITERS below this test detected
        that tear on 12/12 runs against the buggy writer (~0.3 s/run on a 16-core
        box) and passes on every run with the corrected writer (both guards odd
        before the body). Keep the count high: a low count makes the
        writer/reader window too rare and the guard goes flaky.
        """
        sc.create_region(self.name)
        stop = Event()
        # High enough that the writer/reader interleave reliably hits the
        # mid-body window: the pre-fix writer was caught tearing on every run at
        # this count, so the test is a real regression guard, not a no-op.
        n_iters = 300000

        p = Process(target=_torn_read_writer, args=(self.name, stop, n_iters))
        p.start()
        try:
            mm = sc.open_region(self.name)
            try:
                checks = 0
                while not stop.is_set() or checks < 1:
                    req, feats, valid = sc.read_view(mm, 1)
                    if valid and req > 0:
                        # whole body is one write: feats[0] must match req_seq
                        # (f32 of k/1000 rounds within ~1/1000 of k after *1000)
                        self.assertAlmostEqual(
                            feats[0] * 1000.0, float(req), delta=0.51,
                            msg=f"torn read: req_seq={req} feats[0]={feats[0]!r}")
                        # the constant features must be intact too
                        self.assertAlmostEqual(feats[1], 0.123, places=4)
                        self.assertAlmostEqual(feats[3], 0.789, places=4)
                        self.assertAlmostEqual(feats[2], -0.456, places=4)
                        checks += 1
                self.assertGreater(checks, 0)
            finally:
                mm.close()
        finally:
            p.join(timeout=10)
            if p.is_alive():
                p.terminate()

    def test_serve_loop_against_live_mock(self):
        """End-to-end with the real serve_loop running in a background process.

        Uses the module-scope worker + stub policy (picklable under spawn)."""
        sc.create_region(self.name)
        stop = Event()

        p = Process(target=_run_sidecar_worker, args=(self.name, stop))
        p.start()
        try:
            with sc.MockKtxWriter(self.name) as ktx:
                req = ktx.publish_state(3, *_SAMPLE_STATES[2])
                mv = ktx.await_answer(3, req, timeout=2.0)
                self.assertIsNotNone(mv, "live sidecar never answered")
                self.assertEqual((mv["fwd"], mv["side"], mv["jump"]), (1, -1, 1))
        finally:
            stop.set()
            p.join(timeout=5)
            if p.is_alive():
                p.terminate()


# ===========================================================================
# 2a. Argmax parity -- STRUCTURAL (no torch). The decode + world-view are shared.
# ===========================================================================
class TestArgmaxDecodeParity(unittest.TestCase):
    """The sidecar's argmax decode reproduces eval_closedloop's bit-for-bit.

    eval_closedloop.policy_step_action turns the three head logits into
    (fwd, side, jump) via argmax-1 / argmax-1 / argmax. We pin that the sidecar
    helper matches a local copy of that decode over an aggressive logit sweep,
    INCLUDING ties (where argmax must pick the lowest index, as torch does)."""

    def test_decode_matches_reference_on_sweep(self):
        vals = [-3.5, -1.0, -0.0001, 0.0, 0.0001, 0.5, 2.0, 9.9]
        checked = 0
        for a in vals:
            for b in vals:
                for c in vals:
                    lf = [a, b, c]
                    for d in vals:
                        ls = [b, d, a]
                        lj = [c, d]
                        got = sc.move_argmax_from_logits(lf, ls, lj)
                        ref = _ref_policy_decode(lf, ls, lj)
                        self.assertEqual(got, ref,
                                         msg=f"decode mismatch lf={lf} ls={ls} lj={lj}")
                        checked += 1
        self.assertGreater(checked, 1000)

    def test_decode_tie_breaks_to_lowest_index(self):
        # all-equal logits -> argmax picks index 0 (matches torch/numpy)
        self.assertEqual(sc.move_argmax_from_logits([1.0, 1.0, 1.0],
                                                    [2.0, 2.0, 2.0],
                                                    [0.5, 0.5]),
                         (0 - 1, 0 - 1, 0))  # (-1, -1, 0)

    def test_decode_ranges(self):
        # fwd/side land in {-1,0,1}, jump in {0,1}
        for lf in ([5, 0, 0], [0, 5, 0], [0, 0, 5]):
            for lj in ([5, 0], [0, 5]):
                fwd, side, jump = sc.move_argmax_from_logits(lf, [0, 5, 0], lj)
                self.assertIn(fwd, (-1, 0, 1))
                self.assertIn(side, (-1, 0, 1))
                self.assertIn(jump, (0, 1))

    def test_sidecar_and_reference_share_world_view(self):
        # the mock writer builds features via the shared module (no skew)
        name = _unique_name("wv")
        sc.create_region(name)
        try:
            with sc.MockKtxWriter(name) as ktx:
                st = _SAMPLE_STATES[0]
                req = ktx.publish_features(0, mwv.state_features(*st))
                r, feats, valid = sc.read_view(ktx.mm, 0)
                self.assertEqual(req, r)
                for a, b in zip(feats, mwv.state_features(*st)):
                    self.assertAlmostEqual(a, b, places=5)
        finally:
            sc.unlink_region(name)


# ===========================================================================
# 2b. Argmax parity -- NUMERIC against the real MoveMLP (load-on-demand, skips
#     cleanly when torch OR the checkpoint is absent).
# ===========================================================================
def _load_runner():
    """Return a MoveMLPRunner, or None with a reason if it cannot be built.

    Skips (not fails) when torch is missing OR the gitignored checkpoint is
    absent -- the test_physent_collision.py 'skip-clean if data/dep absent'
    pattern. The structural parity above still guarantees the decode is shared.
    """
    try:
        import torch  # noqa: F401
        import numpy  # noqa: F401
    except Exception as e:  # noqa: BLE001
        return None, f"torch/numpy unavailable ({e})"
    try:
        runner = sc.MoveMLPRunner()
    except FileNotFoundError as e:
        return None, f"checkpoint absent ({e})"
    except Exception as e:  # noqa: BLE001  (e.g. CUDA-only assert in train import)
        return None, f"runner build failed ({e})"
    return runner, None


class TestNumericArgmaxParity(unittest.TestCase):
    """The sidecar's move == a direct copy of eval_closedloop.policy_step_action
    on the SAME model + SAME world-view, for a sample of vectors."""

    @classmethod
    def setUpClass(cls):
        cls.runner, cls.reason = _load_runner()

    def setUp(self):
        if self.runner is None:
            self.skipTest(f"numeric MoveMLP parity skipped: {self.reason}; "
                          "structural decode+world-view parity is proven above")

    def _eval_closedloop_move(self, features):
        """Bit-for-bit eval_closedloop.policy_step_action, inlined here as the
        oracle: float32 [1,6] -> model(x) -> argmax-1/argmax-1/argmax."""
        np = self.runner._np
        torch = self.runner._torch
        x = torch.from_numpy(np.asarray([features], dtype=np.float32)).to(self.runner.device)
        with torch.no_grad():
            lf, ls, lj = self.runner.model(x)
            fwd = int(lf.argmax(1).item()) - 1
            side = int(ls.argmax(1).item()) - 1
            jump = int(lj.argmax(1).item())
        return fwd, side, jump

    def test_sidecar_move_matches_eval_closedloop(self):
        for st, feats in zip(_SAMPLE_STATES, _SAMPLE_FEATURES):
            sidecar_move = self.runner.move(feats)
            ref_move = self._eval_closedloop_move(feats)
            self.assertEqual(sidecar_move, ref_move,
                             msg=f"argmax parity failed for state {st}: "
                                 f"sidecar={sidecar_move} eval_closedloop={ref_move}")

    def test_parity_holds_over_random_states(self):
        import random
        rng = random.Random(0)
        for _ in range(200):
            vx = rng.uniform(-700, 700)
            vy = rng.uniform(-700, 700)
            vz = rng.uniform(-400, 400)
            yaw = rng.uniform(-180, 180)
            pitch = rng.uniform(-90, 90)
            feats = mwv.state_features(vx, vy, vz, yaw, pitch)
            self.assertEqual(self.runner.move(feats), self._eval_closedloop_move(feats),
                             msg=f"argmax parity failed for ({vx},{vy},{vz},{yaw},{pitch})")

    def test_full_transport_parity_with_real_policy(self):
        """End-to-end: real MoveMLP served over shm == eval_closedloop argmax."""
        name = _unique_name("numparity")
        sc.create_region(name)
        try:
            with sc.MockKtxWriter(name) as ktx:
                mm = sc.open_region(name)
                try:
                    for slot, (st, feats) in enumerate(
                            zip(_SAMPLE_STATES[:sc.MAX_SLOTS],
                                _SAMPLE_FEATURES[:sc.MAX_SLOTS])):
                        req = ktx.publish_features(slot, feats)
                        sc.serve_once(mm, self.runner.move)
                        mv = ktx.await_answer(slot, req, timeout=1.0)
                        self.assertIsNotNone(mv)
                        ref = self._eval_closedloop_move(feats)
                        self.assertEqual((mv["fwd"], mv["side"], mv["jump"]), ref,
                                         msg=f"served move != eval_closedloop for {st}")
                finally:
                    mm.close()
        finally:
            sc.unlink_region(name)


if __name__ == "__main__":
    unittest.main()
