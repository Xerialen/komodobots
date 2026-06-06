# Frogbots vs New Bot

Status: living decision framework.

## Purpose

This document exists to prevent premature commitment to either:

- extending KTX/Frogbots forever
- rewriting everything from scratch

The laboratory should generate evidence that informs this decision.

## Current position

Current working assumption:

Use KTX/Frogbots as the starting substrate.

Reason:

They already appear to provide:

- server-native execution
- participation in real physics
- participation in real collision
- participation in real combat
- KTX integration
- MVD generation/recording

This assumption remains unproven.

## Key question

Can Frogbots become a server-native shell while we replace or enhance the movement brain?

If yes, extending Frogbots is probably the lowest-risk path.

## Evidence we need

### Architecture

- Where do movement decisions originate?
- How tightly coupled are routing and movement?
- Can movement be overridden cleanly?

### Data

- Can human movement be measured reliably?
- Can bot movement be measured reliably?

### Automation

- Can experiments run unattended?
- Can MVDs be generated and analyzed automatically?

### Movement

- Can a movement override be inserted?
- Does it break routing, combat, or server behaviour?

## Decision gates

### Keep Frogbots

Evidence suggests:

- movement can be replaced or enhanced
- server-native benefits remain intact
- architecture remains manageable

### Consider a new bot

Evidence suggests:

- movement is inseparable from legacy route logic
- architecture becomes excessively restrictive
- major goals cannot be achieved without extensive rewrites

## Current status

No decision.

The project is currently gathering evidence.

## Latest QWD route evidence

The QWD trajectory/action path is now a meaningful keep-Frogbots signal, but not proof.

`dm3_sng_shortcut.qwd` maps close to existing static `dm3.bot` markers, yet not to direct route edges:

- nearest-marker p50/p95/max: `70.112` / `120.324` / `142.597` qu
- `0.939` of waypoints within `128` qu of a static marker
- direct `.bot` edge ratio across collapsed human marker transitions: `0.0`
- graph reachable ratio: `1.0`, but via multi-edge paths
- QWD commands are side-move dominant: nonzero side `0.718`, nonzero forward `0.089`

Interpretation: Frogbots still look useful as the server-native shell and spatial context provider, but the first QWD-derived movement test should be a hybrid waypoint/controller probe. Pure route-following or `.bot` mutation would throw away the human command signal and overtrust route topology that does not match the shortcut.
