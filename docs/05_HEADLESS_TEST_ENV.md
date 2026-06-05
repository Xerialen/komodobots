# Headless Test Environment

Status: incomplete. Expected to be expanded by Codex after inspecting the actual environment.

## Purpose

Document the environment used to run repeatable Komodobots experiments.

This file is intended to become the authoritative description of the movement laboratory.

## Current understanding

The user already has a headless QuakeWorld-related setup used for ezhud development, referred to as something similar to `ezquake-test`.

The details are not yet verified.

## Initial Codex task

Investigate and document:

- environment name
- operating system
- location on disk
- launch scripts
- server binaries
- client binaries
- KTX availability
- MVDSV availability
- MVD recording capability
- DM2 automation capability
- log locations
- configuration locations

## Desired end state

One command should be able to:

1. Start environment.
2. Load stock DM2.
3. Spawn test bots.
4. Start recording.
5. Run experiment.
6. Stop recording.
7. Parse MVD.
8. Produce report.

## Deliverables

- Environment diagram.
- Folder layout.
- Startup instructions.
- Shutdown instructions.
- Troubleshooting section.
- Automation entry point.

## Open questions

- Does the existing ezquake-test environment already contain KTX?
- Does it already contain MVDSV?
- Can MVD recording be automated today?
- Can multiple bots be spawned automatically?
- Is the environment local, remote, containerized, or mixed?
