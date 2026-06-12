# Test Cases and Evidence

Status: living workflow document.

## Purpose

Komodobots needs repeatable evidence, not one-off chat memory. A completed test
case should remain available for future changes; the individual execution is
logged as a test run.

This document defines how user stories, test cases, test runs, and evidence fit
together for agents and humans.

## Core model

```text
User Story
  owns acceptance criteria and user value

Test Case
  durable reusable check for one behavior

Test Run
  one execution of a test case against a PR, commit, build, or environment

Evidence
  logs, screenshots, command output, browser results, CI links, MVD output
```

The test case survives. The test run records what happened this time.

## IDs

Use short stable IDs:

```text
US-LAB-001
TC-LAYOUT-001
TR-2026-06-12-001
BUG-QTV-001
```

Prefer meaningful area prefixes when helpful:

- `TC-LAYOUT-*` for dashboard layout behavior.
- `TC-CONTROL-*` for control bridge and game controls.
- `TC-QTV-*` for Live Game / QTV behavior.
- `TC-LIVE3D-*` for telemetry and Live 3D behavior.
- `TC-LAB-*` for harness/server behavior.

## Test case lifecycle

```text
draft -> active -> automated | retired
             \-> superseded
```

- `draft`: proposed but not yet trusted.
- `active`: reusable and expected to be run when relevant code changes.
- `automated`: covered by a committed test; keep the case as traceability.
- `retired`: behavior no longer exists or no longer matters.
- `superseded`: replaced by a newer case; link the replacement.

## Test run results

Each execution records one result:

- `passed`: observed behavior matched expected behavior.
- `failed`: observed behavior did not match expected behavior.
- `blocked`: setup/tooling/environment prevented execution.
- `skipped`: intentionally not run, with reason.

Failed runs should link to a bug, follow-up issue, or PR fix. Blocked runs should
name the missing setup or broken tool.

## Where things live

- Durable user stories: GitHub issues.
- Durable test cases: GitHub issues or `docs/` when the case is project-wide.
- PR-specific test runs: PR body or PR comment.
- Long-term experiment findings: `docs/07_FINDINGS_LOG.md`.
- Architecture/process decisions: `docs/08_DECISION_LOG.md`.
- Automated regression tests: committed test files under `tests/` or the
  relevant package test directory.

## Test case template

```md
## TC-LAYOUT-001: Control panel does not overlay Live Game

Area: Dashboard layout
Story: US-LAB-003
Type: Manual browser / Playwright / Regression
Priority: High
Status: active

### Preconditions
- Dashboard is running.
- BotLab opens with `views=game`.
- Control panel is available.

### Steps
1. Open BotLab.
2. Enable Live Game.
3. Open Control panel.

### Expected result
- Control panel appears beside the Live Game.
- It does not cover the game canvas.
- Live 3D is not opened unless explicitly selected.

### Evidence required
- URL tested.
- Commit SHA.
- Screenshot or browser geometry check.
- Console/network notes if this is a web test.
```

## Test run template

```md
## Test Run Evidence

Test run: TR-2026-06-12-001
PR: #156
Commit: abc123
Date: 2026-06-12
Environment: local dashboard, Chrome debug, ws://127.0.0.1:8771

### Results
- [x] TC-LAYOUT-001 passed
- [x] TC-LAYOUT-002 passed
- [ ] TC-QTV-001 failed

### Evidence
- `npm run build` passed.
- `python -m unittest ...` passed.
- Browser geometry confirmed the control rail is beside the game.
- Failure: Live Game stayed retrying; console showed the linked QTV/FTE error.
```

## Agent workflow

When acting as Coder:

1. Identify the user story or behavior changed.
2. Reuse an existing test case if one covers the behavior.
3. Create or update a test case if the behavior is new or changed.
4. Run the relevant automated and manual/browser checks.
5. Log a test run in the PR or issue.
6. Promote important repeated manual checks to automation when practical.

When acting as Reviewer:

1. Check whether the PR names the relevant test cases.
2. Check whether test runs are logged for changed user-facing behavior.
3. Treat missing evidence as a blocker only when it creates concrete merge risk.
4. Prefer asking for a focused test run over broad, vague "more testing."

## KomodoLab starting cases

Seed these as issues or doc-backed cases as the dashboard work continues:

- `TC-LAYOUT-001`: Control panel appears beside Live Game and does not overlay it.
- `TC-LAYOUT-002`: Live 3D is off by default unless requested in the URL.
- `TC-CONTROL-001`: Game mode buttons send allowlisted game commands.
- `TC-CONTROL-002`: Cvar console rejects unsafe commands and logs responses.
- `TC-LAB-001`: Dashboard session start acquires a safe lab lock.
- `TC-LAB-002`: Harness runs refuse to take over a fresh dashboard lock.
- `TC-QTV-001`: Live Game connects or shows an honest retry/error state.
- `TC-LIVE3D-001`: Live 3D renders the selected live bot from telemetry frames.
