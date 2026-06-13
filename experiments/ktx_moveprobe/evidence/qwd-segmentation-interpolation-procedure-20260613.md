# QWD Segmentation And Interpolation Procedure - 2026-06-13

Purpose: give a cold agent the complete procedure for turning a human POV QWD
into controller-ready movement evidence without needing to ask the bot to try
first.

This document is the companion to
`experiments/ktx_moveprobe/evidence/bunnyjump-code-replication-20260613.md`.
The bunnyjump guide says what worked: preserve the human mouse timeline, jump
timing, and side-switch timing. This guide explains how to extract those
signals from new QWD demos and how to fill sparse state data safely.

## Core Idea

A POV `.qwd` demo is a human reference trace, but it is not one clean table.

It contains two different kinds of evidence:

1. Exact command labels from `dem_cmd`.
2. Sparse world-state labels from network payloads such as `svc_playerinfo`.

The command labels are the strongest teaching signal. They give the per-frame
view angle result, movement commands, buttons, and frame duration. They are what
the player actually sent to the server.

The state labels are weaker but still valuable. They give sampled origin,
velocity, and movement state. They may be missing on many command frames, may
arrive at a different cadence, and may include discontinuities from teleports,
respawns, or parser-visible gaps.

Therefore the correct process is:

```text
extract exact commands
+ extract sparse state
+ time-align them
+ segment away discontinuities
+ interpolate only inside clean segments
+ emit a controller-ready trace
+ validate live against the trace
```

Do not ask the bot to discover this trace. The QWD already contains the human
choreography. The bot's job comes later: prove whether the controller can
execute that choreography inside live KTX physics.

## Concepts

### Command Frame

A command frame is one human input row from the QWD `dem_cmd` stream.

It contains:

- `msec`: how long the frame lasts.
- `view_angles`: the absolute pitch/yaw/roll after the player's mouse input.
- `forwardmove`, `sidemove`, `upmove`: the movement command values.
- `buttons`: jump and attack bits.
- `impulse`: weapon or special command intent.

For bunnyjumping, the most important fields are `view_angles.yaw`,
`sidemove`, `forwardmove`, `buttons`, and `msec`.

Important: QWD does not contain raw hardware mouse deltas. It contains the
post-input view-angle result. That is enough for our controller because KTX
consumes absolute command angles.

### State Sample

A state sample is a recovered player-state row from the QWD network stream.

It contains:

- origin: where the player was in the map.
- velocity: how fast and in what direction the player was moving.
- onground / movement flags: rough movement regime hints.
- time: when that state was observed in the demo.

State samples are not guaranteed to exist for every command frame. In the new
ztricks QWD set, there are often only about half as many state rows as command
rows. That is normal enough to handle, but unsafe to zip together.

### Zip Alignment

Zip alignment means pairing command row `N` with state row `N`.

This is unsafe whenever the command and state counts differ or their timestamps
drift. It can silently shift the whole trace, which creates false conclusions
about jump timing, speed, and mouse movement.

Use zip alignment only for old reproduction work where the sidecar proves it is
safe. New QWD work should default to time alignment.

### Time Alignment

Time alignment matches state samples to command frames by demo time, not by row
number.

This is the default safe seam:

1. Parse all command frames.
2. Parse all state samples.
3. Estimate the command/state time offset.
4. Match each state sample to the nearest command time.
5. Mark command rows without a direct state as missing-state rows.
6. Interpolate missing state only inside a clean segment.

The sidecar must record how many rows were matched, how many were interpolated,
and whether any residuals are too large.

### Segmentation

Segmentation means splitting one QWD into independent movement pieces before
interpolation or scoring.

Split the trace when any of these occur:

- Teleport or respawn.
- Impossible distance jump.
- Large time gap.
- Sudden state reset to a new room or start position.
- Long missing-state window.
- A new attempt starts after a failure.

For bunnyjump analysis, also record phase boundaries inside each clean segment:

- still or setup.
- grounded acceleration.
- jump edge.
- airborne sweep.
- landing or recovery.

Segmentation protects the evidence. Interpolating across a teleporter or a
respawn fabricates movement that never happened.

### Interpolation

Interpolation estimates the values between known data points.

Use it differently for different channels:

- Position and velocity: linear interpolation for evidence. Local quadratic or
  monotone spline guidance may be used for controller targets after validating
  that it does not overshoot.
- View yaw and derived angles: unwrap angles first, then interpolate. Without
  unwrapping, `359 -> 1` looks like a 358 degree spin instead of a 2 degree
  turn.
- Buttons: never smooth. Preserve discrete edges such as jump press and jump
  release.
- Movement commands: usually hold nearest command or preserve the exact command
  row. Do not blur `sidemove` sign switches into fake analog values unless the
  controller explicitly asks for a smoothed policy target.

Nexus's "interpolate between datapoints" means fill the missing state between
observed samples, not invent a new human input stream.

### Controller-Ready Trace

A controller-ready trace is the result of this procedure.

Each output row should have:

- time or cursor.
- `msec`.
- target origin and velocity.
- target yaw, yaw rate, and optionally pitch.
- command intent: forward, side, up.
- jump and attack button edges.
- segment id and phase.
- source flags: matched, interpolated, nearest, or missing.
- confidence flags for discontinuities and large gaps.

The bot can then use this as choreography:

- replay exact yaw timing,
- preserve jump edges,
- preserve side-switch timing,
- apply limited strength correction only inside explicit phase gates,
- compare live divergence back to the human trace.

## Procedure

### 1. Inventory The QWDs

Record:

- filename,
- SHA-256,
- map name / level name,
- command frame count,
- state sample count,
- command duration,
- command cadence,
- source path.

Use:

```powershell
python scripts\qwd_seam_validator.py `
  --demo path\to\demo.qwd `
  --output-json artifacts\qwd-study\demo-seam.json `
  --output-md artifacts\qwd-study\demo-seam.md
```

A usable QWD should have clean command parsing and plausible command values. A
QWD can still be useful for mouse/strafe/jump labels even when its state samples
are sparse.

### 2. Extract Exact Commands

Use:

```powershell
python tools\qwd_usercmd\qwd_usercmd.py `
  path\to\demo.qwd `
  --output artifacts\qwd-study\demo-usercmd.ndjson `
  --include-cmd-angles `
  --strict-plausibility
```

This produces the strongest action-label evidence. Preserve:

- yaw timeline,
- yaw-rate timeline,
- side sign and side magnitude,
- forward command usage,
- jump press and release frames,
- frame `msec`.

For bunnyjumping, do not discard the yaw shape. The mouse movement is part of
the movement code.

### 3. Extract State Samples

Use the QWD route probe for a compact state/action bridge:

```powershell
python scripts\probe_qwd_route_applicability.py `
  --demo-root artifacts\qwd-study `
  --pattern "*.qwd" `
  --output-json artifacts\qwd-study\qwd-route-probe.json `
  --output-md artifacts\qwd-study\qwd-route-probe.md `
  --raw-output-dir artifacts\qwd-study\raw `
  --waypoint-spacing 64
```

The probe recovers anchored self-player `svc_playerinfo` samples and reports
coverage, speed summaries, discontinuities, and waypoint downsampling.

Interpret low state coverage carefully:

- Low coverage does not invalidate the command labels.
- Low coverage does mean route geometry and speed claims need interpolation and
  confidence flags.

### 4. Reject Unsafe Zip Pairing

If command frames and state frames differ, or if zip time deltas are large, do
not pair by row number.

Use:

```powershell
python scripts\qwd_seam_validator.py `
  --demo path\to\demo.qwd `
  --output-json artifacts\qwd-study\demo-seam.json `
  --output-md artifacts\qwd-study\demo-seam.md
```

The validator reports:

- command frames,
- state frames,
- zip coverage,
- whether zip is unsafe,
- angle-channel deltas,
- time-alignment drops.

If `zip unsafe=True`, use time alignment plus interpolation.

### 5. Time-Align Commands And State

Use the replay builder for the current reusable seam:

```powershell
python scripts\build_replay_command_file.py `
  --demo path\to\demo.qwd `
  --alignment time `
  --output artifacts\replay\demo.cmds `
  --output-json artifacts\replay\replay-build-demo.json
```

This emits one row per command frame and records whether each row's state was
matched, interpolated, nearest, or missing.

Inspect the JSON sidecar before treating the trace as lockstep evidence:

- `paired_coverage`
- `reference_source_counts`
- `interpolated_command_indices`
- `state_alignment`
- `angle_channel_delta_deg`
- `command_msec`

### 6. Segment Before Interpolating

Do not interpolate across discontinuities.

For each demo, split around:

- `continuity.discontinuities` from the route probe,
- suspicious large `dt`,
- suspicious large distance,
- teleport source/destination transitions,
- respawns,
- repeated attempt resets,
- long missing-state spans.

Keep each segment's metadata:

- segment id,
- start/end command cursor,
- start/end demo time,
- start/end origin,
- reason for split,
- whether segment is route-worthy or command-only.

Classify each segment:

- `controller_candidate`: clean enough for route guidance and live scoring.
- `command_label_only`: useful for mouse/strafe/jump timing, not geometry.
- `diagnostic_only`: too many discontinuities or too little state.

### 7. Interpolate Inside Clean Segments

Within each clean segment:

1. Preserve every command row.
2. Fill missing origin and velocity at command times.
3. Unwrap yaw before interpolation.
4. Compute derived values:
   - horizontal speed,
   - velocity yaw,
   - target yaw,
   - yaw lead,
   - target error,
   - yaw rate,
   - side/yaw coupling,
   - jump-edge timing.
5. Mark rows that used interpolation.

For evidence, prefer conservative linear interpolation and explicit event
projection. For controller guidance, local quadratic interpolation can be used
where it has been checked against the original points.

Never smooth buttons. A jump edge is an event, not a curve.

### 8. Emit Controller Targets

The final teaching artifact should be a compact JSON or `.cmds` sidecar with:

- source QWD SHA,
- extraction tool versions or commit SHA,
- segment definitions,
- per-row command labels,
- per-row interpolated state,
- interpolation method,
- confidence flags,
- derived movement quantities,
- recommended controller mode or policy type.

Recommended policy types:

- `replay`: exact QWD yaw and commands are good enough to try directly.
- `phase_strengthened_replay`: preserve QWD yaw/jump/side timing, but increase
  side magnitude or phase-gated strength.
- `hybrid_waypoint_controller`: use waypoints plus QWD command profile.
- `diagnostic_only`: learn from the commands, but do not claim route execution.

### 9. Validate With The Bot

Only after the QWD trace is built should the bot try.

The live validation loop is:

1. Start a clean lab run.
2. Snap or route the bot to the same start context.
3. Apply the controller target.
4. Record MVD and moveprobe command logs.
5. Score live output against the human trace.
6. Separately score mouse shape and movement output.
7. Reject mixed attempts, restarts, or teleport-contaminated evidence.

The bot does not create the reference. The bot tests whether the reference can
be executed.

## Why This Matters

Bunnyjumping is synchronized movement, not raw speed.

The human signal has several coupled parts:

- mouse yaw shape,
- strafe side and side-switch timing,
- jump edge timing,
- velocity direction,
- ground/air phase,
- route direction and geometry.

If we collapse this into one number like max speed, the bot can look fast while
still moving wrong. If we generate yaw ourselves, the bot can become spammy and
lose the human rhythm. If we zip-align sparse state, the bot can learn a false
jump point or a false velocity direction.

Segmentation and interpolation make the human trace teachable without lying
about what the demo contains.

## Current Tool Map

- `tools/qwd_usercmd/qwd_usercmd.py`: extracts exact QWD command labels.
- `scripts/qwd_seam_validator.py`: audits command/state coverage and unsafe zip
  alignment.
- `scripts/probe_qwd_route_applicability.py`: extracts paired trajectory
  evidence, discontinuities, and waypoints.
- `scripts/build_replay_command_file.py`: builds time-aligned replay `.cmds`
  files and interpolates missing reference state.
- `scripts/build_ztricks_reference_trace.py`: builds the successful ztricks
  Distance reference trace with conservative event proof and local-quadratic
  controller guidance.
- `scripts/ztricks_reference_trace.py`: shared ztricks reference interpolation
  helpers.

## Rules For Future Agents

1. Do not treat QWD state sparsity as failure. Commands may still be excellent.
2. Do not zip-align unless the seam validator proves it is safe.
3. Do not interpolate across teleports, respawns, or attempt resets.
4. Do not smooth jump buttons or attack buttons.
5. Do unwrap angles before interpolation.
6. Do mark interpolated rows in every artifact.
7. Do score mouse shape separately from speed and route completion.
8. Do preserve the accepted baseline before tuning away from it.

## Minimal Checklist

Before a new QWD-derived route is handed to a bot:

- [ ] QWD command extraction is clean.
- [ ] Seam validator run exists.
- [ ] Unsafe zip alignment is rejected or explicitly justified.
- [ ] Discontinuities are listed.
- [ ] Segments are classified.
- [ ] Missing state is interpolated only inside clean segments.
- [ ] Angles are unwrapped before interpolation.
- [ ] Buttons are preserved as discrete events.
- [ ] Output sidecar records matched/interpolated/missing rows.
- [ ] Live validation plan names the score gates before the bot tries.

