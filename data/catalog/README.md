# `schema/` — komodobots ML data-substrate schemas

Machine-readable schemas for the layered store described in
[`../00-DATA-ARCHITECTURE.md`](../00-DATA-ARCHITECTURE.md). They are internally
consistent: every feature in the registry traces to a real column in
`catalog.sql` and a stats key in `normalization_stats.template.json`.

| File | schema tag | What it defines |
|---|---|---|
| `catalog.sql` | `komodobots.catalog.v1` (+ v2 additions) | DuckDB/SQLite DDL: `maps`, `markers`, `nav_edges`, `items`, `item_value`, `players`, `demos`, `episodes`, `player_ticks`, `item_events`, `actions`, `feature_partitions`. **v2 (4on4):** `teams`, `actor_ticks` (omniscient all-player state), `actor_visibility` (derived POMDP + belief), `audio_cues`, `frag_events`, `region_control_timeline`, + `item_events.team_id`. The relational spine; PIT-join example at the bottom. |
| `feature_registry.yaml` | `komodobots.feature_registry.v1` (`registry_version: 5`) | Every model input declared once: name, dtype, source/formula, unit, normalization method + `stats_key`, version, `leakage_safe`. Grouped by position / velocity / orientation / player_resource / item / timing / player_style / **entity_observation / audio / team** / action / rtg. **v3:** appends the turn-direction SELF features `yaw_rate_z` + `face_vel_angle_norm` (SELF vector 16→18). **v4:** appends the route-conditioning SELF features `goal_heading_sincos` + `goal_dist_norm` (SELF 18→21). **v5 (sequence-aware):** SELF channels unchanged; the policy consumes a FLAT last-`SELF_HISTORY=16`-tick SELF history (the `self_history` field, width 16×21=336) — a shape/contract change, not a new per-tick feature. |
| `normalization_stats.template.json` | `komodobots.normalization_stats.v1` (`artifact_version 0.5.0`, `registry_version 5`) | The frozen, versioned stats artifact. Per-feature `{method, params, computed_from, clip}`. Train-split-only; real dm3 AABB bounds (asymmetric, verified) + known player cadences. **v2 keys:** `global.time_since_seen`, `global.team_spread`, `global.audio_intensity`; sincos `rel_bearing`/`rel_pitch`/`audio_dir`; ammo caps `sh/nl/rk/cl`. **v3 key:** `per_map.<map>.yaw_rate` (required by the appended `yaw_rate_z`). **v4:** NO new keys (the goal features are parameter-free). **v5:** NO new keys — the SELF channels are unchanged, so the SAME stats apply to each of the 16 history rows. |
| `item_catalog.dm3.json` | `komodobots.item_catalog.v1` | The dm3 item set: type, category, world origin, respawn_seconds, static value. Unknown coords/respawns flagged `"_verify": true` + `coords_verified:false` (fill from mvd-mcp `getItems`/`getWeaponPickups`). |
| `dataset_spec.yaml` | `komodobots.dataset_spec.v1` (`dataset_spec_version 5`) | Windowing (K=64, stride 16), episode boundaries, obs/action/reward/RTG record layout, WebDataset+HDF5 shard format, split policy, storage paths. **v2:** `entities`/`ent_mask` (N_max=7) + `audio`/`team` tensors, team-augmented reward shaping with difference-reward credit assignment, world_state-vs-agent_observation scope note. **v5 (sequence-aware):** adds the `self_history` record-layout key — the FLAT last-`SELF_HISTORY=16`-tick SELF history (width 16×21=336) the policy consumes in place of the single tick. |

## How they relate

```
catalog.sql            -- raw/curated TABLES (silver spine)
   |  columns: player_ticks.ox, .vx, .yaw, .health; items.respawn_seconds; ...
   v
feature_registry.yaml  -- TRANSFORMS those columns into model features
   |  each feature: source=<catalog column>  norm=<method>  stats_key=<-.>
   v
normalization_stats.json -- the FROZEN params for each norm method (train-only)
   |
   v
dataset_spec.yaml      -- WINDOWS the normalized features into training tensors
                          (+ item_catalog.dm3.json supplies item origins/respawns/values)
```

**v2 (4on4) gold stage — world_state -> agent_observation.** `actor_ticks` (omniscient
all-player state) is NOT trained on; a new gold derivation per `(tick, observer)` applies
the `actor_visibility` POMDP mask (PVS -> FOV -> raycast on bsp_geom hull 0) to produce the
POMDP-masked `agent_observation` — the ONLY training input. Invisible entities are a mask
bit + zeroed live fields + a carried belief block (never a sentinel). See
`00-DATA-ARCHITECTURE.md` §2.7–§3.7.

Version pinning for reproducibility: a model card records
`(git_sha, dvc_dataset_hash, normalization artifact_version, registry_version)`.
`feature_partitions` in `catalog.sql` records `registry_version` +
`norm_artifact_version` per built Parquet partition so a stale scaler/model pair
can never deploy together.

Status: schemas are **design templates**. The catalog, item table, and item
events are NEW (the mvd-mcp item endpoints are not yet wired). See
`00-DATA-ARCHITECTURE.md` §Build order for the incremental stand-up plan.

**Populating (P1+P2):** `scripts/catalog_load.py` loads the static spine + one fixture's
identity/team/frag rows; `scripts/catalog_etl_qwd.py` populates the per-tick trajectory
tables (`episodes`/`player_ticks`/`actions`) from real self-POV `.qwd` demos and can fold
the fixture team layer. **P2:** `scripts/qwd_observed_others.py` decodes the in-PVS
observed-OTHER players (the `agent_observation` layer) from the same `.qwd` stream, and the
ETL folds them into `actor_ticks` (self ego + each observed other, time-joined per tick).
Only the fully OMNISCIENT all-player state (players outside the recorder's PVS),
`actor_visibility`/`audio_cues`, and demo-wide item/region timelines still need the
`.mvd`/mvd_analyzer path (deferred). See `docs/20_ML_DATA_ARCHITECTURE.md`
§Observed-other players → actor_ticks.
