# STOP AND READ FIRST

Before writing code, read:

1. docs/00_VISION_AND_NORTH_STAR.md
2. docs/01_PROJECT_BRIEF.md
3. docs/25_DATA_CONTRACT.md — before touching any data extraction, transform, training-data, or model-prep code. Do not infer new fields or change the output format unless the contract, schema, golden example, and tests all move in the same PR.

Every task in this repository must contribute evidence toward one question:

Can QuakeWorld bots become realistic enough to act as believable substitutes for real players?

Bunnyjumping, DM2, KTX, Frogbots, MVD analysis, route learning, and movement controllers are not end goals. They are experiments designed to answer that question.

## First objective

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