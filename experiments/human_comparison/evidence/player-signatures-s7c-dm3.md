# Player Movement Signatures s7c-player-signatures-dm3

## Scope

- Map: `dm3`
- Source aggregate: `experiments/human_comparison/evidence/human-reference-s7c-bot-comparable-cadence-dm3-aggregate.json`
- Reference rows: `6`
- S3g bot rows: `2`
- Bot source run IDs: `20260606T003718Z`
- Stop condition: `False`
- Stop reason: Reference set has enough repeated rows to start checking player-style stability.

- S7a is a measurement scaffold, not a player-specific movement controller.
- Features marked as candidate axes are descriptive single-demo signals, not stable style claims.
- Land-speed gaps stay visible so player-specific work does not hide the unresolved bunnyhop/high-speed deficit.

## Exact-Player Signature Rows

| Player | Demo | Avg | P95 | Stationary | Low | Air | Cadence/min |
|---|---|---:|---:|---:|---:|---:|---:|
| `Milton` | `4on4_blue_vs_anza[dm3]20260602-2022.mvd` | 314.2 | 535.0 | 5.9% | 12.4% | 35.1% | 44.9 |
| `Milton` | `4on4_blue_vs_red[dm3]20260601-1914.mvd` | 306.4 | 524.9 | 8.5% | 15.6% | 30.8% | 42.0 |
| `carapace` | `4on4_book_vs_-s-[dm3]20260526-2011.mvd` | 282.8 | 524.9 | 11.5% | 19.6% | 34.2% | 44.0 |
| `carapace` | `4on4_-s-_vs_]sr[[dm3]20260520-2032.mvd` | 295.3 | 508.9 | 8.7% | 17.1% | 28.2% | 40.4 |
| `yeti` | `4on4_red_vs_blue[dm3]20260530-0322.mvd` | 291.5 | 505.8 | 7.5% | 15.4% | 35.9% | 48.6 |
| `yeti` | `4on4_red_vs_blue[dm3]20260528-2109.mvd` | 301.3 | 514.0 | 8.3% | 16.8% | 36.0% | 51.0 |

## Feature Axes

| Metric | Reference range | Spread | S3g bot relation | Interpretation |
|---|---:|---:|---|---|
| Avg | 282.8-314.2 | 31.5 | `all_bots_below_reference_range` | `generic_human_vs_bot_land_speed_gap` |
| P95 | 505.8-535.0 | 29.2 | `all_bots_below_reference_range` | `generic_human_vs_bot_land_speed_gap` |
| Stationary | 5.9%-11.5% | 5.6% | `all_bots_below_reference_range` | `generic_human_bot_mismatch` |
| Low | 12.4%-19.6% | 7.2% | `mixed_bot_relation` | `candidate_player_style_axis_but_thin` |
| Air | 28.2%-36.0% | 7.8% | `mixed_bot_relation` | `candidate_player_style_axis_but_thin` |
| Cadence/min | 40.4-51.0 | 10.6 | `mixed_bot_relation` | `candidate_player_style_axis_but_thin` |

## Repeated-Player Stability

| Metric | Repeated players | Between-player mean spread | Max within-player spread | Separation ratio | Stability interpretation |
|---|---:|---:|---:|---:|---|
| Avg | 3 | 21.3 | 12.6 | 1.69 | `stable_but_generic_land_speed_gap` |
| P95 | 3 | 20.0 | 16.0 | 1.25 | `stable_but_generic_land_speed_gap` |
| Stationary | 3 | 2.9% | 2.8% | 1.04 | `mixed_or_overlap_repeated_axis` |
| Low | 3 | 4.3% | 3.2% | 1.34 | `mixed_or_overlap_repeated_axis` |
| Air | 3 | 4.7% | 6.0% | 0.78 | `mixed_or_overlap_repeated_axis` |
| Cadence/min | 3 | 7.6 | 3.7 | 2.06 | `repeated_candidate_style_axis` |

## Headline Land-Speed Gaps

| Metric | Reference range | S3g bot range | Best bot gap to ref min |
|---|---:|---:|---:|
| Avg | 282.8-314.2 | 190.1-248.2 | 34.6 |
| P95 | 505.8-535.0 | 361.0-375.3 | 130.5 |

## Next Goal

- S7d should decide what to do with the bot-comparable repeated axes: keep cadence as a diagnostic target, broaden exact-player/bot samples, or design a tiny controller probe, while keeping the generic land-speed gap visible.
