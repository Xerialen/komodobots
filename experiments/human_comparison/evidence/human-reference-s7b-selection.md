# S7b Exact-Player Repeat Selection

## Source

- Stats DB: `qw-stats-xerialen` Turso `player_games` / `games` metadata
- Manifest: `servexeri:/mnt/usb-ssd/4on4-corpus/manifest.tsv`
- Demo root: `servexeri:/mnt/usb-ssd/4on4-corpus/demos`
- Vault guidance: avoid hub mass-downloads; use the existing 4on4 corpus.

## Criteria

- exact player_name match in Turso player_games
- mode='4on4'
- map='dm3' for S3g/S5b/S7a comparability
- duration >= 1100 seconds
- sha256 exists in the existing 4on4 corpus manifest
- basename does not contain tmp
- newest eligible row per target player excluding any demo already used in the S5/S5b aggregate
- no hub download and no bulk content scan

## Selected Repeats

| Player | Metadata rows | Manifest eligible | Additional available | Selected demo | Date | Frags | Deaths | SHA-256 |
|---|---:|---:|---:|---|---|---:|---:|---|
| `Milton` | 265 | 30 | 28 | `4on4_blue_vs_red[dm3]20260601-1914.mvd` | `2026-06-01 19:34:29 +0000` | 99 | 24 | `9acddc0807f9` |
| `carapace` | 172 | 22 | 21 | `4on4_-s-_vs_]sr[[dm3]20260520-2032.mvd` | `2026-05-20 20:52:58 +0000` | 87 | 19 | `2eed3c5acf9c` |
| `yeti` | 439 | 17 | 16 | `4on4_red_vs_blue[dm3]20260528-2109.mvd` | `2026-05-28 21:29:50 +0930` | 87 | 16 | `fa3792df611f` |

## Notes

- Each selected local copy was verified against the manifest SHA-256 before parsing.
- Raw demos and parser outputs remain ignored under `artifacts/human-demos/`.
