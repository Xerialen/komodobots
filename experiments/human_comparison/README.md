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
`aerowalk`, `e1m2`, and trick demos, but no filename-inferred `dm2` demo. That
inventory check is a filename-token heuristic, not a content parse of every local
demo. The next S4 step should find or select a real DM2 human comparison set
before judging S3g as human-like.

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

## Current S4c Result

S4c selects one map-matched human `dm3` 4on4 demo from the same existing
`servexeri` corpus:

```text
4on4_blue_vs_red[dm3]20260426-0307.mvd
```

It parses as `dm3` / `The Abandoned Base` and produces eight active 4on4 player
movement rows. The summary compares that human range against the existing S3g
`dm3` bot run `20260606T003718Z`.

This is the first direct same-map S3g-vs-human movement anchor, but it is not a
realism verdict. In this single sample, S3g is weaker than the human reference on
p95 speed for both bots; `/ bro` is also below the human average-speed range and
above the human airborne-proxy range. The next step should build a Milton/elite
reference-set inventory before training, player-specific modelling, or more
movement-command heuristics.

## Current S5a Result

S5a uses Turso `player_games` / `games` metadata cross-referenced against the
existing `servexeri` 4on4 corpus manifest. This proves exact-player reference
selection is possible without training, hub mass-downloads, or a full content
scan.

The first selected Milton reference demo is:

```text
4on4_blue_vs_anza[dm3]20260602-2022.mvd
```

It contains an exact `Milton` player row on `dm3`, parses as `The Abandoned Base`,
and produces a Milton movement row with avg `314.2` qu/s, p95 `535.0`,
stationary `5.9%`, low-speed `12.4%`, airborne proxy `35.1%`, and cadence
`44.9`/min.

This is still a single-match reference, not a style model. The next S5 step
should build a tiny aggregate from a few exact-player elite/Milton samples before
moving to S6 route primitives or S7 player-specific movement.

## Current S5b Result

S5b aggregates three exact-player `dm3` references selected by metadata:

```text
Milton   -> 4on4_blue_vs_anza[dm3]20260602-2022.mvd
carapace -> 4on4_book_vs_-s-[dm3]20260526-2011.mvd
yeti     -> 4on4_red_vs_blue[dm3]20260530-0322.mvd
```

The aggregate range is intentionally tiny but no longer a single-match target:

| Metric | Reference range | S3g bot range |
|---|---:|---:|
| Avg | `282.8-314.2` | `190.1-248.2` |
| P95 | `505.8-535.0` | `361.0-375.3` |
| Low | `12.4%-19.6%` | `18.9%-26.1%` |
| Air | `34.2%-35.9%` | `24.8%-44.2%` |

This points away from more command-value tuning and toward S6 route/state
diagnosis: the current bot command projection can emit bounded movement, but the
result is not sustaining elite-like high-speed movement on `dm3`.

## Current S7a Result

S7a turns the S5b aggregate into a small movement-signature scaffold:

```text
experiments/human_comparison/evidence/player-signatures-s7a-dm3.json
experiments/human_comparison/evidence/player-signatures-s7a-dm3.md
```

The scaffold separates broad bot-vs-human movement deficits from possible
player-specific axes:

| Axis | S7a interpretation |
|---|---|
| Avg speed | generic S3g-vs-human land-speed gap |
| P95 speed | generic S3g-vs-human land-speed gap |
| Low-speed ratio | candidate style axis, but too thin |
| Jump cadence | reference-only candidate axis |

The stop condition is triggered because the current set is only one `dm3` demo
per target player. S7 should broaden exact-player references before any
player-specific movement controller work.
