# dm3 Route Observatory

Tooling that turns parsed MVD demos into a **canonical route set** for dm3, so route-conditioned
training and believability validation rest on what humans actually do — not on a handful of scripted
examples.

## The route definition (owner-set)

> **A route is the path between two resources.**

Resources are the map's pickups/control points. qwds only exist for a handful of named routes; the
**parsed demo data contains every resource→resource path that occurs in play**. So the observed-traffic
route set extracted here is **co-canonical with the qwd named routes** and covers far more.

## Three layers

| Layer | Source (ground truth) | What it gives |
|---|---|---|
| **Resources** | demo item entities (`mapEntities`) | the nodes — 1 RA, 1 YA (`YA.box`), SNG, RL, GL (`water.GL`), LG (`water.LG`), Quad, Pent, Ring, 3 megahealths (`SNG.MH`, `hill`, `Pent`) |
| **Routes** | per-player loc streams (`streams.players[].pos.li`) | the paths between resources + traffic weight (`resource_routes.dm3.json`) |
| **Tactics** | spawn flowcharts + notes (`evidence/`) | *which* route from *which* spawn, *when* (mate/enemy/item-timing) |

> **Eval-integrity note:** resources are anchored to the demo's item entities, never to prose. dm3 has
> **one YA** (at `YA.box`; the loc literally named `YA` holds the SSG). The flowchart's "2nd/3rd YA"
> means the single YA's **respawns** (20s timing), not extra locations.

## Files

- `../../data/catalog/resource_routes.dm3.json` — the canonical artifact (`komodobots.resource_routes.v1`):
  `resources` + directed `routes` (`from`,`to`,`count`,`byPlayer`), with provenance.
- `route_extract.py` — `<qw-analyze full JSON> <out.json>`: collapses each player's `li` loc-stream to
  resource visits and emits the ranked resource→resource route table for one demo.
- `build_canonical.py` — `<routes1.json> [routes2.json ...]`: merges per-demo tables, writes the catalog
  artifact, and prints the `loc_catalog` + qwd reconciliation.
- `pov_fuse_extract.py` — `<analysis.json> <player> <t0_s> <t1_s> <frames_dir> <out.json>`: slices one
  route leg and computes its **movement signature** (`komodobots.route_leg.v1`). See below.
- `pov_fuse_render.py` — `<leg.json> <frames_dir> <out.html>`: the fused POV+route contact sheet.
- `pov_fuse_shot.js` — `<html> <out.png> [--rows <dir>]`: headless screenshot for self-validation.
- `evidence/dm3_resource_routes.png` — the route map (resources as nodes, routes as traffic-weighted edges).
- `evidence/dm3_spawn_flowchart.webp`, `evidence/dm3_spawn_tactics.md` — the tactical (layer-3) source.
- `evidence/pov_fuse_megaRL.png` — worked example: Milton's mega→RL leg, POV fused with the route plot.

## Regenerate the route canon

```sh
QW=qw-analyze-v20         # mvd_analyzer CLI
$QW <demo.mvd> > /tmp/a.json
python experiments/route_observatory/route_extract.py /tmp/a.json /tmp/routes.json
python experiments/route_observatory/build_canonical.py /tmp/routes.json [/tmp/routes2.json ...]
```

## Movement signatures (the `route-signature` skill)

The canon above says **where** humans go. The `pov_fuse_*` tools add **how** they move along a leg —
the per-route **movement signature** (speed profile, jump cadence, look-vs-move, straightness) that is
both the route-conditioned **BC target** and the **believability rubric**. The fused contact sheet
(`[POV frame] [top-down route plot with view + velocity arrows] [HUD]`) is validated by reading the
render back and checking the plotted state against the POV pixels (eval-integrity — the fused state
must match what is on screen).

```sh
FR=<frames_dir>          # 1fps POV JPGs (tNNNNNN.jpg); match_ms = (video_t − offset)*1000
python experiments/route_observatory/pov_fuse_extract.py /tmp/a.json Milton 266 273.5 "$FR" /tmp/leg.json
python experiments/route_observatory/pov_fuse_render.py  /tmp/leg.json "$FR" /tmp/sheet.html
node   experiments/route_observatory/pov_fuse_shot.js    /tmp/sheet.html /tmp/sheet.png --rows /tmp/rows
```

Full procedure, data-shape conventions (`pos` is struct-of-arrays; `pos.li` flickers — use x/y +
teamsay), leg-selection by straightness, and the mandatory self-validation gate are in the skill:
`.claude/skills/route-signature/SKILL.md`.

## Reconciliation with the qwd canon (v1 / book-vs-mix)

The qwd resource-routes are all **present** in the demo route set: `sng_to_rl` SNG↔RL **64×**,
`mega_to_rl` SNG.MH↔RL **150×**, `ring_to_mega` Ring↔SNG.MH **21×**, `rl_to_ya` RL↔YA **5×**. The other
7 qwds (`hilljump`, `sng_jumps`, `ra_jumps`, `rl_to_bridge`, `mega_to_window`, `sng_shortcut(2)`) are
**movement tricks** (shortcuts/enablers) — not resource pairs — matching the route-program taxonomy.

## Caveats

- **v1 = one human demo** (book-vs-mix, hub 129232, 8 players). Traffic weights firm up by aggregating
  more human demos through `build_canonical.py` (bot demos excluded — they aren't human movement).
- MVD positions are **1/8-qu** (protocol-bound). This canon defines route *topology + traffic*; precise
  trajectory geometry is the qwd side's job (the two are complementary).
