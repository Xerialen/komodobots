# Bunnyjump Lab Plan

Status: living document.

## Purpose

Build a repeatable laboratory for studying QuakeWorld movement.

The lab exists to generate evidence, not assumptions.

## First test environment

Stock DM2.

Primary area: big room.

Reason:

- Real target map.
- Open enough to isolate movement.
- Avoids immediately coupling experiments to trick routes.

## Phase 0

Establish automation.

Requirements:

- launch environment
- spawn bots
- load DM2
- record MVD
- parse MVD
- generate report

## Phase 1

Measure baseline Frogbots.

Questions:

- Do they bunnyhop?
- What speeds do they achieve?
- How often do they jump?
- How often do they lose speed?

## Phase 2

Prove movement replacement is possible.

Create a deliberately simple movement override.

Goal:

Determine whether movement can be isolated and swapped without breaking the rest of the system.

## Future phases

- Bunnyjump controller experiments.
- Human-demo comparisons.
- Route primitives.
- Rocket-jump behaviour.
- Player-specific movement models.
