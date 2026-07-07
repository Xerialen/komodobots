"""Gating stdlib tests for scripts/carve_catalog_slice.py (plans/instrument-pool-growth.md §3.2).

The fixture builds its schema by executing the COMMITTED scripts/catalog_schema.sql (so the
test's FK web cannot drift from the real one — the audit-M1 lesson: a hand-listed subset of
tables passes a hand-built fixture while failing the real catalog's FK check), populates the
full web (maps/players/items/markers are FK targets of carved rows), and locks: subset-only
copy, FK-clean output, fail-closed on missing shas / unknown tables / summary mismatch, and the
vintage-gap tolerance (a source WITHOUT a current-schema table carves with a notice, never a
crash). Windows-portable: tempdir-only paths, every sqlite connection closed before cleanup
(the WinError-32 precedent in test_catalog_etl_mvd).
"""

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import carve_catalog_slice as CV  # noqa: E402

SCHEMA_SQL = (REPO_ROOT / "scripts" / "catalog_schema.sql").read_text(encoding="utf-8")

SHA = {i: format(i, "x") * 16 for i in (1, 2, 3)}   # 64-char distinct fake shas


def build_fixture(db_path, *, drop_tables=(), extra_table=None):
    con = sqlite3.connect(db_path)
    con.executescript(SCHEMA_SQL)
    for t in drop_tables:
        con.execute(f"DROP TABLE {t}")
    if extra_table:
        con.execute(f"CREATE TABLE {extra_table} (x INTEGER)")
    con.execute("INSERT INTO maps (map_id, name, x_min, x_max, y_min, y_max, z_min, z_max, "
                "diagonal) VALUES (1, 'dm3', -984, 2048, -960, 1136, -416, 496, 3797.1)")
    con.execute("INSERT INTO markers (map_id, marker_id, origin_x, origin_y, origin_z) "
                "VALUES (1, 7, 0, 0, 0)")
    con.execute("INSERT INTO nav_edges (map_id, from_marker, to_marker, edge_idx) "
                "VALUES (1, 7, 7, 0)")
    con.execute("INSERT INTO items (item_id, map_id, classname, item_type, category, "
                "origin_x, origin_y, origin_z, static_value) "
                "VALUES (5, 1, 'item_armorInv', 'ra', 'armor', 0, 0, 0, 1.0)")
    con.execute("INSERT INTO item_value (map_id, item_type, method, importance_norm) "
                "VALUES (1, 'ra', 'pearson_control_frags', 1.0)")
    for pid in (1, 2):
        con.execute("INSERT INTO players (player_id, handle) VALUES (?, ?)", (pid, f"p{pid}"))
    for did in (1, 2, 3):
        con.execute("INSERT INTO demos (demo_id, path, source, map_id, sha256) "
                    "VALUES (?, ?, 'mvd', 1, ?)", (did, f"d{did}.mvd", SHA[did]))
        con.execute("INSERT INTO teams (team_id, demo_id, name) VALUES (?, ?, 'red')",
                    (did * 10, did))
        con.execute("INSERT INTO item_events (demo_id, item_id, t_s, event_kind, player_id, "
                    "team_id) VALUES (?, 5, 1.0, 'pickup', 1, ?)", (did, did * 10))
        eid = did * 100
        con.execute("INSERT INTO episodes (episode_id, demo_id, player_id, map_id, start_tick, "
                    "end_tick, n_steps, split) VALUES (?, ?, 1, 1, 0, 1, 2, 'val')", (eid, did))
        for tick in (0, 1):
            con.execute("INSERT INTO player_ticks (episode_id, tick, t_s, ox, oy, oz, "
                        "vx, vy, vz, yaw, pitch, hspeed, onground) "
                        "VALUES (?, ?, ?, 0,0,0, 0,0,0, 0,0, 200.0, 0)", (eid, tick, tick * 0.013))
            con.execute("INSERT INTO actions (episode_id, tick, label_source) "
                        "VALUES (?, ?, 'idm')", (eid, tick))
        con.execute("INSERT INTO actor_ticks (episode_id, tick, actor_id, team_id, ox, oy, oz) "
                    "VALUES (?, 0, 2, ?, 0, 0, 0)", (eid, did * 10))
    con.commit()
    con.close()


def table_counts(db_path):
    con = sqlite3.connect(db_path)
    try:
        names = [n for (n,) in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        return {n: con.execute(f"SELECT COUNT(*) FROM {n}").fetchone()[0] for n in names}
    finally:
        con.close()


def write_summary(path, src_db):
    counts = table_counts(src_db)
    Path(path).write_text(json.dumps(
        {"etl": {"table_counts": {t: counts[t] for t in ("demos", "episodes", "player_ticks")}}}),
        encoding="utf-8")


def write_list(path, shas):
    Path(path).write_text("# test subset\n" + "\n".join(shas) + "\n", encoding="utf-8")


class TestCarve(unittest.TestCase):
    def _setup(self, td, **fixture_kw):
        src = Path(td) / "src.sqlite"
        build_fixture(src, **fixture_kw)
        summary = Path(td) / "summary.json"
        write_summary(summary, src)
        lst = Path(td) / "demos.txt"
        write_list(lst, [SHA[1], SHA[2]])
        return src, summary, lst, Path(td) / "out.sqlite"

    def test_carve_subsets_and_passes_fk_check(self):
        with tempfile.TemporaryDirectory() as td:
            src, summary, lst, out = self._setup(td)
            counts = CV.carve(src, out, lst, summary)
            self.assertEqual(counts["demos"], 2)
            self.assertEqual(counts["episodes"], 2)
            self.assertEqual(counts["player_ticks"], 4)
            self.assertEqual(counts["actions"], 4)
            self.assertEqual(counts["teams"], 2)
            self.assertEqual(counts["actor_ticks"], 2)
            self.assertEqual(counts["item_events"], 2)
            # FK-target static tables are whole-copied — omitting them was the audit-M1 hole
            self.assertEqual(counts["maps"], 1)
            self.assertEqual(counts["players"], 2)
            self.assertEqual(counts["items"], 1)
            got = table_counts(out)
            con = sqlite3.connect(out)
            try:
                shas = {s for (s,) in con.execute("SELECT lower(sha256) FROM demos")}
                self.assertEqual(shas, {SHA[1], SHA[2]}, "only-subset rows")
                con.execute("PRAGMA foreign_keys=ON")
                self.assertEqual(con.execute("PRAGMA foreign_key_check").fetchall(), [])
                # schema identical to the SOURCE (same table set)
                self.assertEqual(set(got), set(table_counts(src)))
            finally:
                con.close()

    def test_missing_sha_refused(self):
        with tempfile.TemporaryDirectory() as td:
            src, summary, lst, out = self._setup(td)
            write_list(lst, [SHA[1], "f" * 64])
            with self.assertRaises(SystemExit) as cm:
                CV.carve(src, out, lst, summary)
            self.assertIn("missing from source", str(cm.exception))
            self.assertFalse(out.exists())

    def test_unknown_source_table_refused(self):
        with tempfile.TemporaryDirectory() as td:
            src, summary, lst, out = self._setup(td, extra_table="mystery_rows")
            with self.assertRaises(SystemExit) as cm:
                CV.carve(src, out, lst, summary)
            self.assertIn("mystery_rows", str(cm.exception))

    def test_vintage_gap_tolerated_with_notice(self):
        # the Phase-4 source predates damage_events/region_control_timeline — a carve must
        # proceed (documented waiver) and only NOTE the absent tables, never crash.
        with tempfile.TemporaryDirectory() as td:
            src, summary, lst, out = self._setup(
                td, drop_tables=("damage_events", "region_control_timeline"))
            with self.assertLogs(CV.LOGGER, level="WARNING") as logs:
                counts = CV.carve(src, out, lst, summary)
            self.assertEqual(counts["demos"], 2)
            self.assertNotIn("damage_events", counts)
            self.assertTrue(any("vintage gap" in m for m in logs.output))

    def test_summary_mismatch_refused(self):
        with tempfile.TemporaryDirectory() as td:
            src, summary, lst, out = self._setup(td)
            rec = json.loads(summary.read_text(encoding="utf-8"))
            rec["etl"]["table_counts"]["player_ticks"] += 1
            summary.write_text(json.dumps(rec), encoding="utf-8")
            with self.assertRaises(SystemExit) as cm:
                CV.carve(src, out, lst, summary)
            self.assertIn("not the recorded", str(cm.exception))

    def test_existing_output_refused(self):
        with tempfile.TemporaryDirectory() as td:
            src, summary, lst, out = self._setup(td)
            out.write_bytes(b"precious")
            with self.assertRaises(SystemExit):
                CV.carve(src, out, lst, summary)
            self.assertEqual(out.read_bytes(), b"precious")

    def test_duplicate_or_empty_list_refused(self):
        with tempfile.TemporaryDirectory() as td:
            src, summary, lst, out = self._setup(td)
            write_list(lst, [SHA[1], SHA[1]])
            with self.assertRaises(SystemExit):
                CV.carve(src, out, lst, summary)
            write_list(lst, [])
            with self.assertRaises(SystemExit):
                CV.carve(src, out, lst, summary)


if __name__ == "__main__":
    unittest.main()
