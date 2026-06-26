# Extraction-coverage audit — decoder Result inventory vs catalog vs registry

> **GENERATED FILE — do not edit by hand.** Regenerate with:
> ```
> python3 scripts/audit_extraction_coverage.py
> ```
>
> Read-only audit for Demo Extraction Spec v1 (`docs/27` §3.9/§7), ticket #389 (T1),
> epic #388. Loads NO database, hits NO network. It enumerates the decoder Result
> inventory (anchored in `docs/ml-data-architecture/_source-schemas.md`) and diffs it against the operative
> schema `scripts/catalog_schema.sql`, `data/catalog/feature_registry.json`, and what
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
| `damage_available` | extracted | damage.per_hit | mvd-etl | — | era-gate flag: TRUE if the demo carried the `-view full` damage block (per-hit stream authoritative), FALSE => UNKNOWN/pre-era (fail-closed, never zero). MVD ETL writes per demo (T5) |

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
| `start_t_s` | structural | — | mvd-etl | — | PK/FK/provenance/split bookkeeping |
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
| `onground` | derived | mvd.pos.xyz | mvd-etl, qwd-etl | yes | geometric onground proxy (pmove_sim); MVD has no server flag |
| `onground_is_proxy` | derived | — | mvd-etl, qwd-etl | — | ETL flags proxy provenance (always TRUE for MVD) |
| `waterlevel` | excluded-with-reason | mvd.liquid.waterlevel | — | — | decoder CAN emit via -include liquid; ETL does NOT request it -> left NULL |
| `health` | extracted | state.health | mvd-etl | yes | MVD ETL forward-fills the `-event-types health` value step-timeline onto each tick (T3). NULL on QWD (not yet wired). |
| `armor` | extracted | state.armor | mvd-etl | yes | MVD ETL forward-fills the `-event-types armor` value step-timeline onto each tick (T3). NULL on QWD. |
| `armor_type` | GAP | state.armor_type | — | yes | GAP today, but an ETL-WIRING gap not a missing source: the `at` armor-type stream EXISTS and already populates actor_ticks.armor_type (T4) — the ego player_ticks fill loop just doesn't forward-fill it onto the spine. Wiring it is a catalog-buildout (Class-A) task, NOT an analyzer-fitness decoder change. |
| `weapon` | GAP | state.weapon_active | qwd-etl | yes | GAP today: the per-tick weapon stream is gain/lose POSSESSION, not STAT_ACTIVEWEAPON (the active-weapon id the column means). STAT_ACTIVEWEAPON IS parsed by the mvd-reader (parser/stats.go) but NOT surfaced in the Result; surfacing it is WS-1 of analyzer-fitness (see state.weapon_active). GAP until that decoder change lands. |
| `shells` | extracted | state.ammo | mvd-etl | — | MVD ETL forward-fills the `-view full` `sh` step-timeline onto each tick (T6). NULL on QWD. |
| `nails` | extracted | state.ammo | mvd-etl | — | MVD ETL forward-fills the `-view full` `nl` step-timeline (T6). NULL on QWD. |
| `rockets` | extracted | state.ammo | mvd-etl | — | MVD ETL forward-fills the `-view full` `rk` step-timeline (T6). NULL on QWD. |
| `cells` | extracted | state.ammo | mvd-etl | — | MVD ETL forward-fills the `-view full` `cl` step-timeline (T6). NULL on QWD. |
| `quad_rem` | extracted | state.powerups | mvd-etl | — | MVD ETL derives remaining-seconds from the `-view full` `q` held-interval [s,e] at each tick (T6); NULL when not held. NULL on QWD. |
| `pent_rem` | extracted | state.powerups | mvd-etl | — | MVD ETL derives remaining-seconds from the `-view full` `pe` held-interval at each tick (T6); NULL when not held. NULL on QWD. |
| `ring_rem` | extracted | state.powerups | mvd-etl | — | MVD ETL derives remaining-seconds from the `-view full` `r` held-interval at each tick (T6); NULL when not held. NULL on QWD. |
| `floor_height` | derived | geom.dm3_bsp | mvd-etl | — | [G] z - downward hull-1 floor-trace endpoint (matches trace.csv height_above_floor). NULL where the trace startsolids / over void. MVD ETL (T7) |
| `over_void` | derived | geom.dm3_bsp | mvd-etl | — | [G] 1 if no floor within FLOOR_PROBE_QU OR floor < VOID_THRESH_QU (deep chasm); matches build_trace.py over_void. NULL if startsolid (T7) |
| `wall_dist` | derived | geom.dm3_bsp | mvd-etl | — | [G] min of the 4 axial ±x/±y hull-1 wall traces, capped at WALL_PROBE_QU. NULL if startsolid (T7) |
| `ledge_ahead` | derived | geom.dm3_bsp | mvd-etl | — | [G] floor drop along velocity (forward+down trace gap). NULL if hspeed<LEDGE_MIN_HSPEED / void / startsolid (T7) |
| `ramp_normal_z` | derived | geom.dm3_bsp | mvd-etl | — | [R-input] floor-plane normal z from the downward trace (1.0 flat; <0.95 ramp). NULL over void/startsolid (T7) |
| `regime` | derived | — | mvd-etl | — | [R] accel/cruise/grounded/airborne/water/on-ramp from hspeed+onground+ramp_normal_z (T7) |
| `leg_phase` | derived | — | mvd-etl | — | launch/cruise/approach/land within a resource-to-resource leg (route_legs #334 segmentation); NULL outside any ego goal-conditioned leg (T7) |

### `item_events`

| column | class | decoder field | populated by | registry | reason |
|---|---|---|---|---|---|
| `event_id` | structural | — | — | — | PK/FK/provenance/split bookkeeping |
| `demo_id` | structural | — | mvd-etl, qwd-etl | — | PK/FK/provenance/split bookkeeping |
| `item_id` | derived | items.world_coords | mvd-etl, qwd-etl | — | spatial join to items by origin x/y/z (NULL for backpack drops) |
| `t_s` | extracted | items.pickup_respawn | mvd-etl, qwd-etl | — | MVD writes from `-view full` items.items[].phases[] + backpacks (T4); QWD via fixture |
| `event_kind` | extracted | items.pickup_respawn | mvd-etl, qwd-etl | — | pickup (phase.takenAt) / respawn (phase.respawnAt) / drop (backpack) |
| `player_id` | extracted | items.pickup_respawn | mvd-etl, qwd-etl | — | picker (phase.takenBy / backpack.player); NULL for respawn |
| `origin_x` | extracted | items.backpack_drops | mvd-etl, qwd-etl | — | backpacks.origin for dropped packs (NULL for static pickups, which carry item_id) |
| `origin_y` | extracted | items.backpack_drops | mvd-etl, qwd-etl | — | backpacks.origin |
| `origin_z` | extracted | items.backpack_drops | mvd-etl, qwd-etl | — | backpacks.origin |
| `item_type` | extracted | items.pickup_respawn | mvd-etl, qwd-etl | — | denormalized kind (items.kind / backpack.weapon) |
| `team_id` | extracted | world.roster_teams | mvd-etl, qwd-etl | yes | team attribution of the pickup (phase.team / backpack.team -> teams) |

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
| `demo_id` | structural | — | mvd-etl | — | PK/FK/provenance/split bookkeeping |
| `name` | extracted | world.roster_teams | mvd-etl | — | MVD writes distinct per-player roster team names (T4); QWD via fixture |
| `side` | derived | world.roster_teams | mvd-etl | — | canonical A/B side label (first-seen team order) |

### `actor_ticks`

| column | class | decoder field | populated by | registry | reason |
|---|---|---|---|---|---|
| `episode_id` | structural | — | mvd-etl, qwd-etl | — | PK/FK/provenance/split bookkeeping |
| `tick` | structural | — | mvd-etl, qwd-etl | — | PK/FK/provenance/split bookkeeping |
| `actor_id` | structural | — | mvd-etl, qwd-etl | — | PK/FK/provenance/split bookkeeping |
| `team_id` | extracted | world.roster_teams | mvd-etl, qwd-etl | — | MVD writes the absolute team_id from the per-player roster team (T4); QWD writes NULL (no roster join yet) |
| `alive` | extracted | state.spawn_death | mvd-etl, qwd-etl | yes | QWD writes; MVD forward-fills the per-player death/spawn step-timeline (T4; NULL before first death/spawn) |
| `ox` | extracted | world.all_players_state | mvd-etl, qwd-etl | — | QWD ETL writes (self+observed others); MVD ETL writes the omniscient all-players state per episode tick (T4) |
| `oy` | extracted | world.all_players_state | mvd-etl, qwd-etl | — | QWD + MVD (T4) |
| `oz` | extracted | world.all_players_state | mvd-etl, qwd-etl | — | QWD + MVD (T4) |
| `vx` | extracted | world.all_players_state | mvd-etl, qwd-etl | yes | QWD + MVD (T4) |
| `vy` | extracted | world.all_players_state | mvd-etl, qwd-etl | yes | QWD + MVD (T4) |
| `vz` | extracted | world.all_players_state | mvd-etl, qwd-etl | yes | QWD + MVD (T4) |
| `pitch` | extracted | world.all_players_state | mvd-etl, qwd-etl | — | QWD + MVD (T4) |
| `yaw` | extracted | world.all_players_state | mvd-etl, qwd-etl | — | QWD + MVD (T4) |
| `roll` | extracted | world.all_players_state | mvd-etl, qwd-etl | — | QWD + MVD (MVD writes 0.0; angle16 has no roll) (T4) |
| `hspeed` | derived | world.all_players_state | mvd-etl, qwd-etl | — | hypot(vx,vy) |
| `onground` | derived | world.all_players_state | mvd-etl, qwd-etl | — | geometric proxy (QWD); MVD leaves NULL for observed-others (the proxy lives on the ego player_ticks spine) |
| `onground_is_proxy` | derived | — | mvd-etl, qwd-etl | — | proxy-provenance flag |
| `waterlevel` | excluded-with-reason | mvd.liquid.waterlevel | — | — | decoder CAN emit; not requested -> NULL |
| `health` | extracted | state.health | mvd-etl | yes | MVD forward-fills each player's `-view full` `h` step-timeline (T4); QWD NULL |
| `armor` | extracted | state.armor | mvd-etl | yes | MVD forward-fills each player's `a` step-timeline (T4); QWD NULL |
| `armor_type` | extracted | state.armor_type | mvd-etl | yes | MVD forward-fills each player's `at` ('ga'/'ya'/'ra') step-timeline -> 0/1/2 (T4). The `-view full` `at` stream carries the skin/type the T3 `-event-types armor` decode lacked; QWD NULL |
| `weapon` | GAP | state.weapon_active | mvd-etl | yes | GAP today (same as player_ticks.weapon): the per-tick weapon stream is gain/lose POSSESSION, not STAT_ACTIVEWEAPON. The active-weapon id IS parsed by the mvd-reader but unsurfaced; surfacing it = WS-1 of analyzer-fitness. GAP until then. |
| `shells` | extracted | state.ammo | mvd-etl | — | MVD forward-fills each player's `-view full` `sh` step-timeline (T6); QWD NULL |
| `nails` | extracted | state.ammo | mvd-etl | — | MVD forward-fills each player's `nl` step-timeline (T6); QWD NULL |
| `rockets` | extracted | state.ammo | mvd-etl | — | MVD forward-fills each player's `rk` step-timeline (T6); QWD NULL |
| `cells` | extracted | state.ammo | mvd-etl | — | MVD forward-fills each player's `cl` step-timeline (T6); QWD NULL |
| `quad_rem` | extracted | state.powerups | mvd-etl | — | MVD derives remaining-seconds from each player's `q` held-interval at each tick (T6; NULL when not held); QWD NULL |
| `pent_rem` | extracted | state.powerups | mvd-etl | — | MVD derives remaining-seconds from each player's `pe` held-interval (T6; NULL when not held); QWD NULL |
| `ring_rem` | extracted | state.powerups | mvd-etl | — | MVD derives remaining-seconds from each player's `r` held-interval (T6; NULL when not held); QWD NULL |
| `floor_height` | derived | geom.dm3_bsp | mvd-etl | — | [G] per-actor z above floor from the dm3 hull-1 floor trace (T7). NULL if startsolid |
| `over_void` | derived | geom.dm3_bsp | mvd-etl | — | [G] per-actor void/deep-chasm-below flag (T7). NULL if startsolid |
| `wall_dist` | derived | geom.dm3_bsp | mvd-etl | — | [G] per-actor nearest-wall distance (±x/±y), capped (T7). NULL if startsolid |
| `ledge_ahead` | derived | geom.dm3_bsp | mvd-etl | — | [G] per-actor forward floor-drop along velocity (T7). NULL if hspeed<min/void/startsolid |
| `ramp_normal_z` | derived | geom.dm3_bsp | mvd-etl | — | [R-input] per-actor floor-plane normal z (T7). NULL over void/startsolid |
| `regime` | derived | — | mvd-etl | — | [R] per-actor regime from hspeed + a LOCAL geometric onground + ramp_normal_z (T7); the actor_ticks.onground column itself stays NULL by T4 design |
| `leg_phase` | derived | — | mvd-etl | — | ALWAYS NULL on actor_ticks: leg-phase needs the ego goal/route context, defined only for the episode-owning ego player (T7) |

### `actor_visibility`

| column | class | decoder field | populated by | registry | reason |
|---|---|---|---|---|---|
| `episode_id` | structural | — | mvd-etl | — | PK/FK/provenance/split bookkeeping |
| `tick` | structural | — | mvd-etl | — | PK/FK/provenance/split bookkeeping |
| `observer_id` | structural | — | mvd-etl | — | PK/FK/provenance/split bookkeeping |
| `target_id` | structural | — | mvd-etl | — | PK/FK/provenance/split bookkeeping |
| `is_visible` | derived | — | mvd-etl | yes | POMDP gate = COALESCE(pvs,TRUE) AND in_fov AND los_clear; derived offline (T8). |
| `pvs_visible` | derived | — | mvd-etl | — | BSP visleaf prefilter NOT sourced (no visdata decoder) -> NULL; optional perf prefilter, LOS is the gate (T8). |
| `in_fov` | derived | — | mvd-etl | — | target bearing within the observer awareness cone (reuses egocentric angle math) (T8). |
| `los_clear` | derived | — | mvd-etl | — | raycast observer-eye->target-eye on dm3.bsp hull-0 (pmove_sim) (T8). |
| `vis_angle_source` | derived | — | mvd-etl | — | 'demoparser' — schema-33 carries real per-tick view yaw/pitch (T8). |
| `last_seen_tick` | structural | — | mvd-etl | — | PK/FK/provenance/split bookkeeping |
| `last_seen_t_s` | derived | — | mvd-etl | — | belief/memory block carried forward when target invisible (T8). |
| `last_seen_ox` | derived | — | mvd-etl | yes | belief/memory block carried forward when target invisible (T8). |
| `last_seen_oy` | derived | — | mvd-etl | — | belief/memory block carried forward when target invisible (T8). |
| `last_seen_oz` | derived | — | mvd-etl | — | belief/memory block carried forward when target invisible (T8). |
| `last_seen_vx` | derived | — | mvd-etl | — | belief/memory block carried forward when target invisible (T8). |
| `last_seen_vy` | derived | — | mvd-etl | — | belief/memory block carried forward when target invisible (T8). |
| `last_seen_vz` | derived | — | mvd-etl | — | belief/memory block carried forward when target invisible (T8). |
| `time_since_seen_s` | derived | — | mvd-etl | yes | seconds since last-seen (0 visible, NULL never-seen) (T8). |
| `seen_ever` | derived | — | mvd-etl | yes | latches once the observer has ever seen the target (T8). |

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
| `demo_id` | structural | — | mvd-etl | — | PK/FK/provenance/split bookkeeping |
| `t_s` | extracted | frags.kill_timeline | mvd-etl | — | MVD writes from `-view full` frags.frags (T4); QWD via fixture |
| `killer_id` | extracted | frags.kill_timeline | mvd-etl | — | frags.frags[].killer -> player_id |
| `victim_id` | extracted | frags.kill_timeline | mvd-etl | — | frags.frags[].victim -> player_id |
| `weapon` | extracted | frags.kill_timeline | mvd-etl | — | frags.frags[].weapon (rl/lg/sg/.../tele/fall/teamkill) |
| `is_suicide` | extracted | frags.kill_timeline | mvd-etl | — | frags.frags[].isSuicide |
| `is_teamkill` | extracted | frags.kill_timeline | mvd-etl | — | frags.frags[].isTeamKill |

### `damage_events`

| column | class | decoder field | populated by | registry | reason |
|---|---|---|---|---|---|
| `event_id` | structural | — | — | — | PK/FK/provenance/split bookkeeping |
| `demo_id` | structural | — | mvd-etl | — | PK/FK/provenance/split bookkeeping |
| `t_s` | extracted | damage.per_hit | mvd-etl | — | MVD writes from `-view full` damage.events (T5, era-gated); damage.events[].time/1000 |
| `attacker_id` | extracted | damage.per_hit | mvd-etl | — | damage.events[].attacker -> player_id (NULL for 'world'/environmental) |
| `victim_id` | extracted | damage.per_hit | mvd-etl | — | damage.events[].victim -> player_id |
| `weapon` | extracted | damage.per_hit | mvd-etl | — | damage.events[].weapon (rl/lg/sg/.../fall/drown/trigger) |
| `damage` | extracted | damage.per_hit | mvd-etl | — | damage.events[].damage (hit-point amount) |
| `is_splash` | extracted | damage.per_hit | mvd-etl | — | damage.events[].isSplash |
| `is_env` | extracted | damage.per_hit | mvd-etl | — | damage.events[].isEnv (fall/drown/trigger) |
| `is_self` | extracted | damage.per_hit | mvd-etl | — | damage.events[].isSelf (attacker==victim) |
| `is_teamkill` | extracted | damage.per_hit | mvd-etl | — | damage.events[].isTeam (same-team damage) |

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
| `state.weapon_held` | getStateAt rl/lg/gl/ssg/sng (bools) | MVD | held-weapon POSSESSION intervals (5 of 8 weapons; SG/NG/axe absent) — NOT the active/selected weapon |
| `state.weapon_active` | STAT_ACTIVEWEAPON — PARSED by the mvd-reader (parser/stats.go) but NOT surfaced in the Result (v35) | MVD — parsed, UNSURFACED | active-weapon id; the demoparser fork exposes it as active_weapon()=stat[10]. Surfacing it in mvd_analyzer = WS-1 (analyzer-fitness) -> unblocks player_ticks/actor_ticks.weapon (weapon_onehot) |
| `state.ammo` | getStateAt sh/nl/rk/cl (int16) | MVD | shells/nails/rockets/cells |
| `state.powerups` | getStateAt q/pe/r (bools) | MVD | quad/pent/ring held |
| `state.spawn_death` | getStateAt sp/d (bools) | MVD | spawn/death event bools |
| `mvd.hidden.usercmd` | KTX mvdhidden usercmd blocks 0x0001/0x0002 (mvd/types.go); the mvd-reader hidden-message switch (parser.go) does NOT decode them | MVD (KTX) — POTENTIAL, undecoded | true per-player usercmd. FEASIBILITY PROVEN: the independent demoparser fork DECODES this block (src/mvd/hidden.rs:143-179) recovering forward/side/buttons/impulse (the full 23-byte block also carries up/3 angles/msec, read-then-discarded). If per-tick-dense + present in our KTX corpus this yields GROUND-TRUTH forwardmove for ALL players across the MVD corpus -> dissolves the 'MVD=obs-only, forwardmove-unrecoverable' premise. WS-2 spike gates on density + KTX-version coverage, NOT feasibility |
| `world.all_players_state` | getStateAt (every player) / getBuckets | MVD | omniscient per-player state -> actor_ticks |
| `world.roster_teams` | getOverview teams/players roster | MVD | team membership + frags |
| `items.world_coords` | getMapEntities / getItems x,y,z (float32 qu) | MVD | static item spawn coords + classname + spawnflags |
| `items.pickup_respawn` | getItems phases[] (takenAt/respawnAt/takenBy) | MVD | pickup + observed respawn timeline |
| `items.weapon_pickups` | getWeaponPickups (world+backpack acquisitions) | MVD | slot-weapon pickups + effectiveness |
| `items.backpack_drops` | getBackpacks (origin qu, entNum join key) | MVD | RL/LG drop world position (KTX) |
| `frags.kill_timeline` | getFrags (time,killer,victim,weapon,isSuicide,isTeamKill) | MVD | kill timeline |
| `events.life` | getEvents frag/powerup/streak/spawn/death/weapon/item/chat | MVD | authoritative spawn/death log |
| `damage.per_hit` | `-view full` damage.events (attacker,victim,weapon,damage,isSplash/isEnv/isSelf/isTeam) | MVD (KTX ~2024+) | per-hit KTX damage; mvdhidden_dmgdone. POPULATED -> damage_events (T5), ERA-GATED via demos.damage_available |
| `region.control_timeline` | getRegionControl bucketStates/stats | MVD | bucketed map-region control |
| `audio.weapon_item_cues` | getEvents weapon/item (sound sources) | MVD | weapon-fire/item-pickup audio cue sources |
| `locgraph.movement` | getLocGraph / getLocTrails | MVD | data-derived loc movement graph (NOT a Frogbot nav mesh) |
| `metadata.ruleset` | getMetadata serverInfo/matchSettings | MVD | ruleset: spawnmodel/powerups/noItems |
| `demoinfo.scoreboard` | getDemoInfo (KTX scoreboard, Bot skill) | MVD (KTX) | per-player stats; is_bot flag |
| `provenance.sha` | loadDemo sha256 + map + duration | MVD+QWD | demo provenance |
| `geom.dm3_bsp` | pmove_sim hull-1 traces over the sha-locked dm3.bsp (NOT a decoder field) | derived | [G] wall/floor/ledge/ramp from BSP collision geometry (T7) |
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
| extracted | 84 |
| derived | 43 |
| excluded-with-reason | 43 |
| **GAP** | **9** |
| (structural: PK/FK/provenance) | 68 |
| (UNCLASSIFIED — needs a verdict) | 0 |
| classified content columns | 179 |

## GAP reconciliation (vs epic #388 / build-out plan)

The per-column GAPs above are the *defined-but-unpopulated* columns the population
tickets (T3/T4/T8) fill. They roll up to the **6 genuine gaps** the plan names — the
only truly-new work — confirming the audit neither invents nor misses a gap:

- G1: no coverage audit (THIS script fills it)
- G2: schema-file drift (scripts/catalog_schema.sql operative vs data/catalog/catalog.sql dup vs registry's dangling `schema/catalog.sql` reference)
- G3: damage_events table absent (only frag_events exists) — ADDRESSED by T5 #393: the table is now schema-defined + populated from `-view full` damage.events, era-gated via demos.damage_available (fail-closed)
- G4: ammo + powerup-remaining source columns absent (registry defines the features) — ADDRESSED by T6 #394: shells/nails/rockets/cells + quad_rem/pent_rem/ring_rem added to player_ticks + actor_ticks and populated from the same `-view full` per-player sh/nl/rk/cl + q/pe/r streams (ammo forward-filled; powerup remaining-seconds derived from the held-interval, NULL when not held)
- G5: stored [G] geometry / [R] regime / leg-phase columns absent — ADDRESSED by T7 #395: floor_height/over_void/wall_dist/ledge_ahead/ramp_normal_z + regime + leg_phase added to player_ticks + actor_ticks and DERIVED (pmove_sim hull-1 traces over the sha-locked dm3.bsp for [G]; kinematics+ramp for [R]; route_legs #334 segmentation for leg-phase). They are now schema-defined + populated, appearing as DERIVED columns above (NULL where undefined, never fabricated; leg_phase NULL on actor_ticks — no ego goal context)
- G6: docs/27 inaccuracies (frag_events/actor_visibility/audio_cues/teams called greenfield/reserved when schema-defined-but-empty; wrong schema path)

**Scoping (which ticket each per-column GAP feeds):** `player_ticks` health/armor -> T3 (DONE); the omniscient `actor_ticks` all-players state + health/armor/armor_type + team_id, plus `item_events`/`frag_events`/`teams` -> T4 (DONE; from `-view full`). The GAPs that REMAIN: `player_ticks.armor_type`/`weapon` + `actor_ticks.weapon`, and the `audio_cues.*` derived layer -> T8 (separate from visibility; not in #396). The weapon GAPs are an ANALYZER-FITNESS decoder gap: STAT_ACTIVEWEAPON is parsed by the mvd-reader but not surfaced in the Result (surfacing it = WS-1; see the `state.weapon_active` inventory entry); `player_ticks.armor_type` is instead an ETL-WIRING gap (the `at` stream exists, already feeding `actor_ticks.armor_type` — Class-A catalog-buildout, not a decoder change). The `damage_events` table (G3) is now schema-defined + populated (T5 #393, era-gated via `demos.damage_available`), so it appears as extracted columns above. The ammo/powerup source columns (G4) are likewise now schema-defined + populated (T6 #394: `shells`/`nails`/`rockets`/`cells` + `quad_rem`/`pent_rem`/`ring_rem` on `player_ticks` + `actor_ticks`, from the same `-view full` streams), so they too appear as extracted columns above. The [G] geometry / [R] regime / leg-phase columns (G5) are now ADDRESSED by T7 #395: `floor_height`/`over_void`/`wall_dist`/`ledge_ahead`/`ramp_normal_z` + `regime` + `leg_phase` are schema-defined on `player_ticks` + `actor_ticks` and populated by the MVD ETL, so they appear as DERIVED columns above (computed from the sha-locked dm3.bsp hull-1 traces + kinematics + the route_legs #334 segmentation — NULL where undefined, never fabricated; `leg_phase` is NULL on `actor_ticks` for want of an ego goal context). The POMDP `actor_visibility.*` layer is now ADDRESSED by T8 #396: per (episode, tick, ego-observer, target) FOV (egocentric bearing cone) + LOS (observer-eye->target-eye hull-0 raycast on the sha-locked dm3.bsp) + carried-forward belief block, populated by the MVD ETL, so they appear as DERIVED columns above. PVS is an OPTIONAL perf prefilter that is NOT sourced here (pmove_sim does not decode the BSP visdata), so `pvs_visible` is left NULL and the gate COALESCEs it to TRUE — LOS is the correctness gate (honest degrade, never a fabricated PVS boolean). The `audio_cues.*` derived layer remains the one defined-but-empty T8 gap (out of #396 scope). No per-column GAP remains absent from the schema entirely.

**Training connection (T9 #397, capstone — NOT a schema-coverage gap).** The catalog is now "structured & connected to enable training": `data/catalog/dataset_spec.yaml` (the §2.9 entities/`ent_mask`/window contract) is machine-read by the stdlib reader `ml/pipeline/dataset_spec.py` (no PyYAML); the worked consumer `ml/pipeline/assemble_obs_template.py` assembles the AMP `(s,s')` obs from the now-populated T3-T8 columns honoring the §7 PIT/as-of leakage guard (every read is <= the obs tick; the item context is an as-of join) and the §6.5 clean-movement filter (fail-closed on era-gated-unknown damage); and `ml/pipeline/normalize_fit.refit_template` refits the normalization stats TRAIN-SPLIT-ONLY (§6.2) over the richer fields (fixture-derived example at `norm/normalization_stats.refit.template.json`, the real refit being the separate gated 1537-demo run). This is a downstream consumer/template deliverable, so it adds NO schema column and changes none of the per-column verdicts above.
