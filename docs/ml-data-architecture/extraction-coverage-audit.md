# Extraction-coverage audit — decoder Result inventory vs catalog vs registry

> **GENERATED FILE — do not edit by hand.** Regenerate with:
> ```
> python3 scripts/audit_extraction_coverage.py
> ```
>
> Read-only audit for Demo Extraction Spec v1 (`docs/27` §3.9/§7), ticket #389 (T1),
> epic #388. Loads NO database, hits NO network. It enumerates the decoder Result
> inventory (anchored in `docs/ml-data-architecture/_source-schemas.md`) and diffs it against the operative
> schema `scripts/catalog_schema.sql`, `data/catalog/feature_registry.yaml`, and what
> `catalog_etl_mvd.py` / `catalog_etl_qwd.py` actually populate. Classifies every
> catalog column **extracted / derived / excluded-with-reason / GAP**.

## Per-column classification (grouped by table)

### `maps`

| column | class | decoder field | populated by | registry | reason |
|---|---|---|---|---|---|
| `map_id` | structural | — | — | — | PK/FK/provenance/split bookkeeping |
| `name` | structural | — | — | — | PK/FK/provenance/split bookkeeping |
| `source_bsp` | excluded-with-reason | items.world_coords | — | — | static AABB from maps.v1/BSP, not per-demo decode |
| `source_bsp_sha256` | structural | — | — | — | PK/FK/provenance/split bookkeeping |
| `x_min` | excluded-with-reason | items.world_coords | — | — | static AABB from maps.v1/BSP, not per-demo decode |
| `x_max` | excluded-with-reason | items.world_coords | — | — | static AABB from maps.v1/BSP, not per-demo decode |
| `y_min` | excluded-with-reason | items.world_coords | — | — | static AABB from maps.v1/BSP, not per-demo decode |
| `y_max` | excluded-with-reason | items.world_coords | — | — | static AABB from maps.v1/BSP, not per-demo decode |
| `z_min` | excluded-with-reason | items.world_coords | — | — | static AABB from maps.v1/BSP, not per-demo decode |
| `z_max` | excluded-with-reason | items.world_coords | — | — | static AABB from maps.v1/BSP, not per-demo decode |
| `center_x` | derived | — | — | — | computed from AABB |
| `center_y` | derived | — | — | — | computed from AABB |
| `center_z` | derived | — | — | — | computed from AABB |
| `diagonal` | derived | — | — | — | computed from AABB |
| `maxspeed` | excluded-with-reason | — | — | — | QW physics constant (default), not a decoder field |
| `jumpspeed` | excluded-with-reason | — | — | — | QW physics constant (default), not a decoder field |
| `gravity` | excluded-with-reason | — | — | — | QW physics constant (default), not a decoder field |
| `friction` | excluded-with-reason | — | — | — | QW physics constant (default), not a decoder field |
| `stopspeed` | excluded-with-reason | — | — | — | QW physics constant (default), not a decoder field |
| `accelerate` | excluded-with-reason | — | — | — | QW physics constant (default), not a decoder field |
| `airaccel_cap` | excluded-with-reason | — | — | — | QW physics constant (default), not a decoder field |
| `server_fps` | structural | — | — | — | PK/FK/provenance/split bookkeeping |

### `markers`

| column | class | decoder field | populated by | registry | reason |
|---|---|---|---|---|---|
| `map_id` | structural | — | — | — | PK/FK/provenance/split bookkeeping |
| `marker_id` | structural | — | — | — | PK/FK/provenance/split bookkeeping |
| `origin_x` | excluded-with-reason | locgraph.movement | — | — | Frogbot .bot CreateMarker parse; mvd_analyzer has no nav mesh |
| `origin_y` | excluded-with-reason | locgraph.movement | — | — | Frogbot .bot CreateMarker parse; mvd_analyzer has no nav mesh |
| `origin_z` | excluded-with-reason | locgraph.movement | — | — | Frogbot .bot CreateMarker parse; mvd_analyzer has no nav mesh |
| `zone` | excluded-with-reason | locgraph.movement | — | — | Frogbot .bot CreateMarker parse; mvd_analyzer has no nav mesh |
| `goal` | excluded-with-reason | locgraph.movement | — | — | Frogbot .bot CreateMarker parse; mvd_analyzer has no nav mesh |
| `near_item_id` | structural | — | — | — | PK/FK/provenance/split bookkeeping |
| `is_teleport` | excluded-with-reason | locgraph.movement | — | — | Frogbot .bot CreateMarker parse; mvd_analyzer has no nav mesh |
| `is_door` | excluded-with-reason | locgraph.movement | — | — | Frogbot .bot CreateMarker parse; mvd_analyzer has no nav mesh |

### `nav_edges`

| column | class | decoder field | populated by | registry | reason |
|---|---|---|---|---|---|
| `map_id` | structural | — | — | — | PK/FK/provenance/split bookkeeping |
| `from_marker` | excluded-with-reason | — | — | — | Frogbot path-edge geometry; not a decoder field |
| `to_marker` | excluded-with-reason | — | — | — | Frogbot path-edge geometry; not a decoder field |
| `edge_idx` | excluded-with-reason | — | — | — | Frogbot path-edge geometry; not a decoder field |
| `distance_qu` | excluded-with-reason | — | — | — | Frogbot path-edge geometry; not a decoder field |
| `path_flags` | excluded-with-reason | — | — | — | Frogbot path-edge geometry; not a decoder field |
| `is_jump` | excluded-with-reason | — | — | — | Frogbot path-edge geometry; not a decoder field |
| `is_teleport` | excluded-with-reason | — | — | — | Frogbot path-edge geometry; not a decoder field |

### `items`

| column | class | decoder field | populated by | registry | reason |
|---|---|---|---|---|---|
| `item_id` | structural | — | — | — | PK/FK/provenance/split bookkeeping |
| `map_id` | structural | — | — | — | PK/FK/provenance/split bookkeeping |
| `classname` | extracted | items.world_coords | — | — | getMapEntities.class |
| `item_type` | extracted | items.world_coords | — | — | getMapEntities.class |
| `category` | extracted | items.world_coords | — | — | getMapEntities.class |
| `origin_x` | extracted | items.world_coords | — | — | getMapEntities world spawn coords |
| `origin_y` | extracted | items.world_coords | — | — | getMapEntities world spawn coords |
| `origin_z` | extracted | items.world_coords | — | — | getMapEntities world spawn coords |
| `respawn_seconds` | excluded-with-reason | items.pickup_respawn | — | yes | canonical prior (domain), validated against observed phases[] |
| `static_value` | excluded-with-reason | — | — | yes | importance prior; fitted/domain, not a decoder field |
| `nearest_marker` | excluded-with-reason | — | — | — | nav-routing denormalization (Frogbot markers); not a decoder field |
| `coords_verified` | excluded-with-reason | — | — | — | provenance flag for getMapEntities-filled coords; not a decoder field |

### `item_value`

| column | class | decoder field | populated by | registry | reason |
|---|---|---|---|---|---|
| `map_id` | structural | — | — | — | PK/FK/provenance/split bookkeeping |
| `item_type` | excluded-with-reason | — | — | — | fitted on train split (logreg/pearson); not a decoder field |
| `method` | excluded-with-reason | — | — | — | fitted on train split (logreg/pearson); not a decoder field |
| `coef` | excluded-with-reason | — | — | — | fitted on train split (logreg/pearson); not a decoder field |
| `importance_norm` | excluded-with-reason | — | — | — | fitted on train split (logreg/pearson); not a decoder field |
| `n_rounds` | excluded-with-reason | — | — | — | fitted on train split (logreg/pearson); not a decoder field |
| `dataset_version` | excluded-with-reason | — | — | — | fitted on train split (logreg/pearson); not a decoder field |
| `fitted_on_split` | structural | — | — | — | PK/FK/provenance/split bookkeeping |

### `players`

| column | class | decoder field | populated by | registry | reason |
|---|---|---|---|---|---|
| `player_id` | structural | — | — | — | PK/FK/provenance/split bookkeeping |
| `handle` | structural | — | mvd-etl, qwd-etl | — | PK/FK/provenance/split bookkeeping |
| `is_bot` | structural | — | mvd-etl, qwd-etl | — | PK/FK/provenance/split bookkeeping |

### `demos`

| column | class | decoder field | populated by | registry | reason |
|---|---|---|---|---|---|
| `demo_id` | structural | — | mvd-etl | — | PK/FK/provenance/split bookkeeping |
| `path` | structural | — | mvd-etl, qwd-etl | — | PK/FK/provenance/split bookkeeping |
| `source` | structural | — | mvd-etl, qwd-etl | — | PK/FK/provenance/split bookkeeping |
| `map_id` | structural | — | mvd-etl, qwd-etl | — | PK/FK/provenance/split bookkeeping |
| `demo_kind` | structural | — | mvd-etl, qwd-etl | — | PK/FK/provenance/split bookkeeping |
| `recorded_at` | structural | — | — | — | PK/FK/provenance/split bookkeeping |
| `duration_s` | structural | — | qwd-etl | yes | PK/FK/provenance/split bookkeeping |
| `server_fps` | structural | — | qwd-etl | — | PK/FK/provenance/split bookkeeping |
| `sha256` | structural | — | mvd-etl, qwd-etl | — | PK/FK/provenance/split bookkeeping |
| `parser_commit` | structural | — | mvd-etl, qwd-etl | — | PK/FK/provenance/split bookkeeping |

### `episodes`

| column | class | decoder field | populated by | registry | reason |
|---|---|---|---|---|---|
| `episode_id` | structural | — | — | — | PK/FK/provenance/split bookkeeping |
| `demo_id` | structural | — | mvd-etl, qwd-etl | — | PK/FK/provenance/split bookkeeping |
| `player_id` | structural | — | mvd-etl, qwd-etl | yes | PK/FK/provenance/split bookkeeping |
| `map_id` | structural | — | mvd-etl, qwd-etl | — | PK/FK/provenance/split bookkeeping |
| `start_tick` | structural | — | mvd-etl, qwd-etl | — | PK/FK/provenance/split bookkeeping |
| `end_tick` | structural | — | mvd-etl, qwd-etl | — | PK/FK/provenance/split bookkeeping |
| `n_steps` | structural | — | mvd-etl, qwd-etl | — | PK/FK/provenance/split bookkeeping |
| `total_reward` | structural | — | — | — | PK/FK/provenance/split bookkeeping |
| `split` | structural | — | mvd-etl, qwd-etl | — | PK/FK/provenance/split bookkeeping |
| `split_policy` | structural | — | mvd-etl, qwd-etl | — | PK/FK/provenance/split bookkeeping |

### `player_ticks`

| column | class | decoder field | populated by | registry | reason |
|---|---|---|---|---|---|
| `episode_id` | structural | — | mvd-etl, qwd-etl | — | PK/FK/provenance/split bookkeeping |
| `tick` | structural | — | mvd-etl, qwd-etl | — | PK/FK/provenance/split bookkeeping |
| `t_s` | extracted | provenance.sha | mvd-etl, qwd-etl | yes | ETL writes server-clock seconds |
| `msec` | extracted | qwd.usercmd.msec | mvd-etl, qwd-etl | — | MVD: tick-delta; QWD: usercmd msec |
| `ox` | extracted | mvd.pos.xyz | mvd-etl, qwd-etl | yes | ETL writes origin x |
| `oy` | extracted | mvd.pos.xyz | mvd-etl, qwd-etl | yes | ETL writes origin y |
| `oz` | extracted | mvd.pos.xyz | mvd-etl, qwd-etl | yes | ETL writes origin z |
| `vx` | extracted | mvd.velocity.xyz | mvd-etl, qwd-etl | yes | ETL writes velocity x (analyzer finite-diff; derived for QWD) |
| `vy` | extracted | mvd.velocity.xyz | mvd-etl, qwd-etl | yes | ETL writes velocity y |
| `vz` | extracted | mvd.velocity.xyz | mvd-etl, qwd-etl | yes | ETL writes velocity z |
| `pitch` | extracted | mvd.view.pitchyaw | mvd-etl, qwd-etl | yes | ETL writes view pitch |
| `yaw` | extracted | mvd.view.pitchyaw | mvd-etl, qwd-etl | yes | ETL writes view yaw |
| `roll` | extracted | mvd.view.pitchyaw | mvd-etl, qwd-etl | — | ETL writes view roll |
| `hspeed` | derived | mvd.velocity.xyz | mvd-etl, qwd-etl | yes | hypot(vx,vy) computed by ETL |
| `onground` | derived | mvd.pos.xyz | mvd-etl, qwd-etl | — | geometric onground proxy (pmove_sim); MVD has no server flag |
| `onground_is_proxy` | derived | — | mvd-etl, qwd-etl | — | ETL flags proxy provenance (always TRUE for MVD) |
| `waterlevel` | excluded-with-reason | mvd.liquid.waterlevel | — | — | decoder CAN emit via -include liquid; ETL does NOT request it -> left NULL |
| `health` | GAP | state.health | — | yes | decoder emits getStateAt h; MVD ETL requests only positions,view,velocity -> NULL. T3. |
| `armor` | GAP | state.armor | — | yes | decoder emits getStateAt a; ETL leaves NULL. T3. |
| `armor_type` | GAP | state.armor_type | — | yes | decoder emits getStateAt at; ETL leaves NULL. T3. |
| `weapon` | GAP | state.weapon_held | qwd-etl | yes | decoder emits held-weapon intervals; MVD+QWD ETL write NULL. T3. |

### `item_events`

| column | class | decoder field | populated by | registry | reason |
|---|---|---|---|---|---|
| `event_id` | structural | — | — | — | PK/FK/provenance/split bookkeeping |
| `demo_id` | structural | — | qwd-etl | — | PK/FK/provenance/split bookkeeping |
| `item_id` | derived | items.world_coords | qwd-etl | — | spatial join to items by kind+origin (NULL for backpacks) |
| `t_s` | extracted | items.pickup_respawn | qwd-etl | — | QWD ETL writes (fixture); decoder source getItems/getWeaponPickups/getBackpacks |
| `event_kind` | extracted | items.pickup_respawn | qwd-etl | — | pickup/respawn/drop/backpack_pickup |
| `player_id` | extracted | items.pickup_respawn | qwd-etl | — | picker (takenBy / weaponPickups.player) |
| `origin_x` | extracted | items.backpack_drops | qwd-etl | — | getBackpacks.origin for dropped packs |
| `origin_y` | extracted | items.backpack_drops | qwd-etl | — | getBackpacks.origin |
| `origin_z` | extracted | items.backpack_drops | qwd-etl | — | getBackpacks.origin |
| `item_type` | extracted | items.pickup_respawn | qwd-etl | — | denormalized kind |
| `team_id` | extracted | world.roster_teams | qwd-etl | yes | team attribution of the pickup |

### `actions`

| column | class | decoder field | populated by | registry | reason |
|---|---|---|---|---|---|
| `episode_id` | structural | — | mvd-etl, qwd-etl | — | PK/FK/provenance/split bookkeeping |
| `tick` | structural | — | mvd-etl, qwd-etl | — | PK/FK/provenance/split bookkeeping |
| `forwardmove` | extracted | qwd.usercmd.forwardmove | mvd-etl, qwd-etl | yes | QWD=ground-truth; MVD=IDM-recovered |
| `sidemove` | extracted | qwd.usercmd.sidemove | mvd-etl, qwd-etl | yes | QWD=ground-truth; MVD=IDM sign |
| `upmove` | extracted | qwd.usercmd.upmove | mvd-etl, qwd-etl | yes | QWD=ground-truth; MVD=IDM proxy |
| `buttons` | extracted | qwd.usercmd.buttons | mvd-etl, qwd-etl | yes | QWD=ground-truth; MVD=IDM jump bit |
| `impulse` | excluded-with-reason | qwd.usercmd.impulse | — | — | QWD struct carries it; ETL does not write the column (weapon-switch out of movement scope) |
| `cmd_yaw` | extracted | qwd.usercmd.cmd_angles | mvd-etl, qwd-etl | yes | QWD commanded yaw; MVD view-yaw proxy (lossless) |
| `cmd_pitch` | extracted | qwd.usercmd.cmd_angles | mvd-etl, qwd-etl | — | QWD commanded pitch; MVD view-pitch proxy |
| `cmd_roll` | extracted | qwd.usercmd.cmd_angles | mvd-etl, qwd-etl | — | QWD commanded roll; MVD writes 0.0 |
| `label_source` | derived | — | mvd-etl, qwd-etl | — | fidelity tier set by ETL (qwd_usercmd / idm) |
| `confidence` | derived | — | mvd-etl, qwd-etl | yes | ETL-assigned label confidence |
| `align_shift` | excluded-with-reason | — | — | — | cmd<->state alignment offset; not written by either ETL (per-frame aligned in place) |
| `is_interp` | derived | — | mvd-etl, qwd-etl | — | interp/hold-out flag set by ETL |

### `feature_partitions`

| column | class | decoder field | populated by | registry | reason |
|---|---|---|---|---|---|
| `partition_id` | structural | — | — | — | PK/FK/provenance/split bookkeeping |
| `map_id` | structural | — | — | — | PK/FK/provenance/split bookkeeping |
| `dt` | structural | — | — | — | PK/FK/provenance/split bookkeeping |
| `path` | excluded-with-reason | — | — | — | gold-parquet build lineage; not a decoder field |
| `n_rows` | structural | — | — | — | PK/FK/provenance/split bookkeeping |
| `registry_version` | structural | — | — | — | PK/FK/provenance/split bookkeeping |
| `norm_artifact_version` | structural | — | — | — | PK/FK/provenance/split bookkeeping |
| `git_sha` | structural | — | — | — | PK/FK/provenance/split bookkeeping |

### `teams`

| column | class | decoder field | populated by | registry | reason |
|---|---|---|---|---|---|
| `team_id` | structural | — | — | — | PK/FK/provenance/split bookkeeping |
| `demo_id` | structural | — | — | — | PK/FK/provenance/split bookkeeping |
| `name` | extracted | world.roster_teams | — | — | QWD ETL via fixture; decoder getOverview roster |
| `side` | derived | world.roster_teams | — | — | canonical A/B side label |

### `actor_ticks`

| column | class | decoder field | populated by | registry | reason |
|---|---|---|---|---|---|
| `episode_id` | structural | — | qwd-etl | — | PK/FK/provenance/split bookkeeping |
| `tick` | structural | — | qwd-etl | — | PK/FK/provenance/split bookkeeping |
| `actor_id` | structural | — | qwd-etl | — | PK/FK/provenance/split bookkeeping |
| `team_id` | GAP | world.roster_teams | qwd-etl | — | QWD writes NULL (no roster join yet); MVD writes NONE. T4. |
| `alive` | extracted | state.spawn_death | qwd-etl | — | QWD writes; MVD GAP (T4) |
| `ox` | extracted | world.all_players_state | qwd-etl | — | QWD ETL writes (self+observed others); MVD ETL writes NONE -> T4 |
| `oy` | extracted | world.all_players_state | qwd-etl | — | QWD only; MVD GAP (T4) |
| `oz` | extracted | world.all_players_state | qwd-etl | — | QWD only; MVD GAP (T4) |
| `vx` | extracted | world.all_players_state | qwd-etl | yes | QWD only; MVD GAP (T4) |
| `vy` | extracted | world.all_players_state | qwd-etl | yes | QWD only; MVD GAP (T4) |
| `vz` | extracted | world.all_players_state | qwd-etl | yes | QWD only; MVD GAP (T4) |
| `pitch` | extracted | world.all_players_state | qwd-etl | — | QWD only; MVD GAP (T4) |
| `yaw` | extracted | world.all_players_state | qwd-etl | — | QWD only; MVD GAP (T4) |
| `roll` | extracted | world.all_players_state | qwd-etl | — | QWD only; MVD GAP (T4) |
| `hspeed` | derived | world.all_players_state | qwd-etl | — | hypot(vx,vy) |
| `onground` | derived | world.all_players_state | qwd-etl | — | geometric proxy (QWD); MVD GAP |
| `onground_is_proxy` | derived | — | qwd-etl | — | proxy-provenance flag |
| `waterlevel` | excluded-with-reason | mvd.liquid.waterlevel | — | — | decoder CAN emit; not requested -> NULL |
| `health` | GAP | state.health | — | yes | omniscient health decodable; populated NOWHERE. T3/T4. |
| `armor` | GAP | state.armor | — | yes | decodable; populated nowhere. T3/T4. |
| `armor_type` | GAP | state.armor_type | — | yes | decodable; populated nowhere. T3/T4. |
| `weapon` | GAP | state.weapon_held | — | yes | decodable; populated nowhere. T3/T4. |

### `actor_visibility`

| column | class | decoder field | populated by | registry | reason |
|---|---|---|---|---|---|
| `episode_id` | structural | — | — | — | PK/FK/provenance/split bookkeeping |
| `tick` | structural | — | — | — | PK/FK/provenance/split bookkeeping |
| `observer_id` | structural | — | — | — | PK/FK/provenance/split bookkeeping |
| `target_id` | structural | — | — | — | PK/FK/provenance/split bookkeeping |
| `is_visible` | GAP | — | — | yes | spec'd POMDP gate (PVS+FOV+LOS); table empty. T8. |
| `pvs_visible` | GAP | — | — | — | BSP visleaf prefilter; empty. T8. |
| `in_fov` | GAP | — | — | — | bearing-in-FOV; empty. T8. |
| `los_clear` | GAP | — | — | — | raycast on hull-0; empty. T8. |
| `vis_angle_source` | structural | — | — | — | PK/FK/provenance/split bookkeeping |
| `last_seen_tick` | structural | — | — | — | PK/FK/provenance/split bookkeeping |
| `last_seen_t_s` | GAP | — | — | — | belief/memory block; empty. T8. |
| `last_seen_ox` | GAP | — | — | yes | belief/memory block; empty. T8. |
| `last_seen_oy` | GAP | — | — | — | belief/memory block; empty. T8. |
| `last_seen_oz` | GAP | — | — | — | belief/memory block; empty. T8. |
| `last_seen_vx` | GAP | — | — | — | belief/memory block; empty. T8. |
| `last_seen_vy` | GAP | — | — | — | belief/memory block; empty. T8. |
| `last_seen_vz` | GAP | — | — | — | belief/memory block; empty. T8. |
| `time_since_seen_s` | GAP | — | — | yes | belief block; empty. T8. |
| `seen_ever` | GAP | — | — | yes | belief block; empty. T8. |

### `audio_cues`

| column | class | decoder field | populated by | registry | reason |
|---|---|---|---|---|---|
| `episode_id` | structural | — | — | — | PK/FK/provenance/split bookkeeping |
| `tick` | structural | — | — | — | PK/FK/provenance/split bookkeeping |
| `observer_id` | structural | — | — | — | PK/FK/provenance/split bookkeeping |
| `src_type` | GAP | audio.weapon_item_cues | — | — | weapon_fire/item_pickup from getEvents + synthesized footstep; table empty. T8. |
| `src_x` | GAP | audio.weapon_item_cues | — | yes | sound source world position; empty. T8. |
| `src_y` | GAP | audio.weapon_item_cues | — | yes | sound source world position; empty. T8. |
| `src_z` | GAP | audio.weapon_item_cues | — | — | sound source world position; empty. T8. |
| `intensity0` | GAP | — | — | yes | emission intensity (decay model); empty. T8. |
| `t_emit_s` | GAP | — | — | yes | emission time for decay; empty. T8. |

### `frag_events`

| column | class | decoder field | populated by | registry | reason |
|---|---|---|---|---|---|
| `event_id` | structural | — | — | — | PK/FK/provenance/split bookkeeping |
| `demo_id` | structural | — | — | — | PK/FK/provenance/split bookkeeping |
| `t_s` | extracted | frags.kill_timeline | — | — | QWD ETL via fixture; decoder getFrags |
| `killer_id` | extracted | frags.kill_timeline | — | — | getFrags.killer |
| `victim_id` | extracted | frags.kill_timeline | — | — | getFrags.victim |
| `weapon` | extracted | frags.kill_timeline | — | — | getFrags.weapon |
| `is_suicide` | extracted | frags.kill_timeline | — | — | getFrags.isSuicide |
| `is_teamkill` | extracted | frags.kill_timeline | — | — | getFrags.isTeamKill |

### `region_control_timeline`

| column | class | decoder field | populated by | registry | reason |
|---|---|---|---|---|---|
| `demo_id` | structural | — | qwd-etl | — | PK/FK/provenance/split bookkeeping |
| `bucket_idx` | structural | — | qwd-etl | — | PK/FK/provenance/split bookkeeping |
| `t_s` | extracted | region.control_timeline | qwd-etl | — | QWD ETL via fixture; decoder getRegionControl |
| `region_name` | extracted | region.control_timeline | qwd-etl | — | getRegionControl region |
| `teamA_control` | extracted | region.control_timeline | qwd-etl | yes | side-A control fraction |
| `teamB_control` | extracted | region.control_timeline | qwd-etl | — | side-B control fraction |
| `contested` | extracted | region.control_timeline | qwd-etl | — | contested flag |

## Decoder Result inventory (master list)

Sourced from the committed static reference `docs/ml-data-architecture/_source-schemas.md` + qw-analyze schema-33 `-include` groups + getStateAt
field codes + the QWD `usercmd_t` struct. Referenced by decoder **role**, not tool name.

| decoder field | origin | availability | note |
|---|---|---|---|
| `mvd.pos.xyz` | qw-analyze -include positions (native ~77fps track) | MVD+QWD | origin qu |
| `mvd.pos.loc` | qw-analyze -include positions (loc index) | MVD | nearest named loc |
| `mvd.view.pitchyaw` | qw-analyze -include view (angle16 vya/vp) | MVD+QWD | view angles deg; lossless |
| `mvd.velocity.xyz` | qw-analyze -include velocity (finite-differenced) | MVD+QWD | qu/s; analyzer-derived |
| `mvd.height.floor` | qw-analyze -include height | MVD | height above floor; NOT requested by ETL |
| `mvd.liquid.waterlevel` | qw-analyze -include liquid | MVD | waterlevel proxy; NOT requested by ETL |
| `state.health` | getStateAt h (int16) | MVD | HP; state-only stream |
| `state.armor` | getStateAt a (int16) | MVD | AP |
| `state.armor_type` | getStateAt at ('ga'/'ya'/'ra'/'') | MVD | armor type |
| `state.weapon_held` | getStateAt rl/lg/gl/ssg/sng (bools) | MVD | held-weapon intervals; no single active-weapon int |
| `state.ammo` | getStateAt sh/nl/rk/cl (int16) | MVD | shells/nails/rockets/cells |
| `state.powerups` | getStateAt q/pe/r (bools) | MVD | quad/pent/ring held |
| `state.spawn_death` | getStateAt sp/d (bools) | MVD | spawn/death event bools |
| `world.all_players_state` | getStateAt (every player) / getBuckets | MVD | omniscient per-player state -> actor_ticks |
| `world.roster_teams` | getOverview teams/players roster | MVD | team membership + frags |
| `items.world_coords` | getMapEntities / getItems x,y,z (float32 qu) | MVD | static item spawn coords + classname + spawnflags |
| `items.pickup_respawn` | getItems phases[] (takenAt/respawnAt/takenBy) | MVD | pickup + observed respawn timeline |
| `items.weapon_pickups` | getWeaponPickups (world+backpack acquisitions) | MVD | slot-weapon pickups + effectiveness |
| `items.backpack_drops` | getBackpacks (origin qu, entNum join key) | MVD | RL/LG drop world position (KTX) |
| `frags.kill_timeline` | getFrags (time,killer,victim,weapon,isSuicide,isTeamKill) | MVD | kill timeline |
| `events.life` | getEvents frag/powerup/streak/spawn/death/weapon/item/chat | MVD | authoritative spawn/death log |
| `damage.per_hit` | getEvents damage detail (victim,damage,weapon,isSplash...) | MVD (KTX ~2024+) | per-hit KTX damage; mvdhidden_dmgdone |
| `region.control_timeline` | getRegionControl bucketStates/stats | MVD | bucketed map-region control |
| `audio.weapon_item_cues` | getEvents weapon/item (sound sources) | MVD | weapon-fire/item-pickup audio cue sources |
| `locgraph.movement` | getLocGraph / getLocTrails | MVD | data-derived loc movement graph (NOT a Frogbot nav mesh) |
| `metadata.ruleset` | getMetadata serverInfo/matchSettings | MVD | ruleset: spawnmodel/powerups/noItems |
| `demoinfo.scoreboard` | getDemoInfo (KTX scoreboard, Bot skill) | MVD (KTX) | per-player stats; is_bot flag |
| `provenance.sha` | loadDemo sha256 + map + duration | MVD+QWD | demo provenance |
| `qwd.usercmd.forwardmove` | QWD usercmd_t.forwardmove | QWD | ground-truth forward input |
| `qwd.usercmd.sidemove` | QWD usercmd_t.sidemove | QWD | ground-truth side input |
| `qwd.usercmd.upmove` | QWD usercmd_t.upmove | QWD | ground-truth up input (jump/swim) |
| `qwd.usercmd.buttons` | QWD usercmd_t.buttons | QWD | button bitfield (jump/attack) |
| `qwd.usercmd.impulse` | QWD usercmd_t.impulse | QWD | weapon switch |
| `qwd.usercmd.cmd_angles` | QWD usercmd_t.angles[3] | QWD | commanded view angles deg |
| `qwd.usercmd.msec` | QWD usercmd_t.msec | QWD | frame duration ms |
| `qwd.view_angles` | QWD per-record view-angle floats | QWD | resulting view angles deg |

## Summary

| class | count |
|---|---|
| extracted | 54 |
| derived | 15 |
| excluded-with-reason | 43 |
| **GAP** | **28** |
| (structural: PK/FK/provenance) | 66 |
| (UNCLASSIFIED — needs a verdict) | 0 |
| classified content columns | 140 |

## GAP reconciliation (vs epic #388 / build-out plan)

The per-column GAPs above are the *defined-but-unpopulated* columns the population
tickets (T3/T4/T8) fill. They roll up to the **6 genuine gaps** the plan names — the
only truly-new work — confirming the audit neither invents nor misses a gap:

- G1: no coverage audit (THIS script fills it)
- G2: schema-file drift (scripts/catalog_schema.sql operative vs data/catalog/catalog.sql dup vs registry's dangling `schema/catalog.sql` reference)
- G3: damage_events table absent (only frag_events exists)
- G4: ammo + powerup-remaining source columns absent (registry defines the features)
- G5: stored [G] geometry / [R] regime / leg-phase columns absent
- G6: docs/27 inaccuracies (frag_events/actor_visibility/audio_cues/teams called greenfield/reserved when schema-defined-but-empty; wrong schema path)

**Scoping (which ticket each per-column GAP feeds):** `player_ticks`/`actor_ticks` health/armor/armor_type/weapon -> T3/T4; `actor_ticks` (MVD all-players) + team_id -> T4; `actor_visibility.*` + `audio_cues.*` -> T8. The ammo/powerup source columns (G4), `damage_events` table (G3), and [G]/[R]/leg-phase columns (G5) are **absent from the schema entirely** (not just unpopulated) — they are schema-addition tickets T5/T6/T7, so they do not appear as columns here; that absence IS the finding.
