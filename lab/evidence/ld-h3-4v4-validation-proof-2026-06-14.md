# LD-H3 4v4 Validation and KTX Casting Proof Run - 2026-06-14

Scope: offline proof for issues #177-#184. This proves the KTX parser,
fixed-roster ledger, control-plan artifact path, dashboard rendering, read-only
casting ingest, conservative live observer, and browser fixture paths. It does
not claim live KTX completion; the all-stock baseline and Komodobot-slot live
games still need a declared lab slot.

## Inputs

- Generated fixture ledger:
  `lab/dashboard/public/data/4v4-validation.example.json`
- Generated casting fixture:
  `lab/dashboard/public/data/casting-match.example.json`
- Dashboard URL:
  `http://127.0.0.1:5173/botlab/?fixture=4v4&views=game`
- Casting URL:
  `http://127.0.0.1:5173/botlab/?casting=1&fixture=casting`
- KTX source reference:
  `C:\Users\benya\Workspace\thevault\quakeworld\qw-4on4-stats-reference.md`

## Commands

```powershell
python tests\test_ktx_match_stats.py
python tests\test_fourvfour_validation_build.py
python tests\test_fourvfour_validation_runner.py
python tests\test_control_bridge.py
python tests\test_fourvfour_validation_panel.py
python tests\test_ktx_casting_ingest.py
python tests\test_ktx_live_observer.py
python tests\test_casting_scoreboard.py
npm ci
npm run build
```

## Results

- KTX normalizer tests: 4 passed.
- Ledger builder tests: 6 passed.
- Runner/control tests: 6 passed.
- Control bridge regression suite: 62 passed.
- Dashboard panel logic tests: 7 passed.
- Read-only casting ingest tests: 4 passed.
- Conservative KTX live observer tests: 7 passed.
- Casting scoreboard fixture tests: 6 passed.
- Dashboard production build: passed. Vite emitted the existing large-chunk
  warning; no build error.

## Browser Evidence

Tooling: shared debug Chrome on `127.0.0.1:9222` plus Chrome DevTools MCP.

- Desktop screenshot:
  `lab/evidence/ld-h3-4v4-validation-desktop.png`
- Narrow screenshot:
  `lab/evidence/ld-h3-4v4-validation-narrow.png`
- Casting scoreboard screenshot:
  `lab/evidence/ld-h3-casting-scoreboard-1280x720.png`
- Narrow viewport DOM/geometry check:
  8 bot rows, Team A and Team B sections, Komodobot text present, no horizontal
  overflow inside `[data-section="4v4-validation"]`.
- Casting DOM/geometry check:
  8 player rows, two KTX teams, final KTX badge present, no BotLab control
  text, and no horizontal overflow in the casting surface.
- Network:
  `/botlab/data/4v4-validation.example.json` returned 304 from the Vite server.
  `/botlab/data/casting-match.example.json` returned 304 from the Vite server.
  Existing local `/demos/records/records.json` and `/demos/records/verdicts.json`
  requests still 404 in local fixture mode; those are pre-existing records-panel
  endpoints and not part of the new 4v4 fixture fetch.
- Console:
  Vite/React dev messages, the expected telemetry WebSocket failure against
  `ws://192.168.86.33:8770` when not on a live lab session, existing records
  404 noise, and FTE/QTV startup logs. No 4v4 panel runtime exception observed.

## Live Gap

Issue #181's live acceptance criteria require:

- one all-stock fixed-roster baseline game,
- one Komodobot-slot validation game,
- MVD/KTX stats artifacts for both,
- rebuilt `4v4-validation.json` from those artifacts.

That live proof was not run in this implementation pass. The runner/control
path now writes roster/plan artifacts and prepares a lab-only 4v4 KTX lobby, but
the actual KTX team split still must be proven in a live R-T/team pre-flight.
