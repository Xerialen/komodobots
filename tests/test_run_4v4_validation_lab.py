from __future__ import annotations

import sys
import tempfile
from types import SimpleNamespace
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

    def test_remote_script_applies_komodobot_cvars_before_addbots(self) -> None:
        script = live4v4.REMOTE_SCRIPT
        self.assertIn("komodobot_cvars_b64", script)
        self.assertIn("komodobot-moveprobe.cvars", script)
        self.assertIn('send_cmd "$cvar_line"', script)
        self.assertLess(script.index("komodobot-moveprobe.cvars"), script.index('log "running spectator shim"'))

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

    def test_komodobot_mode_rejects_non_small_integer(self) -> None:
        self.assertEqual(live4v4.validate_komodobot_mode_arg("10"), 10)
        for bad in ("x", "-1", "100"):
            with self.subTest(bad=bad), self.assertRaises(argparse.ArgumentTypeError):
                live4v4.validate_komodobot_mode_arg(bad)


class AnalyzerEnvironmentTests(unittest.TestCase):
    def test_should_use_wsl_bridge_auto_disables_inside_wsl(self) -> None:
        with patch.object(live4v4, "running_inside_wsl", return_value=True):
            self.assertFalse(live4v4.should_use_wsl_bridge(no_wsl_bridge=False))
        with patch.object(live4v4, "running_inside_wsl", return_value=False):
            self.assertTrue(live4v4.should_use_wsl_bridge(no_wsl_bridge=False))
            self.assertFalse(live4v4.should_use_wsl_bridge(no_wsl_bridge=True))

    def test_ensure_prereqs_omits_wsl_when_using_direct_analyzer(self) -> None:
        required: list[str] = []
        commands: list[list[str]] = []

        def fake_require(tool: str) -> None:
            required.append(tool)

        def fake_run(cmd: list[str], **_kwargs):
            commands.append(cmd)
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch.object(live4v4, "require_tool", fake_require), patch.object(live4v4, "run", fake_run):
            live4v4.ensure_prereqs(
                "servexeri",
                "Ubuntu-24.04",
                "/opt/qw-analyze",
                "dm3",
                "mvdsv-lab",
                use_wsl_bridge=False,
            )

        self.assertEqual(required, ["ssh", "scp", "bash"])
        self.assertEqual(commands[0][0], "ssh")
        self.assertEqual(commands[1], ["bash", "-lc", "test -x /opt/qw-analyze"])

    def test_run_analyzer_can_call_direct_linux_analyzer_without_wsl(self) -> None:
        with tempfile.TemporaryDirectory(prefix="4v4-analyzer-test-") as tmp:
            run_dir = Path(tmp)
            (run_dir / "demo.mvd").write_bytes(b"demo")
            calls: list[list[str]] = []

            def fake_run(cmd: list[str], **_kwargs):
                calls.append(cmd)
                return SimpleNamespace(returncode=1 if cmd[2] == "events" else 0, stdout=f"{cmd[2]} out", stderr="")

            with patch.object(live4v4, "run", fake_run):
                exits = live4v4.run_analyzer(
                    run_dir,
                    "Ubuntu-24.04",
                    "/opt/qw-analyze",
                    use_wsl_bridge=False,
                )

            self.assertEqual(exits, {"json": 0, "md": 0, "events": 1})
            self.assertEqual(calls[0], ["/opt/qw-analyze", "-format", "json", str(run_dir / "demo.mvd")])
            self.assertTrue(all(call[0] != "wsl" for call in calls))
            self.assertEqual((run_dir / "analysis.json").read_text(encoding="utf-8"), "json out")


class KomodobotReplayCvarTests(unittest.TestCase):
    def test_komodobot_cvar_suffix_accounts_for_spectator_client(self) -> None:
        self.assertEqual(live4v4.komodobot_cvar_suffix(1), 2)
        self.assertEqual(live4v4.komodobot_cvar_suffix(8), 9)
        for bad in (0, 9):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                live4v4.komodobot_cvar_suffix(bad)

    def test_build_komodobot_moveprobe_cvars_sets_only_selected_runtime_suffix(self) -> None:
        cvars = live4v4.build_komodobot_moveprobe_cvars(
            cvar_suffix=3,
            mode=10,
            replay_file="bots/replay/dm3_sng_to_rl.cmds",
        )

        self.assertIn("set k_fb_moveprobe_mode_s3 10", cvars)
        self.assertIn("set k_fb_moveprobe_replay_file_s3 bots/replay/dm3_sng_to_rl.cmds", cvars)
        self.assertIn("set k_fb_moveprobe_replay_loop_s3 1", cvars)
        self.assertIn("set k_fb_moveprobe_log_commands 1", cvars)
        self.assertIn("set k_fb_moveprobe_log_interval 1.0", cvars)
        self.assertNotIn("k_fb_moveprobe_mode_s1", cvars)

    def test_build_komodobot_moveprobe_cvars_rejects_unsafe_replay_paths(self) -> None:
        for bad in ("../x.cmds", "bots/replay/x y.cmds", "qw/x.cmds"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                live4v4.build_komodobot_moveprobe_cvars(cvar_suffix=2, mode=10, replay_file=bad)


if __name__ == "__main__":
    unittest.main()
