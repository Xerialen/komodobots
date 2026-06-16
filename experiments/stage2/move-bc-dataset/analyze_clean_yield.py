#!/usr/bin/env python3
"""Clean-segment yield improvement analysis for the MOVE BC pool dataset.

Re-derives per-frame replay frames (with reference_source flags) and re-runs the
validated pmove_sim, then compares:

  BASELINE  -- fixed 77-frame windows, a window is "clean" only if its MAX
               per-frame error <= 4 qu (the build_move_bc_pool.py method).

  IMPROVED  -- per-FRAME clean mask: a frame is clean if its replay error <= 4 qu
               (under teleport+periodic reanchoring), then maximal runs of
               consecutive clean frames are cut at discontinuity boundaries
               (teleport/respawn, large-dt). Runs shorter than MIN_RUN are
               dropped (too short to teach a 1s movement phase). This recovers
               clean frames trapped inside a window that one contaminated frame
               failed.

Also classifies every *contaminated* (err>4qu) frame into a contamination class
(Task 3) and tags whether the failing frame's reference state was interpolated
(Task 1, interpolation-inflation hypothesis).

Pure stdlib. Runs under WSL2 against the Windows repo + BSP and WSL demo corpus.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed

REPO_ROOT = Path(__file__).resolve().parents[3]
for _p in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pmove_sim  # noqa: E402

SEGMENT = 77            # same 1s window as the baseline build
DIVERGE_THRESH = 4.0    # qu, same acceptance tolerance
MIN_RUN = 24            # min consecutive-clean frames to keep a sub-segment
                        # (~1/3 s; shorter runs can't teach a movement phase)

_WORLD = None


def _init_worker(bsp_path):
    global _WORLD
    sys.setrecursionlimit(20000)
    _WORLD = pmove_sim.WorldModel.load(bsp_path)


def _pctl(vals, q):
    if not vals:
        return None
    s = sorted(vals)
    return s[min(len(s) - 1, int(q * (len(s) - 1)))]


def _classify_contamination(rows, frames, tele_set, k):
    """Classify why frame k (0-based replay row index, err>thresh) diverged.

    Priority order (most-specific first):
      teleport     -- within 2 frames of a detected teleport/respawn reanchor
      submodel     -- frame is grounded (onground) but the world trace under the
                      sim leaves it airborne / large vertical error: rode a
                      plat/lift (submodel) the sim can't collide
      collision    -- large horizontal error while grounded or air, no vertical
                      signature: most consistent with a player-vs-player block
      drift        -- residual (small physics drift that still crossed 4qu)

    (interpolation-inflation is assessed at the DEMO level via paired_coverage,
    not per-frame: the shard does not carry the per-frame reference_source flag.)
    """
    # teleport proximity
    for d in (-2, -1, 0, 1, 2):
        if (k + d) in tele_set:
            return "teleport"
    fr = frames[k + 1] if k + 1 < len(frames) else frames[k]
    r = rows[k]
    ev = r["err_v"]
    eh = r["err_h"]
    rec_ground = bool(fr.get("onground"))
    # submodel/lift: strong vertical error, especially when recorded onground but
    # the worldmodel sim cannot find the (submodel) floor.
    if ev >= 8.0 and ev >= 0.6 * r["err"]:
        return "submodel"
    if rec_ground and ev >= 4.0:
        return "submodel"
    if eh >= 8.0:
        return "collision"
    return "drift"


def _load_shard(path):
    """Load a per-demo NDJSON shard into replay-ready frames.

    Shard row keys: demo,map,frame,msec,o,v,a,m,buttons,onground,pm_code.
    This reuses the ALREADY-BUILT BC labels (origin/velocity/angles/move/
    buttons + onground/pm_code) so we skip the expensive build_replay_frames
    re-extraction (~124s on a 212k-frame demo; the replay itself is ~12s).
    """
    frames = []
    with open(path, "r", encoding="utf-8") as fh:
        for ln in fh:
            ln = ln.strip()
            if not ln:
                continue
            r = json.loads(ln)
            frames.append({
                "msec": r["msec"], "origin": r["o"], "velocity": r["v"],
                "angles": r["a"], "move": r["m"], "buttons": r["buttons"],
                "onground": r.get("onground"), "pm_code": r.get("pm_code"),
                "map_level": r.get("map"),
            })
    return frames


def process_one(args):
    demo_path, want_classify, shard_dir, cov = args
    demo = Path(demo_path)
    t0 = time.time()
    shard = Path(shard_dir) / (demo.stem + ".ndjson")
    if not shard.exists():
        return {"demo": demo.name, "ok": False, "error": f"no shard: {shard.name}"}
    try:
        frames = _load_shard(shard)
    except Exception as e:  # noqa: BLE001
        return {"demo": demo.name, "ok": False, "error": f"load:{type(e).__name__}: {e}"}
    if not frames or len(frames) < 3:
        return {"demo": demo.name, "ok": False, "error": "no frames"}
    meta = {"map_level": frames[0].get("map_level"), "paired_coverage": cov}

    sim_frames = [
        {"msec": f["msec"], "origin": f["origin"], "velocity": f["velocity"],
         "angles": f["angles"], "move": f["move"], "buttons": f["buttons"]}
        for f in frames
    ]
    tele = pmove_sim.detect_teleports(sim_frames)
    tele_set = set(tele)
    try:
        summary, rows = pmove_sim.replay(
            _WORLD, sim_frames,
            reanchor_at=tele, reanchor_every=SEGMENT,
            diverge_thresh=DIVERGE_THRESH,
        )
    except Exception as e:  # noqa: BLE001
        return {"demo": demo.name, "ok": False, "error": f"replay:{type(e).__name__}: {e}"}

    n = len(rows)  # == frames_simulated == len(frames)-1

    # ---- BASELINE: fixed 77-frame windows, max-err vote ----
    seg_max = []
    cur = 0.0
    for i, r in enumerate(rows):
        if i > 0 and (i % SEGMENT == 0):
            seg_max.append(cur); cur = 0.0
        if not r["teleport_reanchor"]:
            cur = max(cur, r["err"])
    seg_max.append(cur)
    base_clean_segs = sum(1 for m in seg_max if m <= DIVERGE_THRESH)
    base_clean_frames = base_clean_segs * SEGMENT

    # ---- IMPROVED: per-frame clean mask + boundary-aware maximal runs ----
    # frame i is clean if replay err<=thresh. Reanchor rows themselves are NOT
    # counted as boundaries here except teleports (periodic reanchor is just to
    # bound drift, it does not mark a discontinuity).
    clean_flag = [False] * n
    for i, r in enumerate(rows):
        if r["err"] <= DIVERGE_THRESH:
            clean_flag[i] = True
    # boundaries that force a run break (teleport/respawn)
    boundary = set()
    for k in tele:
        boundary.add(k)
    # build maximal runs of consecutive clean frames, broken at boundaries
    runs = []
    i = 0
    while i < n:
        if not clean_flag[i] or i in boundary:
            i += 1
            continue
        j = i
        while j < n and clean_flag[j] and (j == i or j not in boundary):
            j += 1
        runs.append((i, j))  # [i, j)
        i = j
    kept_runs = [(a, b) for (a, b) in runs if (b - a) >= MIN_RUN]
    imp_clean_frames = sum(b - a for (a, b) in kept_runs)
    imp_total_clean_frames_all = sum(1 for c in clean_flag if c)

    out = {
        "demo": demo.name, "ok": True,
        "map_level": meta.get("map_level"),
        "paired_coverage": meta.get("paired_coverage"),
        "frames": n,
        "teleports": len(tele),
        # baseline
        "base_segments": len(seg_max),
        "base_clean_segments": base_clean_segs,
        "base_clean_frames": base_clean_frames,
        # improved
        "imp_clean_frames_raw": imp_total_clean_frames_all,
        "imp_clean_frames": imp_clean_frames,
        "imp_runs": len(kept_runs),
        "seg_max_err_p50": round(_pctl(seg_max, 0.5), 3),
        "build_secs": round(time.time() - t0, 2),
    }

    if want_classify:
        cls = {"teleport": 0, "submodel": 0,
               "collision": 0, "drift": 0}
        dirty = 0
        for k, r in enumerate(rows):
            if r["teleport_reanchor"]:
                continue
            if r["err"] <= DIVERGE_THRESH:
                continue
            dirty += 1
            cls[_classify_contamination(rows, frames, tele_set, k)] += 1
        out["contam_frames"] = dirty
        out["contam_class"] = cls
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", type=Path,
                    default=REPO_ROOT / "experiments/stage2/move-bc-dataset/manifest.json")
    ap.add_argument("--demo-list", type=Path, required=True,
                    help="TSV player<TAB>abspath (same as the build list)")
    ap.add_argument("--bsp", default="/mnt/c/nQuake/qw/maps/dm3.bsp")
    ap.add_argument("--shard-dir", type=Path, required=True,
                    help="dir of per-demo NDJSON shards (WSL ~/move_bc_shards)")
    ap.add_argument("--workers", type=int, default=os.cpu_count())
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--min-coverage", type=float, default=0.0,
                    help="only analyze demos with paired_coverage >= this")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--classify", action="store_true",
                    help="also classify contamination frames (slower output, same sim cost)")
    args = ap.parse_args(argv)

    man = json.loads(args.manifest.read_text())
    # coverage by demo name from the manifest (authoritative dm3 flag too)
    cov_by_name = {d["demo"]: d.get("paired_coverage", 0.0)
                   for d in man["demos"] if d.get("is_dm3")}

    demos = []
    for ln in args.demo_list.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        parts = ln.split("\t")
        path = parts[-1].strip()
        name = Path(path).name
        if name not in cov_by_name:        # not a dm3 pool demo
            continue
        if cov_by_name[name] < args.min_coverage:
            continue
        demos.append(path)
    if args.limit:
        demos = demos[: args.limit]

    print(f"clean-yield analysis: {len(demos)} demos "
          f"(min_cov={args.min_coverage}), {args.workers} workers", flush=True)
    t0 = time.time()
    rows = []
    with ProcessPoolExecutor(max_workers=args.workers,
                             initializer=_init_worker,
                             initargs=(args.bsp,)) as ex:
        futs = {ex.submit(process_one,
                          (p, args.classify, str(args.shard_dir),
                           cov_by_name[Path(p).name])): p for p in demos}
        for fut in as_completed(futs):
            r = fut.result()
            rows.append(r)
            done = len(rows)
            if done % 10 == 0 or done == len(demos):
                el = time.time() - t0
                print(f"  {done}/{len(demos)} ({el:.0f}s, {el/max(done,1):.2f}s/demo)",
                      flush=True)

    ok = [r for r in rows if r.get("ok")]
    tot_frames = sum(r["frames"] for r in ok)
    base_cf = sum(r["base_clean_frames"] for r in ok)
    imp_cf = sum(r["imp_clean_frames"] for r in ok)
    imp_raw = sum(r["imp_clean_frames_raw"] for r in ok)
    agg = {
        "demos_analyzed": len(ok),
        "demos_failed": len(rows) - len(ok),
        "min_coverage": args.min_coverage,
        "total_frames": tot_frames,
        "baseline_clean_frames": base_cf,
        "baseline_clean_frac": round(base_cf / max(tot_frames, 1), 4),
        "improved_clean_frames": imp_cf,
        "improved_clean_frac": round(imp_cf / max(tot_frames, 1), 4),
        "improved_clean_frames_raw_mask": imp_raw,
        "improved_over_baseline_ratio": round(imp_cf / max(base_cf, 1), 4),
        "min_run_frames": MIN_RUN,
        "segment_frames": SEGMENT,
        "diverge_thresh_qu": DIVERGE_THRESH,
        "wall_clock_secs": round(time.time() - t0, 1),
    }
    if args.classify:
        cc = {"teleport": 0, "submodel": 0, "collision": 0, "drift": 0}
        tot_contam = 0
        for r in ok:
            if "contam_class" not in r:
                continue
            tot_contam += r.get("contam_frames", 0)
            for k, v in r["contam_class"].items():
                cc[k] += v
        agg["contam_total_frames"] = tot_contam
        agg["contam_class_frames"] = cc
        agg["contam_class_frac"] = {k: round(v / max(tot_contam, 1), 4)
                                    for k, v in cc.items()}

    out = {"summary": agg, "demos": sorted(rows, key=lambda r: -r.get("frames", 0))}
    args.out.write_text(json.dumps(out, indent=1))
    print("\n=== DONE ===")
    print(json.dumps(agg, indent=1))


if __name__ == "__main__":
    sys.setrecursionlimit(20000)
    main()
