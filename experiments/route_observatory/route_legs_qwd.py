#!/usr/bin/env python3
"""route_legs_qwd.py — route legs + signature envelopes from a .qwd-derived catalog.

Same POSITION-based segmentation + signature as route_legs.py, but the source is the elite
SmackDown3 POV corpus loaded by scripts/catalog_etl_qwd.py into a catalog SQLite
(player_ticks = pos/vel/angles/hspeed; one continuity-split episode per run). Segmenting per
EPISODE prevents legs straddling a teleport/respawn. dm3 resource coords are map-static, so
they are reused from the MVD-derived envelopes (resource_xy).

This widens every route's envelope from one 4on4 game to many elite 1v1 games — movement
along a route is the same map+physics regardless of team size (the 1v1/4on4 caveat is about
tactics, not movement).

Usage: route_legs_qwd.py <catalog.sqlite> <mvd_envelopes.json> <out_dir> [rho=200]
"""
import sys, json, os, math, sqlite3
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from route_legs import (resource_visits, route_env, pctl, band,  # noqa: E402
                        compute_signature, move_dir_deg, hspeed, DEFAULT_RHO)


def load_coords(mvd_env_json):
    """dm3 resource item coords {name:(x,y)} — reused from the MVD envelopes (map-static)."""
    e = json.load(open(mvd_env_json))
    return {k: (float(x), float(y)) for k, (x, y) in e["resource_xy"].items()}


def episode_ticks(con, episode_id):
    """Ordered pov_fuse tick dicts for one episode from catalog.player_ticks."""
    cur = con.execute(
        "SELECT t_s, ox, oy, oz, vx, vy, vz, yaw, hspeed FROM player_ticks "
        "WHERE episode_id=? ORDER BY tick", (episode_id,))
    out = []
    for t_s, ox, oy, oz, vx, vy, vz, yaw, hs in cur:
        vx = vx or 0.0; vy = vy or 0.0; vz = vz or 0.0
        out.append({"t": t_s, "x": ox, "y": oy, "z": oz,
                    "hs": hs if hs is not None else hspeed(vx, vy),
                    "yaw": yaw if yaw is not None else 0.0,
                    "mdir": move_dir_deg(vx, vy), "vz": vz})
    return out


def main(db, mvd_env_json, out_dir, rho=DEFAULT_RHO):
    os.makedirs(out_dir, exist_ok=True)
    coords = load_coords(mvd_env_json)
    con = sqlite3.connect(db)

    # episode -> (demo, player) for provenance
    epmeta = {}
    try:
        for eid, dlabel, plabel in con.execute(
                "SELECT e.episode_id, d.path, p.handle FROM episodes e "
                "LEFT JOIN demos d ON e.demo_id=d.demo_id "
                "LEFT JOIN players p ON e.player_id=p.player_id"):
            epmeta[eid] = (os.path.basename(dlabel or "?"), plabel or "?")
    except sqlite3.OperationalError:
        pass  # schema variant; fall back to episode_id only

    episode_ids = [r[0] for r in con.execute("SELECT DISTINCT episode_id FROM player_ticks")]
    legs = []
    for eid in episode_ids:
        ticks = episode_ticks(con, eid)
        if len(ticks) < 3:
            continue
        visits = resource_visits(ticks, coords, rho)
        demo, player = epmeta.get(eid, ("?", "?"))
        for (i0, t0, a), (i1, t1, b) in zip(visits, visits[1:]):
            if a == b:
                continue
            seg = ticks[i0:i1 + 1]
            if len(seg) < 3:
                continue
            sig = compute_signature(seg)
            gx, gy = coords[b]
            end_dist = round(math.hypot(seg[-1]['x'] - gx, seg[-1]['y'] - gy), 1)
            legs.append({"demo": demo, "player": player, "episode": eid,
                         "from": a, "to": b, "end_dist_qu": end_dist, **sig})
    con.close()

    with open(os.path.join(out_dir, "legs_qwd.jsonl"), "w") as f:
        for L in legs:
            f.write(json.dumps(L) + "\n")

    byroute = defaultdict(list)
    for L in legs:
        byroute[(L["from"], L["to"])].append(L)
    envelopes = []
    for (a, b), ls in sorted(byroute.items(), key=lambda kv: -len(kv[1])):
        durs = sorted(L["dur_s"] for L in ls)
        core = [L for L in ls if L["dur_s"] <= durs[len(durs) // 2]] or ls
        e = {"from": a, "to": b, "count": len(ls), "core_count": len(core),
             "end_dist_qu_median": pctl([L["end_dist_qu"] for L in ls], .50),
             "demos": sorted({L["demo"] for L in ls}), "players": sorted({L["player"] for L in ls})}
        e.update(route_env(core))
        e["all_traffic"] = route_env(ls)
        envelopes.append(e)

    out = {"schema": "komodobots.route_envelopes_qwd.v1", "db": db,
           "method": f"position-based item visits per episode, rho={rho}qu",
           "n_episodes": len(episode_ids), "n_legs": len(legs), "distinct_routes": len(envelopes),
           "envelopes": envelopes}
    json.dump(out, open(os.path.join(out_dir, "envelopes_qwd.json"), "w"), indent=1)

    eds = sorted(L["end_dist_qu"] for L in legs) or [0]
    print(f"episodes: {len(episode_ids)}  legs: {len(legs)}  routes: {len(envelopes)}")
    print(f"end_dist_qu median={eds[len(eds)//2]:.0f} p90={eds[int(len(eds)*.9)]:.0f}  "
          f"(small => .qwd frame matches MVD frame; large => coordinate offset to resolve)")
    print("\nTOP 15 corpus routes  count  demos  dur(med)  hs_mean(med)  jumpInt(med)  straight")
    for e in envelopes[:15]:
        ji = e["jump_interval_s"]["median"] if e["jump_interval_s"] else None
        print(f"  {e['count']:3}x  {len(e['demos'])}d  {e['from']:8}->{e['to']:8}  "
              f"{e['dur_s']['median']:5.1f}s  {e['hs_mean']['median']:4.0f}   {str(ji):>6}     "
              f"{e['straightness']['median']:.3f}")


if __name__ == '__main__':
    if len(sys.argv) < 4:
        raise SystemExit(__doc__)
    rho = float(sys.argv[4]) if len(sys.argv) > 4 else DEFAULT_RHO
    main(sys.argv[1], sys.argv[2], sys.argv[3], rho)
