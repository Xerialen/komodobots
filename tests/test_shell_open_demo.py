"""Shell-level openDemo wiring contract (LD-D3, issue #98).

Guards the fix for the "closed Demo view" race:

  openDemo() called while Demo view is closed
  -> DemoPane not mounted -> demoPaneHandleRef.current is null
  -> params must NOT be dropped; they must be queued and flushed once
     DemoPane mounts and wires its handle (onHandleReady callback).

Since the project has no React test runner, these tests validate the contract
at the source-code level by inspecting App.tsx and DemoPane.tsx for the
required structural guarantees.  A future LD-E4 (#104) browser-driven smoke
test will cover the runtime path end-to-end.

Contract assertions locked here:

1. App.tsx declares a pending-params queue ref (pendingDemoRef).
2. App.tsx openDemo branches on demoPaneHandleRef.current:
   - handle present  -> calls handle.openDemo(params) directly
   - handle absent   -> parks params in pendingDemoRef
3. App.tsx provides an onDemoPaneHandleReady callback that flushes the queue.
4. App.tsx passes onHandleReady={onDemoPaneHandleReady} to <DemoPane ...>.
5. DemoPane.tsx accepts the onHandleReady prop in its interface.
6. DemoPane.tsx calls onHandleReady after wiring handleRef.current = { openDemo }.
7. DemoPane.tsx clears handleRef on unmount so App.tsx detects the closed state.
"""

import re
import unittest
from pathlib import Path

DASHBOARD_SRC = (
    Path(__file__).resolve().parent.parent / "lab" / "dashboard" / "src"
)
APP_TSX = DASHBOARD_SRC / "App.tsx"
DEMO_PANE_TSX = DASHBOARD_SRC / "DemoPane.tsx"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestPendingQueueInApp(unittest.TestCase):
    """App.tsx must declare the pending-params ref and use it correctly."""

    @classmethod
    def setUpClass(cls):
        cls.src = read(APP_TSX)

    def test_pending_ref_declared(self):
        """pendingDemoRef must be a useRef holding OpenDemoParams or null."""
        self.assertIn("pendingDemoRef", self.src,
                      "App.tsx must declare pendingDemoRef")
        self.assertIn("useRef<OpenDemoParams | null>", self.src,
                      "pendingDemoRef must be typed useRef<OpenDemoParams | null>")

    def test_open_demo_parks_params_when_handle_absent(self):
        """openDemo must assign to pendingDemoRef.current when the handle is null."""
        self.assertIn("pendingDemoRef.current = params", self.src,
                      "openDemo must park params in pendingDemoRef.current")

    def test_open_demo_calls_handle_when_present(self):
        """openDemo must call demoPaneHandleRef.current.openDemo(params) when mounted."""
        self.assertIn("demoPaneHandleRef.current.openDemo(params)", self.src,
                      "openDemo must call handle directly when already mounted")

    def test_flush_callback_declared(self):
        """onDemoPaneHandleReady must exist and flush pendingDemoRef."""
        self.assertIn("onDemoPaneHandleReady", self.src,
                      "App.tsx must declare onDemoPaneHandleReady callback")
        self.assertIn("pendingDemoRef.current = null", self.src,
                      "onDemoPaneHandleReady must clear the queue after flushing")

    def test_flush_callback_passed_to_demo_pane(self):
        """DemoPane must receive onHandleReady wired to onDemoPaneHandleReady."""
        self.assertIn("onHandleReady={onDemoPaneHandleReady}", self.src,
                      "App.tsx must pass onHandleReady={onDemoPaneHandleReady} to DemoPane")


class TestDemoPaneHandleWiring(unittest.TestCase):
    """DemoPane.tsx must accept onHandleReady and call it after wiring the handle."""

    @classmethod
    def setUpClass(cls):
        cls.src = read(DEMO_PANE_TSX)

    def test_on_handle_ready_prop_declared(self):
        """DemoPaneProps must include the onHandleReady optional callback."""
        self.assertIn("onHandleReady", self.src,
                      "DemoPane.tsx must declare onHandleReady in its props interface")
        # Must be optional (?) so existing callers without it keep working.
        self.assertIn("onHandleReady?", self.src,
                      "onHandleReady must be optional in DemoPaneProps")

    def test_on_handle_ready_destructured(self):
        """DemoPane function must destructure onHandleReady from props."""
        self.assertIn("onHandleReady", self.src,
                      "DemoPane must accept onHandleReady in props destructuring")

    def test_handle_ready_called_after_wiring(self):
        """onHandleReady must be invoked after handleRef.current is set."""
        src = self.src
        # Locate the block where handleRef.current is assigned.
        wire_pos = src.find("handleRef.current = { openDemo }")
        self.assertGreater(wire_pos, 0,
                           "DemoPane must set handleRef.current = { openDemo }")
        # onHandleReady must appear in the source after the assignment.
        ready_pos = src.find("onHandleReady?.()", wire_pos)
        self.assertGreater(ready_pos, 0,
                           "onHandleReady?.() must be called after handleRef is wired")

    def test_handle_cleared_on_unmount(self):
        """handleRef must be cleared in the useEffect cleanup so App.tsx
        detects the unmounted state and does not call a stale handle."""
        self.assertIn("handleRef.current = null", self.src,
                      "DemoPane cleanup must set handleRef.current = null on unmount")


class TestQueueFlushOrdering(unittest.TestCase):
    """The flush in onDemoPaneHandleReady must consume demoPaneHandleRef, not
    call openDemo recursively (which would re-enter setLayout infinitely)."""

    @classmethod
    def setUpClass(cls):
        cls.src = read(APP_TSX)

    def test_flush_uses_handle_not_open_demo(self):
        """onDemoPaneHandleReady must call demoPaneHandleRef.current.openDemo,
        not the shell-level openDemo (which would re-add the pane guard)."""
        # Find the const declaration of the callback (not a comment or prop reference).
        start = self.src.find("const onDemoPaneHandleReady")
        self.assertGreater(start, 0,
                           "App.tsx must have 'const onDemoPaneHandleReady' declaration")
        # The flush section must contain .openDemo(params) via the handle ref.
        flush_section = self.src[start:start + 400]
        self.assertIn("demoPaneHandleRef.current.openDemo", flush_section,
                      "Flush must call demoPaneHandleRef.current.openDemo, "
                      "not the shell-level openDemo wrapper")


if __name__ == "__main__":
    unittest.main()
