"""Live Game / QTV pane status detection contracts.

The pane is plain HTML/JS, so these tests lock the source-level contract that
matters for #158: a live FTE stream can connect without echoing f_demostart.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
QTV_HTML = REPO_ROOT / "lab" / "dashboard" / "public" / "panes" / "qtv.html"


def _connected_log_function_body() -> str:
    src = QTV_HTML.read_text(encoding="utf-8")
    match = re.search(r"function isQtvConnectedLog\(text\) \{(?P<body>.*?)\n    \}", src, re.S)
    if not match:
        raise AssertionError("qtv.html must define isQtvConnectedLog(text)")
    return match.group("body")


def _function_body(name: str) -> str:
    src = QTV_HTML.read_text(encoding="utf-8")
    match = re.search(rf"function {name}\([^)]*\) \{{(?P<body>.*?)\n    \}}", src, re.S)
    if not match:
        raise AssertionError(f"qtv.html must define {name}()")
    return match.group("body")


class TestQtvPaneStatusDetection(unittest.TestCase):
    def test_relay_acceptance_marks_qtv_connected(self):
        """The relay banner is the earliest reliable successful qtvplay signal."""
        body = _connected_log_function_body()
        self.assertIn('"Welcome to FTEQTV"', body)
        self.assertIn('"streaming \\""', body)
        self.assertIn('"\\" via \\""', body)

    def test_runtime_entered_game_log_marks_qtv_connected(self):
        """FTE may not echo f_demostart, but it does print entered-the-game."""
        body = _connected_log_function_body()
        self.assertIn(
            '" entered the game"',
            body,
            "Live Game status must treat the runtime entered-the-game log as connected",
        )

    def test_hook_based_connect_detection_is_preserved(self):
        """Keep the original f_demostart/autotrack detection path."""
        body = _connected_log_function_body()
        self.assertIn('"f_demostart"', body)
        self.assertIn('"autotrack"', body)

    def test_left_game_log_is_not_a_connect_signal(self):
        """A disconnect/cleanup line must not be accepted as connected."""
        body = _connected_log_function_body()
        self.assertNotIn("left the game", body)

    def test_module_print_uses_connect_detection_helper(self):
        src = QTV_HTML.read_text(encoding="utf-8")
        self.assertIn("if (isQtvConnectedLog(text))", src)

    def test_qtvplay_attach_has_connected_fallback(self):
        """After qtvplay is issued, the pane must not stay retrying forever."""
        src = QTV_HTML.read_text(encoding="utf-8")
        self.assertIn("ASSUME_CONNECTED_AFTER_QTVPLAY_MS", src)
        self.assertIn("scheduleAttachConnectedFallback();", _function_body("attach"))

    def test_connected_fallback_only_promotes_retrying_state(self):
        """The fallback acts only from "retrying", and since the engine-boot
        race fix (cbuf commands can be dropped right after FTEC appears) it
        must VERIFY the stream via the client-state API: players present ->
        connected, otherwise go around the retry loop instead of blindly
        promoting."""
        body = _function_body("scheduleAttachConnectedFallback")
        self.assertIn('if (state !== "retrying") return;', body)
        self.assertIn("spectatablePlayers().length > 0", body)
        self.assertIn('setState("connected")', body)
        self.assertIn("scheduleRetry();", body)

    def test_disconnect_clears_connected_fallback(self):
        body = _function_body("onQtvDisconnect")
        self.assertIn("clearAttachConnectedFallback();", body)


if __name__ == "__main__":
    unittest.main()
