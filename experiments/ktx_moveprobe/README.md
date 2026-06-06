# KTX Frogbot Movement Probe

Status: S2/S3 experiment scaffold.

## Purpose

Prove that Frogbot movement commands can be overridden at the final command-emission point without replacing the KTX/MVDSV lab loop.

The patch in this directory is deliberately crude. It is not a bunnyjump controller and should not be promoted as movement AI.

## Patch

Apply `frogbot-moveprobe.patch` to a KTX checkout at commit `08807da` or an equivalent source tree:

```bash
cd ~/nquakesv/build/ktx
git apply /path/to/frogbot-moveprobe.patch
cmake --build build
```

The patch adds `k_fb_moveprobe_mode` handling inside `BotSetCommand()` after the prewar-freeze guard and immediately before button assembly and `trap_SetBotCMD(...)`.

It can also emit sampled command rows with the exact values about to be handed to `trap_SetBotCMD(...)`:

```text
FBMOVEPROBE_CMD time=12.250 ed=3 name=/ goldenboy mode=2 msec=13 angles=0.0,90.0,0.0 move=800,0,0 buttons=2 impulse=0
```

S3e diagnostic rows append route-vs-view context:

```text
FBMOVEPROBE_CMD time=12.500 ed=3 name=/ goldenboy mode=5 msec=12 angles=0.0,90.0,0.0 move=-200,400,0 buttons=2 impulse=7 diag=270.0,90.0,180.0,1
```

S6b diagnostic rows also append minimal route-state context:

```text
FBMOVEPROBE_CMD time=12.500 ed=3 name=/ goldenboy mode=7 msec=12 angles=0.0,90.0,0.0 move=0,824,0 buttons=2 impulse=7 diag=270.0,90.0,180.0,0 route=12,10,42,14,524288,8192,1,1.250
```

S6d diagnostic rows further append water/swim context:

```text
FBMOVEPROBE_CMD time=12.500 ed=3 name=/ goldenboy mode=7 msec=12 angles=0.0,90.0,0.0 move=0,824,0 buttons=2 impulse=7 diag=270.0,90.0,180.0,0 route=12,10,42,14,32768,128,0,0.050 water=3,-3,528,16,120.0,25.5,-4.0,80.0,0.100,0.200,0.300
```

Those rows are deliberately console-oriented, temporary probe output. They exist to compare stock, forced-jump, fixed-command, route-yaw, and aim-independent runs before building a real movement controller.

Modes:

| Mode | Meaning |
|---:|---|
| `0` | Off. Stock Frogbot command emission. |
| `1` | Force the jump button while preserving existing Frogbot movement direction and combat. |
| `2` | Replace the final movement command with fixed yaw/forward/sidemove/upmove values and force jump while leaving firing and weapon selection intact. |
| `3` | Set yaw from Frogbot route intent, send forward/sidemove/upmove command values, and force jump. This is a movement probe, not a combat-aim-preserving controller. |
| `4` | S3a probe: set yaw from Frogbot route intent, emit forward plus alternating side commands, and force jump. This is a bounded strafe/jump primitive, not a final bunnyjump controller. |
| `5` | S3d probe: preserve combat view yaw, project route/strafe intent into local forward/sidemove commands, and force jump. This tests aim-independent movement math, not a final controller. |
| `6` | S3f probe: start from mode `5`, but when the projected local forward command is negative, fold that backpedal amount into sidemove and clamp forward to `0`. This tests a no-backpedal correction, not a final controller. |
| `7` | S3g probe: start from mode `6`, then cap horizontal command magnitude to the original route/strafe intent magnitude. This tests whether no-backpedal survives without very large folded sidemove. |

Mode `2`, `3`, `4`, `5`, `6`, and `7` cvars:

| Cvar | Default in runner | Meaning |
|---|---:|---|
| `k_fb_moveprobe_yaw` | `0` | Bot view yaw used for fixed-command mode `2`. |
| `k_fb_moveprobe_forwardmove` | `800` | Forward command sent to `trap_SetBotCMD` in modes `2`, `3`, and `4`; route-intent scale for modes `5`, `6`, and `7`. |
| `k_fb_moveprobe_sidemove` | `0` | Side command sent to `trap_SetBotCMD` in modes `2` and `3`; mode `4` treats `0` as a default alternating `+/-400`; modes `5`, `6`, and `7` use the value as a route-relative strafe component. |
| `k_fb_moveprobe_upmove` | `0` | Up command sent to `trap_SetBotCMD` in modes `2`, `3`, `4`, `5`, `6`, and `7`. |
| `k_fb_moveprobe_log_commands` | `0` | When `1`, print sampled final command rows before `trap_SetBotCMD`. |
| `k_fb_moveprobe_log_interval` | `0.25` | Minimum seconds between command log samples per bot. Use `0` for every command. |

Mode `3` ignores `k_fb_moveprobe_yaw`; it computes yaw from `self->fb.dir_move_` when Frogbot has a non-zero horizontal route direction. If that route vector is empty for a frame, mode `3` leaves the already-computed stock command intact for that frame.

Mode `4` also ignores `k_fb_moveprobe_yaw`. It uses the same route-derived yaw as mode `3`, but alternates the sign of `sidemove` about five times per second, offset by bot slot. This is only a bounded S3a movement-literacy probe.

Mode `5` preserves `self->fb.desired_angle` instead of setting route yaw. It builds a desired route-relative movement vector, optionally adds the alternating strafe component, then projects that world vector into local `forwardmove`/`sidemove` commands using the preserved combat yaw. Exact `forwardmove=800` coverage is not expected in mode `5`; use horizontal-command coverage instead.

Mode `6` uses the same aim-independent projection as mode `5`, then clamps negative local `forwardmove` to `0` and transfers the removed magnitude into local `sidemove`. This keeps the bot from deliberately backpedaling when route intent is behind its preserved view angle.

Mode `7` uses the same no-backpedal correction as mode `6`, then normalizes local horizontal command magnitude back down to the intended route/strafe magnitude. With the usual `forwardmove=800 sidemove=200`, the expected cap is about `825`.

The S3e diagnostic suffix is shaped as `diag=<route_yaw>,<view_yaw>,<yaw_delta>,<backward>`. `backward=1` means the emitted local `forwardmove` is negative. `yaw_delta` and `view_yaw` are interpretable for aim-independent modes `5`, `6`, and `7`; route-yaw modes `3` and `4` overwrite view yaw from the route, so their deltas are structural noise.

The S6b diagnostic suffix is shaped as `route=<linked_marker>,<touch_marker>,<goal_ed>,<goal_marker>,<path_state>,<bot_state>,<blocked>,<dir_speed>`. Marker ids are Frogbot marker indexes plus one, or `-1` when absent. `goal_ed` is the current Quake edict number from `self->s.v.goalentity`; `goal_marker` is that entity's marker when available. `blocked=1` means either the `STUCK_PATH` bit is present in `path_state` or `fb.obstruction_normal` is currently non-zero. This is trace context only, not a new movement mode.

The S6d diagnostic suffix is shaped as `water=<waterlevel>,<watertype>,<flags>,<swim_arrow>,<emitted_upmove>,<velocity_x>,<velocity_y>,<velocity_z>,<dir_move_x>,<dir_move_y>,<dir_move_z>`. It exists to inspect whether `WATER_PATH` low-speed windows are shallow-water edge handling, active swim intent, missing vertical/upmove emission, route-edge geometry, or still unknown. `swim_arrow` uses the Frogbot `UP=16` / `DOWN=32` constants. `dir_move_*` is the raw Frogbot route movement vector sampled at command time.

## Runner

The lab runner can now write the cvars into the generated KTX config:

```bash
python scripts/run_bot_lab.py --map frobodm2 --duration 40 --bot-count 2 --moveprobe-mode 1
python scripts/run_bot_lab.py --map frobodm2 --duration 40 --bot-count 2 --moveprobe-mode 2 --moveprobe-yaw 90
python scripts/run_bot_lab.py --map frobodm2 --duration 20 --bot-count 2 --moveprobe-mode 0 --moveprobe-log-commands
python scripts/run_bot_lab.py --map frobodm2 --duration 25 --bot-count 2 --bot-spacing 6 --moveprobe-mode 3 --moveprobe-log-commands
python scripts/run_bot_lab.py --map frobodm2 --duration 25 --bot-count 2 --bot-spacing 6 --moveprobe-mode 4 --moveprobe-log-commands
python scripts/run_bot_lab.py --map frobodm2 --duration 25 --bot-count 2 --bot-spacing 6 --moveprobe-mode 5 --moveprobe-sidemove 200 --moveprobe-log-commands
python scripts/run_bot_lab.py --map dm3 --duration 25 --bot-count 2 --bot-spacing 6 --moveprobe-mode 6 --moveprobe-sidemove 200 --moveprobe-log-commands
python scripts/run_bot_lab.py --map dm3 --duration 25 --bot-count 2 --bot-spacing 6 --moveprobe-mode 7 --moveprobe-sidemove 200 --moveprobe-log-commands
```

Each run records the mode and command values in `run.env`, `lab.cfg`, and `run-summary.md`.

When command logging is enabled, the runner parses `screen.log` and writes:

- `moveprobe-commands.json`
- `moveprobe-commands.md`

The S2 v2a comparison is three short runs with `--moveprobe-log-commands`: stock mode `0`, forced-jump mode `1`, and fixed-command mode `2`. The comparison verifies final `msec`, view angles, movement command values, buttons, and impulses before any controller work continues.

The S2 v2b probe adds mode `3` as the smallest useful movement experiment after v2a: route-derived yaw plus a simple forward command. Its goal is to test whether the command seam can produce plausible movement from an existing route signal, not to solve aim/movement separation or bunnyjumping.

Known v2a comparison runs:

| Run ID | Mode | Result |
|---|---:|---|
| `20260605T222006Z` | `0` | Stock variable commands logged; movement remained plausible. |
| `20260605T222047Z` | `1` | Variable movement preserved; final buttons included jump. |
| `20260605T222129Z` | `2` | Constant `yaw=90 forward=800 side=0 up=0 buttons=2`; movement collapsed. |
| `20260605T224811Z` | `3` | Route-derived yaw varied and mostly emitted `forward=800`; `/ goldenboy` moved plausibly, while `/ bro` was stationary for 59.7% of active time. |
| `20260605T225720Z` | `3` | Fresh `frobodm2` repeat; both bots passed the v2c command/plausibility gate. |
| `20260605T225802Z` | `3` | Fresh `dm3` repeat; both bots passed the v2c command/plausibility gate. |
| `20260605T231033Z` | `4` | S3a alternating strafe on `frobodm2`; side command emitted and both bots passed gate, with one RL frag. |
| `20260605T231115Z` | `4` | S3a alternating strafe on `dm3`; side command emitted, but `/ bro` failed low-speed gate at `63.0%`. |
| `20260605T231737Z` | `4` | S3b `dm3` with `sidemove=200`; both bots passed side/plausibility gate. |
| `20260605T231819Z` | `4` | S3b `dm3` with `sidemove=300`; side command emitted, but `/ bro` failed low-speed gate at `51.1%`. |
| `20260605T233120Z` | `4` | S3c `frobodm2` with `sidemove=200`; both bots passed side/plausibility gate and one RL frag was recorded. |
| `20260605T233202Z` | `4` | S3c `dm3` repeat with `sidemove=200`; both bots passed side/plausibility gate. |
| `20260605T234620Z` | `5` | S3d `frobodm2` aim-independent projection; command coverage passed, `/ goldenboy` passed behavior gate, `/ bro` failed stationary/low-speed gates. |
| `20260605T234701Z` | `5` | S3d `dm3` aim-independent projection; command coverage passed, `/ goldenboy` passed behavior gate, `/ bro` failed stationary/low-speed gates. |
| `20260606T000331Z` | `5` | S3e `frobodm2` diagnostics; both bots passed, `/ bro` showed more yaw/backward conflict than `/ goldenboy`, one SSG frag. |
| `20260606T000414Z` | `5` | S3e `dm3` diagnostics; both bots passed command gates but failed low-speed, with the strongest yaw/backward signal on `/ bro`. |
| `20260606T001705Z` | `6` | S3f `dm3` no-backpedal correction; both bots passed with `0.0%` backward commands, one SG frag. |
| `20260606T001825Z` | `6` | S3f `frobodm2` no-backpedal correction; both bots passed with `0.0%` backward commands, one GL frag. |
| `20260606T003718Z` | `7` | S3g `dm3` bounded no-backpedal correction; both bots passed, `MaxMove` stayed about `824.5`, one SG frag. |
| `20260606T003808Z` | `7` | S3g `frobodm2` bounded no-backpedal correction; both bots passed, `MaxMove` stayed about `824.6`. |

## Plausibility summary

Use the v2c helper to summarize command coverage and movement plausibility across run artifacts:

```bash
python scripts/summarize_moveprobe_plausibility.py 20260605T225720Z 20260605T225802Z --output-md artifacts/lab-runs/moveprobe-v2c-fresh-summary.md
```

Default gate thresholds are intentionally simple and provisional:

- expected forward command coverage >= `80%`
- nonzero horizontal command coverage >= `0%` by default, or `80%` for aim-independent probes where exact local forward values vary
- nonzero side command coverage >= `0%` by default, or `80%` for S3a mode `4`
- jump-button command coverage >= `80%`
- distinct sampled yaw values >= `10`
- stationary time <= `25%`
- low-speed time <= `40%`

By default, `--expected-forward` is derived from each run's `MOVEPROBE_FORWARDMOVE` in `run.env` and falls back to `800`. Pass `--expected-forward` explicitly when summarizing older or custom artifacts whose intended forward command is not recorded.

For modes `5`, `6`, and `7`, use `--min-forward-ratio 0 --min-horizontal-ratio 0.8 --min-side-ratio 0.8`, because the preserved view yaw makes exact local `forwardmove=800` coverage the wrong signal.

The helper matches movement rows to command rows by movement `user_id` and command `ed` when both are available. For older artifacts without those IDs it falls back to bot netname, so duplicate bot names are ambiguous and should be avoided in comparison runs.

The gate is not a realism score. It is a guard against accidentally treating speed alone as success while ignoring stationary or command-coverage failures.

For S3a mode `4`, run the same helper with `--min-side-ratio 0.8` so the report proves a strafe command was actually emitted:

```bash
python scripts/summarize_moveprobe_plausibility.py 20260605T231033Z 20260605T231115Z --min-side-ratio 0.8 --output-md artifacts/lab-runs/moveprobe-s3a-summary.md
```

The first S3b parameter check suggests `sidemove=200` is a better `dm3` starting point than the mode `4` default `400`:

```bash
python scripts/summarize_moveprobe_plausibility.py 20260605T231737Z 20260605T231819Z --min-side-ratio 0.8 --output-md artifacts/lab-runs/moveprobe-s3b-summary.md
```

The S3c cross-map/repeat check validates `sidemove=200` as a repeatable route-yaw strafe candidate:

```bash
python scripts/summarize_moveprobe_plausibility.py 20260605T233120Z 20260605T233202Z --min-side-ratio 0.8 --output-md artifacts/lab-runs/moveprobe-s3c-summary.md
```

The S3d aim-independent movement-vector probe uses horizontal command coverage instead of exact-forward coverage:

```bash
python scripts/summarize_moveprobe_plausibility.py 20260605T234620Z 20260605T234701Z --min-forward-ratio 0 --min-horizontal-ratio 0.8 --min-side-ratio 0.8 --output-md artifacts/lab-runs/moveprobe-s3d-summary.md
```

The S3e diagnostic check uses the same gate and adds backward/yaw-delta columns:

```bash
python scripts/summarize_moveprobe_plausibility.py 20260606T000331Z 20260606T000414Z --min-forward-ratio 0 --min-horizontal-ratio 0.8 --min-side-ratio 0.8 --output-md artifacts/lab-runs/moveprobe-s3e-summary.md
```

S3e interpretation: yaw delta and negative local `forwardmove` are plausible contributors to the `dm3` mode `5` split, but not a complete explanation. The next proposed probe is S3f: prevent sustained backpedal commands in mode `5` and test `dm3` first.

The S3f no-backpedal correction uses mode `6` and the same gate:

```bash
python scripts/summarize_moveprobe_plausibility.py 20260606T001705Z 20260606T001825Z --min-forward-ratio 0 --min-horizontal-ratio 0.8 --min-side-ratio 0.8 --output-md artifacts/lab-runs/moveprobe-s3f-summary.md
```

S3f interpretation: mode `6` passes both routed maps and removes sampled backward commands, but folded side commands can reach roughly `1100`. The next proposed probe is S3g: bound or normalize local command magnitudes while preserving the no-backpedal property.

The S3g bounded no-backpedal correction uses mode `7` and the same gate:

```bash
python scripts/summarize_moveprobe_plausibility.py 20260606T003718Z 20260606T003808Z --min-forward-ratio 0 --min-horizontal-ratio 0.8 --min-side-ratio 0.8 --output-md artifacts/lab-runs/moveprobe-s3g-summary.md
```

S3g interpretation: mode `7` passes both routed maps while keeping sampled horizontal command magnitude near the intended `824.6` cap. This is a better S3 candidate than mode `6`, but the next step should anchor the gate against human-demo movement before more command tuning.

Committed derived summaries live under `experiments/ktx_moveprobe/evidence/` for S3e, S3f, and S3g. Raw MVDs and full run directories stay ignored under `artifacts/`.

## Route-state diagnosis

S6a uses the existing S3g `dm3` run and asks whether low-speed windows can be explained from current artifacts before adding another command mode:

```bash
python scripts/diagnose_route_state.py --stage s6a-route-state --run-id 20260606T003718Z --output-json artifacts/lab-runs/20260606T003718Z/s6a-route-state-diagnosis.json --output-md artifacts/lab-runs/20260606T003718Z/s6a-route-state-diagnosis.md
```

S6a result: the artifacts expose position traces, sampled final commands, route yaw, view yaw, yaw delta, backward-command state, and map-entity locations. They do not expose Frogbot route node, next waypoint, target entity, obstruction, or route primitive state. In the S3g `dm3` run, `8` of `9` analyzed top low-speed windows still had average sampled horizontal command at or above `400`. At that point the next step was route-state logging, not mode `8`.

S6b extends the same command log with the `route=` suffix and updates `scripts/diagnose_route_state.py` to summarize route-state values inside each low-speed window. Run `20260606T031102Z` proved route-state context is available; the next step is to decode repeated marker/path-state patterns before mode `7` changes again.

The diagnosis helper reports command/sample clock overlap and treats corrupt sibling JSON artifacts as warnings, so a bad or mismatched artifact is visible in the output instead of silently looking like missing commands. `--run-id` may be either a run id under `artifacts/lab-runs/` or an explicit existing run directory; explicit paths are read-only by design.

S6c decodes those route-state values against KTX/Frogbot source and `dm3.bot` route edges:

```bash
python scripts/attribute_route_state_windows.py --output-json experiments/ktx_moveprobe/evidence/route-state-s6c-attribution.json --output-md experiments/ktx_moveprobe/evidence/route-state-s6c-attribution.md
```

S6c result: `path_state=32768` is `WATER_PATH`, not `STUCK_PATH`. The repeated `/ bro` `water.LG` pattern groups `3` low-speed windows around linked/goal marker `59`, with `.bot` edge `276->59 idx=[0]` in the worst windows, `blocked=0`, sampled command near `824`, and low native `dir_speed`. The next step is water-path/swim-intent diagnosis, not another command mode.

S6d extends the same command log with the `water=` suffix and updates the attribution helper to summarize waterlevel, watertype, player water flags, swim arrow, emitted upmove, velocity, and raw `dir_move` in the same low-speed windows:

```bash
python scripts/attribute_route_state_windows.py --stage s6d-water-path --diagnosis-json artifacts/lab-runs/<run-id>/s6d-water-path-diagnosis.json --output-json experiments/ktx_moveprobe/evidence/route-state-s6d-water-attribution.json --output-md experiments/ktx_moveprobe/evidence/route-state-s6d-water-attribution.md
```

S6e changes only mode `7` vertical command handling: when `waterlevel > 1`, it preserves the native pre-probe `direction[2]`; otherwise mode `7` still uses `k_fb_moveprobe_upmove` and keeps its horizontal aim-independent/no-backpedal/bounded behavior.

```bash
python scripts/attribute_route_state_windows.py --stage s6e-water-edge-upmove --diagnosis-json artifacts/lab-runs/<run-id>/s6e-water-edge-diagnosis.json --output-json experiments/ktx_moveprobe/evidence/route-state-s6e-water-upmove-attribution.json --output-md experiments/ktx_moveprobe/evidence/route-state-s6e-water-upmove-attribution.md
```

S6e result: a short `dm3` rerun did not remove the repeated `water.LG` / `276->59` WATER_PATH low-speed pattern; it shifted to `/ goldenboy`, and both bots had worse low-speed ratios. Stop upmove tuning here and inspect `.bot` route-edge geometry around `276->59` / marker `59` before adding another controller change.

S6f inspects the static `.bot` route-edge geometry and S6 attribution samples without changing KTX:

```bash
python scripts/inspect_route_edge_geometry.py --stage s6f-route-edge-geometry --edge 276:59 --marker 59 --output-json experiments/ktx_moveprobe/evidence/route-edge-s6f-geometry.json --output-md experiments/ktx_moveprobe/evidence/route-edge-s6f-geometry.md
```

S6f result: `276->59` and `59->276` are explicit path-index-0 edges, marker `59` has static origin `[1329.0, -378.0, -24.0]`, but marker `276` has no static `CreateMarker` origin. The committed S6d/S6e attribution evidence contains `30` unique focus-edge samples with `WATER_PATH`, `blocked=0`, and `86.7%` low native `dir_speed`, but no precise static route-coordinate fix is justified from `dm3.bot` alone. The next step should move toward S7 exact-player movement signatures, not another water-edge command tweak.

## Rollback

This is an experiment patch. After running it against `servexeri`, restore the deployed `qwprogs.so` from the backup made before copying the patched build, and reset or reverse-apply the source checkout patch.
