"""KTX match-stat normalizer contract tests (LD-H3.1, issue #177)."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "lab" / "server"))

import ktx_match_stats as kms  # noqa: E402


def player(
    name: str,
    team: str,
    *,
    frags: int,
    deaths: int,
    kills: int | None = None,
    tk: int = 0,
    given: int = 0,
    taken: int = 0,
    ewep: int = 0,
    taken_to_die: int | None = None,
    items: dict | None = None,
    weapons: dict | None = None,
    bot: bool = True,
) -> dict:
    if kills is None:
        kills = max(frags, 0)
    if taken_to_die is None:
        taken_to_die = 99999 if deaths == 0 else taken // deaths
    ent = {
        "top-color": 4,
        "bottom-color": 4,
        "ping": 10,
        "login": name.lower(),
        "name": name,
        "team": team,
        "stats": {
            "frags": frags,
            "deaths": deaths,
            "tk": tk,
            "spawn-frags": 0,
            "kills": kills,
            "suicides": 0,
        },
        "dmg": {
            "taken": taken,
            "given": given,
            "team": tk * 100,
            "self": 0,
            "team-weapons": tk * 75,
            "enemy-weapons": ewep,
            "taken-to-die": taken_to_die,
        },
        "xferRL": 0,
        "xferLG": 0,
        "spree": {"max": 0, "quad": 0},
        "control": 0.0,
        "speed": {"max": 520.0, "avg": 310.0},
        "weapons": weapons or {},
        "items": items or {},
    }
    if bot:
        ent["bot"] = {"skill": 20, "customised": False}
    return ent


def base_match(players: list[dict]) -> dict:
    return {
        "version": 3,
        "date": "2026-06-14 20:00:00 +0200",
        "map": "dm3",
        "hostname": "servexeri lab",
        "ip": "127.0.0.1",
        "port": 28599,
        "matchtag": "LD-H3 fixture",
        "mode": "team",
        "tl": 5,
        "fl": 5,
        "dm": 1,
        "tp": 2,
        "duration": 300,
        "demo": "fixture.mvd",
        "teams": ["Team A", "Team B"],
        "players": players,
    }


class KtxMatchStatsTest(unittest.TestCase):
    def test_minimal_team_fixture_normalizes_optional_blocks_as_zero(self):
        raw = base_match([
            player("A1", "Team A", frags=10, deaths=5, kills=11, given=1100, taken=500, ewep=900),
            player("A2", "Team A", frags=8, deaths=7, given=900, taken=700),
            player("A3", "Team A", frags=6, deaths=8, given=700, taken=800),
            player("A4", "Team A", frags=4, deaths=9, given=500, taken=900),
            player("B1", "Team B", frags=9, deaths=6, given=1000, taken=600),
            player("B2", "Team B", frags=7, deaths=7, given=800, taken=700),
            player("B3", "Team B", frags=5, deaths=8, given=600, taken=800),
            player("B4", "Team B", frags=3, deaths=9, given=400, taken=900),
        ])
        data = kms.normalize_match(raw, source_path="minimal.json")

        self.assertEqual(data["schema"], "komodobots.ktx_match_stats.v1")
        self.assertEqual(data["source"]["kind"], "ktxstats")
        self.assertTrue(data["match"]["is_ktx_teamplay"])
        self.assertIn("KTX fl matches tl", "; ".join(data["warnings"]))
        self.assertEqual(len(data["players"]), 8)

        first = data["players"][0]
        self.assertEqual(first["stats"]["frags"], 10)
        self.assertEqual(first["stats"]["damage_done"], 1100)
        self.assertAlmostEqual(first["stats"]["efficiency"], 11 / 16, places=4)
        self.assertEqual(first["stats"]["health_pickups"], 0)
        self.assertEqual(first["stats"]["rl_pickups"], 0)
        self.assertIn("players[0]", first["sources"]["frags"])

        by_team = {t["name"]: t for t in data["teams"]}
        self.assertEqual(by_team["Team A"]["score"], 28)
        self.assertEqual(by_team["Team B"]["score"], 24)
        self.assertEqual(by_team["Team A"]["score_source"],
                         "sum(players[].stats.frags) because KTX JSON has no team score block")

    def test_rich_mvd_analyzer_demo_info_fixture_preserves_ktx_fields(self):
        raw_match = base_match([
            player(
                "komodo-dev", "Team A", frags=12, deaths=0, kills=12,
                given=2400, taken=300, ewep=1800,
                items={
                    "health_15": {"took": 2},
                    "health_25": {"took": 3},
                    "health_100": {"took": 1},
                    "q": {"took": 4},
                    "p": {"took": 1},
                    "r": {"took": 0},
                },
                weapons={
                    "rl": {
                        "kills": {"total": 7, "team": 0, "enemy": 7, "self": 0},
                        "pickups": {"taken": 5, "dropped": 2},
                    },
                    "lg": {
                        "kills": {"total": 2, "team": 0, "enemy": 2, "self": 0},
                        "pickups": {"taken": 1},
                    },
                },
            ),
            player("A2", "Team A", frags=1, deaths=1, given=100, taken=100),
            player("A3", "Team A", frags=1, deaths=1, given=100, taken=100),
            player("A4", "Team A", frags=1, deaths=1, given=100, taken=100),
            player("B1", "Team B", frags=1, deaths=1, given=100, taken=100),
            player("B2", "Team B", frags=1, deaths=1, given=100, taken=100),
            player("B3", "Team B", frags=1, deaths=1, given=100, taken=100),
            player("B4", "Team B", frags=1, deaths=1, given=100, taken=100),
        ])
        data = kms.normalize_match({"demoInfo": raw_match, "schemaVersion": 21})

        self.assertEqual(data["source"]["kind"], "mvd_analyzer.demoInfo")
        dev = data["players"][0]
        self.assertEqual(dev["id"], "01:team_a:komodo-dev")
        self.assertTrue(dev["identity"]["is_bot"])
        self.assertEqual(dev["identity"]["bot"]["skill"], 20)
        self.assertIsNone(dev["stats"]["taken_to_die"])
        self.assertIs(dev["stats"]["survived_without_death"], True)
        self.assertEqual(dev["stats"]["taken_to_die_raw"], 99999)
        self.assertEqual(dev["pickups"]["health"]["total"], 6)
        self.assertEqual(dev["stats"]["quad_pickups"], 4)
        self.assertEqual(dev["stats"]["pent_pickups"], 1)
        self.assertEqual(dev["stats"]["rl_pickups"], 5)
        self.assertEqual(dev["stats"]["rl_drops"], 2)
        self.assertEqual(dev["stats"]["enemy_rl_kills"], 7)
        self.assertEqual(dev["weapons"]["lg"]["pickups_taken"], 1)
        self.assertEqual(dev["stats"]["enemy_weapon_damage"], 1800)
        self.assertEqual(dev["stats"]["avg_speed"], 310.0)
        self.assertEqual(dev["stats"]["max_speed"], 520.0)

    def test_wrong_mode_and_broken_player_return_warnings_not_exceptions(self):
        raw = {
            "mode": "ffa",
            "dm": 3,
            "tp": 0,
            "duration": 120,
            "players": [{"name": "broken", "team": ""}],
        }
        data = kms.normalize_match(raw)

        warnings = "; ".join(data["warnings"])
        self.assertIn("mode is 'ffa'", warnings)
        self.assertIn("deathmatch dm is 3", warnings)
        self.assertIn("teamplay tp is 0", warnings)
        self.assertIn("missing required stats block", warnings)
        self.assertEqual(data["players"][0]["stats"]["frags"], 0)
        self.assertFalse(data["match"]["is_ktx_teamplay"])

    def test_cli_writes_canonical_json(self):
        with tempfile.TemporaryDirectory(prefix="ktx-normalize-") as tmp:
            tmp_path = Path(tmp)
            raw_path = tmp_path / "raw.json"
            out_path = tmp_path / "out.json"
            raw_path.write_text(
                json.dumps(base_match([
                    player("A1", "Team A", frags=1, deaths=1),
                    player("A2", "Team A", frags=1, deaths=1),
                    player("A3", "Team A", frags=1, deaths=1),
                    player("A4", "Team A", frags=1, deaths=1),
                    player("B1", "Team B", frags=1, deaths=1),
                    player("B2", "Team B", frags=1, deaths=1),
                    player("B3", "Team B", frags=1, deaths=1),
                    player("B4", "Team B", frags=1, deaths=1),
                ])),
                encoding="utf-8",
            )
            rc = kms.main([str(raw_path), "--out", str(out_path)])
            self.assertEqual(rc, 0)
            written = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(written["schema"], "komodobots.ktx_match_stats.v1")
            self.assertEqual(written["source"]["path"], str(raw_path))


if __name__ == "__main__":
    unittest.main()
