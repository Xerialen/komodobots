"""Tests for scripts/map_regions.py — named control REGIONS + deterministic assignment (#317).

These are pure stdlib `unittest` and have NO catalog dependency (CI has no demos): they
exercise the loader + the `assign_region` contract directly against the committed dm3 region
file and the dm3 map-entity coords.

What they assert (the #317 deliverable-3 spec):
  (a) assignment is DETERMINISTIC and NON-OVERLAPPING — nearest-region-with-cap means a point
      is claimed by exactly one region (or None); two regions never both claim a point. We
      check this structurally (the assigned region IS the nearest within-cap one) and by
      re-running (same input -> same output).
  (b) SPOT-CHECKS — each major control point's own primary-item coord assigns to its expected
      region (RA coord -> "RA", Quad coord -> "Quad", ...), and the merged sub-points collapse
      into their parent region (RA.low -> "RA", YA.box -> "YA", SNG.MH -> "SNG") so the #315
      phantom shuffles (RA.low<->RA, YA.box<->YA) cannot occur.
  (c) a point far from everything assigns to None.

Follows the komodobots test convention: scripts/ on sys.path, module imported top-level.
"""
import json
import math
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
SCRIPTS = REPO_ROOT / "scripts"
for _p in (str(SCRIPTS), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import map_regions as M  # noqa: E402

DM3_ENTITIES = (REPO_ROOT / "lab" / "dashboard" / "public" / "data"
                / "map_entities" / "dm3.json")


def _entity_coord(loc: str, kind: str):
    """Return (x, y, z) for the dm3 map entity with this `loc` label and `kind`."""
    doc = json.loads(DM3_ENTITIES.read_text(encoding="utf-8"))
    for e in doc.get("entities", []):
        if (e.get("loc") or e.get("name")) == loc and e.get("kind") == kind:
            return (float(e["x"]), float(e["y"]), float(e["z"]))
    raise AssertionError(f"no dm3 entity loc={loc!r} kind={kind!r}")


class TestRegionLoading(unittest.TestCase):
    def setUp(self):
        self.rs = M.load_regions()

    def test_loads_expected_region_count_and_map(self):
        self.assertEqual(self.rs.map, "dm3")
        # 10-16 named regions per the #317 spec; this file ships 13.
        self.assertGreaterEqual(len(self.rs), 10)
        self.assertLessEqual(len(self.rs), 16)

    def test_region_names_unique_and_present(self):
        names = self.rs.names()
        self.assertEqual(len(names), len(set(names)), "region names must be unique")
        # the named control points from the taxonomy must all be present.
        for must in ("RA", "Quad", "Ring", "mega", "RL", "YA", "Pent", "SNG", "LG", "GL"):
            self.assertIn(must, names)

    def test_all_radii_positive(self):
        for r in self.rs.regions:
            self.assertGreater(r.radius_qu, 0.0)


class TestDeterministicNonOverlap(unittest.TestCase):
    """assign() == nearest-region-within-cap, so a point is claimed by exactly one region."""

    def setUp(self):
        self.rs = M.load_regions()

    def _brute_nearest_within_cap(self, x, y, z):
        """Independent reference implementation of the contract."""
        best = None
        best_d = math.inf
        for r in self.rs.regions:
            d = math.sqrt((x - r.cx) ** 2 + (y - r.cy) ** 2 + (z - r.cz) ** 2)
            if d < best_d:
                best_d = d
                best = r
        if best is not None and best_d <= best.radius_qu:
            return best.name
        return None

    def test_assignment_matches_nearest_within_cap_over_grid(self):
        # sweep a coarse 3D grid spanning the dm3 bounding box; assign() must always agree
        # with the independent nearest-within-cap reference (=> deterministic + single-owner).
        for x in range(-1100, 2100, 220):
            for y in range(-1000, 900, 220):
                for z in range(-450, 350, 160):
                    got = self.rs.assign(x, y, z)
                    want = self._brute_nearest_within_cap(x, y, z)
                    self.assertEqual(got, want, f"mismatch at ({x},{y},{z})")

    def test_no_point_is_claimed_by_two_regions(self):
        # Stronger non-overlap statement: for any assigned point, NO OTHER region's center is
        # nearer than the assigning region's. (If two regions both 'contained' a point by
        # radius, nearest-wins still gives it to exactly one — this asserts that explicitly.)
        for x in range(-1100, 2100, 260):
            for y in range(-1000, 900, 260):
                for z in range(-450, 350, 200):
                    name = self.rs.assign(x, y, z)
                    if name is None:
                        continue
                    owner = next(r for r in self.rs.regions if r.name == name)
                    owner_d = owner.dist(x, y, z)
                    for r in self.rs.regions:
                        if r.name == name:
                            continue
                        # no other region is strictly nearer than the owner
                        self.assertGreaterEqual(r.dist(x, y, z), owner_d,
                                                f"{r.name} nearer than owner {name} at ({x},{y},{z})")

    def test_assignment_is_repeatable(self):
        p = (256.0, -704.0, 304.0)
        self.assertEqual(self.rs.assign(*p), self.rs.assign(*p))

    def test_module_level_assign_region_matches_default_set(self):
        for p in [(256, -704, 304), (952, 296, 56), (-512, 448, 96), (9999, 9999, 9999)]:
            self.assertEqual(M.assign_region(*p), self.rs.assign(*p))


class TestSpotChecksPrimaryControlPoints(unittest.TestCase):
    """Each major item's own primary-item coord assigns to its expected named region."""

    def setUp(self):
        self.rs = M.load_regions()

    def test_primary_control_point_coords(self):
        cases = [
            ("RA",   _entity_coord("RA", "ra")),       # the Red Armor
            ("Quad", _entity_coord("Quad", "quad")),   # the Quad artifact
            ("Ring", _entity_coord("Ring", "ring")),   # the Ring of Shadows
            ("mega", _entity_coord("hill", "mh")),     # central Megahealth
            ("RL",   _entity_coord("RL", "rl")),       # Rocket Launcher
            ("YA",   _entity_coord("YA.box", "ya")),   # the Yellow Armor (lives at YA.box)
            ("Pent", _entity_coord("Pent", "pent")),   # the Pentagram artifact
            ("SNG",  _entity_coord("SNG", "sng")),     # Super Nailgun
            ("LG",   _entity_coord("water.LG", "lg")), # Lightning Gun (water)
            ("GL",   _entity_coord("water.GL", "gl")), # Grenade Launcher (water)
        ]
        for want, coord in cases:
            self.assertEqual(self.rs.assign(*coord), want,
                             f"{want} primary coord {coord} did not assign to {want}")


class TestSubPointCollapse(unittest.TestCase):
    """Merged sub-points collapse into their parent region -> #315 phantom shuffles gone."""

    def setUp(self):
        self.rs = M.load_regions()

    def test_ra_subpoints_collapse_into_RA(self):
        # the RA.low<->RA phantom shuffle: RA.low must land in the SAME region as RA.
        ra = self.rs.assign(*_entity_coord("RA", "ra"))
        ra_low = self.rs.assign(*_entity_coord("RA.low", "ng"))
        self.assertEqual(ra, "RA")
        self.assertEqual(ra_low, "RA")
        self.assertEqual(ra, ra_low, "RA.low and RA must be ONE region (no RA.low<->RA leg)")

    def test_ya_subpoints_collapse_into_YA(self):
        # the YA.box<->YA phantom shuffle: YA.box, the YA ledge, and YA.up are all ONE region.
        ya_box = self.rs.assign(*_entity_coord("YA.box", "ya"))
        ya_ledge = self.rs.assign(*_entity_coord("YA", "ssg"))
        ya_up = self.rs.assign(*_entity_coord("YA.up", "shells"))
        self.assertEqual(ya_box, "YA")
        self.assertEqual(ya_ledge, "YA")
        self.assertEqual(ya_up, "YA")
        self.assertEqual(ya_box, ya_ledge, "YA.box and YA must be ONE region (no YA.box<->YA leg)")

    def test_sng_subpoints_collapse_into_SNG(self):
        sng = self.rs.assign(*_entity_coord("SNG", "sng"))
        sng_mh = self.rs.assign(*_entity_coord("SNG.MH", "mh"))
        sng_low = self.rs.assign(*_entity_coord("SNG.low", "nails"))
        self.assertEqual(sng, "SNG")
        self.assertEqual(sng_mh, "SNG")
        self.assertEqual(sng_low, "SNG")

    def test_sng_tele_is_separate_from_SNG(self):
        # SNG.tele is intentionally a DIFFERENT region from the SNG nest.
        sng = self.rs.assign(*_entity_coord("SNG", "sng"))
        sng_tele = self.rs.assign(*_entity_coord("SNG.tele", "nails"))
        self.assertEqual(sng, "SNG")
        self.assertEqual(sng_tele, "SNG.tele")
        self.assertNotEqual(sng, sng_tele)


class TestOutsideAllRegions(unittest.TestCase):
    def setUp(self):
        self.rs = M.load_regions()

    def test_far_points_assign_to_none(self):
        for p in [(5000.0, 5000.0, 5000.0), (-3000.0, 0.0, 0.0), (0.0, 0.0, 4000.0)]:
            self.assertIsNone(self.rs.assign(*p), f"{p} should be outside all regions")


if __name__ == "__main__":
    unittest.main()
