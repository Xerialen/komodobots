"""Tests for validate_catalog.py (C4). Pure stdlib; runs under `python -m unittest`."""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import catalog_load       # noqa: E402
import validate_catalog as V  # noqa: E402

REPO_ROOT = HERE.parent
CATALOG_DIR = REPO_ROOT / "data" / "catalog"
FIXTURE_DIR = REPO_ROOT / "data" / "fixtures" / "dm3_milton_211436"
STATS = CATALOG_DIR / "normalization_stats.template.json"


class TestValidPasses(unittest.TestCase):
    def test_real_catalog_is_valid(self):
        con, _ = catalog_load.build(CATALOG_DIR, FIXTURE_DIR)
        errs = V.validate(con, STATS, expect_items=51, raise_on_error=False)
        self.assertEqual(errs, [], errs)

    def test_validate_raises_nothing_on_clean(self):
        con, _ = catalog_load.build(CATALOG_DIR, FIXTURE_DIR)
        # should not raise
        V.validate(con, STATS, expect_items=51)

    def test_normalization_stats_valid(self):
        self.assertEqual(V.validate_normalization_stats(STATS), [])


class TestSeededFailures(unittest.TestCase):
    """Each seeds one bad row and asserts the matching validator catches it."""

    def setUp(self):
        self.con, _ = catalog_load.build(CATALOG_DIR, FIXTURE_DIR)

    def test_bad_static_value_caught(self):
        self.con.execute(
            "INSERT INTO items (map_id, classname, item_type, category, "
            "origin_x, origin_y, origin_z, static_value) "
            "VALUES (1,'weapon_x','rl','weapon',0,0,0,9.9)")
        errs = V.validate_items(self.con)
        self.assertTrue(any("static_value" in e for e in errs), errs)

    def test_unknown_item_type_caught(self):
        self.con.execute(
            "INSERT INTO items (map_id, classname, item_type, category, "
            "origin_x, origin_y, origin_z, static_value) "
            "VALUES (1,'weapon_bfg','bfg','weapon',0,0,0,0.5)")
        errs = V.validate_items(self.con)
        self.assertTrue(any("unknown item_type" in e for e in errs), errs)

    def test_orphan_nav_edge_caught(self):
        # SQLite's FK enforcement would block this at insert; the validator exists
        # for engines that treat FKs as metadata only (DuckDB). Disable FKs to
        # simulate that and prove the validator catches the orphan itself.
        self.con.execute("PRAGMA foreign_keys = OFF")
        self.con.execute(
            "INSERT INTO nav_edges (map_id, from_marker, to_marker, edge_idx) "
            "VALUES (1, 99999, 99998, 0)")
        errs = V.validate_nav_edges(self.con)
        self.assertTrue(any("missing marker" in e for e in errs), errs)

    def test_validate_all_raises_with_full_list(self):
        self.con.execute(
            "INSERT INTO items (map_id, classname, item_type, category, "
            "origin_x, origin_y, origin_z, static_value) "
            "VALUES (1,'weapon_x','bfg','weapon',0,0,0,9.9)")
        with self.assertRaises(V.CatalogError) as ctx:
            V.validate(self.con, STATS, expect_items=51)
        # the bad row trips both the count and the type/value checks
        self.assertTrue(len(ctx.exception.errors) >= 2, ctx.exception.errors)

    def test_bad_normalization_method_caught(self):
        bad = {"global": {"x": {"method": "nope"}},
               "per_map": {"dm3": {"pos_x": {"method": "minmax", "min": 10, "max": 5}}}}
        import json, tempfile, os
        fd, p = tempfile.mkstemp(suffix=".json")
        os.write(fd, json.dumps(bad).encode())
        os.close(fd)
        try:
            errs = V.validate_normalization_stats(Path(p))
            self.assertTrue(any("unknown method" in e for e in errs), errs)
            self.assertTrue(any("min must be < max" in e for e in errs), errs)
        finally:
            os.unlink(p)


if __name__ == "__main__":
    unittest.main()
