"""Records panel (LD-E4, issue #104): pure-logic contract tests.

Locks the data-contract rules that RecordsPanel.tsx implements in TypeScript:

  * selectRouteRecords: for a context route, returns the four record entries
    (fastest_time / first_completion / peak_speed / edge_speed) with their
    human_ref beside each; null when the record has not been set yet.
  * selectAllRoutesSummary: for the overall / no-context fallback, returns the
    per-map best table (one row per route, fastest_time value + human_time_s).
  * recordClickParams: given a record entry and context, produces the
    OpenDemoParams for the shell's openDemo action (demo_url, map, t=event_t_s,
    name="<map>·<route>·<kind>"); handles null event_t_s and demo_archived.
  * freshnessDot: determines whether a record is "new" since session start
    (value changed between two snapshots); returns true only when a non-null
    record was updated.
  * RECORD_KINDS_ORDERED: the four record kinds in display order.
  * humanRefLabel: renders human_ref.value as "{v:.1f} {units}" for display.
  * recordValueLabel: renders record.value as "{v:.2f} s" or "{v:.0f} qu/s".
  * noRecordsYet: returns True when all four records for a route are null.
  * routeHasRecords: opposite of noRecordsYet — at least one record is set.

All pure logic; no browser or TypeScript runtime required.
"""

import unittest

# ---------------------------------------------------------------------------
# Constants (mirrored from RecordsPanel.tsx)
# ---------------------------------------------------------------------------

RECORD_KINDS_ORDERED = [
    "fastest_time",
    "first_completion",
    "peak_speed",
    "edge_speed",
]

RECORD_UNITS = {
    "fastest_time": "s",
    "first_completion": "s",
    "peak_speed": "qu/s",
    "edge_speed": "qu/s",
}

# ---------------------------------------------------------------------------
# Helpers (mirrored logic from RecordsPanel.tsx)
# ---------------------------------------------------------------------------


def select_route_records(records_json: dict, map_name: str, route: str) -> dict | None:
    """Return the four record entries for a route, or None if route is absent.

    Returns a dict keyed by kind -> record_entry|None, and 'aggregates'.
    Returns None if route is absent or map is absent.
    Gracefully handles entries with a missing 'records' key.
    """
    routes = records_json.get("maps", {}).get(map_name, {}).get("routes", {})
    if not routes or route not in routes:
        return None
    entry = routes[route]
    return {
        "records": entry.get("records", {k: None for k in RECORD_KINDS_ORDERED}),
        "aggregates": entry.get("aggregates", {}),
    }


def select_all_routes_summary(records_json: dict, map_name: str) -> list[dict]:
    """Return per-route summary rows for the overall/no-context fallback.

    Each row: {route, fastest_time_value, human_time_s, has_any_record}.
    Rows are sorted by human_time_s ascending (shortest route first).
    """
    routes = records_json.get("maps", {}).get(map_name, {}).get("routes", {})
    rows = []
    for route_name, entry in routes.items():
        ft = entry["records"].get("fastest_time")
        agg = entry.get("aggregates", {})
        rows.append({
            "route": route_name,
            "fastest_time_value": ft["value"] if ft else None,
            "human_time_s": agg.get("human_time_s"),
            "has_any_record": any(
                entry["records"].get(k) is not None
                for k in RECORD_KINDS_ORDERED
            ),
        })
    rows.sort(key=lambda r: (r["human_time_s"] is None, r["human_time_s"] or 0))
    return rows


def record_click_params(record: dict, map_name: str, route: str, kind: str) -> dict:
    """Build OpenDemoParams for openDemo from a record entry.

    Returns {demo_url, map, t, route, name, demo_archived}.
    t is event_t_s (may be null).
    """
    return {
        "demo_url": record["demo_url"],
        "map": map_name,
        "t": record.get("event_t_s"),
        "route": route,
        "name": f"{map_name}·{route}·{kind}",
        "demo_archived": record.get("demo_archived"),
    }


def freshness_dot(prev_record: dict | None, curr_record: dict | None) -> bool:
    """Return True if a record's value changed between two snapshots.

    Only triggers when both snapshots are non-null (a new record appearing
    from nothing is not a "freshness" change — it is covered by "first record").
    """
    if prev_record is None or curr_record is None:
        return False
    return prev_record.get("value") != curr_record.get("value")


def human_ref_label(human_ref: dict | None) -> str | None:
    """Render human_ref.value as '{v:.1f} {units}' for display, or None."""
    if human_ref is None:
        return None
    v = human_ref.get("value")
    source = human_ref.get("source", "")
    if v is None:
        return None
    # Derive units from source field name (matches record units conventions)
    if "speed" in source.lower() or "qu" in source.lower():
        return f"{v:.0f} qu/s"
    return f"{v:.2f} s"


def record_value_label(value: float | None, units: str) -> str | None:
    """Render record.value as '{v:.2f} s' or '{v:.0f} qu/s'."""
    if value is None:
        return None
    if units == "s":
        return f"{value:.2f} s"
    return f"{value:.0f} qu/s"


def no_records_yet(route_entry: dict) -> bool:
    """Return True when all four records for a route are null."""
    return all(
        route_entry["records"].get(k) is None
        for k in RECORD_KINDS_ORDERED
    )


def route_has_records(route_entry: dict) -> bool:
    """Return True when at least one record is set."""
    return not no_records_yet(route_entry)


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

def make_record(
    value: float,
    units: str,
    run_id: str = "20260608T120000Z",
    demo_url: str | None = None,
    event_t_s: float | None = 10.0,
    demo_archived: bool | None = None,
    human_ref_value: float | None = None,
    human_ref_source: str = "duration_s",
) -> dict:
    """Build a minimal record entry for tests."""
    if demo_url is None:
        demo_url = f"/demos/files/non-games/lab/Komodobots/dm3/{run_id}.mvd"
    entry = {
        "value": value,
        "units": units,
        "run_id": run_id,
        "demo_url": demo_url,
        "demo_archived": demo_archived,
        "event_t_s": event_t_s,
        "set_at": run_id[:10].replace("T", "-")[:10],
    }
    if human_ref_value is not None:
        entry["human_ref"] = {
            "value": human_ref_value,
            "source": human_ref_source,
            "demo_url": "/demos/files/non-games/lab/Komodobots/human/dm3_sng_to_rl.qwd",
        }
    else:
        entry["human_ref"] = None
    return entry


def make_route_entry(
    *,
    fastest_time: dict | None = None,
    first_completion: dict | None = None,
    peak_speed: dict | None = None,
    edge_speed: dict | None = None,
    attempts: int = 0,
    finishes: int = 0,
    median_time_s: float | None = None,
    human_time_s: float = 8.99,
) -> dict:
    return {
        "records": {
            "fastest_time": fastest_time,
            "first_completion": first_completion,
            "peak_speed": peak_speed,
            "edge_speed": edge_speed,
        },
        "aggregates": {
            "attempts": attempts,
            "finishes": finishes,
            "median_time_s": median_time_s,
            "human_time_s": human_time_s,
        },
    }


def make_records_json(routes: dict, map_name: str = "dm3") -> dict:
    """Build a minimal records.json fixture."""
    return {
        "schema": "komodobots.records.v1",
        "maps": {
            map_name: {"routes": routes},
            "dm2": {"routes": {}},
            "frobodm2": {"routes": {}},
            "trick": {"routes": {}},
        },
        "provenance": {"runs_scanned": 0, "runs_scored": 0},
    }


# ---------------------------------------------------------------------------
# Tests: RECORD_KINDS_ORDERED constant
# ---------------------------------------------------------------------------

class TestRecordKindsOrdered(unittest.TestCase):
    """Locks the four-kind contract and their display order."""

    def test_exactly_four_kinds(self):
        self.assertEqual(len(RECORD_KINDS_ORDERED), 4)

    def test_all_expected_kinds_present(self):
        for k in ("fastest_time", "first_completion", "peak_speed", "edge_speed"):
            self.assertIn(k, RECORD_KINDS_ORDERED)

    def test_fastest_time_is_first(self):
        self.assertEqual(RECORD_KINDS_ORDERED[0], "fastest_time")

    def test_edge_speed_is_last(self):
        self.assertEqual(RECORD_KINDS_ORDERED[-1], "edge_speed")

    def test_units_assigned_to_all_kinds(self):
        for k in RECORD_KINDS_ORDERED:
            self.assertIn(k, RECORD_UNITS)
            self.assertIn(RECORD_UNITS[k], ("s", "qu/s"))

    def test_time_kinds_use_seconds(self):
        self.assertEqual(RECORD_UNITS["fastest_time"], "s")
        self.assertEqual(RECORD_UNITS["first_completion"], "s")

    def test_speed_kinds_use_qus(self):
        self.assertEqual(RECORD_UNITS["peak_speed"], "qu/s")
        self.assertEqual(RECORD_UNITS["edge_speed"], "qu/s")


# ---------------------------------------------------------------------------
# Tests: selectRouteRecords
# ---------------------------------------------------------------------------

class TestSelectRouteRecords(unittest.TestCase):
    """Records lookup for context route."""

    def setUp(self):
        ft = make_record(6.5, "s", human_ref_value=8.99, human_ref_source="duration_s")
        self.records_json = make_records_json({
            "sng_to_rl": make_route_entry(
                fastest_time=ft,
                attempts=5, finishes=3, human_time_s=8.99,
            ),
            "hilljump": make_route_entry(human_time_s=9.43),
        })

    def test_returns_none_for_absent_route(self):
        result = select_route_records(self.records_json, "dm3", "nonexistent_route")
        self.assertIsNone(result)

    def test_returns_none_for_absent_map(self):
        result = select_route_records(self.records_json, "dm2", "sng_to_rl")
        # dm2 has no routes in the fixture
        self.assertIsNone(result)

    def test_returns_all_four_record_keys(self):
        result = select_route_records(self.records_json, "dm3", "sng_to_rl")
        self.assertIsNotNone(result)
        for k in RECORD_KINDS_ORDERED:
            self.assertIn(k, result["records"])

    def test_fastest_time_value_correct(self):
        result = select_route_records(self.records_json, "dm3", "sng_to_rl")
        self.assertAlmostEqual(result["records"]["fastest_time"]["value"], 6.5)

    def test_unset_records_are_null(self):
        result = select_route_records(self.records_json, "dm3", "sng_to_rl")
        self.assertIsNone(result["records"]["first_completion"])
        self.assertIsNone(result["records"]["peak_speed"])
        self.assertIsNone(result["records"]["edge_speed"])

    def test_aggregates_included(self):
        result = select_route_records(self.records_json, "dm3", "sng_to_rl")
        self.assertEqual(result["aggregates"]["attempts"], 5)
        self.assertEqual(result["aggregates"]["finishes"], 3)

    def test_human_ref_beside_fastest_time(self):
        result = select_route_records(self.records_json, "dm3", "sng_to_rl")
        ft = result["records"]["fastest_time"]
        self.assertIsNotNone(ft["human_ref"])
        self.assertAlmostEqual(ft["human_ref"]["value"], 8.99)

    def test_hilljump_empty_records_still_all_four_keys(self):
        result = select_route_records(self.records_json, "dm3", "hilljump")
        self.assertIsNotNone(result)
        for k in RECORD_KINDS_ORDERED:
            self.assertIn(k, result["records"])
            self.assertIsNone(result["records"][k])


# ---------------------------------------------------------------------------
# Tests: selectAllRoutesSummary
# ---------------------------------------------------------------------------

class TestSelectAllRoutesSummary(unittest.TestCase):
    """Overall/no-context fallback table."""

    def setUp(self):
        ft_short = make_record(3.1, "s", run_id="20260608T120000Z")
        ft_long = make_record(9.8, "s", run_id="20260608T130000Z")
        self.records_json = make_records_json({
            "sng_shortcut2": make_route_entry(
                fastest_time=ft_short, attempts=10, finishes=5, human_time_s=3.65,
            ),
            "sng_to_rl": make_route_entry(
                fastest_time=ft_long, attempts=5, finishes=2, human_time_s=8.99,
            ),
            "mega_to_window": make_route_entry(human_time_s=3.8),  # no records
        })

    def test_returns_one_row_per_route(self):
        rows = select_all_routes_summary(self.records_json, "dm3")
        self.assertEqual(len(rows), 3)

    def test_rows_contain_expected_keys(self):
        rows = select_all_routes_summary(self.records_json, "dm3")
        for row in rows:
            self.assertIn("route", row)
            self.assertIn("fastest_time_value", row)
            self.assertIn("human_time_s", row)
            self.assertIn("has_any_record", row)

    def test_sorted_by_human_time_ascending(self):
        rows = select_all_routes_summary(self.records_json, "dm3")
        times = [r["human_time_s"] for r in rows]
        self.assertEqual(times, sorted(times))

    def test_shortest_first_is_sng_shortcut2(self):
        rows = select_all_routes_summary(self.records_json, "dm3")
        self.assertEqual(rows[0]["route"], "sng_shortcut2")

    def test_fastest_time_value_correct(self):
        rows = select_all_routes_summary(self.records_json, "dm3")
        by_route = {r["route"]: r for r in rows}
        self.assertAlmostEqual(by_route["sng_shortcut2"]["fastest_time_value"], 3.1)

    def test_no_record_route_has_null_fastest_time(self):
        rows = select_all_routes_summary(self.records_json, "dm3")
        by_route = {r["route"]: r for r in rows}
        self.assertIsNone(by_route["mega_to_window"]["fastest_time_value"])

    def test_has_any_record_true_when_fastest_time_set(self):
        rows = select_all_routes_summary(self.records_json, "dm3")
        by_route = {r["route"]: r for r in rows}
        self.assertTrue(by_route["sng_to_rl"]["has_any_record"])

    def test_has_any_record_false_when_all_null(self):
        rows = select_all_routes_summary(self.records_json, "dm3")
        by_route = {r["route"]: r for r in rows}
        self.assertFalse(by_route["mega_to_window"]["has_any_record"])

    def test_empty_routes_returns_empty_list(self):
        rows = select_all_routes_summary(self.records_json, "dm2")
        self.assertEqual(rows, [])


# ---------------------------------------------------------------------------
# Tests: recordClickParams
# ---------------------------------------------------------------------------

class TestRecordClickParams(unittest.TestCase):
    """OpenDemoParams construction from a record entry."""

    def test_demo_url_passed_through(self):
        rec = make_record(6.5, "s", demo_url="/demos/files/non-games/lab/Komodobots/dm3/RUN.mvd", event_t_s=11.0)
        params = record_click_params(rec, "dm3", "sng_to_rl", "fastest_time")
        self.assertEqual(params["demo_url"], "/demos/files/non-games/lab/Komodobots/dm3/RUN.mvd")

    def test_map_passed_through(self):
        rec = make_record(6.5, "s")
        params = record_click_params(rec, "dm3", "sng_to_rl", "fastest_time")
        self.assertEqual(params["map"], "dm3")

    def test_t_is_event_t_s(self):
        rec = make_record(6.5, "s", event_t_s=11.23)
        params = record_click_params(rec, "dm3", "sng_to_rl", "fastest_time")
        self.assertAlmostEqual(params["t"], 11.23)

    def test_t_is_none_when_event_t_s_is_null(self):
        rec = make_record(6.5, "s", event_t_s=None)
        params = record_click_params(rec, "dm3", "sng_to_rl", "fastest_time")
        self.assertIsNone(params["t"])

    def test_name_format(self):
        rec = make_record(6.5, "s")
        params = record_click_params(rec, "dm3", "sng_to_rl", "fastest_time")
        self.assertEqual(params["name"], "dm3·sng_to_rl·fastest_time")

    def test_route_included_for_context(self):
        rec = make_record(6.5, "s")
        params = record_click_params(rec, "dm3", "hilljump", "peak_speed")
        self.assertEqual(params["route"], "hilljump")

    def test_demo_archived_passed_through(self):
        rec = make_record(6.5, "s", demo_archived=True)
        params = record_click_params(rec, "dm3", "sng_to_rl", "fastest_time")
        self.assertIs(params["demo_archived"], True)

    def test_demo_archived_null_passed_through(self):
        rec = make_record(6.5, "s", demo_archived=None)
        params = record_click_params(rec, "dm3", "sng_to_rl", "fastest_time")
        self.assertIsNone(params["demo_archived"])

    def test_speed_record_click_params(self):
        rec = make_record(534.7, "qu/s", event_t_s=7.5)
        params = record_click_params(rec, "dm3", "sng_to_rl", "edge_speed")
        self.assertAlmostEqual(params["t"], 7.5)
        self.assertEqual(params["name"], "dm3·sng_to_rl·edge_speed")


# ---------------------------------------------------------------------------
# Tests: freshnessDot
# ---------------------------------------------------------------------------

class TestFreshnessDot(unittest.TestCase):
    """New-record highlight: value changed between two refetches."""

    def test_no_change_returns_false(self):
        rec = make_record(6.5, "s")
        self.assertFalse(freshness_dot(rec, rec))

    def test_value_changed_returns_true(self):
        prev = make_record(7.0, "s")
        curr = make_record(6.5, "s")
        self.assertTrue(freshness_dot(prev, curr))

    def test_prev_null_returns_false(self):
        curr = make_record(6.5, "s")
        self.assertFalse(freshness_dot(None, curr))

    def test_curr_null_returns_false(self):
        prev = make_record(6.5, "s")
        self.assertFalse(freshness_dot(prev, None))

    def test_both_null_returns_false(self):
        self.assertFalse(freshness_dot(None, None))

    def test_same_value_different_run_id_returns_false(self):
        # Two different runs but same record value (tie) — no freshness dot
        prev = make_record(6.5, "s", run_id="20260608T120000Z")
        curr = make_record(6.5, "s", run_id="20260609T120000Z")
        self.assertFalse(freshness_dot(prev, curr))


# ---------------------------------------------------------------------------
# Tests: humanRefLabel
# ---------------------------------------------------------------------------

class TestHumanRefLabel(unittest.TestCase):
    """Human reference display formatting."""

    def test_duration_formats_as_seconds(self):
        ref = {"value": 8.99, "source": "duration_s", "demo_url": "x"}
        self.assertEqual(human_ref_label(ref), "8.99 s")

    def test_speed_formats_as_qus(self):
        ref = {"value": 528.6, "source": "human_speed_at_edge", "demo_url": "x"}
        self.assertEqual(human_ref_label(ref), "529 qu/s")

    def test_peak_speed_formats_as_qus(self):
        ref = {"value": 534.7, "source": "peak_speed", "demo_url": "x"}
        self.assertIn("qu/s", human_ref_label(ref))

    def test_none_returns_none(self):
        self.assertIsNone(human_ref_label(None))

    def test_value_none_returns_none(self):
        ref = {"value": None, "source": "duration_s", "demo_url": "x"}
        self.assertIsNone(human_ref_label(ref))


# ---------------------------------------------------------------------------
# Tests: recordValueLabel
# ---------------------------------------------------------------------------

class TestRecordValueLabel(unittest.TestCase):
    """Record value display formatting."""

    def test_seconds_two_decimal_places(self):
        self.assertEqual(record_value_label(6.5, "s"), "6.50 s")

    def test_seconds_rounds(self):
        self.assertEqual(record_value_label(8.991, "s"), "8.99 s")

    def test_qus_zero_decimal(self):
        self.assertEqual(record_value_label(534.7, "qu/s"), "535 qu/s")

    def test_none_value_returns_none(self):
        self.assertIsNone(record_value_label(None, "s"))


# ---------------------------------------------------------------------------
# Tests: noRecordsYet / routeHasRecords
# ---------------------------------------------------------------------------

class TestNoRecordsYet(unittest.TestCase):
    """Honest empty state helpers."""

    def _make_empty_entry(self):
        return make_route_entry()

    def _make_partial_entry(self):
        return make_route_entry(fastest_time=make_record(6.5, "s"))

    def _make_full_entry(self):
        return make_route_entry(
            fastest_time=make_record(6.5, "s"),
            first_completion=make_record(6.5, "s"),
            peak_speed=make_record(534.7, "qu/s"),
            edge_speed=make_record(528.6, "qu/s"),
        )

    def test_no_records_yet_when_all_null(self):
        self.assertTrue(no_records_yet(self._make_empty_entry()))

    def test_not_no_records_yet_when_one_set(self):
        self.assertFalse(no_records_yet(self._make_partial_entry()))

    def test_not_no_records_yet_when_all_set(self):
        self.assertFalse(no_records_yet(self._make_full_entry()))

    def test_route_has_records_false_when_all_null(self):
        self.assertFalse(route_has_records(self._make_empty_entry()))

    def test_route_has_records_true_when_one_set(self):
        self.assertTrue(route_has_records(self._make_partial_entry()))

    def test_route_has_records_true_when_all_set(self):
        self.assertTrue(route_has_records(self._make_full_entry()))


# ---------------------------------------------------------------------------
# Tests: integration — context-sensitive rendering contract
# ---------------------------------------------------------------------------

class TestContextSensitiveRendering(unittest.TestCase):
    """Exercises the full context-sensitive rendering path end-to-end.

    The RecordsPanel component chooses between:
      - route-context mode: single route's four records + human refs
      - overall/fallback mode: per-route best table

    These tests lock the selection logic used for each mode.
    """

    def setUp(self):
        ft_sng = make_record(6.5, "s", human_ref_value=8.99, human_ref_source="duration_s")
        ps_sng = make_record(480.0, "qu/s", human_ref_value=534.7, human_ref_source="peak_speed")
        es_sng = make_record(510.0, "qu/s", human_ref_value=528.6, human_ref_source="human_speed_at_edge")
        self.records_json = make_records_json({
            "sng_to_rl": make_route_entry(
                fastest_time=ft_sng, peak_speed=ps_sng, edge_speed=es_sng,
                attempts=10, finishes=6, median_time_s=7.2, human_time_s=8.99,
            ),
            "hilljump": make_route_entry(
                fastest_time=make_record(8.0, "s"),
                attempts=3, finishes=1, human_time_s=9.43,
            ),
            "mega_to_window": make_route_entry(human_time_s=3.8),
        })

    def test_route_context_returns_all_four_records(self):
        result = select_route_records(self.records_json, "dm3", "sng_to_rl")
        self.assertIsNotNone(result)
        for k in RECORD_KINDS_ORDERED:
            self.assertIn(k, result["records"])

    def test_route_context_first_completion_is_null_when_not_set(self):
        result = select_route_records(self.records_json, "dm3", "sng_to_rl")
        self.assertIsNone(result["records"]["first_completion"])

    def test_route_context_human_refs_available_for_set_records(self):
        result = select_route_records(self.records_json, "dm3", "sng_to_rl")
        self.assertIsNotNone(result["records"]["fastest_time"]["human_ref"])
        self.assertIsNotNone(result["records"]["peak_speed"]["human_ref"])
        self.assertIsNotNone(result["records"]["edge_speed"]["human_ref"])

    def test_overall_mode_all_routes_present(self):
        rows = select_all_routes_summary(self.records_json, "dm3")
        route_names = {r["route"] for r in rows}
        self.assertEqual(route_names, {"sng_to_rl", "hilljump", "mega_to_window"})

    def test_click_through_sng_fastest_time(self):
        result = select_route_records(self.records_json, "dm3", "sng_to_rl")
        ft = result["records"]["fastest_time"]
        params = record_click_params(ft, "dm3", "sng_to_rl", "fastest_time")
        self.assertIn("/dm3/", params["demo_url"])
        self.assertAlmostEqual(params["t"], 10.0)  # fixture event_t_s

    def test_click_through_null_event_t_s(self):
        # first_completion is null — no click through (handled by UI)
        # but peak_speed has event_t_s
        result = select_route_records(self.records_json, "dm3", "sng_to_rl")
        ps = result["records"]["peak_speed"]
        params = record_click_params(ps, "dm3", "sng_to_rl", "peak_speed")
        # event_t_s is 10.0 from the fixture
        self.assertIsNotNone(params["t"])

    def test_no_context_route_shows_overall(self):
        # Overall mode is triggered when context route is None.
        # select_route_records returns None for absent routes.
        result = select_route_records(self.records_json, "dm3", None)  # type: ignore[arg-type]
        self.assertIsNone(result)  # UI falls back to overall summary

    def test_new_record_freshness_detected(self):
        # Simulate a refetch that improved fastest_time
        prev_ft = make_record(7.0, "s")
        curr_ft = make_record(6.5, "s")
        self.assertTrue(freshness_dot(prev_ft, curr_ft))

    def test_no_freshness_when_same_value_after_refetch(self):
        ft = make_record(6.5, "s")
        self.assertFalse(freshness_dot(ft, ft))


# ---------------------------------------------------------------------------
# Tests: edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):
    """Division-by-zero / no-data / missing-field safety."""

    def test_select_route_records_missing_records_key_not_crash(self):
        # Malformed entry: records key missing
        rj = make_records_json({"sng_to_rl": {"aggregates": {}}})
        result = select_route_records(rj, "dm3", "sng_to_rl")
        # Should not raise; returns the entry even if records key missing
        self.assertIsNotNone(result)

    def test_click_params_no_event_t_s_key(self):
        # Record without event_t_s key at all (not the same as None)
        rec = {"value": 6.5, "units": "s", "demo_url": "/x.mvd", "run_id": "R"}
        params = record_click_params(rec, "dm3", "sng_to_rl", "fastest_time")
        self.assertIsNone(params["t"])

    def test_human_ref_label_with_qu_in_source(self):
        ref = {"value": 100.0, "source": "active_mean_speed_qu", "demo_url": "x"}
        label = human_ref_label(ref)
        self.assertIn("qu/s", label)

    def test_select_all_routes_empty_map(self):
        rj = {"schema": "komodobots.records.v1",
              "maps": {"dm3": {"routes": {}}},
              "provenance": {}}
        rows = select_all_routes_summary(rj, "dm3")
        self.assertEqual(rows, [])

    def test_freshness_dot_same_zero(self):
        prev = make_record(0.0, "s")
        curr = make_record(0.0, "s")
        self.assertFalse(freshness_dot(prev, curr))

    def test_record_value_label_integer_seconds(self):
        self.assertEqual(record_value_label(10.0, "s"), "10.00 s")

    def test_record_value_label_large_speed(self):
        label = record_value_label(1000.0, "qu/s")
        self.assertEqual(label, "1000 qu/s")


if __name__ == "__main__":
    unittest.main()
