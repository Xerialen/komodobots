# Lab Dashboard — functional specification (UX handoff)

Status: living document · Source of truth for **what the dashboard does**.
Audience: the frontend-design pass (#107) and anyone restyling or extending the dashboard.
Scope: behavior, content, states, interactions. Not an engineering doc — implementation
decisions live in `artifacts/lab-dashboard-plan.md` and the tickets.

Traceability: every behavior cites its ticket inline like (#94); tickets #84–#108 form the
milestone **Lab Dashboard v1** (label `labdevelopment`). If this spec and merged behavior
disagree, the merged behavior wins — then update this file (part of "done", see #108).

---

## 1. Purpose & users

**One user.** A Division-1 QuakeWorld player and bot researcher running movement experiments
on a private LAN lab server. He is simultaneously the scientist (steering experiments), the
referee (judging whether a bot run looks human), and the only audience. There are no other
personas — no spectators, no teammates, no admins.

**The product is a lab instrument.** The project trains QuakeWorld bots to move like humans
(bunnyhop, trick jumps). The dashboard is the window onto that effort: it must answer, at a
glance and without flattery, two questions:

1. **Is the bot getting better?** — measured against the human, per route, with brutal
   honesty (the KPI dock, §7).
2. **What is the bot doing right now / what did it do?** — watchable evidence: live 3D
   telemetry, the live in-game picture, recorded demos, and the route geometry itself
   (the four main views, §3).

**Environment.** Served at `http://192.168.86.33:8095/botlab/` on the home LAN (#85). Used
on two displays: a 49" 5120×1440 superultrawide and a 27" 2560×1440 (#107). Chrome,
desktop, mouse+keyboard. Sessions are frequent and short: check a result, watch a run,
tweak a cvar, leave it streaming on the side monitor during an experiment block.

**Tone target.** Honest, dense, calm. The dashboard never celebrates prematurely and never
hides a zero. "Brutal" is a design requirement, not a metaphor (#101).

---

## 2. The mental model

### Scoreboard vs instrument panel

The app has exactly two kinds of surface:

- **The scoreboard** — the KPI dock (#100). Four numbers versus targets, always visible
  (even collapsed, the rail still shows them). It answers "are we winning?" It changes
  slowly: after runs, after records, after verdicts.
- **The instrument panel** — the four main views (#87). They answer "what is happening?"
  They change fast: 100 Hz telemetry, live video, demo playback, route browsing.

The user flips between the two constantly: glance, drill in, judge, adjust, glance again.
Keep the scoreboard cheap to see and the instruments cheap to open/close.

### The four views are four tenses of the same subject

Fixed left→right order (#87), and the order is meaningful:

| Position | View | Tense |
|---|---|---|
| 1 (leftmost) | **Demo** | The past — recorded evidence, replayed in-engine (#94, #98) |
| 2 | **Mockup** | The timeless — the map and the human routes, no run attached (#97) |
| 3 | **Live 3D** | The present, from outside — telemetry instruments (#89, #103) |
| 4 (rightmost) | **Live In-Game** | The present, from inside — the actual game picture (#88) |

### Context: everything answers "for which map & route?"

A single shell-level **context** `{map, route|null, source}` drives the KPI dock and ties
the surfaces together (#100). Producers:

- **live** — a running attempt (telemetry attempt metadata).
- **mockup** — the user selected a map/route in the Mockup view (#97).
- **demo** — the demo being played, when known (a record demo knows its route) (#98).

**Precedence: live wins while an attempt is running; otherwise the most recent user
selection (mockup or demo).** When the attempt ends, context returns to the last user
selection (#100). The current context is always displayed at the top of the dock, e.g.
`dm3 · sng_to_rl · live`, with its source badge.

### Browse mode vs live session

- **Browse mode** (no attempt running): the dashboard is a study tool — replay records,
  inspect route geometry, read the scoreboard. Everything works offline from committed/
  archived data; nothing requires the lab server.
- **Live session**: an attempt is streaming. Live panes animate, the dock grows a live
  metrics section (#102), context locks to the attempt. Live sessions come from two
  origins the user treats differently:
  - **harness-owned** — the scripted experiment queue owns the lab; the dashboard is
    read-only (watch, but the control panels refuse) (#96);
  - **dashboard-owned** — the user started a session from the control panel and may
    spawn bots, assign routes, send cvars, and change allowlisted game controls (#105).

---

## 3. View inventory

### 3.1 Top bar (shell chrome)

Always visible (#87).

- **Four view toggles** `[Demo | Mockup | Live 3D | Live Game]` — independent on/off;
  any subset including none (none → centered hint in the empty pane area).
- **KPI dock collapse/expand control** (#100).
- **Control panel button** — opens the right-side control panel (#105).
- **Console button** — opens the cvar console side panel (#105).
- **Status line**: `map · port · run_id · telemetry state` (e.g.
  `dm3 · port 28599 · 20260605T201217Z · connected`; `no attempt yet` when idle) (#84, #87).

### 3.2 Demo view (leftmost main view)

**Purpose.** Watch recorded runs — record-holders, archived attempts, human reference
demos — as the *actual in-game rendering*, with seek. This is where claims get verified by
eye (#94, #98).

**Content.**
- **Picker header** with two source tabs (#98):
  - **Records** — the records registry (§8): per route → record kind → click to play.
  - **Archive** — every archived lab demo (newest-first, filterable by map) plus the
    human reference demos in the `human/` subtree.
- **Player area** — an embedded game engine (FTE WASM in an iframe; see §10 iframe note)
  playing the selected `.mvd`/`.qwd` file in-game.
- **Transport controls** — play/pause, seek bar (when duration is known), playback speed
  (#94). Skeleton-quality now; the design pass owns their final form (#107).

**States.** empty (nothing selected — picker prominent) · loading · playing · ended ·
error (bad/missing demo file → explicit error state, never an infinite spinner) (#94);
Records tab unavailable (records fetch failed → explicit error in that tab, Archive still
works) (#98).

**Key interactions.** Pick → play; record click → seek-to-event with 2 s pre-roll (§6.5);
transport incl. backward seek (§6.6). Picking a new demo while one plays switches cleanly;
while playing, the view emits context `{map, route?}` (#98).

### 3.3 Mockup view — offline 3D browser

**Purpose.** Browse maps and study routes *without any run*: the platonic reference. What
does the route look like, where are the gaps, what speed does each gap demand (#97)?

**Content.**
- **Map selector**: `dm3 · dm2 · frobodm2 · trick` (#91, #97).
- **3D scene**: the textured map mesh (default quite transparent, §3.8), free-orbit
  camera starting at a per-map overview point (#91, #97).
- **Route browser**: the censused routes for the map (11 on dm3, §7.2; from the routes
  manifest, #90) with human stats (duration, active-mean speed, peak). Selecting a route draws its **human reference
  polyline** plus **gap markers** at the census launch-edge/landing points, labeled
  `required <speed> vs human <speed>` (e.g. the sng_to_rl decisive gap: required 526,
  human carried 528). Teleporter entrances are marked. Multiple routes can be shown at
  once in distinct colors (#97).
- **Empty-map honesty**: dm2/frobodm2/trick currently have no censused routes — the list
  says so explicitly ("no censused routes yet") rather than hiding (#97).

**States.** map + no route · one/many routes selected · empty-route-list map.

**Key interactions.** Map switch; route select/deselect (multi); orbit/zoom; opacity +
wireframe (§6.3). Selections emit context `{map, route}` (#97, #100).

### 3.4 Live 3D view

**Purpose.** The instrument view of the running attempt: trajectory, speed, and geometry
from outside, at telemetry rate (#89).

**Content.**
- Textured map mesh of the live map (same scene rig as Mockup) (#99).
- **Per-bot live objects** (#103): position marker, growing trail (the path so far),
  velocity arrow (length ∝ speed), small name label. Distinct stable color per bot.
- **Human reference line** for the route, toggleable (today: cyan line from the human
  `.cmds` trajectory) (#84).
- **Telemetry HUD** (bottom overlay, ~12 Hz display refresh of a ~100 Hz stream): speed,
  yaw rate, onground/air, hop count, air time, current vs optimal strafe angle (#84);
  with multiple bots, one compact row per bot (up to ~4) and the selected bot expanded
  (#103).

**States.** waiting for attempt (idle scene, "waiting for attempt…") · live single-bot ·
live multi-bot · telemetry disconnected (explicit state, not a frozen scene) (#84).

**Key interactions.** Orbit/zoom (user camera preserved across updates); click a marker or
HUD row → camera follows that bot, overview framing when several and none selected (#103);
reference-line toggle; opacity + wireframe (§6.3). `new_attempt` clears trails and re-arms;
a bot removed mid-session freezes/greys rather than vanishing mid-frame (#89, #103).

### 3.5 Live In-Game view (rightmost main view)

**Purpose.** The actual game picture of the live attempt — what a spectator camera in the
real engine sees. The eye-test instinct lives here and in Demo (#88).

**Content.** Embedded game engine (FTE WASM iframe) attached to the lab server's QTV
stream; **status chip** in the pane header: `loading | connected | retrying |
disconnected` (#88).

**States.** The lab server is *ephemeral* — it exists only while a session runs, so
disconnect→retry is the **normal** cycle, not an error: no attempt → "retrying/waiting"
(calm, not alarming); attempt live → connected; attempt ends → back to retrying; next
attempt → auto-reattaches without a reload (~3 s retry loop) (#88).

**Key interactions.** None beyond watching; attach/detach is automatic per attempt (port
from attempt metadata, default 28599). The engine's own mouse/keyboard capture exists
inside the iframe but is not part of the dashboard's interaction model.

### 3.6 KPI dock (left dock, not a main view)

**Purpose.** The scoreboard: four numbers vs targets, live metrics during a session,
records — all context-sensitive (#100). Detailed definitions in §7–§8.

**Content, top to bottom (expanded, ~300 px wide, full height, semi-opaque):**
1. **Context line** — `map · route · source` (#100).
2. **The brutal scoreboard** — The Race, Jump Count, Speedometer, Eye Test; each a large
   number with its target and delta (#101); plus the eye-test entry control (#106).
3. **Live section** — only while `source = live`: current speed sparkline, arc-local
   human comparison, launch-edge callout, attempt meta (#102). Otherwise collapsed to
   "no live session".
4. **Records section** — records for the context route (or per-map best table when no
   route context); click-through to Demo view (#104).

**Collapsed rail mode:** a slim vertical rail showing the four scoreboard numbers in
micro form; live section and records hidden (#100, #101, #104). Collapse state persists.

**States.** expanded · rail · per-section: fresh / stale-or-error badge (records fetch
failed — the dock never silently shows outdated numbers as current) (#101) · live vs
browse (#102) · no-data ("honest zeros", §7).

### 3.7 Control side panels (not main views)

**Purpose.** Steer the lab: start/stop a session, pick the map, spawn/remove bots, assign
each bot its route, send cvars — *lab server only*, always subordinate to the experiment
harness (#96, #105).

**Content.**
- **Session block**: start/stop, target port, **lock-state badge** (who owns the lab:
  `harness | dashboard | free`, with force-takeover confirm for stale locks) (#96, #105).
- **Map selector**: dm3 / dm2 / frobodm2 / trick / ztricks (#105).
- **Session start semantics**: starting a dashboard session prepares movement practice,
  not a live match. The bridge seeds the default practice roster, gives known maps
  separated spawn-snap origins to avoid repeated telefrag loops, and puts bots in
  moveprobe practice-idle mode (no movement, jump, or firing) until a per-bot route assignment
  overrides that slot.
- **Game controls**: direct game-level buttons for KTX `4on4`, `2on2`, `1on1`, `ffa`,
  `dmm1`–`dmm4`, powerups on/off (`k_pow` plus q/p/r/s), start game (`ready`), and
  stop game (`break`), prewar, and bot weapon lockout (`axe only` / `weapons free`).
  These control the running game, not the dashboard session. **Start game** clears the
  global practice idle mode, unlocks normal bot weapons, and readies the match; **stop
  game** breaks the match and returns the session to quiet practice.
  A ztricks-only **Distance standstill** preset applies the A5 start-point cvars
  (`spawn_origin`, mode 23, far-platform fixed goal, and circle-jump launch knobs)
  clears existing dashboard bots, and spawns one bot so the visible lab can watch a clean standing-start attempt.
  The preset is exposed as **try** beside a **pause** button; pause clears the visible
  trick bot(s) without stopping the session.
- **Bot roster**: one row per live bot — name, slot, **assigned route read back from the
  server** (never optimistic; the roster shows what the server says it is running, #95,
  #105) — plus add-bot / remove-bot controls. A per-row respawn control is enabled
  only when it is safe to be precise: one live bot in this KTX build. Internally that
  uses clear-all + add-one because KTX `removebot` is not reliably slot-addressable.
- **Per-bot route assignment**: a route dropdown per roster row (routes of the current
  map); assigning issues one atomic "assign" action. Two bots may run two *different*
  routes on the same map at the same time — this is the module's acceptance test (#95,
  #105).
- **Cvar console side panel**: separate vertical panel with command history (up/down),
  response echo, inline rejection rendering for denied commands, `@2 k_fb_… value`
  shorthand to target bot slot 2 (#105).

**States.** closed · open+free · open+dashboard-session-running · open+locked-by-harness
(every mutating control disabled, reason shown: "experiment harness owns the lab") ·
open+bridge-disconnected (everything mutating disabled) · stale-lock (takeover offered
behind an explicit confirm) (#96, #105). The control panel and cvar console dock as
solid vertical rails to the right of the view panes.
They consume layout width like the KPI rail; they must never be translucent overlays on
top of Live Game / Live 3D. Esc closes side panels; non-modal — panes keep streaming
beside them (#87, #105).

---

## 4. Layout system

### 4.1 The row

One horizontal arrangement, left to right (#87, #100):

```
[KPI dock | rail] [Demo] [Mockup] [Live 3D] [Live Game]
[Control] [Cvar console]
[--------------------- top bar above all ---------------------]
```

- Open panes share a single row in **fixed order regardless of the order they were
  toggled on** (#87); equal-width by default, with sensible min-widths.
- The KPI dock is a **grid column, not an overlay** — it reflows the panes when it
  collapses/expands; it never covers the Demo view (#100; this is why the dock design
  beat an overlay).
- The control panel and cvar console are side rails: non-modal, vertical, and
  constrained so the panes keep streaming beside them (#105).

### 4.2 The toggle matrix

| Open views | Behavior |
|---|---|
| 0 | Centered hint in the pane area ("toggle a view to begin") (#87) |
| 1 | The single pane fills the row (#87) |
| 2–3 | Equal split in fixed order |
| 4 | Four-up; at narrow widths min-widths bind (see 4.4) |

Layout state (open set, dock collapsed, control panel open, console panel open, opacity value) persists in
localStorage and is reflected in the URL (`?views=demo,live3d`) for shareable layouts;
URL params win on load (#87, #99). Without URL or stored layout, the default open set
is Live Game only; Live 3D is opt-in via the toggle.

Interactions may change the layout: clicking a record opens/focuses the Demo view if it
was closed (#98, #104). That reflow must be unsurprising — the pane appears in its fixed
slot (leftmost), everything else shifts right.

### 4.3 Typical working sets (design for these)

- **Judging a record**: Demo + Mockup (replay left, geometry right) + dock.
- **Live experiment watching**: Live 3D + Live Game + dock (live section active).
- **Steering a session**: drawer open over Live 3D + Live Game.
- **Glance mode** (side monitor): one pane + rail.
- **Everything**: all four + dock — the 49" layout.

### 4.4 Responsive intent (two real targets, no mobile)

- **5120×1440 (49" superultrawide, primary)**: all four panes + expanded dock are
  comfortable (~1175 px per pane). The design pass sets max-widths so panes don't become
  absurdly wide; density tuning at this size is a deliverable of #107.
- **2560×1440 (27")**: 2–3 panes + dock is the realistic working set; all-four must still
  function. Hard floor from the tickets: at 1920 px with all four views + dock open there
  is **no horizontal scrollbar** and every pane respects its min-width (#100).
- **~1280×800 (incidental small window)**: must stay *usable* — panes may deliberately
  stack or scroll; nothing may overlap illegibly (#107). Mechanism is a design decision
  (§11).

---

## 5. State matrix

What every surface shows in each app state. (Degraded states — telemetry down, records
fetch failed, bridge down — overlay any column as explicit badges/states; they never
render as blank or stale-presented-as-fresh. #84, #98, #101, #105)

| Surface | Idle (nothing running, nothing picked) | Browse (route picked / demo playing, no live run) | Live session (1 bot) | Demo playback (during anything) | Multi-bot live (dashboard session) |
|---|---|---|---|---|---|
| **Top bar status** | `map · port · no attempt yet · connected` | same as idle | `map · port · run_id · connected` | unchanged by playback | same as live |
| **Demo pane** | empty + picker | playing/ended if a demo picked | unchanged (may keep playing) | playing; emits context | unchanged |
| **Mockup pane** | map + no route | map + selected route(s) | unchanged (still browsable) | unchanged | unchanged |
| **Live 3D pane** | "waiting for attempt…" idle scene | same | trail + arrow + HUD updating; reference line | same | one trail/marker/label per bot; per-bot HUD rows |
| **Live Game pane** | retrying/waiting (calm) | same | connected, in-game picture | same | connected (engine view tracks one bot) |
| **Dock · context** | `— · — · none` or last selection | `map · route · mockup/demo` | `map · route* · live` | demo context unless live overrides | `map · route* · live` |
| **Dock · scoreboard** | overall mode (no route): totals + medians | context-route numbers | context-route numbers; refetch at attempt end | context-route numbers | context-route numbers |
| **Dock · live section** | "no live session" | "no live session" | speed sparkline, arc-local %, edge callout, attempt meta | unchanged | per the selected bot; reset on `new_attempt` |
| **Dock · records** | per-map best table | context-route records | context-route records; new-record highlight on refetch | context-route records | same |
| **Drawer (if open)** | session_start enabled (if lock free) | same | harness-owned: all mutating disabled + reason; dashboard-owned: full control | unchanged | full control; roster shows N bots + read-back routes |

\* live route context: until per-bot assignments are exposed end-to-end, the live route
defaults to the harness default (sng_to_rl on dm3) with a manual override dropdown in the
live section header (#102); once assignments flow (#95, #105), the selected bot's
read-back route is the context.

---

## 6. Interaction catalog

Every interaction and its outcome. (Keyboard equivalents exist for view toggles, dock
collapse, and drawer dismiss; the full keyboard map is documented in a help popover —
bindings are a design-pass deliverable, #87, #100, #107.)

### 6.1 Shell

| Action | Outcome |
|---|---|
| Toggle a view on/off (top bar) | Pane appears/disappears in its fixed slot; row reflows; persisted + URL updated (#87) |
| Toggle all views off | Centered hint (#87) |
| Collapse/expand KPI dock (button or shortcut) | Dock ↔ rail; panes reflow to use the width; persisted (#100) |
| Open control panel | Right-side vertical panel opens, non-modal (#105) |
| Open cvar console | Right-side vertical panel opens, or left-side when control is already open (#105) |
| Esc | Side panels close (#105) |
| Reload / open shared URL | `?views=` wins; else localStorage restores last layout (#87) |

### 6.2 Mockup view

| Action | Outcome |
|---|---|
| Select map | Mesh swaps; camera to that map's overview point; route list for that map (or "no censused routes yet") (#97) |
| Select route | Human polyline + labeled gap markers + teleport markers drawn; context `{map, route}` emitted → dock recomputes (#97, #100) |
| Select 2nd route | Both drawn, distinct colors (#97) |
| Deselect route | Its geometry removed; exactly the others remain (#97) |
| Orbit / zoom | Free camera; never reset by data updates |

### 6.3 3D shared controls (Mockup + Live 3D)

| Action | Outcome |
|---|---|
| Opacity slider (0.05–1.0, default ≈0.3) | Map texture opacity changes uniformly across all map materials; trails/lines/markers stay readable at every value; persisted (#92, #99). One value for both panes is acceptable v1; control placement is open (§11) |
| Wireframe toggle (default off) | Wireframe overlay on the textured mesh (#99) |
| Reference-line toggle (Live 3D) | Human reference line show/hide (#84) |

### 6.4 Live 3D

| Action | Outcome |
|---|---|
| Click bot marker / HUD row | Selects bot; camera follows it; HUD expands it (#103) |
| No selection, 2+ bots | Overview framing of all bots (#103) |
| (system) `new_attempt` | Trails cleared, per-bot state reset, edge callout re-armed (#89, #102, #103) |
| (system) bot removed | Marker freezes/greys; no error (#103) |

### 6.5 Record → Demo seek (end to end)

The signature flow. Entry points: a record in the **dock records section** (#104) or in
the **Demo view Records tab** (#98). Identical behavior:

1. User clicks a record (e.g. dm3 · sng_to_rl · `fastest_time` — shows value, run id,
   date, human reference beside it).
2. Shell `openDemo({demo_url, map, t: event_t_s, track: bot})` fires — the single shared
   entry point (#98).
3. If the Demo view is closed, it toggles **on** and appears in the leftmost pane slot;
   the row reflows (#98, #104).
4. The player loads the record's demo file and the map (engine boots in its iframe; load
   is a fresh engine start — reliable, not instant; show a loading state) (#94).
5. On ready, the player tracks the bot's POV and seeks to `max(0, t − 2)` — a **2-second
   pre-roll** before the recorded event (the jump, the record-setting moment). Seek
   granularity is ≈1 s, so landing within ±2 s of the event is in-spec (#94).
6. Playback runs; the pane emits context `{map, route}`; the dock recomputes for that
   route (unless a live attempt holds context) (#98, #100).
7. Transport controls work from there (pause, re-seek, speed). Clicking another record at
   any time switches to it cleanly (#98, #104).

Failure path: demo file missing/404 → user-visible error (toast + pane error state); the
dock and the rest of the app stay functional (#104).

### 6.6 Demo view picker & transport

| Action | Outcome |
|---|---|
| Records tab → click record | §6.5 flow (#98) |
| Archive tab → filter by map, pick demo | Plays from start (newest-first list; includes `human/` reference demos) (#98) |
| Play/pause, speed | Direct playback control (#94) |
| Seek forward | Jumps (≈1 s granularity) (#94) |
| Seek backward | Engine restarts + fast-forwards; lands within ±2 s; show progress, not a freeze (#94) |
| (system) records.json unreachable | Records tab = explicit error state; Archive tab unaffected (#98) |

### 6.7 KPI dock

| Action | Outcome |
|---|---|
| Click record row | §6.5 (#104) |
| Eye-test entry: pick `pass / close / fail` (+ optional note) → submit | Verdict written (run id auto-filled if a lab demo is playing); scoreboard Eye Test updates immediately, no reload (#106) |
| Eye-test submit with no route context | Blocked with hint "select a route" (#106) |
| Live section route override (interim) | Re-targets the live comparison (#102) |
| (system) attempt ends | Scoreboard refetches; changed records get a "new record" highlight (#101, #104) |

### 6.8 Control side panels

| Action | Outcome |
|---|---|
| Start session (map picked) | Lab server starts on the first free lab port; lock taken (`dashboard`); roster appears; Live Game attaches (#96, #105) |
| Stop session | Server stops; lock released (#96) |
| Add bot / remove bot | Roster row appears/greys; Live 3D gains/freezes its marker (#103, #105) |
| Game mode: 4on4 / 2on2 / 1on1 / FFA | Sends the exact allowlisted KTX client command for the running game (#105) |
| Deathmatch: DMM 1 / 2 / 3 / 4 | Sends the exact allowlisted KTX `dmmN` client command (#105) |
| Powerups on/off | Applies `k_pow` and `k_pow_q/p/r/s` together (#105) |
| Start game / stop game | Sends KTX `ready` / `break` through the client-command path (#105) |
| Assign route to a bot (dropdown per row) | One atomic assign; the row then shows the route **the server reports** — until read-back arrives, the row is "pending", never silently confirmed (#95, #105) |
| Cvar console: allowed cvar | Applied live; response echoed (#96, #105) |
| Cvar console: denied cvar/command (not allowlisted, or anything touching production) | Inline rejection rendered exactly where typed; nothing applied (#96, #105) |
| `@2 k_fb_… value` | Targets bot slot 2 (per-slot form) (#105) |
| ↑ / ↓ in console | Command history (#105) |
| Any mutating action while the harness owns the lab | Refused server-side AND pre-disabled in the UI with reason "experiment harness owns the lab" (#96, #105) |
| Stale lock (dead owner or >2 h) | Controls stay disabled until the user explicitly confirms a force-takeover (#96, #105) |

---

## 7. KPI definitions — the brutal scoreboard

Four numbers, each rendered **value vs target with delta**, each with an explicit
"no data yet" state (honest zeros, never blanks) (#101). All four are context-sensitive
to the route (overall fallback when no route context). Update cadence for all
records-derived numbers: fetch on load, refetch when an attempt ends, refresh immediately
after a verdict submit (#101, #106).

Current honest values (2026-06, the state the designer should design for — a dashboard
that looks good while losing):

| # | Name | Reads | Today (honest) | v1 target | End state |
|---|---|---|---|---|---|
| 1 | **The Race** | finishes/attempts · median time as ×human | **6/10 · ×3.9** (rung 1) | 16/20 · ≤×1.25 | ×1.0 |
| 2 | **Jump Count** | routes ever completed, of the 11 | **0/11** | 1/11, then climb | 11/11 |
| 3 | **Speedometer** | % of human speed on the same stretch | **~70%** (62% at the decisive edge) | ≥80% | ≥100% |
| 4 | **Eye Test** | latest human verdict | **fail — "obviously a bot"** | close — "hesitates" | pass |

The v1 targets are what the board renders against today; the end-state column is the
asymptote (#101). Targets are data, not copy — they will be raised as they're hit.

### 7.1 The Race (#101)

- **Definition**: on the context route — `finishes / attempts`, plus the **median bot
  finish time expressed as a multiple of the human's censused time** on the same route.
- **Finish** = the bot reached the route's goal, *by any path* — deliberately weaker than
  Jump Count's "completed" (§7.2). Today the bot finishes rung 1 (sng_shortcut2, human
  3.65 s) 6 times in 10, but at ×3.9 — it arrives the slow way instead of making the
  jump. The pairing **6/10 · ×3.9 next to 0/11** is correct and intentional: Race
  measures arrival and speed, Jump Count measures doing it the human way.
- **Overall mode** (no route context): total finishes/attempts + median multiple across
  routes that have data (#101).
- Source: records aggregates (`attempts`, `finishes`, `median_time_s`, `human_time_s`)
  (#93).

### 7.2 Jump Count (#101)

- **Definition**: `N / 11` — how many of the **11 censused dm3 trick routes** the bot has
  *ever* completed, even once, ever. Completed = an attempt classified as having reached
  the route's goal **on-route** (verify_route classification `REACHED_RL`-family) (#93).
- Scope is the dm3 census regardless of route context; when a route is in context, its
  own completed/not state is indicated (#101).
- The 11 routes (census difficulty ladder, easiest → hardest — "rung 1" = easiest):
  sng_shortcut2, hilljump, rl_to_ya, ring_to_mega, ra_jumps, mega_to_rl, rl_to_bridge,
  sng_shortcut, sng_to_rl, mega_to_window, sng_jumps.
- Today: **0/11**. The first 1 is the campaign's next milestone.

### 7.3 Speedometer (#101, #102)

- **Scoreboard definition**: the bot's record-run **active-mean speed** as a % of the
  human's censused active-mean speed on the same route ("same stretch" comparison —
  never bot-on-easy-route vs human-on-hard-route).
- **Sub-line — the decisive edge**: speed at the route's binding launch edge vs the
  human's, e.g. sng_to_rl: bot ~327 vs human 528.6 ≈ **62%** where ≥526 is *required* to
  make the leap at all. The edge number is the campaign's wall; give it visual weight.
- **Live variant** (live section, during attempts): arc-position-local comparison — the
  bot's current speed vs the human's speed *at the same point along the route* (§7.5).

### 7.4 Eye Test (#101, #106)

- **Definition**: the latest human verdict for the context route. Three fixed states
  (schema): `pass | close | fail`. Display wording (designer may refine labels; the
  three-state enum is fixed): fail = "obviously a bot", close = "hesitates" (it made the
  judge look twice), pass = "could be human".
- Entered in the dock (§6.7); latest verdict wins per route, history is kept (#106).
- Today: **fail** across the board. The v1 target is honest about ambition: not "pass" —
  "make the judge hesitate".

### 7.5 Live metrics (dock live section, during a session) (#102)

- **Current speed** with a short sparkline (stream ~100 Hz; display throttled ~12 Hz).
- **Arc-local human comparison**: bot speed vs the human's speed at the same arc position
  of the route polyline — % and delta. If the bot leaves the route, this clamps and flags
  **"off route"** instead of comparing against a far-away arc point.
- **Launch-edge callout**: when the bot enters the route's censused launch-edge region,
  the crossing speed **freezes on screen** vs the requirement — e.g. `edge: 497 / needs
  526` — and stays until the next attempt. (Display-only mirror; the post-run scorer
  remains the metric of record — say so in a tooltip.)
- **Attempt meta**: run id, elapsed, distance-to-goal.
- Resets on `new_attempt`; collapses to "no live session" otherwise.

---

## 8. Records model

### 8.1 What a record is (#93)

A record is the best value per **(map, route, kind)**. Four kinds:

| Kind | Meaning | Better = |
|---|---|---|
| `fastest_time` | Fastest finish of the route | lower |
| `first_completion` | The run that first completed the route (historical; set once) | n/a |
| `peak_speed` | Highest peak speed achieved on-route | higher |
| `edge_speed` | Highest speed carried across the route's launch edge | higher |

Every record carries: value + units, run id, the demo file of that run, the **event
timestamp** inside that demo (`event_t_s` — what record-click seeks to), date set, and a
**human reference value** with its source (#93).

### 8.2 Bot vs human, everywhere

The human reference is displayed *beside every record value* — the dashboard never shows
a bot number without its human anchor (#93). The human demos themselves are browsable and
playable in the Demo view's Archive under `human/` (#98). Human references are census
ground truth, not records to break — visually distinguish "the bar" from "the bot's best".

### 8.3 Lifecycle & freshness

- Records are derived from per-attempt scoring artifacts; every finished lab run can
  append an attempt and update records automatically (#93). The registry is rebuildable
  from raw artifacts — the UI treats it as read-only data.
- The dashboard fetches records + verdicts from one shared store (single fetch path for
  scoreboard and records panel, #104), on load and on attempt end (#101).
- When a refetch *changes* a record during a session → **"new record" highlight** (#104).
  (Whether this also prompts for an eye-test verdict is open — §11.)
- Aggregates per route (`attempts`, `finishes`, `median_time_s`, `human_time_s`) feed The
  Race (#93, #101).
- Eye-test verdicts live beside records (latest-wins per route, history kept) (#93, #106).
- Today's truthful inventory: bot records exist for attempt speeds/edge speeds; there are
  **zero completion records** (Jump Count 0/11) — `fastest_time` / `first_completion`
  cells will be empty on most routes. Empty cells say "no record yet"; they don't
  disappear (#101, #104).

---

## 9. Control flows

### 9.1 Golden path: spawn → assign → watch → remove (#105)

1. Open drawer. Lock badge: `free`. Pick map `dm3`. **Start session** → server starts on
   the first free lab port (28599 family); badge: `dashboard`; status line gains the
   port; Live Game begins attaching.
2. **Add bot** ×2 → roster shows two rows (name, slot); Live 3D shows two markers in
   distinct colors.
3. **Assign** bot A = `sng_to_rl`, bot B = `hilljump` (route dropdown per row, one atomic
   action each). Rows show "pending" → then the **server-reported** assignment (#95).
   Two bots now run two different routes on the same map simultaneously — two trails
   diverge to their start points in Live 3D; the dock live section follows the selected
   bot.
4. Watch: Live 3D, Live Game, dock live metrics; edge callout freezes per crossing.
5. **Remove bot** B → its marker greys. **Stop session** → server gone; Live Game back
   to calm retrying; lock released; scoreboard refetches (the runs just recorded may
   move records → highlight).

### 9.2 Cvar send, including denials (#96, #105)

- Allowed (e.g. `k_fb_moveprobe_mode 21`, `@2 k_fb_moveprobe_replay_file dm3_hilljump.cmds`,
  `timelimit`, `fraglimit`): applied live to the lab server; echo rendered in the console
  log with the server response.
- Denied — all rendered as inline rejections at the prompt, nothing applied:
  - cvar/command not on the allowlist (allowlist: the lab `k_fb_*` family + an explicit
    small safe set);
  - dangerous commands (rcon/exec/alias/quit/path-like) — flat deny;
  - **anything addressing the production servers (ports 28501–28503 / their screens) —
    hard-denied server-side; the UI must never offer them** (#96).
- Bridge down: console input disabled with reason.
- No session running: everything disabled except session start.
- Every accepted mutating command is audit-logged server-side (#96) — surfacing the audit
  trail in the UI is not required in v1.

### 9.3 Lock-denied UX (#96, #105)

- The experiment harness has **absolute priority**. While a fresh harness lock exists:
  every mutating control is disabled with the reason ("experiment harness owns the lab"),
  *and* the server refuses anyway (UI disabling is courtesy; the bridge is the law).
  Telemetry and all watching surfaces stay fully live — locked means read-only, not
  blind.
- Stale lock (owner process dead or lock older than 2 h): the UI offers **force
  takeover** behind an explicit confirm; never automatic.
- A dashboard-owned session never blocks the harness: the harness picks a different free
  port (the user may see both — context follows the live attempt rules).

### 9.4 Verdict entry (#106)

Pick `pass/close/fail` (+ note) for the context route → written immediately (run id
auto-filled from the playing demo when applicable) → Eye Test updates in place. Verdicts
are **exempt from the harness lock** (they touch no lab server — judging must never be
blocked by a running experiment). Bridge down → visible failure, the entry is not lost
silently, retry works. No route context → blocked with a hint.

---

## 10. Visual & content notes for the designer

### What exists today (the skeleton you are restyling)

- Dark scene: near-black blue-tinted background; map as translucent dark-blue fill
  (opacity ≈0.28) + lighter blue wireframe; **bot marker orange, trail amber, velocity
  arrow green, human reference line cyan**; HUD as a bottom monospace overlay (#84).
- Top status line text-only: `dm3 · port 28599 · <run_id> · connected`.
- Default-styled controls everywhere — Phases 0–6 are deliberately skeleton-quality;
  **#107 owns the final visual call** (dark lab aesthetic is the natural direction, not
  a mandate).

### Sacred (functional contracts — restyle freely, do not break)

- **Fixed view order** Demo → Mockup → Live 3D → Live Game (#87); dock is a column, not
  an overlay (#100).
- **Textures default quite transparent (≈0.3) with a user opacity slider (0.05–1.0)**;
  trails, route lines, markers and HUD must stay legible at *every* slider value — at
  0.05 and at 1.0 (#92, #99). Sky/tool textures stay hidden (#92).
- **Texture scale is ground truth** (matches the real game; verified against ezQuake) —
  never stretch/restyle map textures (#92).
- Per-bot **distinct stable colors** consistent across Live 3D trails, HUD rows, roster
  rows (#103, #105).
- Gap markers carry **required-vs-human speed labels**; the launch-edge callout shows
  crossing-vs-required (#97, #102). These numbers are the product.
- **Honest states**: explicit empty/zero/error states everywhere; stale data badged as
  stale; "no censused routes yet"; "no record yet"; "no live session" (#97, #101, #104).
- **Server truth in the drawer**: assignments display read-back state, with a visible
  pending phase (#95, #105). Lock reasons are shown, not implied (#96).
- Record click → Demo view seek with 2 s pre-roll (#94, #98, #104). Rail mode shows the
  four scoreboard numbers (#100, #101).
- The two engine panes (Demo, Live Game) are **iframes owning a raw game render**: all
  dashboard chrome (headers, chips, transport, pickers) lives *around* the engine
  canvas, never inside it. Engine boot/reload takes seconds — design the loading states.

### Free (explicitly yours)

All colors/typography/spacing/tokens, marker and label shapes, sparkline style, transition
and slide animations, control placement within panes, the rail's micro-layout, chart
treatments, the help popover, empty-state illustrations, and the keyboard map (#107).

---

## 11. Open design decisions

1. **Eye-test prompting model (#106, flagged `opinion: requested`).** The entry mechanics
   are committed (three-state form in the dock → stored verdict, latest-wins). Open: does
   the dashboard *prompt* for a verdict, and when?
   - **(a) Passive** — the form is simply always available (current ticket scope).
     ➕ zero interruption; ➖ verdicts go stale, the Eye Test rots into old news.
   - **(b) Prompt after a watched record demo ends** — the judge just watched; memory is
     fresh; run id auto-fills.
     ➕ catches judgment at the perfect moment; ➖ nags when re-watching demos casually.
   - **(c) Prompt on new record** — piggybacks the new-record highlight (#104).
     ➕ ties verdicts to progress events; ➖ fires when the user *hasn't watched* the run
     yet — risks verdicts on unseen evidence, the one failure mode the Eye Test exists
     to prevent.
   The data path is identical in all three; the prompt surface/timing is the designer's
   recommendation to make (a hybrid — passive + a gentle (b) — is in play).
2. **Opacity-slider placement (#99)**: per-3D-pane header vs one shared top-bar control
   (one shared value for both panes is acceptable in v1).
3. **Small-window behavior (#107)**: at ~1280×800, deliberate stacking vs scrolling.
4. **Keyboard map (#87, #100, #107)**: which keys for view toggles, dock, drawer, demo
   transport; documented in the help popover.
5. **Overall visual direction (#107)**: dark-lab default assumed throughout this spec,
   but the design pass owns the final call.

---

## 12. Non-goals (v1)

- **Not a product.** One user, LAN-only. No public exposure, no tunnel routes, no auth
  UX beyond the LAN-trust assumption, no onboarding, no mobile, no spectator/esports
  mode (#96; plan).
- **Never a production-server surface.** The three production QW servers are hard-denied
  at the bridge; the UI never lists, targets, or even mentions them as options (#96).
- No route authoring in the Mockup view (routes come from the census pipeline).
- No lightmaps in the texture pipeline; no liquid/turb animation (#92).
- No "ghost" trajectory replay inside the 3D views (the Demo view is the replay surface).
- No records UI for non-dm3 maps until routes are censused there (the schema is ready;
  the UI shows the honest empty state) (#93, #97).
- No demo scrubbing precision beyond the engine's ≈1 s seek granularity (#94).

---

## 13. Glossary (for the designer)

| Term | Meaning |
|---|---|
| **QW / QuakeWorld** | The 1996-lineage multiplayer Quake variant this lab targets; competitive movement is its art form. |
| **qu, qu/s** | Quake units (≈ inches of game space) and the speed unit. Running speed ≈ 320 qu/s; good bunnyhoppers cruise 400–600+. All speeds in this spec are qu/s. |
| **Bunnyhop** | Chaining jumps with mid-air strafe steering to exceed run speed. The core skill the bot is learning. |
| **Demo** | A recorded game file, replayable in-engine. **MVD** = server-side recording (every lab run produces one); **QWD** = a player's point-of-view recording (the human reference demos). |
| **QTV** | QuakeTV — the live spectate stream of a running server. The Live In-Game view watches it. |
| **FTE** | The Quake engine compiled to WebAssembly that renders the Demo and Live In-Game panes in-browser. One engine instance per window — hence iframes. |
| **mvdsv / KTX** | The QW server and its mod that the lab runs; the bot lives inside KTX. |
| **cvar** | A named server/game variable (`name value`). The lab's bot knobs are cvars prefixed `k_fb_*`; the console in the drawer sets them live. |
| **Route** | One censused human trick line on a map: a start, a goal, and the human's recorded trajectory between them. dm3 has 11. |
| **Rung** | A route's position on the census difficulty ladder (rung 1 = easiest = sng_shortcut2). "The next rung" = the campaign's current target route. |
| **Census** | The measured ground truth of all 11 dm3 routes: durations, speeds, gap geometry, required speeds — extracted from human demos. The source of every "human" number on the dashboard. |
| **Reference line / .cmds** | The human trajectory polyline drawn in the 3D views, derived from the human demo. |
| **Gap / launch edge / landing** | A jump in a route: the edge you leave, the platform you must reach. **Hard gap**: undershooting drops you into a pit (attempt over). |
| **Required speed** | The minimum speed at the launch edge for the jump to be physically possible (e.g. sng_to_rl's decisive gap: 526; the human crossed at 528). |
| **Attempt / run id** | One bot try at a route, identified by a timestamp id (e.g. `20260605T201217Z`); each produces telemetry, scoring, and an archived demo. |
| **Finish vs completion** | Finish = reached the route's goal by any path (The Race). Completion = reached it on-route, doing the trick (Jump Count; scorer class `REACHED_RL`). |
| **Marker (goal marker)** | The KTX nav-graph node used as a route's goal; "reaching the marker" ends an attempt successfully. |
| **Telemetry sidecar** | The lab service streaming ~100 Hz bot state (position, velocity, speed, onground…) to the dashboard, plus attempt start/end events. |
| **Harness** | The scripted experiment pipeline that owns the lab during automated runs; the dashboard always yields to it (the lock). |
| **Lab lock** | Who owns the lab server right now: `harness`, `dashboard`, or free. Drives every disabled state in the control panels. |
| **ed / slot** | A bot's server-side identity (entity/client slot number); keys per-bot colors, HUD rows, and per-slot cvars (`…_s2` targets slot 2). |
| **Eye test** | The human verdict: does this run look human? `pass / close / fail` — the only KPI measured by a person. |
