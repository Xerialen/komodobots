# Project Brief

> **Program of record:** `docs/18_BENCH_ITERATED_BOT_PROGRAM.md` (greenfield, approved
> 2026-06-16; see `docs/00_VISION_AND_NORTH_STAR.md` and `docs/08_DECISION_LOG.md`). This
> brief predates that reset: the "headless DM2 movement lab" first-goal and the
> aim/Milton/teamplay non-goals below are **historical first-objective context**, not the
> current plan. The current target is a learned move+aim+decision DM3 4on4 stand-in
> (Milton-first). Read `docs/18` for the live goal and `docs/25_DATA_CONTRACT.md` for the data.

## Primary question

Can QuakeWorld bots become realistic enough to act as believable substitutes for real players?

## Current hypothesis

KTX/Frogbots may already provide the hard engine-native substrate:

- physics
- collision
- combat
- item interactions
- MVD recording

If movement can be isolated and replaced, extending Frogbots may be substantially cheaper than building a new bot framework.

## First laboratory goal

Establish a headless DM2 big-room movement lab.

The first goal is NOT to improve movement.

The first goal is to determine whether movement can be isolated, overridden, measured, and compared against real demo data.

## Success criteria

- KTX bots can be spawned automatically.
- DM2 can be loaded automatically.
- MVDs can be recorded automatically.
- MVDs can be analyzed automatically.
- A movement override experiment can be performed.
- The resulting behaviour can be measured.

## Non-goals

- Training Milton.
- Solving teamplay.
- Solving combat AI.
- Building a complete new bot.
- Implementing final bunnyjump logic.

Those come later.