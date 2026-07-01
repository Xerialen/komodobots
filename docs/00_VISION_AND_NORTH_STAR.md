# Vision and North Star

## Why this project exists

Komodobots exists to build the strongest QuakeWorld bot possible — one that may move, aim and play better than the best humans — under a single constraint: **information honesty** (it acts only on what it can see or hear itself, or read in teamsay chat). The codename is **Megalodon Milton**. The program of record is `docs/28_MEGALODON_MILTON_MLOPS_PROGRAM.md`.

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

The strongest possible bot — superhuman movement, aim and play — constrained only by information honesty.
(Originally framed as recreating individual players like Milton; the target is now to *surpass* elite play,
honestly, not to imitate it.) This is the current program of record — see `docs/28`.

## Shared foundation

Both futures require:

Bunnyjumping -> Movement Realism -> Player Realism -> Simulation Realism

## Current focus

_(Live plan is `docs/28` Phase 1; movement remains the focus — it is Brain 1, the Motor Cortex.)_

The largest visible gap today is movement.

The largest visible gap inside movement is bunnyjumping.

Therefore the first laboratory objective is to understand whether KTX/Frogbots can support a replacement or enhanced movement brain while preserving engine-native QuakeWorld behaviour.

## Decision Point Alpha

A future milestone will decide whether the project primarily continues toward FantasyQuake or toward player-specific simulation (Megalodon Milton).

That decision should be driven by evidence produced by the laboratory, not by assumptions.

**Update (2026-06-14): Alpha taken provisionally → Megalodon Milton first**, on the evidence of the
ztricks and dm3 movement breakthroughs.

**Update (2026-06-16): the program of record is now `docs/18_BENCH_ITERATED_BOT_PROGRAM.md`** — a
greenfield, bench-iterated program for a human-like DM3 bot (movement + aim + decisions, all learned
from human demos, judged on a frog-vs-leap 4on4 bench). The earlier staged plan
`references/12_DM3_4ON4_STANDIN_PROGRAM.md` is retained as background only. The decision record and
revisit conditions are in `docs/08_DECISION_LOG.md`.

**Update (2026-06-26): pivot — the program of record is now `docs/28_MEGALODON_MILTON_MLOPS_PROGRAM.md`.**
The goal changed from *believable / human-like* to **information-honest superhuman** ("plays perfectly",
codename Megalodon Milton); the method from behaviour-cloning to **RL on rewards**; and early validation from
the 4v4 believability bench to **route-isolated route-shape adherence AND faster-than-human speed** (4v4 demoted to a Phase-4
drift-detection signal). `docs/18` is retained as history. Architecture = a modular, bottom-up-trained,
freeze-as-you-go brain hierarchy (movement → combat → strategy).
