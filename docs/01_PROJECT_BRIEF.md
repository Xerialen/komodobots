# Project Brief

> **Program of record:** `docs/28_MEGALODON_MILTON_MLOPS_PROGRAM.md` (owner re-plan, 2026-06-26; see
> `docs/00_VISION_AND_NORTH_STAR.md`). **This entire brief is historical.** The "headless DM2 movement
> lab" first-goal and the non-goals below predate two resets; and the "believable substitutes / human-like
> 4on4 stand-in" framing — together with `docs/18_BENCH_ITERATED_BOT_PROGRAM.md` — is itself now
> **superseded** by docs/28: the goal is the information-honest superhuman bot (Megalodon Milton), trained
> by RL and validated route-first. Read `docs/28` for the live goal and `docs/25_DATA_CONTRACT.md` for the
> data mechanics.

## Primary question

_(Historical — superseded by docs/28. The goal is no longer "believable substitutes" but the
strongest-possible, information-honest bot; see `docs/28` / `docs/00`.)_

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