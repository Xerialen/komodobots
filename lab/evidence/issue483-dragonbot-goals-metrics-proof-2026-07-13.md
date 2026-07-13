# Issue #483 — Dragonbot goals & metrics dashboard section — Proof Run 2026-07-13

Scope: the new "Dragonbot" TopBar tab/section on the Bot Lab evidence page
(`lab/dashboard`), reading `dragonbot.hub_feed.v1` from Xerialen/dragonbot, plus
the servexeri-side mirror build script (`lab/server/dragonbot_hub_feed_build.py`)
and smoke evidence that the existing Match/List/Demo/Bench/Version views are
unregressed.

## Inputs

- Real upstream feed fetched via `gh api
  repos/Xerialen/dragonbot/contents/artifacts/hub/goals-metrics.json` (schema
  `dragonbot.hub_feed.v1`, merged to Xerialen/dragonbot main same day per PR #56).
- Local dev fixture (same content, `fetchedUtc` intentionally omitted — see
  `docs/02_SOURCE_MAP.md`):
  `lab/dashboard/public/data/dragonbot-hub-feed.example.json`
- Dashboard URL (dev server): `http://localhost:5183/botlab/?view=dragonbot&fixture=dragonbot`
- Base branch note: this work branches from `feat/central-dashboard` (open PR
  #482), not `main` — see `docs/08_DECISION_LOG.md` 2026-07-13 entry for why.

## Commands

```powershell
python -m unittest tests.test_dragonbot_hub_feed_build -v
python -m unittest discover -s tests -p "test_*.py"
cd lab\dashboard
npm ci
npx tsc --noEmit
npm run build
```

## Results

- `tests/test_dragonbot_hub_feed_build.py`: 21 passed (token resolution from
  `$GITHUB_TOKEN` and `~/.git-credentials`, contents-API URL/decode, schema/shape
  validation, atomic write, and two fail-closed `main()` cases proving the
  previously-published snapshot is left byte-for-byte untouched on a token or
  fetch failure).
- Full stdlib suite: 2026 tests, 7 errors — all `/dev/shm`-path failures in
  `test_move_policy_sidecar.py`, pre-existing and platform-specific (this
  session ran on Windows, where `/dev/shm` does not exist); unrelated to this
  change. No new failures introduced.
- `tsc --noEmit`: clean.
- `vite build`: clean (pre-existing >500 kB chunk-size advisory only, unrelated
  to this change).

## Browser Evidence

Tooling: Python `playwright` (already installed on this machine with cached
Chromium builds under `%LOCALAPPDATA%\ms-playwright`) driving a headless
Chromium against the local `vite` dev server (`npm run dev -- --port 5183`).
No `chrome-devtools`/`playwright` MCP server was available in this delegated
session, so the browser was driven directly via the Python `playwright`
package instead (script kept at
`C:\Users\benya\AppData\Local\Temp\claude\...\scratchpad\dragonbot_screenshots.py`,
not committed — throwaway validation tooling).

### Golden path

- `lab/evidence/issue483-dragonbot-golden-desktop.png` (1440x1000): the
  Dragonbot tab selected, Goal Ladder (G1 frag margin `-17.02 ± 9.63` in red
  against the "frag margin > 0" target label; G2 elite bands table with the
  `validityCaveat` rendered verbatim in the amber callout), Metrics Timeline
  (three batch cards — the Gate D ABBA experiment shows ref-vs-treatment
  `sg.accuracy` plus `Δ`/`z`, and a red BLOCK decision badge; the two
  control_batch rows show a single stat and "no ABBA decision"; `sg.accuracy`
  renders `—` for both control batches, never `0`), Eval Loop (CLEAN badge, C
  29 / D 14 / I 5 tactical tally, per-lens breakdown table, and working links
  to `EVAL-ref-m02.md`/`EVAL-ref-m05.md` on GitHub).
- `lab/evidence/issue483-dragonbot-golden-narrow.png` (420x900): same data at
  a phone-ish viewport. Goal/metric cards reflow to a single column via
  `flexWrap`; the page remains readable. The TopBar nav itself does not wrap
  and the content column does not stretch to fill a narrow viewport — this is
  pre-existing behavior shared by every other evidence-page view at this
  width (verified directly against `?view=versions&fixture=4v4` at the same
  420x900 viewport, `versions-narrow-baseline.png` locally, not committed —
  identical TopBar/gutter behavior), not a regression introduced by this
  change.

### Feed-unreachable fallback

- `lab/evidence/issue483-dragonbot-stale-fallback.png`: after the initial
  successful load, subsequent polls to the fixture URL were intercepted and
  aborted (`page.route(...).abort("failed")`) to simulate the feed going
  unreachable. The panel renders the exact same last-good snapshot (all
  numbers, badges, and the caveat text unchanged) with an amber banner:
  "showing last-good snapshot — the dragonbot feed is currently unreachable or
  stale (Failed to fetch)". No fabricated numbers, no blank state, no crash.

### Smoke: existing views unregressed

`?view=<name>&fixture=4v4` for each, with the new DRAGONBOT tab visible in the
TopBar nav alongside the others in every screenshot:

- `lab/evidence/issue483-smoke-match-view.png` — full 4v4 Match View renders
  (banner, team heads, comparison bars, all-eight-bots table) exactly as
  before.
- `lab/evidence/issue483-smoke-list-view.png` — expected "loading match
  history… (kb2-matches.json)" empty state (the kb2 feed is not deployed on
  the local dev server / no `fixture=kb2` was requested in this smoke pass;
  pre-existing behavior, not a regression).
- `lab/evidence/issue483-smoke-demo-list.png` — same expected empty state as
  List View (kb2 feed not present locally).
- `lab/evidence/issue483-smoke-bench-status.png` — "BENCH IDLE" state (no
  bench feed locally), matches pre-existing empty-state contract.
- `lab/evidence/issue483-smoke-version-history.png` — expected "loading
  version history… (kb2-versions.json)" empty state, same reason as above.

### Console / network

No `pageerror` events across any of the above navigations. Console showed only
expected 404s for feeds not deployed on the local dev server (kb2-matches,
kb2-versions, bench, 4v4 ledger when not using `fixture=4v4`) plus the
intentional `net::ERR_FAILED` / "dragonbot feed fetch failed" pair during the
simulated-outage step — all logged via the existing `logError` helper, not
uncaught exceptions.

## Not validated in this session

- Real deployment of `lab/server/dragonbot_hub_feed_build.py` into the
  servexeri kb2hub-sync cadence (cron/systemd wiring alongside
  `version_history_build.py`), and the resulting `--cutover` to the live hub —
  both owner-coordinated per the ticket; not performed here.
- A live `$GITHUB_TOKEN`/`~/.git-credentials` fetch against the real
  Xerialen/dragonbot repo from servexeri itself (only unit-tested with mocked
  token/fetch layers, plus a one-off `gh api` fetch used to shape the fixture
  and types).
