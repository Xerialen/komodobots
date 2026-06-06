# Reference Aggregate s7c-bot-comparable-cadence-dm3

## Scope

- Map: `dm3`
- Reference rows: `6`
- Targets: `Milton, Milton, carapace, carapace, yeti, yeti`
- Bot summary: `experiments/ktx_moveprobe/evidence/moveprobe-s3g-summary.json`

- Tiny exact-player reference aggregate; useful for movement-range anchoring, not a player-style model.
- Reference rows are selected by metadata before parsing; raw demos and events remain outside Git.

## Reference Rows

| Target | Demo | Avg | P95 | Stationary | Low | Air | Cadence/min |
|---|---|---:|---:|---:|---:|---:|---:|
| `Milton` | `4on4_blue_vs_anza[dm3]20260602-2022.mvd` | 314.2 | 535.0 | 5.9% | 12.4% | 35.1% | 44.9 |
| `Milton` | `4on4_blue_vs_red[dm3]20260601-1914.mvd` | 306.4 | 524.9 | 8.5% | 15.6% | 30.8% | 42.0 |
| `carapace` | `4on4_book_vs_-s-[dm3]20260526-2011.mvd` | 282.8 | 524.9 | 11.5% | 19.6% | 34.2% | 44.0 |
| `carapace` | `4on4_-s-_vs_]sr[[dm3]20260520-2032.mvd` | 295.3 | 508.9 | 8.7% | 17.1% | 28.2% | 40.4 |
| `yeti` | `4on4_red_vs_blue[dm3]20260530-0322.mvd` | 291.5 | 505.8 | 7.5% | 15.4% | 35.9% | 48.6 |
| `yeti` | `4on4_red_vs_blue[dm3]20260528-2109.mvd` | 301.3 | 514.0 | 8.3% | 16.8% | 36.0% | 51.0 |

## Aggregate Range

| Metric | Ref min | Ref mean | Ref max | Bot min | Bot mean | Bot max |
|---|---:|---:|---:|---:|---:|---:|
| Avg | 282.8 | 298.6 | 314.2 | 190.1 | 219.2 | 248.2 |
| P95 | 505.8 | 518.9 | 535.0 | 361.0 | 368.1 | 375.3 |
| Stationary | 5.9% | 8.4% | 11.5% | 0.4% | 1.5% | 2.5% |
| Low | 12.4% | 16.2% | 19.6% | 18.9% | 22.5% | 26.1% |
| Air | 28.2% | 33.4% | 36.0% | 24.8% | 34.5% | 44.2% |
| Cadence/min | 40.4 | 45.2 | 51.0 | 43.3 | 67.5 | 91.7 |

## S3g Bot Rows

| Bot | Avg | Avg range | P95 | P95 range | Stationary | Stationary range | Low | Low range | Air | Air range | Cadence/min | Cadence range |
|---|---:|---|---:|---|---:|---|---:|---|---:|---|---:|---|
| `/ bro` | 190.1 | `below_human_min` | 361.0 | `below_human_min` | 0.4% | `below_human_min` | 26.1% | `above_human_max` | 44.2% | `above_human_max` | 91.7 | `above_human_max` |
| `/ goldenboy` | 248.2 | `below_human_min` | 375.3 | `below_human_min` | 2.5% | `below_human_min` | 18.9% | `within_human_range` | 24.8% | `below_human_min` | 43.3 | `within_human_range` |
