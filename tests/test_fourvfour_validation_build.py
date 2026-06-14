"""BotLab fixed-roster 4v4 ledger builder tests (LD-H3.2, issue #178)."""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "lab" / "server"))

import fourvfour_validation_build as fv  # noqa: E402


def ktx_player(name: str, team: str, frags: int, deaths: int, *, given: int, taken: int) -> dict:
    return {
        "top-color": 4 if team == "Team A" else 13,
        "bottom-color": 4 if team == "Team A" else 13,
        "ping": 10,
        "login": name.lower(),
        "name": name,
        "team": team,
        "stats": {
            "frags": frags,
            "deaths": deaths,
            "tk": 0,
            "spawn-frags": 0,
            "kills": frags,
            "suicides": 0,
        },
        "dmg": {
            "taken": taken,
            "given": given,
            "team": 0,
            "self": 0,
            "team-weapons": 0,
            "enemy-weapons": given - 25,
            "taken-to-die": 99999 if deaths == 0 else taken // deaths,
        },
        "xferRL": 0,
        "xferLG": 0,
        "spree": {"max": 0, "quad": 0},
        "control": 0.0,
        "speed": {"max": 500.0, "avg": 300.0},
        # Optional KTX weapon/item blocks intentionally absent by default.
        "weapons": {},
        "items": {},
        "bot": {"skill": 20, "customised": False},
    }


def ktx_match(run_id: str, *, duration: int = 300, map_name: str = "dm3", komodo_frags: int = 10) -> dict:
    players = [
        ktx_player("komodo-dev", "Team A", komodo_frags, 5, given=2000 + komodo_frags, taken=600),
        ktx_player("a-control-2", "Team A", 8, 6, given=1200, taken=700),
        ktx_player("a-control-3", "Team A", 7, 7, given=1000, taken=800),
        ktx_player("a-control-4", "Team A", 6, 8, given=900, taken=900),
        ktx_player("b-control-1", "Team B", 9, 7, given=1300, taken=850),
        ktx_player("b-control-2", "Team B", 8, 7, given=1200, taken=750),
        ktx_player("b-control-3", "Team B", 7, 7, given=1100, taken=750),
        ktx_player("b-control-4", "Team B", 6, 8, given=1000, taken=850),
    ]
    return {
        "version": 3,
        "run_id": run_id,
        "date": "2026-06-14 20:00:00 +0200",
        "map": map_name,
        "hostname": "servexeri lab",
        "ip": "127.0.0.1",
        "port": 28599,
        "matchtag": run_id,
        "mode": "team",
        "tl": 5,
        "fl": 5,
        "dm": 1,
        "tp": 2,
        "duration": duration,
        "demo": f"{run_id}.mvd",
        "teams": ["Team A", "Team B"],
        "players": players,
    }


def roster(run_id: str, *, controller_version: str = "komodo-v1", team1: str = "Team A",
           team2: str = "Team B") -> dict:
    names = [
        ("komodo-dev", team1, "komodobot", "komodobot", controller_version),
        ("a-control-2", team1, "control", "frogbot", "frogbot-20"),
        ("a-control-3", team1, "control", "frogbot", "frogbot-20"),
        ("a-control-4", team1, "control", "frogbot", "frogbot-20"),
        ("b-control-1", team2, "control", "frogbot", "frogbot-20"),
        ("b-control-2", team2, "control", "frogbot", "frogbot-20"),
        ("b-control-3", team2, "control", "frogbot", "frogbot-20"),
        ("b-control-4", team2, "control", "frogbot", "frogbot-20"),
    ]
    return {
        "schema": "komodobots.4v4_roster_intent.v1",
        "run_id": run_id,
        "map": "dm3",
        "mode": "4on4",
        "deathmatch": 1,
        "teamplay": 2,
        "timelimit": 5,
        "controller_version": controller_version,
        "komodobot_slot": 1,
        "players": [
            {
                "slot": slot,
                "id": f"slot-{slot}",
                "name": name,
                "team": team,
                "role": role,
                "bot_kind": kind,
                "bot_skill": 20,
                "controller_version": version,
            }
            for slot, (name, team, role, kind, version) in enumerate(names, start=1)
        ],
    }


def write_run(root: Path, run_id: str, *, duration: int = 300, controller_version: str = "komodo-v1",
              komodo_frags: int = 10, with_roster: bool = True, map_name: str = "dm3") -> Path:
    d = root / run_id
    d.mkdir(parents=True)
    (d / "analysis.json").write_text(
        json.dumps({"schemaVersion": 21, "demoInfo": ktx_match(
            run_id,
            duration=duration,
            map_name=map_name,
            komodo_frags=komodo_frags,
        )}),
        encoding="utf-8",
    )
    if with_roster:
        (d / "4v4-roster.json").write_text(json.dumps(roster(run_id, controller_version=controller_version)),
                                           encoding="utf-8")
    return d


class FourVFourValidationBuildTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="4v4-ledger-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.runs = self.tmp / "runs"
        self.runs.mkdir()

    def test_two_valid_games_get_slot_keyed_deltas(self):
        write_run(self.runs, "20260614T200000Z", controller_version="komodo-v1", komodo_frags=10)
        write_run(self.runs, "20260614T201000Z", controller_version="komodo-v2", komodo_frags=13)

        data = fv.build(self.runs)

        self.assertEqual(data["schema"], "komodobots.4v4_validation.v1")
        self.assertEqual(data["provenance"]["runs_scanned"], 2)
        self.assertEqual(data["provenance"]["valid_games"], 2)
        self.assertEqual(data["invalid_games"], [])
        self.assertIn("frags", data["metrics"])

        first, second = data["games"]
        self.assertIsNone(first["previous_valid_run_id"])
        self.assertEqual(second["previous_valid_run_id"], "20260614T200000Z")
        komodo = next(p for p in second["players"] if p["roster"]["role"] == "komodobot")
        self.assertEqual(komodo["slot"], 1)
        self.assertEqual(komodo["roster"]["id"], "slot-1")
        self.assertEqual(komodo["deltas"]["frags"]["current"], 13)
        self.assertEqual(komodo["deltas"]["frags"]["previous"], 10)
        self.assertEqual(komodo["deltas"]["frags"]["value"], 3)
        self.assertEqual(komodo["deltas"]["frags"]["scope"], "cross-version")

        control = next(p for p in second["players"] if p["slot"] == 2)
        self.assertEqual(control["deltas"]["frags"]["scope"], "same-version")

    def test_under_five_minutes_is_excluded_but_recorded(self):
        write_run(self.runs, "20260614T200000Z", duration=299)

        data = fv.build(self.runs)

        self.assertEqual(data["games"], [])
        self.assertEqual(len(data["invalid_games"]), 1)
        self.assertIn("under_minimum_duration", data["invalid_games"][0]["reasons"])
        self.assertEqual(data["provenance"]["skipped"]["under_minimum_duration"], 1)

    def test_missing_roster_is_invalid_for_botlab_but_stats_still_parse(self):
        write_run(self.runs, "20260614T200000Z", with_roster=False)

        data = fv.build(self.runs)

        self.assertEqual(data["games"], [])
        self.assertEqual(data["provenance"]["skipped"]["missing_roster_intent"], 1)
        self.assertIn("missing_roster_intent", data["invalid_games"][0]["reasons"])

    def test_raw_ktx_sidecar_is_preferred_over_analyzer_json_when_both_exist(self):
        run = write_run(self.runs, "20260614T200000Z")
        (run / "analysis.json").write_text(json.dumps({"schemaVersion": 21, "frames": []}), encoding="utf-8")
        (run / "ktxstats.json").write_text(json.dumps(ktx_match("20260614T200000Z")), encoding="utf-8")

        data = fv.build(self.runs)

        self.assertEqual(data["provenance"]["valid_games"], 1)
        self.assertTrue(data["games"][0]["stats_artifact"].endswith("ktxstats.json"))

    def test_wrong_team_shape_is_invalid_downstream(self):
        run = write_run(self.runs, "20260614T200000Z")
        raw = json.loads((run / "analysis.json").read_text(encoding="utf-8"))
        raw["demoInfo"]["players"][7]["team"] = "Team A"
        (run / "analysis.json").write_text(json.dumps(raw), encoding="utf-8")

        data = fv.build(self.runs)

        self.assertEqual(data["games"], [])
        self.assertIn("teams_not_two_teams_4_each", data["invalid_games"][0]["reasons"])

    def test_ktx_native_red_blue_teams_are_valid_when_roster_matches(self):
        run = write_run(self.runs, "20260614T200000Z")
        raw = json.loads((run / "analysis.json").read_text(encoding="utf-8"))
        for idx, player in enumerate(raw["demoInfo"]["players"]):
            player["team"] = "red" if idx < 4 else "blue"
        raw["demoInfo"]["teams"] = ["red", "blue"]
        (run / "analysis.json").write_text(json.dumps(raw), encoding="utf-8")
        (run / "4v4-roster.json").write_text(
            json.dumps(roster("20260614T200000Z", team1="red", team2="blue")),
            encoding="utf-8",
        )

        data = fv.build(self.runs)

        self.assertEqual(data["provenance"]["valid_games"], 1)
        self.assertEqual(data["games"][0]["teams"][0]["name"], "blue")
        self.assertEqual(data["games"][0]["teams"][1]["name"], "red")

    def test_analyzer_demoinfo_uses_metadata_for_mode_settings(self):
        run = write_run(self.runs, "20260614T200000Z")
        raw = json.loads((run / "analysis.json").read_text(encoding="utf-8"))
        raw["demoInfo"]["timelimit"] = raw["demoInfo"].pop("tl")
        raw["demoInfo"].pop("dm")
        raw["demoInfo"].pop("tp")
        raw["metadata"] = {
            "matchSettings": {
                "deathmatch": 1,
                "teamplay": 2,
                "timelimit": 5,
            },
            "serverInfo": {
                "deathmatch": "1",
                "teamplay": "2",
                "timelimit": "5",
            },
        }
        (run / "analysis.json").write_text(json.dumps(raw), encoding="utf-8")

        data = fv.build(self.runs)

        self.assertEqual(data["provenance"]["valid_games"], 1)
        self.assertEqual(data["games"][0]["match"]["deathmatch"], 1)
        self.assertEqual(data["games"][0]["match"]["teamplay"], 2)
        self.assertEqual(data["games"][0]["match"]["timelimit"], 5)

    def test_stats_team_names_must_match_roster_team_names(self):
        run = write_run(self.runs, "20260614T200000Z")
        (run / "4v4-roster.json").write_text(
            json.dumps(roster("20260614T200000Z", team1="red", team2="blue")),
            encoding="utf-8",
        )

        data = fv.build(self.runs)

        self.assertEqual(data["games"], [])
        self.assertIn("teams_do_not_match_roster_teams", data["invalid_games"][0]["reasons"])

    def test_missing_optional_ktx_blocks_become_zero_in_valid_game(self):
        write_run(self.runs, "20260614T200000Z")

        data = fv.build(self.runs)

        komodo = data["games"][0]["players"][0]
        self.assertEqual(komodo["stats"]["health_pickups"], 0)
        self.assertEqual(komodo["stats"]["rl_pickups"], 0)
        self.assertEqual(komodo["deltas"]["health_pickups"]["scope"], "no_previous")

    def test_cli_writes_ledger(self):
        write_run(self.runs, "20260614T200000Z")
        out = self.tmp / "records" / "4v4-validation.json"

        rc = fv.main(["--runs-dir", str(self.runs), "--out", str(out)])

        self.assertEqual(rc, 0)
        written = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(written["schema"], "komodobots.4v4_validation.v1")
        self.assertEqual(written["provenance"]["valid_games"], 1)


if __name__ == "__main__":
    unittest.main()
