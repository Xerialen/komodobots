# Milton S5a Selection

## Source

- Stats DB: `qw-stats-xerialen` Turso `player_games` / `games` metadata
- Manifest: `servexeri:/mnt/usb-ssd/4on4-corpus/manifest.tsv`
- Demo root: `servexeri:/mnt/usb-ssd/4on4-corpus/demos`
- thevault note: prefer this existing corpus and avoid mass-downloads from `hub.quakeworld.nu`

## Metadata Method

- Player rows: exact player-name matches in Turso `player_games` where `mode='4on4'`
- Corpus cross-reference: `games.sha256` / `player_games.sha256` must exist in the existing 4on4 corpus manifest
- Bounded query: inspect the latest `500` 4on4 rows per target player before manifest/map filtering

## Target Player Counts

| Player | Total 4on4 rows | Latest-500 manifest hits | DM3 hits | DM2 hits |
|---|---:|---:|---:|---:|
| `Milton` | 1240 | 96 | 23 | 19 |
| `carapace` | 712 | 68 | 14 | 13 |
| `_ ParadokS` | 1729 | 55 | 11 | 10 |
| `yeti` | 1518 | 60 | 17 | 17 |
| `ok98` | 1326 | 59 | 13 | 19 |

## Selected Demo

- Basename: `4on4_blue_vs_anza[dm3]20260602-2022.mvd`
- Remote path: `/mnt/usb-ssd/4on4-corpus/demos/4on4_blue_vs_anza[dm3]20260602-2022.mvd`
- Local artifact path: `artifacts/human-demos/source/4on4_blue_vs_anza[dm3]20260602-2022.mvd`
- SHA-256: `9ca8f72b3afa95ba87830a83478c51bb9b3dd626b733190a4ca2d84b4d66490e`
- Size: `14359909` bytes
- Player row: `Milton`, team `anza`, map `dm3`, date `2026-06-02 20:42:16 +0000`
- Player stats: `118` frags, `18` deaths
- Match: `blue` vs `anza`, score `133`-`261`, duration `1200` s
- Server: `Berlin KTX Server antilag #4`

Selection criteria: exact `Milton` player row, 4on4, `dm3` for S3g/S4c
comparability, SHA present in the existing corpus manifest, latest
manifest-matched `dm3` candidate, no hub download, and no bulk content scan.
