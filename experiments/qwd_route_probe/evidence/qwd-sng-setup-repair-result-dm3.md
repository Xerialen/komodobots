# QWD SNG Hybrid Probe Result qwd-sng-setup-repair-dm3

## Scope

- Map: `dm3`
- Source design: `experiments/qwd_route_probe/evidence/qwd-sng-hybrid-probe-design-dm3.json`
- Bot run IDs: `20260606T231007Z`
- Score temporary mode-9 SNG hybrid waypoint/controller runs by QWD activation, control-point advancement, command profile, and route/water/cadence guardrails. Speed alone cannot pass.

## Aggregate

- Command samples: `867`
- QWD samples: `867`
- QWD active samples: `627`
- Max active seconds: `16.591`
- Max advanced control points: `4`
- Max advanced control points inside MVD: `4`
- Max control-point index: `4`
- Max control-point index inside MVD: `4`
- Min QWD target distance: `99.086` qu

## Players

| Run | Player | Cmds | Active | Active in MVD | Advanced | Advanced in MVD | Active s | Min dist | Low | Stationary | Water path | Low-dir | Active side | Active jump |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `20260606T231007Z` | `/ bro` | 462 | 446 | 424 | 4 | 4 | 16.591 | 99.086 | 0.429 | 0.253 | 0.0 | 0.002 | 1.0 | 1.0 |
| `20260606T231007Z` | `/ goldenboy` | 405 | 181 | 159 | 0 | 0 | 6.831 | 232.815 | 0.301 | 0.258 | 0.0 | 0.017 | 1.0 | 1.0 |

## Stop Conditions

| Condition | Status | Details |
|---|---|---|
| `qwd_probe_activation` | `pass` | `{"active_samples": 627, "max_active_seconds": 16.591, "required_active_seconds": 1.0}` |
| `control_point_advancement` | `pass` | `{"max_advanced_control_points": 4, "max_advanced_control_points_inside_mvd": 4, "required_advanced_control_points": 4, "rule": "Control-point advancement must occur inside the parsed MVD movement window."}` |
| `qwd_activation_mvd_overlap` | `pass` | `{"players_with_active_qwd_outside_mvd_window": [], "rule": "QWD activation/advancement must overlap the parsed MVD movement window before movement guardrails can support a positive claim."}` |
| `diagnostic_preservation` | `pass` | `{"players_missing_route_water_or_cadence": []}` |
| `qwd_command_profile_present` | `pass` | `{"players_with_weak_active_side_or_jump_profile": []}` |
| `waypoint_only_slow_success` | `reject` | `{"low_speed_threshold": 0.4, "players_reaching_points_while_slow_or_stuck": ["/ bro"], "stationary_threshold": 0.25}` |
| `route_dirty_success_guardrail` | `pass` | `{"players_reaching_points_with_dirty_route_context": [], "water_path_or_low_dir_threshold": 0.5}` |

## Decision

- Verdict: `qwd_sng_hybrid_probe_rejected_by_guardrails`
- Reason: The server-loop probe produced evidence, but guardrails failed: waypoint_only_slow_success.
- Next goal: Diagnose whether the failure is route/context contamination or controller command policy before widening QWD control.
