#!/usr/bin/env python3
"""route_condition.py — per-tick ROUTE-CONDITIONING goal vector.

THE navigation signal open-loop BC lacked (the diagnosed divergence root cause). Goal-
conditioned imitation: each tick is labelled with an egocentric vector toward the NEXT
resource (item) on the current route. In training the goal is the leg's OBSERVED next item
(hindsight goal labelling, GCSL-style); at inference the tactical/spawn layer supplies it,
so the policy learns "given my state AND where I'm headed, what action" instead of
memorising one trajectory per route — which is what made open-loop BC compound error.

Proposed as feature_registry registry_version 4 — a SELF append, mirroring how v3 appended
the two turn-direction features (existing-feature normalization unchanged):

  goal_heading_sincos  float32[2]  [sin,cos] atan2(goal_y-oy, goal_x-ox)   map-frame,
                                   same convention as vel_heading_sincos / yaw_sincos
  goal_dist_norm       float32     min(dist(origin,goal)/map_diagonal_dm3, 1)   same
                                   normalization family as nearest_marker_dist_norm
  (provenance-only, NOT trained: from_res, to_res, leg_progress)

Both trained features are leakage_safe: they depend only on pos[t] and the goal coords (an
INPUT), never on future STATE. SELF_DIM 18 -> 21 at v4. The goal is the destination ITEM
ENTITY (position-segmented legs, flicker-immune — see route_legs.py).

Reference implementation + a full-demo emission with a built-in validation (goal_dist must
fall start->end per route). Full catalog-wide emission is build_features.py's job once the
feature lands in the registry (no-merge guardrail: this stages the proposal + proves it).

Usage: route_condition.py <analysis.json> <out_dir>
"""
import sys, json, os, math
import statistics as S
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from route_legs import (player_ticks, resource_visits, resource_coords,  # noqa: E402
                        MAP_DIAGONAL_DM3)


def goal_vector(ox, oy, gx, gy):
    """The v4 route-conditioning trained features for one tick toward goal (gx, gy)."""
    h = math.atan2(gy - oy, gx - ox)
    dist = math.hypot(gx - ox, gy - oy)
    return {"goal_heading_sin": round(math.sin(h), 4),
            "goal_heading_cos": round(math.cos(h), 4),
            "goal_dist_norm": round(min(dist / MAP_DIAGONAL_DM3, 1.0), 4)}


def main(analysis, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    d = json.load(open(analysis))
    coords = resource_coords(d)

    rows = []
    perroute = defaultdict(lambda: [[], []])   # (a,b) -> [start_dists, end_dists]
    for P in d['streams']['players']:
        ticks = player_ticks(P)
        visits = resource_visits(ticks, coords)
        for (i0, t0, a), (i1, t1, b) in zip(visits, visits[1:]):
            if a == b or b not in coords:
                continue
            gx, gy = coords[b]
            span = max(1, i1 - i0)
            perroute[(a, b)][0].append(math.hypot(ticks[i0]['x'] - gx, ticks[i0]['y'] - gy) / MAP_DIAGONAL_DM3)
            perroute[(a, b)][1].append(math.hypot(ticks[i1]['x'] - gx, ticks[i1]['y'] - gy) / MAP_DIAGONAL_DM3)
            for i in range(i0, i1 + 1):
                tk = ticks[i]
                rows.append({"player": P['name'], "t_ms": round(tk['t'] * 1000),
                             "from": a, "to": b, "leg_progress": round((i - i0) / span, 3),
                             "hs": round(tk['hs']), **goal_vector(tk['x'], tk['y'], gx, gy)})

    out = os.path.join(out_dir, "route_conditioning_sample.jsonl")
    with open(out, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")

    nlegs = sum(len(v[0]) for v in perroute.values())
    good = sum(1 for d0s, d1s in perroute.values() if S.median(d1s) < S.median(d0s))
    print(f"emitted {len(rows)} per-tick conditioning rows over {nlegs} legs / "
          f"{len(perroute)} routes -> {out}")
    # VALIDATION (eval-integrity): the conditioning must POINT AT the goal -> per route the
    # median goal_dist must fall from leg start to leg end. ~all routes should pass.
    print(f"VALIDATION: goal_dist median falls start->end in {good}/{len(perroute)} routes "
          f"(should be ~all; a goal-conditioning signal that did not approach would be wrong)")
    print("\ntop routes   n    goal_dist median start -> end")
    for (a, b), (d0s, d1s) in sorted(perroute.items(), key=lambda kv: -len(kv[1][0]))[:12]:
        flag = "" if S.median(d1s) < S.median(d0s) else "  <-- NOT decreasing"
        print(f"  {a:8}->{b:8} {len(d0s):3}  {S.median(d0s):.3f} -> {S.median(d1s):.3f}{flag}")


if __name__ == '__main__':
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    main(sys.argv[1], sys.argv[2])
