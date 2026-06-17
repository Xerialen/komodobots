"""4v4 validation dashboard panel pure-logic tests (LD-H3.4, issue #180).

Mirrors the selection/formatting logic in FourVFourValidationPanel.tsx without
requiring a browser runtime.
"""

import json
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FIXTURE = REPO / "lab" / "dashboard" / "public" / "data" / "4v4-validation.example.json"

HIGHER_IS_BAD = {"deaths", "team_kills", "damage_taken", "team_weapon_damage"}


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


# --- docs/18 T0.7 bench verdict render (mirrors BenchVerdict in the panel TSX) ---

PANEL_TSX = REPO / "lab" / "dashboard" / "src" / "FourVFourValidationPanel.tsx"


def fmt_value(value: float) -> str:
    """Mirror of fmtValue(value, "number") in the panel."""
    if abs(value) >= 100:
        return str(round(value))
    return str(int(value)) if float(value).is_integer() else f"{value:.1f}"


def signed_margin(value) -> str:
    """Mirror of signedMargin() in the panel."""
    if value is None:
        return "—"
    return f"+{fmt_value(value)}" if value > 0 else fmt_value(value)


def margin_lead(total) -> str:
    """Mirror of marginLead() in the panel."""
    if total is None:
        return "no scored games"
    return "leap ahead" if total > 0 else "leap behind" if total < 0 else "even"


class BenchVerdictLogicTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ledger = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cls.bench = cls.ledger.get("bench")

    def test_fixture_carries_bench_aggregate(self):
        self.assertIsNotNone(self.bench, "fixture must carry the ledger-level bench aggregate")
        self.assertEqual(self.bench["schema"], "komodobots.bench_frag_margin.v1")
        self.assertEqual(self.bench["games_scored"], len(self.bench["per_game"]))

    def test_aggregate_is_internally_consistent(self):
        per_game_total = sum(g["frag_margin"] for g in self.bench["per_game"])
        self.assertEqual(self.bench["leap_frag_margin_total"], per_game_total)
        n = self.bench["games_scored"]
        self.assertEqual(self.bench["leap_frag_margin_mean"], round(per_game_total / n, 4))
        self.assertEqual(self.bench["leap_wins"] + self.bench["frog_wins"], n)

    def test_per_game_bench_and_gate_present(self):
        for game in self.ledger["games"]:
            self.assertIn("bench", game)
            self.assertIn("damage_matrix", game)
            b = game["bench"]
            self.assertEqual(b["frag_margin"], b["leap_frags"] - b["frog_frags"])
            self.assertIsInstance(game["damage_matrix"]["gate_pass"], bool)

    def test_gate_verdict_is_and_of_per_game(self):
        per_game_pass = all(g["damage_matrix"]["gate_pass"] for g in self.ledger["games"])
        self.assertEqual(self.bench["damage_matrix_gate_pass"], per_game_pass)

    def test_render_strings_for_fixture(self):
        # The committed fixture is a leap-ahead demo (+6 over best-of-2).
        self.assertEqual(signed_margin(self.bench["leap_frag_margin_total"]), "+6")
        self.assertEqual(signed_margin(self.bench["leap_frag_margin_mean"]), "+3")
        self.assertEqual(margin_lead(self.bench["leap_frag_margin_total"]), "leap ahead")

    def test_negative_baseline_renders_as_behind(self):
        # The expected T0.7 first result: leap loses -> negative margin is a valid baseline.
        self.assertEqual(signed_margin(-4), "-4")
        self.assertEqual(signed_margin(-2.5), "-2.5")
        self.assertEqual(margin_lead(-4), "leap behind")
        self.assertEqual(margin_lead(0), "even")
        self.assertEqual(margin_lead(None), "no scored games")

    def test_panel_source_wires_the_bench_verdict(self):
        src = PANEL_TSX.read_text(encoding="utf-8")
        self.assertIn('data-section="4v4-bench-verdict"', src)
        self.assertIn("ledger.bench", src)
        self.assertIn("R-T gate", src)


EVIDENCE_TSX = REPO / "lab" / "dashboard" / "src" / "FourVFourEvidence.tsx"


class SpeedColumnsFixtureTest(unittest.TestCase):
    """avg_speed / max_speed are carried in the fixture and wired into the TSX columns."""

    @classmethod
    def setUpClass(cls):
        cls.ledger = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cls.game = latest_game(cls.ledger)

    def test_fixture_metrics_list_includes_speed_keys(self):
        self.assertIn("avg_speed", self.ledger["metrics"])
        self.assertIn("max_speed", self.ledger["metrics"])

    def test_all_players_have_avg_and_max_speed_in_stats(self):
        for p in self.game["players"]:
            self.assertIn("avg_speed", p["stats"], f"slot {p['slot']} missing avg_speed")
            self.assertIn("max_speed", p["stats"], f"slot {p['slot']} missing max_speed")
            avg = p["stats"]["avg_speed"]
            mx = p["stats"]["max_speed"]
            self.assertIsNotNone(avg, f"slot {p['slot']} avg_speed is None")
            self.assertIsNotNone(mx, f"slot {p['slot']} max_speed is None")
            self.assertGreater(mx, avg, f"slot {p['slot']}: max_speed {mx} not > avg_speed {avg}")

    def test_all_players_have_speed_deltas_in_latest_game(self):
        # Second game (latest) must have cross-version deltas for speed.
        for p in self.game["players"]:
            self.assertIn("avg_speed", p["deltas"], f"slot {p['slot']} missing avg_speed delta")
            self.assertIn("max_speed", p["deltas"], f"slot {p['slot']} missing max_speed delta")

    def test_panel_tsx_wires_avg_and_max_speed_columns(self):
        src = PANEL_TSX.read_text(encoding="utf-8")
        self.assertIn("avg_speed", src)
        self.assertIn("max_speed", src)
        self.assertIn("Avg spd", src)
        self.assertIn("Max spd", src)

    def test_evidence_tsx_wires_avg_and_max_speed_columns(self):
        src = EVIDENCE_TSX.read_text(encoding="utf-8")
        self.assertIn("avg_speed", src)
        self.assertIn("max_speed", src)
        self.assertIn("Avg spd", src)
        self.assertIn("Max spd", src)

    def test_stat_value_returns_number_for_speed(self):
        komodo = next(p for p in self.game["players"] if p["roster"]["role"] == "komodobot")
        self.assertIsNotNone(stat_value(komodo, "avg_speed"))
        self.assertIsNotNone(stat_value(komodo, "max_speed"))


if __name__ == "__main__":
    unittest.main()
