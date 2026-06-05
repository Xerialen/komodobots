# KTX Frogbot Movement Probe

Status: S2 experiment scaffold.

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

Those rows are deliberately console-oriented, temporary probe output. They exist to compare stock, forced-jump, and fixed-command runs before building a real movement controller.

Modes:

| Mode | Meaning |
|---:|---|
| `0` | Off. Stock Frogbot command emission. |
| `1` | Force the jump button while preserving existing Frogbot movement direction and combat. |
| `2` | Replace the final movement command with fixed yaw/forward/sidemove/upmove values and force jump while leaving firing and weapon selection intact. |
| `3` | Set yaw from Frogbot route intent, send forward/sidemove/upmove command values, and force jump. This is a movement probe, not a combat-aim-preserving controller. |
| `4` | S3a probe: set yaw from Frogbot route intent, emit forward plus alternating side commands, and force jump. This is a bounded strafe/jump primitive, not a final bunnyjump controller. |
| `5` | S3d probe: preserve combat view yaw, project route/strafe intent into local forward/sidemove commands, and force jump. This tests aim-independent movement math, not a final controller. |

Mode `2`, `3`, `4`, and `5` cvars:

| Cvar | Default in runner | Meaning |
|---|---:|---|
| `k_fb_moveprobe_yaw` | `0` | Bot view yaw used for fixed-command mode `2`. |
| `k_fb_moveprobe_forwardmove` | `800` | Forward command sent to `trap_SetBotCMD` in modes `2`, `3`, and `4`; route-intent scale for mode `5`. |
| `k_fb_moveprobe_sidemove` | `0` | Side command sent to `trap_SetBotCMD` in modes `2` and `3`; mode `4` treats `0` as a default alternating `+/-400`; mode `5` uses the value as a route-relative strafe component. |
| `k_fb_moveprobe_upmove` | `0` | Up command sent to `trap_SetBotCMD` in modes `2`, `3`, `4`, and `5`. |
| `k_fb_moveprobe_log_commands` | `0` | When `1`, print sampled final command rows before `trap_SetBotCMD`. |
| `k_fb_moveprobe_log_interval` | `0.25` | Minimum seconds between command log samples per bot. Use `0` for every command. |

Mode `3` ignores `k_fb_moveprobe_yaw`; it computes yaw from `self->fb.dir_move_` when Frogbot has a non-zero horizontal route direction. If that route vector is empty for a frame, mode `3` leaves the already-computed stock command intact for that frame.

Mode `4` also ignores `k_fb_moveprobe_yaw`. It uses the same route-derived yaw as mode `3`, but alternates the sign of `sidemove` about five times per second, offset by bot slot. This is only a bounded S3a movement-literacy probe.

Mode `5` preserves `self->fb.desired_angle` instead of setting route yaw. It builds a desired route-relative movement vector, optionally adds the alternating strafe component, then projects that world vector into local `forwardmove`/`sidemove` commands using the preserved combat yaw. Exact `forwardmove=800` coverage is not expected in mode `5`; use horizontal-command coverage instead.

## Runner

The lab runner can now write the cvars into the generated KTX config:

```bash
python scripts/run_bot_lab.py --map frobodm2 --duration 40 --bot-count 2 --moveprobe-mode 1
python scripts/run_bot_lab.py --map frobodm2 --duration 40 --bot-count 2 --moveprobe-mode 2 --moveprobe-yaw 90
python scripts/run_bot_lab.py --map frobodm2 --duration 20 --bot-count 2 --moveprobe-mode 0 --moveprobe-log-commands
python scripts/run_bot_lab.py --map frobodm2 --duration 25 --bot-count 2 --bot-spacing 6 --moveprobe-mode 3 --moveprobe-log-commands
python scripts/run_bot_lab.py --map frobodm2 --duration 25 --bot-count 2 --bot-spacing 6 --moveprobe-mode 4 --moveprobe-log-commands
python scripts/run_bot_lab.py --map frobodm2 --duration 25 --bot-count 2 --bot-spacing 6 --moveprobe-mode 5 --moveprobe-sidemove 200 --moveprobe-log-commands
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

For mode `5`, use `--min-forward-ratio 0 --min-horizontal-ratio 0.8 --min-side-ratio 0.8`, because the preserved view yaw makes exact local `forwardmove=800` coverage the wrong signal.

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

## Rollback

This is an experiment patch. After running it against `servexeri`, restore the deployed `qwprogs.so` from the backup made before copying the patched build, and reset or reverse-apply the source checkout patch.
