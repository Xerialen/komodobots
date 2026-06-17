#!/usr/bin/env python3
"""Drift guard: the KTX live-mode patch embeds the live unit -- keep it in sync
(bot-program T0.3 / PR-B).

`experiments/ktx_moveprobe/frogbot-moveprobe-live.patch` adds the live-brain C
unit into the KTX source tree as new files (`src/move_world_view.{c,h}`,
`src/move_shm.{c,h}`) plus the CMake + bot_movement.c wiring. Those embedded
copies MUST stay byte-identical to the canonical, CI-byte-matched unit in
`experiments/ktx_moveprobe/live/` -- otherwise the patch the box builds would
diverge from the contract `tests/test_live_c_parity.py` pins.

This test extracts each new-file body from the patch and asserts it equals the
canonical file, so any edit to one without the other fails CI. Pure stdlib, no
network, no compiler.

Run locally:  python3 -m unittest tests.test_live_patch_sync -v
"""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIVE_DIR = ROOT / "experiments" / "ktx_moveprobe" / "live"
PATCH = ROOT / "experiments" / "ktx_moveprobe" / "frogbot-moveprobe-live.patch"

# canonical file in live/  ->  the src/ path the patch adds it as
EMBEDDED = {
    "move_world_view.h": "src/move_world_view.h",
    "move_world_view.c": "src/move_world_view.c",
    "move_shm.h": "src/move_shm.h",
    "move_shm.c": "src/move_shm.c",
}


def _extract_new_file(patch_text: str, src_path: str) -> str:
    """Return the body of a `new file` section for `src_path` from a git diff.

    Collects the `+` lines of the file's single 0-based hunk, strips the leading
    `+`, and rejoins -- i.e. the literal file content the patch would create.
    """
    lines = patch_text.splitlines()
    header = f"diff --git a/{src_path} b/{src_path}"
    try:
        i = lines.index(header)
    except ValueError:
        raise AssertionError(f"patch has no section for {src_path}")
    # the section must be a new-file addition
    section = []
    saw_new_file = False
    saw_hunk = False
    i += 1
    while i < len(lines) and not lines[i].startswith("diff --git "):
        ln = lines[i]
        if ln.startswith("new file mode"):
            saw_new_file = True
        elif ln.startswith("@@ "):
            saw_hunk = True
        elif saw_hunk:
            if ln.startswith("+"):
                section.append(ln[1:])
            elif ln.startswith("\\"):
                pass  # "\ No newline at end of file"
            else:
                raise AssertionError(
                    f"unexpected non-added line in new-file hunk for {src_path}: {ln!r}")
        i += 1
    if not saw_new_file:
        raise AssertionError(f"{src_path} is not added as a new file in the patch")
    if not saw_hunk:
        raise AssertionError(f"{src_path} has no hunk in the patch")
    return "\n".join(section) + "\n"


class TestLivePatchSync(unittest.TestCase):
    def setUp(self):
        if not PATCH.exists():
            self.fail(f"live patch missing: {PATCH}")
        self.patch_text = PATCH.read_text()

    def test_embedded_copies_match_canonical(self):
        for canonical_name, src_path in EMBEDDED.items():
            canonical = (LIVE_DIR / canonical_name).read_text()
            embedded = _extract_new_file(self.patch_text, src_path)
            self.assertEqual(
                embedded, canonical,
                f"{src_path} embedded in the patch has drifted from the canonical "
                f"experiments/ktx_moveprobe/live/{canonical_name}; regenerate the "
                f"patch (copy live/ into KTX src/ and re-diff).")

    def test_patch_wires_build_and_seam(self):
        # the patch must also add the two sources to CMake and call the live hook
        self.assertIn("diff --git a/CMakeLists.txt b/CMakeLists.txt", self.patch_text)
        self.assertIn("move_world_view.c", self.patch_text)
        self.assertIn("move_shm.c", self.patch_text)
        self.assertIn("BotApplyMoveProbeLive", self.patch_text)
        self.assertIn("mode == 30", self.patch_text)


if __name__ == "__main__":
    unittest.main()
