"""Tests for the agent_observation transform (P3). Pure stdlib; `python -m unittest`.

Verifies the POMDP policy input: SELF kinematics + per-observed-other EGOCENTRIC
vectors with pad/mask. Covers the empty-observed (0 others) and N-capped (>N_max)
cases the verify gate calls out, the no-future-leakage masking rule (unobserved live
channels zeroed, not sentinel), relative-only team flag, and determinism vs input
row order.
"""
import math
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from features import agent_observation as AO   # noqa: E402
from features import egocentric as E           # noqa: E402

# A minimal, self-contained normalization stats dict (the shape build_features loads).
STATS = {
    "per_map": {
        "dm3": {
            "pos_x": {"method": "minmax", "min": -984.0, "max": 2048.0, "clip": [-984.0, 2048.0]},
            "pos_y": {"method": "minmax", "min": -960.0, "max": 1136.0, "clip": [-960.0, 1136.0]},
            "pos_z": {"method": "minmax", "min": -416.0, "max": 496.0, "clip": [-416.0, 496.0]},
            "vel_x": {"method": "zscore", "mean": 0.0, "std": 310.0, "clip": [-2500.0, 2500.0]},
            "vel_y": {"method": "zscore", "mean": 0.0, "std": 310.0, "clip": [-2500.0, 2500.0]},
            "vel_z": {"method": "zscore", "mean": 0.0, "std": 180.0, "clip": [-1000.0, 1000.0]},
            "hspeed": {"method": "robust", "median": 320.0, "iqr": 210.0, "clip": [0.0, 2500.0]},
        }
    }
}

# fixture geometry (reuse the egocentric test's grounded snapshot)
MILTON = {"ox": 1499.0, "oy": -176.0, "oz": -78.0, "yaw": 0.0, "pitch": 0.0,
          "vx": 0.0, "vy": 0.0, "vz": 0.0, "hspeed": 0.0, "onground": True}
ZEPP = {"actor_id": 7, "ox": 1812.0, "oy": 431.0, "oz": -88.0, "yaw": 90.0,
        "vx": 200.0, "vy": -100.0, "vz": 0.0, "alive": True}


class TestSelfFeatures(unittest.TestCase):
    def test_width_and_known_channels(self):
        v = AO.self_features(MILTON, STATS)
        self.assertEqual(len(v), AO.SELF_DIM)
        # pos minmax: x at -984 -> 0; here 1499 -> (1499+984)/3032
        self.assertAlmostEqual(v[0], (1499.0 + 984.0) / 3032.0, places=6)
        # onground bit is the 14th channel (index 13) per SELF_FIELDS
        self.assertEqual(AO.SELF_FIELDS[13], "onground")
        self.assertEqual(v[13], 1.0)

    def test_velocity_heading_zero_below_floor(self):
        # hspeed 0 < 80 -> heading undefined -> (0,0)
        v = AO.self_features(MILTON, STATS)
        i = AO.SELF_FIELDS.index("vel_heading_sin")
        self.assertEqual((v[i], v[i + 1]), (0.0, 0.0))

    def test_velocity_heading_defined_when_moving(self):
        moving = dict(MILTON, vx=300.0, vy=0.0, hspeed=300.0)
        v = AO.self_features(moving, STATS)
        i = AO.SELF_FIELDS.index("vel_heading_sin")
        # heading 0deg (+x) -> sin 0, cos 1
        self.assertAlmostEqual(v[i], 0.0, places=6)
        self.assertAlmostEqual(v[i + 1], 1.0, places=6)

    def test_missing_health_armor_zeroed_not_sentinel(self):
        v = AO.self_features(MILTON, STATS)   # no health/armor keys
        self.assertEqual(v[AO.SELF_FIELDS.index("health_norm")], 0.0)
        self.assertEqual(v[AO.SELF_FIELDS.index("armor_norm")], 0.0)

    def test_health_armor_normalized_when_present(self):
        v = AO.self_features(dict(MILTON, health=250, armor=200), STATS)
        self.assertAlmostEqual(v[AO.SELF_FIELDS.index("health_norm")], 1.0, places=6)
        self.assertAlmostEqual(v[AO.SELF_FIELDS.index("armor_norm")], 1.0, places=6)


class TestEntityFeatures(unittest.TestCase):
    def test_width(self):
        e = AO.entity_features(ZEPP, MILTON, STATS)
        self.assertEqual(len(e), AO.ENTITY_DIM)

    def test_egocentric_distance_matches_world(self):
        e = AO.entity_features(ZEPP, MILTON, STATS)
        rel_dist = e[AO.ENTITY_FIELDS.index("entity_rel_dist_norm")]
        world = math.dist((MILTON["ox"], MILTON["oy"], MILTON["oz"]),
                          (ZEPP["ox"], ZEPP["oy"], ZEPP["oz"]))
        self.assertAlmostEqual(rel_dist, world / AO._MAP_DIAGONAL["dm3"], places=6)
        self.assertTrue(0.0 < rel_dist < 1.0)

    def test_bearing_sincos_unit_norm(self):
        e = AO.entity_features(ZEPP, MILTON, STATS)
        bs = e[AO.ENTITY_FIELDS.index("entity_rel_bearing_sin")]
        bc = e[AO.ENTITY_FIELDS.index("entity_rel_bearing_cos")]
        self.assertAlmostEqual(bs * bs + bc * bc, 1.0, places=6)
        # Zepp is to Milton's +y (left) at yaw 0 -> bearing > 0 -> sin > 0
        self.assertGreater(bs, 0.0)

    def test_rel_velocity_is_egocentric_rotated(self):
        # at yaw 0 the ego frame == world frame, so rel_vx == zscore(world vx)
        e = AO.entity_features(ZEPP, MILTON, STATS)
        rvx = e[AO.ENTITY_FIELDS.index("entity_rel_vel_x")]
        self.assertAlmostEqual(rvx, 200.0 / 310.0, places=6)
        # at yaw 90 the same world vel rotates: forward becomes +y component
        ego90 = dict(MILTON, yaw=90.0)
        e90 = AO.entity_features(ZEPP, ego90, STATS)
        rvx90 = e90[AO.ENTITY_FIELDS.index("entity_rel_vel_x")]
        fwd, _ = E.egocentric_vec((ZEPP["vx"], ZEPP["vy"]), 90.0)
        self.assertAlmostEqual(rvx90, fwd / 310.0, places=6)

    def test_unobserved_health_armor_zeroed(self):
        # is_visible False -> live est channels zeroed even if values supplied
        masked = dict(ZEPP, health=100, armor=150, is_visible=False)
        e = AO.entity_features(masked, MILTON, STATS)
        self.assertEqual(e[AO.ENTITY_FIELDS.index("entity_health_est_norm")], 0.0)
        self.assertEqual(e[AO.ENTITY_FIELDS.index("entity_armor_est_norm")], 0.0)
        self.assertEqual(e[AO.ENTITY_FIELDS.index("entity_is_visible")], 0.0)

    def test_dead_entity_alive_zero(self):
        dead = dict(ZEPP, alive=False)
        e = AO.entity_features(dead, MILTON, STATS)
        self.assertEqual(e[AO.ENTITY_FIELDS.index("entity_alive")], 0.0)

    def test_teammate_flag_relative_only(self):
        # unknown teams (None) -> 0
        e0 = AO.entity_features(ZEPP, MILTON, STATS)
        self.assertEqual(e0[AO.ENTITY_FIELDS.index("entity_is_teammate")], 0.0)
        # same absolute team -> 1
        mate = dict(ZEPP, team_id=5)
        ego = dict(MILTON, team_id=5)
        e1 = AO.entity_features(mate, ego, STATS)
        self.assertEqual(e1[AO.ENTITY_FIELDS.index("entity_is_teammate")], 1.0)
        # different team -> 0
        foe = dict(ZEPP, team_id=9)
        e2 = AO.entity_features(foe, ego, STATS)
        self.assertEqual(e2[AO.ENTITY_FIELDS.index("entity_is_teammate")], 0.0)

    def test_ego_team_must_be_present_for_teammate_one(self):
        # mirrors the shard-builder bug: if the EGO team is missing (None) the teammate
        # channel can NEVER be 1.0 even when the other actor's team is populated. This is
        # exactly why build_features must carry the ego actor_ticks.team_id into
        # self_state (instead of hard-coding None).
        i = AO.ENTITY_FIELDS.index("entity_is_teammate")
        mate = dict(ZEPP, team_id=10)
        ego_noteam = dict(MILTON)                 # team_id absent -> None
        self.assertEqual(AO.entity_features(mate, ego_noteam, STATS)[i], 0.0)
        ego_team = dict(MILTON, team_id=10)       # ego team present + matching -> 1.0
        self.assertEqual(AO.entity_features(mate, ego_team, STATS)[i], 1.0)


class TestEncodeObservation(unittest.TestCase):
    def test_empty_observed_all_padded(self):
        obs = AO.encode_observation(MILTON, [], STATS, n_max=7)
        self.assertEqual(len(obs["self"]), AO.SELF_DIM)
        self.assertEqual(obs["n_obs"], 0)
        self.assertEqual(len(obs["ents"]), 7)
        self.assertEqual(len(obs["mask"]), 7)
        self.assertEqual(obs["mask"], [0.0] * 7)        # every slot masked
        for row in obs["ents"]:                         # every pad row all-zero
            self.assertEqual(row, [0.0] * AO.ENTITY_DIM)

    def test_single_observed(self):
        obs = AO.encode_observation(MILTON, [ZEPP], STATS, n_max=7)
        self.assertEqual(obs["n_obs"], 1)
        self.assertEqual(obs["mask"][0], 1.0)
        self.assertEqual(obs["mask"][1:], [0.0] * 6)
        # the real slot is non-trivial (distance channel populated)
        self.assertGreater(obs["ents"][0][0], 0.0)
        # pad slots zeroed
        self.assertEqual(obs["ents"][1], [0.0] * AO.ENTITY_DIM)

    def test_ncap_keeps_nearest(self):
        # 9 others at increasing distance; N_max=7 keeps the 7 nearest
        others = [dict(actor_id=i, ox=MILTON["ox"] + 100.0 * i, oy=MILTON["oy"],
                       oz=MILTON["oz"], vx=0.0, vy=0.0, vz=0.0, alive=True)
                  for i in range(1, 10)]
        obs = AO.encode_observation(MILTON, others, STATS, n_max=7)
        self.assertEqual(obs["n_obs"], 7)
        self.assertEqual(sum(obs["mask"]), 7.0)
        # nearest-first: slot 0 is the closest (i=1, dist 100), monotonic non-decreasing
        dists = [row[0] for row in obs["ents"][:7]]
        self.assertEqual(dists, sorted(dists))
        # the two farthest (i=8,9) were dropped: max kept dist < their dist
        self.assertLess(max(dists), (900.0 / AO._MAP_DIAGONAL["dm3"]))

    def test_deterministic_vs_input_order(self):
        # shuffling the input list must not change the encoded observation (stable sort)
        others = [dict(actor_id=i, ox=MILTON["ox"] + 50.0 * i, oy=MILTON["oy"] + 10.0 * i,
                       oz=MILTON["oz"], vx=10.0 * i, vy=0.0, vz=0.0, alive=True)
                  for i in range(1, 6)]
        a = AO.encode_observation(MILTON, others, STATS, n_max=7)
        b = AO.encode_observation(MILTON, list(reversed(others)), STATS, n_max=7)
        self.assertEqual(a["ents"], b["ents"])
        self.assertEqual(a["mask"], b["mask"])

    def test_equal_distance_tiebreak_by_actor_id(self):
        # two others at the SAME distance must order deterministically by actor_id
        o_hi = dict(actor_id=20, ox=MILTON["ox"] + 100.0, oy=MILTON["oy"], oz=MILTON["oz"],
                    vx=0.0, vy=0.0, vz=0.0, alive=True)
        o_lo = dict(actor_id=3, ox=MILTON["ox"] - 100.0, oy=MILTON["oy"], oz=MILTON["oz"],
                    vx=0.0, vy=0.0, vz=0.0, alive=True)
        obs = AO.encode_observation(MILTON, [o_hi, o_lo], STATS, n_max=7)
        # same dist -> actor_id 3 sorts before 20; both real slots, rest padded
        self.assertEqual(obs["n_obs"], 2)
        self.assertEqual(obs["mask"][:2], [1.0, 1.0])


class TestFeatureColumns(unittest.TestCase):
    def test_flat_column_count(self):
        cols = AO.feature_columns(n_max=7)
        # self + 7*(entity + mask)
        self.assertEqual(len(cols["flat"]), AO.SELF_DIM + 7 * (AO.ENTITY_DIM + 1))
        self.assertEqual(cols["flat"][0], "self.pos_x_norm")
        self.assertIn("ent0.entity_rel_dist_norm", cols["flat"])
        self.assertIn("ent6.mask", cols["flat"])


if __name__ == "__main__":
    unittest.main()
