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
