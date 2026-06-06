# QWD SNG Slow-Success Diagnosis qwd-sng-slow-success-diagnosis-dm3

## Scope

- Run: `20260606T231007Z`
- Source result: `experiments/qwd_route_probe/evidence/qwd-sng-setup-repair-result-dm3.json`
- Source verdict: `qwd_sng_hybrid_probe_rejected_by_guardrails`
- Start radius used: `320.0` qu
- Design start radius: `192.0` qu
- Point radius: `96.0` qu
- Offline attribution of the setup-repaired SNG run. It splits active QWD commands by current control-point target, joins each phase to MVD movement segments, and checks whether the slow guardrail failure is setup, route/map context, or command-profile weakness.

## Player Classification

| Player | Slow candidate | Verdict | Flags |
|---|---:|---|---|
| `/ bro` | `True` | `loose_setup_radius_plus_post_cp3_progression_gap` | `loose_start_radius_contaminated_active_window, cp0_phase_low_speed_before_tight_start, cp0_phase_stationary_before_tight_start, cp0_route_blocked_context, post_cp3_target_gap_remains_outside_point_radius, strong_qwd_side_profile_present, strong_jump_profile_present, water_path_not_primary, low_dir_speed_not_primary` |
| `/ goldenboy` | `False` | `not_slow_success_candidate` | `cp0_phase_low_speed_before_tight_start, cp0_phase_stationary_before_tight_start, cp0_route_blocked_context, strong_qwd_side_profile_present, strong_jump_profile_present, water_path_not_primary, low_dir_speed_not_primary` |

## Start Radius Sensitivity

### / bro

| Radius | First time | Distance | Origin |
|---:|---:|---:|---|
| 320.0 | 0 | 281.954 | `[192.0, -208.0, -175.0]` |
| 256.0 | 27516 | 255.283 | `[240.0, -238.75, -176.0]` |
| 192.0 | 31652 | 83.332 | `[226.25, -317.875, 74.75]` |
| 160.0 | 31652 | 83.332 | `[226.25, -317.875, 74.75]` |
| 128.0 | 31652 | 83.332 | `[226.25, -317.875, 74.75]` |
| 96.0 | 31652 | 83.332 | `[226.25, -317.875, 74.75]` |

### / goldenboy

| Radius | First time | Distance | Origin |
|---:|---:|---:|---|
| 320.0 | 29450 | 318.855 | `[184.375, -140.375, -176.0]` |
| 256.0 | 29675 | 253.881 | `[172.625, -226.125, -137.0]` |
| 192.0 | None | None | `[]` |
| 160.0 | None | None | `[]` |
| 128.0 | None | None | `[]` |
| 96.0 | None | None | `[]` |

## Active Phases

### / bro

| CP target | Active range | Commands | MVD p50 | Low | Stationary | QWD dist p50 | Closest target | Blocked | Water path | Low-dir | Cmd h50 |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | `0-29677` | 286 | 84.385 | 0.526 | 0.383 | 306.015 | 227.386 | 0.371 | 0.0 | 0.003 | 600.0 |
| 2 | `31438-31756` | 4 | 429.657 | 0.0 | 0.0 | 142.505 | 158.42 | 0.0 | 0.0 | 0.0 | 600.0 |
| 3 | `31859-35707` | 38 | 212.592 | 0.22 | 0.006 | 119.997 | 98.719 | 0.0 | 0.0 | 0.0 | 600.0 |
| 4 | `35811-45719` | 96 | 167.091 | 0.279 | 0.002 | 231.677 | 181.154 | 0.0 | 0.0 | 0.0 | 600.0 |

### / goldenboy

| CP target | Active range | Commands | MVD p50 | Low | Stationary | QWD dist p50 | Closest target | Blocked | Water path | Low-dir | Cmd h50 |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | `29288-45719` | 159 | 0.0 | 0.681 | 0.615 | 313.025 | 232.805 | 0.623 | 0.0 | 0.0 | 600.0 |

## Decision

- Verdict: `qwd_sng_slow_success_attributed_to_loose_setup_and_post_cp3_gap`
- Reason: The advancing bot was activated by the widened start radius long before a tight start-radius crossing, then still failed to enter the next target radius after CP3. This is not learned SNG.
- Next goal: Tighten SNG activation around the real CP0 approach and add phase-level success gates before changing projection policy or trying other DM3 QWD moves.
