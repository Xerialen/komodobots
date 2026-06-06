# Human MVD S5b-yeti-dm3 Summary

## Demo

- Run: `s5b-yeti-dm3-red-vs-blue-20260530-0322`
- Demo: `4on4_red_vs_blue[dm3]20260530-0322.mvd`
- Kind: `4on4`
- Map: `dm3`
- Match title: `The Abandoned Base`
- Duration: `1200062` ms
- Frags: `4`
- SHA-256: `adedb2eccb861ebbc96f551fc21c738dc8740ecd327ea11990ede2802f83aff7`

## Inventory Context

- Inventory root: `C:\Users\benya\projects\quakeworld\komodobots\artifacts\human-demos\source`
- Local demos inventoried: `5`
- Local DM2 filename candidates: `1`
- Inventory map inference: `filename_token_heuristic`
- Ignored named slots: `0` (active < 1s, samples < 10, or distance < 100qu)

## Movement Players

| Player | Samples | Active s | Avg | P95 | Max | Stationary | Low | Air | Cadence/min |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `cronus` | 86508 | 1199.204 | 285.1 | 473.8 | 1215.7 | 10.1% | 16.7% | 28.8% | 38.2 |
| `!_!` | 86508 | 1198.556 | 261.8 | 536.1 | 2057.0 | 14.6% | 22.4% | 34.9% | 41.1 |
| `viag` | 86508 | 1199.248 | 272.3 | 503.7 | 1966.2 | 11.3% | 19.4% | 31.8% | 42.0 |
| `yeti` | 86508 | 1199.353 | 291.5 | 505.8 | 2187.7 | 7.5% | 15.4% | 35.9% | 48.6 |
| `Schotty` | 86508 | 1198.808 | 250.2 | 392.9 | 2137.3 | 9.2% | 17.6% | 24.1% | 29.3 |
| `evalcat` | 86508 | 1198.996 | 281.8 | 502.0 | 2051.2 | 10.4% | 16.1% | 30.4% | 40.2 |
| `@_@` | 86508 | 1199.049 | 253.5 | 475.2 | 1390.6 | 17.8% | 25.0% | 33.7% | 38.4 |
| `BLooD_DoG(D_P)` | 86508 | 1198.610 | 289.0 | 500.3 | 1335.5 | 11.7% | 18.3% | 32.2% | 42.6 |

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
| Avg | 250.2 | 273.2 | 291.5 | 190.1 | 219.2 | 248.2 |
| P95 | 392.9 | 486.2 | 536.1 | 361.0 | 368.1 | 375.3 |
| Stationary | 7.5% | 11.6% | 17.8% | 0.4% | 1.5% | 2.5% |
| Low | 15.4% | 18.9% | 25.0% | 18.9% | 22.5% | 26.1% |
| Air | 24.1% | 31.5% | 35.9% | 24.8% | 34.5% | 44.2% |

| Bot | Avg | Avg range | P95 | P95 range | Stationary | Stationary range | Low | Low range | Air | Air range |
|---|---:|---|---:|---|---:|---|---:|---|---:|---|
| `/ bro` | 190.1 | `below_human_min` | 361.0 | `below_human_min` | 0.4% | `below_human_min` | 26.1% | `above_human_max` | 44.2% | `above_human_max` |
| `/ goldenboy` | 248.2 | `below_human_min` | 375.3 | `below_human_min` | 2.5% | `below_human_min` | 18.9% | `within_human_range` | 24.8% | `within_human_range` |