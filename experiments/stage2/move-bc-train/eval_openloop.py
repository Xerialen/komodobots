#!/usr/bin/env python3
"""Stage-2 MOVE-BC OPEN-LOOP evaluation (references/12 Stage 2 / §6 gate (a)).

For each held-out demo we take the recorded per-frame state stream and the
recorded view-yaw + msec, then REPLACE the recorded (fwd,side,jump) usercmd with
each of three controllers and replay through the validated pmove_sim, measuring
how well the resulting trajectory retains the recorded human route (1s-segmented
free-run, teleport + every-77 reanchor -- the same divergence instrument the
dataset clean-mask uses):

  RECORDED  (mode-10 baseline) -- replay the recorded usercmd. This reproduces
            the human trajectory (the clean-segment definition), so it is the
            retention CEILING, not a competitor.
  AIR-LAW   (analytic prior)   -- the velocity-relative strafe-jump rule from
            scripts/fit_air_law.py: forward held, strafe toward the view-yaw
            (the side that rotates velocity toward look, maximising the
            900 - cs^2 air-accel gain), jump whenever grounded. This is the
            PRIOR the BC policy must beat or match on retention (references/12 KILL
            criterion: if BC < air-law prior -> keep hand-mover).
  BC        (learned policy)   -- argmax of the MoveMLP heads on the state
            feature vector.

The view-yaw and msec are taken from the recording in ALL THREE (open-loop:
view = AIM, deferred to Stage 3; here we replay the human view so MOVE is
isolated). Acceptance: BC mean/p95 segment retention >= AIR-LAW prior.

Also reports raw action-reproduction accuracy of BC vs recorded usercmd on the
held-out frames (the "did it pick the human's button" number).

Pure numpy + torch (load checkpoint). Runs in WSL2.
"""
from __future__ import annotations

import logging
import argparse
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import torch


LOGGER = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parents[3]
for _p in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pmove_sim  # noqa: E402
# World-view features come from the shared single-source-of-truth module (T0.4),
# so the open/closed-loop evaluators score MoveMLP on exactly the same feature
# vector the dataset was built with and the live sidecar will serve.
import move_world_view  # noqa: E402

SEGMENT = 77
DIVERGE_THRESH = 4.0
MOVE_MAG = 320.0
sys.path.insert(0, str(Path(__file__).resolve().parent))
from train import MoveMLP, FEATURE_DIM  # noqa: E402


# Re-exported from the shared world-view module so this evaluator and the
# offline dataset builder compute the feature vector from one canonical place
# (T0.4). eval_closedloop imports state_features/wrap180 from here, so the names
# stay stable.
wrap180 = move_world_view.wrap180
state_features = move_world_view.state_features


def airlaw_action(vx, vy, vz, yaw, onground):
    """Analytic strafe-jump prior (fit_air_law velocity-relative rule).

    Strafe toward the view: choose the side whose wishdir rotates velocity
    toward the look direction, i.e. sign of the signed angle (view - velocity).
    Forward is held. Jump whenever grounded (bhop), else hold air strafe.
    """
    hsp = math.hypot(vx, vy)
    if hsp < 1.0:
        # no heading: just run forward, jump if grounded
        return (1, 0, 1 if onground else 0)
    vhead = math.degrees(math.atan2(vy, vx))
    dlook = wrap180(yaw - vhead)        # +: view is left of velocity
    side_cls = 1 if dlook > 0 else (-1 if dlook < 0 else 0)
    # classic air-strafe: forward + strafe toward look. On the ground the engine
    # accelerates straight, so forward-only is fine; in air the side term carries
    # the 900-cs^2 gain.
    fwd_cls = 1
    jump = 1 if onground else 0
    return (fwd_cls, side_cls, jump)


def bc_action_batch(model, feats, device):
    x = torch.from_numpy(np.asarray(feats, dtype=np.float32)).to(device)
    with torch.no_grad():
        lf, ls, lj = model(x)
        f = lf.argmax(1).cpu().numpy() - 1
        s = ls.argmax(1).cpu().numpy() - 1
        j = lj.argmax(1).cpu().numpy()
    return f, s, j


def build_cmds(frames, fwd_arr, side_arr, jump_arr):
    """Construct replay frames: recorded state+view+msec, substituted move
    (sign quantised to +-MOVE_MAG, the discrete action vocabulary)."""
    out = []
    for i, f in enumerate(frames):
        buttons = pmove_sim.BUTTON_JUMP if jump_arr[i] else 0
        out.append({
            "msec": f["msec"], "origin": f["origin"], "velocity": f["velocity"],
            "angles": f["angles"],
            "move": [int(fwd_arr[i] * MOVE_MAG), int(side_arr[i] * MOVE_MAG), 0],
            "buttons": buttons,
        })
    return out


def build_recorded_cmds(frames):
    """Exact recorded usercmd replay (mode-10 baseline) -- TRUE human ceiling,
    using the recorded move MAGNITUDES and recorded buttons verbatim."""
    return [{
        "msec": f["msec"], "origin": f["origin"], "velocity": f["velocity"],
        "angles": f["angles"], "move": f["move"], "buttons": f["buttons"],
    } for f in frames]


def seg_retention(world, sim_frames):
    """1s-segmented free-run retention. Returns (clean_seg_frac, p50, p95, mean_err)."""
    tele = pmove_sim.detect_teleports(sim_frames)
    summary, rows = pmove_sim.replay(
        world, sim_frames, reanchor_at=tele, reanchor_every=SEGMENT,
        diverge_thresh=DIVERGE_THRESH,
    )
    # PER-FRAME clean fraction (the canonical analyze_clean_yield metric):
    # frame err <= 4qu, excluding teleport-reanchor rows. This is directly
    # comparable to the dataset's ~90% improved_clean_frac.
    errs = [r["err"] for r in rows if not r["teleport_reanchor"]]
    n_f = len(errs)
    clean_f = sum(1 for e in errs if e <= DIVERGE_THRESH)
    # coarse whole-segment metric kept for reference
    seg_max = []
    cur = 0.0
    for i, r in enumerate(rows):
        if i > 0 and (i % SEGMENT == 0):
            seg_max.append(cur); cur = 0.0
        if not r["teleport_reanchor"]:
            cur = max(cur, r["err"])
    seg_max.append(cur)
    n_seg = len(seg_max)
    clean = sum(1 for m in seg_max if m <= DIVERGE_THRESH)
    s = sorted(errs)
    p50 = s[len(s)//2] if s else None
    p95 = s[min(len(s)-1, int(0.95*(len(s)-1)))] if s else None
    return {
        "clean_frame_frac": round(clean_f / n_f, 4) if n_f else None,
        "frame_err_p50": round(p50, 3) if p50 is not None else None,
        "frame_err_p95": round(p95, 3) if p95 is not None else None,
        "clean_seg_frac": round(clean / n_seg, 4) if n_seg else None,
        "mean_err": summary["mean_err"], "p95_err": summary["p95_err"],
    }


def load_shard(path):
    frames = []
    with open(path) as fh:
        for ln in fh:
            ln = ln.strip()
            if not ln:
                continue
            r = json.loads(ln)
            frames.append({
                "msec": r["msec"], "origin": r["o"], "velocity": r["v"],
                "angles": r["a"], "move": r["m"], "buttons": r["buttons"],
                "onground": r.get("onground"),
            })
    return frames


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="~/move_bc_dataset.npz")
    ap.add_argument("--ckpt", default="~/move_bc_policy.pt")
    ap.add_argument("--shard-dir", default="~/move_bc_shards")
    ap.add_argument("--bsp", default="/mnt/c/nQuake/qw/maps/dm3.bsp")
    ap.add_argument("--val-frac", type=float, default=0.15)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--n-demos", type=int, default=12, help="held-out demos to replay")
    ap.add_argument("--max-frames", type=int, default=20000)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    d = np.load(Path(args.data).expanduser(), allow_pickle=True)
    demos_meta = json.loads(str(d["demos"]))
    demo_id = d["demo_id"]
    # reproduce the by-demo split to recover the held-out demo names
    uniq = np.unique(demo_id)
    rng = np.random.default_rng(args.seed)
    rng.shuffle(uniq)
    n_val = max(1, int(round(args.val_frac * len(uniq))))
    val_ids = uniq[:n_val].tolist()

    ck = torch.load(Path(args.ckpt).expanduser(), map_location=device, weights_only=False)
    model = MoveMLP(hidden=ck["hidden"]).to(device)
    model.load_state_dict(ck["state_dict"]); model.eval()

    world = pmove_sim.WorldModel.load(args.bsp)
    shard_dir = Path(args.shard_dir).expanduser()

    # pick held-out demos that have shards, prefer larger ones
    cand = [(i, demos_meta[i]) for i in val_ids if i < len(demos_meta)]
    cand = [(i, m) for (i, m) in cand
            if (shard_dir / (m["demo"][:-4] + ".ndjson")).exists()]
    cand = cand[: args.n_demos]

    per_demo = []
    acc_f = acc_s = acc_j = acc_n = 0
    t0 = time.time()
    for di, m in cand:
        shard = shard_dir / (m["demo"][:-4] + ".ndjson")
        frames = load_shard(shard)
        if args.max_frames:
            frames = frames[: args.max_frames]
        # features + recorded labels
        feats = []
        rec_f = []; rec_s = []; rec_j = []
        for f in frames:
            vx, vy, vz = f["velocity"]
            feats.append(state_features(vx, vy, vz, f["angles"][1], f["angles"][0]))
            fm, sm, _ = f["move"]
            rec_f.append(1 if fm > 0 else (-1 if fm < 0 else 0))
            rec_s.append(1 if sm > 0 else (-1 if sm < 0 else 0))
            rec_j.append(1 if int(f["buttons"]) & pmove_sim.BUTTON_JUMP else 0)
        bf, bs, bj = bc_action_batch(model, feats, device)
        rec_f = np.array(rec_f); rec_s = np.array(rec_s); rec_j = np.array(rec_j)
        acc_f += int((bf == rec_f).sum()); acc_s += int((bs == rec_s).sum())
        acc_j += int((bj == rec_j).sum()); acc_n += len(frames)

        # air-law prior actions: need onground -> derive from a forward pass of
        # the sim on the recorded actions is circular; instead approximate
        # onground from the recorded vz sign + a sim categorize. Simpler &
        # honest: run the prior closed-form using a per-frame onground estimate
        # from the recorded state by a single pmove categorize.
        pm = pmove_sim.Pmove(world)
        al_f = np.empty(len(frames), np.int64)
        al_s = np.empty(len(frames), np.int64)
        al_j = np.empty(len(frames), np.int64)
        for i, f in enumerate(frames):
            st = pmove_sim.PlayerState(f["origin"], f["velocity"])
            pm._fwd, pm._right = pmove_sim.angle_vectors(f["angles"])
            pm._categorize(st)
            vx, vy, vz = f["velocity"]
            a = airlaw_action(vx, vy, vz, f["angles"][1], st.onground)
            al_f[i], al_s[i], al_j[i] = a

        rec_cmds = build_recorded_cmds(frames)
        rec_q_cmds = build_cmds(frames, rec_f, rec_s, rec_j)  # sign-quantised recorded
        bc_cmds = build_cmds(frames, bf, bs, bj)
        al_cmds = build_cmds(frames, al_f, al_s, al_j)
        r_rec = seg_retention(world, rec_cmds)
        r_recq = seg_retention(world, rec_q_cmds)
        r_bc = seg_retention(world, bc_cmds)
        r_al = seg_retention(world, al_cmds)
        per_demo.append({
            "demo": m["demo"], "tier": m["tier"], "player": m.get("player", ""),
            "frames": len(frames),
            "recorded": r_rec, "recorded_quantised": r_recq,
            "airlaw": r_al, "bc": r_bc,
        })
        print(f"  {m['demo'][:42]:42s} rec={r_rec['clean_frame_frac']} "
              f"recQ={r_recq['clean_frame_frac']} "
              f"airlaw={r_al['clean_frame_frac']} bc={r_bc['clean_frame_frac']}", flush=True)

    def agg(key):
        vals = [pd[key]["clean_frame_frac"] for pd in per_demo if pd[key]["clean_frame_frac"] is not None]
        p50 = [pd[key]["frame_err_p50"] for pd in per_demo]
        p95 = [pd[key]["frame_err_p95"] for pd in per_demo]
        return {
            "mean_clean_frame_frac": round(float(np.mean(vals)), 4),
            "median_clean_frame_frac": round(float(np.median(vals)), 4),
            "mean_frame_err_p50": round(float(np.mean(p50)), 3),
            "mean_frame_err_p95": round(float(np.mean(p95)), 3),
        }

    out = {
        "n_held_out_demos_replayed": len(per_demo),
        "max_frames_per_demo": args.max_frames,
        "action_reproduction_acc": {
            "fwd": round(acc_f / acc_n, 4),
            "side": round(acc_s / acc_n, 4),
            "jump": round(acc_j / acc_n, 4),
            "frames": acc_n,
        },
        "retention": {
            "metric": "clean_frame_frac = fraction of replay frames with origin err <= 4qu (teleport+77 reanchor), the canonical analyze_clean_yield per-frame retention",
            "recorded_mode10_baseline_exact": agg("recorded"),
            "recorded_sign_quantised": agg("recorded_quantised"),
            "airlaw_prior": agg("airlaw"),
            "bc_policy": agg("bc"),
        },
        "per_demo": per_demo,
        "wall_clock_secs": round(time.time() - t0, 1),
    }
    bc = out["retention"]["bc_policy"]["mean_clean_frame_frac"]
    al = out["retention"]["airlaw_prior"]["mean_clean_frame_frac"]
    out["bc_beats_airlaw_prior"] = bool(bc >= al)
    out["verdict_openloop"] = ("BC >= air-law prior (PASS open-loop retention)"
                               if bc >= al else
                               "BC < air-law prior (KILL per references/12)")
    print("\n" + json.dumps({k: out[k] for k in
          ["action_reproduction_acc", "retention",
           "bc_beats_airlaw_prior", "verdict_openloop"]}, indent=1))
    if args.out:
        Path(args.out).expanduser().write_text(json.dumps(out, indent=1))
        print(f"wrote {args.out}")


if __name__ == "__main__":
    sys.setrecursionlimit(20000)
    main()
