from __future__ import annotations

import argparse
import socket
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

    def test_derive_qtv_port_defaults_to_game_port(self) -> None:
        # The proven servexeri model (live port_2850x.cfg) serves the built-in
        # QTV stream on the SAME port number as the game port, so only one port
        # needs to be firewall-opened. Default qtv == game.
        self.assertEqual(qtv.derive_qtv_port(28599, None), 28599)
        # an explicit port still wins.
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
        info = qtv.build_watch_info("203.0.113.7", 28599, "komodobots-lab-qtv:28599")
        self.assertEqual(info["tcp_stream"], "tcp:203.0.113.7:28599")
        # ezQuake's qtvplay needs a bare host:port -- NOT a tcp: scheme (which it
        # mis-parses as the hostname "tcp"). Regression guard for that bug.
        self.assertEqual(info["ezquake_command"], "qtvplay 203.0.113.7:28599")
        self.assertNotIn("tcp:", info["ezquake_command"])
        self.assertEqual(info["hub_url"], qtv.HUB_URL)
        self.assertEqual(info["server_hostname"], "komodobots-lab-qtv:28599")


class CfgTests(unittest.TestCase):
    def _cfg(self, **overrides: object) -> str:
        params = dict(
            run_id="20260607T000000Z",
            game_port=28599,
            qtv_port=28599,
            qtv_password="",
            map_name="dm3",
            hostname="komodobots-lab-qtv:28599",
            bot_count=4,
        )
        params.update(overrides)
        return qtv.build_qtv_cfg(**params)  # type: ignore[arg-type]

    def test_cfg_contains_required_qtv_cvars(self) -> None:
        cfg = self._cfg()
        self.assertIn("qtv_streamport 28599", cfg)
        self.assertIn("qtv_maxstreams", cfg)
        self.assertIn('hostname "komodobots-lab-qtv:28599"', cfg)
        self.assertIn("set k_defmap dm3", cfg)
        # spectating wants no time cap so the FFA keeps streaming.
        self.assertIn("timelimit 0", cfg)

    def test_cfg_omits_unsupported_sv_mvdhost_cvar(self) -> None:
        # sv_mvdhost does not exist on servexeri's mvdsv build (confirmed: the
        # binary's only qtv cvars are qtv_streamport/qtv_password, and the
        # server logs `Unknown command "sv_mvdhost"`). Emitting it is a no-op
        # error, so the cfg must not contain it.
        cfg = self._cfg()
        self.assertNotIn("sv_mvdhost", cfg)

    def test_cfg_keeps_match_populated_via_autoadd_plus_one(self) -> None:
        # KTX auto-add maintains the bots, but only while a human is present
        # (BotStartFrame requires human_count>0). The reconnect-loop keepalive
        # supplies that presence, so autoadd_limit is bot_count+1 (the +1 covers
        # the keepalive human) to leave exactly bot_count bots.
        cfg = self._cfg(bot_count=4)
        self.assertIn("set k_fb_enabled 1", cfg)
        self.assertIn("set k_fb_autoadd_limit 5", cfg)

    def test_cfg_omits_moveprobe_cvars(self) -> None:
        # Bots run stock for spectating; none of the experiment cvars belong here,
        # so this config cannot perturb ongoing movement experiments.
        cfg = self._cfg()
        self.assertNotIn("moveprobe", cfg)

    def test_cfg_password_quotes_are_stripped(self) -> None:
        cfg = self._cfg(qtv_password='ab"cd')
        self.assertIn('qtv_password "abcd"', cfg)

    def test_cfg_password_rejects_newline_injection(self) -> None:
        with self.assertRaises(argparse.ArgumentTypeError):
            self._cfg(qtv_password="abc\nset admin 1")

    def test_cfg_is_self_describing_about_non_disruption(self) -> None:
        cfg = self._cfg()
        self.assertIn("Does NOT modify nQuake-managed configs", cfg)


class ReconnectLoopTests(unittest.TestCase):
    def test_keepalive_cycle_under_login_timeout(self) -> None:
        # The keepalive MUST reconnect before mvdsv's 60s login timeout so the
        # previous connection still lingers when the next connects (continuous
        # presence). If this invariant breaks, the match drains every cycle.
        self.assertLess(qtv.KEEPALIVE_CYCLE_S, qtv.LOGIN_TIMEOUT_S)

    def test_up_script_runs_presence_only_reconnect_loop(self) -> None:
        # The keepalive adds NO bots (--bot-count 0); KTX autoadd does. And it is
        # a reconnect loop (per cycle), not a single long-lived client.
        self.assertIn("--bot-count 0", qtv.REMOTE_UP_SCRIPT)
        self.assertIn("--run-for $cycle", qtv.REMOTE_UP_SCRIPT)
        self.assertIn("while", qtv.REMOTE_UP_SCRIPT)


class PublicHostTests(unittest.TestCase):
    def test_pick_lan_ip_prefers_192_168(self) -> None:
        # `hostname -I` on servexeri lists LAN, tailscale (100.64/10), docker
        # (172.17) etc. We want the routable LAN address, not CGNAT/docker.
        self.assertEqual(
            qtv.pick_lan_ip("192.168.86.33 100.102.34.74 172.17.0.1"),
            "192.168.86.33",
        )

    def test_pick_lan_ip_skips_cgnat_when_lan_not_first(self) -> None:
        self.assertEqual(
            qtv.pick_lan_ip("100.102.34.74 192.168.86.33"),
            "192.168.86.33",
        )

    def test_pick_lan_ip_falls_back_to_first_token(self) -> None:
        self.assertEqual(qtv.pick_lan_ip("203.0.113.7"), "203.0.113.7")

    def test_pick_lan_ip_empty_raises(self) -> None:
        with self.assertRaises(RuntimeError):
            qtv.pick_lan_ip("   ")


class ReachabilityTests(unittest.TestCase):
    def test_tcp_reachable_true_when_connect_succeeds(self) -> None:
        class _FakeSock:
            def close(self) -> None:
                pass

        def connector(addr, timeout):  # noqa: ANN001
            return _FakeSock()

        self.assertTrue(qtv.tcp_reachable("192.168.86.33", 28599, connector=connector))

    def test_tcp_reachable_false_on_timeout(self) -> None:
        def connector(addr, timeout):  # noqa: ANN001
            raise socket.timeout("timed out")

        self.assertFalse(qtv.tcp_reachable("192.168.86.33", 28599, connector=connector))

    def test_tcp_reachable_false_on_refused(self) -> None:
        def connector(addr, timeout):  # noqa: ANN001
            raise ConnectionRefusedError()

        self.assertFalse(qtv.tcp_reachable("192.168.86.33", 28599, connector=connector))


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
        with self.assertRaises(argparse.ArgumentTypeError):
            qtv.validate_run_id("foo_bar")
        self.assertEqual(qtv.validate_run_id("foo-bar"), "foo-bar")


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
        # Default port must be distinct from the moveprobe lab's 28599 so the
        # two labs never fight for a port (the QTV lab would auto-bump onto a
        # non-firewalled port otherwise).
        self.assertEqual(args.game_port, 28610)
        self.assertNotEqual(args.game_port, 28599)
        self.assertIs(args.func, qtv.cmd_up)

    def test_down_target_must_be_lab_owned(self) -> None:
        parser = qtv.build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["down", "--session", "turkishbathhouse_28501"])


class AttachTests(unittest.TestCase):
    def test_attach_detach_parser_defaults(self) -> None:
        parser = qtv.build_parser()
        a = parser.parse_args(["attach"])
        self.assertEqual(a.port, 28599)  # the moveprobe lab's port
        self.assertIs(a.func, qtv.cmd_attach)
        d = parser.parse_args(["detach", "--port", "28610"])
        self.assertEqual(d.port, 28610)
        self.assertIs(d.func, qtv.cmd_detach)

    def test_attach_script_only_touches_komodobots_sessions(self) -> None:
        # Safety guard: attach/detach must refuse any port not owned by a
        # komodobots lab screen session, so it can never enable QTV on (or
        # otherwise touch) the live qw_2850x / qtv / qwfwd servers.
        script = qtv.REMOTE_ATTACH_SCRIPT
        self.assertIn("komodobots_", script)
        self.assertIn("refusing", script)
        self.assertIn("qtv_streamport", script)


if __name__ == "__main__":
    unittest.main()
