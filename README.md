# Komodobots

Komodobots is a QuakeWorld bot research lab.

The project exists to answer one larger question:

> Can QuakeWorld bots become realistic enough to act as believable substitutes for real players?

The program of record is **`docs/18_BENCH_ITERATED_BOT_PROGRAM.md`** (greenfield, 2026-06-16): a learned move+aim+decision DM3 4on4 stand-in, modeled on real elite human demos, measured on a 4v4 bench. The data that feeds it is contracted in `docs/20_DATA_CONTRACT.md`.

This repository is not primarily about making Frogbots bunnyhop. Movement (bunnyjumping) was the first visible and measurable bottleneck on the path toward realistic player and match simulation; the earlier "DM2 big room movement lab" framing in older docs is historical context, not the current plan.

## Two possible long-term destinations

Komodobots may later support either or both of these tracks:

1. **FantasyQuake** — simulated matches, seasons, drafts, and player value based on real QuakeWorld data.
2. **Megalodon Milton** — player-specific agents that try to imitate elite players, starting with Milton, from MVD-derived evidence.

Both tracks need the same foundation: believable movement, then believable player behaviour, then believable simulation.

## Start here

Codex and human contributors should read these first:

1. [`docs/00_VISION_AND_NORTH_STAR.md`](docs/00_VISION_AND_NORTH_STAR.md)
2. [`codex/START_HERE.md`](codex/START_HERE.md)
3. [`docs/01_PROJECT_BRIEF.md`](docs/01_PROJECT_BRIEF.md)

## Current hypothesis

KTX/Frogbots may already provide the hard engine-native substrate: server physics, collision, combat, KTX rules, and MVD recording. If we can replace or enhance only the movement controller, we may avoid rebuilding a complete QuakeWorld simulation stack.

This hypothesis is unproven. The first lab must prove or disprove it.
