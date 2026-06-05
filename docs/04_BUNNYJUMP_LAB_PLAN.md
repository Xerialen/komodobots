# Bunnyjump Lab Plan

Status: living document.

## Purpose

Build a repeatable laboratory for studying QuakeWorld movement.

The lab exists to generate evidence, not assumptions.

## First test environment

Use routed Frogbot maps for bot-generated movement evidence:

- `frobodm2`
- `dm3`

Keep stock `dm2` as the `qw-sim` continuity map, not as a Frogbot route-building target. User clarified on 2026-06-05 that Frogbots have never worked on stock `dm2`, which is why `frobodm2` exists.

## Phase 0

Establish automation.

Requirements:

- launch environment
- spawn bots
- load DM2
- record MVD
- parse MVD
- generate report

Status: complete. The one-command runner records and parses MVDs on routed maps.

## Phase 1

Measure baseline Frogbots.

Questions:

- Do they bunnyhop?
- What speeds do they achieve?
- How often do they jump?
- How often do they lose speed?

Status: complete for first baseline. Movement report v2 measures speed, vertical-motion ratio, airborne proxy, cadence, and post-landing speed delta.

## Phase 2

Prove movement replacement is possible.

Create a deliberately simple movement override.

Goal:

Determine whether movement can be isolated and swapped without breaking the rest of the system.

Status: first probe complete, S2 still active.

The KTX moveprobe patch hooks `BotSetCommand()` after the prewar-freeze guard and immediately before button assembly and `trap_SetBotCMD(...)`.

- Mode `1` forced jump while preserving existing Frogbot direction and combat. Run `20260605T213149Z` spawned two bots, recorded three frags, parsed successfully, and generated movement metrics.
- Mode `2` replaced the final movement command with a fixed command. Run `20260605T213010Z` still produced the full lab artifact set, but the bots became nearly stationary.

Interpretation: the final command can be perturbed, and fixed-command replacement reaches the lab artifact loop, but useful movement-vector replacement is not yet proven. The next step is to instrument the exact values emitted to `trap_SetBotCMD(...)` before building a controller.

## Future phases

- Bunnyjump controller experiments.
- Human-demo comparisons.
- Route primitives.
- Rocket-jump behaviour.
- Player-specific movement models.
