# Headless Test Environment

Status: repeatable bot lab runner verified on `frobodm2` and `dm3` through 2026-06-06. Baseline movement v2 metrics are generated automatically. KTX final-command movement probes include route-vs-view diagnostics, and S6b route-state logging can tag low-speed windows with Frogbot marker/goal/path-state context.

## Purpose

Document the environment used to run repeatable Komodobots experiments.

This file is the authoritative starting point for the movement laboratory.

## Summary

The existing `ezquake-test` environment is real and useful, but it is primarily a headless ezQuake HUD screenshot harness. It replays an existing MVD in a real client under Xvfb and measures pixels. It does not itself start a server, spawn bots, or produce new MVDs.

The better foundation for Komodobots is the existing `servexeri` QuakeWorld server stack:

- `servexeri` runs Ubuntu 24.04 and has `~/nquakesv/` installed.
- `~/nquakesv/` contains MVDSV, KTX, bot route files, stock `dm2.bsp`, `frobodm2.bsp`, and MVD recording configuration.
- KTX on `servexeri` is built with Frogbot object files and has `botcmd` support available in the deployed `qwprogs.so`.
- MVD parsing can be handled by the existing WSL `~/mvd-mcp-bundle/` binaries or the local `mvd_analyzer` source tree.

User clarification on 2026-06-05: no one plays on this server, so Komodobots can use any port it wants, including the existing `turkishbathhouse` ports. The main remaining reason to prefer a separate lab process or generated lab config is hygiene: easy cleanup, repeatability, and avoiding confusion with the nQuake-managed startup scripts.

First smoke result on 2026-06-05: a separate lab MVDSV/KTX process on port `28599` loaded `frobodm2`, accepted a tiny scripted QuakeWorld client, spawned two Frogbots, recorded an MVD, and the WSL parser extracted two RL frags from the recording. The lab process was stopped after artifact collection.

Second lab milestone on 2026-06-05: `scripts/run_frobodm2_lab.py` made that path repeatable from one local command. It was verified twice on `servexeri:28599`, producing separate local artifact directories under `artifacts/lab-runs/`.

Map clarification from the user on 2026-06-05: stock `dm2` matters because `qw-sim` was built around it, not because it is the ideal bunnyhopping lab. Frogbots have never worked on stock `dm2`; `frobodm2` exists for that reason. Do not spend effort building stock `dm2` Frogbot routes for this lab. Use Frogbot-supported maps such as `frobodm2` and `dm3` for bot movement evidence, while keeping stock `dm2` in mind for `qw-sim` continuity.

Third lab milestone on 2026-06-05: `scripts/extract_movement_metrics.py` now derives per-bot movement tables from `events.txt` kind `5` player origin samples. The runner writes `movement-metrics.json` and `movement-metrics.md` automatically after parsing the MVD.

Fourth lab milestone on 2026-06-05: movement metrics schema v2 adds vertical-motion and airborne-proxy metrics: air-proxy time ratio, run cadence, average air-proxy duration, and post-landing speed delta/loss over a fixed window.

Fifth lab milestone on 2026-06-05: the first S2 movement override probe patched KTX `BotSetCommand()` after the prewar-freeze guard and immediately before button assembly and `trap_SetBotCMD(...)`. Moveprobe mode `1` forced jump while preserving Frogbot direction/combat and produced a normal `frobodm2` run with three frags and movement metrics. Moveprobe mode `2` replaced the final movement command with a fixed command plus forced jump and produced full lab artifacts, but the bots became nearly stationary. Moveprobe mode `3` used route-derived yaw; after an initial mixed run, fresh `frobodm2` and `dm3` repeats passed explicit command/plausibility gates for all bot rows. S2 movement override feasibility is provisionally satisfied pending review, while aim/combat separation remains open.

Sixth lab milestone on 2026-06-06: S3e added route-vs-view diagnostic logging to mode `5` command rows. The fresh diagnostic run passed on `frobodm2` but failed both `dm3` bot rows on low-speed, with the strongest yaw/backward signal on `/ bro`. This keeps the next step small: test whether avoiding negative local `forwardmove` helps before building a larger controller.

Seventh lab milestone on 2026-06-06: S3f added mode `6`, a no-backpedal variant of mode `5`. It passed the current horizontal/side/jump behavior gate on both `dm3` and `frobodm2`, but generated very large side commands after folding negative forward into strafe. This is a successful corrective probe, not a final controller.

Eighth lab milestone on 2026-06-06: S6a added route-state diagnosis over the existing S3g `dm3` artifacts. It found that `8` of `9` analyzed top low-speed windows had strong sampled movement commands nearby, but the artifacts did not expose route node, next waypoint, target entity, obstruction, or route primitive state.

Ninth lab milestone on 2026-06-06: S6b added minimal KTX route-state logging to sampled command rows and reran `dm3` mode `7` as `20260606T031102Z`. The diagnosis can now tag low-speed windows with marker, goal, path-state, bot-state, blocked, and route `dir_speed` context. `/ bro` repeated low-speed windows at `water.LG` with linked/goal marker `59`, path state `32768`, and `blocked=0`.

## Environment Diagram

```text
Windows host / pinnacle-win11
  C:\Users\benya\projects\quakeworld\komodobots
    docs for this investigation

  C:\Users\benya\projects\quakeworld\hud\ezquake-test
    source copy of the headless HUD capture runner

  WSL Ubuntu-24.04
    ~/mvd-mcp-bundle/
      mvd-api, mvd-mcp, dm2.bsp, run-mcp.sh

servexeri / Ubuntu 24.04
  ~/nquakesv/
    mvdsv + KTX live server install
    ktx/bots/maps/frobodm2.bot
    ktx/bots/maps/dm3.bot
    qw/maps/dm2.bsp
    qw/maps/frobodm2.bsp
    qw/maps/dm3.bsp
    ktx/demos/

  ~/hud-runner/
    capture-linux.sh headless ezQuake/Xvfb renderer
```

## Verified Assets

### Local Project Assets

| Asset | Location | Finding |
|---|---|---|
| Komodobots repo | `C:\Users\benya\projects\quakeworld\komodobots` | Local clone of `Xerialen/komodobots`. |
| KTX source | `C:\Users\benya\projects\quakeworld\engine\ktx` | Commit `08807da`; `CMakeLists.txt` has `BOT_SUPPORT` defaulting to `ON`. |
| KTX bot source | `engine/ktx/src/bot_*.c`, `include/fb_globals.h`, `include/g_syscalls.h` | Movement and bot command implementation is available locally. `trap_AddBot`, `trap_RemoveBot`, and `trap_SetBotCMD` are exposed in `g_syscalls.h`. |
| KTX route reference | `engine/ktx/resources/example-configs/ktx/bots/maps/frobodm2.bot` | Local reference route file exists. |
| HUD capture runner | `C:\Users\benya\projects\quakeworld\hud\ezquake-test` | Commit `64156c9`; extracted render/measure harness. Useful for visual checks, not for server-side bot experiments. |
| MVD analyzer source | `C:\Users\benya\projects\quakeworld\tools\mvd_analyzer` | Commit `fab7808`; contains `mvd-analytics/cmd/qw-analyze`, `mvd-api`, and `mvd-mcp`. |

### Server Assets on `servexeri`

Verified by SSH on 2026-06-05.

| Asset | Location / command | Finding |
|---|---|---|
| OS | `uname -a` | Ubuntu 24.04, Linux `6.8.0-111-generic`, host `servexeri`. |
| Live server root | `~/nquakesv/` | Present. |
| MVDSV binary | `~/nquakesv/mvdsv`, `~/nquakesv/build/mvdsv/mvdsv` | Present. Server build checkout reported commit `90aa017`. |
| KTX module | `~/nquakesv/ktx/qwprogs.so` | Present. KTX build checkout reported commit `08807da`. |
| Existing ports | `28501`, `28502`, `28503` | Running as `turkishbathhouse:*`; all were empty at inspection time. User confirmed no one plays there, so lab use is allowed. |
| Stock DM2 map | `~/nquakesv/qw/maps/dm2.bsp` | Present. |
| Frogbot DM2 map | `~/nquakesv/qw/maps/frobodm2.bsp` | Present. |
| DM3 map | `~/nquakesv/qw/maps/dm3.bsp` | Present. |
| Frogbot route | `~/nquakesv/ktx/bots/maps/frobodm2.bot` | Present. |
| DM3 Frogbot route | `~/nquakesv/ktx/bots/maps/dm3.bot` | Present. |
| DM2 loc | `~/nquakesv/ktx/locs/dm2.loc` | Present. |
| Frogbot loc | `~/nquakesv/ktx/locs/frobodm2.loc` | Present. |
| DM3 loc | `~/nquakesv/ktx/locs/dm3.loc` | Present. |
| Demo directory | `~/nquakesv/ktx/demos/` | Exists but contained only the `demoshere` marker during inspection. |
| HUD runner | `~/hud-runner/` | Present; current Linux headless screenshot path. |
| nQuake client | `~/nquake/` | Present for the HUD runner. |

### Active Server Config Findings

| Config | Finding |
|---|---|
| `~/nquakesv/ktx/server.cfg` | Executes `mvdsv.cfg`, `ktx.cfg`, passwords/VIP/ban configs; runs `check_maps`; defaults `k_fb_enabled 0` to keep bot mode off after map reset. |
| `~/nquakesv/ktx/ktx.cfg` | `demo_tmp_record 1` enables MVD autorecording; `k_demotxt_format "json"` asks KTX to write JSON sidecars. |
| `~/nquakesv/ktx/mvdsv.cfg` | `sv_demotxt 2`, `sv_demodir demos`, `sv_demofps 77`, `sv_demoUseCache 1`; downloads for demos are enabled. |
| `~/nquakesv/run/port_28501.sh` | Starts a server with `./mvdsv -port 28501 -mem 64 -game ktx +exec port_28501.cfg`. |
| `~/nquakesv/start_servers.sh` | Generates per-port configs from `~/.nquakesv/ports/*` and starts screen sessions. |
| `~/nquakesv/stop_servers.sh` | Stops configured live ports and QTV/QWFWD. Do not use this for lab automation unless intentionally managing live service. |

### Bot Support Findings

KTX source and deployed artifacts both indicate bot support is available:

- Local KTX `CMakeLists.txt` defaults `BOT_SUPPORT` to `ON`.
- `src/bot_commands.c` registers `botcmd` subcommands including `enable`, `addbot`, `fill`, `removebot`, `removeall`, `skill`, `debug`, `health`, `weapon`, and editor commands.
- `src/commands.c` registers `botcmd` with `CF_BOTH | CF_MATCHLESS | CF_PARAMS`, but the successful smoke test showed `botcmd` is a KTX client command, not an MVDSV server-console command.
- `strings ~/nquakesv/ktx/qwprogs.so` shows `botcmd`, `/botcmd enable`, `addbot`, and `k_fb_enabled`.
- Deployed `~/nquakesv/ktx/bots/maps/` contains route files, including `frobodm2.bot`.

The unattended control path that worked was a minimal scripted QuakeWorld client that completed the challenge/connect/sign-on flow and then sent reliable string commands:

```text
prespawn <spawncount> 0 0
spawn <spawncount> 0
begin <spawncount>
botcmd addbot
```

KTX Frogbot auto-add was not enough for a zero-human test because the auto-add path depends on `human_count`. Full ezQuake under Xvfb was attempted, but it did not reliably become a connected slot during this pass.

The smoke-test shim is now captured in `experiments/qw_min_client.py`. It is an experiment artifact used by the current lab launcher. Example direct invocation from a host that can reach the MVDSV UDP port:

```bash
python experiments/qw_min_client.py 28599 --host 127.0.0.1 --local-port 28630 --run-for 45 --bot-count 2
```

### Parser Assets

| Asset | Location | Finding |
|---|---|---|
| WSL bundle | `~/mvd-mcp-bundle/` in `Ubuntu-24.04` | Present on host `PINNACLEWIN11`. |
| Parser binaries | `~/mvd-mcp-bundle/mvd-api`, `~/mvd-mcp-bundle/mvd-mcp` | Present; static Linux/amd64 bundle. |
| BSP geometry | `~/mvd-mcp-bundle/bsps/dm2.bsp` | Present, so DM2 loc/region analysis can use map geometry. |
| API usage | `./mvd-api -addr :8080` | Help output works; default cache root is `~/.cache/qw-mvd`. |
| Source rebuild | WSL `go version` | `go` was not on PATH during inspection. Use the bundle binaries first; fix Go separately if source rebuilds are needed. |

The bundle README says it was built from mvd_analyzer commit `7d83ebe`, while the local source checkout is `fab7808`. Treat this as a version-skew risk until pinned.

## Capability Matrix

| Desired capability | Current status | Evidence / note |
|---|---|---|
| Run KTX with bot support | Proven on `frobodm2` and `dm3` | KTX source has `BOT_SUPPORT ON`; deployed `qwprogs.so` contains bot command strings and lab runs spawned two Frogbots. |
| Load stock DM2 automatically | Proven for load/record/parse only | `20260605T195452Z` loaded stock `dm2` and produced a parsable MVD, but no Frogbots entered because stock `dm2.bot` is absent. |
| Run a second routed map | Proven on `dm3` | `20260605T200124Z` loaded `dm3`, spawned `/ bro` and `/ goldenboy`, recorded an MVD, and parsed it. |
| Spawn bots automatically | Proven on routed maps via scripted client | MVDSV console `botcmd` failed as `Unknown command`; a minimal connected QW client successfully sent `botcmd addbot` twice. |
| Record MVD automatically | Proven on `frobodm2` and `dm3` | KTX saved non-empty MVDs after `sv_demostop`. |
| Parse MVD automatically | Proven for summary/events | `qw-analyze-v20` parsed JSON/Markdown summary exit 0; events mode emitted data then exited 1 with `qw-analyze: end of demo`. |
| Generate movement report automatically | Proven v2 | `scripts/extract_movement_metrics.py` writes speed plus airborne-proxy movement metrics from MVD event position samples. |
| Test movement overrides automatically | Provisionally proven | `experiments/ktx_moveprobe/frogbot-moveprobe.patch` hooks KTX `BotSetCommand()` after the prewar-freeze guard and before button assembly/`trap_SetBotCMD(...)`; `20260605T225720Z` and `20260605T225802Z` passed explicit mode `3` command/plausibility gates on two routed maps. S3d/S3e mode `5` proves aim-independent command emission; S3f mode `6` proves a no-backpedal correction can pass the current gate, with command-magnitude caveats. S6b route-state logging proves the same command trace can be tagged with marker/goal/path-state/blocked context. |
| Visual validation | Available for playback | `ezquake-test` / `~/hud-runner` can render existing demos headlessly; useful after new MVDs exist. |

## One-command Bot Runner

Run from the repo root:

```bash
python scripts/run_bot_lab.py
```

Useful verification forms:

```bash
python scripts/run_bot_lab.py --duration 40 --bot-count 2
python scripts/run_bot_lab.py --map dm3 --duration 40 --bot-count 2
python scripts/run_bot_lab.py --map frobodm2 --duration 40 --bot-count 2 --moveprobe-mode 1
python scripts/run_bot_lab.py --map frobodm2 --duration 20 --bot-count 2 --moveprobe-mode 0 --moveprobe-log-commands
python scripts/run_bot_lab.py --map frobodm2 --duration 25 --bot-count 2 --bot-spacing 6 --moveprobe-mode 3 --moveprobe-log-commands
```

The `--moveprobe-*` options only change behavior when the S2 KTX patch from `experiments/ktx_moveprobe/` is applied to the server-side KTX build. Without that patch, the runner still records the cvars in `lab.cfg` and `run.env`, but stock KTX ignores them.

`--moveprobe-log-commands` enables the patch's sampled `FBMOVEPROBE_CMD` console rows. The runner parses those rows from `screen.log` into `moveprobe-commands.json` and `moveprobe-commands.md`, making it possible to compare the actual command values emitted by stock mode `0`, forced-jump mode `1`, fixed-command mode `2`, route-yaw modes `3`/`4`, aim-independent mode `5`, and no-backpedal mode `6`. S3e/S3f diagnostic rows also include route yaw, view yaw, yaw delta, and backward-command flags. Event rows are parsed beside the sampled command log: `FBMOVEPROBE_QWD_EVENT` -> `moveprobe-qwd-events.*`, `FBMOVEPROBE_REPLAY_EVENT` -> `moveprobe-replay-events.*`, and A5 `FBMOVEPROBE_S23` transition rows -> `moveprobe-s23-events.*`.

### ztricks batch attempts

For ztricks Distance tuning, prefer the batch harness over the old one-attempt
manual loop:

```bash
python scripts/run_ztricks_batch.py --attempts 6 --attempt-seconds 8 --refcurve
```

What it does:

1. Starts one temporary `ztricks` lab server and one MVD recording.
2. Keeps a passive client connected so recording does not depend on each short
   control shim.
3. For each attempt, clears spawn-snap state, sends `botcmd removeall`, sets
   the mode-23 Distance route cvars, restores the known A5 spawn
   origin/velocity, adds one bot, and lets the attempt run.
4. Copies the normal lab artifacts back under `artifacts/lab-runs/<run-id>/`.
5. Writes `ztricks-batch-plan.*`, `ztricks-batch-execution.tsv`, and
   `ztricks-batch-score.json/md`.

The current ztricks defaults use the first grounded human reference state
(`-3434.375 3686.875 -488`, velocity `259 -172 0`) and, with `--refcurve`,
enable the human terminal guidance curve with entry target
`(-3439.375, 3758.125)`, y corridor `3768.5 +/- 24`, and `carve_d=95`.

The scorer can also be run on any existing compatible artifact directory:

```bash
python scripts/score_ztricks_batch.py --run-id <run-id>
```

The score is release-first: it compares each attempt to the successful
`getspeed.qwd` formula (`vh`, lip distance, velocity yaw, target error, yaw
lead, jump release, and landing distance). Do not treat a high raw speed or a
near-lip pass as success unless the release formula rows also improve.
This release-first warning applies to `distance_standstill`. The safe-floor
`spawn_left_speedjump` route deliberately uses a different profile:
`python scripts/run_ztricks_batch.py --route spawn_left_speedjump ...` and
`python scripts/score_ztricks_batch.py --route spawn_left_speedjump --run-id <run-id>`
score start-to-peak horizontal speed gain against the successful human
attempt's `495.5 qu/s` peak, with no ledge/landing completion gate.

The ztricks scorer now follows Nexus's interpolation advice: sampled telemetry
rows are not treated as isolated dots. Bot release and landing estimates use
XY projection onto adjacent sampled segments, and the physical lip event uses
a linear crossing at `x=-3348`. The human reference trace is generated with:

```bash
python scripts/build_ztricks_reference_trace.py
```

That writes `experiments/a5_distance_standstill/ztricks-reference-trace.json/md`.
The trace keeps conservative linear/projection events for evidence, and also
adds a local-quadratic controller guidance curve over the terminal mouse/yaw
sweep. Angles are unwrapped before interpolation so `359 -> 1` is treated as a
small turn, not a full rotation.

### Per-slot moveprobe cvars (LD-F1 #95)

With `experiments/ktx_moveprobe/frogbot-moveprobe-perslot.patch` applied to the deployed lab KTX build, the route-defining lab cvars accept a per-slot form `k_fb_moveprobe_<param>_s<N>` for `mode`, `replay_file`, `fixed_goal`, `spawn_origin`, and `spawn_velocity`, where `N` is the bot's `ed` number from `FBMOVEPROBE_CMD` rows. Unset per-slot cvars fall back to the global cvar (existing single-route configs behave identically); malformed per-slot values fail loudly (`FBMOVEPROBE_PERSLOT_ERROR` row + bot held at spawn). This is what lets two bots attempt two different routes on the same map at the same time. Per-slot cvars are set through `--ktx-extra-cvars`; extra route files upload via `--extra-replay-cmds` (repeatable). When command logging is on, each bot also emits one `FBMOVEPROBE_ASSIGN` row per assignment change, and `scripts/run_frobodm2_lab.py` parses assignment + error rows into `moveprobe-assignments.json` / `moveprobe-assignments.md` beside the other run artifacts. Full convention, formats, base checksums, and apply notes: `experiments/ktx_moveprobe/README.md`.

What it does:

1. Checks local tools: `ssh`, `scp`, `wsl`, and `python`.
2. Checks remote prerequisites on `servexeri`: `python3`, `screen`, `quakestat`, `~/nquakesv/mvdsv`, and the selected map BSP. Route presence is recorded by the remote run and missing routes are treated as an experiment result.
3. Chooses port `28599` if free, or the next free port in a small range unless `--strict-port` is used.
4. Creates `~/komodobots-lab/runs/<run-id>/` remotely.
5. Uploads `experiments/qw_min_client.py`.
6. Generates a run-specific KTX config and starts `mvdsv` in a named `screen` session.
7. Loads the selected map, enables Frogbots, starts recording, and runs the client shim.
8. Stops recording, copies the latest produced MVD into the remote run directory as `demo.mvd`, records SHA-256 and size, and stops the screen session.
9. Copies the remote run directory to `artifacts/lab-runs/<run-id>/`.
10. Runs `~/qw-sim/bin/qw-analyze-v20` through WSL in `json`, `md`, and `events` modes.
11. Derives movement metrics from `events.txt` kind `5` player origin samples.
12. Derives optional moveprobe command logs from `screen.log` when the patched KTX build emits `FBMOVEPROBE_CMD` rows.
13. Derives optional moveprobe event logs for QWD, replay, and A5 S23 transition events when the patched KTX build emits those rows.
14. Writes `run-summary.md`, `movement-metrics.json`, `movement-metrics.md`, and optional `moveprobe-commands.*` / `moveprobe-*-events.*` artifacts.

Local artifact layout:

```text
artifacts/lab-runs/<run-id>/
  analysis.json
  analysis.md
  demo.mvd
  demo.remote-path.txt
  demo.sha256
  demo.size
  demo.txt
  events.txt
  hardcopy.*.txt
  lab.cfg
  pyclient.stdout
  pyclient.stderr
  remote.stdout
  remote.stderr
  movement-metrics.json
  movement-metrics.md
  run-summary.md
  run.env
  screen.log
```

Verified repeatability runs:

| Run ID | Port | Local demo size | Parser exits | Result |
|---|---:|---:|---|---|
| `20260605T190849Z` | `28599` | `108554` bytes | `json=0`, `md=0`, `events=1` | Two bots observed, two frags, summary written. |
| `20260605T191116Z` | `28599` | `98919` bytes | `json=0`, `md=0`, `events=1` | Two bots observed, no frags, summary written. |
| `20260605T200124Z` | `28599` | `102929` bytes | `json=0`, `md=0`, `events=1` | `dm3`; two bots observed, one frag, summary written. |
| `20260605T201217Z` | `28599` | `110679` bytes | `json=0`, `md=0`, `events=1` | `frobodm2`; two bots, two frags, movement metrics written. |
| `20260605T201313Z` | `28599` | `106867` bytes | `json=0`, `md=0`, `events=1` | `dm3`; two bots, one frag, movement metrics written. |
| `20260605T205256Z` | `28599` | `105711` bytes | `json=0`, `md=0`, `events=1` | `frobodm2`; two bots, v2 baseline metrics written. |
| `20260605T205353Z` | `28599` | `109061` bytes | `json=0`, `md=0`, `events=1` | `dm3`; two bots, v2 baseline metrics written. |
| `20260605T213010Z` | `28599` | `73890` bytes | `json=0`, `md=0`, `events=1` | `frobodm2`; S2 moveprobe mode `2`, fixed command replacement plus forced jump, two bots, one telefrag, near-stationary metrics. |
| `20260605T213149Z` | `28599` | `109520` bytes | `json=0`, `md=0`, `events=1` | `frobodm2`; S2 moveprobe mode `1`, forced jump perturbation, two bots, three frags, movement metrics written. |
| `20260605T222006Z` | `28599` | `71105` bytes | `json=0`, `md=0`, `events=1` | `frobodm2`; S2 v2a stock mode `0`, command logging enabled, `196` commands parsed. |
| `20260605T222047Z` | `28599` | `65648` bytes | `json=0`, `md=0`, `events=1` | `frobodm2`; S2 v2a forced-jump mode `1`, command logging enabled, `196` commands parsed. |
| `20260605T222129Z` | `28599` | `47234` bytes | `json=0`, `md=0`, `events=1` | `frobodm2`; S2 v2a fixed-command mode `2`, command logging enabled, `197` commands parsed, near-stationary metrics. |
| `20260605T224811Z` | `28599` | `59812` bytes | `json=0`, `md=0`, `events=1` | `frobodm2`; S2 v2b route-yaw mode `3`, command logging enabled, `197` commands parsed, mixed movement plausibility. |
| `20260605T225720Z` | `28599` | `67335` bytes | `json=0`, `md=0`, `events=1` | `frobodm2`; S2 v2c route-yaw mode `3`, command logging enabled, `197` commands parsed, both bots passed plausibility gate. |
| `20260605T225802Z` | `28599` | `64591` bytes | `json=0`, `md=0`, `events=1` | `dm3`; S2 v2c route-yaw mode `3`, command logging enabled, `196` commands parsed, both bots passed plausibility gate. |
| `20260605T231033Z` | `28599` | `68834` bytes | `json=0`, `md=0`, `events=1` | `frobodm2`; S3a mode `4`, alternating side command logged, both bots passed stricter side/plausibility gate, one RL frag. |
| `20260605T231115Z` | `28599` | `71271` bytes | `json=0`, `md=0`, `events=1` | `dm3`; S3a mode `4`, alternating side command logged, `/ bro` failed low-speed gate. |
| `20260605T231737Z` | `28599` | `63831` bytes | `json=0`, `md=0`, `events=1` | `dm3`; S3b mode `4` with `sidemove=200`, both bots passed side/plausibility gate. |
| `20260605T231819Z` | `28599` | `66789` bytes | `json=0`, `md=0`, `events=1` | `dm3`; S3b mode `4` with `sidemove=300`, `/ bro` failed low-speed gate. |
| `20260605T233120Z` | `28599` | `68715` bytes | `json=0`, `md=0`, `events=1` | `frobodm2`; S3c mode `4` with `sidemove=200`, both bots passed side/plausibility gate, one RL frag. |
| `20260605T233202Z` | `28599` | `63803` bytes | `json=0`, `md=0`, `events=1` | `dm3`; S3c mode `4` with `sidemove=200`, both bots passed side/plausibility gate. |
| `20260605T234620Z` | `28599` | `62771` bytes | `json=0`, `md=0`, `events=1` | `frobodm2`; S3d mode `5` with `sidemove=200`, command coverage passed, `/ bro` failed behavior gates, `/ goldenboy` passed, one SSG frag. |
| `20260605T234701Z` | `28599` | `62921` bytes | `json=0`, `md=0`, `events=1` | `dm3`; S3d mode `5` with `sidemove=200`, command coverage passed, `/ bro` failed behavior gates, `/ goldenboy` passed. |
| `20260606T000331Z` | `28599` | `70414` bytes | `json=0`, `md=0`, `events=1` | `frobodm2`; S3e mode `5` diagnostics, both bots passed horizontal/side behavior gate, one SSG frag. |
| `20260606T000414Z` | `28599` | `74149` bytes | `json=0`, `md=0`, `events=1` | `dm3`; S3e mode `5` diagnostics, both bots passed command gates but failed low-speed behavior gate. |
| `20260606T001705Z` | `28599` | `68881` bytes | `json=0`, `md=0`, `events=1` | `dm3`; S3f mode `6`, both bots passed horizontal/side behavior gate, one SG frag. |
| `20260606T001825Z` | `28599` | `70030` bytes | `json=0`, `md=0`, `events=1` | `frobodm2`; S3f mode `6`, both bots passed horizontal/side behavior gate, one GL frag. |

In verified runs, `quakestat -qws localhost:28599 -P -nh` reported `DOWN` after cleanup.

## Spectating the Lab (QTV in Browser)

Status: `scripts/run_lab_qtv.py` added 2026-06-07. Pure helpers (port selection,
config generation, watch-URL building, validation) are covered by
`tests/test_run_lab_qtv.py` and pass in CI. **Live-server behavior is not yet
verified**: the authoring sandbox has no `ssh` and cannot reach `servexeri`, so
the SSH/screen orchestration must be confirmed from a host that can reach the
box. This is the first thing to run when verifying.

Purpose: watch the bot lab live from a browser without disturbing the
measurement pipeline or the ongoing movement experiments. It is a **standalone**
launcher, separate from `run_bot_lab.py`, so the proven runner is untouched.

How it stays non-disruptive:

- Dedicated MVDSV/KTX process on its own UDP game port (default `28599` family)
  and its own TCP QTV stream port (default game-port + `100`).
- Its own screen session, always prefixed `komodobots_qtv_...`. `down`/`status`
  only ever match that prefix, and `down` only deletes the `kqtv_*.cfg` files the
  launcher itself wrote. It never calls `start_servers.sh`/`stop_servers.sh`,
  never edits `~/.nquakesv/ports/*`, and never touches the existing live
  QTV/QWFWD.
- Bots run **stock**: the generated config carries no `k_fb_moveprobe_*` cvars,
  so a spectate session cannot perturb a movement experiment.

QTV mechanism (source-grounded): MVDSV has a built-in QTV server, so no separate
`qtv` proxy is needed for a single lab server. Confirmed cvars in
`QW-Group/mvdsv` `src/sv_demo_qtv.c`: `qtv_streamport` (TCP stream listen port),
`qtv_password`, `qtv_maxstreams`, `qtv_pendingtimeout`, `qtv_streamtimeout`,
`qtv_sayenabled`. `sv_mvdhost` advertises the public `host:port` of the stream.
We do not override `sv_master`, so the lab server heartbeats to the QW masters
exactly like the box's other public servers and appears on the Hub.

Watch paths the launcher prints:

- Browser: open `https://hub.quakeworld.nu/`, find `komodobots-lab-qtv:<port>`,
  click its watch/eye action (the Hub's web player bridges the QTV stream).
- ezQuake (desktop): `/qtvplay tcp:<public-host>:<qtv-port>`.

Usage:

```bash
python scripts/run_lab_qtv.py up --map dm3 --bot-count 4
python scripts/run_lab_qtv.py status
python scripts/run_lab_qtv.py down            # stops all lab QTV sessions
python scripts/run_lab_qtv.py down --session komodobots_qtv_dm3_28599_<run-id>
```

`up` starts the server, enables Frogbots, spawns `--bot-count` bots, and keeps a
thin connected client (`experiments/qw_min_client.py`) alive for `--duration`
seconds (default `3600`). The keepalive client matters because QTV spectators do
**not** count as server players, so without one human present the Frogbots would
drain. `--public-host auto` (default) resolves the box's public address remotely;
pass an explicit IP/DNS if auto-detection is wrong.

First-verification checklist on a host that can reach `servexeri`:

```bash
python scripts/run_lab_qtv.py up --map dm3 --bot-count 4 --duration 600
python scripts/run_lab_qtv.py status     # expect the QTV port listening, server UP
# open the printed Hub URL / qtvplay link and confirm you can watch the bots
python scripts/run_lab_qtv.py down
```

If the QTV port never reports listening, the deployed MVDSV build may lack QTV
support or the TCP port is firewalled; both are recorded as experiment results,
not silent failures.

## 2026-06-05 Smoke Run

Run identity:

- Run ID: `20260605T180521Z`
- Remote run directory: `servexeri:/home/xerial/komodobots-lab/runs/20260605T180521Z`
- Screen session: `komodobots_lab_28599`
- Port: `28599`
- Map: `frobodm2`
- Demo: `servexeri:/home/xerial/nquakesv/ktx/demos/ffa_2[frobodm2]20260605-1825.mvd`
- Demo size: `112289` bytes
- Transferred demo SHA-256: `00CFFC080105966C14DA0FA6736BF66D2C31F0989DAFA7DC82EB9072956A4FBA`

Server setup used:

```text
k_fb_enabled 1
k_fb_autoadd_limit 0
k_fb_auto_delay 1
k_fb_skill 10
map frobodm2
sv_demoeasyrecord komodobots_frobodm2_20260605T180521Z_pyclient
```

KTX canceled the manual easy-record name when the real FFA match recording started, then saved `ffa_2[frobodm2]20260605-1825.mvd` on `sv_demostop`.

Observed server evidence:

- Scripted client connected as `KomodoPy`.
- `/ bro` entered the game.
- `/ goldenboy` entered the game.
- Server status showed three slots: the scripted client plus two Frogbots.
- Server log showed `/ goldenboy was gibbed by / bro's rocket`.

Parser evidence:

```text
json exit=0 bytes=24395 stderr=
md exit=0 bytes=96 stderr=
events exit=1 bytes=813009 stderr=qw-analyze: end of demo
```

JSON summary:

- Duration: `39307` ms
- Map title: `Frogbotrophobopolis`
- Total frags: `2`
- `28354` ms: `/ bro` killed `/ goldenboy` with `rl`
- `34828` ms: `/ goldenboy` killed `/ bro` with `rl`

Cleanup:

- `screen -S komodobots_lab_28599 -X quit`
- `quakestat -qws localhost:28599 -P -nh` reported `DOWN`.

## Automation Entry Point

Current Komodobots-owned entry point:

```text
scripts/run_bot_lab.py
```

The current implementation still lives in `scripts/run_frobodm2_lab.py`; `scripts/run_bot_lab.py` is the preferred neutral wrapper.

Current behavior:

1. SSH to `servexeri`.
2. Create a temporary lab workspace under `~/komodobots-lab/`.
3. Generate a lab-specific KTX port config. Any port is acceptable; using a high port such as `28599` still keeps logs/process names obvious.
4. Start `~/nquakesv/mvdsv -port <port> -mem 64 -game ktx +exec <generated-cfg>` in its own `screen` session.
5. Load the selected map. Use maps with real Frogbot routes such as `frobodm2` or `dm3`.
6. Enable Frogbots and spawn one or more bots through the scripted client.
7. Run for a short fixed duration.
8. Stop the match/server and collect the generated `.mvd` plus the KTX sidecar if it is present and non-empty.
9. Copy artifacts back under a gitignored local output directory such as `artifacts/lab-runs/<timestamp>/`.
10. Invoke the WSL `qw-analyze-v20` path to produce JSON, Markdown, and line-delimited event output.
11. Run `scripts/extract_movement_metrics.py` to produce per-player movement metrics.
12. Write `run-summary.md`; documentation is updated manually as findings become project-relevant.

Important guardrails:

- `~/nquakesv/stop_servers.sh` is acceptable when intentionally managing the whole unused server stack, but a lab runner should preferably stop only the process/session it started.
- Do not modify `~/.nquakesv/ports/*` for the lab unless intentionally promoting the lab to managed service.
- Keep lab configs and generated demos outside the live `ktx/` config unless the change is deliberate and documented.
- Prefer a temporary screen session name such as `komodobots_lab_28599`.
- Record exact KTX/MVDSV/mvd_analyzer commits or binary versions in each report.

## Lab Dashboard Frontend

Canonical home since LD-A1 (#84): `lab/dashboard/` in this repository (Vite + React +
TypeScript + three.js, base `/botlab/`; absorbed from `Xerialen/local-hub`
`feat/botlab-viewer` — see `docs/02_SOURCE_MAP.md` and `lab/README.md`).

- Deployed surface: `http://192.168.86.33:8095/botlab/`, served by the local-hub
  `web/serve.py` (screen `localhub-web`) on servexeri. Until LD-A2 (#85) lands the
  additive deploy script and same-URL cutover, the deployed copy still comes from the
  old local-hub patch build; this repo's `lab/dashboard/dist/` is the replacement.
- Live services the page consumes: telemetry sidecar `ws://192.168.86.33:8770`
  (`scripts/telemetry_ws.py`) and the deployed `/qtv/` page in an iframe (temporary,
  replaced by the standalone postMessage QTV pane in LD-B2, #88).
- Dev loop: `cd lab/dashboard && npm ci && npm run dev` (see `lab/README.md`).
- View shell (LD-B1, #87): top-bar toggles render any subset of the four main views in
  the fixed left→right order Demo → Mockup → Live 3D → Live Game (SPEC §4.1). The KPI
  dock is a real shell column; the control panel and cvar console are non-modal side
  panels. The control panel docks right. The cvar console docks right when alone, or
  left when the control panel is already open. Layout state (open set, dock collapsed,
  control panel open, console panel open) persists in localStorage and the open set is
  mirrored in the URL (`?views=…`, URL wins on load) — `lab/dashboard/src/layoutState.ts`.
- Hosted CI: `.github/workflows/lab-dashboard-ci.yml` runs on GitHub-hosted
  `ubuntu-latest` for pull requests touching `lab/**` or `tests/lab_*.py`
  (lab pytest files are not discovered by `PR Tests`' `test_*.py` unittest
  glob, so this workflow is their only hosted gate). It performs `npm ci`,
  `tsc --noEmit`, optional lint, `vite build`, `python -m compileall` over lab
  Python directories, and optional `tests/lab_*.py` pytest. This is distinct
  from `.github/workflows/lab-ci.yml`, which remains the manual self-hosted
  servexeri bot-lab runner and is not touched by LD-A3 (#86).
- Control bridge (LD-F2, #96): the telemetry sidecar also carries a JSON command
  channel (`lab/server/control_bridge.py`, deployed flat next to `telemetry_ws.py`
  together with `qw_min_client.py`). Hard server-side gates: caller authorization
  for every mutating op — loopback peer (operator/ssh tunnel) or the per-deploy
  control token auto-created 0600 at `~/komodobots-lab/control.token`, plus a
  browser Origin allowlist (`--allow-origin`, default empty = browsers are
  telemetry-only) as CSRF defense on top (Codex P1, #129); lab port allowlist
  28599–28609 only; production 28501/28502/28503 and `qw_*` screens flat-denied;
  cvar/console allowlists; the `game_command` op is a separate allowlisted enum for
  KTX game controls (`4on4`, `2on2`, `1on1`, `ffa`, `dmm1`–`dmm4`, powerups on/off,
  `ready`, `break`) and legacy guarded lab presets rather than a broad raw-command
  escape hatch. Dashboard session start is deliberately not
  "start game": it seeds the practice roster in moveprobe mode `24`, assigns separated
  spawn-snap origins for maps with known safe starts (`dm3`, `ztricks`), clears the
  global spawn cvar after seeding, and suppresses movement/jump/firing so unassigned
  bots wait quietly until route assignment. The game-control `start` command clears the global
  practice idle mode, unlocks normal bot weapons, and readies the match; `stop` breaks
  the match and restores quiet practice posture. In the dashboard UI, ztricks Distance
  is now represented as the normal `distance_standstill` route in the route manifest,
  not as a separate global trick control. The per-bot route row applies its A5
  spawn-snap (`-3516.125 3712 -453.125`), mode 23, fixed goal 8, launch-vh 430 /
  launch-angle 50 / swing 8 metadata plus the default-off terminal-carve cvars
  (`launch_target_{x,y,z}`, `lip_x`, release speed floors, carve side/angle, yaw-lead
  and target-error windows), then lets the operator start it with that bot's
  `try` or `loop` action while `stand still` returns the slot to mode 24. This creates
  a visible standing-start attempt; it does not change the A5 finding that the current
  deployed controller has not solved the jump. The `spawn_left_speedjump` route is the
  safe-floor counterpart: it starts at the real ztricks deathmatch spawn
  (`-1168 1632 -496`), seeds zero velocity, points 90 degrees left from the BSP
  spawn angle, sets both `lip_x` and `lip_y` so KTX projects Nexus-curve progress
  along the diagonal lane, rotates the reference curve by `45` degrees, and
  measures horizontal speed increase rather than far-platform landing. Live batch
  `zbatch_20260612T180901Z` reached human-level speed on `5/6` attempts, best
  `506.2 qu/s` against the `495.5 qu/s` target. Reproduction batches
  `zbatch_20260612T182309Z` and `zbatch_20260612T182505Z` reached `6/6` and
  `7/8` respectively, with the fixed-param miss at `494.9 qu/s`. Audit log at
  `~/komodobots-lab/control-audit.log`.
  The lab lock `~/komodobots-lab/lab.lock` gives the experiment harness absolute
  priority: `run_frobodm2_lab.py` writes `owner=harness` for the duration of each
  attempt and the bridge refuses every mutating op while that lock is fresh
  (pid alive, ≤ 2 h); stale locks need an explicit `force=true`. Dashboard sessions
  run as `komodobots_lab_<port>` screens with the `mvdsv-lab` binary. The bridge checks
  both TCP and UDP bind availability and retries the next allowlisted lab port if MVDSV
  still fails during startup, and the harness refuses a port such a session occupies.
  Protocol, ops, and the `kbot-telemetry`
  restart procedure: `lab/README.md`. The dashboard UI can start/stop dashboard-owned
  sessions, manage bots/routes, send allowlisted cvars, and change allowlisted game
  controls through the bridge.

  Dashboard ztricks smoke on 2026-06-11: after redeploying the sidecar bridge, the
  browser flow started `ztricks` run `dash_20260611T214504Z` on port `28600` and clicked
  **Distance standstill**. The server log shows the quoted spawn-snap cvar applied and
  the first `FBMOVEPROBE_CMD` row at `origin=-3516.125,3712.000,-453.125`; later rows show
  `move=320` and `buttons=2`, proving a visible standing-start attempt from the A5 start
  point. Earlier unquoted smoke rows stayed at a normal spawn, which is why the preset
  now uses the quoted triplet form from the proven lab cfg.
  Follow-up browser pass on 2026-06-11 used the right-side control panel against
  `dash_20260611T221516Z` on port `28599`: a fresh force-takeover ztricks session
  showed `no bots`, clicking **try** returned `game ztricks_distance_standstill`,
  produced one roster row (`s3 / bro`), and the server log contained 18 nonzero
  `FBMOVEPROBE_CMD` rows starting at the same spawn. The visible symptom after that
  burst is that the bot settles/stands still; that is current controller behavior, not
  a dashboard command failure. The same pass verified the shorter response path no
  longer times out, while botcmd shims still need a 5 s connected window for reliable
  `removeall`.
  2026-06-12 route-only retry: the ztricks manifest no longer exposes a
  `game_command` override, so per-bot **try** uses the same route-cvar sequence
  as replay routes. The bridge quotes space-containing validated cvar values
  before console stuffing. Browser retry on `dash_20260612T120449Z` selected
  `distance_standstill` for bot `s5`, pressed that row's **try**, and the server
  emitted `FBMOVEPROBE_ASSIGN ... ed=5 ... mode=23 mode_src=slot ... fixed_goal=8
  goal_src=slot spawn_origin=-3516.125,3712,-453.125 spawn_src=slot` followed by
  mode-23 `FBMOVEPROBE_CMD` rows from the A5 start with `move=320,0,0`.
  2026-06-12 live retry on fresh session `dash_20260612T135158Z` (port `28599`)
  exposed the repeat-attempt edge: clearing a per-slot cvar must be stuffed as
  `set name ""`, and the dashboard must wait one sampled frame before restoring
  `spawn_origin`, otherwise KTX may only observe the final unchanged value and
  not re-arm the one-shot spawn snap. After fixing that, selecting
  `distance_standstill` for `s3` and pressing **try** emitted slot-sourced ASSIGN
  rows and 21 nonzero mode-23 command rows from the A5 start area. The repeat
  **try** emitted fresh clear/restore ASSIGN rows and nonzero movement again.
  The controller still missed the jump: closest first-attempt landing distance
  was about `138q`, so the remaining controller failure is tracked in GitHub
  issue #167.
- Multi-bot attempts: the telemetry stream interleaves one frame per probed bot
  (`frame.ed`/`frame.name`). The 3D view keeps a separate marker/trail/velocity-arrow
  per `ed` (distinct colors, in order of first appearance); the camera follow and the
  HUD's derived values (yaw rate, hops, air time) lock onto the attempt's first-seen
  bot, and the HUD shows that bot's name. A `new_attempt` resets all of it.
- Demo pane (LD-D2, #94): standalone FTE WASM demo player at `/botlab/panes/demo.html`
  (plays archived lab `.mvd` and human `.qwd` with seek/track/speed and a same-origin
  postMessage API; see `lab/README.md` for params, API, and FTE behavior notes). Two
  servexeri web-root dependencies: the existing `demos/files/non-games ->
  /mnt/usb-ssd/non-games` symlink (lab demo archive; verified present 2026-06-11) and a
  NEW `maps -> ~/nquakesv/qw/maps` symlink for local-first `.bsp` resolution
  (documented in `lab/README.md`, not yet created — lab host is read-only until the
  LD-A2 deploy path lands; the pane falls back to `assets.quake.world` meanwhile).

## Folder Layout

Current relevant layout:

```text
C:\Users\benya\projects\quakeworld\
  komodobots\
  engine\ktx\
  hud\ezquake-test\
  tools\mvd_analyzer\

servexeri:~/nquakesv/
  mvdsv
  build/mvdsv/mvdsv
  ktx/
    server.cfg
    ktx.cfg
    mvdsv.cfg
    port_28501.cfg
    bots/maps/frobodm2.bot
    bots/maps/dm3.bot
    locs/dm2.loc
    locs/frobodm2.loc
    locs/dm3.loc
    demos/
  qw/maps/
    dm2.bsp
    frobodm2.bsp
    dm3.bsp
  run/
    port_28501.sh
    port_28502.sh
    port_28503.sh

WSL Ubuntu-24.04:~/mvd-mcp-bundle/
  mvd-api
  mvd-mcp
  run-mcp.sh
  bsps/dm2.bsp
```

## Startup Instructions

Current server startup:

```bash
ssh servexeri 'cd ~/nquakesv && ./start_servers.sh'
```

Lab startup:

```bash
python scripts/run_bot_lab.py
```

The runner starts a separate generated lab process and cleans it up when the run finishes. It does not call `~/nquakesv/start_servers.sh`.

## Shutdown Instructions

Current full server shutdown:

```bash
ssh servexeri 'cd ~/nquakesv && ./stop_servers.sh'
```

The runner automatically kills only the lab screen/process it started. Manual cleanup, if needed:

```bash
ssh servexeri 'screen -S komodobots_lab_28599 -X quit'
```

The current runner uses session names shaped like `komodobots_lab_<port>_<run-id>`.

## Risks and Missing Dependencies

- Bot spawn control is proven through `experiments/qw_min_client.py`, but the shim is still intentionally protocol-narrow.
- Existing ports may be used for experiments; user confirmed no one plays there. Still prefer explicit lab configs/session names so output and cleanup stay understandable.
- The KTX `.txt` demo sidecar for the smoke run was zero bytes even though the `.mvd` parsed correctly.
- The WSL parser bundle and local `mvd_analyzer` source are at different commits. Pin the intended parser binary before using metrics as regression evidence.
- `go` was not on PATH in WSL during inspection. Rebuilding `mvd_analyzer` from source needs a toolchain fix, even though the prebuilt bundle works.
- Determinism is unknown. The lab must record seed/config/server version details before comparing movement runs.
- Stock `dm2` can load, record, and parse, but it is not a Frogbot-supported route target in this environment. User confirmed there is no point building routes for it now.
- A first-pass movement report schema exists, but it is still position-derived and does not yet infer ground-truth jump commands, grounded state, or usercmd intent.
- The S2 v2c moveprobe proves the final command can be perturbed and directly logged before `trap_SetBotCMD(...)`, and that route-derived yaw can pass provisional command/plausibility gates on two routed maps. S3 mode `4` proves nonzero alternating side commands can also be emitted; S3c indicates `sidemove=200` is repeatable across `frobodm2` and `dm3`. S3d/S3e mode `5` proves aim-independent route/strafe commands can be emitted and diagnosed, but behavior remains split. S3f mode `6` removes backpedal commands but emits large folded side commands. S3g mode `7` bounds those commands and passes both routed maps. S4c/S5a/S5b human and elite references show S3g remains below same-map reference avg/p95 movement. S6c attributes the strongest repeated S6b low-speed pattern to `WATER_PATH` route edges with low native `dir_speed`. S7j mode `8` shows transition-only horizontal budget scaling is measurable after the transition gate fix, but the combined fixed runs reject it under S7i stop conditions because pre-air, airborne-proxy, post-air, and non-airborne buckets regressed despite a small all-segment gain.

## Troubleshooting

Useful read-only checks:

```bash
ssh servexeri 'for p in 28501 28502 28503; do quakestat -qws localhost:$p -P -nh; done'
ssh servexeri 'cd ~/nquakesv && find ktx/bots/maps -maxdepth 1 -name "*.bot" | sort | head'
ssh servexeri 'cd ~/nquakesv && ls -lah ktx/demos'
wsl -d Ubuntu-24.04 -- bash -lc 'cd ~/mvd-mcp-bundle && ./mvd-api -h'
```

Likely failure areas:

- `botcmd` requires a connected client/admin context; MVDSV server console returns `Unknown command "botcmd"`.
- No demo appears because no match actually starts, the run is too short, or autorecord only persists after match finalization.
- KTX may produce an empty `.txt` sidecar even when the `.mvd` is valid.
- `qw-analyze-v20 -format events` may emit useful data but exit nonzero with `qw-analyze: end of demo` on short recordings.
- MVD appears but parser cannot resolve map geometry because `MVDA_BSP_DIR` is not pointed at `~/mvd-mcp-bundle/bsps`.
- A lab script stops more of `turkishbathhouse` than intended by using `stop_servers.sh` when it only meant to stop one lab process.
- Long full-match human 4on4 traces can produce `events.txt` files over `100 MB`. S7b optimized landing-window movement extraction with an indexed segment lookup after the old repeated full-list scan timed out on three parallel 20-minute references.

## Next Smallest Experiment

Move the repeatable runner one notch closer to the north star:

1. Keep `dm2` as a `qw-sim` continuity map, not as a Frogbot route-building target.
2. Use routed maps such as `frobodm2` and `dm3` to generate bot movement demos.
3. After S7j, do not promote mode `8` as controller behavior. The next smallest useful branch is S7k: inspect the failed air-transition, non-airborne, and probe-activation context before trying another controller probe.
