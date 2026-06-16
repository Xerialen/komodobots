#!/usr/bin/env python3
"""Stage-2 MOVE-BC dataset builder (docs/12 Stage 2, §5).

Reads the per-demo NDJSON shards (state=(o,v,a,onground,pm_code),
action=(m=[fwd,side,up],buttons)), re-derives the SAME per-frame clean mask the
clean-segment-index.json was built from (analyze_clean_yield.py: frame i clean
iff pmove_sim replay err<=4qu under teleport + every-77 reanchor; maximal runs
broken at teleport boundaries; runs < 24 frames dropped), and emits a packed
.npz of MAP-AGNOSTIC, VELOCITY-RELATIVE input FEATURES + discrete MOVE action
labels, tagged with a demo index (for demo-level train/val split) and quality
tier (A/B/C).

FEATURES (state-only -- never derived from the action being predicted, so the
policy cannot cheat). Since T0.4 these are computed by the SHARED world-view
module scripts/move_world_view.state_features (the single source of truth used
both offline here and by the live sidecar, so the world-view is built the SAME
way; see docs/18 wall #2). The 6 features it returns, in order:
  hspeed/320          horizontal speed, maxspeed-normalised
  vz/320              vertical velocity
  lvm_sin, lvm_cos    look-lead = signed angle(view-yaw - velocity-heading),
                      the air-law 'lvm' control axis, as sin/cos (continuous,
                      wrap-safe). When |v_h|~0 the heading is undefined -> 0.
  moving              1 if |v_h| >= 1 else 0 (heading-valid flag)
  pitch/90            view pitch (small but lets the net know up/down look)
This is exactly the *state* side of fit_air_law.frame_quantities; the action
side (wishdir-vs-velocity 'rotation') is the LABEL space, not an input.

NOTE on `onground`/`pm_code`: the .qwd POV svc_playerinfo recovery does NOT
carry server-side ground/pmove flags -- every shard row has onground=false,
pm_code=0 (verified across the corpus). So onground is NOT used as a feature
(it is constant and uninformative). The closed-loop gate and the air-law prior
both run through pmove_sim, which derives the true onground from dm3 geometry
each tick, so ground state is recovered there, not from the label stream.

ACTION (MLMove-style discrete distribution). The .qwd usercmd carries
forward/side/up move bytes + buttons. We map the continuous move to a small
discrete vocabulary and predict one class per head:
  fwd_cls   in {-, 0, +}             (back / none / forward)
  side_cls  in {-, 0, +}             (left / none / right strafe)
  jump_cls  in {0, 1}               (BUTTON_JUMP)
A frame's (fwd,side) sign is the human's wishdir basis; magnitude is replayed at
the canonical full deflection (the air-law gain is dominated by DIRECTION, not
the 320-vs-400 magnitude -- both saturate wishspeed). up/attack are not part of
the MOVE micro action (jump is, via buttons); attack/aim are AIM's job (Stage 3,
deferred -- see report). For closed-loop replay the human view-yaw is fed back
(view angle = AIM, deferred); MOVE predicts fwd/side/jump conditioned on state
incl. the current view.

Pure-stdlib + numpy. Heavy compute in WSL2.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
for _p in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pmove_sim  # noqa: E402
# Shared world-view module is the SINGLE SOURCE OF TRUTH for the MoveMLP feature
# vector (bot-program T0.4). The features below are computed by importing it, not
# inline, so the offline dataset and the live sidecar (T0.6) build the world-view
# the SAME way (docs/18 wall #2 "one world-view"; T0.5 golden-vector parity).
import move_world_view  # noqa: E402
from move_world_view import state_features  # noqa: E402

SEGMENT = 77
DIVERGE_THRESH = 4.0
MIN_RUN = 24

# canonical full-deflection move magnitude used when replaying a sign class
MOVE_MAG = 320.0

_WORLD = None


def _init_worker(bsp_path):
    global _WORLD
    sys.setrecursionlimit(20000)
    _WORLD = pmove_sim.WorldModel.load(bsp_path)


# Re-exported from the shared world-view module (canonical definition).
wrap180 = move_world_view.wrap180


def _load_shard(path):
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
            })
    return frames


def _clean_mask(frames):
    """Reproduce analyze_clean_yield.py improved per-frame mask -> kept runs."""
    sim_frames = [
        {"msec": f["msec"], "origin": f["origin"], "velocity": f["velocity"],
         "angles": f["angles"], "move": f["move"], "buttons": f["buttons"]}
        for f in frames
    ]
    tele = pmove_sim.detect_teleports(sim_frames)
    _summary, rows = pmove_sim.replay(
        _WORLD, sim_frames, reanchor_at=tele, reanchor_every=SEGMENT,
        diverge_thresh=DIVERGE_THRESH,
    )
    n = len(rows)
    clean = [r["err"] <= DIVERGE_THRESH for r in rows]
    boundary = set(tele)
    runs = []
    i = 0
    while i < n:
        if not clean[i] or i in boundary:
            i += 1
            continue
        j = i
        while j < n and clean[j] and (j == i or j not in boundary):
            j += 1
        runs.append((i, j))
        i = j
    kept = [(a, b) for (a, b) in runs if (b - a) >= MIN_RUN]
    return kept, n


def _features_and_labels(frames, runs):
    """For each kept clean frame index i (replay row i == state before cmd i,
    i.e. frames[i] is the state, frames[i]['move'/'buttons'] is the action),
    build the state feature vector and the discrete action label."""
    feats = []
    labels = []   # (fwd_cls, side_cls, jump_cls) each as small int
    idxs = []
    for (a, b) in runs:
        for i in range(a, b):
            f = frames[i]
            vx, vy, vz = f["velocity"]
            yaw = f["angles"][1]
            pitch = f["angles"][0]
            # SINGLE SOURCE OF TRUTH (T0.4): the world-view feature vector is
            # computed by the shared module, not inline, so offline and live
            # build it identically. state_features returns FEATURE_NAMES order:
            # (hspeed/320, vz/320, lvm_sin, lvm_cos, moving, pitch/90).
            feats.append(state_features(vx, vy, vz, yaw, pitch))
            fwd, side, _up = f["move"]
            buttons = int(f["buttons"])
            fwd_cls = 1 if fwd > 0 else (-1 if fwd < 0 else 0)
            side_cls = 1 if side > 0 else (-1 if side < 0 else 0)
            jump_cls = 1 if (buttons & pmove_sim.BUTTON_JUMP) else 0
            labels.append((fwd_cls + 1, side_cls + 1, jump_cls))  # shift to 0..2
            idxs.append(i)
    return feats, labels, idxs


def process_one(args):
    shard_path, demo_idx, tier = args
    try:
        frames = _load_shard(shard_path)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "shard": Path(shard_path).name, "err": str(e)}
    if len(frames) < 3:
        return {"ok": False, "shard": Path(shard_path).name, "err": "few frames"}
    runs, n = _clean_mask(frames)
    feats, labels, idxs = _features_and_labels(frames, runs)
    if not feats:
        return {"ok": False, "shard": Path(shard_path).name, "err": "no clean frames"}
    X = np.asarray(feats, dtype=np.float32)
    Y = np.asarray(labels, dtype=np.int8)
    demo_id = np.full(len(feats), demo_idx, dtype=np.int32)
    tier_id = np.full(len(feats), {"A": 0, "B": 1, "C": 2}[tier], dtype=np.int8)
    return {"ok": True, "shard": Path(shard_path).name, "X": X, "Y": Y,
            "demo_id": demo_id, "tier_id": tier_id, "n_clean": len(feats),
            "n_frames": n, "n_runs": len(runs)}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard-dir", default=os.path.expanduser("~/move_bc_shards"))
    ap.add_argument("--clean-index", type=Path,
                    default=REPO_ROOT / "experiments/stage2/move-bc-dataset/clean-segment-index.json")
    ap.add_argument("--demo-list", type=Path,
                    default=REPO_ROOT / "experiments/stage2/move-bc-dataset/selfpov_4on4_demolist.tsv")
    ap.add_argument("--bsp", default="/mnt/c/nQuake/qw/maps/dm3.bsp")
    ap.add_argument("--out", default=os.path.expanduser("~/move_bc_dataset.npz"))
    ap.add_argument("--workers", type=int, default=os.cpu_count())
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args(argv)

    idx = json.loads(args.clean_index.read_text())
    tier_by_demo = {d["demo"]: d["tier"] for d in idx["demos"]}
    player_by_demo = {}
    for ln in args.demo_list.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        p = ln.split("\t")
        player_by_demo[Path(p[-1]).name] = p[0]

    # build job list: only demos that are in the clean index AND have a shard
    shard_dir = Path(args.shard_dir)
    jobs = []
    demos_meta = []
    for di, d in enumerate(sorted(idx["demos"], key=lambda x: x["demo"])):
        name = d["demo"]
        stem = name[:-4] if name.endswith(".qwd") else name
        shard = shard_dir / (stem + ".ndjson")
        if not shard.exists():
            continue
        jobs.append((str(shard), len(demos_meta), d["tier"]))
        demos_meta.append({"demo": name, "tier": d["tier"],
                           "player": player_by_demo.get(name, "")})
    if args.limit:
        jobs = jobs[: args.limit]
        demos_meta = demos_meta[: args.limit]
    print(f"dataset build: {len(jobs)} shards, {args.workers} workers", flush=True)

    Xs, Ys, Ds, Ts = [], [], [], []
    t0 = time.time()
    done = fail = 0
    with ProcessPoolExecutor(max_workers=args.workers,
                             initializer=_init_worker,
                             initargs=(args.bsp,)) as ex:
        futs = {ex.submit(process_one, j): j for j in jobs}
        for fut in as_completed(futs):
            r = fut.result()
            done += 1
            job_idx = futs[fut][1]
            if not r["ok"]:
                fail += 1
                demos_meta[job_idx]["error"] = r["err"]
            else:
                Xs.append(r["X"]); Ys.append(r["Y"])
                Ds.append(r["demo_id"]); Ts.append(r["tier_id"])
                demos_meta[job_idx]["n_clean"] = r["n_clean"]
            if done % 25 == 0 or done == len(jobs):
                el = time.time() - t0
                print(f"  {done}/{len(jobs)} fail={fail} "
                      f"({el:.0f}s, {el/max(done,1):.2f}s/shard)", flush=True)

    X = np.concatenate(Xs); Y = np.concatenate(Ys)
    D = np.concatenate(Ds); T = np.concatenate(Ts)
    np.savez_compressed(args.out, X=X, Y=Y, demo_id=D, tier_id=T,
                        demos=np.array(json.dumps(demos_meta)))
    print(f"\nwrote {args.out}: X={X.shape} Y={Y.shape} "
          f"demos={len(demos_meta)} clean_frames={len(X)}", flush=True)
    # quick label balance
    for k, nm in enumerate(["fwd", "side", "jump"]):
        vals, cnts = np.unique(Y[:, k], return_counts=True)
        print(f"  {nm}: " + " ".join(f"{int(v)}:{int(c)}" for v, c in zip(vals, cnts)))


if __name__ == "__main__":
    sys.setrecursionlimit(20000)
    main()
