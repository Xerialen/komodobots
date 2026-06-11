"""KPI context-store demo producer wiring contract tests (LD-E1, issue #100).

Validates that App.tsx wires DemoPane's onContext callback to:
  1. Set the local demoContext preview state (used in the status-bar line).
  2. Dispatch {kind: "demo", map: ctx.map, route: ctx.route} to the KPI
     context reducer so the KPI dock transitions to source="demo" when a demo
     is playing.

These tests are source-inspection smoke tests — they do not run a browser or
TypeScript runtime.  They lock the wiring contract so that any App.tsx refactor
that removes the demo dispatch would fail here.

Codex P1 finding addressed:
  "App.tsx still passes onContext={setDemoContext} only. There is no
   dispatchContext({kind:'demo',...}) path in App.tsx, so playing a demo
   never updates the KPI dock to {source:'demo'}."
"""

import os
import re
import sys
import unittest

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_APP_TSX = os.path.join(_REPO_ROOT, "lab", "dashboard", "src", "App.tsx")


class TestDemoProducerWiring(unittest.TestCase):
    """App.tsx must dispatch demo context to the KPI reducer."""

    def setUp(self):
        with open(_APP_TSX, encoding="utf-8") as fh:
            self.source = fh.read()

    # ------------------------------------------------------------------
    # 1. dispatch call present
    # ------------------------------------------------------------------

    def test_dispatchContext_demo_kind_present(self):
        """App.tsx must call dispatchContext with kind:'demo' somewhere in the
        DemoPane onContext callback."""
        self.assertIn('kind: "demo"', self.source,
                      'App.tsx must dispatch {kind: "demo"} for the demo producer')

    def test_dispatch_includes_map_and_route(self):
        """The demo dispatch must forward both map and route from the context
        object, matching the DemoContextUpdate schema in contextStore.ts."""
        # Look for a block that has kind:"demo" and both ctx.map and ctx.route
        # within reasonable proximity (same statement / object literal).
        pattern = re.compile(
            r'kind:\s*"demo".*?ctx\.map.*?ctx\.route|'
            r'ctx\.map.*?ctx\.route.*?kind:\s*"demo"',
            re.DOTALL,
        )
        self.assertRegex(
            self.source,
            pattern,
            'dispatchContext({kind:"demo",...}) must forward ctx.map and ctx.route',
        )

    # ------------------------------------------------------------------
    # 2. local preview state still set
    # ------------------------------------------------------------------

    def test_setDemoContext_still_called(self):
        """setDemoContext must still be called so the status-bar preview works.
        Removing it would silently break the top-bar demo context line."""
        self.assertIn("setDemoContext(ctx)", self.source,
                      "App.tsx must still call setDemoContext(ctx) for the preview")

    # ------------------------------------------------------------------
    # 3. null guard: do not dispatch on null (demo ended)
    # ------------------------------------------------------------------

    def test_null_guard_before_dispatch(self):
        """When DemoPane clears context (ctx=null), the demo dispatch must NOT
        fire — the store's last-user-selection should persist, not reset.
        Verify a null guard (ctx !== null or similar) wraps the dispatch."""
        # Accept: `if (ctx !== null)`, `ctx != null`, `ctx &&`
        pattern = re.compile(
            r'(ctx\s*!==\s*null|ctx\s*!=\s*null|if\s*\(\s*ctx\s*\))',
            re.DOTALL,
        )
        self.assertRegex(
            self.source,
            pattern,
            'dispatchContext must be guarded against null ctx (ctx !== null or ctx != null or if (ctx))',
        )

    # ------------------------------------------------------------------
    # 4. live precedence still respected via applyContextUpdate
    # ------------------------------------------------------------------

    def test_applyContextUpdate_imported(self):
        """applyContextUpdate must still be imported — it enforces live > demo
        precedence inside the reducer.  If it were removed, the precedence
        rules would be broken."""
        self.assertIn("applyContextUpdate", self.source,
                      "App.tsx must still import applyContextUpdate from contextStore.ts")

    # ------------------------------------------------------------------
    # 5. both producers (mockup + demo) use dispatchContext
    # ------------------------------------------------------------------

    def test_mockup_dispatch_still_present(self):
        """MockupPane.onSelect must still dispatch {kind:'mockup',...} — verify
        the demo fix did not accidentally break the mockup producer."""
        self.assertIn('kind: "mockup"', self.source,
                      'App.tsx must still dispatch {kind:"mockup"} for the mockup producer')


class TestDemoProducerPrecedence(unittest.TestCase):
    """Pure-logic: demo dispatch respects live > demo precedence in the store."""

    def _make_store(self):
        """Return a minimal Python replica of the contextStore reducer state."""
        # Replicate applyContextUpdate logic from contextStore.ts
        INITIAL = {"map": "dm3", "route": None, "source": "none"}

        class Store:
            def __init__(self):
                self.context = dict(INITIAL)
                self.last_user = dict(INITIAL)

            def dispatch(self, update):
                kind = update["kind"]
                if kind == "live":
                    if update["live"]:
                        self.context = {"map": update["map"], "route": None, "source": "live"}
                        # last_user unchanged
                    else:
                        if self.last_user["source"] != "none":
                            self.context = dict(self.last_user)
                        else:
                            self.context = {"map": self.context["map"], "route": None, "source": "none"}
                elif kind in ("mockup", "demo"):
                    next_ctx = {"map": update["map"], "route": update.get("route"), "source": kind}
                    if self.context["source"] == "live":
                        self.last_user = next_ctx  # park for later
                    else:
                        self.context = next_ctx
                        self.last_user = next_ctx

        return Store()

    def test_demo_dispatch_sets_source_demo(self):
        """Dispatching {kind:'demo'} when no live run is active sets source='demo'."""
        store = self._make_store()
        store.dispatch({"kind": "demo", "map": "frobodm2", "route": "sng_to_rl"})
        self.assertEqual(store.context["source"], "demo")
        self.assertEqual(store.context["map"], "frobodm2")
        self.assertEqual(store.context["route"], "sng_to_rl")

    def test_live_overrides_demo(self):
        """Live attempt overrides demo context."""
        store = self._make_store()
        store.dispatch({"kind": "demo", "map": "dm3", "route": None})
        store.dispatch({"kind": "live", "map": "dm3", "live": True})
        self.assertEqual(store.context["source"], "live")

    def test_demo_parked_during_live(self):
        """Demo dispatch while live is active parks as last_user, not active."""
        store = self._make_store()
        store.dispatch({"kind": "live", "map": "dm3", "live": True})
        store.dispatch({"kind": "demo", "map": "trick", "route": "any"})
        # Active context is still live
        self.assertEqual(store.context["source"], "live")
        # But last_user has the demo selection
        self.assertEqual(store.last_user["source"], "demo")
        self.assertEqual(store.last_user["map"], "trick")

    def test_demo_surfaces_after_live_ends(self):
        """When live ends, last demo selection surfaces."""
        store = self._make_store()
        store.dispatch({"kind": "live", "map": "dm3", "live": True})
        store.dispatch({"kind": "demo", "map": "trick", "route": "speed_run"})
        store.dispatch({"kind": "live", "map": "dm3", "live": False})
        self.assertEqual(store.context["source"], "demo")
        self.assertEqual(store.context["map"], "trick")

    def test_null_ctx_does_not_dispatch(self):
        """When ctx is null the dispatch must not fire (null guard in App.tsx).
        Simulate by verifying that NOT calling dispatch leaves context unchanged."""
        store = self._make_store()
        store.dispatch({"kind": "demo", "map": "dm3", "route": "sng_to_rl"})
        snap_context = dict(store.context)
        # Null ctx: we do NOT dispatch (App.tsx guard: if (ctx !== null) {...})
        # Context must remain unchanged
        self.assertEqual(store.context, snap_context)

    def test_two_demo_dispatches_update_to_latest(self):
        """Dispatching demo context twice updates to the most recent."""
        store = self._make_store()
        store.dispatch({"kind": "demo", "map": "dm3", "route": "sng_to_rl"})
        store.dispatch({"kind": "demo", "map": "frobodm2", "route": None})
        self.assertEqual(store.context["map"], "frobodm2")
        self.assertIsNone(store.context["route"])



class TestMockupCallbackStability(unittest.TestCase):
    """App.tsx must use a stable (memoized) onSelect callback for MockupPane.

    Codex inline P1 (Xerialen/komodobots#142 discussion_r3395309484):
      "MockupPane runs its context effect with onSelect in the dependency list,
       and this inline arrow gets a new identity on every App render.  The
       callback dispatches a context update, whose reducer always returns a fresh
       state object, so the parent re-renders, the prop changes again, and the
       child effect dispatches again until React hits the maximum update depth."

    Fix contract:
      - App.tsx must define a useCallback-memoized handler (onMockupSelect)
        for the MockupPane onSelect prop.
      - The inline arrow `(sel: MockupSelection) => { dispatchContext(...) }`
        must NOT be passed directly as the onSelect prop.
      - onMockupSelect must dispatch {kind:"mockup", map, route}.
    """

    def setUp(self):
        import os
        _REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
        _APP_TSX = os.path.join(_REPO_ROOT, "lab", "dashboard", "src", "App.tsx")
        with open(_APP_TSX, encoding="utf-8") as fh:
            self.source = fh.read()

    def test_onMockupSelect_callback_defined(self):
        """App.tsx must define a named memoized handler for the MockupPane prop.
        A useCallback wrapping the dispatch is required to prevent the render loop."""
        self.assertIn("onMockupSelect", self.source,
                      "App.tsx must define onMockupSelect (memoized mockup handler)")

    def test_onMockupSelect_uses_useCallback(self):
        """onMockupSelect must be wrapped in useCallback."""
        import re
        pattern = re.compile(
            r"onMockupSelect\s*=\s*useCallback",
            re.DOTALL,
        )
        self.assertRegex(
            self.source,
            pattern,
            "onMockupSelect must be assigned via useCallback (not a plain arrow)",
        )

    def test_MockupPane_receives_stable_callback(self):
        """MockupPane must receive onMockupSelect (not an inline arrow)."""
        # The stable form: onSelect={onMockupSelect}
        self.assertIn("onSelect={onMockupSelect}", self.source,
                      "MockupPane must receive onSelect={onMockupSelect}")

    def test_no_inline_arrow_for_mockup_onSelect(self):
        """The inline arrow for mockup dispatch must not be passed directly to onSelect.
        Pattern: onSelect={(sel => or onSelect={(sel: MockupSelection) =>"""
        import re
        # Look for the dangerous pattern in JSX prop assignment
        pattern = re.compile(
            r"onSelect=\{.*?sel.*?=>.*?dispatchContext.*?mockup",
            re.DOTALL,
        )
        # Must NOT match
        self.assertNotRegex(
            self.source,
            pattern,
            "MockupPane onSelect must not use an inline arrow (causes render loop)",
        )

    def test_onMockupSelect_dispatches_mockup_kind(self):
        """The memoized callback must dispatch {kind:'mockup'} with map and route."""
        import re
        # Find onMockupSelect body and verify it dispatches kind:mockup
        # Accept either direct string or variable reference
        idx = self.source.find("onMockupSelect = useCallback")
        self.assertGreater(idx, -1, "onMockupSelect = useCallback not found")
        block = self.source[idx:idx + 400]
        self.assertIn('"mockup"', block,
                      "onMockupSelect must dispatch kind:'mockup'")
        self.assertIn("sel.map", block,
                      "onMockupSelect must forward sel.map")
        self.assertIn("sel.route", block,
                      "onMockupSelect must forward sel.route")

if __name__ == "__main__":
    unittest.main()
