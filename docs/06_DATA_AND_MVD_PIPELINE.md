# Data and MVD Pipeline

Status: living document.

## Purpose

This document explains what data Komodobots expects to get from QuakeWorld demos, what it cannot get, and how bot-generated MVDs should be compared against human MVDs.

## Core principle

Use MVD-derived evidence to measure movement realism.

Do not rely on visual vibes alone.

## Important limitation

MVDs are server-side recordings of game state and events.

They generally do not provide normal player input/usercmd streams such as exact key presses, mouse deltas, `forwardmove`, `sidemove`, or jump timing commands.

Therefore, learning from Milton or other elite players is not simple supervised learning from button labels.

The likely problem is inverse control:

Observed movement trace -> infer or optimize a legal command policy that produces similar movement inside the real server loop.

## Available or expected signals

From `mvd_analyzer`, `qw-sim`, and related parsers, Komodobots expects to work with:

- player positions over time
- derived velocity
- view angles / aim where available
- health / armor / weapon state
- powerup state
- item pickups
- weapon pickups
- damage events
- frag events
- location trails
- loc graph transitions
- region control summaries
- map entities
- KTX scoreboard/demo info

## First movement metrics

For DM2 big-room bunnyjump lab work, start with:

- horizontal speed average
- horizontal speed max
- speed gain over time
- airborne time ratio
- inferred jump rhythm
- direction/yaw change rhythm if available
- stuck or near-stationary time
- time spent in target area
- route or area exits

## Human comparison sets

Preferred order:

1. Clean human DM2 MVDs.
2. Elite DM2 MVDs.
3. Milton DM2 MVDs.
4. Bot-generated MVDs.

Milton is the long-term player-specific reference, but the first lab may use any clean DM2 movement data to validate the analysis pipeline.

## Bot-generated MVD loop

Target loop:

1. Run KTX/MVDSV headlessly.
2. Load stock DM2.
3. Spawn Frogbot or test bot.
4. Run fixed-duration movement experiment.
5. Record MVD.
6. Parse MVD with `mvd_analyzer` and/or `qw-sim`.
7. Generate metrics and report.
8. Append findings to `docs/07_FINDINGS_LOG.md`.

## Open questions

- Which exact parser output should be canonical for movement metrics?
- Can `qw-sim` already compute all required movement metrics?
- Where will human reference MVDs live?
- How should generated MVD artifacts be stored without bloating Git?
- Can bot experiments be made deterministic enough for regression testing?
