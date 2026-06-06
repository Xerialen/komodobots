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

The first design gate for that hybrid probe is now written in `experiments/qwd_route_probe/evidence/qwd-sng-hybrid-probe-design-dm3.*`:

- preserve the `14` QWD SNG control points
- use a temporary KTX moveprobe mode, likely `9`
- activate only near the first SNG control point on `dm3`
- use waypoint attraction plus the QWD side-dominant command profile (`forwardmove=320`, `sidemove=508`)
- preserve route, water, command, probe-activation, cadence, and movement-bucket diagnostics
- reject or mark inconclusive any run that reaches points only through slow/stuck movement or loses diagnostics

Decision status: continue Frogbots for one bounded QWD SNG runtime probe. If that produces positive server-loop evidence, expand the method to the remaining DM3 QWD moves. If it requires invasive route rewrites or cannot preserve diagnostics, the from-scratch option becomes stronger.

First runtime result:

Temporary mode `9` now provides bounded server-loop evidence, but not a positive learning result yet.

Run `20260606T221429Z` on `dm3`:

- command/QWD samples: `866`
- QWD active samples: `11`
- max active seconds: `1.12`
- max advanced control points: `2` of required `4`
- diagnostics preserved: route, water, probe-state, cadence, and movement metrics
- active command profile passed where active: side `1.0`, jump `1.0`
- slow/stuck and route-dirty success guardrails did not reject the run

Decision status: keep Frogbots alive for one narrower SNG repair step, but do not expand to all DM3 QWD moves yet. The current blocker is not that KTX/Frogbots cannot accept QWD-derived control; it is that the first activation/control-point advancement setup did not execute enough of the shortcut under guardrails.
