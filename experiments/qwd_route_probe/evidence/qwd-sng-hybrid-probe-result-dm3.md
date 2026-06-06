# QWD SNG Hybrid Probe Result qwd-sng-hybrid-probe-dm3

## Scope

- Map: `dm3`
- Source design: `experiments/qwd_route_probe/evidence/qwd-sng-hybrid-probe-design-dm3.json`
- Bot run IDs: `20260606T221429Z`
- Score temporary mode-9 SNG hybrid waypoint/controller runs by QWD activation, control-point advancement, command profile, and route/water/cadence guardrails. Speed alone cannot pass.

## Aggregate

- Command samples: `866`
- QWD samples: `866`
- QWD active samples: `11`
- Max active seconds: `1.12`
- Max advanced control points: `2`
- Max control-point index: `2`
- Min QWD target distance: `97.576` qu

## Players

| Run | Player | Cmds | Active | Advanced | Active s | Min dist | Low | Stationary | Water path | Low-dir | Active side | Active jump |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `20260606T221429Z` | `/ bro` | 462 | 0 | 0 | 0.0 | 282.748 | 0.16 | 0.053 | 0.16 | 0.102 | None | None |
| `20260606T221429Z` | `/ goldenboy` | 404 | 11 | 2 | 1.12 | 97.576 | 0.17 | 0.036 | 0.0 | 0.21 | 1.0 | 1.0 |

## Stop Conditions

| Condition | Status | Details |
|---|---|---|
| `qwd_probe_activation` | `pass` | `{"active_samples": 11, "max_active_seconds": 1.12, "required_active_seconds": 1.0}` |
| `control_point_advancement` | `inconclusive` | `{"max_advanced_control_points": 2, "required_advanced_control_points": 4}` |
| `diagnostic_preservation` | `pass` | `{"players_missing_route_water_or_cadence": []}` |
| `qwd_command_profile_present` | `pass` | `{"players_with_weak_active_side_or_jump_profile": []}` |
| `waypoint_only_slow_success` | `pass` | `{"low_speed_threshold": 0.4, "players_reaching_points_while_slow_or_stuck": [], "stationary_threshold": 0.25}` |
| `route_dirty_success_guardrail` | `pass` | `{"players_reaching_points_with_dirty_route_context": [], "water_path_or_low_dir_threshold": 0.5}` |

## Decision

- Verdict: `qwd_sng_hybrid_probe_inconclusive`
- Reason: The server-loop probe lacked required evidence for: control_point_advancement.
- Next goal: Repair activation, instrumentation, or spawn/context setup before trying other DM3 QWD moves.
