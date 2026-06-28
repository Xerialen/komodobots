"""Anti-drift guard: the KTX live-mode patch stack must apply clean-room.

The live-mode KTX bot is built by applying ``experiments/ktx_moveprobe/*.patch`` in a
fixed order onto ``QW-Group/ktx@08807da`` (see ``experiments/ktx_moveprobe/T0.3_LIVE_MODE.md``).
Those patches are external to this repo, so a silent drift between two of them is
invisible to normal CI until a rebuild fails. That is exactly what blocked the T3.1
handoff toggle (#422 / PR #454): ``-p99`` was refined (its call site wrapped in
``if (live_log) {...}``) *after* ``-fraction`` was generated against the bare form, so
the committed stack no longer applied clean-room and ``-fraction`` failed at
``bot_movement.c:3270``.

This test reproduces the documented apply sequence -- now through the ``handoff``
toggle (#422 T3.1) that landed on top -- against a pinned snapshot of the three files
the stack MODIFIES (``tests/fixtures/ktx_08807da/`` -- the ``live``/``handoff`` patches
*create* the ``move_*`` units, so they need no pre-image) and asserts every patch
applies with rc=0, in order. No network clone, no compiler -- just ``git apply`` -- so
it is hermetic and safe in the gating floor.
"""
import logging
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

LOGGER = logging.getLogger(__name__)

REPO = Path(__file__).resolve().parent.parent
PATCH_DIR = REPO / "experiments" / "ktx_moveprobe"
FIXTURE = REPO / "tests" / "fixtures" / "ktx_08807da"

# The documented clean-room apply order (T0.3_LIVE_MODE.md + T3.1_HANDOFF.md). The
# order is load-bearing: live + dump + p99 + fraction + handoff all edit
# bot_movement.c and each builds on the prior tree. `handoff` (#422 T3.1) applies
# last; it also edits CMakeLists.txt and creates move_highway.*/route_canon_dm3.h
# (new-file hunks, no pre-image needed).
PATCH_STACK = (
    "frogbot-moveprobe-perslot.patch",
    "frogbot-moveprobe-live.patch",
    "frogbot-moveprobe-live-dump.patch",
    "frogbot-moveprobe-live-p99.patch",
    "frogbot-moveprobe-live-fraction.patch",
    "frogbot-moveprobe-handoff.patch",
)

_GIT = shutil.which("git")


def _seed(dest: Path) -> None:
    """Copy the pinned base snapshot into a throwaway tree."""
    shutil.copytree(FIXTURE, dest, dirs_exist_ok=True)
    (dest / "README.md").unlink(missing_ok=True)  # fixture doc, not part of the tree


@unittest.skipUnless(_GIT, "git not on PATH")
class KtxPatchStackAppliesCleanRoom(unittest.TestCase):
    def test_stack_applies_in_documented_order(self):
        with tempfile.TemporaryDirectory() as td:
            tree = Path(td) / "ktx"
            _seed(tree)
            for name in PATCH_STACK:
                patch = PATCH_DIR / name
                self.assertTrue(patch.is_file(), f"missing patch: {patch}")
                proc = subprocess.run(
                    [_GIT, "apply", "--recount", str(patch)],
                    cwd=tree, capture_output=True, text=True,
                )
                if proc.returncode != 0:
                    self.fail(
                        f"clean-room apply DRIFTED at '{name}' (rc={proc.returncode}). "
                        f"The KTX live-mode patch stack no longer applies in the "
                        f"documented order onto ktx@08807da -- regenerate the offending "
                        f"patch so the full stack applies.\ngit apply stderr:\n{proc.stderr}"
                    )
                LOGGER.info("clean-room apply ok: %s", name)

    def test_fraction_counter_on_applied_live_path(self):
        # Guard the SPECIFIC drift: the fraction per-frame LIVE counter must land on
        # the applied-live branch (between *jumping and the LIVE status log), so the
        # freshness gate's live=<live>/<total> ratio is counted whatever form -p99 takes.
        with tempfile.TemporaryDirectory() as td:
            tree = Path(td) / "ktx"
            _seed(tree)
            for name in PATCH_STACK:
                subprocess.run(
                    [_GIT, "apply", "--recount", str(PATCH_DIR / name)],
                    cwd=tree, check=True, capture_output=True, text=True,
                )
            text = (tree / "src" / "bot_movement.c").read_text()
            start = text.index("*jumping = (mv.jump != 0) ? true : false;")
            end = text.index("BotMoveProbeLiveLog(slot, 1,", start)
            applied_block = text[start:end]
            self.assertIn(
                "moveprobe_live_frames[slot]++;", applied_block,
                "fraction live-frame counter is not on the applied-live path",
            )


if __name__ == "__main__":
    unittest.main()
