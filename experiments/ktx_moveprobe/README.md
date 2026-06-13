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

Patch artifacts are pinned to LF line endings by the repo `.gitattributes`. Keep
them that way: CRLF-normalized patch files can fail `git apply` against the
pinned KTX checkout even when their textual diff appears unchanged.

The patch adds `k_fb_moveprobe_mode` handling inside `BotSetCommand()` after the prewar-freeze guard and immediately before button assembly and `trap_SetBotCMD(...)`.

## Per-slot cvars patch (LD-F1 #95)

`frogbot-moveprobe-perslot.patch` is a second patch in this lineage. It applies to a
pristine KTX `08807da` checkout and includes the earlier lab movement-probe
instrumentation plus the per-slot and dashboard-practice additions. Base file
checksums for that clean checkout:

```text
md5 src/bot_movement.c  105e3beeb86b7b351a0c2b3bb870e109
md5 src/bot_botgoals.c  bcca093dc21ef7387036d5e50d7b02a2
```

The patch itself is LF per the repo `.gitattributes` rule. Apply with:

```bash
cd ~/nquakesv/build/ktx
git apply /path/to/frogbot-moveprobe-perslot.patch
./build_cmake.sh linux-amd64
```

What it adds:

- **Per-slot cvar convention** `k_fb_moveprobe_<param>_s<N>` for `mode`, `replay_file`,
  `fixed_goal`, `spawn_origin`, and `spawn_velocity`, where `N` is the bot's edict/client number — the same
  `ed` printed in `FBMOVEPROBE_CMD` rows, so telemetry joins to assignments directly.
  One helper pair (`BotMoveProbeCvarStringForBot` / `BotMoveProbeCvarIntForBot`) builds
  the suffixed name, reads it via `trap_cvar_string`, and falls back to the global cvar
  when the per-slot cvar is unset or empty. With no per-slot cvars set, behavior is
  unchanged (additive guarantee).
- **Per-slot replay stores.** Replay `.cmds` files now load into a bounded cache of
  `MOVEPROBE_REPLAY_MAX_FILES` (4) stores keyed by filename, so two bots can run two
  different route files on the same map at the same time. A store is reclaimed only when
  no client slot currently resolves to it.
- **Loud failure** (lab precedent #77): a malformed per-slot value — non-integer `mode`
  or `fixed_goal`, per-slot `fixed_goal` naming a marker absent on the map, missing or
  unloadable per-slot `replay_file`, bad `spawn_origin` or `spawn_velocity` triplet — prints (throttled to
  one row per slot per ~2 s, not gated on command logging):

  ```text
  FBMOVEPROBE_PERSLOT_ERROR time=30.125 ed=4 name=/ bro param=replay_file value=nonexistent.cmds reason=replay_load_failed
  ```

  and the bot is **held at spawn** (zeroed movement command) while the condition
  persists. Global-fallback values keep their legacy silent behavior exactly.
  The one-shot spawn-snap latch re-arms whenever the resolved `spawn_origin`
  assignment changes with a per-slot cvar involved on either side of the change
  (#95 review P2), so a per-slot value edited mid-session — including a newly
  malformed one — is re-parsed and re-validated instead of silently keeping the
  previous snapped state. Pure-global configs never take that branch, so their
  legacy latch behavior is unchanged.
- **Assignment instrumentation** (consumed by LD-F3): when command logging is on, each
  bot prints one `FBMOVEPROBE_ASSIGN` row whenever its resolved assignment changes:

  ```text
  FBMOVEPROBE_ASSIGN time=12.250 ed=3 name=/ goldenboy mode=21 mode_src=slot replay_file=dm3_sng_to_rl.cmds replay_src=slot fixed_goal=42 goal_src=global spawn_origin=100.0,200.0,-24.0 spawn_src=slot
  ```

  `*_src` says whether the value came from the per-slot (`slot`) or global (`global`)
  cvar; unset string values print `-`; whitespace inside values is comma-folded. The
  runner parses these rows (plus error rows) into `moveprobe-assignments.json/md`, and
  `scripts/moveprobe_parse.py` is the shared regex home (`parse_moveprobe_assign_logs`,
  `parse_moveprobe_perslot_error_logs`).

Driving a two-bot/two-route session from the runner:

```bash
python scripts/run_frobodm2_lab.py --map dm3 --duration 45 --bot-count 2 \
  --moveprobe-mode 21 --replay-cmds tricks/dm3/dm3_sng_to_rl.cmds \
  --extra-replay-cmds tricks/dm3/dm3_hilljump.cmds \
  --ktx-extra-cvars "k_fb_moveprobe_replay_file_s4 bots/replay/dm3_hilljump.cmds;k_fb_moveprobe_spawn_origin_s4 1234 -567 24" \
  --moveprobe-log-commands
```

(`--extra-replay-cmds` uploads additional route files without touching the global
`k_fb_moveprobe_replay_file`; per-slot values use the same `bots/replay/<name>` form.)

Validation so far: `git apply --check` against a fresh `08807da` KTX worktree,
compile-verified on servexeri with `./build_cmake.sh linux-amd64`, and deployed as
`~/nquakesv/ktx/qwprogs-mode24-20260612T101218Z.so` on 2026-06-12. Live dashboard
proof started `ztricks` through the bridge (`dash_20260612T101502Z`) and emitted
mode-24 command rows with zero movement/buttons while the seeded practice bots waited
for per-slot route assignment.

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

S7j mode `8` rows append transition-probe state:

```text
FBMOVEPROBE_CMD time=12.500 ed=3 name=/ goldenboy mode=8 msec=12 angles=0.0,90.0,0.0 move=0,1031,0 buttons=2 impulse=7 diag=270.0,90.0,180.0,0 route=12,10,42,14,32768,128,0,0.050 water=1,-3,528,0,0.0,25.5,-4.0,80.0,0.100,0.200,0.300 probe=1,0,0.125,999.000,1.250
```

QWD mode `9` rows append SNG waypoint/controller state:

```text
FBMOVEPROBE_CMD time=12.500 ed=3 name=/ goldenboy mode=9 msec=12 angles=0.0,90.0,0.0 move=320,508,0 buttons=2 impulse=7 diag=270.0,90.0,180.0,0 route=12,10,42,14,32768,128,0,0.050 water=1,-3,528,0,0.0,25.5,-4.0,80.0,0.100,0.200,0.300 probe=0,0,999.000,999.000,1.000 qwd=1,3,14,72.250,4,0,1.375
```

Mode `23` ztricks terminal-carve rows append release-state diagnostics:

```text
FBMOVEPROBE_CMD time=12.500 ed=3 name=/ goldenboy mode=23 msec=13 angles=0.0,-19.0,0.0 move=320,320,0 buttons=2 impulse=0 diag=0.0,-19.0,19.0,0 route=8,7,42,8,32768,128,0,1.000 water=0,0,528,0,0.0,475.0,-94.0,0.0,1.000,0.000,0.000 probe=0,0,999.000,999.000,1.000 qwd=0,0,0,999999.000,0,0,0.000 replay=0,0,0,0,0.000,0.000,0.000,0.000,0.000,0.000 origin=-3360.800,3777.200,-488.000 zjump=2,12.800,475.200,-11.3,-3.0,8.3,-7.7,1,1
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
| `8` | S7j probe: start from mode `7`, then scale horizontal command budget only during takeoff/recent-air/recent-landing transition windows. This is a falsifiable probe against S7i guardrails, not accepted controller behavior. |
| `9` | QWD SNG probe: activate near the first `dm3_sng_shortcut.qwd` control point, advance through a bounded QWD waypoint string, and project waypoint attraction plus QWD-style sidemove into preserved combat view yaw. This is not accepted controller behavior. |
| `10` | Open-loop replay: snap to frame 0 of a `.cmds` file and emit the exact recorded view angles, movement, and jump buttons on the replay clock. |
| `11` | Closed-loop replay steering: use the replay clock/path but re-aim from the bot origin toward a lookahead human frame. Diagnostic only; it discards the recorded mouse. |
| `12` | Corrective replay: emit the recorded command stream, with default-off command-space path blend, ground realign, autojump, and bounded yaw correction probes for live/QWD divergence. |
| `21` | Generative replay-route follow: use replay frames as waypoints, then apply the mode-20 style bunnyhop weave toward the path. |
| `22` | Human-faithful actuation probe: reuse mode-21 navigation but drive a smooth simulated yaw plus held strafe key. |
| `23` | Hybrid Frogbot route + bunnyhop weave. When the ztricks terminal-carve cvars are unset it behaves as before; when the route sets target/lip/release cvars it temporarily emits the configured fwd+side terminal carve and jump release rule near the lip. |
| `24` | Dashboard practice idle: apply spawn-snap/ASSIGN instrumentation, then emit no movement, jump, or firing until a per-slot route assignment overrides the global mode. |
| `25` | Human-mouse speed catch-up probe: replay the recorded mouse/timeline, but when live speed trails the human frame by `k_fb_moveprobe_s25_gap` above `k_fb_moveprobe_s25_min_speed`, project a velocity-relative accel wishdir into the recorded view basis. Experimental; current ztricks evidence improves peak/top-end speed but does not yet beat sustained human speed. |

Mode `2`, `3`, `4`, `5`, `6`, `7`, `8`, and `9` cvars:

| Cvar | Default in runner | Meaning |
|---|---:|---|
| `k_fb_moveprobe_yaw` | `0` | Bot view yaw used for fixed-command mode `2`. |
| `k_fb_moveprobe_forwardmove` | `800` | Forward command sent to `trap_SetBotCMD` in modes `2`, `3`, and `4`; route-intent scale for modes `5`, `6`, `7`, and `8`; waypoint-attraction component for mode `9` when explicitly set. |
| `k_fb_moveprobe_sidemove` | `0` | Side command sent to `trap_SetBotCMD` in modes `2` and `3`; mode `4` treats `0` as a default alternating `+/-400`; modes `5`, `6`, `7`, and `8` use the value as a route-relative strafe component; mode `9` uses it as the QWD-style side-dominant component. |
| `k_fb_moveprobe_upmove` | `0` | Up command sent to `trap_SetBotCMD` in modes `2`, `3`, `4`, `5`, `6`, `7`, `8`, and `9`. |
| `k_fb_moveprobe_log_commands` | `0` | When `1`, print sampled final command rows before `trap_SetBotCMD`. |
| `k_fb_moveprobe_log_interval` | `0.25` | Minimum seconds between command log samples per bot. Use `0` for every command. |
| `k_fb_moveprobe_transition_scale` | `1.25` | Mode `8` multiplier for desired horizontal command budget while the transition probe is active. |
| `k_fb_moveprobe_transition_window` | `0.4` | Mode `8` takeoff/recent-air/recent-landing window in seconds. |
| `k_fb_moveprobe_qwd_waypoints` | empty | Mode `9` semicolon-separated QWD control points as `x,y,z` triples. |
| `k_fb_moveprobe_qwd_point_radius` | `96` | Mode `9` radius for advancing to the next QWD control point. |
| `k_fb_moveprobe_qwd_start_radius` | `192` | Mode `9` radius around control point `0` required before the QWD probe activates. |

Mode `25` cvars:

Replay-backed modes (`10`, `11`, `12`, `21`, `22`, and `25`) also accept two
benchmark-safety cvars. `k_fb_moveprobe_replay_stale_gap` defaults to `1.0`
second and is clamped to `0.1..120.0`; set it high enough to prevent an in-run
command gap from silently re-snapping the bot to frame 0. `k_fb_moveprobe_replay_one_shot`
defaults off; set it to `1` for one-shot benchmarks such as
`getandmaintainspeed.qwd` so death/respawn marks the attempt done instead of
mixing several attempts into one MVD. The replay clock also tolerates tiny
backward jitter up to `0.25s`; larger backward jumps still reset as map/session
clock resets.

Replay-backed modes can opt into recorded command cadence with
`k_fb_moveprobe_replay_use_recorded_msec 1`. When enabled, the replay frame's
recorded `msec` replaces the current bot-think `cmd_msec` immediately before
`trap_SetBotCMD`. This is default-off because most lab runs should keep the
server's native command cadence, but tight demos such as `dm3_ring_to_mega` can
use it to test whether pass/fail variance comes from cadence drift rather than
route steering.

Replay-backed modes can also opt into reference interpolation with
`k_fb_moveprobe_replay_interpolate 1`. The replay clock still selects the same
current frame, and forward/side/up/buttons remain discrete from that frame, but
the QWD reference origin, velocity, and view angles are linearly interpolated
from the previous frame to the current clock position. This follows Nexus's
"interpolate between datapoints" guidance without smearing strafe/jump key
state, and is intended for tight routes where live server frame timing lands
between QWD samples.

Replay-backed modes also have two diagnostic/default-off start-clock controls.
`k_fb_moveprobe_replay_step_cursor` advances the replay cursor by a fixed
number of frames per emitted bot command instead of wall-clock time; this is a
diagnostic for cadence drift and was rejected for `dm3_ring_to_mega` because it
made the route consistently short. `k_fb_moveprobe_replay_start_resnap 1`
repairs early activation warps by snapping the bot back to the expected replay
frame when horizontal divergence exceeds
`k_fb_moveprobe_replay_start_resnap_dist` before
`k_fb_moveprobe_replay_start_resnap_cursor`. Keep it off for normal evidence
runs unless a route has proven frame-0/frame-1 start corruption.

Replay-backed modes can optionally preserve the QWD attack bit for rocket-jump
routes. Set `k_fb_moveprobe_replay_attack 1` to translate recorded `buttons&1`
frames into bot firing, and set `k_fb_moveprobe_replay_attack_impulse` to the
weapon impulse to request while firing (`7` by default for RL). This is
default-off so pure movement routes such as `dm3_sng_to_rl` keep their previous
behavior, while routes such as `dm3_mega_to_rl`, `dm3_rl_to_bridge`, and
`dm3_rl_to_ya` can reproduce their recorded attack+jump windows instead of
trying to fake rocket-jump speed with strafe-only commands.
When enabled, the replay asks for the configured weapon throughout the route and
only raises `+attack` on recorded attack frames; that avoids losing the rocket
jump to a same-frame weapon-switch delay.
Rocket-jump demos recorded in KTPro Standby may also require the lab-only
loadout grant: set `k_fb_moveprobe_replay_attack_grant 1` to give the bot RL
and rockets at replay activation, and optionally set
`k_fb_moveprobe_replay_attack_rockets` (default fallback `50`) when the route
needs a specific ammo floor. The grant is gated by both
`k_fb_moveprobe_replay_attack` and `k_fb_moveprobe_replay_attack_grant`, so
pure movement replays cannot receive weapons accidentally.

Corrective replay mode `12` also has a default-off early-landing guard:
`k_fb_moveprobe_corr_autojump 1` presses jump only when the bot is unexpectedly
on ground and the recorded QWD frame is not already jumping. This is for cases
where a small live/QWD offset makes the bot touch a ledge the human barely
missed; without a fresh jump press, exact replay can bleed all launch speed
through ground friction.

Mode `12` can also apply a default-off command-space path blend before the older
yaw correction: set `k_fb_moveprobe_corr_cmd_blend` to a small value such as
`0.02`-`0.05` to blend the recorded forward/side wish direction toward the
current QWD origin while preserving the recorded mouse/view angles. Optional
knobs are `k_fb_moveprobe_corr_cmd_deadband` (default fallback `8` qu),
`k_fb_moveprobe_corr_cmd_after` (default fallback `0` replay cursor), and
`k_fb_moveprobe_corr_cmd_move` (default fallback: preserve the recorded
horizontal command magnitude). This exists for narrow routes such as
`dm3_ring_to_mega`, where a small live offset can clip a slot even though the
human mouse pattern and raw speed are nearly correct.

Mode `12` can also use recorded idle windows to repair accumulated horizontal
offset before the next route leg. Set `k_fb_moveprobe_corr_ground_realign 1` to
walk toward the current QWD origin only when the live bot is grounded, the QWD
frame has zero forward/side/up movement, and the QWD frame is not firing or
jumping. Optional knobs: `k_fb_moveprobe_corr_ground_realign_deadband` (default
fallback `12` qu), `k_fb_moveprobe_corr_ground_realign_move` (default fallback
`320`), and `k_fb_moveprobe_corr_ground_realign_after` (default fallback `0`
replay cursor). This exists for routes such as `dm3_rl_to_bridge`, where the
human pauses on the ledge but the bot can arrive about `40` qu off-line after a
rocket boost; use the `after` cursor to keep realign inactive before earlier
boost/landing phases where a few units of pre-launch shift can miss the floor.

| Cvar | Default in KTX | Meaning |
|---|---:|---|
| `k_fb_moveprobe_s25_min_speed` | `320` | Minimum live horizontal speed before the catch-up branch can replace the recorded movement vector. |
| `k_fb_moveprobe_s25_gap` | `32` | Required human-frame speed lead, in qu/s, before catch-up engages. |
| `k_fb_moveprobe_s25_numerator` | `8` | Target `v dot wishdir` numerator for the velocity-relative air-strafe wishdir. |
| `k_fb_moveprobe_s25_bootstrap_deg` | `25` | Fallback wishdir angle when speed is too low for the numerator formula. |
| `k_fb_moveprobe_s25_move` | `400` | Local movement magnitude used when projecting the catch-up wishdir into the recorded view basis. |
| `k_fb_moveprobe_s25_flip` | `0` | Diagnostic sign inversion for the catch-up wishdir. `1` was worse on the first ztricks run. |
| `k_fb_moveprobe_s25_path_div` | `0` | Default-off path leash. When >0 and divergence exceeds this horizontal distance, the catch-up branch can also engage for path correction. |
| `k_fb_moveprobe_s25_path_blend` | `0` | Default-off path blend amount, clamped 0..1, that mixes the velocity-relative wishdir toward the human frame origin when the path leash is active. Early live tests with `0.25` and `0.05` were worse. |
| `k_fb_moveprobe_s25_velsign` | `0` | Default-off diagnostic that chooses the strafe side whose wishdir is closer to the human velocity vector. First live test was worse, so leave disabled unless explicitly probing direction. |
| `k_fb_moveprobe_s25_phase_start` | `0` | Default-off replay cursor where phase recovery can engage even below the global speed floor. Used to test the post-burst sustain collapse in `getandmaintainspeed.qwd`. |
| `k_fb_moveprobe_s25_phase_target` | `850` | Human-frame speed required for phase recovery once `phase_start` is reached. |
| `k_fb_moveprobe_s25_phase_min_speed` | `0` | Live speed floor for phase recovery. |
| `k_fb_moveprobe_s25_phase_move` | same as `s25_move` | Movement magnitude used only while phase recovery is active. |
| `k_fb_moveprobe_s25_phase_numerator` | same as `s25_numerator` | Velocity-relative numerator used only while phase recovery is active. |
| `k_fb_moveprobe_s25_phase_human_cmd` | `0` | Default-off phase probe that keeps the recorded mouse and human side-input sign, but uses `phase_move` as the side magnitude instead of projecting a velocity-relative wishdir. This produced the best current `getandmaintainspeed.qwd` live result at `phase_start 1500`, `phase_target 850`, `phase_move 950`, but still does not beat the human's sustained `>900` time. |
| `k_fb_moveprobe_s25_phase2_start` | `0` | Default-off second phase cursor that can switch phase recovery to `phase2_move`. The first late-boost test after cursor `2044` was worse, so leave disabled unless explicitly probing late sustain. |
| `k_fb_moveprobe_s25_phase2_move` | same as `phase_move` | Movement magnitude used after `phase2_start` when enabled. |
| `k_fb_moveprobe_s25_phase_jump` | `0` | Default-off phase jump-hold probe. The first live test was much worse than replayed human jump timing, so leave disabled unless explicitly isolating bunnyhop cadence. |
| `k_fb_moveprobe_s25_phase_gap_gain` | `0` | Default-off adaptive phase probe that adds `(human_speed - live_speed) * gain` to the phase movement magnitude when the bot is behind. A conservative `0.25` capped at `960` was worse than the fixed `950` profile. |
| `k_fb_moveprobe_s25_phase_move_max` | `0` | Optional cap for `phase_gap_gain`; `0` means no cap. |
| `k_fb_moveprobe_s25_phase_yaw_offset` | `0` | Default-off phase yaw-bias probe, clamped to `-20..20` degrees. First `+5` and `-5` live tests were both worse than the unshifted human mouse. |
| `k_fb_moveprobe_s25_phase_human_scale` | `0` | Default-off phase probe that scales the exact recorded forward/side command values instead of replacing side input with a fixed magnitude. `2.375` (`400 -> 950`) was worse than fixed side magnitude because it preserved too many low/zero command frames for this live bot. |
| `k_fb_moveprobe_s25_phase_lane_nudge` | `0` | Default-off phase-human-command nudge toward the replay origin when the bot is outside `phase_lane_deadband`. It preserves the human mouse and side-command backbone, then adds a small projected forward/side correction capped by `phase_lane_max`. First `dm3_ring_to_mega` tests were mixed/worse, so leave disabled unless explicitly probing final-lane contact drift. |
| `k_fb_moveprobe_s25_phase_lane_deadband` | `6` fallback | Horizontal divergence deadband, in qu, before `phase_lane_nudge` contributes. |
| `k_fb_moveprobe_s25_phase_lane_max` | `96` fallback | Maximum extra movement command contribution from `phase_lane_nudge`. |

Mode `25` accepted operational baseline:

- Run: `gm25_clocktol1500m950_0420`.
- Evidence snapshot:
  `experiments/ktx_moveprobe/evidence/getandmaintainspeed-accepted-baseline-20260613.md`.
- Deployed binary:
  `~/nquakesv/ktx/qwprogs-s25clocktol-20260612T2207Z.so`, SHA-256
  `83b0b75297cd81a5b0c29d1e747eec434a703ca00dd430152689eca3176463fe`.
- User verdict: visually/operationally more than good enough for the current
  baseline.
- Strict scorer verdict: still `FAIL` because the human reference sustains
  `>900` qu/s much longer. Treat the run as the frozen accepted baseline, not
  as proof that mode `25` beats `getandmaintainspeed.qwd`.

Mode `3` ignores `k_fb_moveprobe_yaw`; it computes yaw from `self->fb.dir_move_` when Frogbot has a non-zero horizontal route direction. If that route vector is empty for a frame, mode `3` leaves the already-computed stock command intact for that frame.

Mode `4` also ignores `k_fb_moveprobe_yaw`. It uses the same route-derived yaw as mode `3`, but alternates the sign of `sidemove` about five times per second, offset by bot slot. This is only a bounded S3a movement-literacy probe.

Mode `5` preserves `self->fb.desired_angle` instead of setting route yaw. It builds a desired route-relative movement vector, optionally adds the alternating strafe component, then projects that world vector into local `forwardmove`/`sidemove` commands using the preserved combat yaw. Exact `forwardmove=800` coverage is not expected in mode `5`; use horizontal-command coverage instead.

Mode `6` uses the same aim-independent projection as mode `5`, then clamps negative local `forwardmove` to `0` and transfers the removed magnitude into local `sidemove`. This keeps the bot from deliberately backpedaling when route intent is behind its preserved view angle.

Mode `7` uses the same no-backpedal correction as mode `6`, then normalizes local horizontal command magnitude back down to the intended route/strafe magnitude. With the usual `forwardmove=800 sidemove=200`, the expected cap is about `825`.

Mode `8` uses the same aim-independent, no-backpedal, bounded behavior as mode `7`, but scales the desired horizontal command magnitude by `k_fb_moveprobe_transition_scale` only when the pre-probe bot logic is jumping from ground, recently left ground, or recently landed inside `k_fb_moveprobe_transition_window`. Outside those windows, mode `8` should match mode `7` horizontal behavior. S7j rejects the corrected probe under the S7i stop conditions because pre-air, airborne-proxy, post-air, and non-airborne buckets regressed in the combined fixed runs, so do not treat it as accepted controller behavior.

Mode `9` is a temporary QWD SNG hybrid probe. It reads up to `16` QWD control points, only activates on `dm3` near the first point, advances points by radius, and combines waypoint attraction with the side-dominant QWD command profile. It preserves combat view yaw and existing route/water/probe diagnostics. The first runtime run `20260606T221429Z` was inconclusive: it activated for `1.12` seconds and advanced `2` points, but the design gate requires at least `4` before expanding to other DM3 QWD moves. Setup-repair run `20260606T231007Z` widened only the start radius to `320` qu and advanced `4` points inside the MVD window, but it is rejected by slow-success guardrails, so this still is not accepted controller behavior.

The S3e diagnostic suffix is shaped as `diag=<route_yaw>,<view_yaw>,<yaw_delta>,<backward>`. `backward=1` means the emitted local `forwardmove` is negative. `yaw_delta` and `view_yaw` are interpretable for aim-independent modes `5`, `6`, and `7`; route-yaw modes `3` and `4` overwrite view yaw from the route, so their deltas are structural noise.

The S6b diagnostic suffix is shaped as `route=<linked_marker>,<touch_marker>,<goal_ed>,<goal_marker>,<path_state>,<bot_state>,<blocked>,<dir_speed>`. Marker ids are Frogbot marker indexes plus one, or `-1` when absent. `goal_ed` is the current Quake edict number from `self->s.v.goalentity`; `goal_marker` is that entity's marker when available. `blocked=1` means either the `STUCK_PATH` bit is present in `path_state` or `fb.obstruction_normal` is currently non-zero. This is trace context only, not a new movement mode.

The S6d diagnostic suffix is shaped as `water=<waterlevel>,<watertype>,<flags>,<swim_arrow>,<emitted_upmove>,<velocity_x>,<velocity_y>,<velocity_z>,<dir_move_x>,<dir_move_y>,<dir_move_z>`. It exists to inspect whether `WATER_PATH` low-speed windows are shallow-water edge handling, active swim intent, missing vertical/upmove emission, route-edge geometry, or still unknown. `swim_arrow` uses the Frogbot `UP=16` / `DOWN=32` constants. `dir_move_*` is the raw Frogbot route movement vector sampled at command time.

The S7j diagnostic suffix is shaped as `probe=<active>,<on_ground>,<since_ground>,<since_air>,<scale>`. It exists to verify that mode `8` only applies the transition scale in the intended takeoff/air-transition windows and to support post-run stop-condition checks. Transition timing uses resettable file-scope per-slot state with explicit "has ground/air time" flags so map/session gaps and time-zero samples do not inherit stale timing, while normal mode-8 frames still preserve recent-ground/recent-air history across command samples.

The QWD diagnostic suffix is shaped as `qwd=<active>,<control_point_index>,<control_point_count>,<distance_qu>,<advanced_control_points>,<complete>,<active_seconds>`. It exists to prove whether the temporary QWD-derived controller activated, which target it was chasing, how far it got, and whether a future success claim is just waypoint-only slow/stuck motion.

The ztricks terminal-carve suffix is shaped as `zjump=<phase>,<d_lip>,<vh>,<vel_yaw>,<target_yaw>,<target_err>,<yaw_lead>,<armed>,<release_rule>`. It exists to prove whether the mode-23 Distance attempt reaches the human release formula before scoring landing. The primitive is default-off and only engages when route/control metadata sets `k_fb_moveprobe_s23_launch_target_{x,y,z}`. The committed ztricks route also sets `k_fb_moveprobe_s23_lip_x`, optional `k_fb_moveprobe_s23_lip_y`, release speed floors, `carve_d`, `carve_angle`, `carve_side`, `release_lip`, yaw-lead bounds, target-error bounds, `spawn_velocity`, and optional human-reference curve knobs (`k_fb_moveprobe_s23_refcurve*`). When `lip_y` is non-zero, KTX computes `d_lip` as projected progress along the configured lip-to-target lane instead of raw `lip_x - origin.x`; this lets `spawn_left_speedjump` use the same Nexus curve timing on a diagonal floor route. `k_fb_moveprobe_s23_refcurve_yaw_offset` rotates the human reference curve onto safe-floor calibration lanes such as `spawn_left_speedjump`; leave both `lip_y` and yaw offset at `0` for the original Distance lane. The reference curve can steer with fwd+side inside the terminal lane corridor; formula release still requires `armed=1`, and the fallback unarmed jump is limited to the release-lip window so it cannot spend the attempt at terminal-lane entry.

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
python scripts/run_bot_lab.py --map dm3 --duration 25 --bot-count 2 --bot-spacing 6 --moveprobe-mode 8 --moveprobe-sidemove 200 --moveprobe-transition-scale 1.25 --moveprobe-transition-window 0.4 --moveprobe-log-commands
python scripts/run_bot_lab.py --map dm3 --duration 45 --bot-count 2 --bot-spacing 6 --moveprobe-mode 9 --moveprobe-forwardmove 320 --moveprobe-sidemove 508 --moveprobe-qwd-waypoints "<x,y,z;...>" --moveprobe-qwd-point-radius 96 --moveprobe-qwd-start-radius 192 --moveprobe-log-commands --moveprobe-log-interval 0.1
```

Each run records the mode and command values in `run.env`, `lab.cfg`, and `run-summary.md`.

For ztricks Distance specifically, use the batch harness when tuning approach
and release parameters:

```bash
python scripts/build_ztricks_reference_trace.py
python scripts/run_ztricks_batch.py --attempts 6 --attempt-seconds 8 --refcurve
python scripts/score_ztricks_batch.py --run-id <run-id>
```

`run_ztricks_batch.py` keeps one temporary `ztricks` server and one MVD
recording alive, then cycles clean single-bot attempts by clearing spawn-snap
state, `removeall`, setting the route's mode-23 cvars, restoring the route
spawn origin/velocity, and adding one bot. Pass `--route spawn_left_speedjump`
to run the safe-floor drill from the real spawn. `score_ztricks_batch.py`
segments the resulting `moveprobe-commands.json` into attempts and scores by
route profile: Distance still uses the successful human `getspeed.qwd` release
formula before landing distance, while `spawn_left_speedjump` reports
start-to-peak horizontal speed gain against the `495.5 qu/s` human target.

Interpolation contract (Nexus note, 2026-06-12): do not compare only discrete
sample rows. `score_ztricks_batch.py` estimates bot release/landing by
projecting the target point onto adjacent sampled segments, and estimates the
physical lip event by linearly crossing `x=-3348`. The generated
`ztricks-reference-trace.json` keeps those conservative event estimates for
evidence, plus a local-quadratic controller guidance curve over the successful
human terminal sweep (angles are unwrapped before interpolation). Do not spline
across teleports or attempt boundaries.

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
| `20260606T163907Z`, `20260606T164610Z` | `8` | Corrected S7j air-transition probes on `dm3`; combined evidence rejects mode `8` under S7i stop conditions because all-segment and route-context gains were outweighed by pre-air, airborne-proxy, post-air, and non-airborne regressions. |
| `20260606T221429Z` | `9` | QWD SNG hybrid probe on `dm3`; QWD control activated for `1.12` seconds and advanced `2` points, but the required advancement gate is `4`, so the result is inconclusive. |
| `20260606T231007Z` | `9` | QWD SNG setup repair on `dm3`; widened start radius to `320` qu, advanced `4` points inside the MVD window, but rejected by slow-success guardrails (`/ bro` low-speed `42.9%`, stationary `25.3%`). |
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

S3g interpretation: mode `7` passes both routed maps while keeping sampled horizontal command magnitude near the intended `824.6` cap. This is a better S3 candidate than mode `6`, but the next step should anchor the gate against human-demo movement before more command tuning. S7c regenerated the committed S3g summary from these existing artifacts so `jump_cadence_per_min` is available for bot-vs-human cadence comparison.

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

Attribution joins command rows by diagnosis `user_id` to command-row `ed` when those IDs are present. Netname matching is only a fallback for older artifacts without IDs, so duplicate bot names cannot mix another player's route or water samples into the current window.

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

S6f result: `276->59` and `59->276` are explicit path-index-0 edges, marker `59` has static origin `[1329.0, -378.0, -24.0]`, but marker `276` has no static `CreateMarker` origin. The committed S6d/S6e attribution evidence contains `30` unique focus-edge samples with `WATER_PATH`, `blocked=0`, and `86.7%` low native `dir_speed`, but no precise static route-coordinate fix is justified from `dm3.bot` alone. S7a/S7b moved this branch into exact-player movement signatures and repeated references, S7c made cadence bot-comparable from existing S3g artifacts, and S7d kept cadence diagnostic after normalization. The next step is S7e cadence evidence broadening or airborne-proxy segmentation, not another water-edge command tweak.

## Rollback

This is an experiment patch. After running it against `servexeri`, restore the deployed `qwprogs.so` from the backup made before copying the patched build, and reset or reverse-apply the source checkout patch.
