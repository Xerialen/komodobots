# Human Comparison Evidence

This folder holds small derived artifacts for S4 human-demo comparison work.

Raw human MVDs and parser outputs stay outside Git under `artifacts/human-demos/`.
Commit only compact JSON/Markdown summaries that make PR claims auditable without
checking in demos or multi-megabyte event streams.

## Current S4a Result

S4a inventories the local human demo folder:

```text
C:\Users\benya\projects\quakeworld\data\quake-development\clients\xerialqw-bench\qw\matchinfo\demos
```

It parses `1on1_reppie_vs_locust_aerowalk.mvd` through the same
`qw-analyze-v20` plus `scripts/extract_movement_metrics.py` pipeline used by bot
lab runs.

This is a parser proof, not a DM2 realism baseline. The local inventory contains
`aerowalk`, `e1m2`, and trick demos, but no inferred true `dm2` demo. The next S4
step should find or select a real DM2 human comparison set before judging S3g as
human-like.

## Current S4b Result

S4b selects one true DM2 human demo from the existing `servexeri`
`/mnt/usb-ssd/4on4-corpus/` corpus, following thevault guidance to avoid
mass-downloading from `hub.quakeworld.nu`.

The first selected demo is:

```text
4on4_blue_vs_red[dm2]20260228-0512.mvd
```

It parses as `dm2` / `Claustrophobopolis` and produces eight active 4on4 player
movement rows. This gives S4 a true-DM2 human reference file, but it is still not
map-matched to S3g because S3g evidence is on `dm3` and `frobodm2`.
