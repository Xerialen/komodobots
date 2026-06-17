#!/usr/bin/env python3
"""T0.5 (#210) PR-B -- live world-view parity check (offline half).

The CI gate (PR-A, tests/test_golden_vector_parity.py) proves the C
``move_world_view`` unit and the Python ``move_world_view.state_features``
compute bit-identical features over a real demo, locked to a committed golden.
This script closes the *other* half of docs/18 wall #2: it proves KTX's **live**
seam -- the ``mwv_state_features(...)`` call inside ``BotApplyMoveProbeLive``
(mode 30) that feeds the MoveMLP sidecar over /dev/shm -- computes the same
features the Python offline builder would, *from the same inputs*.

How: the ``frogbot-moveprobe-live-dump.patch`` makes KTX emit one line per live
tick, carrying the exact f32 inputs it fed to the world-view AND the f32 features
it computed:

    [moveprobe-dump] slot S req R in IX IY IZ IYAW IPITCH feat F0 F1 F2 F3 F4 F5

where every IX.. and F0.. is an 8-hex-digit little-endian f32 bit pattern.
This script reads KTX's dumped *inputs*, recomputes the features in Python, and
diffs at exact f32 bit level. A 0-mismatch result means the live seam and the
offline builder agree bit-for-bit -- no train/serve skew.

This is FORMULA parity (same inputs -> identical features), per the owner's
T0.5 decision. Whether KTX's pmove reproduces a human's exact trajectory (pmove
resim) is a separate question owned by T0.7 / pmove-validation, NOT this gate --
that is exactly why we recompute from KTX's *own* dumped inputs, so the bot's
trajectory is irrelevant to the diff.

Stdlib only (mirrors the CI gate); imports the sibling move_world_view module.
"""
from __future__ import annotations

import argparse
import json
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import move_world_view as mwv  # noqa: E402

# [moveprobe-dump] slot S req R in <5x f32-hex> feat <6x f32-hex>
_HEX = r"([0-9a-fA-F]{8})"
LINE_RE = re.compile(
    r"\[moveprobe-dump\]\s+slot\s+(\d+)\s+req\s+(\d+)\s+in\s+"
    + r"\s+".join([_HEX] * 5)
    + r"\s+feat\s+"
    + r"\s+".join([_HEX] * mwv.FEATURE_DIM)
)


def f32_from_hex(h: str) -> float:
    """Decode an 8-hex-digit little-endian f32 bit pattern to a Python float."""
    return struct.unpack("<f", struct.pack("<I", int(h, 16)))[0]


def f32_bits(x: float) -> int:
    """The f32 bit pattern of a Python float cast to single precision."""
    return struct.unpack("<I", struct.pack("<f", x))[0]


def parse_dump(text: str):
    """Yield (slot, req, inputs[5], feat_bits[6]) for each dump line."""
    for line in text.splitlines():
        m = LINE_RE.search(line)
        if not m:
            continue
        g = m.groups()
        slot = int(g[0])
        req = int(g[1])
        inputs = [f32_from_hex(h) for h in g[2:7]]
        feat_bits = [int(h, 16) for h in g[7:7 + mwv.FEATURE_DIM]]
        yield slot, req, inputs, feat_bits


def check(text: str):
    """Recompute features from KTX's dumped inputs; diff vs KTX's dumped feats."""
    rows = 0
    mismatches = []
    slots_seen = set()
    for slot, req, (vx, vy, vz, yaw, pitch), ktx_bits in parse_dump(text):
        rows += 1
        slots_seen.add(slot)
        py = mwv.state_features(vx, vy, vz, yaw, pitch)
        py_bits = [f32_bits(v) for v in py]
        if py_bits != ktx_bits:
            mismatches.append(
                {
                    "slot": slot,
                    "req": req,
                    "inputs_f32_hex": [f"{f32_bits(v):08x}" for v in (vx, vy, vz, yaw, pitch)],
                    "ktx_feat_hex": [f"{b:08x}" for b in ktx_bits],
                    "python_feat_hex": [f"{b:08x}" for b in py_bits],
                }
            )
    return rows, sorted(slots_seen), mismatches


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("dump", type=Path, help="KTX run log containing [moveprobe-dump] lines")
    ap.add_argument("--out", type=Path, help="write evidence JSON here")
    ap.add_argument("--meta", type=json.loads, default={},
                    help="extra JSON merged into the evidence (ktx_commit, host, ...)")
    ap.add_argument("--max-mismatch-samples", type=int, default=20,
                    help="cap mismatch samples stored in the JSON (count is always exact)")
    args = ap.parse_args(argv)

    text = args.dump.read_text(errors="replace")
    rows, slots, mismatches = check(text)

    if rows == 0:
        print("ERROR: no [moveprobe-dump] lines found -- is k_fb_moveprobe_live_dump set?",
              file=sys.stderr)
        return 2

    evidence = {
        **args.meta,
        "feature_names": mwv.FEATURE_NAMES,
        "ticks": rows,
        "slots": slots,
        "parity": {
            "scheme": "exact-f32-bit",
            "recomputed_from": "ktx-dumped inputs",
            "mismatched_ticks": len(mismatches),
            "max_ulp_diff": 0 if not mismatches else None,
        },
        "mismatch_samples": mismatches[: args.max_mismatch_samples],
        "not_this_ticket": {
            "pmove_resim_fidelity": "T0.7 #212 / artifacts/pmove-validation",
        },
    }
    if args.out:
        args.out.write_text(json.dumps(evidence, indent=2) + "\n", newline="\n")

    ok = len(mismatches) == 0
    print(f"ticks={rows} slots={slots} mismatched={len(mismatches)} -> "
          + ("PASS (live seam == offline, exact f32-bit)" if ok else "FAIL"))
    if not ok:
        for s in mismatches[:5]:
            print("  mismatch:", json.dumps(s), file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
