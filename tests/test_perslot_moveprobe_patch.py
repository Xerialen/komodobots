"""LD-F1 (#95): structural guard for the committed per-slot KTX patch.

CI cannot compile KTX, so this asserts the contract the rest of the lab
depends on: the per-slot helper + all four wired params exist in the patch,
the loud-fail and ASSIGN emitters use exactly the format strings the Python
parsers expect (drift guard against moveprobe_parse.py), and the patch stays
additive with respect to the FBMOVEPROBE_CMD stream.

The patch applies to the LIVE deployed lab tree (08807da plus all lab
modifications), not to a pristine KTX 08807da checkout; base checksums are
recorded in experiments/ktx_moveprobe/README.md.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from moveprobe_parse import (
    parse_moveprobe_assign_line,
    parse_moveprobe_perslot_error_logs,
)

PATCH_PATH = (
    REPO_ROOT / "experiments" / "ktx_moveprobe" / "frogbot-moveprobe-perslot.patch"
)

# The exact C string literals the patch must emit with. The sample rows in
# test_moveprobe_assign_parse.py are rendered per these formats.
ASSIGN_FORMAT_SEGMENTS = [
    'FBMOVEPROBE_ASSIGN time=%.3f ed=%d name=%s mode=%d mode_src=%s ',
    'replay_file=%s replay_src=%s fixed_goal=%d goal_src=%s ',
    'spawn_origin=%s spawn_src=%s\\n',
]
ERROR_FORMAT = (
    'FBMOVEPROBE_PERSLOT_ERROR time=%.3f ed=%d name=%s param=%s value=%s reason=%s\\n'
)


class PerSlotPatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = PATCH_PATH.read_text(encoding="utf-8", errors="replace")
        cls.added = [
            line[1:]
            for line in cls.text.splitlines()
            if line.startswith("+") and not line.startswith("+++")
        ]
        cls.removed = [
            line[1:]
            for line in cls.text.splitlines()
            if line.startswith("-") and not line.startswith("---")
        ]
        cls.added_blob = "\n".join(cls.added)

    def test_patch_targets_both_files(self) -> None:
        self.assertIn("diff --git a/src/bot_movement.c b/src/bot_movement.c", self.text)
        self.assertIn("diff --git a/src/bot_botgoals.c b/src/bot_botgoals.c", self.text)

    def test_per_slot_helper_and_naming_convention(self) -> None:
        self.assertIn("int BotMoveProbeCvarStringForBot(", self.added_blob)
        self.assertIn("int BotMoveProbeCvarIntForBot(", self.added_blob)
        # The convention itself: k_fb_moveprobe_<param>_s<N>.
        self.assertIn('"k_fb_moveprobe_%s_s%d"', self.added_blob)
        # The global fallback read keeps unset slots additive.
        self.assertIn('"k_fb_moveprobe_%s"', self.added_blob)

    def test_all_four_params_are_wired(self) -> None:
        self.assertIn('BotMoveProbeCvarIntForBot(self, "mode"', self.added_blob)
        self.assertIn('BotMoveProbeCvarStringForBot(self, "replay_file"', self.added_blob)
        self.assertIn('BotMoveProbeCvarIntForBot(self, "fixed_goal"', self.added_blob)
        self.assertIn('BotMoveProbeCvarStringForBot(self, "spawn_origin"', self.added_blob)

    def test_replaces_the_global_call_sites(self) -> None:
        # The old single-source reads must actually be removed, not duplicated.
        removed_blob = "\n".join(self.removed)
        self.assertIn('cvar("k_fb_moveprobe_mode")', removed_blob)
        self.assertIn('trap_cvar_string("k_fb_moveprobe_replay_file"', removed_blob)
        self.assertIn('cvar("k_fb_moveprobe_fixed_goal")', removed_blob)
        self.assertIn('trap_cvar_string("k_fb_moveprobe_spawn_origin"', removed_blob)

    def test_loud_fail_emitter_format(self) -> None:
        self.assertIn(ERROR_FORMAT, self.added_blob)
        # Hold-at-spawn contract markers.
        self.assertIn("BotMoveProbeReportPerSlotError", self.added_blob)
        self.assertIn("fb_moveprobe_perslot_goal_error", self.added_blob)

    def test_assign_emitter_format(self) -> None:
        for segment in ASSIGN_FORMAT_SEGMENTS:
            self.assertIn(segment, self.added_blob, segment)

    def test_assign_format_round_trips_through_parser(self) -> None:
        # Render a row exactly per the C format segments and parse it back.
        c_format = "".join(ASSIGN_FORMAT_SEGMENTS).replace("\\n", "\n")
        rendered = (
            c_format.replace("%.3f", "{:.3f}")
            .replace("%d", "{}")
            .replace("%s", "{}")
            .format(
                7.125, 3, "/ goldenboy", 21, "slot",
                "dm3_sng_to_rl.cmds", "slot", 42, "global",
                "100.0,200.0,-24.0", "slot",
            )
        )
        row = parse_moveprobe_assign_line(rendered)
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["mode"], 21)
        self.assertEqual(row["replay_file"], "dm3_sng_to_rl.cmds")

    def test_error_format_round_trips_through_parser(self) -> None:
        c_format = ERROR_FORMAT.replace("\\n", "\n")
        rendered = (
            c_format.replace("%.3f", "{:.3f}")
            .replace("%d", "{}")
            .replace("%s", "{}")
            .format(9.5, 4, "/ bro", "spawn_origin", "100,abc", "bad_origin_triplet")
        )
        errors = parse_moveprobe_perslot_error_logs(rendered)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["reason"], "bad_origin_triplet")

    def test_additive_command_stream(self) -> None:
        # The FBMOVEPROBE_CMD row format must be untouched (additive guarantee:
        # a run with no per-slot cvars set keeps an identical command stream).
        for line in self.removed:
            self.assertNotIn("FBMOVEPROBE_CMD ", line)
        # The legacy replay load rows keep their exact shape (the loader was
        # rewritten, so they move, but the emitted format must survive).
        self.assertIn("FBMOVEPROBE_REPLAY load_failed file=%s", self.added_blob)
        self.assertIn("FBMOVEPROBE_REPLAY loaded file=%s frames=%d", self.added_blob)

    def test_per_slot_replay_store_is_bounded(self) -> None:
        self.assertIn("#define MOVEPROBE_REPLAY_MAX_FILES 4", self.added_blob)
        self.assertIn("moveprobe_replay_store_for_slot", self.added_blob)

    def test_spawn_snap_latch_rearms_on_per_slot_change(self) -> None:
        # Review fix (#95 P2): a per-slot spawn_origin edited mid-session must
        # re-arm the one-shot snap latch so the new value is re-parsed and a
        # malformed triplet loud-fails instead of being silently ignored.
        self.assertIn("moveprobe_spawn_last[MAX_CLIENTS][64]", self.added_blob)
        self.assertIn("moveprobe_spawn_last_from_slot[MAX_CLIENTS]", self.added_blob)
        self.assertIn(
            "if ((snap_from_slot || moveprobe_spawn_last_from_slot[slot])",
            self.added_blob,
        )
        self.assertIn("moveprobe_spawn_snapped[slot] = 0;", self.added_blob)


if __name__ == "__main__":
    unittest.main()
