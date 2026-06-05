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

KTX movement probe patch: `C:\Users\benya\projects\quakeworld\komodobots\experiments\ktx_moveprobe\frogbot-moveprobe.patch`

Why it matters:

- `scripts/run_bot_lab.py` is the preferred one-command lab runner entry point.
- The runner SSHes to `servexeri`, creates a named MVDSV/KTX screen session, loads a selected map, runs the client shim, copies the generated MVD to `artifacts/lab-runs/<run-id>/`, parses it through WSL `qw-analyze-v20`, writes `run-summary.md` plus `movement-metrics.md`, and stops only its owned screen session.
- `experiments/qw_min_client.py` is the protocol-narrow connected-client control path for KTX commands such as `botcmd addbot`.
- `scripts/extract_movement_metrics.py` derives per-player horizontal speed, distance, speed-threshold time ratios, and stationary time from `events.txt` kind `5` player origin samples.
- `scripts/summarize_moveprobe_plausibility.py` combines per-run `movement-metrics.json` and `moveprobe-commands.json` artifacts into an explicit command-coverage plus stationary/low-speed gate.
- `experiments/ktx_moveprobe/frogbot-moveprobe.patch` is the first S2 KTX source probe. It applies to KTX commit `08807da`, hooks `src/bot_movement.c::BotSetCommand()` after the prewar-freeze guard, and adds cvar-controlled command perturbation immediately before button assembly and `trap_SetBotCMD(...)`.
- The same patch includes v2a command instrumentation. When `k_fb_moveprobe_log_commands=1`, KTX prints sampled `FBMOVEPROBE_CMD` rows containing the final `msec`, angles, movement command values, buttons, and impulse about to be sent to `trap_SetBotCMD(...)`.
- The patch also includes v2b mode `3`, a route-yaw probe that sets yaw from `self->fb.dir_move_`, emits simple movement command values, and forces jump when a route direction is available.
- The patch now includes S3a mode `4`, a bounded route-yaw plus alternating-sidemove probe. It is a disposable movement-literacy experiment, not a final bunnyjump controller.
- `scripts/run_frobodm2_lab.py` parses those command rows into `moveprobe-commands.json` and `moveprobe-commands.md` beside the normal MVD, parser, and movement-metrics artifacts.

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
