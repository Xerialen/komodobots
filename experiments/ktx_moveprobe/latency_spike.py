#!/usr/bin/env python3
"""T0.2 live-transport latency spike (bot-program Phase 0).

Goal
----
Pick the cheapest way to hand a per-tick *action* (move + aim + fire + weapon)
to a bot slot every server tick, and prove it clears the Phase-0 budget:

    p99 < ~0.5 ms/tick for up to 4 slots at ~77 Hz (~13 ms/tick wall budget).

Why this benchmark looks the way it does
-----------------------------------------
The seam we feed is `BotApplyMoveProbe` -> `trap_SetBotCMD` in
`artifacts/ktx-live/bot_movement.c` (line ~6191). The per-tick action that the
server hands a bot slot is exactly:

    trap_SetBotCMD(edict, cmd_msec,
                   desired_angle.x, desired_angle.y, desired_angle.z,   # AIM
                   direction.x,     direction.y,     direction.z,       # MOVE
                   buttons,                                             # FIRE/JUMP (bit0/bit1)
                   impulse)                                             # WEAPON select

So one action is: 3 move floats + 3 aim floats + a buttons byte (fire+jump) +
an impulse byte (weapon) + cmd_msec. We pack an identical fixed-size record for
every candidate transport so the comparison is apples-to-apples.

The KTX QVM bot loop is single-threaded: on each server frame it walks the bot
list and calls `trap_SetBotCMD` once per bot. So the realistic consumer is ONE
reader (the server frame) that, every ~13 ms tick, fetches the *freshest*
action for each of up to 4 slots. The producer (a python "brain" sidecar) writes
each slot's freshest action asynchronously. The number that gates Phase 0 is the
per-tick *consume* cost on the server side: the time the server thread spends
fetching+decoding the freshest action. We measure that p99, both per-slot and
per full 4-slot tick.

Candidates
----------
(a) action-file  : per-tick action-file re-read. Producer atomically rewrites a
                   per-slot file; consumer re-opens+reads it each tick.
                   (Modeled on the existing cvar/file-style transport the
                   moveprobe README already uses to avoid Quake transport
                   limits.)
(b) shm          : POSIX shared memory. Producer mmaps /dev/shm/<name> and writes
                   the freshest record in place with a seqlock; consumer mmaps
                   the same region and reads the latest record. This is the
                   shm_open()+mmap() mechanism a native trap would use, exercised
                   here from Python via mmap over /dev/shm.
(c) socket       : unix-domain DATAGRAM socket = the "short action-queue". Producer
                   sends one datagram per action; consumer drains the socket and
                   keeps the last (freshest) datagram per slot. Bounded by a small
                   OS receive buffer, so it behaves as a short, lossy-newest queue.

Honest environment limit
-------------------------
This is a HOST-LOCAL microbenchmark. It measures the transport cost on this
machine only. It does NOT run the real KTX server (no server build / SSH in this
sandbox). The on-KTX end-to-end p99 must be validated when the pipe is actually
wired into the moveprobe patch -- that is ticket T0.3. We do not fabricate
on-server numbers here.

Run
---
    python3 experiments/ktx_moveprobe/latency_spike.py
    python3 experiments/ktx_moveprobe/latency_spike.py --json   # machine-readable
    python3 experiments/ktx_moveprobe/latency_spike.py --slots 4 --hz 77 --seconds 8

Stdlib only (mmap / socket / struct / os / time / multiprocessing). No deps.
"""

from __future__ import annotations

import logging
import argparse
import json
import math
import mmap
import os
import socket
import statistics
import struct
import sys
import tempfile
import time
from multiprocessing import Process, Event


LOGGER = logging.getLogger(__name__)
# --- Action record (mirrors the trap_SetBotCMD payload) ----------------------
# seq (u32) | cmd_msec (u16) | buttons (u8) | impulse (u8)
#   | aim.x aim.y aim.z (3x f32)  | move.x move.y move.z (3x f32)
# = 4 + 2 + 1 + 1 + 12 + 12 = 32 bytes. Fixed-size, identical for all transports.
ACTION_FMT = "<IHBB6f"
ACTION_SIZE = struct.calcsize(ACTION_FMT)
assert ACTION_SIZE == 32, ACTION_SIZE

# shm layout per slot: seq_a (u32) | <ACTION_SIZE bytes> | seq_b (u32)
# seqlock: writer bumps seq_a before write and seq_b after; reader retries until
# seq_a == seq_b (consistent snapshot, no torn read), lock-free.
SHM_SLOT_FMT_HEAD = "<I"
SHM_SLOT_SIZE = 4 + ACTION_SIZE + 4  # 40 bytes/slot, padded to cache-ish line


def pack_action(seq: int, cmd_msec: int, buttons: int, impulse: int,
                aim, move) -> bytes:
    return struct.pack(ACTION_FMT, seq & 0xFFFFFFFF, cmd_msec & 0xFFFF,
                       buttons & 0xFF, impulse & 0xFF,
                       aim[0], aim[1], aim[2], move[0], move[1], move[2])


def make_action(seq: int) -> bytes:
    """A plausible per-tick action (values just need to be representative)."""
    yaw = (seq * 1.7) % 360.0
    return pack_action(
        seq=seq,
        cmd_msec=13,                 # ~77 Hz frame
        buttons=(seq & 1) | ((seq & 2)),  # fire/jump toggling
        impulse=(2 + (seq % 8)),     # weapon select churn
        aim=(0.0, yaw, 0.0),
        move=(800.0, -400.0 if (seq & 4) else 400.0, 0.0),
    )


def percentile(sorted_us, q):
    if not sorted_us:
        return float("nan")
    if len(sorted_us) == 1:
        return sorted_us[0]
    # linear interpolation, like numpy default
    pos = (len(sorted_us) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return sorted_us[lo]
    return sorted_us[lo] + (sorted_us[hi] - sorted_us[lo]) * (pos - lo)


def summarize(samples_us):
    s = sorted(samples_us)
    return {
        "n": len(s),
        "min_us": round(s[0], 3),
        "mean_us": round(statistics.fmean(s), 3),
        "median_us": round(percentile(s, 0.50), 3),
        "p95_us": round(percentile(s, 0.95), 3),
        "p99_us": round(percentile(s, 0.99), 3),
        "p999_us": round(percentile(s, 0.999), 3),
        "max_us": round(s[-1], 3),
    }


def now():
    return time.perf_counter()


# =============================================================================
# (a) action-file re-read
# =============================================================================
def producer_file(paths, hz, seconds, stop_evt):
    period = 1.0 / hz
    n = int(seconds * hz) + 20
    seq = 0
    # Pre-open dir for atomic rename.
    dirs = [os.path.dirname(p) for p in paths]
    t0 = now()
    while not stop_evt.is_set():
        seq += 1
        for i, p in enumerate(paths):
            data = make_action(seq)
            # Atomic publish: write temp, fsync-free rename (same fs).
            tmp = p + f".tmp.{os.getpid()}"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, p)
        # pace
        target = t0 + seq * period
        sl = target - now()
        if sl > 0:
            time.sleep(sl)
        if seq >= n:
            break


def consume_file_tick(paths, bufs):
    """Read freshest action for every slot once. Returns total bytes (sanity)."""
    total = 0
    for p in paths:
        with open(p, "rb") as f:
            d = f.read()
        total += len(d)
    return total


def run_file(slots, hz, seconds, warmup_ticks):
    tmpdir = tempfile.mkdtemp(prefix="t02_file_")
    paths = [os.path.join(tmpdir, f"slot_{i}.act") for i in range(slots)]
    # seed files so first read never misses
    for p in paths:
        with open(p, "wb") as f:
            f.write(make_action(0))
    stop = Event()
    prod = Process(target=producer_file, args=(paths, hz, seconds, stop))
    prod.start()
    res = _drive_consumer(lambda: consume_file_tick(paths, None),
                          hz, seconds, warmup_ticks)
    stop.set()
    prod.join(timeout=3)
    if prod.is_alive():
        prod.terminate()
    for p in paths:
        try:
            os.remove(p)
        except OSError:
            pass
    try:
        os.rmdir(tmpdir)
    except OSError:
        pass
    return res


# =============================================================================
# (b) POSIX shared memory (mmap over /dev/shm) with a seqlock per slot
# =============================================================================
def _shm_path(name):
    return f"/dev/shm/{name}"


def producer_shm(shm_name, slots, hz, seconds, stop_evt):
    period = 1.0 / hz
    n = int(seconds * hz) + 20
    path = _shm_path(shm_name)
    fd = os.open(path, os.O_RDWR)
    try:
        mm = mmap.mmap(fd, slots * SHM_SLOT_SIZE)
    finally:
        os.close(fd)
    seq = 0
    t0 = now()
    while not stop_evt.is_set():
        seq += 1
        for i in range(slots):
            base = i * SHM_SLOT_SIZE
            data = make_action(seq)
            # seqlock write: bump seq_a (odd), write body, set seq_b = seq_a
            struct.pack_into(SHM_SLOT_FMT_HEAD, mm, base, seq)
            mm[base + 4: base + 4 + ACTION_SIZE] = data
            struct.pack_into(SHM_SLOT_FMT_HEAD, mm, base + 4 + ACTION_SIZE, seq)
        target = t0 + seq * period
        sl = target - now()
        if sl > 0:
            time.sleep(sl)
        if seq >= n:
            break
    mm.close()


def make_shm_consumer(shm_name, slots):
    path = _shm_path(shm_name)
    fd = os.open(path, os.O_RDWR)
    try:
        mm = mmap.mmap(fd, slots * SHM_SLOT_SIZE)
    finally:
        os.close(fd)

    def consume_tick():
        total = 0
        for i in range(slots):
            base = i * SHM_SLOT_SIZE
            # seqlock read: retry until the two guards match (consistent snapshot)
            for _ in range(8):
                sa = struct.unpack_from(SHM_SLOT_FMT_HEAD, mm, base)[0]
                body = mm[base + 4: base + 4 + ACTION_SIZE]
                sb = struct.unpack_from(SHM_SLOT_FMT_HEAD, mm,
                                        base + 4 + ACTION_SIZE)[0]
                if sa == sb:
                    break
            rec = struct.unpack(ACTION_FMT, body)
            total += rec[0]
        return total

    return mm, consume_tick


def run_shm(slots, hz, seconds, warmup_ticks):
    shm_name = f"t02_shm_{os.getpid()}"
    path = _shm_path(shm_name)
    size = slots * SHM_SLOT_SIZE
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    os.ftruncate(fd, size)
    # seed
    mm0 = mmap.mmap(fd, size)
    os.close(fd)
    for i in range(slots):
        base = i * SHM_SLOT_SIZE
        struct.pack_into(SHM_SLOT_FMT_HEAD, mm0, base, 0)
        mm0[base + 4: base + 4 + ACTION_SIZE] = make_action(0)
        struct.pack_into(SHM_SLOT_FMT_HEAD, mm0, base + 4 + ACTION_SIZE, 0)
    mm0.flush()
    mm0.close()

    stop = Event()
    prod = Process(target=producer_shm, args=(shm_name, slots, hz, seconds, stop))
    prod.start()
    mm, consume_tick = make_shm_consumer(shm_name, slots)
    res = _drive_consumer(consume_tick, hz, seconds, warmup_ticks)
    stop.set()
    prod.join(timeout=3)
    if prod.is_alive():
        prod.terminate()
    mm.close()
    try:
        os.remove(path)
    except OSError:
        pass
    return res


# =============================================================================
# (c) unix-domain DATAGRAM socket = short action-queue (lossy-newest)
# =============================================================================
def producer_socket(sock_path, slots, hz, seconds, stop_evt):
    period = 1.0 / hz
    n = int(seconds * hz) + 20
    s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    seq = 0
    t0 = now()
    while not stop_evt.is_set():
        seq += 1
        for i in range(slots):
            # prefix slot id so the consumer can route; 1 byte + action
            msg = bytes([i]) + make_action(seq)
            try:
                s.sendto(msg, sock_path)
            except (BlockingIOError, ConnectionRefusedError, OSError):
                pass  # queue full / consumer not ready: newest-wins, drop is fine
        target = t0 + seq * period
        sl = target - now()
        if sl > 0:
            time.sleep(sl)
        if seq >= n:
            break
    s.close()


def make_socket_consumer(sock_path, slots):
    if os.path.exists(sock_path):
        os.remove(sock_path)
    s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    s.bind(sock_path)
    # small receive buffer -> behaves as a *short* queue; newest matters
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 64 * 1024)
    except OSError:
        pass
    s.setblocking(False)
    latest = [make_action(0) for _ in range(slots)]
    msgsize = 1 + ACTION_SIZE

    def consume_tick():
        # Drain everything queued; keep the freshest per slot (newest-wins).
        while True:
            try:
                d = s.recv(msgsize * 8)
            except BlockingIOError:
                break
            except OSError:
                break
            if not d:
                break
            # may contain multiple concatenated only if SOCK_STREAM; DGRAM = 1 msg
            slot = d[0]
            if 0 <= slot < slots:
                latest[slot] = d[1:1 + ACTION_SIZE]
        total = 0
        for i in range(slots):
            rec = struct.unpack(ACTION_FMT, latest[i])
            total += rec[0]
        return total

    return s, consume_tick


def run_socket(slots, hz, seconds, warmup_ticks):
    d = tempfile.mkdtemp(prefix="t02_sock_")
    sock_path = os.path.join(d, "act.sock")
    s, consume_tick = make_socket_consumer(sock_path, slots)
    stop = Event()
    prod = Process(target=producer_socket,
                   args=(sock_path, slots, hz, seconds, stop))
    prod.start()
    res = _drive_consumer(consume_tick, hz, seconds, warmup_ticks)
    stop.set()
    prod.join(timeout=3)
    if prod.is_alive():
        prod.terminate()
    s.close()
    try:
        os.remove(sock_path)
    except OSError:
        pass
    try:
        os.rmdir(d)
    except OSError:
        pass
    return res


# =============================================================================
# Consumer driver: emulate the single-threaded server frame loop at `hz`.
# Each tick: measure the time to fetch the freshest action for ALL slots.
# =============================================================================
def _drive_consumer(consume_tick_fn, hz, seconds, warmup_ticks):
    period = 1.0 / hz
    total_ticks = int(seconds * hz)
    per_tick_us = []           # time to service all slots in one tick
    t0 = now()
    sink = 0
    for t in range(total_ticks):
        # pace to the tick boundary (server runs at fixed frame rate)
        target = t0 + t * period
        sl = target - now()
        if sl > 0:
            time.sleep(sl)
        a = now()
        sink ^= consume_tick_fn()
        b = now()
        if t >= warmup_ticks:
            per_tick_us.append((b - a) * 1e6)
    return {"per_tick_us": per_tick_us, "_sink": sink, "ticks": total_ticks}


def main():
    ap = argparse.ArgumentParser(description="T0.2 transport latency spike")
    ap.add_argument("--slots", type=int, default=4)
    ap.add_argument("--hz", type=float, default=77.0)
    ap.add_argument("--seconds", type=float, default=8.0)
    ap.add_argument("--warmup-ticks", type=int, default=77)
    ap.add_argument("--json", action="store_true", help="emit JSON only")
    ap.add_argument("--budget-ms", type=float, default=0.5,
                    help="per-tick p99 budget in ms (Phase-0 = ~0.5)")
    args = ap.parse_args()

    candidates = [
        ("action-file", run_file),
        ("shm", run_shm),
        ("socket", run_socket),
    ]
    results = {}
    for name, fn in candidates:
        r = fn(args.slots, args.hz, args.seconds, args.warmup_ticks)
        per_tick = summarize(r["per_tick_us"])
        # per-slot estimate = per-tick / slots (server services all slots in one frame)
        per_tick["per_slot_p99_us"] = round(per_tick["p99_us"] / max(args.slots, 1), 3)
        results[name] = {
            "per_tick": per_tick,
            "ticks_measured": len(r["per_tick_us"]),
        }

    budget_us = args.budget_ms * 1000.0
    # choose: lowest per-tick p99 that clears the budget; prefer simplest on ties
    passing = [(n, results[n]["per_tick"]["p99_us"]) for n in results
               if results[n]["per_tick"]["p99_us"] < budget_us]
    passing.sort(key=lambda kv: kv[1])
    chosen = passing[0][0] if passing else None

    out = {
        "config": {
            "slots": args.slots, "hz": args.hz, "seconds": args.seconds,
            "warmup_ticks": args.warmup_ticks,
            "budget_ms_per_tick": args.budget_ms,
            "action_size_bytes": ACTION_SIZE,
            "python": sys.version.split()[0],
        },
        "results": results,
        "chosen": chosen,
        "note": ("Host-local microbenchmark only. On-KTX end-to-end p99 must be "
                 "validated when the pipe is wired into the moveprobe patch (T0.3). "
                 "No on-server numbers are fabricated here."),
    }

    if args.json:
        print(json.dumps(out, indent=2))
        return 0

    print(f"T0.2 live-transport latency spike")
    print(f"  config: {args.slots} slots @ {args.hz:g} Hz for {args.seconds:g}s "
          f"(budget p99 < {args.budget_ms:g} ms/tick), action={ACTION_SIZE} B, "
          f"python {out['config']['python']}")
    print(f"  warmup: {args.warmup_ticks} ticks discarded; "
          f"measured ~{results['shm']['ticks_measured']} ticks/candidate")
    print()
    hdr = (f"  {'candidate':<14} {'p50(ms)':>9} {'p95(ms)':>9} {'p99(ms)':>9} "
           f"{'p999(ms)':>9} {'max(ms)':>9} {'/slot p99(ms)':>14} {'verdict':>9}")
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    for name, _ in candidates:
        pt = results[name]["per_tick"]
        verdict = "PASS" if pt["p99_us"] < budget_us else "FAIL"
        print(f"  {name:<14} "
              f"{pt['median_us']/1000:>9.4f} {pt['p95_us']/1000:>9.4f} "
              f"{pt['p99_us']/1000:>9.4f} {pt['p999_us']/1000:>9.4f} "
              f"{pt['max_us']/1000:>9.4f} {pt['per_slot_p99_us']/1000:>14.4f} "
              f"{verdict:>9}")
    print()
    if chosen:
        ch = results[chosen]["per_tick"]
        print(f"  CHOSEN PIPE: {chosen}  "
              f"(per-tick p99 = {ch['p99_us']/1000:.4f} ms for {args.slots} slots; "
              f"~{ch['per_slot_p99_us']/1000:.4f} ms/slot)")
    else:
        print("  CHOSEN PIPE: none cleared the budget (see numbers above)")
    print()
    print("  ENV LIMIT: host-local microbenchmark only. The real KTX server is")
    print("  NOT run here (no server build/SSH in this sandbox). On-KTX end-to-end")
    print("  p99 must be validated when the pipe is wired into the moveprobe patch")
    print("  -- that is ticket T0.3. No on-server numbers are fabricated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
