# Roadmap

Status: living document.

## North Star

```mermaid
flowchart TD
    A[Komodobots] --> B[Movement Realism]
    B --> C[Player Realism]
    C --> D[Simulation Realism]

    D --> E[FantasyQuake]
    D --> F[Megalodon Milton]

    B --> B1[Bunnyjumping]
    B --> B2[Rocket Jumping]
    B --> B3[Route Movement]
    B --> B4[Movement Decisions]
```

## Experiment Ladder

```mermaid
flowchart TD
    S0[Smoke Test: lab loop breathes] --> S1[Baseline Frogbot MVD]
    S1 --> S2[Movement Override Feasibility]
    S2 --> S3[DM2 Big Room Bunnyjump Controller]
    S3 --> S4[Human DM2 Comparison]
    S4 --> S5[Milton Movement Reference Set]
    S5 --> S6[Route Primitives]
    S6 --> S7[Player Specific Movement]
```

## Current Stage

Current active stage:

`S5b - Tiny Milton/elite reference aggregate`

## Stage Status Table

| Stage | Status | Evidence Needed |
|---------|---------|---------|
| S0 Smoke Test | Complete | Bot moves, MVD recorded, MVD parsed |
| S1 Baseline | Complete | Measured current Frogbot movement with speed and airborne-proxy metrics |
| S2 Override | Provisionally satisfied pending review | Route-yaw mode `3` passed explicit v2c command/plausibility gates on `frobodm2` and `dm3` |
| S3 Bunnyjump Controller | Provisionally satisfied pending human anchor | S3g mode `7` passed `dm3` and `frobodm2` while preserving combat yaw, removing backward commands, and bounding sampled command magnitude near `824.6` |
| S4 Human Comparison | First same-map anchor complete | S4c parsed one human `dm3` 4on4 demo and compared it against S3g `dm3`; S3g is not yet human-like on the observed movement ranges |
| S5 Milton Reference | Active | S5a proved exact-player Milton/elite selection from Turso metadata plus the existing corpus; S5b should aggregate a tiny reference set |
| S6 Route Primitives | Pending | Route-level movement behaviours |
| S7 Player Specific | Pending | Player-style movement models |

## Roadmap Rule

Whenever a stage changes, update this file and record supporting evidence in:

- docs/07_FINDINGS_LOG.md
- docs/08_DECISION_LOG.md

## Route-Yaw Scaffold Stop Condition

Mode `3` and mode `4` deliberately commandeer view yaw to align movement with Frogbot route intent. That proves movement override mechanics, but it is not a believable player controller because a real player can aim at an enemy while moving route-relative.

S3c validated `sidemove=200` as a repeatable route-yaw strafe candidate on `frobodm2` and `dm3`, but mode `3` and mode `4` still commandeer aim. S3d mode `5` then emitted aim-independent route/strafe commands, but behavior split. S3e diagnostics showed route-vs-view yaw deltas and backward local commands are plausible contributors, especially for `/ bro` on `dm3`, but not a complete explanation. S3f mode `6` removed backward commands and passed both routed maps, but did so with very large folded side commands. S3g mode `7` bounded those commands and passed both routed maps.

S4a built the human-demo parser scaffold and parsed one local `aerowalk` duel, but found no local true `dm2` candidate. S4b selected and parsed one true human `dm2` 4on4 demo from the existing `servexeri` corpus, but S3g bot evidence is on `dm3` and `frobodm2`. S4c selected a same-map human `dm3` 4on4 sample and compared it against S3g `dm3`; this solved the map mismatch, but showed S3g is still weak versus the human range on p95 speed and partly on average speed.

S5a proved exact-player reference selection is feasible from Turso metadata plus the existing corpus manifest, then parsed one exact `Milton` `dm3` sample. That sample shows a sharper S3g gap than the generic S4c human sample: S3g is below the sample's p95 range and `/ bro` is below average speed while above low-speed and airborne-proxy ranges.

The next branch is S5b: build a tiny Milton/elite reference aggregate so the project does not tune against a single match before S6 route primitives or S7 player-specific movement.
