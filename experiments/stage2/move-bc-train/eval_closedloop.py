#!/usr/bin/env python3
"""Stage-2 MOVE-BC CLOSED-LOOP gate (references/12 §6 'Closed-loop MOVE gate' + §7
Stage-2 acceptance).

THE REAL STAGE-2 ACCEPTANCE. The trained policy drives pmove_sim with the
sim's OWN evolving state fed back each tick (NOT human state): we seed from a
recorded clean-segment start state, then for a budgeted horizon we

  1. read the sim's current velocity (vx,vy,vz) + the recorded view-yaw/pitch
     for that tick (view = AIM, deferred to Stage 3 -> replay human view),
  2. build the SAME 6-dim state feature vector,
  3. argmax the policy -> (fwd,side,jump) at +-320 / BUTTON_JUMP,
  4. step pmove_sim one frame; the new sim velocity feeds step 1 next tick.

No re-anchoring to human state -- this is the closed-loop drift test the open-
loop replay cannot see. We measure, over the horizon, the bot's sustained
horizontal speed (avg + p95) and compare to the promoted dm3 4on4 anchor bands
(references/dm3_4on4_anchors.json movement family). We run the AIR-LAW prior and
the RECORDED-human usercmd through the same closed-loop harness for reference.

PLANE HONESTY: the anchor movement bands are on the MVD event-rate finite-
difference plane (~13 ms sampling). These demos' usercmds tick at ~13 ms (msec
in the shard), so the closed-loop sim speed is sampled at the same ~13 ms cadence
-- reasonably comparable, but NOT identical to the MVD central-difference
estimator; reported as in-band / out-of-band with that caveat stated.

Pure numpy + torch. WSL2.
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
sys.path.insert(0, str(Path(__file__).resolve().parent))
from train import MoveMLP  # noqa: E402
from eval_openloop import (wrap180, state_features, airlaw_action,  # noqa: E402
                           load_shard)

MOVE_MAG = 320.0


def policy_step_action(model, st, yaw, pitch, device):
    f = state_features(st.velocity[0], st.velocity[1], st.velocity[2], yaw, pitch)
    x = torch.from_numpy(np.asarray([f], dtype=np.float32)).to(device)
    with torch.no_grad():
        lf, ls, lj = model(x)
        fwd = int(lf.argmax(1).item()) - 1
        side = int(ls.argmax(1).item()) - 1
        jump = int(lj.argmax(1).item())
    return fwd, side, jump


def closed_loop_run(world, frames, controller, model=None, device="cpu",
                    horizon=385, start=0):
    """Drive the sim closed-loop for `horizon` ticks from frames[start].

    controller in {"bc","airlaw","recorded"}. Returns per-tick horizontal speed
    list + the route end-displacement vs the recorded human end position over the
    same window (route retention proxy)."""
    pm = pmove_sim.Pmove(world)
    f0 = frames[start]
    st = pmove_sim.PlayerState(list(f0["origin"]), list(f0["velocity"]))
    speeds = []
    n = min(horizon, len(frames) - 1 - start)
    for k in range(n):
        f = frames[start + k]
        yaw, pitch = f["angles"][1], f["angles"][0]
        msec = f["msec"] if f["msec"] else 13
        if controller == "recorded":
            mv = f["move"]; buttons = f["buttons"]
        else:
            if controller == "bc":
                fwd, side, jump = policy_step_action(model, st, yaw, pitch, device)
            else:  # airlaw -- needs onground; categorize first
                pm._fwd, pm._right = pmove_sim.angle_vectors(f["angles"])
                pm._categorize(st)
                fwd, side, jump = airlaw_action(st.velocity[0], st.velocity[1],
                                                st.velocity[2], yaw, st.onground)
            mv = [int(fwd * MOVE_MAG), int(side * MOVE_MAG), 0]
            buttons = pmove_sim.BUTTON_JUMP if jump else 0
        cmd = pmove_sim.Cmd(msec, f["angles"], mv, buttons)
        pm.run_frame(st, cmd)
        speeds.append(math.hypot(st.velocity[0], st.velocity[1]))
    # route retention: distance from sim end-origin to recorded human end-origin
    rec_end = frames[start + n]["origin"]
    sim_end = st.origin
    route_err = math.dist(sim_end[:2], rec_end[:2])
    return speeds, route_err


def stats(speeds):
    if not speeds:
        return None
    a = np.asarray(speeds)
    return {
        "avg": round(float(a.mean()), 2),
        "p95": round(float(np.percentile(a, 95)), 2),
        "max": round(float(a.max()), 2),
        "frac_moving": round(float((a >= 50).mean()), 3),
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="~/move_bc_dataset.npz")
    ap.add_argument("--ckpt", default="~/move_bc_policy.pt")
    ap.add_argument("--shard-dir", default="~/move_bc_shards")
    ap.add_argument("--bsp", default="/mnt/c/nQuake/qw/maps/dm3.bsp")
    ap.add_argument("--anchors", type=Path,
                    default=REPO_ROOT / "references/dm3_4on4_anchors.json")
    ap.add_argument("--val-frac", type=float, default=0.15)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--n-demos", type=int, default=20)
    ap.add_argument("--horizon", type=int, default=385, help="~5s at 13ms ticks")
    ap.add_argument("--starts-per-demo", type=int, default=8)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    d = np.load(Path(args.data).expanduser(), allow_pickle=True)
    demos_meta = json.loads(str(d["demos"]))
    demo_id = d["demo_id"]
    uniq = np.unique(demo_id)
    rng = np.random.default_rng(args.seed)
    rng.shuffle(uniq)
    n_val = max(1, int(round(args.val_frac * len(uniq))))
    val_ids = uniq[:n_val].tolist()

    ck = torch.load(Path(args.ckpt).expanduser(), map_location=device, weights_only=False)
    model = MoveMLP(hidden=ck["hidden"]).to(device); model.load_state_dict(ck["state_dict"]); model.eval()
    world = pmove_sim.WorldModel.load(args.bsp)
    shard_dir = Path(args.shard_dir).expanduser()

    anchors = json.loads(args.anchors.read_text())
    mv = anchors["metrics"]["movement"]["fields"]
    avg_band = (mv["avg_horizontal_speed_qu_per_s"]["pool"]["min"],
                mv["avg_horizontal_speed_qu_per_s"]["pool"]["max"])
    p95_band = (mv["p95_horizontal_speed_qu_per_s"]["pool"]["min"],
                mv["p95_horizontal_speed_qu_per_s"]["pool"]["max"])

    cand = [(i, demos_meta[i]) for i in val_ids if i < len(demos_meta)]
    cand = [(i, m) for (i, m) in cand
            if (shard_dir / (m["demo"][:-4] + ".ndjson")).exists()][: args.n_demos]

    bc_avgs, bc_p95s, bc_routes = [], [], []
    al_avgs, al_p95s, al_routes = [], [], []
    rec_avgs, rec_p95s, rec_routes = [], [], []
    rng2 = np.random.default_rng(args.seed + 1)
    t0 = time.time()
    n_runs = 0
    for di, m in cand:
        frames = load_shard(shard_dir / (m["demo"][:-4] + ".ndjson"))
        if len(frames) < args.horizon + 10:
            continue
        max_start = len(frames) - args.horizon - 2
        starts = rng2.integers(0, max_start, size=args.starts_per_demo)
        for s in starts:
            s = int(s)
            bc_sp, bc_re = closed_loop_run(world, frames, "bc", model, device, args.horizon, s)
            al_sp, al_re = closed_loop_run(world, frames, "airlaw", None, device, args.horizon, s)
            rec_sp, rec_re = closed_loop_run(world, frames, "recorded", None, device, args.horizon, s)
            for sp, av, pv, ro, re in [
                (bc_sp, bc_avgs, bc_p95s, bc_routes, bc_re),
                (al_sp, al_avgs, al_p95s, al_routes, al_re),
                (rec_sp, rec_avgs, rec_p95s, rec_routes, rec_re)]:
                st = stats(sp)
                av.append(st["avg"]); pv.append(st["p95"]); ro.append(re)
            n_runs += 1
        print(f"  {m['demo'][:46]:46s} runs+={args.starts_per_demo}", flush=True)

    def band_report(avgs, p95s, routes, label):
        avg_m = float(np.mean(avgs)); p95_m = float(np.mean(p95s))
        return {
            "controller": label,
            "sustained_avg_speed_mean": round(avg_m, 2),
            "sustained_avg_speed_median": round(float(np.median(avgs)), 2),
            "sustained_p95_speed_mean": round(p95_m, 2),
            "route_err_qu_median": round(float(np.median(routes)), 1),
            "route_err_qu_mean": round(float(np.mean(routes)), 1),
            "in_avg_band": bool(avg_band[0] <= avg_m <= avg_band[1]),
            "in_p95_band": bool(p95_band[0] <= p95_m <= p95_band[1]),
        }

    bc_rep = band_report(bc_avgs, bc_p95s, bc_routes, "bc")
    al_rep = band_report(al_avgs, al_p95s, al_routes, "airlaw")
    rec_rep = band_report(rec_avgs, rec_p95s, rec_routes, "recorded")

    # acceptance: BC sustained speed in/above hand-mover (airlaw) AND route err
    # <= airlaw; in-band is the stretch goal.
    bc_ge_airlaw_speed = bc_rep["sustained_avg_speed_mean"] >= al_rep["sustained_avg_speed_mean"]
    bc_ge_airlaw_route = bc_rep["route_err_qu_median"] <= al_rep["route_err_qu_median"]

    out = {
        "harness": "closed-loop, simulated-state feedback, human view-yaw replayed (AIM deferred)",
        "horizon_ticks": args.horizon,
        "approx_horizon_secs": round(args.horizon * 0.013, 1),
        "runs": n_runs, "demos": len(cand),
        "anchor_bands": {
            "avg_horizontal_speed_qu_per_s_pool": {"min": avg_band[0], "max": avg_band[1]},
            "p95_horizontal_speed_qu_per_s_pool": {"min": p95_band[0], "max": p95_band[1]},
            "plane": "MVD event-rate finite-difference (~13ms); sim sampled at recorded ~13ms tick (caveat: not identical estimator)",
        },
        "recorded_human_closed_loop": rec_rep,
        "airlaw_prior_closed_loop": al_rep,
        "bc_policy_closed_loop": bc_rep,
        "bc_ge_airlaw_sustained_speed": bool(bc_ge_airlaw_speed),
        "bc_ge_airlaw_route_retention": bool(bc_ge_airlaw_route),
        "wall_clock_secs": round(time.time() - t0, 1),
    }
    print("\n" + json.dumps({k: out[k] for k in [
        "anchor_bands", "recorded_human_closed_loop", "airlaw_prior_closed_loop",
        "bc_policy_closed_loop", "bc_ge_airlaw_sustained_speed",
        "bc_ge_airlaw_route_retention"]}, indent=1))
    if args.out:
        Path(args.out).expanduser().write_text(json.dumps(out, indent=1))
        print(f"wrote {args.out}")


if __name__ == "__main__":
    sys.setrecursionlimit(20000)
    main()
