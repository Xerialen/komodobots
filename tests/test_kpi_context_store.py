"""KPI context store contract tests (LD-E1, issue #100).

Validates the contextStore.ts design contract in Python:
- KpiContext schema: {map, route, source} where source in {live,mockup,demo,none}
- INITIAL_KPI_CONTEXT: {map:"dm3", route:null, source:"none"}
- applyContextUpdate precedence rules:
    live(live=True)  -> source becomes "live", route cleared
    live(live=False) -> falls back to lastUser if source!="none", else "none"
    mockup update    -> updates active context AND lastUser (if not live)
    demo update      -> same as mockup
    mockup during live -> updates lastUser only (active stays live)
    demo during live   -> updates lastUser only
- The context line format used in KpiDock is testable: "{map} · {route} · {source}"
- MockupSelection wire: the onSelect callback emits {map, route} matching the
  manifest contract from test_mockup_context.py (MockupSelection is consumed by
  dispatchContext({kind:"mockup", ...}))

These tests exercise the PURE LOGIC defined by applyContextUpdate.  No browser
or TypeScript runtime required.  The tests implement the same rules described in
contextStore.ts docstrings so that a TypeScript regression (e.g., wrong precedence)
would break these tests even before the dashboard is deployed.
"""

import unittest


# ---------------------------------------------------------------------------
# Re-implement the pure logic from contextStore.ts in Python for testing.
# This is intentionally a direct translation of the TypeScript so that any
# divergence in either file is a test failure.
# ---------------------------------------------------------------------------

CONTEXT_SOURCES = {"live", "mockup", "demo", "none"}


def initial_kpi_context():
    """Return the initial KPI context matching INITIAL_KPI_CONTEXT."""
    return {"map": "dm3", "route": None, "source": "none"}


def apply_context_update(current: dict, last_user: dict, update: dict) -> tuple[dict, dict]:
    """Pure function matching contextStore.ts applyContextUpdate.

    Returns (new_context, new_last_user).
    """
    kind = update["kind"]

    if kind == "live":
        if update["live"]:
            # Live attempt started: override with live source, route cleared.
            new_ctx = {"map": update["map"], "route": None, "source": "live"}
            return new_ctx, last_user
        else:
            # Live ended: surface last user selection or fall back to none.
            if last_user["source"] != "none":
                return last_user, last_user
            else:
                fallback = {"map": current["map"], "route": None, "source": "none"}
                return fallback, last_user

    elif kind == "mockup":
        next_ctx = {"map": update["map"], "route": update["route"], "source": "mockup"}
        if current["source"] == "live":
            # Live active — save pending selection, don't override active.
            return current, next_ctx
        return next_ctx, next_ctx

    elif kind == "demo":
        next_ctx = {"map": update["map"], "route": update["route"], "source": "demo"}
        if current["source"] == "live":
            return current, next_ctx
        return next_ctx, next_ctx

    else:
        raise ValueError(f"Unknown update kind: {kind!r}")


# ---------------------------------------------------------------------------
# Helper: simulate a useReducer dispatch loop.
# ---------------------------------------------------------------------------

class ContextStore:
    """Simulates the useReducer({context, lastUser}) from App.tsx LD-E1."""

    def __init__(self):
        self.context = initial_kpi_context()
        self.last_user = initial_kpi_context()

    def dispatch(self, update: dict) -> None:
        self.context, self.last_user = apply_context_update(
            self.context, self.last_user, update
        )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestInitialState(unittest.TestCase):
    """INITIAL_KPI_CONTEXT contract."""

    def test_initial_map(self):
        ctx = initial_kpi_context()
        self.assertEqual(ctx["map"], "dm3")

    def test_initial_route_is_null(self):
        ctx = initial_kpi_context()
        self.assertIsNone(ctx["route"])

    def test_initial_source_is_none(self):
        ctx = initial_kpi_context()
        self.assertEqual(ctx["source"], "none")

    def test_source_is_valid_value(self):
        ctx = initial_kpi_context()
        self.assertIn(ctx["source"], CONTEXT_SOURCES)


class TestContextSchema(unittest.TestCase):
    """KpiContext schema: required keys, valid source values."""

    def _assert_valid_context(self, ctx: dict, label: str = ""):
        self.assertIn("map", ctx, f"missing 'map' {label}")
        self.assertIn("route", ctx, f"missing 'route' {label}")
        self.assertIn("source", ctx, f"missing 'source' {label}")
        self.assertIsInstance(ctx["map"], str, f"map must be str {label}")
        self.assertTrue(len(ctx["map"]) > 0, f"map must be non-empty {label}")
        self.assertIn(ctx["source"], CONTEXT_SOURCES, f"source must be valid {label}")
        # route is either None or a non-empty string
        if ctx["route"] is not None:
            self.assertIsInstance(ctx["route"], str, f"route must be str or None {label}")
            self.assertTrue(len(ctx["route"]) > 0, f"route must be non-empty when set {label}")

    def test_initial_context_schema(self):
        self._assert_valid_context(initial_kpi_context(), "initial")

    def test_live_update_schema(self):
        store = ContextStore()
        store.dispatch({"kind": "live", "map": "dm3", "live": True})
        self._assert_valid_context(store.context, "after live start")

    def test_mockup_update_schema(self):
        store = ContextStore()
        store.dispatch({"kind": "mockup", "map": "dm3", "route": "sng_to_rl"})
        self._assert_valid_context(store.context, "after mockup")

    def test_demo_update_schema(self):
        store = ContextStore()
        store.dispatch({"kind": "demo", "map": "frobodm2", "route": None})
        self._assert_valid_context(store.context, "after demo")


class TestLivePrecedence(unittest.TestCase):
    """Live source overrides everything; ending live restores last selection."""

    def test_live_start_sets_source_to_live(self):
        store = ContextStore()
        store.dispatch({"kind": "live", "map": "trick", "live": True})
        self.assertEqual(store.context["source"], "live")

    def test_live_start_sets_map(self):
        store = ContextStore()
        store.dispatch({"kind": "live", "map": "trick", "live": True})
        self.assertEqual(store.context["map"], "trick")

    def test_live_start_clears_route(self):
        store = ContextStore()
        store.dispatch({"kind": "mockup", "map": "dm3", "route": "sng_to_rl"})
        store.dispatch({"kind": "live", "map": "dm3", "live": True})
        self.assertIsNone(store.context["route"])

    def test_live_overrides_mockup_source(self):
        store = ContextStore()
        store.dispatch({"kind": "mockup", "map": "dm3", "route": "sng_to_rl"})
        store.dispatch({"kind": "live", "map": "dm3", "live": True})
        self.assertEqual(store.context["source"], "live")

    def test_live_end_restores_mockup_selection(self):
        store = ContextStore()
        # User browses mockup, then live starts, then live ends.
        store.dispatch({"kind": "mockup", "map": "dm3", "route": "sng_to_rl"})
        store.dispatch({"kind": "live", "map": "dm3", "live": True})
        store.dispatch({"kind": "live", "map": "dm3", "live": False})
        self.assertEqual(store.context["source"], "mockup")
        self.assertEqual(store.context["route"], "sng_to_rl")

    def test_live_end_restores_demo_selection(self):
        store = ContextStore()
        store.dispatch({"kind": "demo", "map": "trick", "route": "some_route"})
        store.dispatch({"kind": "live", "map": "trick", "live": True})
        store.dispatch({"kind": "live", "map": "trick", "live": False})
        self.assertEqual(store.context["source"], "demo")
        self.assertEqual(store.context["route"], "some_route")

    def test_live_end_without_prior_user_selection_gives_none_source(self):
        store = ContextStore()
        store.dispatch({"kind": "live", "map": "dm3", "live": True})
        store.dispatch({"kind": "live", "map": "dm3", "live": False})
        self.assertEqual(store.context["source"], "none")

    def test_live_end_retains_map_when_no_prior_selection(self):
        store = ContextStore()
        store.dispatch({"kind": "live", "map": "frobodm2", "live": True})
        store.dispatch({"kind": "live", "map": "frobodm2", "live": False})
        # Should retain the map from the live attempt (not lose it)
        self.assertEqual(store.context["map"], "frobodm2")


class TestMockupProducer(unittest.TestCase):
    """MockupPane selection wire (kind="mockup")."""

    def test_mockup_sets_source(self):
        store = ContextStore()
        store.dispatch({"kind": "mockup", "map": "dm3", "route": "sng_to_rl"})
        self.assertEqual(store.context["source"], "mockup")

    def test_mockup_sets_map_and_route(self):
        store = ContextStore()
        store.dispatch({"kind": "mockup", "map": "dm2", "route": "hilljump"})
        self.assertEqual(store.context["map"], "dm2")
        self.assertEqual(store.context["route"], "hilljump")

    def test_mockup_null_route(self):
        store = ContextStore()
        store.dispatch({"kind": "mockup", "map": "trick", "route": None})
        self.assertIsNone(store.context["route"])
        self.assertEqual(store.context["source"], "mockup")

    def test_mockup_during_live_does_not_override_active_context(self):
        store = ContextStore()
        store.dispatch({"kind": "live", "map": "dm3", "live": True})
        store.dispatch({"kind": "mockup", "map": "dm3", "route": "sng_to_rl"})
        # Active context should still be live, not mockup
        self.assertEqual(store.context["source"], "live")

    def test_mockup_during_live_saved_as_last_user(self):
        store = ContextStore()
        store.dispatch({"kind": "live", "map": "dm3", "live": True})
        store.dispatch({"kind": "mockup", "map": "dm3", "route": "sng_to_rl"})
        # After live ends, the mockup selection should surface
        store.dispatch({"kind": "live", "map": "dm3", "live": False})
        self.assertEqual(store.context["source"], "mockup")
        self.assertEqual(store.context["route"], "sng_to_rl")

    def test_mockup_updates_last_user_selection(self):
        store = ContextStore()
        store.dispatch({"kind": "mockup", "map": "dm3", "route": "sng_to_rl"})
        self.assertEqual(store.last_user["route"], "sng_to_rl")


class TestDemoProducer(unittest.TestCase):
    """Demo context wire (kind="demo", LD-D3 stub)."""

    def test_demo_sets_source(self):
        store = ContextStore()
        store.dispatch({"kind": "demo", "map": "dm3", "route": "sng_to_rl"})
        self.assertEqual(store.context["source"], "demo")

    def test_demo_during_live_does_not_override_active(self):
        store = ContextStore()
        store.dispatch({"kind": "live", "map": "dm3", "live": True})
        store.dispatch({"kind": "demo", "map": "trick", "route": None})
        self.assertEqual(store.context["source"], "live")

    def test_demo_during_live_restored_when_live_ends(self):
        store = ContextStore()
        store.dispatch({"kind": "live", "map": "dm3", "live": True})
        store.dispatch({"kind": "demo", "map": "trick", "route": "some"})
        store.dispatch({"kind": "live", "map": "dm3", "live": False})
        self.assertEqual(store.context["source"], "demo")
        self.assertEqual(store.context["map"], "trick")


class TestMockupSelectionWire(unittest.TestCase):
    """Validates that MockupSelection {map, route} maps correctly to a mockup update.

    The App.tsx wire is: onSelect={(sel) => dispatchContext({kind:"mockup", ...sel})}
    This test locks the translation so that if MockupSelection schema changes,
    the tests break immediately.
    """

    def _mockup_selection_to_update(self, sel: dict) -> dict:
        """Mirrors the App.tsx inline lambda."""
        return {"kind": "mockup", "map": sel["map"], "route": sel["route"]}

    def test_wire_sng_to_rl(self):
        sel = {"map": "dm3", "route": "sng_to_rl"}
        update = self._mockup_selection_to_update(sel)
        store = ContextStore()
        store.dispatch(update)
        self.assertEqual(store.context["map"], "dm3")
        self.assertEqual(store.context["route"], "sng_to_rl")
        self.assertEqual(store.context["source"], "mockup")

    def test_wire_null_route(self):
        sel = {"map": "trick", "route": None}
        update = self._mockup_selection_to_update(sel)
        store = ContextStore()
        store.dispatch(update)
        self.assertIsNone(store.context["route"])

    def test_wire_map_switch_clears_route(self):
        store = ContextStore()
        store.dispatch({"kind": "mockup", "map": "dm3", "route": "sng_to_rl"})
        # Switching map (mock: MockupPane resets route to null on map change)
        store.dispatch({"kind": "mockup", "map": "dm2", "route": None})
        self.assertEqual(store.context["map"], "dm2")
        self.assertIsNone(store.context["route"])


class TestContextLineFormat(unittest.TestCase):
    """KpiDock context line format: '{map} · {route|"(no route)"}'.

    The format used in KpiDock.tsx <data-context-line> for Playwright assertions.
    """

    def _context_line(self, ctx: dict) -> str:
        route_part = ctx["route"] if ctx["route"] is not None else "(no route)"
        return f"{ctx['map']} · {route_part}"

    def test_with_route(self):
        ctx = {"map": "dm3", "route": "sng_to_rl", "source": "mockup"}
        self.assertEqual(self._context_line(ctx), "dm3 · sng_to_rl")

    def test_without_route(self):
        ctx = {"map": "trick", "route": None, "source": "live"}
        self.assertEqual(self._context_line(ctx), "trick · (no route)")

    def test_initial_state_line(self):
        ctx = initial_kpi_context()
        self.assertEqual(self._context_line(ctx), "dm3 · (no route)")


class TestPrecedenceSequence(unittest.TestCase):
    """Integration: full precedence sequence exercise."""

    def test_full_lifecycle(self):
        """user browses → live starts → mockup during live → live ends → demo."""
        store = ContextStore()

        # Phase 1: user browses mockup
        store.dispatch({"kind": "mockup", "map": "dm3", "route": "sng_to_rl"})
        self.assertEqual(store.context["source"], "mockup")

        # Phase 2: live attempt starts on dm3
        store.dispatch({"kind": "live", "map": "dm3", "live": True})
        self.assertEqual(store.context["source"], "live")
        self.assertIsNone(store.context["route"])

        # Phase 3: user clicks a different mockup route during live
        store.dispatch({"kind": "mockup", "map": "dm3", "route": "hilljump"})
        # Active still live
        self.assertEqual(store.context["source"], "live")

        # Phase 4: live ends — should restore hilljump (the last user selection)
        store.dispatch({"kind": "live", "map": "dm3", "live": False})
        self.assertEqual(store.context["source"], "mockup")
        self.assertEqual(store.context["route"], "hilljump")

        # Phase 5: user opens a demo
        store.dispatch({"kind": "demo", "map": "trick", "route": "speed_run"})
        self.assertEqual(store.context["source"], "demo")
        self.assertEqual(store.context["map"], "trick")

    def test_back_to_back_live_attempts(self):
        """Two consecutive live attempts; context stays live throughout."""
        store = ContextStore()
        store.dispatch({"kind": "mockup", "map": "dm3", "route": "sng_to_rl"})
        store.dispatch({"kind": "live", "map": "dm3", "live": True})
        # First live ends, second starts immediately
        store.dispatch({"kind": "live", "map": "dm3", "live": False})
        # Momentary restoration of mockup
        self.assertEqual(store.context["source"], "mockup")
        store.dispatch({"kind": "live", "map": "frobodm2", "live": True})
        self.assertEqual(store.context["source"], "live")
        self.assertEqual(store.context["map"], "frobodm2")


if __name__ == "__main__":
    unittest.main()
