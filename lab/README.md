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
