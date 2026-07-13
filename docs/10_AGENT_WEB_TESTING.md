# Agent Web Testing

Status: living workflow document.

## Default rule

Every meaningful web/UI change must be validated by an agent in a real browser
before it is called done.

Builds and unit tests are necessary, but they do not prove the visible workflow.
For web work, the evidence should include a browser check.

Global browser-runtime validation habits live in
`C:\Users\benya\Workspace\thevault\claude\engineering-hygiene-skills.md`. This
file is the KomodoBots/BotLab-specific specialization.

## Preferred local rig

Use the shared debug-Chrome setup documented in:

```text
C:\Users\benya\Workspace\thevault\claude\browser-testing-setup.md
```

Default browser endpoint:

```text
http://127.0.0.1:9222
```

Tool split:

- `chrome-devtools`: console, network, DOM, performance, and browser debugging.
- Playwright/browser automation: repeatable flows, screenshots, viewport checks,
  and end-to-end user journeys.
- Codex in-app Browser: useful for quick local verification when it is the
  active user-facing surface, especially for `localhost` / `127.0.0.1` targets.

Use whichever tool is available in the current agent runtime, but record which
tool produced the evidence.

## Required web evidence

For UI changes, log:

```text
URL tested:
Commit SHA:
Viewport(s):
Browser/tool used:
Console errors:
Network failures:
Screenshots/video/geometry:
Test cases run:
Result:
```

If console or network errors are pre-existing or from a third-party runtime,
name that explicitly. Do not simply say "checked browser" without evidence.

## KomodoLab dashboard baseline

For dashboard layout/control changes, the normal validation packet is:

- `npm run build` in `lab/dashboard`.
- Focused Python tests for changed dashboard contracts when available.
- Browser opens `/botlab/` successfully.
- The changed view or control is exercised.
- Console checked for blocking React/Vite/dashboard errors.
- Desktop viewport checked.
- Narrow/mobile-ish viewport checked when layout changed.
- Screenshot or geometry assertion recorded for layout changes.

## Runtime failure probes

Recent dashboard regressions were not caught by TypeScript, Vite build, or source
inspection alone. Use these probes whenever the touched code is near the listed
area.

### 3D map and asset loading

Run a browser smoke against both Mockup and Live 3D when touching map assets,
`mapScene.ts`, `BotLab3D.tsx`, route display, GLB generation, or layout state:

```text
/botlab/?views=mockup,live3d
```

Record:

- Console output containing `GLTFLoader`, `RangeError`, `Unexpected token`, `.glb`,
  `mapScene`, or `ztricks`.
- Network responses for `/botlab/maps/*.glb`.
- Whether the loaded asset response is really `model/gltf-binary` with `glTF`
  magic, not routed HTML.
- Whether unknown or aliased maps render a non-crashing empty/unavailable state.

Known regression classes to guard:

- GLB `bufferView` entries missing the required `buffer` index.
- Adding wireframe children while iterating `Object3D.traverse`, which can recurse
  until `Maximum call stack size exceeded`.
- Raw telemetry map names that do not match committed assets, for example
  `ztricks` needing the committed `trick.glb` asset.

For Live Game / QTV work, also record:

- QTV relay URL.
- WebSocket URL.
- Whether the iframe is connected, retrying, or failed.
- Relevant console/network errors from the FTE/QTV runtime.

If telemetry and Live 3D work while Live Game stays `retrying`, treat that as a
QTV/relay/runtime state split, not a generic dashboard connection failure. The
test run should say which path is healthy and which path is failing.

### Records and KPI data

For KPI dock, scoreboard, records, and verdict changes, record the responses for:

```text
/botlab/records.json
/botlab/verdicts.json
```

Distinguish these outcomes:

- Valid data loaded and rendered.
- Expected missing optional data, such as `verdicts.json` not deployed yet.
- Misconfigured required data, such as `records.json` returning 404 while the UI
  presents it as a runtime scoreboard error.

Do not collapse these into a generic "records unavailable" note when the user
story depends on reviewing recorded attempts.

### 4v4 validation and casting views

For the fixed-roster 4v4 validation panel, validate both the normal dashboard
layout and a narrow viewport:

```text
/botlab/?fixture=4v4&views=game
```

Record:

- The panel loads `4v4-validation.example.json` or the deployed
  `/demos/records/4v4-validation.json` feed.
- Eight bot rows render, four per team.
- The Komodobot row is visually identified.
- Delta values fit in the metric cells without horizontal overflow.
- Missing records remain a feed-status problem and do not crash the dashboard.

For the read-only casting scoreboard, validate the standalone casting URL:

```text
/botlab/?casting=1&fixture=casting
```

Record:

- Two teams and eight player rows render from the KTX match stats document.
- BotLab controls are absent.
- The final/provisional badge matches the source document.
- No player-row text overflows at an OBS-style 16:9 viewport.

Current evidence from the 2026-06-14 implementation run is stored at:

- `lab/evidence/ld-h3-4v4-validation-desktop.png`
- `lab/evidence/ld-h3-4v4-validation-narrow.png`
- `lab/evidence/ld-h3-casting-scoreboard-1280x720.png`
- `lab/evidence/ld-h3-4v4-validation-proof-2026-06-14.md`

### Dragonbot goals & metrics (issue #483)

Golden-path and feed-unreachable-fallback evidence, plus smoke screenshots of
the Match/List/Demo/Bench/Version views proving no regression, captured via
Python `playwright` against a local `vite` dev server (no `chrome-devtools`/
`playwright` MCP server was available in that session — see
`lab/evidence/issue483-dragonbot-goals-metrics-proof-2026-07-13.md` for the
tooling note). Stored at:

- `lab/evidence/issue483-dragonbot-golden-desktop.png`
- `lab/evidence/issue483-dragonbot-golden-narrow.png`
- `lab/evidence/issue483-dragonbot-stale-fallback.png`
- `lab/evidence/issue483-smoke-match-view.png`
- `lab/evidence/issue483-smoke-list-view.png`
- `lab/evidence/issue483-smoke-demo-list.png`
- `lab/evidence/issue483-smoke-bench-status.png`
- `lab/evidence/issue483-smoke-version-history.png`
- `lab/evidence/issue483-dragonbot-goals-metrics-proof-2026-07-13.md`

## Repeatable automation path

When a manual browser case is repeated often or protects important behavior,
promote it to Playwright or an equivalent browser test.

Suggested package scripts for web apps:

```json
{
  "test:web": "playwright test",
  "test:web:headed": "playwright test --headed",
  "test:web:report": "playwright show-report"
}
```

Do not add this dependency to every new spike by default. Add it when the project
reaches a maturity level where repeated UI regressions are more expensive than
the test harness.

## Agent checklist

Before claiming a UI task is done:

- Is the app running from the same path the user will use?
- Did the browser open the exact URL?
- Did the visible workflow work, not just the component render?
- Did any console error point to the changed code?
- Did layout still work at the relevant viewport sizes?
- Is the result tied to a durable test case or clearly marked exploratory?
