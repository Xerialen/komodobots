# AUTO-GENERATED — DO NOT HAND-EDIT.
# Generated from data/catalog/feature_registry.json by scripts/generate_from_registry.py
# Regenerate with: python scripts/generate_from_registry.py


"""Generated registry constants — the SINGLE source for the obs-vector layout.

Imported by scripts/features/agent_observation.py (the live + offline encoder) and
ml/broad_bc/shard_contract.py (the shard contract) so the SELF/entity/action layout and
the v5 history dims live in ONE place — data/catalog/feature_registry.json `observation`.
"""

import logging

LOGGER = logging.getLogger(__name__)

REGISTRY_VERSION = 5

SELF_FIELDS = (
    "pos_x_norm",
    "pos_y_norm",
    "pos_z_norm",
    "vel_x_z",
    "vel_y_z",
    "vel_z_z",
    "hspeed_norm",
    "vel_heading_sin",
    "vel_heading_cos",
    "yaw_sin",
    "yaw_cos",
    "pitch_sin",
    "pitch_cos",
    "onground",
    "health_norm",
    "armor_norm",
    "yaw_rate_z",
    "face_vel_angle_norm",
    "goal_heading_sin",
    "goal_heading_cos",
    "goal_dist_norm",
)

SELF_DIM = 21

SELF_HISTORY = 16

SELF_HISTORY_DIM = SELF_HISTORY * SELF_DIM  # 336

ENTITY_FIELDS = (
    "entity_rel_dist_norm",
    "entity_rel_bearing_sin",
    "entity_rel_bearing_cos",
    "entity_rel_pitch_sin",
    "entity_rel_pitch_cos",
    "entity_rel_vel_x",
    "entity_rel_vel_y",
    "entity_rel_vel_z",
    "entity_health_est_norm",
    "entity_armor_est_norm",
    "entity_alive",
    "entity_is_teammate",
    "entity_is_visible",
)

ENTITY_DIM = 13

ACT_FIELDS = (
    "forwardmove",
    "sidemove",
    "upmove",
    "jump_button",
    "attack_button",
)

ACT_DIM = 5

N_MAX_DEFAULT = 7

REQUIRED_NORM_KEYS = (
    "yaw_rate",
)
