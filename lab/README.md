# lab/ — Lab Dashboard

**komodobots `lab/` is now the canonical home of the botlab dashboard.** The page
previously lived in the separate `Xerialen/local-hub` repo only as a patch against a
gitignored hub fork (`deploy/frontend-botlab.patch` on the `feat/botlab-viewer` branch);
LD-A1 (#84) absorbed those sources here as komodobots-owned code. The local-hub copy is
deprecated for development — change the dashboard here, never via the patch.

- `SPEC.md` — functional specification for Lab Dashboard v1 (tickets #84–#108).
- `dashboard/` — the frontend app (Vite + React + TypeScript + three.js).
- `server/` — lab-host (servexeri) server-side pieces: `records_build.py` (LD-D1, #93)
  and `control_bridge.py` (LD-F2, #96).
- `tools/` — build steps that export committed experiment data as stable
  dashboard data files (currently `build_routes_manifest.py`, LD-C1 #90).
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

### Routes manifests (`public/data/routes/`, LD-C1)

The canonical "what routes exist" feed for the Mockup view, KPI dock and control
drawer: per-map JSON (`dm3.json`, `dm2.json`, `frobodm2.json`, `trick.json`) plus
`index.json`, schema `komodobots.routes.v1`. Built from the committed trick census
(`experiments/nav_doctrine/evidence/trick-census/census.json`) and the committed human
replay trajectories (`experiments/nav_doctrine/evidence/replay/dm3_<route>.cmds`) —
the dashboard never parses experiment-internal files ad hoc. Each dm3 route carries
human stats (duration, active-mean/peak speed), a downsampled display polyline, gap
markers (edge/land, `required_speed` vs `human_speed_at_edge`), teleports, and source
provenance with sha256 hashes. Non-dm3 maps are honest empty route lists until routes
are censused there.

The manifests are committed and deterministic. Regenerate after a census/replay
change (the unit test fails if they go stale):

```bash
python lab/tools/build_routes_manifest.py   # rewrites lab/dashboard/public/data/routes/
```

Full schema in the `lab/tools/build_routes_manifest.py` header; tests in
`tests/test_build_routes_manifest.py`.

`public/maps/` (LD-C2, #91) carries the scripted worldmodel meshes for the whole lab
map set — `{dm3,dm2,frobodm2,trick}.obj` plus `maps.json` (per-map source-BSP sha256
provenance and the world AABB whose center is the Mockup view's camera start, #97) —
built deterministically by `lab/tools/bsp_to_obj.py` from the non-committed `.bsp`
files (see `docs/06_DATA_AND_MVD_PIPELINE.md` § Map meshes). The top-level
`public/dm3.obj` is the legacy one-off export the deployed viewer still loads; it is
superseded by `maps/dm3.obj` once #97 switches the viewer to `maps/`.

## Control bridge (LD-F2, #96)

`server/control_bridge.py` adds a browser→lab-server command channel **inside the
existing telemetry sidecar** (`scripts/telemetry_ws.py`, screen `kbot-telemetry`,
`ws://servexeri:8770`) — no new service, no new port. Clients send JSON text frames
on the same websocket; telemetry frames keep streaming regardless.

```text
client -> server   {"op", "req_id", ...}
server -> client   {"re": req_id, "ok", "detail", ...}
server -> all      {"type": "control_event", "event", ...}   on successful mutation
```

Ops: `session_start {map, force?}` · `session_stop {port?, force?}` · `set_map {map}`
· `addbot {count?}` · `removebot {slot?|all}` · `set_cvar {name, value, slot?}` (slot
maps to the LD-F1 `_s<N>` per-slot form) · `console {line}` · `lock_status` ·
`verdict` (reserved for LD-F5, #106).

### Security (binding, all enforced server-side)

- Caller authorization (Codex P1, #129): every mutating op requires a **trusted
  caller** — a loopback peer (operator on servexeri, or an
  `ssh -L 8770:localhost:8770` tunnel) or a request `token` matching the per-deploy
  secret at `~/komodobots-lab/control.token` (auto-generated 0600 on first start,
  constant-time compare, value redacted in the audit log; override the path with
  `--control-token-file`). With no token configured, remote peers can never mutate.
- Browser CSRF gate: a websocket connection that presented an `Origin` header only
  reaches the control channel when that origin is allowlisted via `--allow-origin`
  (repeatable, exact match; default empty = browser clients are telemetry-only).
  This is defense in depth on top of the loopback/token check, never a substitute —
  the LD-F3 UI deploy must pass both the dashboard origin and the token.
  Telemetry frames and `lock_status` stay readable without auth, as before.
- Target port allowlist **28599–28609 only**; production **28501/28502/28503 are
  untouchable** — those port numbers and `qw_*` screen names are flat-denied anywhere
  in any command path (bridge dispatch AND executor re-check).
- Cvar allowlist: `k_fb_*`, `timelimit`, `fraglimit`, `samelevel`. Console lines pass a
  first-token allowlist plus a denylist (`rcon*`, `exec`, `alias`, `sv_crypt*`, `quit`,
  anything path-like or `;`-chained).
- LAN-only exposure: the sidecar keeps its existing bind; no tunnel/ingress route may
  be added for it.
- Every mutating command attempt (allowed **and** refused) is appended with
  timestamp + peer + op to `~/komodobots-lab/control-audit.log` (JSON lines).

### Lab lock (experiment harness has absolute priority)

JSON lock at `~/komodobots-lab/lab.lock`: `{owner: harness|dashboard, run_id, pid, ts}`
(+ `port`, `map` for dashboard sessions). The harness remote script writes
`owner=harness` at server start and removes it in cleanup including failure paths;
while that lock is **fresh** (pid alive, age ≤ 2 h) the bridge refuses every mutating
op with `"experiment harness owns the lab"`. A stale lock (dead pid or > 2 h) is taken
over only with an explicit `force=true` on `session_start`/`session_stop` (UI confirm
lands in LD-F3, #105). Dashboard sessions use screens named `komodobots_lab_<port>`;
the harness refuses to start on a port one occupies.

### Deployment + restart procedure (`kbot-telemetry` screen on servexeri)

The sidecar is deployed flat: `telemetry_ws.py` + `moveprobe_parse.py` (existing) +
`control_bridge.py` + `qw_min_client.py` (new, for bot ops via a connected client —
`botcmd` is not a server-console command) in the same directory. Without
`control_bridge.py` the sidecar degrades to telemetry-only and says so on stdout.

```bash
# on servexeri — copy the four files, then restart the screen:
screen -S kbot-telemetry -X quit   # stop (telemetry consumers reconnect automatically)
screen -dmS kbot-telemetry python3 ~/komodobots-lab/sidecar/telemetry_ws.py \
    --allow-origin http://192.168.86.33:8095
screen -ls | grep kbot-telemetry   # verify it is back
# first start auto-creates the control token at ~/komodobots-lab/control.token (0600);
# remote (non-loopback, non-browser) control clients send it as "token" per request,
# or skip the token entirely via: ssh -L 8770:localhost:8770 servexeri
# telemetry-only fallback if the bridge must be disabled:
#   ... telemetry_ws.py --no-control
```

Live end-to-end verification (golden-path transcript, security negative tests, lock
tests, production-untouched evidence) rides the next declared lab slot — see the
LD-F2 PR for the checklist.
