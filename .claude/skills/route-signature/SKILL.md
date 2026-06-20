---
name: route-signature
description: Use when mapping a dm3 route from real play or extracting/validating a player's MOVEMENT SIGNATURE along a route leg from a parsed MVD demo (+ POV frames) — i.e. producing the route-conditioned BC target or the believability rubric, or fusing a POV recording against demo state. Turns the resource→route canon into per-route human signatures (speed profile, jump cadence, look-vs-move) and a self-validatable POV+route fused view. Pairs with eval-integrity (the fused state must match the pixels) and the route_observatory route canon.
---

# route-signature — extract & validate a route's human movement signature

The route canon (`experiments/route_observatory/`, `resource_routes.dm3.json`) says **where** humans
go. This skill produces **how** they move along a leg — the speed profile, jump cadence, and
look-vs-move signature that is simultaneously the **route-conditioned BC target** and the
**believability rubric**. It does that with a fused view you validate by eye, then by reading the
render back yourself.

## Where this sits in the workflow

```
resource→route canon (route_observatory)      WHERE humans go      [done: PR #332]
        ↓  route-signature  (this skill)
per-route human movement signature             HOW humans move      ← BC target + rubric
        ↓
route-conditioned BC training (Phase 2, GPU/pinnacle)               ← check in before this
        ↓
bot trajectory overlaid on the human envelope  →  per-route believability score
```

Use it when you need to: map a new route from play, define/refresh a route's BC target, build a
believability rubric for a route, or fuse any POV-frame recording against parsed demo state.

## The pipeline (three tools, all in `experiments/route_observatory/`)

1. **`pov_fuse_extract.py`** `<analysis.json> <player> <t0_s> <t1_s> <frames_dir> <out.json>`
   — slices one leg's per-tick state and computes the **signature** (`komodobots.route_leg.v1`):
   speed min/mean/max, debounced jump cadence, look-vs-move, straightness, plus resource markers
   (anchored to demo item entities) and cleaned teamsay binds. `analysis.json` = `qw-analyze` full
   JSON; `--offset` is the frame↔match sync (book-vs-mix = 1695).
2. **`pov_fuse_render.py`** `<leg.json> <frames_dir> <out.html>` — a fused contact sheet: per second,
   `[POV frame] [top-down route plot: speed-coloured path + cyan view-arrow + orange velocity-arrow] [HUD]`.
3. **`pov_fuse_shot.js`** `<html> <out.png> [--rows <dir>]` — headless Chromium+SwiftShader screenshot
   (full sheet; `--rows` writes full-res per-row crops for self-validation). Needs `playwright`
   (set `NODE_PATH` if it lives outside the cwd).

```sh
QW=qw-analyze-v20
$QW <demo.mvd> > /tmp/a.json
python experiments/route_observatory/pov_fuse_extract.py /tmp/a.json Milton 266 273.5 <frames_dir> /tmp/leg.json
python experiments/route_observatory/pov_fuse_render.py  /tmp/leg.json <frames_dir> /tmp/sheet.html
node   experiments/route_observatory/pov_fuse_shot.js    /tmp/sheet.html /tmp/sheet.png --rows /tmp/rows
```

## Conventions that took a session to pin down — get these right

- `streams.players[].pos` is **struct-of-arrays**: `t,x,y,z,li,vp,vya,vx,vy,vz`.
- `pos.t` is **milliseconds**; `vya` is **quake angle units** (`×360/65536` → degrees).
- **`pos.li` (loc index) FLICKERS** as a player crosses zones at speed — it bounces between
  non-adjacent loc names tick-to-tick. **Never** key the fused view off per-tick `li`. Use the
  smooth `x/y` trajectory + the human **teamsay** binds (ground-truth intent) for labels.
- Frame↔match sync: `match_ms = (video_t − offset) × 1000`. Verify once per demo against an
  on-screen clock (book-vs-mix: frame `t001695` = match_t 0).
- A *sustained-speed* run is not necessarily a clean *route* — pick legs by **straightness**
  (net/path) + resource endpoints, not raw speed (raw speed catches mid-arena jukes too).

## Mandatory self-validation gate (eval-integrity)

A fused panel is a claim about what the player did. Before reporting it, **render it and READ the
PNG back yourself**, and confirm the plotted state matches the pixels — apply the `eval-integrity`
skill:
- POV scene type matches the teamsay location (e.g. blue water in frame ↔ "coming [bridge]").
- `look-vs-move` near 0° ↔ a visibly smooth forward bhop; a spike ↔ a visible flick/turn.
- the trajectory endpoint dot sits on the resource it should (e.g. on the RL marker when the HUD
  shows the pickup + `[RL]`).
- speed colouring matches visible motion.
If you cannot see the underlying behaviour in the render, you cannot conclude about it — that is
exactly check #3 of eval-integrity. The litmus test: the owner should never have to say "show me."

## Caveats to carry into any report (don't overstate)

- **Jump cadence is a v1 PROXY** (vz rising-edge, debounced) — MVD has no onground flag. Replace
  with geometric onground (#316) once it is baked into the catalog. State this whenever you quote a
  cadence number.
- MVD positions are **1/8 qu** (protocol-bound): the signature is topology + dynamics, not
  sub-qu geometry.
- A signature from **one demo is one instance**. The variation (the point) needs many human
  instances per route — aggregate before treating a signature as "the" target.
- Resources are anchored to demo item entities, **never prose** (dm3 has **one** YA at `YA.box`).

See `experiments/route_observatory/README.md` for the route definition + 3-layer model, and
`evidence/pov_fuse_megaRL.png` for the worked example (Milton's mega→RL leg).
