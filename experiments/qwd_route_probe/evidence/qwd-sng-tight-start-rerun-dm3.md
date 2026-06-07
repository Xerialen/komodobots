# QWD SNG Hybrid Probe Result qwd-sng-tight-start-rerun-dm3

## Scope

- Map: `dm3`
- Source design: `experiments/qwd_route_probe/evidence/qwd-sng-hybrid-probe-design-dm3.json`
- Bot run IDs: `20260607T003837Z`
- Score temporary mode-9 SNG hybrid waypoint/controller runs by QWD activation, control-point advancement, command profile, and route/water/cadence guardrails. Speed alone cannot pass.

## Aggregate

- Command samples: `865`
- QWD samples: `865`
- QWD active samples: `274`
- Max active seconds: `16.383`
- Max advanced control points: `12`
- Max advanced control points inside MVD: `12`
- Max control-point index: `12`
- Max control-point index inside MVD: `12`
- Min QWD target distance: `96.066` qu

## Players

| Run | Player | Cmds | Active | Active in MVD | Advanced | Advanced in MVD | Active s | Min dist | Low | Stationary | Water path | Low-dir | Active side | Active jump |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `20260607T003837Z` | `/ bro` | 461 | 157 | 157 | 11 | 11 | 16.383 | 96.066 | 0.55 | 0.063 | 0.0 | 0.007 | 1.0 | 1.0 |
| `20260607T003837Z` | `/ goldenboy` | 404 | 117 | 117 | 12 | 12 | 12.149 | 96.257 | 0.146 | 0.004 | 0.092 | 0.047 | 1.0 | 1.0 |

## Stop Conditions

| Condition | Status | Details |
|---|---|---|
| `qwd_probe_activation` | `pass` | `{"active_samples": 274, "max_active_seconds": 16.383, "required_active_seconds": 1.0}` |
| `control_point_advancement` | `pass` | `{"max_advanced_control_points": 12, "max_advanced_control_points_inside_mvd": 12, "required_advanced_control_points": 4, "rule": "Control-point advancement must occur inside the parsed MVD movement window."}` |
| `tight_start_activation` | `inconclusive` | `{"design_start_radius_qu": 192.0, "players_advancing_after_loose_start": [], "players_with_unverifiable_start_distance": [{"first_active_inside_mvd_advanced_control_points": 2, "first_active_inside_mvd_control_point_index": 2, "first_active_inside_mvd_distance_qu": 160.417, "first_active_inside_mvd_time_ms": 1587, "player": "/ bro"}, {"first_active_inside_mvd_advanced_control_points": 2, "first_active_inside_mvd_control_point_index": 2, "first_active_inside_mvd_distance_qu": 167.498, "first_active_inside_mvd_time_ms": 7248, "player": "/ goldenboy"}], "rule": "A run that reaches the advancement gate must show first active in-MVD evidence at CP0 before same-frame advancement and inside the design start radius."}` |
| `phase_target_progression` | `reject` | `{"minimum_phase_duration_s": 1.0, "players_with_unresolved_post_advance_targets": [{"active_duration_s": 5.557, "control_point_index": 8, "min_distance_qu": 100.211, "player": "/ bro"}, {"active_duration_s": 6.873, "control_point_index": 9, "min_distance_qu": 100.806, "player": "/ bro"}, {"active_duration_s": 5.824, "control_point_index": 6, "min_distance_qu": 97.146, "player": "/ goldenboy"}, {"active_duration_s": 1.04, "control_point_index": 9, "min_distance_qu": 96.518, "player": "/ goldenboy"}], "point_radius_qu": 96.0, "rule": "After the required SNG advancement, a long active phase on the next target must enter that target radius before the run can count as bounded positive evidence."}` |
| `qwd_activation_mvd_overlap` | `pass` | `{"players_with_active_qwd_outside_mvd_window": [], "rule": "QWD activation/advancement must overlap the parsed MVD movement window before movement guardrails can support a positive claim."}` |
| `diagnostic_preservation` | `pass` | `{"players_missing_route_water_or_cadence": []}` |
| `qwd_command_profile_present` | `pass` | `{"players_with_weak_active_side_or_jump_profile": []}` |
| `waypoint_only_slow_success` | `reject` | `{"low_speed_threshold": 0.4, "players_reaching_points_while_slow_or_stuck": ["/ bro"], "stationary_threshold": 0.25}` |
| `route_dirty_success_guardrail` | `pass` | `{"players_reaching_points_with_dirty_route_context": [], "water_path_or_low_dir_threshold": 0.5}` |

## Decision

- Verdict: `qwd_sng_hybrid_probe_rejected_by_guardrails`
- Reason: The server-loop probe produced evidence, but guardrails failed: phase_target_progression, waypoint_only_slow_success.
- Next goal: Use tight design-radius evidence if it has not been collected yet; if tight-start phases still stall or start evidence is unverifiable, add denser/event-level advancement and active-window diagnostics before changing projection policy.
