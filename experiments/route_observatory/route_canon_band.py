#!/usr/bin/env python3
"""route_canon_band.py — widen each #420 Route Canon SEED LINE into an empirical BAND (#421 T2.2).

For every highway in `route_canon.dm3.json`, harvest the corpus legs that are the SAME clean
traversal as the owner-cut seed, then aggregate them into a band. The harvest is gated by
(1) endpoint == seed, (2) trick-clean (`build_route_canon._suspect_trick`), (3) trajectory
SIMILARITY to the seed line, (4) `route_class` — and **NEVER by the `(from,to)` resource pair
alone**, which would re-pool base + shortcut traversals (the exact contamination #420 prevents; see
`route_canon.dm3.json` `_match_key`). filter 1 is a cheap prefilter, NOT the decision.

The seed line stays #428's MSE/RMSE centerline (the elite path to beat). This band is the
**human-range tolerance/feasibility envelope** consumed by **Phase-4 drift/believability monitoring
+ curriculum** — NOT a #428 input (docs/28 M2 "Route Canon & Ground-Truth Signatures").

Reuses (anchors — do not reinvent): route_legs.player_ticks / resource_visits / resource_coords /
route_env / pctl, pov_fuse_extract.compute_signature, build_route_canon._suspect_trick / _self_damage.

Usage:
  route_canon_band.py <route_canon.json> --analysis <alias>=<full.json> [--analysis ...] -o <bands.json>
    --analysis maps each highway-seed `demo` alias -> a qw-analyze full JSON
      (qw-analyze -view full -include positions,view,velocity <demo>).
"""
import logging
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "ml", "pipeline"))
from route_legs import player_ticks, resource_visits, resource_coords, route_env, pctl  # noqa: E402
from pov_fuse_extract import compute_signature  # noqa: E402
from build_route_canon import _suspect_trick, _self_damage  # noqa: E402

LOGGER = logging.getLogger(__name__)

SCHEMA = "komodobots.route_canon_bands.v1"

# Similarity gate (the `_match_key` rule). A candidate must FOLLOW the seed, not merely share its
# endpoints. SIM_QU is the median per-point (x,y) distance ceiling (= route_legs visit rho). The
# straightness/jump backstops are EXPLICIT tolerance WIDTHS (auditor N5): one seed is not a
# distribution, so #421 sets the width here; the corpus harvest later tightens it empirically.
SIM_QU = 200.0
CORRIDOR_M = 64            # resample points for similarity + the positional corridor
STRAIGHT_TOL = 0.15       # |straightness - seed| ceiling
JUMP_TOL_FRAC = 0.5       # |jumps - seed| / max(seed_jumps, 1) ceiling
MIN_LEG_TICKS = 3


def _resample_xy(pts, m=CORRIDOR_M):
    """Resample a polyline [(x,y),...] to m points evenly along its INDEX (linear interpolation)."""
    n = len(pts)
    if n == 0:
        return []
    if n == 1:
        return [pts[0]] * m
    out = []
    for k in range(m):
        u = k * (n - 1) / (m - 1)
        i = int(math.floor(u))
        if i >= n - 1:
            out.append(pts[-1])
            continue
        f = u - i
        (x0, y0), (x1, y1) = pts[i], pts[i + 1]
        out.append((x0 + f * (x1 - x0), y0 + f * (y1 - y0)))
    return out


def _median_point_dist(seed_xy, cand_xy, m=CORRIDOR_M):
    """Median per-point (x,y) distance between two polylines resampled to a common m (arc-fraction
    alignment). The honest v1 path metric; Fréchet/DTW is the named upgrade if the band shows
    contamination."""
    a, b = _resample_xy(seed_xy, m), _resample_xy(cand_xy, m)
    if not a or not b:
        return float("inf")
    ds = sorted(math.hypot(a[k][0] - b[k][0], a[k][1] - b[k][1]) for k in range(m))
    return ds[len(ds) // 2]


def _seed_xy(segment):
    return [(p[1], p[2]) for p in segment["trajectory"]]   # trajectory rows are [t, x, y, z]


def gate_keep(seed_seg, cand_ticks, cand_sig, self_dmg,
              sim_qu=SIM_QU, m=CORRIDOR_M, straight_tol=STRAIGHT_TOL, jump_tol_frac=JUMP_TOL_FRAC):
    """Similarity gate filters 2-4 (the caller applies filter 1 endpoint + the route_class match).
    Returns (keep, median_dist_qu, reason). `self_dmg` is the leg's self-damage events, or None when
    the damage stream is unavailable (fail-closed via _suspect_trick)."""
    susp, reasons, _ = _suspect_trick(cand_ticks, self_dmg)   # filter 2: trick-clean (reuse #420)
    if susp:
        return False, None, "suspect_trick: " + "; ".join(reasons)
    dist = _median_point_dist(_seed_xy(seed_seg), [(t["x"], t["y"]) for t in cand_ticks], m)
    if dist > sim_qu:                                         # filter 3: path similarity
        return False, dist, f"path dissimilar: median {round(dist)} > {round(sim_qu)} qu"
    seed_sig = seed_seg["signature"]                          # filter 3 backstop (explicit width)
    ss, cs = seed_sig.get("straightness"), cand_sig.get("straightness")
    if ss is not None and cs is not None and abs(cs - ss) > straight_tol:
        return False, dist, f"straightness {cs} outside seed {ss} +/- {straight_tol}"
    sj = seed_sig.get("jumps", 0)
    if abs(cand_sig.get("jumps", 0) - sj) > jump_tol_frac * max(sj, 1):
        return False, dist, f"jump-count {cand_sig.get('jumps', 0)} outside seed {sj}"
    return True, dist, "kept"


def positional_corridor(kept_xy, m=CORRIDOR_M):
    """At each of m arc-fractions, the p10/median/p90 of x and y across the kept legs — the literal
    'widen the seed LINE to a BAND'. Resample-by-fraction aligns legs of different lengths."""
    if not kept_xy:
        return []
    res = [_resample_xy(t, m) for t in kept_xy]
    corridor = []
    for k in range(m):
        xs = [r[k][0] for r in res]
        ys = [r[k][1] for r in res]
        corridor.append({"frac": round(k / (m - 1), 4),
                         "x": {"p10": pctl(xs, .10), "median": pctl(xs, .50), "p90": pctl(xs, .90)},
                         "y": {"p10": pctl(ys, .10), "median": pctl(ys, .50), "p90": pctl(ys, .90)}})
    return corridor


def build_band(highway, analyses, coords_by_alias):
    """Harvest one canon highway's band across the provided analyses. Matches on the FIRST segment's
    endpoints (single-segment base highways; a multi-segment shortcut matches its segment[0] — a
    documented limitation, fine since Phase-1 consumes base highways only)."""
    seed_seg = highway["segments"][0]
    seed_from, seed_to, rclass = seed_seg["from_resource"], seed_seg["to_resource"], highway["route_class"]
    sd_demo, sd_player = highway["seed"]["demo"], highway["seed"]["player"]
    sd_t0, sd_t1 = float(highway["seed"]["start_s"]), float(highway["seed"]["end_s"])

    # The seed is ALWAYS a member of its own band (n >= 1, corridor always brackets the seed); corpus
    # matches widen it. An idiosyncratic half-route cut that no other corpus traversal resembles stays
    # n=1 — honestly "no corpus support yet", not an empty band.
    kept = [{"demo": sd_demo, "player": sd_player, "t0": sd_t0, "t1": sd_t1,
             "source": "seed", "median_dist_qu": 0.0}]
    kept_sigs = [seed_seg["signature"]]
    kept_xy = [[(p[1], p[2]) for p in seed_seg["trajectory"]]]
    by_source = {"seed": 1}

    for alias, d in analyses.items():
        coords = coords_by_alias[alias]
        dmg = d.get("damage")
        events = dmg.get("events") if isinstance(dmg, dict) else None
        dmg_events = events if isinstance(events, list) else None
        for P in d["streams"]["players"]:
            ticks = player_ticks(P)
            visits = resource_visits(ticks, coords)
            for (i0, t0, a), (i1, t1, b) in zip(visits, visits[1:]):
                if (a, b) != (seed_from, seed_to):          # filter 1: endpoint prefilter (cheap)
                    continue
                if (alias == sd_demo and P["name"] == sd_player          # don't double-count the seed
                        and not (t1 < sd_t0 or t0 > sd_t1)):             # leg if it re-appears here
                    continue
                seg = ticks[i0:i1 + 1]
                if len(seg) < MIN_LEG_TICKS:
                    continue
                sig = compute_signature(seg)
                sdmg = (None if dmg_events is None
                        else _self_damage(dmg_events, P["name"], seg[0]["t"] * 1000, seg[-1]["t"] * 1000))
                keep, dist, reason = gate_keep(seed_seg, seg, sig, sdmg)
                if not keep:
                    continue
                kept.append({"demo": alias, "player": P["name"], "source": "corpus",
                             "t0": round(t0, 2), "t1": round(t1, 2),
                             "median_dist_qu": round(dist, 1) if dist is not None else None})
                kept_sigs.append(sig)
                kept_xy.append([(t["x"], t["y"]) for t in seg])
                by_source[alias] = by_source.get(alias, 0) + 1

    LOGGER.info("%s [%s] %s->%s: kept %d traversal(s) %s",
                highway["id"], rclass, seed_from, seed_to, len(kept), dict(by_source))
    return {
        "id": highway["id"], "label": highway["label"], "route_class": rclass,
        "from_resource": seed_from, "to_resource": seed_to,
        "seed": highway["seed"],
        "n_traversals": len(kept), "by_source": by_source,
        "gate": {"sim_qu": SIM_QU, "corridor_m": CORRIDOR_M, "straight_tol": STRAIGHT_TOL,
                 "jump_tol_frac": JUMP_TOL_FRAC,
                 "rule": "endpoint==seed AND _suspect_trick-clean AND median(x,y)<=sim_qu AND "
                         "route_class==seed AND straightness/jumps within explicit tol; "
                         "NEVER (from,to) alone"},
        "signature_band": route_env(kept_sigs) if kept_sigs else None,
        # a corridor needs a BAND: with only the seed (n=1) it would be the seed line resampled
        # (p10==median==p90), which is already route_canon — emit it only once corpus widens the seed.
        "positional_corridor": positional_corridor(kept_xy) if len(kept_xy) > 1 else [],
        "members": kept,
    }


def main(argv):
    canon_path, out, amap = None, None, {}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("-o", "--out"):
            out = argv[i + 1]; i += 2
        elif a == "--analysis":
            key, _, val = argv[i + 1].partition("="); amap[key] = val; i += 2
        elif canon_path is None:
            canon_path = a; i += 1
        else:
            raise SystemExit(f"unexpected arg: {a!r}")
    if not canon_path or not out:
        raise SystemExit("usage: route_canon_band.py <route_canon.json> "
                         "--analysis <alias>=<full.json> [...] -o <bands.json>")

    canon = json.loads(open(canon_path, encoding="utf-8").read())
    analyses, coords_by_alias = {}, {}
    for alias, path in amap.items():
        d = json.loads(open(path, encoding="utf-8").read())
        analyses[alias] = d
        coords_by_alias[alias] = resource_coords(d)

    bands = []
    for h in canon["highways"]:
        seed_alias = h["seed"]["demo"]
        if seed_alias not in analyses:
            LOGGER.warning("highway %r: no --analysis for seed demo %r — harvesting only the "
                           "provided analyses (seed not necessarily present)", h["id"], seed_alias)
        bands.append(build_band(h, analyses, coords_by_alias))

    doc = {
        "schema": SCHEMA, "map": canon.get("map", "dm3"),
        "_generated_by": "experiments/route_observatory/route_canon_band.py",
        "_seed_source": os.path.basename(canon_path),
        "_consumer": ("Phase-4 drift/believability monitoring + curriculum. NOT a #428 input — #428 "
                      "scores MSE/RMSE against the #420 seed centerline (route_canon segments[]."
                      "trajectory); this band is the human-range tolerance envelope around it."),
        "_match_key": ("harvest gated by seed-trajectory similarity + route_class, NEVER by "
                       "(from,to) — re-pooling the pair re-introduces the trick/shortcut "
                       "contamination #420 prevents (see route_canon.dm3.json _match_key)."),
        "_provenance": {"analyses": sorted(amap), "n_bands": len(bands)},
        "bands": bands,
    }
    open(out, "w", encoding="utf-8").write(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    print(f"WROTE {out}  ({len(bands)} bands; "
          f"{sum(b['n_traversals'] for b in bands)} kept traversals total)")
    for b in bands:
        print(f"  {b['id']:28} [{b['route_class']:8}] {b['from_resource']}->{b['to_resource']} "
              f"n={b['n_traversals']:3} {dict(b['by_source'])}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    main(sys.argv[1:])
