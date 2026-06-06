# Air-Transition Probe Result s7j-air-transition-probe-dm3

## Scope

- Map: `dm3`
- Source S7i design: `experiments/human_comparison/evidence/air-transition-probe-design-s7i-dm3.json`
- Source S7f reference rows: `experiments/human_comparison/evidence/airborne-segments-s7f-dm3.json`
- Bot run IDs: `20260606T163907Z, 20260606T164610Z`
- S7j implements the S7i mode-8 transition-only horizontal command-budget probe, runs it in the headless dm3 bot lab, and evaluates the result against S7i stop conditions. Passing validation is evidence, not proof of believable player behavior.

## Run Configuration

| Run | Mode | Forward | Side | Up | Transition scale | Transition window | Command logging |
|---|---:|---:|---:|---:|---:|---:|---|
| `20260606T163907Z` | 8 | 800 | 200 | 0 | 1.25 | 0.4 | 1 @ 0.25s |
| `20260606T164610Z` | 8 | 800 | 200 | 0 | 1.25 | 0.4 | 1 @ 0.25s |

## Bucket Changes

| Bucket | S7g bot p50 | S7j bot p50 | S7j/S7g | S7j rows | Bot/ref p50 |
|---|---:|---:|---:|---:|---:|
| Pre-air window | 207.1 | 149.7 | 0.723 | 4 | 0.358 |
| Airborne-proxy segments | 122.6 | 100.4 | 0.819 | 4 | 0.232 |
| Post-air window | 184.5 | 179.6 | 0.973 | 4 | 0.491 |
| All accepted segments | 222.0 | 230.0 | 1.036 | 4 | 0.689 |
| Non-airborne segments | 312.1 | 286.3 | 0.917 | 4 | 0.895 |
| Route low-dir-speed segments | 141.0 | 201.2 | 1.427 | 4 |  |
| Route WATER_PATH segments | 95.3 | 96.2 | 1.009 | 1 |  |

## Probe Activation

- Samples with probe state: `546`
- Transition-active samples: `110`
- Transition-active ratio: `0.201`

| Run | Player | Samples | Active samples | Active ratio | Active scales |
|---|---|---:|---:|---:|---|
| `20260606T163907Z` | `/ bro` | 109 | 21 | 0.193 | `[1.25]` |
| `20260606T163907Z` | `/ goldenboy` | 86 | 16 | 0.186 | `[1.25]` |
| `20260606T164610Z` | `/ bro` | 187 | 66 | 0.353 | `[1.25]` |
| `20260606T164610Z` | `/ goldenboy` | 164 | 7 | 0.043 | `[1.25]` |

## Cadence

| Axis | Reference range | S7j bot range | Relation |
|---|---:|---:|---|
| Cadence/active min | 40.4-51.0 | 18.5-148.6 | `mixed_bot_relation` |
| Cadence/non-low-speed min | 48.7-61.3 | 19.2-297.2 | `mixed_bot_relation` |
| Cadence/air-proxy min | 128.0-143.1 | 131.7-245.3 | `mixed_bot_relation` |

## Stop Conditions

| Condition | Status | Details |
|---|---|---|
| `missing_required_reporting` | `pass` | `{'missing_buckets': [], 'missing_cadence_axes': []}` |
| `probe_activation_reporting` | `pass` | `{'sample_count': 546, 'transition_active_count': 110, 'transition_active_ratio': 0.201}` |
| `all_segment_proxy_win` | `reject` | `{'all_segments_improved': True, 'air_transition_buckets_improved': []}` |
| `air_transition_regression` | `reject` | `{'regressed_buckets': ['pre_air_window_segments', 'airborne_proxy_segments'], 'tolerance_ratio': 0.95}` |
| `non_airborne_guardrail` | `reject` | `{'ratio_to_s7g_baseline': 0.917, 'tolerance_ratio': 0.95}` |
| `water_path_guardrail` | `pass` | `{'ratio_to_s7g_baseline': 1.009, 'current_bot_player_count': 1, 'tolerance_ratio': 0.95}` |
| `cadence_still_diagnostic` | `pass` | `{'reported_axes': ['jump_cadence_per_min', 'jump_cadence_per_non_low_speed_min', 'jump_cadence_per_airborne_proxy_min'], 'note': 'Cadence remains reporting-only; it is not a success criterion for S7j.'}` |

## Decision

- Verdict: `air_transition_probe_rejected_by_s7i_stop_conditions`
- Air-transition buckets improved: `[]`
- Failed stop conditions: `['all_segment_proxy_win', 'air_transition_regression', 'non_airborne_guardrail']`
- Inconclusive stop conditions: `[]`
- Reason: S7j produced evidence, but stop conditions failed: all_segment_proxy_win, air_transition_regression, non_airborne_guardrail.
- Next goal: S7k should inspect the failed bucket and command/probe activation context before trying another controller probe.
