#!/usr/bin/env python3
"""route_legs.py — full-game route-leg extraction + per-route signature ENVELOPES.

A route = the path between two RESOURCES (items). Resource visits are detected by
POSITION (player within RHO qu of an item entity), NOT by the loc-index `li`.

WHY position, not li: `pos.li` FLICKERS at speed — a leg's li-endpoint can sit ~1000 qu
from the actual item, so li-based leg geometry is WRONG (validated: li "mega->RL" legs
START closer to RL than they end, decreased in 0/36). Position-based item-to-item legs are
geometry-faithful: goal_dist falls ~monotonically to ~0 at the destination item (validated
14/14 on RL->YA.box). This also matches the owner's definition (route = path between two
resource ITEMS) more directly than the li/region canon (PR #332), whose per-leg geometry
inherits the flicker (its traffic counts still reproduce; the per-leg geometry does not).

Reuses the committed pov_fuse_extract.compute_signature (anchor; do not reinvent).
Memory-safe: full game (8 players x ~87k ticks) = 42 MB JSON / ~280 MB RAM.

Outputs: <out_dir>/legs.jsonl  +  <out_dir>/envelopes.json
Usage: route_legs.py <analysis.json> <out_dir> [rho_qu=200]
"""
import sys, json, os, math
from collections import defaultdict

# pov_fuse_extract lives in this same directory (experiments/route_observatory).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pov_fuse_extract import (hspeed, yaw_deg, move_dir_deg, compute_signature,  # noqa: E402
                              RES_KINDS)

MAP_DIAGONAL_DM3 = 3797.1
DEFAULT_RHO = 200.0   # qu item-visit radius (dm3 resources are spaced > 2*RHO apart)
MIN_TICKS = 3


def resource_coords(d):
    """{resource_name: (x,y)} from the demo's item entities (the TRUE item locations)."""
    coords = {}
    for e in d['mapEntities']['entities']:
        k = (e.get('kind') or '').lower()
        if k in RES_KINDS and e.get('loc') and e['loc'] not in coords:
            coords[e['loc']] = (e['x'], e['y'])
    return coords


def player_ticks(P):
    """Whole player's stream -> pov_fuse tick dicts (the compute_signature input shape)."""
    pos = P['pos']
    out = []
    for i in range(len(pos['t'])):
        mdir = move_dir_deg(pos['vx'][i], pos['vy'][i])
        out.append({"t": pos['t'][i] / 1000.0,
                    "x": pos['x'][i], "y": pos['y'][i], "z": pos['z'][i],
                    "hs": hspeed(pos['vx'][i], pos['vy'][i]),
                    "yaw": yaw_deg(pos['vya'][i]),
                    "mdir": mdir, "vz": pos['vz'][i]})
    return out


def resource_visits(ticks, coords, rho=DEFAULT_RHO):
    """Ordered item visits [(tick_index, t_s, resname)] by POSITION (flicker-immune):
    each time the player enters the rho-radius of an item different from the last one."""
    seq, last = [], None
    for i, tk in enumerate(ticks):
        here, best = None, rho
        for nm, (gx, gy) in coords.items():
            dd = math.hypot(tk['x'] - gx, tk['y'] - gy)
            if dd < best:
                best, here = dd, nm
        if here is not None and here != last:
            seq.append((i, tk['t'], here))
            last = here
    return seq


def pctl(xs, q):
    xs = sorted(xs)
    if not xs:
        return None
    k = (len(xs) - 1) * q
    f, c = math.floor(k), math.ceil(k)
    if f == c:
        return round(xs[int(k)], 3)
    return round(xs[f] * (c - k) + xs[c] * (k - f), 3)


def band(xs):
    xs = [x for x in xs if x is not None]
    if not xs:
        return None
    return {"n": len(xs), "p10": pctl(xs, .10), "median": pctl(xs, .50),
            "p90": pctl(xs, .90), "mean": round(sum(xs) / len(xs), 3),
            "min": round(min(xs), 3), "max": round(max(xs), 3)}


def route_env(ls):
    intervals = [L["jump_interval_mean_s"] for L in ls if L["jump_interval_mean_s"] is not None]
    return {
        "dur_s": band([L["dur_s"] for L in ls]),
        "hs_mean": band([L["hs_mean"] for L in ls]),
        "hs_max": band([L["hs_max"] for L in ls]),
        "jumps_per_leg": band([L["jumps"] for L in ls]),
        "jump_interval_s": band(intervals),
        "lookmove_deg": band([L["lookmove_mean_deg"] for L in ls]),
        "straightness": band([L["straightness"] for L in ls]),
    }


def main(analysis, out_dir, rho=DEFAULT_RHO):
    os.makedirs(out_dir, exist_ok=True)
    d = json.load(open(analysis))
    coords = resource_coords(d)
    players = d['streams']['players']

    legs = []
    dt_samples = []
    for P in players:
        ticks = player_ticks(P)
        if len(ticks) > 10:
            dt_samples.append(ticks[10]['t'] - ticks[9]['t'])
        visits = resource_visits(ticks, coords, rho)
        for (i0, t0, a), (i1, t1, b) in zip(visits, visits[1:]):
            if a == b:
                continue
            seg = ticks[i0:i1 + 1]
            if len(seg) < MIN_TICKS:
                continue
            sig = compute_signature(seg)
            gx, gy = coords[b]
            end_dist = round(math.hypot(seg[-1]['x'] - gx, seg[-1]['y'] - gy), 1)
            legs.append({"player": P['name'], "from": a, "to": b,
                         "t0": round(t0, 2), "t1": round(t1, 2),
                         "end_dist_qu": end_dist, **sig})

    with open(os.path.join(out_dir, "legs.jsonl"), "w") as f:
        for L in legs:
            f.write(json.dumps(L) + "\n")

    byroute = defaultdict(list)
    for L in legs:
        byroute[(L["from"], L["to"])].append(L)

    envelopes = []
    for (a, b), ls in sorted(byroute.items(), key=lambda kv: -len(kv[1])):
        durs = sorted(L["dur_s"] for L in ls)
        med = durs[len(durs) // 2]
        # CORE = faster-half traversals = the route actually being RUN (vs a slow/indirect
        # instance). The route-conditioned BC TARGET; full traffic = outer believability band.
        core = [L for L in ls if L["dur_s"] <= med] or ls
        e = {"from": a, "to": b, "count": len(ls), "core_count": len(core),
             "core_def": "legs with dur_s <= per-route median (faster half = route-running)",
             "end_dist_qu_median": pctl([L["end_dist_qu"] for L in ls], .50),
             "players": sorted({L["player"] for L in ls})}
        e.update(route_env(core))
        e["all_traffic"] = route_env(ls)
        envelopes.append(e)

    out = {
        "schema": "komodobots.route_envelopes.v2",
        "demo": d.get("filePath"), "source": analysis,
        "method": f"position-based item visits, rho={rho}qu (flicker-immune; supersedes li)",
        "resources": sorted(coords), "resource_xy": {k: [round(x), round(y)] for k, (x, y) in coords.items()},
        "n_legs_total": len(legs), "distinct_routes": len(envelopes),
        "tick_dt_s": round(sum(dt_samples) / len(dt_samples), 4) if dt_samples else None,
        "jump_method": "v1 vz-proxy (no onground in MVD); replace w/ geometric onground #316",
        "envelopes": envelopes,
    }
    json.dump(out, open(os.path.join(out_dir, "envelopes.json"), "w"), indent=1)

    print(f"players: {[P['name'] for P in players]}")
    print(f"resources ({len(coords)}): {sorted(coords)}")
    print(f"tick dt ~ {out['tick_dt_s']}s  | rho={rho}qu")
    print(f"legs: {len(legs)}  | distinct routes: {len(envelopes)}")
    # geometry validation: median end_dist should be SMALL (player really reached the item)
    eds = sorted(L["end_dist_qu"] for L in legs)
    print(f"end_dist_qu: median={eds[len(eds)//2]:.0f}  p90={eds[int(len(eds)*.9)]:.0f}  "
          f"(small => legs really terminate at the destination item)\n")
    print("TOP 24 routes  count  core  dur(med)  hs_mean(med)  jumpInt(med)  straight(med)")
    for e in envelopes[:24]:
        ji = e["jump_interval_s"]["median"] if e["jump_interval_s"] else None
        print(f"  {e['count']:3}x  {e['core_count']:3}  {e['from']:8}->{e['to']:8}  "
              f"{e['dur_s']['median']:5.1f}s  {e['hs_mean']['median']:4.0f}   "
              f"{str(ji):>6}     {e['straightness']['median']:.3f}")


if __name__ == '__main__':
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    rho = float(sys.argv[3]) if len(sys.argv) > 3 else DEFAULT_RHO
    main(sys.argv[1], sys.argv[2], rho)
