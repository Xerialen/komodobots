"""LD-F1 (#95): structural guard for the committed per-slot KTX patch.

CI cannot compile KTX, so this asserts the contract the rest of the lab
depends on: the per-slot helper + all route params exist in the patch,
the loud-fail and ASSIGN emitters use exactly the format strings the Python
parsers expect (drift guard against moveprobe_parse.py), and the patch stays
additive with respect to the FBMOVEPROBE_CMD stream.

The patch applies to a pristine KTX 08807da checkout; base checksums are
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

    def test_all_five_params_are_wired(self) -> None:
        self.assertIn('BotMoveProbeCvarIntForBot(self, "mode"', self.added_blob)
        self.assertIn('BotMoveProbeCvarStringForBot(self, "replay_file"', self.added_blob)
        self.assertIn('BotMoveProbeCvarIntForBot(self, "fixed_goal"', self.added_blob)
        self.assertIn('BotMoveProbeCvarStringForBot(self, "spawn_origin"', self.added_blob)
        self.assertIn('BotMoveProbeCvarStringForBot(self, "spawn_velocity"', self.added_blob)

    def test_replaces_the_global_call_sites(self) -> None:
        # The new call sites must go through the per-slot helpers rather than
        # reintroducing the old single-source global reads.
        self.assertIn('BotMoveProbeCvarIntForBot(self, "mode"', self.added_blob)
        self.assertIn('BotMoveProbeCvarStringForBot(self, "replay_file"', self.added_blob)
        self.assertIn('BotMoveProbeCvarIntForBot(self, "fixed_goal"', self.added_blob)
        self.assertIn('BotMoveProbeCvarStringForBot(self, "spawn_origin"', self.added_blob)
        self.assertIn('BotMoveProbeCvarStringForBot(self, "spawn_velocity"', self.added_blob)
        self.assertNotIn('cvar("k_fb_moveprobe_mode")', self.added_blob)
        self.assertNotIn('trap_cvar_string("k_fb_moveprobe_replay_file"', self.added_blob)
        self.assertNotIn('cvar("k_fb_moveprobe_fixed_goal")', self.added_blob)
        self.assertNotIn('trap_cvar_string("k_fb_moveprobe_spawn_origin"', self.added_blob)

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
        self.assertIn("moveprobe_spawn_velocity_last[MAX_CLIENTS][64]", self.added_blob)
        self.assertIn("moveprobe_spawn_last_from_slot[MAX_CLIENTS]", self.added_blob)
        self.assertIn("moveprobe_spawn_velocity_last_from_slot[MAX_CLIENTS]", self.added_blob)
        self.assertIn(
            "if ((snap_from_slot || snap_velocity_from_slot",
            self.added_blob,
        )
        self.assertIn("moveprobe_spawn_snapped[slot] = 0;", self.added_blob)
        self.assertIn('"spawn_velocity"', self.added_blob)
        self.assertIn('"bad_velocity_triplet"', self.added_blob)

    def test_dashboard_practice_idle_mode_exists(self) -> None:
        # Dashboard sessions seed bots in this global mode so they can spawn,
        # emit ASSIGN state, and then wait still until per-slot route assignment.
        self.assertIn("if (mode == 24)", self.added_blob)
        self.assertIn("Dashboard practice idle", self.added_blob)
        self.assertIn("VectorClear(direction);", self.added_blob)
        self.assertIn("*jumping = false;", self.added_blob)
        self.assertIn("*firing = false;", self.added_blob)
        self.assertIn("*impulse = 0;", self.added_blob)
        self.assertIn("BotApplyMoveProbe(self, &jumping, &firing, &impulse, direction)", self.added_blob)

    def test_ztricks_terminal_carve_primitive_is_default_off_and_logged(self) -> None:
        # The ztricks route turns this on with target/lip cvars; unset target
        # coordinates leave normal mode-23 behavior unchanged.
        for cvar in (
            "k_fb_moveprobe_s23_launch_target_x",
            "k_fb_moveprobe_s23_launch_target_y",
            "k_fb_moveprobe_s23_launch_target_z",
            "k_fb_moveprobe_s23_lip_x",
            "k_fb_moveprobe_s23_lip_y",
            "k_fb_moveprobe_s23_release_vh",
            "k_fb_moveprobe_s23_release_vh_min",
            "k_fb_moveprobe_s23_carve_d",
            "k_fb_moveprobe_s23_carve_angle",
            "k_fb_moveprobe_s23_carve_side",
            "k_fb_moveprobe_s23_release_lip",
            "k_fb_moveprobe_s23_refcurve",
            "k_fb_moveprobe_s23_refcurve_vh_min",
            "k_fb_moveprobe_s23_refcurve_yaw_offset",
            "k_fb_moveprobe_s23_refcurve_entry_x",
            "k_fb_moveprobe_s23_refcurve_entry_y",
            "k_fb_moveprobe_s23_refcurve_y",
            "k_fb_moveprobe_s23_refcurve_y_tol",
            "k_fb_moveprobe_s23_yawlead_min",
            "k_fb_moveprobe_s23_yawlead_max",
            "k_fb_moveprobe_s23_targeterr_min",
            "k_fb_moveprobe_s23_targeterr_max",
        ):
            self.assertIn(cvar, self.added_blob)
        self.assertIn("zjump_enabled = ((ztarget_x != 0.0f)", self.added_blob)
        self.assertIn("BotMoveProbeZtricksReferenceCurve", self.added_blob)
        self.assertIn("BotMoveProbeQuadratic", self.added_blob)
        self.assertIn("zdesired_vel_yaw = anglemod(zdesired_vel_yaw + zrefcurve_yaw_offset);", self.added_blob)
        self.assertIn("zdesired_view_yaw = anglemod(zdesired_view_yaw + zrefcurve_yaw_offset);", self.added_blob)
        self.assertIn("zd_lip = ((zlip_x - self->s.v.origin[0]) * zlip_dx)", self.added_blob)
        self.assertIn("+ ((zlip_y - self->s.v.origin[1]) * zlip_dy);", self.added_blob)
        self.assertIn("fallback_x = zrefcurve_entry_x;", self.added_blob)
        self.assertIn("fallback_y = zrefcurve_entry_y;", self.added_blob)
        self.assertIn("nav_dir[0] = fallback_x - self->s.v.origin[0];", self.added_blob)
        self.assertIn("zrefcurve_y_tol = 24.0f;", self.added_blob)
        self.assertIn("ztrack = (zd_lip >= 0.0f) && (zd_lip <= zcarve_d);", self.added_blob)
        self.assertIn("zterminal = ztrack && ((zrefcurve <= 0.0f) || zcorridor);", self.added_blob)
        self.assertIn("if (zarmed && onground && (zvh >= zrelease_vh)", self.added_blob)
        self.assertIn("direction[1] = sv_maxspeed * zside;", self.added_blob)
        self.assertIn("&& (zd_lip <= zrelease_lip) && press_jump", self.added_blob)
        self.assertIn("zjump=%d,%.3f,%.3f,%.1f,%.1f,%.1f,%.1f,%d,%d", self.added_blob)


if __name__ == "__main__":
    unittest.main()
