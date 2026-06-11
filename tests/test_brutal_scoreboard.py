"""Brutal scoreboard data-contract tests (LD-E2, issue #101).

Validates the deriveScoreboard logic in Python, testing the same rules as
BrutalScoreboard.tsx:

- The Race: finishes/attempts + median×human from route aggregates (or overall)
- Jump Count: N/11 from first_completion records across all dm3 routes
- Speedometer: peak_speed % of human_ref, edge_speed sub-line
- Eye Test: latest verdict from verdicts.json per route
- Honest zeros: no record yet → null/0, never hidden
- Route context: single-route mode vs overall mode
- Context route completed flag from first_completion presence

These tests exercise the pure data derivation.  No browser or TypeScript
runtime required.
"""

import unittest


# ---------------------------------------------------------------------------
# Constants from BrutalScoreboard.tsx
# ---------------------------------------------------------------------------

DM3_ROUTES_ORDERED = [
    "sng_shortcut2",
    "hilljump",
    "rl_to_ya",
    "ring_to_mega",
    "ra_jumps",
    "mega_to_rl",
    "rl_to_bridge",
    "sng_shortcut",
    "sng_to_rl",
    "mega_to_window",
    "sng_jumps",
]

TOTAL_DM3_ROUTES = len(DM3_ROUTES_ORDERED)  # 11


# ---------------------------------------------------------------------------
# Re-implement deriveScoreboard from BrutalScoreboard.tsx in Python
# ---------------------------------------------------------------------------

def _make_context(map_name="dm3", route=None, source="none"):
    return {"map": map_name, "route": route, "source": source}


def derive_scoreboard(records, verdicts, context):
    """Python translation of BrutalScoreboard.tsx deriveScoreboard.

    Returns a dict matching ScoreboardState shape:
      race: {finishes, attempts, multipleOfHuman}
      jumpCount: {completed, total, contextRouteCompleted}
      speedometer: {botSpeed, humanSpeed, pct, edge}
      eyeTest: {verdict, label}
      loaded: bool
      error: str | None
    """
    base = {
        "race": {"finishes": 0, "attempts": 0, "multipleOfHuman": None},
        "jumpCount": {
            "completed": 0,
            "total": TOTAL_DM3_ROUTES,
            "contextRouteCompleted": None,
        },
        "speedometer": {
            "botSpeed": None,
            "humanSpeed": None,
            "pct": None,
            "edge": None,
        },
        "eyeTest": {"verdict": None, "label": "no verdict yet"},
        "loaded": False,
        "error": None,
    }

    if records is None:
        return base

    dm3_map = records.get("maps", {}).get("dm3")
    if not dm3_map:
        return {**base, "loaded": True}

    dm3_routes = dm3_map.get("routes", {})

    # ---- Jump Count --------------------------------------------------------
    completed = 0
    context_route_completed = None

    for route_name in DM3_ROUTES_ORDERED:
        route_data = dm3_routes.get(route_name, {})
        has_completion = route_data.get("records", {}).get("first_completion") is not None
        if has_completion:
            completed += 1
        if route_name == context.get("route"):
            context_route_completed = has_completion

    # ---- The Race ----------------------------------------------------------
    route = context.get("route")
    race_finishes = 0
    race_attempts = 0
    race_multiple = None

    if route and route in dm3_routes:
        agg = dm3_routes[route].get("aggregates", {})
        race_finishes = agg.get("finishes", 0)
        race_attempts = agg.get("attempts", 0)
        median = agg.get("median_time_s")
        human_t = agg.get("human_time_s", 0)
        if race_finishes > 0 and median is not None and human_t > 0:
            race_multiple = median / human_t
    else:
        # Overall mode
        for rd in dm3_routes.values():
            agg = rd.get("aggregates", {})
            race_finishes += agg.get("finishes", 0)
            race_attempts += agg.get("attempts", 0)
        multiples = []
        for rd in dm3_routes.values():
            agg = rd.get("aggregates", {})
            f = agg.get("finishes", 0)
            m = agg.get("median_time_s")
            h = agg.get("human_time_s", 0)
            if f > 0 and m is not None and h > 0:
                multiples.append(m / h)
        if multiples:
            race_multiple = sum(multiples) / len(multiples)

    # ---- Speedometer -------------------------------------------------------
    bot_speed = None
    human_speed = None
    speed_pct = None
    edge_info = None

    if route and route in dm3_routes:
        route_data = dm3_routes[route]
        records_dict = route_data.get("records", {})

        peak_rec = records_dict.get("peak_speed")
        if peak_rec:
            bot_speed = peak_rec.get("value")
            hr = peak_rec.get("human_ref")
            if hr:
                human_speed = hr.get("value")
        if bot_speed is not None and human_speed is not None and human_speed > 0:
            speed_pct = (bot_speed / human_speed) * 100

        edge_rec = records_dict.get("edge_speed")
        if edge_rec:
            bot_edge = edge_rec.get("value")
            hr2 = edge_rec.get("human_ref")
            human_edge = hr2.get("value") if hr2 else None
            edge_pct = None
            if bot_edge is not None and human_edge is not None and human_edge > 0:
                edge_pct = (bot_edge / human_edge) * 100
            edge_info = {
                "botEdgeSpeed": bot_edge,
                "humanEdgeSpeed": human_edge,
                "pct": edge_pct,
            }

    # ---- Eye Test ----------------------------------------------------------
    verdict = None
    verdict_label = "no verdict yet"

    if verdicts and route:
        entry = verdicts.get("routes", {}).get(route)
        if entry:
            verdict = entry.get("verdict")
            if verdict == "pass":
                verdict_label = "could be human"
            elif verdict == "close":
                verdict_label = "hesitates"
            elif verdict == "fail":
                verdict_label = "obviously a bot"

    return {
        "race": {
            "finishes": race_finishes,
            "attempts": race_attempts,
            "multipleOfHuman": race_multiple,
        },
        "jumpCount": {
            "completed": completed,
            "total": TOTAL_DM3_ROUTES,
            "contextRouteCompleted": context_route_completed,
        },
        "speedometer": {
            "botSpeed": bot_speed,
            "humanSpeed": human_speed,
            "pct": speed_pct,
            "edge": edge_info,
        },
        "eyeTest": {"verdict": verdict, "label": verdict_label},
        "loaded": True,
        "error": None,
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def make_route_record(
    attempts=10,
    finishes=6,
    median_time_s=14.2,
    human_time_s=3.65,
    peak_speed_bot=None,
    peak_speed_human=None,
    edge_speed_bot=None,
    edge_speed_human=None,
    has_first_completion=False,
):
    """Build a minimal RouteRecords fixture."""
    records = {}
    if has_first_completion:
        records["first_completion"] = {
            "value": median_time_s,
            "units": "s",
            "run_id": "20260610T000000Z",
            "human_ref": {"value": human_time_s, "source": "census"},
        }
    if peak_speed_bot is not None:
        records["peak_speed"] = {
            "value": peak_speed_bot,
            "units": "qu/s",
            "run_id": "20260610T000001Z",
            "human_ref": (
                {"value": peak_speed_human, "source": "census"}
                if peak_speed_human is not None
                else None
            ),
        }
    if edge_speed_bot is not None:
        records["edge_speed"] = {
            "value": edge_speed_bot,
            "units": "qu/s",
            "run_id": "20260610T000002Z",
            "human_ref": (
                {"value": edge_speed_human, "source": "census"}
                if edge_speed_human is not None
                else None
            ),
        }
    return {
        "records": records,
        "aggregates": {
            "attempts": attempts,
            "finishes": finishes,
            "median_time_s": median_time_s if finishes > 0 else None,
            "human_time_s": human_time_s,
        },
    }


def make_empty_records():
    """Records fixture with all 11 dm3 routes present but no records."""
    routes = {r: make_route_record(attempts=0, finishes=0, median_time_s=None) for r in DM3_ROUTES_ORDERED}
    return {
        "schema": "komodobots.records.v1",
        "maps": {"dm3": {"routes": routes}},
    }


def make_records_with_sng_to_rl(
    attempts=10,
    finishes=6,
    median_time_s=35.1,  # ~×3.9 of 8.99
    peak_bot=327.0,
    peak_human=534.7,
    edge_bot=327.0,
    edge_human=528.6,
    has_first_completion=False,
):
    """Records fixture with sng_to_rl populated."""
    routes = {r: make_route_record(attempts=0, finishes=0, median_time_s=None) for r in DM3_ROUTES_ORDERED}
    routes["sng_to_rl"] = make_route_record(
        attempts=attempts,
        finishes=finishes,
        median_time_s=median_time_s,
        human_time_s=8.99,
        peak_speed_bot=peak_bot,
        peak_speed_human=peak_human,
        edge_speed_bot=edge_bot,
        edge_speed_human=edge_human,
        has_first_completion=has_first_completion,
    )
    return {
        "schema": "komodobots.records.v1",
        "maps": {"dm3": {"routes": routes}},
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestConstants(unittest.TestCase):
    def test_route_count(self):
        self.assertEqual(TOTAL_DM3_ROUTES, 11)

    def test_route_order(self):
        """sng_shortcut2 is rung 1 (easiest); sng_jumps is hardest."""
        self.assertEqual(DM3_ROUTES_ORDERED[0], "sng_shortcut2")
        self.assertEqual(DM3_ROUTES_ORDERED[-1], "sng_jumps")

    def test_all_expected_routes_present(self):
        expected = {
            "sng_shortcut2", "hilljump", "rl_to_ya", "ring_to_mega",
            "ra_jumps", "mega_to_rl", "rl_to_bridge", "sng_shortcut",
            "sng_to_rl", "mega_to_window", "sng_jumps",
        }
        self.assertEqual(set(DM3_ROUTES_ORDERED), expected)


class TestDeriveScoreboardNullRecords(unittest.TestCase):
    """Honest zeros when records is None (fetch failed)."""

    def setUp(self):
        self.ctx = _make_context()
        self.sb = derive_scoreboard(None, None, self.ctx)

    def test_not_loaded(self):
        self.assertFalse(self.sb["loaded"])

    def test_race_zeros(self):
        self.assertEqual(self.sb["race"]["finishes"], 0)
        self.assertEqual(self.sb["race"]["attempts"], 0)
        self.assertIsNone(self.sb["race"]["multipleOfHuman"])

    def test_jump_count_zeros(self):
        self.assertEqual(self.sb["jumpCount"]["completed"], 0)
        self.assertEqual(self.sb["jumpCount"]["total"], 11)

    def test_speedometer_nulls(self):
        self.assertIsNone(self.sb["speedometer"]["botSpeed"])
        self.assertIsNone(self.sb["speedometer"]["pct"])

    def test_eye_test_no_verdict(self):
        self.assertIsNone(self.sb["eyeTest"]["verdict"])
        self.assertEqual(self.sb["eyeTest"]["label"], "no verdict yet")


class TestDeriveScoreboardEmptyRecords(unittest.TestCase):
    """Honest zeros when records exist but all routes are empty."""

    def setUp(self):
        self.records = make_empty_records()
        self.ctx = _make_context(route="sng_to_rl")
        self.sb = derive_scoreboard(self.records, None, self.ctx)

    def test_loaded(self):
        self.assertTrue(self.sb["loaded"])

    def test_jump_count_zero(self):
        self.assertEqual(self.sb["jumpCount"]["completed"], 0)

    def test_context_route_not_completed(self):
        self.assertFalse(self.sb["jumpCount"]["contextRouteCompleted"])

    def test_race_zero_attempts(self):
        self.assertEqual(self.sb["race"]["attempts"], 0)
        self.assertEqual(self.sb["race"]["finishes"], 0)

    def test_speedometer_null(self):
        self.assertIsNone(self.sb["speedometer"]["pct"])

    def test_eye_test_no_route_verdict(self):
        self.assertIsNone(self.sb["eyeTest"]["verdict"])


class TestDeriveScoreboardRaceRouteContext(unittest.TestCase):
    """The Race — route context: single-route aggregates."""

    def setUp(self):
        # 6/10 finishes, median 35.1s / human 8.99s = ×3.9
        self.records = make_records_with_sng_to_rl(
            attempts=10, finishes=6, median_time_s=35.1
        )
        self.ctx = _make_context(route="sng_to_rl")
        self.sb = derive_scoreboard(self.records, None, self.ctx)

    def test_finishes(self):
        self.assertEqual(self.sb["race"]["finishes"], 6)

    def test_attempts(self):
        self.assertEqual(self.sb["race"]["attempts"], 10)

    def test_multiple_of_human(self):
        # 35.1 / 8.99 ≈ 3.904
        multiple = self.sb["race"]["multipleOfHuman"]
        self.assertIsNotNone(multiple)
        self.assertAlmostEqual(multiple, 35.1 / 8.99, places=3)

    def test_multiple_greater_than_one(self):
        """Bot is slower than human — multiple > 1."""
        self.assertGreater(self.sb["race"]["multipleOfHuman"], 1.0)


class TestDeriveScoreboardRaceNoFinishes(unittest.TestCase):
    """No finishes → multipleOfHuman is None."""

    def setUp(self):
        self.records = make_records_with_sng_to_rl(
            attempts=5, finishes=0, median_time_s=None
        )
        self.ctx = _make_context(route="sng_to_rl")
        self.sb = derive_scoreboard(self.records, None, self.ctx)

    def test_multiple_is_none(self):
        self.assertIsNone(self.sb["race"]["multipleOfHuman"])

    def test_finishes_zero(self):
        self.assertEqual(self.sb["race"]["finishes"], 0)


class TestDeriveScoreboardRaceOverallMode(unittest.TestCase):
    """The Race — overall mode (no route context): sum across all routes."""

    def setUp(self):
        # Two routes with data: sng_to_rl + sng_shortcut2
        routes = {r: make_route_record(attempts=0, finishes=0, median_time_s=None) for r in DM3_ROUTES_ORDERED}
        routes["sng_to_rl"] = make_route_record(
            attempts=10, finishes=6, median_time_s=35.1, human_time_s=8.99
        )
        routes["sng_shortcut2"] = make_route_record(
            attempts=5, finishes=3, median_time_s=14.2, human_time_s=3.65
        )
        self.records = {
            "schema": "komodobots.records.v1",
            "maps": {"dm3": {"routes": routes}},
        }
        self.ctx = _make_context()  # no route
        self.sb = derive_scoreboard(self.records, None, self.ctx)

    def test_total_finishes(self):
        self.assertEqual(self.sb["race"]["finishes"], 9)  # 6+3

    def test_total_attempts(self):
        self.assertEqual(self.sb["race"]["attempts"], 15)  # 10+5

    def test_overall_multiple_is_average(self):
        # average of 35.1/8.99 and 14.2/3.65
        m1 = 35.1 / 8.99
        m2 = 14.2 / 3.65
        expected = (m1 + m2) / 2
        multiple = self.sb["race"]["multipleOfHuman"]
        self.assertIsNotNone(multiple)
        self.assertAlmostEqual(multiple, expected, places=4)


class TestJumpCount(unittest.TestCase):
    """Jump Count — N/11 routes completed, ever."""

    def test_zero_completions(self):
        records = make_empty_records()
        ctx = _make_context(route="sng_to_rl")
        sb = derive_scoreboard(records, None, ctx)
        self.assertEqual(sb["jumpCount"]["completed"], 0)
        self.assertEqual(sb["jumpCount"]["total"], 11)
        self.assertFalse(sb["jumpCount"]["contextRouteCompleted"])

    def test_one_completion_context_route(self):
        records = make_records_with_sng_to_rl(has_first_completion=True)
        ctx = _make_context(route="sng_to_rl")
        sb = derive_scoreboard(records, None, ctx)
        self.assertEqual(sb["jumpCount"]["completed"], 1)
        self.assertTrue(sb["jumpCount"]["contextRouteCompleted"])

    def test_completion_other_route(self):
        """sng_shortcut2 completed; context is sng_to_rl."""
        routes = {r: make_route_record(attempts=0, finishes=0, median_time_s=None) for r in DM3_ROUTES_ORDERED}
        routes["sng_shortcut2"] = make_route_record(has_first_completion=True)
        records = {
            "schema": "komodobots.records.v1",
            "maps": {"dm3": {"routes": routes}},
        }
        ctx = _make_context(route="sng_to_rl")
        sb = derive_scoreboard(records, None, ctx)
        self.assertEqual(sb["jumpCount"]["completed"], 1)
        self.assertFalse(sb["jumpCount"]["contextRouteCompleted"])

    def test_multiple_completions(self):
        routes = {r: make_route_record(attempts=0, finishes=0, median_time_s=None) for r in DM3_ROUTES_ORDERED}
        for name in ["sng_shortcut2", "hilljump", "rl_to_ya"]:
            routes[name] = make_route_record(has_first_completion=True)
        records = {
            "schema": "komodobots.records.v1",
            "maps": {"dm3": {"routes": routes}},
        }
        ctx = _make_context()
        sb = derive_scoreboard(records, None, ctx)
        self.assertEqual(sb["jumpCount"]["completed"], 3)

    def test_context_route_none_sets_contextRouteCompleted_none(self):
        records = make_empty_records()
        ctx = _make_context()  # no route
        sb = derive_scoreboard(records, None, ctx)
        self.assertIsNone(sb["jumpCount"]["contextRouteCompleted"])

    def test_all_11_routes_counted(self):
        """All routes in DM3_ROUTES_ORDERED must be scannable."""
        routes = {r: make_route_record(has_first_completion=True) for r in DM3_ROUTES_ORDERED}
        records = {
            "schema": "komodobots.records.v1",
            "maps": {"dm3": {"routes": routes}},
        }
        ctx = _make_context()
        sb = derive_scoreboard(records, None, ctx)
        self.assertEqual(sb["jumpCount"]["completed"], 11)


class TestSpeedometer(unittest.TestCase):
    """Speedometer — bot speed as % of human on context route."""

    def test_no_route_context_no_speed(self):
        records = make_empty_records()
        ctx = _make_context()
        sb = derive_scoreboard(records, None, ctx)
        self.assertIsNone(sb["speedometer"]["pct"])

    def test_route_no_peak_record(self):
        records = make_empty_records()
        ctx = _make_context(route="sng_to_rl")
        sb = derive_scoreboard(records, None, ctx)
        self.assertIsNone(sb["speedometer"]["pct"])

    def test_speed_percentage(self):
        # Bot 327 qu/s / human 534.7 qu/s = ~61.1%
        records = make_records_with_sng_to_rl(peak_bot=327.0, peak_human=534.7)
        ctx = _make_context(route="sng_to_rl")
        sb = derive_scoreboard(records, None, ctx)
        pct = sb["speedometer"]["pct"]
        self.assertIsNotNone(pct)
        self.assertAlmostEqual(pct, 327.0 / 534.7 * 100, places=3)

    def test_speed_above_100_pct(self):
        """Bot faster than human reference → pct > 100."""
        records = make_records_with_sng_to_rl(peak_bot=600.0, peak_human=534.7)
        ctx = _make_context(route="sng_to_rl")
        sb = derive_scoreboard(records, None, ctx)
        self.assertGreater(sb["speedometer"]["pct"], 100.0)

    def test_bot_speed_stored(self):
        records = make_records_with_sng_to_rl(peak_bot=327.0, peak_human=534.7)
        ctx = _make_context(route="sng_to_rl")
        sb = derive_scoreboard(records, None, ctx)
        self.assertEqual(sb["speedometer"]["botSpeed"], 327.0)
        self.assertEqual(sb["speedometer"]["humanSpeed"], 534.7)

    def test_edge_speed_sub_line(self):
        # Edge: bot 327 / human 528.6 = ~61.9%
        records = make_records_with_sng_to_rl(
            edge_bot=327.0, edge_human=528.6
        )
        ctx = _make_context(route="sng_to_rl")
        sb = derive_scoreboard(records, None, ctx)
        edge = sb["speedometer"]["edge"]
        self.assertIsNotNone(edge)
        self.assertEqual(edge["botEdgeSpeed"], 327.0)
        self.assertEqual(edge["humanEdgeSpeed"], 528.6)
        self.assertAlmostEqual(edge["pct"], 327.0 / 528.6 * 100, places=3)

    def test_no_edge_record_edge_is_none(self):
        records = make_records_with_sng_to_rl(edge_bot=None, edge_human=None)
        ctx = _make_context(route="sng_to_rl")
        sb = derive_scoreboard(records, None, ctx)
        self.assertIsNone(sb["speedometer"]["edge"])

    def test_no_human_ref_pct_null(self):
        """peak_speed record with no human_ref → pct is None."""
        routes = {r: make_route_record(attempts=0, finishes=0, median_time_s=None) for r in DM3_ROUTES_ORDERED}
        routes["sng_to_rl"] = {
            "records": {
                "peak_speed": {
                    "value": 327.0,
                    "units": "qu/s",
                    "run_id": "20260610T000000Z",
                    "human_ref": None,
                }
            },
            "aggregates": {
                "attempts": 5,
                "finishes": 2,
                "median_time_s": 35.1,
                "human_time_s": 8.99,
            },
        }
        records = {
            "schema": "komodobots.records.v1",
            "maps": {"dm3": {"routes": routes}},
        }
        ctx = _make_context(route="sng_to_rl")
        sb = derive_scoreboard(records, None, ctx)
        self.assertIsNotNone(sb["speedometer"]["botSpeed"])
        self.assertIsNone(sb["speedometer"]["humanSpeed"])
        self.assertIsNone(sb["speedometer"]["pct"])


class TestEyeTest(unittest.TestCase):
    """Eye Test — latest human verdict from verdicts.json."""

    def _verdicts(self, route, verdict):
        return {
            "schema": "komodobots.verdicts.v1",
            "routes": {
                route: {
                    "verdict": verdict,
                    "note": "test",
                    "run_id": None,
                    "date": "2026-06-10",
                }
            },
        }

    def test_no_verdicts(self):
        records = make_empty_records()
        ctx = _make_context(route="sng_to_rl")
        sb = derive_scoreboard(records, None, ctx)
        self.assertIsNone(sb["eyeTest"]["verdict"])
        self.assertEqual(sb["eyeTest"]["label"], "no verdict yet")

    def test_fail_verdict_label(self):
        records = make_empty_records()
        ctx = _make_context(route="sng_to_rl")
        verdicts = self._verdicts("sng_to_rl", "fail")
        sb = derive_scoreboard(records, verdicts, ctx)
        self.assertEqual(sb["eyeTest"]["verdict"], "fail")
        self.assertEqual(sb["eyeTest"]["label"], "obviously a bot")

    def test_close_verdict_label(self):
        records = make_empty_records()
        ctx = _make_context(route="sng_to_rl")
        verdicts = self._verdicts("sng_to_rl", "close")
        sb = derive_scoreboard(records, verdicts, ctx)
        self.assertEqual(sb["eyeTest"]["verdict"], "close")
        self.assertEqual(sb["eyeTest"]["label"], "hesitates")

    def test_pass_verdict_label(self):
        records = make_empty_records()
        ctx = _make_context(route="sng_to_rl")
        verdicts = self._verdicts("sng_to_rl", "pass")
        sb = derive_scoreboard(records, verdicts, ctx)
        self.assertEqual(sb["eyeTest"]["verdict"], "pass")
        self.assertEqual(sb["eyeTest"]["label"], "could be human")

    def test_verdict_scoped_to_route(self):
        """Verdict for a different route doesn't leak into context route."""
        records = make_empty_records()
        ctx = _make_context(route="sng_to_rl")
        verdicts = self._verdicts("hilljump", "pass")  # different route
        sb = derive_scoreboard(records, verdicts, ctx)
        self.assertIsNone(sb["eyeTest"]["verdict"])

    def test_no_route_context_no_verdict(self):
        records = make_empty_records()
        ctx = _make_context()  # no route
        verdicts = self._verdicts("sng_to_rl", "fail")
        sb = derive_scoreboard(records, verdicts, ctx)
        self.assertIsNone(sb["eyeTest"]["verdict"])

    def test_seed_verdict_matches_spec(self):
        """The seed verdict file has verdict=fail for sng_to_rl (SPEC §7.4)."""
        records = make_empty_records()
        ctx = _make_context(route="sng_to_rl")
        seed_verdicts = {
            "schema": "komodobots.verdicts.v1",
            "routes": {
                "sng_to_rl": {
                    "verdict": "fail",
                    "note": "Seed verdict",
                    "run_id": None,
                    "date": "2026-06-10",
                }
            },
        }
        sb = derive_scoreboard(records, seed_verdicts, ctx)
        self.assertEqual(sb["eyeTest"]["verdict"], "fail")
        self.assertEqual(sb["eyeTest"]["label"], "obviously a bot")


class TestHonestZeros(unittest.TestCase):
    """Honest zeros: never hide a bad number, never show stale data as current."""

    def test_zero_route_count_not_11(self):
        """Empty records always shows 0/11, not null."""
        records = make_empty_records()
        ctx = _make_context()
        sb = derive_scoreboard(records, None, ctx)
        self.assertEqual(sb["jumpCount"]["completed"], 0)
        self.assertEqual(sb["jumpCount"]["total"], 11)

    def test_no_finishes_multiple_is_null_not_zero(self):
        """0 finishes → multipleOfHuman should be null, not 0."""
        records = make_records_with_sng_to_rl(finishes=0)
        ctx = _make_context(route="sng_to_rl")
        sb = derive_scoreboard(records, None, ctx)
        self.assertIsNone(sb["race"]["multipleOfHuman"])

    def test_no_peak_speed_pct_is_null_not_zero(self):
        records = make_empty_records()
        ctx = _make_context(route="sng_to_rl")
        sb = derive_scoreboard(records, None, ctx)
        self.assertIsNone(sb["speedometer"]["pct"])

    def test_loaded_flag(self):
        """loaded=True only after successful records fetch."""
        sb_null = derive_scoreboard(None, None, _make_context())
        self.assertFalse(sb_null["loaded"])
        sb_ok = derive_scoreboard(make_empty_records(), None, _make_context())
        self.assertTrue(sb_ok["loaded"])


class TestCurrentHonestStateSpec(unittest.TestCase):
    """Validate the honest current state from SPEC §7 table (2026-06).

    Today: 6/10 · ×3.9, Jump Count 0/11, ~70%/62%, fail verdict.
    These tests lock the logic against those current real values.
    """

    def setUp(self):
        # Matches the SPEC §7 honest current state.
        self.records = make_records_with_sng_to_rl(
            attempts=10,
            finishes=6,
            median_time_s=35.1,  # ×3.9 of 8.99
            peak_bot=327.0,      # ~70% of 534.7? Actually spec says ~70% active-mean
            peak_human=534.7,
            edge_bot=327.0,      # ~62% of 528.6
            edge_human=528.6,
        )
        self.verdicts = {
            "schema": "komodobots.verdicts.v1",
            "routes": {"sng_to_rl": {"verdict": "fail", "note": "", "run_id": None, "date": "2026-06-10"}},
        }
        self.ctx = _make_context(route="sng_to_rl")
        self.sb = derive_scoreboard(self.records, self.verdicts, self.ctx)

    def test_race_6_of_10(self):
        self.assertEqual(self.sb["race"]["finishes"], 6)
        self.assertEqual(self.sb["race"]["attempts"], 10)

    def test_race_multiple_approx_3_9(self):
        m = self.sb["race"]["multipleOfHuman"]
        self.assertIsNotNone(m)
        # 35.1 / 8.99 ≈ 3.904
        self.assertAlmostEqual(m, 35.1 / 8.99, places=2)
        self.assertGreater(m, 1.25)  # fails the v1 target

    def test_jump_count_zero(self):
        self.assertEqual(self.sb["jumpCount"]["completed"], 0)

    def test_eye_test_fail(self):
        self.assertEqual(self.sb["eyeTest"]["verdict"], "fail")
        self.assertEqual(self.sb["eyeTest"]["label"], "obviously a bot")

    def test_speedometer_below_80_pct_target(self):
        pct = self.sb["speedometer"]["pct"]
        self.assertIsNotNone(pct)
        self.assertLess(pct, 80.0)  # fails the v1 target

    def test_edge_below_100_pct(self):
        edge = self.sb["speedometer"]["edge"]
        self.assertIsNotNone(edge)
        self.assertLess(edge["pct"], 100.0)


if __name__ == "__main__":
    unittest.main()
