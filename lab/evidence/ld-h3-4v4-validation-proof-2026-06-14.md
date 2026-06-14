# LD-H3 4v4 Validation and KTX Casting Proof Run - 2026-06-14

Scope: proof for issues #177-#184. This proves the KTX parser, fixed-roster
ledger, live lab runner, control-plan artifact path, dashboard rendering,
read-only casting ingest, conservative live observer, browser fixture paths, and
two completed live KTX DM3 4v4 validation games on an allowlisted lab port.

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
python tests\test_run_4v4_validation_lab.py
python tests\test_fourvfour_validation_panel.py
python tests\test_ktx_casting_ingest.py
python tests\test_ktx_live_observer.py
python tests\test_casting_scoreboard.py
python scripts\run_4v4_validation_lab.py --run-id codex_live_4v4_base_20260614T1935Z --port 28599 --strict-port --controller-version stock-frogbot-20-baseline
python scripts\run_4v4_validation_lab.py --run-id codex_live_4v4_dev_20260614T1945Z --port 28599 --strict-port --controller-version komodobot-dev-live-label
python lab\server\fourvfour_validation_build.py --runs-dir artifacts\4v4-validation-runs --out artifacts\records\4v4-validation.json --summary
npm ci
npm run build
```

## Results

- KTX normalizer tests: passed.
- Ledger builder tests: 10 passed.
- Runner/control tests: passed.
- Live 4v4 lab runner tests: 9 passed.
- Control bridge regression suite: 62 passed.
- Dashboard panel logic tests: 7 passed.
- Read-only casting ingest tests: 4 passed.
- Conservative KTX live observer tests: 7 passed.
- Casting scoreboard fixture tests: 6 passed.
- `npm ci`: passed; `npm audit` reported 2 dependency advisories (1 moderate,
  1 high) in the existing dependency tree.
- Dashboard production build: passed. Vite emitted the existing large-chunk
  warning; no build error.
- Live KTX ledger rebuild:
  `runs: scanned=9 valid=2 skipped={'missing_stats_artifact': 7}`.
- Live Komodobot-slot delta:
  `codex_live_4v4_dev_20260614T1945Z` compared against
  `codex_live_4v4_base_20260614T1935Z`: frags `13 -> 12`, delta `-1`.

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

## Live KTX Evidence

Issue #181's live acceptance criteria required:

- one all-stock fixed-roster baseline game,
- one Komodobot-slot validation game,
- MVD/KTX stats artifacts for both,
- rebuilt `4v4-validation.json` from those artifacts.

The live proof was run on `servexeri:28599` using the lab-only
`scripts/run_4v4_validation_lab.py` harness:

| Run ID | Result |
|---|---|
| `codex_live_4v4_base_20260614T1935Z` | Valid 300-second DM3 KTX teamplay match; red 69, blue 66; `demo.mvd` 2,653,010 bytes. |
| `codex_live_4v4_dev_20260614T1945Z` | Valid 300-second DM3 KTX teamplay match; red 50, blue 42; `demo.mvd` 2,527,672 bytes; previous valid run set to the baseline. |

Both runs had eight KTX bot players, four on `red` and four on `blue`, plus one
spectator control shim. The ledger accepted `mode=team`, `deathmatch=1`,
`teamplay=2`, `duration=300`, and the fixed roster intent. The second run used
stock Frogbot behavior with a different `controller_version` label; this proves
the validation/delta machinery before a real Komodobot controller is swapped in.

Important live finding: analyzer output embeds the KTX stats in `demoInfo`, but
the authoritative mode settings can be in analyzer metadata
(`metadata.matchSettings` / `metadata.serverInfo`) instead of raw KTX `dm`/`tp`
fields. `lab/server/ktx_match_stats.py` now accepts both shapes.
