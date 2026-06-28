#!/usr/bin/env python3
"""Shared compile harness for the C live world-view unit (bot-program, docs/18 wall #2).

Compiles experiments/ktx_moveprobe/live/*.c ONCE per process and exposes the
helpers that both world-view parity gates use:

  * tests/test_live_c_parity.py        -- static synthetic grid (T0.3 PR-A)
  * tests/test_golden_vector_parity.py -- dynamic real-demo golden vectors (T0.5)

Keeping the build in one module means the two gates can never drift in HOW they
compile or invoke the C unit -- which would be ironic for a parity test. The
leading underscore keeps this file out of `unittest discover -p "test_*.py"`.

Skips cleanly (does NOT fail) only when no C compiler is present -- the
"skip if a dep is absent" pattern. GitHub's ubuntu-latest runner has cc, so the
gates run for real in CI. A present-but-failing compile is a hard error.
"""
from __future__ import annotations

import atexit
import os
import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIVE_DIR = ROOT / "experiments" / "ktx_moveprobe" / "live"
C_SOURCES = ["move_world_view.c", "move_shm.c", "move_highway.c", "selftest_main.c"]

# Set at import. HARNESS is the compiled binary path, or None. SKIP_REASON is
# set (and HARNESS left None) only when no compiler exists; a present-but-failing
# compile leaves both None so require_harness() fails loudly instead of skipping.
HARNESS = None
SKIP_REASON = None
BUILD_LOG = ""
_TMPDIR = None


def _build():
    global HARNESS, SKIP_REASON, BUILD_LOG, _TMPDIR
    cc = os.environ.get("CC") or shutil.which("cc") or shutil.which("gcc")
    if not cc:
        SKIP_REASON = ("no C compiler (cc/gcc) found; the C<->Python world-view "
                       "parity gate needs one. CI's ubuntu-latest has gcc.")
        return
    _TMPDIR = tempfile.mkdtemp(prefix="komodo_live_parity_")
    out = os.path.join(_TMPDIR, "live_selftest")
    cmd = [cc, "-O2", "-std=c11", "-Wall", "-Wextra",
           "-o", out] + [str(LIVE_DIR / s) for s in C_SOURCES] + ["-lm"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    BUILD_LOG = f"$ {' '.join(cmd)}\n{proc.stdout}{proc.stderr}"
    if proc.returncode == 0 and os.path.exists(out):
        HARNESS = out
    else:
        SKIP_REASON = None  # compiler present but build failed -> a real defect
        HARNESS = None


_build()


@atexit.register
def _cleanup():
    if _TMPDIR and os.path.isdir(_TMPDIR):
        shutil.rmtree(_TMPDIR, ignore_errors=True)


def require_harness(case: unittest.TestCase):
    """Skip the case if no compiler; fail it if the compile broke."""
    if HARNESS is None and SKIP_REASON is not None:
        case.skipTest(SKIP_REASON)
    if HARNESS is None:
        case.fail("C live unit failed to compile (compiler present):\n" + BUILD_LOG)


def run(*args, stdin: str | None = None) -> str:
    """Invoke the compiled selftest harness and return stdout (raises on rc!=0)."""
    proc = subprocess.run([HARNESS, *args], input=stdin,
                          capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise AssertionError(
            f"harness {args} rc={proc.returncode}\nstdout={proc.stdout}\n"
            f"stderr={proc.stderr}")
    return proc.stdout


def f32_bits(x) -> int:
    """IEEE-754 bits of x rounded to single precision (the shm wire precision)."""
    return struct.unpack("<I", struct.pack("<f", float(x)))[0]
