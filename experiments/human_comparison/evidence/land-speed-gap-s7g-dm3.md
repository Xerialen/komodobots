# Land-Speed Gap Characterization s7g-land-speed-gap-dm3

## Scope

- Map: `dm3`
- Source S7f evidence: `experiments/human_comparison/evidence/airborne-segments-s7f-dm3.json`
- Reference players: `6`
- Bot rows: `6`
- Transition window: `400` ms
- Command match margin: `150` ms
- S7g reuses the S7f exact-player and unchanged mode-7 bot rows, then buckets accepted movement segments by airborne-proxy overlap, pre/post-air transition windows, sampled moveprobe command strength, and route-state hints when available.

## Group Comparison

Group values are player-level p50 segment speeds summarized across players/rows, so one long human trace does not dominate.

| Segment bucket | Reference p50 | Bot p50 | Bot/ref p50 |
|---|---:|---:|---:|
| All accepted segments | 334.0 | 222.0 | 0.665 |
| Airborne-proxy segments | 433.8 | 122.6 | 0.283 |
| Non-airborne segments | 320.0 | 312.1 | 0.975 |
| Pre-air window | 418.0 | 207.1 | 0.495 |
| Post-air window | 365.7 | 184.5 | 0.505 |
| Sampled strong-command segments |  | 211.1 |  |
| Sampled weak-command segments |  | 285.4 |  |
| Route low-dir-speed segments |  | 141.0 |  |
| Route WATER_PATH segments |  | 95.3 |  |

## Bot Route Context

| Player | Run | Strong-command p50 | Low-dir-speed p50 | WATER_PATH p50 |
|---|---|---:|---:|---:|
| `/ bro` | `20260606T003718Z` | 115.2 |  |  |
| `/ goldenboy` | `20260606T003718Z` | 306.9 |  |  |
| `/ bro` | `20260606T031102Z` | 96.9 | 94.6 | 96.0 |
| `/ goldenboy` | `20260606T031102Z` | 321.4 | 322.2 |  |
| `/ bro` | `20260606T041805Z` | 106.8 | 96.0 | 94.6 |
| `/ goldenboy` | `20260606T041805Z` | 318.8 | 186.1 |  |

## Decision

- Verdict: `land_speed_gap_concentrates_around_air_transitions_and_route_low_dir_speed`
- Airborne p50 ratio: `0.283`
- Pre-air p50 ratio: `0.495`
- Post-air p50 ratio: `0.505`
- Non-air p50 ratio: `0.975`
- Route WATER_PATH bot p50 speed: `95.279` qu/s
- Reason: The broad all-segment speed gap is not equally distributed. Bot non-airborne p50 speed is close to the exact-player non-airborne p50, but bot pre-air, airborne, and post-air windows are far below reference speed. Route-state samples also expose very slow WATER_PATH/low-dir-speed spans, so the next controller evidence should target speed production around air transitions and route primitives rather than cadence.
- Next goal: S7h should decide whether the first controller probe targets air-transition horizontal speed production or a narrow route primitive such as WATER_PATH low-dir-speed recovery.
