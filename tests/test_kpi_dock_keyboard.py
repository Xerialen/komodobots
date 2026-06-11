"""KPI dock keyboard shortcut contract tests (LD-E1, issue #100).

Documents and validates the "[" key shortcut contract for toggling layout.dockCollapsed.

Design rules encoded here:
- The shortcut key is "[" (no modifier required, non-conflicting with Escape/view toggles).
- The handler is installed unconditionally (not gated on dock state, unlike Esc handler).
- Input/textarea/select elements suppress the shortcut so normal typing is unaffected.
- The top-bar KPI button carries aria-keyshortcuts="[" and a title that mentions the key.
- The toggle is idempotent: pressing "[" twice returns to the original state.

These tests exercise the PURE LOGIC of the toggle function — no browser or TypeScript
runtime required.  They lock the shortcut contract so any App.tsx refactor that changes
the key or removes the guard would fail here.
"""

import sys
import os
import re
import unittest

# Locate App.tsx relative to this test file.
_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_APP_TSX = os.path.join(_REPO_ROOT, "lab", "dashboard", "src", "App.tsx")
_KPI_DOCK_TSX = os.path.join(_REPO_ROOT, "lab", "dashboard", "src", "KpiDock.tsx")


# ---------------------------------------------------------------------------
# Pure-logic model of the "[" shortcut handler from App.tsx
# ---------------------------------------------------------------------------

# Suppressed element tags (mirrors the TypeScript guard).
_SUPPRESSED_TAGS = {"INPUT", "TEXTAREA", "SELECT"}


def should_handle_key(key: str, focused_tag: str | None) -> bool:
    """Return True if the "[" shortcut handler should fire.

    Mirrors the App.tsx onKeyDown guard:
        if (event.key !== "[") return;
        const tag = (event.target as HTMLElement | null)?.tagName ?? "";
        if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
    """
    if key != "[":
        return False
    if focused_tag and focused_tag.upper() in _SUPPRESSED_TAGS:
        return False
    return True


def toggle_dock_collapsed(collapsed: bool) -> bool:
    """The toggle reducer: !state.dockCollapsed."""
    return not collapsed


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestKeyShortcutContract(unittest.TestCase):
    """The "[" key is the designated dock shortcut."""

    def test_bracket_key_triggers_handler(self):
        self.assertTrue(should_handle_key("[", None))

    def test_other_keys_do_not_trigger(self):
        for key in ["Escape", "k", "K", "d", "D", " ", "Enter", "]", "/"]:
            with self.subTest(key=key):
                self.assertFalse(should_handle_key(key, None), f"key {key!r} should not trigger")

    def test_empty_string_does_not_trigger(self):
        self.assertFalse(should_handle_key("", None))


class TestInputGuard(unittest.TestCase):
    """Shortcut is suppressed when focus is in a form element."""

    def test_suppressed_in_input(self):
        self.assertFalse(should_handle_key("[", "INPUT"))

    def test_suppressed_in_textarea(self):
        self.assertFalse(should_handle_key("[", "TEXTAREA"))

    def test_suppressed_in_select(self):
        self.assertFalse(should_handle_key("[", "SELECT"))

    def test_case_insensitive_tag_match(self):
        # tagName in browsers is uppercase; verify our model handles lowercase too
        # (belt-and-suspenders; TypeScript uses tagName which is always uppercase).
        self.assertFalse(should_handle_key("[", "input"))
        self.assertFalse(should_handle_key("[", "textarea"))
        self.assertFalse(should_handle_key("[", "select"))

    def test_not_suppressed_in_button(self):
        self.assertTrue(should_handle_key("[", "BUTTON"))

    def test_not_suppressed_in_div(self):
        self.assertTrue(should_handle_key("[", "DIV"))

    def test_not_suppressed_when_no_target(self):
        self.assertTrue(should_handle_key("[", None))


class TestToggleIdempotency(unittest.TestCase):
    """Pressing "[" twice returns to the original state."""

    def test_expand_then_collapse(self):
        state = False  # expanded
        state = toggle_dock_collapsed(state)
        self.assertTrue(state)   # collapsed
        state = toggle_dock_collapsed(state)
        self.assertFalse(state)  # back to expanded

    def test_collapse_then_expand(self):
        state = True   # collapsed
        state = toggle_dock_collapsed(state)
        self.assertFalse(state)  # expanded
        state = toggle_dock_collapsed(state)
        self.assertTrue(state)   # back to collapsed


class TestAppTsxShortcutSource(unittest.TestCase):
    """Smoke: verify the actual App.tsx contains the required shortcut wiring."""

    def setUp(self):
        with open(_APP_TSX, encoding="utf-8") as fh:
            self.source = fh.read()

    def test_bracket_key_handler_present(self):
        """App.tsx must check for the "[" key in a keydown handler."""
        self.assertIn('event.key !== "["', self.source,
                      'App.tsx must guard on event.key !== "["')

    def test_input_guard_present(self):
        """App.tsx must suppress the shortcut in INPUT elements."""
        self.assertIn("INPUT", self.source,
                      'App.tsx must have INPUT guard for the dock shortcut')

    def test_kpi_button_has_aria_keyshortcuts(self):
        """Top-bar KPI button must carry aria-keyshortcuts="[" ."""
        self.assertIn('aria-keyshortcuts="["', self.source,
                      'KPI toggle button must expose aria-keyshortcuts="["')

    def test_kpi_button_title_mentions_key(self):
        """KPI button title must mention the [ key for discoverability."""
        # Look for the aria-keyshortcuts attribute near the KPI button title.
        self.assertRegex(self.source, r'title="KPI dock[^"]*\[',
                         'KPI button title must mention the [ shortcut key')

    def test_handler_not_gated_on_dock_state(self):
        """The "[" handler must always be active (not conditional on collapsed state).

        The Escape handler is gated on layout.drawerOpen because it's only meaningful
        when the drawer is open.  The dock shortcut should always fire so the user can
        expand a collapsed dock with the same key.  Verify the effect dependency array
        is empty: `}, []);`
        """
        # Find the block containing the bracket shortcut and confirm its deps array is [].
        # A simple heuristic: the effect that contains '[' key check should end with `}, []);`
        match = re.search(
            r'event\.key\s*!==\s*"\[".*?},\s*\[\s*\]\s*\);',
            self.source,
            re.DOTALL,
        )
        self.assertIsNotNone(match,
            'The "[" keydown effect in App.tsx must have an empty dependency array `}, [])`')


if __name__ == "__main__":
    unittest.main()
