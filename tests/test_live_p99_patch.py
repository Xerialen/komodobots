#!/usr/bin/env python3
"""Guard: the T0.3 PR-C on-KTX p99 patch is present + well-formed (#209).

`experiments/ktx_moveprobe/frogbot-moveprobe-live-p99.patch` layers lightweight
per-tick cost instrumentation onto the mode-30 seam (`src/bot_movement.c`) on top
of the live patch. CI cannot build KTX, so this asserts the shipped patch is a
valid unified diff that adds the instrumentation to bot_movement.c only -- the
box clean-room build (`experiments/ktx_moveprobe/T0.3_LIVE_MODE.md`) is the
compile proof. Pure stdlib, no network, no compiler.

Run locally:  python3 -m unittest tests.test_live_p99_patch -v
"""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / "experiments" / "ktx_moveprobe" / "frogbot-moveprobe-live-p99.patch"


class TestLiveP99Patch(unittest.TestCase):
    def setUp(self):
        if not PATCH.exists():
            self.fail(f"p99 patch missing: {PATCH}")
        self.text = PATCH.read_text()

    def test_targets_bot_movement_only(self):
        # git-style header, and only bot_movement.c is touched
        self.assertIn("diff --git a/src/bot_movement.c b/src/bot_movement.c", self.text)
        headers = [ln for ln in self.text.splitlines() if ln.startswith("diff --git ")]
        self.assertEqual(headers, ["diff --git a/src/bot_movement.c b/src/bot_movement.c"])

    def test_adds_instrumentation(self):
        added = "\n".join(ln[1:] for ln in self.text.splitlines()
                          if ln.startswith("+") and not ln.startswith("+++"))
        for marker in ("moveprobe_now_us", "moveprobe_p99_record",
                       "moveprobe_p99_maybe_report", "clock_gettime(CLOCK_MONOTONIC",
                       "on-KTX cost"):
            self.assertIn(marker, added,
                          f"p99 patch missing instrumentation marker: {marker!r}")
        # the instrumentation is inserted inside the existing native-only guard:
        # the `#ifndef Q3_VM` directly above it is a context (unchanged) line.
        self.assertIn(" #ifndef Q3_VM\n+#include <time.h>", self.text,
                      "p99 instrumentation must be added inside the native-only guard")

    def test_lf_only(self):
        self.assertNotIn("\r", self.text, "patch must be LF-only (eol=lf)")


if __name__ == "__main__":
    unittest.main()
