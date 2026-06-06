# Airborne Proxy Segment Inspection s7f-airborne-segments-dm3

## Scope

- Map: `dm3`
- Source reference aggregate: `experiments/human_comparison/evidence/human-reference-s7c-bot-comparable-cadence-dm3-aggregate.json`
- Source bot evidence: `experiments/human_comparison/evidence/cadence-evidence-s7e-dm3.json`
- Reference players: `6`
- Bot rows: `6`
- S7f replays the movement-metrics airborne proxy over raw events.txt kind 5 samples, then records compact per-player distributions for the exact-player dm3 reference rows and unchanged mode-7 bot rows.

## Group Comparison

| Axis | Reference | Bot | Bot/ref p50 |
|---|---:|---:|---:|
| Player-median air duration | 325.0 | 217.2 | 0.7 |
| Player-median air Z range | 43.8 | 11.5 | 0.3 |
| Player-median air speed | 431.8 | 114.4 | 0.3 |
| Player-median pre-landing speed | 424.4 | 120.4 | 0.3 |
| Raw active avg speed | 298.3 | 219.2 | 0.7 |
| Raw segment p95 speed | 519.5 | 370.4 | 0.7 |

## Player Rows

| Group | Player | Run | Air runs | Air duration | Air Z | Air speed | Active avg | Segment p95 | Air ratio | Cadence |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `reference` | `Milton` | `s5a-milton-dm3-blue-vs-anza-20260602-2022` | 898 | 330.0 p50 / 1006.1 p95 | 43.8 p50 / 220.6 p95 | 433.3 p50 / 560.3 p95 | 314.2 | 535.0 | 35.1% | 44.9 |
| `reference` | `Milton` | `s7b-milton-dm3-blue-vs-red-20260601-1914` | 840 | 324.0 p50 / 1003.5 p95 | 43.8 p50 / 216.7 p95 | 443.0 p50 / 568.0 p95 | 306.4 | 524.9 | 30.8% | 42.0 |
| `reference` | `carapace` | `s5b-carapace-dm3-book-vs-s-20260526-2011` | 880 | 326.0 p50 / 1064.2 p95 | 43.8 p50 / 180.2 p95 | 430.3 p50 / 572.3 p95 | 282.8 | 524.9 | 34.2% | 44.0 |
| `reference` | `carapace` | `s7b-carapace-dm3-s-vs-sr-20260520-2032` | 807 | 325.0 p50 / 826.5 p95 | 43.8 p50 / 198.6 p95 | 439.4 p50 / 548.3 p95 | 295.3 | 508.9 | 28.2% | 40.4 |
| `reference` | `yeti` | `s5b-yeti-dm3-red-vs-blue-20260530-0322` | 971 | 325.0 p50 / 957.5 p95 | 43.8 p50 / 200.4 p95 | 420.7 p50 / 532.9 p95 | 291.5 | 505.8 | 35.9% | 48.6 |
| `reference` | `yeti` | `s7b-yeti-dm3-red-vs-blue-20260528-2109` | 1019 | 325.0 p50 / 858.4 p95 | 43.8 p50 / 211.6 p95 | 422.2 p50 / 535.0 p95 | 301.3 | 514.0 | 36.0% | 51.0 |
| `bot` | `/ bro` | `20260606T003718Z` | 39 | 205.0 p50 / 490.0 p95 | 5.9 p50 / 63.0 p95 | 104.1 p50 / 281.4 p95 | 190.1 | 361.0 | 44.2% | 91.7 |
| `bot` | `/ goldenboy` | `20260606T003718Z` | 14 | 229.5 p50 / 1083.2 p95 | 17.2 p50 / 129.1 p95 | 164.8 p50 / 333.7 p95 | 248.2 | 375.3 | 24.8% | 43.3 |
| `bot` | `/ bro` | `20260606T031102Z` | 59 | 200.0 p50 / 385.6 p95 | 5.4 p50 / 33.2 p95 | 97.6 p50 / 185.4 p95 | 136.3 | 359.6 | 50.6% | 138.7 |
| `bot` | `/ goldenboy` | `20260606T031102Z` | 8 | 242.5 p50 / 917.5 p95 | 24.0 p50 / 238.8 p95 | 124.6 p50 / 285.9 p95 | 285.5 | 381.3 | 15.0% | 24.6 |
| `bot` | `/ bro` | `20260606T041805Z` | 50 | 205.0 p50 / 428.2 p95 | 5.5 p50 / 26.1 p95 | 98.2 p50 / 294.4 p95 | 183.9 | 365.5 | 48.9% | 117.6 |
| `bot` | `/ goldenboy` | `20260606T041805Z` | 6 | 255.5 p50 / 445.0 p95 | 22.8 p50 / 76.0 p95 | 295.6 p50 / 330.8 p95 | 286.5 | 386.3 | 9.1% | 18.5 |

## Decision

- Verdict: `pivot_from_cadence_to_air_rhythm_and_land_speed_gap`
- Duration p50 ratio: `0.668`
- Z-delta p50 ratio: `0.264`
- Airborne-speed p50 ratio: `0.265`
- Active-speed p50 ratio: `0.735`
- Reason: Raw airborne-proxy segments are not human-like jumps: bot player-median airborne runs are shorter, much lower-Z, and much slower than the exact-player references. The high airborne-proxy-normalized cadence is therefore a symptom of broken air/land rhythm, not a controller-ready cadence target.
- Next goal: S7g should characterize the land-speed gap around route and air segments before another controller probe. Cadence should stay diagnostic until bots can produce human-scale airborne segments and horizontal speed.
