# Human MVD S4c-dm3 Summary

## Demo

- Run: `s4c-dm3-blue-vs-red-20260426-0307`
- Demo: `4on4_blue_vs_red[dm3]20260426-0307.mvd`
- Kind: `4on4`
- Map: `dm3`
- Match title: `The Abandoned Base`
- Duration: `729226` ms
- Frags: `4`
- SHA-256: `6897a00a4c185751ac82c579c091437cc5b82701df14cc2178da4792924ad4fe`

## Inventory Context

- Inventory root: `C:\Users\benya\projects\quakeworld\komodobots\artifacts\human-demos\source`
- Local demos inventoried: `2`
- Local DM2 filename candidates: `1`
- Inventory map inference: `filename_token_heuristic`
- Ignored named slots: `0` (active < 1s, samples < 10, or distance < 100qu)

## Movement Players

| Player | Samples | Active s | Avg | P95 | Max | Stationary | Low | Air | Cadence/min |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `Flynn` | 52865 | 728.796 | 301.7 | 503.7 | 2045.4 | 8.1% | 15.0% | 25.4% | 35.4 |
| `evalcat` | 52865 | 728.615 | 306.1 | 515.2 | 1824.0 | 6.1% | 12.6% | 32.5% | 42.1 |
| `cronus` | 52865 | 728.761 | 290.0 | 483.2 | 2109.8 | 10.2% | 16.8% | 24.0% | 32.6 |
| `Aus` | 52865 | 728.611 | 289.3 | 495.9 | 2260.1 | 10.8% | 17.2% | 26.3% | 36.2 |
| `BLooD_DoG(D_P)` | 52865 | 728.728 | 333.5 | 513.1 | 2434.5 | 3.5% | 9.1% | 39.6% | 53.7 |
| `Buns Ranger` | 52865 | 728.225 | 278.6 | 452.8 | 2485.8 | 5.9% | 13.1% | 33.8% | 42.4 |
| `Schotty` | 52865 | 728.675 | 235.4 | 390.5 | 2264.9 | 13.0% | 21.0% | 21.9% | 23.6 |
| `george` | 52865 | 728.349 | 249.8 | 504.0 | 1904.2 | 21.1% | 28.6% | 31.9% | 39.0 |

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
| Avg | 235.4 | 285.5 | 333.5 | 190.1 | 219.2 | 248.2 |
| P95 | 390.5 | 482.3 | 515.2 | 361.0 | 368.1 | 375.3 |
| Stationary | 3.5% | 9.8% | 21.1% | 0.4% | 1.5% | 2.5% |
| Low | 9.1% | 16.7% | 28.6% | 18.9% | 22.5% | 26.1% |
| Air | 21.9% | 29.4% | 39.6% | 24.8% | 34.5% | 44.2% |

| Bot | Avg | Avg range | P95 | P95 range | Stationary | Stationary range | Low | Low range | Air | Air range |
|---|---:|---|---:|---|---:|---|---:|---|---:|---|
| `/ bro` | 190.1 | `below_human_min` | 361.0 | `below_human_min` | 0.4% | `below_human_min` | 26.1% | `within_human_range` | 44.2% | `above_human_max` |
| `/ goldenboy` | 248.2 | `within_human_range` | 375.3 | `below_human_min` | 2.5% | `below_human_min` | 18.9% | `within_human_range` | 24.8% | `within_human_range` |