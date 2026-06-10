#!/usr/bin/env python3
"""A2b #111: tail autopsy — patternize the >=526 lucky tries.

The A2 sweep (#74, PR #110) found the >=526 launch-edge objective is reached
only as ~1-seed-in-30 tail events (48/1986 configs, best single try 554.5)
while the best config MEDIAN ceilings at 470. USER DIRECTIVE: the metric and
the 526 target never change — analyze WHY the lucky tries succeed, then make
it reproducible (or prove it cannot be done).

Subcommands (in run order):

  inventory  — every (config, seed) pair with rung-B edge >= 526 from the raw
               sweep jsonl, plus the within-config control bands.
  trace      — re-run ALL 30 seeds of every lucky config with rich traces
               (mode23_sim.run_attempt(rich_trace=True), additive) and extract
               per-try features over the final-approach window (the straight
               from the marker-83 corner to the launch plane). Reproduction is
               asserted per try: the re-run edge value must equal the
               sweep-recorded value (the sim is seed-deterministic), and the
               local crossing-index finder must agree with
               route_metrics.edge_speed exactly.
  analyze    — band comparison (lucky / near / mid / deep) + the
               backwards-from-the-edge divergence scan: at which checkpoint do
               lucky tries separate from controls?

Metric semantics are IMPORTED from route_metrics — never re-implemented. The
crossing-INDEX finder here exists only because edge_speed returns a speed,
not a row index; it uses route_metrics' own constants and is cross-checked
against edge_speed on every traced try (hard assert).

Row shape: mode23_sim trace rows; rich keys (yaw/jump/msec/sign/law/vx/vy/vz)
are required by the feature extractor.
"""

from __future__ import annotations

import argparse
import json
import math
import multiprocessing
import statistics
import sys
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from mode23_sim import (  # noqa: E402
    LawParams, build_world_and_graph, load_route_cfg, load_teleporters,
)
from mode23_sweep import (  # noqa: E402
    ARRIVE_R, DEFAULT_BSP, EDGE_TARGET, RUNG_B, edge_objective, load_jsonl,
)
from route_metrics import (  # noqa: E402
    EDGE_CROSS_EPS, EDGE_CORRIDOR, EDGE_Z_WINDOW, TELEPORT_JUMP,
    _truncate_at_arrival, legit_segment,
)

REPO = SCRIPTS.parent
SWEEP_DIR = REPO / "artifacts" / "p3b-sweep"
DEFAULT_OUT = REPO / "artifacts" / "tail-autopsy"

# Control bands (within-config, on the sweep-recorded per-seed edge values).
BANDS = (("lucky", 526.0, math.inf), ("near", 490.0, 526.0),
         ("mid", 450.0, 490.0), ("deep", -math.inf, 450.0))

# Final-approach window, parameterized by BACKWARD xy arc length from the
# measured crossing (the plane's along-axis is not monotone over the route:
# the spawn already sits at along -240 and the route initially runs away from
# the plane, so along-checkpoints would alias the spawn area). The runway =
# the last ~1000 qu of path: westbound south walkway (~450 qu) + the 83/84
# corner + the northbound bridge (~500 qu).
BACKDISTS = (0.0, 100.0, 200.0, 300.0, 400.0, 500.0, 600.0, 700.0,
             800.0, 900.0, 1000.0, 1100.0, 1200.0)
WINDOW_BACKDIST = 1000.0   # ground-contact/jump features over the last 1000 qu


def band_of(v):
    if v is None:
        return "none"
    for name, lo, hi in BANDS:
        if lo <= v < hi:
            return name
    return "none"


# ── plane helpers (gap-parameterized, same convention as edge_speed) ─────────
def plane_axes(gap):
    ex, ey, ez = (float(v) for v in gap["edge"][:3])
    ux, uy = float(gap["land"][0]) - ex, float(gap["land"][1]) - ey
    n = math.hypot(ux, uy)
    return ex, ey, ez, ux / n, uy / n


def find_crossings(rows, gap):
    """Indices b of every QUALIFYING crossing row pair a->b, in row order —
    the same scan edge_speed performs (route_metrics constants, teleport
    exclusion, corridor + z gates). edge_speed(rows, gap) == rows[out[-1]]["vh"]
    whenever out is non-empty; callers assert exactly that."""
    ex, ey, ez, ux, uy = plane_axes(gap)

    def along(r):
        return (r["x"] - ex) * ux + (r["y"] - ey) * uy

    out = []
    for i, (a, b) in enumerate(zip(rows, rows[1:])):
        if along(a) >= -EDGE_CROSS_EPS or along(b) < -EDGE_CROSS_EPS:
            continue
        step = math.hypot(b["x"] - a["x"], b["y"] - a["y"]) + abs(b["z"] - a["z"])
        if step > TELEPORT_JUMP:
            continue
        cross = abs((b["y"] - ey) * ux - (b["x"] - ex) * uy)
        if cross > EDGE_CORRIDOR or abs(b["z"] - ez) > EDGE_Z_WINDOW:
            continue
        out.append(i + 1)
    return out


# ── feature extraction (pure; unit-tested) ───────────────────────────────────
def ground_episodes(rows, i0, i1):
    """Consecutive onground runs in rows[i0..i1] inclusive: entry/exit speeds
    (exit = first airborne row after the episode -> friction loss is
    vh_entry - vh_exit), duration, and position."""
    eps = []
    i = i0
    while i <= i1:
        if rows[i]["onground"]:
            j = i
            while j + 1 <= i1 and rows[j + 1]["onground"]:
                j += 1
            exit_vh = rows[j + 1]["vh"] if j + 1 < len(rows) else rows[j]["vh"]
            eps.append({
                "i": i, "n": j - i + 1,
                "t": rows[i]["t"], "dt": round(rows[j]["t"] - rows[i]["t"], 3),
                "vh_in": round(rows[i]["vh"], 1), "vh_out": round(exit_vh, 1),
                "loss": round(rows[i]["vh"] - exit_vh, 1),
                "x": round(rows[i]["x"], 1), "y": round(rows[i]["y"], 1),
                "z": round(rows[i]["z"], 1),
            })
            i = j + 1
        else:
            i += 1
    return eps


def backdist_checkpoints(rows, ci, targets=BACKDISTS):
    """Walk BACKWARD from the crossing row ci accumulating xy arc length;
    record the first row at/past each backward-distance target. Monotone by
    construction (unlike the plane's along-axis). None when the trace is
    shorter than the target (try started closer than that to the crossing)."""
    out = {}
    k = 0
    targets = sorted(targets)
    d = 0.0
    prev = rows[ci]
    for i in range(ci, -1, -1):
        r = rows[i]
        d += math.hypot(r["x"] - prev["x"], r["y"] - prev["y"])
        prev = r
        while k < len(targets) and d >= targets[k]:
            out[targets[k]] = {"vh": round(r["vh"], 1), "t": r["t"],
                               "onground": r["onground"], "i": i,
                               "x": round(r["x"], 1), "y": round(r["y"], 1),
                               "z": round(r["z"], 1)}
            k += 1
        if k >= len(targets):
            break
    # backdist 0 = the crossing row itself
    out.setdefault(0.0, {"vh": round(rows[ci]["vh"], 1), "t": rows[ci]["t"],
                         "onground": rows[ci]["onground"], "i": ci,
                         "x": round(rows[ci]["x"], 1),
                         "y": round(rows[ci]["y"], 1),
                         "z": round(rows[ci]["z"], 1)})
    for tgt in targets:
        out.setdefault(tgt, None)
    return out


def heading_of(row):
    return math.degrees(math.atan2(row["vy"], row["vx"]))


def signed_err(bearing, heading):
    d = bearing - heading
    while d > 180.0:
        d -= 360.0
    while d < -180.0:
        d += 360.0
    return d


def dedup_linked_seq(rows):
    seq = []
    for r in rows:
        lk = r.get("linked")
        if lk is None:
            continue
        if not seq or seq[-1] != lk:
            seq.append(lk)
    return seq


def extract_features(rows, events, gap, goal_pos, marker110_nav):
    """Per-try feature record over the truncated legit segment. Returns None
    when the try never crosses (edge None)."""
    seg = legit_segment(rows, ())
    seg = _truncate_at_arrival(seg, ARRIVE_R)
    crossings = find_crossings(seg, gap)
    if not crossings:
        return None
    ci = crossings[-1]
    edge = seg[ci]["vh"]

    cps = backdist_checkpoints(seg, ci)
    # window = the last WINDOW_BACKDIST qu of path before the crossing
    wcp = cps.get(WINDOW_BACKDIST)
    w0 = wcp["i"] if wcp is not None else 0

    eps = ground_episodes(seg, w0, ci)
    jumps = sum(int(seg[i].get("jump", 0)) for i in range(w0, ci + 1))

    # carrot handovers inside the window (events carry cmd-time t)
    t0, t1 = seg[w0]["t"], seg[ci]["t"]
    carrots = [e for e in events if e.get("event") == "carrot"
               and t0 <= e["t"] <= t1]

    b = seg[ci]
    bearing_110 = math.degrees(math.atan2(marker110_nav[1] - b["y"],
                                          marker110_nav[0] - b["x"]))
    head = heading_of(b)
    return {
        "edge": round(edge, 1),
        "t_cross": b["t"],
        "n_crossings": len(crossings),
        "window_t": round(t1 - t0, 2),
        "entry_vh": round(seg[w0]["vh"], 1),
        "entry_xy": (round(seg[w0]["x"], 1), round(seg[w0]["y"], 1)),
        "entry_z": round(seg[w0]["z"], 1),
        "backdist": {str(int(k)): v for k, v in cps.items()},
        "ground_eps": eps,
        "n_ground_eps": len(eps),
        "ground_frames": sum(e["n"] for e in eps),
        "friction_loss": round(sum(e["loss"] for e in eps), 1),
        "jumps": jumps,
        "cross_onground": b["onground"],
        "cross_z": round(b["z"], 1),
        "cross_heading": round(head, 1),
        "cross_err_110": round(signed_err(bearing_110, head), 1),
        "cross_sign": b.get("sign"),
        "carrots": [{"t": c["t"], "passed": c["passed"],
                     "new_linked": c["new_linked"]} for c in carrots],
        "path": dedup_linked_seq(seg),
        "arrived": bool(seg and seg[-1]["dist_goal"] < ARRIVE_R),
        "seg_rows": len(seg),
        "raw_rows": len(rows),
    }


# ── inventory ────────────────────────────────────────────────────────────────
def build_inventory(sweep_dir=SWEEP_DIR):
    recs = (load_jsonl(Path(sweep_dir) / "stage1.jsonl")
            + load_jsonl(Path(sweep_dir) / "stage2.jsonl"))
    if not recs:
        raise SystemExit(f"no sweep records in {sweep_dir}")
    inv = []
    for rec in recs:
        vals = rec["rungB"]["edge_values"]
        lucky = [(i + 1, v) for i, v in enumerate(vals)
                 if v is not None and v >= EDGE_TARGET]
        if not lucky:
            continue
        inv.append({
            "id": rec["id"], "params": rec["params"],
            "lucky": [{"seed": s, "edge": v} for s, v in lucky],
            "edge_values": vals,
            "bands": {b: sum(1 for v in vals if band_of(v) == b)
                      for b in ("lucky", "near", "mid", "deep", "none")},
        })
    return inv


# ── trace worker ─────────────────────────────────────────────────────────────
_G = {}


def _init_worker(bsp, dump):
    from bsp_geom import Bsp
    from mode23_sim import run_attempt  # noqa: F401 (cached import)
    world, graph = build_world_and_graph(bsp, dump)
    route_rl = load_route_cfg("sng_to_rl")
    route_a = load_route_cfg("sng_shortcut2")
    geom = Bsp.load(bsp)
    _G.update(world=world, graph=graph, teles=load_teleporters(bsp),
              gap=route_rl["gap"],
              goal_b=graph.markers[RUNG_B["goal_marker"]].nav,
              m110=graph.markers[110].nav,
              route_a=route_a, goal_a=route_a["goal"],
              floor=lambda x, y, z: geom.floor_z(x, y, z))


def trace_one(job):
    """One (config, seed): rich re-run + reproduction assert + features."""
    from mode23_sim import run_attempt
    p = LawParams(**job["params"])
    res = run_attempt(_G["world"], _G["graph"], job["seed"], config="c5",
                      budget_s=RUNG_B["budget_s"], spawn=RUNG_B["spawn"],
                      goal_marker=RUNG_B["goal_marker"], goal_pos=_G["goal_b"],
                      teleporters=_G["teles"], params=p, rich_trace=True)
    edge = edge_objective(res.rows, _G["gap"])
    rec_v = job["recorded"]
    if rec_v is None:
        assert edge is None, f"{job['id']} seed {job['seed']}: " \
            f"recorded None, re-run {edge}"
    else:
        assert edge is not None and round(edge, 1) == rec_v, \
            f"{job['id']} seed {job['seed']}: recorded {rec_v}, re-run {edge}"
    feats = None
    if edge is not None:
        feats = extract_features(res.rows, res.events, _G["gap"],
                                 _G["goal_b"], _G["m110"])
        # the index finder must agree with the imported metric EXACTLY
        assert feats is not None and abs(feats["edge"] - round(edge, 1)) < 0.05, \
            f"{job['id']} seed {job['seed']}: finder {feats} vs metric {edge}"
    return {"id": job["id"], "seed": job["seed"], "band": band_of(rec_v),
            "edge": None if edge is None else round(edge, 1),
            "features": feats}


def run_trace(inv, outdir, bsp, dump, workers):
    jobs = []
    for cfg in inv:
        for seed0, v in enumerate(cfg["edge_values"], start=1):
            jobs.append({"id": cfg["id"], "params": cfg["params"],
                         "seed": seed0, "recorded": v})
    path = Path(outdir) / "features.jsonl"
    done = {(r["id"], r["seed"]) for r in load_jsonl(path)}
    pending = [j for j in jobs if (j["id"], j["seed"]) not in done]
    print(f"trace: {len(jobs)} tries, {len(done)} done, {len(pending)} to run, "
          f"workers={workers}", flush=True)
    if not pending:
        return
    t0 = time.time()
    with multiprocessing.Pool(workers, initializer=_init_worker,
                              initargs=(bsp, dump)) as pool:
        with open(path, "a", encoding="utf-8") as fh:
            for k, rec in enumerate(pool.imap_unordered(trace_one, pending,
                                                        chunksize=4), 1):
                fh.write(json.dumps(rec) + "\n")
                if k % 100 == 0 or k == len(pending):
                    fh.flush()
                    el = time.time() - t0
                    print(f"[{k}/{len(pending)}] {el:.0f}s", flush=True)


# ── analysis ─────────────────────────────────────────────────────────────────
def _med(vals):
    vals = [v for v in vals if v is not None]
    return round(statistics.median(vals), 1) if vals else None


def _q(vals, q):
    vals = sorted(v for v in vals if v is not None)
    if not vals:
        return None
    i = (len(vals) - 1) * q
    lo, hi = int(math.floor(i)), int(math.ceil(i))
    return round(vals[lo] + (vals[hi] - vals[lo]) * (i - lo), 1)


def band_table(tries, key_fn):
    out = {}
    for b in ("lucky", "near", "mid", "deep"):
        vals = [key_fn(t) for t in tries if t["band"] == b
                and t["features"] is not None]
        vals = [v for v in vals if v is not None]
        out[b] = {"n": len(vals), "median": _med(vals),
                  "p10": _q(vals, 0.10), "p90": _q(vals, 0.90)}
    return out


def analyze(outdir):
    tries = load_jsonl(Path(outdir) / "features.jsonl")
    if not tries:
        # Fail LOUDLY before writing anything: an empty/missing features
        # file (analyze before trace, interrupted trace, mistyped --out —
        # e.g. pointed at the committed evidence dir, which holds only the
        # summary copies) would otherwise overwrite band-summary.json with
        # all-zero tables. Same guard pattern as mode23_sweep report
        # (Codex P2 on PR #110, repeated on PR #112).
        raise SystemExit(
            f"no traced tries found in {Path(outdir) / 'features.jsonl'} "
            f"(run `tail_autopsy.py trace` first); refusing to write an "
            f"empty band summary")
    crossed = [t for t in tries if t["features"] is not None]
    print(f"{len(tries)} tries, {len(crossed)} crossed", flush=True)

    feats = {
        "edge": lambda t: t["features"]["edge"],
        "entry_vh": lambda t: t["features"]["entry_vh"],
        "window_t": lambda t: t["features"]["window_t"],
        "n_ground_eps": lambda t: t["features"]["n_ground_eps"],
        "ground_frames": lambda t: t["features"]["ground_frames"],
        "friction_loss": lambda t: t["features"]["friction_loss"],
        "jumps": lambda t: t["features"]["jumps"],
        "n_crossings": lambda t: t["features"]["n_crossings"],
        "t_cross": lambda t: t["features"]["t_cross"],
        "abs_cross_err_110": lambda t: abs(t["features"]["cross_err_110"]),
        "cross_z": lambda t: t["features"]["cross_z"],
    }
    for cp in BACKDISTS:
        key = str(int(cp))
        feats[f"vh@bd{key}"] = (
            lambda t, k=key: (t["features"]["backdist"].get(k) or {}).get("vh"))

    out = {name: band_table(tries, fn) for name, fn in feats.items()}
    summary_path = Path(outdir) / "band-summary.json"
    summary_path.write_text(json.dumps(out, indent=1))
    for name, tab in out.items():
        line = f"{name:18s}"
        for b in ("lucky", "near", "mid", "deep"):
            d = tab[b]
            line += f" | {b} n={d['n']:4d} med={d['median']} [{d['p10']},{d['p90']}]"
        print(line)
    print(f"wrote {summary_path}")
    return out


# ── patternization design grid (TRAINING seeds 1..30 only) ──────────────────
# Tuning happens HERE, on the same seeds the sweep used; the pre-registered
# fresh-seed test (31..60) never feeds back into the design.
DESIGN_SEEDS = tuple(range(1, 31))


def design_grid():
    """The FINAL design round (r7): refinement of the circle-jump launch
    around the round-6 optimum (cj400a40), crossing runway cvar families x
    launch_vh x launch_angle. The full design path (rounds 1-7: spin-up
    loops, delegation speed gate, jump floor, numerator cross, runway
    constants, circle-jump discovery, this refinement) is preserved in
    evidence design-grid-r{1..7}.json and narrated in tail-autopsy.md §4 —
    the committed code holds the LAST grid only; earlier grids are
    reproducible from their JSON params records. Winner -> PATTERNIZED."""
    bases = {
        "p130s12t35": dict(pass_r=130.0, numerator=5.0, swing=12.0,
                           turn_thresh=35.0, corner_thresh=45.0,
                           corner_aim=85.0),
        "p130s12t25": dict(pass_r=130.0, numerator=5.0, swing=12.0,
                           turn_thresh=25.0, corner_thresh=45.0,
                           corner_aim=85.0),
        "p100s12t35": dict(pass_r=100.0, numerator=5.0, swing=12.0,
                           turn_thresh=35.0, corner_thresh=45.0,
                           corner_aim=85.0),
        "p130s24t35": dict(pass_r=130.0, numerator=5.0, swing=24.0,
                           turn_thresh=35.0, corner_thresh=45.0,
                           corner_aim=85.0),
    }
    out = []
    for bn, b in bases.items():
        for lv in (390.0, 400.0, 410.0, 420.0):
            for la in (35.0, 38.0, 40.0, 42.0):
                out.append((f"{bn}_cj{lv:g}a{la:g}",
                            LawParams(**b, launch_vh=lv, launch_angle=la)))
    return out


def eval_design(args_):
    name, p, seeds = args_
    from mode23_sim import run_attempt
    vals, entries = [], []
    for seed in seeds:
        res = run_attempt(_G["world"], _G["graph"], seed, config="c5",
                          budget_s=RUNG_B["budget_s"], spawn=RUNG_B["spawn"],
                          goal_marker=RUNG_B["goal_marker"],
                          goal_pos=_G["goal_b"], teleporters=_G["teles"],
                          params=p, rich_trace=True)
        v = edge_objective(res.rows, _G["gap"])
        vals.append(None if v is None else round(v, 1))
        if v is not None:
            f = extract_features(res.rows, res.events, _G["gap"],
                                 _G["goal_b"], _G["m110"])
            cp = f["backdist"].get("1000") if f else None
            entries.append(cp["vh"] if cp else None)
    present = sorted(v for v in vals if v is not None)
    return {"name": name, "params": {k: v for k, v in p.__dict__.items()},
            "edge_values": vals, "edge_n": len(present),
            "edge_median": _med(present),
            "edge_max": present[-1] if present else None,
            "n_526": sum(1 for v in present if v >= EDGE_TARGET),
            "entry_vh_median": _med([e for e in entries if e is not None])}


# ── the patternized candidate + fresh-seed confirmation block ────────────────
# Selected on TRAINING seeds 1..30 (design rounds 1-7, design-grid*.json):
# cvar base = the sweep's p100_n5_s12_t35_c45-85 family + the circle-jump
# launch (launch_vh 400, launch_angle 42). Training numbers: 13/30 seeds
# >= 526, median 528.0, edge_n 26/30, max 558.3.
PATTERNIZED = LawParams(pass_r=100.0, numerator=5.0, swing=12.0,
                        turn_thresh=35.0, corner_thresh=45.0, corner_aim=85.0,
                        launch_vh=400.0, launch_angle=42.0)
PATTERNIZED_BASE = LawParams(pass_r=100.0, numerator=5.0, swing=12.0,
                             turn_thresh=35.0, corner_thresh=45.0,
                             corner_aim=85.0)
FRESH_SEEDS = tuple(range(31, 61))


def eval_rung_a(args_):
    name, pd, seed = args_
    from mode23_sim import analyze_attempt, run_attempt
    p = LawParams(**pd)
    res = run_attempt(_G["world"], _G["graph"], seed, config="c5",
                      budget_s=48.1, spawn=(385.5, 614.25, 56.0),
                      goal_marker=191, goal_pos=_G["goal_a"],
                      teleporters=_G["teles"], floor_fn=_G["floor"], params=p)
    a = analyze_attempt(res.rows, _G["route_a"])
    return name, seed, a["reached"], a["arrival_tws"]


def eval_rung_b_seed(args_):
    name, pd, seed = args_
    from mode23_sim import run_attempt
    p = LawParams(**pd)
    res = run_attempt(_G["world"], _G["graph"], seed, config="c5",
                      budget_s=RUNG_B["budget_s"], spawn=RUNG_B["spawn"],
                      goal_marker=RUNG_B["goal_marker"], goal_pos=_G["goal_b"],
                      teleporters=_G["teles"], params=p)
    v = edge_objective(res.rows, _G["gap"])
    return name, seed, None if v is None else round(v, 1)


def run_fresh(outdir, bsp, dump, workers, seeds=FRESH_SEEDS):
    """The PRE-REGISTERED confirmation block: rung B + rung A, patternized
    vs base, on the fresh seed set. ALL runs are reported (no selection)."""
    variants = {"patternized": PATTERNIZED, "base": PATTERNIZED_BASE}
    jobs_b = [(n, p.__dict__, s) for n, p in variants.items() for s in seeds]
    jobs_a = [(n, p.__dict__, s) for n, p in variants.items() for s in seeds]
    with multiprocessing.Pool(workers, initializer=_init_worker,
                              initargs=(bsp, dump)) as pool:
        res_b = pool.map(eval_rung_b_seed, jobs_b)
        res_a = pool.map(eval_rung_a, jobs_a)
    out = {n: {"rungB": {}, "rungA": {}} for n in variants}
    for name, seed, v in res_b:
        out[name]["rungB"][seed] = v
    for name, seed, reached, tws in res_a:
        out[name]["rungA"][seed] = {"reached": reached, "tws": tws}
    report = {"seeds": list(seeds)}
    for name in variants:
        bvals = [out[name]["rungB"][s] for s in seeds]
        present = sorted(v for v in bvals if v is not None)
        n526 = sum(1 for v in present if v >= EDGE_TARGET)
        reach = sum(1 for s in seeds if out[name]["rungA"][s]["reached"])
        tws = sorted(d["tws"] for d in out[name]["rungA"].values()
                     if d["tws"] is not None)
        report[name] = {
            "edge_values": bvals, "edge_n": len(present),
            "edge_median": _med(present),
            "edge_max": present[-1] if present else None,
            "n_526": n526,
            "rungA_reach": reach, "rungA_tws_median": _med(tws),
        }
    path = Path(outdir) / "fresh-seed-results.json"
    path.write_text(json.dumps(report, indent=1))
    print(json.dumps({k: v for k, v in report.items() if k != "seeds"},
                     indent=1))
    print(f"wrote {path}")
    return report


def run_design(outdir, bsp, dump, workers, seeds=DESIGN_SEEDS):
    grid = design_grid()
    print(f"design grid: {len(grid)} configs x {len(seeds)} TRAINING seeds "
          f"({seeds[0]}..{seeds[-1]})", flush=True)
    with multiprocessing.Pool(workers, initializer=_init_worker,
                              initargs=(bsp, dump)) as pool:
        recs = pool.map(eval_design, [(n, p, seeds) for n, p in grid])
    path = Path(outdir) / "design-grid.json"
    path.write_text(json.dumps(recs, indent=1))
    for r in sorted(recs, key=lambda r: (-(r["n_526"]),
                                         -(r["edge_median"] or 0))):
        print(f"{r['name']:22s} n526={r['n_526']:2d} edge_n={r['edge_n']:2d}/"
              f"{len(seeds)} med={r['edge_median']} max={r['edge_max']} "
              f"entry={r['entry_vh_median']}")
    print(f"wrote {path}")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["inventory", "trace", "analyze",
                                     "design", "rung-a", "fresh"])
    ap.add_argument("--seeds", default=None,
                    help="seed range lo..hi (fresh/rung-a; default per mode)")
    ap.add_argument("--sweep-dir", default=str(SWEEP_DIR))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--bsp", default=DEFAULT_BSP)
    ap.add_argument("--dump", default=None)
    ap.add_argument("--workers", type=int, default=12)
    args = ap.parse_args()
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

    if args.mode == "inventory":
        inv = build_inventory(args.sweep_dir)
        n_lucky = sum(len(c["lucky"]) for c in inv)
        (outdir / "inventory.json").write_text(json.dumps(inv, indent=1))
        print(f"{len(inv)} configs, {n_lucky} lucky (config,seed) pairs "
              f"-> {outdir / 'inventory.json'}")
        return

    if args.mode == "trace":
        inv = json.loads((outdir / "inventory.json").read_text())
        run_trace(inv, outdir, args.bsp, args.dump, args.workers)
        return

    if args.mode == "design":
        run_design(outdir, args.bsp, args.dump, args.workers)
        return

    if args.mode in ("rung-a", "fresh"):
        if args.seeds:
            lo, hi = args.seeds.split("..")
            seeds = tuple(range(int(lo), int(hi) + 1))
        else:
            seeds = DESIGN_SEEDS if args.mode == "rung-a" else FRESH_SEEDS
        if args.mode == "fresh":
            run_fresh(outdir, args.bsp, args.dump, args.workers, seeds)
            return
        # rung-a: the candidate + base on the given seeds (training check)
        variants = {"patternized": PATTERNIZED, "base": PATTERNIZED_BASE}
        jobs = [(n, p.__dict__, s) for n, p in variants.items()
                for s in seeds]
        with multiprocessing.Pool(args.workers, initializer=_init_worker,
                                  initargs=(args.bsp, args.dump)) as pool:
            res = pool.map(eval_rung_a, jobs)
        agg = {}
        for name, seed, reached, tws in res:
            d = agg.setdefault(name, {"reach": 0, "tws": []})
            d["reach"] += int(reached)
            if tws is not None:
                d["tws"].append(tws)
        for name, d in agg.items():
            print(f"{name}: rungA reach {d['reach']}/{len(seeds)}, "
                  f"tws median {_med(sorted(d['tws']))}")
        return

    analyze(outdir)


if __name__ == "__main__":
    main()
