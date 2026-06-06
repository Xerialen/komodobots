# QWD SNG Hybrid Probe Design

## Scope

- Map: `dm3`.
- Source mapping: `experiments/qwd_route_probe/evidence/qwd-frogbot-route-map-dm3-sng-shortcut.json`.
- Source demo: `dm3_sng_shortcut.qwd`.
- Consume the committed SNG QWD-to-Frogbot mapping and write a design-only contract for the first server-loop hybrid waypoint/controller probe. This does not change KTX, Frogbot behavior, route data, lab runners, or parser behavior.

## Mapping Inputs

- Control points: `14`.
- QWD waypoints in source mapping: `33`.
- Nearest-marker p50/p95/max: `70.112` / `120.324` / `142.597` qu.
- Direct `.bot` edge ratio: `0.0`.
- Graph reachable ratio: `1.0`.
- QWD nonzero forward/side/jump: `0.089` / `0.718` / `0.284`.
- Recommended forward/side commands: `320` / `508`.

## Probe Contract

- Probe id: `qwd-dm3-sng-hybrid-waypoint-controller`.
- Status: `design_only_no_controller_behavior_changed`.
- Follow-up: Implement one temporary KTX moveprobe mode, likely mode 9.

Runtime shape:

- Do not edit dm3.bot.
- Use cvar_string to read a bounded semicolon-separated QWD waypoint string.
- Activate only when the bot is on dm3 and within the start radius of control point 0.
- Advance control points only when the bot enters the control-point radius.
- Project waypoint-attraction plus QWD-style sidemove into the bot's preserved combat view yaw.
- Preserve route, water, command, probe-activation, cadence, and movement-bucket diagnostics.

Suggested cvars:

| cvar | value |
|---|---|
| `k_fb_moveprobe_mode` | `9` |
| `k_fb_moveprobe_qwd_waypoints` | `307.375,-321.250,56.000;302.375,-254.125,56.000;255.500,-141.750,81.625;214.000,35.625,74.000;36...` |
| `k_fb_moveprobe_qwd_point_radius` | `96.0` |
| `k_fb_moveprobe_qwd_start_radius` | `192.0` |
| `k_fb_moveprobe_forwardmove` | `320` |
| `k_fb_moveprobe_sidemove` | `508` |
| `k_fb_moveprobe_log_commands` | `1` |
| `k_fb_moveprobe_log_interval` | `0.1` |

Control points:

| # | origin | nearest marker | marker distance |
|---:|---|---:|---:|
| 0 | `307.375,-321.25,56.0` | 157 | 99.853 |
| 1 | `302.375,-254.125,56.0` | 28 | 86.379 |
| 2 | `255.5,-141.75,81.625` | 158 | 46.2 |
| 3 | `214.0,35.625,74.0` | 159 | 129.086 |
| 4 | `368.0,145.375,99.375` | 29 | 43.624 |
| 5 | `458.5,228.5,62.125` | 53 | 85.732 |
| 6 | `520.875,416.875,97.75` | 51 | 82.499 |
| 7 | `384.75,530.625,85.625` | 155 | 75.401 |
| 8 | `214.125,616.5,83.25` | 149 | 85.087 |
| 9 | `27.5,672.125,97.75` | 143 | 61.493 |
| 10 | `-34.125,692.125,98.5` | 145 | 71.067 |
| 11 | `-150.75,659.625,115.625` | 153 | 114.482 |
| 12 | `-240.875,557.875,130.375` | 32 | 105.222 |
| 13 | `-424.25,492.625,120.0` | 126 | 53.23 |

## Validation Plan

- `patch_compile`: Build succeeds and stock mode 0 remains available.
- `server_loop_run`: Run produces MVD, movement metrics, moveprobe command logs, and qwd probe rows.
- `trajectory_scoring`: At least 4 control points advanced or result is inconclusive; probe active for at least 1.0s or result is inconclusive.
- `guardrails`: No success claim if route/water/cadence diagnostics are missing or regress badly.

## Stop Conditions

- `no_server_loop_execution` (inconclusive): If the bot never activates or advances fewer than four control points, do not call the move learned.
- `waypoint_only_success` (reject): Reject success if the bot reaches points only by slow/stuck movement that fails movement-bucket checks.
- `diagnostic_loss` (inconclusive): Missing command, route, water, cadence, or qwd probe diagnostics blocks success claims.
- `route_or_water_regression` (reject_or_route_handoff): If WATER_PATH or low-dir route slices dominate failure, pivot to a route primitive instead of widening QWD control.
- `positive_sng_gate` (continue_to_more_dm3_qwds): Only after SNG has positive server-loop evidence should the automation attempt the other DM3 QWD moves.

## Decision

- Verdict: `ready_to_implement_qwd_sng_hybrid_server_loop_probe`.
- Frogbots-vs-from-scratch: `continue_frogbots_for_qwd_sng_runtime_probe`.
- Reason: The SNG QWD trajectory is close enough to Frogbot marker space for context, but direct route topology does not match the shortcut and the human command profile is side-move dominant. The next evidence must therefore execute a temporary hybrid waypoint/controller probe inside KTX.
- Next goal: Implement mode 9 plus a comparison helper, run the SNG shortcut probe on dm3, then ask Claude to review whether server-loop evidence justifies trying the remaining DM3 QWD moves.

