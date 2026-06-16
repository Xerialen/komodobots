#!/usr/bin/env python3
"""Policy sidecar serving MoveMLP over the T0.2 shared-memory transport
(bot-program Phase 0, ticket T0.6 / docs/18 wall #1 "Live brain pipe").

WHAT THIS IS
------------
A Python helper that turns the already-trained MoveMLP move-brain into a *live*
per-slot service:

  1. loads the trained MoveMLP checkpoint EXACTLY as
     experiments/stage2/move-bc-train/eval_closedloop.py loads it (same arch,
     same hidden width from the checkpoint, same eval mode);
  2. reads a per-slot world-view -- the SAME 6 features
     (hspeed/320, vz/320, lvm_sin, lvm_cos, moving, pitch/90) -- via the single
     source of truth scripts/move_world_view.py, so there is NO train/serve skew
     (docs/18 wall #2);
  3. returns the MOVE decision only (fwd, side, jump). Aim and fire stay stock
     frogbot in Phase 0, so the sidecar serves move and nothing else;
  4. answers over the T0.2 chosen pipe -- POSIX shared memory with a per-slot
     seqlock -- for up to 4 slots.

It reproduces eval_closedloop's argmax BIT-FOR-BIT on the same input + weights:
the shared `move_argmax_from_logits` helper below is the one definition both this
sidecar and the parity test call, and the live world-view comes from the same
`move_world_view.state_features` the offline dataset/evaluators use.

THE TRANSPORT (mirrors the T0.2 decision + suggested wiring)
------------------------------------------------------------
T0.2 (experiments/ktx_moveprobe/T0.2_LATENCY_SPIKE.md) picked POSIX shm with a
per-slot seqlock and measured per-tick p99 ~0.012 ms for 4 slots @ 77 Hz (~40x
under the 0.5 ms budget). That spike modelled the SERVER->bot action hand-off
(one 32-byte `trap_SetBotCMD` record per slot). T0.6 needs the *request/response*
of a live brain, so this module lays out one `/dev/shm` region with TWO per-slot
records, each independently seqlock-guarded with the identical lock-free protocol
the spike validated (writer bumps a guard before + after the body; reader retries
until the two guards match -> never a torn read):

  * VIEW record  (KTX -> sidecar): the 6 world-view floats + a request seq the
    server bumps each tick. The KTX live side is the WRITER here; the sidecar is
    the READER. (KTX live mode is T0.3 and needs the live box -- it does not
    exist yet, so in-sandbox a Python mock plays the KTX role; see MockKtxWriter.)
  * MOVE record  (sidecar -> KTX): fwd/side/jump (the move decision), plus the
    request seq it answered and a response seq. The sidecar is the WRITER; KTX is
    the READER and feeds the move onto its existing `direction` / `*jumping`
    locals exactly as the moveprobe patch does today, leaving aim/fire stock.

Keeping both records under the same seqlock the spike measured means the proven
transport cost carries over; the sidecar adds only the MoveMLP forward (a few
matmuls on a 6-vector -- trivial, by design; see train.py "Why MLP not GRU").

PURITY / CI
-----------
The TRANSPORT + the argmax helper are PURE STDLIB (mmap / struct / os / math) so
the round-trip test runs on the stdlib-only CI floor (.github/workflows/
pr-tests.yml). torch is imported LAZILY (only when a MoveMLP forward is actually
needed), so importing this module -- and the transport test -- never requires
torch. The numeric argmax-parity test loads torch + the checkpoint on demand and
skips cleanly when either is absent (the test_physent_collision.py pattern).
"""
from __future__ import annotations

import argparse
import math
import mmap
import os
import struct
import sys
import time
from pathlib import Path
from typing import Callable, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS = str(REPO_ROOT / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

# Single source of truth for the world-view features (T0.4). Same module the
# offline dataset builder and the evaluators use -> no train/serve skew.
import move_world_view as mwv  # noqa: E402

# ---------------------------------------------------------------------------
# Action constants -- kept identical to the offline reference so the move the
# sidecar serves is the move eval_closedloop would have applied.
# ---------------------------------------------------------------------------
# eval_closedloop.MOVE_MAG: fwd/side in {-1,0,1} are scaled to +/-320 qu/s.
MOVE_MAG = 320.0
# pmove_sim.BUTTON_JUMP: the jump bit in the buttons byte.
BUTTON_JUMP = 2

# Max bot slots we serve. Phase-0 bench is 4v4; the leap team has up to 4 bots.
MAX_SLOTS = 4

# ---------------------------------------------------------------------------
# Shared-memory layout (one /dev/shm region; per-slot VIEW + MOVE records, each
# seqlock-guarded exactly like the T0.2 spike's slot record).
# ---------------------------------------------------------------------------
# VIEW record (KTX -> sidecar), seqlock-wrapped body:
#   req_seq (u32) | 6 world-view floats (f32) | valid (u8) | pad(3)
# `valid` lets the writer mark a slot as "no live request this tick" (e.g. the
# slot is empty or KTX chose stock-frogbot for it); the sidecar then skips it.
VIEW_BODY_FMT = "<I6fB3x"
VIEW_BODY_SIZE = struct.calcsize(VIEW_BODY_FMT)
# seqlock framing: seq_a (u32) | body | seq_b (u32)
VIEW_SLOT_SIZE = 4 + VIEW_BODY_SIZE + 4

# MOVE record (sidecar -> KTX), seqlock-wrapped body:
#   ans_seq (u32) | fwd (i8) | side (i8) | jump (u8) | pad(1) | move floats x,y,z (f32)
# `ans_seq` echoes the req_seq the sidecar answered, so KTX can tell fresh from
# stale (its T0.3 freshness/fallback check keys on this advancing).
MOVE_BODY_FMT = "<IbbBx3f"
MOVE_BODY_SIZE = struct.calcsize(MOVE_BODY_FMT)
MOVE_SLOT_SIZE = 4 + MOVE_BODY_SIZE + 4

# Region = [ VIEW[0..MAX] ][ MOVE[0..MAX] ]; MOVE block starts after the VIEW block.
VIEW_BLOCK_SIZE = MAX_SLOTS * VIEW_SLOT_SIZE
MOVE_BLOCK_SIZE = MAX_SLOTS * MOVE_SLOT_SIZE
REGION_SIZE = VIEW_BLOCK_SIZE + MOVE_BLOCK_SIZE

_SEQ_FMT = "<I"  # seqlock guard word
_SEQ_MASK = 0xFFFFFFFF


def _shm_path(name: str) -> str:
    return f"/dev/shm/{name}"


def _view_base(slot: int) -> int:
    return slot * VIEW_SLOT_SIZE


def _move_base(slot: int) -> int:
    return VIEW_BLOCK_SIZE + slot * MOVE_SLOT_SIZE


# ---------------------------------------------------------------------------
# Seqlock read/write helpers (lock-free).
#
# Layout per record: guard_a (u32) | body | guard_b (u32) -- the two-guard form
# the T0.2 report describes. The guard is a DEDICATED monotonic write counter,
# kept separate from the application payload (req_seq / ans_seq live in the
# body): it goes ODD while a write is in flight and back to an EVEN value when
# the write completes. The reader retries until guard_a == guard_b AND the value
# is even, so it can never observe a torn body OR a body whose write is still in
# progress. (Conflating the guard with the payload seq -- the spike's shortcut
# -- can let a fast back-to-back writer present matched guards around a body
# from the *next* write; a dedicated odd/even counter closes that window.)
# ---------------------------------------------------------------------------
def _seqlock_write(mm: mmap.mmap, base: int, body_fmt: str, body_size: int,
                   *body_values) -> None:
    """Write `body_values` into the slot under the seqlock.

    Bump the guard to ODD (write-in-progress), write the body, then bump it to
    the next EVEN (stable). A reader that catches us mid-write sees an odd /
    mismatched guard and retries.
    """
    tail = base + 4 + body_size
    g = struct.unpack_from(_SEQ_FMT, mm, base)[0]
    g_odd = (g + 1) | 1                     # next odd value
    struct.pack_into(_SEQ_FMT, mm, base, g_odd)
    struct.pack_into(body_fmt, mm, base + 4, *body_values)
    g_even = (g_odd + 1) & _SEQ_MASK        # next even value
    struct.pack_into(_SEQ_FMT, mm, tail, g_even)
    struct.pack_into(_SEQ_FMT, mm, base, g_even)


def _seqlock_read(mm: mmap.mmap, base: int, body_fmt: str, body_size: int,
                  retries: int = 16):
    """Read a consistent body snapshot under the seqlock.

    Retry until both guards match and are even (a complete, untorn write).
    Returns (ok, body_tuple): ok is False if every retry caught a write in
    flight (the caller falls back); body is still the last snapshot read. The
    application seq inside the body is what callers use for freshness.
    """
    tail = base + 4 + body_size
    body = None
    for _ in range(max(1, retries)):
        ga = struct.unpack_from(_SEQ_FMT, mm, base)[0]
        if ga & 1:                          # odd -> writer mid-write, retry
            continue
        body = struct.unpack_from(body_fmt, mm, base + 4)
        gb = struct.unpack_from(_SEQ_FMT, mm, tail)[0]
        if ga == gb:
            return True, body
    return False, body


# ---------------------------------------------------------------------------
# VIEW record (KTX writes, sidecar reads)
# ---------------------------------------------------------------------------
def write_view(mm: mmap.mmap, slot: int, req_seq: int,
               features: Sequence[float], valid: bool = True) -> None:
    """Publish a world-view for `slot` (the role KTX plays live; the mock here)."""
    if len(features) != mwv.FEATURE_DIM:
        raise ValueError(
            f"world-view must have {mwv.FEATURE_DIM} features, got {len(features)}")
    _seqlock_write(mm, _view_base(slot), VIEW_BODY_FMT, VIEW_BODY_SIZE,
                   req_seq & _SEQ_MASK, *(float(x) for x in features),
                   1 if valid else 0)


def read_view(mm: mmap.mmap, slot: int) -> Tuple[int, Tuple[float, ...], bool]:
    """Read (req_seq, features, valid) for `slot` (the sidecar's read).

    A slot whose write was caught in flight on every retry reads back as
    invalid, so the sidecar simply skips it this pass (never acts on a torn or
    half-written world-view)."""
    ok, body = _seqlock_read(mm, _view_base(slot), VIEW_BODY_FMT, VIEW_BODY_SIZE)
    if not ok or body is None:
        return 0, (0.0,) * mwv.FEATURE_DIM, False
    req_seq = body[0]
    features = tuple(body[1:1 + mwv.FEATURE_DIM])
    valid = bool(body[1 + mwv.FEATURE_DIM])
    return req_seq, features, valid


# ---------------------------------------------------------------------------
# MOVE record (sidecar writes, KTX reads)
# ---------------------------------------------------------------------------
def write_move(mm: mmap.mmap, slot: int, ans_seq: int,
               fwd: int, side: int, jump: int) -> None:
    """Publish the move decision for `slot` (the sidecar's write)."""
    mx = float(fwd) * MOVE_MAG
    my = float(side) * MOVE_MAG
    _seqlock_write(mm, _move_base(slot), MOVE_BODY_FMT, MOVE_BODY_SIZE,
                   ans_seq & _SEQ_MASK, int(fwd), int(side),
                   int(jump) & 0xFF, mx, my, 0.0)


def read_move(mm: mmap.mmap, slot: int):
    """Read the move decision for `slot` (the role KTX plays live; the mock here).

    Returns a dict: ans_seq, fwd, side, jump, move=[x,y,z], buttons (jump bit),
    fresh (False if the read was caught mid-write on every retry -- KTX's T0.3
    fallback path would treat that like a stale slot).
    """
    ok, body = _seqlock_read(mm, _move_base(slot), MOVE_BODY_FMT, MOVE_BODY_SIZE)
    if body is None:
        body = (0, 0, 0, 0, 0.0, 0.0, 0.0)
    ans_seq, fwd, side, jump, mx, my, mz = body
    return {
        "ans_seq": ans_seq,
        "fwd": int(fwd),
        "side": int(side),
        "jump": int(jump),
        "move": [mx, my, mz],
        "buttons": BUTTON_JUMP if jump else 0,
        "fresh": ok,
    }


# ---------------------------------------------------------------------------
# Region lifecycle
# ---------------------------------------------------------------------------
def create_region(name: str) -> mmap.mmap:
    """Create + zero a fresh /dev/shm region and return an mmap over it.

    Seeds every slot's seqlock guards to 0 and marks views invalid so a reader
    that races ahead of the first write sees a clean, consistent "no request"
    state rather than garbage.
    """
    path = _shm_path(name)
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        os.ftruncate(fd, REGION_SIZE)
        mm = mmap.mmap(fd, REGION_SIZE)
    finally:
        os.close(fd)
    for slot in range(MAX_SLOTS):
        write_view(mm, slot, 0, [0.0] * mwv.FEATURE_DIM, valid=False)
        write_move(mm, slot, 0, 0, 0, 0)
    mm.flush()
    return mm


def open_region(name: str) -> mmap.mmap:
    """Open an existing /dev/shm region created by create_region()."""
    path = _shm_path(name)
    fd = os.open(path, os.O_RDWR)
    try:
        return mmap.mmap(fd, REGION_SIZE)
    finally:
        os.close(fd)


def unlink_region(name: str) -> None:
    try:
        os.remove(_shm_path(name))
    except OSError:
        pass


# ---------------------------------------------------------------------------
# The argmax -- the ONE definition both the sidecar and the parity test call.
# ---------------------------------------------------------------------------
def move_argmax_from_logits(logits_fwd: Sequence[float],
                            logits_side: Sequence[float],
                            logits_jump: Sequence[float]) -> Tuple[int, int, int]:
    """Reproduce eval_closedloop.policy_step_action's argmax decode bit-for-bit.

    eval_closedloop does, on the three MoveMLP heads (fwd 3-way, side 3-way,
    jump 2-way):
        fwd  = argmax(lf) - 1   # {back,-1 | none,0 | fwd,+1}
        side = argmax(ls) - 1   # {left,-1 | none,0 | right,+1}
        jump = argmax(lj)       # {0,1}
    This is the integer decode of those logits; the calling runner produces the
    logits with the same MoveMLP forward, so sidecar == eval_closedloop on the
    same weights + input by construction.
    """
    fwd = int(_argmax(logits_fwd)) - 1
    side = int(_argmax(logits_side)) - 1
    jump = int(_argmax(logits_jump))
    return fwd, side, jump


def _argmax(xs: Sequence[float]) -> int:
    """Index of the max element. Ties resolve to the lowest index, matching
    torch.argmax (and numpy.argmax) tie behavior so parity holds on ties too."""
    best_i = 0
    best_v = xs[0]
    for i in range(1, len(xs)):
        if xs[i] > best_v:
            best_v = xs[i]
            best_i = i
    return best_i


# ---------------------------------------------------------------------------
# MoveMLP runner -- loads the checkpoint exactly like eval_closedloop, lazily.
# ---------------------------------------------------------------------------
# eval_closedloop default checkpoint location.
DEFAULT_CKPT = "~/move_bc_policy.pt"


def _find_ckpt(ckpt: Optional[str]) -> Optional[Path]:
    cands = [ckpt] if ckpt else [DEFAULT_CKPT]
    for c in cands:
        if not c:
            continue
        p = Path(c).expanduser()
        if p.exists():
            return p
    return None


class MoveMLPRunner:
    """Loads MoveMLP and produces the three head logits for a world-view.

    Mirrors eval_closedloop.main's load (torch.load(weights_only=False) ->
    MoveMLP(hidden=ck["hidden"]) -> load_state_dict -> eval) and
    policy_step_action's forward (float32 [1,6] -> model(x) -> three logit
    tensors). Importing torch is deferred to construction time so the rest of
    this module (and the transport test) need no torch.
    """

    def __init__(self, ckpt: Optional[str] = None, device: Optional[str] = None):
        import numpy as np  # noqa: F401  (deferred heavy deps)
        import torch
        # eval_closedloop adds <repo>/experiments/stage2/move-bc-train to import
        # `train.MoveMLP`; do the same.
        train_dir = REPO_ROOT / "experiments/stage2/move-bc-train"
        if str(train_dir) not in sys.path:
            sys.path.insert(0, str(train_dir))
        from train import MoveMLP

        self._np = np
        self._torch = torch
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        path = _find_ckpt(ckpt)
        if path is None:
            raise FileNotFoundError(
                f"MoveMLP checkpoint not found (looked for {ckpt or DEFAULT_CKPT}); "
                "it is a gitignored WSL/4090 artifact")
        self.ckpt_path = path
        ck = torch.load(path, map_location=self.device, weights_only=False)
        self.hidden = ck["hidden"]
        self.model = MoveMLP(hidden=self.hidden).to(self.device)
        self.model.load_state_dict(ck["state_dict"])
        self.model.eval()

    def logits(self, features: Sequence[float]):
        """Return (lf, ls, lj) as plain python float lists for one world-view.

        Same forward path as eval_closedloop.policy_step_action: a float32
        [1, FEATURE_DIM] tensor through model(x).
        """
        np = self._np
        torch = self._torch
        x = torch.from_numpy(np.asarray([features], dtype=np.float32)).to(self.device)
        with torch.no_grad():
            lf, ls, lj = self.model(x)
        return (lf[0].tolist(), ls[0].tolist(), lj[0].tolist())

    def move(self, features: Sequence[float]) -> Tuple[int, int, int]:
        """Full move decision for one world-view: forward + shared argmax."""
        lf, ls, lj = self.logits(features)
        return move_argmax_from_logits(lf, ls, lj)


# A runner is just "world-view floats -> (fwd, side, jump)".
MoveFn = Callable[[Sequence[float]], Tuple[int, int, int]]


# ---------------------------------------------------------------------------
# The sidecar serve step + loop
# ---------------------------------------------------------------------------
def serve_once(mm: mmap.mmap, move_fn: MoveFn,
               last_seq: Optional[list] = None) -> int:
    """Service all slots once: read each VIEW, compute the move, write each MOVE.

    Only answers slots whose VIEW is `valid`. If `last_seq` is given, a slot
    whose req_seq has not advanced is skipped (already answered) -- the cheap
    "freshest request only" behavior the live loop wants. Returns the number of
    slots answered this pass.
    """
    answered = 0
    for slot in range(MAX_SLOTS):
        req_seq, features, valid = read_view(mm, slot)
        if not valid:
            continue
        if last_seq is not None and req_seq == last_seq[slot]:
            continue
        fwd, side, jump = move_fn(features)
        write_move(mm, slot, req_seq, fwd, side, jump)
        if last_seq is not None:
            last_seq[slot] = req_seq
        answered += 1
    return answered


def serve_loop(name: str, move_fn: MoveFn, hz: float = 77.0,
               duration: Optional[float] = None,
               stop_predicate: Optional[Callable[[], bool]] = None) -> int:
    """Open an existing region and serve it at `hz` until duration/stop.

    Returns the total number of slot answers written. The KTX live side (T0.3)
    owns region creation; the sidecar attaches. For in-sandbox/manual runs use
    create_region() first (or --create on the CLI).
    """
    mm = open_region(name)
    last_seq = [-1] * MAX_SLOTS
    period = 1.0 / hz if hz > 0 else 0.0
    total = 0
    t0 = time.perf_counter()
    tick = 0
    try:
        while True:
            if duration is not None and (time.perf_counter() - t0) >= duration:
                break
            if stop_predicate is not None and stop_predicate():
                break
            total += serve_once(mm, move_fn, last_seq)
            tick += 1
            if period:
                target = t0 + tick * period
                sl = target - time.perf_counter()
                if sl > 0:
                    time.sleep(sl)
    finally:
        mm.close()
    return total


# ---------------------------------------------------------------------------
# Mock KTX writer -- stands in for the (not-yet-built, box-only T0.3) live KTX
# side so the round-trip is provable entirely in-sandbox.
# ---------------------------------------------------------------------------
class MockKtxWriter:
    """Plays the KTX live side against the shm transport, in Python.

    Per "tick": publish a world-view into a slot's VIEW record (the role KTX's
    BotApplyMoveProbe live mode will play), then read back the sidecar's MOVE
    record once it answers. Used by the round-trip test and the CLI self-check.
    Build a world-view from raw state via `move_world_view.state_features`, the
    SAME function the offline builder uses -- so even the mock cannot introduce
    skew.
    """

    def __init__(self, name: str):
        self.mm = open_region(name)
        self._seq = [0] * MAX_SLOTS

    def close(self) -> None:
        self.mm.close()

    def __enter__(self) -> "MockKtxWriter":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def publish_features(self, slot: int, features: Sequence[float]) -> int:
        """Publish a precomputed world-view; returns the request seq used."""
        self._seq[slot] += 1
        write_view(self.mm, slot, self._seq[slot], features, valid=True)
        return self._seq[slot]

    def publish_state(self, slot: int, vx: float, vy: float, vz: float,
                      yaw: float, pitch: float) -> int:
        """Publish a world-view built from raw state (KTX's real path)."""
        feats = mwv.state_features(vx, vy, vz, yaw, pitch)
        return self.publish_features(slot, feats)

    def await_answer(self, slot: int, req_seq: int, timeout: float = 2.0,
                     poll: float = 0.0005):
        """Block (briefly) until the sidecar's MOVE answers `req_seq` for `slot`.

        Returns the move dict (read_move) or None on timeout. Mirrors the
        freshness check KTX's T0.3 reader will do: accept only an answer whose
        ans_seq has caught up to the request it issued.
        """
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            mv = read_move(self.mm, slot)
            if mv["ans_seq"] == req_seq:
                return mv
            time.sleep(poll)
        return None


# ---------------------------------------------------------------------------
# CLI -- run the sidecar, or a self-contained round-trip self-check.
# ---------------------------------------------------------------------------
def _selfcheck(name: str, hz: float) -> int:
    """In-process round-trip: mock writer -> sidecar serve_once -> mock reader.

    Uses a tiny deterministic stub policy (no torch needed) to prove the
    transport end to end. Real serving uses MoveMLPRunner.
    """
    def stub_move(feats):
        # deterministic, exercises all three axes from the features
        fwd = 1 if feats[0] > 0.3 else (-1 if feats[0] < 0.05 else 0)
        side = 1 if feats[2] > 0.2 else (-1 if feats[2] < -0.2 else 0)
        jump = 1 if feats[1] > 0.5 else 0
        return fwd, side, jump

    create_region(name)
    try:
        with MockKtxWriter(name) as ktx:
            req = ktx.publish_state(0, 240.0, 180.0, 90.0, 30.0, -5.0)
            mm = open_region(name)
            try:
                answered = serve_once(mm, stub_move)
            finally:
                mm.close()
            mv = ktx.await_answer(0, req, timeout=0.5)
            exp = stub_move(mwv.state_features(240.0, 180.0, 90.0, 30.0, -5.0))
            ok = (mv is not None and answered == 1
                  and (mv["fwd"], mv["side"], mv["jump"]) == exp)
            print(f"selfcheck: answered={answered} req_seq={req} "
                  f"move={mv} expected_fwd_side_jump={exp} -> "
                  f"{'OK' if ok else 'FAIL'}")
            return 0 if ok else 1
    finally:
        unlink_region(name)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--shm-name", default="komodo_move_t06",
                    help="/dev/shm region name shared with KTX")
    ap.add_argument("--ckpt", default=DEFAULT_CKPT,
                    help="MoveMLP checkpoint (gitignored WSL/4090 artifact)")
    ap.add_argument("--hz", type=float, default=77.0, help="serve rate")
    ap.add_argument("--duration", type=float, default=None,
                    help="serve this many seconds then exit (default: forever)")
    ap.add_argument("--create", action="store_true",
                    help="create the region first (normally KTX/T0.3 owns this)")
    ap.add_argument("--selfcheck", action="store_true",
                    help="run an in-process transport round-trip and exit "
                         "(stub policy; needs no torch)")
    args = ap.parse_args(argv)

    if args.selfcheck:
        return _selfcheck(args.shm_name, args.hz)

    runner = MoveMLPRunner(ckpt=args.ckpt)
    print(f"loaded MoveMLP from {runner.ckpt_path} (hidden={runner.hidden}, "
          f"device={runner.device}); serving shm '{args.shm_name}' at {args.hz:g} Hz",
          flush=True)
    if args.create:
        create_region(args.shm_name).close()
    total = serve_loop(args.shm_name, runner.move, hz=args.hz, duration=args.duration)
    print(f"served {total} slot-answers", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
