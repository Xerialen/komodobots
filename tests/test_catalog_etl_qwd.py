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
    # Origins must stay inside the dm3 AABB ([-984,-960,-416]..[2048,1136,496]) because
    # they now also flow into actor_ticks (self ego row), which validate_catalog AABB-checks.
    ep1 = etl._pack_episode(frames(n_frames // 2, 0.0), 0)
    ep2 = etl._pack_episode(frames(n_frames // 2, 1000.0), n_frames // 2)
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


def _synthetic_demo_with_observed():
    """A 1-episode synthetic demo plus an observed-OTHER payload, mirroring the real
    extract_demo() contract (frames carry abs_t_s; `observed.others` is the packed
    per-other timeline). Used to test the actor_ticks (agent_observation) join."""
    seg = []
    base_t = 100.0
    n = 60  # ~0.78 s @ 13 ms/frame — long enough for an unfed other to go stale
    for i in range(n):
        seg.append({
            "msec": 13, "origin": [100.0 + i, 50.0, 0.0], "velocity": [300.0, 0.0, 0.0],
            "angles": [0.0, 90.0, 0.0], "move": [400, 0, 0], "buttons": 2,
            "onground": True, "pm_code": 0, "reference_interpolated": False,
            "abs_t_s": round(base_t + i * 0.013, 4),  # 100.000 .. 100.767
        })
    ep = etl._pack_episode(seg, 0)
    # Other player slot 7: received samples spanning the whole episode (well inside dm3
    # AABB). One row per [t, ox,oy,oz, vx,vy,vz, pitch,yaw,roll, alive, ong, solid, pm].
    # Last sample (dead) is at-or-before the final ticks, so late ticks carry alive=0.
    other7 = [
        [100.00, 200.0, -100.0, 0.0, 100, 0, 0, 0.0, 45.0, 0.0, 1, 1, 1, 0],
        [100.30, 240.0, -120.0, 0.0, 120, 0, 0, 0.0, 50.0, 0.0, 1, 0, 1, 0],
        [100.60, 260.0, -130.0, 0.0, 0, 0, 0, 0.0, 60.0, 0.0, 0, 0, 1, 0],  # dead, t<=last tick
    ]
    # Other player slot 9: a SINGLE early sample, then silence — must go stale and drop
    # out of the late ticks (final tick 100.767 is >0.5 s past 100.00).
    other9 = [[100.00, -500.0, 800.0, 0.0, 0, 0, 0, 0.0, 10.0, 0.0, 1, 1, 1, 0]]
    return {
        "ok": True, "demo": "obs.qwd", "sha256": "feedface", "map_level": "The Abandoned Base",
        "playernum": 3, "n_frames": n, "coverage": 1.0, "duration_s": n * 0.013, "server_fps": 77.0,
        "episodes": [ep],
        "observed": {"ok": True, "self_playernum": 3, "n_playerinfo": 4,
                     "bodies": n, "bodies_clean": n, "stop_reasons": {},
                     "others": {"7": other7, "9": other9}},
    }


class TestObservedOthersActorTicks(unittest.TestCase):
    def setUp(self):
        self.con = catalog_load.connect()
        catalog_load.load_maps(self.con, CATALOG_DIR / "maps.seed.json")
        self.map_id = self.con.execute("SELECT map_id FROM maps WHERE name='dm3'").fetchone()[0]

    def test_nearest_observed_window(self):
        samp = {"t": [100.0, 100.2, 100.4], "rows": [["a"], ["b"], ["c"]]}
        # at-or-before pick
        self.assertEqual(etl._nearest_observed(samp, 100.25, 0.5)[0], "b")
        self.assertEqual(etl._nearest_observed(samp, 100.41, 0.5)[0], "c")
        # a hair before the first sample, inside window -> forward pick
        self.assertEqual(etl._nearest_observed(samp, 99.9, 0.5)[0], "a")
        # far past the last sample -> stale -> None
        self.assertIsNone(etl._nearest_observed(samp, 101.5, 0.5))
        # far before the first sample -> None
        self.assertIsNone(etl._nearest_observed(samp, 90.0, 0.5))

    def test_actor_ticks_self_and_others(self):
        rec = _synthetic_demo_with_observed()
        ins = etl.insert_demo(self.con, self.map_id, rec, "train")
        self.assertEqual(ins["observed_others"], 2)        # slots 7 and 9 registered
        (n_pt0,) = self.con.execute("SELECT COUNT(*) FROM player_ticks").fetchone()
        self.assertGreater(ins["actor_ticks"], n_pt0)      # self ego rows + observed others
        # self ego appears in actor_ticks for every tick (player_ticks count == self rows)
        (n_pt,) = self.con.execute("SELECT COUNT(*) FROM player_ticks").fetchone()
        self_pid = ins["player_id"]
        (n_self_actor,) = self.con.execute(
            "SELECT COUNT(*) FROM actor_ticks WHERE actor_id=?", (self_pid,)).fetchone()
        self.assertEqual(n_self_actor, n_pt)
        # exactly 2 distinct OTHER actors populated
        (n_other_actors,) = self.con.execute(
            "SELECT COUNT(DISTINCT actor_id) FROM actor_ticks WHERE actor_id<>?",
            (self_pid,)).fetchone()
        self.assertEqual(n_other_actors, 2)
        # every actor_ticks row references a real player and a real (episode,tick)
        self.assertEqual(self.con.execute(
            """SELECT COUNT(*) FROM actor_ticks a
               WHERE NOT EXISTS (SELECT 1 FROM players p WHERE p.player_id=a.actor_id)
                  OR NOT EXISTS (SELECT 1 FROM player_ticks t
                     WHERE t.episode_id=a.episode_id AND t.tick=a.tick)""").fetchone()[0], 0)
        # the dead late-sample for slot 7 lands as alive=0 somewhere
        self.assertGreater(self.con.execute(
            "SELECT COUNT(*) FROM actor_ticks WHERE alive=0").fetchone()[0], 0)

    def test_stale_other_drops_out(self):
        # slot 9 has one sample at t=100.00 only; ticks past the 0.5s window must NOT
        # carry it, while slot 7 (samples through 100.39) stays present late.
        rec = _synthetic_demo_with_observed()
        ins = etl.insert_demo(self.con, self.map_id, rec, "train")
        slot9_handle = "qwd:obs#o9"
        s9 = self.con.execute("SELECT player_id FROM players WHERE handle=?", (slot9_handle,)).fetchone()[0]
        # last tick's absolute time ~100.377; slot 9 last seen 100.00 -> >0.5s stale -> absent
        last_tick = self.con.execute("SELECT MAX(tick) FROM player_ticks").fetchone()[0]
        present_late = self.con.execute(
            "SELECT COUNT(*) FROM actor_ticks WHERE actor_id=? AND tick=?",
            (s9, last_tick)).fetchone()[0]
        self.assertEqual(present_late, 0)
        # slot 9 DID appear on the very first tick (within window of its single sample)
        present_early = self.con.execute(
            "SELECT COUNT(*) FROM actor_ticks WHERE actor_id=? AND tick=0", (s9,)).fetchone()[0]
        self.assertEqual(present_early, 1)

    def test_populated_actor_ticks_validates(self):
        catalog_load.load_items(self.con, CATALOG_DIR / "item_catalog.dm3.json", self.map_id)
        catalog_load.load_markers(self.con, CATALOG_DIR / "markers.dm3.json", self.map_id)
        catalog_load.load_nav_edges(self.con, CATALOG_DIR / "nav_edges.dm3.json", self.map_id)
        etl.insert_demo(self.con, self.map_id, _synthetic_demo_with_observed(), "train")
        errs = validate_catalog.validate(self.con, raise_on_error=False)
        self.assertEqual(errs, [], errs)


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
