from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch
import argparse


REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(REPO_ROOT), str(REPO_ROOT / "scripts"), str(REPO_ROOT / "lab" / "server")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import run_4v4_validation_lab as live4v4  # noqa: E402


class RemoteScriptShapeTests(unittest.TestCase):
    def test_remote_script_refuses_to_clobber_existing_lab_lock(self) -> None:
        self.assertIn("Lab lock already exists; refusing to clobber it", live4v4.REMOTE_SCRIPT)
        self.assertIn('cat "$lab_lock"', live4v4.REMOTE_SCRIPT)

    def test_remote_script_uses_spectator_shim_and_fixed_team_botcmds(self) -> None:
        script = live4v4.REMOTE_SCRIPT
        self.assertIn("--spectator", script)
        self.assertEqual(script.count('--botcmd "addbot 20 $team1"'), 4)
        self.assertEqual(script.count('--botcmd "addbot 20 $team2"'), 4)
        self.assertIn("--botcmd removeall", script)

    def test_remote_script_limits_to_lab_ports_and_denies_production_ports(self) -> None:
        script = live4v4.REMOTE_SCRIPT
        self.assertIn("28599|2860[0-9]", script)
        self.assertIn("28501|28502|28503", script)
        self.assertIn("Refusing production port", script)

    def test_remote_script_copies_raw_ktx_json_sidecar_for_ledger(self) -> None:
        self.assertIn('cp -- "${demo%.mvd}.json" "$rundir/ktxstats.json"', live4v4.REMOTE_SCRIPT)

    def test_remote_config_allows_ktx_4v4_mode(self) -> None:
        script = live4v4.REMOTE_SCRIPT
        self.assertIn("set k_allowed_free_modes 4095", script)
        self.assertIn("set k_defmode 4on4", script)
        self.assertIn("maxclients 9", script)
        self.assertIn("set k_maxclients 8", script)
        self.assertIn("set sv_login 0", script)
        self.assertIn("set k_lockmap 1", script)
        self.assertNotIn("\nk_maxclients 8", script)


class PortSelectionTests(unittest.TestCase):
    def test_choose_lab_port_refuses_non_lab_port(self) -> None:
        with self.assertRaises(RuntimeError):
            live4v4.choose_lab_port("servexeri", 28501, strict=True)

    def test_choose_lab_port_scans_allowlist_only(self) -> None:
        queried: list[int] = []

        def fake_port_down(_host: str, port: int) -> bool:
            queried.append(port)
            return port == 28601

        with patch.object(live4v4, "remote_port_is_down", fake_port_down):
            self.assertEqual(live4v4.choose_lab_port("servexeri", 28599, strict=False), 28601)

        self.assertTrue(all(28599 <= port <= 28609 for port in queried))
        self.assertIn(28601, queried)


class ArgumentValidationTests(unittest.TestCase):
    def test_run_id_rejects_path_or_shell_characters(self) -> None:
        for bad in ("../x", "x;y", "x y"):
            with self.subTest(bad=bad), self.assertRaises(argparse.ArgumentTypeError):
                live4v4.validate_run_id_arg(bad)

    def test_remote_binary_rejects_paths_and_shell_characters(self) -> None:
        self.assertEqual(live4v4.validate_remote_bin_arg("mvdsv-lab"), "mvdsv-lab")
        for bad in ("../mvdsv", "mvdsv;rm", "mvdsv lab"):
            with self.subTest(bad=bad), self.assertRaises(argparse.ArgumentTypeError):
                live4v4.validate_remote_bin_arg(bad)


class LiveLeapWiringTests(unittest.TestCase):
    def test_leap_cvar_block_enables_mode30_on_leap_edicts_only(self) -> None:
        block = live4v4.build_leap_cvar_block("komodo_move_t07", 3)
        # leap bots seat at edicts 2..5 (slots 1..4) behind the slot-0 spectator
        for edict in (2, 3, 4, 5):
            self.assertIn(f"set k_fb_moveprobe_mode_s{edict} 30", block)
        # the frog edicts must stay stock -- never mode 30
        for edict in (1, 6, 7, 8, 9):
            self.assertNotIn(f"set k_fb_moveprobe_mode_s{edict} 30", block)
        self.assertIn('set k_fb_moveprobe_live_shm_name "komodo_move_t07"', block)
        self.assertIn("set k_fb_moveprobe_live_stale_ticks 3", block)

    def test_sidecar_command_attaches_without_create(self) -> None:
        cmd = live4v4.build_sidecar_command(
            "~/t0.3-venv/bin/python", "~/komodo-t0.3/scripts/move_policy_sidecar.py",
            "komodo_move_t07", "~/move_bc_policy.pt", 77,
        )
        self.assertIn("cd ~/komodo-t0.3/scripts &&", cmd)
        self.assertIn("--shm-name komodo_move_t07", cmd)
        self.assertIn("--ckpt ~/move_bc_policy.pt", cmd)
        self.assertIn("--hz 77", cmd)
        self.assertNotIn("--create", cmd)  # KTX owns the region; sidecar mirrors

    def test_b64_roundtrips(self) -> None:
        import base64

        text = 'set a 1\nset b "x"\n'
        self.assertEqual(base64.b64decode(live4v4._b64(text)).decode("utf-8"), text)

    def test_remote_script_wires_live_leap(self) -> None:
        script = live4v4.REMOTE_SCRIPT
        self.assertIn('live_leap="${9:-0}"', script)
        self.assertIn('shm_name="${10:-}"', script)
        self.assertIn('leap_cvars_b64="${11:-}"', script)
        self.assertIn('sidecar_cmd_b64="${12:-}"', script)
        # cfg gets the leap cvars; sidecar attaches once the region appears
        self.assertIn("base64 -d >> \"$cfg_path\"", script)
        self.assertIn('[ -e "/dev/shm/$shm_name" ]', script)
        self.assertIn('eval "$sidecar_cmd"', script)
        # and is torn down (cleanup + post-match)
        self.assertIn("move_policy_sidecar.py --shm-name $shm_name", script)

    def test_remote_script_unlinks_region_on_normal_path(self) -> None:
        # The success path clears the EXIT trap (trap - EXIT), so the region must
        # be removed inline post-match, not only in cleanup().
        script = live4v4.REMOTE_SCRIPT
        self.assertIn('rm -f "/dev/shm/$shm_name"', script)
        self.assertIn("trap - EXIT", script)

    def test_remote_script_fails_run_when_live_brain_never_serves(self) -> None:
        # P1: mode 30 falls back to stock Frogbot silently, so the run MUST fail
        # (non-zero exit) if the region never appeared or the sidecar died early --
        # otherwise a frog-vs-frog match gets scored under a live-leap label.
        script = live4v4.REMOTE_SCRIPT
        self.assertIn('touch "$rundir/sidecar.started"', script)
        self.assertIn('echo "$?" > "$rundir/sidecar.exitcode"', script)
        self.assertIn('if [ ! -f "$rundir/sidecar.started" ]; then', script)
        self.assertIn('kill -0 "$sidecar_pid"', script)
        # both integrity failures abort the run before it is scored
        self.assertEqual(script.count("exit 9"), 2)
        self.assertIn("mislabeled as live-leap", script)

    def test_remote_script_gates_shm_cleanup_on_live_and_ownership(self) -> None:
        # P2: cleanup() must not pkill/unlink the shared region unless THIS
        # invocation is a live run that actually started the sidecar -- else a
        # losing lock-race invocation stomps the active run's sidecar/region.
        script = live4v4.REMOTE_SCRIPT
        self.assertIn(
            'if [ "$live_leap" = "1" ] && [ -n "$sidecar_pid" ] && [ -n "$shm_name" ]; then',
            script,
        )

    def test_main_live_leap_requires_leap_team(self) -> None:
        rc = live4v4.main(["--live-leap", "--skip-prereq-check"])
        self.assertEqual(rc, 2)

    def test_run_remote_passes_live_leap_positional_args_in_order(self) -> None:
        import tempfile

        captured: dict = {}

        class _Proc:
            returncode = 0
            stdout = ""
            stderr = ""

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            return _Proc()

        with tempfile.TemporaryDirectory() as td, patch.object(live4v4, "run", fake_run):
            live4v4.run_remote_4v4_lab(
                host="servexeri", run_id="rid", port=28599, duration=5.0,
                map_name="dm3", timelimit=5, mvdsv_bin="mvdsv-lab",
                team1="leap", team2="frog", local_run_dir=Path(td),
                live_leap=True, shm_name="komodo_move_t07",
                leap_cvars="set k_fb_moveprobe_mode_s2 30\n",
                sidecar_cmd="cd x && y --shm-name komodo_move_t07",
            )
        # last four positional args after team2: live_leap, shm, b64(cvars), b64(cmd)
        tail = captured["cmd"][-4:]
        self.assertEqual(tail[0], "1")
        self.assertEqual(tail[1], "komodo_move_t07")
        self.assertEqual(live4v4._b64("set k_fb_moveprobe_mode_s2 30\n"), tail[2])
        self.assertEqual(live4v4._b64("cd x && y --shm-name komodo_move_t07"), tail[3])

    def test_run_remote_off_by_default(self) -> None:
        import tempfile

        captured: dict = {}

        class _Proc:
            returncode = 0
            stdout = ""
            stderr = ""

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            return _Proc()

        with tempfile.TemporaryDirectory() as td, patch.object(live4v4, "run", fake_run):
            live4v4.run_remote_4v4_lab(
                host="servexeri", run_id="rid", port=28599, duration=5.0,
                map_name="dm3", timelimit=5, mvdsv_bin="mvdsv-lab",
                team1="leap", team2="frog", local_run_dir=Path(td),
            )
        self.assertEqual(captured["cmd"][-4], "0")  # live_leap off


if __name__ == "__main__":
    unittest.main()
