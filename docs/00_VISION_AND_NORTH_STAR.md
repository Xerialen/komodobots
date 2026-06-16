# Vision and North Star

## Why this project exists

Komodobots exists to investigate whether QuakeWorld bots can become sufficiently realistic to serve as believable stand-ins for real players.

The project is NOT primarily about:

- bunnyjumping
- DM2
- Frogbots
- route files
- machine learning

Those are tools and experiments.

## Two possible futures

### FantasyQuake

Draft players.
Rate players.
Simulate matches.
Run seasons.

### Megalodon Milton

Learn individual players.
Recreate their behaviour.
Simulate hypothetical player matchups.
Create digital versions of historical and concurrent players.

## Shared foundation

Both futures require:

Bunnyjumping -> Movement Realism -> Player Realism -> Simulation Realism

## Current focus

The largest visible gap today is movement.

The largest visible gap inside movement is bunnyjumping.

Therefore the first laboratory objective is to understand whether KTX/Frogbots can support a replacement or enhanced movement brain while preserving engine-native QuakeWorld behaviour.

## Decision Point Alpha

A future milestone will decide whether the project primarily continues toward FantasyQuake or toward player-specific simulation (Megalodon Milton).

That decision should be driven by evidence produced by the laboratory, not by assumptions.

**Update (2026-06-14): Alpha taken provisionally → Megalodon Milton first**, on the evidence of the
ztricks and dm3 movement breakthroughs. The program of record is `references/12_DM3_4ON4_STANDIN_PROGRAM.md`
(a learned individual brain for a live 4on4 DM3 stand-in); the decision record and revisit conditions
are in `docs/08_DECISION_LOG.md`.
