#!/usr/bin/env python3
"""A2 #74: pre-registered offline sweep over mode-23 constants (P3b).

Everything here executes the pre-registration written to the loop ledger
BEFORE the first sweep run (artifacts/loop-state.md, A2 rows; committed copy
in experiments/p3b_sweep/evidence/sweep-report.md). Summary:

PROTOCOLS (per config, seeds 1..30, SAME seeds across configs):
  * Rung A — sng_shortcut2 floor + tiebreak, the exact A1 calibration
    protocol: spawn (385.5, 614.25, 56), pin marker 191, budget 48.1 s,
    verify_route attempt conditioning via mode23_sim.analyze_attempt.
    Yields: reach count, arrival-tws median (None-safe), and the Gate-2
    corner stat = pooled pre-arrival deduped linked-marker exits from 207
    (conversion = share that goes to 191; 206->207 share is diagnostic).
  * Rung B — the STEP-0 surrogate for the >=526 launch-edge objective
    (the directed walkable route to RL never crosses the census launch
    edge, so the objective is measured on the directed bridge approach):
    spawn m75 org (1959, -425, -24), pin marker 148 (one hop past tip
    marker 110), budget 20.0 s.  Per seed: route_metrics.edge_speed (A0
    metric, constants UNCHANGED) over legit_segment(rows, ()) truncated at
    the first arrival within 60 qu (3D) of the pin nav.  None = never
    crossed; None is NEVER averaged as 0.

RANKING (applies unchanged to the final stage-1 UNION stage-2 table):
  eligible iff rung-A reach >= 12/30 (sim-c5 baseline, A1) AND rung-B
  edge_n >= 8/30; sort by (edge_median desc, corner conversion desc with
  None last, config id asc).  Ineligible configs are listed, not ranked.
  Transfer candidates: ranks 1-3 + mid rank max(4, ceil(N_ranked/2)).

OFF-RAMP: if NO config (ranked or unranked) records ANY seed with
  edge >= 526.0 -> control-law ceiling finding -> ESCALATION (no PR ship).

CLI:
  python mode23_sweep.py sweep  --stage 1 [--workers 12] [--out DIR]
  python mode23_sweep.py sweep  --stage 2 [--workers 12] [--out DIR]
  python mode23_sweep.py report [--out DIR]
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import multiprocessing
import statistics
import sys
import time
from dataclasses import asdict, replace
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from mode23_sim import (  # noqa: E402
    DEFAULT_BSP, LawParams, analyze_attempt, build_world_and_graph,
    load_route_cfg, load_teleporters, run_attempt, verify_route_mod,
)
from route_metrics import (  # noqa: E402
    _truncate_at_arrival, edge_speed, legit_segment,
)

REPO = SCRIPTS.parent
DEFAULT_OUT = REPO / "artifacts" / "p3b-sweep"

SEEDS = tuple(range(1, 31))

# Rung A: the exact A1 calibration protocol (floor + tiebreak rung).
RUNG_A = {"spawn": (385.5, 614.25, 56.0), "goal_marker": 191, "budget_s": 48.1}
# Rung B: the STEP-0 surrogate (directed bridge approach past tip marker 110).
RUNG_B = {"spawn": (1959.0, -425.0, -24.0), "goal_marker": 148, "budget_s": 20.0}

ARRIVE_R = 60.0            # REACH_RL convention (verify_route.REACH_RL)
CORNER_FROM, CORNER_TO = 207, 191
CORNER_DIAG = 206          # diagnostic column: 206 -> 207 share

REACH_FLOOR = 12           # sim-c5 baseline reach (A1)
EDGE_N_FLOOR = 8           # rankability floor on rung-B crossing count
EDGE_TARGET = 526.0        # the sprint objective (census required 525.3)

# ── stage-1 grid (pre-registered) ────────────────────────────────────────────
PASS_R_VALUES = (100.0, 130.0, 170.0)
NUMERATOR_VALUES = (5.0, 9.0, 16.0, 26.0)
SWING_VALUES = (6.0, 12.0, 24.0)
TURN_VALUES = (25.0, 35.0, 50.0)
CORNER_PAIRS = ((58.0, 68.0), (45.0, 85.0), (75.0, 50.0))
GOVERNORS = ("none", "vel", "pos")
LEADS = (0.0, 0.3)

# stage-2 refinement steps (pre-registered)
DIM_STEPS = {"pass_r": 20.0, "numerator": 3.0, "swing": 4.0,
             "turn_thresh": 7.0, "corner": (8.0, 8.0), "carrot_lead": 0.15}
STAGE2_CAP = 300
PREC_THRESH_GRID = (45.0, 60.0, 75.0)
PREC_TIMEOUT_GRID = (1.0, 2.0, 3.0)


def stage1_grid():
    out = []
    for pr, nu, sw, tt, (ct, ca), gov, lead in itertools.product(
            PASS_R_VALUES, NUMERATOR_VALUES, SWING_VALUES, TURN_VALUES,
            CORNER_PAIRS, GOVERNORS, LEADS):
        out.append(LawParams(pass_r=pr, numerator=nu, swing=sw,
                             turn_thresh=tt, corner_thresh=ct, corner_aim=ca,
                             governor=gov, carrot_lead=lead))
    return out


def config_id(p: LawParams) -> str:
    gov = p.governor
    if gov != "none":
        gov += f"{p.prec_thresh:g}x{p.prec_timeout:g}"
    return (f"p{p.pass_r:g}_n{p.numerator:g}_s{p.swing:g}_t{p.turn_thresh:g}"
            f"_c{p.corner_thresh:g}-{p.corner_aim:g}_g{gov}_l{p.carrot_lead:g}")


# ── pure helpers (unit-tested) ───────────────────────────────────────────────
def dedup_linked(rows):
    """First-class linked-marker sequence: consecutive duplicates collapsed,
    None skipped (the decomposition's deduped sequence convention)."""
    seq = []
    for r in rows:
        lk = r.get("linked")
        if lk is None:
            continue
        if not seq or seq[-1] != lk:
            seq.append(lk)
    return seq


def exits_from(seq, frm):
    """Successors of every occurrence of `frm` in a deduped sequence."""
    return [b for a, b in zip(seq, seq[1:]) if a == frm]


def corner_stats(rows, route):
    """Gate-2 corner stat on one rung-A run: pooled PRE-ARRIVAL deduped
    linked-marker exits from 207 (and the 206 diagnostic), over the run's
    verify_route attempt segments — the P2 decomposition's convention."""
    vr = verify_route_mod()
    e207, e206 = [], []
    for s, e in vr.segment_attempts(rows, route):
        seg = legit_segment(rows[s:e], route["tele_entrances"])
        if len(seg) < 3:
            continue
        seg = _truncate_at_arrival(seg, vr.REACH_RL)
        seq = dedup_linked(seg)
        e207 += exits_from(seq, CORNER_FROM)
        e206 += exits_from(seq, CORNER_DIAG)
    return e207, e206


def edge_objective(rows, gap):
    """The pre-registered rung-B per-seed measurement: A0 edge_speed over the
    legit segment truncated at first arrival within 60 qu of the pin (rows
    carry dist_goal vs the pin nav).  No sanctioned teleporters: any teleport
    (the pit ride) truncates the segment.  None = never crossed."""
    seg = legit_segment(rows, ())
    seg = _truncate_at_arrival(seg, ARRIVE_R)
    return edge_speed(seg, gap, ())


def _median(vals):
    return round(statistics.median(vals), 1) if vals else None


def aggregate(cid, p: LawParams, rung_a_runs, corner_207, corner_206,
              edge_vals, edge_arrivals, elapsed=None):
    """Fold per-seed results into the per-config jsonl record."""
    reach = sum(1 for r in rung_a_runs if r["reached"])
    tws = sorted(r["arrival_tws"] for r in rung_a_runs
                 if r["arrival_tws"] is not None)
    conv = (round(corner_207.count(CORNER_TO) / len(corner_207), 3)
            if corner_207 else None)
    diag = (round(corner_206.count(CORNER_FROM) / len(corner_206), 3)
            if corner_206 else None)
    present = sorted(v for v in edge_vals if v is not None)
    return {
        "id": cid,
        "params": asdict(p),
        "rungA": {
            "reach": reach,
            "tws_median": _median(tws),
            "corner_exits_207": len(corner_207),
            "corner_conv": conv,
            "corner_exits_206": len(corner_206),
            "corner_206_to_207": diag,
            "per_seed": rung_a_runs,
        },
        "rungB": {
            "edge_n": len(present),
            "edge_median": _median(present),
            "edge_max": round(present[-1], 1) if present else None,
            "arrivals": sum(edge_arrivals),
            "edge_values": [None if v is None else round(v, 1)
                            for v in edge_vals],
        },
        "elapsed_s": elapsed,
    }


def eligible(rec):
    return (rec["rungA"]["reach"] >= REACH_FLOOR
            and rec["rungB"]["edge_n"] >= EDGE_N_FLOOR)


def rank_key(rec):
    """Pre-registered ranking: edge_median desc, corner conversion desc with
    None LAST, config id asc.  None is never compared as a number."""
    conv = rec["rungA"]["corner_conv"]
    return (-rec["rungB"]["edge_median"],
            -(conv if conv is not None else -1.0),
            rec["id"])


def split_ranked(records):
    elig = sorted((r for r in records if eligible(r)), key=rank_key)
    elig_ids = {r["id"] for r in elig}
    rest = [r for r in records if r["id"] not in elig_ids]
    return elig, rest


def pick_candidates(ranked):
    """Transfer candidates: ranks 1-3 + mid rank max(4, ceil(N/2)), 1-based.
    Fewer than 4 rankable configs -> escalation (None)."""
    n = len(ranked)
    if n < 4:
        return None
    mid = max(4, math.ceil(n / 2))
    return [ranked[0], ranked[1], ranked[2], ranked[mid - 1]]


# ── stage-2 grid (pre-registered refinement rule) ────────────────────────────
_DIMS = ("pass_r", "numerator", "swing", "turn_thresh", "corner",
         "governor", "carrot_lead")


def dim_value(p: LawParams, dim):
    if dim == "corner":
        return (p.corner_thresh, p.corner_aim)
    return getattr(p, dim)


def marginal_ranges(ranked):
    """Per-dimension marginal effect: range of mean edge_median grouped by
    the dimension's values, over RANKED configs only."""
    out = {}
    for dim in _DIMS:
        groups = {}
        for r in ranked:
            v = dim_value(LawParams(**r["params"]), dim)
            groups.setdefault(v, []).append(r["rungB"]["edge_median"])
        means = [sum(g) / len(g) for g in groups.values()]
        out[dim] = round(max(means) - min(means), 2) if len(means) > 1 else 0.0
    return out


def stage2_grid(records):
    """Local grid around the stage-1 leader on the top-3 dims by marginal
    range (+- the pre-registered step; non-positive values dropped), plus the
    governor threshold/timeout grid if any governor config ranked top-8.
    Deduped against stage-1 ids, capped at STAGE2_CAP."""
    ranked, _ = split_ranked(records)
    if not ranked:
        return [], {}
    leader = LawParams(**ranked[0]["params"])
    ranges = marginal_ranges(ranked)
    # top-3 dims by marginal range; governor has no +-step (its refinement is
    # the separate top-8 threshold/timeout rule below), so it contributes no
    # axis if selected.
    top3 = sorted(_DIMS, key=lambda d: -ranges[d])[:3]

    axes = []
    for dim in top3:
        if dim == "governor":
            continue
        if dim == "corner":
            st_, sa = DIM_STEPS["corner"]
            ct, ca = leader.corner_thresh, leader.corner_aim
            vals = [(ct - st_, ca - sa), (ct, ca), (ct + st_, ca + sa)]
            vals = [v for v in vals if v[0] > 0 and v[1] > 0]
        else:
            step = DIM_STEPS[dim]
            base = getattr(leader, dim)
            lo = 0.0 if dim == "carrot_lead" else None
            vals = []
            for v in (base - step, base, base + step):
                if lo is not None:
                    v = max(v, lo)
                if v > 0 or (dim == "carrot_lead" and v >= 0):
                    vals.append(v)
            vals = sorted(set(vals))
        axes.append((dim, vals))

    grid = []
    for combo in itertools.product(*(vals for _, vals in axes)):
        q = leader
        for (dim, _), v in zip(axes, combo):
            if dim == "corner":
                q = replace(q, corner_thresh=v[0], corner_aim=v[1])
            else:
                q = replace(q, **{dim: v})
        grid.append(q)

    govs_in_top8 = {LawParams(**r["params"]).governor
                    for r in ranked[:8]} - {"none"}
    for gv in sorted(govs_in_top8):
        for th in PREC_THRESH_GRID:
            for to in PREC_TIMEOUT_GRID:
                grid.append(replace(leader, governor=gv,
                                    prec_thresh=th, prec_timeout=to))

    have = {r["id"] for r in records}
    out, seen = [], set()
    for q in grid:
        cid = config_id(q)
        if cid in have or cid in seen:
            continue
        seen.add(cid)
        out.append(q)
    return out[:STAGE2_CAP], {"leader": config_id(leader), "ranges": ranges,
                              "dims": [d for d, _ in axes]}


# ── worker ───────────────────────────────────────────────────────────────────
_G = {}


def _init_worker(bsp, dump):
    from bsp_geom import Bsp
    world, graph = build_world_and_graph(bsp, dump)
    geom = Bsp.load(bsp)
    route_a = load_route_cfg("sng_shortcut2")
    route_rl = load_route_cfg("sng_to_rl")
    _G.update(
        world=world, graph=graph, teles=load_teleporters(bsp),
        route_a=route_a, goal_a=route_a["goal"],
        gap=route_rl["gap"],
        goal_b=graph.markers[RUNG_B["goal_marker"]].nav,
        floor=lambda x, y, z: geom.floor_z(x, y, z),
    )


def eval_config(pdict):
    p = LawParams(**pdict)
    cid = config_id(p)
    t0 = time.time()
    rung_a_runs, e207, e206 = [], [], []
    for seed in SEEDS:
        res = run_attempt(_G["world"], _G["graph"], seed, config="c5",
                          budget_s=RUNG_A["budget_s"], spawn=RUNG_A["spawn"],
                          goal_marker=RUNG_A["goal_marker"],
                          goal_pos=_G["goal_a"], teleporters=_G["teles"],
                          floor_fn=_G["floor"], params=p)
        a = analyze_attempt(res.rows, _G["route_a"])
        rung_a_runs.append({"seed": seed, "reached": a["reached"],
                            "arrival_tws": a["arrival_tws"],
                            "arrival_t": a["arrival_t"]})
        c7, c6 = corner_stats(res.rows, _G["route_a"])
        e207 += c7
        e206 += c6
    edge_vals, arrivals = [], []
    for seed in SEEDS:
        res = run_attempt(_G["world"], _G["graph"], seed, config="c5",
                          budget_s=RUNG_B["budget_s"], spawn=RUNG_B["spawn"],
                          goal_marker=RUNG_B["goal_marker"],
                          goal_pos=_G["goal_b"], teleporters=_G["teles"],
                          params=p)
        edge_vals.append(edge_objective(res.rows, _G["gap"]))
        arrivals.append(any(r["dist_goal"] < ARRIVE_R for r in res.rows))
    return aggregate(cid, p, rung_a_runs, e207, e206, edge_vals, arrivals,
                     elapsed=round(time.time() - t0, 1))


# ── jsonl I/O ────────────────────────────────────────────────────────────────
def load_jsonl(path):
    if not Path(path).exists():
        return []
    return [json.loads(ln) for ln in Path(path).read_text().splitlines() if ln.strip()]


def load_all(outdir):
    return (load_jsonl(Path(outdir) / "stage1.jsonl"),
            load_jsonl(Path(outdir) / "stage2.jsonl"))


# ── report ───────────────────────────────────────────────────────────────────
def fmt_row(rank, r):
    p = LawParams(**r["params"])
    a, b = r["rungA"], r["rungB"]
    conv = "—" if a["corner_conv"] is None else f"{a['corner_conv']:.2f}"
    med = "—" if b["edge_median"] is None else f"{b['edge_median']:.1f}"
    mx = "—" if b["edge_max"] is None else f"{b['edge_max']:.1f}"
    return (f"| {rank} | `{r['id']}` | {med} | {b['edge_n']}/30 | {mx} | "
            f"{a['reach']}/30 | {conv} ({a['corner_exits_207']}) | "
            f"{b['arrivals']}/30 | {p.pass_r:g}/{p.numerator:g}/{p.swing:g}/"
            f"{p.turn_thresh:g}/{p.corner_thresh:g}-{p.corner_aim:g}/"
            f"{p.governor}/{p.carrot_lead:g} |")


TABLE_HEADER = (
    "| rank | config | edge_med | edge_n | edge_max | reachA | conv207 (n) "
    "| arrB | pass_r/num/swing/turn/corner/gov/lead |\n"
    "|---|---|---|---|---|---|---|---|---|")


def build_report(outdir):
    s1, s2 = load_all(outdir)
    records = s1 + s2
    ranked, unranked = split_ranked(records)
    cands = pick_candidates(ranked)
    best_overall = None
    for r in records:
        mx = r["rungB"]["edge_max"]
        if mx is not None and (best_overall is None
                               or mx > best_overall["rungB"]["edge_max"]):
            best_overall = r
    reached = (best_overall is not None
               and best_overall["rungB"]["edge_max"] >= EDGE_TARGET)
    ranked_reached = any(r["rungB"]["edge_max"] is not None
                         and r["rungB"]["edge_max"] >= EDGE_TARGET
                         for r in ranked)
    live = next((r for r in records
                 if LawParams(**r["params"]) == LawParams()), None)
    out = {
        "n_configs": len(records), "n_stage1": len(s1), "n_stage2": len(s2),
        "n_ranked": len(ranked), "n_unranked": len(unranked),
        "edge_target": EDGE_TARGET,
        "target_reached_any": bool(reached),
        "target_reached_ranked": bool(ranked_reached),
        "best_overall": {"id": best_overall["id"],
                         "edge_max": best_overall["rungB"]["edge_max"],
                         "edge_median": best_overall["rungB"]["edge_median"],
                         "ranked": eligible(best_overall)}
        if best_overall else None,
        "live_point": {"id": live["id"], "reach": live["rungA"]["reach"],
                       "tws_median": live["rungA"]["tws_median"],
                       "edge_median": live["rungB"]["edge_median"],
                       "edge_n": live["rungB"]["edge_n"]} if live else None,
        "marginals": marginal_ranges(ranked) if ranked else {},
        "candidates": [c["id"] for c in cands] if cands else None,
        "ranked": [r["id"] for r in ranked],
    }
    return records, ranked, unranked, cands, out


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["sweep", "report", "grid"])
    ap.add_argument("--stage", type=int, default=1, choices=[1, 2])
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--bsp", default=DEFAULT_BSP)
    ap.add_argument("--dump", default=None)
    ap.add_argument("--limit", type=int, default=None,
                    help="run only the first N pending configs (smoke)")
    args = ap.parse_args()
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

    if args.mode == "grid":
        grid = stage1_grid()
        print(f"stage-1 grid: {len(grid)} configs")
        live = LawParams()
        print("live point included:",
              any(g == live for g in grid), config_id(live))
        return

    if args.mode == "report":
        records, ranked, unranked, cands, summary = build_report(outdir)
        print(json.dumps(summary, indent=2))
        (outdir / "ranked.json").write_text(json.dumps(summary, indent=1))
        lines = [TABLE_HEADER]
        for i, r in enumerate(ranked, 1):
            lines.append(fmt_row(i, r))
        (outdir / "ranked.md").write_text(
            "\n".join(lines) + f"\n\nunranked: {len(unranked)} configs "
            f"(reach < {REACH_FLOOR}/30 or edge_n < {EDGE_N_FLOOR}/30)\n")
        print(f"wrote {outdir / 'ranked.json'} and ranked.md "
              f"({len(ranked)} ranked, {len(unranked)} unranked)")
        return

    # sweep
    s1, s2 = load_all(outdir)
    if args.stage == 1:
        grid = stage1_grid()
        done = {r["id"] for r in s1}
        path = outdir / "stage1.jsonl"
    else:
        if not s1:
            raise SystemExit("stage 2 requires stage1.jsonl")
        grid, meta = stage2_grid(s1)
        (outdir / "stage2-plan.json").write_text(json.dumps(
            {"n": len(grid), **meta, "ids": [config_id(p) for p in grid]},
            indent=1))
        print(f"stage-2 plan: {len(grid)} configs around {meta.get('leader')} "
              f"on dims {meta.get('dims')} (marginals {meta.get('ranges')})")
        done = {r["id"] for r in s2}
        path = outdir / "stage2.jsonl"

    pending = [p for p in grid if config_id(p) not in done]
    if args.limit:
        pending = pending[:args.limit]
    print(f"stage {args.stage}: {len(grid)} configs, {len(done)} done, "
          f"{len(pending)} to run, workers={args.workers}", flush=True)
    if not pending:
        return

    t0 = time.time()
    with multiprocessing.Pool(args.workers, initializer=_init_worker,
                              initargs=(args.bsp, args.dump)) as pool:
        with open(path, "a", encoding="utf-8") as fh:
            for k, rec in enumerate(pool.imap_unordered(
                    eval_config, [asdict(p) for p in pending],
                    chunksize=1), 1):
                fh.write(json.dumps(rec) + "\n")
                fh.flush()
                el = time.time() - t0
                eta = el / k * (len(pending) - k)
                print(f"[{k}/{len(pending)}] {rec['id']} "
                      f"reach={rec['rungA']['reach']}/30 "
                      f"edge_n={rec['rungB']['edge_n']} "
                      f"edge_med={rec['rungB']['edge_median']} "
                      f"({el / 60:.1f} min, eta {eta / 60:.0f} min)",
                      flush=True)
    print(f"stage {args.stage} complete in {(time.time() - t0) / 60:.1f} min")


if __name__ == "__main__":
    main()
