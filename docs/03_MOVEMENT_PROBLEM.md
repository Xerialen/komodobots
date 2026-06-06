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

## Working hypothesis

The largest visible realism gap is movement.

The largest visible movement gap is bunnyjumping.

Therefore movement is the first laboratory target.
