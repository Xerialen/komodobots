#!/usr/bin/env python3
"""Bake the golden world-view feature vectors for the T0.5 parity gate (#210).

Reads a committed human-replay .cmds demo, runs each tick's (vx,vy,vz,yaw,pitch)
through the canonical scripts/move_world_view.state_features, and writes the
expected 6 features per tick as f32 IEEE-754 hex -- the exact bit pattern that
crosses the live shm VIEW. tests/test_golden_vector_parity.py then locks BOTH the
Python module and the C live unit against this committed golden over real dm3
gameplay (the dynamic counterpart of the synthetic grid in test_live_c_parity.py).

Regenerate ONLY after a deliberate world-view change or a demo swap:

    python scripts/build_golden_vector_fixture.py

then commit tests/fixtures/golden_vector_parity.tsv.
"""
from __future__ import annotations

import logging
import argparse
import hashlib
import struct
import sys
from pathlib import Path


LOGGER = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import move_world_view as mwv  # noqa: E402

SCHEMA = "komodobots.golden_vector.v1"
DEFAULT_DEMO = (ROOT / "experiments" / "nav_doctrine" / "evidence" / "replay"
                / "dm3_sng_shortcut2.cmds")
DEFAULT_OUT = ROOT / "tests" / "fixtures" / "golden_vector_parity.tsv"


def normalized_sha256(path: Path) -> str:
    """SHA-256 of the file with CRLF normalized to LF (Windows/Linux invariant)."""
    data = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def read_cmds_states(path: Path):
    """Yield (row_idx, msec, (vx, vy, vz, yaw, pitch)) for each data row.

    .cmds column convention (komodobots.replay.v1; see tests/test_edge_speed.py):
        0=msec 1=ox 2=oy 3=oz 4=vx 5=vy 6=vz 7=pitch 8=yaw 9=roll ...
    state_features wants (vx, vy, vz, yaw, pitch) -> columns (4, 5, 6, 8, 7);
    the yaw/pitch swap (col 8 is yaw, col 7 is pitch) is the one easy bug, pinned here.
    """
    idx = 0
    for ln in path.read_text().splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        p = ln.split()
        if len(p) < 14:
            continue
        msec = int(float(p[0]))
        state = (float(p[4]), float(p[5]), float(p[6]), float(p[8]), float(p[7]))
        yield idx, msec, state
        idx += 1


def f32_hex(x) -> str:
    return f"{struct.unpack('<I', struct.pack('<f', float(x)))[0]:08x}"


def build_lines(demo: Path) -> list[str]:
    rows = list(read_cmds_states(demo))
    header = (f"# {SCHEMA} demo={demo.name} cmds_sha256={normalized_sha256(demo)} "
              f"rows={len(rows)} feature_names={','.join(mwv.FEATURE_NAMES)}")
    lines = [header]
    for idx, msec, state in rows:
        feats = mwv.state_features(*state)
        hexes = "\t".join(f32_hex(v) for v in feats)
        lines.append(f"{idx}\t{msec}\t{hexes}")
    return lines


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--demo", type=Path, default=DEFAULT_DEMO,
                    help="source .cmds replay (default: dm3_sng_shortcut2)")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT,
                    help="golden TSV output path")
    args = ap.parse_args(argv)
    lines = build_lines(args.demo)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    # newline="\n" forces LF on every platform so the committed golden + its
    # sha are Windows/Linux invariant (matches the repo's LF-normalized goldens).
    args.out.write_text("\n".join(lines) + "\n", newline="\n")
    print(f"wrote {args.out} ({len(lines) - 1} rows) from {args.demo.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
