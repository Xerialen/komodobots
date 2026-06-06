# Human MVD S5b-carapace-dm3 Summary

## Demo

- Run: `s5b-carapace-dm3-book-vs-s-20260526-2011`
- Demo: `4on4_book_vs_-s-[dm3]20260526-2011.mvd`
- Kind: `4on4`
- Map: `dm3`
- Match title: `The Abandoned Base`
- Duration: `1199998` ms
- Frags: `4`
- SHA-256: `45f653c08fbb5488e2619a24ee0dd71347316e60265b8e4caaff0f3607ce0f30`

## Inventory Context

- Inventory root: `C:\Users\benya\projects\quakeworld\komodobots\artifacts\human-demos\source`
- Local demos inventoried: `5`
- Local DM2 filename candidates: `1`
- Inventory map inference: `filename_token_heuristic`
- Ignored named slots: `0` (active < 1s, samples < 10, or distance < 100qu)

## Movement Players

| Player | Samples | Active s | Avg | P95 | Max | Stationary | Low | Air | Cadence/min |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `Milton` | 85646 | 1199.419 | 286.7 | 498.0 | 1375.8 | 12.1% | 18.7% | 24.9% | 35.9 |
| `andeh` | 85646 | 1198.886 | 264.8 | 508.4 | 1418.4 | 13.7% | 22.1% | 28.8% | 37.9 |
| `wimsuit` | 85646 | 1199.271 | 281.7 | 468.8 | 2195.1 | 7.7% | 14.9% | 23.6% | 32.3 |
| `carapace` | 85646 | 1198.701 | 282.8 | 524.9 | 1500.8 | 11.5% | 19.6% | 34.2% | 44.0 |
| `Javve` | 85646 | 1198.885 | 291.8 | 508.1 | 1346.9 | 9.2% | 17.0% | 36.2% | 46.4 |
| `sae` | 85646 | 1198.882 | 290.1 | 500.1 | 1334.0 | 7.7% | 15.8% | 28.7% | 39.1 |
| `reppie` | 85646 | 1198.659 | 275.0 | 527.5 | 1690.6 | 12.9% | 22.2% | 37.5% | 51.3 |
| `bps` | 85646 | 1198.450 | 255.2 | 485.5 | 1458.8 | 12.7% | 21.9% | 30.7% | 38.9 |

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
| Avg | 255.2 | 278.5 | 291.8 | 190.1 | 219.2 | 248.2 |
| P95 | 468.8 | 502.6 | 527.5 | 361.0 | 368.1 | 375.3 |
| Stationary | 7.7% | 10.9% | 13.7% | 0.4% | 1.5% | 2.5% |
| Low | 14.9% | 19.0% | 22.2% | 18.9% | 22.5% | 26.1% |
| Air | 23.6% | 30.6% | 37.5% | 24.8% | 34.5% | 44.2% |

| Bot | Avg | Avg range | P95 | P95 range | Stationary | Stationary range | Low | Low range | Air | Air range |
|---|---:|---|---:|---|---:|---|---:|---|---:|---|
| `/ bro` | 190.1 | `below_human_min` | 361.0 | `below_human_min` | 0.4% | `below_human_min` | 26.1% | `above_human_max` | 44.2% | `above_human_max` |
| `/ goldenboy` | 248.2 | `below_human_min` | 375.3 | `below_human_min` | 2.5% | `below_human_min` | 18.9% | `within_human_range` | 24.8% | `within_human_range` |