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

Cadence evidence broadening helper: `C:\Users\benya\projects\quakeworld\komodobots\scripts\broaden_cadence_evidence.py`

Airborne proxy segment inspector: `C:\Users\benya\projects\quakeworld\komodobots\scripts\inspect_airborne_proxy_segments.py`

Land-speed gap characterization helper: `C:\Users\benya\projects\quakeworld\komodobots\scripts\characterize_land_speed_gap.py`

Controller probe target decision helper: `C:\Users\benya\projects\quakeworld\komodobots\scripts\choose_controller_probe_target.py`

Air-transition probe design helper: `C:\Users\benya\projects\quakeworld\komodobots\scripts\design_air_transition_probe.py`

Air-transition probe comparison helper: `C:\Users\benya\projects\quakeworld\komodobots\scripts\compare_air_transition_probe.py`

S7j failed-bucket diagnosis helper: `C:\Users\benya\projects\quakeworld\komodobots\scripts\diagnose_s7j_failed_buckets.py`

Context-gated probe design helper: `C:\Users\benya\projects\quakeworld\komodobots\scripts\design_context_gated_probe.py`

QWD POV usercmd extractor: `C:\Users\benya\projects\quakeworld\komodobots\tools\qwd_usercmd\qwd_usercmd.py`

QWD trajectory route applicability probe: `C:\Users\benya\projects\quakeworld\komodobots\scripts\probe_qwd_route_applicability.py`

QWD-to-Frogbot route mapping helper: `C:\Users\benya\projects\quakeworld\komodobots\scripts\map_qwd_route_to_frogbot.py`

QWD SNG hybrid probe design helper: `C:\Users\benya\projects\quakeworld\komodobots\scripts\design_qwd_sng_hybrid_probe.py`

QWD SNG hybrid probe comparison helper: `C:\Users\benya\projects\quakeworld\komodobots\scripts\compare_qwd_sng_hybrid_probe.py`

QWD SNG hybrid probe diagnosis helper: `C:\Users\benya\projects\quakeworld\komodobots\scripts\diagnose_qwd_sng_probe.py`

QWD SNG MVD crossing inspector: `C:\Users\benya\projects\quakeworld\komodobots\scripts\inspect_qwd_sng_mvd_crossings.py`

QWD SNG slow-success attribution helper: `C:\Users\benya\projects\quakeworld\komodobots\scripts\diagnose_qwd_sng_slow_success.py`

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
- `scripts/broaden_cadence_evidence.py` consumes the S7c aggregate plus existing `dm3` mode-7 bot movement artifacts to broaden S7e cadence evidence without rerunning KTX or changing controller behavior.
- `scripts/inspect_airborne_proxy_segments.py` replays the movement-metrics airborne proxy over raw `events.txt` kind `5` samples for the S7 exact-player references and unchanged mode-7 bot rows, producing compact S7f segment distribution evidence without rerunning KTX.
- `scripts/characterize_land_speed_gap.py` consumes the S7f row set and existing raw artifacts to bucket accepted movement segments by airborne-proxy overlap, pre/post-air windows, sampled command strength, and route-state hints, producing compact S7g land-speed context without rerunning KTX.
- `scripts/choose_controller_probe_target.py` consumes S7g land-speed context and chooses the first controller-probe target, preferring human-comparable air-transition evidence over narrow bot-only route diagnostics unless comparable evidence is missing.
- `scripts/design_air_transition_probe.py` consumes committed S7g/S7h/S7e evidence and writes the S7i air-transition probe contract, required post-probe measurements, and stop conditions before any controller behavior changes.
- `scripts/compare_air_transition_probe.py` evaluates a follow-up bot probe against the committed S7i contract. It combines the new bot run with the S7f reference rows, reruns S7g-style context buckets, reports transition-probe activation, preserves cadence as diagnostic, and applies the S7i stop conditions.
- `scripts/diagnose_s7j_failed_buckets.py` consumes the corrected S7j result plus S7g baseline context and recomputes per-segment command/probe/route context for the failed pre-air, airborne-proxy, and non-airborne buckets before another movement probe.
- `scripts/design_context_gated_probe.py` consumes the committed S7k diagnosis and writes the S7l design-only context gate for the next probe. It separates clean air-transition candidate slices from route-guardrail/measurement-risk slices and requires future success claims to be made on clean-context buckets rather than all-segment or route-dirty gains.
- `tools/qwd_usercmd/qwd_usercmd.py` extracts exact first-person `.qwd` POV-demo `usercmd_t` streams into `komodobots.qwd_usercmd.v1` line-delimited JSON. It is the Phase 1 action-label path for human commands, separate from MVD state/evaluation evidence.
- `scripts/probe_qwd_route_applicability.py` measures the Phase 2 QWD bridge: exact `dem_cmd` rows paired with anchored self-player `svc_playerinfo` origin/velocity rows, plus continuity splits and waypoint downsampling for route/controller applicability. It is evidence for trajectory extraction, not a Frogbot `.bot` route importer or replay controller.
- `scripts/map_qwd_route_to_frogbot.py` maps one extracted QWD trajectory onto the existing Frogbot `dm3.bot` marker graph. It measures nearest-marker fit, collapsed marker sequence, direct `.bot` edge coverage, shortest graph paths, and recommends route-following, command-imitation, or a hybrid waypoint/controller probe.
- `scripts/design_qwd_sng_hybrid_probe.py` consumes the committed `dm3_sng_shortcut.qwd` route-mapping artifact and writes the first design-only contract for a temporary KTX hybrid waypoint/controller probe. It preserves the QWD waypoint string, side-dominant command profile, diagnostics requirements, and stop conditions without changing KTX or Frogbot behavior.
- `scripts/compare_qwd_sng_hybrid_probe.py` scores temporary mode-9 SNG hybrid server-loop runs against that design contract. It requires QWD activation, control-point advancement, command/MVD window overlap, route/water/cadence diagnostics, active command-profile coverage, and slow/route-dirty guardrails before any positive claim. It records first active in-window target distance and active control-point phases, rejects loose-start advancement and unresolved post-advance target phases, and now consumes optional `moveprobe-qwd-events.json` rows as event-level activation/advancement proof when a rerun produces them.
- `scripts/diagnose_qwd_sng_probe.py` aligns mode-9 command-log server time to MVD-relative event time, checks closest MVD approach to QWD control points, and classifies whether failures are timing-window, start-context, guardrail, inconclusive start-proof, or control-point advancement issues before another live run. It prefers the actual run's recorded QWD radii over design defaults so setup-repair reruns are diagnosed with their real activation radius, and it preserves scorer-reported inconclusive gates such as `tight_start_activation` instead of collapsing every MVD-overlapped rejection into a setup-repaired verdict.
- `scripts/inspect_qwd_sng_mvd_crossings.py` derives first CP0 start-radius entry and sequential point-radius entries directly from MVD position samples, then compares those physical crossings against the first sampled QWD command row. It is an evidence-density diagnostic: it can prove physical control-point traversal, but it does not prove internal mode-9 activation timing by itself.
- `scripts/diagnose_qwd_sng_slow_success.py` consumes the setup-repaired mode-9 SNG run and splits active QWD commands by current control-point target, joins each phase to MVD movement segments, and attributes slow-success failures to setup radius, route/map context, command-profile weakness, or post-control-point progression gaps.
- `scripts/build_replay_command_file.py` builds the open-loop replay command file (`komodobots.replay.v1`) for KTX moveprobe mode 10. It pairs exact `tools/qwd_usercmd` commands with anchored `probe_qwd_route_applicability` origin/velocity by frame order and emits one line per frame (`msec ox oy oz vx vy vz pitch yaw roll fwd side up buttons`); frame 0 is the bot snap state, every frame is the divergence reference. The stream is too large for a cvar, so KTX reads it from a file. See `docs/08_DECISION_LOG.md` for the KTX-vs-ezQuake decision.
- `scripts/run_frobodm2_lab.py` (mode 10 wiring) adds `--replay-cmds` (uploads the replay file to `~/nquakesv/ktx/bots/replay/` and sets `k_fb_moveprobe_replay_file`) and `--record-trick-name` (dual-writes the run's demo to `tricks/dm3/` and the local nQuake demo mirror for watching beside the human tricks).
- `experiments/ktx_moveprobe/frogbot-moveprobe.patch` is the first S2 KTX source probe. It applies to KTX commit `08807da`, hooks `src/bot_movement.c::BotSetCommand()` after the prewar-freeze guard, and adds cvar-controlled command perturbation immediately before button assembly and `trap_SetBotCMD(...)`.
- The same patch includes v2a command instrumentation. When `k_fb_moveprobe_log_commands=1`, KTX prints sampled `FBMOVEPROBE_CMD` rows containing the final `msec`, angles, movement command values, buttons, and impulse about to be sent to `trap_SetBotCMD(...)`.
- The patch also includes v2b mode `3`, a route-yaw probe that sets yaw from `self->fb.dir_move_`, emits simple movement command values, and forces jump when a route direction is available.
- The patch now includes S3a mode `4`, a bounded route-yaw plus alternating-sidemove probe. It is a disposable movement-literacy experiment, not a final bunnyjump controller.
- The patch now includes S3d mode `5`, an aim-independent projection probe that preserves combat view yaw and projects route/strafe intent into local forward/side commands.
- S3e command rows can include diagnostic fields as `diag=route_yaw,view_yaw,yaw_delta,backward`, and the summarizer reports backward-command ratio plus absolute yaw-delta average/p90/>90-degree ratios.
- The patch now includes S3f mode `6`, a no-backpedal variant of mode `5` that folds negative local `forwardmove` into `sidemove` and clamps local forward to `0`.
- The patch now includes S3g mode `7`, a bounded variant of mode `6` that normalizes local horizontal command magnitude back to the original route/strafe intent magnitude.
- S6e modifies mode `7` only at water edges: when `waterlevel > 1`, it preserves the native pre-probe vertical `direction[2]`; otherwise mode `7` keeps using `k_fb_moveprobe_upmove`.
- The patch now includes S7j mode `8`, a temporary air-transition horizontal-command budget probe. It starts from mode `7`, scales desired horizontal command only in takeoff/recent-air/recent-landing windows, preserves the mode-7 water-edge upmove behavior, and appends `probe=active,on_ground,since_ground,since_air,scale` to sampled command rows.
- The patch now includes QWD-derived mode `9`, a temporary `dm3` SNG hybrid waypoint/controller probe. It reads a bounded QWD waypoint string, activates near the first SNG control point, advances control points by radius, projects waypoint attraction plus side-dominant QWD-style movement into preserved combat view yaw, and appends `qwd=active,index,count,distance,advanced,complete,active_seconds` to sampled command rows.
- Mode `9` now also emits unsampled `FBMOVEPROBE_QWD_EVENT` rows on QWD `activate`, `advance`, and `complete` edges when command logging is enabled. These rows preserve target/next indices, distance, advanced count, active/complete flags, active seconds, and origin so a future rerun can prove internal activation/advance timing without relying on sparse sampled command rows.
- The patch now includes S6b diagnostic route-state logging as `route=linked_marker,touch_marker,goal_ed,goal_marker,path_state,bot_state,blocked,dir_speed` appended to sampled `FBMOVEPROBE_CMD` rows.
- The patch now includes S6d diagnostic water/swim logging as `water=waterlevel,watertype,flags,swim_arrow,emitted_upmove,velocity_xyz,dir_move_xyz` appended to sampled `FBMOVEPROBE_CMD` rows after the `route=` suffix.
- `scripts/run_frobodm2_lab.py` parses those command rows into `moveprobe-commands.json` and `moveprobe-commands.md` beside the normal MVD, parser, and movement-metrics artifacts.
- `scripts/run_frobodm2_lab.py` parses S6d water rows into nested `water_state` command data and summarizes waterlevels, watertypes, player flags, swim arrows, emitted upmove, velocity Z, and raw route `dir_move` Z.
- `scripts/run_frobodm2_lab.py` parses S7j probe rows into nested `probe_state` command data and summarizes transition-active sample counts, active ratios, and active scale values.
- `scripts/run_frobodm2_lab.py` passes mode-9 QWD waypoint/radius cvars through base64-safe remote shell transport, parses nested `qwd_state` command data, and summarizes QWD activation, control-point index/count, target distance, advanced points, completion, and active seconds.
- `scripts/run_frobodm2_lab.py` parses `FBMOVEPROBE_QWD_EVENT` rows into `moveprobe-qwd-events.json` and `moveprobe-qwd-events.md`; run summaries include the parsed QWD event count.
- `experiments/ktx_moveprobe/frogbot-moveprobe-perslot.patch` (LD-F1 #95) adds the per-slot cvar convention `k_fb_moveprobe_<param>_s<N>` (`mode`, `replay_file`, `fixed_goal`, `spawn_origin`; `N` = the bot's `ed`), bounded per-slot replay-file stores, `FBMOVEPROBE_ASSIGN` assignment rows, and `FBMOVEPROBE_PERSLOT_ERROR` loud failures with hold-at-spawn. It applies to the LIVE deployed lab tree (not pristine `08807da`); base checksums and apply notes live in `experiments/ktx_moveprobe/README.md`.
- `scripts/moveprobe_parse.py` additionally parses `FBMOVEPROBE_ASSIGN` and `FBMOVEPROBE_PERSLOT_ERROR` rows (`parse_moveprobe_assign_logs`, `parse_moveprobe_perslot_error_logs`); `scripts/run_frobodm2_lab.py` writes them to `moveprobe-assignments.json` and `moveprobe-assignments.md` and accepts `--extra-replay-cmds` for uploading additional per-slot route files.
- `scripts/diagnose_route_state.py` now consumes the nested `route_state` command data and reports marker/goal/path-state/blocked context for low-speed windows.
- `scripts/attribute_route_state_windows.py` uses KTX `include/fb_globals.h`, `include/g_consts.h`, `src/route_calc.c`, `src/bot_botwater.c`, `src/bot_movement.c`, and `resources/example-configs/ktx/bots/maps/dm3.bot` to decode S6b/S6d/S6e repeated marker/path-state/water-state patterns.
- `experiments/ktx_moveprobe/evidence/` keeps small committed derived summaries for important S3 runs while raw MVDs and per-run directories remain outside Git under `artifacts/`. S7c regenerated the S3g summary from existing artifacts to include bot-side cadence.
- `experiments/human_comparison/evidence/` keeps small committed derived inventory/summary files for S4 human-demo work while raw human demos and parser event streams remain outside Git under `artifacts/human-demos/`.
- `experiments/qwd_route_probe/evidence/` keeps compact committed QWD state/action/waypoint applicability summaries, while per-frame paired NDJSON and waypoint exports remain ignored under `artifacts/qwd-route-probe/`.

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
- `s7e-cadence-evidence-dm3` broadens bot cadence evidence from existing unchanged `dm3` mode-7 artifacts: S3g `20260606T003718Z`, S6b `20260606T031102Z`, and S6d `20260606T041805Z`. S6e `20260606T044000Z` is excluded because it changed water-edge vertical command behavior.
- `s7f-airborne-segments-dm3` inspects raw airborne-proxy segment distributions from the six exact-player `dm3` reference rows and six unchanged mode-7 bot rows. Bot player-median air segments are shorter, much lower-Z, and much slower, so cadence remains diagnostic and the next work should characterize land-speed/air-rhythm gaps.
- `s7g-land-speed-gap-dm3` characterizes accepted segment speed by context using the S7f row set. Bot non-airborne p50 speed is close to exact-player non-airborne p50, but bot pre-air, airborne, and post-air windows are much slower; route WATER_PATH samples are very slow, so the next work should choose between air-transition speed production and a narrow route primitive.
- `s7h-controller-probe-target-dm3` chooses air-transition horizontal speed production as the first controller-probe target. `WATER_PATH` remains a secondary guardrail because it is very slow but bot-only and route-diagnostic rather than human-comparable.
- `s7i-air-transition-probe-design-dm3` turns the S7h target into a constrained design-only probe contract. It keeps mode-7 behavior unchanged in this PR, requires pre-air/airborne/post-air/non-air/route/cadence reporting after any follow-up probe, and rejects all-segment speed gains if air-transition buckets or WATER_PATH context get worse.
- `s7j-air-transition-probe-dm3` implements and runs the S7i mode-8 air-transition horizontal-command probe across fixed runs `20260606T163907Z` and `20260606T164610Z` after fixing the transition gate to use the pre-probe jump intent. The combined guardrail-complete evidence rejects the probe: all-segment speed improved, but pre-air and airborne-proxy p50s regressed and non-airborne p50 fell below the S7i tolerance.
- `s7k-failed-bucket-diagnosis-dm3` diagnoses the corrected S7j failed buckets without another lab run. It separates mixed controller/route-context failures in pre-air and airborne-proxy buckets from route/map-context contamination in the non-airborne guardrail, and keeps the Frogbots-vs-from-scratch decision open for one narrower context-gated probe.
- `s7l-context-gated-probe-design-dm3` turns S7k into a design-only gate for the next probe. It finds enough clean air-transition evidence to continue (`2` pre-air rows / `326` segments and `3` airborne rows / `844` segments), but requires route-dirty slices to remain guardrails rather than success evidence.
- `qwd-sng-hybrid-probe-dm3` implements the temporary QWD-derived mode `9` plumbing and runs one real `dm3` SNG server-loop probe as `20260606T221429Z`. The run preserved diagnostics and activated for `1.12` seconds, but advanced only `2` control points against the required `4`, and the activation/advancement happened outside the parsed MVD movement window. The committed result is inconclusive rather than proof that Frogbots learned SNG.
- `qwd-sng-repair-diagnosis-dm3` diagnoses that same run without rerunning KTX. `/ bro` never reached the configured start radius during the MVD window, while `/ goldenboy` activated after the MVD movement window (`47044-48082` ms aligned vs `45816` ms match duration), so the next repair should make activation overlap recorded movement evidence before changing the controller policy.
- `qwd-sng-setup-repair-dm3` reruns mode `9` with the same QWD control points, `96` qu point radius, and command profile, but widens the start radius to `320` qu. Run `20260606T231007Z` repairs the evidence-window blocker: QWD activation overlaps the parsed MVD window and `/ bro` advances `4` control points inside it. The scorer still rejects the run because `/ bro` reaches points while above the slow/stationary guardrails, so this is setup progress, not proof of learned SNG.
- `qwd-sng-tight-start-rerun-dm3` restores the original `192` qu start radius with unchanged mode `9` projection and diagnostics. Run `20260607T003837Z` advances up to `12` control points inside the MVD window, but the scorer still rejects it on unresolved phase-target progression and `/ bro` slow-success guardrails; the regenerated diagnosis verdict is `qwd_sng_start_evidence_inconclusive` because the current sampled command log cannot verify pre-advance CP0 tight-start evidence when the first active row is already at CP2.
- `qwd-sng-tight-start-mvd-crossings-dm3` inspects the same run's MVD position samples directly. `/ bro` enters CP0's `192` qu start radius at `1761` ms (`83.482` qu) and reaches `11` sequential point-radius control points; `/ goldenboy` enters CP0 at `7432` ms (`85.522` qu) and reaches `12`. The first sampled QWD command rows are still already at CP2 and nearest-MVD samples are far from CP0/CP2, so the next gap is event-level QWD activation/advance instrumentation rather than route-geometry proof.
- `s6a-route-state` diagnoses S3g `dm3` run `20260606T003718Z`. The existing artifacts expose position traces, sampled final commands, route yaw, view yaw, yaw delta, backward command state, and map-entity locations, but no Frogbot route node, next waypoint, target entity, obstruction, or route primitive state. Eight of nine analyzed top low-speed windows still had average sampled horizontal command at or above `400`.
- `s6b-route-state` diagnoses S6b `dm3` run `20260606T031102Z` with the new `route=` command suffix. Route-state context is now available; `/ bro` had `17` low-speed windows, repeated `water.LG` windows tagged with linked/goal marker `59`, path state `32768`, and `blocked=0`, while `/ goldenboy` had no S6-threshold low-speed windows.
- `s6d-water-path` diagnoses S6d `dm3` run `20260606T041805Z` with the new `water=` command suffix. The repeated `/ bro` `water.LG` windows again had strong sampled commands, linked/goal marker `59`, `WATER_PATH`, and `blocked=0`; water-state attribution showed window samples at waterlevel `1` with occasional `2`, no deep-water samples, `swim_arrow=0`, and emitted `upmove=0`.
- `s6f-route-edge-geometry` inspects the static `dm3.bot` route edge `276->59` and S6d/S6e attribution samples. The edge and its reciprocal are explicit, but marker `276` has no static `CreateMarker` origin, so no precise static edge vector or tiny coordinate fix is justified from the route file alone.
- Stock `dm2` has `dm2.bsp` and `dm2.loc`, but no `ktx/bots/maps/dm2.bot`; do not treat stock `dm2` as a Frogbot-supported map unless a real route appears.

### Lab dashboard frontend (lab/dashboard)

Canonical home since LD-A1 (#84): `lab/dashboard/` in this repository — a self-contained
Vite + React + TypeScript + three.js app built with base `/botlab/`.

Hosted dashboard CI (LD-A3, #86): `.github/workflows/lab-dashboard-ci.yml`.
It runs on GitHub-hosted `ubuntu-latest` for PRs touching `lab/**` or
`tests/lab_*.py` (lab pytest files, which `PR Tests`' `test_*.py` unittest
discovery does not pick up), installs
`lab/dashboard` with `npm ci`, runs `tsc --noEmit`, optional `npm run lint`,
`vite build`, and cheap Python checks for `lab/server` / future `lab/tools`.
This workflow is separate from `.github/workflows/lab-ci.yml`, the manual
self-hosted servexeri bot-lab runner.

Provenance: absorbed from the separate `Xerialen/local-hub` repo, branch
`feat/botlab-viewer`, where the page existed only as `deploy/frontend-botlab.patch`
against a gitignored clone of `quakeworldnu/hub.quakeworld.nu` plus
`deploy/botlab-assets/`. The ported sources (`telemetryClient.ts`, `BotLab3D.tsx`,
`TelemetryHud.tsx`, `quakeCoords.ts`) are functionally identical to the patch versions;
the app shell (`App.tsx`, `main.tsx`) was adapted to drop the hub fork's `@qwhub/*`
dependencies. LD-B2 (#88) replaced the temporary `/qtv/` iframe with the standalone
`panes/qtv.html` same-origin FTE WASM pane and removed the `FteQtvPlayer` hub-fork
dependency entirely. Assets `public/dm3.obj` and `public/dm3_sng_to_rl.cmds`
match the local-hub blobs byte-for-byte (verified by git blob SHA:
`d23bbfa` / `da9a987`).

LD-B1 (#87) added the view shell: `src/layoutState.ts` (fixed view order, `?views=` /
localStorage persistence) and an `App.tsx` top bar + pane grid that rehomes the LD-A1
Live 3D scene and live-game iframe into their fixed pane slots (Demo/Mockup/dock/drawer
are labeled placeholders for LD-C3/LD-E1/LD-F3; Demo landed in LD-D3).

LD-D3 (#98) implemented the Demo view:

- `src/DemoPane.tsx` — Demo view React component. Picker header with two source tabs:
  **Records** (fetches `/demos/records/records.json` in `komodobots.records.v1` schema;
  groups by route → kind; click-to-play with `event_t_s` seek) and **Archive** (fetches
  `/v2/demos.json`; walks the `["non-games","lab","Komodobots"]` subtree; map-filterable;
  newest-first). Player area is the `public/panes/demo.html` iframe mounted once a demo
  is selected, then reloaded via `{cmd:"load"}` postMessage (no React re-mount between
  demos). Exports `OpenDemoParams`, `DemoContext`, and `DemoPaneHandle` types; the handle
  ref carries `openDemo` for the shell.
- `src/App.tsx` additions:
  - `openDemo(params: OpenDemoParams)` — shell-level entry point (SPEC §6.5). Opens
    the Demo view if closed, then posts `{cmd:"load"}` via `DemoPaneHandle`. Exported
    as the single entry point for LD-E4 (#104) record clicks.
  - `ShellActionsContext` / `useShellActions()` — React context that provides
    `openDemo` to child components (KPI dock, future LD-E4) without prop-drilling.
  - `demoContext` state: receives `{map, route?}` from `DemoPane.onContext` while a
    demo is playing; displayed in the status bar; wired to the shared context store in
    LD-E3 (#100).
  - The Demo pane placeholder is replaced by the real `<DemoPane>` component.

LD-B3 (#89) extracted the reusable map-scene module:

- `src/mapScene.ts` — standalone Three.js scene rig consumed by `BotLab3D.tsx` and
  the future Mockup pane (LD-C3, #97).  Provides `createMapScene(container, mapName,
  qCenter?, onMeshLoaded?)` which encapsulates: scene + `PerspectiveCamera` +
  `WebGLRenderer` + `OrbitControls`, OBJ mesh loading from `/botlab/maps/<map>.obj`
  with fill/wireframe materials and Quake Z→Y rotation, resize-observer wiring, and a
  `dispose()` that frees all GPU resources.  Also exports `fetchMapCenter(mapName)` to
  resolve per-map AABB centers from the committed `public/maps/maps.json` (LD-C2).
  `BotLab3D.tsx` now delegates scene setup to `createMapScene` and retains only the
  bot-actor lifecycle (marker/trail/velocity arrow), telemetry frame loop, and reference
  path rendering.  `App.tsx` documents that one `TelemetryClient` instance is created at
  shell scope and shared across all pane consumers (single WebSocket per page; panes only
  register frameListeners, they do not own the connection).

LD-F4 (#103) extended `BotLab3D.tsx` and `TelemetryHud.tsx` for multi-bot live 3D:

- `src/BotLab3D.tsx` additions:
  - `makeNameSprite(name)` — canvas-texture `THREE.Sprite` per bot, child of the marker
    mesh, positioned above it; shows bot name without a DOM overlay.
  - Trail budget is now `MAX_TRAIL_POINTS_PER_BOT` (per-bot, not shared), so N bots each
    get a full 12 000-point trail.
  - `selectedEd` prop (optional `number | null`) controls camera follow: when null and one
    bot is active, follow first-seen (single-bot compat); when null and 2+ bots are active,
    follow their centroid (overview); when set, follow the selected bot exclusively.
  - `onBotClick` prop — raycaster fires on `pointerdown` against marker meshes and calls
    this callback with the clicked `ed`; `marker.userData.ed` carries the identity.
  - `BOT_COLORS` is now exported so downstream components can reference the same palette.
- `src/TelemetryHud.tsx` additions:
  - Per-ed accumulators (`accumRef` holds a `Map<ed, PerEdAcc>`) — hop count and air time
    tracked independently per bot; capped at `MAX_HUD_BOTS = 4` (exported).
  - Compact row (non-selected bots): name / vh / hops / onground; clickable to select.
  - Expanded row (selected or first-seen bot): full detail identical to pre-F4 display.
  - `selectedEd` and `onBotClick` props parallel the BotLab3D interface; `App.tsx` wires
    both to the same `selectedEd` state and `setSelectedEd` setter.
- `src/App.tsx` additions: `selectedEd` state (`number | null`); reset to null on
  `new_attempt` so camera re-locks to the first bot automatically.

The local-hub copy is deprecated for development; see `lab/README.md` for the dev loop.

Deployment (LD-A2, #85): `lab/deploy_dashboard.py` builds the app and ships `dist/` to
`servexeri:~/local-hub/web/botlab-staged/` (additive staging; tar-over-ssh, then rsync
runs remotely on servexeri). The live same-URL cutover (`--cutover --confirm-live`,
promoting `botlab-staged/` → `botlab/` after a tar.gz backup) is an owner-approval
step. Sibling safety is structural: rsync destinations are restricted to a two-entry
allowlist and sibling entry-HTML sha256 hashes are verified before/after every sync.
`--audit-assets` is a read-only report of legacy shared `web/assets/` chunks still
referenced outside `botlab*/`. Tests: `tests/test_deploy_dashboard.py`. Procedure and
the do-not-overwrite-siblings rule: `lab/README.md`.

Standalone panes under `public/panes/` (served at `/botlab/panes/`, outside the React
app so the FTE engine owns its own window — one engine instance per window, SPEC §10):

- `public/panes/demo.html` — LD-D2 (#94) standalone FTE WASM demo player. Params
  `?demo=<url>&map=<name>&t=<s>&track=<userid>[&duration=<s>&name=<label>]`; same-origin
  postMessage API (`load`/`seek`/`speed`/`pause`/`play` in; `status`/`time`/`ended` out);
  map `.bsp` resolves local-first (`/maps/<map>.bsp` on the lab web tier, then
  `assets.quake.world`). Plays both `.mvd` and `.qwd` (the virtual demo filename's
  extension must match the real format — FTE picks its parser by extension). Modeled on
  `local-hub/web/demos/play.html`; full behavior notes in `lab/README.md`.
- `public/panes/fte_demo.cfg` — the demo config mapped to `id1/config.cfg`, copied from
  local-hub `config_v5.cfg` with two LD-D2 changes: it boots the demo paused
  (`demo_setspeed 0` before `playdemo match`, so load hitches cannot fast-forward the
  wall-anchored demo clock) and `f_demoend` echoes the sentinel the pane converts into
  the `ended` event.
- `public/panes/qtv.html` — LD-B2 (#88) standalone FTE WASM QTV spectate pane (the Live
  In-Game view). Params `?port=<labport>&relay=<ws-relay-url>&map=<mapname>`; same-origin
  postMessage API (`attach`/`disconnect` in; `status` out with states
  `loading|connected|retrying|disconnected`). FTE boots once; subsequent attach/detach
  cycles re-issue `qtvplay tcp:127.0.0.1:<port>@<relay>` without reloading the page. The
  ~3 s retry loop on QTV disconnect is driven by the pane itself (detected via
  `svc_disconnect: EndOfDemo` in FTE console output). `f_demostart → autotrack` picks a
  bot to follow on connect. The shell (`App.tsx`) sends `{cmd:"attach"}` on every new
  attempt from telemetry; the pane's own retry loop handles the between-attempts
  reconnect without shell involvement. Map `.bsp` preload is local-first (optimization
  only; QTV fetches maps independently via `cl_download_mapsrc`). Modeled on
  `local-hub/web/watch.html` and `local-hub/frontend/src/pages/botlab/App.tsx`;
  hub-fork `FteQtvPlayer` dependency removed.
- `public/panes/fte_qtv.cfg` — the QTV config mapped to `id1/config.cfg`, copied from
  local-hub `web/config_qtv_v5.cfg` with one LD-B2 addition: `con_stayhidden 1` so the
  FTE console does not flash on QTV connect/disconnect. `f_demostart "autotrack"` is the
  connect hook (same as the local-hub config). No `playdemo` / `demo_setspeed` lines —
  this config is for live QTV streaming, not demo playback.

### Lab dashboard data builders (lab/tools)

- `lab/tools/build_routes_manifest.py` (LD-C1, #90) — stdlib builder that exports the
  committed trick census (`experiments/nav_doctrine/evidence/trick-census/census.json`)
  plus the committed human replay trajectories
  (`experiments/nav_doctrine/evidence/replay/dm3_<route>.cmds`) into the committed,
  versioned routes manifests `lab/dashboard/public/data/routes/{dm3,dm2,frobodm2,trick,index}.json`
  (schema `komodobots.routes.v1`) — the canonical "what routes exist" feed for the
  Mockup view, KPI dock and control drawer. Deterministic/idempotent (LF outputs,
  `-text` in `.gitattributes`, LF-normalized sha256 provenance hashes);
  `tests/test_build_routes_manifest.py` locks the committed outputs against a fresh
  build. Pipeline details: `docs/06_DATA_AND_MVD_PIPELINE.md` § Routes manifest.

### Lab map meshes (lab/tools/bsp_to_obj.py and bsp_to_mesh.py)

- `lab/tools/bsp_to_obj.py` (LD-C2, #91) — stdlib Quake1 BSP v29 → OBJ exporter that
  commits the previously one-off path that produced `public/dm3.obj` (2026-06-09 via
  demopasha `phase0/bsp_parse.py`). Lineage: demopasha's face/edge/surfedge walk + fan
  triangulation, `scripts/bsp_geom.py`'s stdlib-struct lump parsing. Worldmodel faces
  only, raw Quake coords, triangle-only 1-indexed `f` lines — same conventions as the
  deployed dm3.obj, so `BotLab3D.tsx` needs no changes.
- Committed OBJ outputs: `lab/dashboard/public/maps/{dm3,dm2,frobodm2,trick}.obj` plus
  `maps.json` (schema `komodobots.maps.v1`) with per-map source-BSP sha256 provenance,
  vertex/triangle counts, and the world AABB whose center is the Mockup view's
  camera-overview start point (#97). Deterministic: same BSP in → byte-identical OBJ
  out (LF outputs, `-text` in `.gitattributes`). The source BSPs are NOT committed
  (~1 MB game assets); they live in `C:\nQuake\qw\maps\` locally and
  `servexeri:~/nquakesv/qw/maps/` (verified byte-identical for dm3/frobodm2/trick;
  dm2 fetched from the lab pool). `tests/test_bsp_to_obj.py` locks the exporter on a
  synthetic in-memory BSP and the committed assets against `maps.json`. Evidence:
  `lab/evidence/ld-c2-mesh-*.png` (harness: `lab/evidence/ld-c2-meshdev.html`).
  Pipeline details:
  `docs/06_DATA_AND_MVD_PIPELINE.md` § Map meshes.
- The legacy `public/dm3.obj` (all-models export, mojibake header) stays untouched —
  the deployed viewer loads it by that path until the Mockup view (#97) switches to
  `maps/`.
- `lab/tools/bsp_to_mesh.py` (LD-C4, #92) — textured glTF binary (`.glb`) pipeline,
  successor to `bsp_to_obj.py` for the Mockup and Live 3D views. Decodes BSP v29
  miptex pixel data using the Quake 256-colour palette (loaded from `pak0.pak` or
  `palette.lmp`; canonical id1 palette also embedded as a fallback), computes per-face
  UV coordinates from texinfo `s_axis`/`t_axis`/offsets, groups worldmodel faces by
  texture into per-material glTF primitives, and emits a self-contained GLB with
  embedded PNG images. Requires stdlib only (no third-party dependencies): PNG encoding uses a
  minimal zlib-based encoder (`_encode_png_rgb`) and nearest-neighbour resize (`_nn_resize_rgb`)
  in pure Python — no Pillow.
  Special texture handling: sky textures → TAG_SKY placeholder; clip/trigger/hint/skip
  tool textures → TAG_SKIP placeholder; `*`-prefixed liquid textures → TAG_LIQUID
  (decoded normally); fullbright naive (no lightmaps). Sampler uses REPEAT wrap for
  correct tiling. `--validate` mode checks UV spans and enforces the ≤ 3 MB/map budget.
  Committed outputs: `lab/dashboard/public/maps/{dm3,dm2,frobodm2,trick}.glb` plus
  new keys (`glb`, `texture_count`, `glb_bytes`, `glb_triangles`, `glb_vertices`)
  added to `maps.json` alongside the existing OBJ keys (no conflicts).
  `maps.json` source-BSP sha256 matches the value embedded in each GLB's `asset.extras`.
  `tests/test_bsp_to_mesh.py` locks the pipeline on a synthetic in-memory BSP (UV
  formula, worldmodel-only rule, GLB structure, sampler REPEAT, material extras tags,
  determinism) and the committed assets (GLB magic/version, size budget, SHA provenance).

### Lab control bridge (lab/server)

`lab/server/control_bridge.py` (LD-F2, #96) is the browser→lab-server command channel,
hosted inside the existing telemetry sidecar `scripts/telemetry_ws.py` (decision D4: no
new service). The sidecar's client text frames carry JSON `{op, req_id, ...}` commands;
the bridge authorizes the caller for every mutating op (loopback peer or per-deploy
control token at `~/komodobots-lab/control.token`, fail-closed; the sidecar adds a
browser Origin allowlist as CSRF defense on top — Codex P1, #129), validates (lab-port
allowlist 28599–28609, flat deny of production
28501/28502/28503 and `qw_*` screens, cvar/console allowlists), enforces the
harness-priority lab lock (`~/komodobots-lab/lab.lock`), audits every mutating attempt
to `~/komodobots-lab/control-audit.log`, and dispatches through an injectable
`LabExecutor` (screen sessions + the `qw_min_client.py` shim — `botcmd` is not a
server-console command). `experiments/qw_min_client.py` gained a repeatable `--botcmd`
flag for the bridge's bot ops; `scripts/run_frobodm2_lab.py` writes/releases the
`owner=harness` lock around each attempt and refuses ports held by dashboard sessions.
`experiments/smoke_ws_control.py` is the manual local smoke / lab-slot end-to-end
client. Protocol, security gates, and the `kbot-telemetry` deploy/restart procedure:
`lab/README.md`. Tests: `tests/test_control_bridge.py`,
`tests/test_control_channel_wiring.py`.

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
- QWD POV demos are the current source-grounded path for exact human action labels.
- Verified local source commit for QWD usercmd extraction: `b443a89b2c663acd9ed95fad02407da0efc2ea04`.
- Verified `src/qwprot` submodule commit for `usercmd_t`: `dd5165c1b702efeaee391b94f491cd1220018691`.

Important files/anchors:

- `src/cl_demo.c` - `CL_WriteDemoCmd()` writes `float demotime`, `byte dem_cmd`, raw `usercmd_t`, then three viewangle floats; `CL_WriteDemoMessage()` writes length-prefixed `dem_read`; the read loop switches on `message_type & 7`.
- `src/qwprot/src/protocol.h` - `usercmd_t` layout: `byte msec`, `vec3_t angles`, `short forwardmove/sidemove/upmove`, `byte buttons`, `byte impulse`; current layout validates as `24` bytes with compiler padding after `msec`.
- `src/com_msg.c` - `MSG_WriteDeltaUsercmd()` / read side cross-check the canonical command field set and sizes.
- `src/sv_ents.c` - server broadcast/MVD path zeroes normal movement intent, so MVDs remain state/evaluation evidence rather than exact human input labels.

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
