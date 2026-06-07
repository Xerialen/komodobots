# QWD SNG Slow-Success Diagnosis qwd-sng-tight-start-rerun-dm3

## Scope

- Run: `20260607T003837Z`
- Source result: `experiments/qwd_route_probe/evidence/qwd-sng-tight-start-rerun-dm3.json`
- Source verdict: `qwd_sng_hybrid_probe_rejected_by_guardrails`
- Start radius used: `192.0` qu
- Design start radius: `192.0` qu
- Point radius: `96.0` qu
- Offline attribution of the setup-repaired SNG run. It splits active QWD commands by current control-point target, joins each phase to MVD movement segments, and checks whether the slow guardrail failure is setup, route/map context, or command-profile weakness.

## Player Classification

| Player | Slow candidate | Verdict | Flags |
|---|---:|---|---|
| `/ bro` | `True` | `mixed_controller_and_setup_context` | `post_cp3_target_gap_remains_outside_point_radius, strong_qwd_side_profile_present, strong_jump_profile_present, water_path_not_primary, low_dir_speed_not_primary` |
| `/ goldenboy` | `False` | `not_slow_success_candidate` | `post_cp3_target_gap_remains_outside_point_radius, strong_qwd_side_profile_present, strong_jump_profile_present, water_path_not_primary, low_dir_speed_not_primary` |

## Start Radius Sensitivity

### / bro

| Radius | First time | Distance | Origin |
|---:|---:|---:|---|
| 320.0 | 1761 | 83.482 | `[226.125, -317.875, 74.875]` |
| 256.0 | 1761 | 83.482 | `[226.125, -317.875, 74.875]` |
| 192.0 | 1761 | 83.482 | `[226.125, -317.875, 74.875]` |
| 160.0 | 1761 | 83.482 | `[226.125, -317.875, 74.875]` |
| 128.0 | 1761 | 83.482 | `[226.125, -317.875, 74.875]` |
| 96.0 | 1761 | 83.482 | `[226.125, -317.875, 74.875]` |

### / goldenboy

| Radius | First time | Distance | Origin |
|---:|---:|---:|---|
| 320.0 | 7432 | 85.522 | `[224.0, -320.0, 75.0]` |
| 256.0 | 7432 | 85.522 | `[224.0, -320.0, 75.0]` |
| 192.0 | 7432 | 85.522 | `[224.0, -320.0, 75.0]` |
| 160.0 | 7432 | 85.522 | `[224.0, -320.0, 75.0]` |
| 128.0 | 7432 | 85.522 | `[224.0, -320.0, 75.0]` |
| 96.0 | 7432 | 85.522 | `[224.0, -320.0, 75.0]` |

## Active Phases

### / bro

| CP target | Active range | Commands | MVD p50 | Low | Stationary | QWD dist p50 | Closest target | Blocked | Water path | Low-dir | Cmd h50 |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2 | `1587-1791` | 3 | 438.547 | 0.0 | 0.0 | 135.321 | 173.848 | 0.0 | 0.0 | 0.0 | 600.0 |
| 3 | `1903-2742` | 9 | 287.26 | 0.0 | 0.0 | 168.205 | 141.258 | 0.0 | 0.0 | 0.0 | 600.0 |
| 4 | `2844-3161` | 4 | 327.384 | 0.0 | 0.0 | 156.417 | 174.781 | 0.0 | 0.0 | 0.0 | 599.799 |
| 5 | `3264-3575` | 4 | 326.26 | 0.0 | 0.0 | 155.445 | 181.539 | 0.0 | 0.0 | 0.0 | 599.462 |
| 6 | `3677-4305` | 7 | 329.538 | 0.0 | 0.0 | 193.127 | 171.8 | 0.0 | 0.0 | 0.0 | 599.801 |
| 7 | `4408-4929` | 6 | 300.6 | 0.0 | 0.0 | 157.779 | 151.523 | 0.0 | 0.0 | 0.0 | 600.0 |
| 8 | `5046-10603` | 54 | 186.978 | 0.184 | 0.0 | 197.019 | 115.919 | 0.0 | 0.0 | 0.0 | 600.0 |
| 9 | `10706-17579` | 67 | 189.027 | 0.208 | 0.006 | 319.939 | 129.575 | 0.0 | 0.0 | 0.0 | 600.0 |
| 10 | `17681-17785` | 2 | 180.386 | 0.196 | 0.0 | 119.162 | 173.147 | 0.0 | 0.0 | 0.0 | 599.637 |
| 11 | `17888-17888` | 1 | None | None | None | 196.64 | None | 0.0 | 0.0 | 0.0 | 600.0 |

### / goldenboy

| CP target | Active range | Commands | MVD p50 | Low | Stationary | QWD dist p50 | Closest target | Blocked | Water path | Low-dir | Cmd h50 |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2 | `7248-7558` | 4 | 432.067 | 0.0 | 0.0 | 134.577 | 154.982 | 0.0 | 0.0 | 0.0 | 599.784 |
| 3 | `7670-8494` | 9 | 284.632 | 0.1 | 0.0 | 155.598 | 148.39 | 0.0 | 0.0 | 0.0 | 600.0 |
| 4 | `8596-8927` | 4 | 330.596 | 0.0 | 0.0 | 161.415 | 181.867 | 0.0 | 0.0 | 0.0 | 599.674 |
| 5 | `9029-9336` | 4 | 338.397 | 0.0 | 0.0 | 145.394 | 179.992 | 0.0 | 0.0 | 0.0 | 600.0 |
| 6 | `9449-15273` | 57 | 179.955 | 0.25 | 0.0 | 149.21 | 110.337 | 0.0 | 0.0 | 0.0 | 600.0 |
| 7 | `15376-15912` | 6 | 280.137 | 0.0 | 0.0 | 146.15 | 144.362 | 0.0 | 0.0 | 0.0 | 599.681 |
| 8 | `16014-16643` | 7 | 275.38 | 0.066 | 0.0 | 187.584 | 167.534 | 0.0 | 0.0 | 0.0 | 599.473 |
| 9 | `16745-17785` | 11 | 295.108 | 0.019 | 0.0 | 179.683 | 128.426 | 0.0 | 0.0 | 0.0 | 600.0 |
| 10 | `17888-17991` | 2 | 178.754 | 0.0 | 0.0 | 110.346 | 149.26 | 0.0 | 0.0 | 0.0 | 599.977 |
| 11 | `18094-18403` | 4 | 248.079 | 0.0 | 0.0 | 139.224 | 152.682 | 0.0 | 0.0 | 0.0 | 600.0 |
| 12 | `18505-19336` | 9 | 109.302 | 0.476 | 0.0 | 201.589 | 186.973 | 0.111 | 0.0 | 0.0 | 600.0 |

## Decision

- Verdict: `qwd_sng_slow_success_needs_mixed_followup`
- Reason: The slow-success rejection did not isolate to a single setup or controller cause.
- Next goal: Keep the next follow-up diagnostic and do not expand to other QWD moves yet.
