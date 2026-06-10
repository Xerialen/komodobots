"""control_bridge: security gates + lock protocol + dispatch (LD-F2, #96).

Locks the binding security rules: lab-port allowlist 28599-28609 only, flat
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

    def send_botcmds(self, port, botcmds):
        self.calls.append(("send_botcmds", port, tuple(botcmds)))


NOW = 1_750_000_000.0


def make_bridge(tmp, available_ports=None, pid_alive=lambda pid: True, now=NOW):
    executor = FakeExecutor(available_ports)
    bridge = cb.ControlBridge(
        lab_home=Path(tmp),
        executor=executor,
        now_fn=lambda: now,
        pid_alive=pid_alive,
        own_pid=4242,
    )
    return bridge, executor


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
            ]
            for request in ops:
                response, broadcast = bridge.handle(request, "peer")
                self.assertFalse(response["ok"], request)
                self.assertIn("experiment harness owns the lab", response["detail"])
                self.assertIsNone(broadcast)
            self.assertEqual(executor.calls, [])  # nothing executed
            # read-only lock_status still answers
            response, _ = bridge.handle({"op": "lock_status", "req_id": "8"}, "peer")
            self.assertTrue(response["ok"])
            self.assertEqual(response["state"], "fresh")
            self.assertEqual(response["lock"]["owner"], "harness")

    def test_stale_lock_needs_force(self):
        with tempfile.TemporaryDirectory() as tmp:
            harness_lock(tmp)
            bridge, executor = make_bridge(tmp, pid_alive=lambda pid: False)
            response, _ = bridge.handle({"op": "session_start", "map": "dm3", "req_id": "1"}, "p")
            self.assertFalse(response["ok"])
            self.assertIn("force=true", response["detail"])
            response, broadcast = bridge.handle(
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
            response, _ = bridge.handle(
                {"op": "set_cvar", "name": "k_fb_skill", "value": 1, "force": True, "req_id": "1"}, "p"
            )
            self.assertFalse(response["ok"])
            self.assertEqual(executor.calls, [])


class TestSessionLifecycle(unittest.TestCase):
    def test_golden_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge, executor = make_bridge(tmp)
            response, broadcast = bridge.handle({"op": "session_start", "map": "dm3", "req_id": "1"}, "p")
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
            lock = cb.read_lock(Path(tmp) / "lab.lock")
            self.assertEqual(lock["owner"], "dashboard")
            self.assertEqual(lock["port"], 28599)
            self.assertEqual(lock["pid"], 4242)
            self.assertIn("ts", lock)
            self.assertIn("run_id", lock)

            # second start refuses while the session runs
            response, _ = bridge.handle({"op": "session_start", "map": "dm3", "req_id": "2"}, "p")
            self.assertFalse(response["ok"])
            self.assertIn("already running", response["detail"])

            # stop releases the lock
            response, broadcast = bridge.handle({"op": "session_stop", "req_id": "3"}, "p")
            self.assertTrue(response["ok"], response)
            self.assertEqual(broadcast, {"type": "control_event", "event": "session_stop", "port": 28599})
            self.assertIn(("stop_session", 28599), executor.calls)
            self.assertIsNone(cb.read_lock(Path(tmp) / "lab.lock"))

    def test_ports_exhausted_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge, executor = make_bridge(tmp, available_ports=())
            response, broadcast = bridge.handle({"op": "session_start", "map": "dm3", "req_id": "1"}, "p")
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
            response, broadcast = bridge.handle(
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
            response, _ = bridge.handle(
                {"op": "session_start", "map": "dm3", "force": True, "req_id": "1"}, "p"
            )
            self.assertTrue(response["ok"], response)
            stops = [c for c in executor.calls if c[0] == "stop_session"]
            self.assertEqual(stops, [])

    def test_session_start_invalid_map(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge, executor = make_bridge(tmp)
            for bad in ("../dm3", "dm3;quit", "", None, "qw_x"):
                response, _ = bridge.handle({"op": "session_start", "map": bad, "req_id": "1"}, "p")
                self.assertFalse(response["ok"], bad)
            self.assertEqual(executor.calls, [])

    def test_session_stop_refuses_production_port_even_with_force(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge, executor = make_bridge(tmp)
            for port in (28501, 28502, 28503, 27500):
                response, _ = bridge.handle(
                    {"op": "session_stop", "port": port, "force": True, "req_id": "1"}, "p"
                )
                self.assertFalse(response["ok"], port)
            self.assertEqual(executor.calls, [])

    def test_session_stop_without_lock_needs_force(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge, executor = make_bridge(tmp)
            response, _ = bridge.handle({"op": "session_stop", "port": 28600, "req_id": "1"}, "p")
            self.assertFalse(response["ok"])
            response, _ = bridge.handle(
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
            ):
                response, _ = bridge.handle(request, "p")
                self.assertFalse(response["ok"], request)
                self.assertIn("no dashboard session", response["detail"])
            self.assertEqual(executor.calls, [])

    def test_set_cvar_and_slot_form(self):
        with tempfile.TemporaryDirectory() as tmp:
            dashboard_lock(tmp, port=28600)
            bridge, executor = make_bridge(tmp)
            response, broadcast = bridge.handle(
                {"op": "set_cvar", "name": "k_fb_moveprobe_mode", "value": 21, "req_id": "1"}, "p"
            )
            self.assertTrue(response["ok"], response)
            self.assertEqual(executor.calls[-1], ("stuff", 28600, "set k_fb_moveprobe_mode 21"))
            self.assertEqual(broadcast["event"], "set_cvar")

            response, _ = bridge.handle(
                {"op": "set_cvar", "name": "k_fb_moveprobe_mode", "value": 21, "slot": 2, "req_id": "2"}, "p"
            )
            self.assertTrue(response["ok"])
            self.assertEqual(executor.calls[-1], ("stuff", 28600, "set k_fb_moveprobe_mode_s2 21"))

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
                response, broadcast = bridge.handle({**request, "req_id": "r"}, "p")
                self.assertFalse(response["ok"], request)
                self.assertIsNone(broadcast)
            self.assertEqual(executor.calls, [])

    def test_console_security_refusals(self):
        with tempfile.TemporaryDirectory() as tmp:
            dashboard_lock(tmp)
            bridge, executor = make_bridge(tmp)
            for line in ("rcon_password x", "exec a.cfg", "alias a b", "quit", "status;quit", "say /x"):
                response, _ = bridge.handle({"op": "console", "line": line, "req_id": "r"}, "p")
                self.assertFalse(response["ok"], line)
            self.assertEqual(executor.calls, [])
            response, _ = bridge.handle({"op": "console", "line": "status", "req_id": "r"}, "p")
            self.assertTrue(response["ok"])
            self.assertEqual(executor.calls, [("stuff", 28599, "status")])

    def test_addbot_and_removebot(self):
        with tempfile.TemporaryDirectory() as tmp:
            dashboard_lock(tmp)
            bridge, executor = make_bridge(tmp)
            response, _ = bridge.handle({"op": "addbot", "count": 2, "req_id": "1"}, "p")
            self.assertTrue(response["ok"])
            self.assertEqual(executor.calls[-1], ("add_bots", 28599, 2))
            for bad in (0, 9, "2", True):
                response, _ = bridge.handle({"op": "addbot", "count": bad, "req_id": "x"}, "p")
                self.assertFalse(response["ok"], bad)
            response, _ = bridge.handle({"op": "removebot", "req_id": "2"}, "p")
            self.assertEqual(executor.calls[-1], ("send_botcmds", 28599, ("removebot",)))
            response, _ = bridge.handle({"op": "removebot", "slot": "all", "req_id": "3"}, "p")
            self.assertEqual(executor.calls[-1], ("send_botcmds", 28599, ("removeall",)))
            response, _ = bridge.handle({"op": "removebot", "slot": 4, "req_id": "4"}, "p")
            self.assertEqual(executor.calls[-1], ("send_botcmds", 28599, ("removebot 4",)))
            response, _ = bridge.handle({"op": "removebot", "slot": "x", "req_id": "5"}, "p")
            self.assertFalse(response["ok"])


class TestProtocolEdges(unittest.TestCase):
    def test_unknown_op_and_bad_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge, _ = make_bridge(tmp)
            for request in ({"op": "reboot", "req_id": "1"}, {"req_id": "1"}, "x", None, 7, []):
                response, broadcast = bridge.handle(request, "p")
                self.assertFalse(response["ok"], request)
                self.assertIsNone(broadcast)

    def test_verdict_reserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge, _ = make_bridge(tmp)
            response, _ = bridge.handle({"op": "verdict", "req_id": "1"}, "p")
            self.assertFalse(response["ok"])
            self.assertIn("LD-F5", response["detail"])

    def test_executor_exception_answers_instead_of_raising(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge, executor = make_bridge(tmp)
            executor.start_session = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
            response, broadcast = bridge.handle({"op": "session_start", "map": "dm3", "req_id": "1"}, "p")
            self.assertFalse(response["ok"])
            self.assertIn("boom", response["detail"])
            self.assertIsNone(broadcast)
            # no lock left behind by the failed start
            self.assertIsNone(cb.read_lock(Path(tmp) / "lab.lock"))

    def test_lock_status_free(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge, _ = make_bridge(tmp)
            response, broadcast = bridge.handle({"op": "lock_status", "req_id": "1"}, "p")
            self.assertTrue(response["ok"])
            self.assertEqual(response["state"], "free")
            self.assertIsNone(response["lock"])
            self.assertIsNone(broadcast)


class TestAudit(unittest.TestCase):
    def test_every_mutating_attempt_is_audited(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge, _ = make_bridge(tmp)
            bridge.handle({"op": "session_start", "map": "dm3", "req_id": "1"}, "1.2.3.4")
            bridge.handle({"op": "set_cvar", "name": "rcon_password", "value": "x", "req_id": "2"}, "1.2.3.4")
            bridge.handle({"op": "lock_status", "req_id": "3"}, "1.2.3.4")  # read-only: not audited
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


if __name__ == "__main__":
    unittest.main()
