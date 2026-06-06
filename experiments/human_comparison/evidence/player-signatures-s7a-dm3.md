# Player Movement Signatures s7a-player-signatures-dm3

## Scope

- Map: `dm3`
- Source aggregate: `experiments/human_comparison/evidence/human-reference-s5b-aggregate.json`
- Reference rows: `3`
- S3g bot rows: `2`
- Stop condition: `True`
- Stop reason: Only three single-demo exact-player rows are available; this can seed axes but cannot support stable player-style claims.

- S7a is a measurement scaffold, not a player-specific movement controller.
- Features marked as candidate axes are descriptive single-demo signals, not stable style claims.
- Land-speed gaps stay visible so player-specific work does not hide the unresolved bunnyhop/high-speed deficit.

## Exact-Player Signature Rows

| Player | Demo | Avg | P95 | Stationary | Low | Air | Cadence/min |
|---|---|---:|---:|---:|---:|---:|---:|
| `Milton` | `4on4_blue_vs_anza[dm3]20260602-2022.mvd` | 314.2 | 535.0 | 5.9% | 12.4% | 35.1% | 44.9 |
| `carapace` | `4on4_book_vs_-s-[dm3]20260526-2011.mvd` | 282.8 | 524.9 | 11.5% | 19.6% | 34.2% | 44.0 |
| `yeti` | `4on4_red_vs_blue[dm3]20260530-0322.mvd` | 291.5 | 505.8 | 7.5% | 15.4% | 35.9% | 48.6 |

## Feature Axes

| Metric | Reference range | Spread | S3g bot relation | Interpretation |
|---|---:|---:|---|---|
| Avg | 282.8-314.2 | 31.5 | `all_bots_below_reference_range` | `generic_human_vs_bot_land_speed_gap` |
| P95 | 505.8-535.0 | 29.2 | `all_bots_below_reference_range` | `generic_human_vs_bot_land_speed_gap` |
| Stationary | 5.9%-11.5% | 5.6% | `all_bots_below_reference_range` | `generic_human_bot_mismatch` |
| Low | 12.4%-19.6% | 7.2% | `mixed_bot_relation` | `candidate_player_style_axis_but_thin` |
| Air | 34.2%-35.9% | 1.7% | `mixed_bot_relation` | `not_yet_useful_for_player_style` |
| Cadence/min | 44.0-48.6 | 4.5 | `reference_only` | `reference_only_candidate_style_axis` |

## Headline Land-Speed Gaps

| Metric | Reference range | S3g bot range | Best bot gap to ref min |
|---|---:|---:|---:|
| Avg | 282.8-314.2 | 190.1-248.2 | 34.6 |
| P95 | 505.8-535.0 | 361.0-375.3 | 130.5 |

## Next Goal

- S7b should broaden exact-player movement references before controller work: add repeated dm3 samples for Milton/carapace/yeti where available, then rerun this signature scaffold to separate stable player style from one-match noise and the generic S3g land-speed gap.
