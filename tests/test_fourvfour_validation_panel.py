"""4v4 validation dashboard panel pure-logic tests (LD-H3.4, issue #180).

Mirrors the selection/formatting logic in FourVFourValidationPanel.tsx without
requiring a browser runtime.
"""

import json
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FIXTURE = REPO / "lab" / "dashboard" / "public" / "data" / "4v4-validation.example.json"
PANEL_SOURCE = REPO / "lab" / "dashboard" / "src" / "FourVFourValidationPanel.tsx"

HIGHER_IS_BAD = {"deaths", "team_kills", "damage_taken", "team_weapon_damage", "rl_drops"}


def latest_game(ledger: dict) -> dict | None:
    return ledger["games"][-1] if ledger.get("games") else None


def players_for_team(game: dict, team_name: str) -> list[dict]:
    return sorted(
        [p for p in game["players"] if (p["roster"].get("team") or p["identity"].get("team")) == team_name],
        key=lambda p: p["slot"],
    )


def delta_tone(metric: str, value):
    if value is None:
        return "none"
    if value == 0:
        return "neutral"
    better = value < 0 if metric in HIGHER_IS_BAD else value > 0
    return "good" if better else "bad"


def delta_label(delta: dict | None, kind: str = "number") -> str:
    if not delta or delta.get("value") is None or delta.get("scope") == "no_previous":
        return ""
    value = delta["value"]
    sign = "+" if value > 0 else ""
    if kind == "percent":
        return f"{sign}{round(value * 100)}%"
    if float(value).is_integer():
        return f"{sign}{int(value)}"
    return f"{sign}{value:.1f}"


def stat_value(player: dict, key: str):
    value = player["stats"].get(key)
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


class FourVFourValidationPanelLogicTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ledger = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cls.game = latest_game(cls.ledger)

    def test_fixture_has_two_games_and_latest_previous_id(self):
        self.assertEqual(self.ledger["schema"], "komodobots.4v4_validation.v1")
        self.assertEqual(len(self.ledger["games"]), 2)
        self.assertEqual(self.game["previous_valid_run_id"], "20260614T200000Z")

    def test_latest_game_renders_all_eight_bots_by_team(self):
        self.assertEqual(len(self.game["players"]), 8)
        self.assertEqual(len(players_for_team(self.game, "Team A")), 4)
        self.assertEqual(len(players_for_team(self.game, "Team B")), 4)

    def test_komodobot_slot_is_pinned(self):
        komodos = [p for p in self.game["players"] if p["roster"]["role"] == "komodobot"]
        self.assertEqual(len(komodos), 1)
        self.assertEqual(komodos[0]["slot"], 1)
        self.assertTrue(komodos[0]["roster"]["tracked"])

    def test_frags_delta_has_strong_positive_label(self):
        komodo = next(p for p in self.game["players"] if p["roster"]["role"] == "komodobot")
        self.assertEqual(stat_value(komodo, "frags"), 14)
        delta = komodo["deltas"]["frags"]
        self.assertEqual(delta["previous"], 10)
        self.assertEqual(delta["current"], 14)
        self.assertEqual(delta["value"], 4)
        self.assertEqual(delta["scope"], "cross-version")
        self.assertEqual(delta_label(delta), "+4")
        self.assertEqual(delta_tone("frags", delta["value"]), "good")

    def test_lower_is_better_delta_semantics(self):
        self.assertEqual(delta_tone("team_kills", -1), "good")
        self.assertEqual(delta_tone("team_kills", 1), "bad")
        self.assertEqual(delta_tone("damage_taken", -50), "good")
        self.assertEqual(delta_tone("damage_taken", 50), "bad")
        self.assertEqual(delta_tone("frags", -1), "bad")

    def test_unavailable_metric_is_not_rendered_as_zero(self):
        player = {"stats": {"taken_to_die": None}}
        self.assertIsNone(stat_value(player, "taken_to_die"))

    def test_team_totals_available_for_header(self):
        teams = {team["name"]: team for team in self.game["teams"]}
        self.assertEqual(teams["Team A"]["player_count"], 4)
        self.assertGreater(teams["Team A"]["score"], teams["Team B"]["score"])
        self.assertIn("damage_done", teams["Team A"]["totals"])

    def test_requested_pickups_speed_and_rl_denial_are_available_with_deltas(self):
        komodo = next(p for p in self.game["players"] if p["roster"]["role"] == "komodobot")
        for key in (
            "pill_pickups",
            "brick_pickups",
            "mega_pickups",
            "ya_pickups",
            "ra_pickups",
            "lg_pickups",
            "enemy_rl_kills",
            "avg_speed",
            "max_speed",
        ):
            with self.subTest(key=key):
                self.assertIsNotNone(stat_value(komodo, key))
                self.assertIn(key, komodo["deltas"])
                self.assertIsNotNone(komodo["deltas"][key]["value"])

        teams = {team["name"]: team for team in self.game["teams"]}
        self.assertEqual(teams["Team A"]["totals"]["mega_pickups"], 5)
        self.assertEqual(teams["Team A"]["totals"]["ya_pickups"], 7)
        self.assertEqual(teams["Team A"]["totals"]["ra_pickups"], 3)
        self.assertEqual(teams["Team A"]["totals"]["lg_pickups"], 4)

    def test_visible_metric_source_uses_quake_terms_and_no_aggregate_health_column(self):
        source = PANEL_SOURCE.read_text(encoding="utf-8")
        self.assertIn('label: "to-die"', source)
        self.assertIn('label: "RL EK"', source)
        self.assertIn('label: "AvgSpd"', source)
        self.assertIn('label: "MaxSpd"', source)
        self.assertIn('data-validation-table={title}', source)
        self.assertIn("grid grid-cols-4 gap-1", source)
        self.assertNotIn('label: "TTD"', source)
        self.assertNotIn('key: "health_pickups"', source)
        self.assertNotIn("min-w-[760px]", source)


if __name__ == "__main__":
    unittest.main()
