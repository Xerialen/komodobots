from __future__ import annotations

import argparse
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import run_lab_qtv as qtv


class PortAndSessionTests(unittest.TestCase):
    def test_session_name_uses_lab_owned_prefix(self) -> None:
        name = qtv.session_name("dm3", 28599, "20260607T000000Z")
        self.assertTrue(name.startswith(qtv.SESSION_PREFIX + "_"))
        self.assertEqual(name, "komodobots_qtv_dm3_28599_20260607T000000Z")

    def test_derive_qtv_port_defaults_to_offset(self) -> None:
        self.assertEqual(qtv.derive_qtv_port(28599, None), 28599 + qtv.QTV_PORT_OFFSET)
        # an explicit port wins.
        self.assertEqual(qtv.derive_qtv_port(28599, 28000), 28000)

    def test_next_free_port_returns_first_free(self) -> None:
        busy = {28599, 28600}
        port = qtv.next_free_port(lambda p: p not in busy, 28599)
        self.assertEqual(port, 28601)

    def test_next_free_port_raises_when_none_free(self) -> None:
        with self.assertRaises(RuntimeError):
            qtv.next_free_port(lambda p: False, 28599, span=3)


class WatchInfoTests(unittest.TestCase):
    def test_build_watch_info_shapes_urls(self) -> None:
        info = qtv.build_watch_info("203.0.113.7", 28699, "komodobots-lab-qtv:28599")
        self.assertEqual(info["tcp_stream"], "tcp:203.0.113.7:28699")
        self.assertEqual(info["ezquake_command"], "qtvplay tcp:203.0.113.7:28699")
        self.assertEqual(info["hub_url"], qtv.HUB_URL)
        self.assertEqual(info["server_hostname"], "komodobots-lab-qtv:28599")


class CfgTests(unittest.TestCase):
    def _cfg(self, **overrides: object) -> str:
        params = dict(
            run_id="20260607T000000Z",
            game_port=28599,
            qtv_port=28699,
            qtv_password="",
            public_host="203.0.113.7",
            map_name="dm3",
            hostname="komodobots-lab-qtv:28599",
        )
        params.update(overrides)
        return qtv.build_qtv_cfg(**params)  # type: ignore[arg-type]

    def test_cfg_contains_required_qtv_cvars(self) -> None:
        cfg = self._cfg()
        self.assertIn("qtv_streamport 28699", cfg)
        self.assertIn('sv_mvdhost "203.0.113.7:28699"', cfg)
        self.assertIn("qtv_maxstreams", cfg)
        self.assertIn('hostname "komodobots-lab-qtv:28599"', cfg)
        self.assertIn("set k_defmap dm3", cfg)
        # spectating wants no time cap so the FFA keeps streaming.
        self.assertIn("timelimit 0", cfg)

    def test_cfg_omits_moveprobe_cvars(self) -> None:
        # Bots run stock for spectating; none of the experiment cvars belong here,
        # so this config cannot perturb ongoing movement experiments.
        cfg = self._cfg()
        self.assertNotIn("moveprobe", cfg)

    def test_cfg_password_quotes_are_stripped(self) -> None:
        cfg = self._cfg(qtv_password='ab"cd')
        self.assertIn('qtv_password "abcd"', cfg)

    def test_cfg_is_self_describing_about_non_disruption(self) -> None:
        cfg = self._cfg()
        self.assertIn("Does NOT modify nQuake-managed configs", cfg)


class ValidationTests(unittest.TestCase):
    def test_validate_session_rejects_non_lab_sessions(self) -> None:
        with self.assertRaises(argparse.ArgumentTypeError):
            qtv.validate_session("turkishbathhouse_28501")
        self.assertEqual(
            qtv.validate_session("komodobots_qtv_dm3_28599_run"),
            "komodobots_qtv_dm3_28599_run",
        )

    def test_validate_public_host_accepts_auto_ip_dns(self) -> None:
        self.assertEqual(qtv.validate_public_host("auto"), "auto")
        self.assertEqual(qtv.validate_public_host("203.0.113.7"), "203.0.113.7")
        self.assertEqual(qtv.validate_public_host("lab.example.net"), "lab.example.net")
        with self.assertRaises(argparse.ArgumentTypeError):
            qtv.validate_public_host("not a host!")

    def test_validate_port_range(self) -> None:
        self.assertEqual(qtv.validate_port("28599"), 28599)
        with self.assertRaises(argparse.ArgumentTypeError):
            qtv.validate_port("70000")

    def test_validate_map_and_run_id(self) -> None:
        self.assertEqual(qtv.validate_map_name("dm3"), "dm3")
        with self.assertRaises(argparse.ArgumentTypeError):
            qtv.validate_map_name("bad name")
        with self.assertRaises(argparse.ArgumentTypeError):
            qtv.validate_run_id("bad/id")


class ParserTests(unittest.TestCase):
    def test_parser_requires_subcommand(self) -> None:
        parser = qtv.build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args([])

    def test_up_defaults(self) -> None:
        parser = qtv.build_parser()
        args = parser.parse_args(["up"])
        self.assertEqual(args.map_name, "dm3")
        self.assertEqual(args.bot_count, 4)
        self.assertEqual(args.public_host, "auto")
        self.assertEqual(args.host, "servexeri")
        self.assertIs(args.func, qtv.cmd_up)

    def test_down_target_must_be_lab_owned(self) -> None:
        parser = qtv.build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["down", "--session", "turkishbathhouse_28501"])


if __name__ == "__main__":
    unittest.main()
