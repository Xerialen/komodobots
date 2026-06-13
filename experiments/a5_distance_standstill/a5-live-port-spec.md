# A5 live port spec -- QWD/replay seam audit follow-up

Date: 2026-06-10

This is the live KTX port contract for the A5 ztricks Distance follow-up. It is written against the authoritative deployed source tree, `servexeri:~/nquakesv/build/ktx`, not the stale local KTX clone.

## Remote audit

- `servexeri:~/nquakesv/build/ktx` reports commit `08807da`.
- Dirty remote files at audit time: `src/bot_botgoals.c`, `src/bot_movement.c`, `src/marker_load.c`.
- Deployed module symlink at audit time: `~/nquakesv/ktx/qwprogs.so -> qwprogs-mode21.so`.
- Deployed `qwprogs.so` md5 observed earlier in the audit: `ae815cc7871a8cc241d9b4e6145b3403`.

## Replay seam fixes

Mode 10/12 exact replay is still the control evidence path, and `trap_SetBotCMD` is not the primary suspect. The live seam still needs two guardrails before new sim/live comparisons:

- On replay activation, set the entity model angles consistently with `fixangle`, or avoid `fixangle`. The overlay patch uses model-angle conversion (`angles[PITCH] = -desired_pitch / 3`) before `fixangle=1` so the first bot command is not silently rewritten by `PF2_SetBotCMD`.
- Add replay timing diagnostics. Keep live `cmd_msec` as the syscall value by default, but record source row `msec`, source cursor start time, live elapsed time, and first-active angle delta. Use `scripts/audit_replay_timing.py` for scored comparisons before any source-msec A/B.

## A5 mode 23 defaults

Adopt Claude's defaults, with the tightening from this audit:

- Use a fixed target point for ztricks Distance via `k_fb_moveprobe_s23_launch_target`.
- Re-snap to the standstill origin every attempt, including after the catcher teleport. The catcher injects a 300 qu/s throw, so treating the first snap as one-time state corrupts retry evidence.
- Include `release_vh` as a separate terminal-carve release gate.
- Keep the 3 s launch timeout constant unless a separately registered experiment changes it.
- Treat `FBMOVEPROBE_S23` transition rows as the attempt source of truth. The lab runner now parses these into `moveprobe-s23-events.json` and `.md`.

## Terminal carve behavior

When mode 23 launch instrumentation is armed:

1. Build speed exactly as before until the bot enters the terminal window.
2. Arm terminal carve only while grounded, near the lip (`d_lip <= carve_d`), and at speed (`vh >= carve_vh`).
3. While carving, hold a carve wishdir toward the target side of velocity and suppress jump.
4. Release by heading tolerance plus speed (`|herr| <= carve_tol` and `vh >= release_vh`) or by the lip backstop (`d_lip <= 8`).
5. On release, force the jump for that command frame and aim at the fixed target.
6. Log `attempt`, `snap`, `rearm`, `arm`, `release`, `timeout`, and `land_reset` events.

## Live smoke before scored A5 runs

- Inertness gate with all new cvars unset.
- Short ztricks smoke with `spawn_origin`, `launch_target`, `lip_x`, `carve_d`, `carve_angle`, `carve_vh`, `release_vh`, and `carve_tol` set.
- Confirm spawn snap and catcher teleport re-arm by `moveprobe-s23-events.json`.
- Confirm per-attempt standstill reset and zero-velocity snap after catcher throws.
- Run `scripts/audit_replay_timing.py` before any scored live replay comparison.

