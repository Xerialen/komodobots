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
per target player. S7b below broadens exact-player references before any
player-specific movement controller work.

## Current S7b Result

S7b broadens the same target players to two `dm3` demos each:

```text
Milton   -> 4on4_blue_vs_red[dm3]20260601-1914.mvd
carapace -> 4on4_-s-_vs_]sr[[dm3]20260520-2032.mvd
yeti     -> 4on4_red_vs_blue[dm3]20260528-2109.mvd
```

These were selected from Turso metadata cross-referenced with the existing
`servexeri` 4on4 corpus manifest, copied from that corpus, and SHA-256 verified
before parsing. Raw demos and parser output remain ignored under
`artifacts/human-demos/`.

The repeated aggregate still shows the generic land-speed gap:

| Metric | Reference range | S3g bot range |
|---|---:|---:|
| Avg | `282.8-314.2` | `190.1-248.2` |
| P95 | `505.8-535.0` | `361.0-375.3` |

Repeated-player stability does not promote low-speed or airborne proxy to stable
style targets yet. Jump cadence is the only repeated candidate axis, but it is
reference-only at the S7b snapshot. S7c below carries the same cadence/tempo
metric into the committed S3g bot summary before controller work.

## Current S7c Result

S7c carries existing S3g bot cadence from the raw movement artifacts into the
committed moveprobe summary and compares it against the repeated exact-player
aggregate:

```text
experiments/human_comparison/evidence/human-reference-s7c-bot-comparable-cadence-dm3-aggregate.json
experiments/human_comparison/evidence/human-reference-s7c-bot-comparable-cadence-dm3-aggregate.md
experiments/human_comparison/evidence/player-signatures-s7c-dm3.json
experiments/human_comparison/evidence/player-signatures-s7c-dm3.md
```

The repeated exact-player cadence range is `40.4-51.0`/min. S3g `/ bro` is above
that range at `91.7`/min, while `/ goldenboy` is within it at `43.3`/min.
Cadence is now a bot-comparable repeated candidate axis with mixed bot relation.

This still does not authorize a player-specific movement controller. Avg and p95
remain generic S3g-vs-human land-speed gaps, so S7d should decide whether
cadence remains diagnostic, needs broader sampling, or warrants a tiny controller
probe.

## Current S7d Result

S7d re-normalizes the S7c cadence comparison by movement and airborne-proxy time
without rerunning the lab:

```text
experiments/human_comparison/evidence/cadence-normalization-s7d-dm3.json
experiments/human_comparison/evidence/cadence-normalization-s7d-dm3.md
```

The existing `jump_cadence_per_min` field is already active-row normalized
(`airborne_proxy_count / active_time_s * 60`). S7d tests stricter denominators:
non-stationary time, non-low-speed time, and airborne-proxy time.

| Axis | Reference range | S3g bot range | Relation |
|---|---:|---:|---|
| Non-stationary cadence | `44.2-55.6`/min | `44.4-92.1`/min | mixed |
| Non-low-speed cadence | `48.7-61.3`/min | `53.3-124.1`/min | mixed |
| Air-proxy cadence | `128.0-143.1`/min | `174.4-207.6`/min | all bots above |

Movement-time normalization keeps `/ goldenboy` inside the exact-player range,
but airborne-proxy normalization puts both S3g bots above the reference range.
Cadence should therefore stay diagnostic for now. A cadence controller would
risk optimizing a proxy before the air-rhythm and land-speed gaps are understood.

## Current S7e Result

S7e broadens the bot side of the cadence evidence without rerunning the lab:

```text
experiments/human_comparison/evidence/cadence-evidence-s7e-dm3.json
experiments/human_comparison/evidence/cadence-evidence-s7e-dm3.md
```

The included bot rows come from existing unchanged `dm3` mode-7 artifacts:
`20260606T003718Z`, `20260606T031102Z`, and `20260606T041805Z`.
Run `20260606T044000Z` is excluded because S6e changed water-edge vertical
command behavior.

| Axis | Reference range | Broadened bot range | Relation |
|---|---:|---:|---|
| Active cadence | `40.4-51.0`/min | `18.5-138.7`/min | mixed |
| Non-stationary cadence | `44.2-55.6`/min | `18.6-146.6`/min | mixed |
| Non-low-speed cadence | `48.7-61.3`/min | `20.2-289.5`/min | mixed |
| Air-proxy cadence | `128.0-143.1`/min | `164.1-274.1`/min | all bots above |

S7e strengthens the S7d stop condition. Cadence remains useful as a diagnostic
axis, but it is not controller-authorizing because all unchanged mode-7 bot rows
are above the exact-player airborne-proxy cadence range while raw and
movement-time cadence remain mixed.

## Current S7f Result

S7f inspects the raw airborne-proxy segment distributions behind the S7d/S7e
cadence warning:

```text
experiments/human_comparison/evidence/airborne-segments-s7f-dm3.json
experiments/human_comparison/evidence/airborne-segments-s7f-dm3.md
```

The helper replays the existing movement-metrics airborne proxy over raw
`events.txt` kind `5` samples for the six exact-player `dm3` reference rows and
six unchanged mode-7 bot rows.

| Axis | Reference | Bot | Bot/ref p50 |
|---|---:|---:|---:|
| Player-median air duration | `325.0` ms | `217.2` ms | `0.668` |
| Player-median air Z range | `43.8` qu | `11.5` qu | `0.264` |
| Player-median air speed | `431.8` qu/s | `114.4` qu/s | `0.265` |
| Raw active avg speed | `298.3` qu/s | `219.2` qu/s | `0.735` |

The bot airborne-proxy runs are not human-like jumps. They are shorter,
lower-Z, and much slower vertical-motion runs, so cadence remains diagnostic.
The next useful step is S7g: characterize the land-speed gap around route and
air segments before another controller probe.

## Current S7g Result

S7g characterizes the land-speed gap by segment context without rerunning the
lab:

```text
experiments/human_comparison/evidence/land-speed-gap-s7g-dm3.json
experiments/human_comparison/evidence/land-speed-gap-s7g-dm3.md
```

The helper reuses the S7f exact-player and unchanged mode-7 bot rows, then
buckets accepted movement segments by airborne-proxy overlap, `400` ms pre/post
air windows, sampled moveprobe command strength, and route-state hints where
bot artifacts expose them.

| Segment bucket | Reference p50 | Bot p50 | Bot/ref p50 |
|---|---:|---:|---:|
| All accepted segments | `334.0` qu/s | `222.0` qu/s | `0.665` |
| Airborne-proxy segments | `433.8` qu/s | `122.6` qu/s | `0.283` |
| Non-airborne segments | `320.0` qu/s | `312.1` qu/s | `0.975` |
| Pre-air window | `418.0` qu/s | `207.1` qu/s | `0.495` |
| Post-air window | `365.7` qu/s | `184.5` qu/s | `0.505` |
| Route `WATER_PATH` samples | n/a | `95.3` qu/s | n/a |

The speed gap is not uniform. Generic non-airborne p50 speed is close to the
exact-player p50 in this row set, but air-transition/airborne contexts remain
far below reference and route `WATER_PATH` contexts are extremely slow. The next
useful step is S7h: choose whether the first controller probe targets
air-transition horizontal speed production or a narrow route primitive such as
`WATER_PATH` low-dir-speed recovery.

## Current S7h Result

S7h chooses the first controller-probe target from the S7g context without
rerunning the lab:

```text
experiments/human_comparison/evidence/controller-probe-target-s7h-dm3.json
experiments/human_comparison/evidence/controller-probe-target-s7h-dm3.md
```

| Candidate | Priority | Human comparable | Key evidence |
|---|---|---:|---|
| Air-transition horizontal speed production | `preferred_first_probe_target` | `true` | pre-air `0.495`, air `0.283`, post-air `0.505`, non-air `0.975` |
| Route `WATER_PATH` low-dir-speed recovery | `secondary_guardrail_target` | `false` | `WATER_PATH` `95.3` qu/s, low-dir `141.0` qu/s, route-matched segments `3,674` |

The first controller probe should target air-transition horizontal speed
production because that gap is broad and human-comparable. `WATER_PATH` remains
a guardrail and deferred narrow route target because it is very slow but
bot-only and route-diagnostic. S7i should design a tiny probe that keeps cadence
diagnostic, retains route diagnostics, and rejects all-segment speed gains if
air-transition buckets or `WATER_PATH` context get worse.

## Current S7i Result

S7i turns the S7h target into a design-only probe contract:

```text
experiments/human_comparison/evidence/air-transition-probe-design-s7i-dm3.json
experiments/human_comparison/evidence/air-transition-probe-design-s7i-dm3.md
```

The proposed follow-up probe id is
`s7i-mode8-air-transition-horizontal-speed`. S7i does not change KTX or
Frogbot behavior. The next implementation must start from mode `7`, change only
horizontal command budget during takeoff/air-transition windows, keep cadence
diagnostic, and preserve route/water logging.

Required post-probe reporting:

- pre-air, airborne, post-air, and non-airborne segment p50s,
- route low-dir-speed and `WATER_PATH` p50s,
- active, non-low-speed, and airborne-proxy cadence.

Stop conditions reject all-segment speed gains if air-transition buckets do not
improve, if non-airborne or `WATER_PATH` context regresses, or if cadence/route
reporting disappears.
