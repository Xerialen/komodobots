# Source schemas — mvd_analyzer + demoparser (real-code study)

> **Companion (generated):** the runnable coverage audit
> `extraction-coverage-audit.md` diffs this decoder Result inventory against the
> operative catalog schema + feature registry + what each ETL populates, classifying
> every column extracted/derived/excluded/GAP. Regenerate with
> `python3 scripts/audit_extraction_coverage.py` (Demo Extraction Spec v1, ticket #389).

> **⚠️ DATED CORRECTION (2026-06-26, analyzer-fitness WS-0).** This study predates the MVD reader's
> **schema v31/v32/v33** additions, so §A/§C/§D below are STALE where they say mvd_analyzer "has no
> velocity / no view angles" — schema **v35** now exposes view pitch/yaw (v31), derived velocity (v32),
> and float32 precision (v33). Trust `scripts/audit_extraction_coverage.py` (the generated companion) +
> `plans/analyzer-fitness-plan.md` for current truth. Two findings in this doc are now LOAD-BEARING for
> analyzer-fitness: (1) §C/§B1 — `active_weapon()=stat[10]` is recoverable (WS-1: the mvd-reader parses
> STAT_ACTIVEWEAPON but does not surface it in the Result); (2) **§B4 — the KTX hidden-usercmd block is
> decodable** (demoparser `src/mvd/hidden.rs:143-179` recovers forward/side/buttons/impulse; up/angles/msec
> are present but discarded). (2) is the WS-2 spike: true forwardmove from MVD is feasibility-proven, gated
> only on per-tick density + KTX-version coverage.


Study target: replace template placeholders (`coords_verified=false`, `_verify=true`,
`*_unavailable`) in `schema/catalog.sql` + `schema/item_catalog.dm3.json` with real
fields from the two parsers actually on this machine.

Two **independent** parsers (confirmed — no cross-references either direction):

- **mvd_analyzer** (Go) — `~/projects/quakeworld/mvd_analyzer`. The stack behind the
  `mvd-mcp` tools. MCP wrapper → `mvd-api` REST (`:8080`) → `mvd-analytics` analysis
  library, which uses its **own** Go MVD reader `mvd-reader/` (NOT demoparser).
- **demoparser** (Rust, crate `mimer`) — `~/projects/demoparser`. Standalone MVD parser
  feeding a Supabase "moments" pipeline + a Discord bot. `grep` for `demoparser|mimer`
  in mvd_analyzer = 0 hits; `grep` for `mvd_analyzer|mvd-reader` in demoparser = 0 hits.

The komodobots template is wired to **mvd_analyzer / mvd-mcp** (catalog.sql comments cite
`getItems`/`getWeaponPickups`/`getBackpacks`). demoparser is a *parallel option*, weaker
for this purpose (see §B/§D).

Authoritative schema doc: `mvd-analytics/RESULT_SCHEMA.md`. Go source of truth:
`mvd-analytics/result/*.go`. HTTP semantics + units: `mvd-api/API.md`.

---

## Units / keying (both confirm Quake conventions — matches catalog.sql header)

- **Position** = Quake units (qu). `x/y/z` are `float32` in result structs; `int32` in the
  position *track*; world maps can exceed ±32768 so int32 not int16
  (`RESULT_SCHEMA.md:530`).
- **Velocity** = NOT EXPOSED by mvd_analyzer (no velocity field anywhere in result schema).
  demoparser has a `velocity` field but it is **hardcoded `[0;3]`** (see §B3).
- **Angles** = degrees (pitch,yaw,roll). Only demoparser exposes view angles
  (`PlayerState.angles: [f32;3]`); mvd_analyzer does NOT carry angles in its streams.
- **Time** — *storage* is `int32 milliseconds` everywhere (`RESULT_SCHEMA.md:533-550`); the
  *view/query layer* (`/buckets`,`/events`,`/state-at`,`/stream-slice`) emits `float64
  seconds` at its public surface. Raw stream entries embedded in `/stream-slice` stay in
  int32 ms. Scale ms→s by `*0.001`.
- **Tick rate** — MVD wire carries a **1-byte ms delta per frame** (`mvd.Decoder.timeMs`,
  `RESULT_SCHEMA.md:554`). Native position cadence ≈ 13 ms (~77 fps) — matches the
  template's `server_fps DEFAULT 77.0` and the "~13 @ 77fps" comment in catalog.sql.
  Positions in mvd_analyzer are stored at native rate (`/stream-slice?fields=pos` is the
  only native-rate source); buckets/state-at downsample.
- **Players keyed by** name (canonical demoinfo-resolved; collisions suffixed `name#slot`),
  also `playerUserIDs[name]→int` (hub viewer id). **Teams** keyed by team-name string;
  duel gets per-player synthetic team.
- **Data origin** — mvd_analyzer parses MVD (MVDSV multiview server recordings) only via
  `mvd-reader`. It does NOT call demoparser.

---

# (A) mvd_analyzer — endpoint-by-endpoint output schemas

Each MCP tool `getX` forwards 1:1 to `GET /v1/demos/{id}/<x>` (`mvd-mcp/mcp_tools.go`,
`mvd-api/API.md`). Field shapes are `mvd-analytics/result/*.go` mirrored in `RESULT_SCHEMA.md`.

## getItems → `ItemsResult` (`result/items.go`) — **THE PRIORITY ANSWER: YES**

`{ items: [ItemTimeline] }`. Per **item entity** (one row per spawned entity; multiple of a
kind get `mh_1`,`mh_2` suffixes, ctrl-sorted):

| Field | Type | Unit/meaning |
|---|---|---|
| `name` | string | e.g. `ya_1`, `mh_1`, `rl` |
| `kind` | string | `ra/ya/ga/mh/quad/pent/ring/rl/lg/ssg/sng/ng/gl/h15/h25/nails/shells/rockets/cells` |
| `entNum` | int | server ent number (stable within match) |
| **`x`,`y`,`z`** | **float32** | **WORLD SPAWN POSITION in qu** ← items.go:30-32 |
| `loc` | string (omitempty) | nearest named loc |
| `phases` | []ItemPhase | pickup/respawn timeline |

`ItemPhase` (`result/items.go:ItemPhase`):

| Field | Type | meaning |
|---|---|---|
| `availableFrom` | int32 ms | when item became available (0 = match start) |
| `takenAt` | int32 ms (omitempty) | when picked up |
| `takenBy` | string (omitempty) | picker display name (KTX-only; blank on non-KTX) |
| `team` | string (omitempty) | picker team |
| `respawnAt` | int32 ms (omitempty) | when it returns; **0 = still held / unknown** (esp. MH, whose timer needs `//ktx timer`) |

**Item world coords:** YES — `x,y,z float32` per entity, derived from the MVD entity stream
(model-classified baselines), present on **any** demo, KTX or not (`items.go` header comment;
`RESULT_SCHEMA.md:884-900`). **Respawn timing:** YES, but *observational, not a fixed prior* —
respawn is the actual `respawnAt - takenAt` interval observed in *this match*. Fixed canonical
respawn-seconds (30s weapon / 20s armor / etc.) is NOT a field; it's domain knowledge the
template already hardcodes. For MH, `respawnAt` is the real decay-dependent return time when
KTX `//ktx timer` is present, else 0.

## getMapEntities / getMapEntitiesByMap → `MapEntitiesResult` (`result/map_entities.go`)

**This is the cleaner static-coords source than getItems** (per-match noise removed). The
map's *designed* layout from the offline BSP-entity corpus (`mvd-analytics/mapents/data/<map>.json`),
identical for every demo. `{ map, entities: [MapEntity] }`:

| Field | Type | meaning |
|---|---|---|
| `type` | string | `item`/`spawn`/`teleportDst`/`teleportSrc`/`button`/`door` |
| `class` | string | raw BSP classname (`weapon_rocketlauncher`, `item_armorInv`, …) |
| `kind` | string (omitempty) | items only; same vocab as ItemTimeline.Kind |
| `name` | string | loc-based label, `-1`/`-2` disambiguated |
| `x`,`y`,`z` | float32 | **qu**; entity origin (point) or bbox centre (brush) |
| `loc` | string (omitempty) | nearest loc |
| `target`/`targetName` | string | teleport pair join keys |
| `spawnflags` | int (omitempty) | raw BSP spawnflags (e.g. item_health H_ROTTEN=1/H_MEGA=2) |
| `bounds` | {min[3],max[3]} | brush entities only (trigger/door volume, world coords) |

Reachable by map name with **no demo**: `GET /v1/maps/{map}/entities` (MCP `getMapEntitiesByMap`).
For dm3 this *directly* populates `items.origin_x/y/z` + `classname` + `spawnflags` for the
template — the authoritative static-coords answer.

## getWeaponPickups → `[]WeaponPickup` (`result/weapon_pickups.go`)

Slot-weapon acquisitions (world spawners + RL/LG backpacks):

| Field | Type | meaning |
|---|---|---|
| `time` | int32 ms | acquisition time |
| `player`,`team` | string | who |
| `weapon` | string | `rl/lg/gl/ssg/sng/ng` |
| `source` | string | `world` \| `backpack` |
| `hadBefore` | bool | redundant grab (already held) → kills not credited |
| `kills` | int | kills-before-next-death effectiveness |
| `nextDeathTime` | int32 ms (omitempty) | 0 if never died before match end |
| `backpackEnt` | int (omitempty) | join key ↔ `BackpackDrop.entNum` (backpack source only) |
| `dropper`,`dropperTeam` | string | backpack source |
| `dropTime` | int32 ms (omitempty) | when pack was dropped |

NOTE: `getWeaponPickups` carries **no x/y/z** (it's an event log, not coords). Coords for a
backpack pickup come via the joined `getBackpacks.origin`. Weapon-spawner world coords come
from `getItems`/`getMapEntities`.

## getBackpacks → `[]BackpackDrop` (`result/backpacks.go`)

RL/LG drops from KTX `//ktx drop`:

| Field | Type | meaning |
|---|---|---|
| `time` | int32 ms | drop time |
| `player`,`team` | string | dropper |
| `weapon` | string | `rl`\|`lg` (heavy weapons only — KTX emits hint only for these) |
| `origin` | [3]float32 | **drop world position, qu** |
| `loc` | string (omitempty) | nearest loc |
| `entNum` | int | join key ↔ `WeaponPickup.backpackEnt` |

Pickup tracking deliberately omitted (wire flutter unreliable).

## getStateAt → `view.StateAtView`

`{ t (sec), players: { name: { <field>: value, pos:{x,y,z} } } }`. Per-field carry-forward at
`time`; intervals report bool; position is nearest sample. Field codes (the per-tick state
vocabulary, `RESULT_SCHEMA.md:636-657`):
`h`(health int16), `a`(armor int16), `at`(armortype "ga"/"ya"/"ra"/""), `li`(loc index),
`pos`(x,y,z), `rl/lg/gl/ssg/sng`(weapon held bool), `q/pe/r`(quad/pent/ring bool),
`sh/nl/rk/cl`(shells/nails/rockets/cells int16), `sp/d`(spawn/death event bools).
**No velocity, no angles, no buttons, no usercmd.** State only.

## getStreamSlice → `view.StreamSliceView`

Raw native-rate change entries in `[from,to)` per field + carry-forward at window start.
`pos` here is the **only ~77fps native position source** — `{ pos:{ t:[ms…], x:[…],y:[…],z:[…] } }`,
change streams `[{t:ms,v}]`, intervals `[{s:ms,e:ms}]`. Entry t/s/e are int32 ms.

## getBuckets → `view.ColumnarBuckets` (default) / `view.BucketsView` (row)

Per-player time series on a fixed `windowMs` grid. Columnar: `windowMs,startMs,count`, per
player `{first,n,alive:[0/1],h|a|li|sh|nl|rk|cl:[int16],x|y|z:[int32],at:[str],
rl|lg|gl|ssg|sng|q|pe|r|sp|d:[0/1]}`. `time(i)=startMs+i*windowMs` (ms). Down-sampled (one
reduced value per window; default reducer `first` = value at window start).

## getEvents → `view.EventsView`

`{ events:[{ t(sec), type, player, team?, detail? }] }`. Default types
`frag,powerup,streak,spawn,death,weapon,item,chat`; opt-in `health,armor,loc,damage,telefrag,stomp`.
**Authoritative spawn/death life-event log.** A `damage` event detail:
`{victim,damage,weapon,isSplash?,isEnv?,isSelf?,isTeam?,victimWep?}`.

## getFrags → `FragResult` (`result/frag.go`)

`{ totalFrags, frags:[{time(ms),killer,victim,weapon,isSuicide?,isTeamKill?}],
byWeapon:{wpn:int}, byPlayer:{name:{kills,deaths,teamkills?,byWeapon}} }`. Weapon vocab:
`rl,lg,gl,ssg,sng,ng,sg,ax,tele` + env `lava/fall/water/slime/world/squish`.

## getOverview → composed (`mvd-api/overview.go`)

`{ schemaVersion, map, gameDir, mode?, duration(sec), matchStart, matchEnd,
teams:[{name,frags}], players:[{name,team,frags,kills,deaths,suicides}],
topStreaks:[≤5], topPowerups:[≤5], locCount, hasRegionControl(bool), playerUserIDs:{name:int},
errors:[…]? }`. Call first; `hasRegionControl=false`/non-empty `errors` ⇒ degraded.

## getMetadata → `MetadataResult` (`result/metadata.go`)

`{ serverInfo:{cvar:val}, matchSettings:{mode,deathmatch,teamplay,timelimit,fraglimit,
spawnmodel,spawnK,antilag,overtime,powerups,dmgfrags,noItems,midair,instagib,yawnmode,
airstep,vwep,noweapon,matchtag,socdv2}, countdownText }`. The ruleset — **read `spawnmodel`/
`powerups`/`noItems` to know which items actually spawn + which respawn rules apply.**

## getDemoInfo → `DemoInfoResult` (`result/demoinfo.go`)

Verbatim KTX scoreboard JSON (untransformed). Per-player `Stats`(frags/deaths/tk/kills/
suicides), `Dmg`, `Spree`, `Speed`(max,avg), `Bot`(skill — present iff frogbot),
`Weapons[k]`(Acc/Kills/Deaths/Pickups/Damage), `Items[k]`(Took,Time). 422 on non-KTX demos.

## getLocGraph → `LocGraphResult` (`result/locgraph.go`)

`{ locs:[LocNode], edges:[LocEdge] }`.
`LocNode = { name, x,y,z, total(sec), byPlayer, byTeam, armed?,unarmed?,quad?,pent? }`.
`LocEdge = { from, to, kind("normal"|"teleport"), total, byPlayer, byTeam, armed?,… }`.
Loc-to-loc movement graph; edge weights = observed transition counts (NOT a static nav mesh —
data-derived from player movement). Coordinates are loc **anchor points** in qu, not item origins.

## getLocTable → `{ locTable: [string] }` (index 0 = "" no-loc sentinel). Decoder for `li`.

## getLocTrails → `view.LocTrailsView`

`{ players:[{ name, sequence:[{ s(sec), e(sec), loc }] }] }`. Per-player loc residences w/ dwell.

## getRegionControl → `RegionControlResult` (`result/timeline.go`)

`{ teamA, teamB, regions:[ControlRegion{name,locs[],points[],centroidX/Y}],
bucketStates:{region: "AaCcBb_…" one char/bucket}, stats:{region: RegionStats{
teamAControl,teamAWeakControl,contested,weakContested,empty,teamBWeakControl,teamBControl
(all percent), byPlayer:{name:{team,armed,unarmed}} }} }`. "armed"=carrying RL/LG. Regions are
named loc-groups, NOT geometric zones (membership = resolved loc name ∈ region.locs).

## getChat → `[]MatchEvent`: `{ time(ms), type("chat"|"teamsay"), player, team, message, messageClean }`.

---

# (B) demoparser (Rust crate `mimer`) — data model

MVD-only (no QWD/POV support). JSON output built ad-hoc via `serde_json::json!` (no top-level
typed struct); Supabase ingest; no CSV.

## B1. Per-tick player state — `PlayerState` (`src/state/mod.rs:81-116`)

`player_num:u8, name:String, team:String, user_id:u32, origin:[f32;3] (DF_ORIGIN, qu),
angles:[f32;3] (DF_ANGLES, deg), frame:u8, weapon_frame:u8 (fire = 0→1 transition),
stats:[i32;32], dead:bool, gib:bool, last_update_time:f32, connected:bool,
antilag_origin:Option<[f32;3]>, antilag_time:f32`.
Accessors (`:142-148`): `health()`=stats[0], `armor()`=stats[4], `items()`=stats[15] as u32
bitfield, `active_weapon()`=stats[10]. STAT indices (`mvd/types.rs:99-112`): per-type ammo
SHELLS=6/NAILS=7/ROCKETS=8/CELLS=9 and armor exist as stat slots but **only health/armor/
items/activeweapon have named accessors**. Powerups via STAT_ITEMS bitfield IT_* (`types.rs:116-130`):
IT_QUAD, IT_INVULNERABILITY(pent), IT_INVISIBILITY(ring), IT_ROCKET_LAUNCHER, IT_LIGHTNING, armor1/2/3.
`frags` stored separately in `MatchState.frags:HashMap<u8,i16>`.

## B2. Timing — `MvdFrame` (`src/mvd/frame.rs:18-34`)

`time:f32 (accumulated sec), msec:u8 (per-frame ms delta; time += msec/1000), frame_type:u8,
player_num:u8, client_mask:u32`. Frame index = `MatchState.frame_count:u64`. Positions sampled
1/sec into `position_timeline`.

## B3. Entities / items

`EntityState` (`state/mod.rs:648-654`): `entity_num:u16, model_index:u8, origin:[f32;3],
last_update:f32`. `ItemEntityEvent` (`:681-691`): `time, event_type{Spawned,PickedUp},
entity_num:u16, item_name:String, position:[f32;3], picked_up_by:Option<u8>`. `BackpackEvent`,
`PowerupEvent{Quad/Pent/Ring, Pickup/Expired/LostOnDeath, position}`, `RearmCycle`(death→rearm).
BSP item spawns (`map/bsp.rs`): `ItemSpawn{item_type:ItemType, origin:[f32;3], classname}`.

## B4. CRITICAL — inputs / usercmd (Rust)

- **MVD inputs ARE partially present, via the hidden-message channel** (NOT playerinfo):
  `HiddenMessage::UserCmd{player_num:u8, forward:i16, side:i16, buttons:u8, impulse:u8}`
  (`src/mvd/hidden.rs:32-38`). The full block (msec, 3 angles, fwd/side/**up**, buttons,
  impulse — 23 bytes) is decoded at `hidden.rs:143-179` but **`up`, `msec`, `dropnum`, and
  `angles` are read then DISCARDED** (`Ok(_msec)`/`Ok(_up)`). Surfaces as `AttackEvent`
  (`state/mod.rs:723-735`): `{time, player_num, attacking:bool, forward:i16, side:i16,
  impulse:u8}` — and **only stored when shooting or weapon-switching** (`:854`). So inputs are
  lossy/conditional: no upmove, no idle-tick movement, no msec/angles retained.
- **`PlayerInfoMsg.msec` and `.velocity` are hardcoded `None`/`[0;3]`** — `messages.rs:606`
  comment "NO msec, NO velocity, NO usercmd in MVD playerinfo"; `:702-715`.
- **QWD (client POV) demos: NOT handled at all** — no QWD reader, no `usercmd_t` client decode.
  Parser reads modern headerless MVDSV only.

## B5. Output / Supabase schema (`supabase/migrations/*.sql` + `scripts/migrations/`)

`Moment` (typed, `output/moments.rs:23-37`): `id, time_seconds, tier, score, signals{rl_swing,
eco_swing,control_phase_started,control_duration_s,high_value_kills,denied_rearm_bonus},
score_breakdown, evidence{trigger_kills,before,after,frag_pace}, narrative, best_pov, hub_url`.
Supabase tables: `demos`(sha256 PK, filename, map, duration_s, hub_id, winner, model_version),
`moments`(id, demo_sha256, time_seconds, tier, score, signals jsonb, …, hub_url),
`feedback`, `users`, `model_versions`, `floods`(hunter/target, kill_time_seconds, kill_weapon,
target_damage, total_damage, coordinated, …), plus phase-4b `analyses`/`claims`/`analysis_metrics`.
This is a **moment/highlight** model, not a per-tick (state,action) ML model.

---

# (C) Mapping — template field ← real source (+ transform)

Unit transform `ms→s = *0.001` applies to every time field below.

## `maps`
| template col | source | transform |
|---|---|---|
| name, source_bsp | `getMapEntities`/overview `map` + BSP filename | direct |
| x_min..z_max (AABB) | derive from `getMapEntities` entity x/y/z extents, OR read dm3.bsp | min/max over entities (approx) or BSP model[0] mins/maxs (exact) |
| center_*, diagonal | computed from AABB | arithmetic |
| maxspeed/jumpspeed/gravity/friction/… | NOT in either parser | keep template defaults (QW physics constants) — **[not in code]** |
| server_fps 77.0 | confirmed by ms-delta cadence | keep default |

## `items` (de-placeholder the dm3 catalog) — **PRIMARY WIN**
| template col | source | transform |
|---|---|---|
| classname | `getMapEntities.entities[].class` (or `getItems` via kind→class) | direct |
| item_type | `getItems.kind` / `getMapEntities.kind` | direct (vocab already matches: rl/ra/ya/ga/mh/quad/…) |
| category | `ItemTimeline.Category()` (armor/mega/health/powerup/weapon/ammo) | direct |
| **origin_x/y/z** | **`getMapEntities.entities[].x/y/z`** (static, no demo) OR `getItems.x/y/z` | direct float32 qu → REAL |
| **coords_verified** | set **TRUE** once filled from getMapEntities | — |
| respawn_seconds | NOT a static field — keep template canonical priors; *observe* actual via `getItems` phase `respawnAt-takenAt` | keep prior; optionally validate |
| static_value | NOT in either parser | keep template prior |
| nearest_marker | no Frogbot markers in mvd_analyzer; `getItems.loc`/`getMapEntities.loc` gives a loc name instead | map loc→marker separately, or repurpose |
| spawnflags (mega/h15 disambig) | `getMapEntities.entities[].spawnflags` (H_ROTTEN=1/H_MEGA=2) | direct |

## `item_events` — **PRIMARY WIN**
| template col | source | transform |
|---|---|---|
| demo_id | `loadDemo` sha | direct |
| item_id | join to `items` by kind + nearest origin | spatial join |
| t_s | `getItems.phases[].takenAt` / `.respawnAt`; `getBackpacks.time`; `getWeaponPickups.time` | ms→s |
| event_kind | `pickup` ← phase.takenAt; `respawn` ← phase.respawnAt; `backpack_pickup` ← weaponPickups source=backpack; `drop` ← getBackpacks | mapping |
| player_id | `getItems.phases[].takenBy` (KTX only) / `getWeaponPickups.player` | name→player_id |
| origin_x/y/z | `getBackpacks.origin` (dropped packs) | direct |
| item_type | `getItems.kind` / `getBackpacks.weapon` | direct |

## `player_ticks` (state spine)
| template col | source | transform |
|---|---|---|
| tick, t_s, msec | `getBuckets` index / `getStreamSlice` entry t | ms→s; msec from frame delta (~13) |
| ox/oy/oz | `getStreamSlice?fields=pos` (native ~77fps) or `getStateAt.pos` | int32 ms-track → qu |
| vx/vy/vz | **NOT EXPOSED by mvd_analyzer**; demoparser velocity hardcoded 0 | **must derive numerically** = Δpos/Δt, or pmove_sim |
| pitch/yaw/roll | **NOT in mvd_analyzer**; demoparser `PlayerState.angles` (MVD DF_ANGLES) | demoparser only |
| hspeed | derive `hypot(vx,vy)` after deriving v | computed |
| onground | NOT exposed (template already flags MVD as proxy) | Z-motion proxy, `onground_is_proxy=TRUE` |
| waterlevel | NOT in MVD | NULL for MVD (template already says so) |
| health | `getStateAt`/`getBuckets` `h` (int16) | direct |
| armor | `a` (int16) | direct |
| armor_type | `at` ("ga"/"ya"/"ra"/"") → 0/1/2 | string→int map |
| weapon | held-weapon intervals `rl/lg/gl/ssg/sng` (bools) — no single "active weapon" int in mvd_analyzer; demoparser has `active_weapon()`=stat[10] | derive active from intervals, or use demoparser |

## `actions` (imitation labels) — see §D for the hard truth
| template col | source | transform |
|---|---|---|
| forwardmove | demoparser `AttackEvent.forward` (MVD hidden usercmd) | **only when shooting/switching** |
| sidemove | demoparser `AttackEvent.side` | same caveat |
| upmove | **DISCARDED in demoparser; not in MVD playerinfo** | **[not recoverable from MVD]** |
| buttons | demoparser `HiddenMessage::UserCmd.buttons` (attack bit survives via AttackEvent.attacking) | partial |
| impulse | demoparser `AttackEvent.impulse` | weapon switch |
| cmd_yaw/pitch/roll | demoparser usercmd angles **DISCARDED**; resulting-view `PlayerState.angles` available as proxy | view-angle proxy, not commanded angle |
| label_source | `qwd_usercmd` is impossible (no QWD support); MVD gives partial `moveprobe`-like inputs only when firing; else `idm` (must train IDM yourself) | — |
| confidence | 1.0 for the sparse fired-frame inputs; <1 for IDM-recovered | — |

## `players` ← `getOverview.players[].name`/`team` + `playerUserIDs`; `is_bot` ← `getDemoInfo.Bot` present.
## `episodes` ← continuity splits over `getEvents(spawn/death)` per demo+player. Times ms→s.
## `markers`/`nav_edges` ← **NOT in mvd_analyzer** (no Frogbot graph). `getLocGraph` is a
   *data-derived* loc movement graph (different concept). Frogbot markers stay from the ad-hoc
   KTX `.bot` parse the template already references. `getMapEntities` teleporters/buttons CAN
   feed `is_teleport`/`is_door` + teleport edges.

---

# (D) De-placeholderable NOW vs genuinely unknown

## Can be de-placeholdered NOW (from mvd_analyzer / mvd-mcp)
1. **`items.origin_x/y/z` + `coords_verified=TRUE`** — `getMapEntities`/`getMapEntitiesByMap`
   gives every dm3 item spawn's world qu coords with **no demo needed**, plus `class` +
   `spawnflags`. This is THE answer to the item_catalog.dm3.json placeholders. `getItems` on a
   dm3 demo confirms which actually spawn under the ruleset.
2. **`item_events` table entirely** — `getItems.phases` (pickup/respawn), `getWeaponPickups`,
   `getBackpacks`. Real timestamps, pickers (KTX), respawn intervals.
3. **`player_ticks` state cols** — health/armor/armor_type/weapon-held/ammo/loc/position all
   from `getStateAt`/`getStreamSlice`/`getBuckets`. Native ~77fps position via stream-slice.
4. **`players`, `episodes`, `demos` provenance** — overview/metadata/loadDemo sha.
5. **`is_teleport`/`is_door` + teleport edges** — `getMapEntities` brush entities + target pairs.

## Genuinely remains unknown / external
1. **Velocity (vx,vy,vz)** — exposed by NEITHER parser (mvd_analyzer absent; demoparser
   hardcoded 0). Must be **derived** (finite-difference Δpos/Δt) or simulated (pmove_sim).
2. **View angles in mvd_analyzer** — absent. demoparser `PlayerState.angles` (MVD DF_ANGLES)
   is the only source; it is *resulting* view angle, not the *commanded* usercmd angle.
3. **Full per-tick action labels (`actions` for imitation)** — **the hard truth:**
   - MVD = **server-side state recording**; it does NOT carry per-tick usercmd for the
     resulting view. demoparser recovers usercmd `forward/side/buttons/impulse` ONLY from the
     KTX hidden-usercmd block, and ONLY emits it on shoot/weapon-switch frames (`upmove`,
     `msec`, commanded `angles` are decoded then discarded). So you get **sparse, partial**
     inputs — not a dense per-tick action stream.
   - **QWD (client POV) demos are NOT supported by either parser.** The template's
     `actions.label_source='qwd_usercmd'` tier has **no implementation here** — neither repo
     reads a client POV demo's usercmd_t. Dense ground-truth human inputs would require a
     QWD parser that does not exist in either codebase, OR an inverse-dynamics model (`idm`)
     trained on the state stream (confidence<1), OR the bot-lab `moveprobe`/`sim` tiers the
     template already cites (external to both parsers).
   - Net: **MVD → state-rich, action-poor** (partial inputs at fire frames only); **QWD →
     not parsed at all**. The imitation track's dense action labels are NOT available from
     these two tools as-is.
4. **`maps` physics constants + AABB** — not in parser output; from BSP / QW physics knowledge.
5. **`items.static_value`, `item_value` model** — priors/fitted, not parser fields.
6. **`markers`/`nav_edges` (Frogbot)** — not in mvd_analyzer; from the KTX `.bot` parse.

## One-line answers
- **Do getItems/getWeaponPickups give item coords + respawn timers?** getItems: **YES coords**
  (`x,y,z float32` qu per entity) **+ YES observed respawn** (`phases[].respawnAt`, real
  per-match interval, 0/MH-dynamic caveat). getWeaponPickups: no coords (event log) but real
  pickup times + effectiveness. **getMapEntities is the cleanest static-coord source** (no demo,
  + classname + spawnflags). Item world origins for the dm3 catalog can be filled authoritatively.
- **Does the parser expose inputs?** mvd_analyzer: **NO** (state only — no usercmd, no
  velocity, no angles). demoparser: **partial MVD usercmd** (forward/side/buttons/impulse, only
  on fire/switch frames; upmove+angles+msec discarded), **no QWD support at all**.
