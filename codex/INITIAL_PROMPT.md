# Initial Codex Prompt

You are working inside the Komodobots repository.

Before doing anything else, read:

- AGENTS.md
- docs/00_VISION_AND_NORTH_STAR.md
- docs/01_PROJECT_BRIEF.md
- docs/02_SOURCE_MAP.md
- codex/START_HERE.md

## Important

Do not start by implementing a bunnyjump controller.

Do not start by training Milton.

Do not start by redesigning Frogbots.

The first goal is to establish a repeatable laboratory capable of producing evidence.

## Current mission

Investigate the existing headless QuakeWorld test environment and determine whether it can be used as the foundation of the Komodobots movement lab.

Document findings in:

`docs/05_HEADLESS_TEST_ENV.md`

## Desired laboratory capabilities

- run KTX with bot support
- load stock DM2 automatically
- spawn bots automatically
- record MVD automatically
- parse MVD automatically
- generate reports automatically
- support future movement override experiments

## First deliverables

1. Updated `docs/05_HEADLESS_TEST_ENV.md`
2. Inventory of existing environment assets
3. Proposed automation entry point
4. Risks and missing dependencies

## Documentation requirements

If you discover:

- new sources -> update `docs/02_SOURCE_MAP.md`
- movement insights -> update `docs/03_MOVEMENT_PROBLEM.md`
- environment details -> update `docs/05_HEADLESS_TEST_ENV.md`
- data pipeline details -> update `docs/06_DATA_AND_MVD_PIPELINE.md`
- experiment results -> update `docs/07_FINDINGS_LOG.md`
- architecture decisions -> update `docs/08_DECISION_LOG.md`

The repository should become more understandable after every session.
