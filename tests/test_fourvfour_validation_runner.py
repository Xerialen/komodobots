"""Fixed-roster 4v4 validation runner/control tests (LD-H3.3, issue #179)."""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "lab" / "server"))

import control_bridge as cb  # noqa: E402
import fourvfour_validation_runner as runner  # noqa: E402


class FakeExecutor:
    def __init__(self):
        self.calls = []

    def stuff(self, port, line):
        self.calls.append(("stuff", port, line))

    def send_botcmds(self, port, botcmds):
        self.calls.append(("send_botcmds", port, tuple(botcmds)))

    def send_client_cmds(self, port, commands):
        self.calls.append(("send_client_cmds", port, tuple(commands)))

    def add_bots(self, port, count):
        self.calls.append(("add_bots", port, count))


def dashboard_lock(path: Path, port: int = 28599):
    cb.write_lock(
        path / "lab.lock",
        {
            "owner": "dashboard",
            "run_id": "dash_20260614T200000Z",
            "pid": 4242,
            "ts": cb.utc_now_iso(),
            "port": port,
            "map": "dm3",
        },
    )


class FourVFourValidationRunnerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="4v4-runner-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_roster_intent_records_ktx_native_fixed_teams_and_komodo_slot(self):
        roster = runner.build_roster_intent(
            run_id="20260614T200000Z",
            controller_version="komodo-v2",
            komodobot_slot=3,
        )

        self.assertEqual(roster["schema"], "komodobots.4v4_roster_intent.v1")
        self.assertEqual(roster["map"], "dm3")
        self.assertEqual(roster["mode"], "4on4")
        self.assertEqual(roster["deathmatch"], 1)
        self.assertEqual(roster["teamplay"], 2)
        self.assertEqual(roster["timelimit"], 5)
        self.assertEqual(roster["komodobot_slot"], 3)
        self.assertEqual(len(roster["players"]), 8)
        teams = {team: 0 for team in ("red", "blue")}
        roles = {"komodobot": 0, "control": 0}
        for player in roster["players"]:
            teams[player["team"]] += 1
            roles[player["role"]] += 1
            self.assertEqual(player["bot_skill"], 20)
        self.assertEqual(teams, {"red": 4, "blue": 4})
        self.assertEqual(roles, {"komodobot": 1, "control": 7})
        komodo = roster["players"][2]
        self.assertEqual(komodo["role"], "komodobot")
        self.assertEqual(komodo["controller_version"], "komodo-v2")

    def test_roster_intent_allows_explicit_safe_team_names(self):
        roster = runner.build_roster_intent(
            run_id="20260614T200000Z",
            team_names=("alpha", "beta"),
        )

        self.assertEqual(roster["players"][0]["team"], "alpha")
        self.assertEqual(roster["players"][7]["team"], "beta")

    def test_roster_intent_rejects_unsafe_or_duplicate_team_names(self):
        for teams in (("red", "red"), ("red team", "blue"), ("1234567890", "blue")):
            with self.assertRaises(ValueError, msg=str(teams)):
                runner.build_roster_intent(run_id="20260614T200000Z", team_names=teams)

    def test_control_plan_refuses_production_ports(self):
        for denied in (28501, 28502, 28503, 27500, 28610):
            with self.assertRaises(ValueError, msg=str(denied)):
                runner.build_control_plan(run_id="r", port=denied)

    def test_control_plan_uses_lab_port_and_bridge_action(self):
        plan = runner.build_control_plan(run_id="20260614T200000Z", port=28599)

        self.assertEqual(plan["schema"], "komodobots.4v4_validation_plan.v1")
        self.assertEqual(plan["port"], 28599)
        self.assertEqual(
            plan["control_requests"],
            [
                {"op": "session_start", "map": "dm3"},
                {"op": "game_command", "action": "4v4_validation_prepare"},
            ],
        )
        self.assertIn({"kind": "console", "line": "set teamplay 2"}, plan["expected_bridge_steps"])
        self.assertEqual(
            [step for step in plan["expected_bridge_steps"] if step["line"] == "addbot 20 red"],
            [{"kind": "botcmd", "line": "addbot 20 red"}] * 4,
        )
        self.assertEqual(
            [step for step in plan["expected_bridge_steps"] if step["line"] == "addbot 20 blue"],
            [{"kind": "botcmd", "line": "addbot 20 blue"}] * 4,
        )
        self.assertIn(28501, plan["safety"]["denied_ports"])

    def test_write_run_artifacts_outputs_roster_and_plan(self):
        paths = runner.write_run_artifacts(
            self.tmp / "run",
            run_id="20260614T200000Z",
            port=28599,
            controller_version="komodo-v2",
        )

        self.assertTrue(paths["roster"].is_file())
        self.assertTrue(paths["plan"].is_file())
        roster = json.loads(paths["roster"].read_text(encoding="utf-8"))
        plan = json.loads(paths["plan"].read_text(encoding="utf-8"))
        self.assertEqual(roster["run_id"], "20260614T200000Z")
        self.assertEqual(plan["run_id"], "20260614T200000Z")

    def test_bridge_validation_action_command_construction(self):
        steps = cb.validate_game_command("4v4_validation_prepare")

        self.assertEqual(steps, list(cb.VALIDATION_4V4_STEPS))
        self.assertEqual(steps[0], ("client", "break"))
        self.assertIn(("botcmd", "removeall"), steps)
        self.assertIn(("client", "4on4"), steps)
        self.assertIn(("client", "dmm1"), steps)
        self.assertIn(("console", "set teamplay 2"), steps)
        self.assertIn(("console", "set k_fb_skill 20"), steps)
        self.assertIn(("console", "map dm3"), steps)
        self.assertEqual(steps.count(("botcmd", "addbot 20 red")), 4)
        self.assertEqual(steps.count(("botcmd", "addbot 20 blue")), 4)
        self.assertEqual(steps[-1], ("client", "ready"))
        self.assertEqual(cb.validate_console_line("set teamplay 2"), "set teamplay 2")

    def test_bridge_dispatch_executes_validation_action_inside_dashboard_session(self):
        dashboard_lock(self.tmp, port=28599)
        executor = FakeExecutor()
        bridge = cb.ControlBridge(
            lab_home=self.tmp,
            executor=executor,
            pid_alive=lambda _pid: True,
            own_pid=4242,
        )

        response, broadcast = bridge.handle(
            {"op": "game_command", "action": "4v4_validation_prepare", "req_id": "r1"},
            "local",
            peer_host="127.0.0.1",
        )

        self.assertTrue(response["ok"], response)
        self.assertEqual(broadcast["action"], "4v4_validation_prepare")
        self.assertIn(("send_botcmds", 28599, ("removeall",)), executor.calls)
        self.assertIn(("send_client_cmds", 28599, ("4on4",)), executor.calls)
        self.assertIn(("send_client_cmds", 28599, ("dmm1",)), executor.calls)
        self.assertIn(("stuff", 28599, "set teamplay 2"), executor.calls)
        self.assertIn(("stuff", 28599, "map dm3"), executor.calls)
        self.assertEqual(executor.calls.count(("send_botcmds", 28599, ("addbot 20 red",))), 4)
        self.assertEqual(executor.calls.count(("send_botcmds", 28599, ("addbot 20 blue",))), 4)
        self.assertEqual(executor.calls[-1], ("send_client_cmds", 28599, ("ready",)))


if __name__ == "__main__":
    unittest.main()
