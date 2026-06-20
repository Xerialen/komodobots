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
- `evidence/dm3_resource_routes.png` — the route map (resources as nodes, routes as traffic-weighted edges).
- `evidence/dm3_spawn_flowchart.webp`, `evidence/dm3_spawn_tactics.md` — the tactical (layer-3) source.

## Regenerate

```sh
QW=qw-analyze-v20         # mvd_analyzer CLI
$QW <demo.mvd> > /tmp/a.json
python experiments/route_observatory/route_extract.py /tmp/a.json /tmp/routes.json
python experiments/route_observatory/build_canonical.py /tmp/routes.json [/tmp/routes2.json ...]
```

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
