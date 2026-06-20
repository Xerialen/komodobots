#!/usr/bin/env python3
"""Build the canonical dm3 resource->route set from one or more per-demo route tables.

A route = the path a human takes between two consecutive RESOURCE visits, extracted from
parsed MVD demos (see route_extract.py). This is the OBSERVED-TRAFFIC route canon, co-equal
with the qwd named routes; it covers every resource pair that actually occurs in play
(the qwds only cover a handful). Resources are anchored to the demo's item entities
(ground truth: dm3 has ONE YA, at loc YA.box).

Usage: build_canonical.py <routes1.json> [routes2.json ...]
  Each routesN.json is the output of route_extract.py for one demo.
  -> writes data/catalog/resource_routes.dm3.json (merged + schema'd) and prints the
     loc_catalog + qwd reconciliation.
"""
import json, os, sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
CATALOG = os.path.join(REPO, "data", "catalog")

inputs = sys.argv[1:]
if not inputs:
    sys.exit("usage: build_canonical.py <routes1.json> [routes2.json ...]")

resources = set()
demos = []
merged = defaultdict(lambda: {"count": 0, "byPlayer": defaultdict(int)})
for path in inputs:
    d = json.load(open(path))
    resources.update(d["resources"])
    demos.append(os.path.basename(d.get("demo") or d.get("source") or path))
    for r in d["routes"]:
        m = merged[(r["from"], r["to"])]
        m["count"] += r["count"]
        for p, c in r.get("byPlayer", {}).items():
            m["byPlayer"][p] += c

resources = sorted(resources)
loc_names = {l["name"] for l in json.load(open(os.path.join(CATALOG, "loc_catalog.dm3.json")))["locs"]}
missing = [r for r in resources if r not in loc_names]
routes = [{"from": a, "to": b, "count": m["count"], "byPlayer": dict(m["byPlayer"])}
          for (a, b), m in sorted(merged.items(), key=lambda kv: -kv[1]["count"])]
canonical = {
    "schema": "komodobots.resource_routes.v1",
    "map": "dm3",
    "_purpose": "Canonical observed-traffic route set: the path a human takes between two RESOURCES, "
                "from parsed MVD demos. Co-canonical with the qwd named routes; covers ALL resource pairs "
                "seen in play. Resources anchored to demo item entities (dm3 has ONE YA at YA.box).",
    "_source": "mvd_analyzer qw-analyze-v20 locGraph + per-player loc streams; precision 1/8 qu (MVD protocol-bound)",
    "_provenance": {"demos": demos, "date": "2026-06-20",
                    "note": "Aggregate across more human demos to firm up traffic weights."},
    "resources": resources, "route_count": len(routes), "routes": routes,
}
out = os.path.join(CATALOG, "resource_routes.dm3.json")
json.dump(canonical, open(out, "w"), indent=1)
print(f"WROTE {out}  ({len(resources)} resources, {len(routes)} routes, demos={demos})")
print("resources not in loc_catalog:", missing or "(none)")

# qwd named routes -> resource pairs (None second element = movement trick, not a resource pair)
QWD = {'sng_to_rl': ('SNG', 'RL'), 'rl_to_ya': ('RL', 'YA.box'), 'ring_to_mega': ('Ring', 'SNG.MH'),
       'mega_to_rl': ('SNG.MH', 'RL'), 'rl_to_bridge': ('RL', None), 'mega_to_window': ('SNG.MH', None),
       'hilljump': ('hill', None), 'sng_jumps': ('SNG', None), 'ra_jumps': ('RA', None),
       'sng_shortcut': ('SNG', None), 'sng_shortcut2': ('SNG', None)}
cnt = {(r["from"], r["to"]): r["count"] for r in routes}
pc = lambda a, b: cnt.get((a, b), 0) + cnt.get((b, a), 0)
print("\nqwd named routes vs canonical set:")
for name, (a, b) in QWD.items():
    if b is None:
        print(f"  {name:16} MOVEMENT TRICK at {a} (shortcut/enabler)")
    else:
        c = pc(a, b)
        print(f"  {name:16} {a}<->{b}: {'present '+str(c)+'x' if c else 'ABSENT in these demos'}")
