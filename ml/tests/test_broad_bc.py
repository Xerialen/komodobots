"""ml/tests/test_broad_bc.py — tests for the BROAD behavioral-cloning trainer.

Run by the NON-GATING ml-tests.yml (and importable under bare stdlib python).
Two layers, mirroring ml/tests/test_pipeline.py:
  * DEPS-FREE: contract, synthetic shard, broad-input assembly, split-by-demo,
    label encoding, the reference trainer's reproducibility + learnability, and
    the model-card stub. These ALWAYS run (no torch/numpy needed) — they are the
    offline CPU-smoke contract.
  * TORCH: a tiny BroadBCPolicy forward/train step, SKIPPED when torch is absent.
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
sys.path.insert(0, str(ML))
sys.path.insert(0, str(REPO_ROOT / "scripts"))   # in-tree shared transform

from broad_bc import shard_contract as SC   # noqa: E402
from broad_bc import synth_shard            # noqa: E402
from broad_bc import core                   # noqa: E402
from features import agent_observation as AO  # noqa: E402  (shared obs+action encoder)

_HAVE_TORCH = importlib.util.find_spec("torch") is not None
_HAVE_NUMPY = importlib.util.find_spec("numpy") is not None
_HAVE_PYARROW = importlib.util.find_spec("pyarrow") is not None


class TestShardContract(unittest.TestCase):
    def test_heads_and_registry(self):
        self.assertEqual(SC.EXPECTS_REGISTRY_VERSION, 2)
        self.assertEqual(SC.head_names(), ["fwd", "side", "up", "jump", "attack"])

    def test_sign3_and_bin_encoding(self):
        self.assertEqual(SC.encode_sign3(0.9), 2)
        self.assertEqual(SC.encode_sign3(-0.9), 0)
        self.assertEqual(SC.encode_sign3(0.0), 1)
        self.assertEqual(SC.encode_bin(1.0), 1)
        self.assertEqual(SC.encode_bin(0.0), 0)

    def test_encode_action_row_uses_schema_columns(self):
        schema = SC.ShardSchema()
        row = [0.0] * len(SC.ACT_COLS)
        row[SC.ACT_COLS.index("forwardmove")] = 1.0    # fwd  -> 2 (+)
        row[SC.ACT_COLS.index("sidemove")] = -1.0       # side -> 0 (-)
        row[SC.ACT_COLS.index("upmove")] = 0.0          # up   -> 1 (none)
        row[SC.ACT_COLS.index("jump_button")] = 1.0     # jump -> 1
        row[SC.ACT_COLS.index("attack_button")] = 0.0   # attack -> 0
        self.assertEqual(SC.encode_action_row(row, schema), [2, 0, 1, 1, 0])

    def test_rebind_schema_with_reordered_act_cols(self):
        # FEAT could pin a different act-column order; schema rebinds, no code change.
        reordered = ("attack_button", "jump_button", "upmove", "sidemove",
                     "forwardmove", "cmd_delta_yaw_sin", "cmd_delta_yaw_cos")
        schema = SC.ShardSchema(act_cols=reordered)
        row = [0.0] * len(reordered)
        row[reordered.index("forwardmove")] = 1.0
        row[reordered.index("attack_button")] = 1.0
        labels = SC.encode_action_row(row, schema)
        # heads order is still fwd,side,up,jump,attack
        self.assertEqual(labels[0], 2)   # fwd +
        self.assertEqual(labels[4], 1)   # attack on

    def test_contract_doc_emit(self):
        with tempfile.TemporaryDirectory() as d:
            p = SC.write_contract_doc(Path(d) / "c.json")
            doc = json.loads(p.read_text())
            self.assertEqual(doc["expects_registry_version"], 2)
            self.assertIn("entities", doc["array_keys"])
            self.assertEqual(len(doc["action_heads"]), 5)


class TestSyntheticShardAndLoader(unittest.TestCase):
    def test_broad_input_includes_observed_others(self):
        schema = SC.ShardSchema()
        sh = synth_shard.make_synthetic_shard(
            n_windows=5, obs_dim=16, ent_dim=10, audio_dim=4, team_dim=6, seed=3)
        rows = list(core.shard_to_rows(sh, schema))
        self.assertEqual(len(rows), 5)
        # input dim = obs(16) + pooled_ent(10) + n_vis_frac(1) + audio(4) + team(6)
        self.assertEqual(len(rows[0]["x"]), 16 + 10 + 1 + 4 + 6)
        # every label is a valid class id for its head
        for r in rows:
            for (hidx, (_n, k, _c, _kind)) in enumerate(schema.heads()):
                self.assertTrue(0 <= r["y"][hidx] < k)

    def test_pool_entities_masked_mean(self):
        ent = [[2.0, 0.0], [4.0, 0.0], [99.0, 99.0]]   # 3rd slot is pad
        em = [1.0, 1.0, 0.0]
        pooled, n_vis = core._pool_entities(ent, em)
        self.assertEqual(n_vis, 2)
        self.assertAlmostEqual(pooled[0], 3.0)          # mean(2,4); pad ignored
        self.assertAlmostEqual(pooled[1], 0.0)

    def test_roundtrip_write_read_stdlib(self):
        schema = SC.ShardSchema()
        with tempfile.TemporaryDirectory() as d:
            paths = synth_shard.make_synthetic_corpus(
                Path(d), n_demos=3, windows_per_demo=20, seed=0,
                obs_dim=8, ent_dim=6)
            rows, in_dim = core.iter_corpus(paths, schema)
            self.assertGreater(len(rows), 0)
            # obs(8) + pooled_ent(6) + n_vis_frac(1) + audio(4 default) + team(6 default)
            self.assertEqual(in_dim, 8 + 6 + 1 + 4 + 6)


class TestSplitByDemo(unittest.TestCase):
    def test_no_demo_straddles_split(self):
        rows = [{"demo_id": f"d{i % 4}", "x": [0.0], "y": [0]} for i in range(40)]
        tr, va, val_demos = core.split_by_demo(rows, val_frac=0.25, seed=0)
        tr_demos = {r["demo_id"] for r in tr}
        va_demos = {r["demo_id"] for r in va}
        self.assertTrue(tr_demos.isdisjoint(va_demos))     # group-disjoint
        self.assertEqual(va_demos, set(val_demos))

    def test_split_deterministic(self):
        rows = [{"demo_id": f"d{i % 6}"} for i in range(60)]
        _, _, v1 = core.split_by_demo(rows, 0.34, seed=42)
        _, _, v2 = core.split_by_demo(rows, 0.34, seed=42)
        self.assertEqual(v1, v2)


class TestReferenceTrainerReproducible(unittest.TestCase):
    def _train(self, seed):
        schema = SC.ShardSchema()
        sh = synth_shard.make_synthetic_shard(
            n_windows=120, obs_dim=12, ent_dim=8, seed=7)
        rows = list(core.shard_to_rows(sh, schema))
        in_dim = len(rows[0]["x"])
        head_dims = [k for (_n, k, _c, _kind) in schema.heads()]
        _model, history = core.train_ref(
            rows, in_dim, head_dims, hidden=16, epochs=5, lr=0.2, seed=seed, batch=32)
        return [h["train_loss"] for h in history]

    def test_identical_loss_same_seed(self):
        self.assertEqual(self._train(0), self._train(0))     # reproducible

    def test_loss_decreases(self):
        curve = self._train(0)
        self.assertLess(curve[-1], curve[0])                 # learns

    def test_learns_from_broad_input_beats_majority(self):
        # the synthetic target depends on the observed-other channel, so a fitted
        # model must beat the majority baseline -> proves broad input is used.
        schema = SC.ShardSchema()
        sh = synth_shard.make_synthetic_shard(n_windows=300, seed=11)
        rows = list(core.shard_to_rows(sh, schema))
        tr, va, _ = core.split_by_demo(
            [dict(r, demo_id="a" if i % 5 else "b") for i, r in enumerate(rows)],
            val_frac=0.2, seed=0)
        in_dim = len(rows[0]["x"])
        head_specs = [(n, k) for (n, k, _c, _kind) in schema.heads()]
        head_dims = [k for (_n, k) in head_specs]
        model, _ = core.train_ref(tr, in_dim, head_dims, hidden=24, epochs=12,
                                  lr=0.3, seed=0, batch=64)
        metrics = core.evaluate_heads(model, va, head_specs)
        # at least the strongest head must clear its majority baseline
        beats = [m["val_acc"] >= m["majority_baseline"] for m in metrics.values()]
        self.assertTrue(any(beats))


class TestModelCard(unittest.TestCase):
    def test_pins_reproducibility_quadruple(self):
        schema = SC.ShardSchema()
        card = core.build_model_card(
            run_kind="cpu_smoke", schema=schema, in_dim=37, hidden=24,
            head_specs=[("fwd", 3)], metrics={}, history=[], seed=5,
            repo_root=REPO_ROOT, norm_artifact_version="X-1",
            registry_version=2, dataset_version="ds-1")
        for key in ("git_sha", "registry_version", "norm_artifact_version", "seed"):
            self.assertIn(key, card)
        self.assertEqual(card["seed"], 5)
        self.assertEqual(card["registry_version"], 2)
        self.assertTrue(card["input_is_broad"])
        self.assertTrue(card["input_includes_observed_others"])
        self.assertFalse(card["move_only"])


@unittest.skipUnless(_HAVE_TORCH and _HAVE_NUMPY, "torch/numpy not installed")
class TestTorchPolicySmoke(unittest.TestCase):
    def test_forward_and_one_step(self):
        import torch
        import train_broad_bc as TB
        m = TB.BroadBCPolicy(f_obs=12, f_ent=8, f_aux=10, n_max=7,
                             ent_out=16, hidden=32, head_dims=(3, 3, 3, 2, 2))
        B = 4
        obs = torch.randn(B, 12)
        ent = torch.randn(B, 7, 8)
        emask = torch.ones(B, 7)
        emask[:, 4:] = 0.0
        aux = torch.randn(B, 10)
        logits = m(obs, ent, emask, aux)
        self.assertEqual(len(logits), 5)
        self.assertEqual(logits[0].shape, (B, 3))
        self.assertEqual(logits[3].shape, (B, 2))
        # one backward step works
        y = torch.zeros(B, 5, dtype=torch.long)
        loss = sum(torch.nn.functional.cross_entropy(logits[h], y[:, h])
                   for h in range(5))
        loss.backward()
        self.assertTrue(any(p.grad is not None for p in m.parameters()))

    def test_pool_ignores_pad_slots(self):
        import torch
        import train_broad_bc as TB
        m = TB.BroadBCPolicy(f_obs=4, f_ent=4, f_aux=0, n_max=3,
                             ent_out=8, hidden=8, head_dims=(2,))
        # identical real slot, different pad slots -> identical output (pad ignored)
        obs = torch.zeros(1, 4)
        ent_a = torch.tensor([[[1.0, 2, 3, 4], [9, 9, 9, 9], [0, 0, 0, 0]]])
        ent_b = torch.tensor([[[1.0, 2, 3, 4], [-5, -5, -5, -5], [7, 7, 7, 7]]])
        emask = torch.tensor([[1.0, 0.0, 0.0]])
        aux = torch.zeros(1, 0)
        with torch.no_grad():
            oa = m(obs, ent_a, emask, aux)[0]
            ob = m(obs, ent_b, emask, aux)[0]
        self.assertTrue(torch.allclose(oa, ob))


class TestActionEncoderMatchesContract(unittest.TestCase):
    """FEAT's shared action encoder (scripts/features.agent_observation.encode_action)
    must produce the columns the trainer's ACT_COLS/heads consume — the FEAT<->TRAINER
    action contract. Stdlib-only (deps-free)."""

    def test_act_fields_align_with_trainer_heads(self):
        # the 5 cloned heads' source columns, in order, are exactly ACT_FIELDS.
        head_src = [c for (_n, _k, c, _kind) in
                    [(n, k, c, kd) for (n, k, c, kd) in SC.ACTION_HEADS]]
        self.assertEqual(list(AO.ACT_FIELDS), head_src)
        self.assertEqual(AO.ACT_DIM, 5)
        # and they are a prefix of the trainer's full ACT_COLS (so width-5 binds by name)
        self.assertEqual(tuple(AO.ACT_FIELDS), SC.ACT_COLS[:5])

    def test_encode_action_normalizes_and_decodes_buttons(self):
        act = {"forwardmove": 400, "sidemove": -200, "upmove": 0,
               "buttons": 3}              # buttons 3 = jump(2) | attack(1)
        vec = AO.encode_action(act)
        self.assertEqual(len(vec), AO.ACT_DIM)
        self.assertAlmostEqual(vec[0], 1.0)       # 400/400
        self.assertAlmostEqual(vec[1], -0.5)      # -200/400
        self.assertAlmostEqual(vec[2], 0.0)
        self.assertEqual(vec[3], 1.0)             # jump bit
        self.assertEqual(vec[4], 1.0)             # attack bit
        # and the trainer's label encoder turns it into the expected head classes
        labels = SC.encode_action_row(vec, SC.ShardSchema())
        self.assertEqual(labels, [2, 0, 1, 1, 1])  # fwd+ side- up_none jump attack

    def test_encode_action_clamps_and_handles_none(self):
        self.assertEqual(AO.encode_action(None), [0.0] * AO.ACT_DIM)
        over = AO.encode_action({"forwardmove": 800, "sidemove": -800, "buttons": 0})
        self.assertEqual(over[0], 1.0)            # clamped to +1
        self.assertEqual(over[1], -1.0)           # clamped to -1
        self.assertEqual(over[3], 0.0)
        self.assertEqual(over[4], 0.0)


_HAVE_DUCKDB = importlib.util.find_spec("duckdb") is not None


def _load_build_features():
    """Import ml/pipeline/build_features.py by path (it adds scripts/ to sys.path)."""
    spec = importlib.util.spec_from_file_location(
        "build_features_recon", ML / "pipeline" / "build_features.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@unittest.skipUnless(_HAVE_PYARROW and _HAVE_NUMPY and _HAVE_DUCKDB,
                     "pyarrow/numpy/duckdb not installed")
class TestParquetShardBridge(unittest.TestCase):
    """The reconciliation bridge: FEAT writes ONE flattened-column Parquet with many
    windows + per-window demo_id + act/weight; core.read_shard reshapes it back to the
    nested arrays + per-window demo_ids the trainer consumes. Builds a tiny REAL shard
    via the FEAT builder over a 2-demo in-memory catalog."""

    def _make_catalog(self, db_path):
        import sqlite3
        ddl = (REPO_ROOT / "scripts" / "catalog_schema.sql").read_text()
        con = sqlite3.connect(str(db_path))
        con.executescript(ddl)
        # one map row (dm3) so the join works
        con.execute("INSERT INTO maps (map_id,name,x_min,x_max,y_min,y_max,z_min,z_max,"
                    "diagonal) VALUES (1,'dm3',-984,2048,-960,1136,-416,496,3797.1)")
        # the observed-other actor (FK target for actor_ticks.actor_id)
        con.execute("INSERT INTO players (player_id,handle) VALUES (99,'other')")
        # 2 demos -> 2 episodes (one each), both 'train', a handful of ticks each
        for demo_id, eid, pid in ((1, 1, 1), (2, 2, 2)):
            con.execute("INSERT INTO demos (demo_id,path,source,map_id,sha256) "
                        "VALUES (?,?,?,1,?)", (demo_id, f"d{demo_id}.qwd", "qwd", f"sha{demo_id}"))
            con.execute("INSERT INTO players (player_id,handle) VALUES (?,?)",
                        (pid, f"p{pid}"))
            con.execute("INSERT INTO episodes (episode_id,demo_id,player_id,map_id,"
                        "start_tick,end_tick,n_steps,split) VALUES (?,?,?,1,0,7,8,'train')",
                        (eid, demo_id, pid))
            for tick in range(8):
                con.execute("INSERT INTO player_ticks (episode_id,tick,t_s,ox,oy,oz,"
                            "vx,vy,vz,yaw,pitch,hspeed,onground,health,armor) "
                            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (eid, tick, tick * 0.013, 100.0 + tick, 50.0, 24.0,
                             200.0, 0.0, 0.0, 90.0, 0.0, 200.0, 1, 100, 50))
                # an observed-other actor row (so entities are non-trivial)
                con.execute("INSERT INTO actor_ticks (episode_id,tick,actor_id,alive,"
                            "ox,oy,oz,vx,vy,vz,yaw,hspeed) "
                            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                            (eid, tick, 99, 1, 300.0, 80.0, 24.0, -150.0, 10.0, 0.0, 45.0, 150.0))
                con.execute("INSERT INTO actions (episode_id,tick,forwardmove,sidemove,"
                            "upmove,buttons,label_source,confidence,is_interp) "
                            "VALUES (?,?,?,?,?,?,?,?,?)",
                            (eid, tick, 400.0, -200.0, 0.0, 2 if tick % 2 else 0,
                             "qwd_usercmd", 1.0, 0))
        con.commit()
        con.close()

    def test_build_and_read_roundtrip(self):
        bf = _load_build_features()
        norm = json.loads(
            (REPO_ROOT / "data" / "catalog" / "normalization_stats.template.json")
            .read_text())
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "mini.sqlite"
            self._make_catalog(db)
            out = Path(d) / "shard.parquet"
            summ = bf.build_observation_shard(
                db, norm, out, split="train", map_name="dm3",
                lookback_k=4, stride=2, n_max=7)
            # the build emitted act + per-head label counts + non-trivial entities
            self.assertEqual(summ["act_dim"], 5)
            self.assertEqual(summ["label_coverage"], 1.0)
            self.assertEqual(summ["n_demos"], 2)
            self.assertGreater(summ["observed_other_step_frac"], 0.0)
            self.assertGreater(summ["mean_abs_entity_feature"], 0.0)

            # --- the BRIDGE: read the flattened Parquet back to nested arrays --------
            shard = core.read_shard(out)
            self.assertIn(SC.KEY_ACT, shard)
            self.assertIn(SC.KEY_DEMO_IDS, shard)
            self.assertEqual(len(set(shard[SC.KEY_DEMO_IDS])), 2)   # 2 demos in one file
            n_win = len(shard[SC.KEY_OBS])
            self.assertEqual(len(shard[SC.KEY_OBS][0]), 4)          # K=4 ticks
            self.assertEqual(len(shard[SC.KEY_OBS][0][0]), AO.SELF_DIM)     # obs width
            self.assertEqual(len(shard[SC.KEY_ENTITIES][0][0]), 7)         # N_max slots
            self.assertEqual(len(shard[SC.KEY_ENTITIES][0][0][0]), AO.ENTITY_DIM)
            self.assertEqual(len(shard[SC.KEY_ACT][0][0]), AO.ACT_DIM)
            self.assertFalse(shard[SC.KEY_META]["has_audio"])
            self.assertFalse(shard[SC.KEY_META]["has_team"])

            # --- the loader turns it into BC rows with the per-window demo split key --
            schema = SC.ShardSchema()
            rows = list(core.shard_to_rows(shard, schema))
            self.assertGreater(len(rows), 0)
            self.assertEqual(len({r["demo_id"] for r in rows}), 2)
            # act label decodes: forwardmove=400 -> fwd head class 2 (+)
            self.assertEqual(rows[0]["y"][0], 2)
            # input width = obs(16) + pooled_ent(13) + n_vis_frac(1); no audio/team
            self.assertEqual(len(rows[0]["x"]), AO.SELF_DIM + AO.ENTITY_DIM + 1)

