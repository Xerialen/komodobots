"""Tests for catalog_load.py (C2). Pure stdlib; runs under `python -m unittest`.

Follows the komodobots convention: insert scripts/ into sys.path so the module is
imported top-level (`import catalog_load`), not as a package.

Path note: in this staging tree the catalogs live in ../../schema and the fixture in
../../fixtures/dm3_milton_211436. When these files land in the repo, point CATALOG_DIR
at the repo's data/catalog dir (see INTEGRATION.md).
"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import catalog_load  # noqa: E402

REPO_ROOT = HERE.parent
CATALOG_DIR = REPO_ROOT / "data" / "catalog"
FIXTURE_DIR = REPO_ROOT / "data" / "fixtures" / "dm3_milton_211436"


class TestSchemaApplies(unittest.TestCase):
    def test_nineteen_tables(self):
        con = catalog_load.connect()
        tabs = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")]
        self.assertEqual(len(tabs), 19, tabs)  # +damage_events (T5 #393)
        for required in ("maps", "items", "markers", "nav_edges", "demos",
                         "teams", "players", "frag_events", "damage_events", "actor_ticks",
                         "actor_visibility", "audio_cues", "region_control_timeline"):
            self.assertIn(required, tabs)


class TestCatalogRoundTrip(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.con, cls.summary = catalog_load.build(CATALOG_DIR, FIXTURE_DIR)

    def test_one_map_dm3(self):
        row = self.con.execute("SELECT name, diagonal, server_fps FROM maps").fetchone()
        self.assertEqual(row[0], "dm3")
        self.assertAlmostEqual(row[1], 3797.1, places=1)
        self.assertEqual(row[2], 77.0)

    def test_all_51_items_loaded(self):
        (n,) = self.con.execute("SELECT COUNT(*) FROM items").fetchone()
        self.assertEqual(n, 51)
        # the timed items have verified respawns folded in (B3)
        (ra,) = self.con.execute(
            "SELECT respawn_seconds FROM items WHERE item_type='ra'").fetchone()
        self.assertEqual(ra, 20)
        (quad,) = self.con.execute(
            "SELECT respawn_seconds FROM items WHERE item_type='quad'").fetchone()
        self.assertEqual(quad, 60)

    def test_markers_299_with_234_static(self):
        (total,) = self.con.execute("SELECT COUNT(*) FROM markers").fetchone()
        (static,) = self.con.execute(
            "SELECT COUNT(*) FROM markers WHERE origin_x IS NOT NULL").fetchone()
        self.assertEqual(total, 299)
        self.assertEqual(static, 234)

    def test_nav_edges_loaded_with_distances(self):
        (n,) = self.con.execute("SELECT COUNT(*) FROM nav_edges").fetchone()
        self.assertGreater(n, 1000)
        # edges between two static markers must carry a straight-line distance
        (with_dist,) = self.con.execute(
            "SELECT COUNT(*) FROM nav_edges WHERE distance_qu IS NOT NULL").fetchone()
        self.assertGreater(with_dist, 0)

    def test_teams_book_vs_3b(self):
        names = {r[0] for r in self.con.execute("SELECT name FROM teams")}
        self.assertEqual(names, {"Book", "3b"})
        # side A is Book (first listed)
        (side_a,) = self.con.execute(
            "SELECT name FROM teams WHERE side='A'").fetchone()
        self.assertEqual(side_a, "Book")

    def test_score_reconciles_294_80(self):
        # the score comes from overview (authoritative), surfaced in the summary
        tf = self.summary["fixture"]["team_frags"]
        self.assertEqual(tf["Book"], 294)
        self.assertEqual(tf["3b"], 80)
        pf = self.summary["fixture"]["player_frags"]
        self.assertEqual(sum(v for k, v in pf.items()
                             if k in ("Milton", "wimsuit", "sae", "stepcop")), 294)
        self.assertEqual(sum(v for k, v in pf.items()
                             if k in ("gLAd", "gor", "Zepp", "SS")), 80)

    def test_frag_events_round_trip(self):
        # the sample window has 9 Milton frags; all reference real player rows
        (n,) = self.con.execute("SELECT COUNT(*) FROM frag_events").fetchone()
        self.assertEqual(n, 9)
        # every killer in the sample is Milton
        rows = self.con.execute(
            """SELECT p.handle FROM frag_events f
               JOIN players p ON p.player_id = f.killer_id""").fetchall()
        self.assertTrue(all(r[0] == "milton" for r in rows))


if __name__ == "__main__":
    unittest.main()
