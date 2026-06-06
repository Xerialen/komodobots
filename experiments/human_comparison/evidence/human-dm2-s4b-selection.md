# Human DM2 S4b Selection

## Source

- Host: `servexeri`
- Manifest: `/mnt/usb-ssd/4on4-corpus/manifest.tsv`
- Demo root: `/mnt/usb-ssd/4on4-corpus/demos`
- Vault rule: `thevault/quakeworld/mvds.md` says to avoid mass-downloads from `hub.quakeworld.nu` and prefer this existing corpus.

## Corpus Counts

| Filter | Count |
|---|---:|
| Manifest rows | 6409 |
| Rows containing `[dm2]` | 1598 |
| Rows starting `4on4_` and containing `[dm2]` | 1450 |
| Cleanish 4on4 DM2 rows, excluding `tmp` and missing files | 1171 |

## Selection Criteria

- Existing corpus file; no hub download.
- Basename starts with `4on4_`.
- Basename contains `[dm2]`.
- Basename does not contain `tmp`.
- File exists under the corpus demo root.
- Single moderate-size 2026 demo for the first parse.

## Selected Demo

| Field | Value |
|---|---|
| SHA-256 | `f8269d8139b129426b569eaf6b2be278964d740bd0365647f4410db74da76585` |
| Size | `8624854` bytes |
| Basename | `4on4_blue_vs_red[dm2]20260228-0512.mvd` |
| Remote path | `/mnt/usb-ssd/4on4-corpus/demos/4on4_blue_vs_red[dm2]20260228-0512.mvd` |
| Local artifact path | `artifacts/human-demos/source/4on4_blue_vs_red[dm2]20260228-0512.mvd` |
