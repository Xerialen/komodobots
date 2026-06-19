"""komodobots feature-transform math (C3) — pure standard library.

The canonical implementation of the per-feature normalization and egocentric
geometry described by feature_registry.yaml and normalization_stats.json. Imported
by BOTH the offline feature build (ml/) and the live bot, so the same vector math
runs at train time and inference time (the in-tree/out-of-tree parity guarantee).

NO third-party imports anywhere under this package — the unit suite runs on bare
Python 3.12 with no pip install.

Repo destination: scripts/features/
"""
from .transforms import (
    apply_clip, zscore, minmax, robust, log1p_zscore, divide_period,
    identity, sincos, normalize,
)
from .egocentric import (
    egocentric_xy, egocentric_vec, rel_distance, rel_bearing_deg, rel_pitch_deg,
)
from .agent_observation import (
    encode_observation, self_features, entity_features, feature_columns,
    SELF_FIELDS, ENTITY_FIELDS, SELF_DIM, ENTITY_DIM, N_MAX_DEFAULT,
)

__all__ = [
    "apply_clip", "zscore", "minmax", "robust", "log1p_zscore", "divide_period",
    "identity", "sincos", "normalize",
    "egocentric_xy", "egocentric_vec", "rel_distance", "rel_bearing_deg", "rel_pitch_deg",
    "encode_observation", "self_features", "entity_features", "feature_columns",
    "SELF_FIELDS", "ENTITY_FIELDS", "SELF_DIM", "ENTITY_DIM", "N_MAX_DEFAULT",
]
