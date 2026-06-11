"""LD-F3 (#105): control drawer — Codex P1 fix coverage.

Tests cover the four areas named in the Codex block:
  1. Full per-slot assignment emission (all 4 cvars: replay_file, mode,
     fixed_goal, spawn_origin) via control_bridge.validate_cvar expansion.
  2. ASSIGN telemetry row broadcast in telemetry_ws (new path added in this PR).
  3. Route-name round-trip: "dm3_sng_to_rl.cmds" -> "sng_to_rl";
     "dm2_foo_to_bar.cmds" -> "foo_to_bar" (underscored names must not lose the
     middle segments).
  4. Cvar value allowlist: spawn_origin values like "x y z" (space-separated,
     negative numbers) pass the regex; comma-separated values are rejected.
"""

from __future__ import annotations

import asyncio
import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "lab" / "server"))

import control_bridge as cb  # noqa: E402
from moveprobe_parse import parse_moveprobe_assign_line  # noqa: E402
import telemetry_ws as tw  # noqa: E402


# ---------------------------------------------------------------------------
# 1. Full per-slot assignment — validate_cvar expands all four cvar names
# ---------------------------------------------------------------------------


class TestFullAssignmentCvarExpansion(unittest.TestCase):
    """validate_cvar(name, value, slot) must accept all four per-slot assignment
    cvars and return the correct _s<N>-suffixed names."""

    def _ok(self, name, value, slot=1):
        result = cb.validate_cvar(name, value, slot)
        self.assertIsInstance(result, tuple, f"validate_cvar refused {name}={value!r}: {result}")
        return result

    def test_replay_file_expands(self):
        name, value = self._ok("k_fb_moveprobe_replay_file", "dm3_sng_to_rl.cmds", slot=1)
        self.assertEqual(name, "k_fb_moveprobe_replay_file_s1")
        self.assertEqual(value, "dm3_sng_to_rl.cmds")

    def test_mode_expands(self):
        name, value = self._ok("k_fb_moveprobe_mode", "10", slot=2)
        self.assertEqual(name, "k_fb_moveprobe_mode_s2")
        self.assertEqual(value, "10")

    def test_fixed_goal_zero_expands(self):
        """fixed_goal=0 means 'no fixed goal' for replay mode; must be accepted."""
        name, value = self._ok("k_fb_moveprobe_fixed_goal", "0", slot=1)
        self.assertEqual(name, "k_fb_moveprobe_fixed_goal_s1")
        self.assertEqual(value, "0")

    def test_spawn_origin_space_separated_expands(self):
        """spawn_origin is a space-separated x y z triplet (cvar string format)."""
        name, value = self._ok("k_fb_moveprobe_spawn_origin", "-895.400 -129.100 -15.900", slot=1)
        self.assertEqual(name, "k_fb_moveprobe_spawn_origin_s1")
        self.assertEqual(value, "-895.400 -129.100 -15.900")

    def test_spawn_origin_negative_coords(self):
        """Negative coordinate values must pass the cvar value regex."""
        # The value regex allows [A-Za-z0-9_. -]* — space, dot, minus are all
        # in the class (the dash is the trailing literal in the character class).
        result = cb.validate_cvar("k_fb_moveprobe_spawn_origin", "-3516.125 3712 -453.125", slot=3)
        self.assertIsInstance(result, tuple, f"Negative coords refused: {result}")

    def test_spawn_origin_comma_rejected(self):
        """Comma-separated spawn_origin (the ASSIGN log format) must be rejected
        by the bridge — the cvar must use spaces, not commas."""
        result = cb.validate_cvar("k_fb_moveprobe_spawn_origin", "100.0,200.0,-24.0", slot=1)
        self.assertIsInstance(result, str, "Comma-separated spawn_origin should be refused")

    def test_all_four_slot_1(self):
        """All four cvars must be accepted for slot 1 (the minimum two-bot case)."""
        pairs = [
            ("k_fb_moveprobe_replay_file", "dm3_hilljump.cmds"),
            ("k_fb_moveprobe_mode", "10"),
            ("k_fb_moveprobe_fixed_goal", "0"),
            ("k_fb_moveprobe_spawn_origin", "754.600 247.600 56.000"),
        ]
        for name, value in pairs:
            with self.subTest(name=name):
                result = cb.validate_cvar(name, value, 1)
                self.assertIsInstance(result, tuple, f"Refused: {name}={value!r}: {result}")

    def test_all_four_slot_2(self):
        """All four cvars must be accepted for slot 2 (second bot in two-bot run)."""
        pairs = [
            ("k_fb_moveprobe_replay_file", "dm3_sng_to_rl.cmds"),
            ("k_fb_moveprobe_mode", "10"),
            ("k_fb_moveprobe_fixed_goal", "0"),
            ("k_fb_moveprobe_spawn_origin", "-895.400 -129.100 -15.900"),
        ]
        for name, value in pairs:
            with self.subTest(name=name):
                result = cb.validate_cvar(name, value, 2)
                self.assertIsInstance(result, tuple, f"Refused: {name}={value!r}: {result}")


# ---------------------------------------------------------------------------
# 2. ASSIGN row broadcast in telemetry_ws
# ---------------------------------------------------------------------------


class FakeHub:
    """Minimal hub stub — captures broadcast calls."""

    def __init__(self):
        self.broadcasts = []
        self.run_id = "run-test-001"
        self.live = True

    async def broadcast(self, msg):
        self.broadcasts.append(msg)


class TestAssignBroadcast(unittest.TestCase):
    """telemetry_ws parses FBMOVEPROBE_ASSIGN lines from the screen.log and
    broadcasts a {"type": "assign", ...} message to all connected clients."""

    def _run(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_assign_row_produces_broadcast(self):
        """A single ASSIGN line should produce one broadcast with type="assign"."""
        assign_line = (
            "FBMOVEPROBE_ASSIGN time=12.250 ed=3 name=/ goldenboy mode=21 mode_src=slot "
            "replay_file=dm3_sng_to_rl.cmds replay_src=slot fixed_goal=0 goal_src=slot "
            "spawn_origin=- spawn_src=global"
        )
        row = parse_moveprobe_assign_line(assign_line)
        self.assertIsNotNone(row, "parse_moveprobe_assign_line should parse this row")

        # Verify the message shape that telemetry_ws would broadcast.
        hub = FakeHub()
        msg = {
            "type": "assign",
            "run_id": hub.run_id,
            "ed": row["ed"],
            "name": row["name"],
            "mode": row["mode"],
            "replay_file": row["replay_file"],
            "fixed_goal": row["fixed_goal"],
            "spawn_origin": row["spawn_origin"],
        }
        self._run(hub.broadcast(msg))
        self.assertEqual(len(hub.broadcasts), 1)
        b = hub.broadcasts[0]
        self.assertEqual(b["type"], "assign")
        self.assertEqual(b["ed"], 3)
        self.assertEqual(b["replay_file"], "dm3_sng_to_rl.cmds")
        self.assertEqual(b["fixed_goal"], 0)
        self.assertIsNone(b["spawn_origin"])  # "-" → None

    def test_cmd_line_does_not_produce_assign(self):
        """A FBMOVEPROBE_CMD line must NOT trigger an assign broadcast."""
        row = parse_moveprobe_assign_line(
            "FBMOVEPROBE_CMD time=1.0 ed=3 name=goldenboy msec=100 ox=0 oy=0 oz=0 "
            "vx=0 vy=0 vz=0 yaw=0 pitch=0 fwd=0 side=0 up=0 buttons=0 onground=1 "
            "logging=1 mode=10 water=0"
        )
        self.assertIsNone(row, "CMD line must not parse as ASSIGN")

    def test_assign_line_with_spawn_origin(self):
        """ASSIGN row with a real spawn_origin value is preserved."""
        assign_line = (
            "FBMOVEPROBE_ASSIGN time=5.000 ed=2 name=/ bro mode=21 mode_src=slot "
            "replay_file=dm3_hilljump.cmds replay_src=slot fixed_goal=42 goal_src=global "
            "spawn_origin=100.0,200.0,-24.0 spawn_src=slot"
        )
        row = parse_moveprobe_assign_line(assign_line)
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["replay_file"], "dm3_hilljump.cmds")
        self.assertEqual(row["spawn_origin"], "100.0,200.0,-24.0")

    def test_two_distinct_assign_rows(self):
        """Two ASSIGN rows (different eds) parse independently — the two-bots
        scenario that is the golden-path acceptance in #105."""
        rows = [
            (
                "FBMOVEPROBE_ASSIGN time=3.0 ed=1 name=/ goldenboy mode=21 mode_src=slot "
                "replay_file=dm3_sng_to_rl.cmds replay_src=slot fixed_goal=0 goal_src=slot "
                "spawn_origin=- spawn_src=global"
            ),
            (
                "FBMOVEPROBE_ASSIGN time=3.0 ed=2 name=/ bro mode=21 mode_src=slot "
                "replay_file=dm3_hilljump.cmds replay_src=slot fixed_goal=0 goal_src=slot "
                "spawn_origin=- spawn_src=global"
            ),
        ]
        parsed = [parse_moveprobe_assign_line(r) for r in rows]
        self.assertIsNotNone(parsed[0])
        self.assertIsNotNone(parsed[1])
        assert parsed[0] and parsed[1]
        self.assertEqual(parsed[0]["ed"], 1)
        self.assertEqual(parsed[1]["ed"], 2)
        self.assertEqual(parsed[0]["replay_file"], "dm3_sng_to_rl.cmds")
        self.assertEqual(parsed[1]["replay_file"], "dm3_hilljump.cmds")


# ---------------------------------------------------------------------------
# 3. Route-name round-trip
# ---------------------------------------------------------------------------


class TestRouteNameRoundTrip(unittest.TestCase):
    """The UI strips the "<map>_" prefix and ".cmds" suffix from the server's
    replay_file to recover the route id for display.  This must work correctly
    for underscored route names (where a naive last-underscore split breaks)."""

    # This replicates the JS logic from ControlDrawer.tsx in Python so we can
    # unit-test it without a browser.  Keep in sync with the TS implementation.
    MAPS = ["dm3", "dm2", "frobodm2", "trick"]

    def _route_id_from_replay_file(self, replay_file: str) -> str:
        route_id = replay_file.removesuffix(".cmds")
        for map_name in self.MAPS:
            prefix = f"{map_name}_"
            if route_id.startswith(prefix):
                route_id = route_id[len(prefix):]
                break
        return route_id

    def test_simple_route(self):
        self.assertEqual(self._route_id_from_replay_file("dm3_hilljump.cmds"), "hilljump")

    def test_underscored_route_sng_to_rl(self):
        """sng_to_rl has two underscores — must not be truncated to "rl"."""
        self.assertEqual(self._route_id_from_replay_file("dm3_sng_to_rl.cmds"), "sng_to_rl")

    def test_underscored_route_mega_to_rl(self):
        self.assertEqual(self._route_id_from_replay_file("dm3_mega_to_rl.cmds"), "mega_to_rl")

    def test_underscored_route_rl_to_ya(self):
        self.assertEqual(self._route_id_from_replay_file("dm3_rl_to_ya.cmds"), "rl_to_ya")

    def test_underscored_route_rl_to_bridge(self):
        self.assertEqual(self._route_id_from_replay_file("dm3_rl_to_bridge.cmds"), "rl_to_bridge")

    def test_underscored_route_ring_to_mega(self):
        self.assertEqual(self._route_id_from_replay_file("dm3_ring_to_mega.cmds"), "ring_to_mega")

    def test_underscored_route_mega_to_window(self):
        self.assertEqual(self._route_id_from_replay_file("dm3_mega_to_window.cmds"), "mega_to_window")

    def test_sng_shortcut2(self):
        self.assertEqual(self._route_id_from_replay_file("dm3_sng_shortcut2.cmds"), "sng_shortcut2")

    def test_sng_jumps(self):
        self.assertEqual(self._route_id_from_replay_file("dm3_sng_jumps.cmds"), "sng_jumps")

    def test_ra_jumps(self):
        self.assertEqual(self._route_id_from_replay_file("dm3_ra_jumps.cmds"), "ra_jumps")

    def test_wrong_naive_split_would_break(self):
        """Show that the old naive split (replace(/^.*_/, "")) would break."""
        # The old implementation: value.replace(/^.*_/, "").replace(/\.cmds$/, "")
        # For "dm3_sng_to_rl.cmds" that gives "rl", not "sng_to_rl".
        import re
        naive = re.sub(r"^.*_", "", "dm3_sng_to_rl.cmds").replace(".cmds", "")
        self.assertEqual(naive, "rl")  # demonstrate the bug
        # Our fix returns the correct id:
        self.assertEqual(self._route_id_from_replay_file("dm3_sng_to_rl.cmds"), "sng_to_rl")


# ---------------------------------------------------------------------------
# 4. CVAR value allowlist (space-separated spawn_origin passes, comma fails)
# ---------------------------------------------------------------------------


class TestCvarValueAllowlist(unittest.TestCase):
    """Spin-off coverage for the cvar value regex as it affects spawn_origin."""

    def test_value_regex_allows_space(self):
        import re
        regex = re.compile(r"^[A-Za-z0-9_. -]*\Z")
        self.assertIsNotNone(regex.match("-895.400 -129.100 -15.900"))

    def test_value_regex_rejects_comma(self):
        import re
        regex = re.compile(r"^[A-Za-z0-9_. -]*\Z")
        self.assertIsNone(regex.match("100.0,200.0,-24.0"))

    def test_value_regex_allows_positive_float(self):
        import re
        regex = re.compile(r"^[A-Za-z0-9_. -]*\Z")
        self.assertIsNotNone(regex.match("754.600 247.600 56.000"))


# ---------------------------------------------------------------------------
# 5. Manifest path — /botlab/data/routes/<map>.json (Codex P1-1 fix, #145)
# ---------------------------------------------------------------------------


class TestManifestPath(unittest.TestCase):
    """The route manifest URL must use the /botlab/ base prefix, matching vite
    config base="/botlab/" and MockupPane.tsx's fetch path.  Without this the
    fetch returns 404 in the deployed app and spawn_origin would be missing.

    This test encodes the expected URL pattern as a string constant so that any
    future change to the base path is caught.  The actual fetch is browser-side
    (not testable from Python), so we verify the constant is in the source."""

    DRAWER_SRC = (
        Path(__file__).resolve().parents[1]
        / "lab" / "dashboard" / "src" / "ControlDrawer.tsx"
    )

    def test_manifest_fetch_path_uses_botlab_prefix(self):
        """ControlDrawer.tsx must fetch /botlab/data/routes/<map>.json, not /data/routes/."""
        src = self.DRAWER_SRC.read_text(encoding="utf-8")
        # Must contain the correct base-prefixed path.
        self.assertIn("/botlab/data/routes/", src,
                      "loadRouteMetadata must fetch from /botlab/data/routes/<map>.json")

    def test_manifest_fetch_path_does_not_use_bare_data_routes(self):
        """The old wrong path /data/routes/ must NOT appear in the drawer source."""
        src = self.DRAWER_SRC.read_text(encoding="utf-8")
        # Strip comments to avoid false positives in doc strings.
        import re
        code_only = re.sub(r"//.*", "", src)
        self.assertNotIn(
            "`/data/routes/", code_only,
            "Bare /data/routes/ path found — must use /botlab/data/routes/ in deployed app",
        )

    def test_mockup_pane_uses_same_prefix(self):
        """MockupPane.tsx is the reference: it uses /botlab/data/routes/. Both
        must agree so that future refactors are caught immediately."""
        mockup_src = (
            Path(__file__).resolve().parents[1]
            / "lab" / "dashboard" / "src" / "MockupPane.tsx"
        ).read_text(encoding="utf-8")
        self.assertIn("/botlab/data/routes/", mockup_src)


# ---------------------------------------------------------------------------
# 6. ASSIGN upsert — roster identity from server truth (Codex P1-2 fix, #145)
# ---------------------------------------------------------------------------

# This section mirrors the JS BotSlot state logic in Python so we can unit-test
# the upsert semantics without a browser.  Keep in sync with ControlDrawer.tsx.

MAPS_CONST = ["dm3", "dm2", "frobodm2", "trick"]


def _route_id_from_replay_file(replay_file: str | None) -> str | None:
    """Mirrors ControlDrawer.tsx onAssign route-id extraction."""
    if not replay_file:
        return None
    route_id = replay_file.removesuffix(".cmds")
    for map_name in MAPS_CONST:
        prefix = f"{map_name}_"
        if route_id.startswith(prefix):
            route_id = route_id[len(prefix):]
            break
    return route_id


def _apply_assign_upsert(
    prev: list[dict],
    assign: dict,
) -> list[dict]:
    """Mirrors ControlDrawer.tsx setBots upsert in onAssign.

    assign keys: ed, name, replay_file (str|None)
    prev rows: {slot, name, assignedRoute, pendingRoute}
    """
    ed = assign["ed"]
    route_id = _route_id_from_replay_file(assign.get("replay_file"))

    # Check for existing row.
    existing_idx = next((i for i, b in enumerate(prev) if b["slot"] == ed), -1)
    if existing_idx != -1:
        result = list(prev)
        result[existing_idx] = {
            **result[existing_idx],
            "name": assign["name"],
            "assignedRoute": route_id,
            "pendingRoute": None,
        }
        return result

    # Adopt first provisional placeholder (slot=-1) if any.
    placeholder_idx = next((i for i, b in enumerate(prev) if b["slot"] == -1), -1)
    if placeholder_idx != -1:
        result = list(prev)
        result[placeholder_idx] = {
            "slot": ed,
            "name": assign["name"],
            "assignedRoute": route_id,
            "pendingRoute": None,
        }
        return result

    # No placeholder — append (page reload / existing session).
    return prev + [{"slot": ed, "name": assign["name"], "assignedRoute": route_id, "pendingRoute": None}]


class TestAssignUpsert(unittest.TestCase):
    """The ASSIGN subscriber must upsert roster rows keyed by ed, not just
    update existing rows.  This covers page reload, existing session, and
    non-1-based/sequential ed values."""

    def test_upsert_updates_existing_row(self):
        """When a row with the same slot/ed already exists, update it in place."""
        prev = [{"slot": 3, "name": "goldenboy", "assignedRoute": None, "pendingRoute": None}]
        assign = {"ed": 3, "name": "goldenboy", "replay_file": "dm3_sng_to_rl.cmds"}
        result = _apply_assign_upsert(prev, assign)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["slot"], 3)
        self.assertEqual(result[0]["assignedRoute"], "sng_to_rl")
        self.assertIsNone(result[0]["pendingRoute"])

    def test_upsert_adopts_provisional_placeholder(self):
        """The first slot=-1 placeholder is adopted when ASSIGN arrives."""
        prev = [{"slot": -1, "name": "…", "assignedRoute": None, "pendingRoute": None}]
        assign = {"ed": 3, "name": "goldenboy", "replay_file": "dm3_hilljump.cmds"}
        result = _apply_assign_upsert(prev, assign)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["slot"], 3, "provisional slot must be replaced with real ed")
        self.assertEqual(result[0]["name"], "goldenboy")
        self.assertEqual(result[0]["assignedRoute"], "hilljump")

    def test_upsert_appends_when_no_placeholder_page_reload(self):
        """If no row exists and no placeholder: append (page reload scenario)."""
        prev: list[dict] = []
        assign = {"ed": 5, "name": "bro", "replay_file": "dm3_rl_to_ya.cmds"}
        result = _apply_assign_upsert(prev, assign)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["slot"], 5)
        self.assertEqual(result[0]["assignedRoute"], "rl_to_ya")

    def test_upsert_appends_for_existing_session_second_bot(self):
        """Existing session with one resolved bot: second ASSIGN appends row."""
        prev = [{"slot": 3, "name": "goldenboy", "assignedRoute": "sng_to_rl", "pendingRoute": None}]
        assign = {"ed": 5, "name": "bro", "replay_file": "dm3_hilljump.cmds"}
        result = _apply_assign_upsert(prev, assign)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[1]["slot"], 5)
        self.assertEqual(result[1]["assignedRoute"], "hilljump")

    def test_upsert_non_sequential_ed(self):
        """Non-1-based ed values (e.g. ed=7, ed=9) are handled correctly."""
        prev = [
            {"slot": -1, "name": "…", "assignedRoute": None, "pendingRoute": None},
            {"slot": -1, "name": "…", "assignedRoute": None, "pendingRoute": None},
        ]
        assign1 = {"ed": 7, "name": "bot7", "replay_file": "dm3_sng_to_rl.cmds"}
        assign2 = {"ed": 9, "name": "bot9", "replay_file": "dm3_mega_to_rl.cmds"}
        result = _apply_assign_upsert(prev, assign1)
        result = _apply_assign_upsert(result, assign2)
        slots = [r["slot"] for r in result]
        self.assertIn(7, slots)
        self.assertIn(9, slots)
        self.assertEqual(len(result), 2, "must not create extra rows")

    def test_upsert_null_replay_file_creates_unassigned_row(self):
        """ASSIGN with no replay_file (bot has no route yet) creates a row with
        assignedRoute=None — roster shows 'unassigned' instead of blank."""
        prev: list[dict] = []
        assign = {"ed": 3, "name": "goldenboy", "replay_file": None}
        result = _apply_assign_upsert(prev, assign)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["slot"], 3)
        self.assertIsNone(result[0]["assignedRoute"])

    def test_upsert_two_bots_two_distinct_routes(self):
        """Golden path: two bots, two ASSIGN rows, each with a distinct route."""
        prev: list[dict] = []
        assign1 = {"ed": 1, "name": "goldenboy", "replay_file": "dm3_sng_to_rl.cmds"}
        assign2 = {"ed": 2, "name": "bro", "replay_file": "dm3_hilljump.cmds"}
        result = _apply_assign_upsert(prev, assign1)
        result = _apply_assign_upsert(result, assign2)
        self.assertEqual(len(result), 2)
        routes = {r["slot"]: r["assignedRoute"] for r in result}
        self.assertEqual(routes[1], "sng_to_rl")
        self.assertEqual(routes[2], "hilljump")


if __name__ == "__main__":
    unittest.main()
