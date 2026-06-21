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


def _tiny_catalog_teamed(path: Path) -> None:
    """Like _tiny_catalog but POPULATES actor_ticks.team_id: ego p1 + teammate p2 on
    team 10, opponent p3 on team 20. Used to prove the shard builder carries the ego's
    team into self_state so entity_features encodes is_teammate=1.0 for the teammate
    (and 0.0 for the opponent). One TRAIN episode is enough.

    The teammate (p2) is placed NEARER the ego than the opponent (p3) at every tick, so
    the nearest-first entity layout is deterministic: slot 0 = teammate, slot 1 = opponent.
    """
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
    # two teams: ego+teammate on 10, opponent on 20
    con.execute("INSERT INTO teams (team_id, demo_id, name, side) VALUES (10, 1, 'red', 'A')")
    con.execute("INSERT INTO teams (team_id, demo_id, name, side) VALUES (20, 1, 'blue', 'B')")
    con.execute("""INSERT INTO episodes (episode_id, demo_id, player_id, map_id, start_tick, end_tick, n_steps, split)
                   VALUES (1,1,1,1,0,39,40,'train')""")

    TEAM_OF = {1: 10, 2: 10, 3: 20}   # p1 ego + p2 teammate -> 10 ; p3 opponent -> 20
    for tk in range(40):
        vx = float(100.0 + tk)
        con.execute("""INSERT INTO player_ticks
            (episode_id, tick, t_s, msec, ox, oy, oz, vx, vy, vz, pitch, yaw, roll, hspeed, onground)
            VALUES (?,?,?,?, ?,?,?, ?,?,?, ?,?,?, ?,?)""",
            (1, tk, tk * 0.013, 13, 100.0, 50.0, -10.0, vx, 20.0, 0.0, 0.0, 0.0, 0.0,
             (vx * vx + 400.0) ** 0.5, 1))
        # self ego row in actor_ticks WITH team_id (the only place team lives)
        con.execute("""INSERT INTO actor_ticks
            (episode_id, tick, actor_id, team_id, alive, ox, oy, oz, vx, vy, vz, pitch, yaw, roll, hspeed)
            VALUES (?,?,?,?,?, ?,?,?, ?,?,?, ?,?,?, ?)""",
            (1, tk, 1, TEAM_OF[1], 1, 100.0, 50.0, -10.0, vx, 20.0, 0.0, 0.0, 0.0, 0.0, 0.0))
        # teammate p2 — NEARER (200 qu in x) -> sorts to slot 0
        con.execute("""INSERT INTO actor_ticks
            (episode_id, tick, actor_id, team_id, alive, ox, oy, oz, vx, vy, vz, pitch, yaw, roll, hspeed)
            VALUES (?,?,?,?,?, ?,?,?, ?,?,?, ?,?,?, ?)""",
            (1, tk, 2, TEAM_OF[2], 1, 300.0, 50.0, -10.0, -50.0, 0.0, 0.0, 0.0, 90.0, 0.0, 50.0))
        # opponent p3 — FARTHER (700 qu in x) -> sorts to slot 1
        con.execute("""INSERT INTO actor_ticks
            (episode_id, tick, actor_id, team_id, alive, ox, oy, oz, vx, vy, vz, pitch, yaw, roll, hspeed)
            VALUES (?,?,?,?,?, ?,?,?, ?,?,?, ?,?,?, ?)""",
            (1, tk, 3, TEAM_OF[3], 1, 800.0, 50.0, -10.0, 0.0, 0.0, 0.0, 0.0, 180.0, 0.0, 0.0))
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
            # v5 (sequence-aware): the fit stamps registry_version 5 (SELF channels + keys
            # unchanged from v4; only the obs contract moved to the flat self_history).
            self.assertEqual(doc["registry_version"], 5)  # tracks shard_contract.EXPECTS_REGISTRY_VERSION (v5)
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

    def test_self_history_stored_once_per_window_at_last_real_tick(self):
        """v5 storage-shrink (OOM fix): build_observation_shard stores self_history as ONE
        flat [HD] vector PER WINDOW (the last-real-tick history) — NOT a per-tick [K, HD].
        Asserts (a) the column is [n, HD] (so width==HD, the 64x collapse) and (b) the stored
        vector is BYTE-IDENTICAL to AO.assemble_self_history over the window's per-tick SELF
        (the `obs` column) up to the last real tick — i.e. exactly what the old [K, HD][ti]
        extraction yielded. Proves training data is unchanged; only storage shrank."""
        import numpy as np
        import normalize_fit as NF
        import build_features as BF
        from features import agent_observation as AO
        from broad_bc import core as BC, shard_contract as SC

        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "tiny.sqlite"
            _tiny_catalog(db)
            stats = Path(d) / "stats.json"
            NF.fit_stats_doc(db, stats, split="train", map_name="dm3", artifact_version="t")
            norm = json.loads(stats.read_text(encoding="utf-8"))
            out = Path(d) / "shard.parquet"
            K, H, S, HD = 16, AO.SELF_HISTORY, AO.SELF_DIM, AO.SELF_HISTORY_DIM
            BF.build_observation_shard(db, norm, out, split="train",
                                       lookback_k=K, stride=8, n_max=7)

            import pyarrow.parquet as pq
            t = pq.read_table(out)
            n = t.num_rows
            # (a) the FLAT self_history column has EXACTLY HD floats per row (one history per
            # window). The OLD per-tick storage would have K*HD = 16*336 per row -> reshape
            # to (n, HD) would FAIL. So a clean (n, HD) reshape IS the storage-shrink proof.
            sh = np.array(t.column("self_history").to_pylist(),
                          dtype=np.float32).reshape(n, HD)
            self.assertEqual(sh.shape, (n, HD))
            self.assertEqual(HD, H * S)                           # 336 = 16 * 21
            obs = np.array(t.column("obs").to_pylist(),
                           dtype=np.float32).reshape(n, K, S)
            mk = np.array(t.column("mask").to_pylist(),
                          dtype=np.float32).reshape(n, K)
            # (b) training-equivalence: stored history == assemble_self_history over the
            # per-tick obs up to the last real tick (the old [K, HD][ti] value).
            for wi in range(n):
                ti = BC._last_real_tick(mk[wi].tolist())
                window_selves = [obs[wi][j].tolist() for j in range(ti + 1)]
                expected = AO.assemble_self_history(window_selves[:ti + 1], H)
                np.testing.assert_array_equal(sh[wi], np.asarray(expected, dtype=np.float32))
                # newest SELF_DIM block == the last real tick's obs (closed invariant)
                np.testing.assert_array_equal(sh[wi][-S:], obs[wi][ti])

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


@unittest.skipUnless(_HAVE_DUCKDB and _HAVE_PYARROW, "duckdb/pyarrow not installed")
class TestP3EgoTeamCarried(unittest.TestCase):
    """Regression for the BLOCKING finding: the shard builder MUST carry the ego actor's
    team_id into self_state so entity_features encodes entity_is_teammate=1.0 for a
    teammate (and 0.0 for an opponent). Previously self_state['team_id'] was hard-coded
    None, which silently trained the teammate/opponent channel as all-zero whenever the
    catalog had a populated actor_ticks.team_id."""

    def test_teammate_channel_encodes_one_when_team_present(self):
        import numpy as np
        import normalize_fit as NF
        import build_features as BF
        from features import agent_observation as AO

        tm_idx = AO.ENTITY_FIELDS.index("entity_is_teammate")
        dist_idx = AO.ENTITY_FIELDS.index("entity_rel_dist_norm")

        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "teamed.sqlite"
            _tiny_catalog_teamed(db)
            stats = Path(d) / "stats.json"
            NF.fit_stats_doc(db, stats, split="train", map_name="dm3", artifact_version="t")
            norm = json.loads(stats.read_text(encoding="utf-8"))

            out = Path(d) / "shard.parquet"
            BF.build_observation_shard(db, norm, out, split="train",
                                       lookback_k=16, stride=8, n_max=7)

            import pyarrow.parquet as pq
            t = pq.read_table(out)
            n = t.num_rows
            K, Nm, ENT = 16, 7, AO.ENTITY_DIM
            ent = np.array(t.column("entities").to_pylist(),
                           dtype=np.float32).reshape(n, K, Nm, ENT)
            em = np.array(t.column("ent_mask").to_pylist(),
                          dtype=np.float32).reshape(n, K, Nm)
            mk = np.array(t.column("mask").to_pylist(),
                          dtype=np.float32).reshape(n, K)

            real_step = mk.astype(bool)
            # exactly two observed others (teammate p2 + opponent p3) per real step
            self.assertTrue(bool((em.sum(-1)[real_step] == 2).all()))

            # teammate p2 is placed nearer -> slot 0; opponent p3 farther -> slot 1.
            # (assert the layout, then read the is_teammate channel per slot)
            steps = em[real_step].astype(bool)            # [R, Nm]
            ent_steps = ent[real_step]                    # [R, Nm, ENT]
            self.assertEqual(ent_steps.shape[0], int(real_step.sum()))
            # slot 0 nearer than slot 1 across all real steps
            self.assertTrue(bool((ent_steps[:, 0, dist_idx] < ent_steps[:, 1, dist_idx]).all()))
            # THE FIX: nearer teammate slot encodes is_teammate == 1.0 ...
            self.assertTrue(bool((ent_steps[:, 0, tm_idx] == 1.0).all()))
            # ... and the farther opponent slot encodes is_teammate == 0.0
            self.assertTrue(bool((ent_steps[:, 1, tm_idx] == 0.0).all()))
            # exactly one teammate per real step over the real slots (sanity)
            tm_over_real = np.where(steps, ent_steps[:, :, tm_idx], 0.0)
            self.assertTrue(bool((tm_over_real.sum(-1) == 1.0).all()))


def _tiny_catalog_turning(path: Path) -> None:
    """A minimal TRAIN-only catalog whose ego view yaw TURNS tick-to-tick (so yaw_rate is
    non-trivially nonzero) — for the build-vs-inference turn-direction parity test. Each
    tick advances yaw by +10 deg and moves at a real horizontal speed (so the velocity
    heading / face_vel_angle are defined, above the 80 qu/s floor)."""
    import sqlite3

    sql = (REPO_ROOT / "data" / "catalog" / "catalog.sql").read_text(encoding="utf-8")
    con = sqlite3.connect(str(path))
    con.executescript(sql)
    con.execute("""INSERT INTO maps
        (map_id, name, x_min, x_max, y_min, y_max, z_min, z_max, diagonal)
        VALUES (1, 'dm3', -984.0, 2048.0, -960.0, 1136.0, -416.0, 496.0, 3797.1)""")
    con.execute("""INSERT INTO demos (demo_id, path, source, map_id, sha256)
                   VALUES (1, 'd.qwd', 'qwd', 1, 'feedface')""")
    con.execute("INSERT INTO players (player_id, handle, is_bot) VALUES (1, 'p1', 0)")
    con.execute("""INSERT INTO episodes (episode_id, demo_id, player_id, map_id, start_tick, end_tick, n_steps, split)
                   VALUES (1,1,1,1,0,7,8,'train')""")
    for tk in range(8):
        yaw = 10.0 * tk                       # turning +10 deg/tick (+~769 deg/s @ 13ms)
        vx, vy, vz = 250.0, 90.0, -20.0       # real motion -> hspeed ~266 > 80 floor
        hsp = (vx * vx + vy * vy) ** 0.5
        con.execute("""INSERT INTO player_ticks
            (episode_id, tick, t_s, msec, ox, oy, oz, vx, vy, vz, pitch, yaw, roll, hspeed, onground)
            VALUES (?,?,?,?, ?,?,?, ?,?,?, ?,?,?, ?,?)""",
            (1, tk, tk * 0.013, 13, 100.0 + tk, 50.0, -10.0, vx, vy, vz, 5.0, yaw, 0.0, hsp, 0))
        con.execute("""INSERT INTO actor_ticks
            (episode_id, tick, actor_id, alive, ox, oy, oz, vx, vy, vz, pitch, yaw, roll, hspeed)
            VALUES (?,?,?,?, ?,?,?, ?,?,?, ?,?,?, ?)""",
            (1, tk, 1, 1, 100.0 + tk, 50.0, -10.0, vx, vy, vz, 5.0, yaw, 0.0, hsp))
    con.commit()
    con.close()


@unittest.skipUnless(_HAVE_DUCKDB and _HAVE_PYARROW, "duckdb/pyarrow not installed")
class TestTurnDirectionBuildInferenceParity(unittest.TestCase):
    """TRAIN/INFERENCE PARITY for the turn-direction features, via the REAL build path.

    The deps-free counterpart (ml/tests/test_eval_closedloop.TestTurnDirectionTrainInference
    Parity) reproduces the build's per-tick self_state; THIS one runs the actual
    build_features._load_episode_ticks over a tiny catalog so the real query + yaw_rate
    computation are exercised, then asserts the build's encoded SELF vector equals the
    inference builder's (CL._self_state_from_sim) for the SAME tick — proving the offline
    yaw_rate matches what the closed-loop / dry-route rollouts feed the model."""

    def test_build_self_vec_matches_inference_self_vec(self):
        import normalize_fit as NF
        import build_features as BF
        import eval_broad_closedloop as CL
        from features import agent_observation as AO

        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "turning.sqlite"
            _tiny_catalog_turning(db)
            stats = Path(d) / "stats.json"
            NF.fit_stats_doc(db, stats, split="train", map_name="dm3", artifact_version="t")
            norm = json.loads(stats.read_text(encoding="utf-8"))
            # the fit must have emitted a yaw_rate zscore key (the new normalization field).
            self.assertIn("yaw_rate", norm["per_map"]["dm3"])
            self.assertEqual(norm["per_map"]["dm3"]["yaw_rate"]["method"], "zscore")

            episodes, _ = BF._load_episode_ticks(db, split="train")
            ticks = episodes[1]
            self.assertGreaterEqual(len(ticks), 3)

            # pick tick index 3 (a mid-episode tick with a real previous yaw -> nonzero rate).
            j = 3
            t = ticks[j]
            build_self = t["self"]
            # the build computed yaw_rate from the PREVIOUS tick's yaw: assert it is the
            # nonzero turn rate we constructed (+10 deg over 13 ms ~= +769.23 deg/s).
            self.assertAlmostEqual(build_self["yaw_rate"], 10.0 / 0.013, places=3)

            build_vec = AO.encode_observation(build_self, [], norm, "dm3", 7)["self"]

            # INFERENCE path: rebuild the SAME tick's self_state from a sim state at the
            # build's kinematics + the yaw_rate the rollout would compute (shared helper on
            # this tick's yaw, the PREVIOUS tick's yaw, this tick's dt).
            class _S:
                def __init__(s, st):
                    s.origin = [float(st["ox"]), float(st["oy"]), float(st["oz"])]
                    s.velocity = [float(st["vx"]), float(st["vy"]), float(st["vz"])]
                    s.onground = bool(st["onground"])
            prev_yaw = float(ticks[j - 1]["self"]["yaw"])
            yaw_rate = AO.yaw_rate_degps(float(build_self["yaw"]), prev_yaw, 0.013)
            infer_self = CL._self_state_from_sim(
                _S(build_self), float(build_self["yaw"]), float(build_self["pitch"]),
                yaw_rate=yaw_rate)
            infer_vec = AO.encode_observation(infer_self, [], norm, "dm3", 7)["self"]

            # the build + inference yaw_rate are identical (same helper, same inputs) ...
            self.assertAlmostEqual(yaw_rate, build_self["yaw_rate"], places=9)
            # ... so the full SELF vectors are byte-identical (the parity guarantee).
            self.assertEqual(build_vec, infer_vec)
            self.assertEqual(len(build_vec), AO.SELF_DIM)


@unittest.skipUnless(_HAVE_DUCKDB and _HAVE_PYARROW, "duckdb/pyarrow not installed")
class TestCliBackCompat(unittest.TestCase):
    """Regression for the BLOCKING CLI finding: the documented legacy invocation
    `build_features.py --catalog-dir ... --fixture-dir ... --stats ... --out ...`
    (NO `fixture` subcommand) must still parse and run, AND the explicit `fixture`
    subcommand must work too."""

    def _args(self, extra):
        return ["--catalog-dir", str(CATALOG_DIR),
                "--fixture-dir", str(FIXTURE_DIR),
                "--stats", str(STATS)] + extra

    def test_documented_legacy_form_runs(self):
        import build_features as BF
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "shard.parquet"
            # the exact form INTEGRATION.md / ml/README.md document (no subcommand)
            rc = BF.main(self._args(["--out", str(out)]))
            self.assertEqual(rc, 0)
            self.assertTrue(out.exists())

    def test_explicit_fixture_subcommand_runs(self):
        import build_features as BF
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "shard.parquet"
            rc = BF.main(["fixture"] + self._args(["--out", str(out)]))
            self.assertEqual(rc, 0)
            self.assertTrue(out.exists())

    def test_missing_required_fixture_args_errors_cleanly(self):
        import build_features as BF
        # no --catalog-dir etc. and no subcommand -> helpful non-zero, not a traceback
        rc = BF.main([])
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
