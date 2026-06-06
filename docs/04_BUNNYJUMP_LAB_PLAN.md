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

Status: provisionally satisfied pending review.

The KTX moveprobe patch hooks `BotSetCommand()` after the prewar-freeze guard and immediately before button assembly and `trap_SetBotCMD(...)`.

- Mode `1` forced jump while preserving existing Frogbot direction and combat. Run `20260605T213149Z` spawned two bots, recorded three frags, parsed successfully, and generated movement metrics.
- Mode `2` replaced the final movement command with a fixed command and forced jump. Run `20260605T213010Z` still produced the full lab artifact set, but the bots became nearly stationary.
- Mode `3` used Frogbot's route movement direction as yaw, emitted a simple forward command, and forced jump. Run `20260605T224811Z` proved varied route-derived command emission and plausible movement for `/ goldenboy`, but `/ bro` spent `59.7%` of active time stationary.
- The v2c repeatability check (`20260605T225720Z` on `frobodm2`, `20260605T225802Z` on `dm3`) passed explicit command/plausibility gates for all four bot rows.

Interpretation: the final command can be perturbed and directly observed. The stock/mode `1`/mode `2` command-log comparison confirmed that forced jump and fixed movement values reach `trap_SetBotCMD(...)`; it also confirmed that blind fixed-command replacement collapses into stationary behavior. Mode `3` plus v2c is a provisional useful-movement proof. The next step can move toward a bounded S3 bunnyjump primitive, while keeping aim/combat separation explicit.

## Future phases

- Bunnyjump controller experiments: S3g mode `7` is the current best movement-literacy candidate. It preserves combat yaw, removes sampled backward commands, passes both routed maps, and bounds sampled horizontal command magnitude near `824.6`. Do not add more command heuristics until human/elite reference evidence points to a specific missing behavior.
- Human-demo comparisons: S4c now provides a first same-map `dm3` human anchor for S3g and shows S3g is still below the human p95 speed range. S5a proved exact Milton/elite selection is feasible from metadata and parsed one Milton `dm3` sample; the next data step is S5b, a tiny aggregate so one match does not become the whole target.
- Route primitives.
- Rocket-jump behaviour.
- Player-specific movement models.
