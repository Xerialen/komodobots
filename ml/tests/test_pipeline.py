"""ml/ tests — run by the NON-GATING ml-tests.yml CI (installs requirements first).

Split into:
  * dependency-free tests (Welford, parity-of-imports) — always run,
  * DuckDB/pyarrow smoke tests — skipped if those deps are absent, so the file is
    importable even in the stdlib-only environment (it just skips the heavy cases).
"""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ML = HERE.parent
REPO_ROOT = ML.parent
sys.path.insert(0, str(ML / "pipeline"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import normalize_fit as NF   # noqa: E402  (dependency-free core)

CATALOG_DIR = REPO_ROOT / "data" / "catalog"
FIXTURE_DIR = REPO_ROOT / "data" / "fixtures" / "dm3_milton_211436"
STATS = CATALOG_DIR / "normalization_stats.template.json"

_HAVE_DUCKDB = importlib.util.find_spec("duckdb") is not None
_HAVE_PYARROW = importlib.util.find_spec("pyarrow") is not None


class TestWelford(unittest.TestCase):
    def test_mean_std(self):
        w = NF.fit_feature([2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0])
        self.assertAlmostEqual(w.mean, 5.0, places=9)
        self.assertAlmostEqual(w.std, 2.0, places=9)  # population std (ddof=0)
        self.assertEqual((w.lo, w.hi), (2.0, 9.0))

    def test_chan_merge_matches_single_pass(self):
        data = [1.0, 2.0, 3.0, 10.0, 20.0, 30.0, 7.0]
        full = NF.fit_feature(data)
        a = NF.fit_feature(data[:3])
        b = NF.fit_feature(data[3:])
        merged = a.merge(b)
        self.assertAlmostEqual(merged.mean, full.mean, places=9)
        self.assertAlmostEqual(merged.std, full.std, places=9)
        self.assertEqual(merged.n, full.n)

    def test_specs_emit_valid_methods(self):
        w = NF.fit_feature([1.0, 2.0, 3.0])
        self.assertEqual(w.zscore_spec()["method"], "zscore")
        self.assertEqual(w.minmax_spec(clip=[0, 10])["method"], "minmax")


class TestParityImport(unittest.TestCase):
    def test_ml_imports_shared_in_tree_features(self):
        # the parity guarantee: ml/ uses the SAME transforms as the in-tree path
        from features import transforms as T
        self.assertAlmostEqual(T.minmax(1499.0, -984.0, 2048.0), 2483.0 / 3032.0, places=9)


@unittest.skipUnless(_HAVE_DUCKDB and _HAVE_PYARROW, "duckdb/pyarrow not installed")
class TestBuildFeaturesSmoke(unittest.TestCase):
    def test_emits_parquet_and_pit_join(self):
        import build_features as BF
        norm = json.loads(STATS.read_text(encoding="utf-8"))
        rows = BF.build_actor_features(FIXTURE_DIR, norm)
        self.assertEqual(len(rows), 8)            # 8 actors
        self.assertTrue(all("pos_x_n" in r for r in rows))
        # Milton holds quad in the snapshot
        milton = next(r for r in rows if r["actor"] == "Milton")
        self.assertEqual(milton["has_quad"], 1)

        with tempfile.TemporaryDirectory() as d:
            out = BF.emit_parquet(rows, Path(d) / "shard.parquet")
            import pyarrow.parquet as pq
            tbl = pq.read_table(out)
            self.assertEqual(tbl.num_rows, 8)

        con, _ = __import__("catalog_load").build(CATALOG_DIR, FIXTURE_DIR)
        pit = BF.pit_join_demo(con, FIXTURE_DIR)
        self.assertEqual(len(pit), 9)             # 9 frags in the sample window
        # ASOF must attach a weapon picked at-or-before each frag (no future leak)
        for t, killer, victim, weapon, picked_at in pit:
            if picked_at is not None:
                self.assertLessEqual(picked_at, t)


def _tiny_catalog(path: Path) -> None:
    """Build a minimal synthetic catalog (stdlib sqlite3) with a TRAIN and a VAL
    episode, each with self ego rows (player_ticks + actor_ticks) and observed-other
    actor_ticks rows, so the P3 fit/shard path can be exercised end-to-end without the
    real corpus."""
    import sqlite3

    sql = (REPO_ROOT / "data" / "catalog" / "catalog.sql").read_text(encoding="utf-8")
    con = sqlite3.connect(str(path))
    con.executescript(sql)
    con.execute("""INSERT INTO maps
        (map_id, name, x_min, x_max, y_min, y_max, z_min, z_max, diagonal)
        VALUES (1, 'dm3', -984.0, 2048.0, -960.0, 1136.0, -416.0, 496.0, 3797.1)""")
    con.execute("""INSERT INTO demos (demo_id, path, source, map_id, sha256)
                   VALUES (1, 'd.qwd', 'qwd', 1, 'deadbeef')""")
    for pid in (1, 2, 3):
        con.execute("INSERT INTO players (player_id, handle, is_bot) VALUES (?, ?, 0)", (pid, f"p{pid}", ))
    # episode 1 = train (self=p1), episode 2 = val (self=p1)
    con.execute("""INSERT INTO episodes (episode_id, demo_id, player_id, map_id, start_tick, end_tick, n_steps, split)
                   VALUES (1,1,1,1,0,99,100,'train')""")
    con.execute("""INSERT INTO episodes (episode_id, demo_id, player_id, map_id, start_tick, end_tick, n_steps, split)
                   VALUES (2,1,1,1,0,49,50,'val')""")

    def add(eid, ntk, vx_base):
        for tk in range(ntk):
            vx = float(vx_base + tk)
            con.execute("""INSERT INTO player_ticks
                (episode_id, tick, t_s, msec, ox, oy, oz, vx, vy, vz, pitch, yaw, roll, hspeed, onground)
                VALUES (?,?,?,?, ?,?,?, ?,?,?, ?,?,?, ?,?)""",
                (eid, tk, tk * 0.013, 13, 100.0 + tk, 50.0, -10.0, vx, 20.0, 0.0, 0.0, 45.0, 0.0,
                 (vx * vx + 400.0) ** 0.5, 1))
            # self ego in actor_ticks
            con.execute("""INSERT INTO actor_ticks
                (episode_id, tick, actor_id, alive, ox, oy, oz, vx, vy, vz, pitch, yaw, roll, hspeed)
                VALUES (?,?,?,?, ?,?,?, ?,?,?, ?,?,?, ?)""",
                (eid, tk, 1, 1, 100.0 + tk, 50.0, -10.0, vx, 20.0, 0.0, 0.0, 45.0, 0.0, 0.0))
            # two observed-others at varying offsets
            con.execute("""INSERT INTO actor_ticks
                (episode_id, tick, actor_id, alive, ox, oy, oz, vx, vy, vz, pitch, yaw, roll, hspeed)
                VALUES (?,?,?,?, ?,?,?, ?,?,?, ?,?,?, ?)""",
                (eid, tk, 2, 1, 300.0 + tk, 100.0, 0.0, -50.0, 0.0, 0.0, 0.0, 90.0, 0.0, 50.0))
            con.execute("""INSERT INTO actor_ticks
                (episode_id, tick, actor_id, alive, ox, oy, oz, vx, vy, vz, pitch, yaw, roll, hspeed)
                VALUES (?,?,?,?, ?,?,?, ?,?,?, ?,?,?, ?)""",
                (eid, tk, 3, 1, 500.0, 200.0, 50.0, 0.0, 0.0, 0.0, 0.0, 180.0, 0.0, 0.0))
    add(1, 100, 100.0)   # train
    add(2, 50, 900.0)    # val (different vx range -> must NOT affect the train-only fit)
    con.commit()
    con.close()


class TestP3TrainOnlyFit(unittest.TestCase):
    """normalize_fit.fit_from_catalog must use ONLY the train split, deterministically."""

    def test_fit_is_train_only_and_deterministic(self):
        import normalize_fit as NF
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "tiny.sqlite"
            _tiny_catalog(db)
            fit = NF.fit_from_catalog(db, split="train", map_name="dm3")
            # train has 100 player_ticks; val (50) MUST be excluded
            self.assertEqual(fit["n_rows"], 100)
            vmean = fit["feats"]["vel_x"]["mean"]
            # train vx in [100,199] -> mean ~149.5; if val (900+) leaked it would be far higher
            self.assertLess(vmean, 200.0)
            self.assertGreater(vmean, 100.0)
            # deterministic: refit identical
            fit2 = NF.fit_from_catalog(db, split="train", map_name="dm3")
            self.assertEqual(fit["feats"]["vel_x"], fit2["feats"]["vel_x"])

    def test_fit_stats_doc_provenance(self):
        import normalize_fit as NF
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "tiny.sqlite"
            _tiny_catalog(db)
            out = Path(d) / "stats.json"
            doc = NF.fit_stats_doc(db, out, split="train", map_name="dm3", artifact_version="t")
            self.assertEqual(doc["computed_from"], "train")
            self.assertEqual(doc["registry_version"], 2)
            self.assertIn("vel_x", doc["per_map"]["dm3"])
            self.assertEqual(doc["per_map"]["dm3"]["pos_x"]["method"], "minmax")
            # writing is byte-stable (sort_keys) -> re-write hashes identical
            import hashlib
            h1 = hashlib.sha256(out.read_bytes()).hexdigest()
            NF.fit_stats_doc(db, out, split="train", map_name="dm3", artifact_version="t")
            self.assertEqual(h1, hashlib.sha256(out.read_bytes()).hexdigest())


@unittest.skipUnless(_HAVE_DUCKDB and _HAVE_PYARROW, "duckdb/pyarrow not installed")
class TestP3ObservationShard(unittest.TestCase):
    """build_features.build_observation_shard: observed-others present + non-trivial,
    no future leakage into pad, deterministic byte-identical rebuild."""

    def test_shard_has_nontrivial_observed_others_and_no_leak(self):
        import numpy as np
        import normalize_fit as NF
        import build_features as BF
        from features import agent_observation as AO

        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "tiny.sqlite"
            _tiny_catalog(db)
            stats = Path(d) / "stats.json"
            NF.fit_stats_doc(db, stats, split="train", map_name="dm3", artifact_version="t")
            norm = json.loads(stats.read_text(encoding="utf-8"))

            out = Path(d) / "shard.parquet"
            summ = BF.build_observation_shard(db, norm, out, split="train",
                                              lookback_k=16, stride=8, n_max=7)
            self.assertGreater(summ["n_windows"], 0)
            self.assertEqual(summ["self_dim"], AO.SELF_DIM)
            self.assertEqual(summ["entity_dim"], AO.ENTITY_DIM)
            # every train tick here has 2 observed-others -> all real steps have one
            self.assertEqual(summ["observed_other_step_frac"], 1.0)
            self.assertGreater(summ["mean_abs_entity_feature"], 0.0)

            import pyarrow.parquet as pq
            t = pq.read_table(out)
            n = t.num_rows
            K, Nm, ENT = 16, 7, AO.ENTITY_DIM
            ent = np.array(t.column("entities").to_pylist(), dtype=np.float32).reshape(n, K, Nm, ENT)
            em = np.array(t.column("ent_mask").to_pylist(), dtype=np.float32).reshape(n, K, Nm)
            mk = np.array(t.column("mask").to_pylist(), dtype=np.float32).reshape(n, K)
            real = em.astype(bool)
            # exactly 2 real entity slots per real step (the 2 observed-others)
            self.assertTrue(bool((em.sum(-1)[mk.astype(bool)] == 2).all()))
            # observed-other features are non-trivial (have variance across real cells)
            self.assertTrue(bool((ent[real].std(axis=0) > 1e-6).any()))
            # NO leakage: pad entity cells are zero; padded steps zero everything
            self.assertTrue(bool(np.all(ent[~real] == 0.0)))

    def test_shard_rebuild_byte_identical(self):
        import normalize_fit as NF
        import build_features as BF
        import hashlib

        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "tiny.sqlite"
            _tiny_catalog(db)
            stats = Path(d) / "stats.json"
            NF.fit_stats_doc(db, stats, split="train", map_name="dm3", artifact_version="t")
            norm = json.loads(stats.read_text(encoding="utf-8"))
            a = Path(d) / "a.parquet"
            b = Path(d) / "b.parquet"
            BF.build_observation_shard(db, norm, a, split="train", lookback_k=16, stride=8)
            BF.build_observation_shard(db, norm, b, split="train", lookback_k=16, stride=8)
            self.assertEqual(hashlib.sha256(a.read_bytes()).hexdigest(),
                             hashlib.sha256(b.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
