# Demo Extraction Specification

**Spec id:** `komodobots.demo-extraction.v1` · **Status:** living document (additive versioning,
§8) · **Authored:** 2026-06-24.

This is the **umbrella, method-agnostic contract** for *everything we extract from QuakeWorld
demos* — the complete, raw, durable representation that every downstream model (AMP / RL / BC /
analytics) consumes a subset of. It exists because the extraction truth has been **scattered**
across a movement-only contract (`docs/25_DATA_CONTRACT.md`), a substrate spec
(`docs/ml-data-architecture/00-DATA-ARCHITECTURE.md`), a fusion plan (`docs/13`), and the ETL
code — and because we have historically extracted only **movement**, a fraction of what the demos
carry. The goal: **define the maximal extraction once**, so the expensive parse is never redone
when the modelling method changes.

> **Governing principle — extract maximal RAW, derive obs downstream.** The extraction captures
> every quantity the demo physically carries plus everything derivable from fixed map geometry.
> Models build their observation vectors *from this catalog*; we do **not** bake model-specific
> observations into the extraction. New methods cost a query, not a re-parse.

> **Change-control (inherited from `docs/25` §5).** Do not add, rename, or retype an extracted
> field without updating, in the same PR: this document, `scripts/catalog_schema.sql`,
> `data/catalog/feature_registry.yaml`, and the relevant tests. Decisions → `docs/08_DECISION_LOG.md`;
> newly discovered source-data behaviour → `docs/07_FINDINGS_LOG.md`.

---

## 0. Relationship to existing docs (consolidate by reference — do not duplicate)

| Doc | What it owns | This spec's relation |
|---|---|---|
| `docs/25_DATA_CONTRACT.md` | The **older movement-MOVE** training contract: Layer-A 11-field NDJSON shard + Layer-B 6-feature vector from `~/ctv_decomp` QWDs. | Sub-contract for one *consumer* (MOVE). This spec is the broader extraction it draws from; §3 supersedes its field view with the full catalog. |
| `docs/ml-data-architecture/00-DATA-ARCHITECTURE.md` | The catalog **substrate**: positioning (§2), items (§3), POMDP/observability (§2.8), normalization (§6), splits/leakage/versioning (§7). | The substrate this spec extracts *into*. §5 references its derivation specs and fills the gaps; §6 references its §7. |
| `docs/13_QWD_MVD_FUSION_PLAN.md` | The two-source QWD+MVD fusion roadmap (opponent-collision physics). | The plan that motivates the two-source design; §2 here is its data contract. |
| `docs/06_DATA_AND_MVD_PIPELINE.md` | Narrative + the QWD-POV usercmd-label apparatus and moveprobe history. | Prior art for §2/§4 (not the normative extraction). |
| `docs/02_SOURCE_MAP.md` | Software sources (KTX, MVDSV, parsers) + parser-pinning warning. | Provenance source for §2. This spec is registered there. |
| `scripts/catalog_schema.sql` (`catalog.v1`) · `data/catalog/feature_registry.yaml` (v5) | The machine-readable schema + feature registry. | The binding artifacts §3/§7 reference field-by-field. |

---

## 1. Purpose & scope

- **Method-agnostic.** This spec describes *what data exists*, not how any model uses it. AMP needs
  `(state, next-state)` pairs; RL needs reward inputs + a state-prior; BC needs `(state, action)`;
  analytics needs events. All are subsets/derivations of the catalog defined here.
- **Two sources** (§2): the omniscient **server MVD** corpus (all players, full game state,
  inverse-dynamics-recovered movement) and the first-person **client QWD** corpus (ground-truth
  per-frame usercmds — including the `forwardmove` that MVD cannot recover).
- **Maximal & raw.** §3 enumerates every recoverable quantity, tagged by role; §7 stores them raw in
  the relational catalog. Derived context (geometry, regime, threat, item-urgency) is computed once
  and stored alongside (§5), not left for each consumer to recompute.
- **Out of scope:** model architectures, reward design, training (those live in the set-aside
  modelling plan and `docs/18`/`docs/20`).

---

## 2. Sources & provenance

Two demo formats, decoded by tools referenced **by role + provenance, never by tool name** (names
are in flux; provenance is what makes a run reproducible):

| Source | What it physically carries | Movement actions | Decoder (role) | Provenance lock |
|---|---|---|---|---|
| **Server MVD** (omniscient) | per-frame (~72–77 Hz) for **all players**: origin + view-angles; health/armor/armor-type/ammo/active-weapon/items+powerups (event-rate); frags, deaths (attacker/victim/weapon); per-hit damage (KTX hidden block, era-gated); item pickup/respawn timeline; movers; chat/obituaries; pauses; cvars. **No usercmds.** | **IDM-recovered** (jump, in-regime strafe-sign); **forwardmove unrecoverable**. | the MVD movement decoder (per-tick stream) + the full in-house MVD result decoder | binary sha (e.g. movement decoder `6954ffb6`, schema-33) + decoder schema version + per-demo sha256 + size |
| **Client QWD** (first-person POV) | the recording player's **raw per-frame usercmds** (`forwardmove`/`sidemove`/`upmove`/`buttons`/viewangles @ ~77 Hz) + that client's precise origin/angles + the svc stream it received. | **ground-truth** (incl. forwardmove + true viewangles). | the QWD usercmd decoder | usercmd struct layout + per-demo sha256 + size |

**Corpora (servexeri; canonical; never copied to aws-dev):**
- MVD 4on4: `/mnt/usb-ssd/4on4-corpus/demos/` (~6,409 unique 4on4 `.mvd`).
- QWD POV dm3: `/mnt/usb-ssd/4on4-corpus/challenge-tv-pov-dm3/` (548 = 70 `.qwd` + 478 `.qwz`→`.qwd`).
- Vault refs: `~/thevault/quakeworld/mvds.md`, `~/thevault/projects/mvd_analyzer.md`.

**Reconciliation.** Both sources land in **one schema**; `actions.label_source` distinguishes
`qwd_usercmd` (ground-truth) / `idm` (recovered) / `sim` / `moveprobe`. Games present as **both** an
MVD and a POV QWD are the **calibration set** (validate IDM recovery + the fidelity contract, §4).

**Era-gating (must be marked per field, never assumed).** Per-hit damage / fine economy ride the KTX
`mvdhidden_dmgdone` block and exist only on ~2024+ KTX demos. Availability is a field attribute (§3).

**Parser pinning.** Per `docs/02`/`docs/06`: pin the decoder commit/sha before any output is treated
as regression evidence. The schema-21 MVD binary silently drops view-yaw → IDM strafe-sign fails;
the schema-33 binary (`6954ffb6`) is required for movement.

---

## 3. The complete field taxonomy (the heart)

Every recoverable quantity, organized by **entity** and tagged by **role**. Role tags:
**[K]** kinematic · **[A]** action · **[I]** intent/goal · **[G]** geometry · **[R]** regime ·
**[C]** combat/threat · **[E]** economy/items · **[M]** meta/provenance. Recoverability:
**obs** (observed on wire) · **idm** (inverse-dynamics-recovered) · **fd** (finite-differenced) ·
**der** (derived from geometry/rules) · **none** (unrecoverable). Availability:
**always** · **pov** (QWD POV only) · **era** (KTX-era-gated). Each maps to a catalog column
(`scripts/catalog_schema.sql`) or a derivation (§5).

### 3.1 Self / per-actor kinematic state — `player_ticks` / `actor_ticks`
| Field | Role | Recov. | Avail. | Units | Source |
|---|---|---|---|---|---|
| ox, oy, oz | K | obs | always | qu | `svc_playerinfo` origin |
| vx, vy, vz | K | fd | always | qu/s | finite-diff of origin (KTX velocity oracle validates) |
| hspeed | K | der | always | qu/s | `hypot(vx,vy)` |
| pitch, yaw, roll | K | obs | always | deg | `svc_playerinfo` angles (angle16, lossless) |
| yaw_rate | K | fd | always | deg/s | `wrap180(Δyaw)/Δt` — the air-strafe direction signal |
| face_vel_angle | K | der | always | deg | signed `yaw − atan2(vy,vx)` |
| onground | K/R | der | always | bool | geometric floor trace (`onground_is_proxy` for MVD) |
| waterlevel | R | obs | pov/sim | 0–3 | sim/QWD (NULL for MVD) |
| msec | M | obs | always | ms | per-frame duration (fidelity, §4) |
| t_s, tick | M | obs | always | s, idx | episode clock |

### 3.2 Recovered / ground-truth movement actions — `actions`
| Field | Role | Recov. | Avail. | Notes |
|---|---|---|---|---|
| forwardmove | A | **obs (pov)** / **none (mvd)** | pov | **Ground-truth only from QWD POV.** MVD: unrecoverable → held out (§6). |
| sidemove | A | obs(pov) / idm(mvd) | always | MVD: sign `= −sign(yaw_rate)`, magnitude prior, **gated hspeed ≥ 400** (≈90% reliable); below gate `is_interp=1`. |
| upmove | A | obs(pov) / idm(mvd) | always | jump-conditional for MVD. |
| buttons (jump=2, attack=1) | A | obs(pov) / idm(mvd) | always | MVD jump = onground TRUE→FALSE transition w/ upward intent. |
| cmd_yaw, cmd_pitch, cmd_roll | A | obs(pov) / der(mvd) | always | QWD: true commanded angles; MVD: view-angle proxy. |
| label_source, confidence, is_interp, align_shift | M | — | always | provenance + hold-out keys (§6). |

### 3.3 All-actors omniscient state — `actor_ticks` (+ `actor_visibility`, §5)
Per `(episode, tick, actor_id)`: full kinematic state (3.1) **for every player**, plus
`team_id` [C], `alive` [C], `health`/`armor`/`armor_type`/`weapon` [C/E]. This is the raw material
for threat context [C] and is omniscient in MVD (PVS-broadcast; ~99% coverage in competitive demos).
**Status (v1): POPULATED, T4 (#392)** — the MVD ETL writes every player's state per ego-episode tick
from the same `-view full` decode (kinematics + forward-filled `h`/`a`/`at`→health/armor/armor_type +
`d`/`sp`→alive + the roster team_id). `weapon` stays NULL (no active-weapon source, as §3.4);
`onground`/`onground_is_proxy` stay NULL for observed-others (the geometric proxy lives on the ego
`player_ticks` spine).

### 3.4 Player status — health / armor / ammo / weapons / powerups [C/E]

> **Binding rule (resolves the silent-omission risk).** A field is part of the **v1 binding
> contract** only if it has a **concrete catalog destination** — an existing column or table in
> `scripts/catalog_schema.sql`. A field without a destination is **PENDING** (§9), explicitly
> *excluded* from v1 — never silently "in the taxonomy." Adding a destination is a schema change that
> moves the field from PENDING→binding under change-control (§8). This makes "the next extraction
> silently omits a field while looking compliant" impossible: omission of a binding field is a
> coverage-audit failure (§7); a PENDING field has no v1 obligation.

| Field | Role | Recov. | Status (v1) | Catalog destination |
|---|---|---|---|---|
| health, armor | C | obs | **binding** (**populated, T3** — MVD) | `player_ticks.health/armor` — MVD ETL forward-fills the per-tick value step-timeline |
| armor_type (GA/YA/RA) | C | obs | **binding** (`player_ticks` unpopulated; `actor_ticks` **populated, T4**) | `…armor_type` — the `-view full` per-player `at` ('ga'/'ya'/'ra') step-timeline → 0/1/2 fills `actor_ticks.armor_type` (T4). The ego `player_ticks` path (a separate `-event-types armor` decode) lacks the skin/type → still NULL there (derive / unify, T7) |
| active_weapon | C/E | obs | **binding** (unpopulated) | `…weapon` — column exists; the per-tick weapon stream is gain/lose INVENTORY, not STAT_ACTIVEWEAPON — no honest active-weapon source without a decoder change (deferred) |
| ammo: shells, nails, rockets, cells | E | obs | **binding** (**populated, T6** — MVD) | `player_ticks`/`actor_ticks.shells/nails/rockets/cells` — MVD ETL forward-fills the `-view full` per-player `sh`/`nl`/`rk`/`cl` step-timeline onto each tick (T6, #394) |
| powerups: quad, pent, ring (remaining seconds) | C/E | obs | **binding** (**populated, T6** — MVD) | `player_ticks`/`actor_ticks.quad_rem/pent_rem/ring_rem` — remaining-SECONDS derived from the `-view full` per-player `q`/`pe`/`r` held-interval `[s,e]` at each tick (T6, #394); NULL when not held (never 0). The feature layer applies the registry `/60,/300,/60` norm |

Source (wire): `svc_updatestat` STAT_HEALTH / ARMOR / ACTIVEWEAPON / SHELLS / NAILS / ROCKETS / CELLS /
ITEMS (+ entity skin for armor type). **health/armor are now populated** on `player_ticks` by the MVD
ETL (T3, #391): a second best-effort decode `-view events -event-types health,armor` yields per-player
absolute value step-timelines, forward-filled onto each tick by demo-time. `armor_type` and
`active_weapon` **remain unpopulated** — the per-tick event streams carry the AP value but neither the
armor skin/type nor the active-weapon id (its weapon events are gain/lose inventory) — tracked by §7.

### 3.5 Items / economy timeline — `items`, `item_events` [E/I]
Static `items` (type, origin, respawn_seconds, static_value, nearest_marker) — POPULATED
(`data/catalog/item_catalog.dm3.json`). `item_events` (pickup/respawn/drop, t_s, player, type) —
**POPULATED, T4 (#392)**: the MVD ETL writes the `-view full` `items.items[].phases[]`
(pickup at `takenAt`/`takenBy`/`team`, respawn at `respawnAt`) joined to `items.item_id` by origin,
plus `backpacks` drops (NULL item_id, kept origin). Respawn-ETA + contest features per
`00-DATA-ARCHITECTURE.md` §3.3–3.4 (item-urgency [E], feeds [C] filtering).

### 3.6 Combat events — frags / deaths / damage [C]
`frag_events` (chronological, killer/victim/weapon, suicide/teamkill), deaths (deduped: STAT_HEALTH +
DF_DEAD + obituary), `damage_events` (per-hit attacker/victim/weapon/amount/splash, **era-gated** to
~2024+ KTX demos). **Status (v1): both binding — `frag_events` (schema-defined, **POPULATED, T4 #392**)
and `damage_events` (schema-defined, **POPULATED, T5 #393**, era-gated).** The `frag_events` table is
filled by the MVD ETL from the `-view full` top-level `frags.frags`
(`time`/`killer`/`victim`/`weapon`/`isSuicide`/`isTeamKill`) — NOTE the discrete `-view events`
frag/death streams are degenerate (score-delta / victim-only) and are NOT the kill source. `damage_events`
is filled from the `-view full` top-level `damage.events`
(`time`/`attacker`/`victim`/`weapon`/`damage`/`isSplash`/`isEnv`/`isSelf`/`isTeam`; attacker/victim NULL
for environmental `world`/fall/drown). It is **era-gated and fail-closed**: per-hit damage is the KTX
hidden `mvdhidden_dmgdone` block, present only in ~2024+ demos, so a per-demo `demos.damage_available`
flag records whether the block was present — TRUE means the stream is authoritative (0 rows = genuinely
zero damage), FALSE means the demo predates the block (damage **UNKNOWN**, never read as zero; no rows
emitted). Verified empirically on the real 4on4 book_vs_mix MVD (schema-33, sha 6954ffb6): the block is
present (2868 hits). The movement pillar uses these only to **filter** clean-movement segments (§6,
fail-closed on unknown damage); they are the combat pillar's core.

### 3.7 World / movers / static — `maps`, `markers`, `nav_edges`, movers
Map AABB + physics constants (`maps`); Frogbot nav graph (`markers`, `nav_edges` — POPULATED);
movers (lifts/doors) per-frame origin (entity deltas — not populated). Static map geometry from
`dm3.bsp` (sha-locked) drives [G] (§5).

### 3.8 Meta / provenance [M]
Per demo: sha256, size_bytes, decoder binary sha + schema version, source (mvd/qwd), map, players,
teams, demo start wall-clock, pauses, server cvars, split + split_policy. Per row: label_source,
confidence, is_interp, onground_is_proxy.

### 3.9 Coverage table (the completeness guarantee)
The spec is complete **iff** every field the decoder's Result schema produces is accounted for here
as **extracted** / **derived** / **excluded-with-reason**. The coverage audit (§7) diffs the live
catalog against the decoder Result inventory (the in-house analyzer's `mvd-analytics/result/*` +
`RESULT_SCHEMA.md`; see Appendix A / `docs/02_SOURCE_MAP.md`) and emits a per-field table. **Excluded-with-reason examples:** `svc_sound`
details (not movement/economy relevant), temp-entities (projectile FX; rocket *positions* are
derivable if needed — reserved §9), lightstyles/muzzleflash (cosmetic).

---

## 4. Fidelity contract (RESOLVED — fidelity experiment, 2026-06-24)

**Why this is a contract, not a footnote.** QW air-acceleration integrates `wishdir=f(yaw)` **once
per physics frame** (no sub-stepping; `pmove_sim.py`). If the corpus sample rate is **coarser** than
the physics the human executed, the sim cannot reproduce — or a model learn — the true
high-frequency air-strafe. This is physics fidelity, not smoothing.

**Known (audit):** MVD ≈ 72–77 Hz (`msec` ≈ 13–14 ms); `pmove_sim` integrates `dt = msec·0.001`;
yaw/sidemove/jump are **step-held** (no temporal interpolation anywhere). Step-held-per-frame is what
the real engine does, so the open question is **rate alignment**, not smoothing.

### 4.1 Experiment (N=5 dm3 POV `.qwd`, `pmove_sim` anchored per-step replay)

Two halves on the **same** 5 demos (`laker__sc-sk`, `paradoks__e_vs_{bad,code,tdi}`,
`paradoks__goldens_e_vs_4x`), measured as **anchored per-step horizontal-speed error in the bhop
regime** (recorded `hspeed ≥ 400 qu/s`) — reset the sim to the recorded state each frame, step one
cmd, compare `sim_vh` to the recorded next-frame speed. Anchored isolates per-step action fidelity
from open-loop compounding.

1. **Ground-truth half** — replay the **real QWD usercmds** (true forwardmove + true viewangles).
   Per-step bhop speed error **0.5 / 1.2 / 2.0 / 2.3 / 3.1 qu/s** (the 5 demos) = **<1 % of speed**.
   Anchored per-step origin err ~0.5–1.6 qu. → `pmove_sim` reproduces real human bunnyhop speed
   essentially exactly; the inputs are already **at** the physics rate (1 usercmd / frame).
2. **MVD-degradation half** — degrade the **same** inputs to the MVD/IDM representation
   (`forwardmove → 0`; `sidemove = −sign(yaw_rate)·400` gated `|yaw_rate| ≥ 20°/s`; jump from
   geometric-onground `T→F` with `vz>1`; yaw **angle16-quantized**, step-held — verbatim
   `catalog_etl_mvd.py`), keeping the exact MVD state. Per-step bhop speed error rises to
   **6.5 / 6.8 / 7.3 / 8.9 / 21.9 qu/s** = **3–14× the ground-truth**, but still only **~1.5–5 % of
   speed**. 1-second-horizon origin err ~65–96 qu (vs ground-truth 10–43). Worst on the *slowest*
   demo (laker, max 459, near the 400 gate); cleanest deep bhop (max 770–804) degrades least.

### 4.2 Contract (filled)

- **Canonical rate = native per-frame, ~72–77 Hz (1 usercmd / physics frame). No temporal
  resampling.** Both sources are consumed step-held at native rate (the engine's own input model);
  the QWD path is speed-faithful at it.
- **QWD ↔ MVD alignment:** QWD = ground-truth usercmd per client frame; MVD = server snapshot per
  ~13 ms frame. Consumed at native rate, **no cross-resampling** (the alignment that mattered for
  route *replay* is action↔state time-base matching, not up-sampling — `alignment="time"`).
- **Velocity derivation:** decoder central-difference, used as-is — the ~0.5–1.6 qu anchored origin
  err confirms the state stream is physics-consistent.
- **Resample / interpolation policy → NOT NEEDED.** The MVD's extra error is **representational, not
  temporal**: forwardmove is unrecoverable (set 0), analog strafe magnitude collapses to ±400-sign,
  yaw quantizes to angle16, and geometric-onground undercounts fast re-hops. **None of these is a
  sampling-rate deficit, so resampling cannot recover any of them.** The earlier "interpolation was
  the key" intuition is correct *in principle* (it matters when the control signal is coarser than
  the physics) but does **not** apply here — the corpus is already at the physics rate.

### 4.3 Consequence for method (why this is recorded here)

The MVD **state** (origin / velocity / view) is omniscient and exact; only the **IDM-recovered
actions** carry the 3–14× noise. So: (a) direct action-cloning on MVD labels inherits a 3–14×
action-label noise floor vs ground truth — consistent with the supervised family's closed-loop speed
stall; (b) the MVD corpus's durable value is as an **exact state-distribution**, best consumed
**observation-only** — scoring `(s, s')` transitions (no action labels), which sidesteps the IDM loss
entirely; (c) the 548 QWD POV demos remain the **ground-truth action oracle** whenever forwardmove or
analog magnitude is genuinely required. This is a property of the data, not of any one method.

> Reproduce: `scripts/fidelity_mvd_degradation.py <demo.qwd> 4000 <dm3.bsp>` (the 548 POV `.qwd`
> live on servexeri `/mnt/usb-ssd/4on4-corpus/challenge-tv-pov-dm3/`); the degradation mirrors
> `catalog_etl_mvd.py` IDM recovery verbatim.

---

## 5. Derivation specs (computed once, stored in the catalog)

Reference `00-DATA-ARCHITECTURE.md` §2 (geometry/nav), §3 (items) where covered; this fills the gaps.
All geometry uses the sha-locked `dm3.bsp` via the existing trace primitives in `pmove_sim.py`
(`player_trace`, `_recursive_hull_check`, `hull_point_contents`, `derive_onground`).

- **[G] map geometry (BINDING + POPULATED — T7 #395):** distance-to-nearest-wall (`wall_dist`, min of
  the 4 axial ±x/±y hull-1 traces, capped at 512 qu), ledge-ahead (`ledge_ahead`, forward+down trace
  drop along velocity), ramp/incline (`ramp_normal_z`, the floor-trace plane `normal.z`; <0.95 = ramp),
  floor-height-below (`floor_height` = z − downward-trace floor z; matches `trace.csv`/`build_trace.py`
  `height_above_floor`) + `over_void` (no floor within 4096 qu, OR floor < −200 qu deep-chasm — the
  `build_trace.py` rule). All via the `pmove_sim.player_trace` hull-1 machinery against the sha-locked
  `dm3.bsp` (the SAME `WorldModel` the onground prober already loads per worker — no second BSP load).
  Stored as `player_ticks` **and** `actor_ticks` columns; NULL where the trace starts in solid / over a
  void (undefined, never fabricated). *Why:* makes a trick-jump interpretable (you strafe *toward* a
  ledge). Jump-pad/teleporter proximity stays reserved (Frogbot `markers.is_teleport` join — §9).
- **[R] regime (BINDING + POPULATED — T7 #395):** `regime` ∈ {accel `<400` / cruise `≥400` (the IDM
  gate) / grounded / airborne / water / on-ramp}, from `hspeed` + (geometric) `onground` + the [G]
  `ramp_normal_z` (priority water > airborne > on-ramp > cruise/accel). MVD has no waterlevel so `water`
  never emits for MVD (honest). Stored on `player_ticks` + `actor_ticks` (the actor regime uses a local
  geometric onground; the `actor_ticks.onground` column itself stays NULL by T4 design).
- **leg-phase (BINDING + POPULATED — T7 #395):** `leg_phase` ∈ {launch / cruise / approach / land},
  segmented from the #334 `route_legs.py` resource-to-resource legs (position-based visits) on the
  per-leg hspeed profile + onground (cruise = the contiguous ≥400 band; launch = the build-up before
  it; land = the trailing grounded arrival; approach = the decelerating glide between). Per-tick label
  on the ego goal-conditioned `player_ticks` spine; **NULL on `actor_ticks`** (observed others have no
  ego goal/route context) and NULL on ego ticks outside any leg.
- **[C] threat / line-of-sight (BINDING + POPULATED — T8 #396):** `actor_visibility` is now derived
  + populated per (episode, tick, ego-observer, target). **FOV** (`in_fov`) = target bearing/pitch
  within the observer awareness cone (reuses `scripts/features/egocentric.py` `rel_bearing_deg`/
  `rel_pitch_deg`; a generous 90° forward-hemisphere half-angle — LOS is the real gate, FOV only
  drops targets behind the observer). **LOS** (`los_clear`) = a hull-0 point ray observer-eye→
  target-eye (both lifted the QW view height **22 qu** above origin) via `pmove_sim`’s
  `_recursive_hull_check` against the sha-locked `dm3.bsp`; clear iff the segment never enters solid
  (fraction==1.0). **PVS** is an OPTIONAL perf prefilter that is **NOT sourced** — `pmove_sim` parses
  BSP leafs/contents but not the visdata/PVS clusters, so `pvs_visible` is left **NULL** (“not
  prefiltered”, never a fabricated boolean) and `is_visible = COALESCE(pvs_visible, TRUE) AND in_fov
  AND los_clear` — LOS is the correctness gate. The **belief block** (`last_seen_{tick,t_s,o*,v*}`,
  `time_since_seen_s`, `seen_ever`) carries forward the last-seen snapshot while the target is
  invisible (0 while visible, NULL before ever seen — 3-state, never a sentinel). `vis_angle_source =
  'demoparser'` (schema-33 carries real per-tick view yaw/pitch). Used to **filter** clean-movement
  segments (§6.5), not (yet) as a movement input.
- **[E] item-urgency (BINDING — T8 #396):** respawn-ETA-on-arrival + contest, per
  `00-DATA-ARCHITECTURE.md` §3.3–3.4, from `items.respawn_seconds` + `item_events` (both populated).
  These are the `source: derived` registry features `item_remaining_norm` / `item_eta_norm` /
  `item_up_on_arrival` / `item_value_prior` — DERIVED at materialization from the populated source
  tables (PIT-safe: only pickups at-or-before `t_now`), **not** new columns. The derivation lives in
  `scripts/catalog_etl_mvd.py` (`item_respawn_at` / `item_urgency`); unobserved respawn = the 3rd
  `unknown_flag` state (mask `remaining_norm`, never a sentinel).

---

## 6. Hold-out / leakage / provenance rules (formalized)

Reference `00-DATA-ARCHITECTURE.md` §7 (splits, leakage, versioning); this makes the per-field gates
explicit and normative:

1. **forwardmove from MVD is `none`-recoverable → NEVER a training target.** Only `label_source =
   'qwd_usercmd'` forwardmove is ground-truth. (The asymmetry is the whole reason for the two-source
   design.)
2. **Every IDM (`idm`) action row is held out** (`is_interp = 1`) until a per-head weight scheme
   re-enables the trustworthy heads (jump, in-regime strafe-sign). Below-gate strafe rows
   (`hspeed < 400`) stay `is_interp = 1` regardless.
3. **Believability gates are eval-only.** `scripts/gmv_believability.py` (G-MV1/3/4) and the human
   envelope `references/dm3_4on4_anchors.json` are **judge** signals; they never enter a training
   reward/loss (anti-Goodhart). Any reward "human band" reads a **disjoint reward-leakage split**,
   never the gate anchors.
4. **Splits are by whole demo** (`episodes.split` / `split_policy`); normalization stats fit on the
   TRAIN split only, frozen (`00` §6.2). No window crosses an episode boundary (`00` §5.2).
5. **Clean-movement filter (definition, FAIL-CLOSED on unknown).** A segment is *clean* (eligible for
   the human movement prior/characterization) iff, across it, **(a)** no enemy is within `THREAT_R` qu
   with line-of-sight, AND **(b)** the player is *provably* not taking or dealing damage. Threshold
   `THREAT_R` and the window are spec parameters set in Phase B.
   - **Unknown ≠ clean (fail-closed).** Because per-hit damage is era-gated (§3.6), a demo without a
     `damage_events` source has **unknown**, not *absent*, damage. The catalog makes this distinction
     explicit and machine-readable via **`demos.damage_available`** (T5 #393): TRUE => the per-hit
     `damage_events` stream is authoritative for that demo (no rows in a window = *positively zero*
     damage); FALSE/NULL => the demo predates the KTX damage block, damage is **unknown**. A segment
     whose damage state cannot be **positively established as zero** in the same plane and window —
     whether from `damage_events` (only trustworthy when `damage_available` is TRUE) or another named
     same-plane source (e.g. a verified health-drop / KTX scoreboard reconciliation) — is treated as
     **NOT clean** and excluded from prior construction. Absent `damage_events` (or `damage_available`
     not TRUE) is never read as "no damage."
   This keeps combat/evasion segments (and era-gated-unknown segments) out, so the prior learns
   technique, not evasion.
   - **Implementation (T8 #396).** `scripts/catalog_etl_mvd.py` `tick_is_clean(...)` is the
     predicate. (a) is fed the distances of enemies that ALSO have line-of-sight this tick (from the
     T8 `actor_visibility` layer — an enemy behind a wall is not active combat); (b) is fail-closed:
     `damage_available is not True` returns `(False, "damage_unknown_fail_closed")` BEFORE any
     event check, so a pre-era demo can never be certified clean. `THREAT_R`/`damage_window` are the
     documented `CLEAN_THREAT_R_QU` / `CLEAN_DAMAGE_WINDOW_S` defaults (Phase-B-tunable constants).

---

## 7. The data deliverable (format, completeness, durability, validation)

- **Storage = the relational catalog (SQLite), source of truth.** Tables (`scripts/catalog_schema.sql`,
  19 tables — all defined; the 4on4 ones below are schema-defined, several populated by tickets):
  `demos`, `players`, `teams`, `maps`, `markers`, `nav_edges`, `items`, `item_value`,
  `episodes`, `player_ticks`, `actor_ticks`, `actions`, `feature_partitions`, `actor_visibility`,
  `audio_cues`, `frag_events`, `damage_events`, `region_control_timeline`, `item_events`. The
  derived [G] geometry / [R] regime / leg-phase columns now live additively on `player_ticks` +
  `actor_ticks` (T7 #395 — no new table). Optional per-consumer **parquet** export; SQLite remains
  canonical.
- **Raw-maximal principle:** store observed + finite-diff + geometry-derived; do **not** store
  model-specific normalized obs (those are built downstream from `feature_registry.yaml`).
- **Completeness method:** the coverage audit (§3.9) diffs the populated catalog against the decoder
  Result inventory → a committed **coverage report** (extracted / derived / excluded-with-reason).
  **Current state:** the movement slice plus the §3.3/3.5/3.6 omniscient world are populated — T3
  filled `player_ticks.health/armor`, and **T4 (#392)** filled `actor_ticks` (all-players state +
  health/armor/armor_type + team_id + alive), `item_events`, `frag_events`, and `teams` from the MVD
  `-view full` decode; **T5 (#393)** added + filled `damage_events` (per-hit attacker/victim/weapon/
  amount + splash/env/self/teamkill flags) from the `-view full` `damage.events`, era-gated via
  `demos.damage_available`; **T6 (#394)** added + filled the ammo (`shells/nails/rockets/cells`) +
  powerup-remaining (`quad_rem/pent_rem/ring_rem`) source columns on `player_ticks` + `actor_ticks`
  from the same `-view full` per-player streams; **T7 (#395)** added + populated the derived [G]
  geometry (`floor_height/over_void/wall_dist/ledge_ahead/ramp_normal_z`), [R] `regime`, and
  `leg_phase` columns on `player_ticks` + `actor_ticks` (geometry from the sha-locked `dm3.bsp`
  hull-1 traces; regime from kinematics; leg-phase from the #334 route-leg segmentation — `leg_phase`
  NULL on `actor_ticks`); **T8 (#396)** derived + populated the POMDP `actor_visibility` layer
  (per (episode, tick, ego-observer, target) FOV + hull-0 LOS raycast + carried-forward belief, with
  `pvs_visible` NULL — PVS not sourced, see §5 [C]) and wired the [E] item-urgency + §6.5
  clean-movement filter derivations. Still defined-but-empty: **`audio_cues`** (the other T8 derived
  layer, not in #396). The report makes the remaining (defined-but-empty / derived) gaps explicit and
  tracked.
- **Durability:** every demo sha256 + size; decoder binary sha + schema version; spec id (§8);
  canonical on servexeri (~GB, not git, not aws-dev); only the summary + coverage report + this spec
  are committed.
- **Validation gates:** FK integrity (`PRAGMA foreign_key_check`); field-coverage vs inventory;
  hold-out intact (MVD forwardmove absent from trainable; `idm` rows `is_interp=1`); fidelity
  reproduced (§4, QWD replay + velocity oracle); QWD↔MVD cross-check on calibration-set games;
  per-source frame-coverage threshold (drop demos below it, log the drop — no silent truncation).

---

## 8. Versioning & durability

- **Spec id `komodobots.demo-extraction.v1`.** **Additive rule:** new extractable fields **append**
  (new columns / new tables / new role rows) and bump the minor version; they never restructure
  existing fields. A breaking change (field removal, unit change, retype) requires **v2** + a
  migration note in `docs/08_DECISION_LOG.md`, flagged ≥30 days ahead where it affects committed data.
- **Durable home:** this doc in `docs/`, registered in `docs/02_SOURCE_MAP.md` + the evidence chain
  (`docs/21_ML_EVIDENCE_CHAIN_GATE.md`); the binding schema is `scripts/catalog_schema.sql` +
  `data/catalog/feature_registry.yaml`; provenance per §2. The plans live in `plans/` (committed).
- **No tool names in the contract** — decoders referenced by role + binary sha + schema version, so a
  rename of the analyzers does not break the spec.

---

## 9. Pending / expected fields (reservation for the analyzer-extension track)

The decoders are being extended to emit more fields (parallel track). This section **reserves slots**
so new output lands additively (§8) without redesign. Each, once the decoder emits it, becomes a §3
row + a catalog column with the same metadata discipline:

- **[K] richer self:** explicit on-wire velocity (if a future schema carries it, replacing finite-diff
  → upgrades fidelity §4); per-frame waterlevel/onground for MVD (today MVD-NULL).
- **[E] ammo/powerups:** `player_ticks`/`actor_ticks.shells/nails/rockets/cells` +
  `quad_rem/pent_rem/ring_rem` columns exist in the schema and are **populated** (T6 #394) from the
  `-view full` per-player `sh/nl/rk/cl` step-timelines (forward-filled) and `q/pe/r` held-intervals
  (remaining-seconds; NULL when not held) — no longer reserved. Genuinely reserved: a normalized
  powerup-interval *table* (per-pickup span rows), if a consumer needs spans rather than per-tick
  remaining. PENDING.
- **[C] combat tables:** `frag_events` (T4 #392) and `damage_events` (T5 #393, era-gated via
  `demos.damage_available`) both exist in the schema and are **populated** — no longer reserved.
  Genuinely reserved (no table yet): weapon-fire events; projectile (rocket/grenade/nail) tracks
  (derivable from entity origins). PENDING.
- **[C] damage/economy coverage:** per-hit damage on older (pre-2024) demos if a future decoder
  recovers it (would relax the fail-closed exclusion of §6.5 for those demos).
- **[C] visibility / POMDP:** `actor_visibility` is **populated** (T8 #396 — FOV + hull-0 LOS +
  belief; `pvs_visible` NULL, PVS not sourced). Genuinely reserved: a BSP visdata/PVS-cluster decoder
  to fill `pvs_visible` as a real prefilter (perf-only; LOS already gates correctness), and the
  `audio_cues` derived layer. PENDING.
- **[E] items:** `item_events` populated from `-view full` item phases + backpack drops (T4 #392); the
  respawn-ETA / contest derivation is wired (T8 #396 — `item_respawn_at`/`item_urgency`, the
  `source: derived` registry features). Remaining reserved: weapon-pickup effectiveness joins.
- **[A] actions:** wider QWD POV coverage (more matched MVD↔QWD pairs) → larger ground-truth +
  calibration set.
- **[M]:** decoder-emitted frame-coverage / drop diagnostics.

When the new data arrives: add the §3 rows, extend `catalog_schema.sql` + `feature_registry.yaml`,
re-run the coverage audit (§3.9), bump the minor version (§8). **No re-parse of already-extracted
fields is required** — that is the point of this spec.

---

## Appendix A — full wire/decoder inventory reference

The "everything extractable" master list (diffed against in §3.9) lives in the **in-house MVD/QWD
analyzer source tree** — see `docs/02_SOURCE_MAP.md` for its canonical checkout location and pinned
commit (referenced by role + commit, not a machine-specific path). Within that tree, the relevant
modules are: the **wire layer** `mvd-reader/` (`parser/*`, `MVD_FORMAT.md`); the **decoded Result
schema** `mvd-analytics/result/*` (`result.go`, `streams.go` `PlayerStream`/`PositionTrack`,
`damage.go`, `items.go`, `frag.go`) + `RESULT_SCHEMA.md`. The QWD usercmd layout is in this repo at
`tools/qwd_usercmd/qwd_usercmd.py`. These are the authority for what a demo physically carries; §3 is
the contract for what we extract from it.
