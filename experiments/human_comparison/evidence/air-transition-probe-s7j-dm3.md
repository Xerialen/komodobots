# Air-Transition Probe Result s7j-air-transition-probe-dm3

## Scope

- Map: `dm3`
- Source S7i design: `experiments/human_comparison/evidence/air-transition-probe-design-s7i-dm3.json`
- Source S7f reference rows: `experiments/human_comparison/evidence/airborne-segments-s7f-dm3.json`
- Bot run IDs: `20260606T161101Z`
- S7j implements the S7i mode-8 transition-only horizontal command-budget probe, runs it in the headless dm3 bot lab, and evaluates the result against S7i stop conditions. Passing validation is evidence, not proof of believable player behavior.

## Run Configuration

| Run | Mode | Forward | Side | Up | Transition scale | Transition window | Command logging |
|---|---:|---:|---:|---:|---:|---:|---|
| `20260606T161101Z` | 8 | 800 | 200 | 0 | 1.25 | 0.4 | 1 @ 0.25s |

## Bucket Changes

| Bucket | S7g bot p50 | S7j bot p50 | S7j/S7g | S7j rows | Bot/ref p50 |
|---|---:|---:|---:|---:|---:|
| Pre-air window | 207.1 | 209.1 | 1.009 | 2 | 0.500 |
| Airborne-proxy segments | 122.6 | 182.7 | 1.490 | 2 | 0.421 |
| Post-air window | 184.5 | 202.4 | 1.097 | 2 | 0.553 |
| All accepted segments | 222.0 | 188.0 | 0.847 | 2 | 0.563 |
| Non-airborne segments | 312.1 | 275.0 | 0.881 | 2 | 0.859 |
| Route low-dir-speed segments | 141.0 | 71.4 | 0.507 | 2 |  |
| Route WATER_PATH segments | 95.3 | 98.2 | 1.030 | 1 |  |

## Probe Activation

- Samples with probe state: `195`
- Transition-active samples: `127`
- Transition-active ratio: `0.651`

| Run | Player | Samples | Active samples | Active ratio | Active scales |
|---|---|---:|---:|---:|---|
| `20260606T161101Z` | `/ bro` | 109 | 55 | 0.505 | `[1.25]` |
| `20260606T161101Z` | `/ goldenboy` | 86 | 72 | 0.837 | `[1.25]` |

## Cadence

| Axis | Reference range | S7j bot range | Relation |
|---|---:|---:|---|
| Cadence/active min | 40.4-51.0 | 27.7-82.3 | `mixed_bot_relation` |
| Cadence/non-low-speed min | 48.7-61.3 | 36.3-113.9 | `mixed_bot_relation` |
| Cadence/air-proxy min | 128.0-143.1 | 153.2-215.9 | `all_bots_above_reference_range` |

## Stop Conditions

| Condition | Status | Details |
|---|---|---|
| `missing_required_reporting` | `pass` | `{'missing_buckets': [], 'missing_cadence_axes': []}` |
| `probe_activation_reporting` | `pass` | `{'sample_count': 195, 'transition_active_count': 127, 'transition_active_ratio': 0.651}` |
| `all_segment_proxy_win` | `pass` | `{'all_segments_improved': False, 'air_transition_buckets_improved': ['pre_air_window_segments', 'airborne_proxy_segments', 'post_air_window_segments']}` |
| `air_transition_regression` | `pass` | `{'regressed_buckets': [], 'tolerance_ratio': 0.95}` |
| `non_airborne_guardrail` | `reject` | `{'ratio_to_s7g_baseline': 0.881, 'tolerance_ratio': 0.95}` |
| `water_path_guardrail` | `pass` | `{'ratio_to_s7g_baseline': 1.03, 'current_bot_player_count': 1, 'tolerance_ratio': 0.95}` |
| `cadence_still_diagnostic` | `pass` | `{'reported_axes': ['jump_cadence_per_min', 'jump_cadence_per_non_low_speed_min', 'jump_cadence_per_airborne_proxy_min'], 'note': 'Cadence remains reporting-only; it is not a success criterion for S7j.'}` |

## Decision

- Verdict: `air_transition_probe_rejected_by_s7i_stop_conditions`
- Air-transition buckets improved: `['pre_air_window_segments', 'airborne_proxy_segments', 'post_air_window_segments']`
- Failed stop conditions: `['non_airborne_guardrail']`
- Inconclusive stop conditions: `[]`
- Reason: S7j produced evidence, but stop conditions failed: non_airborne_guardrail.
- Next goal: S7k should inspect the failed bucket and command/probe activation context before trying another controller probe.
