"""control_bridge: security gates + lock protocol + dispatch (LD-F2, #96).

Locks the binding security rules: caller authorization for every mutating op
(loopback peer or per-deploy control token, fail-closed -- Codex P1, #129),
lab-port allowlist 28599-28609 only, flat
deny of production 28501/28502/28503 and qw_* screen names anywhere in command
paths, the cvar allowlist (k_fb_*, timelimit, fraglimit + explicit safe set),
the console allow/denylist (rcon*, exec, alias, sv_crypt*, quit, path-like,
chained), the harness-priority lock (fresh harness lock refuses every mutating
op; stale needs explicit force=true), the audit trail (every mutating attempt,
allowed AND refused, gets a timestamp+peer+op line), and the session lifecycle
(dashboard lock written on session_start, removed on session_stop, broadcast
control_event only on success). Live end-to-end behavior on servexeri rides
the declared lab slot per the LD-F1 precedent.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lab" / "server"))

import control_bridge as cb  # noqa: E402


class FakeExecutor:
    """Records calls; never touches screen/processes."""

    def __init__(self, available_ports=None):
        self.available = set(cb.ALLOWED_LAB_PORTS if available_ports is None else available_ports)
        self.calls = []

    def port_available(self, port):
        return port in self.available

    def start_session(self, port, map_name, run_id, cfg_text, setup_cmds):
        self.calls.append(("start_session", port, map_name, run_id, cfg_text, tuple(setup_cmds)))

    def stop_session(self, port):
        self.calls.append(("stop_session", port))

    def stuff(self, port, line):
        self.calls.append(("stuff", port, line))

    def add_bots(self, port, count):
        self.calls.append(("add_bots", port, count))

    def wait_for_bot_spawn(self, seconds):
        self.calls.append(("wait_for_bot_spawn", seconds))

    def send_botcmds(self, port, botcmds):
        self.calls.append(("send_botcmds", port, tuple(botcmds)))

    def send_client_cmds(self, port, commands):
        self.calls.append(("send_client_cmds", port, tuple(commands)))


NOW = 1_750_000_000.0


def make_bridge(tmp, available_ports=None, pid_alive=lambda pid: True, now=NOW, control_token=None):
    executor = FakeExecutor(available_ports)
    bridge = cb.ControlBridge(
        lab_home=Path(tmp),
        executor=executor,
        now_fn=lambda: now,
        pid_alive=pid_alive,
        own_pid=4242,
        control_token=control_token,
    )
    return bridge, executor


def local(bridge, request, peer="p"):
    """Call the bridge as a loopback (auth-trusted) peer.

    Caller authorization itself is locked by TestAuthorization; everything else
    exercises the gates BEHIND it the way the operator/ssh-tunnel path does.
    """
    return bridge.handle(request, peer, peer_host="127.0.0.1")


def fresh_ts(now=NOW):
    from datetime import datetime, timezone

    return datetime.fromtimestamp(now - 60, tz=timezone.utc).strftime(cb.LOCK_TS_FORMAT)


def old_ts(now=NOW):
    from datetime import datetime, timezone

    return datetime.fromtimestamp(now - 3 * 3600, tz=timezone.utc).strftime(cb.LOCK_TS_FORMAT)


def harness_lock(tmp, ts=None):
    cb.write_lock(Path(tmp) / "lab.lock", {"owner": "harness", "run_id": "r1", "pid": 999, "ts": ts or fresh_ts()})


def dashboard_lock(tmp, port=28599, ts=None):
    cb.write_lock(
        Path(tmp) / "lab.lock",
        {"owner": "dashboard", "run_id": "dash_x", "pid": 4242, "ts": ts or fresh_ts(), "port": port, "map": "dm3"},
    )


class TestValidators(unittest.TestCase):
    def test_port_allowlist(self):
        for port in (28599, 28605, 28609):
            self.assertEqual(cb.validate_lab_port(port), port)
        for port in (28501, 28502, 28503, 28598, 28610, 0, -1, 27500, "x", None, True):
            self.assertIsNone(cb.validate_lab_port(port), port)

    def test_flat_deny(self):
        for text in ("28501", "x 28502 y", "port=28503", "qw_1", "screen qw_2"):
            self.assertTrue(cb.hits_flat_deny(text), text)
        self.assertFalse(cb.hits_flat_deny("komodobots_lab_28599"))

    def test_map_names(self):
        self.assertEqual(cb.validate_map_name("frobodm2"), "frobodm2")
        for bad in ("../dm3", "dm3;quit", "dm 3", "", None, "dm3\n", "qw_dm3"):
            self.assertIsNone(cb.validate_map_name(bad), bad)

    def test_cvar_allowlist(self):
        self.assertEqual(cb.validate_cvar("k_fb_moveprobe_mode", 21), ("k_fb_moveprobe_mode", "21"))
        self.assertEqual(cb.validate_cvar("timelimit", 5), ("timelimit", "5"))
        self.assertEqual(cb.validate_cvar("fraglimit", 0), ("fraglimit", "0"))
        # slot -> the LD-F1 _s<N> per-slot form
        self.assertEqual(cb.validate_cvar("k_fb_moveprobe_mode", 21, slot=3), ("k_fb_moveprobe_mode_s3", "21"))
        for name in ("sv_rcon", "rcon_password", "sv_crypt_key", "hostname", "sv_demodir", "k_pow"):
            self.assertIsInstance(cb.validate_cvar(name, "1"), str, name)

    def test_cvar_value_gates(self):
        self.assertIsInstance(cb.validate_cvar("k_fb_x", "../etc"), str)
        self.assertIsInstance(cb.validate_cvar("k_fb_x", 'a"b'), str)
        self.assertIsInstance(cb.validate_cvar("k_fb_x", "a;b"), str)
        self.assertIsInstance(cb.validate_cvar("k_fb_x", "28501"), str)  # flat deny
        self.assertIsInstance(cb.validate_cvar("k_fb_x", "qw_name"), str)  # flat deny
        self.assertIsInstance(cb.validate_cvar("k_fb_x", "1", slot=99), str)
        self.assertIsInstance(cb.validate_cvar("k_fb_x", "1", slot=True), str)

    def test_format_set_cvar_quotes_space_values(self):
        self.assertEqual(cb.format_set_cvar_command("k_fb_moveprobe_mode_s3", "23"), "set k_fb_moveprobe_mode_s3 23")
        self.assertEqual(cb.format_set_cvar_command("k_fb_moveprobe_replay_file_s3", ""), 'set k_fb_moveprobe_replay_file_s3 ""')
        self.assertEqual(
            cb.format_set_cvar_command("k_fb_moveprobe_spawn_origin_s3", "-3516.125 3712 -453.125"),
            'set k_fb_moveprobe_spawn_origin_s3 "-3516.125 3712 -453.125"',
        )

    def test_console_allow_and_deny(self):
        for line in ("status", "map dm3", "set k_fb_skill 10", "timelimit 2", "sv_demostop"):
            self.assertEqual(cb.validate_console_line(line), line)
        for line in (
            "rcon_password x",
            "rcon say hi",
            "exec server.cfg",
            "alias a b",
            "sv_crypt_key x",
            "quit",
            "say /home/x",
            "status; quit",
            'say "x"',
            "set sv_rcon 1",  # set must pass the cvar allowlist
            "map ../dm3",
            "map dm3 extra",
            "status 28501",
            "kick 1",  # not on the allowlist
            "",
            None,
        ):
            self.assertIsNone(cb.validate_console_line(line), line)

    def test_game_command_allowlist(self):
        self.assertEqual(cb.validate_game_command("gamemode", "4on4"), [("client", "4on4")])
        self.assertEqual(cb.validate_game_command("gamemode", "FFA"), [("client", "ffa")])
        self.assertEqual(cb.validate_game_command("deathmatch", 3), [("client", "dmm3")])
        self.assertEqual(
            cb.validate_game_command("powerups", "off"),
            [
                ("console", "set k_pow 0"),
                ("console", "set k_pow_q 0"),
                ("console", "set k_pow_p 0"),
                ("console", "set k_pow_r 0"),
                ("console", "set k_pow_s 0"),
            ],
        )
        self.assertEqual(
            cb.validate_game_command("start"),
            [
                ("console", "set k_fb_moveprobe_mode 0"),
                ("console", 'set k_fb_moveprobe_spawn_origin ""'),
                ("botcmd", "weapon random"),
                ("client", "ready"),
            ],
        )
        self.assertEqual(
            cb.validate_game_command("stop"),
            [
                ("client", "break"),
                ("console", "set k_fb_moveprobe_mode 24"),
            ],
        )
        self.assertEqual(cb.validate_game_command("prewar"), [("client", "break"), ("console", "set k_prewar 0")])
        self.assertEqual(cb.validate_game_command("bot_respawn", "4"), [("botcmd", "removeall"), ("addbot", "1")])
        self.assertEqual(cb.validate_game_command("bot_weapon_lock"), [("botcmd", "weapon 1")])
        self.assertEqual(cb.validate_game_command("bot_weapon_unlock"), [("botcmd", "weapon random")])
        self.assertEqual(cb.validate_game_command("trick_pause"), [("botcmd", "removeall")])
        ztricks_steps = cb.validate_game_command("ztricks_distance_standstill")
        self.assertEqual(ztricks_steps[0], ("botcmd", "removeall"))
        self.assertIn(("console", "set k_fb_moveprobe_mode_s3 0"), ztricks_steps)
        self.assertIn(("console", "set k_fb_moveprobe_mode_s3 23"), ztricks_steps)
        self.assertIn(("console", "set k_fb_moveprobe_fixed_goal_s3 8"), ztricks_steps)
        self.assertIn(
            ("console", 'set k_fb_moveprobe_spawn_origin_s3 "-3516.125 3712 -453.125"'),
            ztricks_steps,
        )
        self.assertIn(("console", "set k_fb_moveprobe_replay_file_s3"), ztricks_steps)
        self.assertLess(
            ztricks_steps.index(("console", "set k_fb_moveprobe_fixed_goal_s3 8")),
            ztricks_steps.index(("console", "set k_fb_moveprobe_mode_s3 23")),
        )
        self.assertEqual(ztricks_steps[-1], ("addbot", "1"))
        for action, value in (
            ("gamemode", "3on3"),
            ("deathmatch", "5"),
            ("powerups", "toggle"),
            ("exec", "server.cfg"),
            ("bot_respawn", "x"),
            ("bot_respawn", "32"),
        ):
            self.assertIsInstance(cb.validate_game_command(action, value), str)


class TestLock(unittest.TestCase):
    def test_classify(self):
        alive = lambda pid: True  # noqa: E731
        dead = lambda pid: False  # noqa: E731
        fresh = {"owner": "harness", "run_id": "r", "pid": 1, "ts": fresh_ts()}
        self.assertEqual(cb.classify_lock(fresh, now=NOW, pid_alive=alive), "fresh")
        self.assertEqual(cb.classify_lock(fresh, now=NOW, pid_alive=dead), "stale")
        old = dict(fresh, ts=old_ts())
        self.assertEqual(cb.classify_lock(old, now=NOW, pid_alive=alive), "stale")
        self.assertEqual(cb.classify_lock({"_corrupt": True}, now=NOW, pid_alive=alive), "stale")
        self.assertEqual(cb.classify_lock({"owner": "x"}, now=NOW, pid_alive=alive), "stale")

    def test_read_lock_corrupt_and_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lab.lock"
            self.assertIsNone(cb.read_lock(path))
            path.write_text("{not json", encoding="utf-8")
            self.assertEqual(cb.read_lock(path), {"_corrupt": True})


class TestHarnessPriority(unittest.TestCase):
    def test_fresh_harness_lock_refuses_every_mutating_op(self):
        with tempfile.TemporaryDirectory() as tmp:
            harness_lock(tmp)
            bridge, executor = make_bridge(tmp)
            ops = [
                {"op": "session_start", "map": "dm3", "req_id": "1"},
                {"op": "session_start", "map": "dm3", "force": True, "req_id": "1f"},
                {"op": "session_stop", "req_id": "2"},
                {"op": "set_map", "map": "dm3", "req_id": "3"},
                {"op": "addbot", "req_id": "4"},
                {"op": "removebot", "req_id": "5"},
                {"op": "set_cvar", "name": "k_fb_skill", "value": 10, "req_id": "6"},
                {"op": "console", "line": "status", "req_id": "7"},
                {"op": "game_command", "action": "gamemode", "value": "4on4", "req_id": "7g"},
            ]
            for request in ops:
                response, broadcast = local(bridge,request, "peer")
                self.assertFalse(response["ok"], request)
                self.assertIn("experiment harness owns the lab", response["detail"])
                self.assertIsNone(broadcast)
            self.assertEqual(executor.calls, [])  # nothing executed
            # read-only lock_status still answers
            response, _ = local(bridge,{"op": "lock_status", "req_id": "8"}, "peer")
            self.assertTrue(response["ok"])
            self.assertEqual(response["state"], "fresh")
            self.assertEqual(response["lock"]["owner"], "harness")

    def test_stale_lock_needs_force(self):
        with tempfile.TemporaryDirectory() as tmp:
            harness_lock(tmp)
            bridge, executor = make_bridge(tmp, pid_alive=lambda pid: False)
            response, _ = local(bridge,{"op": "session_start", "map": "dm3", "req_id": "1"}, "p")
            self.assertFalse(response["ok"])
            self.assertIn("force=true", response["detail"])
            response, broadcast = local(bridge,
                {"op": "session_start", "map": "dm3", "force": True, "req_id": "2"}, "p"
            )
            self.assertTrue(response["ok"], response)
            self.assertEqual(broadcast["event"], "session_start")
            lock = cb.read_lock(Path(tmp) / "lab.lock")
            self.assertEqual(lock["owner"], "dashboard")

    def test_stale_force_does_not_apply_to_session_scoped_ops(self):
        with tempfile.TemporaryDirectory() as tmp:
            harness_lock(tmp, ts=old_ts())
            bridge, executor = make_bridge(tmp)
            response, _ = local(bridge,
                {"op": "set_cvar", "name": "k_fb_skill", "value": 1, "force": True, "req_id": "1"}, "p"
            )
            self.assertFalse(response["ok"])
            self.assertEqual(executor.calls, [])


class TestSessionLifecycle(unittest.TestCase):
    def test_golden_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge, executor = make_bridge(tmp)
            response, broadcast = local(bridge,{"op": "session_start", "map": "dm3", "req_id": "1"}, "p")
            self.assertTrue(response["ok"], response)
            self.assertEqual(response["port"], 28599)  # first free allowlisted port
            self.assertEqual(broadcast["event"], "session_start")
            call = executor.calls[0]
            self.assertEqual(call[0], "start_session")
            cfg = call[4]
            self.assertIn("set qtv_streamport 28599", cfg)
            self.assertIn("set k_defmap dm3", cfg)
            self.assertIn("set demo_tmp_record 1", cfg)
            self.assertIn("map dm3", call[5])
            self.assertIn("set k_fb_autoremove_at 0", call[5])
            self.assertEqual(
                executor.calls[1:9],
                [
                    ("stuff", 28599, "set k_fb_moveprobe_mode 24"),
                    ("stuff", 28599, "set k_fb_moveprobe_fixed_goal 0"),
                    ("stuff", 28599, 'set k_fb_moveprobe_spawn_origin "385.500 614.250 56.000"'),
                    ("add_bots", 28599, 1),
                    ("wait_for_bot_spawn", cb.PRACTICE_BOT_SPAWN_SETTLE_S),
                    ("stuff", 28599, 'set k_fb_moveprobe_spawn_origin "-895.400 -129.100 -15.900"'),
                    ("add_bots", 28599, 1),
                    ("wait_for_bot_spawn", cb.PRACTICE_BOT_SPAWN_SETTLE_S),
                ],
            )
            self.assertEqual(executor.calls[9], ("stuff", 28599, 'set k_fb_moveprobe_spawn_origin ""'))
            lock = cb.read_lock(Path(tmp) / "lab.lock")
            self.assertEqual(lock["owner"], "dashboard")
            self.assertEqual(lock["port"], 28599)
            self.assertEqual(lock["pid"], 4242)
            self.assertIn("ts", lock)
            self.assertIn("run_id", lock)

            # second start refuses while the session runs
            response, _ = local(bridge,{"op": "session_start", "map": "dm3", "req_id": "2"}, "p")
            self.assertFalse(response["ok"])
            self.assertIn("already running", response["detail"])

    def test_session_start_retries_next_port_after_start_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge, executor = make_bridge(tmp)
            real_start = executor.start_session

            def flaky_start(port, *args):
                if port == 28599:
                    raise RuntimeError("tcp bind failed")
                return real_start(port, *args)

            executor.start_session = flaky_start
            response, broadcast = local(bridge,{"op": "session_start", "map": "trick", "req_id": "1"}, "p")
            self.assertTrue(response["ok"], response)
            self.assertEqual(response["port"], 28600)
            self.assertEqual(broadcast["port"], 28600)
            self.assertIn(("stop_session", 28599), executor.calls)
            lock = cb.read_lock(Path(tmp) / "lab.lock")
            self.assertEqual(lock["port"], 28600)
            self.assertEqual(lock["map"], "trick")

            # stop releases the lock on the successfully retried port
            response, broadcast = local(bridge,{"op": "session_stop", "req_id": "3"}, "p")
            self.assertTrue(response["ok"], response)
            self.assertEqual(broadcast, {"type": "control_event", "event": "session_stop", "port": 28600})
            self.assertIn(("stop_session", 28600), executor.calls)
            self.assertIsNone(cb.read_lock(Path(tmp) / "lab.lock"))

    def test_ports_exhausted_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge, executor = make_bridge(tmp, available_ports=())
            response, broadcast = local(bridge,{"op": "session_start", "map": "dm3", "req_id": "1"}, "p")
            self.assertFalse(response["ok"])
            self.assertIn("no free lab port", response["detail"])
            self.assertIsNone(broadcast)
            self.assertEqual(executor.calls, [])

    def test_force_start_after_stale_dashboard_lock_sweeps_old_session(self):
        # Codex P2 (#129): the stale dashboard lock's screen can still be
        # alive (staleness tracks the bridge pid, not the MVDSV screen).
        # A forced session_start must stop that session before allocating,
        # or the old screen is orphaned with no lock pointing at it.
        with tempfile.TemporaryDirectory() as tmp:
            dashboard_lock(tmp, port=28600, ts=old_ts())
            bridge, executor = make_bridge(tmp, available_ports={28601})
            # Model the live orphan screen: 28600 reads occupied until swept.
            real_stop = executor.stop_session

            def stop_session(port):
                real_stop(port)
                executor.available.add(port)

            executor.stop_session = stop_session
            response, broadcast = local(bridge,
                {"op": "session_start", "map": "dm3", "force": True, "req_id": "1"}, "p"
            )
            self.assertTrue(response["ok"], response)
            # swept FIRST, then started -- and the swept port is reusable
            self.assertEqual(executor.calls[0], ("stop_session", 28600))
            self.assertEqual(executor.calls[1][0], "start_session")
            self.assertEqual(response["port"], 28600)
            self.assertEqual(broadcast["event"], "session_start")
            lock = cb.read_lock(Path(tmp) / "lab.lock")
            self.assertEqual(lock["owner"], "dashboard")
            self.assertEqual(lock["port"], 28600)
            self.assertEqual(lock["pid"], 4242)

    def test_force_start_after_stale_lock_without_port_does_not_sweep(self):
        with tempfile.TemporaryDirectory() as tmp:
            harness_lock(tmp, ts=old_ts())  # harness locks carry no port
            bridge, executor = make_bridge(tmp)
            response, _ = local(bridge,
                {"op": "session_start", "map": "dm3", "force": True, "req_id": "1"}, "p"
            )
            self.assertTrue(response["ok"], response)
            stops = [c for c in executor.calls if c[0] == "stop_session"]
            self.assertEqual(stops, [])

    def test_session_start_invalid_map(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge, executor = make_bridge(tmp)
            for bad in ("../dm3", "dm3;quit", "", None, "qw_x"):
                response, _ = local(bridge,{"op": "session_start", "map": bad, "req_id": "1"}, "p")
                self.assertFalse(response["ok"], bad)
            self.assertEqual(executor.calls, [])

    def test_session_stop_refuses_production_port_even_with_force(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge, executor = make_bridge(tmp)
            for port in (28501, 28502, 28503, 27500):
                response, _ = local(bridge,
                    {"op": "session_stop", "port": port, "force": True, "req_id": "1"}, "p"
                )
                self.assertFalse(response["ok"], port)
            self.assertEqual(executor.calls, [])

    def test_session_stop_without_lock_needs_force(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge, executor = make_bridge(tmp)
            response, _ = local(bridge,{"op": "session_stop", "port": 28600, "req_id": "1"}, "p")
            self.assertFalse(response["ok"])
            response, _ = local(bridge,
                {"op": "session_stop", "port": 28600, "force": True, "req_id": "2"}, "p"
            )
            self.assertTrue(response["ok"])
            self.assertEqual(executor.calls, [("stop_session", 28600)])


class TestSessionScopedOps(unittest.TestCase):
    def test_ops_refused_without_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge, executor = make_bridge(tmp)
            for request in (
                {"op": "set_map", "map": "dm3", "req_id": "1"},
                {"op": "addbot", "req_id": "2"},
                {"op": "set_cvar", "name": "k_fb_skill", "value": 1, "req_id": "3"},
                {"op": "console", "line": "status", "req_id": "4"},
                {"op": "game_command", "action": "start", "req_id": "5"},
            ):
                response, _ = local(bridge,request, "p")
                self.assertFalse(response["ok"], request)
                self.assertIn("no dashboard session", response["detail"])
            self.assertEqual(executor.calls, [])

    def test_set_cvar_and_slot_form(self):
        with tempfile.TemporaryDirectory() as tmp:
            dashboard_lock(tmp, port=28600)
            bridge, executor = make_bridge(tmp)
            response, broadcast = local(bridge,
                {"op": "set_cvar", "name": "k_fb_moveprobe_mode", "value": 21, "req_id": "1"}, "p"
            )
            self.assertTrue(response["ok"], response)
            self.assertEqual(executor.calls[-1], ("stuff", 28600, "set k_fb_moveprobe_mode 21"))
            self.assertEqual(broadcast["event"], "set_cvar")

            response, _ = local(bridge,
                {"op": "set_cvar", "name": "k_fb_moveprobe_mode", "value": 21, "slot": 2, "req_id": "2"}, "p"
            )
            self.assertTrue(response["ok"])
            self.assertEqual(executor.calls[-1], ("stuff", 28600, "set k_fb_moveprobe_mode_s2 21"))

            response, _ = local(bridge, {
                "op": "set_cvar",
                "name": "k_fb_moveprobe_spawn_origin",
                "value": "-3516.125 3712 -453.125",
                "slot": 2,
                "req_id": "3",
            }, "p")
            self.assertTrue(response["ok"], response)
            self.assertEqual(
                executor.calls[-1],
                ("stuff", 28600, 'set k_fb_moveprobe_spawn_origin_s2 "-3516.125 3712 -453.125"'),
            )

    def test_set_cvar_security_refusals(self):
        with tempfile.TemporaryDirectory() as tmp:
            dashboard_lock(tmp)
            bridge, executor = make_bridge(tmp)
            for request in (
                {"op": "set_cvar", "name": "rcon_password", "value": "x"},
                {"op": "set_cvar", "name": "sv_crypt_key", "value": "x"},
                {"op": "set_cvar", "name": "k_fb_x", "value": "28501"},
                {"op": "set_cvar", "name": "k_fb_x", "value": "qw_a"},
                {"op": "set_cvar", "name": "k_fb_x", "value": "../x"},
            ):
                response, broadcast = local(bridge,{**request, "req_id": "r"}, "p")
                self.assertFalse(response["ok"], request)
                self.assertIsNone(broadcast)
            self.assertEqual(executor.calls, [])

    def test_console_security_refusals(self):
        with tempfile.TemporaryDirectory() as tmp:
            dashboard_lock(tmp)
            bridge, executor = make_bridge(tmp)
            for line in ("rcon_password x", "exec a.cfg", "alias a b", "quit", "status;quit", "say /x"):
                response, _ = local(bridge,{"op": "console", "line": line, "req_id": "r"}, "p")
                self.assertFalse(response["ok"], line)
            self.assertEqual(executor.calls, [])
            response, _ = local(bridge,{"op": "console", "line": "status", "req_id": "r"}, "p")
            self.assertTrue(response["ok"])
            self.assertEqual(executor.calls, [("stuff", 28599, "status")])

    def test_addbot_and_removebot(self):
        with tempfile.TemporaryDirectory() as tmp:
            dashboard_lock(tmp)
            bridge, executor = make_bridge(tmp)
            response, _ = local(bridge,{"op": "addbot", "count": 2, "req_id": "1"}, "p")
            self.assertTrue(response["ok"])
            self.assertEqual(executor.calls[-1], ("add_bots", 28599, 2))
            for bad in (0, 9, "2", True):
                response, _ = local(bridge,{"op": "addbot", "count": bad, "req_id": "x"}, "p")
                self.assertFalse(response["ok"], bad)
            response, _ = local(bridge,{"op": "removebot", "req_id": "2"}, "p")
            self.assertEqual(executor.calls[-1], ("send_botcmds", 28599, ("removebot",)))
            response, _ = local(bridge,{"op": "removebot", "slot": "all", "req_id": "3"}, "p")
            self.assertEqual(executor.calls[-1], ("send_botcmds", 28599, ("removeall",)))
            response, _ = local(bridge,{"op": "removebot", "slot": 4, "req_id": "4"}, "p")
            self.assertEqual(executor.calls[-1], ("send_botcmds", 28599, ("removebot 4",)))
            response, _ = local(bridge,{"op": "removebot", "slot": "x", "req_id": "5"}, "p")
            self.assertFalse(response["ok"])

    def test_game_command_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            dashboard_lock(tmp, port=28600)
            bridge, executor = make_bridge(tmp)

            response, broadcast = local(bridge,
                {"op": "game_command", "action": "gamemode", "value": "2on2", "req_id": "1"}, "p"
            )
            self.assertTrue(response["ok"], response)
            self.assertEqual(executor.calls[-1], ("send_client_cmds", 28600, ("2on2",)))
            self.assertEqual(broadcast["event"], "game_command")
            self.assertEqual(broadcast["action"], "gamemode")

            response, _ = local(bridge,
                {"op": "game_command", "action": "deathmatch", "value": "4", "req_id": "2"}, "p"
            )
            self.assertTrue(response["ok"], response)
            self.assertEqual(executor.calls[-1], ("send_client_cmds", 28600, ("dmm4",)))

            response, _ = local(bridge,
                {"op": "game_command", "action": "powerups", "value": "on", "req_id": "3"}, "p"
            )
            self.assertTrue(response["ok"], response)
            self.assertEqual(
                executor.calls[-5:],
                [
                    ("stuff", 28600, "set k_pow 1"),
                    ("stuff", 28600, "set k_pow_q 1"),
                    ("stuff", 28600, "set k_pow_p 1"),
                    ("stuff", 28600, "set k_pow_r 1"),
                    ("stuff", 28600, "set k_pow_s 1"),
                ],
            )

            response, _ = local(bridge,
                {"op": "game_command", "action": "gamemode", "value": "wipeout", "req_id": "4"}, "p"
            )
            self.assertFalse(response["ok"])

            response, broadcast = local(bridge,
                {"op": "game_command", "action": "start", "req_id": "4b"}, "p"
            )
            self.assertTrue(response["ok"], response)
            self.assertEqual(
                executor.calls[-4:],
                [
                    ("stuff", 28600, "set k_fb_moveprobe_mode 0"),
                    ("stuff", 28600, 'set k_fb_moveprobe_spawn_origin ""'),
                    ("send_botcmds", 28600, ("weapon random",)),
                    ("send_client_cmds", 28600, ("ready",)),
                ],
            )
            self.assertEqual(broadcast["action"], "start")

            response, broadcast = local(bridge,
                {"op": "game_command", "action": "stop", "req_id": "4c"}, "p"
            )
            self.assertTrue(response["ok"], response)
            self.assertEqual(
                executor.calls[-2:],
                [
                    ("send_client_cmds", 28600, ("break",)),
                    ("stuff", 28600, "set k_fb_moveprobe_mode 24"),
                ],
            )
            self.assertEqual(broadcast["action"], "stop")

            response, broadcast = local(bridge,
                {"op": "game_command", "action": "prewar", "req_id": "5"}, "p"
            )
            self.assertTrue(response["ok"], response)
            self.assertEqual(
                executor.calls[-2:],
                [
                    ("send_client_cmds", 28600, ("break",)),
                    ("stuff", 28600, "set k_prewar 0"),
                ],
            )
            self.assertEqual(broadcast["action"], "prewar")

            response, broadcast = local(bridge,
                {"op": "game_command", "action": "bot_respawn", "value": "4", "req_id": "6"}, "p"
            )
            self.assertTrue(response["ok"], response)
            self.assertEqual(executor.calls[-2:], [("send_botcmds", 28600, ("removeall",)), ("add_bots", 28600, 1)])
            self.assertEqual(broadcast["action"], "bot_respawn")
            self.assertEqual(broadcast["value"], "4")

            response, broadcast = local(bridge,
                {"op": "game_command", "action": "bot_weapon_lock", "req_id": "7"}, "p"
            )
            self.assertTrue(response["ok"], response)
            self.assertEqual(executor.calls[-1], ("send_botcmds", 28600, ("weapon 1",)))
            self.assertEqual(broadcast["action"], "bot_weapon_lock")

            response, broadcast = local(bridge,
                {"op": "game_command", "action": "trick_pause", "req_id": "8"}, "p"
            )
            self.assertTrue(response["ok"], response)
            self.assertEqual(executor.calls[-1], ("send_botcmds", 28600, ("removeall",)))
            self.assertEqual(broadcast["action"], "trick_pause")

    def test_ztricks_distance_standstill_dispatch_requires_ztricks(self):
        with tempfile.TemporaryDirectory() as tmp:
            dashboard_lock(tmp, port=28600)  # default map is dm3
            bridge, executor = make_bridge(tmp)

            response, _ = local(bridge,
                {"op": "game_command", "action": "ztricks_distance_standstill", "req_id": "1"}, "p"
            )
            self.assertFalse(response["ok"])
            self.assertIn("requires a ztricks session", response["detail"])
            self.assertEqual(executor.calls, [])

    def test_ztricks_distance_standstill_dispatch_sets_preset_and_adds_bot(self):
        with tempfile.TemporaryDirectory() as tmp:
            dashboard_lock(tmp, port=28600)
            lock = cb.read_lock(Path(tmp) / "lab.lock")
            lock["map"] = "ztricks"
            cb.write_lock(Path(tmp) / "lab.lock", lock)
            bridge, executor = make_bridge(tmp)

            response, broadcast = local(bridge,
                {"op": "game_command", "action": "ztricks_distance_standstill", "req_id": "1"}, "p"
            )
            self.assertTrue(response["ok"], response)
            self.assertEqual(broadcast["action"], "ztricks_distance_standstill")
            self.assertEqual(executor.calls[0], ("send_botcmds", 28600, ("removeall",)))
            self.assertIn(("stuff", 28600, "set k_fb_moveprobe_mode_s3 0"), executor.calls)
            self.assertIn(("stuff", 28600, "set k_fb_moveprobe_mode_s3 23"), executor.calls)
            self.assertIn(("stuff", 28600, "set k_fb_moveprobe_fixed_goal_s3 8"), executor.calls)
            self.assertIn(
                ("stuff", 28600, 'set k_fb_moveprobe_spawn_origin_s3 "-3516.125 3712 -453.125"'),
                executor.calls,
            )
            self.assertIn(("stuff", 28600, "set k_fb_moveprobe_replay_file_s3"), executor.calls)
            fixed_goal_idx = executor.calls.index(("stuff", 28600, "set k_fb_moveprobe_fixed_goal_s3 8"))
            mode_idx = executor.calls.index(("stuff", 28600, "set k_fb_moveprobe_mode_s3 23"))
            self.assertLess(fixed_goal_idx, mode_idx)
            self.assertEqual(executor.calls[-1], ("add_bots", 28600, 1))


class TestProtocolEdges(unittest.TestCase):
    def test_unknown_op_and_bad_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge, _ = make_bridge(tmp)
            for request in ({"op": "reboot", "req_id": "1"}, {"req_id": "1"}, "x", None, 7, []):
                response, broadcast = local(bridge,request, "p")
                self.assertFalse(response["ok"], request)
                self.assertIsNone(broadcast)

    def test_verdict_implemented(self):
        # LD-F5 (#106): verdict (certification) is now a real op; a valid request succeeds.
        # User decision 2026-06-10: no pass/close/fail -- certification only.
        with tempfile.TemporaryDirectory() as tmp:
            bridge, _ = make_bridge(tmp)
            response, broadcast = local(bridge, {
                "op": "verdict", "map": "dm3", "route": "sng_to_rl", "req_id": "1",
            })
            self.assertTrue(response["ok"], response)
            self.assertIsNotNone(broadcast)

    def test_executor_exception_answers_instead_of_raising(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge, executor = make_bridge(tmp)
            executor.start_session = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
            response, broadcast = local(bridge,{"op": "session_start", "map": "dm3", "req_id": "1"}, "p")
            self.assertFalse(response["ok"])
            self.assertIn("boom", response["detail"])
            self.assertIsNone(broadcast)
            # no lock left behind by the failed start
            self.assertIsNone(cb.read_lock(Path(tmp) / "lab.lock"))

    def test_lock_status_free(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge, _ = make_bridge(tmp)
            response, broadcast = local(bridge,{"op": "lock_status", "req_id": "1"}, "p")
            self.assertTrue(response["ok"])
            self.assertEqual(response["state"], "free")
            self.assertIsNone(response["lock"])
            self.assertIsNone(broadcast)


class TestAuthorization(unittest.TestCase):
    """Codex P1 (#129): mutating frames need a trusted caller -- loopback or token."""

    MUTATING_REQUESTS = (
        {"op": "session_start", "map": "dm3"},
        {"op": "session_stop", "port": 28600, "force": True},
        {"op": "set_map", "map": "dm3"},
        {"op": "addbot", "count": 1},
        {"op": "removebot"},
        {"op": "set_cvar", "name": "k_fb_skill", "value": 10},
        {"op": "console", "line": "status"},
        {"op": "game_command", "action": "start"},
        # LD-F5 (#106): verdict (certification) is a real mutating op.
        {"op": "verdict", "map": "dm3", "route": "sng_to_rl"},
    )

    def test_request_set_covers_every_mutating_op(self):
        self.assertEqual({r["op"] for r in self.MUTATING_REQUESTS}, set(cb.MUTATING_OPS))

    def test_is_loopback_host(self):
        for host in ("127.0.0.1", "127.0.0.2", "::1", "::ffff:127.0.0.1"):
            self.assertTrue(cb.is_loopback_host(host), host)
        for host in ("192.168.86.20", "100.102.34.74", "8.8.8.8",
                     "::ffff:192.168.86.20", "localhost", "evil", "", None, 7):
            self.assertFalse(cb.is_loopback_host(host), host)

    def test_remote_peer_without_token_cannot_mutate(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge, executor = make_bridge(tmp)  # no token configured
            for request in self.MUTATING_REQUESTS:
                response, broadcast = bridge.handle(
                    {**request, "req_id": "r"}, "lan-peer", peer_host="192.168.86.50"
                )
                self.assertFalse(response["ok"], request)
                self.assertIn("unauthorized", response["detail"])
                self.assertIsNone(broadcast)
            self.assertEqual(executor.calls, [])  # nothing executed
            self.assertIsNone(cb.read_lock(Path(tmp) / "lab.lock"))  # no lock written
            # every refused attempt is audited
            lines = (Path(tmp) / "control-audit.log").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), len(self.MUTATING_REQUESTS))

    def test_missing_peer_host_is_treated_as_remote(self):
        # fail closed: a caller whose address is unknown is NOT trusted
        with tempfile.TemporaryDirectory() as tmp:
            bridge, executor = make_bridge(tmp)
            response, _ = bridge.handle({"op": "session_start", "map": "dm3", "req_id": "1"}, "p")
            self.assertFalse(response["ok"])
            self.assertIn("unauthorized", response["detail"])
            self.assertEqual(executor.calls, [])

    def test_remote_peer_with_wrong_or_missing_token_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge, executor = make_bridge(tmp, control_token="s3cret-token")
            for bad in (None, "", "wrong", 7, True, "s3cret-token ", "S3CRET-TOKEN"):
                request = {"op": "session_start", "map": "dm3", "req_id": "1"}
                if bad is not None:
                    request["token"] = bad
                response, _ = bridge.handle(request, "lan-peer", peer_host="192.168.86.50")
                self.assertFalse(response["ok"], bad)
                self.assertIn("unauthorized", response["detail"])
            self.assertEqual(executor.calls, [])

    def test_remote_peer_with_valid_token_can_mutate(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge, executor = make_bridge(tmp, control_token="s3cret-token")
            response, broadcast = bridge.handle(
                {"op": "session_start", "map": "dm3", "token": "s3cret-token", "req_id": "1"},
                "lan-peer",
                peer_host="192.168.86.50",
            )
            self.assertTrue(response["ok"], response)
            self.assertEqual(broadcast["event"], "session_start")
            self.assertEqual(cb.read_lock(Path(tmp) / "lab.lock")["owner"], "dashboard")

    def test_loopback_does_not_need_token(self):
        # the ssh -L / on-host operator path keeps working with a token configured
        with tempfile.TemporaryDirectory() as tmp:
            bridge, executor = make_bridge(tmp, control_token="s3cret-token")
            response, _ = bridge.handle(
                {"op": "session_start", "map": "dm3", "req_id": "1"}, "p", peer_host="127.0.0.1"
            )
            self.assertTrue(response["ok"], response)

    def test_token_is_redacted_in_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge, _ = make_bridge(tmp, control_token="s3cret-token")
            bridge.handle(
                {"op": "session_start", "map": "dm3", "token": "s3cret-token", "req_id": "1"},
                "lan-peer",
                peer_host="192.168.86.50",
            )
            text = (Path(tmp) / "control-audit.log").read_text(encoding="utf-8")
            self.assertNotIn("s3cret-token", text)
            entry = json.loads(text.splitlines()[0])
            self.assertEqual(entry["request"]["token"], "<redacted>")

    def test_lock_status_needs_no_auth(self):
        # read-only: stays answerable so the dashboard can show lab state
        with tempfile.TemporaryDirectory() as tmp:
            bridge, _ = make_bridge(tmp)
            response, _ = bridge.handle({"op": "lock_status", "req_id": "1"}, "lan-peer",
                                        peer_host="192.168.86.50")
            self.assertTrue(response["ok"])
            self.assertEqual(response["state"], "free")


class TestAudit(unittest.TestCase):
    def test_every_mutating_attempt_is_audited(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge, _ = make_bridge(tmp)
            local(bridge,{"op": "session_start", "map": "dm3", "req_id": "1"}, "1.2.3.4")
            local(bridge,{"op": "set_cvar", "name": "rcon_password", "value": "x", "req_id": "2"}, "1.2.3.4")
            local(bridge,{"op": "lock_status", "req_id": "3"}, "1.2.3.4")  # read-only: not audited
            lines = (Path(tmp) / "control-audit.log").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2)
            entries = [json.loads(line) for line in lines]
            self.assertEqual(entries[0]["op"], "session_start")
            self.assertTrue(entries[0]["ok"])
            self.assertEqual(entries[0]["peer"], "1.2.3.4")
            self.assertIn("ts", entries[0])
            self.assertEqual(entries[1]["op"], "set_cvar")
            self.assertFalse(entries[1]["ok"])


class TestConfigBuilders(unittest.TestCase):
    def test_config_refuses_bad_input(self):
        with self.assertRaises(ValueError):
            cb.build_session_config("../dm3", 28599)
        with self.assertRaises(ValueError):
            cb.build_session_config("dm3", 28501)
        with self.assertRaises(ValueError):
            cb.build_session_setup_cmds("dm3;quit")

    def test_session_name_gate(self):
        self.assertEqual(cb.lab_session_name(28599), "komodobots_lab_28599")
        for port in (28501, 27500):
            with self.assertRaises(ValueError):
                cb.lab_session_name(port)


# ---------------------------------------------------------------------------
# LD-F5 (#106): verdict op tests
# User decision 2026-06-10: certification only (no pass/close/fail).
# ---------------------------------------------------------------------------


class TestVerdictValidation(unittest.TestCase):
    """Unit tests for validate_verdict_args (pure validator).

    User decision 2026-06-10: verdict = sparse certification (human-level
    declared by user).  No pass/close/fail three-state.  Args: map, route, note?.
    """

    def test_valid_certification(self):
        # No note.
        self.assertIsNone(cb.validate_verdict_args("dm3", "sng_to_rl", None))

    def test_valid_certification_with_note(self):
        self.assertIsNone(cb.validate_verdict_args("dm3", "sng_to_rl", "looks human"))

    def test_invalid_map(self):
        for bad_map in ("../dm3", "dm3;quit", "", None):
            err = cb.validate_verdict_args(bad_map, "sng_to_rl", None)
            self.assertIsNotNone(err, bad_map)
            self.assertIn("map", err)

    def test_invalid_route(self):
        for bad_route in ("../route", "route;cmd", "", None):
            err = cb.validate_verdict_args("dm3", bad_route, None)
            self.assertIsNotNone(err, bad_route)
            self.assertIn("route", err)

    def test_note_too_long(self):
        err = cb.validate_verdict_args("dm3", "sng_to_rl", "x" * 1001)
        self.assertIsNotNone(err)
        self.assertIn("note too long", err)

    def test_note_control_chars(self):
        err = cb.validate_verdict_args("dm3", "sng_to_rl", "bad\x00note")
        self.assertIsNotNone(err)
        self.assertIn("control character", err)

    def test_note_tab_allowed(self):
        # tabs are not control-char-blocked (they are printable in notes)
        self.assertIsNone(cb.validate_verdict_args("dm3", "sng_to_rl", "ok\there"))

    def test_note_none_is_valid(self):
        self.assertIsNone(cb.validate_verdict_args("dm3", "sng_to_rl", None))


class TestVerdictOp(unittest.TestCase):
    """Integration tests for the bridge verdict (certification) op."""

    def _certify(self, bridge, route="sng_to_rl", note=None, req_id="v1"):
        req = {"op": "verdict", "map": "dm3", "route": route, "req_id": req_id}
        if note is not None:
            req["note"] = note
        return local(bridge, req)

    def _make_bridge_and_submit(self, tmp, request=None):
        bridge, executor = make_bridge(tmp)
        if request is None:
            request = {
                "op": "verdict",
                "map": "dm3",
                "route": "sng_to_rl",
                "note": "looks human to me",
                "req_id": "v1",
            }
        response, broadcast = local(bridge, request)
        return response, broadcast, Path(tmp) / "records" / "verdicts.json"

    def test_happy_path_writes_verdicts_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            response, broadcast, vpath = self._make_bridge_and_submit(tmp)
            self.assertTrue(response["ok"], response)
            self.assertEqual(response["route"], "sng_to_rl")
            self.assertIn("date", response)
            self.assertTrue(vpath.exists())
            verdicts = json.loads(vpath.read_text(encoding="utf-8"))
            self.assertEqual(verdicts["schema"], "komodobots.verdicts.v2")
            certs = verdicts["certifications"]["sng_to_rl"]
            self.assertIsInstance(certs, list)
            self.assertEqual(len(certs), 1)
            self.assertIn("date", certs[0])
            self.assertEqual(certs[0].get("note"), "looks human to me")

    def test_broadcast_on_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            response, broadcast, _ = self._make_bridge_and_submit(tmp)
            self.assertTrue(response["ok"])
            self.assertIsNotNone(broadcast)
            self.assertEqual(broadcast["type"], "control_event")
            self.assertEqual(broadcast["event"], "verdict")
            self.assertEqual(broadcast["route"], "sng_to_rl")
            self.assertIn("date", broadcast)

    def test_certifications_appended(self):
        """Each certification is appended (sparse list, not latest-wins)."""
        with tempfile.TemporaryDirectory() as tmp:
            bridge, _ = make_bridge(tmp)
            vpath = Path(tmp) / "records" / "verdicts.json"
            self._certify(bridge, req_id="1")
            self._certify(bridge, note="second cert", req_id="2")
            verdicts = json.loads(vpath.read_text(encoding="utf-8"))
            certs = verdicts["certifications"]["sng_to_rl"]
            self.assertEqual(len(certs), 2)

    def test_two_routes_independent(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge, _ = make_bridge(tmp)
            vpath = Path(tmp) / "records" / "verdicts.json"
            self._certify(bridge, route="sng_to_rl", req_id="1")
            self._certify(bridge, route="hilljump", req_id="2")
            verdicts = json.loads(vpath.read_text(encoding="utf-8"))
            self.assertEqual(len(verdicts["certifications"]["sng_to_rl"]), 1)
            self.assertEqual(len(verdicts["certifications"]["hilljump"]), 1)

    def test_verdict_lock_exempt_during_harness_lock(self):
        """verdict must succeed even when the harness holds a fresh lock."""
        with tempfile.TemporaryDirectory() as tmp:
            harness_lock(tmp)
            bridge, _ = make_bridge(tmp)
            response, broadcast = self._certify(bridge)
            self.assertTrue(response["ok"], response)

    def test_verdict_invalid_fields_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge, _ = make_bridge(tmp)
            # bad route name
            response, _ = local(bridge, {"op": "verdict", "map": "dm3", "route": "../bad", "req_id": "2"})
            self.assertFalse(response["ok"])
            # bad map name
            response, _ = local(bridge, {"op": "verdict", "map": "../dm3", "route": "sng_to_rl", "req_id": "3"})
            self.assertFalse(response["ok"])
            # note too long
            response, _ = local(bridge, {"op": "verdict", "map": "dm3", "route": "sng_to_rl", "note": "x" * 1001, "req_id": "4"})
            self.assertFalse(response["ok"])

    def test_verdict_audited(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge, _ = make_bridge(tmp)
            self._certify(bridge)
            lines = (Path(tmp) / "control-audit.log").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            entry = json.loads(lines[0])
            self.assertEqual(entry["op"], "verdict")
            self.assertTrue(entry["ok"])

    def test_verdict_requires_auth(self):
        """verdict is still a mutating op: unauthorized remote peers are refused."""
        with tempfile.TemporaryDirectory() as tmp:
            bridge, _ = make_bridge(tmp)
            # no token configured, remote peer (not loopback) -- refused
            response, _ = bridge.handle(
                {"op": "verdict", "map": "dm3", "route": "sng_to_rl", "req_id": "1"},
                "remote-peer",
                peer_host="192.168.86.50",
            )
            self.assertFalse(response["ok"])
            self.assertIn("unauthorized", response["detail"])

    def test_note_optional(self):
        with tempfile.TemporaryDirectory() as tmp:
            response, _, vpath = self._make_bridge_and_submit(
                tmp,
                {"op": "verdict", "map": "dm3", "route": "sng_to_rl", "req_id": "1"},
            )
            self.assertTrue(response["ok"])
            verdicts = json.loads(vpath.read_text(encoding="utf-8"))
            cert = verdicts["certifications"]["sng_to_rl"][0]
            self.assertIn("date", cert)
            self.assertNotIn("note", cert)  # no note key when absent


if __name__ == "__main__":
    unittest.main()
