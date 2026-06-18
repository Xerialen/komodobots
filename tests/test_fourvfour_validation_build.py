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

    def test_demo_url_points_at_served_online_route(self):
        # KTX writes the validation demo into ONLINE_DEMOS_DIR, served by cloud_hub
        # at /demos/online/<name>. The ledger demo.url must use that served route so
        # the dashboard "watch demo" link resolves; the old /demos/files/... prefix
        # had no cloud_hub route and 404'd. Regression guard for the #259 demo link.
        write_run(self.runs, "20260614T200000Z", controller_version="komodo-v1", komodo_frags=10)

        game = fv.build(self.runs)["games"][0]

        self.assertEqual(game["demo"]["name"], "20260614T200000Z.mvd")
        self.assertEqual(game["demo"]["url"], "/demos/online/20260614T200000Z.mvd")
        self.assertNotIn("/demos/files/", game["demo"]["url"])

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

    def test_speed_metrics_appear_in_ledger_and_deltas(self):
        # avg_speed / max_speed flow from the KTX speed block through the built ledger.
        write_run(self.runs, "20260614T200000Z")
        write_run(self.runs, "20260614T201000Z", controller_version="komodo-v2")

        data = fv.build(self.runs)

        self.assertIn("avg_speed", data["metrics"])
        self.assertIn("max_speed", data["metrics"])

        _, second = data["games"]
        for player in second["players"]:
            slot = player["slot"]
            self.assertIn("avg_speed", player["stats"], f"slot {slot} missing avg_speed in stats")
            self.assertIn("max_speed", player["stats"], f"slot {slot} missing max_speed in stats")
            self.assertEqual(player["stats"]["avg_speed"], 300.0,
                             f"slot {slot} unexpected avg_speed")
            self.assertEqual(player["stats"]["max_speed"], 500.0,
                             f"slot {slot} unexpected max_speed")
            self.assertIn("avg_speed", player["deltas"], f"slot {slot} missing avg_speed delta")
            self.assertIn("max_speed", player["deltas"], f"slot {slot} missing max_speed delta")
            # Second game has a previous, so delta value must be computed (300-300=0).
            avg_delta = player["deltas"]["avg_speed"]
            self.assertEqual(avg_delta["current"], 300.0)
            self.assertEqual(avg_delta["previous"], 300.0)
            self.assertEqual(avg_delta["value"], 0.0)

    def test_speed_delta_no_previous_when_single_game(self):
        write_run(self.runs, "20260614T200000Z")

        data = fv.build(self.runs)

        komodo = data["games"][0]["players"][0]
        self.assertEqual(komodo["deltas"]["avg_speed"]["scope"], "no_previous")
        self.assertIsNone(komodo["deltas"]["avg_speed"]["value"])
        self.assertIsNone(komodo["deltas"]["max_speed"]["value"])

    def test_extract_run_speeds_robust_to_malformed_metrics(self):
        # movement-metrics.json that is valid JSON but not an object (e.g. [] or a
        # string) must degrade to no speed, never raise (the "never raises" contract).
        with tempfile.TemporaryDirectory() as d:
            run_dir = Path(d)
            for bad in ("[]", '"nope"', "123"):
                (run_dir / fv.MOVEMENT_METRICS_FILENAME).write_text(bad)
                self.assertEqual(fv.extract_run_speeds(run_dir), {})
            # absent artifacts -> empty mapping (null speed), no crash
            (run_dir / fv.MOVEMENT_METRICS_FILENAME).unlink()
            self.assertEqual(fv.extract_run_speeds(run_dir), {})

    def test_attach_speeds_preserves_ktx_speed_when_no_analyzer(self):
        # A KTX stats block can carry speed; with no analyzer overlay it must be
        # kept, not cleared.
        players = [{"identity": {"name": "a"}, "roster": {"name": "a"},
                    "stats": {"avg_speed": 250.0, "max_speed": 480.0}}]
        fv._attach_speeds(players, {})
        self.assertEqual(players[0]["stats"]["avg_speed"], 250.0)
        self.assertEqual(players[0]["stats"]["max_speed"], 480.0)


def leap_roster(run_id: str, *, controller_version: str = "komodo-v1", team1: str = "Team A",
                team2: str = "Team B") -> dict:
    """A full frog-vs-leap roster: four leap bots (team1) vs four skill-20 frogbots (team2)."""
    names = [
        ("leap-1", team1, "leap", "komodobot", controller_version),
        ("leap-2", team1, "leap", "komodobot", controller_version),
        ("leap-3", team1, "leap", "komodobot", controller_version),
        ("leap-4", team1, "leap", "komodobot", controller_version),
        ("frog-control-5", team2, "control", "frogbot", "frogbot-20"),
        ("frog-control-6", team2, "control", "frogbot", "frogbot-20"),
        ("frog-control-7", team2, "control", "frogbot", "frogbot-20"),
        ("frog-control-8", team2, "control", "frogbot", "frogbot-20"),
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
        "komodobot_slot": None,
        "leap_team": team1,
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


def split_leap_roster(run_id: str, *, controller_version: str = "komodo-v1",
                      team1: str = "Team A", team2: str = "Team B") -> dict:
    """A malformed roster: the four leap bots are split 2+2 across both teams.

    Each team still holds four players (two leap + two skill-20 frogbot controls),
    so a pure role-count check would accept it, but no single leap team can be
    resolved (Codex P2 on PR #227). This must be rejected before scoring.
    """
    names = [
        ("leap-1", team1, "leap", "komodobot", controller_version),
        ("leap-2", team1, "leap", "komodobot", controller_version),
        ("a-control-3", team1, "control", "frogbot", "frogbot-20"),
        ("a-control-4", team1, "control", "frogbot", "frogbot-20"),
        ("leap-3", team2, "leap", "komodobot", controller_version),
        ("leap-4", team2, "leap", "komodobot", controller_version),
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
        "komodobot_slot": None,
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


class BenchFragMarginTest(unittest.TestCase):
    """docs/18 T0.1: bench emits leap-frog frag margin + R-T damage.matrix gate."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="4v4-bench-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.runs = self.tmp / "runs"
        self.runs.mkdir()

    def test_komodobot_roster_marks_komodo_team_as_leap(self):
        # Default roster: komodo-dev (slot 1, Team A) + 7 controls. Team A is leap.
        write_run(self.runs, "20260614T200000Z", komodo_frags=10)
        data = fv.build(self.runs)
        game = data["games"][0]
        bench = game["bench"]
        self.assertTrue(bench["resolved"])
        self.assertEqual(bench["leap_team"], "Team A")
        self.assertEqual(bench["frog_team"], "Team B")
        # Team A frags = 10+8+7+6 = 31; Team B = 9+8+7+6 = 30; margin = +1.
        self.assertEqual(bench["leap_frags"], 31)
        self.assertEqual(bench["frog_frags"], 30)
        self.assertEqual(bench["frag_margin"], 1)
        self.assertTrue(bench["leap_won"])

    def test_full_leap_roster_resolves_team_and_margin(self):
        run = write_run(self.runs, "20260614T200000Z", komodo_frags=12)
        run.joinpath("4v4-roster.json").write_text(
            json.dumps(leap_roster("20260614T200000Z")), encoding="utf-8"
        )
        data = fv.build(self.runs)
        self.assertEqual(data["provenance"]["valid_games"], 1)
        bench = data["games"][0]["bench"]
        self.assertTrue(bench["resolved"])
        self.assertEqual(bench["leap_team"], "Team A")
        self.assertEqual(bench["frog_team"], "Team B")
        # Team A leap frags = 12+8+7+6 = 33; Team B frog = 30; margin = +3.
        self.assertEqual(bench["frag_margin"], 3)
        # The legitimate four-leap-on-one-team shape still emits a green gate.
        self.assertTrue(data["games"][0]["damage_matrix"]["gate_pass"])
        self.assertTrue(data["bench"]["damage_matrix_gate_pass"])

    def test_split_leap_roster_is_invalid_and_never_scored_or_gated_green(self):
        # Regression for Codex P2 on PR #227: four leap bots split 2+2 across two
        # teams of four pass a pure role-count check but cannot resolve a single
        # leap team. Such a run must be rejected, not counted as a valid game with
        # a green damage.matrix gate and no margin.
        run = write_run(self.runs, "20260614T200000Z")
        run.joinpath("4v4-roster.json").write_text(
            json.dumps(split_leap_roster("20260614T200000Z")), encoding="utf-8"
        )
        data = fv.build(self.runs)

        # Not counted as valid; recorded as invalid with a clear reason.
        self.assertEqual(data["games"], [])
        self.assertEqual(data["provenance"]["valid_games"], 0)
        self.assertEqual(len(data["invalid_games"]), 1)
        reasons = data["invalid_games"][0]["reasons"]
        self.assertIn("roster_leap_roles_split_across_teams", reasons)
        # Defense in depth: the bench fail-closed check also fires.
        self.assertIn("bench_could_not_resolve_leap_vs_frog_teams", reasons)
        # No margin is emitted and the gate is NOT green.
        bench = data["bench"]
        self.assertEqual(bench["games_scored"], 0)
        self.assertIsNone(bench["leap_frag_margin_total"])
        self.assertFalse(bench["damage_matrix_gate_pass"])

    def test_damage_matrix_gate_green_when_enemy_damage_positive_and_no_team_damage(self):
        write_run(self.runs, "20260614T200000Z")
        data = fv.build(self.runs)
        gate = data["games"][0]["damage_matrix"]
        self.assertGreater(gate["enemy_damage"], 0)
        self.assertEqual(gate["intra_team_damage"], 0)
        self.assertTrue(gate["gate_pass"])
        self.assertEqual(gate["reasons"], [])
        self.assertTrue(data["bench"]["damage_matrix_gate_pass"])

    def test_damage_matrix_gate_red_when_intra_team_damage_present(self):
        run = write_run(self.runs, "20260614T200000Z")
        raw = json.loads((run / "analysis.json").read_text(encoding="utf-8"))
        raw["demoInfo"]["players"][1]["dmg"]["team"] = 150  # a teammate took friendly fire
        (run / "analysis.json").write_text(json.dumps(raw), encoding="utf-8")
        data = fv.build(self.runs)
        gate = data["games"][0]["damage_matrix"]
        self.assertEqual(gate["intra_team_damage"], 150)
        self.assertFalse(gate["gate_pass"])
        self.assertIn("intra_team_damage_above_tolerance", gate["reasons"])
        self.assertFalse(data["bench"]["damage_matrix_gate_pass"])

    def test_damage_matrix_gate_red_when_no_enemy_damage(self):
        run = write_run(self.runs, "20260614T200000Z")
        raw = json.loads((run / "analysis.json").read_text(encoding="utf-8"))
        for player in raw["demoInfo"]["players"]:
            player["dmg"]["given"] = 0
        (run / "analysis.json").write_text(json.dumps(raw), encoding="utf-8")
        data = fv.build(self.runs)
        gate = data["games"][0]["damage_matrix"]
        self.assertEqual(gate["enemy_damage"], 0)
        self.assertFalse(gate["gate_pass"])
        self.assertIn("no_enemy_damage", gate["reasons"])

    def test_bench_aggregate_is_best_of_n_and_repeatable(self):
        write_run(self.runs, "20260614T200000Z", komodo_frags=10)  # margin +1
        write_run(self.runs, "20260614T201000Z", komodo_frags=14)  # margin +5
        first = fv.build(self.runs)
        second = fv.build(self.runs)
        bench = first["bench"]
        self.assertEqual(bench["schema"], "komodobots.bench_frag_margin.v1")
        self.assertEqual(bench["games_scored"], 2)
        self.assertEqual(bench["leap_frag_margin_total"], 6)  # +1 then +5
        self.assertEqual(bench["leap_frag_margin_mean"], 3.0)
        self.assertEqual(bench["leap_wins"], 2)
        self.assertTrue(bench["damage_matrix_gate_pass"])
        self.assertEqual(len(bench["per_game"]), 2)
        self.assertEqual([g["frag_margin"] for g in bench["per_game"]], [1, 5])
        # Repeatable across two runs (docs/18 exit criterion).
        self.assertEqual(first["bench"], second["bench"])

    def test_bench_aggregate_empty_when_no_valid_games(self):
        data = fv.build(self.runs)
        bench = data["bench"]
        self.assertEqual(bench["games_scored"], 0)
        self.assertIsNone(bench["leap_frag_margin_total"])
        self.assertIsNone(bench["leap_frag_margin_mean"])
        self.assertFalse(bench["damage_matrix_gate_pass"])


if __name__ == "__main__":
    unittest.main()
