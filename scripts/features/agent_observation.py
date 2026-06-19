"""agent_observation — the POMDP policy input transform (P3, pure standard library).

Turns ONE self tick (the ego player) plus the set of observed-OTHER actors that the
ego currently perceives (the `actor_ticks` rows for that (episode_id, tick) minus the
ego's own row) into the model-ready **agent_observation**:

    self  : a flat, normalized SELF feature vector  (width = SELF_DIM)
    ents  : per-observed-other EGOCENTRIC vectors    (shape = [N_max, ENTITY_DIM])
    mask  : 1.0 = a real entity occupies the slot, 0.0 = pad/absent  (len = N_max)

This is the SINGLE transform shared by the offline feature build (ml/) and the live
bot: train/serve parity. It composes the per-feature math in `transforms` and the
egocentric geometry in `egocentric` — it adds NO new math, only the assembly + the
observed-others layout (N-nearest cap, pad/mask) the dataset_spec calls for.

Layout authority: data/catalog/feature_registry.yaml (groups position / velocity /
orientation / player_resource for SELF; entity_observation for OTHERS) and
data/catalog/dataset_spec.yaml (record_layout.obs / entities / ent_mask, N_max=7).

POMDP masking rule (registry): a live per-entity channel that is NOT observed is
ZEROED (never a sentinel number); the slot's presence is carried by the mask bit.
Team identity is ALWAYS relative (is_teammate), never an absolute team id.

NO third-party imports — runs on bare Python 3.12.
"""
from __future__ import annotations

import math

from .transforms import normalize
from .egocentric import egocentric_vec, rel_distance, rel_bearing_deg, rel_pitch_deg

# --- fixed widths (frozen per registry_version) ------------------------------
# SELF feature vector (obs.npy inner width), in registry order:
#   pos_x_norm, pos_y_norm, pos_z_norm                      (3)  position minmax/map
#   vel_x_z, vel_y_z, vel_z_z                               (3)  velocity zscore/map (world frame)
#   hspeed_norm                                             (1)  robust/map
#   vel_heading_sin, vel_heading_cos                        (2)  sincos
#   yaw_sin, yaw_cos, pitch_sin, pitch_cos                  (4)  sincos
#   onground                                                (1)  0/1
#   health_norm, armor_norm                                 (2)  /250, /200
SELF_FIELDS: tuple[str, ...] = (
    "pos_x_norm", "pos_y_norm", "pos_z_norm",
    "vel_x_z", "vel_y_z", "vel_z_z",
    "hspeed_norm",
    "vel_heading_sin", "vel_heading_cos",
    "yaw_sin", "yaw_cos", "pitch_sin", "pitch_cos",
    "onground",
    "health_norm", "armor_norm",
)
SELF_DIM = len(SELF_FIELDS)

# Per-OTHER-actor vector (entities.npy innermost width), in registry order:
#   entity_rel_dist_norm                                    (1)  /diagonal
#   entity_rel_bearing_sin, entity_rel_bearing_cos          (2)  sincos
#   entity_rel_pitch_sin, entity_rel_pitch_cos              (2)  sincos
#   entity_rel_vel_x, entity_rel_vel_y, entity_rel_vel_z    (3)  zscore/map, egocentric-rotated
#   entity_health_est_norm, entity_armor_est_norm           (2)  /250,/200 (ZEROED if not observed)
#   entity_alive                                            (1)  0/1
#   entity_is_teammate                                      (1)  relative; 0 when team unknown
#   entity_is_visible                                       (1)  observed-this-tick gate
ENTITY_FIELDS: tuple[str, ...] = (
    "entity_rel_dist_norm",
    "entity_rel_bearing_sin", "entity_rel_bearing_cos",
    "entity_rel_pitch_sin", "entity_rel_pitch_cos",
    "entity_rel_vel_x", "entity_rel_vel_y", "entity_rel_vel_z",
    "entity_health_est_norm", "entity_armor_est_norm",
    "entity_alive",
    "entity_is_teammate",
    "entity_is_visible",
)
ENTITY_DIM = len(ENTITY_FIELDS)

# dataset_spec.entity_max.N_max — 4on4 => 7 other actors.
N_MAX_DEFAULT = 7

# constant denominators (mirror feature_registry constants / divide_period)
_HEALTH_CAP = 250.0
_ARMOR_CAP = 200.0


def self_features(self_state: dict, stats: dict, map_name: str = "dm3") -> list[float]:
    """Normalized SELF feature vector (length SELF_DIM) for one ego tick.

    `self_state` keys (qu / qu/s / deg), any missing one treated as 0 / unknown:
        ox, oy, oz, vx, vy, vz, yaw, pitch, hspeed, onground, health, armor
    `stats` = a normalization_stats.json dict (per_map[map] holds pos_*/vel_*/hspeed).
    """
    pm = stats["per_map"][map_name]
    ox = float(self_state.get("ox", 0.0))
    oy = float(self_state.get("oy", 0.0))
    oz = float(self_state.get("oz", 0.0))
    vx = float(self_state.get("vx", 0.0))
    vy = float(self_state.get("vy", 0.0))
    vz = float(self_state.get("vz", 0.0))
    yaw = float(self_state.get("yaw", 0.0))
    pitch = float(self_state.get("pitch", 0.0))
    hspeed = self_state.get("hspeed")
    hspeed = math.hypot(vx, vy) if hspeed is None else float(hspeed)

    pos_x = normalize(ox, pm["pos_x"])
    pos_y = normalize(oy, pm["pos_y"])
    pos_z = normalize(oz, pm["pos_z"])
    vel_x = normalize(vx, pm["vel_x"])
    vel_y = normalize(vy, pm["vel_y"])
    vel_z = normalize(vz, pm["vel_z"])
    hsp = normalize(hspeed, pm["hspeed"])

    # velocity heading (sincos) — only meaningful when actually moving; below the
    # 80 qu/s floor (registry note) the heading is undefined, so emit (0,0).
    if hspeed >= 80.0:
        vh_sin, vh_cos = normalize(math.degrees(math.atan2(vy, vx)), {"method": "sincos"})
    else:
        vh_sin, vh_cos = 0.0, 0.0

    yaw_sin, yaw_cos = normalize(yaw, {"method": "sincos"})
    pitch_sin, pitch_cos = normalize(pitch, {"method": "sincos"})

    onground = 1.0 if self_state.get("onground") else 0.0
    health = self_state.get("health")
    armor = self_state.get("armor")
    health_n = (min(max(float(health), 0.0), _HEALTH_CAP) / _HEALTH_CAP) if health is not None else 0.0
    armor_n = (min(max(float(armor), 0.0), _ARMOR_CAP) / _ARMOR_CAP) if armor is not None else 0.0

    return [
        pos_x, pos_y, pos_z,
        vel_x, vel_y, vel_z,
        hsp,
        vh_sin, vh_cos,
        yaw_sin, yaw_cos, pitch_sin, pitch_cos,
        onground,
        health_n, armor_n,
    ]


def entity_features(other: dict, self_state: dict, stats: dict, map_name: str = "dm3") -> list[float]:
    """Egocentric per-OTHER-actor feature vector (length ENTITY_DIM).

    `other` = one observed actor's state (same kinematic keys as self, plus optional
    `alive`, `team_id`, `health`, `armor`, `is_visible`). All relative geometry is
    rotated into the ego's yaw frame (translation+rotation invariant). A live channel
    that is not observed is ZEROED (per the POMDP rule), the mask bit carrying presence.
    """
    pm = stats["per_map"][map_name]
    self_pos = (float(self_state.get("ox", 0.0)),
                float(self_state.get("oy", 0.0)),
                float(self_state.get("oz", 0.0)))
    self_yaw = float(self_state.get("yaw", 0.0))
    other_pos = (float(other.get("ox", 0.0)),
                 float(other.get("oy", 0.0)),
                 float(other.get("oz", 0.0)))

    diagonal = float(stats.get("constants", {}).get("map_diagonal", {}).get(map_name)
                     or _MAP_DIAGONAL.get(map_name, _MAP_DIAGONAL["dm3"]))

    rel_dist = rel_distance(other_pos, self_pos) / diagonal
    bearing = rel_bearing_deg(other_pos, self_pos, self_yaw)
    b_sin, b_cos = normalize(bearing, {"method": "sincos"})
    pitch = rel_pitch_deg(other_pos, self_pos)
    p_sin, p_cos = normalize(pitch, {"method": "sincos"})

    # other velocity rotated into the ego frame, then per-map zscore (reuses self vel keys)
    ovx = float(other.get("vx", 0.0))
    ovy = float(other.get("vy", 0.0))
    ovz = float(other.get("vz", 0.0))
    rvx_world, rvy_world = egocentric_vec((ovx, ovy), self_yaw)
    rel_vx = normalize(rvx_world, pm["vel_x"])
    rel_vy = normalize(rvy_world, pm["vel_y"])
    rel_vz = normalize(ovz, pm["vel_z"])

    # is_visible: True when the actor has a fresh observed sample this tick. The .qwd
    # observed-others ETL only writes an actor_ticks row when the client was RECEIVING
    # that player (in PVS within the staleness window) — so a present row IS an
    # observed/visible sample. Default True for a present entity.
    is_visible = 1.0 if other.get("is_visible", True) else 0.0

    health = other.get("health")
    armor = other.get("armor")
    h_est = (min(max(float(health), 0.0), _HEALTH_CAP) / _HEALTH_CAP) if (health is not None and is_visible) else 0.0
    a_est = (min(max(float(armor), 0.0), _ARMOR_CAP) / _ARMOR_CAP) if (armor is not None and is_visible) else 0.0

    alive = 1.0 if other.get("alive", True) else 0.0

    # relative team identity ONLY (never the absolute id). Unknown team => 0.0.
    self_team = self_state.get("team_id")
    other_team = other.get("team_id")
    is_teammate = 1.0 if (self_team is not None and other_team is not None and self_team == other_team) else 0.0

    return [
        rel_dist,
        b_sin, b_cos,
        p_sin, p_cos,
        rel_vx, rel_vy, rel_vz,
        h_est, a_est,
        alive,
        is_teammate,
        is_visible,
    ]


# AABB diagonals (qu) used for entity_rel_dist_norm — mirror feature_registry constants.
_MAP_DIAGONAL = {"dm3": 3797.1}


def encode_observation(
    self_state: dict,
    observed_others: list[dict],
    stats: dict,
    map_name: str = "dm3",
    n_max: int = N_MAX_DEFAULT,
) -> dict:
    """Assemble the full agent_observation for one (episode_id, tick) ego sample.

    Returns:
        {
          "self":  [SELF_DIM]   normalized self vector,
          "ents":  [n_max][ENTITY_DIM]  per-slot entity vectors (pad rows are all-0),
          "mask":  [n_max]      1.0 real slot / 0.0 pad,
          "n_obs": int          number of observed others actually encoded (<= n_max),
        }

    `observed_others` is the set of OTHER actors perceived this tick (the ego's own
    actor row MUST already be excluded by the caller). If more than `n_max` are
    present, the N NEAREST (by egocentric distance) are kept — the rest dropped — so
    the slot budget always holds. Ordering of kept entities is nearest-first, but the
    consumer pools with the pad-mask (DeepSets/transformer) and is permutation-
    invariant; the deterministic sort only guarantees a stable, reproducible layout.
    """
    self_vec = self_features(self_state, stats, map_name)

    self_pos = (float(self_state.get("ox", 0.0)),
                float(self_state.get("oy", 0.0)),
                float(self_state.get("oz", 0.0)))
    # nearest-first, with a fully-deterministic tiebreak (distance, then actor_id) so a
    # rebuild is byte-identical regardless of input row order.
    ordered = sorted(
        observed_others,
        key=lambda o: (rel_distance((float(o.get("ox", 0.0)), float(o.get("oy", 0.0)),
                                     float(o.get("oz", 0.0))), self_pos),
                       o.get("actor_id", 0)),
    )
    kept = ordered[:n_max]

    ents: list[list[float]] = []
    mask: list[float] = []
    for other in kept:
        ents.append(entity_features(other, self_state, stats, map_name))
        mask.append(1.0)
    # pad to n_max with all-zero rows + 0 mask
    pad_row = [0.0] * ENTITY_DIM
    while len(ents) < n_max:
        ents.append(list(pad_row))
        mask.append(0.0)

    return {"self": self_vec, "ents": ents, "mask": mask, "n_obs": len(kept)}


def feature_columns(n_max: int = N_MAX_DEFAULT) -> dict:
    """The exact flattened column names this transform emits, for the shard schema
    contract. `self.<field>` and per-slot `ent{i}.<field>` + `ent{i}.mask`."""
    cols = {"self": list(SELF_FIELDS), "entity": list(ENTITY_FIELDS), "n_max": n_max}
    flat: list[str] = [f"self.{f}" for f in SELF_FIELDS]
    for i in range(n_max):
        flat += [f"ent{i}.{f}" for f in ENTITY_FIELDS]
        flat.append(f"ent{i}.mask")
    cols["flat"] = flat
    return cols
