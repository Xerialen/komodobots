# Human MVD S5a-milton-dm3 Summary

## Demo

- Run: `s5a-milton-dm3-blue-vs-anza-20260602-2022`
- Demo: `4on4_blue_vs_anza[dm3]20260602-2022.mvd`
- Kind: `4on4`
- Map: `dm3`
- Match title: `The Abandoned Base`
- Duration: `1200013` ms
- Frags: `4`
- SHA-256: `9ca8f72b3afa95ba87830a83478c51bb9b3dd626b733190a4ca2d84b4d66490e`

## Inventory Context

- Inventory root: `C:\Users\benya\projects\quakeworld\komodobots\artifacts\human-demos\source`
- Local demos inventoried: `3`
- Local DM2 filename candidates: `1`
- Inventory map inference: `filename_token_heuristic`
- Ignored named slots: `0` (active < 1s, samples < 10, or distance < 100qu)

## Movement Players

| Player | Samples | Active s | Avg | P95 | Max | Stationary | Low | Air | Cadence/min |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `rghst` | 85701 | 1198.609 | 248.5 | 456.0 | 1955.2 | 14.0% | 20.5% | 34.5% | 43.9 |
| `fateful` | 85701 | 1198.727 | 267.4 | 482.9 | 1312.1 | 11.0% | 19.9% | 31.4% | 41.2 |
| `Milton` | 85701 | 1199.415 | 314.2 | 535.0 | 1025.7 | 5.9% | 12.4% | 35.1% | 44.9 |
| `Anza  (FU)` | 85701 | 1198.473 | 256.9 | 447.4 | 1430.1 | 9.6% | 16.5% | 32.7% | 40.5 |
| `niomic` | 85701 | 1199.103 | 292.9 | 503.8 | 1126.7 | 9.8% | 16.8% | 31.0% | 43.5 |
| `splif` | 85701 | 1198.513 | 261.3 | 486.7 | 1949.7 | 14.5% | 21.6% | 33.4% | 43.3 |
| `ToT_Oddjob` | 85701 | 1198.500 | 278.5 | 514.0 | 1468.4 | 12.9% | 20.2% | 32.4% | 42.6 |
| `gflip` | 85701 | 1198.528 | 296.2 | 496.9 | 1142.9 | 7.4% | 14.2% | 37.2% | 51.9 |

## S3g Comparison Context

- Bot summary: `C:\Users\benya\projects\quakeworld\komodobots\experiments\ktx_moveprobe\evidence\moveprobe-s3g-summary.json`
- Bot maps: `dm3, frobodm2`
- Same-map comparable: `True`
- Verdict: `same_map_human_reference_available`

This is map-matched to at least one S3g bot run and can seed a small comparison.

## Same-Map Movement Comparison

Single-demo, same-map descriptive comparison only; it anchors S3g metrics against human movement ranges but is not a realism verdict.

| Metric | Human min | Human mean | Human max | Bot min | Bot mean | Bot max |
|---|---:|---:|---:|---:|---:|---:|
| Avg | 248.5 | 277.0 | 314.2 | 190.1 | 219.2 | 248.2 |
| P95 | 447.4 | 490.3 | 535.0 | 361.0 | 368.1 | 375.3 |
| Stationary | 5.9% | 10.6% | 14.5% | 0.4% | 1.5% | 2.5% |
| Low | 12.4% | 17.8% | 21.6% | 18.9% | 22.5% | 26.1% |
| Air | 31.0% | 33.5% | 37.2% | 24.8% | 34.5% | 44.2% |

| Bot | Avg | Avg range | P95 | P95 range | Stationary | Stationary range | Low | Low range | Air | Air range |
|---|---:|---|---:|---|---:|---|---:|---|---:|---|
| `/ bro` | 190.1 | `below_human_min` | 361.0 | `below_human_min` | 0.4% | `below_human_min` | 26.1% | `above_human_max` | 44.2% | `above_human_max` |
| `/ goldenboy` | 248.2 | `below_human_min` | 375.3 | `below_human_min` | 2.5% | `below_human_min` | 18.9% | `within_human_range` | 24.8% | `below_human_min` |