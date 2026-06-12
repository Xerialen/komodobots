# Ztricks Distance Speedjump Formula v0

Status: working controller contract, not a final bot brain.

## Purpose

The ztricks Distance jump is not solved by "more speed" alone. The successful
human attempt coordinates four things in the same short window:

- horizontal speed
- velocity heading
- view yaw / mouse sweep
- jump timing at the lip

This note turns the successful `getspeed.qwd` attempt into a controller-shaped
formula for the next live KTX primitive.

## Human Reference

Source: `getspeed-aligned.cmds`, attempt 11.

Key rows:

| state | row | origin | speed | velocity heading | view yaw | command | buttons |
|---|---:|---|---:|---:|---:|---|---:|
| attempt start | 1807 | `-3516.1 3712.0 -453.1` | 300.0 | 0.0 | 3.0 | `0 0 0` | 2 |
| first grounded | 1830 | `-3437.8 3689.1 -488.0` | 288.1 | -29.0 | 78.4 | `-400 400 0` | 0 |
| terminal sweep start | 1904 | `-3439.4 3758.1 -488.0` | 441.4 | 41.4 | 39.1 | `400 400 0` | 0 |
| speed floor crossed | 1908 | `-3419.9 3770.6 -488.0` | 450.8 | 27.5 | 23.8 | `400 400 0` | 0 |
| aligned near target line | 1916 | `-3373.0 3779.2 -488.0` | 472.8 | -3.3 | -11.4 | `400 400 0` | 0 |
| jump/release | 1918 | `-3360.8 3777.2 -488.0` | 475.2 | -11.3 | -19.0 | `400 400 0` | 2 |
| lip crossing | 1920 | `-3348.6 3774.8 -481.4` | 475.2 | -11.3 | -24.5 | `400 400 0` | 2 |
| landing | 1969 | `-3044.1 3760.5 -488.0` | 495.5 | 2.7 | 1.0 | `0 0 0` | 0 |

Angles are degrees. Negative headings mean slightly south of east.

## Formula

Definitions:

- `vh = hypot(vx, vy)`
- `vel_yaw = atan2(vy, vx)`
- `target_yaw = atan2(target_y - y, target_x - x)`
- `yaw_lead = wrap(view_yaw - vel_yaw)`
- `target_error = wrap(target_yaw - vel_yaw)`
- `d_lip = lip_x - x`, with `lip_x ~= -3348`

Constants from the successful attempt:

- target point: `(-3044.1, 3760.5, -488.0)`
- release point: `(-3360.8, 3777.2, -488.0)`
- release speed floor: `vh >= 470`
- emergency lower speed floor for exploration: `vh >= 453`
- release window: `0 <= d_lip <= 35`, ideal `d_lip ~= 13`
- release velocity heading: about `-11 deg`
- release view-yaw lead: about `-8 deg` relative to velocity
- command through terminal sweep: `forwardmove=400`, `sidemove=400`

The terminal sweep in the human attempt lasts 15 command rows / 195 ms:

- `vh`: `441.4 -> 475.2`
- `vel_yaw`: `41.4 -> -11.3`
- `view_yaw`: `39.1 -> -19.0`
- `yaw_lead`: `-2.3 -> -7.7`
- `d_lip`: `91.4 -> 12.8`

## Controller Shape

Phase 1: reset / standstill

- Snap to `-3516.125 3712 -453.125`.
- Zero velocity for the requested standstill case.
- Hold mode 24 until the operator presses try.

Phase 2: build

- Use the existing grounded circle/route behavior only to produce a useful
  terminal entry, not to decide the final jump.
- The target is not "reach marker 8"; the target is a release state:
  `y ~= 3777`, `vh >= 450`, and a path that lets the controller rotate the
  velocity heading toward the landing line before `d_lip` collapses.

Phase 3: arm terminal carve

Arm when all are true:

- grounded
- `vh >= 450`
- `d_lip <= 80`
- `y` is inside the successful lane, roughly `3760 <= y <= 3820`

While armed:

- suppress jump
- keep full horizontal command
- hold a strafe/wishdir that rotates velocity heading southward toward the
  target line
- keep view yaw slightly south of velocity, aiming for `yaw_lead` from `-5`
  to `-10`

Phase 4: release

Jump when all are true:

- grounded
- `vh >= release_vh`, initially `470` for human-like attempts or `453` for
  first live exploration
- `0 <= d_lip <= 35`
- `target_error` is near zero or slightly positive, roughly `-2 <=
  target_error <= 10`
- `yaw_lead` is in the human-like range, roughly `-12 <= yaw_lead <= -4`

Backstop:

- If `d_lip <= 8`, jump anyway only if `vh >= 453`; otherwise classify as
  low-speed/no-release rather than pretending the attempt was meaningful.

Phase 5: flight

- Continue the jump bit for the first few air frames if KTX input semantics
  require it, but the score is determined by the release state.
- Keep logging origin, velocity, view yaw, command, and buttons.

## Why The Current Live Attempt Failed

Live session `dash_20260612T142054Z` proved the current mode-23 controller can
move and can generate speed, but it does not synchronize the terminal sweep.

Closest pass to the human release point:

- distance: `6.0q`
- origin: `(-3354.980, 3775.733, -487.969)`
- speed: `457.1`
- velocity heading: `84.6 deg`
- yaw: `134.6 deg`
- buttons: `1`, no jump bit

That is almost the right place and enough exploratory speed, but it is travelling
north, nearly perpendicular to the successful release. The first actual jump
fired later at `153.0` speed from the wrong lane.

## Next KTX Primitive

Add default-off cvars for a ztricks-oriented terminal carve:

```text
k_fb_moveprobe_s23_launch_target "-3044.1 3760.5 -488"
k_fb_moveprobe_s23_release_vh 470
k_fb_moveprobe_s23_release_vh_min 453
k_fb_moveprobe_s23_carve_d 80
k_fb_moveprobe_s23_release_lip 35
k_fb_moveprobe_s23_yawlead_min -12
k_fb_moveprobe_s23_yawlead_max -4
k_fb_moveprobe_s23_targeterr_min -2
k_fb_moveprobe_s23_targeterr_max 10
```

The primitive should log one row-level diagnostic suffix:

```text
zjump=phase,d_lip,vh,vel_yaw,target_yaw,target_err,yaw_lead,armed,release_rule
```

The next live loop should run one attempt, freeze, and score only the release
state first. Landing is secondary until release state matches the formula.
