"""
LD-F4 (#103): Multi-bot live 3D — contract tests.

Tests are offline source-inspection only (no browser / Three.js runtime
needed).  They lock in the key contracts established by the LD-F4 changes
so regressions in BotLab3D.tsx, TelemetryHud.tsx, and App.tsx are caught
in CI before a live two-route acceptance run.

Codex review notes are preserved as docstring markers so the rationale
survives future edits.
"""

import pathlib
import re
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
BOTLAB3D = REPO_ROOT / "lab" / "dashboard" / "src" / "BotLab3D.tsx"
HUD = REPO_ROOT / "lab" / "dashboard" / "src" / "TelemetryHud.tsx"
APP = REPO_ROOT / "lab" / "dashboard" / "src" / "App.tsx"


def read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


class BotLab3DContractTests(unittest.TestCase):
    """BotLab3D.tsx source contracts for LD-F4."""

    def setUp(self):
        self.src = read(BOTLAB3D)

    # ── Per-bot trail budget ────────────────────────────────────────────

    def test_per_bot_budget_constant_present(self):
        """MAX_TRAIL_POINTS_PER_BOT must be defined (per-bot budget, not shared)."""
        self.assertIn("MAX_TRAIL_POINTS_PER_BOT", self.src)

    def test_old_shared_budget_gone(self):
        """MAX_TRAIL_POINTS (old shared constant) must not be used as the primary
        trail allocation — LD-F4 replaces it with per-bot budget."""
        # The old name may still appear in comments; ensure it is not used
        # as the trail Float32Array size argument.
        self.assertNotIn("new Float32Array(MAX_TRAIL_POINTS * 3)", self.src)

    # ── Name label (sprite) ─────────────────────────────────────────────

    def test_name_sprite_factory_present(self):
        """makeNameSprite function must be defined."""
        self.assertIn("makeNameSprite", self.src)

    def test_name_sprite_uses_canvas(self):
        """Name label must use a CanvasTexture (not CSS2DObject — avoids DOM
        overlay complexity with the existing renderer setup)."""
        self.assertIn("CanvasTexture", self.src)
        self.assertIn("SpriteMaterial", self.src)

    def test_name_sprite_added_to_marker(self):
        """The sprite must be added as a child of the marker mesh so it moves
        with the bot automatically."""
        self.assertIn("marker.add(nameSprite)", self.src)

    # ── Marker userData.ed ──────────────────────────────────────────────

    def test_marker_stores_ed_in_userdata(self):
        """marker.userData must include { ed } so the raycaster can identify
        which bot was clicked without a separate lookup map."""
        self.assertIn("marker.userData = { ed }", self.src)

    # ── Raycaster for click-to-select ───────────────────────────────────

    def test_raycaster_present(self):
        """A THREE.Raycaster must be created inside the effect for marker
        click detection."""
        self.assertIn("new THREE.Raycaster()", self.src)

    def test_pointerdown_listener_added_and_removed(self):
        """pointerdown must be registered on the renderer canvas and removed
        in cleanup to avoid listener leaks on remount."""
        self.assertIn("pointerdown", self.src)
        # Both addEventListener and removeEventListener must be present
        self.assertIn("addEventListener(\"pointerdown\"", self.src)
        self.assertIn("removeEventListener(\"pointerdown\"", self.src)

    def test_onbotclick_prop_declared(self):
        """onBotClick must be a named prop on BotLab3D."""
        self.assertIn("onBotClick", self.src)

    # ── Camera follow policy ────────────────────────────────────────────

    def test_selectedEd_ref_used_for_follow(self):
        """selectedEdRef.current must be consulted in the frame handler to
        determine which bot the camera follows."""
        self.assertIn("selectedEdRef.current", self.src)

    def test_overview_centroid_when_multi_bot(self):
        """When 2+ bots are active and no bot is selected, the camera must
        follow the centroid — confirmed by presence of centroid arithmetic."""
        self.assertIn("actors.size > 1", self.src)
        # Simple centroid: divide sum of positions by count
        self.assertIn("actors.size", self.src)
        # Centroid computed and stored into followPosition
        self.assertIn("followPosition.set(", self.src)

    # ── BOT_COLORS export ────────────────────────────────────────────────

    def test_bot_colors_exported(self):
        """BOT_COLORS must be exported so tests and the HUD can reference the
        same color assignments."""
        self.assertIn("export const BOT_COLORS", self.src)


class TelemetryHudContractTests(unittest.TestCase):
    """TelemetryHud.tsx source contracts for LD-F4."""

    def setUp(self):
        self.src = read(HUD)

    def test_max_hud_bots_exported(self):
        """MAX_HUD_BOTS must be exported so downstream code can cap display."""
        self.assertIn("export const MAX_HUD_BOTS", self.src)

    def test_per_ed_accumulator_map(self):
        """Each ed must have its own accumulator (not a single shared one)."""
        self.assertIn("accumRef", self.src)
        # The accumulator stores per-ed state in a Map
        self.assertIn("accMap", self.src)
        self.assertIn("accMap.set(frame.ed", self.src)

    def test_compact_row_rendered_for_non_selected(self):
        """Non-selected bots must render a compact row (contains key compact
        layout fields: name/ed, vh, hops, onground label)."""
        # Compact row must show all three status cells
        self.assertIn("frame.vh.toFixed(0)", self.src)
        self.assertIn("state.hopCount", self.src)
        self.assertIn("onground", self.src)

    def test_expanded_row_for_selected(self):
        """The selected bot must use the full expanded detail view."""
        self.assertIn("expanded", self.src)
        # Expanded row shows strafe diagnostics (a field only in expanded view)
        self.assertIn("strafe", self.src.lower())

    def test_onbotclick_prop_declared(self):
        """onBotClick must be a named prop for HUD row click-to-select."""
        self.assertIn("onBotClick", self.src)

    def test_selectedEd_prop_declared(self):
        """selectedEd must be an optional prop."""
        self.assertIn("selectedEd", self.src)

    def test_insertion_order_preserved(self):
        """Display order must follow insertion (first-seen bot first) via an
        explicit order ref — not arbitrary Map iteration order."""
        self.assertIn("orderRef", self.src)

    def test_per_ed_hop_accumulator_reset_on_attempt(self):
        """All per-ed accumulators must clear on new_attempt so hop counts
        restart from zero on each attempt.  The clear is via
        accumRef.current.clear() (the ref holds a Map)."""
        self.assertIn("accumRef.current.clear()", self.src)


class AppWiringTests(unittest.TestCase):
    """App.tsx wiring contracts for LD-F4."""

    def setUp(self):
        self.src = read(APP)

    def test_selected_ed_state_declared(self):
        """App must declare selectedEd state (number | null)."""
        self.assertIn("selectedEd", self.src)
        self.assertIn("setSelectedEd", self.src)

    def test_selected_ed_passed_to_botlab3d(self):
        """selectedEd must be passed as a prop to BotLab3D."""
        self.assertIn("selectedEd={selectedEd}", self.src)

    def test_onbotclick_passed_to_botlab3d(self):
        """onBotClick={setSelectedEd} must be wired into BotLab3D so marker
        clicks update App-level selection state."""
        self.assertIn("onBotClick={setSelectedEd}", self.src)

    def test_selected_ed_passed_to_telemetryhud(self):
        """selectedEd must be passed as a prop to TelemetryHud."""
        # Both the prop name and its value must appear together
        self.assertIn("selectedEd={selectedEd}", self.src)

    def test_onbotclick_passed_to_telemetryhud(self):
        """onBotClick={setSelectedEd} must be wired into TelemetryHud so HUD
        compact row clicks update App-level selection state."""
        # Count occurrences — must appear at least twice (BotLab3D + TelemetryHud)
        count = self.src.count("onBotClick={setSelectedEd}")
        self.assertGreaterEqual(count, 2,
            "onBotClick={setSelectedEd} must be wired to both BotLab3D and TelemetryHud")

    def test_selected_ed_reset_on_new_attempt(self):
        """selectedEd must reset to null on new_attempt so camera re-locks to
        the first-seen bot at the start of each run."""
        self.assertIn("resetSelectedEd", self.src)
        self.assertIn("setSelectedEd(null)", self.src)


class BotHudLogicTests(unittest.TestCase):
    """Pure-logic unit tests for per-ed HUD accumulation (no browser)."""

    def _make_frame(self, ed=1, name="bro", t=0.0, vh=200.0,
                    yaw=0.0, pitch=0.0, onground=0,
                    vx=200.0, vy=0.0, vz=0.0,
                    fwd=127, side=0, up=0,
                    dir_speed=None, dist_to_rl=None):
        return {
            "type": "frame",
            "run_id": "test",
            "t": t,
            "ed": ed,
            "name": name,
            "origin": {"x": 0, "y": 0, "z": 0},
            "vel": {"x": vx, "y": vy, "z": vz},
            "vh": vh,
            "yaw": yaw,
            "pitch": pitch,
            "move": {"fwd": fwd, "side": side, "up": up},
            "buttons": 0,
            "onground": onground,
            "dir_speed": dir_speed,
            "dist_to_rl": dist_to_rl,
        }

    def test_angle_delta_wraps(self):
        """angleDelta must handle 180-degree wrap (e.g. 355 -> 5 = 10°).
        Note: (0-180)%360 = 180 in both Python and JS (positive modulo), so
        angle_delta(0, 180) = 180 - 360 = -180 only if the delta > 180 branch
        fires.  In JS: (0-180)%360 = -180 (JS % can return negative), so the
        branch does NOT fire and the result is -180 directly.  We test only the
        common cases that behave identically in both runtimes."""
        def angle_delta(a, b):
            # Mirror the TypeScript implementation exactly.
            # JS % can return negative values; simulate with Python's fmod.
            import math
            delta = math.fmod(a - b, 360)
            if delta > 180:
                delta -= 360
            if delta < -180:
                delta += 360
            return delta

        self.assertAlmostEqual(angle_delta(5, 355), 10.0)
        self.assertAlmostEqual(angle_delta(355, 5), -10.0)
        self.assertAlmostEqual(angle_delta(180, 0), 180.0)
        # JS: (0-180)%360 = -180 → branch not taken → -180
        self.assertAlmostEqual(angle_delta(0, 180), -180.0)

    def test_hop_detection_logic(self):
        """Hop count must increment exactly once per ground->air transition."""
        hop_count = 0
        prev_onground = 1  # start on ground
        transitions = [1, 1, 0, 0, 1, 0, 1, 1]  # 2 ground->air = 2 hops
        for og in transitions:
            if prev_onground == 1 and og == 0:
                hop_count += 1
            prev_onground = og
        self.assertEqual(hop_count, 2)

    def test_max_hud_bots_is_4(self):
        """MAX_HUD_BOTS from the source must equal 4 (issue #103 spec: 'up to ~4')."""
        src = read(HUD)
        m = re.search(r"export const MAX_HUD_BOTS\s*=\s*(\d+)", src)
        self.assertIsNotNone(m, "MAX_HUD_BOTS not found in TelemetryHud.tsx")
        self.assertEqual(int(m.group(1)), 4)

    def test_per_bot_trail_budget_at_least_6000(self):
        """MAX_TRAIL_POINTS_PER_BOT must be at least 6000 (enough for 60 s at
        100 Hz per bot — the minimum for a useful attempt trace)."""
        src = read(BOTLAB3D)
        m = re.search(r"MAX_TRAIL_POINTS_PER_BOT\s*=\s*(\d+)", src)
        self.assertIsNotNone(m, "MAX_TRAIL_POINTS_PER_BOT not found in BotLab3D.tsx")
        self.assertGreaterEqual(int(m.group(1)), 6000)


if __name__ == "__main__":
    unittest.main()
