# KomodoLab User-Story Test Run

Test run: TR-2026-06-12-komodolab-user-stories
Date: 2026-06-12
Commit tested: `28ed1da`
Environment:
- Local dashboard: `http://127.0.0.1:5173/botlab/`
- WebSocket: `ws://127.0.0.1:8771`
- Live lab: `servexeri`, dashboard session `dash_20260612T060213Z`
- Lab map/port: `ztricks`, port `28600`
- Browser: Codex in-app Browser with Playwright API

## Baseline Validation

- `npm run build` in `lab/dashboard`: passed.
- `python -m unittest discover -s tests`: 957 tests passed.
- GitHub issue-template YAML parse: passed for `bug_report.yml`, `test_case.yml`, `user_story.yml`.
- `python scripts/ld_g2_golden_path.py --live`: all 6 checks passed.

## User-Story Results

| Story | Result | Evidence |
|---|---|---|
| US-LAB-001 Watch live attempt surfaces | Partial | Live 3D and telemetry work; Live Game stays `retrying` (#158). |
| US-LAB-002 Start/repeat ztricks attempt | Passed with caveat | `try` returned `game ztricks_distance_standstill`; server emitted fresh `FBMOVEPROBE_CMD` mode 23 rows. Roster stale rows tracked in #157. |
| US-LAB-003 See bot state | Partial | Live 3D showed `/ bro`, `ed 4`, `hops: 1`, and increasing air time. Roster kept stale `s2`/`s4` rows after resets (#157). |
| US-LAB-004 Control game state | Passed | UI buttons succeeded and audit logged `gamemode 4on4`, `gamemode ffa`, `deathmatch 2`, `powerups off/on`, `start`, `stop`, `prewar`, `bot_weapon_lock`, `bot_weapon_unlock`. |
| US-LAB-005 Use cvar console safely | Passed with UX note | `set samelevel 1` succeeded; `quit` was rejected. Bare `samelevel 1` was rejected, so the console expects explicit `set` form. |
| US-LAB-006 Protect lab ownership | Passed by existing checks | Full unit suite and live lock display passed; lock visible as dashboard-owned ztricks session on port `28600`. |
| US-LAB-007 Review evidence/records | Failed | KPI showed `scoreboard error: records.json: HTTP 404`; Records panel showed `records unavailable` (#159). |
| US-LAB-008 Agent workflow templates | Passed | Issue-form YAML parsed successfully. |

## Browser Evidence

Final browser URL:

```text
http://127.0.0.1:5173/botlab/?views=live3d%2Cgame&ws=ws%3A%2F%2F127.0.0.1%3A8771
```

Final visible state:

- Live 3D: open, rendered a canvas, showed `/ bro` / `ed 4`, `hops: 1`, and air time after `try`.
- Live Game: open but stayed `retrying`.
- Control rail: open to the right of Live Game.
- Cvar console rail: open to the right of Control.
- Browser console errors from the dashboard page: none.

Narrow viewport check at `1180x720`:

- No document-level horizontal overflow.
- Control and cvar rails remained solid separate rails.
- The pane area clipped into its own scrollable space when all surfaces were open; no visible pane content rendered on top of the rails.

## Server Evidence

Control audit included successful entries:

```text
2026-06-12T07:21:36Z game gamemode 4on4
2026-06-12T07:21:39Z game gamemode ffa
2026-06-12T07:21:42Z game deathmatch 2
2026-06-12T07:21:43Z game powerups off
2026-06-12T07:21:46Z game powerups on
2026-06-12T07:21:51Z game start
2026-06-12T07:21:54Z game stop
2026-06-12T07:21:57Z game prewar
2026-06-12T07:22:03Z game bot_weapon_lock
2026-06-12T07:23:07Z console: set samelevel 1
2026-06-12T07:25:14Z game bot_weapon_unlock
2026-06-12T07:25:34Z game start
2026-06-12T07:25:46Z game ztricks_distance_standstill
```

Server screen hardcopy showed fresh mode-23 command rows after `try`:

```text
[2026-06-12 07:24:56] FBMOVEPROBE_CMD time=4962.637 ed=4 name=/ bro mode=23 ...
```

## Bugs Registered

- #157: Bot roster keeps stale rows after repeated ztricks tries.
- #158: Live Game pane stays retrying while telemetry and Live 3D work.
- #159: KPI records surface reports records.json 404 in BotLab.

## Next Retest

Rerun this test after fixing #157/#158/#159. The smallest useful retest is:

1. Start/confirm a ztricks dashboard session.
2. Click `try`.
3. Verify Live 3D telemetry, Live Game rendering, and roster convergence.
4. Verify records/KPI load or show a deliberate configured-empty state.
