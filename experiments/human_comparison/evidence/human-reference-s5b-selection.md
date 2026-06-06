# Reference Aggregate S5b Selection

## Source

- Stats DB: `qw-stats-xerialen` Turso `player_games` / `games` metadata
- Manifest: `servexeri:/mnt/usb-ssd/4on4-corpus/manifest.tsv`
- Demo root: `servexeri:/mnt/usb-ssd/4on4-corpus/demos`
- thevault note: prefer this existing corpus and avoid mass-downloads from `hub.quakeworld.nu`

## Selection Criteria

- Exact `player_name` match in Turso `player_games`
- `mode='4on4'`
- `map='dm3'` for S3g/S4c/S5a comparability
- `duration >= 1100` seconds
- SHA-256 exists in the existing 4on4 corpus manifest
- Basename does not contain `tmp`
- Newest eligible row per target player
- No hub download and no bulk content scan

## Selected Targets

| Target | Demo | Date | Team | F/D | SHA-256 |
|---|---|---|---|---:|---|
| `Milton` | `4on4_blue_vs_anza[dm3]20260602-2022.mvd` | `2026-06-02 20:42:16 +0000` | `anza` | `118/18` | `9ca8f72b3afa` |
| `carapace` | `4on4_book_vs_-s-[dm3]20260526-2011.mvd` | `2026-05-26 20:31:44 +0000` | `-s-` | `32/66` | `45f653c08fbb` |
| `yeti` | `4on4_red_vs_blue[dm3]20260530-0322.mvd` | `2026-05-30 03:43:08 +0000` | `red` | `87/25` | `adedb2eccb86` |

These three rows form a deliberately tiny S5b exact-player `dm3` aggregate. It
is large enough to avoid tuning against a single Milton match, but still small
enough to keep the experiment reversible and reviewable.
