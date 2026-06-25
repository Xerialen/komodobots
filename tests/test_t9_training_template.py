"""test_t9_training_template.py — T9 #397 capstone: the training-connection template.

The two highest-risk properties get ADVERSARIAL fixtures that would FAIL on a naive impl:

  * test_asof_join_does_not_leak_future — a future-timestamped item_event exists; the obs at
    tick T must attach the LATEST event at-or-before T, NEVER the future one. A naive
    "nearest" or "next" join leaks; asof_latest_leq must not.
  * test_norm_refit_is_train_split_only — train vs val/test rows are DELIBERATELY disjoint in
    value; the refit must equal the train-only computation and DIFFER from the all-rows
    computation (proving val/test never touched the scaler).

Plus: dataset_spec.yaml parses with the stdlib reader (and matches shard_contract's pinned
constants), and the worked consumer assembles a correctly-shaped obs from a fixture catalog.

Pure stdlib; runs under `python -m unittest`.
"""
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
SCRIPTS = REPO_ROOT / "scripts"
PIPELINE = REPO_ROOT / "ml" / "pipeline"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(PIPELINE))

import dataset_spec as DS                 # noqa: E402
import assemble_obs_template as AOT       # noqa: E402
import normalize_fit as NF                # noqa: E402
from features import agent_observation as AO   # noqa: E402

SCHEMA_SQL = (SCRIPTS / "catalog_schema.sql").read_text()
TEMPLATE_STATS = REPO_ROOT / "data" / "catalog" / "normalization_stats.template.json"


# =============================================================================
# Fixture catalog builder — a few demos/episodes/ticks, T3-T8 columns populated.
# =============================================================================
def _con() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA_SQL)
    con.execute("INSERT INTO maps (map_id, name, x_min, x_max, y_min, y_max, z_min, z_max, "
                "diagonal) VALUES (1, 'dm3', -984, 2048, -960, 1136, -416, 496, 3797.1)")
    return con


def _seed_demo(con, demo_id, sha, damage_available):
    con.execute(
        "INSERT INTO demos (demo_id, path, source, map_id, sha256, damage_available) "
        "VALUES (?,?, 'mvd', 1, ?, ?)",
        (demo_id, f"bronze/demos/d{demo_id}.mvd", sha, damage_available))
    # teams 1 & 2 (actor_ticks.team_id FK -> teams); seed once per connection. team_id is the
    # PRIMARY KEY, so OR IGNORE makes this idempotent for a second demo on the SAME connection
    # without an id(con) cache (which is unsafe: CPython reuses the id of a freed connection, so
    # a later test's fresh :memory: con can collide and skip the seed -> FK failure under the
    # full-suite ordering, the CI flake this avoids).
    for tid in (1, 2):
        con.execute("INSERT OR IGNORE INTO teams (team_id, demo_id, name, side) VALUES (?,?,?,?)",
                    (tid, demo_id, f"team{tid}", "A" if tid == 1 else "B"))


def _seed_players(con, names):
    for pid, name in names:
        con.execute("INSERT INTO players (player_id, handle, is_bot) VALUES (?,?,0)", (pid, name))


def _seed_episode(con, episode_id, demo_id, player_id, split, n_steps):
    con.execute(
        "INSERT INTO episodes (episode_id, demo_id, player_id, map_id, start_tick, end_tick, "
        "n_steps, split, split_policy) VALUES (?,?,?,1,0,?,?,?,'group_by_demo_id')",
        (episode_id, demo_id, player_id, n_steps - 1, n_steps, split))


def _seed_player_tick(con, episode_id, tick, t_s, **kw):
    cols = dict(ox=0.0, oy=0.0, oz=0.0, vx=100.0, vy=0.0, vz=0.0,
                yaw=0.0, pitch=0.0, hspeed=100.0, onground=1, msec=13,
                health=100, armor=0, shells=25, nails=0, rockets=0, cells=0,
                quad_rem=None, pent_rem=None, ring_rem=None, regime="cruise", leg_phase=None)
    cols.update(kw)
    con.execute(
        "INSERT INTO player_ticks (episode_id, tick, t_s, msec, ox, oy, oz, vx, vy, vz, "
        "yaw, pitch, hspeed, onground, health, armor, shells, nails, rockets, cells, "
        "quad_rem, pent_rem, ring_rem, regime, leg_phase) "
        "VALUES (:episode_id,:tick,:t_s,:msec,:ox,:oy,:oz,:vx,:vy,:vz,:yaw,:pitch,:hspeed,"
        ":onground,:health,:armor,:shells,:nails,:rockets,:cells,:quad_rem,:pent_rem,"
        ":ring_rem,:regime,:leg_phase)",
        dict(episode_id=episode_id, tick=tick, t_s=t_s, **cols))


def _seed_actor_tick(con, episode_id, tick, actor_id, team_id, ox=0.0, oy=0.0, oz=0.0):
    con.execute(
        "INSERT INTO actor_ticks (episode_id, tick, actor_id, ox, oy, oz, vx, vy, vz, yaw, "
        "alive, team_id) VALUES (?,?,?,?,?,?,0,0,0,0,1,?)",
        (episode_id, tick, actor_id, ox, oy, oz, team_id))


def _seed_visibility(con, episode_id, tick, observer_id, target_id, is_visible):
    con.execute(
        "INSERT INTO actor_visibility (episode_id, tick, observer_id, target_id, is_visible, "
        "in_fov, los_clear, vis_angle_source, seen_ever) VALUES (?,?,?,?,?,?,?, 'demoparser', 1)",
        (episode_id, tick, observer_id, target_id, is_visible, is_visible, is_visible))


def _seed_item_event(con, event_id, demo_id, t_s, item_type, player_id):
    con.execute(
        "INSERT INTO item_events (event_id, demo_id, t_s, event_kind, player_id, "
        "origin_x, origin_y, origin_z, item_type) VALUES (?,?,?, 'pickup', ?, 0,0,0, ?)",
        (event_id, demo_id, t_s, player_id, item_type))


# =============================================================================
# 1) dataset_spec.yaml stdlib reader
# =============================================================================
class TestDatasetSpecReader(unittest.TestCase):
    def test_parses_window_and_entity_contract(self):
        c = DS.load()
        self.assertEqual(c["schema_version"], 5)
        self.assertEqual(c["registry_version"], 5)
        self.assertEqual(c["window"]["lookback_K"], 64)
        self.assertEqual(c["window"]["stride"], 16)
        self.assertEqual(c["entity_max"]["N_max"], 7)
        self.assertTrue(c["window"]["pad_short_windows"])
        for key in ("obs", "self_history", "entities", "ent_mask", "act", "mask", "weight"):
            self.assertIn(key, c["record_layout_keys"], key)
        self.assertEqual(c["split"]["method"], "group_by_demo_id")
        self.assertEqual(c["split"]["held_out_players"], ["milton"])
        self.assertAlmostEqual(c["split"]["fractions"]["train"], 0.70)

    def test_matches_shard_contract_pinned_constants(self):
        """The stdlib-read spec MUST agree with shard_contract's hardcoded geometry — this is
        the drift guard the reader exists for (the two were previously duplicated, never
        cross-checked)."""
        sys.path.insert(0, str(REPO_ROOT / "ml"))
        from broad_bc import shard_contract as SC
        c = DS.load()
        self.assertEqual(c["registry_version"], SC.EXPECTS_REGISTRY_VERSION)
        self.assertEqual(c["entity_max"]["N_max"], SC.DEFAULT_N_MAX)

    def test_missing_required_field_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            bad = Path(td) / "bad.yaml"
            bad.write_text("dataset_spec_version: 5\nregistry_version: 5\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                DS.load(bad)


# =============================================================================
# 2) PIT / ASOF leakage guard — the headline test (adversarial fixture)
# =============================================================================
class TestAsofLeakageGuard(unittest.TestCase):
    def test_asof_primitive_never_returns_future(self):
        events = [(1.0, "past"), (5.0, "future")]
        # at t=3 the only legal event is the past one; the future (t=5) must NOT leak.
        self.assertEqual(AOT.asof_latest_leq(events, 3.0)[1], "past")
        # at the exact event time, the at-or-before event is selected (<=, not <).
        self.assertEqual(AOT.asof_latest_leq(events, 5.0)[1], "future")
        # before any event -> None (no fabrication).
        self.assertIsNone(AOT.asof_latest_leq(events, 0.5))

    def test_obs_assembly_does_not_leak_future_item_event(self):
        """Adversarial: a FUTURE pickup (t_s=9.0) exists in the same demo. The obs at an
        EARLIER tick (t_s≈0.0) must attach the PAST pickup (t_s=0.0), never the future one.
        A naive nearest/next join would attach the future pickup -> this asserts it does not."""
        con = _con()
        _seed_players(con, [(1, "alpha"), (2, "beta")])
        _seed_demo(con, 1, "sha_clean", True)
        _seed_episode(con, 1, 1, 1, "train", 3)
        for tk in range(3):
            _seed_player_tick(con, 1, tk, t_s=tk * 0.013)
            _seed_actor_tick(con, 1, tk, 1, team_id=1)         # ego self row
            _seed_actor_tick(con, 1, tk, 2, team_id=1, oy=5000.0)  # far teammate (no threat)
            _seed_visibility(con, 1, tk, 1, 2, 0)
        # two item events: a PAST pickup at t=0.0 and a FUTURE pickup at t=9.0.
        _seed_item_event(con, 10, 1, 0.0, "rl", 1)
        _seed_item_event(con, 11, 1, 9.0, "quad", 1)
        con.commit()

        norm = AOT.load_norm(TEMPLATE_STATS)
        out = AOT.assemble_amp_reference(con, norm, split="train")
        self.assertTrue(out["transitions"], "expected at least one clean transition")
        for tr in out["transitions"]:
            # every obs is at t_s well before 9.0 -> the as-of event must be the PAST 'rl',
            # NEVER the FUTURE 'quad'. The leak would show up as item_type == 'quad'.
            self.assertIsNotNone(tr["last_item_event"])
            self.assertEqual(tr["last_item_event"]["item_type"], "rl",
                             "FUTURE item_event leaked into the obs (as-of join is unsafe)")
            self.assertLessEqual(tr["last_item_event_t"], tr["tick"] * 0.013 + 1e-9)

    def test_naive_nearest_join_would_leak(self):
        """Demonstrate the test has TEETH: on a tick CLOSER to the future event than to the
        past one, a NAIVE nearest-time join LEAKS the future, while the as-of join stays
        <= t_obs and does not. This is why the leakage guard is non-trivial."""
        events = [(0.0, "rl"), (9.0, "quad")]

        def naive_nearest(evs, t):
            return min(evs, key=lambda e: abs(e[0] - t))
        # t=5.0 is nearer to the FUTURE event (9.0, dist 4.0) than the past (0.0, dist 5.0).
        self.assertEqual(naive_nearest(events, 5.0)[1], "quad")          # naive LEAKS the future
        self.assertEqual(AOT.asof_latest_leq(events, 5.0)[1], "rl")      # as-of: future excluded


# =============================================================================
# 3) §6.5 clean-movement gating (fail-closed on unknown damage; LOS-gated proximity)
# =============================================================================
class TestCleanMovementGate(unittest.TestCase):
    def _build(self, damage_available, enemy_near_with_los):
        con = _con()
        _seed_players(con, [(1, "alpha"), (2, "enemy")])
        _seed_demo(con, 1, f"sha_{damage_available}_{enemy_near_with_los}", damage_available)
        _seed_episode(con, 1, 1, 1, "train", 2)
        for tk in range(2):
            _seed_player_tick(con, 1, tk, t_s=tk * 0.013)
            _seed_actor_tick(con, 1, tk, 1, team_id=1)
            # enemy on the OTHER team; near (oy=100) or far (oy=5000)
            enemy_oy = 100.0 if enemy_near_with_los else 5000.0
            _seed_actor_tick(con, 1, tk, 2, team_id=2, oy=enemy_oy)
            _seed_visibility(con, 1, tk, 1, 2, 1 if enemy_near_with_los else 0)
        con.commit()
        return con

    def test_unknown_damage_is_excluded_fail_closed(self):
        con = self._build(damage_available=None, enemy_near_with_los=False)
        out = AOT.assemble_amp_reference(con, AOT.load_norm(TEMPLATE_STATS), split="train")
        self.assertEqual(out["stats"]["clean_transitions"], 0)
        self.assertEqual(out["stats"]["excluded_unknown_damage_fail_closed"], 1)

    def test_enemy_with_los_in_range_excluded(self):
        con = self._build(damage_available=True, enemy_near_with_los=True)
        out = AOT.assemble_amp_reference(con, AOT.load_norm(TEMPLATE_STATS), split="train")
        self.assertEqual(out["stats"]["clean_transitions"], 0)
        self.assertEqual(out["stats"]["excluded_combat"], 1)

    def test_clean_segment_passes(self):
        con = self._build(damage_available=True, enemy_near_with_los=False)
        out = AOT.assemble_amp_reference(con, AOT.load_norm(TEMPLATE_STATS), split="train")
        self.assertEqual(out["stats"]["clean_transitions"], 1)


# =============================================================================
# 4) Worked consumer assembles a correctly-shaped obs vector
# =============================================================================
class TestObsShape(unittest.TestCase):
    def test_obs_vector_shape_and_dim(self):
        con = _con()
        _seed_players(con, [(1, "alpha"), (2, "beta")])
        _seed_demo(con, 1, "sha_shape", True)
        _seed_episode(con, 1, 1, 1, "train", 2)
        for tk in range(2):
            _seed_player_tick(con, 1, tk, t_s=tk * 0.013)
            _seed_actor_tick(con, 1, tk, 1, team_id=1)
            _seed_actor_tick(con, 1, tk, 2, team_id=1, oy=5000.0)
            _seed_visibility(con, 1, tk, 1, 2, 0)
        con.commit()
        out = AOT.assemble_amp_reference(con, AOT.load_norm(TEMPLATE_STATS), split="train")
        tr = out["transitions"][0]
        self.assertEqual(len(tr["s"]), AO.SELF_DIM)
        self.assertEqual(len(tr["s_next"]), AO.SELF_DIM)
        self.assertEqual(out["stats"]["self_dim"], AO.SELF_DIM)
        self.assertTrue(all(isinstance(v, float) for v in tr["s"]))


# =============================================================================
# 5) Train-split-only norm refit — the second headline test (adversarial fixture)
# =============================================================================
class TestNormRefitTrainOnly(unittest.TestCase):
    def _build_split_disjoint(self):
        """TRAIN ticks have vx≈+1000; VAL/TEST ticks have vx≈-1000. If the refit ever touched
        val/test, the fitted mean would move toward 0 — so the train-only mean must stay ≈+1000."""
        con = _con()
        _seed_players(con, [(1, "alpha")])
        _seed_demo(con, 1, "sha_train", True)
        _seed_demo(con, 2, "sha_val", True)
        _seed_demo(con, 3, "sha_test", True)
        _seed_episode(con, 1, 1, 1, "train", 4)
        _seed_episode(con, 2, 2, 1, "val", 4)
        _seed_episode(con, 3, 3, 1, "test", 4)
        for tk in range(4):
            _seed_player_tick(con, 1, tk, t_s=tk * 0.013, vx=1000.0, hspeed=1000.0, shells=50)
            _seed_player_tick(con, 2, tk, t_s=tk * 0.013, vx=-1000.0, hspeed=10.0, shells=5)
            _seed_player_tick(con, 3, tk, t_s=tk * 0.013, vx=-1000.0, hspeed=10.0, shells=5)
        con.commit()
        return con

    def test_refit_uses_train_rows_only(self):
        con = self._build_split_disjoint()
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "cat.sqlite"
            # dump in-memory to a file (normalize_fit opens its own sqlite3 connection)
            disk = sqlite3.connect(str(db))
            con.backup(disk)
            disk.close()
            out = Path(td) / "norm" / "refit.json"
            doc = NF.refit_template(db, out, split="train", map_name="dm3")

        velx = doc["per_map"]["dm3"]["vel_x"]
        # train-only mean is ≈ +1000 (all train vx are +1000). If val/test (-1000) had leaked,
        # the mean would collapse toward 0 -> assert it stayed train-only.
        self.assertGreater(velx["mean"], 900.0,
                           "vel_x mean drifted toward 0 -> val/test rows leaked into the fit")
        self.assertEqual(velx["computed_from"]["n"], 4, "fitted on exactly the 4 train ticks")
        # hspeed (robust) median from train-only is ≈1000; all-rows would be lower.
        self.assertGreater(doc["per_map"]["dm3"]["hspeed"]["median"], 900.0)
        # the artifact is honestly labeled fixture-derived (heavy-run boundary).
        self.assertTrue(doc["_fixture_derived"])
        self.assertIn("_ammo_empirical_train_only", doc["per_map"]["dm3"])

    def test_train_only_differs_from_all_rows(self):
        """Prove the discipline matters: a fit over ALL rows gives a DIFFERENT mean than the
        train-only fit, so 'train-only' is not a no-op on this fixture."""
        con = self._build_split_disjoint()
        # train-only via the production path
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "c.sqlite"
            disk = sqlite3.connect(str(db))
            con.backup(disk)
            disk.close()
            train_fit = NF.fit_from_catalog(db, split="train")
        train_mean = train_fit["feats"]["vel_x"]["mean"]

        # all-rows mean computed directly (the WRONG, leaking way) -> ≈ +1000*4 + -1000*8 over 12
        all_vx = [r[0] for r in con.execute("SELECT vx FROM player_ticks").fetchall()]
        all_mean = sum(all_vx) / len(all_vx)
        self.assertNotAlmostEqual(train_mean, all_mean, places=1)
        self.assertGreater(train_mean, 900.0)   # train-only
        self.assertLess(all_mean, 0.0)           # all-rows is dragged negative by val/test


if __name__ == "__main__":
    unittest.main()
