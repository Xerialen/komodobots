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

Built-in QTV (for browser spectating):

- MVDSV has a built-in QTV stream, so a single lab server needs no standalone `qtv` proxy. Confirmed cvars in `QW-Group/mvdsv` `src/sv_demo_qtv.c`: `qtv_streamport` (TCP stream listen port), `qtv_password`, `qtv_maxstreams`, `qtv_pendingtimeout` (default 5s), `qtv_streamtimeout` (default 45s), `qtv_sayenabled`.
- The current servexeri MVDSV build rejects `sv_mvdhost` as an unknown command, so the lab launcher prints the watch target instead of depending on that cvar.
- A viewer connects with ezQuake `/qtvplay <host>:<qtv_streamport>`; ezQuake does not parse a `tcp:` scheme in `qtvplay`.
- Used by `scripts/run_lab_qtv.py`. Pin the deployed MVDSV commit and confirm QTV support is compiled in before relying on the stream.

Deployment note:

- `servexeri:~/nquakesv/` has `mvdsv` and `build/mvdsv/mvdsv` present; the build checkout reported commit `90aa017` during the 2026-06-05 inspection.
- Existing ports are `28501`, `28502`, and `28503`. User clarified on 2026-06-05 that no one plays on this server, so lab automation may use any port; a separate temporary port/process is still useful for cleanup and repeatability.
- `~/nquakesv/stop_servers.sh` stops a live QTV/QWFWD, so an nQuake-managed QTV proxy already exists on the box. The lab QTV launcher deliberately stands up a *separate* dedicated stream instead of reusing it, to avoid coupling lab spectating to live service config.

### DrLex Frogbots

Repository: https://github.com/DrLex0/quake-frogbots

Why it matters:

- Historical Frogbot lineage.
- Useful for understanding original bot assumptions and route logic.
- Not the first implementation target unless KTX integration blocks us.

## Analysis and data sources

### Agent coordination handoffs

Merge-board analysis and Claude help request: `C:\Users\benya\projects\quakeworld\komodobots\codex\MERGE_BOARD_ANALYSIS_2026-06-10.md`

Why it matters:

- Records the current blocked PR/branch board after the June 10 merge sweep.
- Explains why PRs #124, #125, #126, and branch `qwd/dm3-sng-to-rl-route-map` are not safe mechanical merges/deletions.
- Gives Claude concrete next actions while preserving the Coder/Reviewer role split.

### Komodobots lab automation

Preferred local runner: `C:\Users\benya\projects\quakeworld\komodobots\scripts\run_bot_lab.py`

Implementation/default runner: `C:\Users\benya\projects\quakeworld\komodobots\scripts\run_frobodm2_lab.py`

Local client shim: `C:\Users\benya\projects\quakeworld\komodobots\experiments\qw_min_client.py`

Movement metrics extractor: `C:\Users\benya\projects\quakeworld\komodobots\scripts\extract_movement_metrics.py`

Moveprobe plausibility summarizer: `C:\Users\benya\projects\quakeworld\komodobots\scripts\summarize_moveprobe_plausibility.py`

ztricks batch runner: `C:\Users\benya\projects\quakeworld\komodobots\scripts\run_ztricks_batch.py`

ztricks batch scorer: `C:\Users\benya\projects\quakeworld\komodobots\scripts\score_ztricks_batch.py`

getandmaintainspeed scorer: `C:\Users\benya\projects\quakeworld\komodobots\scripts\score_getandmaintainspeed.py`

ztricks reference trace builder: `C:\Users\benya\projects\quakeworld\komodobots\scripts\build_ztricks_reference_trace.py`

ztricks reference interpolation helpers: `C:\Users\benya\projects\quakeworld\komodobots\scripts\ztricks_reference_trace.py`

QWD segmentation/interpolation procedure: `C:\Users\benya\projects\quakeworld\komodobots\experiments\ktx_moveprobe\evidence\qwd-segmentation-interpolation-procedure-20260613.md`

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

QWD POV content manifest parser: `C:\Users\benya\projects\quakeworld\komodobots\tools\qwd_content_manifest.py`

QWD trajectory route applicability probe: `C:\Users\benya\projects\quakeworld\komodobots\scripts\probe_qwd_route_applicability.py`

QWD-to-Frogbot route mapping helper: `C:\Users\benya\projects\quakeworld\komodobots\scripts\map_qwd_route_to_frogbot.py`

QWD SNG hybrid probe design helper: `C:\Users\benya\projects\quakeworld\komodobots\scripts\design_qwd_sng_hybrid_probe.py`

QWD SNG hybrid probe comparison helper: `C:\Users\benya\projects\quakeworld\komodobots\scripts\compare_qwd_sng_hybrid_probe.py`

QWD SNG hybrid probe diagnosis helper: `C:\Users\benya\projects\quakeworld\komodobots\scripts\diagnose_qwd_sng_probe.py`

QWD SNG MVD crossing inspector: `C:\Users\benya\projects\quakeworld\komodobots\scripts\inspect_qwd_sng_mvd_crossings.py`

QWD SNG slow-success attribution helper: `C:\Users\benya\projects\quakeworld\komodobots\scripts\diagnose_qwd_sng_slow_success.py`

QWD seam validator: `C:\Users\benya\projects\quakeworld\komodobots\scripts\qwd_seam_validator.py`

Replay timing audit helper: `C:\Users\benya\projects\quakeworld\komodobots\scripts\audit_replay_timing.py`

Lab QTV spectate launcher: `C:\Users\benya\projects\quakeworld\komodobots\scripts\run_lab_qtv.py`

KTX movement probe patch: `C:\Users\benya\projects\quakeworld\komodobots\experiments\ktx_moveprobe\frogbot-moveprobe.patch`

A5 live-port overlay/spec: `C:\Users\benya\projects\quakeworld\komodobots\experiments\a5_distance_standstill\a5-live-port-spec.md` and `C:\Users\benya\projects\quakeworld\komodobots\experiments\a5_distance_standstill\a5-live-port-servexeri-overlay.md`

4v4 validation and KTX stats helpers:

- `lab/server/ktx_match_stats.py` normalizes KTX post-game JSON stats into
  `komodobots.ktx_match_stats.v1` for both BotLab validation and casting.
- `lab/server/fourvfour_validation_build.py` builds the fixed-roster 4v4
  validation ledger (`komodobots.4v4_validation.v1`) from KTX stats plus
  `4v4-roster.json` intent files.
- `lab/server/fourvfour_validation_runner.py` writes the dry-run-safe control
  plan and roster intent for the all-bot DM3 4v4 validation setup.
- `scripts/run_4v4_validation_lab.py` runs the lab-only live KTX 4v4 validation
  loop on allowlisted ports: generated KTX config, spectator shim, eight
  Frogbots, MVD capture, analyzer output, and ledger rebuild.
- `lab/server/ktx_casting_ingest.py` is the read-only KTX casting ingest path;
  it reuses the same normalizer and does not import or call the control bridge.
- `lab/server/ktx_live_observer.py` holds the conservative provisional live
  scoreboard model for KTX event/JSON snapshots.
- `lab/dashboard/src/FourVFourValidationPanel.tsx` renders the BotLab KPI
  dock validation panel; `lab/dashboard/src/CastingScoreboard.tsx` renders the
  control-free `?casting=1` OBS/commentary view.
- Fixtures live at `lab/dashboard/public/data/4v4-validation.example.json` and
  `lab/dashboard/public/data/casting-match.example.json`; browser evidence is
  recorded under `lab/evidence/ld-h3-*`.

Why they matter:

- They give the lab a repeatable eight-player, fixed-roster validation record
  for comparing the Komodobot slot against unchanged skill-20 Frogbots.
- They keep public/casting consumption on the same KTX stats semantics without
  exposing game-control actions.
- They encode the distinction between authoritative post-game stats and
  provisional live observer fields.
- Live analyzer output can embed KTX stats under `demoInfo` while putting
  `deathmatch`, `teamplay`, and `timelimit` in analyzer metadata; the shared
  normalizer accepts both that shape and raw KTX `tl`/`dm`/`tp` sidecars.

Why it matters:

- `scripts/run_bot_lab.py` is the preferred one-command lab runner entry point.
- The runner SSHes to `servexeri`, creates a named MVDSV/KTX screen session, loads a selected map, runs the client shim, copies the generated MVD to `artifacts/lab-runs/<run-id>/`, parses it through WSL `qw-analyze-v20`, writes `run-summary.md` plus `movement-metrics.md`, and stops only its owned screen session.
- `experiments/qw_min_client.py` is the protocol-narrow connected-client control path for KTX commands such as `botcmd addbot`.
  For spectator control shims it sends incoming userinfo as `spectator=1`
  and only acknowledges safe KTX `stufftext` handshakes (`cmd ack infoset` /
  `cmd ack noinfoset`) back to the server.
- `scripts/extract_movement_metrics.py` derives per-player horizontal speed, distance, speed-threshold time ratios, stationary time, airborne proxy, and jump cadence from `events.txt` kind `5` player origin samples. S7b added an indexed landing-window speed lookup so long 4on4 human traces can produce movement metrics in seconds instead of timing out in repeated full-list scans.
- `scripts/summarize_moveprobe_plausibility.py` combines per-run `movement-metrics.json` and `moveprobe-commands.json` artifacts into an explicit command-coverage plus stationary/low-speed gate. S7c carries `jump_cadence_per_min` from movement metrics into committed S3g bot summaries.
- `scripts/run_ztricks_batch.py` keeps one temporary `ztricks` lab server and one MVD recording alive while cycling remove/add/single-bot route attempts through a cvar sweep. It now takes a ztricks route profile (`distance_standstill` or `spawn_left_speedjump`) from the route manifest, so Distance uses the A5 target/lip/release metadata while the safe-floor route uses the real spawn, zero velocity, diagonal lip/target, and rotated Nexus reference curve.
- `scripts/score_ztricks_batch.py` segments a batched `moveprobe-commands.json` into attempts and scores by route profile. `distance_standstill` still scores against the successful `getspeed.qwd` release formula, interpolating release/landing by XY projection and the physical lip by linear `x=-3348` crossing. `spawn_left_speedjump` scores start-to-peak horizontal speed gain against the human reference target `495.5 qu/s`.
- `scripts/score_getandmaintainspeed.py` scores one mode-25 live run against `artifacts/qwd-getandmaintainspeed/mouse-analysis.json`. It recomputes MVD event-speed segments, command-log speed/yaw diagnostics, human high-speed cursor windows, and writes `getandmaintainspeed-score.json/md` into the run directory. Its strict PASS target still requires beating human p95, max, sustained `>900` time, and mouse-shape checks; the accepted 2026-06-13 CEST baseline is documented as user-accepted visual/operational evidence, not a strict scorer pass.
- `experiments/ktx_moveprobe/evidence/getandmaintainspeed-reference/` stores the small tracked clean-checkout reference bundle for the accepted mode-25 reproduction guide: the generated replay `.cmds`, mouse-analysis JSON, and mouse-analysis notes. Use this path in documentation or new reproduction runs instead of relying on ignored local `artifacts/qwd-getandmaintainspeed/` files.
- `scripts/build_ztricks_reference_trace.py` writes `experiments/a5_distance_standstill/ztricks-reference-trace.json/md` from A5's successful attempt. The trace preserves raw rows, event crossings, and a local-quadratic controller guidance curve over the terminal sweep; angles are unwrapped before interpolation.
- `scripts/ztricks_reference_trace.py` is the shared interpolation helper for the ztricks reference trace and scorer. Event proof stays conservative (piecewise linear/projection) while controller guidance can use local quadratic samples.
- `experiments/ktx_moveprobe/evidence/qwd-segmentation-interpolation-procedure-20260613.md` is the self-contained QWD teaching-trace procedure. It explains why command labels are stronger than sparse state labels, why new QWD work should time-align rather than zip-align, how to segment teleports/respawns/gaps before interpolation, how to unwrap angles and preserve discrete button edges, and when the bot should validate a prepared trace.
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
- `tools/qwd_usercmd/qwd_usercmd.py` extracts exact first-person `.qwd` POV-demo `usercmd_t` streams into `komodobots.qwd_usercmd.v1` line-delimited JSON. It is the Phase 1 action-label path for human commands, separate from MVD state/evaluation evidence. A QWD provides per-frame absolute view-angle results plus movement commands/buttons; it does not provide raw device mouse deltas.
- `tools/qwd_content_manifest.py` emits `komodobots.qwd_content_manifest.v1` JSON for `.qwd` and qizmo-compressed `.qwz`/disguised `.qwd` POV demos. It reads `svc_serverdata`, `modellist`, `updateuserinfo`, and `setinfo` from the demo network stream to resolve true map, roster, modal active-player count, team counts, POV kind, usercmd presence, and self-POV eligibility. The qizmo bundle is a Linux binary; Windows PowerShell runs it through `wsl.exe --cd /mnt/...` after resolving `QWD_QIZMO_BUNDLE`, `--qizmo-bundle`, or the local Challenge-TV archive candidate path.
- `scripts/probe_qwd_route_applicability.py` measures the Phase 2 QWD bridge: exact `dem_cmd` rows paired with anchored self-player `svc_playerinfo` origin/velocity rows, plus continuity splits and waypoint downsampling for route/controller applicability. It is evidence for trajectory extraction, not a Frogbot `.bot` route importer or replay controller.
- `scripts/map_qwd_route_to_frogbot.py` maps one extracted QWD trajectory onto the existing Frogbot `dm3.bot` marker graph. It measures nearest-marker fit, collapsed marker sequence, direct `.bot` edge coverage, shortest graph paths, and recommends route-following, command-imitation, or a hybrid waypoint/controller probe.
- `scripts/design_qwd_sng_hybrid_probe.py` consumes the committed `dm3_sng_shortcut.qwd` route-mapping artifact and writes the first design-only contract for a temporary KTX hybrid waypoint/controller probe. It preserves the QWD waypoint string, side-dominant command profile, diagnostics requirements, and stop conditions without changing KTX or Frogbot behavior.
- `scripts/compare_qwd_sng_hybrid_probe.py` scores temporary mode-9 SNG hybrid server-loop runs against that design contract. It requires QWD activation, control-point advancement, command/MVD window overlap, route/water/cadence diagnostics, active command-profile coverage, and slow/route-dirty guardrails before any positive claim. It records first active in-window target distance and active control-point phases, rejects loose-start advancement and unresolved post-advance target phases, and now consumes optional `moveprobe-qwd-events.json` rows as event-level activation/advancement proof when a rerun produces them.
- `scripts/diagnose_qwd_sng_probe.py` aligns mode-9 command-log server time to MVD-relative event time, checks closest MVD approach to QWD control points, and classifies whether failures are timing-window, start-context, guardrail, inconclusive start-proof, or control-point advancement issues before another live run. It prefers the actual run's recorded QWD radii over design defaults so setup-repair reruns are diagnosed with their real activation radius, and it preserves scorer-reported inconclusive gates such as `tight_start_activation` instead of collapsing every MVD-overlapped rejection into a setup-repaired verdict.
- `scripts/inspect_qwd_sng_mvd_crossings.py` derives first CP0 start-radius entry and sequential point-radius entries directly from MVD position samples, then compares those physical crossings against the first sampled QWD command row. It is an evidence-density diagnostic: it can prove physical control-point traversal, but it does not prove internal mode-9 activation timing by itself.
- `scripts/diagnose_qwd_sng_slow_success.py` consumes the setup-repaired mode-9 SNG run and splits active QWD commands by current control-point target, joins each phase to MVD movement segments, and attributes slow-success failures to setup radius, route/map context, command-profile weakness, or post-control-point progression gaps.
- `scripts/build_replay_command_file.py` builds the open-loop replay command file (`komodobots.replay.v1`) for KTX moveprobe mode 10. It time-matches exact `tools/qwd_usercmd` commands with anchored `probe_qwd_route_applicability` origin/velocity by QWD demo time, interpolates missing reference rows, emits one line per command (`msec ox oy oz vx vy vz pitch yaw roll fwd side up buttons`), and writes a JSON sidecar with command/state counts, alignment method, offset/shift, interpolated rows, source SHA, msec distribution, and `cmd_angles` vs `view_angles` stats. Legacy `--alignment zip` is refused when counts/drift make it unsafe unless `--allow-unsafe-zip` is explicitly passed. Frame 0 is the bot snap state; every frame is the divergence reference. The stream is too large for a cvar, so KTX reads it from a file. See `docs/08_DECISION_LOG.md` for the KTX-vs-ezQuake decision.
- `scripts/qwd_seam_validator.py` audits `.qwd` command/state coverage, `cmd_angles` vs `view_angles`, `msec` distribution, zip drift, and time-alignment drops for replay/imitation inputs.
- `scripts/audit_replay_timing.py` compares a source `.cmds` file to live `moveprobe-commands.json(.gz)` or `screen.log` rows, reporting source-vs-live `msec`, cursor elapsed-time drift, duplicate/regressing cursors, and first-active-frame angle deltas before changing the live replay timing seam.
- `scripts/run_frobodm2_lab.py` (mode 10 wiring) adds `--replay-cmds` (uploads the replay file to `~/nquakesv/ktx/bots/replay/` and sets `k_fb_moveprobe_replay_file`) and `--record-trick-name` / `--demo-name` as a route label for SSD storage. Released route demos are written only under `servexeri:/mnt/usb-ssd/non-games/lab/Komodobots/<map>/<route>__<run_id>.mvd`; the runner no longer mirrors new demos into `tricks/dm3/` or local nQuake watch folders. If no explicit label is provided for a `dm3_<route>.cmds` replay, the route name is inferred from the replay filename.
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
- The patch now includes dashboard practice idle mode `24`: it allows spawn-snap and ASSIGN instrumentation to run, then emits zero movement, no jump, and no firing until a per-slot route assignment overrides the global mode.
- The patch now includes S6b diagnostic route-state logging as `route=linked_marker,touch_marker,goal_ed,goal_marker,path_state,bot_state,blocked,dir_speed` appended to sampled `FBMOVEPROBE_CMD` rows.
- The patch now includes S6d diagnostic water/swim logging as `water=waterlevel,watertype,flags,swim_arrow,emitted_upmove,velocity_xyz,dir_move_xyz` appended to sampled `FBMOVEPROBE_CMD` rows after the `route=` suffix.
- `scripts/run_frobodm2_lab.py` parses those command rows into `moveprobe-commands.json` and `moveprobe-commands.md` beside the normal MVD, parser, and movement-metrics artifacts.
- `scripts/run_frobodm2_lab.py` parses S6d water rows into nested `water_state` command data and summarizes waterlevels, watertypes, player flags, swim arrows, emitted upmove, velocity Z, and raw route `dir_move` Z.
- `scripts/run_frobodm2_lab.py` parses S7j probe rows into nested `probe_state` command data and summarizes transition-active sample counts, active ratios, and active scale values.
- `scripts/run_frobodm2_lab.py` passes mode-9 QWD waypoint/radius cvars through base64-safe remote shell transport, parses nested `qwd_state` command data, and summarizes QWD activation, control-point index/count, target distance, advanced points, completion, and active seconds.
- `scripts/run_frobodm2_lab.py` parses mode-23 ztricks terminal-carve rows into nested `zjump_state` command data and summarizes phase, arm/release, speed, lip distance, target-error, and yaw-lead values.
- `scripts/run_frobodm2_lab.py` parses `FBMOVEPROBE_QWD_EVENT` rows into `moveprobe-qwd-events.json` and `moveprobe-qwd-events.md`; run summaries include the parsed QWD event count.
- `experiments/ktx_moveprobe/frogbot-moveprobe-perslot.patch` (LD-F1 #95) adds the per-slot cvar convention `k_fb_moveprobe_<param>_s<N>` (`mode`, `replay_file`, `fixed_goal`, `spawn_origin`, `spawn_velocity`; `N` = the bot's `ed`), bounded per-slot replay-file stores, `FBMOVEPROBE_ASSIGN` assignment rows, dashboard practice idle mode `24`, `FBMOVEPROBE_PERSLOT_ERROR` loud failures with hold-at-spawn, the default-off mode-23 ztricks terminal-carve/reference-curve/release primitive, and experimental mode `25` for human-mouse replay speed catch-up. Replay-backed modes now expose `k_fb_moveprobe_replay_stale_gap` and `k_fb_moveprobe_replay_one_shot` so one-shot benchmark runs can prevent silent in-run replay reactivation after command gaps or death/respawn; they also expose default-off `k_fb_moveprobe_replay_use_recorded_msec` for using the QWD frame's recorded command cadence, default-off `k_fb_moveprobe_replay_interpolate` for smoothing QWD reference origin/velocity/view angles between frames while keeping movement/buttons discrete, default-off `k_fb_moveprobe_replay_step_cursor` for fixed-cursor cadence diagnosis, default-off `k_fb_moveprobe_replay_start_resnap*` for repairing proven frame-0/frame-1 activation warps, plus default-off `k_fb_moveprobe_replay_attack` and `k_fb_moveprobe_replay_attack_impulse` so rocket-jump QWD routes can preserve recorded attack+jump windows while pure movement routes keep previous behavior. KTPro Standby rocket-jump replays can additionally opt into `k_fb_moveprobe_replay_attack_grant` and `k_fb_moveprobe_replay_attack_rockets` so the lab bot receives RL/rockets at replay activation instead of failing impulse 7 with `no weapon`. Mode `12` can opt into `k_fb_moveprobe_corr_autojump` to recover from small live/QWD offsets that cause unexpected ground contact and speed loss, `k_fb_moveprobe_corr_cmd_blend` / `_deadband` / `_after` / `_move` to blend the recorded forward/side command direction toward the QWD path without changing the recorded mouse yaw, and `k_fb_moveprobe_corr_ground_realign` / `_after` to use recorded zero-input ledge pauses to walk back toward the QWD origin before the next route leg without shifting earlier rocket phases. Mode `25` logs `s25=` branch telemetry and has default-off diagnostics for path-divergence wishdir blending, human-velocity strafe-side selection, phase recovery, phase human-command actuation, late second-phase movement, phase jump-hold, adaptive phase gap boost, phase yaw offset, exact-human-command scaling, and phase lane nudging. Current `getandmaintainspeed.qwd` evidence rejects path-blend, velsign, late phase2, jump-hold, gap boost, yaw offset, human-command scaling, and phase-start `1600`; the best live profile uses fixed-magnitude phase human-command actuation but still does not beat the human's sustained `>900` time. The ztricks primitive includes optional `k_fb_moveprobe_s23_lip_y` so diagonal calibration routes can compute `d_lip` by projected lane progress while Distance keeps raw X-axis lip distance. It applies to a pristine KTX `08807da` checkout; base checksums, apply notes, and 2026-06-12 deploy evidence live in `experiments/ktx_moveprobe/README.md`.
- `scripts/moveprobe_parse.py` additionally parses `FBMOVEPROBE_ASSIGN` and `FBMOVEPROBE_PERSLOT_ERROR` rows (`parse_moveprobe_assign_logs`, `parse_moveprobe_perslot_error_logs`); `scripts/run_frobodm2_lab.py` writes them to `moveprobe-assignments.json` and `moveprobe-assignments.md` and accepts `--extra-replay-cmds` for uploading additional per-slot route files.
- `scripts/run_frobodm2_lab.py` also parses A5 mode-23 `FBMOVEPROBE_S23` transition rows into `moveprobe-s23-events.json` and `moveprobe-s23-events.md`, so ztricks retry attempts can be scored from explicit `attempt`/`snap`/`arm`/`release`/`timeout`/`land_reset` events instead of sparse sampled commands.
- `scripts/diagnose_route_state.py` now consumes the nested `route_state` command data and reports marker/goal/path-state/blocked context for low-speed windows.
- `scripts/attribute_route_state_windows.py` uses KTX `include/fb_globals.h`, `include/g_consts.h`, `src/route_calc.c`, `src/bot_botwater.c`, `src/bot_movement.c`, and `resources/example-configs/ktx/bots/maps/dm3.bot` to decode S6b/S6d/S6e repeated marker/path-state/water-state patterns.
- `experiments/ktx_moveprobe/evidence/` keeps small committed derived summaries for important S3 runs while raw MVDs and per-run directories remain outside Git under `artifacts/`. S7c regenerated the S3g summary from existing artifacts to include bot-side cadence.
- `experiments/human_comparison/evidence/` keeps small committed derived inventory/summary files for S4 human-demo work while raw human demos and parser event streams remain outside Git under `artifacts/human-demos/`.
- `experiments/qwd_route_probe/evidence/` keeps compact committed QWD state/action/waypoint applicability summaries, while per-frame paired NDJSON and waypoint exports remain ignored under `artifacts/qwd-route-probe/`.
- `scripts/run_lab_qtv.py` is a standalone `up`/`down`/`status` launcher that brings up a browser-spectatable QTV stream for the lab on a dedicated UDP game port plus TCP QTV stream port, using a `komodobots_qtv_*` screen session and a `kqtv_*.cfg` config it owns and cleans up. It never touches nQuake-managed configs or the existing live QTV/QWFWD, and the generated config carries no `k_fb_moveprobe_*` cvars so it cannot perturb movement experiments. It relies on MVDSV's built-in QTV (`qtv_streamport` family), prints the direct `qtvplay <host>:<port>` target, and treats Hub visibility as dependent on normal reachability/listing behavior rather than `sv_mvdhost`. Pure logic is covered by `tests/test_run_lab_qtv.py`; live `servexeri` behavior was verified on 2026-06-07, with browser/Hub reachability still depending on the lab port being externally reachable.

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
  groups by route -> kind; click-to-play with `event_t_s` seek) and **Lab demos**
  (fetches `/v2/demos.json`; filters to active map folders under
  `["non-games","lab","Komodobots"]`; excludes `archive`, `human`, and `records`;
  map-filterable; sortable by demo, map, and date recorded; default newest-first).
  Player area is the `public/panes/demo.html` iframe mounted once a demo is selected,
  then reloaded via `{cmd:"load"}` postMessage (no React re-mount between demos).
  Exports `OpenDemoParams`, `DemoContext`, and `DemoPaneHandle` types; the handle ref
  carries `openDemo` for the shell.
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
  `MockupPane.tsx`.  Provides `createMapScene(container, mapName, qCenter?, onMeshLoaded?)`
  which encapsulates: scene + `PerspectiveCamera` + `WebGLRenderer` + `OrbitControls`,
  mesh loading, Quake Z→Y rotation, resize-observer wiring, and a `dispose()` that frees
  all GPU resources.  Also exports `fetchMapCenter(mapName)` to resolve per-map AABB
  centers from the committed `public/maps/maps.json` (LD-C2).
  `BotLab3D.tsx` delegates scene setup to `createMapScene` and retains only the bot-actor
  lifecycle (marker/trail/velocity arrow), telemetry frame loop, and reference path
  rendering.  `App.tsx` documents that one `TelemetryClient` instance is created at shell
  scope and shared across all pane consumers (single WebSocket per page; panes only
  register frameListeners, they do not own the connection).

LD-C5 (#99) updated the map-scene module to load textured `.glb` assets:

- `src/mapScene.ts` — OBJ path replaced by `GLTFLoader` loading `/botlab/maps/<map>.glb`
  (LD-C4 assets).  Sky textures (TAG_SKY) and tool textures (TAG_SKIP) are hidden by
  default via GLTF material extras.  Visible materials are transparent
  (`opacity = 0.3`, `depthWrite = false`) so trails/markers/lines remain readable at all
  opacity values.  Exposes `setOpacity(value)` (range 0.05–1.0, default 0.3 "quite
  transparent") and `setWireframe(enabled)` (default false) — both called by the shared
  controls in the top bar (see `App.tsx` and `layoutState.ts`).  The `MapSceneMaterials`
  export type is removed; the public API is now the two setters plus the existing
  `setOverviewCamera` and `dispose`.
- `src/layoutState.ts` — `LayoutState` gains `mapOpacity: number` (default 0.3) and
  `wireframe: boolean` (default false); both persisted to localStorage and restored on
  load.  `DEFAULT_MAP_OPACITY` exported.
- `src/BotLab3D.tsx` — accepts new `mapOpacity` and `wireframe` props; forwards them to
  `mapScene.setOpacity` / `mapScene.setWireframe` via dedicated `useEffect` hooks.  Holds
  a `mapSceneRef` so the setters can be called without re-running the heavy scene-setup
  effect.
- `src/MockupPane.tsx` — accepts new `mapOpacity` and `wireframe` props; applies them to
  the scene on creation and on subsequent changes via dedicated `useEffect` hooks.
- `src/App.tsx` — Live 3D pane header gains an opacity range slider (0.05–1.0, step 0.05,
  with live %-label) and a wireframe checkbox; both stored in `layout.mapOpacity` /
  `layout.wireframe` (one value shared by both 3D panes per SPEC §6.3).  MockupPane
  receives both props from layout state.  Old `MapSceneMaterials`-typed fields removed
  (no caller referenced them directly).
- The old OBJ load path (`OBJLoader`, `maps/<map>.obj` URL) is fully removed from the
  app.  `public/dm3.obj` (top-level legacy file) is retained because
  `tests/test_bsp_to_obj.py` reads it for regression comparison.

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
  - `mapOpacity` and `wireframe` props (from LD-C5) are retained alongside the new
    multi-bot props; both sets coexist in the same component.
- `src/TelemetryHud.tsx` additions:
  - Per-ed accumulators (`accumRef` holds a `Map<ed, PerEdAcc>`) — hop count and air time
    tracked independently per bot; capped at `MAX_HUD_BOTS = 4` (exported).
  - Compact row (non-selected bots): name / vh / hops / onground; clickable to select.
  - Expanded row (selected or first-seen bot): full detail identical to pre-F4 display.
  - `selectedEd` and `onBotClick` props parallel the BotLab3D interface; `App.tsx` wires
    both to the same `selectedEd` state and `setSelectedEd` setter.
- `src/App.tsx` additions: `selectedEd` state (`number | null`); reset to null on
  `new_attempt` so camera re-locks to the first bot automatically.  BotLab3D receives
  all four props: `mapOpacity`, `wireframe` (LD-C5), `selectedEd`, `onBotClick` (LD-F4).

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
  `svc_disconnect: EndOfDemo` in FTE console output). Connected-state detection accepts
  FTE hook echoes (`f_demostart`/`autotrack`), relay acceptance (`Welcome to FTEQTV` /
  `streaming ... via ...`), runtime stream messages such as `entered the game`, and a
  short post-`qtvplay` fallback so the shell does not remain stuck at `retrying` while
  FTE is visibly attached. `f_demostart → autotrack` picks a bot to follow on connect.
  The shell (`App.tsx`) sends `{cmd:"attach"}` on every new attempt from telemetry; the
  pane's own retry loop handles the between-attempts reconnect without shell involvement.
  Map `.bsp` preload is local-first (optimization only; QTV fetches maps independently
  via `cl_download_mapsrc`). Modeled on
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
  versioned routes manifests `lab/dashboard/public/data/routes/{dm3,dm2,frobodm2,trick,ztricks,index}.json`
  (schema `komodobots.routes.v1`) — the canonical "what routes exist" feed for the
  Mockup view, KPI dock and control panels. ztricks is the non-dm3 exception: its
  `distance_standstill` route is built from A5's successful 11th `getspeed.qwd`
  attempt (`experiments/a5_distance_standstill/human-replay.json` +
  `getspeed-aligned.cmds`), with the real start-to-landing polyline, edge speed,
  launch heading, and provenance hashes; `required_speed` stays null because A5
  showed speed alone is not a sufficient success gate. The solved live control
  asset is `experiments/a5_distance_standstill/replay/ztricks_distance_standstill.cmds`,
  a 140-frame slice of `getspeed-aligned.cmds` rows `1830..1969`, exposed in the
  manifest as `replay_file=ztricks_distance_standstill.cmds`, mode `10`, recorded
  msec, and replay interpolation. ztricks also carries
  `spawn_left_speedjump`, a flat spawn-floor speed-gain drill from the real
  deathmatch spawn (`-1168 1632 -496`, BSP angle `315`, left yaw `45`) that
  reuses the mode-23 speedjump/reference-curve primitive with no ledge-completion
  gate. Deterministic/idempotent (LF outputs,
  `-text` in `.gitattributes`, LF-normalized sha256 provenance hashes);
  `tests/test_build_routes_manifest.py` locks the committed outputs against a fresh
  build. The controller-shaped breakdown of the successful speedjump lives in
  `experiments/a5_distance_standstill/speedjump-formula.md`. Pipeline details:
  `docs/06_DATA_AND_MVD_PIPELINE.md` § Routes manifest.

- `lab/tools/import_map_entities.py` — stdlib importer that copies the upstream
  `mvd_analyzer` static map-entity corpus from
  `mvd-analytics/mapents/data/<map>.json` into the committed BotLab data layer
  `lab/dashboard/public/data/map_entities/` (schema
  `komodobots.map_entities.v1`). Current imported map set:
  `dm2`, `dm3`, `e1m2`, `phantombase`, `schloss`, and `ztricks`; the upstream
  source already includes `ztricks`, so no local generation was needed. The index
  records the upstream repo, ref, commit, source path, entity counts, and type
  counts. `tests/test_import_map_entities.py` covers the importer with a throwaway
  git fixture, and `scripts/ld_g2_golden_path.py` validates the committed data.
  Pipeline details: `docs/06_DATA_AND_MVD_PIPELINE.md` § Map entity corpus.

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

### Lab Dashboard React sources — Mockup pane + KPI dock (LD-C3, LD-E1)

- `lab/dashboard/src/MockupPane.tsx` (LD-C3, #97) — standalone Three.js offline map/route
  browser.  Loads `public/maps/maps.json` for the map selector (dm3/dm2/frobodm2/trick/ztricks),
  fetches the per-map routes manifest (LD-C1 schema `komodobots.routes.v1`) from
  `public/data/routes/<map>.json`, fetches static map entities from
  `public/data/map_entities/<map>.json` when present, and renders route polylines,
  gap markers, route teleport markers, plus static item/spawn/teleporter context
  using the shared `mapScene.ts` module.  The selected-route detail panel shows nearest
  static entities to the route start, final edge, and landing point; this is now how
  ztricks Distance exposes its source teleporter/landing context. ztricks Distance
  carries the successful `getspeed.qwd` human reference metrics, while null fields such
  as `required_speed` still render as `n/a` instead of being coerced to zero. Multiple routes can be selected
  simultaneously (distinct palette colors); a second click deselects.  Map switch resets
  selection.  Emits `MockupSelection { map: string; route: string | null }` to the
  parent (`App.tsx`) via an `onSelect` callback on every selection change; the most
  recently selected route name is reported (or null when nothing is selected).
  Tests: `tests/test_mockup_context.py` (route schema, ztricks successful-attempt
  reference metrics, nearest static entity context, teleport field names, and MockupSelection
  contract).

- `lab/dashboard/src/contextStore.ts` (LD-E1, #100) — pure TypeScript module (no React
  import) for the KPI dock context store.  Defines `KpiContext { map, route, source }` and
  `applyContextUpdate(current, lastUser, update)` — the pure reducer consumed by
  `useReducer` in `App.tsx`.  Three update kinds: `live` (telemetry live-state),
  `mockup` (MockupPane selection), `demo` (LD-D3 #98 stub).  Precedence: live > last
  user selection > none.  The pure logic is exercised by
  `tests/test_kpi_context_store.py` (33 tests) without any TypeScript/browser runtime.

- `lab/dashboard/src/KpiDock.tsx` (LD-E1, #100; LD-E2, #101; LD-E3, #102; LD-E4, #104) — collapsible
  left dock component.  Two modes: expanded (~288 px) with context line
  (`<data-context-line>`), source badge (`<data-source>`), the live BrutalScoreboard
  component (`<data-section="scoreboard">`), the LiveMetricsPanel
  (`<data-section="live-metrics">` — LD-E3), and the live RecordsPanel
  (`<data-section="records">` — LD-E4); rail (~28 px) with a vertical "KPI" label,
  four micro scoreboard glyphs via RailScoreboard, and a colored source dot.
  `refreshKey` prop (incremented by App.tsx when an attempt ends) is shared by both
  BrutalScoreboard and RecordsPanel; `client`, `isLive`, and `selectedEd` props (LD-E3)
  wire the live metrics panel to the shared TelemetryClient and selected bot.
  Collapse/expand driven by `layout.dockCollapsed` from `layoutState.ts`
  (persisted in localStorage since LD-B1).

- `lab/dashboard/src/LiveMetricsPanel.tsx` (LD-E3, #102) — live attempt metrics panel
  rendered inside the KPI dock while `context.source === "live"`.  Shows:
  - Current speed (`vh`) with an ASCII sparkline (~60-sample history, ~12 Hz display).
  - Arc-local human comparison: projects the bot's 3D origin onto the context route's
    human polyline (nearest-arc-position), interpolates human reference speed at that
    arc fraction from gap-edge anchors, displays bot/human as % + absolute delta.
    When the bot is >384 qu from the nearest polyline point, flags "off route" instead
    of projecting to a distant arc position.
  - Launch-edge callout: tracks the designated launch edge (highest `required_speed` gap
    in the route, e.g. 525.3 qu/s for `sng_to_rl`); when the bot enters a 96 qu XY
    radius around that edge, freezes and displays crossing speed vs `required_speed` and
    `human_speed_at_edge` until `new_attempt`.  Display-only — the post-run
    verify_route scorer is the metric of record (stated in a tooltip). Routes with
    null human-speed anchors are skipped for interpolation, and gaps with null
    `required_speed` (including ztricks Distance and the ztricks spawn-floor
    speed-gain drill) do not create edge-speed callouts rather than being treated
    as zero-speed routes.
  - Attempt meta: run_id, elapsed time, distance-to-goal (`dist_to_rl`).
  - Route override dropdown: until LD-F1/F3 per-bot assignment exposure, the live route
    defaults to `sng_to_rl` on dm3 with a manual override dropdown.
  - Bot identity filter: `selectedEd` prop (from App.tsx / LD-F4 #103) ensures only
    frames from the selected bot are processed; first-seen fallback for single-bot sessions.
  Fetches the routes manifest (`/botlab/data/routes/<map>.json`) once per (map, route).
  Resets fully on `new_attempt`; collapses to "no live session" when not live.
  Pure geometry helpers (`projectOntoSegment`, `projectOntoPolyline`,
  `interpolateSpeedAtArc`, `isInEdgeRegion`, `buildVertexSpeeds`) and
  `designatedLaunchEdge` are exported for Python unit tests.
  Tests: `tests/test_live_metrics_panel.py` (43 tests covering arc projection,
  edge detection, speed interpolation, gap-anchor interpolation, designated-edge
  selection including the committed `dm3/sng_to_rl` manifest).

- `lab/dashboard/src/BrutalScoreboard.tsx` (LD-E2, #101; LD-F5, #106) — the four KPI metric rows
  rendered inside the KPI dock.  Two exported components:
  - `BrutalScoreboard` — full expanded scoreboard with four rows: The Race (finishes/
    attempts · median×human), Jump Count (N/11 censused dm3 routes completed), Speedometer
    (bot peak_speed as % of human · decisive edge sub-line), Eye Test (data-suggested state
    + latest user certification, default "not certified"; optional `controlClient` prop
    enables the passive `CertifyHumanLevel` sub-component — one button, optional note;
    user-initiated only, no nag prompts; calls `controlClient.verdict()` and on success
    calls `refetch()` for immediate scoreboard update).
    Fetches `records.json` (RECORDS_URL `/demos/records/records.json`) and `verdicts.json`
    (VERDICTS_URL `/demos/records/verdicts.json`) on mount and on `refreshKey` change.
    Honest zeros everywhere: explicit empty/no-data states, never blanks or stale data.
    Data derivation is `deriveScoreboard()`, a pure function exercised by
    `tests/test_brutal_scoreboard.py` (57 tests).
  - `RailScoreboard` — compact vertical four-glyph strip for dock rail mode: Race
    (finishes/attempts fraction), Jump Count (N/11), Speedometer (%), Eye Test (★/–).
  Tests: `tests/test_brutal_scoreboard.py` (57 tests locking derive_scoreboard logic,
  DM3_ROUTES_ORDERED, honest zeros, current honest state from SPEC §7).

- `lab/dashboard/src/RecordsPanel.tsx` (LD-E4, #104) — context-sensitive records section
  rendered inside the expanded KPI dock.  Two modes:
    - **route-context**: shows the four record rows (fastest_time / first_completion /
      peak_speed / edge_speed) with the bot value, human_ref comparison, and a freshness
      dot when a value improves after a refetch.  Each set row is clickable and calls
      `ShellActionsContext.openDemo({ demo_url, map, t: event_t_s, route, name })` via
      the shell-level action wired in App.tsx (LD-D3 #98).
    - **overall / no-context fallback**: per-route best table (fastest_time vs human_time_s,
      sorted ascending by human route duration).  Clicking a row opens the fastest_time demo.
  Fetches `/demos/records/records.json` on mount and when `refreshKey` changes. 404 →
  explicit "records unavailable" state, no crash.  Not rendered in rail mode (numbers-only
  per LD-E1 design).  Pure-logic contract tested in `tests/test_records_panel.py` (70 tests).

- `lab/dashboard/src/controlClient.ts` (LD-F3, #105; LD-F5, #106) — TypeScript client for the
  control bridge command channel.  Multiplexed on the SAME WebSocket as telemetry
  (no second connection): `TelemetryClient` exposes `rawMessageListeners` and
  `sendText()` so `ControlClient` can route bridge responses / `control_event`
  broadcasts without owning the socket.  `ControlClient` is created once in `App.tsx`
  (stable ref), wired to the telemetry socket via `onConnectionChange()`, and receives
  raw text frames via `onMessage()`.  Provides typed convenience wrappers for every
  mutating op: `sessionStart`, `sessionStop`, `addBot`, `removeBot`, `setCvar`, `console`
  (with `@<slot>` expansion), `gameCommand` (allowlisted game-level controls), and
  `verdict` (LD-F5: `map, route, note?` — certification that the route has reached
  human-level).  Token auth: optional `?ctoken=` URL param for non-loopback callers;
  loopback dashboard sessions are trusted automatically by the bridge.

- `lab/dashboard/src/ControlDrawer.tsx` (LD-F3, #105) — side-panel control surfaces.
  `ControlDrawer` renders from `App.tsx` when `layout.drawerOpen`; it is a solid
  vertical flex rail to the right of the main view area, not an overlay.
  `CvarConsolePanel` renders as the next solid flex rail when `layout.consoleOpen`.
  Both consume layout width so Live 3D / Live Game shrink instead of being covered;
  the default open view set is Live Game only (`DEFAULT_VIEWS = ["game"]`).
  Control panel sections:
  - **Session block**: lock badge (free / locked / stale), stale-takeover confirm flow,
    map selector (dm3/dm2/frobodm2/trick/ztricks), start/stop buttons. Starting a
    dashboard session is a movement-practice setup step: the bridge seeds a default
    quiet roster, applies separated spawn-snap origins on known maps (`dm3`, `ztricks`),
    and uses moveprobe mode `24` so bots wait still without firing until a per-slot
    route assignment overrides the global idle mode.
  - **Game controls**: direct buttons call `gameCommand` for KTX `4on4`, `2on2`, `1on1`,
    `ffa`, `dmm1`-`dmm4`, powerups on/off, `ready`, and `break`. These mutate the
    running game inside the active dashboard-owned lab server, not the dashboard session
    lifecycle. `start` clears the global practice idle mode, unlocks normal bot weapons,
    and readies the match; `stop` breaks the match and returns the session to quiet
    practice.  Issue #155 controls are also first-class game commands: `prewar` and bot
    ranged-weapon lock/unlock (`axe only` / `weapons free`).
  - **Bot roster**: per-slot rows with name/profile draft fields, route dropdown (routes
    of the current map from the routes manifest), `try`, `loop`, `stand still`,
    `respawn`, and remove controls.  Trickjumps are not a separate UI concept:
    ztricks Distance is the normal `distance_standstill` route in
    `public/data/routes/ztricks.json`, and the safe flat-floor calibration route
    is `spawn_left_speedjump`.  Distance now stores the solved timed replay recipe
    (`mode=10`, `ztricks_distance_standstill.cmds`, recorded msec, interpolation)
    as route `control` metadata; the flat-floor calibration route still stores its
    mode-23 speed-gain cvars.  Selecting a route configures the per-slot assignment
    but keeps the bot in practice-idle mode `24`; `try` starts that slot's route mode,
    `loop` enables the replay-loop cvar and starts it, and `stand still` returns the
    slot to mode `24`.  Route display shows server truth from `FBMOVEPROBE_ASSIGN` rows
    via `TelemetryClient.assignListeners`, with a "pending…" phase until the ASSIGN row
    arrives.  `TelemetryClient.frameListeners` provide an ed/name roster fallback; late
    frames from cleared bots are briefly suppressed after reset/respawn so stale edicts
    do not reappear as phantom rows.  The roster header's `clear` button uses KTX
    `removeall` and is the reliable recovery path when slot-addressed removal leaves
    actual extra bots alive.  Route name round-trips correctly for underscored
    names (e.g. `dm3_sng_to_rl.cmds` → `sng_to_rl`, `ztricks_distance_standstill.cmds`
    → `distance_standstill`).  The row also stages bot name/color/team profile intent;
    current KTX exposes spawn-time Frogbot name cvars but not a safe live color/team
    userinfo mutation command, so full live identity application needs a future bridge
    hook.
  - **Cvar console panel**: command history (up/down), response echo, inline rejection
    rendering, `@<slot>` per-slot shorthand.
  Per-bot assignment sends the per-slot cvars (`replay_file`, `mode`, `fixed_goal`,
  `spawn_origin`, `spawn_velocity`) atomically plus route-level control cvars when present;
  `spawn_origin` is derived from `polyline[0]` in the route manifest unless the route
  declares a `control.spawn_origin` override (fetched lazily, cached).
  Disabled states enforced: bridge disconnected, harness lock fresh, no session running
  (except `session_start`).  Esc closes side panels (wired in `App.tsx`).
  Accepts `telemetryClient` prop for ASSIGN subscription.

### Lab control bridge (lab/server)

`lab/server/control_bridge.py` (LD-F2, #96; LD-F5, #106) is the browser→lab-server command channel,
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
server-console command). Session start now calls `seed_practice_bots()`, which applies
moveprobe mode `24`, spawns the default practice roster one bot at a time with known
safe spawn origins when available, and clears the global spawn cvar. `game_command` is
a separate allowlisted enum for KTX game controls plus legacy guarded lab presets; normal
route attempts, including ztricks Distance, use per-bot route cvars instead. Space-containing
cvar values such as `k_fb_moveprobe_spawn_origin_s<N>` are quoted when stuffed into the
Quake console so the full `x y z` triplet survives; empty cvar values are stuffed as
`set name ""` because bare `set name` only prints the current value. The dashboard
route assignment path clears per-slot `spawn_origin`, waits one sampled frame, then
restores the route spawn so repeated tries of the same route re-arm KTX's one-shot
spawn snap. The enum may dispatch safe client commands,
console cvar lines, short-lived botcmd shims, and addbot actions in declared order.
Botcmd shims stay connected for 5 s because `removeall` was unreliable with the earlier
2 s window; client-command shims use 2 s to keep the dashboard response under timeout.
`experiments/qw_min_client.py` gained repeatable `--botcmd` and `--cmd` flags for
the bridge's bot ops and client-command game controls; `scripts/run_frobodm2_lab.py` writes/releases the
`owner=harness` lock around each attempt and refuses ports held by dashboard sessions.
`experiments/smoke_ws_control.py` is the manual local smoke / lab-slot end-to-end
client. Protocol, security gates, and the `kbot-telemetry` deploy/restart procedure:
`lab/README.md`. Tests: `tests/test_control_bridge.py`,
`tests/test_control_channel_wiring.py`,
`tests/test_f3_control_drawer.py` (LD-F3 #105 Codex P1 fixes: full per-slot
assignment cvar expansion, ASSIGN broadcast shape, route-name round-trip,
spawn_origin allowlist).

LD-F5 (#106) adds the `verdict` op: `{map, route, note?}` (user decision 2026-06-10:
certification only — no pass/close/fail; the user declares the bot has reached human-level).
Validates map + route tokens (same allowlist as `set_map`), optional note (max 1000 chars,
no control chars), writes atomically (temp-file+rename) to
`~/komodobots-lab/records/verdicts.json` (schema `komodobots.verdicts.v2`, co-located with
`records.json`), appends to `certifications[route]` (sparse dated list, history kept),
audit-logs the attempt, and broadcasts a `control_event` on success.  Lock-exempt: the
verdict op bypasses the harness-priority lab lock because it touches only the local records
store, never a running lab server.  The `controlClient.ts` `verdict()` wrapper mirrors the
op; the `CertifyHumanLevel` sub-component inside `BrutalScoreboard.tsx` provides the dock
UI (one button + optional note); user-initiated only, no nag prompts; on success it calls
`refetch()` so the scoreboard Eye Test row updates immediately.  Tests:
`tests/test_control_bridge.py` `TestVerdictValidation` + `TestVerdictOp` (new tests
locking validation, atomic write, certification append, lock exemption, auth enforcement,
audit).

### Lab Dashboard golden-path validation harness (LD-G2, #108)

`scripts/ld_g2_golden_path.py` — stdlib-only offline validation harness for the
Lab Dashboard v1 data contracts.  Runs five offline checks without requiring a
live servexeri connection or a browser:

1. **routes-manifest integrity** — index.json + per-map files parse; every route
   has all required `komodobots.routes.v1` fields (name, human, polyline, gaps,
   teleports, source); route counts match; map names cross-reference `maps.json`.
2. **maps.json / GLB structural check** — every committed `.glb` has correct glTF
   magic (`glTF`), version 2, self-consistent declared file length, and an
   `asset.extras.source_bsp_sha256` that matches the `komodobots.maps.v1`
   provenance record in `maps.json`.
3. **map-entity corpus integrity** — the committed
   `public/data/map_entities/index.json` parses as `komodobots.map_entities.v1`;
   the required maps (`dm2`, `dm3`, `e1m2`, `phantombase`, `schloss`, `ztricks`)
   are present; per-map files parse; entity/type counts and required coordinate
   fields match.
4. **records / verdicts schema round-trip** — `lab/server/verdicts.seed.json`
   parses as valid `komodobots.verdicts.v1`; verdict values are in
   `{pass, close, fail}`; `records_build.SCHEMA` constant matches the harness's
   sentinel.
5. **deploy expected file-set** — committed `public/` key assets (`panes/*.html`,
   `panes/*.cfg`, top-level `dm3.obj`, `dm3_sng_to_rl.cmds`, per-map GLB/OBJ,
   routes JSON files, and map-entity JSON files) all exist before the npm build
   step runs.

Live checks (skipped offline, pass `--live`):
- `@live`: telemetry WebSocket frame validation against `ws://servexeri:8770`.
- `@live`: deployed `records.json` schema check at `http://servexeri:8095`.

Usage:
```bash
python scripts/ld_g2_golden_path.py           # offline only (CI path)
python scripts/ld_g2_golden_path.py --live    # owner slot with servexeri access
```

Contract gap found during LD-G2: `maps.json["dm2"]["glb_bytes"]` was stale
(`611980` vs actual `613256`); corrected in the same PR (see `07_FINDINGS_LOG.md`
entry 2026-06-11).

Tests: `tests/test_ld_g2_golden_path.py` (42 tests).  Includes a deliberately-
broken-fixture negative-control suite (`TestBrokenFixtureFailsLoud`) that
verifies wrong GLB magic, missing route fields, and invalid verdict values each
produce loud, specific failure messages.

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
- `mvd-analytics/mapents/data/*.json` — static map-entity corpus; upstream
  `dbfee83f457946c93e941c4a0b76efd25183d25e` includes the committed BotLab
  imports for `dm2`, `dm3`, `e1m2`, `phantombase`, `schloss`, and `ztricks`.
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

### QuakeWorld Hub (browser spectating)

URL: https://hub.quakeworld.nu/

Why it matters:

- Discovers QuakeWorld servers from the QW master servers and provides an in-browser player for live QTV streams.
- Chosen browser front-end for lab spectating (`scripts/run_lab_qtv.py`) when the lab server is visible/reachable, avoiding a self-hosted web client.
- Caveat: a private high-port lab server only appears if its game port and QTV TCP port are reachable from the internet; `servexeri` already hosts public servers, so this is expected to work but is pending live verification.

## External conceptual sources

## Workflow and agent-operation sources

### Agent-agnostic role docs

Local files:

- `AGENTS.md`
- `coder.md`
- `reviewer.md`
- `CLAUDE.md`
- `codex.md`

Why they matter:

- `AGENTS.md` is the shared project contract.
- `coder.md` defines the implementation role independent of tool brand.
- `reviewer.md` defines the technical merge-safety review role independent of
  tool brand.
- Tool-specific files are thin adapters and must not assign permanent roles.

### Test-case and web-validation methodology

Local files:

- `docs/09_TEST_CASES_AND_EVIDENCE.md`
- `docs/10_AGENT_WEB_TESTING.md`
- `.github/pull_request_template.md`
- `.github/ISSUE_TEMPLATE/user_story.yml`
- `.github/ISSUE_TEMPLATE/bug_report.yml`
- `.github/ISSUE_TEMPLATE/test_case.yml`

Why they matter:

- Durable test cases remain reusable across changes.
- Each execution is logged as a test run with evidence.
- Web/UI changes require real-browser validation by an agent before completion.
- GitHub templates make the workflow usable from issues and PRs instead of
  living only in chat memory.

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

## QuakeWorld ecosystem tooling (DM3 4on4 stand-in program)

Registered for the `docs/12_DM3_4ON4_STANDIN_PROGRAM.md` program. All verified on disk under
`C:\Users\benya\projects\quakeworld\`. Pin commits before relying on behaviour.

- **mvd_analyzer** — `tools/mvd_analyzer` (Go, Schema v32; REST + MCP + `qw-analyze` CLI). Macro /
  economy signal from MVD server demos: `damage` (per-hit, given/taken, EWep buckets, matrix),
  `items`, `timelineAnalysis.regionControl`, `locGraph`, `frags`, `streams`, v19-corrected
  `match.players[]` kills/deaths/suicides. **No usercmd labels.** Field reference:
  `tools/mvd_analyzer/mvd-analytics/RESULT_SCHEMA.md` — read before implementing any gate.
- **deepfrag** — `tools/deepfrag` (Python, OpenSkill). 1on1 ratings; DDR / perf-delta formulas in
  `rate.py` (reused by the A-gates).
- **fantasyquake** — `fantasyquake/scripts/` (fork of deepfrag). `rate_4on4.py` = team-W/L OpenSkill
  (NOT suitable for clone selection — carry-confounded); **`rate_individual.py` = carry-corrected
  per-player rating = the clone-selection axis.**
- **ezquake-source** — `engine/ezquake-source` (C). usercmd/demo ground truth
  (`src/cl_demo.c::CL_WriteDemoCmd`); `.qwd` stores absolute post-mouse view angles, no mouse deltas.
- **ktx** — `engine/ktx` (C). Host substrate + bot code (`bot_aim.c`/`bot_botthink.c`/`bot_botweap.c`);
  seam `src/bot_movement.c::BotSetCommand -> trap_SetBotCMD`; 32-bot cap; hosts live without humans.
- **demoparser** (`engine/demoparser`, Rust; `--dump-moments` for ML) and **demopasha**
  (`tools/demopasha`, Rust+CUDA; byte-perfect MVD+BSP, GPU-validated on the 4090) — data-quality layer.

### Program & external movement-AI references

- `docs/12_DM3_4ON4_STANDIN_PROGRAM.md` — the DM3 4on4 stand-in program of record (Megalodon Milton).
- External method/validation literature (MLMove, Pearce, Humanoid + one-hop refs) is consolidated in
  `docs/12` §9, folded from the prior `docs/11_EXTERNAL_MOVEMENT_AI_SOURCES.md` (superseded).

## Source hygiene rules

- Prefer current source code over historical comments.
- Treat old blog/forum posts as design context only.
- Pin commits when making claims about code behaviour.
- Record any local forks and patches here.
- If an agent discovers a new source, add it here before relying on it.
