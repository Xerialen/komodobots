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
# yaw_rate is the per-map zscore key the appended turn-direction feature normalizes
# against (mean 0, std 220 deg/s — the template placeholder). The unit tests assert the
# (x-mean)/std relationship, not a fitted number, so the placeholder value is fine.
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
            "yaw_rate": {"method": "zscore", "mean": 0.0, "std": 220.0, "clip": [-1500.0, 1500.0]},
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


# =============================================================================
# TURN-DIRECTION features (the fix): wrap180 + yaw_rate_degps shared helpers, the
# appended yaw_rate_z / face_vel_angle_norm SELF channels, and SELF_DIM growth.
# =============================================================================
class TestWrap180(unittest.TestCase):
    """The shared angle-wrap: maps any degree value into (-180, 180] so a turn across
    the +-180 seam is a small signed delta (the parity-critical math for yaw_rate AND
    face_vel_angle)."""

    def test_in_range_unchanged(self):
        self.assertAlmostEqual(AO.wrap180(0.0), 0.0)
        self.assertAlmostEqual(AO.wrap180(45.0), 45.0)
        self.assertAlmostEqual(AO.wrap180(-179.0), -179.0)

    def test_wrap_just_over_180(self):
        self.assertAlmostEqual(AO.wrap180(190.0), -170.0)
        self.assertAlmostEqual(AO.wrap180(-190.0), 170.0)

    def test_endpoints_map_to_positive_180(self):
        # boundary convention: both +180 and -180 land on +180 (range is (-180,180]).
        self.assertAlmostEqual(AO.wrap180(180.0), 180.0)
        self.assertAlmostEqual(AO.wrap180(-180.0), 180.0)

    def test_multi_turn_reduction(self):
        self.assertAlmostEqual(AO.wrap180(360.0 + 30.0), 30.0)
        self.assertAlmostEqual(AO.wrap180(-720.0 - 10.0), -10.0)

    def test_seam_delta_is_small_not_360(self):
        # the WHOLE point: 170 -> -170 is a +20deg turn (wrap of the raw -340), not -340.
        self.assertAlmostEqual(AO.wrap180(-170.0 - 170.0), 20.0)


class TestYawRateDegps(unittest.TestCase):
    """The signed view-yaw turn rate (deg/s) — THE air-strafe direction signal. Same
    helper offline + inference, so identical inputs give identical output (parity)."""

    def test_first_tick_is_zero(self):
        # prev_yaw None (episode/rollout start) -> 0.0 by convention (no turn info yet).
        self.assertEqual(AO.yaw_rate_degps(45.0, None, 0.013), 0.0)

    def test_basic_positive_turn(self):
        # +13 deg over 13 ms -> +1000 deg/s.
        self.assertAlmostEqual(AO.yaw_rate_degps(58.0, 45.0, 0.013), 1000.0, places=6)

    def test_sign_is_turn_direction(self):
        # turning the other way flips the sign (the direction the rule keys on).
        self.assertLess(AO.yaw_rate_degps(45.0, 58.0, 0.013), 0.0)
        self.assertGreater(AO.yaw_rate_degps(58.0, 45.0, 0.013), 0.0)

    def test_dt_scaling(self):
        # same delta over twice the time -> half the rate.
        r1 = AO.yaw_rate_degps(55.0, 45.0, 0.013)
        r2 = AO.yaw_rate_degps(55.0, 45.0, 0.026)
        self.assertAlmostEqual(r1, 2.0 * r2, places=6)

    def test_wrap_across_seam(self):
        # 179 -> -179 is a +2 deg turn (NOT -358); /0.01s -> +200 deg/s.
        self.assertAlmostEqual(AO.yaw_rate_degps(-179.0, 179.0, 0.01), 200.0, places=6)

    def test_nonpositive_dt_is_zero(self):
        self.assertEqual(AO.yaw_rate_degps(58.0, 45.0, 0.0), 0.0)
        self.assertEqual(AO.yaw_rate_degps(58.0, 45.0, -0.013), 0.0)


class TestSelfDimAppended(unittest.TestCase):
    """SELF_DIM = 21 at v4: the frozen-16 prefix + the v3 turn-direction pair (yaw_rate_z,
    face_vel_angle_norm) + the v4 route-conditioning triple (goal_heading_sin/cos,
    goal_dist_norm) — all APPENDED, never reordered — and encode_observation's self width
    matches SELF_DIM."""

    def test_self_dim_is_21_and_order(self):
        self.assertEqual(AO.SELF_DIM, 21)
        self.assertEqual(len(AO.SELF_FIELDS), 21)
        # v3 turn-direction pair keeps its indices (appended after the frozen 16) ...
        self.assertEqual(AO.SELF_FIELDS[16], "yaw_rate_z")
        self.assertEqual(AO.SELF_FIELDS[17], "face_vel_angle_norm")
        # ... then the v4 route-conditioning triple is APPENDED after it, IN THIS ORDER.
        self.assertEqual(AO.SELF_FIELDS[18], "goal_heading_sin")
        self.assertEqual(AO.SELF_FIELDS[19], "goal_heading_cos")
        self.assertEqual(AO.SELF_FIELDS[20], "goal_dist_norm")
        # prefix still ends with the resource pair (nothing reordered).
        self.assertEqual(AO.SELF_FIELDS[14], "health_norm")
        self.assertEqual(AO.SELF_FIELDS[15], "armor_norm")

    def test_encode_self_width_matches_self_dim(self):
        obs = AO.encode_observation(MILTON, [], STATS, n_max=7)
        self.assertEqual(len(obs["self"]), AO.SELF_DIM)


class TestGoalConditioning(unittest.TestCase):
    """The v4 route-conditioning goal channels (goal_heading_sin/cos, goal_dist_norm),
    from the caller-supplied self_state['goal'] via the SHARED goal_vector (parity)."""

    def test_goal_vector_points_at_goal_map_frame(self):
        # goal due +y of origin -> heading sin=1, cos=0 (MAP frame, NOT egocentric).
        gv = AO.goal_vector(0.0, 0.0, (0.0, 100.0), 3797.1)
        self.assertAlmostEqual(gv[0], 1.0, places=6)
        self.assertAlmostEqual(gv[1], 0.0, places=6)
        # goal due +x -> sin=0, cos=1.
        gv2 = AO.goal_vector(0.0, 0.0, (100.0, 0.0), 3797.1)
        self.assertAlmostEqual(gv2[0], 0.0, places=6)
        self.assertAlmostEqual(gv2[1], 1.0, places=6)

    def test_goal_dist_normalized_and_clamped(self):
        gv = AO.goal_vector(0.0, 0.0, (100.0, 0.0), 3797.1)
        self.assertAlmostEqual(gv[2], 100.0 / 3797.1, places=6)
        far = AO.goal_vector(0.0, 0.0, (99999.0, 0.0), 3797.1)
        self.assertEqual(far[2], 1.0)   # clamped to the map diagonal

    def test_free_roam_default_when_no_goal(self):
        # goal None -> [0,0,1]: heading undefined (0,0) + max normalized distance (1.0).
        self.assertEqual(AO.goal_vector(123.0, 45.0, None, 3797.1), [0.0, 0.0, 1.0])

    def test_self_features_free_roam_without_goal(self):
        # MILTON carries no 'goal' -> the 3 appended channels are the free-roam default.
        v = AO.self_features(MILTON, STATS)
        si = AO.SELF_FIELDS.index("goal_heading_sin")
        self.assertEqual(v[si:si + 3], [0.0, 0.0, 1.0])

    def test_self_features_goal_channels_when_set(self):
        # a goal 45deg NE of MILTON -> heading (sin,cos)=(.707,.707), distance in (0,1),
        # and EXACTLY the shared goal_vector for the same inputs (train/serve parity).
        st = dict(MILTON, goal=(MILTON["ox"] + 300.0, MILTON["oy"] + 300.0))
        v = AO.self_features(st, STATS)
        si = AO.SELF_FIELDS.index("goal_heading_sin")
        triple = v[si:si + 3]
        self.assertAlmostEqual(triple[0], math.sin(math.radians(45.0)), places=6)
        self.assertAlmostEqual(triple[1], math.cos(math.radians(45.0)), places=6)
        self.assertTrue(0.0 < triple[2] < 1.0)
        self.assertEqual(triple, AO.goal_vector(MILTON["ox"], MILTON["oy"], st["goal"], 3797.1))


class TestYawRateChannel(unittest.TestCase):
    """The appended yaw_rate_z channel: zscored from the RAW self_state['yaw_rate']."""

    def test_yaw_rate_zscored_from_raw(self):
        i = AO.SELF_FIELDS.index("yaw_rate_z")
        moving = dict(MILTON, yaw_rate=220.0)             # == std -> z == 1.0
        v = AO.self_features(moving, STATS)
        self.assertAlmostEqual(v[i], 1.0, places=6)
        neg = dict(MILTON, yaw_rate=-110.0)               # -0.5 std
        self.assertAlmostEqual(AO.self_features(neg, STATS)[i], -0.5, places=6)

    def test_missing_yaw_rate_is_zero(self):
        # absent key -> 0.0 raw -> z 0.0 (mean 0). First tick / a caller with no prev yaw.
        i = AO.SELF_FIELDS.index("yaw_rate_z")
        self.assertEqual(AO.self_features(MILTON, STATS)[i], 0.0)

    def test_yaw_rate_clip_applied(self):
        # raw beyond the +-1500 clip is clamped before the zscore: 3000 -> 1500 -> z.
        i = AO.SELF_FIELDS.index("yaw_rate_z")
        v = AO.self_features(dict(MILTON, yaw_rate=3000.0), STATS)
        self.assertAlmostEqual(v[i], 1500.0 / 220.0, places=6)


class TestFaceVelAngleChannel(unittest.TestCase):
    """The appended face_vel_angle_norm channel: signed (yaw - vel_heading)/180, SIGN
    preserved, 0 below the 80 qu/s velocity-heading floor."""

    def test_zero_below_speed_floor(self):
        # hspeed 0 < 80 -> heading undefined -> face_vel_angle 0 (same guard as vh).
        i = AO.SELF_FIELDS.index("face_vel_angle_norm")
        self.assertEqual(AO.self_features(MILTON, STATS)[i], 0.0)

    def test_sign_positive_when_facing_left_of_travel(self):
        # moving +x (heading 0) but facing +90 yaw -> wrap180(90-0)/180 = +0.5 (SIGN +).
        i = AO.SELF_FIELDS.index("face_vel_angle_norm")
        st = dict(MILTON, vx=300.0, vy=0.0, hspeed=300.0, yaw=90.0)
        self.assertAlmostEqual(AO.self_features(st, STATS)[i], 0.5, places=6)

    def test_sign_negative_when_facing_right_of_travel(self):
        # facing -90 (i.e. 270) while moving +x -> wrap180(-90)/180 = -0.5 (SIGN -). The
        # near-0 sign is what the strafe rule needs to survive normalization.
        i = AO.SELF_FIELDS.index("face_vel_angle_norm")
        st = dict(MILTON, vx=300.0, vy=0.0, hspeed=300.0, yaw=-90.0)
        self.assertAlmostEqual(AO.self_features(st, STATS)[i], -0.5, places=6)

    def test_zero_when_facing_equals_travel(self):
        i = AO.SELF_FIELDS.index("face_vel_angle_norm")
        st = dict(MILTON, vx=300.0, vy=0.0, hspeed=300.0, yaw=0.0)
        self.assertAlmostEqual(AO.self_features(st, STATS)[i], 0.0, places=6)

    def test_seam_offset_small_signed(self):
        # heading ~+180 (moving -x), facing ~-179 -> a small +deg offset, not ~360.
        i = AO.SELF_FIELDS.index("face_vel_angle_norm")
        st = dict(MILTON, vx=-300.0, vy=0.0, hspeed=300.0, yaw=-179.0)
        # vel_heading = 180; wrap180(-179 - 180) = wrap180(-359) = +1 deg -> +1/180.
        self.assertAlmostEqual(AO.self_features(st, STATS)[i], 1.0 / 180.0, places=6)


class TestFrozen16Unchanged(unittest.TestCase):
    """Appending the two features must NOT perturb any of the original 16 channels."""

    def test_prefix_identical_to_legacy_compute(self):
        st = dict(MILTON, vx=300.0, vy=120.0, hspeed=math.hypot(300.0, 120.0),
                  yaw=30.0, pitch=10.0, health=200, armor=150, yaw_rate=180.0)
        v = AO.self_features(st, STATS)
        # recompute the legacy 16 directly and compare the prefix byte-for-byte.
        pm = STATS["per_map"]["dm3"]
        from features.transforms import normalize as N
        legacy = [
            N(st["ox"], pm["pos_x"]), N(st["oy"], pm["pos_y"]), N(st["oz"], pm["pos_z"]),
            N(st["vx"], pm["vel_x"]), N(st["vy"], pm["vel_y"]), N(st["vz"], pm["vel_z"]),
            N(st["hspeed"], pm["hspeed"]),
        ]
        vh_sin, vh_cos = N(math.degrees(math.atan2(st["vy"], st["vx"])), {"method": "sincos"})
        ys, yc = N(st["yaw"], {"method": "sincos"})
        ps, pc = N(st["pitch"], {"method": "sincos"})
        legacy += [vh_sin, vh_cos, ys, yc, ps, pc, 1.0, 200.0 / 250.0, 150.0 / 200.0]
        for k in range(16):
            self.assertAlmostEqual(v[k], legacy[k], places=9,
                                   msg=f"frozen channel {k} ({AO.SELF_FIELDS[k]}) changed")


class TestFeatureColumns(unittest.TestCase):
    def test_flat_column_count(self):
        cols = AO.feature_columns(n_max=7)
        # self + 7*(entity + mask)
        self.assertEqual(len(cols["flat"]), AO.SELF_DIM + 7 * (AO.ENTITY_DIM + 1))
        self.assertEqual(cols["flat"][0], "self.pos_x_norm")
        self.assertIn("ent0.entity_rel_dist_norm", cols["flat"])
        self.assertIn("ent6.mask", cols["flat"])
        # the appended turn-direction columns are present in the flat schema.
        self.assertIn("self.yaw_rate_z", cols["flat"])
        self.assertIn("self.face_vel_angle_norm", cols["flat"])


class TestSelfHistoryAssembly(unittest.TestCase):
    """The v5 SHARED self-history assembly helper (assemble_self_history) — the
    train/serve parity linchpin. Pure stdlib; tests the order (oldest->newest), the flat
    width (SELF_HISTORY*SELF_DIM = 16*21 = 336), the left-pad-repeat-first rule, and the
    invariant that history[-1] (the newest SELF_DIM block) is the current single-tick SELF."""

    H = AO.SELF_HISTORY
    S = AO.SELF_DIM

    def _vec(self, t):
        # a distinct, recognizable SELF vector per tick: value t*100 + channel index.
        return [float(t * 100 + j) for j in range(self.S)]

    def test_constants(self):
        self.assertEqual(AO.SELF_HISTORY, 16)
        self.assertEqual(AO.SELF_HISTORY_DIM, AO.SELF_HISTORY * AO.SELF_DIM)
        # v5: the SELF is the 21-wide goal-conditioned vector, so the flat history is 336.
        self.assertEqual(AO.SELF_HISTORY_DIM, 336)

    def test_flat_width_and_newest_is_current(self):
        seq = [self._vec(t) for t in range(self.H)]   # exactly H ticks
        flat = AO.assemble_self_history(seq, self.H)
        self.assertEqual(len(flat), self.H * self.S)
        # newest SELF_DIM block (the tail) == the current (last) single-tick SELF.
        self.assertEqual(flat[-self.S:], seq[-1])
        # oldest block (the head) == the earliest tick.
        self.assertEqual(flat[:self.S], seq[0])

    def test_oldest_to_newest_order(self):
        seq = [self._vec(t) for t in range(self.H)]
        flat = AO.assemble_self_history(seq, self.H)
        # reconstruct the per-tick blocks and confirm strict oldest->newest order.
        blocks = [flat[i * self.S:(i + 1) * self.S] for i in range(self.H)]
        self.assertEqual(blocks, seq)

    def test_left_pad_repeats_first_when_fewer_than_h(self):
        # THE padding test: a window with < H real ticks left-pads by REPEATING the
        # earliest available tick (not zeros), so the newest block is still the current.
        seq = [self._vec(0), self._vec(1), self._vec(2)]   # only 3 < H ticks
        flat = AO.assemble_self_history(seq, self.H)
        self.assertEqual(len(flat), self.H * self.S)
        blocks = [flat[i * self.S:(i + 1) * self.S] for i in range(self.H)]
        # first (H-3) blocks are the EARLIEST tick repeated; then the 3 real ticks.
        expected = [seq[0]] * (self.H - 3) + seq
        self.assertEqual(blocks, expected)
        self.assertEqual(flat[-self.S:], seq[-1])          # newest == current

    def test_single_tick_tiles_to_full_history(self):
        # one tick -> the whole history is that tick repeated H times (newest==current).
        v = self._vec(7)
        flat = AO.assemble_self_history([v], self.H)
        self.assertEqual(flat, v * self.H)

    def test_more_than_h_keeps_last_h(self):
        # > H ticks -> only the LAST H are kept (sliding window), oldest dropped.
        seq = [self._vec(t) for t in range(self.H + 9)]
        flat = AO.assemble_self_history(seq, self.H)
        blocks = [flat[i * self.S:(i + 1) * self.S] for i in range(self.H)]
        self.assertEqual(blocks, seq[-self.H:])
        self.assertEqual(flat[:self.S], seq[-self.H])      # oldest kept == H-ago tick
        self.assertEqual(flat[-self.S:], seq[-1])          # newest == current

    def test_empty_is_zero_history(self):
        # degenerate (no ticks) -> all-zero history of the right width (no real caller
        # hits this; every rollout/window has at least the current tick).
        flat = AO.assemble_self_history([], self.H)
        self.assertEqual(flat, [0.0] * (self.H * self.S))


if __name__ == "__main__":
    unittest.main()
