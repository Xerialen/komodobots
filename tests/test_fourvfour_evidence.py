"""4v4 evidence page pure-logic tests (LD-H3, issue #200).

Mirrors the client-side delta + ordering logic in FourVFourEvidence.tsx (the
full-page "4v4 KTX Live Stats Evidence" wireframe) without a browser runtime.
Unlike the dock panel, the evidence page computes deltas itself from the
previous valid game, so these tests guard that math.
"""

import json
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FIXTURE = REPO / "lab" / "dashboard" / "public" / "data" / "4v4-validation.example.json"

# Lower-is-better metrics: a negative change-vs-previous is an improvement.
HIGHER_IS_BAD = {"deaths", "team_kills", "damage_taken", "team_weapon_damage", "rl_drops"}


def latest_game(ledger: dict) -> dict | None:
    return ledger["games"][-1] if ledger.get("games") else None


def find_prev_game(ledger: dict, game: dict) -> dict | None:
    prev_id = game.get("previous_valid_run_id")
    if prev_id:
        for g in ledger["games"]:
            if g["run_id"] == prev_id:
                return g
    idx = ledger["games"].index(game)
    return ledger["games"][idx - 1] if idx > 0 else None


def _num(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def team_delta(curr: dict, prev: dict | None, key: str):
    c = _num(curr["totals"].get(key))
    p = _num(prev["totals"].get(key)) if prev else None
    return None if c is None or p is None else c - p


def player_delta(curr: dict, prev: dict | None, key: str):
    c = _num(curr["stats"].get(key))
    p = _num(prev["stats"].get(key)) if prev else None
    return None if c is None or p is None else c - p


def ordered_players(game: dict) -> list[tuple[dict, int]]:
    out: list[tuple[dict, int]] = []
    for team_idx, team in enumerate(game["teams"]):
        members = [
            p for p in game["players"]
            if (p["roster"].get("team") or p["identity"].get("team")) == team["name"]
        ]
        for player in sorted(members, key=lambda p: p["slot"]):
            out.append((player, team_idx))
    return out


def delta_tone(metric: str, value) -> str:
    if value is None or value == 0:
        return "neutral"
    better = value < 0 if metric in HIGHER_IS_BAD else value > 0
    return "good" if better else "bad"


class FourVFourEvidenceLogicTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ledger = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cls.game = latest_game(cls.ledger)
        cls.prev = find_prev_game(cls.ledger, cls.game)

    def test_prev_game_resolves_from_previous_valid_run_id(self):
        self.assertIsNotNone(self.prev)
        self.assertEqual(self.prev["run_id"], self.game["previous_valid_run_id"])

    def test_ordered_players_groups_by_team_then_slot(self):
        rows = ordered_players(self.game)
        self.assertEqual(len(rows), 8)
        # teams[0] (RED) first, then teams[1] (BLUE); slots ascending within team.
        self.assertEqual([idx for _, idx in rows], [0, 0, 0, 0, 1, 1, 1, 1])
        red_slots = [p["slot"] for p, idx in rows if idx == 0]
        self.assertEqual(red_slots, sorted(red_slots))
        # The tracked komodobot is slot 1, first row.
        first_player, first_idx = rows[0]
        self.assertEqual(first_idx, 0)
        self.assertEqual(first_player["slot"], 1)
        self.assertEqual(first_player["roster"]["role"], "komodobot")

    def test_team_score_and_total_deltas(self):
        team_a = self.game["teams"][0]
        prev_a = next(t for t in self.prev["teams"] if t["name"] == team_a["name"])
        # Score delta is computed from team.score (wireframe shows "Score 35 +4").
        self.assertEqual(team_a["score"] - prev_a["score"], 4)
        # damage_done is a totals key with a numeric delta.
        self.assertIsNotNone(team_delta(team_a, prev_a, "damage_done"))

    def test_komodo_frag_delta_is_plus_four(self):
        komodo = next(p for p in self.game["players"] if p["roster"]["role"] == "komodobot")
        prev_komodo = next(p for p in self.prev["players"] if p["slot"] == komodo["slot"])
        self.assertEqual(komodo["stats"]["frags"], 14)
        self.assertEqual(prev_komodo["stats"]["frags"], 10)
        self.assertEqual(player_delta(komodo, prev_komodo, "frags"), 4)
        self.assertEqual(delta_tone("frags", 4), "good")

    def test_lower_is_better_tone_includes_rl_drops_not_ttd(self):
        # rl_drops is bad-when-up; taken_to_die (TTD, durability) is good-when-up.
        self.assertEqual(delta_tone("rl_drops", 1), "bad")
        self.assertEqual(delta_tone("rl_drops", -1), "good")
        self.assertEqual(delta_tone("taken_to_die", 5), "good")
        self.assertEqual(delta_tone("damage_taken", 50), "bad")
        self.assertEqual(delta_tone("damage_done", 50), "good")
        self.assertEqual(delta_tone("frags", 0), "neutral")

    def test_missing_previous_player_yields_no_delta(self):
        komodo = next(p for p in self.game["players"] if p["roster"]["role"] == "komodobot")
        self.assertIsNone(player_delta(komodo, None, "frags"))


if __name__ == "__main__":
    unittest.main()
