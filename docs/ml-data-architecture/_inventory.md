# KomodoBots — Existing Data Substrate Inventory

**Repo:** `C:\Users\benya\projects\komodobots\`
**HEAD inventoried:** `a518435` — "LD-F4 #103: multi-bot live 3D — per-bot labels, click-to-select, overview camera (#144)"
**Date:** 2026-06-18
**Stack rule:** everything is **stdlib-only Python 3.12**; the deliverable of any change is *evidence* (JSON/Markdown artifacts), not features. Raw artifacts (demos, parser dumps, per-run dirs) live outside Git under `artifacts/` (gitignored); small derived summaries are promoted into Git under `experiments/<name>/evidence/`.

This document inventories what data already exists, with real paths, schema names, field names, units and example values. It is descriptive (what *is*), not prescriptive.

---

## 0. The 36 versioned schema names (the de-facto data dictionary)

Every artifact type carries a `komodobots.<name>.vN` schema string. Grep over the repo yields the full set (this *is* the existing data dictionary):

```
air_transition_probe_design.v1   air_transition_probe_result.v1   air_transition_probe_source.v1
airborne_proxy_segments.v1       bunnyhop_fingerprint.v1          cadence_evidence_broadening.v1
cadence_normalization_decision.v1 context_gated_air_transition_probe_design.v1  controller_probe_target.v1
human_mvd_analysis.v1            human_mvd_inventory.v1           land_speed_gap.v1
maps.v1                          movement_metrics.v2              moveprobe_plausibility.v1
moveprobe_qwd_events.v1          player_movement_signatures.v1   qwd_frogbot_route_mapping.v1
qwd_route_probe.v1               qwd_sng_hybrid_probe_design.v1   qwd_sng_hybrid_probe_result.v1
qwd_sng_mvd_crossings.v1         qwd_sng_probe_diagnosis.v1       qwd_sng_slow_success_diagnosis.v1
qwd_usercmd.v1                   records.v1                       reference_aggregate.v1
replay.v1                        replay_build.v1                  replay_score.v1
route_edge_geometry.v1           route_state_attribution.v2       route_state_diagnosis.v1
routes.v1                        verdicts.v1 / v2
```

Note: schemas are *string tags inside JSON*, **not** enforced by any schema registry/validator. Versioning is manual (e.g. `movement_metrics` is at v2, `route_state_attribution` at v2; everything else v1).

---

## 1. Demo → data pipeline as it exists today

There are **two distinct demo sources** feeding two parallel pipelines, plus an offline physics sim. The headline limitation drives the whole design: **server MVDs record state, not inputs.**

### 1a. Server-side MVD pipeline (state/evaluation evidence)

Used for bot-generated MVDs and human 4on4 reference demos.

1. **Generate / acquire** an `.mvd`.
   - Bot side: `scripts/run_bot_lab.py` → `scripts/run_frobodm2_lab.py` SSHes to **servexeri**, starts a temporary MVDSV/KTX+Frogbots screen session on a lab port (28599–28609), drives bot spawning via the minimal QW client shim `experiments/qw_min_client.py` (`botcmd addbot`), runs a fixed-duration movement experiment, records the MVD, copies it back to `artifacts/lab-runs/<run-id>/demo.mvd`.
   - Human side: `scripts/analyze_human_mvd.py` inventories/copies a selected demo into `artifacts/human-demos/<run-id>/`. Reference demos are pulled from the existing `servexeri:/mnt/usb-ssd/4on4-corpus/` (manifest.tsv, 6409 rows) — **NOT** from hub.quakeworld.nu (deliberate no-hub-mass-download rule).
2. **Parse** with the Go MVD analyzer in WSL: `~/qw-sim/bin/qw-analyze-v20` (the practical binary; source is `mvd_analyzer` at `C:\Users\benya\projects\quakeworld\tools\mvd_analyzer`, commit `fab7808`; a prebuilt `~/mvd-mcp-bundle/` exists from commit `7d83ebe` — **the two differ and are unpinned**, an explicit open risk).
   - `qw-analyze-v20 -format json` → `analysis.json` (match summary; the canonical smoke artifact)
   - `-format md` → `analysis.md`
   - `-format events` → `events.txt` (line-delimited JSON event stream). **Always exits 1 with `qw-analyze: end of demo`** — this is accepted as long as `events.txt` is written and json/md exit 0.
3. **Extract metrics** with `scripts/extract_movement_metrics.py`. Position source: `events.txt` rows with `kind:5` carrying `PlayerNum`, `Origin`, `TimeMs`; player names from `kind:1` rows. Samples clamped to `analysis.json` `match.duration`. → `movement-metrics.json` (`komodobots.movement_metrics.v2`).
4. **Append findings** to `docs/07_FINDINGS_LOG.md`.

**The "demos store state, not inputs" issue:** documented at length in `docs/03_MOVEMENT_PROBLEM.md` and `docs/06_DATA_AND_MVD_PIPELINE.md`. Server broadcast/MVD path (`ezquake src/sv_ents.c`) zeroes normal movement intent, so MVDs give position/velocity/angles/health/items/frags but **no `forwardmove`/`sidemove`/`upmove`/buttons/jump-timing**. The framing is therefore **inverse control**: "observed movement trace → infer a legal command policy that reproduces it inside the real server loop." They do **not** recover human inputs from MVDs.

### 1b. QWD POV pipeline (the action-label exception)

First-person `.qwd` POV demos *do* carry the client's outgoing `usercmd_t` as `dem_cmd` records. This is the only source of exact human action labels.

1. **`tools/qwd_usercmd/qwd_usercmd.py`** (`komodobots.qwd_usercmd.v1`) walks the QWD, decoding the 24-byte `usercmd_t` (`struct "<BxxxfffhhhBB"`: byte msec, 3 pad, float angles[3], short fwd/side/up, byte buttons, byte impulse) plus the trailing 12-byte viewangle payload. Source-grounded in ezQuake `cl_demo.c::CL_WriteDemoCmd` / qwprot `protocol.h`.
2. **`scripts/probe_qwd_route_applicability.py`** (`qwd_route_probe.v1`) pairs each `dem_cmd` action row by frame order with the self-player `svc_playerinfo` origin/velocity row (origin via `MSG_ReadCoord = short/8`), giving same-frame state+action. Also does continuity splits + waypoint downsampling at 64 qu spacing.
3. **`scripts/build_replay_command_file.py`** (`replay.v1` / `replay_build.v1`) fuses commands + anchored origin/velocity into a `.cmds` open-loop replay file (see §8), one line/frame.
4. **Alignment**: for the standalone bunnyhop/getspeed work, alignment between the cmd stream and state stream is captured in `alignment-meta.json` (`shift`, `offset_s`, `max_match_residual_s`, `dropped_cmd_indices`, interpolation-row exclusion). Interpolation/anomaly handling happens here.

### 1c. Offline physics sim (no server needed)

- `experiments/bunnyhop_mastery/sim/qwsim.py` — compact pmove port (air-accel 30-cap, jump=270, gravity 800, friction 4, maxspeed 320) for fast horizontal-speed theory checks.
- `scripts/pmove_sim.py` — **faithful** Python port of MVDSV `src/pmove.c` (reference C copy kept at `artifacts/pmove-validation/reference-mvdsv-pmove.c`), traces against the real `dm3.bsp` (hull 1 swept collision, hull 0 for water/contents). Replays a `.cmds` input stream through `run_frame()` to reproduce a trajectory with **no game server**. This is the en-masse controller-sweep substrate. Known limit: only worldmodel collided, no submodels/players.

### 1d. mvd-mcp analysis stack (available, largely UNUSED by komodobots)

A richer MCP stack exists (`mvd-mcp` tools: `getItems`, `getWeaponPickups`, `getBackpacks`, `getRegionControl`, `getLocGraph`, `getLocTable`, `getLocTrails`, `getFrags`, `getStateAt`, etc.). **A repo-wide grep for these tool names returns zero hits** in komodobots `.py`/`.md` — the project relies only on the `qw-analyze-v20` CLI `kind:5` position stream, not on the items/region/loc-graph endpoints. Doc 06 lists them under "available or expected signals" as a *wishlist*, not as wired-in data.

---

## 2. Every existing data artifact type + real schema

### A. `movement-metrics.json` — `komodobots.movement_metrics.v2`
Per-run, per-named-player derived movement metrics from `events.txt` kind:5 origin samples. Real fields (units in field names): `active_time_s`, `sample_count`, `avg_horizontal_speed_qu_per_s` (e.g. `248.464`), `max_horizontal_speed_qu_per_s` (+ time of max), `p50/p90/p95_horizontal_speed_qu_per_s`, `stationary_time_ratio` (<10 qu/s, e.g. `0.14`), `low_speed_time_ratio` (<100 qu/s), ratio above server MaxSpeed (~320), ratio above 400, path efficiency, vertical-motion time ratio, `airborne_proxy_time_ratio` (e.g. `0.345`), airborne-proxy run count + `jump_cadence_per_min` (= `airborne_proxy_count/active_time_s*60`, e.g. `43.901`), avg airborne-proxy duration, post-landing speed delta, dropped teleport/respawn segments >2500 qu/s. **All position-derived**; airborne fields are Z-motion *proxies*, not ground-truth grounded/jump state.

### B. `moveprobe-commands.json` — (parsed control-plane log; gated by `moveprobe_plausibility.v1`)
KTX moveprobe patch (`experiments/ktx_moveprobe/frogbot-moveprobe.patch`, applies to KTX `08807da`) emits `FBMOVEPROBE_CMD` console rows *immediately before* `trap_SetBotCMD(...)`, sampled. Carries final `msec`, view angles, `forwardmove`/`sidemove`/`upmove`, buttons, impulse — plus suffix diagnostic blocks:
- `diag=route_yaw,view_yaw,yaw_delta,backward` (S3e)
- `route=linked_marker,touch_marker,goal_ed,goal_marker,path_state,bot_state,blocked,dir_speed` (S6b)
- `water=waterlevel,watertype,flags,swim_arrow,emitted_upmove,velocity_xyz,dir_move_xyz` (S6d)
- `probe=active,on_ground,since_ground,since_air,scale` (S7j mode 8)
- `qwd=active,index,count,distance,advanced,complete,active_seconds` (mode 9)
This is the closest thing to an **action record for bots** — the intended command values that reached the syscall (NOT what MVDs can see). Matched to movement rows by `user_id`→`ed`, falling back to netname.

### C. `moveprobe-qwd-events.json` — `komodobots.moveprobe_qwd_events.v1`
Unsampled `FBMOVEPROBE_QWD_EVENT` rows on QWD activate/advance/complete edges: server time, ed/name, event kind, reached/next target index, control-point count, distance, advanced count, active/complete flags, active seconds, origin.

### D. `trace.csv` — per-frame replay trace (LD-D/records eligibility)
Header (22 cols): `i,t,x,y,z,vx,vy,vz,vh,onground,fwd,side,up,yaw,yaw_rate,dir_speed,floor_z,height_above_floor,over_void,dist_to_rl,replay_cursor,divergence_qu`. Example row 1: `1,7.331,-895.09,-129.39,-15.97,25.9,-23.8,0.0,35.2,1,320,0,0,275.2,-1774.2,0.0,-16.0,0.0,0,2572.0,2,0.4`. Units: x/y/z = qu, v* = qu/s, vh = horizontal speed qu/s, yaw = deg, yaw_rate = deg/s, dist_to_rl = qu, divergence_qu = qu (bot-vs-human). This carries the server clock used for record `event_t_s`.

### E. `trace_summary.json` (per lab-run + promoted under `dm3_sng_to_rl_observability/evidence/`)
Compact: `run_id`, `records` (e.g. 4042), `duration_s` (49.1), `max_vh` (496.8), `pct_onground` (29.9), `closest_dist_to_rl` (307.9 qu), `frames_over_void` (33).

### F. `*.cmds` — line-delimited per-frame state+input ("replay" format, `komodobots.replay.v1`)
Header comment: `# komodobots.replay.v1 demo=getspeed.qwd frames=2104 sha256=... fps=76.999`. **14 columns**: `msec ox oy oz vx vy vz pitch yaw roll fwd side up buttons`. Example: `13 -3452.750 3824.000 -488.000 0 0 0 8.2500 267.2709 0.0000 0 0 0 0`. Units: msec = ticks (~13ms @ 77fps), o* = qu, v* = qu/s, angles = deg, fwd/side/up = usercmd movement values, buttons = bitfield (jump = `&2`). Two flavors: human-derived (from QWD usercmd + anchored state) and bot moveprobe replay. Committed human route `.cmds` live at `experiments/nav_doctrine/evidence/replay/dm3_<route>.cmds` (11 routes: hilljump, mega_to_rl, mega_to_window, ra_jumps, ring_to_mega, rl_to_bridge, rl_to_ya, sng_jumps, sng_shortcut, sng_shortcut2, sng_to_rl).

### G. `<name>_features.json` + `<name>_summary.json` — bunnyhop sim feature tables
From `experiments/bunnyhop_mastery/sim/extract_features.py` over a `.cmds`. **No schema tag** (raw list/dict). See §3.

### H. `fingerprint-human-trick5.json` — `komodobots.bunnyhop_fingerprint.v1`
Single-trick movement fingerprint (see §7).

### I. Human comparison artifacts (`experiments/human_comparison/evidence/`)
- `human-demo-inventory.json` — `human_mvd_inventory.v1`: `demo_count`, per-demo `demo_kind` (1on1/2on2/4on4/tricks), `inferred_map` (filename-token heuristic), `name`, `path`, `relative_path`, `sha256`, `size_bytes`.
- `human-milton-s5a-summary.json` — `human_mvd_analysis.v1`: `comparison_context` (verdict strings like `same_map_human_reference_available`), `demo` block (sha256, size, map), `match` (`duration_ms` 1200013, `frag_count`, `map_title` "The Abandoned Base"), `movement_players[]` (each a movement_metrics.v2-shaped row: name, slot, sample_count, the speed/airborne/cadence fields).
- `player-signatures-s7a-dm3.json` — `player_movement_signatures.v1`: `feature_axes[]` each with `family` ∈ {land_speed, tempo_control, air_proxy, jump_cadence}, `field`, `interpretation` (e.g. `generic_human_vs_bot_land_speed_gap`), `bot`/`bot_relation`/`bot_rows`/`player_order` (range_position per player). Plus `evidence_summary` classifying axes into candidate_player_style / generic / reference_only.
- `reference_aggregate.v1`, `cadence-normalization-s7d-dm3.json` (`cadence_normalization_decision.v1`): per-bot `jump_cadence_per_min`, `jump_cadence_per_nonstationary_min`, `jump_cadence_per_non_low_speed_min`, `jump_cadence_per_airborne_proxy_min`, plus `decision.verdict` = `cadence_stays_diagnostic_not_controller_target`.
- `airborne-segments-s7f`, `land-speed-gap-s7g`, `controller-probe-target-s7h`, `air-transition-probe-*` (S7i/j) — the S7 evidence chain (`airborne_proxy_segments.v1`, `land_speed_gap.v1`, `controller_probe_target.v1`, `air_transition_probe_design/result/source.v1`).

### J. QWD-route / SNG probe artifacts (`experiments/qwd_route_probe/evidence/`)
`qwd_route_probe.v1`, `qwd_frogbot_route_mapping.v1`, `qwd_sng_hybrid_probe_design/result.v1`, `qwd_sng_mvd_crossings.v1`, `qwd_sng_probe_diagnosis.v1`, `qwd_sng_slow_success_diagnosis.v1`. Pairing coverage, waypoint sets, nearest-marker p50/p95/max (qu), `.bot` edge coverage, control-point advancement counts, activation timing vs MVD window.

### K. Route-state diagnosis/attribution (`experiments/ktx_moveprobe/evidence/`)
`route_state_diagnosis.v1`, `route_state_attribution.v2`, `route_edge_geometry.v1` — decoded path_state flags (`32768=WATER_PATH`, `524288=STUCK_PATH`), low-speed windows, `.bot` edge attribution (e.g. `276->59`).

### L. Standstill / a5 artifacts (`experiments/a5_distance_standstill/`)
- `alignment-meta.json` (cmd/state alignment, see §1b).
- `start-point.json`: `frame0` {origin[xyz], yaw, pitch}, `teleport_frames`, per-attempt `arrivals[]` {frame, t, origin, yaw, pitch}.
- `human-replay.json` (`replay_score.v1`-ish): `bsp`, `cmds`, `summary` {frames_simulated, first_divergence_frame, max_err/mean_err/p95_err (qu), reanchor_at, diverge_thresh}, per-`attempt` table {rows, lip_row, lip_origin, lip_vh, launch_heading_deg, jumped, jump_bit_at_lip, max_err_clean, landed_recorded, landed_sim}.

### M. Records / dashboard data (committed under `lab/dashboard/public/...`)
- `records.json` — `komodobots.records.v1` (built by `lab/server/records_build.py`, **published to servexeri, not committed**): per `(map,route,kind)` — `fastest_time`, `first_completion`, `peak_speed`, `edge_speed`, each with value + run id + demo URL + `event_t_s`; per-route aggregates `attempts/finishes/median_time_s/human_time_s`; census human reference beside every bot value.
- `routes/{dm3,dm2,frobodm2,trick,index}.json` — `routes.v1`: census stats + downsampled display polyline (~12.5 Hz) + gap markers + teleporters + provenance sha256.
- `maps/maps.json` + `.obj`/`.glb` — `maps.v1`: per-map BSP sha256, vertex/triangle counts, AABB `mins/maxs/center` (dm3 center `(532,88,40)`).
- `verdicts.json` — `verdicts.v1/v2`: human eye-test store (manual).
- `records-scoring.json` — `run-scoring.v1` (per-run cache, rebuildable).

---

## 3. Existing feature extraction

### From `experiments/bunnyhop_mastery/sim/extract_features.py` (over a `.cmds`, fps=77)
**Raw per-frame** (read from cols): `msec`, origin (ox,oy,oz), velocity (vx,vy,vz), `pitch/yaw/roll`, `fwd`(col10), `side`(col11), `up`(col12), `buttons`(col13).
**Derived per-frame** (the `_features.json` table): `t` (cumulative s), `hs` = hypot(vx,vy) qu/s, `vyaw` = view yaw col8 deg, `vhead` = velocity heading atan2(vy,vx) deg (only when hs≥80), `vyaw_rate` = central-diff unwrapped view-yaw rate deg/s, `vhead_rate` = velocity-heading rate deg/s, `lvm` = look-vs-move = wrap180(view_yaw − vel_heading) deg, `ssign` = strafe sign (+1 if side>50, −1 if side<−50, else 0), `jump` = buttons&2, `dist` = cumulative path length qu, `phase` ∈ {straight,turn} (windowed net velocity-heading rate, turn if ≥80 deg/s over ±0.30s, warm-up speed 400).
**Facet aggregations** (the `_summary.json`): A `yawrate_vs_speed` (binned 0–1100 qu/s, view_yawrate med/p90 + vel_headrate med); B `strafe_switch` (flip intervals med/p10/p90 s, sidemove_active_frac, typical |side|); C `jump_cadence` (n presses, hop_period med/p10/p90 s, jump_duty_frac); D `segments` (straight runs with `dvdx` = speed-gain-per-qu, turns with `net_angle`/`loss_pct`/entry/exit); E `look_vs_move` (per-phase mean/med/p10/p90 + frac where look-sign==strafe-sign).

### From the sims (`qwsim.py`, `pmove_sim.py`)
`hspeed`/`hs` = hypot(vx,vy). Physics constants (MV dict): maxspeed 320, accel 10, friction 4, stopspeed 100, gravity 800, jumpspeed 270, aircap 30. `pmove_sim.py` additionally produces full trajectory + `onground`, `waterlevel`, divergence vs recorded, collision fraction/plane normal.

### From `extract_movement_metrics.py`
The §2A movement_metrics.v2 fields — all from kind:5 position samples. Distinguishes raw (origin/time) from derived (speed percentiles, ratios, airborne *proxy*, cadence). The airborne/jump fields are explicitly **proxies** (Z-motion runs), not ground-truth grounded flags.

---

## 4. Existing normalization

Normalization today = **cadence re-normalization only**, and it is diagnostic, not a stored transform applied to a training set.

- `jump_cadence_per_min` baseline = `airborne_proxy_count / active_time_s * 60` (active-row normalized, NOT wall-clock).
- `scripts/decide_cadence_normalization.py` → `cadence-normalization-s7d-dm3.json` recomputes cadence under 3 alternative denominators, all stored per-bot-row in the artifact:
  - `jump_cadence_per_nonstationary_min` (basis: active time excluding `stationary_time_ratio`)
  - `jump_cadence_per_non_low_speed_min`
  - `jump_cadence_per_airborne_proxy_min` (basis: airborne-proxy time)
- Reference ranges are derived from the exact-player aggregate (Milton/carapace/yeti), and the bot value is classified `within/above/below range`. Verdict stored: `cadence_stays_diagnostic_not_controller_target`.
- `summarize_reference_aggregate.py` builds per-field reference **ranges** (min/max across exact-player rows) used to classify bot rows. Coordinate/feature **standardization (z-scoring, min-max scaling for ML)** does **not** exist anywhere. There is no feature-store, no fitted scaler, no persisted mean/std.

---

## 5. Positioning / map data

### Captured
- **Origin & velocity**: qu / qu/s, present in kind:5 MVD samples, `.cmds` rows, `trace.csv`, `svc_playerinfo` pairs. Raw Quake world coords throughout.
- **Map geometry meshes**: `lab/tools/bsp_to_obj.py` / `bsp_to_mesh.py` export BSP v29 worldmodel → `.obj`/`.glb` (`maps.v1`), with AABB `mins/maxs/center`. Used for the 3D dashboard and as collision geometry in `pmove_sim.py` (real `dm3.bsp`, hull 0 + hull 1). Source BSPs are NOT committed (game assets at `C:\nQuake\qw\maps\` / lab pool).
- **Frogbot marker/nav graph** (`.bot` files, e.g. KTX `dm3.bot`): markers with static `CreateMarker` origins (e.g. marker 59 at `[1329,-378,-24]`, zone 17, goal 5), explicit path edges (`276->59` idx 0 + reciprocal), zones. Exposed at runtime via the moveprobe `route=` suffix: `touch_marker`, `linked_marker`, `goal_marker`, `goal_ed`, `path_state` (bitflags), `bot_state`, `blocked`, `dir_speed`. Decoded by `attribute_route_state_windows.py`.
- **Route census geometry** (`experiments/nav_doctrine/evidence/trick-census/census.json`): per route — `arc_xy_total_qu`, `peak_speed`, `n_airborne_segments`, `turns_gt45`, `sharpest_turn_deg`, and rich **gap** records (see §6), `teleports` ({frame, jump_qu, from[xyz], to[xyz]}), `ledge_climbs` ({frames, z_gain}). `water_segments`/`boosts`/`bmodel_rides` arrays exist but are empty for sng_to_rl.
- **Void / floor**: `trace.csv` `floor_z`, `height_above_floor`, `over_void`; census `void_floor_z`, `pit_depth_qu`.
- **Distance fields**: `dist_to_rl` (qu to a goal item) in `trace.csv`; nearest-marker distances in QWD route mapping.

### Absent / weak
- **No nav graph as a queryable structured dataset** — marker graph is read ad-hoc from KTX `.bot` text and partially exposed only inside moveprobe logs. Marker 276 has *no* static origin in `dm3.bot` (blocks coordinate-level fixes).
- **No zones/regions dataset** beyond the per-marker zone integer; `getRegionControl`/`getLocGraph`/`getLocTable` MCP endpoints are unused.
- **No global distance-to-geometry / signed-distance field**; only point traces against BSP at sim time.

---

## 6. Resources (items) & timing

**Essentially absent in komodobots' active data.** The mvd-mcp stack exposes `getItems` / `getWeaponPickups` / `getBackpacks` / `getRegionControl` / `getLocGraph` / `getLocTable`, but **komodobots uses none of them** (zero grep hits). Doc 06 lists "item pickups, weapon pickups, ... powerup state, location trails, region control" as *expected* signals only.

What *does* exist item-wise:
- **Goal-item position as a single distance scalar**: `dist_to_rl` (distance to the RL pickup) in `trace.csv`/`trace_summary.json`, and `fixed_goal`/`spawn_origin` per-slot cvars. Records define "completion" via reaching `REACHED_RL`.
- **Census route endpoints are named after items** (mega_to_rl, ring_to_mega, sng_to_rl, rl_to_ya) but encode geometry/timing of the *route*, not item state. Per-gap `required_speed` (qu/s, ballistic), `human_speed_at_edge`, `margin` quantify the leap, not the pickup.
- **No respawn timers, no item-importance/value model, no pickup events** are represented anywhere in the data substrate. Frags exist (`analysis.json` frag events, census not item-aware).

---

## 7. Player-specific / style data (Milton groundwork)

Two distinct "signature" representations exist:

### `player_movement_signatures.v1` (`player-signatures-s7a-dm3.json`) — the cross-player axis scaffold
Dimensions ("feature_axes") that define a player's signature *today*, each classified by stability:
- **land_speed**: `avg_horizontal_speed_qu_per_s`, `p95_horizontal_speed_qu_per_s` → classified `generic_human_vs_bot_land_speed_gap` (not yet style-discriminating)
- **tempo_control**: `stationary_time_ratio`, `low_speed_time_ratio` (the latter is the one "candidate_player_style_axis_but_thin")
- **air_proxy**: `airborne_proxy_time_ratio` (too tight to discriminate)
- **jump_cadence**: `jump_cadence_per_min` (the strongest repeated axis, but bot relation is mixed)
Reference set = exact-player `dm3` rows for **Milton** (avg 314.2, p95 535.0, stationary 5.9%, low 12.4%, air 35.1%, cadence 44.9/min), **carapace** (282.8 / 524.9 / 11.5% / 19.6% / 34.2% / 44.0), **yeti** (291.5 / 505.8 / 7.5% / 15.4% / 35.9% / 48.6). Selected by Turso `player_games`/`games` metadata cross-referenced to the servexeri corpus manifest. Currently ~2 demos per player. Verdict so far: avg/p95 are generic gaps; no per-player controller justified.

### `bunnyhop_fingerprint.v1` (`fingerprint-human-trick5.json`) — single-run technique fingerprint
Richer single-trick profile: `hspeed` {peak 1087.6, p95 1058.5, p90, p50 880.2}, `accel_rate_qu_per_s2` {p50 44.4, p90, max}, `jump` {count 52, cadence_per_min 84.7}, `view_yaw_offset_deg` {p50 45.3, p90 119.0}, `turn_technique` {median_turn_rate_deg_s 145.0, median_moving_speed_qu_s, oscillation_radius_qu 353.8 + caveat, `speed_vs_turn_rate` binned table}, `path_shape` {net_rotation_deg, net_rotations, net_displacement_qu, path_length_qu, straightness, bbox_qu[]}, `speed_vs_distance` list.

These two are **not unified** — one is a cross-player style-axis comparison, the other a per-trick technique descriptor; no canonical "player profile" object joins them.

---

## 8. Action / label representation

Three representations of action/input data, **none of which come from server MVDs**:

1. **`komodobots.qwd_usercmd.v1`** (human, ground truth): per-frame `{frame, time_s, msec, view_angles[3], forwardmove, sidemove, upmove, buttons, impulse}`. From POV `.qwd`. Example ranges from a trick demo: msec 12–53, fwd −400..380, side −380..380, buttons {0,1,2,3}, impulse {2,7}.
2. **`.cmds` / `komodobots.replay.v1`** (state+action fused, the training-row format): `msec ox oy oz vx vy vz pitch yaw roll fwd side up buttons` — pairs the human commands with anchored origin/velocity by frame order. Frame 0 = snap state, every frame = divergence reference. This is the literal (state→action) row used for open-loop replay (KTX mode 10) and `pmove_sim.py` sweeps.
3. **Bot commands** = the `moveprobe-commands.json` `FBMOVEPROBE_CMD` rows (§2B) — the *intended* command that reached `trap_SetBotCMD`, with route/water/probe/qwd diagnostic suffixes.

**Confidence / alignment metadata** lives in `alignment-meta.json`: `shift` (frame), `offset_s`, `max_match_residual_s` (e.g. 0.006287), `ambiguous_matches_gt_half_frame`, `dropped_cmd_indices` (74 dropped of 2145), `n_interp_rows_excluded`, `anomalous_rows_excluded`. QWD route probe reports per-demo **paired coverage** (min/median 1.000 over the 29-demo dm3 corpus). The open-loop replay caveat: initial-condition-sensitive, QW air physics amplifies frame-0 mismatch — `divergence_qu` per frame + `first_divergence_frame` quantify it.

---

## 9. Storage tech currently in use

- **Plain JSON files** everywhere; many are **line-delimited JSON (NDJSON)** for streams (`events.txt`, qwd_usercmd output, moveprobe logs). Plus `.cmds` (space-delimited text) and `trace.csv` (CSV).
- **No SQLite / Parquet / DuckDB / feature store** anywhere in komodobots. (The only DB touched is external **Turso** + Hub Supabase for *demo-selection metadata* — `player_games`/`games` — never for the movement data itself.)
- **Directory convention**:
  - `artifacts/` — gitignored raw substrate. `artifacts/lab-runs/<run-id-UTC-timestamp>/` (e.g. `20260609T162916Z`) holds demo.mvd/.sha256/.size, analysis.json/.md, events.txt, movement-metrics.*, moveprobe-commands.*, trace.csv, trace_summary.json, run.env, lab.cfg, screen.log. `artifacts/human-demos/`, `artifacts/qwd-route-probe/`, `artifacts/replay/`, `artifacts/pmove-validation/`, `artifacts/trick-census/`.
  - `experiments/<name>/evidence/` — committed small derived summaries.
  - `tricks/dm3/` — committed human/bot reference `.mvd` demos (e.g. `dm3_sng_to_rl__<ts>.mvd`).
  - `lab/dashboard/public/{data/routes,maps}/` — committed dashboard feeds.
- **Versioning**: git for committed evidence; raw artifacts intentionally outside git. Determinism enforced for committed builders (LF-normalized, `-text` in `.gitattributes`, byte-lock tests). Run identity = UTC timestamp run-id. Provenance = sha256 + source path embedded in JSON. Schema = manual `vN` string tag.

---

## 10. Gaps, inconsistencies, pain points

1. **No ML-ready dataset / feature store.** Everything is per-run JSON scattered across `artifacts/<run-id>/` + `experiments/*/evidence/`. There is no consolidated table of (state, action, context) rows, no train/val split, no Parquet/DuckDB. `pmove_sim.py` is positioned as the "en-masse sweep substrate" but consumes one `.cmds` at a time.
2. **No fitted normalization for ML.** Only diagnostic cadence re-normalization exists; no persisted scaler/mean-std, no coordinate normalization, no map-relative framing.
3. **The action-label gap is structural, not solved.** Bots' action data (moveprobe logs) and humans' action data (qwd_usercmd) are *different sources* with different fidelity; server MVDs (the bulk of human reference data, incl. all Milton 4on4) have **no action labels at all**. Imitation is forced into inverse-control/open-loop-replay, which is initial-condition fragile.
4. **Parser version drift, unpinned.** WSL `~/mvd-mcp-bundle` (commit `7d83ebe`) ≠ local `mvd_analyzer` source (`fab7808`); `qw-analyze -format events` always exits 1. Doc 06 flags this as a regression-evidence risk.
5. **Rich item/region/loc-graph signals exist but are unused.** `getItems/getWeaponPickups/getBackpacks/getRegionControl/getLocGraph/getLocTable` are wired in the mvd-mcp stack but **zero** komodobots references. No item state, pickups, respawn timers, or item-value model in any artifact — a hard blocker for combat-aware / FantasyQuake simulation.
6. **Two un-unified "signature" schemas** (`player_movement_signatures.v1` cross-player axes vs `bunnyhop_fingerprint.v1` per-trick technique). No canonical player-profile object.
7. **Airborne / jump data is a Z-motion *proxy*, not ground truth.** `movement_metrics.v2` explicitly cannot prove grounded flag / jump-button press from MVDs; cadence built on the proxy was shown (S7d/e/f) to be entangled with the air-rhythm gap.
8. **Nav/marker graph is text-file-bound.** Frogbot `.bot` markers are read ad-hoc; some markers (276) lack static origins; no structured, queryable nav dataset; route topology doesn't match human QWD routes (direct `.bot` edge ratio 0.0 on the SNG move).
9. **Schema discipline is by-convention only.** 36 `vN` string tags, no validator/registry; coverage uneven (movement_metrics at v2, most at v1); raw NDJSON/CSV streams (`events.txt`, `trace.csv`, `.cmds`) carry **no schema tag** at all.
10. **Human reference corpus is thin & metadata-selected.** ~2 dm3 demos per elite player, selected via external Turso/Hub metadata; the bulk corpus (servexeri 4on4) is map/player-matched by filename + sha256, not content-indexed. No durable, versioned human-reference dataset surface ("where will broader human reference MVDs live?" is an explicit open question in doc 06).
11. **`records.json`/`verdicts.json` are published to servexeri, not committed** — the canonical records store lives off-repo (HTTP at `192.168.86.33:8095`), rebuildable from artifacts but not in git history.
