# Cadence Normalization Decision s7d-cadence-normalization-dm3

## Scope

- Map: `dm3`
- Source aggregate: `experiments/human_comparison/evidence/human-reference-s7c-bot-comparable-cadence-dm3-aggregate.json`
- Reference rows: `6`
- S3g bot rows: `2`
- Bot source run IDs: `20260606T003718Z`

- `jump_cadence_per_min` is already based on active movement-metrics rows (airborne_proxy_count / active_time_s * 60). S7d re-normalizes it by non-stationary time, non-low-speed time, and airborne-proxy time to test whether combat or downtime dilution changes the S7c relation.

## Normalized Cadence Axes

| Axis | Basis | Reference range | S3g bot range | Bot relation |
|---|---|---:|---:|---|
| Cadence/non-stationary min | active time excluding stationary_time_ratio | 44.2-55.6 | 44.4-92.1 | `mixed_bot_relation` |
| Cadence/non-low-speed min | active time excluding low_speed_time_ratio | 48.7-61.3 | 53.3-124.1 | `mixed_bot_relation` |
| Cadence/air-proxy min | airborne_proxy_time_ratio | 128.0-143.1 | 174.4-207.6 | `all_bots_above_reference_range` |

## Bot Rows

| Bot | Cadence/min | Non-stationary | Non-low-speed | Air-proxy |
|---|---:|---:|---:|---:|
| `/ bro` | 91.7 | 92.1 | 124.1 | 207.6 |
| `/ goldenboy` | 43.3 | 44.4 | 53.3 | 174.4 |

## Decision

- Verdict: `cadence_stays_diagnostic_not_controller_target`
- Reason: Movement-time normalization preserves the mixed bot relation, but airborne-proxy normalization puts bot cadence outside the exact-player range. A cadence controller would risk optimizing a proxy before the airborne/landing rhythm gap is understood.
- Next goal: S7e should broaden or dissect the cadence evidence before controller work: add more bot rows and/or inspect airborne-proxy segmentation so cadence can be separated from the unresolved land-speed and air-rhythm gaps.
