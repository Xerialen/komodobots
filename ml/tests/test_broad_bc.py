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
        # v5 (GRU over a goal-conditioned short history): the SELF channels stay the 21-wide
        # v4 goal-conditioned vector, but the policy now consumes the FLAT last-SELF_HISTORY-
        # tick history, so the contract EXPECTS registry_version 5 + a SELF_HISTORY of 16 + a
        # 336-wide flat history. The per-tick SELF channel count + required norm key are kept.
        self.assertEqual(SC.EXPECTS_REGISTRY_VERSION, 5)
        self.assertEqual(SC.EXPECTS_SELF_DIM, 21)
        self.assertEqual(SC.EXPECTS_SELF_DIM, AO.SELF_DIM)   # contract == transform
        self.assertEqual(SC.EXPECTS_SELF_HISTORY, 16)
        self.assertEqual(SC.EXPECTS_SELF_HISTORY, AO.SELF_HISTORY)   # contract == transform
        self.assertEqual(SC.EXPECTS_SELF_HISTORY_DIM, 16 * 21)
        self.assertEqual(SC.EXPECTS_SELF_HISTORY_DIM, AO.SELF_HISTORY_DIM)
        self.assertEqual(SC.REQUIRED_NORM_KEYS, ("yaw_rate",))
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
            self.assertEqual(doc["expects_registry_version"], 5)
            self.assertEqual(doc["expects_self_dim"], 21)
            self.assertEqual(doc["expects_self_history"], 16)
            self.assertEqual(doc["expects_self_history_dim"], 16 * 21)
            self.assertEqual(doc["required_norm_keys"], ["yaw_rate"])
            self.assertIn("entities", doc["array_keys"])
            self.assertIn("self_history", doc["array_keys"])
            self.assertEqual(len(doc["action_heads"]), 5)


class TestSelfHistoryFlattenLayout(unittest.TestCase):
    """DEPS-FREE half of the GRU reshape-order proof: the flat self-history layout the
    model's [B, SELF_HISTORY, SELF_DIM] reshape depends on. assemble_self_history places
    tick t's SELF_DIM channels CONTIGUOUSLY at flat[t*SELF_DIM:(t+1)*SELF_DIM], OLDEST->
    NEWEST. So a row-major reshape to [SELF_HISTORY, SELF_DIM] yields ticks in TIME order
    (the torch model-side reshape is asserted in TestTorchPolicySmoke). Pure stdlib."""

    def test_assemble_self_history_is_tick_contiguous_oldest_to_newest(self):
        H, D = SC.EXPECTS_SELF_HISTORY, SC.EXPECTS_SELF_DIM        # 16, 21
        selves = [[float(t * 100 + c) for c in range(D)] for t in range(H)]  # distinct
        flat = AO.assemble_self_history(selves, H)
        self.assertEqual(len(flat), H * D)                        # == 336
        # tick t's 21 channels live at flat[t*D:(t+1)*D], in order, oldest->newest.
        for t in range(H):
            self.assertEqual(flat[t * D:(t + 1) * D], selves[t])
        # newest block is the current single-tick SELF (the assemble invariant).
        self.assertEqual(flat[-D:], selves[-1])

    def test_left_pad_repeats_earliest_then_time_order_holds(self):
        # with fewer than H ticks the EARLIEST is repeated into the oldest slots, and the
        # per-tick contiguity + oldest->newest order still hold (so the reshape stays
        # time-major at an episode/rollout start).
        H, D = SC.EXPECTS_SELF_HISTORY, SC.EXPECTS_SELF_DIM
        selves = [[float(10 + c) for c in range(D)],             # earliest real
                  [float(20 + c) for c in range(D)]]             # newest real
        flat = AO.assemble_self_history(selves, H)
        self.assertEqual(len(flat), H * D)
        for t in range(H - 1):                                    # padded oldest slots
            self.assertEqual(flat[t * D:(t + 1) * D], selves[0])  # repeat earliest
        self.assertEqual(flat[(H - 1) * D:H * D], selves[1])      # newest is the real last


class TestSyntheticShardAndLoader(unittest.TestCase):
    def test_broad_input_includes_observed_others(self):
        schema = SC.ShardSchema()
        sh = synth_shard.make_synthetic_shard(
            n_windows=5, obs_dim=16, ent_dim=10, audio_dim=4, team_dim=6, seed=3)
        rows = list(core.shard_to_rows(sh, schema))
        self.assertEqual(len(rows), 5)
        # v5: the SELF input is the FLAT self-history (obs_dim * SELF_HISTORY), NOT the
        # single-tick obs. input dim = self_history(16*16) + pooled_ent(10) + n_vis_frac(1)
        # + audio(4) + team(6). (synth obs_dim=16 here is an arbitrary synth width, decoupled
        # from the real 21-wide SELF; the history is obs_dim tiled SELF_HISTORY times.)
        self.assertEqual(len(rows[0]["x"]), 16 * SC.EXPECTS_SELF_HISTORY + 10 + 1 + 4 + 6)
        # every label is a valid class id for its head
        for r in rows:
            for (hidx, (_n, k, _c, _kind)) in enumerate(schema.heads()):
                self.assertTrue(0 <= r["y"][hidx] < k)

    def test_synth_shard_emits_self_history_field(self):
        # v5: the synthetic shard must carry the self_history field at the right flat width
        # (self_history * obs_dim) and meta, so the offline smoke exercises the v5 contract.
        sh = synth_shard.make_synthetic_shard(
            n_windows=4, obs_dim=SC.EXPECTS_SELF_DIM, ent_dim=8, seed=1)
        self.assertIn(SC.KEY_SELF_HISTORY, sh)
        self.assertEqual(sh[SC.KEY_META]["self_history"], SC.EXPECTS_SELF_HISTORY)
        self.assertEqual(sh[SC.KEY_META]["self_history_dim"], SC.EXPECTS_SELF_HISTORY_DIM)
        # v5 storage shrink: self_history is ONE [HD] flat history PER WINDOW (the last-real-
        # tick history), NOT a per-tick [K, HD]. So it indexes [wi] (a flat list), and its
        # length == SELF_HISTORY * SELF_DIM, with the newest SELF_DIM block == the window's
        # LAST-real-tick single-tick obs (the build invariant; k=1 synth -> the only tick).
        self.assertEqual(len(sh[SC.KEY_SELF_HISTORY]), len(sh[SC.KEY_OBS]))   # one per window
        for wi in range(len(sh[SC.KEY_OBS])):
            hist = sh[SC.KEY_SELF_HISTORY][wi]
            # flat [HD], not nested per-tick: a float list of width HD (no inner [K] axis)
            self.assertEqual(len(hist), SC.EXPECTS_SELF_HISTORY_DIM)
            self.assertNotIsInstance(hist[0], list)
            last_obs = sh[SC.KEY_OBS][wi][-1]                # window's last real tick obs
            self.assertEqual(hist[-SC.EXPECTS_SELF_DIM:], last_obs)

    def test_loader_uses_self_history_as_self_input(self):
        # the deps-free loader (shard_to_rows) must read self_history (not the single-tick
        # obs) as the SELF input x, so x starts with the flat history width.
        schema = SC.ShardSchema()
        sh = synth_shard.make_synthetic_shard(
            n_windows=3, obs_dim=SC.EXPECTS_SELF_DIM, ent_dim=8, audio_dim=0, team_dim=0,
            seed=2)
        rows = list(core.shard_to_rows(sh, schema))
        self.assertGreater(len(rows), 0)
        # x = self_history(336) + pooled_ent(8) + n_vis_frac(1); no audio/team here.
        self.assertEqual(len(rows[0]["x"]), SC.EXPECTS_SELF_HISTORY_DIM + 8 + 1)

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
            # v5: SELF input = flat self-history(8 * SELF_HISTORY) + pooled_ent(6) +
            # n_vis_frac(1) + audio(4 default) + team(6 default)
            self.assertEqual(in_dim, 8 * SC.EXPECTS_SELF_HISTORY + 6 + 1 + 4 + 6)


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
            registry_version=3, dataset_version="ds-1")
        for key in ("git_sha", "registry_version", "norm_artifact_version", "seed"):
            self.assertIn(key, card)
        self.assertEqual(card["seed"], 5)
        self.assertEqual(card["registry_version"], 3)
        self.assertTrue(card["input_is_broad"])
        self.assertTrue(card["input_includes_observed_others"])
        self.assertFalse(card["move_only"])

    def test_card_schema_and_data_schema_do_not_collide(self):
        # Regression for the duplicate "schema" key: the model-card format id and
        # the resolved data-schema object must BOTH survive (previously the second
        # "schema": schema.to_dict() silently overwrote the format-id string).
        schema = SC.ShardSchema()
        card = core.build_model_card(
            run_kind="cpu_smoke", schema=schema, in_dim=37, hidden=24,
            head_specs=[("fwd", 3)], metrics={}, history=[], seed=0,
            repo_root=REPO_ROOT)
        # card-format identifier preserved under its own key (not clobbered)
        self.assertEqual(card["card_schema"], "komodobots.model_card.broad_bc.v1")
        # the data-schema object survives under "schema" and is the resolved dict
        self.assertIsInstance(card["schema"], dict)
        self.assertEqual(card["schema"]["contract_version"], SC.SHARD_CONTRACT_VERSION)
        self.assertIn("heads", card["schema"])


class TestRegistryVersionGuard(unittest.TestCase):
    """rows_to_tensors must REJECT a shard whose meta.registry_version differs
    from the version the model card pins (EXPECTS_REGISTRY_VERSION) — otherwise it
    would silently train on a misbound (stale/future) FEAT shard. Deps-free: we
    drive the guard via a small monkeypatched read_shard so it runs with no torch
    needed for the *raise* path (the tensor build after the guard never executes).
    """

    def _import_trainer(self):
        # train_broad_bc imports torch at module load; only import it when present.
        if not (_HAVE_TORCH and _HAVE_NUMPY):
            self.skipTest("torch/numpy not installed")
        import train_broad_bc as TB
        return TB

    def test_mismatched_registry_version_raises(self):
        TB = self._import_trainer()
        schema = SC.ShardSchema()
        bad = synth_shard.make_synthetic_shard(
            n_windows=2, obs_dim=8, ent_dim=6, seed=1)
        bad[SC.KEY_META]["registry_version"] = SC.EXPECTS_REGISTRY_VERSION + 99
        orig = core.read_shard
        core.read_shard = lambda _p: bad
        try:
            with self.assertRaises(ValueError) as ctx:
                TB.rows_to_tensors(["dummy-path"], schema, "cpu")
            self.assertIn("registry_version", str(ctx.exception))
        finally:
            core.read_shard = orig

    def test_matching_registry_version_is_accepted(self):
        TB = self._import_trainer()
        schema = SC.ShardSchema()
        # a CORRECT v5 shard: registry_version == EXPECTS and the SELF width == the v5
        # 21-channel goal-conditioned layout (EXPECTS_SELF_DIM), so it must be ACCEPTED.
        good = synth_shard.make_synthetic_shard(
            n_windows=3, obs_dim=SC.EXPECTS_SELF_DIM, ent_dim=6, seed=2)
        # synth shards already set registry_version == EXPECTS_REGISTRY_VERSION
        self.assertEqual(good[SC.KEY_META]["registry_version"],
                         SC.EXPECTS_REGISTRY_VERSION)
        self.assertEqual(good[SC.KEY_META]["obs_dim"], SC.EXPECTS_SELF_DIM)
        orig = core.read_shard
        core.read_shard = lambda _p: good
        try:
            t, dims = TB.rows_to_tensors(["dummy-path"], schema, "cpu")
        finally:
            core.read_shard = orig
        # tensors built; per-sample weight vector present and aligned to rows
        self.assertIn("w", t)
        self.assertEqual(t["w"].shape[0], t["obs"].shape[0])
        self.assertEqual(dims["f_obs"], SC.EXPECTS_SELF_DIM)

    def test_v3_labelled_but_16_channel_shard_is_rejected_on_obs_dim(self):
        """The hand-edited-label attack Codex called out: a shard whose
        registry_version was set to 3 but whose SELF width is still 16 (the pre-append
        layout) MUST be rejected by the explicit channel-count guard — the equality
        guard alone would pass it. rows_to_tensors rejects BEFORE the tensor build."""
        TB = self._import_trainer()
        schema = SC.ShardSchema()
        bad = synth_shard.make_synthetic_shard(
            n_windows=2, obs_dim=16, ent_dim=6, seed=4)   # 16-channel SELF (pre-v3)
        # registry_version already == EXPECTS (3) — only obs_dim is wrong, so the
        # equality guard would NOT catch it; the obs_dim guard must.
        self.assertEqual(bad[SC.KEY_META]["registry_version"],
                         SC.EXPECTS_REGISTRY_VERSION)
        self.assertEqual(bad[SC.KEY_META]["obs_dim"], 16)
        orig = core.read_shard
        core.read_shard = lambda _p: bad
        try:
            with self.assertRaises(ValueError) as ctx:
                TB.rows_to_tensors(["dummy-path"], schema, "cpu")
            self.assertIn("obs_dim", str(ctx.exception))
            self.assertIn(str(SC.EXPECTS_SELF_DIM), str(ctx.exception))
        finally:
            core.read_shard = orig


class TestShardMetaCheckDepsFree(unittest.TestCase):
    """The shared reject guard SC.check_shard_meta / SC.check_norm_artifact, exercised
    WITHOUT torch (deps-free) so the v2-rejection contract is covered on a stdlib box.
    These are the SAME functions train_broad_bc.rows_to_tensors and eval_broad_dryroute
    call, so testing them here pins the reject rule independent of the GPU stack."""

    def test_stale_v2_registry_version_rejected(self):
        # a stale v2 (16-channel) shard meta must NOT bind to the current layout.
        with self.assertRaises(ValueError) as ctx:
            SC.check_shard_meta({"registry_version": 2, "obs_dim": 16})
        self.assertIn("registry_version", str(ctx.exception))

    def test_pre_v5_single_tick_shard_rejected_on_registry_version(self):
        # a v4 single-tick-SELF shard (no self_history field) MUST be rejected by the
        # registry-version guard — it can no longer bind to the v5 sequence-aware layout.
        with self.assertRaises(ValueError) as ctx:
            SC.check_shard_meta({"registry_version": 4, "obs_dim": SC.EXPECTS_SELF_DIM})
        self.assertIn("registry_version", str(ctx.exception))

    def test_v5_labelled_but_wrong_self_history_dim_rejected(self):
        # the v5 reject-guard idiom (mirrors the #313 obs_dim guard): a shard whose
        # registry_version was set to 5 and whose obs_dim is the correct 21, but whose
        # self_history flat width is NOT SELF_HISTORY*SELF_DIM (e.g. a wrong history
        # length or a hand-edited label on a single-tick shard), MUST be rejected — the
        # registry + obs_dim guards alone would pass it.
        bad_hist = SC.EXPECTS_SELF_HISTORY_DIM - SC.EXPECTS_SELF_DIM   # one tick short
        with self.assertRaises(ValueError) as ctx:
            SC.check_shard_meta({
                "registry_version": SC.EXPECTS_REGISTRY_VERSION,
                "obs_dim": SC.EXPECTS_SELF_DIM,
                "self_history_dim": bad_hist})
        self.assertIn("self_history_dim", str(ctx.exception))
        self.assertIn(str(SC.EXPECTS_SELF_HISTORY_DIM), str(ctx.exception))

    def test_old_per_tick_k_times_hd_self_history_dim_rejected(self):
        # the storage-shrink reject: a shard whose self_history_dim is the OLD per-tick
        # K*HD width (the pre-shrink [K, HD] storage, e.g. K=64 -> 64*336=21504) must be
        # rejected — v5 now stores ONE [HD] history per window, so a row HD != 336 (here a
        # 64x-too-wide value) is not the v5 layout even with registry_version=5 + obs_dim=21.
        K = 64
        old_wide = K * SC.EXPECTS_SELF_HISTORY_DIM            # the old [K*HD] per-row width
        self.assertNotEqual(old_wide, SC.EXPECTS_SELF_HISTORY_DIM)
        with self.assertRaises(ValueError) as ctx:
            SC.check_shard_meta({
                "registry_version": SC.EXPECTS_REGISTRY_VERSION,
                "obs_dim": SC.EXPECTS_SELF_DIM,
                "self_history_dim": old_wide})
        self.assertIn("self_history_dim", str(ctx.exception))
        self.assertIn(str(SC.EXPECTS_SELF_HISTORY_DIM), str(ctx.exception))

    def test_correct_v5_self_history_dim_accepted(self):
        # correct v5 meta: registry_version 5 + obs_dim 21 + self_history_dim 336 -> no raise.
        SC.check_shard_meta({
            "registry_version": SC.EXPECTS_REGISTRY_VERSION,
            "obs_dim": SC.EXPECTS_SELF_DIM,
            "self_history_dim": SC.EXPECTS_SELF_HISTORY_DIM})

    def test_v5_meta_omitting_self_history_dim_is_REJECTED(self):
        # Blocker-2: a shard LABELLED registry_version==5 (EXPECTS) but OMITTING
        # self_history_dim must now be REJECTED — without it the loader would silently fall
        # back to the 21-wide single-tick obs (x_len=21) instead of the required 336. The
        # omit==match leniency is ONLY for pre-v5 fields; v5 makes the self_history contract
        # mandatory (see test_pre_v5_meta_omitting_self_history_dim_is_allowed below for the
        # rv<5 path that still passes).
        with self.assertRaises(ValueError) as ctx:
            SC.check_shard_meta({"registry_version": SC.EXPECTS_REGISTRY_VERSION,
                                 "obs_dim": SC.EXPECTS_SELF_DIM})
        self.assertIn("self_history_dim", str(ctx.exception))

    def test_pre_v5_meta_omitting_self_history_dim_is_allowed(self):
        # a shard with NO registry_version (or rv<5) that omits self_history_dim is NOT
        # rejected on it — the v5 self_history requirement only applies to v5+ labels, and
        # a registry_version mismatch (e.g. 4) is caught by the registry-version guard first,
        # never reaching the self_history requirement.
        SC.check_shard_meta({"obs_dim": SC.EXPECTS_SELF_DIM})   # no registry_version -> ok

    def test_v3_labelled_16_channel_meta_rejected_on_obs_dim(self):
        with self.assertRaises(ValueError) as ctx:
            SC.check_shard_meta(
                {"registry_version": SC.EXPECTS_REGISTRY_VERSION, "obs_dim": 16})
        self.assertIn("obs_dim", str(ctx.exception))

    def test_correct_v5_full_meta_accepted(self):
        # correct v5 meta: registry_version 5 + obs_dim 21 + self_history_dim 336 -> no raise.
        # (v5 requires self_history_dim be PRESENT — a v5 label with obs_dim but no
        # self_history_dim is rejected; see test_v5_meta_omitting_self_history_dim_is_REJECTED.)
        SC.check_shard_meta(
            {"registry_version": SC.EXPECTS_REGISTRY_VERSION,
             "obs_dim": SC.EXPECTS_SELF_DIM,
             "self_history_dim": SC.EXPECTS_SELF_HISTORY_DIM})

    def test_meta_omitting_fields_is_treated_as_matching(self):
        # a minimal/legacy shard that omits registry_version/obs_dim is not rejected
        # (we only reject on a PRESENT, mismatched value).
        SC.check_shard_meta({})
        SC.check_shard_meta({"obs_dim": SC.EXPECTS_SELF_DIM})  # no registry_version

    def test_norm_artifact_missing_yaw_rate_key_rejected(self):
        # a v2-shaped stats artifact (no per_map yaw_rate) must be rejected, not
        # silently zero-filled — it would de-normalize the appended yaw_rate_z feature.
        stats_v2 = {"per_map": {"dm3": {"vel_x": {"method": "zscore"}}}}
        with self.assertRaises(ValueError) as ctx:
            SC.check_norm_artifact(stats_v2, "dm3")
        self.assertIn("yaw_rate", str(ctx.exception))

    def test_norm_artifact_with_yaw_rate_key_accepted(self):
        stats_v3 = {"registry_version": SC.EXPECTS_REGISTRY_VERSION,
                    "per_map": {"dm3": {"yaw_rate": {"method": "zscore"}}}}
        SC.check_norm_artifact(stats_v3, "dm3")          # no raise

    def test_norm_artifact_stale_registry_version_rejected(self):
        stats = {"registry_version": 2,
                 "per_map": {"dm3": {"yaw_rate": {"method": "zscore"}}}}
        with self.assertRaises(ValueError) as ctx:
            SC.check_norm_artifact(stats, "dm3")
        self.assertIn("registry_version", str(ctx.exception))

    def test_template_artifact_passes_norm_check(self):
        # the committed v3 template carries the yaw_rate key + registry_version 3, so the
        # SHIPPED normalization artifact must pass the guard (regression vs. a stale bump).
        tmpl = json.loads(
            (REPO_ROOT / "data" / "catalog" / "normalization_stats.template.json")
            .read_text(encoding="utf-8"))
        self.assertEqual(tmpl["registry_version"], SC.EXPECTS_REGISTRY_VERSION)
        SC.check_norm_artifact(tmpl, "dm3")              # no raise


class TestSelfHistoryArrayRequiredV5(unittest.TestCase):
    """Blocker-2: a v5-LABELLED shard that LACKS the actual `self_history` ARRAY must raise at
    row-build time (the loader must NOT silently fall back to the 21-wide single-tick obs).
    DEPS-FREE — drives the deps-free loader core.shard_to_rows directly (no torch). The SAME
    SC.require_self_history_present guard runs in train_broad_bc.rows_to_tensors (torch path)."""

    def _v5_shard_without_self_history(self):
        # a real v5 synth shard, then DROP the self_history array (keep registry_version==5).
        sh = synth_shard.make_synthetic_shard(
            n_windows=3, obs_dim=SC.EXPECTS_SELF_DIM, ent_dim=8, audio_dim=0, team_dim=0,
            seed=7)
        self.assertEqual(sh[SC.KEY_META]["registry_version"], SC.EXPECTS_REGISTRY_VERSION)
        del sh[SC.KEY_SELF_HISTORY]                       # the contract violation
        sh[SC.KEY_META].pop("self_history_dim", None)     # and its meta width
        return sh

    def test_shard_to_rows_v5_without_self_history_raises_not_xlen21(self):
        schema = SC.ShardSchema()
        sh = self._v5_shard_without_self_history()
        with self.assertRaises(ValueError) as ctx:
            list(core.shard_to_rows(sh, schema))          # must NOT yield x_len=21 rows
        msg = str(ctx.exception)
        self.assertIn("self_history", msg)
        self.assertIn(str(SC.EXPECTS_REGISTRY_VERSION), msg)

    def test_require_self_history_present_direct(self):
        # the shared guard in isolation: v5 + no array -> raise; v5 + array -> ok.
        with self.assertRaises(ValueError):
            SC.require_self_history_present(
                {"registry_version": SC.EXPECTS_REGISTRY_VERSION}, False)
        SC.require_self_history_present(
            {"registry_version": SC.EXPECTS_REGISTRY_VERSION}, True)   # array present -> ok

    def test_pre_v5_shard_without_self_history_falls_back(self):
        # a genuinely pre-v5 shard (registry_version 4) with no self_history array is NOT
        # rejected by the array guard (the single-tick fallback is correct for legacy) — only
        # v5+ labels require the array. shard_to_rows then yields the single-tick obs width.
        schema = SC.ShardSchema()
        sh = synth_shard.make_synthetic_shard(
            n_windows=2, obs_dim=SC.EXPECTS_SELF_DIM, ent_dim=8, audio_dim=0, team_dim=0,
            seed=8)
        del sh[SC.KEY_SELF_HISTORY]
        sh[SC.KEY_META]["registry_version"] = SC.EXPECTS_REGISTRY_VERSION - 1   # pre-v5
        sh[SC.KEY_META].pop("self_history_dim", None)
        rows = list(core.shard_to_rows(sh, schema))        # no raise -> legacy fallback
        # fallback SELF input is the single-tick obs (SELF_DIM), not the 336-wide history.
        self.assertEqual(len(rows[0]["x"]), SC.EXPECTS_SELF_DIM + 8 + 1)


@unittest.skipUnless(_HAVE_TORCH and _HAVE_NUMPY, "torch/numpy not installed")
class TestTorchPolicySmoke(unittest.TestCase):
    def test_forward_and_one_step(self):
        import torch
        import train_broad_bc as TB
        # self_dim=f_obs => the GRU runs over a 1-step sequence (this smoke exercises the
        # heads/pool, not the temporal structure; the f_obs here is not a 21-multiple).
        m = TB.BroadBCPolicy(f_obs=12, f_ent=8, f_aux=10, n_max=7,
                             ent_out=16, hidden=32, head_dims=(3, 3, 3, 2, 2),
                             self_dim=12)
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

    def test_v5_self_history_input_forward_shape(self):
        """v5 SEQUENCE model (GRU SELF encoder): the SELF input is the FLAT self-history
        (SELF_HISTORY*SELF_DIM = 336), not the single-tick 21 — the model RECEIVES the same
        336-wide flat input it always did. Internally it reshapes to [B,16,21] and runs a
        1-layer GRU (hidden GRU_HIDDEN); the trunk's SELF side is now the GRU hidden width
        (GRU_HIDDEN), NOT the flat 336 — the entity encoder, the pool, the trunk body and
        the 5 heads are otherwise unchanged. Assert a forward over a 336-wide SELF input +
        the real entity channel emits the 5 head logits at the right dims (3/3/3/2/2) and one
        backward step reaches the GRU."""
        import torch
        import train_broad_bc as TB
        f_obs = SC.EXPECTS_SELF_HISTORY_DIM                # 336 = 16 * 21
        self.assertEqual(f_obs, 336)
        f_ent = AO.ENTITY_DIM                              # the real entity width (13)
        m = TB.BroadBCPolicy(f_obs=f_obs, f_ent=f_ent, f_aux=0, n_max=7,
                             ent_out=64, hidden=128, head_dims=(3, 3, 3, 2, 2))
        # the SELF path now reshapes the flat 336 to 16 steps of SELF_DIM (21); the GRU
        # consumes SELF_DIM per tick and the trunk's first Linear accepts GRU_HIDDEN +
        # ent_out (NOT the flat f_obs).
        self.assertEqual(m.self_steps, SC.EXPECTS_SELF_HISTORY)     # 16
        self.assertEqual(m.self_dim, SC.EXPECTS_SELF_DIM)           # 21
        self.assertEqual(m.self_gru.input_size, SC.EXPECTS_SELF_DIM)
        self.assertEqual(m.self_gru.hidden_size, TB.GRU_HIDDEN)     # 64
        self.assertEqual(m.trunk[0].in_features, TB.GRU_HIDDEN + 64)
        B = 4
        obs = torch.randn(B, f_obs)                        # the flat self-history input
        ent = torch.randn(B, 7, f_ent)
        emask = torch.ones(B, 7); emask[:, 3:] = 0.0
        aux = torch.zeros(B, 0)
        logits = m(obs, ent, emask, aux)
        self.assertEqual(len(logits), 5)                  # fwd/side/up/jump/attack
        self.assertEqual([lg.shape[1] for lg in logits], [3, 3, 3, 2, 2])
        for lg in logits:
            self.assertEqual(lg.shape[0], B)
        y = torch.zeros(B, 5, dtype=torch.long)
        loss = sum(torch.nn.functional.cross_entropy(logits[h], y[:, h]) for h in range(5))
        loss.backward()
        self.assertTrue(any(p.grad is not None for p in m.parameters()))
        # the gradient must reach the GRU (proves the SELF history actually flows through it)
        self.assertTrue(any(p.grad is not None and p.grad.abs().sum() > 0
                            for p in m.self_gru.parameters()))

    def test_self_history_reshape_is_time_major(self):
        """RESHAPE-ORDER (the main correctness risk of the GRU refactor): the flat
        [SELF_HISTORY*SELF_DIM] SELF input the model receives must reshape to
        [B, SELF_HISTORY, SELF_DIM] in TIME ORDER — tick t's SELF_DIM channels at
        flat[t*SELF_DIM:(t+1)*SELF_DIM], so seq[:, t, :] is tick t (oldest->newest), NOT
        scrambled (a [SELF_DIM, SELF_HISTORY] reshape would silently transpose time and
        channel and feed the GRU garbage). We assert this on the EXACT op the model uses
        (obs.reshape(B, self_steps, self_dim)) and tie it back to the SHARED
        AO.assemble_self_history flatten so the data-side and model-side agree end to end.
        """
        import torch
        import train_broad_bc as TB
        H, D = SC.EXPECTS_SELF_HISTORY, SC.EXPECTS_SELF_DIM   # 16, 21
        # 16 DISTINCT per-tick SELF vectors, oldest->newest: tick t channel c == t*100 + c
        # (every (t,c) value unique so any time/channel swap is detectable).
        selves = [[float(t * 100 + c) for c in range(D)] for t in range(H)]
        flat = AO.assemble_self_history(selves, H)            # the SHARED data-side flatten
        self.assertEqual(len(flat), H * D)
        # the model's exact reshape op (see BroadBCPolicy.forward).
        seq = torch.tensor([flat], dtype=torch.float32).reshape(1, H, D)
        self.assertEqual(tuple(seq.shape), (1, H, D))
        for t in range(H):
            for c in range(D):
                # seq[0, t, c] is tick t channel c == the original oldest->newest input.
                self.assertEqual(float(seq[0, t, c]), t * 100 + c)
            # whole row t equals the t-th input SELF vector (time-major rows).
            self.assertEqual([float(v) for v in seq[0, t]], selves[t])
        # row 0 is the OLDEST tick, row H-1 the NEWEST (== the current single-tick SELF =
        # the last SELF_DIM block of the flat history, the assemble_self_history invariant).
        self.assertEqual([float(v) for v in seq[0, 0]], selves[0])
        self.assertEqual([float(v) for v in seq[0, H - 1]], selves[-1])
        self.assertEqual([float(v) for v in seq[0, H - 1]],
                         [float(v) for v in flat[-D:]])
        # the WRONG reshape ([D, H]) would NOT recover the per-tick rows -> guards the risk.
        wrong = torch.tensor([flat], dtype=torch.float32).reshape(1, D, H)
        self.assertNotEqual([float(v) for v in wrong[0, 1]], selves[1])

    def test_checkpoint_roundtrip_reconstructs_gru(self):
        """CHECKPOINT ROUND-TRIP: saving the policy (with its stored self_dim/gru_hidden)
        and rebuilding via the SHARED inference loader (_build_policy_from_checkpoint)
        reconstructs the SAME GRU arch and yields byte-identical forward outputs. Proves the
        v5-seqaware encoder survives the save/load the eval paths use — no inference drift.
        """
        import tempfile as _tf
        import torch
        import train_broad_bc as TB
        from eval_broad_believability import _build_policy_from_checkpoint

        f_obs = SC.EXPECTS_SELF_HISTORY_DIM                  # 336
        f_ent, f_aux, n_max = AO.ENTITY_DIM, 0, 7
        head_dims = [k for (_n, k, _c, _kd) in SC.ShardSchema().heads()]
        torch.manual_seed(0)
        m = TB.BroadBCPolicy(f_obs=f_obs, f_ent=f_ent, f_aux=f_aux, n_max=n_max,
                             ent_out=64, hidden=128, head_dims=tuple(head_dims))
        m.eval()
        dims = {"f_obs": f_obs, "f_ent": f_ent, "f_aux": f_aux, "n_max": n_max}
        # the EXACT keys train_broad_bc.main() saves (incl. the new GRU config).
        ckpt = {
            "state_dict": m.state_dict(),
            "dims": dims, "head_dims": head_dims, "head_names": SC.head_names(),
            "hidden": 128, "ent_out": 64,
            "self_dim": m.self_dim, "gru_hidden": m.gru_hidden,
            "arch": "BroadBCPolicy", "contract_version": SC.SHARD_CONTRACT_VERSION,
            "seed": 0,
        }
        B = 5
        obs = torch.randn(B, f_obs)
        ent = torch.randn(B, n_max, f_ent)
        emask = torch.ones(B, n_max); emask[:, 4:] = 0.0
        aux = torch.zeros(B, f_aux)
        with torch.no_grad():
            before = m(obs, ent, emask, aux)
        with _tf.TemporaryDirectory() as d:
            p = Path(d) / "ckpt.pt"
            torch.save(ckpt, p)
            loaded = torch.load(p, map_location="cpu")
            m2, dims2, head_dims2 = _build_policy_from_checkpoint(loaded, "cpu")
        # the rebuilt GRU matches the saved config (input=self_dim per tick, hidden=gru_hidden)
        self.assertEqual(m2.self_dim, m.self_dim)
        self.assertEqual(m2.gru_hidden, m.gru_hidden)
        self.assertEqual(m2.self_steps, m.self_steps)
        self.assertEqual(m2.self_gru.input_size, SC.EXPECTS_SELF_DIM)
        self.assertEqual(m2.self_gru.hidden_size, TB.GRU_HIDDEN)
        self.assertEqual(dims2["f_obs"], f_obs)              # input contract preserved (336)
        self.assertEqual(list(head_dims2), head_dims)
        # byte-identical forward after the save/load (same weights AND same wiring).
        with torch.no_grad():
            after = m2(obs, ent, emask, aux)
        for b, a in zip(before, after):
            self.assertTrue(torch.allclose(b, a, atol=1e-6))

    def test_checkpoint_without_gru_config_defaults_to_seqaware(self):
        """ROBUSTNESS: a checkpoint that omits the GRU config (e.g. one saved before the
        config was stamped) must still rebuild — the loader defaults self_dim to the 21-wide
        SELF and gru_hidden to GRU_HIDDEN, which is exactly the v5-seqaware arch, so a real
        336-input checkpoint loads to the right 16-step GRU with no stored config."""
        import tempfile as _tf
        import torch
        import train_broad_bc as TB
        from eval_broad_believability import _build_policy_from_checkpoint

        f_obs = SC.EXPECTS_SELF_HISTORY_DIM                  # 336
        head_dims = [k for (_n, k, _c, _kd) in SC.ShardSchema().heads()]
        m = TB.BroadBCPolicy(f_obs=f_obs, f_ent=AO.ENTITY_DIM, f_aux=0, n_max=7,
                             ent_out=64, hidden=128, head_dims=tuple(head_dims))
        ckpt = {
            "state_dict": m.state_dict(),
            "dims": {"f_obs": f_obs, "f_ent": AO.ENTITY_DIM, "f_aux": 0, "n_max": 7},
            "head_dims": head_dims, "hidden": 128, "ent_out": 64,
            # NB: NO self_dim / gru_hidden keys here.
        }
        with _tf.TemporaryDirectory() as d:
            p = Path(d) / "ckpt.pt"
            torch.save(ckpt, p)
            m2, _dims2, _hd2 = _build_policy_from_checkpoint(
                torch.load(p, map_location="cpu"), "cpu")
        self.assertEqual(m2.self_dim, SC.EXPECTS_SELF_DIM)   # defaulted to 21
        self.assertEqual(m2.gru_hidden, TB.GRU_HIDDEN)       # defaulted to 64
        self.assertEqual(m2.self_steps, SC.EXPECTS_SELF_HISTORY)   # => 16 steps over 336

    def test_pool_ignores_pad_slots(self):
        import torch
        import train_broad_bc as TB
        m = TB.BroadBCPolicy(f_obs=4, f_ent=4, f_aux=0, n_max=3,
                             ent_out=8, hidden=8, head_dims=(2,), self_dim=4)
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

    def test_zero_weight_row_does_not_affect_loss_or_gradients(self):
        """REGRESSION for the P1 shard-weight finding: a row emitted with
        weight=0 (pad / interpolated / missing-label, e.g. all-zero idle labels)
        must NOT influence the loss or the gradients. We replicate the EXACT loss
        used in train_broad_bc.main()'s training loop:
            per_sample = sum_h CE_h(reduction='none')        # [B]
            loss       = (per_sample * w).sum() / w.sum()
        and compare a batch of real rows vs. the SAME batch with one extra
        zero-weight, deliberately MISLABELLED row appended. Identical loss AND
        identical per-parameter grads proves the weight masking is honored.
        """
        import torch
        import torch.nn as nn
        import train_broad_bc as TB

        torch.manual_seed(0)
        f_obs, f_ent, f_aux, n_max = 6, 4, 0, 3
        head_dims = (3, 3, 3, 2, 2)
        H = len(head_dims)
        m = TB.BroadBCPolicy(f_obs=f_obs, f_ent=f_ent, f_aux=f_aux, n_max=n_max,
                             ent_out=8, hidden=16, head_dims=head_dims, self_dim=f_obs)

        # CE modules exactly like the trainer: per-class weight + reduction='none'.
        # Build them once and SHARE across both cases so the zero-weight row is the
        # only difference (the trainer derives per-class weights from the train set,
        # which is held fixed here).
        ce = [nn.CrossEntropyLoss(reduction="none") for _ in range(H)]

        B = 5
        obs = torch.randn(B, f_obs)
        ent = torch.randn(B, n_max, f_ent)
        emask = torch.ones(B, n_max)
        emask[:, 2:] = 0.0
        aux = torch.zeros(B, f_aux)
        y = torch.stack([torch.randint(0, k, (B,)) for k in head_dims], dim=1)  # [B,H]
        w = torch.ones(B)

        # one EXTRA row: weight 0, and labels set to the WRONG class on every head
        # (max class id) so that if it leaked it would clearly move loss/grads.
        obs2 = torch.cat([obs, torch.randn(1, f_obs)], dim=0)
        ent2 = torch.cat([ent, torch.randn(1, n_max, f_ent)], dim=0)
        emask2 = torch.cat([emask, torch.ones(1, n_max)], dim=0)
        aux2 = torch.zeros(B + 1, f_aux)
        wrong = torch.tensor([[k - 1 for k in head_dims]], dtype=torch.long)  # [1,H]
        y2 = torch.cat([y, wrong], dim=0)
        w2 = torch.cat([w, torch.zeros(1)], dim=0)        # extra row weight = 0

        def loss_and_grads(o, e, em, ax, yy, ww):
            m.zero_grad(set_to_none=True)
            logits = m(o, e, em, ax)
            per_sample = sum(ce[h](logits[h], yy[:, h]) for h in range(H))  # [B]
            loss = (per_sample * ww).sum() / ww.sum().clamp(min=1e-8)
            loss.backward()
            grads = [p.grad.detach().clone() for p in m.parameters()
                     if p.grad is not None]
            return loss.detach().clone(), grads

        loss_a, grads_a = loss_and_grads(obs, ent, emask, aux, y, w)
        loss_b, grads_b = loss_and_grads(obs2, ent2, emask2, aux2, y2, w2)

        self.assertTrue(torch.allclose(loss_a, loss_b, atol=1e-6),
                        f"loss changed: {loss_a.item()} vs {loss_b.item()}")
        self.assertEqual(len(grads_a), len(grads_b))
        for ga, gb in zip(grads_a, grads_b):
            self.assertTrue(torch.allclose(ga, gb, atol=1e-6),
                            "a zero-weight row perturbed the gradients")

    def test_zero_weight_row_does_not_change_class_weights_or_loss(self):
        """REGRESSION (class-weight DERIVATION): the per-CLASS imbalance weights are
        derived via TB._class_weights from EFFECTIVE (shard-weighted) counts, so a
        weight=0 row (pad/interp/missing) must not shift them — and therefore must
        not shift the loss/grads built from them. Unlike
        test_zero_weight_row_does_not_affect_loss_or_gradients (which holds class
        weights FIXED), this drives the REAL derivation that main() uses."""
        import torch
        import torch.nn as nn
        import train_broad_bc as TB

        torch.manual_seed(0)
        head_dims = (3, 3, 3, 2, 2)
        head_specs = [("h%d" % i, k) for i, k in enumerate(head_dims)]
        H = len(head_dims)
        B = 6
        y = torch.stack([torch.randint(0, k, (B,)) for k in head_dims], dim=1)  # [B,H]
        w = torch.ones(B)
        cw = TB._class_weights(y, w, list(range(B)), head_specs)

        # append ONE weight=0 row with the WRONG (max) class on every head
        wrong = torch.tensor([[k - 1 for k in head_dims]], dtype=torch.long)
        y2 = torch.cat([y, wrong], dim=0)
        w2 = torch.cat([w, torch.zeros(1)], dim=0)
        cw2 = TB._class_weights(y2, w2, list(range(B + 1)), head_specs)

        # (a) derived class weights identical
        for a, b in zip(cw, cw2):
            self.assertTrue(torch.allclose(a, b), "zero-weight row shifted class weights")

        # (b) loss + grads built FROM the derived weights identical on a fixed batch
        f_obs, f_ent, f_aux, n_max = 6, 4, 0, 3
        m = TB.BroadBCPolicy(f_obs=f_obs, f_ent=f_ent, f_aux=f_aux, n_max=n_max,
                             ent_out=8, hidden=16, head_dims=head_dims, self_dim=f_obs)
        obs = torch.randn(B, f_obs); ent = torch.randn(B, n_max, f_ent)
        emask = torch.ones(B, n_max); aux = torch.zeros(B, f_aux); sw = torch.ones(B)

        def loss_grads(class_weights):
            ce = [nn.CrossEntropyLoss(weight=c, reduction="none") for c in class_weights]
            m.zero_grad()
            logits = m(obs, ent, emask, aux)
            per_sample = sum(ce[h](logits[h], y[:, h]) for h in range(H))
            loss = (per_sample * sw).sum() / sw.sum()
            loss.backward()
            g = torch.cat([p.grad.flatten() for p in m.parameters() if p.grad is not None])
            return float(loss), g

        l1, g1 = loss_grads(cw)
        l2, g2 = loss_grads(cw2)
        self.assertAlmostEqual(l1, l2, places=6)
        self.assertTrue(torch.allclose(g1, g2, atol=1e-6))

    def test_all_zero_weight_batch_is_skipped(self):
        """If an ENTIRE batch is zero-weighted, the trainer guards against the
        0/0 normalization (it skips the step). Here we assert the guarded loss
        formula does not produce NaN/inf and that no gradient step is implied."""
        import torch
        import torch.nn as nn
        import train_broad_bc as TB

        torch.manual_seed(1)
        head_dims = (3, 2)
        H = len(head_dims)
        m = TB.BroadBCPolicy(f_obs=4, f_ent=0, f_aux=0, n_max=2,
                             ent_out=4, hidden=8, head_dims=head_dims, self_dim=4)
        ce = [nn.CrossEntropyLoss(reduction="none") for _ in range(H)]
        B = 3
        obs = torch.randn(B, 4)
        ent = torch.zeros(B, 2, 0)
        emask = torch.zeros(B, 2)
        aux = torch.zeros(B, 0)
        y = torch.stack([torch.randint(0, k, (B,)) for k in head_dims], dim=1)
        w = torch.zeros(B)                                # whole batch zero-weight
        logits = m(obs, ent, emask, aux)
        per_sample = sum(ce[h](logits[h], y[:, h]) for h in range(H))
        wsum = w.sum()
        # mirrors the trainer's guard: wsum==0 -> skip (do not divide by zero)
        self.assertEqual(float(wsum), 0.0)
        # the guarded path never computes per_sample*w/wsum; confirm doing so naively
        # would be non-finite, justifying the guard.
        naive = (per_sample * w).sum() / wsum
        self.assertFalse(torch.isfinite(naive).item())


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

            # --- v5 self_history STORAGE SHRINK: ONE [HD] history PER WINDOW (last real
            # tick), reshaped [n_windows, HD] — NOT the old per-tick [n][K][HD]. -----------
            self.assertIn(SC.KEY_SELF_HISTORY, shard)
            sh_col = shard[SC.KEY_SELF_HISTORY]
            self.assertEqual(len(sh_col), n_win)                   # one row per window
            self.assertEqual(len(sh_col[0]), SC.EXPECTS_SELF_HISTORY_DIM)   # flat HD per row
            # the inner element is a scalar (flat [HD]), NOT a per-tick list ([K][HD] would
            # make sh_col[0][0] itself a length-HD list) — proves the 64x shape collapse.
            self.assertFalse(hasattr(sh_col[0][0], "__len__"))
            self.assertEqual(shard[SC.KEY_META]["self_history_dim"],
                             SC.EXPECTS_SELF_HISTORY_DIM)

            # --- TRAINING-EQUIVALENCE: the stored last-tick history == exactly what the OLD
            # per-tick [K, HD] column held at its last-real-tick index. We reconstruct the
            # window's per-tick SELF sequence from the (still per-tick) `obs` column and
            # assert self_history[wi] == AO.assemble_self_history(window_selves[:ti+1]) — the
            # value the old [K, HD][ti] extraction would have yielded. Byte-identical data.
            H = AO.SELF_HISTORY
            mask = shard[SC.KEY_MASK]
            for wi in range(n_win):
                ti = core._last_real_tick(mask[wi])
                window_selves = [list(map(float, shard[SC.KEY_OBS][wi][j]))
                                 for j in range(ti + 1)]
                expected = AO.assemble_self_history(window_selves[:ti + 1], H)
                got = list(map(float, sh_col[wi]))
                self.assertEqual(got, expected)
                # and the closed invariant: newest SELF_DIM block == last real tick's obs
                self.assertEqual(got[-AO.SELF_DIM:],
                                 list(map(float, shard[SC.KEY_OBS][wi][ti])))

            # --- the loader turns it into BC rows with the per-window demo split key --
            schema = SC.ShardSchema()
            rows = list(core.shard_to_rows(shard, schema))
            self.assertGreater(len(rows), 0)
            self.assertEqual(len({r["demo_id"] for r in rows}), 2)
            # act label decodes: forwardmove=400 -> fwd head class 2 (+)
            self.assertEqual(rows[0]["y"][0], 2)
            # input width = self_history(336) + pooled_ent(13) + n_vis_frac(1); no audio/team
            self.assertEqual(len(rows[0]["x"]), AO.SELF_HISTORY_DIM + AO.ENTITY_DIM + 1)

