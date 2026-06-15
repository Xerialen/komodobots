# Test Cases and Evidence

Status: living workflow document.

## Purpose

Komodobots needs repeatable evidence, not one-off chat memory. A completed test
case should remain available for future changes; the individual execution is
logged as a test run.

This document defines how user stories, test cases, test runs, and evidence fit
together for agents and humans.

Global engineering habits that apply across projects live in the vault note
`C:\Users\benya\Workspace\thevault\claude\engineering-hygiene-skills.md`. This
file specializes those habits for KomodoBots lab evidence.

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

## Contract-test workflow

Use contract tests when runtime code depends on generated or committed artifacts.
These tests should prove that the artifact class is valid before the browser,
lab runner, or parser tries to consume it.

Good KomodoBots targets:

- GLB/glTF map assets and `maps.json` provenance.
- Route manifests and committed route JSON.
- `records.json` and `verdicts.json` schema.
- GitHub issue-form YAML.
- Control bridge request/response envelopes.
- Telemetry frame shapes used by BotLab.

A good contract test has three parts:

1. A whole-artifact scan, not just one fixture.
2. A negative-control fixture or intentionally broken input that fails loudly.
3. A clear error message naming the broken field, file, route, map, or schema.

If a browser or live run finds an artifact-shape bug, add a contract test before
or with the fix. Examples include GLB bufferViews missing `buffer: 0`, stale
`maps.json` byte counts, invalid verdict values, or a route missing required
keys.

## Live-state reconciliation workflow

Use this workflow when the UI represents live lab state from telemetry, control
events, QTV, or records feeds.

Before coding, write down:

- Source of truth: telemetry frame, control event, HTTP file, QTV/FTE state, or
  local UI selection.
- Entity key: edict, slot, bot name, run ID, map, route, or attempt ID.
- Create/update signal.
- Removal, expiry, or reset signal.
- What the UI should show when the source is absent, stale, retrying, or failed.

Test runs should explicitly say whether stale state converged. For example:

- Bot roster after repeated ztricks tries should converge to the live bot set.
- Live 3D can be healthy while Live Game/QTV is retrying; record both states.
- Records data can be optional, absent, misconfigured, or valid; record which one.

If a failed run exposes stale rows, phantom bots, retry loops, or misleading
"unavailable" messages, link the run to a bug and keep the test case active until
the next run proves convergence.

## TC-4V4-001: Fixed-roster validation ledger renders current and previous-game deltas

Preconditions:

- At least two valid KTX DM3 4v4 all-bot stats files exist with matching
  `4v4-roster.json` intent files.
- The roster has one Komodobot slot and seven skill-20 Frogbot slots.

Expected result:

- `fourvfour_validation_build.py` emits `komodobots.4v4_validation.v1`.
- Invalid or non-fixed-roster games are excluded from `games` and recorded in
  `invalid_games`.
- The dashboard KPI dock shows four rows per team, highlights the Komodobot,
  and shows per-metric delta values against the previous valid game.
- The latest-game view uses Quake-facing headings instead of a role column:
  no visible `role`, no `TTD` abbreviation, and no aggregate `health` column.
  `dmg.taken-to-die` is labelled `to-die`.
- Player and team metric grids expose frags, efficiency, team kills, to-die,
  damage done/taken, RL enemies killed, pills, bricks, mega, YA, RA, LG/RL
  pickups, average speed, and max speed.
- The trend view allows one to four selected stats and graphs the fixed
  Komodobot slot across all valid games.

## TC-CASTING-001: Read-only KTX casting scoreboard renders without BotLab controls

Preconditions:

- A KTX match stats JSON file is available from a real or fixture match.

Expected result:

- `ktx_casting_ingest.py` emits `komodobots.ktx_match_stats.v1` with
  `source.casting_read_only=true`.
- `/botlab/?casting=1` renders a scoreboard with two teams and eight player
  rows from the KTX data.
- BotLab control panels, lock controls, and experiment launchers are absent.

## Test Run Evidence

Test run: TR-2026-06-14-4V4-KTX-STATS
PR: pending
Commit: pending
Date: 2026-06-14
Environment: local worktree `4on4-live-stats`, Windows PowerShell, local
dashboard via Vite, Chrome debug, `servexeri` lab KTX on port `28599`.

### Results

- [x] `TC-4V4-001` passed on committed fixture data.
- [x] `TC-4V4-001` passed on two live KTX DM3 4v4 lab games:
  `codex_live_4v4_base_20260614T1935Z` and
  `codex_live_4v4_dev_20260614T1945Z`.
- [x] `TC-CASTING-001` passed on committed fixture data.
- [x] The live ledger rebuilt with two valid games and a Komodobot-slot previous
  valid game delta (`13 -> 12`, delta `-1` frags).

### Evidence

- `python tests\test_ktx_match_stats.py`
- `python tests\test_fourvfour_validation_build.py`
- `python tests\test_fourvfour_validation_runner.py`
- `python tests\test_control_bridge.py`
- `python tests\test_run_4v4_validation_lab.py`
- `python tests\test_fourvfour_validation_panel.py`
- `python tests\test_ktx_casting_ingest.py`
- `python tests\test_ktx_live_observer.py`
- `python tests\test_casting_scoreboard.py`
- `python scripts\run_4v4_validation_lab.py --run-id codex_live_4v4_base_20260614T1935Z --port 28599 --strict-port --controller-version stock-frogbot-20-baseline`
- `python scripts\run_4v4_validation_lab.py --run-id codex_live_4v4_dev_20260614T1945Z --port 28599 --strict-port --controller-version komodobot-dev-live-label`
- `python lab\server\fourvfour_validation_build.py --runs-dir artifacts\4v4-validation-runs --out artifacts\records\4v4-validation.json --summary`
- `npm run build` in `lab/dashboard`
- Browser evidence:
  `lab/evidence/ld-h3-4v4-validation-proof-2026-06-14.md`,
  `lab/evidence/ld-h3-4v4-validation-desktop.png`,
  `lab/evidence/ld-h3-4v4-validation-narrow.png`, and
  `lab/evidence/ld-h3-casting-scoreboard-1280x720.png`.

## TC-4V4-001 dashboard upgrade run - 2026-06-15

Environment: branch `codex/4v4-dashboard-stat-upgrade`, Windows PowerShell,
Vite dashboard fixture at `/botlab/?fixture=4v4&views=game`, Chrome channel
via Playwright CLI, and Browser in-app runtime DOM checks.

Evidence:

- `python tests\test_ktx_match_stats.py`
- `python tests\test_fourvfour_validation_build.py`
- `python tests\test_fourvfour_validation_panel.py`
- `python -m unittest discover -s tests`
- `npm run build` in `lab/dashboard`
- `git diff --check`
- `lab/evidence/4v4-dashboard-upgrade-browser-checks.json`
- `lab/evidence/4v4-dashboard-upgrade-latest-1280x720.png`
- `lab/evidence/4v4-dashboard-upgrade-latest-mobile-390x844.png`
- `lab/evidence/4v4-dashboard-upgrade-trends-1280x720.png`

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
- `TC-LIVE3D-002`: Committed GLB map assets load in the browser without GLTFLoader
  errors.
- `TC-LIVE3D-003`: Telemetry map aliases, including `ztricks -> trick`, do not
  crash Live 3D.
- `TC-RECORDS-001`: KPI records distinguish valid data, optional missing verdicts,
  and required records-feed errors.
- `TC-ROSTER-001`: Bot roster converges after repeated preset tries and does not
  keep stale bot rows as active controls.
