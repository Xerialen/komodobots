# KomodoBots — ML Data Architecture & Feature Template

**Schema tag namespace:** `komodobots.*` · **Target maps:** dm3 (primary), dm2
**Grounded in:** [`_inventory.md`](_inventory.md) (the real substrate) and
[`_external-research.md`](_external-research.md) (formats/formulas). Companion
machine-readable schemas live in [`schema/`](schema/).

> **North-star / scope:** *4on4 believability is the FIRST target.* The team layer,
> observability (POMDP), and multi-actor entity representation are first-class and
> in-scope from day one. Single-agent movement (§§2–9, build steps 1–9) is a *sub-skill*
> trained within the 4on4 agent, not a separate earlier project. The v2 schema additions
> (`teams`, `actor_ticks`, `actor_visibility`, `audio_cues`, `frag_events`,
> `region_control_timeline`, the `entity_observation`/`audio`/`team` feature groups, and
> the `entities`/`ent_mask`/`audio`/`team` tensors) exist to make the 4on4 goal reachable.

This is the **engineering substrate**: the databases, files, schemas, feature
definitions, item value/timing/position tables, and normalization calculations
from which a model is trained reproducibly and the *same* transforms are applied
at inference. It is not a principles document.

---

## 1. Design overview — the layered store

A medallion store (raw -> curated -> feature -> training-ready), each layer in
the format matching its access pattern. This **supersedes today's scattered
state**: per-run JSON spread across `artifacts/<run-id>/` + `experiments/*/evidence/`,
NDJSON streams (`events.txt`, qwd_usercmd output, moveprobe logs), `.cmds`
(space-delimited text) and `trace.csv` — with **no SQLite/Parquet/DuckDB, no
fitted scaler, no consolidated (state,action) table** anywhere (`_inventory.md` §9–10).

For the 4on4 target the store also carries an explicit **world-state vs
agent-observation** split, realized as a new gold derivation stage between silver and
the feature build. The OMNISCIENT all-player world (`actor_ticks`, and the derived
`actor_visibility` / `audio_cues`) lives in silver/gold and is **never trained on
directly**; only the **POMDP-masked `agent_observation`** — what a given observer could
actually perceive at tick t — feeds the model (§2.8).

```
qwbot-data/
  bronze/                                   # raw, append-only system-of-record
    demos/map=dm3/dt=YYYY-MM-DD/*.mvd|*.qwd  # the demos themselves
    events_raw/map=dm3/dt=.../*.jsonl        # raw parsed per-tick events (was events.txt kind:5)
  silver/                                   # cleaned, conformed, deduped
    player_ticks/map=dm3/dt=.../*.parquet    # one row per (episode_id, tick) — catalog.sql spine
    actor_ticks/map=dm3/dt=.../*.parquet     # v2: omniscient ALL-player state (NOT trained on)
    item_events/map=dm3/dt=.../*.parquet     # pickups/respawns (NEW)
    # v2 derived: actor_visibility, audio_cues (POMDP mask + audio; silver/gold)
  gold/
    features/agent_features/map=dm3/dt=.../*.parquet   # PIT feature tables (DuckDB, zstd)
    observations/                            # v2: the world-state vs agent-observation split
      world_state/map=dm3/dt=.../*.parquet     # omniscient (actor_ticks join); NOT trained on
      agent_observation/map=dm3/dt=.../*.parquet  # POMDP-masked per (tick,observer) — the ONLY training input
    training/
      imitation/train/shard-{000000..NNNNNN}.tar        # WebDataset windowed sequences
      imitation/val/shard-{000000..NNNNNN}.tar
      rl/episodes.hdf5                                   # Minari-style offline-RL store
    norm/normalization_stats.json            # frozen stats artifact (§7)
    registry/feature_registry.json           # feature declarations
  catalog.duckdb                            # relational catalog (schema/catalog.sql)
  dvc.yaml + *.dvc                          # data versioning
```

**Storage tech choices.**
- **Relational catalog: DuckDB** (a `catalog.duckdb`), with SQLite as a drop-in
  fallback (the DDL runs on both). DuckDB does columnar/vectorized OLAP, reads
  Parquet footers with predicate pushdown + column projection, and supports
  `ASOF JOIN` for point-in-time joins — exactly the leakage guard the imitation
  track needs. Heavy per-tick features live in **Parquet** (partitioned
  `map=<name>/dt=<date>`, zstd), not in the catalog.
- **Training tensors: WebDataset** sharded tars (~256 MB/shard, ≥10× reader
  hosts, two-level shuffle) for the imitation track; **HDF5 (Minari layout)**
  for the offline-RL episode store.
- **Frozen stats: a hand-rolled versioned JSON** (`normalization_stats.json`) —
  language-agnostic so a C/Go ezQuake-side bot can apply identical normalization
  at inference. (A joblib pickle of an sklearn Pipeline is the Python-only
  alternative; JSON wins for cross-language parity.)

**Migration note (concrete, today -> this).**

| Today (`_inventory.md`) | Becomes |
|---|---|
| `maps.json` (`maps.v1`) | `maps` table (AABB, diagonal, physics constants) |
| KTX `.bot` `CreateMarker` text + moveprobe `route=` suffix | `markers` + `nav_edges` tables |
| `events.txt` kind:5 origin samples + `.cmds` state cols | `player_ticks` table / `silver/player_ticks/*.parquet` |
| `qwd_usercmd.v1` (human GT) + `FBMOVEPROBE_CMD` (bot intent) | `actions` table (with `label_source`, `confidence`) |
| `human_mvd_inventory.v1` + lab-run `run.env` | `demos` table |
| continuity splits (`qwd_route_probe.v1`) / `alignment-meta.json` | `episodes` table (+ `align_shift` on `actions`) |
| `dm3.bsp` entity lump (= `getMapEntities`) + `getItems`/`getWeaponPickups` | `items` (coords DONE), `item_value`, `item_events` |
| `movement_metrics.v2` scalars | per-tick features in `feature_registry.json` (`hspeed_norm`, `jump_cadence_norm`, …) |
| cadence re-normalization (`cadence_normalization_decision.v1`) | replaced by the fitted `normalization_stats.json` |
| `.cmds` (`replay.v1`) | the canonical training row: `player_ticks` ⨝ `actions` (still emittable as `.cmds` for `pmove_sim`) |

The `.cmds`/`replay.v1` open-loop format stays as the **sim input format**
(`pmove_sim.py` consumes it); the architecture just stops it being the *only*
table.

---

## 1b. Data sources & provenance (verified 2026-06-18)

Where each layer's data actually comes from — confirmed by reading the source
trees, not assumed. Three independent parsers feed this architecture; do not
conflate them (this mapping resolves a real attribution confusion):

| Layer / table | Authoritative source | Notes |
|---|---|---|
| `items` world coords (`origin`) | **`dm3.bsp` entity lump** = mvd-api `getMapEntities` (Go, `result/`) | Static, no demo, no hub. All 51 dm3 origins verified. |
| `items` observed respawn intervals | mvd_analyzer **`getItems`** → `ItemTimeline.phases[] {takenAt, respawnAt}` (ms) | Needs a loaded demo. MH respawn is dynamic. |
| `item_events` (pickups/drops/backpacks) | mvd_analyzer **`getWeaponPickups`** + **`getBackpacks`** (origin, entNum, kills) | Go backend; per-demo. |
| `player_ticks` state (origin, hp/armor/weapon, loc/region) | mvd_analyzer (**state-only** — `getStateAt`/`getStreamSlice`/`getLocGraph`/`getLocTable`) | **No velocity/angles/inputs** — velocity is derived Δpos/Δt. |
| `markers` / `nav_edges` | KTX `.bot` `CreateMarker` + `getLocGraph` adjacency | Frogbot graph. |
| `actions` — dense human inputs (`label_source='qwd_usercmd'`) | **KomodoBots' own** `tools/qwd_usercmd/qwd_usercmd.py` (parses the ezQuake QWD `dem_cmd` usercmd struct → fwd/side/up/buttons/angles) | NOT demoparser/mvd_analyzer — those don't read QWD at all. This is the only dense-input ground truth. |
| `actions` — partial MVD buttons | **demoparser** (Rust) — KTX hidden usercmd block | Only `forward/side/buttons/impulse`, only on shoot/weapon-switch frames; `upmove`/`msec`/angles discarded. Sparse — not a substitute for QWD. |
| `actions` — recovered (`label_source='idm'`) | IDM over state-only MVD (§5.3) | `confidence < 1.0`. |
| `actor_ticks` (v2; all-player omniscient state) | mvd_analyzer **`getStateAt`** (all players) | Same state cols as `player_ticks`, one row per actor. Drives observation derivation. |
| `teams` (v2) | `getStateAt` / **`getOverview`** roster | 4on4 = 2 teams. Absolute id for joins/credit only. |
| `frag_events` (v2) | mvd_analyzer **`getFrags`** | Team-frag reward + teamkill penalty. |
| `region_control_timeline` (v2) | mvd_analyzer **`getRegionControl`** | Bucketed region control over time. |
| `audio_cues` (v2) | **`getEvents`** (weapon fire / pickup) + **synthesized footsteps** | NOT FOV/LOS-gated. |
| `actor_visibility` (v2) | **DERIVED** — PVS→FOV→raycast on `bsp_geom` hull 0 | NOT an endpoint; computed offline (§2.8, §9 step 11). |

**Net reality:** MVD → state-rich, action-poor; QWD → dense inputs but only via
KomodoBots' own parser; mvd_analyzer and demoparser are fully independent (zero
cross-refs). Full field-by-field mapping in [`_source-schemas.md`](_source-schemas.md).

---

## 2. The positioning system

Map geometry and agent position, encoded for ML. dm3 AABB (from `maps.v1`,
authoritative): `mins [-984,-960,-416]`, `maxs [2048,1136,496]`, `center
[532,88,40]`, so the **AABB diagonal** is
`sqrt(3032² + 2096² + 912²) = sqrt(9193024 + 4393216 + 831744) = sqrt(14417984) ≈ 3797.1 qu`
(used to normalize every distance).

### 2.1 Normalized world coordinates (auxiliary)
Raw qu are in the thousands and destabilize training. Per-map min-max against
AABB bounds:
```
pos_x_norm = (ox - x_min) / (x_max - x_min)      # dm3: (ox + 984) / 3032   -> [0,1]
pos_y_norm = (oy - y_min) / (y_max - y_min)      # dm3: (oy + 960) / 2096
pos_z_norm = (oz - z_min) / (z_max - z_min)      # dm3: (oz + 416) / 912
```
Absolute position generalizes poorly across maps, so it is **auxiliary**; the
primary spatial signal is egocentric.

### 2.2 Egocentric relative vectors (agent's own frame)
Each entity's position relative to the agent, rotated into the agent's facing
frame `φ = yaw` (radians):
```
d_world = p_entity - p_agent                          # world-frame offset (qu)
dx_ego  =  cos(φ)*d_world.x + sin(φ)*d_world.y
dy_ego  = -sin(φ)*d_world.x + cos(φ)*d_world.y
```
Translation- and rotation-invariant: "RL 600 qu ahead-left" looks identical
regardless of map location or facing.

### 2.3 Polar distance + bearing as (sin, cos)
```
dist  = sqrt(dx_ego² + dy_ego²)
theta = atan2(dy_ego, dx_ego)
feature = [ dist / map_diagonal , sin(theta) , cos(theta) ]    # 3 numbers
```
Bearing is **never a raw angle**: an angle wraps (`α ≡ α + 2π`), giving a false
discontinuity where 1° and 359° look maximally far apart. `(sin, cos)` maps onto
the unit circle so nearby angles stay nearby (benchmark gap is large: cube-rotation
MSE 6.53 / 92% acc@5° for (cos,sin) vs 1057.69 / 20.5% for raw angle). Apply to
**every** periodic quantity: `yaw_sincos`, `pitch_sincos`, `vel_heading_sincos`,
`look_vs_move_sincos`, `item_bearing_sincos`, `spawn_phase_sincos`,
`cmd_delta_yaw_sincos`.

### 2.4 The Frogbot nav graph as structured tables
The ad-hoc KTX `.bot` text (read at runtime only via the moveprobe `route=`
suffix today) becomes two queryable tables (`schema/catalog.sql`):

- **`markers`** — `(map_id, marker_id, origin_x/y/z, zone, goal, near_item_id,
  is_teleport, is_door)`. Example real row: dm3 marker **59** at
  `[1329, -378, -24]`, zone 17, goal 5. Markers with no static origin
  (e.g. dm3 #276) get `origin_* = NULL` — a documented gap, not a guess.
- **`nav_edges`** — `(map_id, from_marker, to_marker, edge_idx, distance_qu,
  path_flags, is_jump, is_teleport)`. Example: dm3 edge **276→59 idx 0** (+ its
  reciprocal). `path_flags` decodes the runtime bitfield (`32768=WATER_PATH`,
  `524288=STUCK_PATH`, from `route_state_diagnosis.v1`).

Derived position features off the graph: `nearest_marker_dist_norm`
(= `min_dist(origin, markers.origin)/diagonal`), `time_to_reach_navgraph_norm`
(graph path length / speed; §4), and zone/region membership.

### 2.5 Void / floor features
From `trace.csv`: `over_void` (0/1, no floor below), `height_above_floor` (qu,
robust-scaled), `floor_z`. These carry the dm3 pit/ledge geometry the routes
(`hilljump`, `sng_to_rl`) depend on.

### 2.6 Optional spatial planes
For a CNN branch, an egocentric multi-channel occupancy/distance-field stack
(`[walls, items, last-known-enemy-decay, self]`, `C×H×W`) precomputed and stored
as Zarr/HDF5. Optional — the entity-vector route (§ resource system) is the
cheaper primary path. Not required for v1.

### 2.7 Multi-actor world-state (4on4 prereq)
`player_ticks` stays the **ego-self** spine. For 4on4 we add `actor_ticks`
(`schema/catalog.sql`): one row per `(episode_id, tick, actor_id)` carrying the **same
state columns** as `player_ticks` (`ox/oy/oz, vx/vy/vz, pitch/yaw/roll, hspeed,
onground(+proxy), waterlevel, health, armor, armor_type, weapon`) plus `team_id` and
`alive`, sourced from `getStateAt` over **all** players. This is the OMNISCIENT world —
the substrate from which observations are DERIVED. It is never an observation itself.

### 2.8 Observability / POMDP layer (the headline 4on4 gap)
**Problem.** A server MVD records every player's exact state at every tick. Train a model
on that raw omniscient world and you get a wallhack/aimbot — it tracks enemies through
walls and across the map. That is non-human and fails the believability north-star.

**Split.** Store the omniscient **world_state** (`actor_ticks`) but train only on a
POMDP-masked **`agent_observation`**, derived per `(tick, observer)` as a new gold stage.
The mask comes from `actor_visibility` (`schema/catalog.sql`).

**Visibility derivation — cheapest-first** (each stage gates the next):
1. **PVS prefilter** — BSP visleaf potentially-visible-set lookup for observer/target
   leaves (`pvs_visible`). Cheap, eliminates most far/occluded pairs.
2. **FOV** — target bearing vs observer yaw/pitch within the view cone (`in_fov`).
3. **Raycast occlusion** — eye→target line trace on the BSP **hull 0** (`los_clear`).

`is_visible = pvs_visible AND in_fov AND los_clear`.

**Belief / memory.** When a target goes invisible the observer keeps a carried-forward
belief: `last_seen_{tick,t_s,ox,oy,oz,vx,vy,vz}`, `time_since_seen_s`, `seen_ever`.

**Invisible ≠ sentinel.** An invisible entity is encoded as a **mask bit
(`entity_is_visible=0`) + ZEROED live fields** while the **belief block carries memory** —
never a magic number in a coordinate channel. This mirrors the 3-state
`item_unknown_flag` pattern (§3.3): mask + zero + separate memory, not a poisoned scalar.

**Consequence for windowing.** Under POMDP the DT/sequence window (§5.2, K=64) flips from
optional to **REQUIRED** — a single masked frame is genuinely partial, so the model needs
the temporal context, and we add the hand-engineered belief features so even the BC
baseline isn't blind to memory.

**Open decision (NOT resolved here).** The FOV stage needs the observer's **view angles**,
which are demoparser-only (absent from the mvd_analyzer state stream). For state-only MVDs
FOV must fall back to an **IDM/angle proxy**. Record which was used in
`actor_visibility.vis_angle_source` (`'demoparser'` vs `'idm_proxy'`).

**Status (POPULATED — T8 #396).** `actor_visibility` is now derived + populated by the MVD ETL
(`scripts/catalog_etl_mvd.py`), per (episode, tick, ego-observer, target):
- **FOV** (`in_fov`) reuses `scripts/features/egocentric.py` (`rel_bearing_deg`/`rel_pitch_deg`); the
  awareness cone is a generous **90° forward-hemisphere** half-angle (a named constant, owner-tunable
  to the render-tight 45°) — LOS is the real gate, FOV only removes targets behind the observer.
- **LOS** (`los_clear`) is a **hull-0 point ray** observer-eye→target-eye (both lifted the QW view
  height **22 qu** above origin), via `pmove_sim._recursive_hull_check` against the sha-locked
  `dm3.bsp`; clear iff the segment never enters solid.
- **PVS honesty caveat.** `pmove_sim.WorldModel` parses BSP leafs/contents but **not** the
  visdata/PVS clusters, so a true visleaf PVS prefilter is not sourced. `pvs_visible` is left **NULL**
  (“not prefiltered”) — an optional perf optimisation, **never a fabricated boolean** — and the gate
  is `is_visible = COALESCE(pvs_visible, TRUE) AND in_fov AND los_clear`. LOS is the correctness gate.
- **Belief** (`last_seen_*`, `time_since_seen_s`, `seen_ever`) carries the last-seen snapshot forward
  while invisible (0 while visible, NULL before ever seen). `vis_angle_source = 'demoparser'` (the
  schema-33 corpus carries real per-tick view yaw/pitch, so the `idm_proxy` fallback is not used).
This layer also drives the §6.5 clean-movement filter (`tick_is_clean`): only enemies WITH
line-of-sight count as active-combat proximity, and the filter is fail-closed on era-gated-unknown
damage. The remaining defined-but-empty POMDP layer is `audio_cues` (a separate T8 derivation).

### 2.9 Entity representation (opponents + teammates)
The `entity_observation` feature group (`schema/feature_registry.json`) encodes a
**variable-length list of OTHER actors**, each as a fixed-width **egocentric** vector
relative to the observer (reusing the §2.2 rotate + §2.3 sin/cos machinery): `rel_dist_norm`,
`rel_bearing_sincos`, `rel_pitch_sincos`, `rel_vel_{x,y,z}` (zscore, reusing the per-map
velocity stats), `health_est_norm` (/250), `armor_est_norm` (/200), `armor_type_onehot[3]`,
`weapon_onehot[8]`, powerup presence + remaining, `is_teammate` (RELATIVE flag), `is_visible`
mask, `seen_ever`, `time_since_seen_log`, and a last-seen relative belief block. Live `_est`
fields are **zeroed when invisible**; the belief block carries memory.

The variable count is handled by a **DeepSets or small transformer head with a pad-mask —
NOT fixed sorted slots** — so the representation is permutation-invariant and side-invariant.
`N_max = 7` (4on4 = 7 other actors); **1v1 is the same code path with more masking**.
Cross-ref the `entities` / `ent_mask` tensors in **`data/catalog/dataset_spec.yaml`**
(`record_layout` keys + `entity_max.N_max`), now machine-read by the stdlib reader
`ml/pipeline/dataset_spec.py` (T9 #397). The worked consumer that assembles this obs from
the populated catalog — leakage-safe (§7) + clean-movement-gated (§6.5) — is
`ml/pipeline/assemble_obs_template.py`.

---

## 3. The resource (item) system

Not yet wired into komodobots' active pipeline (`getItems`/`getWeaponPickups`/
`getBackpacks` had zero grep hits), but the **static layout is now captured** —
see §"Data sources" and the v2 item catalog below.

### 3.1 Item catalog (static) — POPULATED (verified 2026-06-18)
`items` table + [`schema/item_catalog.dm3.json`](schema/item_catalog.dm3.json)
(`komodobots.item_catalog.v2`): one row per spawned entity — `classname`,
`item_type` (rl/ra/ya/mh/quad/pent/ring/…), `category`
(weapon/armor/health/powerup/ammo), world `origin [x,y,z]` (qu), `spawnflags`,
`respawn_seconds`, `static_value` prior. **All 51 dm3 origins are now verified**
(`coords_verified:true`), parsed directly from the `dm3.bsp` entity lump
(BSP v29 `LUMP_ENTITIES`, sha256 `e6df9e9f…` — identical to what mvd-api
`getMapEntities` reads, no demo/hub needed). Real dm3 facts that corrected the
earlier placeholders: **no green armor** (`item_armor1` absent); 1× RA
`[256,-704,304]`, 1× YA `[1232,-904,-48]`, RL `[1520,496,-112]`; **3× megahealth**;
**Quad + Pent + Ring all present**; weapons RL/LG/GL/SNG/NG/SSG ×1. Only
`respawn_seconds` remains convention-based (`respawn_verified:false`) — observed
intervals come from `getItems` `phases[]` on a demo.

### 3.2 Item-event timeline
`item_events` table (`komodobots.item_events.v1`): one row per pickup/respawn/
drop/backpack — `(demo_id, item_id, t_s, event_kind, player_id, item_type)`.
Populated from `getWeaponPickups`/`getItems`/`getBackpacks`. This is the basis
for both respawn-timer features and the data-derived value model.

### 3.3 Respawn-timer features (per item type)
For each tracked item, `respawn_at = t_last_pickup + T` (T = `respawn_seconds`):
```
t_remaining    = max(0, respawn_at - t_now)
remaining_norm = t_remaining / T                 # [0,1]; 0 = available now (divide_period)
available_now  = 1.0 if t_remaining == 0 else 0.0
unknown_flag   = 1.0 if respawn_at unobserved else 0.0   # 3rd state, NOT a sentinel number
```
Megahealth respawn is **dynamic** (timer starts after decay, not pickup) — flag
its `eta` as approximate (`item_catalog.dm3.json` notes this).

### 3.4 ETA / contest features
```
eta            = dist_to_item / max(hspeed, eps)            # seconds to arrive
eta_norm       = min(eta, CAP) / CAP                        # CAP = 10 s
up_on_arrival  = 1.0 if eta >= t_remaining else 0.0         # the core item-contest decision
slack          = (eta - t_remaining) / T                    # signed magnitude
```
`up_on_arrival` directly encodes the timing decision a QW player makes constantly.

### 3.5 Item importance / value model

**(a) Static prior** — `items.static_value` in [0,1], the prior table in
`item_catalog.dm3.json`: RL 1.00 (most map-controlling; every dm3 route
terminates at it), Quad 0.95, RA 0.92, Pent 0.88, MH 0.80, YA 0.78, Ring 0.70,
LG 0.55 … ammo/small-health lowest. (No GA on dm3.) These are well-established QW
priors; coords are now verified, only `respawn_seconds` stays convention-based.

**(b) Data-derived** — `item_value` table. Fit a **logistic regression** of
per-team item-control over a window vs round/frag outcome:
```
P(round_won) = sigmoid( Σ_i  β_i · control_seconds_i  +  b )
```
where `control_seconds_i` = seconds team held item-type `i` available-or-recently-
picked (from `item_events`), and the label = round/frag-window outcome
(`analysis.json` frags). `importance_norm` = normalized `β_i`. **Fit on the
train split only** (leakage guard; `item_value.fitted_on_split='train'`). A
simpler first cut is `pearson(control_time_i, frag_diff)`. The fitted importance
overrides the static prior in `item_value_prior` once enough rounds exist.

### 3.6 Audio-cue features (v2)
QW players act on sound constantly — a rocket fired around a corner, an armor pickup, an
enemy's footsteps. `audio_cues` (`schema/catalog.sql`) is a per-tick table of what the
observer can **hear**, aggregated into the `audio` feature group. Sources:
- **weapon fire** — `getEvents`,
- **item/armor pickup** — `getEvents` / `item_events`,
- **footsteps** — *synthesized*: other actors with `hspeed ≥ run_threshold` AND onground.

Crucially audio is **NOT FOV/LOS-gated** (sound bends around corners — that is the whole
point of hearing). Each type is encoded as `[intensity_norm, dir_sin, dir_cos]` with
distance/time decay `intensity(t) = intensity0 · exp(-(t − t_emit)/τ_type)` (`τ_type` left
as a named per-type parameter, no fitted value yet). Direction is egocentric, like every
other bearing.

### 3.7 Team layer (in scope — 4on4-first)
The 4on4 target makes the team layer first-class, not an afterthought.

**Schema** (`schema/catalog.sql`): `teams` (one row per team per demo), `team_id` added to
`item_events`, plus `frag_events` (from `getFrags`) and `region_control_timeline` (from
`getRegionControl`).

**Features** (`team` group): own-team centroid egocentric (`team_centroid_rel_*`);
**enemy-team centroid gated behind "seen recently"** → zeroed otherwise (no wallhack);
`team_spread_norm` (robust); `region_control_frac ∈ [0,1]`; team item economy
(`team_rl_control`/`team_quad_control` from `item_events.team_id` — RL/Quad control); and a
soft role vector (`player_role_soft`, runner/anchor) in the `player_style` group.

**Reward** (`schema/dataset_spec.yaml`): + team frag (non-teamkill) / − teamkill / +
region-control delta / + team item-control, with **difference rewards** (per-actor marginal
contribution) for credit assignment; RTG precomputed **per-actor** over the team-augmented
reward.

**Team identity is ALWAYS relative** (`is_teammate`); the absolute `team_id` exists in the
catalog only for joins and credit assignment and **never enters the observation**.

---

## 4. The timing system

- **Game/match clock:** `match_progress = t_elapsed / match_duration` ∈ [0,1];
  `time_remaining` mirror. For overtime use min-max vs an expected cap + an
  `overtime` flag rather than dividing by an unknown denominator.
- **Time-since-event** (last pickup/frag/damage): heavy-tailed, so
  `time_since_pickup_log = log1p(t_now - t_last)`, then z-score
  (`log1p_zscore`); plus a `seen_recently` flag.
- **Cyclic encodings:** periodic respawn phase `spawn_phase_sincos =
  [sin(2π·(t mod T)/T), cos(2π·(t mod T)/T)]` — both components, because sine
  alone is symmetric (two phases share a value); the pair gives a unique point
  per phase and makes the wrap point correctly close.
- **Time-to-reach via nav graph:** `time_to_reach_navgraph_norm =
  min(navgraph_path_len(cur_marker, goal_marker)/max(hspeed,eps), CAP)/CAP` —
  graph distance over `nav_edges`, not straight-line.

---

## 5. The (state, action) dataset

### 5.1 Canonical training row
The existing `.cmds`/`replay.v1` row
(`msec ox oy oz vx vy vz pitch yaw roll fwd side up buttons`) is **split into two
catalog tables** joined on `(episode_id, tick)`:
- **`player_ticks`** — state: `t_s, msec, ox/oy/oz, vx/vy/vz, pitch/yaw/roll,
  hspeed, onground(+onground_is_proxy), waterlevel, health, armor, armor_type, weapon`.
- **`actions`** — label: `forwardmove, sidemove, upmove, buttons, impulse,
  cmd_yaw/pitch/roll`, plus `label_source ∈ {qwd_usercmd, moveprobe, idm, sim}`,
  `confidence`, `align_shift`, `is_interp`.

The fused view *is* still emittable as a `.cmds` file for `pmove_sim.py`.

### 5.2 Sequence/window construction
Per `schema/dataset_spec.yaml`: slide a **K=64-tick** window (≈0.83 s @77 fps),
**stride 16** (75% overlap), never crossing an `episode` boundary
(`is_first/is_last/is_terminal` flags). Trailing windows are **padded to K** with
an attention/loss `mask`. Two products from the same windows:
- **Plain (obs, action)** rows (`bc_window:1`) for behavioral cloning.
- **Decision-Transformer** triples `(R̂_t, s_t, a_t)` where return-to-go
  `R̂_t = Σ_{t'=t}^{T} r_{t'}` is **precomputed over the full episode before
  windowing**; context = last K steps → 3K tokens, with a timestep embedding
  added to all three tokens of a step. RTG conditioning lets a target return at
  inference act as a goal — and a *player-id / style token* can condition on a
  specific player's style (the Milton groundwork).

### 5.3 Inverse-dynamics action recovery (the label-less MVD problem)
Server MVDs record **state, not inputs** (`_inventory.md` §1a): position,
velocity, angles, health, items, frags — but no `forwardmove/sidemove/upmove/
buttons`. So most human reference data (incl. all Milton 4on4) has **no action
labels**. Plan (VPT IDM pattern):
1. **Labeled subset** where actions *are* known: QWD POV demos
   (`qwd_usercmd.v1`, exact human inputs) + `pmove_sim` rollouts (ground-truth
   inputs) + bot moveprobe logs.
2. **Train a non-causal inverse-dynamics model** (IDM) that predicts the
   action at tick t from a window of state around t (t−k … t+k) — inverting QW
   pmove is far easier and more data-efficient than modeling behavior.
3. **Pseudo-label** the state-only MVD corpus by running the IDM over it →
   `actions` rows with `label_source='idm'`, `confidence < 1.0`.
4. **Train BC/DT** on the union, **weighting the loss by `actions.confidence`**
   so fragile IDM labels count less.

This formalizes today's "inverse-control / open-loop replay" framing into a
recovery pipeline that produces real `actions` rows, with `divergence_qu` /
`first_divergence_frame` (from `pmove_sim` replay) as the IDM validation metric.

---

## 6. Normalization calculations

### 6.1 Per-feature method selection
| Feature type | Method | Examples |
|---|---|---|
| Roughly Gaussian continuous | **z-score** `(x-μ)/σ` | `vel_x/y/z` |
| Bounded / known range, no outliers | **min-max** `(x-min)/(max-min)` | `pos_*_norm` (AABB) |
| Heavy outliers / fat tails | **robust** `(x-median)/IQR` | `hspeed`, `jump_cadence`, `height_above_floor`, `rtg` |
| Right-skewed durations | **log1p → z-score** | `time_since_pickup` |
| Cyclic / angles | **sin/cos pair** | all `*_sincos`, `spawn_phase` |
| Already-bounded ratios / timers | **divide_period** (constant) | `health/250`, `armor/200`, `*_remaining/T`, `fwd/400` |
| Binary flags / one-hot | **identity** | `available_now`, `over_void`, `armor_type_onehot` |

Math (radians for angles; z-score uses biased std, ddof=0, to match sklearn):
```
z-score : z = (x - μ) / σ
min-max : x' = (x - min) / (max - min)
robust  : x' = (x - median) / IQR ,  IQR = P75 - P25
log1p   : x' = ln(1 + x)            (then z-score)
sincos  : [sin(θ), cos(θ)]
divide  : x' = x / period
```
Order: transform (fix shape, e.g. log1p) **first**, then scale.

### 6.2 Computed from TRAIN SPLIT ONLY, frozen, reapplied identically
μ/σ/min/max/median/IQR are computed from `episodes.split='train'` rows **only**,
frozen into `normalization_stats.json`, and reapplied byte-identically at
val/test/inference. Fitting on all data leaks the test distribution into the
scaler (offline scores inflate, production mismatches). Min-max bounds for
positions are an exception — they come from the authoritative AABB, not fitted.

### 6.3 Welford (online) + Chan (parallel) — streaming over shards
Feature tables exceed RAM, so accumulate in one pass per shard, then merge:
```
# Welford, per shard:
count, mean, M2 = 0, 0, 0
for x in shard:
    count += 1
    delta  = x - mean
    mean  += delta / count
    delta2 = x - mean              # uses UPDATED mean
    M2    += delta * delta2
var = M2 / count                   # population (ddof=0); /(count-1) for sample
std = sqrt(var)

# Chan merge of two partials A,B (associative -> tree-reduce all shards):
n_AB   = n_A + n_B
δ      = mean_B - mean_A
mean_AB = mean_A + δ * (n_B / n_AB)
M2_AB   = M2_A + M2_B + δ² * (n_A * n_B / n_AB)
var_AB  = M2_AB / n_AB
```
Median/IQR (robust) need a streaming quantile sketch (e.g. t-digest) or a second
pass over train shards.

### 6.4 Per-map vs global
**Per-map** for spatial/velocity/speed features (map bounds and item geometry
genuinely differ — a fast map inflates all movement features); **global** for
behavioral/style features (`jump_cadence`, `time_since_pickup`, `rtg`) with
`map_id` carried as a feature. `normalization_stats.json` has both a `global`
block and a `per_map.<map>` block; each feature's `stats_key` in
`feature_registry.json` routes to the right one.

### 6.5 Versioned artifact
`normalization_stats.json` records `artifact_version`, `registry_version`,
`fitted_on`, `split_def`, `n_samples`, `dataset_version`, `git_sha`, and per
feature `{method, params, computed_from:{split,n,dataset_version}, clip}`.
`clip` is applied before the transform. The model card pins
`(git_sha, dvc_hash, artifact_version, registry_version)`; an incompatible
scaler/model pair must refuse to deploy together (enforced by
`feature_partitions.norm_artifact_version`).

### 6.6 Normalization corrections (v2 — vs the Gemini draft)
- **dm3 bounds are asymmetric — Gemini's blanket ±2048 min-max is WRONG.** The verified
  dm3 AABB is `x∈[-984,2048]`, `y∈[-960,1136]`, `z∈[-416,496]` (from `maps.v1`). Keep the
  per-axis AABB + egocentric features + per-feature normalization; do **not** symmetrize.
- **Weapon one-hot** is pinned `float32[8]` over `{axe,sg,ssg,ng,sng,gl,rl,lg}` (self and
  entity); **armor type** is the existing 3-state one-hot.
- **Self ammo per weapon-class** `sh/nl/rk/cl` use `divide_period` caps (placeholders in the
  template; confirm against KTX max ammo).
- **Powerup remaining** (quad/60, pent/300, ring/60) is reused for BOTH self and entities —
  always presence-bit + remaining, never a sentinel.
- **New stats keys:** `global.time_since_seen` (`log1p_zscore`, clip `[0,300]`);
  `global.audio_intensity` (robust); `global.team_spread` (robust); entity `rel_vel` reuses
  the existing `per_map.<map>.vel_*` zscore; entity `rel_dist` is identity-after-/diagonal
  (no fitted key). All train-split-only, Welford/Chan, frozen + versioned.

---

## 7. Splits, leakage, versioning, validation

- **Grouped splits:** `GroupKFold` / `GroupShuffleSplit` keyed by `demo_id` — no
  demo straddles train/test (consecutive ticks are near-duplicates; per-tick
  splitting leaks). Assigned at the `episodes` level (`episodes.split`).
- **Held-out generalization:** reserve whole **players** (`milton`) for a
  style-generalization test, and optionally a whole **map** for layout
  generalization.
- **Leakage controls:** (1) fit transformers on train only (§6.2); (2) grouped
  splits; (3) **PIT/as-of joins** (DuckDB `ASOF JOIN`, `tick ≤ t`) when mining
  imitation labels so every feature uses only state at tick ≤ t —
  `feature_registry.json` marks each feature `leakage_safe`; (4) exclude
  post-outcome / `role: target|conditioning|weight` features from observations.
  The **worked, dependency-light** instance of (1)+(3) is T9 #397:
  `ml/pipeline/assemble_obs_template.py` reads per-tick state on the EXACT tick (PK
  `(episode_id, tick)`) and attaches event context via a stdlib as-of join
  (`asof_latest_leq`, latest `item_events` row at-or-before the obs time, never `> t`).
  Because `player_ticks.t_s` is **episode-relative** but `item_events.t_s` / `damage_events.t_s`
  are **absolute demo-time**, the tick is first mapped onto the absolute clock via
  `episodes.start_t_s` (`abs_t_s = start_t_s + t_s`) and the as-of cut + the §6.5 damage-window
  check both run on that single absolute clock — never mixing clocks (the #407 P1 fix).
  `ml/pipeline/normalize_fit.refit_template` refits the stats from `episodes.split='train'` rows
  only. These properties have adversarial tests that fail on the naive join / a mixed-clock join /
  an empty damage list / an all-rows fit (`tests/test_t9_training_template.py`, incl. a
  multi-episode fixture and a damage-in-window fixture).
- **Versioning:** **DVC** (Git-adjacent pointer files, S3/local remote) for the
  single-author project. Lineage = `git_sha + dvc_dataset_hash + scaler
  artifact_version + registry_version`.
- **Schema validation:** **pandera** for `silver/player_ticks` (e.g. `health`
  ∈ [0,250], `tick ≥ 0`, `yaw` ∈ [-180,180]); Great Expectations if cross-tool
  suites are wanted later. This adds the validator the current "36 vN string
  tags, no registry" convention lacks (`_inventory.md` §10.9).

---

## 8. Worked end-to-end example (real dm3 tick)

Source: `experiments/nav_doctrine/evidence/replay/dm3_sng_to_rl.cmds`
(`komodobots.replay.v1`, `fps=77.043`), first post-spawn frame.

**(a) Raw `.cmds` row** (14 cols):
```
13  -895.375  -129.125  -15.875  0  0  0  10.7996  -42.5500  0.0000  0  0  0  0
msec  ox        oy        oz     vx vy vz  pitch     yaw       roll   fwd side up buttons
```

**(b) Decomposed into catalog rows** (`episode_id=E`, `tick=1`, `t_s≈0.013`):
- `player_ticks`: `ox=-895.375, oy=-129.125, oz=-15.875, vx=vy=vz=0,
  pitch=10.7996, yaw=-42.55, roll=0, hspeed=0, health=100(spawn), armor=0,
  armor_type=0, onground=1, onground_is_proxy=0, waterlevel=0`.
- `actions`: `forwardmove=0, sidemove=0, upmove=0, buttons=0`,
  `label_source='qwd_usercmd', confidence=1.0` (from the QWD this `.cmds` was built from).

**(c) Engineered feature vector** (selected, with example numbers).
dm3: `x_min=-984, span_x=3032; y_min=-960, span_y=2096; z_min=-416, span_z=912;
diagonal=3797.1`. Goal item = RL (placeholder origin; using the tracked
`dist_to_rl≈2572 qu` scalar from `trace.csv` for this route's start).
```
pos_x_norm = (-895.375 + 984)/3032           =  0.02923
pos_y_norm = (-129.125 + 960)/2096           =  0.39641
pos_z_norm = ( -15.875 + 416)/912            =  0.43873
hspeed                                        =  0.0 qu/s
vel_x, vel_y, vel_z                           =  0, 0, 0 qu/s
yaw_sincos   = [sin(-42.55°), cos(-42.55°)]   = [-0.67623,  0.73669]
pitch_sincos = [sin(10.80°),  cos(10.80°)]    = [ 0.18737,  0.98229]
health_norm  = 100/250                        =  0.40000
armor_norm   = 0/200                           =  0.00000
rl_dist_norm = 2572 / 3797.1                  =  0.67736
rl_remaining_norm = clip(respawn_at-t,0,30)/30=  0.00000   # RL up at round start
rl_available_now  = 1.0
rl_eta_norm  = min( (2572/max(0,eps)=∞ ->CAP 10)/10 , 1) = 1.00000   # hspeed=0 -> capped
rl_up_on_arrival  = 1.0                         # eta(∞) >= t_remaining(0)
match_progress    = 0.013 / duration_s ≈ 0.0
```
Action targets (normalized): `forwardmove=0/400=0, sidemove=0, upmove=0,
jump_button=(0&2)=0, attack_button=(0&1)=0`.

**(d) Normalized vector** applying `normalization_stats.json` (train-only stats;
example dm3 numbers). z-score velocities with `dm3.vel_x{μ=2.1,σ=310.4}` etc.;
robust `hspeed{median=320,iqr=210}`:
```
vel_x_z = (0 - 2.1)/310.4    = -0.00677
vel_y_z = (0 - (-0.4))/305.9 =  0.00131
vel_z_z = (0 - 0)/180        =  0.0
hspeed_norm(robust) = (0 - 320)/210 = -1.52381
# minmax pos_* and sincos/divide_period features are already final (parameter-free or AABB-fixed):
pos_x_norm=0.02923  pos_y_norm=0.39641  pos_z_norm=0.43873
yaw_sincos=[-0.67623,0.73669]  health_norm=0.40000  rl_dist_norm=0.67736
```
The same `normalization_stats.json` numbers are applied identically by the live
ezQuake-side bot at inference → zero training-serving skew.

(At a moving tick, e.g. the `sng_to_rl` peak ~496 qu/s, `hspeed_norm =
(496-320)/210 = 0.838` and `vel_heading_sincos` becomes meaningful since
`hspeed ≥ 80`.)

---

## 9. Build order / roadmap (incremental, non-blocking)

Each step is independently shippable and does not block the current evidence loop.

1. **Catalog skeleton.** Stand up `catalog.duckdb` from `schema/catalog.sql`;
   load `maps` from `maps.v1` and backfill `markers`/`nav_edges` by parsing the
   KTX `.bot` files once. *(No change to existing pipelines.)*
2. **Silver `player_ticks`.** Write an adapter: `events.txt` kind:5 + committed
   `.cmds` → `silver/player_ticks/*.parquet` + `episodes` rows. Validate with
   pandera. *(Reuses existing artifacts; no new capture.)*
3. **Actions table.** Load `qwd_usercmd.v1` (confidence 1.0) and moveprobe rows
   into `actions`; carry `alignment-meta.json` into `align_shift`/`is_interp`.
4. **Item layer.** ✅ dm3 static `items` origins DONE (parsed from `dm3.bsp`,
   `item_catalog.dm3.v2`, `coords_verified:true`). Remaining: wire `getItems`
   `phases[]` for observed respawns + `getWeaponPickups`/`getBackpacks` → `item_events`.
   This unblocks all item/timing features.
5. **Feature build + PIT.** Implement the `feature_registry.json` transforms as
   one shared module (used offline AND by the bot), build `gold/features`
   Parquet via DuckDB `ASOF JOIN`.
6. **Fit normalization.** Welford/Chan over train shards → `normalization_stats.json`
   (positions from AABB; rest fitted). Freeze + version with DVC.
7. **Windowing + tensors.** Emit WebDataset (imitation) + HDF5 (RL) per
   `dataset_spec.yaml`; precompute RTG.
8. **IDM recovery.** Train the inverse-dynamics model on the labeled subset,
   pseudo-label the state-only MVD corpus, validate via `pmove_sim` divergence.
9. **Data-derived item value.** Fit the logistic `item_value` model once enough
   rounds with item events exist; swap `item_value_prior` to `importance_norm`.

Steps 1–9 stand up the **single-agent movement sub-skill**. Steps 10–14 are **REQUIRED
for the headline 4on4 goal** (they layer on top of the same store; steps 1–9 proceed
unchanged):

10. **Multi-actor world-state.** `getStateAt` over all players → `actor_ticks` + `teams`
    rows. The omniscient world that observations are derived from.
11. **Visibility derivation.** PVS → FOV → raycast → `actor_visibility` + belief columns.
    **Needs new code:** `C:\Users\benya\projects\komodobots\scripts\bsp_geom.py` currently
    walks **only the player hull (hull 1)** for solidity/floor; extend it with (a) BSP
    node/leaf point-lookup, (b) RLE PVS / visleaf decode, (c) a **hull-0 `trace_segment`**
    eye→target line-of-sight. Use exactly this path. Record `vis_angle_source`
    (`demoparser` vs `idm_proxy`) — open decision (§2.8).
12. **Entity observation.** Build the `entity_observation` tensors (`entities` / `ent_mask`,
    `schema/dataset_spec.yaml`); DeepSets/transformer pad-mask pooling, `N_max=7`.
13. **Audio cues.** Build `audio_cues` from `getEvents` / `item_events` + synthesized
    footsteps → the `audio` feature group (NOT LOS-gated).
14. **Team layer.** `frag_events` (`getFrags`) + `region_control_timeline`
    (`getRegionControl`) → team-augmented reward with difference-reward credit assignment;
    `team` feature group; per-actor RTG over the team reward.

---

## 10. Assessment of the Gemini draft

A second-model (Gemini) draft was reviewed against this architecture. Verdict by bucket:

| Bucket | Items |
|---|---|
| **ADOPT** (folded into v2) | POMDP observation masking; FOV + raycast occlusion; explicit audio cues; explicit memory/belief (last-seen + time-since-seen); ammo-per-weapon; weapon one-hot; powerup remaining-time. |
| **ALREADY-BETTER** (keep ours) | Egocentric + sin/cos features vs raw-global coordinates; per-feature normalization (z/minmax/robust/log1p/divide/sincos routed by `stats_key`) vs a blanket min-max; richer item respawn / ETA / contest timers (`item_remaining`, `item_eta`, `up_on_arrival`). |
| **WRONG** (corrected) | dm3 `±2048` symmetric bounds — the real AABB is **asymmetric** (`x∈[-984,2048]`, `y∈[-960,1136]`, `z∈[-416,496]`); "invisible = sentinel value" — use a **mask bit + zeroed field + belief block** (3-state, per `item_unknown_flag` §3.3). |

---

## See also
- [`schema/README.md`](schema/README.md) — index of the schema files
- [`schema/catalog.sql`](schema/catalog.sql) · [`schema/feature_registry.json`](schema/feature_registry.json) · [`schema/normalization_stats.template.json`](schema/normalization_stats.template.json) · [`schema/item_catalog.dm3.json`](schema/item_catalog.dm3.json) · [`schema/dataset_spec.yaml`](schema/dataset_spec.yaml)
- [`_inventory.md`](_inventory.md) — the real existing substrate
- [`_external-research.md`](_external-research.md) — formats/formulas/citations
