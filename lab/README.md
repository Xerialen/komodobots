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

### Layout (v1, LD-A1)

Two panels: left the three.js telemetry scene (`BotLab3D.tsx` + `TelemetryHud.tsx`,
fed by `telemetryClient.ts`), right the live game iframe. `public/` carries the dm3
render mesh (`dm3.obj`) and the human reference trajectory (`dm3_sng_to_rl.cmds`),
served under `/botlab/`. The view shell, KPI dock, and the rest of the SPEC views land
in later tickets (LD-B1+).
