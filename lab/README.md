# lab/ — Lab Dashboard

**komodobots `lab/` is now the canonical home of the botlab dashboard.** The page
previously lived in the separate `Xerialen/local-hub` repo only as a patch against a
gitignored hub fork (`deploy/frontend-botlab.patch` on the `feat/botlab-viewer` branch);
LD-A1 (#84) absorbed those sources here as komodobots-owned code. The local-hub copy is
deprecated for development — change the dashboard here, never via the patch.

- `SPEC.md` — functional specification for Lab Dashboard v1 (tickets #84–#108).
- `dashboard/` — the frontend app (Vite + React + TypeScript + three.js).
- `deploy_dashboard.py` — additive deploy/staging/cutover script (LD-A2, #85; see below).
- `evidence/` — validation screenshots referenced by the stage PRs.

## dashboard/

Self-contained single-page app, built with base `/botlab/` so the production build is
fully self-contained under that path (no hashed chunks leak into a shared `assets/`
dir, which the old local-hub deploy did). Deployed target: served by `web/serve.py` on
servexeri at `http://192.168.86.33:8095/botlab/`. Deploys go through
`lab/deploy_dashboard.py` (LD-A2, #85); until the owner-approved cutover runs, the live
URL still serves the old local-hub artifacts while the komodobots build sits staged
next to it.

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
- open view set — `?views=demo,mockup,live3d,game` (any subset; wins over the
  localStorage-persisted layout; see "Layout" below)

Build and preview:

```bash
npm run build      # tsc typecheck + vite build -> dist/ (all paths under /botlab/)
npm run preview    # serves the production build at http://localhost:4173/botlab/
```

### Deploy (LD-A2, #85)

`lab/deploy_dashboard.py` (stdlib-only; needs `ssh servexeri` and `npm` on PATH;
rsync runs remotely on servexeri, none needed locally). Three modes:

```bash
python lab/deploy_dashboard.py --stage          # default: build + stage (ADDITIVE)
python lab/deploy_dashboard.py --audit-assets   # read-only legacy shared-chunk report
python lab/deploy_dashboard.py --cutover --confirm-live   # OWNER APPROVAL ONLY
```

- `--stage` builds `dashboard/` and ships `dist/` to
  `servexeri:~/local-hub/web/botlab-staged/` (a new dir; nothing currently served
  is modified). Idempotent: re-running after an unchanged rebuild reports
  `rsync itemized changes: NONE` (checksum quick-check, so fresh build mtimes
  don't force re-transfers). Because the app is built with base `/botlab/`, the
  staged copy's JS/CSS won't resolve until cutover — deliberate, so the staged
  artifact stays byte-identical to what cutover promotes.
- `--cutover` backs up the live `botlab/` to `~/local-hub/web-backups/` (additive),
  then promotes `botlab-staged/` → `botlab/` so the same URL serves the new app.
- **Do-not-overwrite-siblings rule:** the web root also serves `/qtv/`, `/demos/`,
  `/games/` etc. The script can only rsync into a closed allowlist
  (`botlab-staged/`, `botlab/` — enforced in `validate_remote_target`), and every
  remote sync captures sha256 hashes of all sibling entry HTML before/after and
  exits non-zero on any drift. Never deploy by hand-rsyncing into `web/`.
- `--audit-assets` only reports which legacy `web/assets/` chunks are referenced
  by pages outside `botlab*/`; unreferenced ones may be removed manually AFTER
  cutover. The script never deletes outside the allowlist.

Unit tests for the command builders, allowlist guard, and evidence parsers:
`tests/test_deploy_dashboard.py`.

### CI

`.github/workflows/lab-dashboard-ci.yml` runs on hosted `ubuntu-latest` for pull
requests touching `lab/**` or `tests/lab_*.py` (lab pytest files, which the
`PR Tests` `test_*.py` unittest discovery does not run). It installs
`dashboard/`, runs `tsc --noEmit`, runs
`npm run lint` when a lint script exists, builds with Vite, and does cheap Python
checks for `lab/server/` plus future `lab/tools/`. The workflow deliberately does
not touch the servexeri lab server or the manual self-hosted `lab-ci.yml` runner.

### Layout (LD-B1 view shell, #87)

The shell renders a top bar (four view toggles + KPI/Control stub buttons + status
line) over a fixed-order pane grid: **Demo → Mockup → Live 3D → Live Game** (SPEC §4.1
— panes always appear in this left→right order regardless of toggle order; equal
widths, 280 px min-width each, centered hint when zero views are open). Live 3D is the
three.js telemetry scene (`BotLab3D.tsx` + `TelemetryHud.tsx`, fed by
`telemetryClient.ts`); Live Game is the temporary `/qtv/` iframe (until LD-B2, #88);
Demo and Mockup are labeled placeholders (until LD-D3 #94/#98 and LD-C3 #97). The KPI
dock and control drawer are labeled placeholders too (LD-E1 #100, LD-F3 #105) — their
buttons already toggle + persist the collapse/open state.

Layout state (`src/layoutState.ts`): the open view set, dock-collapsed and drawer-open
flags persist in `localStorage` (`komodobots.botlab.layout.v1`); the open set is also
mirrored into the URL as `?views=demo,live3d` (shareable layouts). On load an explicit
`?views=` param wins over localStorage — including `?views=` (empty) for zero views.

`public/` carries the dm3 render mesh (`dm3.obj`) and the human reference trajectory
(`dm3_sng_to_rl.cmds`), served under `/botlab/`.

`public/maps/` (LD-C2, #91) carries the scripted worldmodel meshes for the whole lab
map set — `{dm3,dm2,frobodm2,trick}.obj` plus `maps.json` (per-map source-BSP sha256
provenance and the world AABB whose center is the Mockup view's camera start, #97) —
built deterministically by `lab/tools/bsp_to_obj.py` from the non-committed `.bsp`
files (see `docs/06_DATA_AND_MVD_PIPELINE.md` § Map meshes). The top-level
`public/dm3.obj` is the legacy one-off export the deployed viewer still loads; it is
superseded by `maps/dm3.obj` once #97 switches the viewer to `maps/`.

