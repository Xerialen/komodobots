# STOP AND READ FIRST

Before writing code, read:

1. docs/00_VISION_AND_NORTH_STAR.md
2. docs/01_PROJECT_BRIEF.md
3. docs/25_DATA_CONTRACT.md — before touching any data extraction, transform, training-data, or model-prep code. Do not infer new fields or change the output format unless the contract, schema, golden example, and tests all move in the same PR.

Every task in this repository must contribute toward the program of record,
`docs/28_MEGALODON_MILTON_MLOPS_PROGRAM.md`:

Build Megalodon Milton — the strongest QuakeWorld bot possible (it may move, aim and play better than the
best humans), bound by one constraint: information honesty (it acts only on what it can see or hear itself,
or read in teamsay). Method = RL on rewards; validated route-first, not by a believability bench.

Bunnyjumping, DM2, KTX, Frogbots, MVD analysis, route learning, and movement controllers are not end goals.
They are experiments toward that bot. (Supersedes the earlier "believable substitutes" framing + docs/18.)

## First objective

> **Historical (the lab is long-built).** This section is superseded by `docs/28`. The active objective is
> **docs/28 Phase 1** (epic #414): the data pipeline + Route Canon + the Commander/Motor-Cortex handoff PoC.
> The lab described below already exists.

Do NOT implement a bunnyjump controller.

First establish a repeatable laboratory that can:

- run KTX with bots
- load DM2 automatically
- record MVDs automatically
- parse MVDs automatically
- measure movement automatically
- test movement overrides automatically

## Deliverables

1. docs/05_HEADLESS_TEST_ENV.md
2. scripts to run repeatable DM2 experiments
3. baseline Frogbot movement report
4. movement override feasibility report

The first thing to prove is whether Frogbots can be used as a server-native shell while replacing the movement brain.