-- =============================================================================
-- catalog_schema.sql - SQLite-dialect DDL for the komodobots in-tree catalog (C1)
-- Ported from research/komodobots-ml-data-architecture/schema/catalog.sql.
-- STDLIB-ONLY: loads with the sqlite3 module. No DuckDB needed.
-- The only DuckDB-specific content (an ASOF PIT example) is in a trailing comment.
-- Lands in the repo at: scripts/catalog_schema.sql
-- =============================================================================
-- =============================================================================
-- komodobots ML Data Architecture — Relational Catalog DDL
-- schema tag: komodobots.catalog.v1
-- v2 additions (4on4): actor_ticks, actor_visibility, audio_cues, teams,
--   frag_events, region_control_timeline, item_events.team_id. The 4on4 layer is
--   the FIRST target; single-agent movement (existing tables) is a sub-skill of it.
-- Target: DuckDB (preferred for analytical joins / ASOF PIT joins over Parquet)
--         also runs on SQLite 3 (the `--SQLITE` notes flag the few divergences)
-- =============================================================================
-- This is the relational SPINE. Heavy per-tick feature columns live in Parquet
-- (gold/features/*.parquet, see dataset_spec.yaml); this catalog indexes demos,
-- episodes, maps, the static nav graph, the static item catalog, the item-event
-- timeline, and the recovered (state,action) labels, for joins + grouped splits.
--
-- SUPERSEDES (formalizes existing ad-hoc artifacts from _inventory.md):
--   maps              <- komodobots.maps.v1            (lab/dashboard .../maps.json)
--   markers/nav_edges <- the ad-hoc KTX `.bot` text parse + moveprobe `route=` suffix
--   items/item_events <- NEW (mvd-mcp getItems/getWeaponPickups/getBackpacks — unused today)
--   demos             <- human_mvd_inventory.v1 + lab-run run.env provenance
--   episodes          <- continuity splits in qwd_route_probe.v1 / alignment-meta.json
--   player_ticks      <- events.txt kind:5 samples + .cmds (replay.v1) state cols
--   actions           <- qwd_usercmd.v1 (human GT) + moveprobe FBMOVEPROBE_CMD (bot intent)
--
-- UNITS (Quake conventions, carried in column comments):
--   position  = Quake units (qu)              velocity = qu/s
--   angles    = degrees (pitch,yaw,roll)      time     = seconds unless _ms
--   usercmd fwd/side/up = raw usercmd_t shorts (-400..400 typical)
--   buttons   = bitfield; jump = (buttons & 2)
--   tick rate = ~77 server frames/s (confirmed: .cmds headers fps=77.043, msec=13)
-- =============================================================================

PRAGMA foreign_keys = ON;   -- SQLITE: enforce FKs (DuckDB always treats as metadata)

-- -----------------------------------------------------------------------------
-- maps  (komodobots.maps.v1)  — one row per BSP map
-- AABB drives per-map coordinate normalization (00-DATA-ARCHITECTURE.md §Positioning)
-- -----------------------------------------------------------------------------
CREATE TABLE maps (
    map_id            INTEGER PRIMARY KEY,
    name              TEXT    NOT NULL UNIQUE,      -- 'dm3', 'dm2', 'frobodm2', 'trick'
    source_bsp        TEXT,                         -- 'dm3.bsp'
    source_bsp_sha256 TEXT,                         -- provenance lock
    -- AABB in qu (from maps.v1; dm3 = [-984,-960,-416]..[2048,1136,496])
    x_min REAL NOT NULL, x_max REAL NOT NULL,       -- qu
    y_min REAL NOT NULL, y_max REAL NOT NULL,       -- qu
    z_min REAL NOT NULL, z_max REAL NOT NULL,       -- qu
    center_x REAL, center_y REAL, center_z REAL,    -- qu (dm3 center 532,88,40)
    diagonal  REAL NOT NULL,                        -- qu; sqrt(dx^2+dy^2+dz^2) of AABB
                                                    --   dm3 = 3797.1; used to normalize all distances
    -- physics constants the trajectories were generated/replayed under (pmove_sim.py)
    maxspeed     REAL DEFAULT 320.0,                -- qu/s
    jumpspeed    REAL DEFAULT 270.0,                -- qu/s (impulse on jump)
    gravity      REAL DEFAULT 800.0,                -- qu/s^2
    friction     REAL DEFAULT 4.0,
    stopspeed    REAL DEFAULT 100.0,                -- qu/s
    accelerate   REAL DEFAULT 10.0,
    airaccel_cap REAL DEFAULT 30.0,                 -- qu/s air-accel speed cap
    server_fps   REAL DEFAULT 77.0                  -- physics frames/s
);

-- -----------------------------------------------------------------------------
-- markers  — Frogbot nav-graph nodes (supersedes ad-hoc KTX .bot CreateMarker parse)
-- e.g. dm3 marker 59 @ [1329,-378,-24] zone 17 goal 5
-- NOTE: some markers (e.g. dm3 #276) have NO static origin in .bot -> origin_* NULL.
-- -----------------------------------------------------------------------------
CREATE TABLE markers (
    map_id        INTEGER NOT NULL REFERENCES maps(map_id),
    marker_id     INTEGER NOT NULL,                 -- Frogbot marker index (per-map)
    origin_x REAL, origin_y REAL, origin_z REAL,    -- qu; NULL if no static CreateMarker origin
    zone          INTEGER,                          -- Frogbot zone id (e.g. 17)
    goal          INTEGER,                          -- goal id if this marker is a goal (e.g. 5)
    near_item_id  INTEGER REFERENCES items(item_id),-- item this marker sits on, if any (denormalized helper)
    is_teleport   BOOLEAN DEFAULT FALSE,
    is_door       BOOLEAN DEFAULT FALSE,
    PRIMARY KEY (map_id, marker_id)
);

-- -----------------------------------------------------------------------------
-- nav_edges  — directed Frogbot path edges (supersedes route_edge_geometry.v1)
-- e.g. dm3 edge 276->59 idx 0 (+ reciprocal). path_state bitflags decoded:
--   32768=WATER_PATH, 524288=STUCK_PATH (from route_state_diagnosis.v1)
-- -----------------------------------------------------------------------------
CREATE TABLE nav_edges (
    map_id        INTEGER NOT NULL REFERENCES maps(map_id),
    from_marker   INTEGER NOT NULL,                 -- references markers(marker_id) within map
    to_marker     INTEGER NOT NULL,
    edge_idx      INTEGER,                           -- Frogbot link slot index (e.g. 0)
    distance_qu   REAL,                              -- straight-line qu between marker origins (NULL if origin missing)
    path_flags    INTEGER DEFAULT 0,                 -- bitfield: 32768=WATER, 524288=STUCK, ...
    is_jump       BOOLEAN DEFAULT FALSE,             -- edge requires a jump
    is_teleport   BOOLEAN DEFAULT FALSE,
    PRIMARY KEY (map_id, from_marker, to_marker, edge_idx),
    FOREIGN KEY (map_id, from_marker) REFERENCES markers(map_id, marker_id),
    FOREIGN KEY (map_id, to_marker)   REFERENCES markers(map_id, marker_id)
);
CREATE INDEX idx_nav_edges_from ON nav_edges(map_id, from_marker);

-- -----------------------------------------------------------------------------
-- items  — STATIC item catalog. Coords from the map BSP entity lump
--   (= mvd-api getMapEntities); observed respawns from getItems phases[].
--   dm3 already populated & verified: item_catalog.dm3.json (komodobots.item_catalog.v2).
-- One row per spawned item ENTITY on a map (a map can have N RLs, N RAs, ...).
-- Static value/importance prior lives here; data-derived value lives in item_value.
-- -----------------------------------------------------------------------------
CREATE TABLE items (
    item_id          INTEGER PRIMARY KEY,
    map_id           INTEGER NOT NULL REFERENCES maps(map_id),
    classname        TEXT    NOT NULL,              -- 'item_armorInv' (RA), 'weapon_rocketlauncher', ...
    item_type        TEXT    NOT NULL,              -- canonical: 'rl','ra','ya','ga','mh','quad','pent','ring',
                                                    --   'ssg','ng','sng','gl','lg','cells','rockets','nails',
                                                    --   'shells','health25','health15'
    category         TEXT    NOT NULL,              -- 'weapon'|'armor'|'health'|'powerup'|'ammo'
    origin_x REAL NOT NULL, origin_y REAL NOT NULL, origin_z REAL NOT NULL,  -- qu (world spawn position)
    respawn_seconds  REAL,                           -- convention; observed from getItems phases[] (respawn_verified)
    static_value     REAL    NOT NULL,              -- importance prior in [0,1] (item_catalog.dm3.json)
    nearest_marker   INTEGER,                        -- markers(marker_id) for nav routing
    coords_verified  BOOLEAN DEFAULT FALSE,          -- dm3: TRUE (from BSP); other maps: fill from getMapEntities
    UNIQUE (map_id, classname, origin_x, origin_y, origin_z)
);
CREATE INDEX idx_items_map_type ON items(map_id, item_type);

-- -----------------------------------------------------------------------------
-- item_value  — DATA-DERIVED importance (komodobots.item_value.v1)
-- Populated by a fitted logistic-regression / correlation of item control vs
-- round/frag outcome (00-DATA-ARCHITECTURE.md §Resource importance model).
-- Keyed per (map, item_type) so it generalizes across the N entities of a type.
-- -----------------------------------------------------------------------------
CREATE TABLE item_value (
    map_id          INTEGER NOT NULL REFERENCES maps(map_id),
    item_type       TEXT    NOT NULL,
    method          TEXT    NOT NULL,               -- 'logreg_control_vs_round' | 'pearson_control_frags'
    coef            REAL,                            -- fitted logistic coefficient (log-odds per control-second)
    importance_norm REAL,                            -- normalized to [0,1]; replaces/augments items.static_value
    n_rounds        INTEGER,                         -- support
    dataset_version TEXT,                            -- which dataset commit it was fitted on
    fitted_on_split TEXT DEFAULT 'train',            -- MUST be train-only (leakage guard)
    PRIMARY KEY (map_id, item_type, method)
);

-- -----------------------------------------------------------------------------
-- players  — for per-player style models (Milton/carapace/yeti groundwork)
-- supersedes the player axis in player_movement_signatures.v1
-- -----------------------------------------------------------------------------
CREATE TABLE players (
    player_id     INTEGER PRIMARY KEY,
    handle        TEXT NOT NULL UNIQUE,             -- 'milton','carapace','yeti', or 'bot:frogbot'
    is_bot        BOOLEAN DEFAULT FALSE
);

-- -----------------------------------------------------------------------------
-- demos  — one row per source demo (supersedes human_mvd_inventory.v1 + run.env)
-- source distinguishes the action-label fidelity tier (see actions.label_source)
-- -----------------------------------------------------------------------------
CREATE TABLE demos (
    demo_id       INTEGER PRIMARY KEY,
    path          TEXT NOT NULL UNIQUE,             -- bronze/demos/...mvd or .qwd
    source        TEXT NOT NULL CHECK(source IN ('mvd','qwd','sim','lab_mvd')),
                                                    --   mvd=server state-only, qwd=POV w/ usercmd,
                                                    --   sim=pmove_sim rollout, lab_mvd=bot lab run
    map_id        INTEGER REFERENCES maps(map_id),
    demo_kind     TEXT,                              -- '1on1'|'2on2'|'4on4'|'tricks'|'lab'
    recorded_at   TIMESTAMP,
    duration_s    REAL,                              -- seconds (clamp source for samples)
    server_fps    REAL DEFAULT 77.0,
    sha256        TEXT NOT NULL,                     -- provenance lock
    parser_commit TEXT,                              -- qw-analyze build (drift risk: 7d83ebe vs fab7808)
    UNIQUE (sha256)
);
CREATE INDEX idx_demos_map ON demos(map_id);

-- -----------------------------------------------------------------------------
-- episodes  — a contiguous trajectory segment (continuity-split safe).
-- Grouped-split assignment lives HERE (keyed by demo_id/player_id) so no demo
-- straddles train/val/test (00-DATA-ARCHITECTURE.md §Splits).
-- -----------------------------------------------------------------------------
CREATE TABLE episodes (
    episode_id    INTEGER PRIMARY KEY,
    demo_id       INTEGER NOT NULL REFERENCES demos(demo_id),
    player_id     INTEGER REFERENCES players(player_id),
    map_id        INTEGER REFERENCES maps(map_id),
    start_tick    INTEGER NOT NULL,
    end_tick      INTEGER NOT NULL,
    n_steps       INTEGER NOT NULL,
    total_reward  REAL,                              -- for offline-RL / RTG precompute (NULL for pure BC)
    split         TEXT CHECK(split IN ('train','val','test')) NOT NULL DEFAULT 'train',
    split_policy  TEXT DEFAULT 'group_by_demo_id'    -- audit which grouping produced `split`
);
CREATE INDEX idx_episodes_demo ON episodes(demo_id);
CREATE INDEX idx_episodes_split ON episodes(split);

-- -----------------------------------------------------------------------------
-- player_ticks  — per-tick STATE (the silver row; supersedes events.txt kind:5
-- + the state cols of .cmds/replay.v1). Heavy engineered FEATURES live in Parquet;
-- this table is the canonical raw-state spine for PIT joins.
-- -----------------------------------------------------------------------------
CREATE TABLE player_ticks (
    episode_id   INTEGER NOT NULL REFERENCES episodes(episode_id),
    tick         INTEGER NOT NULL,                   -- frame index within episode
    t_s          REAL    NOT NULL,                   -- seconds since episode start (server clock)
    msec         INTEGER,                            -- frame duration ms (~13 @ 77fps); from usercmd_t.msec
    -- world state (qu / qu/s / deg) — present in MVD kind:5 + .cmds
    ox REAL NOT NULL, oy REAL NOT NULL, oz REAL NOT NULL,   -- origin qu
    vx REAL, vy REAL, vz REAL,                              -- velocity qu/s
    pitch REAL, yaw REAL, roll REAL,                        -- view angles deg
    -- derived scalars carried for convenience (also recomputable)
    hspeed REAL,                                            -- hypot(vx,vy) qu/s
    onground   BOOLEAN,                                     -- GROUND-TRUTH only for sim/.cmds; NULL for MVD
    onground_is_proxy BOOLEAN DEFAULT FALSE,                -- TRUE => derived from Z-motion proxy (MVD)
    waterlevel INTEGER,                                     -- 0..3 (sim/qwd); NULL for MVD
    -- player resource state (MVD exposes these)
    health     INTEGER,                                     -- HP
    armor      INTEGER,                                     -- AP
    armor_type INTEGER,                                     -- 0/1/2 = GA/YA/RA (absorb 0.3/0.6/0.8)
    weapon     INTEGER,                                     -- active weapon id
    PRIMARY KEY (episode_id, tick)
);
CREATE INDEX idx_ticks_t ON player_ticks(episode_id, t_s);

-- -----------------------------------------------------------------------------
-- item_events  — pickups / respawns timeline (NEW; from getWeaponPickups/getItems/
-- getBackpacks). The basis for respawn-timer features + the data-derived value model.
-- komodobots.item_events.v1
-- -----------------------------------------------------------------------------
CREATE TABLE item_events (
    event_id    INTEGER PRIMARY KEY,
    demo_id     INTEGER NOT NULL REFERENCES demos(demo_id),
    item_id     INTEGER REFERENCES items(item_id),  -- NULL if backpack/dropped (not a static spawn)
    t_s         REAL    NOT NULL,                    -- seconds (server clock, same base as player_ticks.t_s)
    event_kind  TEXT    NOT NULL CHECK(event_kind IN ('pickup','respawn','drop','backpack_pickup')),
    player_id   INTEGER REFERENCES players(player_id),  -- who picked up (NULL for respawn)
    origin_x REAL, origin_y REAL, origin_z REAL,     -- qu (for dropped backpacks not at a static origin)
    item_type   TEXT,                                -- denormalized for backpacks w/o item_id
    team_id     INTEGER REFERENCES teams(team_id)    -- v2: team attribution of the pickup
                                                     --   (from getWeaponPickups/getBackpacks); NULL if unknown/FFA
);
CREATE INDEX idx_item_events_demo_t ON item_events(demo_id, t_s);
CREATE INDEX idx_item_events_item   ON item_events(item_id, t_s);

-- -----------------------------------------------------------------------------
-- actions  — recovered (state->action) LABELS + confidence.
-- THREE fidelity tiers (label_source), per _inventory.md §8:
--   'qwd_usercmd'  : ground-truth human inputs (qwd_usercmd.v1)   confidence=1.0
--   'moveprobe'    : bot intended cmd at trap_SetBotCMD            confidence=1.0 (bot only)
--   'idm'          : inverse-dynamics recovered from state-only MVD (VPT IDM); confidence<1
--   'sim'          : ground-truth sim rollout input               confidence=1.0
-- supersedes the scattered qwd_usercmd.v1 / moveprobe-commands rows.
-- -----------------------------------------------------------------------------
CREATE TABLE actions (
    episode_id   INTEGER NOT NULL REFERENCES episodes(episode_id),
    tick         INTEGER NOT NULL,
    -- raw usercmd_t (the canonical action; matches qwd_usercmd.v1 fields)
    forwardmove  REAL,                               -- usercmd short, -400..400
    sidemove     REAL,                               -- usercmd short
    upmove       REAL,                               -- usercmd short (jump/swim)
    buttons      INTEGER,                            -- bitfield; jump=(buttons&2), attack=(buttons&1)
    impulse      INTEGER,                            -- weapon switch etc.
    cmd_yaw   REAL, cmd_pitch REAL, cmd_roll REAL,   -- commanded view angles deg (usercmd angles[3])
    -- recovery metadata
    label_source TEXT NOT NULL CHECK(label_source IN ('qwd_usercmd','moveprobe','idm','sim')),
    confidence   REAL NOT NULL DEFAULT 1.0,          -- [0,1]; IDM rows < 1.0
    align_shift  INTEGER,                            -- frame shift used to align cmd<->state (alignment-meta.json)
    is_interp    BOOLEAN DEFAULT FALSE,              -- TRUE => interpolated/anomalous, exclude from training
    PRIMARY KEY (episode_id, tick),
    FOREIGN KEY (episode_id, tick) REFERENCES player_ticks(episode_id, tick)
);
CREATE INDEX idx_actions_source ON actions(label_source);

-- -----------------------------------------------------------------------------
-- feature_partitions  — manifest of gold Parquet feature files (lineage)
-- -----------------------------------------------------------------------------
CREATE TABLE feature_partitions (
    partition_id          INTEGER PRIMARY KEY,
    map_id                INTEGER REFERENCES maps(map_id),
    dt                    DATE NOT NULL,             -- ingest partition date
    path                  TEXT NOT NULL UNIQUE,      -- gold/features/map=dm3/dt=.../part-*.parquet
    n_rows                INTEGER,
    registry_version      INTEGER,                   -- which feature_registry.yaml built it
    norm_artifact_version TEXT,                       -- which normalization_stats.json it assumes
    git_sha               TEXT                        -- code SHA at build time (reproducibility)
);

-- =============================================================================
-- v2 (4on4) — TEAM LAYER, MULTI-ACTOR WORLD-STATE, OBSERVABILITY (POMDP), AUDIO
-- These tables make the 4on4 agent first-class. `actor_ticks` is the OMNISCIENT
-- world state; `actor_visibility` is the DERIVED POMDP layer that gates what the
-- agent may actually observe. See 00-DATA-ARCHITECTURE.md §2.7–§3.7.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- teams  — one row per team per demo (4on4: 2 teams; FFA/1on1: degenerate).
-- team_id is an ABSOLUTE join/credit key ONLY; the observation always uses the
-- RELATIVE is_teammate flag, never an absolute team id (00-DATA-ARCHITECTURE §3.7).
-- From getStateAt / getOverview roster.
-- -----------------------------------------------------------------------------
CREATE TABLE teams (
    team_id   INTEGER PRIMARY KEY,
    demo_id   INTEGER NOT NULL REFERENCES demos(demo_id),
    name      TEXT,                                  -- roster team name (e.g. 'red', '-s-')
    side      TEXT                                   -- 'A'|'B' canonical side label for region_control_timeline
);
CREATE INDEX idx_teams_demo ON teams(demo_id);

-- -----------------------------------------------------------------------------
-- actor_ticks  — OMNISCIENT per-tick state for EVERY player (not just ego-self).
-- Same state cols as player_ticks; player_ticks stays the ego-self spine and
-- actor_ticks is the all-players world used to DERIVE observations. NEVER trained
-- on directly — only the POMDP-masked agent_observation is. From getStateAt
-- (all players). PK (episode_id, tick, actor_id).
-- -----------------------------------------------------------------------------
CREATE TABLE actor_ticks (
    episode_id   INTEGER NOT NULL REFERENCES episodes(episode_id),
    tick         INTEGER NOT NULL,                   -- frame index within episode
    actor_id     INTEGER NOT NULL REFERENCES players(player_id),  -- which player this row describes
    team_id      INTEGER REFERENCES teams(team_id),  -- absolute team (joins/credit only)
    alive        BOOLEAN,                            -- FALSE between death and respawn
    -- world state (qu / qu/s / deg) — mirrors player_ticks
    ox REAL, oy REAL, oz REAL,                       -- origin qu
    vx REAL, vy REAL, vz REAL,                       -- velocity qu/s (derived Delta-pos/Delta-t for MVD)
    pitch REAL, yaw REAL, roll REAL,                 -- view angles deg
    hspeed REAL,                                     -- hypot(vx,vy) qu/s
    onground   BOOLEAN,                              -- GROUND-TRUTH only for sim/.cmds; NULL for MVD
    onground_is_proxy BOOLEAN DEFAULT FALSE,         -- TRUE => derived from Z-motion proxy (MVD)
    waterlevel INTEGER,                              -- 0..3 (sim/qwd); NULL for MVD
    health     INTEGER,                              -- HP
    armor      INTEGER,                              -- AP
    armor_type INTEGER,                              -- 0/1/2 = GA/YA/RA
    weapon     INTEGER,                              -- active weapon id
    PRIMARY KEY (episode_id, tick, actor_id)
);
CREATE INDEX idx_actor_ticks_et ON actor_ticks(episode_id, tick);

-- -----------------------------------------------------------------------------
-- actor_visibility  — DERIVED POMDP layer: for each (tick, observer, target),
-- can the observer SEE the target, plus carried-forward BELIEF (memory).
-- Derivation is cheapest-first: PVS prefilter -> FOV -> raycast occlusion on
-- bsp_geom HULL 0 (line-of-sight). NOT an mvd endpoint — it is computed offline.
-- "Invisible" => is_visible=FALSE: live target fields are MASKED+ZEROED in the
-- observation while the belief block carries the last-seen memory (mirror the
-- 3-state item_unknown_flag pattern; 00-DATA-ARCHITECTURE §2.8). See §3.6.
-- -----------------------------------------------------------------------------
CREATE TABLE actor_visibility (
    episode_id   INTEGER NOT NULL REFERENCES episodes(episode_id),
    tick         INTEGER NOT NULL,
    observer_id  INTEGER NOT NULL REFERENCES players(player_id),
    target_id    INTEGER NOT NULL REFERENCES players(player_id),
    is_visible   BOOLEAN,                            -- final gate = pvs_visible AND in_fov AND los_clear
    pvs_visible  BOOLEAN,                            -- BSP visleaf PVS prefilter (cheapest)
    in_fov       BOOLEAN,                            -- target bearing within observer yaw/pitch FOV
    los_clear    BOOLEAN,                            -- raycast eye->target on hull 0 unobstructed
    vis_angle_source TEXT,                           -- OPEN DECISION: 'demoparser'|'idm_proxy'
                                                     --   observer view angles are demoparser-only;
                                                     --   state-only MVDs fall back to an IDM/angle proxy
    -- belief / memory block (carried forward when target is invisible)
    last_seen_tick   INTEGER,                        -- last tick is_visible was TRUE
    last_seen_t_s    REAL,                           -- seconds
    last_seen_ox REAL, last_seen_oy REAL, last_seen_oz REAL,  -- qu (last observed origin)
    last_seen_vx REAL, last_seen_vy REAL, last_seen_vz REAL,  -- qu/s (last observed velocity)
    time_since_seen_s REAL,                          -- seconds since last_seen_t_s (0 while visible)
    seen_ever        BOOLEAN DEFAULT FALSE,          -- has observer ever seen target this episode
    PRIMARY KEY (episode_id, tick, observer_id, target_id)
);
CREATE INDEX idx_actor_vis_et ON actor_visibility(episode_id, tick);

-- -----------------------------------------------------------------------------
-- audio_cues  — per-tick spatial sound the observer can HEAR (NOT FOV/LOS-gated;
-- sound bends around corners). src_type: 'weapon_fire'|'item_pickup'|'footstep'.
-- weapon_fire/item_pickup from getEvents (+ item_events); footstep synthesized
-- (other actor with hspeed>=run_threshold AND onground). intensity decays
-- intensity(t) = intensity0 * exp(-(t - t_emit_s)/tau_type). 00-DATA-ARCHITECTURE §3.6.
-- -----------------------------------------------------------------------------
CREATE TABLE audio_cues (
    episode_id   INTEGER NOT NULL REFERENCES episodes(episode_id),
    tick         INTEGER NOT NULL,
    observer_id  INTEGER NOT NULL REFERENCES players(player_id),
    src_type     TEXT NOT NULL,                      -- 'weapon_fire'|'item_pickup'|'footstep'
    src_x REAL, src_y REAL, src_z REAL,              -- qu (sound source world position)
    intensity0   REAL,                               -- emission intensity at t_emit_s (pre-decay)
    t_emit_s     REAL                                -- seconds the sound was emitted (decay reference)
);
CREATE INDEX idx_audio_cues_et ON audio_cues(episode_id, tick);

-- -----------------------------------------------------------------------------
-- frag_events  — kill timeline (NEW; from getFrags). Basis for team-frag reward
-- and teamkill penalty. 00-DATA-ARCHITECTURE §3.7.
-- -----------------------------------------------------------------------------
CREATE TABLE frag_events (
    event_id    INTEGER PRIMARY KEY,
    demo_id     INTEGER NOT NULL REFERENCES demos(demo_id),
    t_s         REAL    NOT NULL,                    -- seconds (server clock, same base as player_ticks.t_s)
    killer_id   INTEGER REFERENCES players(player_id),  -- NULL for environmental
    victim_id   INTEGER REFERENCES players(player_id),
    weapon      TEXT,                                -- weapon name (e.g. 'rl','lg')
    is_suicide  BOOLEAN DEFAULT FALSE,
    is_teamkill BOOLEAN DEFAULT FALSE
);
CREATE INDEX idx_frag_events_demo_t ON frag_events(demo_id, t_s);

-- -----------------------------------------------------------------------------
-- region_control_timeline  — bucketed map-region control over time (from
-- getRegionControl). Feeds region_control_frac feature + region-control-delta
-- reward. teamA/teamB are the canonical sides in teams.side. 00-DATA-ARCHITECTURE §3.7.
-- -----------------------------------------------------------------------------
CREATE TABLE region_control_timeline (
    demo_id        INTEGER NOT NULL REFERENCES demos(demo_id),
    bucket_idx     INTEGER NOT NULL,                 -- time-bucket index
    t_s            REAL,                             -- seconds at bucket start
    region_name    TEXT    NOT NULL,                 -- map region label (e.g. 'rl', 'ya', 'quad')
    teamA_control  REAL,                             -- [0,1] fraction held by side A
    teamB_control  REAL,                             -- [0,1] fraction held by side B
    contested      BOOLEAN,                          -- TRUE if neither side dominant
    PRIMARY KEY (demo_id, bucket_idx, region_name)
);
CREATE INDEX idx_region_control_demo_t ON region_control_timeline(demo_id, t_s);

-- =============================================================================
-- Example PIT (point-in-time) feature query — DuckDB ASOF JOIN, tick<=t guard.
-- For each action label at tick t, attach the LATEST item_event at-or-before t.
-- (No future leakage: only events with item_events.t_s <= label t_s are eligible.)
-- =============================================================================
-- SELECT a.episode_id, a.tick, pt.t_s, ie.item_type, ie.event_kind
-- FROM actions a
-- JOIN player_ticks pt USING (episode_id, tick)
-- ASOF LEFT JOIN item_events ie
--   ON ie.demo_id = (SELECT demo_id FROM episodes e WHERE e.episode_id=a.episode_id)
--   AND ie.t_s <= pt.t_s
-- WHERE a.is_interp = FALSE;
