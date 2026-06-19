"""Tests for catalog_etl_qwd.py (P1). Pure stdlib; runs under `python -m unittest`.

Exercises the pure ETL logic WITHOUT needing the heavy .qwd corpus (CI has no demos):
  - assign_splits: group-by-demo split is total + has the no-straddle property
  - _pack_episode: state+action row shape, tick/t_s monotonicity, hspeed correctness
  - insert_demo: episodes/player_ticks/actions land with matching counts + FK integrity
  - load_fixture_relational: the committed fixture's team-layer rows load + decode
    (frag_events, item_events, region_control_timeline from bucketStates)
  - the populated catalog passes validate_catalog and no demo straddles a split

Follows the komodobots convention: scripts/ on sys.path, modules imported top-level.
"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import catalog_load  # noqa: E402
import catalog_etl_qwd as etl  # noqa: E402
import validate_catalog  # noqa: E402

REPO_ROOT = HERE.parent
CATALOG_DIR = REPO_ROOT / "data" / "catalog"
FIXTURE_DIR = REPO_ROOT / "data" / "fixtures" / "dm3_milton_211436"


def _synthetic_demo(name="syn.qwd", n_frames=200, playernum=3):
    """A fake extract_demo() result: two episodes of straight-line motion with inputs.
    Mirrors the real extractor's contract so insert_demo can be tested without a .qwd."""
    def frames(n, x0):
        seg = []
        x = x0
        for i in range(n):
            seg.append({
                "msec": 13, "origin": [x, 0.0, 0.0], "velocity": [300.0, 40.0, 0.0],
                "angles": [0.0, 90.0, 0.0], "move": [400, 0, 0], "buttons": 2,
                "onground": (i % 2 == 0), "pm_code": 0, "reference_interpolated": False,
            })
            x += 4.0
        return seg
    ep1 = etl._pack_episode(frames(n_frames // 2, 0.0), 0)
    ep2 = etl._pack_episode(frames(n_frames // 2, 5000.0), n_frames // 2)
    return {
        "ok": True, "demo": name, "sha256": "deadbeef" + name,
        "map_level": "The Abandoned Base", "playernum": playernum,
        "n_frames": n_frames, "coverage": 0.9, "duration_s": n_frames * 0.013,
        "server_fps": 77.0, "episodes": [ep1, ep2],
    }


class TestAssignSplits(unittest.TestCase):
    def test_total_and_no_empty_train(self):
        for n in (1, 2, 3, 5, 8, 20, 100):
            labels = etl.assign_splits(n)
            self.assertEqual(len(labels), n)
            self.assertIn("train", labels)
            # every label is one of the three (a demo gets exactly ONE -> no straddle)
            self.assertTrue(set(labels) <= {"train", "val", "test"})

    def test_val_and_test_present_when_enough(self):
        labels = etl.assign_splits(20)
        self.assertIn("val", labels)
        self.assertIn("test", labels)


class TestPackEpisode(unittest.TestCase):
    def test_row_shape_and_monotonic(self):
        seg = [{"msec": 13, "origin": [i * 4.0, 1.0, 2.0], "velocity": [300.0, 40.0, 5.0],
                "angles": [1.0, 2.0, 3.0], "move": [400, -200, 0], "buttons": 3,
                "onground": True, "pm_code": 1, "reference_interpolated": False}
               for i in range(10)]
        ep = etl._pack_episode(seg, start_tick=100)
        self.assertEqual(ep["start"], 100)
        self.assertEqual(ep["n"], 10)
        self.assertEqual(ep["end"], 109)
        ticks = [r["tick"] for r in ep["frames"]]
        self.assertEqual(ticks, list(range(10)))
        ts = [r["t_s"] for r in ep["frames"]]
        self.assertEqual(ts, sorted(ts))  # monotonically non-decreasing
        # hspeed = hypot(vx, vy)
        self.assertAlmostEqual(ep["frames"][0]["hspeed"], (300.0 ** 2 + 40.0 ** 2) ** 0.5, places=2)
        # action fields carried through
        self.assertEqual(ep["frames"][0]["fwd"], 400)
        self.assertEqual(ep["frames"][0]["side"], -200)
        self.assertEqual(ep["frames"][0]["buttons"], 3)


class TestInsertDemo(unittest.TestCase):
    def setUp(self):
        self.con = catalog_load.connect()
        catalog_load.load_maps(self.con, CATALOG_DIR / "maps.seed.json")
        self.map_id = self.con.execute("SELECT map_id FROM maps WHERE name='dm3'").fetchone()[0]

    def test_counts_and_fk(self):
        rec = _synthetic_demo(n_frames=200)
        ins = etl.insert_demo(self.con, self.map_id, rec, "train")
        self.assertEqual(ins["episodes"], 2)
        self.assertEqual(ins["player_ticks"], 200)
        self.assertEqual(ins["actions"], 200)
        # one player_ticks row per actions row, FK to episodes holds
        (n_pt,) = self.con.execute("SELECT COUNT(*) FROM player_ticks").fetchone()
        (n_act,) = self.con.execute("SELECT COUNT(*) FROM actions").fetchone()
        self.assertEqual(n_pt, n_act)
        # actions reference real player_ticks (the schema FK is (episode_id,tick))
        orphan = self.con.execute(
            """SELECT COUNT(*) FROM actions a
               WHERE NOT EXISTS (SELECT 1 FROM player_ticks pt
                 WHERE pt.episode_id=a.episode_id AND pt.tick=a.tick)""").fetchone()[0]
        self.assertEqual(orphan, 0)
        # label fidelity tier recorded
        (src,) = self.con.execute("SELECT DISTINCT label_source FROM actions").fetchone()
        self.assertEqual(src, "qwd_usercmd")

    def test_split_does_not_straddle(self):
        # two demos, different splits; assert each demo's episodes share one split.
        etl.insert_demo(self.con, self.map_id, _synthetic_demo("a.qwd", 120, 3), "train")
        etl.insert_demo(self.con, self.map_id, _synthetic_demo("b.qwd", 120, 4), "test")
        rows = self.con.execute(
            "SELECT demo_id, COUNT(DISTINCT split) FROM episodes GROUP BY demo_id").fetchall()
        self.assertTrue(rows)
        for _demo_id, n_splits in rows:
            self.assertEqual(n_splits, 1, "a demo straddles >1 split")


class TestFixtureRelational(unittest.TestCase):
    def setUp(self):
        self.con = catalog_load.connect()
        catalog_load.load_maps(self.con, CATALOG_DIR / "maps.seed.json")
        self.map_id = self.con.execute("SELECT map_id FROM maps WHERE name='dm3'").fetchone()[0]

    def test_fixture_team_layer_loads(self):
        summ = etl.load_fixture_relational(self.con, FIXTURE_DIR, self.map_id)
        # teams, frag_events, item_events, region_control_timeline all non-empty
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM teams").fetchone()[0], 2)
        self.assertGreater(self.con.execute("SELECT COUNT(*) FROM frag_events").fetchone()[0], 0)
        self.assertGreater(summ["n_item_events"], 0)
        self.assertGreater(summ["n_region_control"], 0)
        # region_control rows decode to in-[0,1] control fractions
        bad = self.con.execute(
            """SELECT COUNT(*) FROM region_control_timeline
               WHERE teamA_control NOT BETWEEN 0 AND 1
                  OR teamB_control NOT BETWEEN 0 AND 1""").fetchone()[0]
        self.assertEqual(bad, 0)

    def test_populated_catalog_validates(self):
        # full static spine + a synthetic demo + fixture team layer -> validate passes.
        catalog_load.load_items(self.con, CATALOG_DIR / "item_catalog.dm3.json", self.map_id)
        catalog_load.load_markers(self.con, CATALOG_DIR / "markers.dm3.json", self.map_id)
        catalog_load.load_nav_edges(self.con, CATALOG_DIR / "nav_edges.dm3.json", self.map_id)
        etl.insert_demo(self.con, self.map_id, _synthetic_demo("v.qwd", 100, 5), "train")
        etl.load_fixture_relational(self.con, FIXTURE_DIR, self.map_id)
        errs = validate_catalog.validate(self.con, raise_on_error=False)
        self.assertEqual(errs, [], errs)


if __name__ == "__main__":
    unittest.main()
