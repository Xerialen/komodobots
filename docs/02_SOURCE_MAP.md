# Source Map

Status: living document. Keep this updated as sources are verified, forked, pinned, or superseded.

## Purpose

This document maps the core sources Komodobots depends on. It should help Codex and humans avoid rediscovering context and avoid using stale assumptions.

## Primary implementation sources

### KTX server-side Frogbots

Repository: https://github.com/QW-Group/ktx

Local checkout: `C:\Users\benya\projects\quakeworld\engine\ktx`

Observed local commit during the 2026-06-05 headless environment inspection: `08807da`.

Why it matters:

- Current server-side Frogbots implementation.
- Candidate engine-native substrate for Komodobots.
- Provides bot support inside the real QuakeWorld/KTX server loop.

Important files/anchors to verify and revisit:

- `CMakeLists.txt` — bot support configuration.
- `include/g_syscalls.h` — `trap_AddBot`, `trap_RemoveBot`, `trap_SetBotCMD`.
- `src/bot_movement.c` — movement command generation, physics estimates, jump/firing command output.
- `include/fb_globals.h` — Frogbot route/path flags and bot data structures.
- `src/bot_loadmap.c` and `src/marker_load.c` — external `.bot` route loading.
- `resources/example-configs/ktx/bots/maps/frobodm2.bot` — practical route file reference.

Deployment note:

- `servexeri:~/nquakesv/` has a live KTX install built from commit `08807da`, with `ktx/qwprogs.so`, `ktx/bots/maps/frobodm2.bot`, `qw/maps/dm2.bsp`, and `qw/maps/frobodm2.bsp` present as of 2026-06-05.

### MVDSV server

Repository: https://github.com/QW-Group/mvdsv

Why it matters:

- Runs the QuakeWorld server process that hosts KTX.
- Provides server-side MVD recording and demo sidecar handling.
- Candidate executable for Komodobots lab ports.

Deployment note:

- `servexeri:~/nquakesv/` has `mvdsv` and `build/mvdsv/mvdsv` present; the build checkout reported commit `90aa017` during the 2026-06-05 inspection.
- Existing ports are `28501`, `28502`, and `28503`. User clarified on 2026-06-05 that no one plays on this server, so lab automation may use any port; a separate temporary port/process is still useful for cleanup and repeatability.

### DrLex Frogbots

Repository: https://github.com/DrLex0/quake-frogbots

Why it matters:

- Historical Frogbot lineage.
- Useful for understanding original bot assumptions and route logic.
- Not the first implementation target unless KTX integration blocks us.

## Analysis and data sources

### Komodobots lab automation

Preferred local runner: `C:\Users\benya\projects\quakeworld\komodobots\scripts\run_bot_lab.py`

Implementation/default runner: `C:\Users\benya\projects\quakeworld\komodobots\scripts\run_frobodm2_lab.py`

Local client shim: `C:\Users\benya\projects\quakeworld\komodobots\experiments\qw_min_client.py`

Movement metrics extractor: `C:\Users\benya\projects\quakeworld\komodobots\scripts\extract_movement_metrics.py`

Moveprobe plausibility summarizer: `C:\Users\benya\projects\quakeworld\komodobots\scripts\summarize_moveprobe_plausibility.py`

Route-state diagnosis helper: `C:\Users\benya\projects\quakeworld\komodobots\scripts\diagnose_route_state.py`

Route-state attribution helper: `C:\Users\benya\projects\quakeworld\komodobots\scripts\attribute_route_state_windows.py`

Route-edge geometry helper: `C:\Users\benya\projects\quakeworld\komodobots\scripts\inspect_route_edge_geometry.py`

Human MVD analysis scaffold: `C:\Users\benya\projects\quakeworld\komodobots\scripts\analyze_human_mvd.py`

Exact-player reference aggregate helper: `C:\Users\benya\projects\quakeworld\komodobots\scripts\summarize_reference_aggregate.py`

Player movement signature helper: `C:\Users\benya\projects\quakeworld\komodobots\scripts\summarize_player_movement_signatures.py`

Cadence normalization decision helper: `C:\Users\benya\projects\quakeworld\komodobots\scripts\decide_cadence_normalization.py`

KTX movement probe patch: `C:\Users\benya\projects\quakeworld\komodobots\experiments\ktx_moveprobe\frogbot-moveprobe.patch`

Why it matters:

- `scripts/run_bot_lab.py` is the preferred one-command lab runner entry point.
- The runner SSHes to `servexeri`, creates a named MVDSV/KTX screen session, loads a selected map, runs the client shim, copies the generated MVD to `artifacts/lab-runs/<run-id>/`, parses it through WSL `qw-analyze-v20`, writes `run-summary.md` plus `movement-metrics.md`, and stops only its owned screen session.
- `experiments/qw_min_client.py` is the protocol-narrow connected-client control path for KTX commands such as `botcmd addbot`.
- `scripts/extract_movement_metrics.py` derives per-player horizontal speed, distance, speed-threshold time ratios, stationary time, airborne proxy, and jump cadence from `events.txt` kind `5` player origin samples. S7b added an indexed landing-window speed lookup so long 4on4 human traces can produce movement metrics in seconds instead of timing out in repeated full-list scans.
- `scripts/summarize_moveprobe_plausibility.py` combines per-run `movement-metrics.json` and `moveprobe-commands.json` artifacts into an explicit command-coverage plus stationary/low-speed gate. S7c carries `jump_cadence_per_min` from movement metrics into committed S3g bot summaries.
- `scripts/diagnose_route_state.py` joins position segments, sampled moveprobe commands, and map-entity locations to identify low-speed windows and whether current artifacts contain route node/goal/obstruction state.
- `scripts/attribute_route_state_windows.py` decodes route-state low-speed windows against KTX/Frogbot flag definitions and `.bot` route-map edges, producing compact S6 attribution evidence without changing controller behavior.
- `scripts/inspect_route_edge_geometry.py` inspects one Frogbot `.bot` edge, its reciprocal/direct neighborhood, static marker-origin availability, and matching S6 attribution samples to decide whether a route-data geometry fix is justified.
- `scripts/analyze_human_mvd.py` inventories local human `.mvd` candidates, copies one selected demo into `artifacts/human-demos/<run-id>/`, parses it through the same `qw-analyze-v20` and movement-metrics path, and writes compact human comparison summaries.
- `scripts/summarize_reference_aggregate.py` combines a tiny exact-player reference set into committed JSON/Markdown ranges and compares them against same-map S3g bot rows. S7c compares bot rows across every reference field, including cadence.
- `scripts/summarize_player_movement_signatures.py` turns exact-player aggregates into compact S7 signature scaffolds, explicitly separating broad S3g-vs-human movement gaps from candidate player-style axes. S7b adds repeated-player stability axes that compare between-player mean spread against within-player spread; S7c treats cadence as bot-comparable instead of reference-only.
- `scripts/decide_cadence_normalization.py` consumes the S7c aggregate and derives non-stationary, non-low-speed, and airborne-proxy normalized cadence comparisons before any cadence controller work.
- `experiments/ktx_moveprobe/frogbot-moveprobe.patch` is the first S2 KTX source probe. It applies to KTX commit `08807da`, hooks `src/bot_movement.c::BotSetCommand()` after the prewar-freeze guard, and adds cvar-controlled command perturbation immediately before button assembly and `trap_SetBotCMD(...)`.
- The same patch includes v2a command instrumentation. When `k_fb_moveprobe_log_commands=1`, KTX prints sampled `FBMOVEPROBE_CMD` rows containing the final `msec`, angles, movement command values, buttons, and impulse about to be sent to `trap_SetBotCMD(...)`.
- The patch also includes v2b mode `3`, a route-yaw probe that sets yaw from `self->fb.dir_move_`, emits simple movement command values, and forces jump when a route direction is available.
- The patch now includes S3a mode `4`, a bounded route-yaw plus alternating-sidemove probe. It is a disposable movement-literacy experiment, not a final bunnyjump controller.
- The patch now includes S3d mode `5`, an aim-independent projection probe that preserves combat view yaw and projects route/strafe intent into local forward/side commands.
- S3e command rows can include diagnostic fields as `diag=route_yaw,view_yaw,yaw_delta,backward`, and the summarizer reports backward-command ratio plus absolute yaw-delta average/p90/>90-degree ratios.
- The patch now includes S3f mode `6`, a no-backpedal variant of mode `5` that folds negative local `forwardmove` into `sidemove` and clamps local forward to `0`.
- The patch now includes S3g mode `7`, a bounded variant of mode `6` that normalizes local horizontal command magnitude back to the original route/strafe intent magnitude.
- S6e modifies mode `7` only at water edges: when `waterlevel > 1`, it preserves the native pre-probe vertical `direction[2]`; otherwise mode `7` keeps using `k_fb_moveprobe_upmove`.
- The patch now includes S6b diagnostic route-state logging as `route=linked_marker,touch_marker,goal_ed,goal_marker,path_state,bot_state,blocked,dir_speed` appended to sampled `FBMOVEPROBE_CMD` rows.
- The patch now includes S6d diagnostic water/swim logging as `water=waterlevel,watertype,flags,swim_arrow,emitted_upmove,velocity_xyz,dir_move_xyz` appended to sampled `FBMOVEPROBE_CMD` rows after the `route=` suffix.
- `scripts/run_frobodm2_lab.py` parses those command rows into `moveprobe-commands.json` and `moveprobe-commands.md` beside the normal MVD, parser, and movement-metrics artifacts.
- `scripts/run_frobodm2_lab.py` parses S6d water rows into nested `water_state` command data and summarizes waterlevels, watertypes, player flags, swim arrows, emitted upmove, velocity Z, and raw route `dir_move` Z.
- `scripts/diagnose_route_state.py` now consumes the nested `route_state` command data and reports marker/goal/path-state/blocked context for low-speed windows.
- `scripts/attribute_route_state_windows.py` uses KTX `include/fb_globals.h`, `include/g_consts.h`, `src/route_calc.c`, `src/bot_botwater.c`, `src/bot_movement.c`, and `resources/example-configs/ktx/bots/maps/dm3.bot` to decode S6b/S6d/S6e repeated marker/path-state/water-state patterns.
- `experiments/ktx_moveprobe/evidence/` keeps small committed derived summaries for important S3 runs while raw MVDs and per-run directories remain outside Git under `artifacts/`. S7c regenerated the S3g summary from existing artifacts to include bot-side cadence.
- `experiments/human_comparison/evidence/` keeps small committed derived inventory/summary files for S4 human-demo work while raw human demos and parser event streams remain outside Git under `artifacts/human-demos/`.

Verification:

- `20260605T190849Z` and `20260605T191116Z` were successful one-command `frobodm2` lab runs on `servexeri:28599`.
- `20260605T200124Z` was a successful one-command `dm3` lab run on `servexeri:28599`.
- `20260605T201217Z` was a fresh `frobodm2` run with automatic movement metrics for `/ bro` and `/ goldenboy`.
- `20260605T201313Z` was a fresh `dm3` run with automatic movement metrics for `/ bro` and `/ goldenboy`.
- `20260605T213010Z` was a `frobodm2` S2 moveprobe mode `2` run with the patched KTX final movement command replaced by a fixed command with forced jump; bots spawned and the lab produced MVD/parser/metrics artifacts, but movement collapsed to near-stationary.
- `20260605T213149Z` was a `frobodm2` S2 moveprobe mode `1` run with the patched KTX final jump command forced while preserving Frogbot direction/combat; bots spawned, fought, recorded three frags, and produced movement metrics.
- `20260605T222006Z`, `20260605T222047Z`, and `20260605T222129Z` were the S2 v2a emitted-command comparison runs for stock mode `0`, forced-jump mode `1`, and fixed-command mode `2`. Each completed the MVD/parser/metrics loop and wrote `moveprobe-commands.*`; mode `2` produced constant `yaw=90 forward=800 side=0 up=0 buttons=2` command logs while movement collapsed.
- `20260605T224811Z` was the S2 v2b route-yaw mode `3` run. It completed the MVD/parser/metrics loop and wrote `moveprobe-commands.*`; `/ goldenboy` moved plausibly, but `/ bro` had high stationary time, motivating v2c.
- `20260605T225720Z` and `20260605T225802Z` were fresh S2 v2c route-yaw mode `3` runs on `frobodm2` and `dm3`. All four bot rows passed the explicit v2c command/plausibility gate.
- `20260605T231033Z` and `20260605T231115Z` were S3a mode `4` alternating-strafe runs on `frobodm2` and `dm3`. The command logs proved nonzero side commands, but the `dm3` run failed the low-speed gate for `/ bro`.
- `20260605T231737Z` and `20260605T231819Z` were S3b `dm3` mode `4` parameter runs. `sidemove=200` passed the side/plausibility gate for both bots; `sidemove=300` still failed `/ bro` on low-speed.
- `20260605T233120Z` and `20260605T233202Z` were S3c mode `4` runs with `sidemove=200` on `frobodm2` and `dm3`. All four bot rows passed the side/plausibility gate, making `200` the first repeatable route-yaw strafe candidate. This still does not solve aim/movement separation.
- `20260605T234620Z` and `20260605T234701Z` were S3d mode `5` aim-independent projection runs. Command coverage passed for all rows, but `/ bro` failed stationary/low-speed gates on both maps while `/ goldenboy` passed.
- `20260606T000331Z` and `20260606T000414Z` were S3e mode `5` diagnostic runs. The diagnostic command logs showed higher yaw-delta/backward-command ratios for the worst `dm3` `/ bro` case, but `dm3` `/ goldenboy` still failed low-speed with a lower backward ratio, so yaw conflict is a partial explanation rather than the whole movement bug.
- `20260606T001705Z` and `20260606T001825Z` were S3f mode `6` no-backpedal runs on `dm3` and `frobodm2`. All four bot rows passed the horizontal/side/jump behavior gate with `0.0%` backward commands. The correction is positive evidence, but command logs show very large side values around `1100`, so it is not yet a realistic controller.
- `20260606T003718Z` and `20260606T003808Z` were S3g mode `7` bounded no-backpedal runs on `dm3` and `frobodm2`. All four bot rows passed with `0.0%` backward commands and sampled horizontal command magnitude capped near `824.6`.
- `s4a-1on1-reppie-vs-locust-aerowalk` parsed local human demo `1on1_reppie_vs_locust_aerowalk.mvd` through the same parser and movement metrics pipeline. It is a parser proof on `aerowalk`, not a DM2 baseline. The local inventory under `C:\Users\benya\projects\quakeworld\data\quake-development\clients\xerialqw-bench\qw\matchinfo\demos` contained five demos and zero filename-inferred `dm2` candidates; inventory map inference is a filename-token heuristic, not content parsing.
- `s4b-dm2-blue-vs-red-20260228-0512` parsed one true DM2 human 4on4 demo selected from `servexeri:/mnt/usb-ssd/4on4-corpus/demos/`. The corpus manifest had 6,409 rows, 1,598 DM2 rows, 1,450 `4on4_` DM2 rows, and 1,171 cleanish 4on4 DM2 rows after excluding `tmp` and missing files. The selected file was `4on4_blue_vs_red[dm2]20260228-0512.mvd`, SHA-256 `f8269d8139b129426b569eaf6b2be278964d740bd0365647f4410db74da76585`.
- `s4c-dm3-blue-vs-red-20260426-0307` parsed one map-matched human `dm3` 4on4 demo selected from the same existing corpus. The exact `[dm3]` inventory had 1,663 rows, 1,629 `4on4_` rows, 1,247 cleanish existing rows, and 444 moderate-size cleanish 2026 rows. The selected file was `4on4_blue_vs_red[dm3]20260426-0307.mvd`, SHA-256 `6897a00a4c185751ac82c579c091437cc5b82701df14cc2178da4792924ad4fe`.
- `s5a-milton-dm3-blue-vs-anza-20260602-2022` parsed one exact `Milton` `dm3` 4on4 reference demo selected by Turso `player_games` metadata cross-referenced with the same corpus manifest. The selected file was `4on4_blue_vs_anza[dm3]20260602-2022.mvd`, SHA-256 `9ca8f72b3afa95ba87830a83478c51bb9b3dd626b733190a4ca2d84b4d66490e`.
- `s5b-elite-dm3` aggregates three exact-player `dm3` references: `Milton`, `carapace`, and `yeti`. It shows the reference p95 range is `505.8` to `535.0` qu/s, while S3g `dm3` bots are `361.0` to `375.3`.
- `s7a-player-signatures-dm3` builds the first exact-player movement-signature scaffold from the S5b `Milton`/`carapace`/`yeti` aggregate. It keeps avg/p95 as generic S3g-vs-human land-speed gaps, marks low-speed and cadence as thin candidate axes, and triggers the stop condition because the current set is one demo per player.
- `s7b-repeated-elite-dm3` selects and parses one additional manifest-backed `dm3` reference for each target player: `Milton` from `4on4_blue_vs_red[dm3]20260601-1914.mvd`, `carapace` from `4on4_-s-_vs_]sr[[dm3]20260520-2032.mvd`, and `yeti` from `4on4_red_vs_blue[dm3]20260528-2109.mvd`. `s7b-player-signatures-dm3` aggregates six rows and finds cadence is the only repeated reference-only candidate axis; avg/p95 remain generic land-speed gaps and low/air/stationary overlap too much for controller targets.
- `s7c-bot-comparable-cadence-dm3` regenerates the committed S3g summary from existing artifacts so bot rows carry cadence, then writes `human-reference-s7c-bot-comparable-cadence-dm3-aggregate.*` and `player-signatures-s7c-dm3.*`. Cadence is now a bot-comparable repeated candidate axis: `/ bro` is above the human cadence range and `/ goldenboy` is within it, while avg/p95 remain generic land-speed gaps.
- `s7d-cadence-normalization-dm3` derives cadence per non-stationary minute, non-low-speed minute, and airborne-proxy minute from the S7c aggregate. It keeps cadence as diagnostic rather than controller-authorizing because both S3g bots are above the exact-player airborne-proxy-normalized range.
- `s6a-route-state` diagnoses S3g `dm3` run `20260606T003718Z`. The existing artifacts expose position traces, sampled final commands, route yaw, view yaw, yaw delta, backward command state, and map-entity locations, but no Frogbot route node, next waypoint, target entity, obstruction, or route primitive state. Eight of nine analyzed top low-speed windows still had average sampled horizontal command at or above `400`.
- `s6b-route-state` diagnoses S6b `dm3` run `20260606T031102Z` with the new `route=` command suffix. Route-state context is now available; `/ bro` had `17` low-speed windows, repeated `water.LG` windows tagged with linked/goal marker `59`, path state `32768`, and `blocked=0`, while `/ goldenboy` had no S6-threshold low-speed windows.
- `s6d-water-path` diagnoses S6d `dm3` run `20260606T041805Z` with the new `water=` command suffix. The repeated `/ bro` `water.LG` windows again had strong sampled commands, linked/goal marker `59`, `WATER_PATH`, and `blocked=0`; water-state attribution showed window samples at waterlevel `1` with occasional `2`, no deep-water samples, `swim_arrow=0`, and emitted `upmove=0`.
- `s6f-route-edge-geometry` inspects the static `dm3.bot` route edge `276->59` and S6d/S6e attribution samples. The edge and its reciprocal are explicit, but marker `276` has no static `CreateMarker` origin, so no precise static edge vector or tiny coordinate fix is justified from the route file alone.
- Stock `dm2` has `dm2.bsp` and `dm2.loc`, but no `ktx/bots/maps/dm2.bot`; do not treat stock `dm2` as a Frogbot-supported map unless a real route appears.

### mvd_analyzer

Repository: https://github.com/galfthan/mvd_analyzer

Local checkout: `C:\Users\benya\projects\quakeworld\tools\mvd_analyzer`

Observed local commit during the 2026-06-05 headless environment inspection: `fab7808`.

Why it matters:

- Parses QuakeWorld MVDs into structured analysis.
- Important for measuring both human demos and bot-generated MVDs.
- MVDs provide server-side state/event traces, not normal player usercmd labels.

Relevant areas:

- `mvd-reader/MVD_FORMAT.md`
- `mvd-analytics/RESULT_SCHEMA.md`
- CLI: `mvd-analytics/cmd/qw-analyze`

Runtime note:

- WSL `Ubuntu-24.04` has a prebuilt `~/mvd-mcp-bundle/` with `mvd-api`, `mvd-mcp`, `run-mcp.sh`, and `bsps/dm2.bsp`.
- Bundle README says it was built from commit `7d83ebe`; this differs from the local source checkout and should be pinned before metrics become regression evidence.

### ezquake-render-runner / ezquake-test

Repository: `Xerialen/ezquake-render-runner`

Local checkout: `C:\Users\benya\projects\quakeworld\hud\ezquake-test`

Observed local commit during the 2026-06-05 headless environment inspection: `64156c9`.

Why it matters:

- Existing headless ezQuake/Xvfb render harness used for HUD validation.
- Useful for visual validation after lab MVDs exist.
- Not sufficient by itself for Komodobots server experiments because it replays existing demos rather than starting KTX/MVDSV or generating new MVDs.

### qw-sim

Repository: `Xerialen/qw-sim` private

Why it matters:

- Existing QuakeWorld data/simulation foundation.
- Fuses parser outputs and stores demo-derived data.
- Candidate place to compare bot-generated MVDs against human movement distributions.

### fantasyquake

Repository: `Xerialen/fantasyquake` private

Why it matters:

- Product-side origin of the simulation need.
- FantasyQuake is one possible long-term destination for Komodobots.

### ezquake-source

Repository: `Xerialen/ezquake-source` private mirror/source reference

Why it matters:

- Useful for understanding client usercmd construction.
- Example: default `cl_forwardspeed`, `cl_sidespeed`, and command clamping.

## External conceptual sources

### Meag KTX/Frogbots blog/discussion

URL: https://www.quakeworld.nu/blog/396

Why it matters:

- Historical design context around KTX/Frogbots integration.
- Mentions hard problems such as route learning, strafejumping, rocket jumps, and static route limitations.
- Old source; use as context, not as current truth.

### Bunnyjump tutorial video

URL: https://www.youtube.com/watch?v=3e_W1VYuAME

Why it matters:

- Potential supplementary source if video analysis or manual review becomes useful.
- Reportedly shows bunnyjump technique with live key/button presses.
- Not a core dependency for the first lab.

## Source hygiene rules

- Prefer current source code over historical comments.
- Treat old blog/forum posts as design context only.
- Pin commits when making claims about code behaviour.
- Record any local forks and patches here.
- If Codex discovers a new source, add it here before relying on it.
