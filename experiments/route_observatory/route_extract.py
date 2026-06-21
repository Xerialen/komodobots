#!/usr/bin/env python3
import logging
# Extract canonical resource->resource routes from a parsed demo (qw-analyze full JSON).
# A route = the path a player takes between two consecutive RESOURCE visits.
# Usage: route_extract.py <analysis.json> [out.json]
import sys, json
from collections import defaultdict


LOGGER = logging.getLogger(__name__)
src = sys.argv[1]
d = json.load(open(src))
locnames = [l['name'] for l in d['locGraph']['locs']]

# Resources = locs holding a major item (armor / weapon / powerup / megahealth).
RES_KINDS = {'ra', 'ya', 'rl', 'sng', 'gl', 'lg', 'quad', 'pent', 'ring', 'mh'}
resources = sorted({e['loc'] for e in d['mapEntities']['entities']
                    if (e.get('kind') or '').lower() in RES_KINDS and e.get('loc')})

routes = defaultdict(lambda: {'count': 0, 'byPlayer': defaultdict(int), 'durations': []})
per_player_visits = {}
for p in d['streams']['players']:
    name = p['name']; li = p['pos']['li']; t = p['pos']['t']
    # collapse consecutive same-loc, keep resource locs only, drop self-loops
    seq = []
    prev = None
    for i, idx in enumerate(li):
        nm = locnames[idx] if 0 <= idx < len(locnames) else None
        if nm != prev:
            prev = nm
            if nm in resources:
                if not seq or seq[-1][1] != nm:
                    seq.append((t[i] / 1000.0, nm))
    per_player_visits[name] = len(seq)
    for (ta, a), (tb, b) in zip(seq, seq[1:]):
        if a == b:
            continue
        key = (a, b)
        routes[key]['count'] += 1
        routes[key]['byPlayer'][name] += 1
        routes[key]['durations'].append(round(tb - ta, 2))

ranked = sorted(routes.items(), key=lambda kv: -kv[1]['count'])
print(f"resources ({len(resources)}):", resources)
print(f"players: {list(per_player_visits.keys())}")
print(f"distinct resource->resource routes: {len(ranked)}  | total traversals: {sum(r['count'] for _,r in ranked)}")
print("\nTOP 30 routes (count = times any player ran A->B):")
for (a, b), r in ranked[:30]:
    durs = sorted(r['durations']); med = durs[len(durs)//2]
    print(f"  {r['count']:3}x  {a:9} -> {b:9}  median {med:4.1f}s  players={len(r['byPlayer'])}")

if len(sys.argv) > 2:
    out = {"schema": "komodobots.resource_routes_demo.v1", "demo": d.get("filePath"), "source": src, "resources": resources,
           "routes": [{"from": a, "to": b, "count": r['count'],
                       "byPlayer": dict(r['byPlayer']),
                       "median_s": sorted(r['durations'])[len(r['durations'])//2]} for (a, b), r in ranked]}
    json.dump(out, open(sys.argv[2], 'w'), indent=1)
    print("wrote", sys.argv[2])
