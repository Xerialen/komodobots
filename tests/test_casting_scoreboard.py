"""Casting scoreboard pure-logic tests (LD-H3.8, issue #184)."""

import json
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FIXTURE = REPO / "lab" / "dashboard" / "public" / "data" / "casting-match.example.json"


def players_for_team(data: dict, team_name: str) -> list[dict]:
    return sorted(
        [p for p in data["players"] if p["identity"]["team"] == team_name],
        key=lambda p: p["stats"]["frags"],
        reverse=True,
    )


def status_label(data: dict) -> str:
    return "live provisional" if data["source"].get("provisional") else "final KTX"


def duration_label(seconds) -> str:
    mins = seconds // 60
    secs = round(seconds % 60)
    return f"{mins}:{secs:02d}"


class CastingScoreboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_fixture_is_canonical_ktx_match_stats(self):
        self.assertEqual(self.data["schema"], "komodobots.ktx_match_stats.v1")
        self.assertTrue(self.data["source"]["casting_read_only"])
        self.assertEqual(self.data["match"]["map"], "dm2")
        self.assertEqual(self.data["match"]["duration"], 1200)

    def test_real_teams_and_players_render_without_bot_assumptions(self):
        self.assertEqual({team["name"] for team in self.data["teams"]}, {"The Vipers", "The Rangers"})
        self.assertEqual(len(self.data["players"]), 8)
        self.assertFalse(any(p["identity"]["is_bot"] for p in self.data["players"]))

    def test_scoreboard_sorts_players_by_frags(self):
        vipers = players_for_team(self.data, "The Vipers")
        self.assertEqual(vipers[0]["identity"]["name"], "viper-1")
        self.assertGreaterEqual(vipers[0]["stats"]["frags"], vipers[-1]["stats"]["frags"])

    def test_team_scores_match_canonical_team_totals(self):
        teams = {team["name"]: team for team in self.data["teams"]}
        self.assertEqual(teams["The Vipers"]["score"], sum(p["stats"]["frags"] for p in players_for_team(self.data, "The Vipers")))
        self.assertEqual(teams["The Rangers"]["score"], sum(p["stats"]["frags"] for p in players_for_team(self.data, "The Rangers")))

    def test_final_vs_provisional_label(self):
        self.assertEqual(status_label(self.data), "final KTX")
        provisional = {**self.data, "source": {**self.data["source"], "provisional": True}}
        self.assertEqual(status_label(provisional), "live provisional")

    def test_duration_label_for_obs_header(self):
        self.assertEqual(duration_label(self.data["match"]["duration"]), "20:00")


if __name__ == "__main__":
    unittest.main()
