# Movement Problem

Status: living document.

## Core problem

The immediate challenge is not route learning.

The immediate challenge is understanding whether QuakeWorld bunnyjumping can be expressed as a controllable, measurable, and eventually learnable movement policy inside the KTX/Frogbot architecture.

## Project-level goal

The goal is not:

`Can Frogbots bunnyhop?`

The goal is:

`Can Frogbots become believable stand-ins for real players?`

Bunnyjumping is currently the most visible bottleneck toward that goal.

## What we believe today

- Frogbots move through real server commands.
- KTX converts bot intent into `forwardmove`, `sidemove`, `upmove`, button presses, angles, and impulses.
- Server physics remain engine-native.
- MVD recording remains engine-native.

## What MVDs can and cannot teach us

MVDs are server-side recordings of game state and events.

They can help us observe:

- player position over time
- derived velocity
- route/area movement
- item, damage, frag, weapon, and state context
- view angles or aim when available through parser/fusion outputs

But MVDs generally do not provide clean normal player usercmd labels:

- exact key presses
- exact mouse deltas
- exact `forwardmove`
- exact `sidemove`
- exact jump button timing

This means learning from Milton or other elite players is probably not simple supervised learning from input labels.

The likely problem is inverse control or engine-in-loop optimization:

`observed elite movement trace -> legal server command policy that produces similar movement`

## Movement literacy before route tricks

Do not start with hard trick routes.

Before high-value DM2 routes such as high RL to quad, RA secret exits, or big-to-tele variants, the bot must first learn movement literacy:

- accelerate into bunnyjumping
- preserve speed across repeated jumps
- alternate strafe/yaw appropriately
- time jumps on landing
- steer without overfitting to a route file
- recover when speed, angle, or timing is wrong

## Frobodm2 vs stock DM2

Use `frobodm2` for the first smoke test if it is the easiest way to prove the lab loop works, because the BSP and Frogbot route file are known to exist.

But `frobodm2` is not the final movement target.

The first real movement target is stock DM2 big room, because it is real target geometry while still open enough to isolate bunnyjumping before route-specific tricks.

## NotebookLM-style force-bunnyhop patches

A crude patch such as:

- always jump whenever moving
- globally enable air-rotation/curljump logic
- lower the ground-speed threshold everywhere

may be useful as a lab probe.

It should not be treated as the solution.

The real target is a movement mode or controller with:

- start conditions
- stop conditions
- tactical permission
- speed/yaw targets
- failure recovery
- skill variation
- human-like imperfection

## What is not yet proven

- Whether movement can be cleanly replaced with useful movement without rewriting the bot stack.
- Whether elite movement can be learned from MVD-derived evidence.
- Whether route logic and movement logic are sufficiently decoupled.
- Whether KTX/Frogbots should remain the substrate or be replaced by a new bot architecture.

## First movement override evidence

The first S2 probe found a candidate command-emission seam in KTX/Frogbots:

`src/bot_movement.c::BotSetCommand()` computes the final bot command and sends it through `trap_SetBotCMD(...)`.

Experiment patch:

`experiments/ktx_moveprobe/frogbot-moveprobe.patch`

Two patched `frobodm2` runs on 2026-06-05 produced different evidence:

- `20260605T213010Z`, moveprobe mode `2`: replacing the final movement command with fixed `yaw=90 forwardmove=800` and forced jump still spawned bots, recorded an MVD, parsed successfully, and produced metrics, but the bots were nearly stationary. This proves the command can be replaced, and also shows a naive fixed command is not useful movement.
- `20260605T213149Z`, moveprobe mode `1`: forcing jump while preserving Frogbot movement direction and combat produced a normal lab run with three frags and strong movement metrics. This proves a small final-command override can ride inside the existing KTX/Frogbot shell without breaking spawn, combat, MVD recording, parsing, or metrics.

The v2a comparison then directly logged the final command values:

- `20260605T222006Z`, stock mode `0`: variable yaw/movement commands and normal firing button values.
- `20260605T222047Z`, forced-jump mode `1`: variable yaw/movement commands preserved, while final buttons included jump (`2` or `3`).
- `20260605T222129Z`, fixed-command mode `2`: both bots emitted constant `yaw=90`, `forward=800`, `side=0`, `up=0`, `buttons=2`, and movement collapsed to roughly `1.6`-`1.9` qu/s average with `0.0%` air proxy.

The v2b route-yaw probe then added moveprobe mode `3`:

- `20260605T224811Z`, route-yaw mode `3`: command logging showed varied route-derived yaw, mostly `forward=800`, and jump-bearing buttons. `/ goldenboy` moved plausibly with avg `330.8` qu/s, p95 `464.6` qu/s, and `27.6%` air proxy. `/ bro` had p95 `442.4` qu/s, but also `59.7%` stationary time and avg only `137.4` qu/s.

The v2c repeatability check added `scripts/summarize_moveprobe_plausibility.py` and reran mode `3`:

- `20260605T225720Z`, `frobodm2`: both bots passed the v2c gate. `/ bro` stationary `6.5%`, low-speed `22.1%`; `/ goldenboy` stationary `0.2%`, low-speed `5.1%`.
- `20260605T225802Z`, `dm3`: both bots passed the v2c gate. `/ bro` stationary `1.1%`, low-speed `1.4%`; `/ goldenboy` stationary `0.0%`, low-speed `1.7%`.

This proves the final emitted command can be observed and replaced, and gives repeatable positive movement-feasibility evidence for a route-derived command policy on two routed maps. It is enough to treat S2 as provisionally satisfied pending review. It does not solve aim/movement separation or bunnyjumping: mode `3` still commandeers view yaw, and the fresh short runs recorded no frags.

## First S3a Bunnyjump-Primitive Evidence

Moveprobe mode `4` adds an alternating route-relative sidemove command on top of mode `3`:

- `20260605T231033Z`, `frobodm2`: both bots passed the stricter S3a gate with nonzero side coverage above `94%`, low stationary/low-speed time, and one RL frag. Movement was plausible, but p95 speeds (`358.9` and `364.5` qu/s) were lower than the mode `3` v2c repeat.
- `20260605T231115Z`, `dm3`: side/jump/forward command coverage was above `93%`, but `/ bro` failed low-speed time at `63.0%`; `/ goldenboy` barely passed low-speed at `39.0%`.

This proves a bounded strafe signal can be emitted and measured, but does not prove better movement. The first S3a primitive is therefore a partial/negative result: alternating `+/-400` sidemove at the current cadence can keep bots moving on `frobodm2`, but appears too disruptive or map-sensitive on `dm3`.

## S3b Sidemove Parameter Diagnosis

S3b reused mode `4` on `dm3` but changed the sidemove magnitude:

- `20260605T231737Z`, `sidemove=200`: both bots passed the side/plausibility gate. `/ bro` low-speed improved from the `400` run's `63.0%` to `26.9%`; `/ goldenboy` low-speed was `28.3%`.
- `20260605T231819Z`, `sidemove=300`: side command coverage still exceeded `91%`, but `/ bro` failed low-speed at `51.1%`; `/ goldenboy` passed at `5.6%`.

This suggests the first usable S3 strafe parameter is smaller than the default `400`. It still does not beat route-yaw mode `3` on speed or simplicity, so the next proof should verify `sidemove=200` across maps/repeats before adding cadence or state.

## S3c Cross-Map Sidemove Validation

S3c reran mode `4` with `--moveprobe-sidemove 200` on both routed maps:

- `20260605T233120Z`, `frobodm2`: both bots passed the side/plausibility gate. `/ bro` averaged `279.6` qu/s with `7.4%` low-speed time; `/ goldenboy` averaged `306.7` qu/s with `4.6%` low-speed time. The run recorded one RL frag.
- `20260605T233202Z`, `dm3`: both bots passed the side/plausibility gate. `/ bro` averaged `248.8` qu/s with `16.7%` low-speed time; `/ goldenboy` averaged `293.3` qu/s with `10.9%` low-speed time.

This validates `sidemove=200` as a repeatable route-yaw strafe candidate. It does not prove player realism. Compared with route-yaw mode `3`, mode `4` lowers high-speed spikes and remains aim-commandeering. The next useful step should test aim-independent movement math: keep the real combat view angle and compute `forwardmove`/`sidemove` from route intent relative to that view.

## S3d Aim-Independent Movement-Vector Probe

S3d added mode `5`: preserve `self->fb.desired_angle`, build a route-relative movement vector with optional alternating strafe, then project it into local `forwardmove`/`sidemove` commands using the preserved combat yaw.

- `20260605T234620Z`, `frobodm2`: all command coverage gates passed with horizontal/side/jump coverage above `85%`, but `/ bro` failed behavior gates with `74.7%` stationary and `79.2%` low-speed time. `/ goldenboy` passed with avg `256.0` qu/s and `21.2%` low-speed time. The run recorded one SSG frag by `/ goldenboy`.
- `20260605T234701Z`, `dm3`: all command coverage gates passed with horizontal/side/jump coverage above `93%`, but `/ bro` failed behavior gates with `40.5%` stationary and `53.8%` low-speed time. `/ goldenboy` passed with avg `219.6` qu/s and `24.7%` low-speed time.

This is an important split result. The final-command seam can emit aim-independent route/strafe commands, but preserving combat yaw makes movement behavior fragile for at least `/ bro`. The next useful step is not a larger controller; it is diagnosing whether the failures correlate with route-vs-view yaw delta, backward command ratios, or specific route states.

## S3e Aim/Move Conflict Diagnostics

S3e kept mode `5`'s aim-independent projection policy, but added command-log diagnostics: route yaw from `self->fb.dir_move_`, preserved view yaw, route-vs-view yaw delta, and whether the emitted local `forwardmove` was negative.

- `20260606T000331Z`, `frobodm2`: both bots passed the horizontal/side/jump behavior gate. `/ bro` had `22.7%` backward commands, absolute yaw-delta avg `53.1`, p90 `110.9`, and low-speed `14.3%`. `/ goldenboy` had `14.0%` backward commands, absolute yaw-delta avg `44.2`, p90 `91.8`, and low-speed `4.0%`. The run recorded one SSG frag by `/ goldenboy`.
- `20260606T000414Z`, `dm3`: both bots passed command coverage but failed the low-speed gate. `/ bro` had the strongest aim/move conflict signal: `41.3%` backward commands, absolute yaw-delta avg `79.6`, p90 `154.7`, `43.1%` of samples above 90 degrees, and low-speed `43.1%`. `/ goldenboy` failed low-speed at `52.8%` despite only `14.0%` backward commands and yaw-delta avg `44.7`.

The diagnostics support a narrow claim: large route-vs-view disagreement and backward local commands are plausible contributors, especially for `/ bro` on `dm3`. They do not fully explain the split, because `/ goldenboy` can still fail low-speed with a much lower backward-command ratio. The next smallest useful corrective experiment should therefore be tiny and falsifiable: clamp or remap negative local forward commands in mode `5`, run `dm3` first against the same gate, and stop if that does not improve low-speed behavior.

## S3f No-Backpedal Correction Probe

S3f added mode `6`: reuse mode `5`'s aim-independent projection, but when projected local `forwardmove` is negative, fold that removed backpedal magnitude into local `sidemove` and clamp local forward to `0`.

- `20260606T001705Z`, `dm3`: both bots passed the horizontal/side/jump behavior gate. `/ bro` improved from S3e low-speed `43.1%` to `38.3%`, with backward commands dropping from `41.3%` to `0.0%`. `/ goldenboy` improved from S3e low-speed `52.8%` to `24.4%`, also with backward commands `0.0%`. The run recorded one SG frag by `/ bro`.
- `20260606T001825Z`, `frobodm2`: both bots passed. `/ bro` low-speed was `13.8%`; `/ goldenboy` low-speed was `26.8%`; both had `0.0%` backward commands. The run recorded one GL frag by `/ goldenboy`.

This is useful evidence that sustained backpedal commands were part of the mode `5` failure. It is not final-controller evidence. Mode `6` passes the current gate partly by emitting very large local side commands, often around `1100`, after folding backpedal into strafe. The next useful experiment should bound command magnitudes while preserving the no-backpedal property, then rerun the same gates.

## S3g Bounded No-Backpedal Probe

S3g added mode `7`: reuse mode `6`'s no-backpedal correction, then normalize local horizontal command magnitude back down to the original route/strafe intent magnitude.

- `20260606T003718Z`, `dm3`: both bots passed. `/ bro` had `0.0%` backward commands, max horizontal command `824.5`, and low-speed `26.1%`; `/ goldenboy` had max horizontal command `824.5` and low-speed `18.9%`. The run recorded one SG frag by `/ bro`.
- `20260606T003808Z`, `frobodm2`: both bots passed. `/ bro` had max horizontal command `824.5` and low-speed `5.5%`; `/ goldenboy` had max horizontal command `824.6` and low-speed `2.7%`.

This is the best S3 movement-literacy candidate so far: it preserves combat yaw, avoids sustained backpedal commands, and no longer relies on very large folded sidemove values. It still is not a realism verdict. The next step should anchor these bot metrics against human-demo movement instead of adding another command heuristic.

## S6a Route-State Diagnosis

S6a added `scripts/diagnose_route_state.py` and inspected the existing S3g `dm3` run `20260606T003718Z` instead of changing movement commands again.

Result:

- Current artifacts expose MVD position samples, sampled final moveprobe commands, route yaw, view yaw, yaw delta, backward-command state, and map-entity locations.
- Current artifacts do not expose Frogbot route node, next waypoint, target entity, obstruction, or route primitive state.
- `/ bro` had `7` low-speed windows of at least `250` ms; the longest contributed `1198` ms of low-speed time near `water.LG`.
- `/ goldenboy` had `4` such low-speed windows; the longest contributed `1078` ms near `RA`.
- Across the top windows, `8` of `9` showed low speed despite average sampled horizontal command at or above `400`; most were near the expected mode `7` cap around `824`.

Interpretation: S3g's high-speed gap is not explained by missing final movement command emission. The current evidence can identify where the bot loses speed and whether strong commands were sampled nearby, but it cannot say whether the cause is route choice, route-node transitions, obstruction handling, or missing route-level movement intent. The next useful step is minimal route-state logging, not mode `8`.

## S6b Route-State Logging

S6b extended the same moveprobe command log with route-state fields and reran a short S3g-style `dm3` probe (`20260606T031102Z`).

Result:

- Route-state fields are now available in `moveprobe-commands.json`: linked marker, touch marker, goal entity, goal marker, path state, bot state, blocked state, and route `dir_speed`.
- `/ bro` had avg `136.3`, p95 `359.6`, low-speed `52.1%`, and `17` low-speed windows; all `5` analyzed top windows still had strong sampled command context.
- `/ goldenboy` had avg `285.5`, p95 `381.3`, low-speed `7.0%`, and no S6-threshold low-speed windows.
- Repeated `/ bro` windows near `water.LG` shared linked/goal marker `59`, path state `32768`, and `blocked=0`.

Interpretation: S6b closes the route-state observability gap, but it does not yet explain or fix the movement gap. The next useful step is to decode repeated marker/path-state patterns, especially `/ bro` at `water.LG`, before changing mode `7`.

## S6c Route-State Attribution

S6c decoded the S6b route-state windows against KTX/Frogbot source flags and the `dm3.bot` route table without changing KTX or running a new controller experiment.

Result:

- `path_state=32768` decodes to `WATER_PATH`; `STUCK_PATH` is `524288`.
- KTX sets `WATER_PATH` in route calculation when either endpoint marker is in water and uses `sv_maxwaterspeed` for that path's route time.
- `dir_speed` is the pre-normalization magnitude captured by `SetDirectionMove()`; the probe then normalizes `dir_move_` and emits its fixed route/strafe command.
- The repeated `/ bro` `water.LG` pattern groups `3` top low-speed windows with linked/goal marker `59`, `blocked=0`, no `STUCK_PATH`, avg sampled command near `824`, and avg native `dir_speed=0.338`.
- The worst two repeated windows are on the `.bot` edge `276->59 idx=[0]`; their native `dir_speed` averages are `0.059` and `0.196` while sampled command magnitude stays high.

Interpretation: the current gap is not missing final command magnitude and not obvious obstruction recovery. The strongest repeated S6b pattern is a water-path route primitive where native Frogbot movement intent magnitude collapses before the mode `7` probe normalizes direction. The next useful step is to inspect water-path/swim intent (`waterlevel`, `swim_arrow`, `upmove`, velocity/dir_move context) around `water.LG`, not to add a new command mode.

## S6d Water-Path Swim-Intent Diagnosis

S6d extended command logging with `waterlevel`, `watertype`, player flags, `swim_arrow`, emitted `upmove`, velocity, and raw route `dir_move`, then reran a short `dm3` mode `7` probe (`20260606T041805Z`).

Result:

- `/ bro` again produced repeated top low-speed windows at `water.LG`, all with strong sampled horizontal commands near `824`, `WATER_PATH`, and `blocked=0`.
- The grouped `/ bro` water-path windows had waterlevel values `[1]` or `[1, 2]`, no deep-water window samples (`waterlevel > 2`), `swim_arrow=0`, and emitted `upmove=0`.
- The worst repeated windows stayed on or near `.bot` edge `276->59 idx=[0]`, with native `dir_speed` averages as low as `0.050` to `0.064`.
- Raw `dir_move_z` was not always zero in these windows, but mode `7` currently overwrites emitted `direction[2]` from `k_fb_moveprobe_upmove`, whose default is `0`.

Interpretation: the repeated `water.LG` failure is not active deep-water swimming, because `BotWaterMove()` only sets `swim_arrow` after `waterlevel > 2` and no such window samples were observed. The sharper S6d hypothesis is a shallow water-edge route transition where mode `7` may be suppressing native vertical movement at `waterlevel == 2`. The next useful experiment is a tiny water-edge upmove preservation probe, not generic speed tuning.

## S6e Water-Edge Upmove Probe

S6e changed only mode `7` vertical command handling: when `waterlevel > 1`, it preserves the native pre-probe `direction[2]`; otherwise mode `7` still uses `k_fb_moveprobe_upmove` and keeps the same aim-independent, no-backpedal, bounded horizontal projection. A single short `dm3` run (`20260606T044000Z`) tested that hypothesis.

Result:

- `/ bro` worsened overall: avg `153.0`, p95 `377.7`, low-speed `46.3%`, and `3` low-speed windows, including one very long `YA.box` blocked/STUCK_PATH-style window.
- `/ goldenboy` also worsened overall: avg `152.7`, p95 `346.7`, low-speed `39.3%`, and `7` low-speed windows.
- The repeated `water.LG` / `276->59` WATER_PATH pattern did not disappear; it appeared on `/ goldenboy` with `2` grouped windows, linked/goal marker `59`, waterlevels `[1, 2]`, `blocked=0`, and strong sampled command magnitude near `824`.
- S6e did emit nonzero upmove in some `/ goldenboy` water-edge samples, but that did not remove the repeated low-speed `water.LG` pattern.

Interpretation: S6e hit the stop condition. Native water-edge upmove preservation is not sufficient as a route-primitive fix, and more upmove tuning would be speculative. The next useful S6 step is a static/diagnostic `.bot` route-edge geometry audit around `276->59` and marker `59`, then a pivot back toward the headline land-speed/bunnyhop gap or broader human-reference evidence.

## S6f Route-Edge Geometry Audit

S6f added `scripts/inspect_route_edge_geometry.py` and inspected `dm3.bot` edge `276->59` plus marker `59` against the committed S6d/S6e route-state attribution evidence. No KTX controller or route file was changed.

Result:

- `276->59` is explicitly defined in `dm3.bot` as path index `0`, and the reciprocal `59->276` edge is also explicitly defined.
- Marker `59` has a static origin at `[1329.0, -378.0, -24.0]`, zone `17`, goal `5`.
- Marker `276` is route-referenced and zoned, but has no static `CreateMarker` origin in `dm3.bot`.
- Therefore the static route file cannot compute a precise horizontal/vertical vector, slope, or coordinate correction for `276->59`.
- The S6d/S6e evidence contains `30` unique sampled `276->59` rows. They are `WATER_PATH`, `blocked=0`, and `86.7%` of focus-edge samples have native `dir_speed < 0.25`.

Interpretation: the repeated water-edge failure is real, but S6f does not reveal a small static route-data fix. The edge is defined, reciprocal, and unflagged in the route file; the missing source origin means a coordinate-level geometry edit would be guesswork. Stop S6 water-edge tuning here and move the next goal toward S7-style player-specific movement signatures while keeping the headline land-speed/bunnyhop gap visible.

## S7a Exact-Player Movement Signature Scaffold

S7a added `scripts/summarize_player_movement_signatures.py` and generated `experiments/human_comparison/evidence/player-signatures-s7a-dm3.*` from the existing S5b exact-player `dm3` aggregate. No controller code, KTX patch, route file, or new demo parse changed.

Result:

- Avg speed and p95 speed remain generic S3g-vs-human land-speed gaps: the best S3g `dm3` bot is still `34.6` qu/s below the reference avg-speed minimum and `130.5` qu/s below the reference p95-speed minimum.
- Low-speed ratio is a possible player-style axis in the tiny reference set (`Milton` `12.4%`, `carapace` `19.6%`, `yeti` `15.4%`), but the bot comparison is mixed and the reference set is too thin.
- Jump cadence is also a possible reference-only axis (`44.0` to `48.6`/min), but the committed S3g bot summary does not carry the same metric.
- Airborne proxy is not useful as a player-style axis here because the exact-player reference spread is too tight while the two S3g bot rows split above and below the range.
- The stop condition is triggered: three single-demo exact-player rows can seed axes, but cannot support stable player-specific style claims.

Interpretation: S7a successfully creates the measurement scaffold, but it points away from immediate player-specific controller work. The next smallest useful step is to broaden exact-player references, especially repeated `dm3` samples for the same targets where available, then rerun the signature scaffold to separate stable style from one-match noise and the unresolved land-speed/bunnyhop gap.

## S7b Repeated Exact-Player References

S7b selected one additional manifest-backed `dm3` demo for each S7a target, parsed them through the same human MVD pipeline, and regenerated the aggregate/signature evidence with six rows.

Result:

- The repeated set preserves the headline land-speed gap. Exact-player avg range is `282.8` to `314.2`; S3g `dm3` bots remain `190.1` to `248.2`. Exact-player p95 range is `505.8` to `535.0`; S3g remains `361.0` to `375.3`.
- Repeated-player stability marks avg and p95 as stable but still generic land-speed gaps, not style targets.
- Low-speed ratio has between-player mean spread `4.3%` and max within-player spread `3.2%`, separation ratio `1.34`; that is still mixed/overlapping, not a stable style target.
- Airborne proxy has between-player mean spread `4.7%` and max within-player spread `6.0%`, so it is not stable enough for player-specific control.
- Jump cadence has between-player mean spread `7.6`/min, max within-player spread `3.7`/min, and separation ratio `2.06`; it is the only repeated candidate axis, but it remains reference-only because S3g committed bot summaries do not carry cadence.

Interpretation: S7b removes the single-demo stop condition but still does not justify player-specific movement control. The next useful step is to make cadence/tempo bot-comparable and controller-relevant, while keeping the generic land-speed/bunnyhop deficit visible.

## S7c Bot-Comparable Cadence

S7c did not rerun the lab. It used the cadence values already present in the committed S3g raw movement artifacts, carried `jump_cadence_per_min` through the S3g plausibility summary, compared bot rows against the repeated exact-player aggregate, and regenerated `player-signatures-s7c-dm3.*`.

Result:

- The repeated exact-player `dm3` cadence range is `40.4` to `51.0`/min, with mean `45.2`/min.
- S3g `/ bro` has cadence `91.7`/min on `dm3`, above the repeated human range.
- S3g `/ goldenboy` has cadence `43.3`/min on `dm3`, inside the repeated human range.
- Cadence is now a bot-comparable repeated candidate style axis with mixed bot relation, not a reference-only axis.
- Avg and p95 remain generic land-speed gaps: reference avg `282.8` to `314.2` versus S3g `190.1` to `248.2`, and reference p95 `505.8` to `535.0` versus S3g `361.0` to `375.3`.
- Low-speed and airborne proxy are still mixed/overlapping under repeated samples.

Interpretation: S7c completes the narrow handoff from "cadence might matter" to "cadence can be compared against bots." It does not justify a broad player-specific movement controller yet. The next useful step is S7d: decide whether cadence should remain a diagnostic target, whether S7 needs broader exact-player/bot samples, or whether a tiny controller probe is justified while the land-speed gap stays visible.

## S7d Cadence Normalization Decision

S7d did not rerun the lab and did not change controller behavior. It added `scripts/decide_cadence_normalization.py`, consumed the S7c aggregate, and wrote `experiments/human_comparison/evidence/cadence-normalization-s7d-dm3.*`.

Important metric correction: `jump_cadence_per_min` is already active-row normalized (`airborne_proxy_count / active_time_s * 60`), not full match wall-clock cadence. S7d tested stricter normalizations:

- Non-stationary cadence: reference `44.2` to `55.6`/min; S3g `/ bro` `92.1`/min above range; `/ goldenboy` `44.4`/min within range.
- Non-low-speed cadence: reference `48.7` to `61.3`/min; S3g `/ bro` `124.1`/min above range; `/ goldenboy` `53.3`/min within range.
- Airborne-proxy cadence: reference `128.0` to `143.1`/min; S3g `/ bro` `207.6`/min and `/ goldenboy` `174.4`/min both above range.

Interpretation: cadence stays diagnostic and is not controller-authorizing yet. Movement-time normalization does not overturn the mixed S7c relation, and airborne-proxy normalization suggests the cadence signal is entangled with air-rhythm/proxy segmentation. The next useful step is S7e: broaden bot rows or inspect airborne-proxy segmentation before any cadence controller probe.

## S7e Cadence Evidence Broadening

S7e did not rerun the lab and did not change controller behavior. It added `scripts/broaden_cadence_evidence.py`, consumed the S7c exact-player aggregate, and broadened the bot side from the original S3g `dm3` row pair to six rows by adding existing S6b/S6d diagnostic `dm3` mode-7 reruns:

- Included unchanged mode-7 runs: `20260606T003718Z`, `20260606T031102Z`, and `20260606T041805Z`.
- Excluded `20260606T044000Z` because S6e changed water-edge vertical command behavior and is therefore a mode-7 variant rather than an unchanged diagnostic rerun.
- Active cadence remains mixed: exact-player `40.4` to `51.0`/min; broadened bots `18.5` to `138.7`/min.
- Non-stationary and non-low-speed cadence also remain mixed.
- Airborne-proxy cadence is consistently high: exact-player `128.0` to `143.1`/min; all six broadened bot rows `164.1` to `274.1`/min.

Interpretation: S7e strengthens S7d rather than overturning it. Cadence remains diagnostic, not controller-authorizing, because all unchanged mode-7 bot rows are above the exact-player airborne-proxy cadence range while raw and movement-time cadence remain unstable/mixed. The next useful step is S7f: inspect raw airborne-proxy segment distributions or pivot back to the larger land-speed gap before any cadence controller probe.

## S7f Raw Airborne-Proxy Segment Inspection

S7f did not rerun the lab and did not change controller behavior. It added `scripts/inspect_airborne_proxy_segments.py`, replayed the existing movement-metrics airborne proxy over raw `events.txt` kind `5` samples, and generated `experiments/human_comparison/evidence/airborne-segments-s7f-dm3.*`.

Result:

- Scope: six exact-player `dm3` reference rows from the S7c aggregate and six unchanged mode-7 bot rows from S7e.
- Player-median airborne-proxy duration: exact-player `325.0` ms versus bot `217.2` ms; bot/reference p50 ratio `0.668`.
- Player-median airborne-proxy Z range: exact-player `43.8` qu versus bot `11.5` qu; ratio `0.264`.
- Player-median airborne-proxy horizontal speed: exact-player `431.8` qu/s versus bot `114.4` qu/s; ratio `0.265`.
- Raw active average speed ratio is less extreme at `0.735`, but still confirms the broader land-speed gap.

Interpretation: the bot airborne-proxy runs are not human-like jumps. They are shorter, lower-Z, and much slower vertical-motion blips. The high airborne-proxy-normalized cadence is therefore a symptom of broken air/land rhythm and low horizontal speed, not a controller-ready cadence target. The next useful step is S7g: characterize the land-speed gap around route and air segments before another controller probe.

## S7g Land-Speed Gap Characterization

S7g did not rerun the lab and did not change controller behavior. It added `scripts/characterize_land_speed_gap.py`, consumed the S7f row set, and bucketed accepted movement segments by airborne-proxy overlap, `400` ms pre/post-air windows, sampled moveprobe command strength, and route-state hints where bot artifacts expose them.

Result:

- Generated `experiments/human_comparison/evidence/land-speed-gap-s7g-dm3.*`.
- All accepted segment p50: exact-player `334.0` qu/s versus bot `222.0` qu/s; bot/reference ratio `0.665`.
- Airborne-proxy segment p50: exact-player `433.8` qu/s versus bot `122.6` qu/s; ratio `0.283`.
- Non-airborne segment p50: exact-player `320.0` qu/s versus bot `312.1` qu/s; ratio `0.975`.
- Pre-air window p50: exact-player `418.0` qu/s versus bot `207.1` qu/s; ratio `0.495`.
- Post-air window p50: exact-player `365.7` qu/s versus bot `184.5` qu/s; ratio `0.505`.
- Route `WATER_PATH` bot samples have p50 `95.3` qu/s.

Interpretation: the speed gap is not uniform. Generic non-airborne p50 speed can be human-scale in the current bot row set, but speed production around air transitions collapses, and sampled route `WATER_PATH`/low-dir-speed contexts remain extremely slow. The next useful step is S7h: choose whether the first controller probe targets air-transition horizontal speed production or a narrow route primitive such as `WATER_PATH` low-dir-speed recovery.

## S7h Controller Probe Target Decision

S7h did not rerun the lab and did not change controller behavior. It added `scripts/choose_controller_probe_target.py`, consumed `experiments/human_comparison/evidence/land-speed-gap-s7g-dm3.json`, and compared two possible first probe targets:

- air-transition horizontal speed production,
- narrow route `WATER_PATH` low-dir-speed recovery.

Result:

- Generated `experiments/human_comparison/evidence/controller-probe-target-s7h-dm3.*`.
- Air-transition was selected as `preferred_first_probe_target`.
- Air-transition evidence is human-comparable across the exact-player and bot row set: pre-air ratio `0.495`, airborne ratio `0.283`, post-air ratio `0.505`, while non-airborne ratio is near reference at `0.975`.
- `WATER_PATH` remains a `secondary_guardrail_target`: p50 speed is only `95.3` qu/s, but the evidence is bot-only route diagnostics with no exact-player reference bucket and only `2` bot rows contributing `WATER_PATH` player p50s.

Interpretation: the first controller probe should target air-transition horizontal speed production, not generic all-segment speed, cadence, or a route-only primitive. The route `WATER_PATH` gap remains important, but it should be monitored as a guardrail and deferred narrow target unless the air-transition probe fails or makes route context worse.

## S7i Air-Transition Probe Design

S7i did not rerun the lab and did not change KTX/Frogbot movement behavior. It added `scripts/design_air_transition_probe.py`, consumed the committed S7g land-speed evidence, S7h target decision, and S7e cadence evidence, then generated `experiments/human_comparison/evidence/air-transition-probe-design-s7i-dm3.*`.

Result:

- Probe id: `s7i-mode8-air-transition-horizontal-speed`.
- Status: `design_only_no_controller_behavior_changed`.
- The follow-up implementation must start from moveprobe mode `7` and change horizontal command budget only during takeoff/air-transition windows.
- It must keep combat view yaw, route projection, no-backpedal folding, command bounding outside the transition window, jump-button policy, route logging, water logging, and cadence reporting unchanged.
- Required post-probe reporting includes pre-air, airborne, post-air, non-airborne, route low-dir-speed, `WATER_PATH`, and cadence axes.

Stop conditions:

- Reject all-segment speed gains when none of the air-transition buckets improve.
- Reject any required air-transition bucket p50 drop greater than `5%` versus S7g.
- Reject non-airborne p50 drops greater than `5%` versus S7g.
- Reject or mark inconclusive if `WATER_PATH` gets worse or route/WATER_PATH diagnostics disappear.
- Keep cadence diagnostic; do not claim success from cadence shifts.

Interpretation: S7i turns the S7h decision into a reviewable contract before controller code. The next useful branch is S7j: implement and run the tiny air-transition probe only if the patch preserves this contract.

## S7j Air-Transition Probe Result

S7j implemented the S7i contract as moveprobe mode `8`: start from mode `7`, scale horizontal command budget only during takeoff/air-transition windows, keep cadence diagnostic, and preserve route/water/probe command logging. Claude review caught that the first mode-8 call used a hardcoded `true` jump gate, which made every grounded frame transition-active. The patch now uses the pre-probe `*jumping` state. It temporarily deployed corrected KTX builds, ran `dm3` lab runs `20260606T163907Z` and `20260606T164610Z`, restored the original server module after each run, and generated `experiments/human_comparison/evidence/air-transition-probe-s7j-dm3.*`.

Result:

- Probe activation fired and was measured across the two fixed runs: `546` command rows carried `probe=` state, with `110` transition-active samples (`20.1%`).
- All accepted segment p50 improved only slightly from `222.0` to `230.0` qu/s, and route `WATER_PATH` stayed barely above baseline where present (`95.3 -> 96.2` qu/s).
- The intended air-transition buckets regressed versus S7g: pre-air p50 `207.1 -> 149.7` qu/s and airborne p50 `122.6 -> 100.4` qu/s.
- Post-air p50 was nearly flat but still below baseline: `184.5 -> 179.6` qu/s.
- Non-airborne p50 failed the S7i guardrail: `312.1 -> 286.3` qu/s.
- Route low-dir-speed p50 improved from `141.0` to `201.2` qu/s, but that is not enough to offset the target-bucket and non-airborne failures.
- Cadence stayed diagnostic rather than proof of success.

Interpretation: Claude's gate fix was required and the comparison now has guardrail-complete evidence. The corrected mode `8` probe is rejected by the S7i stop conditions: a small all-segment gain is not useful when pre-air, airborne, post-air, and non-airborne context get worse. The next useful branch is S7k: inspect the failed bucket and command/probe activation context before trying another controller probe.

## S7k Failed-Bucket Diagnosis

S7k did not rerun the lab and did not change KTX/Frogbot movement behavior. It added `scripts/diagnose_s7j_failed_buckets.py`, consumed the corrected S7j result plus the S7g baseline, and recomputed command/probe/route context for the failed pre-air, airborne-proxy, and non-airborne buckets.

Result:

- Generated `experiments/human_comparison/evidence/failed-bucket-diagnosis-s7k-dm3.*`.
- Pre-air and airborne-proxy failures are mixed controller/route-context failures: both buckets have high strong-command coverage but also substantial low-dir-speed and `WATER_PATH` context in the second S7j run.
- The non-airborne guardrail regression is route/map-context contaminated, not a clean all-ground movement failure. `/ goldenboy` in `20260606T164610Z` had non-airborne p50 `100.8` qu/s with low-dir ratio `0.626` and `WATER_PATH` ratio `0.614`.
- Water is not the whole issue. First-run air-transition rows still had no `WATER_PATH` but remained too slow: `/ bro` airborne p50 `101.8` qu/s and `/ goldenboy` airborne p50 `181.2` qu/s.

Interpretation: S7k does not trigger a from-scratch rebuild. The failure is bounded enough to justify one narrower context-gated Frogbot/KTX probe: keep the engine-native substrate, but gate or separately score low-dir-speed/`WATER_PATH` contexts before another air-transition command-policy change.

## QWD SNG Setup Repair Result

The QWD-derived `dm3_sng_shortcut.qwd` branch tests whether exact human POV commands plus trajectory control points can improve Frogbot movement on `dm3` without abandoning the KTX/Frogbots server-native shell.

The first mode-9 SNG runtime probe activated too late for clean MVD evidence. The setup-repair run `20260606T231007Z` widened only the activation radius from `192` to `320` qu while preserving the same control points, `96` qu point radius, and `forwardmove=320` / `sidemove=508` command profile.

Result:

- QWD active samples: `627`.
- Max active seconds: `16.591`.
- Max advanced control points inside the parsed MVD window: `4`.
- Diagnostics remained present: route, water, command, QWD state, cadence, and movement metrics.
- The run is rejected by `waypoint_only_slow_success`: `/ bro` advanced the first four points with low-speed ratio `0.429` and stationary ratio `0.253`.

Interpretation: this repairs the evidence-window problem but not the movement problem. The bot can be steered through early SNG control points inside real server physics, but it is still too slow/stationary to count as learned human-like movement. The next movement question is whether that slow traversal comes from controller projection, route/map context, or a too-loose setup radius.

## QWD SNG Slow-Success Attribution

The slow-success diagnosis did not rerun KTX and did not change movement behavior. It added `scripts/diagnose_qwd_sng_slow_success.py`, consumed the setup-repaired run `20260606T231007Z`, split active QWD commands by current control-point target, and joined those phases to MVD movement segments.

Result:

- `/ bro` was the slow-success candidate.
- Widening the start radius to `320` qu activated `/ bro` immediately at `t=0` from `281.954` qu away from CP0.
- The original `192` qu design radius would first have activated at `31652` ms, when `/ bro` was `83.332` qu from CP0.
- The CP0 active phase had p50 speed `84.385` qu/s, low-speed ratio `0.526`, stationary ratio `0.383`, and blocked ratio `0.371`.
- After advancing through four control points, `/ bro` still stayed `181.154` qu from CP4 against a `96` qu point radius.
- The active command profile was strong: side ratio `1.0`, jump ratio `1.0`, median horizontal command `600.0`.
- Water and low-dir-speed route context were not primary in the slow-success candidate phases.

Interpretation: the current SNG evidence is route-geometry transfer plus slow/stuck traversal, not human-like movement. This keeps Frogbots viable as the server-native substrate, but blocks expansion to other DM3 QWD moves until the SNG activation and phase-level success gates are tightened.

## QWD SNG Phase-Gate Tightening

The SNG scorer now rejects the two failure modes exposed by the slow-success attribution before it can emit positive bounded evidence:

- `tight_start_activation`: if a bot reaches the advancement gate, its first active in-MVD QWD sample must show pre-advance CP0 evidence inside the `192` qu design start radius. If the first active row has already advanced to a later target, the start evidence is inconclusive rather than rejected.
- `phase_target_progression`: after the required four-point advancement, a long active phase on the next target must enter the `96` qu point radius.

Rescoring run `20260606T231007Z` as `qwd-sng-phase-gate-tightening-dm3` keeps the verdict rejected:

- `/ bro` first activated inside the MVD at `281.954` qu from CP0, outside the `192` qu design start radius.
- `/ bro` then spent `9.908` seconds in the CP4 phase and never got closer than `183.876` qu to CP4 against the `96` qu point radius.
- The previous `waypoint_only_slow_success` rejection still stands.

Interpretation: this makes the SNG evidence gate stricter without changing movement behavior. The next live experiment should rerun mode `9` with tight design-radius activation and unchanged projection before changing command policy or trying other DM3 QWD moves.

## QWD SNG Tight-Start Rerun

The tight-start rerun restored the original `192` qu start radius and kept the same mode `9` QWD control points, `96` qu point radius, and `forwardmove=320` / `sidemove=508` projection. It temporarily deployed the existing KTX moveprobe patch, ran `dm3` lab run `20260607T003837Z`, and restored the stock live KTX module afterward.

Result:

- QWD activation overlapped the parsed MVD movement window for both bots.
- The run produced `865` sampled command rows, `274` active QWD samples, and `16.383` max active seconds.
- Both bots advanced far beyond the previous four-point setup repair: `/ bro` reached `11` control points inside the MVD window, and `/ goldenboy` reached `12`.
- The scorer still rejects the run on `phase_target_progression` and `waypoint_only_slow_success`.
- `tight_start_activation` is inconclusive rather than rejected because the first active in-MVD sampled row was already at CP2 for both bots, so the sampled command log cannot prove the pre-advance CP0 start state.
- `/ bro` remains the slow-success candidate with whole-run low-speed ratio `0.55`, even though many active phases show strong side/jump commands and no water/low-dir-speed route contamination.

Interpretation: this is the strongest evidence so far that the KTX/Frogbots substrate can ingest QWD-derived DM3 SNG control inside real server physics. It is still not learned or believable SNG movement. The current blocker has shifted from "can we activate and advance under tight setup?" to "can we prove exact phase entries and active-window movement quality without relying on sparse command samples or whole-match slow ratios?"

The next useful step should remain diagnostic: capture denser or event-level QWD advancement/start evidence and score active-window movement quality before changing projection policy or expanding to the other DM3 QWD moves.

## Working hypothesis

The largest visible realism gap is movement.

The largest visible movement gap is bunnyjumping.

Therefore movement is the first laboratory target.
