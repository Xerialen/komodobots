# Human DM3 S4c Selection

## Source

- Host: `servexeri`
- Manifest: `/mnt/usb-ssd/4on4-corpus/manifest.tsv`
- Demo root: `/mnt/usb-ssd/4on4-corpus/demos`
- thevault note: prefer this existing corpus and avoid mass-downloads from `hub.quakeworld.nu`

## Remote Inventory Counts

- Manifest rows: `6409`
- Exact `[dm3]` rows: `1663`
- `4on4_` exact `[dm3]` rows: `1629`
- Cleanish 4on4 DM3 rows, excluding `tmp` and missing files: `1247`
- Moderate-size 2026 cleanish 4on4 DM3 rows: `444`

## Selected Demo

- Basename: `4on4_blue_vs_red[dm3]20260426-0307.mvd`
- Remote path: `/mnt/usb-ssd/4on4-corpus/demos/4on4_blue_vs_red[dm3]20260426-0307.mvd`
- Local artifact path: `artifacts/human-demos/source/4on4_blue_vs_red[dm3]20260426-0307.mvd`
- SHA-256: `6897a00a4c185751ac82c579c091437cc5b82701df14cc2178da4792924ad4fe`
- Size: `7632722` bytes

Selection criteria: existing corpus file, no hub download; basename starts with
`4on4_`; basename contains exact `[dm3]`; basename does not contain `tmp`; file
exists under the corpus demo root; single moderate-size 2026 demo for the first
same-map S3g comparison.
