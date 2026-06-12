# Agent Web Testing

Status: living workflow document.

## Default rule

Every meaningful web/UI change must be validated by an agent in a real browser
before it is called done.

Builds and unit tests are necessary, but they do not prove the visible workflow.
For web work, the evidence should include a browser check.

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

For Live Game / QTV work, also record:

- QTV relay URL.
- WebSocket URL.
- Whether the iframe is connected, retrying, or failed.
- Relevant console/network errors from the FTE/QTV runtime.

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
