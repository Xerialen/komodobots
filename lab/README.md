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
- open view set — `?views=demo,mockup,live3d,game` (any subset; wins over the
  localStorage-persisted layout; see "Layout" below)

Build and preview:

```bash
npm run build      # tsc typecheck + vite build -> dist/ (all paths under /botlab/)
npm run preview    # serves the production build at http://localhost:4173/botlab/
```

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
