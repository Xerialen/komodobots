# lab/ — Lab Dashboard

**komodobots `lab/` is now the canonical home of the botlab dashboard.** The page
previously lived in the separate `Xerialen/local-hub` repo only as a patch against a
gitignored hub fork (`deploy/frontend-botlab.patch` on the `feat/botlab-viewer` branch);
LD-A1 (#84) absorbed those sources here as komodobots-owned code. The local-hub copy is
deprecated for development — change the dashboard here, never via the patch.

- `SPEC.md` — functional specification for Lab Dashboard v1 (tickets #84–#108).
- `dashboard/` — the frontend app (Vite + React + TypeScript + three.js).
- `evidence/` — validation screenshots referenced by the stage PRs.

## dashboard/

Self-contained single-page app, built with base `/botlab/` so the production build is
fully self-contained under that path (no hashed chunks leak into a shared `assets/`
dir, which the old local-hub deploy did). Deployed target: served by `web/serve.py` on
servexeri at `http://192.168.86.33:8095/botlab/` (deploy script + cutover is LD-A2, #85;
until that merges, the deployed copy still comes from the old local-hub artifacts).

### Dev loop

```bash
cd lab/dashboard
npm ci
npm run dev        # vite dev server at http://localhost:5173/botlab/
```

The page talks to live LAN services by default:

- telemetry sidecar `ws://192.168.86.33:8770` (`scripts/telemetry_ws.py`) — override
  with `?ws=ws://localhost:8770` (e.g. through an ssh -L tunnel)
- live game view iframe `http://192.168.86.33:8095/qtv/` — override with `?game=...`;
  this is a temporary embed, replaced by the standalone postMessage QTV pane in LD-B2 (#88)
- status-line fallback port `28599` — override with `?port=28600`

Build and preview:

```bash
npm run build      # tsc typecheck + vite build -> dist/ (all paths under /botlab/)
npm run preview    # serves the production build at http://localhost:4173/botlab/
```

### CI

`.github/workflows/lab-dashboard-ci.yml` runs on hosted `ubuntu-latest` for pull
requests touching `lab/**` or `tests/lab_*.py` (lab pytest files, which the
`PR Tests` `test_*.py` unittest discovery does not run). It installs
`dashboard/`, runs `tsc --noEmit`, runs
`npm run lint` when a lint script exists, builds with Vite, and does cheap Python
checks for `lab/server/` plus future `lab/tools/`. The workflow deliberately does
not touch the servexeri lab server or the manual self-hosted `lab-ci.yml` runner.

### Layout (v1, LD-A1)

Two panels: left the three.js telemetry scene (`BotLab3D.tsx` + `TelemetryHud.tsx`,
fed by `telemetryClient.ts`), right the live game iframe. `public/` carries the dm3
render mesh (`dm3.obj`) and the human reference trajectory (`dm3_sng_to_rl.cmds`),
served under `/botlab/`. The view shell, KPI dock, and the rest of the SPEC views land
in later tickets (LD-B1+).

### Demo pane (LD-D2, #94) — `public/panes/demo.html`

Standalone FTE WASM demo player at `/botlab/panes/demo.html`, designed to be iframed by
the view shell (LD-D3, #98) but fully usable as a direct URL. Modeled on the working
precedent `local-hub/web/demos/play.html`: the demo is mapped as virtual file
`qw/match.<ext>` and `panes/fte_demo.cfg` (mapped to `id1/config.cfg`) starts playback
with `playdemo match` at the correct moment, after FTE has downloaded every virtual file.

URL params: `?demo=<url>&map=<name>&t=<seconds>&track=<userid>` (optional:
`&duration=<seconds>` bounds the seek bar, `&name=<label>`). With `t`, the pane seeks to
`max(0, t-2)` once playback rolls — 2 s pre-roll, ±2 s in-spec (SPEC §6.5; engine seek
granularity is ≈1 s).

postMessage API (same-origin only; events are emitted only when embedded):

- inbound: `{cmd:"load", demo, map, t?, track?}` (reloads the page — one FTE instance
  per window, reload is the reliable reset), `{cmd:"seek", t}`, `{cmd:"speed", pct}`,
  `{cmd:"pause"}`, `{cmd:"play"}`
- outbound: `{evt:"status", state, detail?}` on every state change
  (`loading|playing|seeking|ended|error`), `{evt:"time", t}` at 1 Hz, `{evt:"ended"}`

Map `.bsp` resolution is **local-first**: the pane HEADs `/maps/<map>.bsp` on its own
web tier before falling back to `https://assets.quake.world/maps/<map>.bsp`, so lab-only
maps play without being published to the CDN.

Engine behavior notes (measured during LD-D2 validation, FTE git-30-0a71790):

- **Demo parser is picked by the virtual filename extension.** A `.qwd` mapped as
  `match.mvd` dies with `mvd demos/qtv streams should not contain dem_cmd`; the pane
  maps `.qwd` demos as `match.qwd`.
- **The demo clock is wall-anchored and load hitches are swallowed.** With the stock
  config a 9 s human `.qwd` was consumed to its end before the first rendered frame.
  Mitigation chain: `fte_demo.cfg` boots the demo paused → the pane waits until the
  clock settles and the render loop flows → creeps at 10% speed through the first
  world-render hitch → restores full speed → if the surviving offset still exceeds
  1.5 s, one corrective backward `demo_jump` recovers the start (clean once the map is
  cached). Result: playback from ≈1 s at true 1.0 s/s pacing for both formats.
- **Backward seek = engine restart + fast-forward** (SPEC §6.6); measured landings are
  within ±0.2 s of target in both directions.
- **QWD end-of-demo does not fire `f_demoend`**, so the `ended` sentinel only covers
  MVD; a 10 s stalled-clock fallback emits `ended` for QWD (≈11 s latency, honest).

### Deploy (pending LD-A2 #85 cutover)

The pane ships inside `dist/` like the rest of the app — no extra deploy step. Two
web-root requirements on servexeri (`~/local-hub/web/`, served by `web/serve.py` on
:8095), **documented here but not yet applied — the lab host is read-only until the
LD-A2 deploy path lands**:

- `maps` symlink → `~/nquakesv/qw/maps` (enables the local-first `.bsp` resolution:
  `ln -s ~/nquakesv/qw/maps ~/local-hub/web/maps`). Verified absent as of 2026-06-11.
- demo archive exposure: `/demos/files/non-games/` already serves
  `/mnt/usb-ssd/non-games/` (existing symlink from the local-hub demo browser), which
  includes the lab archive `lab/Komodobots/<map>/<run_id>.mvd` and `human/*.qwd`
  written by `scripts/demo_archive.py`.

`public/maps/` (LD-C2, #91) carries the scripted worldmodel meshes for the whole lab
map set — `{dm3,dm2,frobodm2,trick}.obj` plus `maps.json` (per-map source-BSP sha256
provenance and the world AABB whose center is the Mockup view's camera start, #97) —
built deterministically by `lab/tools/bsp_to_obj.py` from the non-committed `.bsp`
files (see `docs/06_DATA_AND_MVD_PIPELINE.md` § Map meshes). The top-level
`public/dm3.obj` is the legacy one-off export the deployed viewer still loads; it is
superseded by `maps/dm3.obj` once #97 switches the viewer to `maps/`.
