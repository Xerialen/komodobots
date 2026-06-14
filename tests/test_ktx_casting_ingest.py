"""Read-only KTX casting ingest tests (LD-H3.6, issue #182)."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "lab" / "server"))

import ktx_casting_ingest as ingest  # noqa: E402


def real_player(name: str, team: str, frags: int, deaths: int, dmg: int) -> dict:
    return {
        "top-color": 13,
        "bottom-color": 4,
        "ping": 25,
        "login": name.lower(),
        "name": name,
        "team": team,
        "stats": {
            "frags": frags,
            "deaths": deaths,
            "tk": 0,
            "spawn-frags": 0,
            "kills": max(frags, 0),
            "suicides": 0,
        },
        "dmg": {
            "taken": deaths * 120,
            "given": dmg,
            "team": 0,
            "self": 0,
            "team-weapons": 0,
            "enemy-weapons": dmg - 100,
            "taken-to-die": 99999 if deaths == 0 else 120,
        },
        "xferRL": 0,
        "xferLG": 0,
        "spree": {"max": 0, "quad": 0},
        "control": 12.5,
        "speed": {"max": 610.0, "avg": 325.0},
        "items": {"q": {"took": 1}} if name.endswith("1") else {},
        "weapons": {"rl": {"pickups": {"taken": 2}, "kills": {"enemy": 4}}},
    }


def real_ktx_match() -> dict:
    teams = ("The Vipers", "The Rangers")
    players = []
    for i in range(1, 5):
        players.append(real_player(f"viper-{i}", teams[0], 20 - i, 8 + i, 2500 - i * 100))
    for i in range(1, 5):
        players.append(real_player(f"ranger-{i}", teams[1], 18 - i, 9 + i, 2300 - i * 100))
    return {
        "version": 3,
        "date": "2026-05-01 21:00:00 +0200",
        "map": "dm2",
        "hostname": "QW.nu commentary server",
        "ip": "203.0.113.10",
        "port": 28501,
        "matchtag": "finals-game-1",
        "mode": "team",
        "tl": 20,
        "dm": 1,
        "tp": 2,
        "duration": 1200,
        "demo": "finals-game-1.mvd",
        "teams": list(teams),
        "players": players,
    }


class KtxCastingIngestTest(unittest.TestCase):
    def test_real_team_real_player_non_dm3_game_normalizes(self):
        data = ingest.ingest({"demoInfo": real_ktx_match()}, source_path="finals.json")

        self.assertEqual(data["schema"], "komodobots.ktx_match_stats.v1")
        self.assertEqual(data["source"]["kind"], "mvd_analyzer.demoInfo")
        self.assertTrue(data["source"]["casting_read_only"])
        self.assertIn("Read-only casting ingest", data["source"]["notes"][-1])
        self.assertEqual(data["match"]["map"], "dm2")
        self.assertEqual(data["match"]["duration"], 1200)
        self.assertEqual(data["match"]["timelimit"], 20)
        self.assertTrue(data["match"]["is_ktx_teamplay"])
        self.assertEqual({team["name"] for team in data["teams"]}, {"The Vipers", "The Rangers"})
        self.assertEqual(len(data["players"]), 8)
        self.assertFalse(any(p["identity"]["is_bot"] for p in data["players"]))
        self.assertNotIn("roster", data["players"][0])

    def test_team_scores_are_real_player_frag_sums(self):
        data = ingest.ingest(real_ktx_match())
        teams = {team["name"]: team for team in data["teams"]}

        self.assertEqual(teams["The Vipers"]["score"], sum(20 - i for i in range(1, 5)))
        self.assertEqual(teams["The Rangers"]["score"], sum(18 - i for i in range(1, 5)))
        self.assertEqual(teams["The Vipers"]["player_count"], 4)
        self.assertEqual(data["players"][0]["stats"]["quad_pickups"], 1)
        self.assertEqual(data["players"][0]["stats"]["rl_pickups"], 2)

    def test_cli_writes_same_canonical_schema(self):
        with tempfile.TemporaryDirectory(prefix="casting-ingest-") as tmp:
            tmp_path = Path(tmp)
            src = tmp_path / "raw.json"
            out = tmp_path / "normalized.json"
            src.write_text(json.dumps(real_ktx_match()), encoding="utf-8")

            rc = ingest.main([str(src), "--out", str(out)])

            self.assertEqual(rc, 0)
            written = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(written["schema"], "komodobots.ktx_match_stats.v1")
            self.assertEqual(written["source"]["path"], str(src))

    def test_casting_ingest_does_not_import_control_bridge(self):
        text = (REPO / "lab" / "server" / "ktx_casting_ingest.py").read_text(encoding="utf-8")
        self.assertNotIn("control_bridge", text)
        self.assertNotIn("ControlBridge", text)


if __name__ == "__main__":
    unittest.main()
