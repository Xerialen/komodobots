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
        # Team A (RED) is the LEAP side — a whole team of leap bots, no single
        # pinned row. The first four rows are all leap; no row is singled out.
        first_player, first_idx = rows[0]
        self.assertEqual(first_idx, 0)
        self.assertEqual(first_player["slot"], 1)
        red_roles = {p["roster"]["role"] for p, idx in rows if idx == 0}
        self.assertEqual(red_roles, {"leap"})

    def test_team_score_and_total_deltas(self):
        team_a = self.game["teams"][0]
        prev_a = next(t for t in self.prev["teams"] if t["name"] == team_a["name"])
        # Score delta is computed from team.score (wireframe shows "Score 35 +4").
        self.assertEqual(team_a["score"] - prev_a["score"], 4)
        # damage_done is a totals key with a numeric delta.
        self.assertIsNotNone(team_delta(team_a, prev_a, "damage_done"))

    def test_lead_leap_frag_delta_is_plus_four(self):
        komodo = next(p for p in self.game["players"] if p["slot"] == 1)
        self.assertEqual(komodo["roster"]["role"], "leap")
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
        komodo = next(p for p in self.game["players"] if p["slot"] == 1)
        self.assertIsNone(player_delta(komodo, None, "frags"))


# --- docs/18 T0.7 bench verdict banner (mirrors BenchVerdictBanner in the evidence TSX) ---

EVIDENCE_TSX = REPO / "lab" / "dashboard" / "src" / "FourVFourEvidence.tsx"


def ev_signed_margin(value) -> str:
    """Mirror of signedMargin() in FourVFourEvidence.tsx."""
    if value is None:
        return "—"
    v = str(int(value)) if float(value).is_integer() else f"{value:.1f}"
    return f"+{v}" if value > 0 else v


class EvidenceBenchBannerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ledger = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cls.bench = cls.ledger.get("bench")

    def test_fixture_carries_bench(self):
        self.assertIsNotNone(self.bench)
        self.assertEqual(self.bench["schema"], "komodobots.bench_frag_margin.v1")

    def test_banner_render_strings(self):
        self.assertEqual(ev_signed_margin(self.bench["leap_frag_margin_total"]), "+6")
        self.assertEqual(ev_signed_margin(self.bench["leap_frag_margin_mean"]), "+3")
        self.assertEqual(
            f"leap {self.bench['leap_wins']} – {self.bench['frog_wins']} frog",
            "leap 2 – 0 frog",
        )

    def test_negative_baseline_renders_signed(self):
        self.assertEqual(ev_signed_margin(-7), "-7")
        self.assertEqual(ev_signed_margin(-1.5), "-1.5")

    def test_evidence_source_wires_the_banner(self):
        src = EVIDENCE_TSX.read_text(encoding="utf-8")
        self.assertIn("data-evidence-bench", src)
        self.assertIn("BenchVerdict", src)
        self.assertIn("ledger.bench", src)


class EvidenceTeamDistinctionTest(unittest.TestCase):
    """Team (LEAP vs FROG) carries the distinction — the single-bot highlight is gone."""

    @classmethod
    def setUpClass(cls):
        cls.src = EVIDENCE_TSX.read_text(encoding="utf-8")

    def test_no_single_bot_highlight(self):
        # No more komodobot row special-case, no amber-50 tracked-row highlight,
        # no per-row tracked emphasis class.
        self.assertNotIn('role === "komodobot"', self.src)
        self.assertNotIn("bg-amber-50", self.src)
        self.assertNotIn("text-amber-700", self.src)
        self.assertNotIn("data-evidence-tracked", self.src)

    def test_team_side_is_the_differentiator(self):
        self.assertIn("toneForTeam", self.src)
        self.assertIn('"LEAP"', self.src)
        self.assertIn('"FROG"', self.src)
        self.assertIn("data-evidence-side", self.src)
        self.assertIn("game.bench?.leap_team", self.src)


class EvidenceTeamCompareAggregationTest(unittest.TestCase):
    """TeamCompare must resolve bar values through the same client-side
    aggregation path as the team cards (teamMetricValue / teamMetricDelta), so
    movement speed — which lives on player stats, not team totals — renders in
    the compare bars instead of dying as "—" (issue #258 Codex P2)."""

    @classmethod
    def setUpClass(cls):
        cls.src = EVIDENCE_TSX.read_text(encoding="utf-8")

    def test_teamcompare_takes_game_objects(self):
        # The compare strip is invoked with the full game / prevGame objects so
        # it can aggregate from player stats.
        self.assertIn("<TeamCompare", self.src)
        compare_call = self.src.split("<TeamCompare", 1)[1].split("/>", 1)[0]
        self.assertIn("game={game}", compare_call)
        self.assertIn("prevGame={prev}", compare_call)

    def test_teamcompare_bars_use_team_metric_helpers(self):
        # Inside TeamCompare's CompareBar, values/deltas route through the
        # aggregation helpers, NOT raw totals[row.key] (the regression we guard).
        body = self.src.split("function TeamCompare", 1)[1].split("\nfunction ", 1)[0]
        self.assertIn("teamMetricValue(game, left, row.key)", body)
        self.assertIn("teamMetricValue(game, right, row.key)", body)
        self.assertIn("teamMetricDelta(game, prevGame, left, prevLeft, row.key)", body)
        self.assertIn("teamMetricDelta(game, prevGame, right, prevRight, row.key)", body)
        # Regression guard: the old direct-total reads must be gone from the bars.
        self.assertNotIn("num(left.totals[row.key])", body)
        self.assertNotIn("num(right.totals[row.key])", body)


class EvidenceTrendsPickReconcileTest(unittest.TestCase):
    """The Trends custom subject selection must survive the 15s ledger refresh:
    the reset-to-defaults effect fires only on a real scope change; on a refresh
    (same scope, new array identities) picks are reconciled against the new pool
    rather than blanket-reset (issue #258 Codex P2)."""

    @classmethod
    def setUpClass(cls):
        cls.src = EVIDENCE_TSX.read_text(encoding="utf-8")
        cls.body = cls.src.split("function TrendsView", 1)[1].split("\nfunction ", 1)[0]

    def test_reset_is_gated_on_scope_change(self):
        # A ref tracks the previous scope; defaults are only applied when scope
        # actually changes.
        self.assertIn("prevScopeRef", self.body)
        self.assertIn("useRef(scope)", self.body)
        self.assertIn("prevScopeRef.current !== scope", self.body)

    def test_refresh_reconciles_instead_of_resetting(self):
        # On a same-scope refresh, kept picks are filtered against the new pool.
        self.assertIn("pool.map((s) => s.id)", self.body)
        self.assertIn("prev.filter((id) => ids.has(id))", self.body)


if __name__ == "__main__":
    unittest.main()
