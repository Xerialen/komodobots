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


if __name__ == "__main__":
    unittest.main()
