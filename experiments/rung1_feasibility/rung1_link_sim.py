#!/usr/bin/env python3
"""A4 #116 work item 4b/5 — END-TO-END sim with the rung-1 trick link IN the
(sim-side) nav graph. Entirely offline: the FBMARKER graph is parsed data;
no map edit, no lab contact, scripts/ untouched (the link + gate live in
THIS file via documented monkeypatching of the sim's selection seam).

What it models (= the D1-style design transposed to rung 1):
  * trick path m210 -> m97, appended into m210's free path slot (7/8 used
    live), flag TRICK (sim-local bit 0x8000);
  * zone-table semantics OPTION (b): the trick edge is EXCLUDED from the
    travel-time tables (like ROCKET_JUMP links — frogbot keeps separate
    tables; recommended for the live D1 code so slow bots map-wide are
    never attracted INTO a gated edge they cannot take). The pinned rung-1
    route already traverses 210, so exclusion costs nothing here. EvalPath
    still sees the per-path travel time (TravelTimeForPath = dist/320).
  * EvalPath gate: the TRICK-flagged path scores PATH_SCORE_NULL unless the
    evaluating bot's current horizontal speed >= gate. Evaluations happen
    where frogbot evaluates paths: PNLM/path-scoring at marker touches and
    at the carrot handover (SetMarker(210)+PNLM at pass_r before 210) —
    i.e. the gate samples speed ~0.3-0.6 s BEFORE the actual lip launch.
    Every trick evaluation is recorded (t, vh, verdict).

PRE-DECLARED (before any run): seeds 1..30 (the A1/A2 convention, same
seeds across cells); configs {c5-live, a2-c4}; gates {437 (census), 410
(sim-bias-adjusted: live-at-lip is ~7-8 % above sim-at-lip on the matched
c5 block — live-lip.json vs sim-lip.json), 0 (ungated upper bound)};
RUNG_A protocol exactly (spawn (385.5, 614.25, 56), pin 191, 48.1 s).

Per seed: trick gate evaluations, link taken?, leap outcome (cleared the
strip / fell short / never launched), lip-crossing speed + cross-track,
reach + arrival_t (paired vs the no-link sim-lip.json baseline runs).

Usage:  python rung1_link_sim.py [--out link-sim.json] [--workers N]
"""

from __future__ import annotations

import logging
import argparse
import json
import math
import multiprocessing
import sys
from pathlib import Path
from statistics import median


LOGGER = logging.getLogger(__name__)
EXP = Path(__file__).resolve().parent
sys.path.insert(0, str(EXP))

from rung1_lib import (  # noqa: E402
    SCRIPTS, attempt_segments, crossing_details, lip_attempt_metrics,
    load_route, rung1_gap, verify_route_mod, write_json,
)

sys.path.insert(0, str(SCRIPTS))
import mode23_sim as M  # noqa: E402
from mode23_sim import (  # noqa: E402
    LawParams, PATH_SCORE_NULL, analyze_attempt, build_world_and_graph,
    load_teleporters, run_attempt,
)
from mode23_sweep import RUNG_A  # noqa: E402

DEFAULT_BSP = r"C:\nQuake\qw\maps\dm3.bsp"
SEEDS = tuple(range(1, 31))
TRICK = 1 << 15                  # sim-local trick flag bit
SRC, DST = 210, 97
GATES = (437.0, 410.0, 0.0)
CONFIGS = {
    "c5-live": LawParams(),
    "a2-c4": LawParams(pass_r=100.0, numerator=9.0, swing=24.0,
                       turn_thresh=50.0, corner_thresh=45.0, corner_aim=85.0),
}

_G = {}


def install_trick_link(graph, gate_recorder):
    """Add the trick edge + gate into the selection seam (per process)."""
    # zone tables EXCLUDING the trick edge (option b), cached before the add
    tt_cache = {RUNG_A["goal_marker"]: graph.traveltime_to(RUNG_A["goal_marker"])}
    src = graph.markers[SRC]
    assert len(src.paths) < M.NUMBER_PATHS, "m210 free path slot gone?"
    idx = len(src.paths)
    src.paths.append((DST, TRICK))
    d = math.dist(src.nav, graph.markers[DST].nav)
    graph.edge_time[(SRC, DST, idx)] = d / M.SV_MAXSPEED   # TravelTimeForPath

    def traveltime_to(goal_num, _cache=tt_cache, _g=graph):
        if goal_num not in _cache:          # other goals: exclude trick edge
            saved = dict(_g.edge_time)
            del _g.edge_time[(SRC, DST, idx)]
            try:
                _cache[goal_num] = type(_g).traveltime_to(_g, goal_num)
            finally:
                _g.edge_time.update(saved)
        return _cache[goal_num]

    graph.traveltime_to = traveltime_to

    # EvalPath gate: thread current speed through path_scoring -> eval_path.
    if not hasattr(M.FrogbotBrain, "_a4_orig_eval_path"):
        M.FrogbotBrain._a4_orig_eval_path = M.FrogbotBrain.eval_path
        M.FrogbotBrain._a4_orig_path_scoring = M.FrogbotBrain.path_scoring
        M.FrogbotBrain._a4_orig_pnlm = M.FrogbotBrain.pnlm

        def pnlm(self, nav, origin, velocity, now):
            self._a4_now = now
            return M.FrogbotBrain._a4_orig_pnlm(self, nav, origin, velocity, now)

        def path_scoring(self, touch_num, origin, velocity):
            self._a4_vh = math.hypot(velocity[0], velocity[1])
            return M.FrogbotBrain._a4_orig_path_scoring(self, touch_num,
                                                        origin, velocity)

        def eval_path(self, test_num, desc, path_time, origin, player_dir,
                      current_goal_time, goal_late_time):
            if desc & TRICK:
                vh = getattr(self, "_a4_vh", 0.0)
                ok = vh >= _G["gate"]
                _G["recorder"].append({"t": round(getattr(self, "_a4_now", -1.0), 3),
                                       "vh": round(vh, 1), "passed": ok})
                if not ok:
                    return PATH_SCORE_NULL
            return M.FrogbotBrain._a4_orig_eval_path(
                self, test_num, desc, path_time, origin, player_dir,
                current_goal_time, goal_late_time)

        M.FrogbotBrain.pnlm = pnlm
        M.FrogbotBrain.path_scoring = path_scoring
        M.FrogbotBrain.eval_path = eval_path
    _G["recorder"] = gate_recorder


def leap_outcome(rows, gap):
    """Classify the leap on a sim trace: the LAST low-cross-track (<=80 qu)
    lip-plane crossing and what happened within 1.2 s after it."""
    segs = [rows]                       # whole-run scan (crossings pre-arrival
    det = None                          # are what we want; arrival truncation
    for seg in segs:                    # applied by the caller's metrics)
        d = crossing_details(seg, gap)
        if d and d["cross_track"] <= 80.0:
            det = d
    if det is None:
        return {"launched": False}
    after = [r for r in rows if det["t"] <= r["t"] <= det["t"] + 1.2]
    landed = any(114.0 <= r["z"] <= 126.0 and r["x"] <= -270.0
                 and r["y"] <= 620.0 for r in after)
    fell = any(r["z"] < 100.0 for r in after)
    return {"launched": True, "cross_vh": det["vh"], "cross_t": det["t"],
            "cross_track": det["cross_track"],
            "cleared": bool(landed and not fell), "fell_short": bool(fell)}


def _init_worker(bsp):
    from bsp_geom import Bsp
    world, graph = build_world_and_graph(bsp, None)
    geom = Bsp.load(bsp)
    route = load_route()
    _G.update(world=world, graph=graph, teles=load_teleporters(bsp),
              route=route, gap=rung1_gap(route), gate=0.0,
              floor=lambda x, y, z: geom.floor_z(x, y, z))
    install_trick_link(graph, [])


def eval_cell(job):
    cname, pdict, gate, seed = job
    _G["gate"] = gate
    rec = []
    _G["recorder"] = rec
    p = LawParams(**pdict)
    res = run_attempt(_G["world"], _G["graph"], seed, config="c5",
                      budget_s=RUNG_A["budget_s"], spawn=RUNG_A["spawn"],
                      goal_marker=RUNG_A["goal_marker"],
                      goal_pos=_G["route"]["goal"], teleporters=_G["teles"],
                      floor_fn=_G["floor"], params=p)
    a = analyze_attempt(res.rows, _G["route"])
    link_rows = sum(1 for r in res.rows if r.get("linked") == DST)
    out = {"seed": seed, "reached": a["reached"], "arrival_t": a["arrival_t"],
           "arrival_tws": a["arrival_tws"],
           "gate_evals": rec, "link_linked_rows": link_rows,
           **leap_outcome(res.rows, _G["gap"])}
    # lip metrics on conditioned segments (same as everywhere else)
    segs = attempt_segments(res.rows, _G["route"])
    if segs:
        m = lip_attempt_metrics(segs[0], _G["gap"])
        out["edge_first_attempt"] = m["edge"]
    return cname, gate, out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bsp", default=DEFAULT_BSP)
    ap.add_argument("--out", default=str(EXP / "link-sim.json"))
    ap.add_argument("--workers", type=int, default=10)
    args = ap.parse_args()

    jobs = [(cn, p.__dict__, g, s) for cn, p in CONFIGS.items()
            for g in GATES for s in SEEDS]
    cells = {}
    with multiprocessing.Pool(args.workers, initializer=_init_worker,
                              initargs=(args.bsp,)) as pool:
        for cn, gate, rec in pool.imap_unordered(eval_cell, jobs):
            cells.setdefault(f"{cn}_gate{gate:g}", []).append(rec)
            n = sum(len(v) for v in cells.values())
            if n % 30 == 0:
                print(f"  {n}/{len(jobs)} runs")
    for v in cells.values():
        v.sort(key=lambda r: r["seed"])

    summary = {}
    for key, recs in sorted(cells.items()):
        evals = [e for r in recs for e in r["gate_evals"]]
        passes = [e for e in evals if e["passed"]]
        launched = [r for r in recs if r.get("launched")]
        cleared = [r for r in launched if r.get("cleared")]
        att_t = [r["arrival_t"] for r in recs if r["arrival_t"] is not None]
        summary[key] = {
            "seeds": len(recs),
            "gate_evals": len(evals),
            "gate_eval_vh_median": (round(median(e["vh"] for e in evals), 1)
                                    if evals else None),
            "gate_passes": len(passes),
            "seeds_with_pass": sum(1 for r in recs
                                   if any(e["passed"] for e in r["gate_evals"])),
            "seeds_linked": sum(1 for r in recs if r["link_linked_rows"] > 0),
            "launched": len(launched),
            "cleared": len(cleared),
            "fell_short": sum(1 for r in launched if r.get("fell_short")),
            "cross_vh": sorted(round(r["cross_vh"]) for r in launched),
            "reach": sum(1 for r in recs if r["reached"]),
            "arrival_t_median": round(median(att_t), 1) if att_t else None,
        }
        s = summary[key]
        print(f"{key:22s} evals={s['gate_evals']:3d} med_vh={s['gate_eval_vh_median']} "
              f"passes={s['gate_passes']:3d} linked={s['seeds_linked']:2d} "
              f"launched={s['launched']:2d} cleared={s['cleared']:2d} "
              f"fell={s['fell_short']:2d} reach={s['reach']:2d} "
              f"arr_t_med={s['arrival_t_median']}")

    write_json(args.out, {"seeds": list(SEEDS), "gates": list(GATES),
                          "configs": list(CONFIGS),
                          "trick": {"src": SRC, "dst": DST, "flag": TRICK,
                                    "table_semantics": "excluded (option b)"},
                          "summary": summary, "cells": cells})


if __name__ == "__main__":
    main()
