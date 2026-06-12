"""Mockup pane data contract (LD-C3, issue #97).

Validates the routes manifest data layer that MockupPane.tsx consumes:
- MockupSelection contract: emits { map, route } where route is the last
  selected route name or null; documented for LD-E1 to consume.
- Routes manifest readability: all four maps load without error; dm3 has 11
  routes with non-empty polylines, gap markers, and human stats.
- Gap required_speed range check: sng_to_rl final gap is in the 526-region
  (the census measurement the project depends on for the trick link).
- Empty-map honesty: dm2/frobodm2/trick emit route lists that are either
  empty or contain valid schemas -- never missing. ztricks is the exception:
  it carries the successful getspeed.qwd distance_standstill reference and a
  spawn-floor speed-gain drill.
- Teleports field is always present (list, possibly empty) so MockupPane.tsx
  can iterate unconditionally.
- Map-entity context exists for ztricks so the pane can annotate the route
  start/edge/land against static teleport/spawn entities.

These tests lock the manifest schema as consumed by the TypeScript component;
changes to komodobots.routes.v1 or the manifest builder must keep them green.
"""

import json
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ROUTES_DIR = REPO / "lab" / "dashboard" / "public" / "data" / "routes"
ENTITIES_DIR = REPO / "lab" / "dashboard" / "public" / "data" / "map_entities"
MAPS = ["dm3", "dm2", "frobodm2", "trick", "ztricks"]


def load_manifest(map_name: str) -> dict:
    path = ROUTES_DIR / f"{map_name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def load_entities(map_name: str) -> dict:
    path = ENTITIES_DIR / f"{map_name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


class TestManifestSchema(unittest.TestCase):
    """Schema contract consumed by MockupPane.tsx."""

    @classmethod
    def setUpClass(cls):
        cls.manifests = {m: load_manifest(m) for m in MAPS}

    def test_all_mockup_maps_present(self):
        for m in MAPS:
            self.assertIn(m, self.manifests, f"{m}.json missing")

    def test_schema_field(self):
        for m, doc in self.manifests.items():
            self.assertEqual(doc["schema"], "komodobots.routes.v1", m)
            self.assertEqual(doc["v"], 1, m)

    def test_routes_is_list(self):
        for m, doc in self.manifests.items():
            self.assertIsInstance(doc["routes"], list, m)

    def test_dm3_has_eleven_routes(self):
        doc = self.manifests["dm3"]
        self.assertEqual(len(doc["routes"]), 11,
                         "dm3 must have exactly 11 censused routes")

    def test_non_dm3_routes_are_empty(self):
        """Empty maps must emit an empty list, not be absent."""
        for m in ["dm2", "frobodm2", "trick"]:
            self.assertEqual(self.manifests[m]["routes"], [],
                             f"{m} should have no routes yet")

    def test_ztricks_has_practice_route(self):
        names = [r["name"] for r in self.manifests["ztricks"]["routes"]]
        self.assertEqual(names, ["distance_standstill", "spawn_left_speedjump"])


class TestRouteFields(unittest.TestCase):
    """Per-route field contract consumed by the route browser and detail panel."""

    @classmethod
    def setUpClass(cls):
        cls.routes = load_manifest("dm3")["routes"]
        cls.sng_to_rl = next(r for r in cls.routes if r["name"] == "sng_to_rl")

    def test_required_keys_present(self):
        required = {"name", "human", "polyline", "gaps", "teleports"}
        for route in self.routes:
            missing = required - set(route.keys())
            self.assertFalse(missing,
                             f"route {route['name']!r} missing: {missing}")

    def test_human_stats_are_numbers(self):
        for route in self.routes:
            h = route["human"]
            self.assertIsInstance(h["duration_s"], (int, float), route["name"])
            self.assertIsInstance(h["active_mean_speed"], (int, float), route["name"])
            self.assertIsInstance(h["peak_speed"], (int, float), route["name"])

    def test_polylines_have_enough_points(self):
        """MockupPane.tsx requires >= 2 points to build a Three.js Line."""
        for route in self.routes:
            self.assertGreaterEqual(
                len(route["polyline"]),
                2,
                f"route {route['name']!r} polyline too short for a Line",
            )

    def test_polyline_points_are_xyz_triples(self):
        for route in self.routes[:3]:  # spot-check first few routes
            for pt in route["polyline"][:5]:
                self.assertEqual(len(pt), 3, f"polyline point must be [x,y,z]: {pt}")
                for coord in pt:
                    self.assertIsInstance(coord, (int, float))

    def test_gaps_have_required_fields(self):
        required_gap = {"edge", "land", "required_speed", "human_speed_at_edge",
                        "hard", "type"}
        for route in self.routes:
            for i, gap in enumerate(route["gaps"]):
                missing = required_gap - set(gap.keys())
                self.assertFalse(
                    missing,
                    f"route {route['name']!r} gap {i} missing: {missing}",
                )

    def test_gap_edge_land_are_xyz_triples(self):
        for route in self.routes:
            for gap in route["gaps"]:
                for key in ("edge", "land"):
                    pt = gap[key]
                    self.assertEqual(len(pt), 3,
                                     f"{route['name']} gap.{key} must be [x,y,z]")

    def test_teleports_is_always_a_list(self):
        """MockupPane.tsx iterates teleports unconditionally; must never be None."""
        for route in self.routes:
            self.assertIsInstance(route["teleports"], list,
                                  f"route {route['name']!r} teleports must be a list")

    def test_teleport_entry_shape_from_to(self):
        """Each teleport entry must have 'from' and 'to' keys (komodobots.routes.v1).

        MockupPane.tsx renders tp.from[0..2]; a mismatch (e.g. enter/exit) causes
        a TypeError and unmounts the pane.  This test locks the field names so a
        manifest schema change is caught in Python CI before a browser smoke test.
        """
        for route in self.routes:
            for i, tp in enumerate(route["teleports"]):
                self.assertIn(
                    "from", tp,
                    f"route {route['name']!r} teleport {i} missing 'from' key",
                )
                self.assertIn(
                    "to", tp,
                    f"route {route['name']!r} teleport {i} missing 'to' key",
                )
                self.assertEqual(
                    len(tp["from"]), 3,
                    f"route {route['name']!r} teleport {i} 'from' must be [x,y,z]",
                )
                self.assertEqual(
                    len(tp["to"]), 3,
                    f"route {route['name']!r} teleport {i} 'to' must be [x,y,z]",
                )

    def test_hard_is_bool(self):
        for route in self.routes:
            for gap in route["gaps"]:
                self.assertIsInstance(gap["hard"], bool,
                                      f"{route['name']} gap hard must be bool")


class TestCriticalValues(unittest.TestCase):
    """Lock the census measurements the trick-link work depends on."""

    @classmethod
    def setUpClass(cls):
        routes = load_manifest("dm3")["routes"]
        cls.sng_to_rl = next(r for r in routes if r["name"] == "sng_to_rl")

    def test_sng_to_rl_exists(self):
        self.assertIsNotNone(self.sng_to_rl)

    def test_sng_to_rl_has_three_gaps(self):
        self.assertEqual(len(self.sng_to_rl["gaps"]), 3)

    def test_sng_to_rl_final_gap_required_speed_526_region(self):
        """The decisive final leap must require >= 520 qu/s (census says 525.3).
        Locks the measurement the trick-link gate (LD-D1) depends on."""
        final_gap = self.sng_to_rl["gaps"][-1]
        req = final_gap["required_speed"]
        self.assertGreaterEqual(req, 520.0,
                                f"sng_to_rl final gap req {req} below 520-region")
        self.assertLessEqual(req, 535.0,
                             f"sng_to_rl final gap req {req} unexpectedly high")

    def test_sng_to_rl_peak_speed_above_526(self):
        peak = self.sng_to_rl["human"]["peak_speed"]
        self.assertGreater(peak, 526.0,
                           f"sng_to_rl human peak {peak} should exceed 526 qu/s")

    def test_sng_to_rl_polyline_at_least_100_points(self):
        """Original ticket measurement: sng_to_rl polyline > 100 points."""
        n = len(self.sng_to_rl["polyline"])
        self.assertGreater(n, 100,
                           f"sng_to_rl polyline only {n} points (expect >100)")


class TestMockupContextContract(unittest.TestCase):
    """Document the MockupSelection event shape emitted by MockupPane.tsx.

    These are data-layer checks that verify the manifest fields MockupPane
    uses to populate the context event { map: string, route: string | null }.
    The actual event emission is TypeScript; this test guards the data contract
    so a manifest schema change that breaks the UI is caught in Python CI first.
    """

    @classmethod
    def setUpClass(cls):
        cls.dm3 = load_manifest("dm3")
        cls.trick = load_manifest("trick")

    def test_map_field_matches_filename(self):
        """map field drives the context event map value."""
        self.assertEqual(self.dm3["map"], "dm3")
        self.assertEqual(self.trick["map"], "trick")

    def test_route_names_are_strings(self):
        """route names are emitted as string | null in MockupSelection."""
        for route in self.dm3["routes"]:
            self.assertIsInstance(route["name"], str)
            self.assertTrue(route["name"], "route name must be non-empty")

    def test_map_with_no_routes_gives_null_route_context(self):
        """When routes == [], MockupPane emits route: null.  Trick has no routes."""
        self.assertEqual(self.trick["routes"], [],
                         "trick map should have no routes yet (emits null route)")

    def test_dm3_non_empty_routes_give_non_null_route_context(self):
        """When routes exist, MockupPane can emit a non-null route name."""
        self.assertTrue(
            len(self.dm3["routes"]) > 0,
            "dm3 must have routes so MockupPane can emit a non-null selection",
        )


class TestZtricksEntityContext(unittest.TestCase):
    """Static map-entity context consumed by MockupPane.tsx for ztricks."""

    @classmethod
    def setUpClass(cls):
        cls.route = load_manifest("ztricks")["routes"][0]
        cls.entities = load_entities("ztricks")["entities"]

    def _nearest(self, point):
        import math
        return min(
            (
                (math.dist(point, [e["x"], e["y"], e["z"]]), e)
                for e in self.entities
            ),
            key=lambda row: row[0],
        )

    def test_ztricks_entities_have_teleport_context(self):
        types = {}
        for entity in self.entities:
            types[entity["type"]] = types.get(entity["type"], 0) + 1
        self.assertEqual(types["spawn"], 1)
        self.assertEqual(types["teleportDst"], 8)
        self.assertEqual(types["teleportSrc"], 26)

    def test_route_start_nearest_teleport_destination(self):
        distance, entity = self._nearest(self.route["polyline"][0])
        self.assertEqual(entity["type"], "teleportDst")
        self.assertEqual(entity["name"], "tele-dst-1")
        self.assertLess(distance, 32.0)

    def test_route_landing_nearest_teleport_source(self):
        distance, entity = self._nearest(self.route["gaps"][0]["land"])
        self.assertEqual(entity["type"], "teleportSrc")
        self.assertEqual(entity["name"], "tele-src-3")
        self.assertLess(distance, 200.0)

    def test_ztricks_route_uses_successful_attempt_reference_metrics(self):
        self.assertAlmostEqual(self.route["human"]["duration_s"], 2.116, places=3)
        self.assertAlmostEqual(self.route["human"]["active_mean_speed"], 388.4, places=1)
        self.assertAlmostEqual(self.route["human"]["peak_speed"], 495.5, places=1)
        self.assertIsNone(self.route["gaps"][0]["required_speed"])
        self.assertAlmostEqual(
            self.route["gaps"][0]["human_speed_at_edge"], 475.2, places=1)
        self.assertEqual(self.route["reference"]["attempt"], 11)
        self.assertEqual(self.route["reference"]["route_rows"], [1807, 1969])
        self.assertAlmostEqual(
            self.route["reference"]["launch_heading_deg"], -11.7, places=1)
        self.assertTrue(self.route["reference"]["landed_recorded"])
        self.assertTrue(self.route["reference"]["landed_sim"])

    def test_spawn_left_speedjump_starts_at_real_spawn(self):
        route = next(r for r in load_manifest("ztricks")["routes"]
                     if r["name"] == "spawn_left_speedjump")
        self.assertEqual(route["polyline"][0], [-1168.0, 1632.0, -496.0])
        distance, entity = self._nearest(route["polyline"][0])
        self.assertEqual(entity["type"], "spawn")
        self.assertLess(distance, 1.0)
        self.assertEqual(route["reference"]["success_metric"], "horizontal_speed_gain")
        self.assertEqual(route["control"]["spawn_velocity"], "0 0 0")


if __name__ == "__main__":
    unittest.main()
