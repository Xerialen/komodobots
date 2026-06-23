#!/usr/bin/env python3
"""A4 #116 work item 3 — lip speed in sim, n=30 declared seeds per config.

PRE-DECLARED (before any run; the A1/A2 convention):
  * seeds 1..30, identical across configs (paired);
  * protocol = RUNG_A exactly (mode23_sweep): spawn (385.5, 614.25, 56),
    pin marker 191, budget 48.1 s, goal_pos = the route goal, teleporters +
    floor_fn as in the sweep's rung-A half;
  * configs (all of record):
      c5-live      — LawParams() (the deployed default; A1 anchor)
      a2-c1        — p100_n5_s24_t35_c45-85_gpos60x2_l0.3 (A2 candidate C-1)
      a2-c2        — p130_n5_s24_t50_c75-50_gvel60x2_l0   (A2 candidate C-2)
      a2-c3        — p100_n5_s24_t35_c45-85_gpos75x2_l0.3 (A2 candidate C-3)
      a2-c4        — p100_n9_s24_t50_c45-85_gnone_l0      (A2 candidate C-4,
                     cvar-only)
      cj-launch    — tail_autopsy.PATTERNIZED (p100/n5/s12/t35/c45-85 +
                     launch_vh 400 / launch_angle 42). DISCLOSED up front:
                     A2b measured the launch forced ON in the rung-A spawn
                     room at reach 10/30 vs 21/30 base (circle wall-locks in
                     tight rooms) — included because the ticket asks; its
                     rung-A reach is expected to crater.
  * measurements per attempt: rung1_lib.lip_attempt_metrics (the same
    functions as the live scoring — edge_speed at the rung-1 gap, closest
    lip approach, reached_lip, grounded-near max) + analyze_attempt reach.

Anchor: the c5-live row must reproduce A1 (reach 12/30, arrival-tws median
279.4) — printed and asserted.

Usage:  python rung1_lip_sim.py [--out sim-lip.json] [--workers N]
"""

from __future__ import annotations

import logging
import argparse
import multiprocessing
import sys
from pathlib import Path
from statistics import median


LOGGER = logging.getLogger(__name__)
EXP = Path(__file__).resolve().parent
sys.path.insert(0, str(EXP))

from rung1_lib import (  # noqa: E402
    REQUIRED, SCRIPTS, attempt_segments, lip_attempt_metrics, load_route,
    rung1_gap, verify_route_mod, write_json,
)

sys.path.insert(0, str(SCRIPTS))
from mode23_sim import (  # noqa: E402
    LawParams, analyze_attempt, build_world_and_graph, load_teleporters,
    run_attempt,
)
from mode23_sweep import RUNG_A  # noqa: E402
from tail_autopsy import PATTERNIZED  # noqa: E402

DEFAULT_BSP = r"C:\nQuake\qw\maps\dm3.bsp"
SEEDS = tuple(range(1, 31))

CONFIGS = {
    "c5-live": LawParams(),
    "a2-c1": LawParams(pass_r=100.0, numerator=5.0, swing=24.0,
                       turn_thresh=35.0, corner_thresh=45.0, corner_aim=85.0,
                       governor="pos", prec_thresh=60.0, prec_timeout=2.0,
                       carrot_lead=0.3),
    "a2-c2": LawParams(pass_r=130.0, numerator=5.0, swing=24.0,
                       turn_thresh=50.0, corner_thresh=75.0, corner_aim=50.0,
                       governor="vel", prec_thresh=60.0, prec_timeout=2.0),
    "a2-c3": LawParams(pass_r=100.0, numerator=5.0, swing=24.0,
                       turn_thresh=35.0, corner_thresh=45.0, corner_aim=85.0,
                       governor="pos", prec_thresh=75.0, prec_timeout=2.0,
                       carrot_lead=0.3),
    "a2-c4": LawParams(pass_r=100.0, numerator=9.0, swing=24.0,
                       turn_thresh=50.0, corner_thresh=45.0, corner_aim=85.0),
    "cj-launch": PATTERNIZED,
}

A1_ANCHOR = {"reach": 12, "tws_median": 279.4}

_G = {}


def _init_worker(bsp):
    from bsp_geom import Bsp
    world, graph = build_world_and_graph(bsp, None)
    geom = Bsp.load(bsp)
    route = load_route()
    _G.update(world=world, graph=graph, teles=load_teleporters(bsp),
              route=route, gap=rung1_gap(route),
              floor=lambda x, y, z: geom.floor_z(x, y, z))


def eval_seed(job):
    name, pdict, seed = job
    p = LawParams(**pdict)
    res = run_attempt(_G["world"], _G["graph"], seed, config="c5",
                      budget_s=RUNG_A["budget_s"], spawn=RUNG_A["spawn"],
                      goal_marker=RUNG_A["goal_marker"],
                      goal_pos=_G["route"]["goal"], teleporters=_G["teles"],
                      floor_fn=_G["floor"], params=p)
    a = analyze_attempt(res.rows, _G["route"])
    vr = verify_route_mod()
    atts = []
    for seg in attempt_segments(res.rows, _G["route"]):
        cls, closest, _, _ = vr.classify(seg, _G["route"]["geom"])
        m = lip_attempt_metrics(seg, _G["gap"])
        m.update(cls=cls, closest_goal=round(closest, 1),
                 t0=seg[0]["t"], dur=round(seg[-1]["t"] - seg[0]["t"], 1))
        atts.append(m)
    return name, {"seed": seed, "reached": a["reached"],
                  "arrival_tws": a["arrival_tws"], "arrival_t": a["arrival_t"],
                  "attempts": atts}


def summarize(name, recs):
    atts = [a for r in recs for a in r["attempts"]]
    lip = [a for a in atts if a["reached_lip"]]
    edges = [a["edge"] for a in atts if a["edge"] is not None]
    lo = [a["edge"] for a in atts if a["crossing"]
          and a["crossing"]["cross_track"] <= 80]
    lip_vh = [a["lip_approach"]["vh"] for a in lip]
    near = [a["grounded_near_vh_max"] for a in atts
            if a["grounded_near_vh_max"] is not None]
    tws = sorted(r["arrival_tws"] for r in recs if r["arrival_tws"] is not None)
    seeds_lip = sum(1 for r in recs if any(a["reached_lip"] for a in r["attempts"]))
    seeds_near437 = sum(1 for r in recs
                        if any(a["grounded_near_vh_max"] is not None
                               and a["grounded_near_vh_max"] >= REQUIRED
                               for a in r["attempts"]))
    return {
        "config": name, "n_seeds": len(recs),
        "reach": sum(1 for r in recs if r["reached"]),
        "arrival_tws_median": round(median(tws), 1) if tws else None,
        "attempts": len(atts),
        "reached_lip_attempts": len(lip),
        "seeds_reaching_lip": seeds_lip,
        "seeds_grounded_near_ge437": seeds_near437,
        "edge_n": len(edges),
        "edge_median": round(median(edges), 1) if edges else None,
        "edge_max": max(edges) if edges else None,
        "edge_ge_437": sum(1 for v in edges if v >= REQUIRED),
        "edge_lowcross_n": len(lo),
        "lip_vh_median": round(median(lip_vh), 1) if lip_vh else None,
        "lip_vh_ge_437": sum(1 for v in lip_vh if v >= REQUIRED),
        "grounded_near_median": round(median(near), 1) if near else None,
        "grounded_near_max": max(near) if near else None,
        "grounded_near_ge_437": sum(1 for v in near if v >= REQUIRED),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bsp", default=DEFAULT_BSP)
    ap.add_argument("--out", default=str(EXP / "sim-lip.json"))
    ap.add_argument("--workers", type=int, default=10)
    args = ap.parse_args()

    jobs = [(name, p.__dict__, s) for name, p in CONFIGS.items() for s in SEEDS]
    per = {name: [] for name in CONFIGS}
    with multiprocessing.Pool(args.workers, initializer=_init_worker,
                              initargs=(args.bsp,)) as pool:
        for name, rec in pool.imap_unordered(eval_seed, jobs):
            per[name].append(rec)
            done = sum(len(v) for v in per.values())
            if done % 30 == 0:
                print(f"  {done}/{len(jobs)} runs done")
    for name in per:
        per[name].sort(key=lambda r: r["seed"])

    summaries = [summarize(name, per[name]) for name in CONFIGS]
    anchor = next(s for s in summaries if s["config"] == "c5-live")
    anchor_ok = (anchor["reach"] == A1_ANCHOR["reach"]
                 and anchor["arrival_tws_median"] == A1_ANCHOR["tws_median"])
    print(f"\nA1 anchor (c5-live): reach {anchor['reach']} (want {A1_ANCHOR['reach']}), "
          f"tws_median {anchor['arrival_tws_median']} (want {A1_ANCHOR['tws_median']}) "
          f"-> {'OK' if anchor_ok else 'MISMATCH'}")

    write_json(args.out, {"seeds": list(SEEDS), "anchor_ok": anchor_ok,
                          "summaries": summaries, "per_config": per})
    hdr = (f"{'config':10s} {'reach':>5s} {'lip%att':>8s} {'edge_n':>6s} "
           f"{'edge_med':>8s} {'ge437':>5s} {'gnd_med':>7s} {'gnd_max':>7s} "
           f"{'gnd437':>6s} {'seeds437':>8s}")
    print("\n" + hdr)
    for s in summaries:
        lipshare = (s["reached_lip_attempts"] / s["attempts"]) if s["attempts"] else 0
        print(f"{s['config']:10s} {s['reach']:5d} {lipshare:8.2f} {s['edge_n']:6d} "
              f"{str(s['edge_median']):>8s} {s['edge_ge_437']:5d} "
              f"{str(s['grounded_near_median']):>7s} {str(s['grounded_near_max']):>7s} "
              f"{s['grounded_near_ge_437']:6d} {s['seeds_grounded_near_ge437']:8d}")


if __name__ == "__main__":
    main()
